"""
Flask Web Server — Dashboard, SSE stream, report generation, psychology gate.

Routes:
  GET  /              — Dashboard UI
  GET  /api/stream    — SSE event stream
  GET  /api/status    — Current system status JSON
  POST /api/psychology — Submit psychology check
  POST /api/report    — Generate .md report
  GET  /api/report/download/<filename> — Download generated report
"""

import json
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from flask import Flask, Response, render_template, request, jsonify, send_file
from flask_cors import CORS

from pipeline.event_bus import EventBus
from server.sse_manager import SSEManager
from psychology.pre_trade_check import evaluate_psychology, Q5_OPTIONS, Q5_LABELS
from core.session import get_session_info, should_block_trading
from core.macro import fetch_macro_data
from core.calendar import get_todays_events, is_nfp_day
from core.cooldown import CooldownEngine
from core.report import generate_report
from journal import journal
from backtest import walk_forward_engine, results_analyzer
import config

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

import pandas as pd

# Shared state (within server process)
_cooldown = CooldownEngine()
_last_psych_result = None
_active_backtest = None

def _get_current_account_state():
    """Sync account state from journal."""
    return journal.get_account_state()


def create_app(event_bus: EventBus) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder=str(config.BASE_DIR / "templates"),
        static_folder=str(config.BASE_DIR / "static"),
    )
    app.secret_key = config.FLASK_SECRET_KEY
    CORS(app)

    sse_manager = SSEManager(event_bus)

    # ─── Routes ─────────────────────────────────────────────

    @app.route("/")
    def dashboard():
        """Serve the main dashboard."""
        return render_template("index.html")

    @app.route("/api/stream")
    def sse_stream():
        """SSE event stream for live dashboard updates."""
        def generate():
            client_queue = sse_manager.subscribe()
            try:
                while True:
                    try:
                        message = client_queue.get(timeout=30)
                        event_type = message.get("event", "update")
                        data = json.dumps(message.get("data", {}))
                        yield f"event: {event_type}\ndata: {data}\n\n"
                    except Exception:
                        # Send keepalive
                        yield f"event: ping\ndata: {{}}\n\n"
            except GeneratorExit:
                sse_manager.unsubscribe(client_queue)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.route("/api/status")
    def get_status():
        """Get current system status."""
        session = get_session_info(get_todays_events())
        cooldown = _cooldown.check_cooldown()
        macro = fetch_macro_data()

        # Get latest data from SSE manager cache
        latest = sse_manager._latest_state
        tick = latest.get("tick", {})
        health = latest.get("health", {})

        # Get current account state
        account = _get_current_account_state()

        block = should_block_trading(
            session,
            daily_pnl=account["daily_pnl"],
            daily_loss=abs(min(0, account["daily_pnl"])),
            confluence_score=latest.get("confluence_update", {}).get("total", 0),
            psych_score=_last_psych_result.feeling if _last_psych_result else 10,
            cooldown_active=cooldown.active,
            is_nfp_day=is_nfp_day(),
        )

        return jsonify({
            "price": tick.get("price", 0),
            "session": session.to_dict(),
            "cooldown": cooldown.to_dict(),
            "macro_bias": macro.get("macro_bias", ""),
            "feed_health": health,
            "account": account,
            "trading_blocked": block,
            "psychology_done": _last_psych_result is not None,
            "news_events": get_todays_events(),
            "timestamp": time.time(),
        })

    @app.route("/api/candles/<tf>")
    def get_candles(tf):
        """Get historical candles and overlays for the chart."""
        latest = sse_manager._latest_state
        candle_data = latest.get("candle_data", {}).get(tf.upper(), [])
        
        # In a real scenario, this would also include computed overlays for that TF
        # For now, we return candles and mock overlays based on current indicator state
        indicator_state = latest.get("indicator_update", {})
        dr_state = latest.get("dealing_range_update", {})

        # Filter indicators by timeframe if applicable
        # (This is a simplification; ideally indicators are stored per timeframe in the event bus)
        
        return jsonify({
            "candles": candle_data,
            "overlays": {
                "fvgs": [vars(f) for f in indicator_state.get("fvgs_h1", [])] if tf == "H1" else [],
                "obs": [vars(o) for o in indicator_state.get("obs_m15", [])] if tf == "M15" else [],
                "swings": [vars(s) for s in (indicator_state.get("swing_highs_h1", []) + indicator_state.get("swing_lows_h1", []))] if tf == "H1" else [],
                "ote": {
                    "high": dr_state.get("ote_high", 0),
                    "low": dr_state.get("ote_low", 0),
                    "eq": dr_state.get("equilibrium", 0)
                } if tf == "H4" and dr_state.get("is_valid") else None,
                "dealing_range": {
                    "high": dr_state.get("range_high", 0),
                    "low": dr_state.get("range_low", 0)
                } if tf == "H4" else None
            }
        })

    @app.route("/api/psychology", methods=["POST"])
    def submit_psychology():
        """Submit the 5-question psychology pre-trade check."""
        global _last_psych_result
        data = request.get_json()

        result = evaluate_psychology(
            feeling=int(data.get("feeling", 5)),
            slept_well=bool(data.get("slept_well", True)),
            financial_stress=bool(data.get("financial_stress", False)),
            last_trade=data.get("last_trade", "none"),
            reason=data.get("reason", "routine_check"),
        )

        _last_psych_result = result
        return jsonify(result.to_dict())

    @app.route("/api/report", methods=["POST"])
    def generate_report_endpoint():
        """Generate the .md trade report."""
        session = get_session_info(get_todays_events())
        macro = fetch_macro_data()
        latest = sse_manager._latest_state

        report_data = {
            "session": session.to_dict(),
            "psychology": _last_psych_result.to_dict() if _last_psych_result else {},
            "price": latest.get("tick", {}).get("price", 0),
            "feed_source": latest.get("health", {}).get("current_source", "unknown"),
            "macro": macro,
            "news_events": get_todays_events(),
            "ict_result": latest.get("ict_update", {}),
            "dealing_range": latest.get("dealing_range_update", {}),
            "indicators": latest.get("indicator_update", {}),
            "confluence": latest.get("confluence_update", {}),
            "account": _get_current_account_state(),
            "journal": journal.get_journal_context(),
            "candles": latest.get("candle_data", {}),
        }

        report_md = generate_report(report_data)

        # Save report
        now = datetime.now(IST)
        filename = f"GOLD_TRADE_{now.strftime('%Y-%m-%d-%H%M')}.md"
        reports_dir = config.DATA_DIR / "reports"
        reports_dir.mkdir(exist_ok=True)
        filepath = reports_dir / filename
        filepath.write_text(report_md)

        return jsonify({
            "success": True,
            "filename": filename,
            "download_url": f"/api/report/download/{filename}",
            "preview": report_md[:500],
        })

    @app.route("/api/report/download/<filename>")
    def download_report(filename):
        """Download a generated report."""
        filepath = config.DATA_DIR / "reports" / filename
        if filepath.exists():
            return send_file(filepath, as_attachment=True, download_name=filename)
        return jsonify({"error": "Report not found"}), 404

    @app.route("/api/backtest/run", methods=["POST"])
    def run_backtest():
        """Trigger a walk-forward backtest."""
        data = request.get_json()
        tf = data.get("timeframe", "15min")
        
        # 1. Check if data exists
        data_path = config.BASE_DIR / "backtest" / "data" / f"XAUUSD_{tf}.csv"
        if not data_path.exists():
            return jsonify({"error": "Historical data not found. Please fetch data first."}), 404
            
        # 2. Run Engine
        engine = walk_forward_engine.BacktestEngine(str(data_path), tf)
        setups = engine.run()
        
        # 3. Analyze
        # For simplicity, we assume the engine uses a simulator inside.
        # In this POC, we just return the setups count.
        from backtest.trade_simulator import TradeSimulator
        sim = TradeSimulator()
        # ... logic to feed setups to sim ...
        
        return jsonify({
            "success": True,
            "setups_found": len(setups),
            "msg": f"Backtest complete on {tf}. Found {len(setups)} setups."
        })

    @app.route("/api/backtest/manual/start", methods=["POST"])
    def start_manual_backtest():
        """Initialize a manual backtest session."""
        global _active_backtest
        data = request.get_json()
        tf = data.get("timeframe", "15min")
        data_path = config.BASE_DIR / "backtest" / "data" / f"XAUUSD_{tf}.csv"
        
        if not data_path.exists():
            return jsonify({"error": "Historical data not found."}), 404
            
        _active_backtest = walk_forward_engine.BacktestEngine(str(data_path), tf)
        _active_backtest.mode = "manual"
        return jsonify({"success": True})

    @app.route("/api/backtest/step")
    def backtest_step():
        """Get the next candle/state for manual backtest."""
        global _active_backtest
        if not _active_backtest:
            return jsonify({"error": "No active backtest session"}), 400
        
        state = _active_backtest.step()
        return jsonify(state)

    @app.route("/api/backtest/latest")
    def get_latest_backtest():
        """Get results of the latest backtest run."""
        res_path = config.BASE_DIR / "backtest" / "results" / "latest_backtest.csv"
        if res_path.exists():
            df = pd.read_csv(res_path)
            return jsonify(df.to_dict('records'))
        return jsonify([])

    @app.route("/api/cooldown/confirm", methods=["POST"])
    def confirm_cooldown():
        """Confirm continuation after $35 daily loss warning."""
        _cooldown.confirm_continue()
        return jsonify({"confirmed": True})

    return app

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
from datetime import datetime

from flask import Flask, Response, render_template, request, jsonify, send_file
from flask_cors import CORS

from pipeline.event_bus import EventBus
from server.sse_manager import SSEManager
from psychology.pre_trade_check import evaluate_psychology
from core.session import get_session_info, should_block_trading
from core.macro import fetch_macro_data
from core.calendar import get_todays_events, is_nfp_day
from core.cooldown import CooldownEngine
from core.report import generate_report
from journal import journal
from backtest.historical_fetch import fetch_historical_data
import config
from backtest import walk_forward_engine
from alerts.telegram_bot import TelegramBot

_telegram = TelegramBot()

logger = logging.getLogger(__name__)

IST = config.IST

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
        session = get_session_info(news_events=get_todays_events())
        cooldown = _cooldown.check_cooldown()
        macro = fetch_macro_data()

        # Get latest data from SSE manager cache
        latest = sse_manager._latest_state
        tick = latest.get("tick", {})
        health = latest.get("health", {})

        # Get current account state
        account = _get_current_account_state()

        # Compute live indicators from candle_builder history for ATR and score
        live_indicators = latest.get("indicator_update", {})
        live_atr = live_indicators.get("atr_h1", 0) if live_indicators else 0
        live_confluence = latest.get("confluence_update", {})
        live_score = live_confluence.get("total", 0) if live_confluence else 0
        
        # v5.0 Market Regime
        regime = latest.get("market_regime", {})

        block = should_block_trading(
            session,
            daily_pnl=account["daily_pnl"],
            daily_loss=abs(min(0, account["daily_pnl"])),
            confluence_score=live_score,
            psych_score=_last_psych_result.feeling if _last_psych_result else 10,
            cooldown_active=cooldown.active,
            is_nfp_day=is_nfp_day(),
        )

        return jsonify({
            "price": tick.get("price", 0),
            "atr": round(live_atr, 2),
            "score": live_score,
            "session": session.to_dict(),
            "cooldown": cooldown.to_dict(),
            "regime": regime,
            "macro_bias": macro.get("macro_bias", ""),
            "feed_health": health,
            "account": account,
            "trading_blocked": block,
            "psychology_done": _last_psych_result is not None,
            "news_events": get_todays_events(),
            "timestamp": time.time(),
        })

    @app.route("/api/strategy/history")
    def get_strategy_history():
        """Get the latest ICT strategy scan history."""
        try:
            latest = sse_manager._latest_state or {}
            history = latest.get("strategy_history", [])
            return jsonify(history)
        except Exception:
            return jsonify([])

    @app.route("/api/candles/<tf>")
    def get_candles(tf):
        """Serve candles from EventBus cache (populated by OANDA feed)."""
        tf_upper = tf.upper()
        if tf_upper not in ("M5", "M15", "H1", "H4"):
            return jsonify({"candles": [], "overlays": {}})

        latest  = sse_manager._latest_state
        candles = latest.get(f"candles_{tf_upper}", [])

        latest = sse_manager._latest_state
        ind = latest.get("indicators", {})
        dr  = latest.get("dealing_range_update", {})

        def _safe(lst):
            return [x if isinstance(x, dict) else (vars(x) if hasattr(x, '__dict__') else {}) for x in (lst or [])]

        overlays = {
            "fvgs_h1":  _safe(ind.get("fvgs_h1", [])),
            "fvgs_m15": _safe(ind.get("fvgs_m15", [])),
            "obs_h1":   _safe(ind.get("obs_h1", [])),
            "obs_m15":  _safe(ind.get("obs_m15", [])),
            "swing_highs_h1": _safe(ind.get("swing_highs_h1", [])),
            "swing_lows_h1":  _safe(ind.get("swing_lows_h1", [])),
            "liquidity_pools": _safe(ind.get("liquidity_pools", [])),
            "dealing_range": {
                "high":     dr.get("range_high"),
                "low":      dr.get("range_low"),
                "eq":       dr.get("equilibrium"),
                "ote_high": dr.get("ote_high"),
                "ote_low":  dr.get("ote_low"),
            } if dr.get("is_valid") else None,
        }

        return jsonify({"candles": candles, "overlays": overlays})

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
            return send_file(filepath, as_attachment=True, download_name=filename, mimetype='text/markdown')
        return jsonify({"error": "Report not found"}), 404

    @app.route("/api/backtest/run", methods=["POST"])
    def run_backtest():
        """Trigger a backtest using the ICT walk-forward engine."""
        from backtest.walk_forward_engine import BacktestEngine, run_all_timeframes
        from backtest.simulation_core import simulate_setups

        data       = request.get_json()
        tf         = data.get("timeframe", "15min")
        start_date = data.get("start_date")
        end_date   = data.get("end_date")
        data_dir   = str(config.BASE_DIR / "backtest" / "data")

        if tf == "all":
            # ── All-TF combined mode ──────────────────────────────────────
            setups, engines = run_all_timeframes(data_dir, start_date, end_date)
            if not setups:
                return jsonify({"error": "No setups found. Fetch data first."}), 404
            # Use M15 full_df for simulation (has highest bar density for MT entry checks)
            primary_engine = engines.get("15min") or next(iter(engines.values()))
            result = simulate_setups(setups, primary_engine.full_df, tf_label="M15+H1")
        elif data.get("strategy") == "session_expansion":
            data_path = config.BASE_DIR / "backtest" / "data" / f"XAUUSD_{tf}.csv"
            if not data_path.exists():
                return jsonify({"error": "Historical data not found. Fetch data first."}), 404
            full_df = pd.read_csv(str(data_path))
            from backtest.new_simulation import run_session_backtest
            result = run_session_backtest(full_df, start_date, end_date)
        else:
            data_path = config.BASE_DIR / "backtest" / "data" / f"XAUUSD_{tf}.csv"
            if not data_path.exists():
                return jsonify({"error": "Historical data not found. Fetch data first."}), 404
            engine = BacktestEngine(str(data_path), timeframe=tf,
                                    start_date=start_date, end_date=end_date)
            setups = engine.run()
            result = simulate_setups(setups, engine.full_df, tf_label=tf)

        summary = result["summary"]
        save_backtest_results(result["trades"], filename="latest_backtest.csv")

        return jsonify({
            "success":          True,
            "setups_found":     len(result["trades"]),
            "trades_simulated": len(result["trades"]),
            "summary":          summary,
            "weekly_avg":       result["weekly_avg"],
            "msg": (
                f"Backtest complete. {len(result['trades'])} trades simulated: "
                f"{summary['wins']}W / {summary['losses']}L. PnL: {summary['total_pnl']}"
            ),
        })

    @app.route("/api/backtest/manual/start", methods=["POST"])
    def start_manual_backtest():
        """Initialize a manual backtest session."""
        global _active_backtest
        data = request.get_json()
        tf = data.get("timeframe", "15min")
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        
        # Manual mode uses M15 as primary regardless of "all" selection
        primary_tf = "15min" if tf == "all" else tf
        data_path = config.BASE_DIR / "backtest" / "data" / f"XAUUSD_{primary_tf}.csv"

        if not data_path.exists():
            return jsonify({"error": "Historical data not found."}), 404

        _active_backtest = walk_forward_engine.BacktestEngine(
            str(data_path),
            primary_tf,
            start_date=start_date,
            end_date=end_date
        )
        
        if _active_backtest.total_bars == 0:
            _active_backtest = None
            return jsonify({"error": f"No historical data found for the selected range in {tf} data."}), 400
            
        _active_backtest.mode = "manual"
        return jsonify({
            "success": True,
            "total_bars": _active_backtest.total_bars
        })

    @app.route("/api/backtest/step")
    def backtest_step():
        """Get the next candle/state for manual backtest."""
        global _active_backtest
        if not _active_backtest:
            return jsonify({"error": "No active backtest session"}), 400
            
        state = _active_backtest.step()
        if not state:
            return jsonify({"error": "End of data"}), 404
            
        # Include confluence and ict checklist in the state
        state["confluence"] = _active_backtest.get_current_confluence()
        state["ict_checklist"] = _active_backtest.get_current_ict_checklist()
            
        return jsonify(state)

    def save_backtest_results(trades, filename="latest_backtest.csv"):
        """Export trades to CSV for analysis."""
        import csv
        path = config.BASE_DIR / "backtest" / "results" / filename
        with open(path, 'w', newline='') as f:
            writer = csv.writer(f)
            # Column names must match what renderBtTable() in sse.js expects
            writer.writerow(["timestamp", "price", "direction", "session", "score", "grade", "result", "pnl", "exit_price", "exit_time", "setup_reason", "exit_reason", "risk_factors", "timeframe"])
            for t in trades:
                writer.writerow([
                    t.entry_time, t.entry_price, t.direction, t.session, t.score, t.grade, 
                    t.result, t.pnl, t.exit_price, t.exit_time, t.setup_reason, 
                    t.exit_reason, t.risk_factors, t.timeframe
                ])

    @app.route("/api/backtest/latest")
    def get_latest_backtest():
        """Get results of the latest backtest run."""
        res_path = config.BASE_DIR / "backtest" / "results" / "latest_backtest.csv"
        if res_path.exists():
            df = pd.read_csv(res_path)
            # Replace NaNs with empty strings to prevent invalid JSON (NaN) crashing the frontend
            df = df.fillna("")
            return jsonify(df.to_dict('records'))
        return jsonify([])

    @app.route("/api/backtest/data-range")
    def get_backtest_data_range():
        """Return the available date range from the 15min CSV for display in the UI."""
        data_path = config.BASE_DIR / "backtest" / "data" / "XAUUSD_15min.csv"
        if not data_path.exists():
            return jsonify({"min_date": None, "max_date": None})
        try:
            df = pd.read_csv(data_path, usecols=["datetime"])
            df["datetime"] = pd.to_datetime(df["datetime"])
            min_d = df["datetime"].min().strftime("%Y-%m-%d")
            max_d = df["datetime"].max().strftime("%Y-%m-%d")
            return jsonify({"min_date": min_d, "max_date": max_d})
        except Exception as e:
            logger.error(f"Error reading data range: {e}")
            return jsonify({"min_date": None, "max_date": None})

    @app.route("/api/backtest/refresh", methods=["POST"])
    def refresh_backtest_data():
        """Manually trigger historical data fetch for all timeframes."""
        try:
            # Fetch core timeframes required for backtesting
            fetch_historical_data("XAU/USD", "15min", 5000)
            fetch_historical_data("XAU/USD", "1h", 5000)
            fetch_historical_data("XAU/USD", "4h", 2000)
            return jsonify({"success": True, "message": "Historical data refreshed successfully."})
        except Exception as e:
            logger.error(f"Data refresh failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/cooldown/confirm", methods=["POST"])
    def confirm_cooldown():
        """Confirm continuation after $35 daily loss warning."""
        _cooldown.confirm_continue()
        return jsonify({"confirmed": True})

    @app.route("/api/alerts/health")
    def alerts_health():
        """Check if Telegram bot is configured."""
        return jsonify({"telegram": _telegram.enabled})

    @app.route("/api/alerts/test", methods=["POST"])
    def test_alert():
        """Send a test Telegram alert of the specified type."""
        data = request.get_json() or {}
        alert_type = data.get("type", "setup")

        if not _telegram.enabled:
            return jsonify({"success": False, "error": "Telegram not configured. Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env"}), 400

        try:
            if alert_type == "setup":
                _telegram.alert_setup(score=9.0, grade="A+", price=3320.50, killzone="NY Open")
            elif alert_type == "failover":
                _telegram.alert_failover("failover", "finnhub-fallback")
            elif alert_type == "edge_decay":
                _telegram.alert_edge_decay(win_rate=35.0)
            elif alert_type == "handoff":
                _telegram.alert_handoff(
                    "📋 <b>AURUM — London→NY Handoff Report</b>\n\n"
                    "Session: <b>London Close / NY Open</b>\n"
                    "Bias: <b>Bullish (ICT OTE + FVG aligned)</b>\n"
                    "Key Levels: BSL at $3340 | OTE Zone $3305–$3315\n\n"
                    "Manual test alert from Aurum Pro."
                )
            else:
                return jsonify({"success": False, "error": f"Unknown alert type: {alert_type}"}), 400

            return jsonify({"success": True})
        except Exception as e:
            logger.error(f"Alert test failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    return app

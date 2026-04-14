"""
Feed Manager — Orchestrates OANDA feed with indicator computation.

Runs as the main async pipeline:
1. OandaFeed seeds candle history from OANDA REST on startup
2. Streams live ticks via OANDA streaming API
3. Polls candles every 5s — detects closes, triggers indicators
4. Publishes all events to EventBus for server consumption

No local CSV storage. No candle self-building. No gap-fill logic.
All candle OHLC comes directly from OANDA broker — always accurate.
"""

import asyncio
import time
import logging
from datetime import datetime

import config
from pipeline.event_bus import EventBus
from pipeline.oanda_feed import OandaFeed
from pipeline.health_monitor import HealthMonitor
from alerts.telegram_bot import TelegramBot
from pipeline.alerts_manager import AlertsManager
from core.session_handoff import generate_handoff
from core.indicators import compute_indicators
from core.confluence import compute_confluence
from core.session import get_session_info
from core.macro import fetch_macro_data
from core.calendar import get_todays_events
from core.dealing_range import compute_dealing_range
from core.ict_sequence import check_ict_sequence
from core import market_classifier
from pipeline.live_strategy import LiveStrategyRunner

logger = logging.getLogger(__name__)


class FeedManager:
    """Orchestrates OANDA feed and event publishing."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.health    = HealthMonitor()
        self.bot       = TelegramBot()
        self.alerts    = AlertsManager(event_bus)

        self._handoff_sent_today = False
        self._strategy_history   = []
        self._last_scan_time     = 0.0
        self.live_strategy       = LiveStrategyRunner(self.bot)

        # OANDA feed — single source of truth for ticks + candles
        self.feed = OandaFeed(
            event_bus=event_bus,
            on_candle_close=self._on_candle_close,
        )

    # ── Candle close callback ─────────────────────────────────

    def _on_candle_close(self, timeframe: str, candle: dict):
        """Called by OandaFeed when a candle closes. candle is a plain dict."""
        self.event_bus.publish("candle", {
            "timeframe": timeframe,
            "candle":    candle,
        })
        # Publish full candle list for this TF so /api/candles/<tf> can serve from cache
        self._publish_candles(timeframe)
        logger.info(
            f"Candle closed: {timeframe} "
            f"O={candle['open']:.2f} H={candle['high']:.2f} "
            f"L={candle['low']:.2f}  C={candle['close']:.2f}"
        )
        if timeframe == "M5":
            self._publish_live_indicators()

    def _publish_candles(self, timeframe: str):
        """Publish latest 300 candles for a TF to EventBus so chart endpoint can serve them."""
        candles = self.feed.get_all_candles(timeframe)[-300:]
        chart_candles = [
            {"time": int(c["timestamp"]), "open": c["open"],
             "high": c["high"], "low": c["low"], "close": c["close"]}
            for c in candles if c.get("timestamp")
        ]
        self.event_bus.publish(f"candles_{timeframe}", chart_candles)

    # ── Indicator computation ─────────────────────────────────

    def _publish_live_indicators(self, force: bool = False):
        """Compute all indicators and confluence for live dashboard."""
        try:
            now = time.time()
            if not force and now - self._last_scan_time < 5.0:
                return
            self._last_scan_time = now

            h4  = self.feed.get_all_candles("H4")[-40:]
            h1  = self.feed.get_all_candles("H1")
            m15 = self.feed.get_all_candles("M15")
            m5  = self.feed.get_all_candles("M5")

            if not (h4 and h1 and m15 and m5):
                logger.debug("TFs not ready for indicator computation")
                return

            current_price = m5[-1]["close"]
            logger.debug(f"Computing indicators @ ${current_price:.2f}")

            # 1. Indicators
            indicators = compute_indicators(h4, h1, m15, m5)
            indicators.m15_candles = m15
            indicators_dict = indicators.to_dict()
            self.event_bus.publish("indicators", indicators_dict)

            # 2. Session & Macro
            news         = get_todays_events()
            session_info = get_session_info(news)
            session_dict = session_info.to_dict()
            self.event_bus.publish("session", session_dict)

            macro = fetch_macro_data()
            self.event_bus.publish("macro", macro)
            self.event_bus.publish("macro_bias", macro.get("macro_bias", ""))

            # 3. Dealing Range
            dr      = compute_dealing_range(indicators.swing_highs_h4, indicators.swing_lows_h4)
            dr_dict = dr.to_dict()
            self.event_bus.publish("dealing_range_update", dr_dict)

            # 4. ICT Sequence
            ict      = check_ict_sequence(indicators, session_dict, current_price, dr_dict)
            ict_dict = ict.to_dict()
            self.event_bus.publish("ict_update", ict_dict)

            # 4a. Market Regime
            regime = market_classifier.classify_market(indicators)
            self.event_bus.publish("market_regime", regime.__dict__)

            # 5. Confluence
            logger.debug("Computing confluence...")
            confluence = compute_confluence(
                indicators, ict_dict, dr_dict, session_dict, macro, current_price
            )

            ist_now = config.get_ist_now()
            levels  = {
                "bsl": next((p.price for p in indicators.liquidity_pools if p.type == "BSL"), None),
                "ssl": next((p.price for p in indicators.liquidity_pools if p.type == "SSL"), None),
                "fvg": indicators.fvgs_h1[-1].to_dict()  if indicators.fvgs_h1  else None,
                "ob":  indicators.obs_m15[-1].to_dict()  if indicators.obs_m15  else None,
            }

            scan_entry = {
                "timestamp":    ist_now.isoformat(),
                "time_ist":     ist_now.strftime("%H:%M:%S"),
                "confluence":   confluence,
                "ict":          ict_dict,
                "dr":           dr_dict,
                "levels":       levels,
                "price":        round(current_price, 2),
                "setup_status": ict_dict.get("setup_status", "Scanning..."),
            }
            self._strategy_history.insert(0, scan_entry)
            if len(self._strategy_history) > 20:
                self._strategy_history.pop()

            confluence["direction"]       = ict_dict.get("direction", "neutral")
            confluence["atr_h1"]          = round(indicators.atr_h1, 2)
            confluence["price"]           = round(current_price, 2)
            confluence["killzone_active"] = session_dict.get("killzone_active", False)
            confluence["session_label"]   = session_dict.get("session_label", "Unknown")

            self.event_bus.publish("confluence_update",  confluence)
            self.event_bus.publish("strategy_history",   self._strategy_history)
            self.event_bus.publish("strategy_update",    scan_entry)

            # 6. Live Strategy
            try:
                m5_bars = self.feed.get_all_candles("M5")
                self.live_strategy.on_m5_close(
                    m5_bars, confluence, ict_dict, self.event_bus, indicators
                )
            except Exception as e:
                logger.error(f"Live strategy error: {e}", exc_info=True)

            # 7. Terminal log
            self._log_strategy_status(confluence, ict_dict, dr_dict)

            # 8. Health
            self.event_bus.publish("health", self.health.get_status())

        except Exception as e:
            logger.error(f"Failed live indicator computation: {e}", exc_info=True)

    def _log_strategy_status(self, confluence: dict, ict: dict, dr: dict):
        """Log a structured strategy table to terminal."""
        try:
            total     = confluence.get("total", 0)
            max_score = confluence.get("maximum", 12)
            tradeable = confluence.get("tradeable", False)
            status_txt = "TRADEABLE ✅" if tradeable else "NO TRADE ❌"

            lines = ["", "=" * 60,
                     f"ICT STRATEGY SCAN | {datetime.now().strftime('%H:%M:%S')} IST",
                     f"SCORE: {total}/{max_score} | STATUS: {status_txt}",
                     "-" * 60]

            for name, data in confluence.get("factors", {}).items():
                lines.append(
                    f"{data.get('status',' ')} {name.replace('_',' ').title():<20} "
                    f"| {data.get('score', 0.0):>4} | {data.get('detail','')}"
                )

            lines += [
                "-" * 60,
                f"ICT Step: {ict.get('grade','None')} ({ict.get('steps_passed',0)}/6) "
                f"| Dir: {ict.get('direction','SIDEWAYS')}",
                f"ACTION:   {ict.get('setup_status','Scanning...')}",
            ]
            if dr.get("is_valid"):
                lines.append(
                    f"Range: ${dr.get('range_low',0):.2f} - ${dr.get('range_high',0):.2f} "
                    f"(EQ: ${dr.get('equilibrium',0):.2f})"
                )
            lines += ["=" * 60, ""]
            logger.info("\n".join(lines))
        except Exception as e:
            logger.error(f"Failed to log strategy status: {e}")

    # ── Session handoff ───────────────────────────────────────

    def _check_session_handoff(self):
        """Trigger daily session handoff at 16:30 IST and reset at midnight."""
        now = datetime.now()
        if now.hour == 16 and now.minute == 30 and not self._handoff_sent_today:
            logger.info("Triggering daily session handoff.")
            h4  = self.feed.get_all_candles("H4")
            h1  = self.feed.get_all_candles("H1")
            m15 = self.feed.get_all_candles("M15")
            m5  = self.feed.get_all_candles("M5")
            current_price = m5[-1]["close"] if m5 else 0.0
            indicators    = compute_indicators(h4, h1, m15, m5)
            handoff_data  = generate_handoff(indicators, h1, current_price)
            self.event_bus.publish("session_handoff", handoff_data)
            self._handoff_sent_today = True

        if now.hour == 0 and now.minute == 0 and self._handoff_sent_today:
            logger.info("Midnight IST: Resetting daily session flags.")
            self._handoff_sent_today = False
            try:
                from alerts.email_summary import send_daily_summary
                send_daily_summary()
            except Exception as e:
                logger.error(f"Daily email summary failed: {e}")

    # ── Periodic health + refresh loop ────────────────────────

    async def _health_check_loop(self):
        """Re-publish indicators every 60s and record feed health."""
        _counter = 0
        while True:
            await asyncio.sleep(5)
            _counter += 1

            if _counter % 12 == 0:   # every 60s
                self._publish_live_indicators(force=True)

            # Record tick health from OANDA connection state
            if self.feed._connected:
                self.health.record_tick()

            self.event_bus.publish("health", self.health.get_status())
            self._check_session_handoff()

    # ── Entry point ───────────────────────────────────────────

    async def run(self):
        """Start OANDA feed + health loop."""
        logger.info("Feed Manager starting (OANDA mode — no local storage)")
        logger.info(f"  Instrument: {config.OANDA_ACCOUNT_ID} / XAU_USD")

        # Initial publish after seed (feed.run() seeds before streaming)
        await asyncio.gather(
            self.feed.run(),
            self._health_check_loop(),
            self._delayed_initial_publish(),
        )

    async def _delayed_initial_publish(self):
        """Wait for seed to complete then push initial state to UI."""
        await asyncio.sleep(10)   # seed takes ~5s for 4 TFs
        for tf in ["M5", "M15", "H1", "H4"]:
            self._publish_candles(tf)
        self._publish_live_indicators(force=True)


async def run_pipeline(event_bus: EventBus):
    """Entry point for the pipeline process."""
    manager = FeedManager(event_bus)
    await manager.run()

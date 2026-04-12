"""
Feed Manager — Orchestrates dual-source WebSocket feeds with automatic failover.

Runs as the main async pipeline:
1. Connects both feeds (primary + standby)
2. Routes ticks to candle builder
3. Monitors health — failover if primary drops > 30s
4. Publishes events to EventBus for server consumption
"""

import asyncio
import time
import logging
from datetime import datetime

import config
from pipeline.event_bus import EventBus
from pipeline.twelve_data_feed import TwelveDataFeed
from pipeline.finnhub_feed import FinnhubFeed
from pipeline.candle_builder import CandleBuilder
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
from backtest.historical_fetch import fetch_historical_data
from pipeline.live_strategy import LiveStrategyRunner

logger = logging.getLogger(__name__)


class FeedManager:
    """Orchestrates data feeds, candle building, and event publishing."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.health = HealthMonitor()
        self.bot = TelegramBot()
        self.alerts = AlertsManager(event_bus)
        self._using_fallback = False
        self._handoff_sent_today = False
        self._strategy_history = []  # Maintain last 50 scans
        self._last_scan_time = 0.0   # User Fix: Latch to prevent duplicate scans
        self.live_strategy = LiveStrategyRunner(self.bot)  # Session Expansion (primary)

        # Candle builder — publishes candle_close events
        self.candle_builder = CandleBuilder(on_candle_close=self._on_candle_close)

        # Feeds
        self.primary = TwelveDataFeed(on_tick_callback=self._on_primary_tick)
        self.fallback = FinnhubFeed(on_tick_callback=self._on_fallback_tick)

    async def _on_primary_tick(self, tick: dict):
        """Handle tick from primary feed."""
        if not self._using_fallback:
            self.candle_builder.process_tick(tick)
            self.health.record_tick("twelve_data")
            self.event_bus.publish("tick", tick)

    async def _on_fallback_tick(self, tick: dict):
        """Handle tick from fallback feed (only when active)."""
        if self._using_fallback:
            self.candle_builder.process_tick(tick)
            self.health.record_tick("finnhub")
            self.event_bus.publish("tick", tick)

    def _on_candle_close(self, timeframe: str, candle):
        """Callback when a candle closes — publish to event bus."""
        # Align topic with frontend expected 'candle' (not candle_close)
        self.event_bus.publish("candle", {
            "timeframe": timeframe,
            "candle": candle.to_dict(),
        })
        logger.info(f"Candle closed: {timeframe} O={candle.open:.2f} H={candle.high:.2f} L={candle.low:.2f} C={candle.close:.2f}")
        
        # Compute and publish indicators and confluence ONLY on M5 close
        if timeframe == "M5":
            self._publish_live_indicators()

    def _publish_live_indicators(self, force: bool = False):
        """Compute all indicators and confluence for live dashboard."""
        try:
            # Latch to prevent duplicate scans (tick + candle close overlap)
            now = time.time()
            if not force and now - self._last_scan_time < 5.0:
                return
            self._last_scan_time = now
            
            h4 = self.candle_builder.get_all_candles("H4")[-40:]
            h1 = self.candle_builder.get_all_candles("H1")
            m15 = self.candle_builder.get_all_candles("M15")
            m5 = self.candle_builder.get_all_candles("M5")
            
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
            news = get_todays_events()
            session_info = get_session_info(news)
            session_dict = session_info.to_dict()
            self.event_bus.publish("session", session_dict)
            
            macro = fetch_macro_data()
            self.event_bus.publish("macro", macro)
            self.event_bus.publish("macro_bias", macro.get("macro_bias", ""))
            
            # 3. Dealing Range
            dr = compute_dealing_range(indicators.swing_highs_h4, indicators.swing_lows_h4)
            dr_dict = dr.to_dict()
            self.event_bus.publish("dealing_range_update", dr_dict)
            
            # 4. ICT Sequence
            ict = check_ict_sequence(indicators, session_dict, current_price, dr_dict)
            ict_dict = ict.to_dict()
            self.event_bus.publish("ict_update", ict_dict)

            # 4a. Market Regime (v5.0)
            regime = market_classifier.classify_market(indicators)
            self.event_bus.publish("market_regime", regime.__dict__)
            
            # 5. Confluence
            logger.debug("Computing confluence...")
            confluence = compute_confluence(indicators, ict_dict, dr_dict, session_dict, macro, current_price)
            
            # ── Accuracy Fix: Use central IST helper and explicit status extraction ──
            ist_now = config.get_ist_now()
            
            # ── Accuracy Fix: Bundle institutional levels for the dashboard ──
            # This ensures they update in sync with the matrix
            levels = {
                "bsl": next((p.price for p in indicators.liquidity_pools if p.type == "BSL"), None),
                "ssl": next((p.price for p in indicators.liquidity_pools if p.type == "SSL"), None),
                "fvg": indicators.fvgs_h1[-1].to_dict() if indicators.fvgs_h1 else None,
                "ob":  indicators.obs_m15[-1].to_dict() if indicators.obs_m15 else None
            }
            
            # Add to history (newest first)
            scan_entry = {
                "timestamp": ist_now.isoformat(),
                "time_ist": ist_now.strftime("%H:%M:%S"),
                "confluence": confluence,
                "ict": ict_dict,
                "dr": dr_dict,
                "levels": levels,
                "price": round(current_price, 2),
                "setup_status": ict_dict.get("setup_status", "Scanning...")
            }
            self._strategy_history.insert(0, scan_entry)
            if len(self._strategy_history) > 20:
                self._strategy_history.pop()
                
            # Enrich confluence with fields live_strategy and alerts_manager need
            confluence["direction"]       = ict_dict.get("direction", "neutral")
            confluence["atr_h1"]          = round(indicators.atr_h1, 2)
            confluence["price"]           = round(current_price, 2)
            confluence["killzone_active"] = session_dict.get("killzone_active", False)
            confluence["session_label"]   = session_dict.get("session_label", "Unknown")
            confluence["raw_score"]       = confluence  # factors already inside confluence dict
            
            self.event_bus.publish("confluence_update", confluence)
            self.event_bus.publish("strategy_history", self._strategy_history)
            self.event_bus.publish("strategy_update", scan_entry) # Added for real-time matrix update

            # 6. ICT Gold Standard strategy (Live Execution)
            # Feeds on every M5 close, decides entry via the synchronized 
            # confluence engine. Publishes trade alerts to Telegram.
            try:
                m5_bars = self.candle_builder.get_all_candles("M5")
                self.live_strategy.on_m5_close(m5_bars, confluence, ict_dict, self.event_bus, indicators)
            except Exception as e:
                logger.error(f"Live strategy error: {e}", exc_info=True)

            # 7. Terminal Logging — provide visual transparency for the user
            self._log_strategy_status(confluence, ict_dict, dr_dict)

            # 7. Health
            self.event_bus.publish("health", self.health.get_status())
        except Exception as e:
            logger.error(f"Failed live indicator computation: {e}", exc_info=True)

    def _log_strategy_status(self, confluence: dict, ict: dict, dr: dict):
        """Log a structured strategy table to terminal for live verification."""
        try:
            total = confluence.get("total", 0)
            max_score = confluence.get("maximum", 12)
            tradeable = confluence.get("tradeable", False)
            
            # Use ASCII only for logging to avoid encoding issues in some terminals
            status_txt = "TRADEABLE ✅" if tradeable else "NO TRADE ❌"
            
            lines = []
            lines.append("")
            lines.append("="*60)
            lines.append(f"ICT STRATEGY SCAN | {datetime.now().strftime('%H:%M:%S')} IST")
            lines.append(f"SCORE: {total}/{max_score} | STATUS: {status_txt}")
            lines.append("-" * 60)
            
            factors = confluence.get("factors", {})
            for name, data in factors.items():
                status = data.get("status", " ")
                score = data.get("score", 0.0)
                detail = data.get("detail", "")
                lines.append(f"{status} {name.replace('_', ' ').title():<20} | {score:>4} | {detail}")
                
            lines.append("-" * 60)
            lines.append(f"ICT Step: {ict.get('grade', 'None')} ({ict.get('steps_passed', 0)}/6) | Dir: {ict.get('direction', 'SIDEWAYS')}")
            lines.append(f"ACTION:   {ict.get('setup_status', 'Scanning...')}")
            if dr.get("is_valid"):
                lines.append(f"Range: ${dr.get('range_low', 0):.2f} - ${dr.get('range_high', 0):.2f} (Equilibrium: ${dr.get('equilibrium', 0):.2f})")
            lines.append("="*60)
            lines.append("")
            
            # Log as a single block
            logger.info("\n".join(lines))
        except Exception as e:
            logger.error(f"Failed to log strategy status: {e}")

    def _check_session_handoff(self):
        """Check if it's time to trigger the daily session handoff."""
        now = datetime.now()
        if now.hour == 16 and now.minute == 30 and not self._handoff_sent_today:
            logger.info("Triggering daily session handoff.")
            h4 = self.candle_builder.get_all_candles("H4")
            h1 = self.candle_builder.get_all_candles("H1")
            m15 = self.candle_builder.get_all_candles("M15")
            m5 = self.candle_builder.get_all_candles("M5")
            current_price = m5[-1]['close'] if m5 else 0.0

            from core.indicators import compute_indicators
            indicators = compute_indicators(h4, h1, m15, m5)
            
            handoff_data = generate_handoff(indicators, h1, current_price)
            self.event_bus.publish("session_handoff", handoff_data)
            self._handoff_sent_today = True
            
        if now.hour == 0 and now.minute == 0:
            if self._handoff_sent_today:
                logger.info("Midnight IST: Resetting daily session flags.")
                self._handoff_sent_today = False
                # Trigger daily email summary here
                from alerts.email_summary import send_daily_summary
                send_daily_summary()

    async def _health_check_loop(self):
        """
        Monitor primary feed health.
        If no tick received for FEED_TIMEOUT_SECONDS → failover to Finnhub.
        If primary recovers → switch back.
        """
        _refresh_counter = 0
        while True:
            await asyncio.sleep(5)  # check every 5 seconds
            _refresh_counter += 1

            # Re-publish full indicator state every 60s so page refreshes get
            # current data immediately without waiting for next M5 close.
            if _refresh_counter % 12 == 0:  # every 12 × 5s = 60s
                self._publish_live_indicators(force=True)

            primary_gap = self.health.primary.seconds_since_last_tick
            fallback_gap = self.health.fallback.seconds_since_last_tick

            if not self._using_fallback:
                # Currently on primary — check if it dropped
                if primary_gap > config.FEED_TIMEOUT_SECONDS and self.fallback.connected:
                    logger.warning(
                        f"Primary feed silent for {primary_gap:.0f}s. "
                        f"Switching to Finnhub."
                    )
                    self._using_fallback = True
                    self.fallback.activate()
                    self.health.record_failover("finnhub")
                    self.bot.alert_failover("PRIMARY_TIMEOUT", "FINNHUB")
                    self.event_bus.publish("feed_status", {
                        "event": "failover",
                        "from": "twelve_data",
                        "to": "finnhub",
                    })
                    self.event_bus.publish("alert", {
                        "type": "feed_failover",
                        "message": "⚠️ Feed switched to Finnhub. Primary recovering.",
                    })
            else:
                # Currently on fallback — check if primary recovered
                if primary_gap < 5 and self.primary.connected:
                    logger.info("Primary feed recovered. Switching back to Twelve Data.")
                    self._using_fallback = False
                    self.fallback.deactivate()
                    self.health.record_failover("twelve_data")
                    self.event_bus.publish("feed_status", {
                        "event": "restored",
                        "from": "finnhub",
                        "to": "twelve_data",
                    })
                    self.event_bus.publish("alert", {
                        "type": "feed_restored",
                        "message": "✅ Primary feed restored.",
                    })

            # Publish health status regularly
            self.event_bus.publish("health", self.health.get_status())

            # Check for session handoff auto-trigger at 4:30 PM IST (16:30)
            self._check_session_handoff()

    def _ensure_historical_data(self):
        """Fetch historical data from Twelve Data if CSVs are missing or small."""
        logger.info("Checking historical data requirements...")
        tf_map = {
            "M5": "5min",
            "M15": "15min",
            "H1": "1h",
            "H4": "4h"
        }
        
        for tf, interval in tf_map.items():
            csv_path = config.BACKTEST_DATA_DIR / f"{config.SYMBOL}_{interval}.csv"
            needs_fetch = False
            
            if not csv_path.exists():
                logger.info(f"Historical data for {tf} missing. Fetching...")
                needs_fetch = True
            else:
                # Check if it has enough bars (at least 5 days)
                import pandas as pd
                try:
                    df = pd.read_csv(csv_path)
                    if len(df) < config.CANDLE_HISTORY_SIZE * 0.8: # 80% threshold
                        logger.info(f"Historical data for {tf} is too small ({len(df)} bars). Fetching...")
                        needs_fetch = True
                except Exception:
                    needs_fetch = True

            if needs_fetch:
                fetch_historical_data(config.TWELVE_DATA_SYMBOL, interval, outputsize=config.CANDLE_HISTORY_SIZE)
        
        # After ensuring CSVs exist, tell candle builder to re-seed if it was already initialized
        # (Though on startup, CandleBuilder is initialized right before this in __init__)
        # To be safe, we re-trigger seeding if history is still small.
        for tf in config.TIMEFRAMES:
            if len(self.candle_builder._history[tf]) < config.CANDLE_HISTORY_SIZE * 0.5:
                self.candle_builder._seed_from_csv(tf)

    async def run(self):
        """Start all feeds and health monitoring."""
        logger.info("Feed Manager starting...")
        logger.info(f"  Primary: Twelve Data ({config.TWELVE_DATA_SYMBOL})")
        logger.info(f"  Fallback: Finnhub ({config.FINNHUB_SYMBOL})")
        logger.info(f"  Failover timeout: {config.FEED_TIMEOUT_SECONDS}s")

        # Ensure we have at least 5 days (approx 2000 bars) of history for all timeframes
        self._ensure_historical_data()

        # Publish initial state for immediate UI populating
        self._publish_live_indicators(force=True)

        # Run all concurrently
        await asyncio.gather(
            self.primary.connect(),
            self.fallback.connect(),
            self._health_check_loop(),
        )


async def run_pipeline(event_bus: EventBus):
    """Entry point for the pipeline process."""
    manager = FeedManager(event_bus)
    await manager.run()

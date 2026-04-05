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
        self.event_bus.publish("candle_close", {
            "timeframe": timeframe,
            "candle": candle.to_dict(),
        })
        logger.info(f"Candle closed: {timeframe} O={candle.open:.2f} H={candle.high:.2f} L={candle.low:.2f} C={candle.close:.2f}")

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
        while True:
            await asyncio.sleep(5)  # check every 5 seconds

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

            await asyncio.sleep(1)

    async def run(self):
        """Start all feeds and health monitoring."""
        logger.info("Feed Manager starting...")
        logger.info(f"  Primary: Twelve Data ({config.TWELVE_DATA_SYMBOL})")
        logger.info(f"  Fallback: Finnhub ({config.FINNHUB_SYMBOL})")
        logger.info(f"  Failover timeout: {config.FEED_TIMEOUT_SECONDS}s")

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

"""
Finnhub WebSocket Client — Fallback feed for XAUUSD ticks.

Connected in standby mode. Activated when Twelve Data drops.
Normalizes ticks to same internal format.
"""

import asyncio
import json
import time
import logging
import websockets

import config

logger = logging.getLogger(__name__)

WS_URL = "wss://ws.finnhub.io"


class FinnhubFeed:
    """Async WebSocket client for Finnhub XAU/USD tick stream (fallback)."""

    def __init__(self, on_tick_callback):
        self.on_tick = on_tick_callback
        self.ws = None
        self.connected = False
        self.active = False           # standby until activated
        self.last_tick_time = 0.0
        self._reconnect_delay = config.FEED_RECONNECT_BASE
        self._running = True

    async def connect(self):
        """Connect and subscribe — stays in standby until activated."""
        while self._running:
            try:
                url = f"{WS_URL}?token={config.FINNHUB_API_KEY}"
                logger.info("Finnhub: connecting (standby mode)...")
                async with websockets.connect(url, ping_interval=20) as ws:
                    self.ws = ws
                    self.connected = True
                    self._reconnect_delay = config.FEED_RECONNECT_BASE
                    logger.info("Finnhub: connected ✅ (standby)")

                    # Subscribe to XAUUSD
                    subscribe_msg = {
                        "type": "subscribe",
                        "symbol": config.FINNHUB_SYMBOL,
                    }
                    await ws.send(json.dumps(subscribe_msg))
                    logger.info(f"Finnhub: subscribed to {config.FINNHUB_SYMBOL}")

                    async for message in ws:
                        if not self._running:
                            break
                        await self._handle_message(message)

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Finnhub: connection closed — {e}")
            except Exception as e:
                logger.error(f"Finnhub: error — {e}")
            finally:
                self.connected = False
                self.ws = None

            if self._running:
                logger.info(f"Finnhub: reconnecting in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, config.FEED_RECONNECT_MAX
                )

    async def _handle_message(self, raw: str):
        """Parse Finnhub trade message and normalize."""
        try:
            data = json.loads(raw)

            if data.get("type") == "trade" and self.active:
                trades = data.get("data", [])
                for trade in trades:
                    price = float(trade.get("p", 0))
                    ts = float(trade.get("t", time.time() * 1000)) / 1000  # ms → s

                    if price > 0:
                        tick = {
                            "price": price,
                            "timestamp": ts,
                            "source": "finnhub",
                        }
                        self.last_tick_time = time.time()
                        await self.on_tick(tick)

            elif data.get("type") == "ping":
                self.last_tick_time = time.time()

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Finnhub: bad message — {e}")

    def activate(self):
        """Switch from standby to active — start forwarding ticks."""
        self.active = True
        logger.info("Finnhub: ACTIVATED — now primary feed")

    def deactivate(self):
        """Switch back to standby — stop forwarding ticks."""
        self.active = False
        logger.info("Finnhub: deactivated — back to standby")

    def stop(self):
        """Signal the feed to stop."""
        self._running = False
        if self.ws:
            asyncio.create_task(self.ws.close())

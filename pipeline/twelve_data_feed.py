"""
Twelve Data WebSocket Client — Primary feed for XAUUSD ticks.

Connects to Twelve Data's WebSocket API, receives real-time price updates,
and normalizes them to the internal tick format.
"""

import asyncio
import json
import time
import logging
import ssl
import websockets

import config

logger = logging.getLogger(__name__)

WS_URL = "wss://ws.twelvedata.com/v1/quotes/price"


class TwelveDataFeed:
    """Async WebSocket client for Twelve Data XAUUSD tick stream."""

    def __init__(self, on_tick_callback):
        self.on_tick = on_tick_callback
        self.ws = None
        self.connected = False
        self.last_tick_time = 0.0
        self._reconnect_delay = config.FEED_RECONNECT_BASE
        self._running = True

    async def connect(self):
        """Connect and subscribe to XAUUSD price stream."""
        if config.SSL_NO_VERIFY:
            ssl_context = ssl._create_unverified_context()
        else:
            ssl_context = ssl.create_default_context()

        while self._running:
            try:
                # Twelve Data often requires the API key in the URL for the handshake to succeed
                url = f"{WS_URL}?apikey={config.TWELVE_DATA_API_KEY}"
                logger.info("Twelve Data: connecting...")
                # Set aggressive ping to keep connection alive and detect drops fast
                async with websockets.connect(url, ping_interval=10, ping_timeout=10, ssl=ssl_context) as ws:
                    self.ws = ws
                    self.connected = True
                    self._reconnect_delay = config.FEED_RECONNECT_BASE
                    logger.info("Twelve Data: connected ✅")

                    # Subscribe to XAUUSD
                    subscribe_msg = {
                        "action": "subscribe",
                        "params": {
                            "symbols": config.TWELVE_DATA_SYMBOL,
                            "apikey": config.TWELVE_DATA_API_KEY,
                        },
                    }
                    await ws.send(json.dumps(subscribe_msg))
                    logger.info(f"Twelve Data: subscribed to {config.TWELVE_DATA_SYMBOL}")

                    # Listen for messages
                    async for message in ws:
                        if not self._running:
                            break
                        await self._handle_message(message)

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Twelve Data: connection closed — {e}")
            except Exception as e:
                logger.error(f"Twelve Data: error — {e}")
            finally:
                self.connected = False
                self.ws = None

            if self._running:
                logger.info(f"Twelve Data: reconnecting in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, config.FEED_RECONNECT_MAX
                )

    async def _handle_message(self, raw: str):
        """Parse Twelve Data message and normalize to internal tick format."""
        try:
            data = json.loads(raw)

            # Skip non-price events (status, heartbeat, etc.)
            event_type = data.get("event")
            if event_type == "price":
                price = float(data.get("price", 0))
                ts = float(data.get("timestamp", time.time()))

                if price > 0:
                    tick = {
                        "price": price,
                        "timestamp": ts,
                        "source": "twelve_data",
                    }
                    self.last_tick_time = time.time()
                    await self.on_tick(tick)
            elif event_type == "subscribe-status":
                status = data.get("status", "")
                logger.info(f"Twelve Data: subscription status — {status}")
            elif event_type == "heartbeat":
                self.last_tick_time = time.time()

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Twelve Data: bad message — {e}")

    def stop(self):
        """Signal the feed to stop."""
        self._running = False
        if self.ws:
            asyncio.create_task(self.ws.close())

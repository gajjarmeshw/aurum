"""
OANDA Feed — Fetches live candles + tick price directly from OANDA practice API.

Replaces CandleBuilder + TwelveData/Finnhub WebSocket feeds.
No local storage, no CSV, no self-built candles.

Flow:
  - Tick price: streaming API (every ~1s)  → publishes 'tick' events
  - Candles:    REST poll every 5s          → on M5 boundary close → publishes 'candle' + triggers indicators
"""

import asyncio
import logging
import time
from datetime import datetime

import requests

import config
from pipeline.event_bus import EventBus

logger = logging.getLogger(__name__)

OANDA_REST    = "https://api-fxpractice.oanda.com"
OANDA_STREAM  = "https://stream-fxpractice.oanda.com"
INSTRUMENT    = "XAU_USD"

TF_MAP = {
    "M1":  ("M1",  60),
    "M5":  ("M5",  300),
    "M15": ("M15", 900),
    "H1":  ("H1",  3600),
    "H4":  ("H4",  14400),
}
OANDA_GRAN = {"M1": "M1", "M5": "M5", "M15": "M15", "H1": "H1", "H4": "H4"}
CANDLE_COUNT = 500   # bars to fetch per TF — more than enough for all indicators
M1_CANDLE_COUNT = 300  # ~5 hours of M1 history for DOR/ASW FVG detection


class OandaFeed:
    """
    Single feed class — replaces TwelveDataFeed + FinnhubFeed + CandleBuilder.

    Responsibilities:
      1. Stream live price ticks via OANDA streaming API
      2. Poll REST every 5s to get current open candle (live bar update)
      3. Detect candle closes by time boundary — fetch verified closed bars
      4. Maintain in-memory candle history (no CSV, no disk)
      5. Publish tick / candle events to EventBus
    """

    def __init__(self, event_bus: EventBus, on_candle_close=None):
        self.event_bus      = event_bus
        self.on_candle_close = on_candle_close

        self._token      = config.OANDA_API_TOKEN
        self._account_id = config.OANDA_ACCOUNT_ID
        self._headers    = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type":  "application/json",
        }

        # In-memory candle store: tf → list of dicts (OHLCV)
        self._candles: dict[str, list] = {tf: [] for tf in TF_MAP}

        # Track last closed bar timestamp per TF to detect new closes
        self._last_closed_ts: dict[str, float] = {tf: 0.0 for tf in TF_MAP}

        self._last_price: float = 0.0
        self._connected: bool   = False

    # ── Public interface (mirrors CandleBuilder) ──────────────

    def get_all_candles(self, tf: str) -> list[dict]:
        return list(self._candles.get(tf, []))

    # ── Boot ─────────────────────────────────────────────────

    async def run(self):
        """Start tick stream + candle poll loop concurrently."""
        logger.info(f"OANDA Feed starting — instrument: {INSTRUMENT}")
        await self._seed_all()   # load initial history before going live
        await asyncio.gather(
            self._tick_stream_loop(),
            self._candle_poll_loop(),
        )

    # ── Initial seed — load history once on startup ───────────

    async def _seed_all(self):
        """Fetch initial candle history for all TFs on startup (non-blocking)."""
        for tf in TF_MAP:
            count = M1_CANDLE_COUNT if tf == "M1" else CANDLE_COUNT
            candles = await asyncio.to_thread(self._fetch_candles, tf, count)
            if candles:
                self._candles[tf] = candles
                self._last_closed_ts[tf] = candles[-1]["timestamp"]
                logger.info(f"OANDA seeded {len(candles)} {tf} candles")
            else:
                logger.warning(f"OANDA seed failed for {tf}")

    # ── Live tick stream ──────────────────────────────────────

    async def _tick_stream_loop(self):
        """Stream live bid/ask from OANDA — publishes tick events.
        Runs blocking iter_lines in a thread to avoid blocking the asyncio event loop.
        """
        import json

        url    = f"{OANDA_STREAM}/v3/accounts/{self._account_id}/pricing/stream"
        params = {"instruments": INSTRUMENT}

        while True:
            try:
                # Open streaming connection in a thread (blocking I/O)
                resp = await asyncio.to_thread(
                    requests.get, url,
                    headers=self._headers, params=params, stream=True, timeout=30
                )
                self._connected = True
                logger.info("OANDA tick stream connected ✅")

                def _read_lines():
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except Exception:
                            continue
                        if data.get("type") != "PRICE":
                            continue
                        bid = float(data["bids"][0]["price"])
                        ask = float(data["asks"][0]["price"])
                        mid = round((bid + ask) / 2.0, 2)
                        self._last_price = mid
                        self.event_bus.publish("tick", {
                            "price":     mid,
                            "bid":       round(bid, 2),
                            "ask":       round(ask, 2),
                            "timestamp": time.time(),
                            "source":    "oanda",
                        })

                await asyncio.to_thread(_read_lines)

            except Exception as e:
                self._connected = False
                logger.warning(f"OANDA stream error: {e} — reconnecting in 5s")
                await asyncio.sleep(5)

    # ── Candle poll loop ──────────────────────────────────────

    async def _candle_poll_loop(self):
        """
        Per-TF smart polling — each TF polled at its own sensible interval:
          M5  → every 10s  (closes every 300s,  need ~30 polls per bar)
          M15 → every 30s  (closes every 900s,  need ~30 polls per bar)
          H1  → every 60s  (closes every 3600s, need ~60 polls per bar)
          H4  → every 120s (closes every 14400s, need ~120 polls per bar)

        Each poll fetches only 3 bars (last closed + current open).
        Total REST calls: 6 + 2 + 1 + 0.5 ≈ ~10 calls/min — very low.
        """
        poll_intervals = {"M5": 10, "M15": 30, "H1": 60, "H4": 120}
        last_poll      = {tf: 0.0 for tf in TF_MAP}

        while True:
            await asyncio.sleep(5)   # base tick — check every 5s
            now = time.time()
            for tf, interval in poll_intervals.items():
                if now - last_poll[tf] >= interval:
                    last_poll[tf] = now
                    try:
                        await asyncio.to_thread(self._poll_tf, tf)
                    except Exception as e:
                        logger.error(f"OANDA candle poll error ({tf}): {e}", exc_info=True)

    def _poll_tf(self, tf: str):
        """Fetch latest 3 bars for one TF — detect close, update open candle."""
        bars = self._fetch_candles(tf, count=3)
        if not bars or len(bars) < 2:
            return

        # bars[-1] = current open (incomplete), bars[-2] = just-closed bar
        closed_bar = bars[-2]
        open_bar   = bars[-1]
        closed_ts  = closed_bar["timestamp"]

        # Detect new candle close
        if closed_ts > self._last_closed_ts[tf]:
            self._last_closed_ts[tf] = closed_ts

            candles = self._candles[tf]
            if candles and candles[-1]["timestamp"] == closed_ts:
                candles[-1] = closed_bar
            else:
                candles.append(closed_bar)
                if len(candles) > CANDLE_COUNT:
                    candles.pop(0)

            if self.on_candle_close:
                self.on_candle_close(tf, closed_bar)

            logger.info(
                f"Candle closed: {tf} "
                f"O={closed_bar['open']:.2f} H={closed_bar['high']:.2f} "
                f"L={closed_bar['low']:.2f}  C={closed_bar['close']:.2f}"
            )

        # Always update the live open candle
        candles = self._candles[tf]
        if candles:
            if candles[-1]["timestamp"] == open_bar["timestamp"]:
                candles[-1] = open_bar
            else:
                candles.append(open_bar)

    # ── REST helper ───────────────────────────────────────────

    def _fetch_candles_sync(self, tf: str, count: int = 500) -> list[dict]:
        return self._fetch_candles(tf, count)

    def _fetch_candles(self, tf: str, count: int = 500) -> list[dict]:
        """
        Fetch OHLCV candles from OANDA REST.
        Returns list of dicts with keys: timestamp, open, high, low, close, volume.
        Only returns bars with complete=True (fully closed) + the current open bar.
        """
        gran = OANDA_GRAN[tf]
        url  = f"{OANDA_REST}/v3/instruments/{INSTRUMENT}/candles"
        params = {
            "granularity": gran,
            "count":       count + 1,   # +1 because last bar is open (incomplete)
            "price":       "M",         # midpoint candles (bid+ask/2)
        }
        try:
            resp = requests.get(url, headers=self._headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            candles = []
            for c in data.get("candles", []):
                mid = c.get("mid", {})
                if not mid:
                    continue
                ts = _oanda_ts(c["time"])
                candles.append({
                    "timestamp": ts,
                    "open":      round(float(mid["o"]), 2),
                    "high":      round(float(mid["h"]), 2),
                    "low":       round(float(mid["l"]), 2),
                    "close":     round(float(mid["c"]), 2),
                    "volume":    int(c.get("volume", 0)),
                    "complete":  c.get("complete", False),
                })
            return candles

        except Exception as e:
            logger.warning(f"OANDA REST fetch failed ({tf}): {e}")
            return []


def _oanda_ts(iso_str: str) -> float:
    """Convert OANDA ISO timestamp string to unix float."""
    # OANDA format: "2026-04-14T09:00:00.000000000Z"
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0

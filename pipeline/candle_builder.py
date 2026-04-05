"""
Candle Builder — Builds M5/M15/H1/H4 candles from tick stream.

Maintains rolling candle state for all 4 timeframes simultaneously.
All built from the same tick stream — no extra API calls.
Publishes candle_close events on completion.
Persists to disk every 15 minutes for recovery.
"""

import time
import json
import logging
from dataclasses import dataclass, field, asdict
from collections import deque
from pathlib import Path

import config

logger = logging.getLogger(__name__)


@dataclass
class Candle:
    """OHLCV candle."""
    timestamp: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = float("inf")
    close: float = 0.0
    volume: int = 0
    timeframe: str = ""
    closed: bool = False

    def update(self, price: float):
        """Update candle with new tick price."""
        if self.open == 0:
            self.open = price
        self.high = max(self.high, price)
        self.low = min(self.low, price) if self.low != float("inf") else price
        self.close = price
        self.volume += 1

    def to_dict(self) -> dict:
        return asdict(self)


class CandleBuilder:
    """
    Builds candles for M5/M15/H1/H4 simultaneously from tick stream.
    
    Keeps last CANDLE_HISTORY_SIZE candles per timeframe in memory.
    Publishes candle_close event via callback when a candle completes.
    """

    def __init__(self, on_candle_close=None):
        self.on_candle_close = on_candle_close
        self._current: dict[str, Candle] = {}
        self._history: dict[str, deque] = {}
        self._last_persist = time.time()

        for tf in config.TIMEFRAMES:
            self._current[tf] = Candle(timeframe=tf)
            self._history[tf] = deque(maxlen=config.CANDLE_HISTORY_SIZE)

        # Try to load persisted candles
        self._load_from_disk()

    def process_tick(self, tick: dict):
        """
        Process incoming tick across all timeframes.
        
        tick: {"price": float, "timestamp": float, "source": str}
        """
        price = tick["price"]
        ts = tick["timestamp"]

        for tf, tf_config in config.TIMEFRAMES.items():
            period = tf_config["seconds"]
            candle = self._current[tf]
            candle_start = self._align_timestamp(ts, period)

            # Check if this tick belongs to a new candle
            if candle.timestamp == 0:
                # First tick ever for this timeframe
                candle.timestamp = candle_start
                candle.update(price)
            elif candle_start > candle.timestamp:
                # New candle period — close the current one
                candle.closed = True
                self._history[tf].append(candle)

                # Notify listeners
                if self.on_candle_close:
                    self.on_candle_close(tf, candle)

                # Start new candle
                new_candle = Candle(timestamp=candle_start, timeframe=tf)
                new_candle.update(price)
                self._current[tf] = new_candle
            else:
                # Same candle period — update
                candle.update(price)

        # Periodic disk persist
        if time.time() - self._last_persist >= config.CANDLE_PERSIST_INTERVAL:
            self._persist_to_disk()
            self._last_persist = time.time()

    def get_candles(self, timeframe: str, count: int | None = None) -> list[dict]:
        """Get closed candles for a timeframe. Most recent last."""
        history = self._history.get(timeframe, deque())
        candles = list(history)
        if count:
            candles = candles[-count:]
        return [c.to_dict() for c in candles]

    def get_current_candle(self, timeframe: str) -> dict | None:
        """Get the in-progress candle for a timeframe."""
        candle = self._current.get(timeframe)
        if candle and candle.timestamp > 0:
            return candle.to_dict()
        return None

    def get_all_candles(self, timeframe: str, count: int | None = None) -> list[dict]:
        """Get closed candles + current open candle."""
        closed = self.get_candles(timeframe, count)
        current = self.get_current_candle(timeframe)
        if current:
            closed.append(current)
        return closed

    @staticmethod
    def _align_timestamp(ts: float, period: int) -> float:
        """Align timestamp to the start of its candle period."""
        return float(int(ts) // period * period)

    def _persist_to_disk(self):
        """Save current candle state to disk for crash recovery."""
        try:
            for tf in config.TIMEFRAMES:
                filepath = config.CANDLE_CACHE_DIR / f"{tf}_candles.json"
                candles = [c.to_dict() for c in self._history[tf]]
                current = self._current[tf].to_dict() if self._current[tf].timestamp > 0 else None
                data = {"closed": candles, "current": current}
                filepath.write_text(json.dumps(data))
            logger.debug("Candles persisted to disk")
        except Exception as e:
            logger.error(f"Failed to persist candles: {e}")

    def _load_from_disk(self):
        """Load candle state from disk if available."""
        for tf in config.TIMEFRAMES:
            filepath = config.CANDLE_CACHE_DIR / f"{tf}_candles.json"
            if filepath.exists():
                try:
                    data = json.loads(filepath.read_text())
                    for c_data in data.get("closed", []):
                        candle = Candle(**c_data)
                        self._history[tf].append(candle)
                    current_data = data.get("current")
                    if current_data and current_data.get("timestamp", 0) > 0:
                        self._current[tf] = Candle(**current_data)
                    logger.info(f"Loaded {len(self._history[tf])} {tf} candles from disk")
                except Exception as e:
                    logger.warning(f"Could not load {tf} candles from disk: {e}")

"""
Dealing Range — H4 dealing range mapper with OTE zone calculation.

Identifies the current H4 range, equilibrium, premium/discount zones,
and the Optimal Trade Entry (OTE) zone at 61.8–79% Fibonacci retracement.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DealingRange:
    """H4 Dealing Range with all derived zones."""
    range_high: float = 0.0
    range_low: float = 0.0
    equilibrium: float = 0.0       # 50% of range
    ote_high: float = 0.0          # 61.8% fib
    ote_low: float = 0.0           # 79% fib
    is_valid: bool = False

    @property
    def range_size(self) -> float:
        return self.range_high - self.range_low

    def classify_price(self, price: float) -> dict:
        """Classify current price relative to dealing range."""
        if not self.is_valid or self.range_size == 0:
            return {"zone": "unknown", "in_ote": False, "in_discount": False, "in_premium": False}

        in_premium = price > self.equilibrium
        in_discount = price < self.equilibrium
        in_ote = self.ote_low <= price <= self.ote_high

        if price >= self.range_high:
            zone = "above_range"
        elif price > self.equilibrium:
            zone = "premium"
        elif price == self.equilibrium:
            zone = "equilibrium"
        elif price >= self.ote_high:
            zone = "discount"
        elif price >= self.ote_low:
            zone = "ote"
        elif price >= self.range_low:
            zone = "deep_discount"
        else:
            zone = "below_range"

        return {
            "zone": zone,
            "in_ote": in_ote,
            "in_discount": in_discount,
            "in_premium": in_premium,
            "distance_to_eq": round(abs(price - self.equilibrium), 2),
        }

    def to_dict(self) -> dict:
        return {
            "range_high": round(self.range_high, 2),
            "range_low": round(self.range_low, 2),
            "equilibrium": round(self.equilibrium, 2),
            "ote_high": round(self.ote_high, 2),
            "ote_low": round(self.ote_low, 2),
            "range_size": round(self.range_size, 2),
            "is_valid": self.is_valid,
        }


def compute_dealing_range(swing_highs: list, swing_lows: list) -> DealingRange:
    """
    Compute H4 dealing range from most recent swing high and swing low.
    
    OTE zone for bullish setup (buying):
      - 61.8% retracement from high = range_low + 0.382 * range
      - 79%   retracement from high = range_low + 0.21 * range
    
    For bearish setup: mirror (premium side).
    We compute both and let the confluence scorer/report decide which to use.
    """
    dr = DealingRange()

    if not swing_highs or not swing_lows:
        return dr

    # User Fix: Tighten lookback to 40 H4 candles (~1 week) for reachable OTE zones
    MAX_LOOKBACK = 40
    if swing_highs and hasattr(swing_highs[-1], 'index'):
        last_idx = swing_highs[-1].index
        recent_highs = [s for s in swing_highs if last_idx - s.index <= MAX_LOOKBACK]
        recent_lows = [s for s in swing_lows if last_idx - s.index <= MAX_LOOKBACK]
    else:
        recent_highs = swing_highs[-10:] if swing_highs else []
        recent_lows = swing_lows[-10:] if swing_lows else []

    # Use most recent swing points within the lookback
    last_high = max(recent_highs, key=lambda s: s.price) if recent_highs else None
    last_low = min(recent_lows, key=lambda s: s.price) if recent_lows else None

    if not last_high or not last_low:
        return dr

    dr.range_high = last_high.price
    dr.range_low = last_low.price
    dr.equilibrium = (dr.range_high + dr.range_low) / 2

    range_size = dr.range_size
    if range_size <= 0:
        return dr

    # OTE zone — bullish: 61.8% to 79% retracement from high
    # Price = High - fib_level * range  →  Low + (1 - fib_level) * range
    dr.ote_high = dr.range_low + (1 - 0.618) * range_size  # 61.8% retrace
    dr.ote_low = dr.range_low + (1 - 0.79) * range_size    # 79% retrace
    dr.is_valid = True

    return dr

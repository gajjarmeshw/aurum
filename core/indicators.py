"""
Technical Indicators — ATR, Swing H/L, FVG, OB, BOS, CHoCH, Liquidity Pools.

All functions accept lists of candle dicts: {"timestamp", "open", "high", "low", "close"}
Returns computed indicator values for use by confluence scorer and report generator.
"""

import logging
from dataclasses import dataclass, field

import config

logger = logging.getLogger(__name__)


@dataclass
class SwingPoint:
    """A swing high or low."""
    price: float
    index: int
    timestamp: float
    type: str  # "high" or "low"


@dataclass
class FVG:
    """Fair Value Gap."""
    high: float          # top of gap
    low: float           # bottom of gap
    direction: str       # "bullish" or "bearish"
    index: int
    timestamp: float
    filled: bool = False


@dataclass
class OrderBlock:
    """Order Block — last opposite candle before impulse."""
    high: float
    low: float
    direction: str       # "bullish" (demand) or "bearish" (supply)
    index: int
    timestamp: float
    mitigated: bool = False


@dataclass
class BOS:
    """Break of Structure."""
    price: float         # level breached
    direction: str       # "bullish" or "bearish"
    index: int
    timestamp: float


@dataclass
class LiquidityPool:
    """Equal highs/lows cluster — liquidity target."""
    price: float
    type: str            # "BSL" (buy-side) or "SSL" (sell-side)
    count: int           # number of equal levels
    swept: bool = False
    sweep_timestamp: float = 0.0


@dataclass
class IndicatorResult:
    """Complete indicator computation result for a timeframe set."""
    atr_h1: float = 0.0
    atr_h4: float = 0.0
    swing_highs_h4: list = field(default_factory=list)
    swing_lows_h4: list = field(default_factory=list)
    swing_highs_h1: list = field(default_factory=list)
    swing_lows_h1: list = field(default_factory=list)
    swing_highs_m15: list = field(default_factory=list)
    swing_lows_m15: list = field(default_factory=list)
    fvgs_h1: list = field(default_factory=list)
    fvgs_m15: list = field(default_factory=list)
    obs_h1: list = field(default_factory=list)
    obs_m15: list = field(default_factory=list)
    obs_m5: list = field(default_factory=list)
    bos_h1: list = field(default_factory=list)
    choch_h1: list = field(default_factory=list)
    liquidity_pools: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to JSON-safe dict."""
        def _serialize(items):
            if not items:
                return []
            if hasattr(items[0], '__dict__'):
                return [vars(i) for i in items]
            return items

        return {
            "atr_h1": round(self.atr_h1, 2),
            "atr_h4": round(self.atr_h4, 2),
            "swing_highs_h4": _serialize(self.swing_highs_h4),
            "swing_lows_h4": _serialize(self.swing_lows_h4),
            "swing_highs_h1": _serialize(self.swing_highs_h1),
            "swing_lows_h1": _serialize(self.swing_lows_h1),
            "fvgs_h1": _serialize(self.fvgs_h1),
            "fvgs_m15": _serialize(self.fvgs_m15),
            "obs_h1": _serialize(self.obs_h1),
            "obs_m15": _serialize(self.obs_m15),
            "obs_m5": _serialize(self.obs_m5),
            "bos_h1": _serialize(self.bos_h1),
            "choch_h1": _serialize(self.choch_h1),
            "liquidity_pools": _serialize(self.liquidity_pools),
        }


# ─── ATR ─────────────────────────────────────────────────────

def compute_atr(candles: list[dict], period: int = None) -> float:
    """Average True Range — measures volatility."""
    period = period or config.ATR_PERIOD
    if len(candles) < period + 1:
        return 0.0

    true_ranges = []
    for i in range(1, len(candles)):
        c = candles[i]
        prev = candles[i - 1]
        tr = max(
            c["high"] - c["low"],
            abs(c["high"] - prev["close"]),
            abs(c["low"] - prev["close"]),
        )
        true_ranges.append(tr)

    # Wilder's smoothing for last `period` TRs
    recent = true_ranges[-(period):]
    if not recent:
        return 0.0
    atr = sum(recent) / len(recent)
    return atr


# ─── Swing Highs / Lows ─────────────────────────────────────

def detect_swings(candles: list[dict], lookback: int = None) -> tuple[list[SwingPoint], list[SwingPoint]]:
    """
    5-bar pivot detection for swing highs and lows.
    Returns (highs, lows).
    """
    lookback = lookback or config.SWING_LOOKBACK
    highs = []
    lows = []

    if len(candles) < lookback * 2 + 1:
        return highs, lows

    for i in range(lookback, len(candles) - lookback):
        c = candles[i]

        # Swing high: higher high than all neighbors
        is_high = all(
            c["high"] >= candles[i + j]["high"]
            for j in range(-lookback, lookback + 1)
            if j != 0
        )
        if is_high:
            highs.append(SwingPoint(
                price=c["high"], index=i,
                timestamp=c.get("timestamp", 0), type="high"
            ))

        # Swing low: lower low than all neighbors
        is_low = all(
            c["low"] <= candles[i + j]["low"]
            for j in range(-lookback, lookback + 1)
            if j != 0
        )
        if is_low:
            lows.append(SwingPoint(
                price=c["low"], index=i,
                timestamp=c.get("timestamp", 0), type="low"
            ))

    return highs, lows


# ─── FVG (Fair Value Gap) ────────────────────────────────────

def detect_fvgs(candles: list[dict]) -> list[FVG]:
    """
    3-candle gap scan.
    Bullish FVG: candle[i-1].high < candle[i+1].low (gap up)
    Bearish FVG: candle[i-1].low > candle[i+1].high (gap down)
    """
    fvgs = []
    if len(candles) < 3:
        return fvgs

    for i in range(1, len(candles) - 1):
        prev = candles[i - 1]
        curr = candles[i]
        next_c = candles[i + 1]

        # Bullish FVG
        if prev["high"] < next_c["low"]:
            fvgs.append(FVG(
                high=next_c["low"],
                low=prev["high"],
                direction="bullish",
                index=i,
                timestamp=curr.get("timestamp", 0),
            ))

        # Bearish FVG
        if prev["low"] > next_c["high"]:
            fvgs.append(FVG(
                high=prev["low"],
                low=next_c["high"],
                direction="bearish",
                index=i,
                timestamp=curr.get("timestamp", 0),
            ))

    return fvgs


# ─── Order Blocks ────────────────────────────────────────────

def detect_order_blocks(candles: list[dict], min_impulse_multiple: float = 1.5) -> list[OrderBlock]:
    """
    Last opposite candle before an impulse move.
    Bullish OB: last bearish candle before strong bullish impulse.
    Bearish OB: last bullish candle before strong bearish impulse.
    """
    obs = []
    if len(candles) < 3:
        return obs

    for i in range(1, len(candles) - 1):
        curr = candles[i]
        next_c = candles[i + 1]
        prev = candles[i - 1]

        curr_body = abs(curr["close"] - curr["open"])
        next_body = abs(next_c["close"] - next_c["open"])
        avg_body = (curr_body + abs(prev["close"] - prev["open"])) / 2

        if avg_body == 0:
            continue

        # Bullish OB: current is bearish, next is strong bullish
        if (curr["close"] < curr["open"] and
                next_c["close"] > next_c["open"] and
                next_body >= avg_body * min_impulse_multiple):
            obs.append(OrderBlock(
                high=curr["high"], low=curr["low"],
                direction="bullish", index=i,
                timestamp=curr.get("timestamp", 0),
            ))

        # Bearish OB: current is bullish, next is strong bearish
        if (curr["close"] > curr["open"] and
                next_c["close"] < next_c["open"] and
                next_body >= avg_body * min_impulse_multiple):
            obs.append(OrderBlock(
                high=curr["high"], low=curr["low"],
                direction="bearish", index=i,
                timestamp=curr.get("timestamp", 0),
            ))

    return obs


# ─── BOS / CHoCH Detection ──────────────────────────────────

def detect_bos_choch(candles: list[dict], swing_highs: list[SwingPoint],
                      swing_lows: list[SwingPoint]) -> tuple[list[BOS], list[BOS]]:
    """
    Break of Structure (BOS) — swing breach in trend direction.
    Change of Character (CHoCH) — swing breach against current trend.
    
    Returns (bos_list, choch_list).
    """
    bos_list = []
    choch_list = []

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return bos_list, choch_list

    # Determine current trend from swing sequence
    # Higher highs + higher lows = bullish
    # Lower highs + lower lows = bearish
    last_two_highs = swing_highs[-2:]
    last_two_lows = swing_lows[-2:]

    trend_up = (last_two_highs[1].price > last_two_highs[0].price and
                last_two_lows[1].price > last_two_lows[0].price)
    trend_down = (last_two_highs[1].price < last_two_highs[0].price and
                  last_two_lows[1].price < last_two_lows[0].price)

    if not candles:
        return bos_list, choch_list

    current_price = candles[-1]["close"]
    last_candle = candles[-1]

    # Check for BOS / CHoCH against most recent swing levels
    last_high = swing_highs[-1]
    last_low = swing_lows[-1]

    # Bullish BOS: price breaks above last swing high in uptrend
    if current_price > last_high.price:
        if trend_up:
            bos_list.append(BOS(
                price=last_high.price, direction="bullish",
                index=len(candles) - 1,
                timestamp=last_candle.get("timestamp", 0),
            ))
        elif trend_down:
            # Breaking high in downtrend = CHoCH
            choch_list.append(BOS(
                price=last_high.price, direction="bullish",
                index=len(candles) - 1,
                timestamp=last_candle.get("timestamp", 0),
            ))

    # Bearish BOS: price breaks below last swing low in downtrend
    if current_price < last_low.price:
        if trend_down:
            bos_list.append(BOS(
                price=last_low.price, direction="bearish",
                index=len(candles) - 1,
                timestamp=last_candle.get("timestamp", 0),
            ))
        elif trend_up:
            choch_list.append(BOS(
                price=last_low.price, direction="bearish",
                index=len(candles) - 1,
                timestamp=last_candle.get("timestamp", 0),
            ))

    return bos_list, choch_list


# ─── Liquidity Pools ────────────────────────────────────────

def detect_liquidity_pools(swing_highs: list[SwingPoint], swing_lows: list[SwingPoint],
                            current_price: float, tolerance: float = 5.0) -> list[LiquidityPool]:
    """
    Equal highs/lows clusters — liquidity targets.
    tolerance: dollar range within which two levels are considered "equal".
    """
    pools = []

    # BSL — equal highs (buy-side liquidity above)
    if swing_highs:
        high_prices = [sh.price for sh in swing_highs[-20:]]  # last 20 swings
        clusters = _cluster_levels(high_prices, tolerance)
        for level, count in clusters:
            if count >= 2 and level > current_price:
                pools.append(LiquidityPool(
                    price=level, type="BSL", count=count,
                    swept=current_price > level,
                ))

    # SSL — equal lows (sell-side liquidity below)
    if swing_lows:
        low_prices = [sl.price for sl in swing_lows[-20:]]
        clusters = _cluster_levels(low_prices, tolerance)
        for level, count in clusters:
            if count >= 2 and level < current_price:
                pools.append(LiquidityPool(
                    price=level, type="SSL", count=count,
                    swept=current_price < level,
                ))

    return pools


def _cluster_levels(prices: list[float], tolerance: float) -> list[tuple[float, int]]:
    """Group nearby price levels into clusters. Returns (avg_price, count) pairs."""
    if not prices:
        return []

    sorted_prices = sorted(prices)
    clusters = []
    current_cluster = [sorted_prices[0]]

    for p in sorted_prices[1:]:
        if p - current_cluster[-1] <= tolerance:
            current_cluster.append(p)
        else:
            clusters.append((sum(current_cluster) / len(current_cluster), len(current_cluster)))
            current_cluster = [p]

    clusters.append((sum(current_cluster) / len(current_cluster), len(current_cluster)))
    return clusters


# ─── Master Compute Function ────────────────────────────────

def compute_indicators(h4_candles: list[dict], h1_candles: list[dict],
                       m15_candles: list[dict], m5_candles: list[dict]) -> IndicatorResult:
    """
    Compute all indicators across all timeframes.
    Returns a complete IndicatorResult.
    """
    result = IndicatorResult()

    # ATR
    result.atr_h1 = compute_atr(h1_candles)
    result.atr_h4 = compute_atr(h4_candles)

    # Swings
    result.swing_highs_h4, result.swing_lows_h4 = detect_swings(h4_candles)
    result.swing_highs_h1, result.swing_lows_h1 = detect_swings(h1_candles)
    result.swing_highs_m15, result.swing_lows_m15 = detect_swings(m15_candles)

    # FVGs
    result.fvgs_h1 = detect_fvgs(h1_candles)
    result.fvgs_m15 = detect_fvgs(m15_candles)

    # Order Blocks
    result.obs_h1 = detect_order_blocks(h1_candles)
    result.obs_m15 = detect_order_blocks(m15_candles)
    result.obs_m5 = detect_order_blocks(m5_candles)

    # BOS / CHoCH on H1
    result.bos_h1, result.choch_h1 = detect_bos_choch(
        h1_candles, result.swing_highs_h1, result.swing_lows_h1
    )

    # Liquidity Pools
    current_price = h1_candles[-1]["close"] if h1_candles else 0
    result.liquidity_pools = detect_liquidity_pools(
        result.swing_highs_h1, result.swing_lows_h1, current_price
    )

    return result

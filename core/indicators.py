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
    size: float = 0.0
    distance: float = 0.0
    filled: bool = False
    
    def to_dict(self):
        return vars(self)


@dataclass
class OrderBlock:
    """Order Block — last opposite candle before impulse."""
    high: float
    low: float
    direction: str       # "bullish" (demand) or "bearish" (supply)
    index: int
    timestamp: float
    mitigated: bool = False
    status: str = ""        # "Inside", "Approaching", or ""
    
    def to_dict(self):
        return vars(self)


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
    fvgs_m5: list = field(default_factory=list)
    obs_h4: list = field(default_factory=list)
    obs_h1: list = field(default_factory=list)
    obs_m15: list = field(default_factory=list)
    obs_m5: list = field(default_factory=list)
    bos_h1: list = field(default_factory=list)
    choch_h1: list = field(default_factory=list)
    bos_m15: list = field(default_factory=list)
    choch_m15: list = field(default_factory=list)
    bos_m5: list = field(default_factory=list)
    choch_m5: list = field(default_factory=list)
    liquidity_pools: list = field(default_factory=list)
    bsl_swept: bool = False
    ssl_swept: bool = False
    m15_candles: list = field(default_factory=list)
    m5_candles: list = field(default_factory=list)
    # Market Regime Indicators (v5.0)
    adx: float = 0.0
    dmp: float = 0.0
    dmn: float = 0.0
    ema_20: float = 0.0
    ema_50: float = 0.0
    candle_body_ratio: float = 0.0

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
            "fvgs_m5": _serialize(self.fvgs_m5),
            "obs_h4": _serialize(self.obs_h4),
            "obs_h1": _serialize(self.obs_h1),
            "obs_m15": _serialize(self.obs_m15),
            "obs_m5": _serialize(self.obs_m5),
            "bos_h1": _serialize(self.bos_h1),
            "choch_h1": _serialize(self.choch_h1),
            "bos_m15": _serialize(self.bos_m15),
            "choch_m15": _serialize(self.choch_m15),
            "bos_m5": _serialize(self.bos_m5),
            "choch_m5": _serialize(self.choch_m5),
            "liquidity_pools": _serialize(self.liquidity_pools),
            "bsl_swept": self.bsl_swept,
            "ssl_swept": self.ssl_swept,
            "status": "✅" if (self.bsl_swept or self.ssl_swept) else "❌",
            "detail": "Recent sweep" if (self.bsl_swept or self.ssl_swept) else "No recent sweep",
            # User Fix: Explicit targets for UI
            "bsl": next((p.price for p in self.liquidity_pools if p.type == "BSL" and not p.swept), 0),
            "ssl": next((p.price for p in self.liquidity_pools if p.type == "SSL" and not p.swept), 0),
            "fvg": vars(self.fvgs_h1[-1]) if self.fvgs_h1 else None,
            "ob": vars(self.obs_m15[-1]) if self.obs_m15 else None,
            "adx": round(self.adx, 1),
            "ema_20": round(self.ema_20, 2),
            "ema_50": round(self.ema_50, 2),
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


# ─── EMA (Exponential Moving Average) ───────────────────────

def compute_ema(candles: list[dict], period: int) -> float:
    """
    Exponential Moving Average.
    EMA = (Close - EMA_prev) * multiplier + EMA_prev
    """
    if len(candles) < period:
        return candles[-1]["close"] if candles else 0.0
    
    multiplier = 2.0 / (period + 1)
    
    # Initialize with SMA for the first 'period' candles
    ema = sum(c["close"] for c in candles[:period]) / period
    
    # Iterate through the rest
    for i in range(period, len(candles)):
        ema = (candles[i]["close"] - ema) * multiplier + ema
        
    return ema


def _wilder_smooth(data: list, length: int) -> list:
    """Welles Wilder's smoothing used by ATR and ADX calculations."""
    if not data:
        return []
    smoothed = [sum(data[:length])]
    for i in range(length, len(data)):
        smoothed.append(smoothed[-1] - (smoothed[-1] / length) + data[i])
    return smoothed


# ─── ADX (Average Directional Index) ────────────────────────

def compute_adx(candles: list[dict], period: int = 14) -> tuple[float, float, float]:
    """
    Directional Movement Index (ADX, +DI, -DI).
    Returns (ADX, DMP, DMN).
    """
    if len(candles) < period * 2:
        return 0.0, 0.0, 0.0

    trs = []
    dmps = []
    dmns = []

    for i in range(1, len(candles)):
        c = candles[i]
        p = candles[i-1]
        
        # True Range
        tr = max(c["high"] - c["low"], 
                 abs(c["high"] - p["close"]), 
                 abs(c["low"] - p["close"]))
        trs.append(tr)
        
        # Directional Movement
        up_move = c["high"] - p["high"]
        down_move = p["low"] - c["low"]
        
        if up_move > down_move and up_move > 0:
            dmps.append(up_move)
            dmns.append(0)
        elif down_move > up_move and down_move > 0:
            dmps.append(0)
            dmns.append(down_move)
        else:
            dmps.append(0)
            dmns.append(0)

    smooth_tr  = _wilder_smooth(trs,  period)
    smooth_dmp = _wilder_smooth(dmps, period)
    smooth_dmn = _wilder_smooth(dmns, period)

    if len(smooth_tr) < period: return 0.0, 0.0, 0.0

    # Calculate DI and DX; only last values of DI are needed for the return
    dxs = []
    last_di_bull = 0.0
    last_di_bear = 0.0

    for i in range(len(smooth_tr)):
        di_bull = 100 * (smooth_dmp[i] / smooth_tr[i]) if smooth_tr[i] != 0 else 0.0
        di_bear = 100 * (smooth_dmn[i] / smooth_tr[i]) if smooth_tr[i] != 0 else 0.0
        sum_di  = di_bull + di_bear
        dx = 100 * (abs(di_bull - di_bear) / sum_di) if sum_di != 0 else 0.0
        dxs.append(dx)
        last_di_bull = di_bull
        last_di_bear = di_bear

    # ADX is SMA of last `period` DX values
    recent_dxs = dxs[-period:]
    adx = sum(recent_dxs) / len(recent_dxs) if recent_dxs else 0.0

    return adx, last_di_bull, last_di_bear


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

    min_fvg = config.SCALP_RISK.get("fvg_min_size", 1.0)
    current_price = candles[-1]["close"]

    for i in range(1, len(candles) - 1):
        prev = candles[i - 1]
        curr = candles[i]
        next_c = candles[i + 1]

        # Bullish FVG
        if prev["high"] < next_c["low"]:
            gap_size = next_c["low"] - prev["high"]
            if gap_size >= min_fvg:
                fvgs.append(FVG(
                    high=next_c["low"],
                    low=prev["high"],
                    direction="bullish",
                    index=i,
                    timestamp=curr.get("timestamp", 0),
                    size=round(gap_size, 2),
                    distance=round(abs(prev["high"] - current_price), 2)
                ))

        # Bearish FVG
        if prev["low"] > next_c["high"]:
            gap_size = prev["low"] - next_c["high"]
            if gap_size >= min_fvg:
                fvgs.append(FVG(
                    high=prev["low"],
                    low=next_c["high"],
                    direction="bearish",
                    index=i,
                    timestamp=curr.get("timestamp", 0),
                    size=round(gap_size, 2),
                    distance=round(abs(next_c["high"] - current_price), 2)
                ))

    return fvgs


# ─── Order Blocks ────────────────────────────────────────────

def detect_order_blocks(candles: list[dict], timeframe: str = "H1", min_impulse_multiple: float = 1.3, lookahead: int = 3) -> list[OrderBlock]:
    """
    Identifies Order Blocks (Supply/Demand zones).
    An OB is the last opposite candle before a strong displacement move.
    
    Now uses a multi-candle lookahead to capture aggregate displacement,
    even if it doesn't happen in a single massive bar.
    """
    obs = []
    if len(candles) < lookahead + 2:
        return obs

    current_price = candles[-1]["close"]

    for i in range(1, len(candles) - lookahead):
        curr = candles[i]

        # Local rolling 10-bar average body size for impulse threshold
        local_avg = sum(abs(candles[j]["close"] - candles[j]["open"]) for j in range(max(0, i-10), i)) / 10 if i >= 10 else 5.0
        if local_avg == 0:
            local_avg = 5.0

        # OB Width Filter: M15 OBs should not be wider than $15
        if timeframe == "M15" and abs(curr["high"] - curr["low"]) > 15.0:
            continue

        # Bullish OB (Demand): curr is bearish, followed by strong bullish displacement
        if curr["close"] < curr["open"]:
            agg_move = 0.0
            for k in range(1, lookahead + 1):
                agg_move += candles[i + k]["close"] - candles[i + k]["open"]
                if agg_move >= local_avg * min_impulse_multiple:
                    obs.append(OrderBlock(
                        high=curr["high"], low=curr["low"],
                        direction="bullish", index=i,
                        timestamp=curr.get("timestamp", 0),
                    ))
                    break

        # Bearish OB (Supply): curr is bullish, followed by strong bearish displacement
        elif curr["close"] > curr["open"]:
            agg_move = 0.0
            for k in range(1, lookahead + 1):
                agg_move += candles[i + k]["open"] - candles[i + k]["close"]
                if agg_move >= local_avg * min_impulse_multiple:
                    obs.append(OrderBlock(
                        high=curr["high"], low=curr["low"],
                        direction="bearish", index=i,
                        timestamp=curr.get("timestamp", 0),
                    ))
                    break

    # Mitigation Check: Only return blocks that haven't been traded through
    valid_obs = []
    for ob in obs:
        is_mitigated = False
        # Check all candles from impulse (ob.index+1) till present
        for j in range(ob.index + 1, len(candles)):
            if ob.direction == "bullish":
                if candles[j]["low"] < ob.low:
                    is_mitigated = True
                    break
            else: # bearish
                if candles[j]["high"] > ob.high:
                    is_mitigated = True
                    break
        
        if not is_mitigated:
            # Set status for UI (Inside/Approaching)
            current_price = candles[-1]["close"]
            if ob.low <= current_price <= ob.high:
                ob.status = "INSIDE"
            elif abs(ob.low - current_price) <= 15 or abs(ob.high - current_price) <= 15:
                # User Fix: Proximity status
                ob.status = "APPROACHING"
            else:
                ob.status = ""
            valid_obs.append(ob)

    return valid_obs


# ─── BOS / CHoCH Detection ──────────────────────────────────

def detect_bos_choch(candles: list[dict], swing_highs: list[SwingPoint],
                      swing_lows: list[SwingPoint]) -> tuple[list[BOS], list[BOS]]:
    """
    Break of Structure (BOS) — swing breach in trend direction.
    Change of Character (CHoCH) — swing breach against current trend.
    
    Scans the last N candles for breaks against swing levels,
    not just the current bar.
    
    Returns (bos_list, choch_list).
    """
    bos_list = []
    choch_list = []

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return bos_list, choch_list

    if not candles:
        return bos_list, choch_list

    # Determine current trend from swing sequence
    last_two_highs = swing_highs[-2:]
    last_two_lows = swing_lows[-2:]

    trend_up = (last_two_highs[1].price > last_two_highs[0].price and
                last_two_lows[1].price > last_two_lows[0].price)
    trend_down = (last_two_highs[1].price < last_two_highs[0].price and
                  last_two_lows[1].price < last_two_lows[0].price)

    last_high = swing_highs[-1]
    last_low = swing_lows[-1]

    # Scan last 15 candles for structure breaks (not just current bar)
    scan_range = candles[-15:] if len(candles) >= 15 else candles
    
    bullish_found = False
    bearish_found = False
    
    for candle in scan_range:
        # Bullish break: candle high breaks above last swing high
        if not bullish_found and candle["high"] > last_high.price:
            direction_label = "bullish"
            if trend_up:
                bos_list.append(BOS(
                    price=last_high.price, direction=direction_label,
                    index=len(candles) - 1,
                    timestamp=candle.get("timestamp", 0),
                ))
            elif trend_down:
                choch_list.append(BOS(
                    price=last_high.price, direction=direction_label,
                    index=len(candles) - 1,
                    timestamp=candle.get("timestamp", 0),
                ))
            bullish_found = True

        # Bearish break: candle low breaks below last swing low
        if not bearish_found and candle["low"] < last_low.price:
            direction_label = "bearish"
            if trend_down:
                bos_list.append(BOS(
                    price=last_low.price, direction=direction_label,
                    index=len(candles) - 1,
                    timestamp=candle.get("timestamp", 0),
                ))
            elif trend_up:
                choch_list.append(BOS(
                    price=last_low.price, direction=direction_label,
                    index=len(candles) - 1,
                    timestamp=candle.get("timestamp", 0),
                ))
            bearish_found = True
        
        if bullish_found and bearish_found:
            break

    return bos_list, choch_list


# ─── Liquidity Pools ────────────────────────────────────────

def detect_liquidity_pools(swing_highs: list[SwingPoint], swing_lows: list[SwingPoint],
                            current_price: float, candles: list[dict] = None,
                            tolerance: float = None) -> list[LiquidityPool]:
    """
    Equal highs/lows clusters — liquidity targets.
    Sweep detection: checks if recent candles actually pierced the pool level.
    tolerance: dollar range (auto-calculated as 0.02% of price if None).
    """
    if tolerance is None:
        tolerance = current_price * 0.0002  # ~$0.5-0.9 for gold
        
    pools = []
    # Use last 20 candles to check for sweeps
    recent_candles = candles[-20:] if candles and len(candles) >= 20 else (candles or [])
    recent_highs = [c["high"] for c in recent_candles] if recent_candles else []
    recent_lows = [c["low"] for c in recent_candles] if recent_candles else []
    max_recent_high = max(recent_highs) if recent_highs else current_price
    min_recent_low = min(recent_lows) if recent_lows else current_price

    range_high = float('inf')
    range_low = 0.0
    if swing_highs and swing_lows:
        # User Fix: Align with dealing_range calculation to ensure consistency
        # Use last 40 H4 candle index window
        MAX_LOOKBACK = 40
        last_idx = swing_highs[-1].index
        recent_sh = [s for s in swing_highs if last_idx - s.index <= MAX_LOOKBACK]
        recent_sl = [s for s in swing_lows if last_idx - s.index <= MAX_LOOKBACK]
        if recent_sh and recent_sl:
            range_high = max(s.price for s in recent_sh)
            range_low = min(s.price for s in recent_sl)

    # BSL — buy-side liquidity above price
    if swing_highs:
        # User Fix: Filter highs ABOVE current price AND WITHIN range_high
        high_prices = [sh.price for sh in swing_highs[-100:] 
                       if current_price + (tolerance or 0) < sh.price <= range_high]
        # User Fix: Prioritize nearest levels and limit distance
        clusters = _cluster_levels(high_prices, tolerance)
        clusters.sort(key=lambda x: abs(x[0] - current_price))
        
        for level, count in clusters:
            if count >= 1: # Relaxed: Single swing points are valid liquidity targets
                # Sticky Sweep: any of the last 15 candles broke then closed inside
                swept = False
                for c in recent_candles[-15:]:
                    if c["high"] > level and c["close"] < level:
                        swept = True
                        break
                pools.append(LiquidityPool(level, "BSL", count=count, swept=swept))

    # SSL — sell-side liquidity below price
    if swing_lows:
        # User Fix: Filter ALL lows BELOW current price AND WITHIN range_low
        low_prices = [sl.price for sl in swing_lows 
                      if range_low <= sl.price < current_price - (tolerance or 0)]
        clusters = _cluster_levels(low_prices, tolerance)
        # Sort by distance to current price and limit
        clusters.sort(key=lambda x: abs(x[0] - current_price))
        
        for level, count in clusters:
            if count >= 1: # Relaxed: Single swing points are valid liquidity targets
                # Sticky Sweep: any of the last 15 candles broke then closed inside
                swept = False
                for c in recent_candles[-15:]:
                    if c["low"] < level and c["close"] > level:
                        swept = True
                        break
                pools.append(LiquidityPool(level, "SSL", count=count, swept=swept))

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

    # ─── Core Indicators (Legacy Support) ───────────────────
    result.atr_h1 = compute_atr(h1_candles)
    result.atr_h4 = compute_atr(h4_candles)

    # Swings
    result.swing_highs_h4, result.swing_lows_h4 = detect_swings(h4_candles)
    result.swing_highs_h1, result.swing_lows_h1 = detect_swings(h1_candles)
    result.swing_highs_m15, result.swing_lows_m15 = detect_swings(m15_candles)

    # FVGs
    result.fvgs_h1 = detect_fvgs(h1_candles)
    result.fvgs_m15 = detect_fvgs(m15_candles)
    result.fvgs_m5 = detect_fvgs(m5_candles)

    # Order Blocks
    result.obs_h4 = detect_order_blocks(h4_candles, "H4")
    result.obs_h1 = detect_order_blocks(h1_candles, "H1")
    result.obs_m15 = detect_order_blocks(m15_candles, "M15")
    result.obs_m5 = detect_order_blocks(m5_candles, "M5")

    # BOS / CHoCH on H1
    result.bos_h1, result.choch_h1 = detect_bos_choch(
        h1_candles, result.swing_highs_h1, result.swing_lows_h1
    )

    # BOS / CHoCH on M15
    result.bos_m15, result.choch_m15 = detect_bos_choch(
        m15_candles, result.swing_highs_m15, result.swing_lows_m15
    )

    # BOS / CHoCH on M5 (For Scalp Triggers)
    result.m5_candles = m5_candles      # needed by confluence Gate 1 + Gate 3B freshness check
    swing_highs_m5, swing_lows_m5 = detect_swings(m5_candles)
    result.bos_m5, result.choch_m5 = detect_bos_choch(
        m5_candles, swing_highs_m5, swing_lows_m5
    )

    # Liquidity Pools
    current_price = m15_candles[-1]["close"] if m15_candles else 0
    result.liquidity_pools = detect_liquidity_pools(
        result.swing_highs_h1, result.swing_lows_h1, current_price, m15_candles
    )

    # ─── Market Regime Indicator Calculations (v5.0) ─────────
    
    # ADX on H1 (Primary Regime Gauge)
    result.adx, result.dmp, result.dmn = compute_adx(h1_candles)
    
    # Dual EMA on H1 (Trend Filter)
    result.ema_20 = compute_ema(h1_candles, 20)
    result.ema_50 = compute_ema(h1_candles, 50)
    
    # Momentum Ratio for last M15 Candle (Entry filter)
    if m15_candles:
        last = m15_candles[-1]
        c_range = last["high"] - last["low"]
        c_body = abs(last["close"] - last["open"])
        result.candle_body_ratio = c_body / c_range if c_range > 0 else 0.0

    return result

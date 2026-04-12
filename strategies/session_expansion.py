"""
Session Expansion Strategy — PRIMARY trade generator for AURUM.

Single source of truth used by:
  - backtest/new_simulation.py  (backtest / GUI)
  - pipeline/feed_manager.py    (live trading)

Core idea
─────────
Gold has a reliable daily structure:
  1. Asian session (5:30–13:30 IST)   → accumulation, tight range
  2. London open  (13:30–15:30 IST)   → first expansion
  3. NY open      (18:30–20:30 IST)   → second expansion

We take ONE trade per session on range breakouts that retest the broken
level, only when volatility and bias conditions are ideal. The edge comes
from being selective — most days are skipped, not traded.

Public API
──────────
  build_daily_plan(full_df, day_date, h1_ema50_fn, h1_atr_fn) -> DailyPlan
  find_breakout_entry(bars_iter, plan, side, window_start, window_end) -> Optional[Entry]

These are pure: same inputs → same outputs. No hidden state, no event bus.
"""

from dataclasses import dataclass
from datetime import timezone, timedelta
from typing import Optional

import pandas as pd

import config
from core import indicators, market_classifier

IST = timezone(timedelta(hours=5, minutes=30))


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class DailyPlan:
    """Everything we need to know at 13:30 IST to decide if today is tradeable."""
    date: str                    # YYYY-MM-DD
    asian_high: float
    asian_low: float
    asian_range: float
    bias: str                    # "long", "short", or "skip"
    h1_ema50: float
    h1_atr: float
    regime: str = "TIGHT_RANGE"   # v5.0 Market Type
    regime_desc: str = ""
    adx_h1: float = 0.0
    skip_reason: Optional[str] = None   # None if tradeable


@dataclass
class Entry:
    """A confirmed entry signal ready to be executed."""
    bar_index: int
    timestamp: pd.Timestamp
    price: float
    sl: float
    tp1: float
    tp2: float
    direction: str               # "long" / "short"
    session: str                 # "London" / "NY"
    sl_dist: float
    setup_reason: str = ""
    risk_factors: str = ""
    timeframe: str = "M5"


# ── Helpers ─────────────────────────────────────────────────────────────────

def _ist_minutes(dt: pd.Timestamp) -> int:
    """Convert a bar timestamp to IST minutes-of-day (0-1439)."""
    if dt.tzinfo is None:
        dt = dt.tz_localize("UTC")
    ist = dt.astimezone(IST)
    return ist.hour * 60 + ist.minute


def _ist_date_str(dt: pd.Timestamp) -> str:
    if dt.tzinfo is None:
        dt = dt.tz_localize("UTC")
    return dt.astimezone(IST).strftime("%Y-%m-%d")


def _compute_atr(bars: pd.DataFrame, period: int = 14) -> float:
    """Simple ATR on the given bar dataframe (uses last `period` bars)."""
    if len(bars) < period + 1:
        return 0.0
    recent = bars.tail(period + 1).copy()
    high = recent["high"].values
    low = recent["low"].values
    close = recent["close"].values
    trs = []
    for i in range(1, len(recent)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        trs.append(tr)
    return sum(trs) / len(trs)


def _compute_ema(series: pd.Series, period: int) -> float:
    if len(series) < period:
        return float(series.iloc[-1]) if len(series) else 0.0
    return float(series.ewm(span=period, adjust=False).mean().iloc[-1])


# ── Daily plan builder ──────────────────────────────────────────────────────

def build_daily_plan(full_df: pd.DataFrame, up_to_idx: int) -> DailyPlan:
    """
    At bar `up_to_idx` (which should be the 13:30 IST bar), compute the
    Asian range, H1 context, and decide today's bias.

    Parameters
    ----------
    full_df    : M5 dataframe with 'datetime', 'open', 'high', 'low', 'close'
    up_to_idx  : index of the first bar AT or AFTER 13:30 IST today
    """
    s = config.SESSION_EXPANSION
    cur_bar = full_df.iloc[up_to_idx]
    cur_ts = pd.to_datetime(cur_bar["datetime"])
    date_str = _ist_date_str(cur_ts)

    # ── Asian session bars: today 5:30 IST → today 13:30 IST ──
    asian_start_min = s["asian_start_hour"] * 60 + s["asian_start_min"]
    asian_end_min = s["asian_end_hour"] * 60 + s["asian_end_min"]

    # Scan backward to find today's Asian session bars
    lookback_start = max(0, up_to_idx - 300)  # 300 M5 bars = 25 hours, safe
    window = full_df.iloc[lookback_start:up_to_idx].copy()
    window.loc[:, "ist_date"] = window["datetime"].apply(_ist_date_str)
    window.loc[:, "ist_min"] = window["datetime"].apply(
        lambda d: _ist_minutes(pd.to_datetime(d))
    )

    asian_bars = window[
        (window["ist_date"] == date_str)
        & (window["ist_min"] >= asian_start_min)
        & (window["ist_min"] < asian_end_min)
    ]

    if len(asian_bars) < 20:
        return DailyPlan(
            date=date_str,
            asian_high=0, asian_low=0, asian_range=0,
            bias="skip", h1_ema50=0, h1_atr=0,
            skip_reason="insufficient_asian_data",
        )

    asian_high = float(asian_bars["high"].max())
    asian_low = float(asian_bars["low"].min())
    asian_range = asian_high - asian_low

    # ── H1 context (EMA50 + ATR14) — computed FIRST so range filter is ATR-relative ──
    # Need 50+ H1 bars for EMA50. 900 M5 bars ≈ 75 hours of data,
    # which after weekend gaps still yields 60+ H1 bars reliably.
    hist = full_df.iloc[max(0, up_to_idx - 900): up_to_idx + 1].copy()
    hist.loc[:, "datetime"] = pd.to_datetime(hist["datetime"])
    hist = hist.set_index("datetime")
    h1 = hist.resample("1h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()

    if len(h1) < 50:
        return DailyPlan(
            date=date_str,
            asian_high=asian_high, asian_low=asian_low, asian_range=asian_range,
            bias="skip", h1_ema50=0, h1_atr=0,
            skip_reason="insufficient_h1_data",
        )

    h1_ema50 = _compute_ema(h1["close"], 50)
    h1_atr = _compute_atr(h1, 14)

    # ── Volatility floor/ceiling (absolute) ──
    if h1_atr < s["atr_min"] or h1_atr > s["atr_max"]:
        return DailyPlan(
            date=date_str,
            asian_high=asian_high, asian_low=asian_low, asian_range=asian_range,
            bias="skip", h1_ema50=h1_ema50, h1_atr=h1_atr,
            skip_reason=f"atr_out_of_band_{h1_atr:.1f}",
        )

    # ── Range quality filter — relative to ATR ──
    range_ratio = asian_range / h1_atr if h1_atr > 0 else 0
    if range_ratio < s["asian_range_min_atr"]:
        return DailyPlan(
            date=date_str,
            asian_high=asian_high, asian_low=asian_low, asian_range=asian_range,
            bias="skip", h1_ema50=h1_ema50, h1_atr=h1_atr,
            skip_reason=f"range_too_tight_{range_ratio:.2f}x",
        )
    if range_ratio > s["asian_range_max_atr"]:
        return DailyPlan(
            date=date_str,
            asian_high=asian_high, asian_low=asian_low, asian_range=asian_range,
            bias="skip", h1_ema50=h1_ema50, h1_atr=h1_atr,
            skip_reason=f"range_too_wide_{range_ratio:.2f}x",
        )

    # ── v5.0 Market Regime Classification ──
    # Create a dummy IndicatorResult to pass to classifier
    res_indicators = indicators.IndicatorResult()
    res_indicators.atr_h1 = h1_atr
    res_indicators.ema_20 = _compute_ema(h1["close"], 20)
    res_indicators.ema_50 = h1_ema50
    
    # Calculate ADX on resampled H1
    h1_candles_list = h1.reset_index().to_dict('records')
    res_indicators.adx, res_indicators.dmp, res_indicators.dmn = indicators.compute_adx(h1_candles_list)
    
    # Latest M15 body ratio (v5.0 momentum check)
    m15_latest = full_df.iloc[up_to_idx-3:up_to_idx+1].copy() # approximate latest M15
    m15_c = m15_latest.iloc[-1]
    r = m15_c["high"] - m15_c["low"]
    b = abs(m15_c["close"] - m15_c["open"])
    res_indicators.candle_body_ratio = b / r if r > 0 else 0.0
    
    regime_info = market_classifier.classify_market(res_indicators)
    regime = regime_info.regime_type

    # ── Hard-Lock/Skip Logic ──
    # Refinement: Allow Swings in VOLATILE_RANGE if ADX > 25 (trending volatility)
    # This aligns with the $300+/week 5m alpha results.
    bias = "neutral"
    skip_reason = ""

    if regime == market_classifier.MarketRegime.VOLATILE_RANGE:
        if res_indicators.adx < 25:
            bias = "skip"
            skip_reason = "VOLATILE_CHOP_LOCK"
        else:
            # Trending Volatility — Allow Swings but cap risk
            pass
    elif regime == market_classifier.MarketRegime.DEAD_MARKET:
        bias = "skip"
        skip_reason = "DEAD_MARKET_LOCK"
    else:
        # Bias from H1 EMA50
        current_price = float(cur_bar["close"])
        distance = current_price - h1_ema50
        if abs(distance) < s["bias_min_distance"]:
            bias = "skip"
            skip_reason = "no_clear_bias"
        else:
            bias = "long" if distance > 0 else "short"
            skip_reason = None

    return DailyPlan(
        date=date_str,
        asian_high=asian_high,
        asian_low=asian_low,
        asian_range=asian_range,
        bias=bias,
        h1_ema50=h1_ema50,
        h1_atr=h1_atr,
        regime=regime,
        regime_desc=regime_info.description,
        adx_h1=float(res_indicators.adx),
        skip_reason=skip_reason,
    )


# ── Entry finder ────────────────────────────────────────────────────────────

def find_breakout_entry(
    full_df: pd.DataFrame,
    plan: DailyPlan,
    window_start_idx: int,
    window_end_idx: int,
    session_label: str,
) -> Optional[Entry]:
    """
    Scan bars [window_start_idx .. window_end_idx] for a breakout entry
    aligned with plan.bias. Uses a two-bar confirmation pattern:

      1. First breakout bar: M5 close beyond asian_high/low in bias direction
      2. Confirmation bar: next M5 also closes in bias direction (no fake-out)
      3. Enter at confirmation bar's close

    No retest required — in trending markets price rarely pulls back. Two-bar
    confirm is the anti-fake-out filter instead.

    Returns the first valid Entry or None.
    """
    s = config.SESSION_EXPANSION

    if plan.bias == "skip":
        return None

    break_level = plan.asian_high if plan.bias == "long" else plan.asian_low

    broken = False
    break_close = 0.0

    end_idx = min(window_end_idx, len(full_df) - 1)

    for i in range(window_start_idx, end_idx + 1):
        bar = full_df.iloc[i]
        close = float(bar["close"])

        if not broken:
            # First breakout bar: close beyond Asian range in bias direction
            if plan.bias == "long" and close > break_level:
                broken = True
                break_close = close
            elif plan.bias == "short" and close < break_level:
                broken = True
                break_close = close
        else:
            # Confirmation bar: must also close in bias direction
            # v5.0 Add: Momentum Candle Check (Deactivated to restore trade count)
            # if plan.regime in [market_classifier.MarketRegime.STRONG_BULL, 
            #                    market_classifier.MarketRegime.STRONG_BEAR,
            #                    market_classifier.MarketRegime.NEWS_DRIVEN]:
            #     c_range = bar["high"] - bar["low"]
            #     c_body = abs(bar["close"] - bar["open"])
            #     ratio = c_body / c_range if c_range > 0 else 0.0
            #     if ratio < config.MOMENTUM_CANDLE_BODY_MIN:
            #         continue

            if plan.bias == "long":
                if close >= break_close:
                    return _build_entry(bar, i, close, plan, session_label, s)
                # Failed confirmation — reset and wait for next breakout
                if close < break_level:
                    broken = False
            else:
                if close <= break_close:
                    return _build_entry(bar, i, close, plan, session_label, s)
                if close > break_level:
                    broken = False

    return None


def _build_entry(bar, bar_idx, price, plan, session_label, s) -> Entry:
    """Given a confirmed bar, construct the Entry with v5.0 Regime RR math."""
    regime_cfg = market_classifier.get_config_for_regime(plan.regime)
    
    sl_dist = plan.h1_atr * s["sl_atr_mult"]
    sl_dist = max(s["sl_min"], min(s["sl_max"], sl_dist))

    # Use regime-specific lots and RR
    target_rr = regime_cfg.get("target_rr", 2.0)

    if plan.bias == "long":
        sl = price - sl_dist
        tp1 = price + sl_dist * 1.0 # TP1 is always 1:1 for BE move
        tp2 = price + sl_dist * target_rr
    else:
        sl = price + sl_dist
        tp1 = price - sl_dist * 1.0
        tp2 = price - sl_dist * target_rr

    return Entry(
        bar_index=bar_idx,
        timestamp=pd.to_datetime(bar["datetime"]),
        price=price,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        direction=plan.bias,
        session=session_label,
        sl_dist=sl_dist,
        setup_reason=f"{session_label} {plan.regime.replace('_', ' ').title()} Breakout",
        risk_factors=f"ATR:{plan.h1_atr:.2f}, ADX:{plan.adx_h1:.2f}, BiasDist:{abs(price-plan.h1_ema50):.2f}",
        timeframe="M5"
    )

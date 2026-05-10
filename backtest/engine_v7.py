"""
Aurum v7 — Multi-engine mechanical trading system for XAUUSD.

Multi-timeframe, regime-aware. Engines fire on M1/M5/M15 closes; H4 trend
bias and H1 ADX/ATR-percentile regime gate every entry. Every trade is
tagged with regime so we can answer "WHEN does this strategy work."

Default engines (post-slippage OOS-validated, ~9 trades/wk):
  DOR — Daily-Open Mean Reversion (high R:R, M1-FVG refinement available)
  ORB — London/NY Opening Range Breakout + Retest (2:1 R:R)
  MR  — M5 stretch mean-reversion, ranging_low_vol regime only (long-only)

Opt-in engines (disabled by default — failed slippage-adjusted OOS test):
  PB  — M5 EMA20 pullback (1.2:1 R:R was too thin to survive 1.5pt slippage)
  AS  — Asian-session breakout (net loss OOS)
  SW  — M15 EMA50 pullback (small sample, marginal)
  ASW — Asian Sweep + Reclaim (replaced by AS in earlier iteration; 9% WR)

To enable:  --engines DOR,ORB,MR,PB

Filters baked in:
  - H4 bar-majority direction
  - H1 regime: 9-cell label (ranging|weak_trend|strong_trend × low|med|high vol)
  - DOR shorts blocked when H4 bullish OR regime.trend == strong_trend
  - DOR / MR / SW shorts disabled (gold's structural bull bias makes them lose)
  - ORB skipped when H1 ADX < 15 (chop)
  - AS Asian range capped at 100pt (post-news days are not breakout days)
  - Same-direction same-engine 2-loss guard (falling-knife protection)

Slippage model (MT5 broker via QTFunded):
  - 1.5pt entry slippage default (override via ENTRY_SLIPPAGE_PT)
  - 1.0pt SL slippage default
  - 0.0pt TP slippage (limit fills)
  Tune from real fill data after 4 weeks live.

Funded-account guardrails:
  - $25 max risk per trade
  - 3 losing trades/day → stop
  - $500 daily loss cap
  - $500 daily profit lock
  - One position at a time (no overlap)
"""

from __future__ import annotations

import argparse
import logging
import math
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

import config
from config import IST
from core.news_blackout import is_news_blackout

logger = logging.getLogger(__name__)

# ─── Config constants ──────────────────────────────────────────────────────

MAX_RISK_PER_TRADE      = 25.0          # USD — QTFunded $10k guardrail
DAILY_LOSS_CAP          = 500.0
DAILY_PROFIT_LOCK       = 500.0
MAX_LOSSES_PER_DAY      = 3
MAX_TRADES_PER_DAY      = 5  # London + NY + intra-session pullbacks (PB engine)
COMMISSION_PER_001_LOT  = 0.07          # OANDA spread/commission per 0.01 lot per side

# ── Slippage model (MT5 broker via QTFunded) ───────────────────────────────
# Defaults assume typical XAUUSD spread + market-order slippage on a competitive
# MT5 broker. Tune from real signal-vs-fill data after 4 weeks live.
ENTRY_SLIPPAGE_PT       = 1.5           # market-order entry: spread + latency slippage
SL_SLIPPAGE_PT          = 1.0           # stop-order exits: gap-through penalty
TP_SLIPPAGE_PT          = 0.0           # limit-order TPs: fill at price-or-better

# Session windows (IST) — sourced from config.KILLZONES
NY_START    = config.KILLZONES["ny_open"]["start"]
NY_END      = config.KILLZONES["ny_extended"]["end"]

# ─── Data types ────────────────────────────────────────────────────────────

@dataclass
class V7Trade:
    engine:       str                      # "DOR" | "ORB"
    entry_time:   pd.Timestamp
    direction:    str                      # "long" | "short"
    entry_price:  float
    sl:           float
    tp:           float
    lots:         float
    risk_usd:     float
    partial_hit:  bool = False             # 1R partial closed → SL moved to BE
    exit_time:    Optional[pd.Timestamp] = None
    exit_price:   Optional[float] = None
    result:       str = "open"             # "win" | "be" | "loss"
    pnl:          float = 0.0
    realized:     float = 0.0
    reason:       str = ""
    regime:       str = "unknown"          # H1 regime label (e.g. "ranging_low_vol")
    tf:           str = "M5"               # entry timeframe ("M1" for FVG-refined, "M15" for SW)


@dataclass
class DailyState:
    date:    str
    pnl:     float = 0.0
    losses:  int   = 0
    trades:  int   = 0
    locked:  bool  = False
    # Per (engine, direction) loss counter — after 2 same-side losses, that direction
    # is cooled for the rest of the day on that engine (falling-knife guard).
    side_losses: dict = field(default_factory=dict)


# ─── Helpers ───────────────────────────────────────────────────────────────

def _size_lots(sl_dist_pt: float, risk_usd: float = MAX_RISK_PER_TRADE) -> float:
    """Lots = risk / (sl_distance_pts × $100-per-pt-per-1-lot)."""
    if sl_dist_pt <= 0:
        return 0.01
    raw = risk_usd / (sl_dist_pt * 100.0)
    lots = math.floor(raw * 100) / 100      # floor to 0.01 step — never over-risk
    return max(lots, 0.01)


def _date_ist(ts: pd.Timestamp) -> str:
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(IST).strftime("%Y-%m-%d")


# ─── Load data ─────────────────────────────────────────────────────────────

def _load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["datetime"] = pd.to_datetime(df["datetime"])
    if df["datetime"].dt.tz is None:
        df["datetime"] = df["datetime"].dt.tz_localize("UTC")
    df = df[df["datetime"].dt.dayofweek < 5]       # weekdays only
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


def _enrich_ist(m5: pd.DataFrame) -> pd.DataFrame:
    """Attach ist / date_ist / minute_ist columns. Called once per run."""
    m5 = m5.copy()
    m5["ist"] = m5["datetime"].dt.tz_convert(IST)
    m5["date_ist"] = m5["ist"].dt.strftime("%Y-%m-%d")
    m5["minute_ist"] = m5["ist"].dt.hour * 60 + m5["ist"].dt.minute
    return m5


# ─── DOR: Daily-Open Mean Reversion ────────────────────────────────────────

def _daily_opens(m5: pd.DataFrame) -> dict[str, float]:
    """{date_ist: 00:00 UTC open price} — the 00:00 UTC tick == 05:30 IST."""
    ref = m5[(m5["datetime"].dt.hour == 0) & (m5["datetime"].dt.minute == 0)]
    opens = dict(zip(ref["date_ist"], ref["open"].astype(float)))
    missing = set(m5["date_ist"].unique()) - opens.keys()
    if missing:
        logger.info("DOR: no 00:00 UTC bar for %d dates — skipped", len(missing))
    return opens


def _load_m1(data_dir) -> pd.DataFrame | None:
    """Load M1 CSV if available; return None if missing."""
    path = str(data_dir / "XAUUSD_1min.csv")
    try:
        m1 = _load_csv(path)
        if m1.empty:
            return None
        m1["ist"] = m1["datetime"].dt.tz_convert(IST)
        m1["date_ist"] = m1["ist"].dt.strftime("%Y-%m-%d")
        m1["minute_ist"] = m1["ist"].dt.hour * 60 + m1["ist"].dt.minute
        return m1
    except Exception:
        return None


def _fvg_entry(m1: pd.DataFrame, t0: pd.Timestamp, is_short: bool,
               do: float) -> dict | None:
    """
    Look for a M1 Fair Value Gap within 10 min after t0 in the signal direction.
    Returns a setup dict with tighter SL if found, else None.
    """
    t1 = t0 + pd.Timedelta(minutes=10)
    window = m1[(m1["datetime"] > t0) & (m1["datetime"] <= t1)].reset_index(drop=True)
    if len(window) < 3:
        return None
    for j in range(1, len(window) - 1):
        pb = window.iloc[j - 1]
        nb = window.iloc[j + 1]
        if is_short:
            if float(pb["low"]) <= float(nb["high"]):
                continue
            fvg_hi = float(pb["low"])
            entry  = float(nb["close"])
            if entry > fvg_hi:
                continue
            sl      = fvg_hi + 1.5
            sl_dist = sl - entry
            if sl_dist < 4.0 or sl_dist > 20.0:
                continue
            tp = do + 5.0
            if tp >= entry:
                continue
            return {"entry_time": nb["datetime"], "direction": "short",
                    "entry": entry, "sl": sl, "tp": tp}
        else:
            if float(pb["high"]) >= float(nb["low"]):
                continue
            fvg_lo = float(pb["high"])
            entry  = float(nb["close"])
            if entry < fvg_lo:
                continue
            sl      = fvg_lo - 1.5
            sl_dist = entry - sl
            if sl_dist < 4.0 or sl_dist > 20.0:
                continue
            tp = do - 5.0
            if tp <= entry:
                continue
            return {"entry_time": nb["datetime"], "direction": "long",
                    "entry": entry, "sl": sl, "tp": tp}
    return None


def _h4_trend(h4: pd.DataFrame | None, bar_time: pd.Timestamp) -> str:
    """
    Returns 'bullish', 'bearish', or 'neutral' based on H4 bar structure.
    Uses last 5 completed H4 bars. Majority (≥60%) of closes moving in one
    direction → that bias. Ties → neutral.
    EMA cross was tested and blocked too many winning trades in volatile markets.
    """
    if h4 is None or h4.empty:
        return "neutral"
    prev = h4[h4["datetime"] < bar_time].tail(6)
    if len(prev) < 4:
        return "neutral"
    closes = prev["close"].tolist()
    ups   = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])
    downs = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i - 1])
    total = len(closes) - 1
    if ups >= round(total * 0.6):
        return "bullish"
    if downs >= round(total * 0.6):
        return "bearish"
    return "neutral"


# ─── H1 Regime: ADX (trend strength) × ATR percentile (volatility) ─────────

ADX_PERIOD       = 14
ATR_PERIOD       = 14
ATR_PCT_LOOKBACK = 100      # rolling window for vol percentile
ADX_RANGE_MAX    = 25.0     # below = ranging
ADX_STRONG_MIN   = 40.0     # above = strong trend


def _adx_series(h1: pd.DataFrame | None) -> pd.DataFrame | None:
    """
    Vectorized H1 regime calc: ADX(14) + ATR(14) + ATR percentile (rolling 100).
    Returns h1 with adx, dmp, dmn, atr, atr_pct columns appended.
    """
    if h1 is None or h1.empty or len(h1) < ADX_PERIOD * 2:
        return None
    df = h1.copy().reset_index(drop=True)
    high, low, close = df["high"], df["low"], df["close"]

    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    up_move   = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm   = ((up_move > down_move) & (up_move > 0)).astype(float)   * up_move.clip(lower=0)
    minus_dm  = ((down_move > up_move) & (down_move > 0)).astype(float) * down_move.clip(lower=0)

    import numpy as np
    atr  = tr.ewm(alpha=1 / ADX_PERIOD, adjust=False).mean()
    atr_safe = atr.where(atr != 0, np.nan)
    pdi  = 100 * plus_dm.ewm(alpha=1 / ADX_PERIOD, adjust=False).mean()  / atr_safe
    mdi  = 100 * minus_dm.ewm(alpha=1 / ADX_PERIOD, adjust=False).mean() / atr_safe
    di_sum = (pdi + mdi).where((pdi + mdi) != 0, np.nan)
    dx   = 100 * (pdi - mdi).abs() / di_sum
    df["adx"] = dx.ewm(alpha=1 / ADX_PERIOD, adjust=False).mean().fillna(0.0).astype(float)
    df["dmp"] = pdi.fillna(0.0).astype(float)
    df["dmn"] = mdi.fillna(0.0).astype(float)
    df["atr"] = atr.fillna(0.0).astype(float)

    # ATR percentile rank vs trailing 100 H1 bars (0..1)
    df["atr_pct"] = df["atr"].rolling(ATR_PCT_LOOKBACK, min_periods=20)\
                              .rank(pct=True).fillna(0.5).astype(float)
    return df


def _regime_at(h1_adx: pd.DataFrame | None, bar_time: pd.Timestamp) -> dict:
    """
    Two-axis regime label from last completed H1 bar:
      trend  ∈ {ranging, weak_trend, strong_trend}
      vol    ∈ {low_vol, med_vol, high_vol}
      label  = f"{trend}_{vol}"
    Returns dict with adx, dmp, dmn, atr_pct, trend, vol, label, dir.
    """
    blank = {"adx": 0.0, "dmp": 0.0, "dmn": 0.0, "atr_pct": 0.5,
             "trend": "unknown", "vol": "unknown", "label": "unknown", "dir": "neutral"}
    if h1_adx is None or h1_adx.empty:
        return blank
    prev = h1_adx[h1_adx["datetime"] < bar_time]
    if prev.empty:
        return blank
    last = prev.iloc[-1]
    adx, dmp, dmn, ap = float(last["adx"]), float(last["dmp"]), float(last["dmn"]), float(last["atr_pct"])

    if adx < ADX_RANGE_MAX:
        trend = "ranging"
    elif adx < ADX_STRONG_MIN:
        trend = "weak_trend"
    else:
        trend = "strong_trend"

    if ap < 0.33:
        vol = "low_vol"
    elif ap < 0.67:
        vol = "med_vol"
    else:
        vol = "high_vol"

    direction = "bullish" if dmp > dmn else ("bearish" if dmn > dmp else "neutral")
    return {"adx": adx, "dmp": dmp, "dmn": dmn, "atr_pct": ap,
            "trend": trend, "vol": vol, "label": f"{trend}_{vol}", "dir": direction}


DOR_MIN_DISPLACEMENT = 20.0   # pt — relaxed for higher frequency in tight markets


def _scan_dor(m5: pd.DataFrame, m1: pd.DataFrame | None = None,
              h4: pd.DataFrame | None = None,
              h1_adx: pd.DataFrame | None = None) -> list[dict]:
    """
    DOR (Daily-Open Reversion). Fires London/NY when price is ≥25pt from DO
    and an M5 candle closes back toward it.

    Filters:
      - H4 bar-majority direction
      - H1 regime gate: BLOCK shorts when ADX>25 + bullish DI (don't fade strong trend up)
                        BLOCK longs  when ADX>25 + bearish DI (don't fade strong trend down)
      - ALLOW DOR longs in any non-strong-bearish regime (gold's structural bid)
    """
    setups: list[dict] = []
    dopen = _daily_opens(m5)

    ls_start, ls_end = 15 * 60, 18 * 60
    ny_start, ny_end = NY_START[0] * 60 + NY_START[1], NY_END[0] * 60 + NY_END[1]
    mask = (
        ((m5["minute_ist"] >= ls_start) & (m5["minute_ist"] < ls_end)) |
        ((m5["minute_ist"] >= ny_start) & (m5["minute_ist"] < ny_end))
    )
    active = m5[mask].reset_index(drop=True)

    for i in range(1, len(active)):
        row  = active.iloc[i]
        prev = active.iloc[i - 1]
        do   = dopen.get(row["date_ist"])
        if do is None:
            continue

        displacement = row["close"] - do
        if abs(displacement) < DOR_MIN_DISPLACEMENT:
            continue

        h4_bias = _h4_trend(h4, row["datetime"])
        regime  = _regime_at(h1_adx, row["datetime"])
        rlbl    = regime["label"]

        # Soft regime gate: only block DOR shorts in strong bull (the proven knife-catcher)
        # All other regimes allowed; tag them so post-trade analysis shows edge by regime.

        # Short fade: H4 not bullish + ADX < 40 (don't fade strong trends in either direction)
        # Data: shorts in strong_trend_* regimes lost ~$110 across 5 trades in Jan-Feb run.
        if displacement > 0 and row["close"] < prev["close"] and row["close"] < row["open"] \
                and h4_bias != "bullish" \
                and regime["trend"] != "strong_trend":
            if m1 is not None:
                refined = _fvg_entry(m1, row["datetime"], is_short=True, do=do)
                if refined:
                    setups.append({
                        "engine": "DOR", **refined, "tf": "M1",
                        "displacement": displacement, "daily_open": do, "regime": rlbl,
                        "reason": f"DOR short M1-FVG | +{displacement:.1f}pt | {rlbl}",
                    })
                    continue
            entry = float(row["close"])
            sl    = float(row["high"]) + 2.0
            sl_dist = sl - entry
            if sl_dist < 6.0 or sl_dist > 20.0:
                continue
            tp = do + 5.0
            if tp >= entry:
                continue
            setups.append({
                "engine":       "DOR",
                "entry_time":   row["datetime"],
                "direction":    "short",
                "entry":        entry,
                "sl":           sl,
                "tp":           tp,
                "displacement": displacement,
                "daily_open":   do,
                "regime":       rlbl,
                "reason":       f"DOR short | +{displacement:.1f}pt | {rlbl}",
            })
            continue

        # Long fade: block when strong bear trend is active (don't catch knives)
        if displacement < 0 and row["close"] > prev["close"] and row["close"] > row["open"] \
                and h4_bias != "bearish" \
                and not (regime["trend"] == "strong_trend" and regime["dir"] == "bearish"):
            if m1 is not None:
                refined = _fvg_entry(m1, row["datetime"], is_short=False, do=do)
                if refined:
                    setups.append({
                        "engine": "DOR", **refined, "tf": "M1",
                        "displacement": displacement, "daily_open": do, "regime": rlbl,
                        "reason": f"DOR long M1-FVG | {displacement:.1f}pt | {rlbl}",
                    })
                    continue
            entry = float(row["close"])
            sl    = float(row["low"]) - 2.0
            sl_dist = entry - sl
            if sl_dist < 6.0 or sl_dist > 20.0:
                continue
            tp = do - 5.0
            if tp <= entry:
                continue
            setups.append({
                "engine":       "DOR",
                "entry_time":   row["datetime"],
                "direction":    "long",
                "entry":        entry,
                "sl":           sl,
                "tp":           tp,
                "displacement": displacement,
                "daily_open":   do,
                "regime":       rlbl,
                "reason":       f"DOR long | {displacement:.1f}pt | {rlbl}",
            })
    return setups


# ─── ORB: London Opening Range Breakout + Retest ───────────────────────────

def _scan_orb(m5: pd.DataFrame, _m1: pd.DataFrame | None = None,
              h4: pd.DataFrame | None = None,
              h1_adx: pd.DataFrame | None = None) -> list[dict]:
    """
    Opening Range Breakout + Retest. London + NY windows.

    Filters:
      - H4 bar-majority direction (no longs in bearish H4, no shorts in bullish H4)
      - H1 regime gate: skip when ADX<15 (chop fakeouts both directions)
      - NY-long re-enabled when H1 regime is bullish (ADX>20 + DMP>DMN)
    """
    setups: list[dict] = []
    MIN_RNG    = 5.0
    MAX_RNG    = 40.0
    RETEST_TOL = 3.0
    TP_RR      = 2.0
    CHOP_ADX   = 15.0   # below this = pure chop, skip both directions

    WINDOWS = [
        ("London", 15 * 60, 15 * 60 + 30, 17 * 60 + 30),
        ("NY",     18 * 60 + 30, 19 * 60, 21 * 60),
    ]

    for date in m5["date_ist"].unique():
        day = m5[m5["date_ist"] == date].reset_index(drop=True)

        for session, orb_start, orb_end, retest_cut in WINDOWS:
            orb_bars = day[(day["minute_ist"] >= orb_start) & (day["minute_ist"] < orb_end)]
            if len(orb_bars) < 3:
                continue

            rng_hi   = float(orb_bars["high"].max())
            rng_lo   = float(orb_bars["low"].min())
            rng_size = rng_hi - rng_lo
            if not (MIN_RNG <= rng_size <= MAX_RNG):
                continue

            h4_bias = _h4_trend(h4, orb_bars.iloc[0]["datetime"])
            regime  = _regime_at(h1_adx, orb_bars.iloc[0]["datetime"])
            rlbl    = regime["label"]

            # Skip pure chop (ADX < 15): breakout-retest fakeouts dominate
            if regime["adx"] > 0 and regime["adx"] < CHOP_ADX:
                continue

            sl_dist = float(max(min(rng_size * 0.5, 15.0), 4.0))

            post = day[day["minute_ist"] >= orb_end].reset_index(drop=True)
            if len(post) < 2:
                continue

            # NY-long allowed only when regime bullish (ADX>20 + DMP>DMN)
            ny_long_ok = session != "NY" or (regime["adx"] >= 20 and regime["dir"] == "bullish")

            bo_dir = None
            bo_idx = -1
            for i in range(len(post)):
                bar = post.iloc[i]
                if int(bar["minute_ist"]) > retest_cut:
                    break
                c = float(bar["close"])
                if c > rng_hi + 1.0 and h4_bias != "bearish" and ny_long_ok:
                    bo_dir, bo_idx = "long",  i;  break
                if c < rng_lo - 1.0 and h4_bias != "bullish":
                    bo_dir, bo_idx = "short", i;  break

            if bo_dir is None:
                continue

            for i in range(bo_idx + 1, len(post)):
                rbar = post.iloc[i]
                if int(rbar["minute_ist"]) > retest_cut:
                    break

                if bo_dir == "long" and float(rbar["low"]) <= rng_hi + RETEST_TOL:
                    entry = rng_hi
                    sl    = entry - sl_dist
                    tp    = entry + sl_dist * TP_RR
                    setups.append({
                        "engine":     "ORB",
                        "entry_time": rbar["datetime"],
                        "direction":  "long",
                        "entry":      entry,
                        "sl":         sl,
                        "tp":         tp,
                        "regime":     rlbl,
                        "reason":     f"ORB-{session} long | {rng_size:.1f}pt | {rlbl}",
                    })
                    break

                if bo_dir == "short" and float(rbar["high"]) >= rng_lo - RETEST_TOL:
                    entry = rng_lo
                    sl    = entry + sl_dist
                    tp    = entry - sl_dist * TP_RR
                    setups.append({
                        "engine":     "ORB",
                        "entry_time": rbar["datetime"],
                        "direction":  "short",
                        "entry":      entry,
                        "sl":         sl,
                        "tp":         tp,
                        "regime":     rlbl,
                        "reason":     f"ORB-{session} short | {rng_size:.1f}pt | {rlbl}",
                    })
                    break

    return setups


# ─── MR: Stretch Mean-Reversion (regime-gated, ranging_low_vol only) ───────

def _scan_mr(m5: pd.DataFrame, _m1: pd.DataFrame | None = None,
             _h4: pd.DataFrame | None = None,
             h1_adx: pd.DataFrame | None = None) -> list[dict]:
    """
    Mean-Reversion stretch entry — fires ONLY in `ranging_low_vol` regime
    (51% WR cash-cow regime in current data).

    Logic:
      - During London (15:00-18:00) or NY (18:30-21:30) IST
      - Compute 20-bar M5 EMA + ATR
      - Fire long when low touches >1.5 ATR below EMA AND closes back up (rejection)
      - Fire short when high touches >1.5 ATR above EMA AND closes back down
      - SL: 1.0 ATR beyond bar extreme
      - TP: M5 EMA20 (textbook MR target)
    """
    setups: list[dict] = []
    if h1_adx is None:
        return setups

    df = m5.copy().reset_index(drop=True)
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    tr = pd.concat([
        (df["high"] - df["low"]),
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"]  - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()

    ls_start, ls_end = 15 * 60, 18 * 60
    ny_start, ny_end = NY_START[0] * 60 + NY_START[1], NY_END[0] * 60 + NY_END[1]
    in_session = (
        ((df["minute_ist"] >= ls_start) & (df["minute_ist"] < ls_end)) |
        ((df["minute_ist"] >= ny_start) & (df["minute_ist"] < ny_end))
    )

    for i in range(30, len(df)):
        if not in_session.iloc[i]:
            continue
        row = df.iloc[i]
        regime = _regime_at(h1_adx, row["datetime"])
        if regime["label"] != "ranging_low_vol":
            continue   # only fire in proven 51% WR regime

        ema, atr = float(row["ema20"]), float(row["atr"])
        if atr <= 0:
            continue

        stretch_lo = ema - 1.5 * atr

        TP_RR = 1.5

        # Long: low pierced below ema-1.5atr AND close rejected back above stretch_lo
        if float(row["low"]) <= stretch_lo and float(row["close"]) > stretch_lo \
                and float(row["close"]) > float(row["open"]):
            entry   = float(row["close"])
            sl      = float(row["low"]) - max(atr * 0.5, 2.0)
            sl_dist = entry - sl
            if sl_dist < 4.0 or sl_dist > 15.0:
                continue
            tp = entry + sl_dist * TP_RR
            setups.append({
                "engine": "MR", "entry_time": row["datetime"], "direction": "long",
                "entry": entry, "sl": sl, "tp": tp,
                "regime": regime["label"],
                "reason": f"MR long stretch | EMA20={ema:.1f} ATR={atr:.1f}",
            })
            continue

        # MR shorts disabled: 37.5% WR, -$38 in current bull-market gold.
        # Re-enable only after data confirms edge in a sustained bear regime.

    return setups


# ─── ASW: Asian Sweep + Reclaim at London Open ─────────────────────────────

def _asian_ranges(m5: pd.DataFrame) -> dict:
    """{date_ist: (asian_hi, asian_lo, width)} using 05:30-13:00 IST window."""
    start_min = 5 * 60 + 30
    end_min   = 13 * 60
    window = m5[(m5["minute_ist"] >= start_min) & (m5["minute_ist"] < end_min)]
    grp = window.groupby("date_ist").agg(hi=("high", "max"), lo=("low", "min"))
    out: dict[str, tuple[float, float, float]] = {}
    for date, row in grp.iterrows():
        hi, lo = float(row["hi"]), float(row["lo"])
        out[date] = (hi, lo, hi - lo)
    return out


# ─── PB: M5 EMA Pullback (high-frequency trend continuation) ───────────────

def _scan_pb(m5: pd.DataFrame, _m1: pd.DataFrame | None = None,
             _h4: pd.DataFrame | None = None,
             h1_adx: pd.DataFrame | None = None) -> list[dict]:
    """
    M5 EMA20 pullback continuation. Fires whenever:
      - In London/NY session window
      - H1 ADX > 18 (any directional move)
      - Price pulled back to EMA20 ± 0.3 ATR then closed in trend direction
      - Direction follows H1 +DI vs -DI dominance
      - 1.2:1 R:R fixed target (high WR over high $)

    Designed to fire 2-4 times per day in trending environments.
    Re-arm cooldown = 3 bars (15min) after each setup so we don't spam.
    """
    if h1_adx is None:
        return []

    setups: list[dict] = []
    df = m5.copy().reset_index(drop=True)
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    tr = pd.concat([
        (df["high"] - df["low"]),
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"]  - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()

    ls_start, ls_end = 15 * 60, 18 * 60
    ny_start, ny_end = NY_START[0] * 60 + NY_START[1], NY_END[0] * 60 + NY_END[1]
    in_session = (
        ((df["minute_ist"] >= ls_start) & (df["minute_ist"] < ls_end)) |
        ((df["minute_ist"] >= ny_start) & (df["minute_ist"] < ny_end))
    )

    last_fire_idx = -100
    COOLDOWN = 3
    TP_RR    = 1.2

    for i in range(30, len(df)):
        if not in_session.iloc[i]:
            continue
        if i - last_fire_idx < COOLDOWN:
            continue
        row = df.iloc[i]
        regime = _regime_at(h1_adx, row["datetime"])
        if regime["adx"] < 18:
            continue

        ema, atr = float(row["ema20"]), float(row["atr"])
        if atr <= 0:
            continue
        rng = atr * 0.3

        c, o, h, lo = float(row["close"]), float(row["open"]), float(row["high"]), float(row["low"])

        # Long pullback: regime bullish + low touched EMA± and close green above EMA
        if regime["dir"] == "bullish" and lo <= ema + rng and lo >= ema - rng \
                and c > o and c > ema:
            entry   = c
            sl      = lo - max(atr * 0.5, 2.0)
            sl_dist = entry - sl
            if sl_dist < 4.0 or sl_dist > 12.0:
                continue
            tp = entry + sl_dist * TP_RR
            setups.append({
                "engine": "PB", "entry_time": row["datetime"], "direction": "long",
                "entry": entry, "sl": sl, "tp": tp,
                "regime": regime["label"],
                "reason": f"PB long EMA-pullback | ADX={regime['adx']:.0f}",
            })
            last_fire_idx = i
            continue

        # Short pullback: regime bearish + high touched EMA± and close red below EMA
        if regime["dir"] == "bearish" and h >= ema - rng and h <= ema + rng \
                and c < o and c < ema:
            entry   = c
            sl      = h + max(atr * 0.5, 2.0)
            sl_dist = sl - entry
            if sl_dist < 4.0 or sl_dist > 12.0:
                continue
            tp = entry - sl_dist * TP_RR
            setups.append({
                "engine": "PB", "entry_time": row["datetime"], "direction": "short",
                "entry": entry, "sl": sl, "tp": tp,
                "regime": regime["label"],
                "reason": f"PB short EMA-pullback | ADX={regime['adx']:.0f}",
            })
            last_fire_idx = i

    return setups


# ─── AS: Asian Session Range Breakout (fills the dead-London-day gap) ──────

def _scan_as(m5: pd.DataFrame, _m1: pd.DataFrame | None = None,
             _h4: pd.DataFrame | None = None,
             h1_adx: pd.DataFrame | None = None) -> list[dict]:
    """
    Asian-session range breakout. Fires when London/NY are dead by trading
    the smaller Asian moves.

    Mechanics:
      1. Mark Asian range from 05:30-09:00 IST (42 M5 bars)
      2. Range must be 5-25pt (filters dead floats and news gaps)
      3. From 09:00 to 13:00 IST, take first M5 close >1pt beyond range
      4. SL: opposite side of range + 2pt (or 0.5*range, whichever tighter)
      5. TP: 1.5R fixed
      6. One setup per direction per day (max 2 AS trades/day)
    """
    setups: list[dict] = []
    ASIAN_START = 5 * 60 + 30      # 05:30 IST
    ASIAN_END   = 9 * 60           # 09:00 IST
    BREAK_CUT   = 13 * 60          # 13:00 IST — last entry
    MIN_RNG     = 4.0              # accept tight Asians too
    MAX_RNG     = 100.0            # post-news/gap days = move is already done
    TP_RR       = 1.5

    for date in m5["date_ist"].unique():
        day = m5[m5["date_ist"] == date].reset_index(drop=True)

        rng_bars = day[(day["minute_ist"] >= ASIAN_START) & (day["minute_ist"] < ASIAN_END)]
        if len(rng_bars) < 20:
            continue

        rng_hi   = float(rng_bars["high"].max())
        rng_lo   = float(rng_bars["low"].min())
        rng_size = rng_hi - rng_lo
        if rng_size < MIN_RNG or rng_size > MAX_RNG:
            continue

        # Cap SL hard at 10pt regardless of range size (wide-Asian days don't get bigger risk)
        sl_dist = float(min(max(rng_size * 0.4, 4.0), 10.0))

        post = day[(day["minute_ist"] >= ASIAN_END) & (day["minute_ist"] < BREAK_CUT)]\
                  .reset_index(drop=True)
        if len(post) < 2:
            continue

        long_fired = False
        short_fired = False

        for i in range(len(post)):
            bar = post.iloc[i]
            c = float(bar["close"])
            regime = _regime_at(h1_adx, bar["datetime"])
            rlbl = regime["label"]

            if not long_fired and c > rng_hi + 1.0:
                entry = c
                sl    = entry - sl_dist
                tp    = entry + sl_dist * TP_RR
                if entry - sl >= 4.0:
                    setups.append({
                        "engine": "AS", "entry_time": bar["datetime"],
                        "direction": "long", "entry": entry, "sl": sl, "tp": tp,
                        "regime": rlbl,
                        "reason": f"AS long break | Asian {rng_size:.1f}pt",
                    })
                long_fired = True

            if not short_fired and c < rng_lo - 1.0:
                entry = c
                sl    = entry + sl_dist
                tp    = entry - sl_dist * TP_RR
                if sl - entry >= 4.0:
                    setups.append({
                        "engine": "AS", "entry_time": bar["datetime"],
                        "direction": "short", "entry": entry, "sl": sl, "tp": tp,
                        "regime": rlbl,
                        "reason": f"AS short break | Asian {rng_size:.1f}pt",
                    })
                short_fired = True

            if long_fired and short_fired:
                break

    return setups


# ─── SW: M15 Swing Continuation (slower, higher R:R) ───────────────────────

def _scan_sw(m5: pd.DataFrame, _m1: pd.DataFrame | None = None,
             _h4: pd.DataFrame | None = None,
             h1_adx: pd.DataFrame | None = None) -> list[dict]:
    """
    M15 EMA50 pullback continuation. Slower than PB (M5) — fires on
    completed M15 candles with 2:1 R:R for larger targets.

    Entry conditions:
      - In London/NY session (15:00-21:30 IST)
      - H1 ADX > 22 (clear trend)
      - M15 candle pulls back to within 0.7 ATR of EMA50
      - M15 close in regime direction
      - Cooldown: 1 M15 bar (15min) between fires
    """
    if h1_adx is None or m5.empty:
        return []

    # Resample M5 → M15 (3 M5 bars per M15)
    m5_idx = m5.copy()
    m5_idx["datetime"] = pd.to_datetime(m5_idx["datetime"])
    m5_idx = m5_idx.set_index("datetime").sort_index()
    m15 = m5_idx[["open", "high", "low", "close"]].resample("15min", origin="start_day", label="left").agg({
        "open":  "first",
        "high":  "max",
        "low":   "min",
        "close": "last",
    }).dropna().reset_index()

    if len(m15) < 60:
        return []

    # Tag with IST minute for session filter
    m15["ist"]        = m15["datetime"].dt.tz_convert(IST)
    m15["minute_ist"] = m15["ist"].dt.hour * 60 + m15["ist"].dt.minute

    m15["ema50"] = m15["close"].ewm(span=50, adjust=False).mean()
    tr = pd.concat([
        (m15["high"] - m15["low"]),
        (m15["high"] - m15["close"].shift(1)).abs(),
        (m15["low"]  - m15["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    m15["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()

    setups: list[dict] = []
    SESS_START = 15 * 60         # 15:00 IST
    SESS_END   = 21 * 60 + 30    # 21:30 IST
    TP_RR      = 1.5             # tightened from 2.0 — 30% WR at 2:1 was below breakeven
    COOLDOWN   = 1               # 1 M15 bar = 15min
    last_fire  = -100

    for i in range(50, len(m15)):
        row = m15.iloc[i]
        if not (SESS_START <= int(row["minute_ist"]) < SESS_END):
            continue
        if i - last_fire < COOLDOWN:
            continue

        regime = _regime_at(h1_adx, row["datetime"])
        if regime["adx"] < 22:
            continue

        ema, atr = float(row["ema50"]), float(row["atr"])
        if atr <= 0:
            continue
        c, o, h, lo = float(row["close"]), float(row["open"]), float(row["high"]), float(row["low"])
        prox = atr * 0.4   # tightened from 0.7 — only entries near EMA, not loose retests

        # Long: pullback touched within prox of EMA50, candle closed up + above EMA
        if regime["dir"] == "bullish" and lo <= ema + prox and lo >= ema - prox \
                and c > o and c > ema:
            entry   = c
            sl      = lo - max(atr * 0.4, 3.0)
            sl_dist = entry - sl
            if sl_dist < 5.0 or sl_dist > 18.0:
                continue
            tp = entry + sl_dist * TP_RR
            setups.append({
                "engine": "SW", "entry_time": row["datetime"], "direction": "long",
                "entry": entry, "sl": sl, "tp": tp,
                "regime": regime["label"], "tf": "M15",
                "reason": f"SW long M15-EMA50 | ADX={regime['adx']:.0f}",
            })
            last_fire = i
            continue

        # SW shorts disabled: 30.8% WR, -$84 in bull-market gold (same pattern as MR/DOR shorts).
        # Re-enable only after data confirms edge in a sustained bear regime.

    return setups


def _scan_asw(m5: pd.DataFrame) -> list[dict]:
    """
    Asian Sweep + Reclaim — the practical 80% pattern at London open.

    Mechanics:
      - Asian range: 05:30-13:00 IST (high + low)
      - Hunt window: 13:00-15:30 IST (London open extends stops past Asian extreme)
      - Step 1: price wicks ≥2pt past Asian high or Asian low (liquidity grab)
      - Step 2: price reclaims — close ≥1pt back inside the Asian range
      - Entry: fade the sweep (short if high swept, long if low swept) on the
        reclaim close
      - SL: 2pt beyond the sweep wick extreme
      - TP: opposite Asian extreme (mean-reversion through range)
      - Asian range width must be 8-60pt (reject compressed/volatile days)
    """
    setups: list[dict] = []
    ranges = _asian_ranges(m5)

    sessions = [
        ("LDN", 13*60, 16*60),
    ]

    for label, hunt_start, hunt_end in sessions:
        hunt_bars = m5[
            (m5["minute_ist"] >= hunt_start) & (m5["minute_ist"] < hunt_end)
        ].reset_index(drop=True)

        sweep_state: dict[str, tuple[str, float]] = {}
        fired: set[str] = set()

        for i in range(len(hunt_bars)):
            row = hunt_bars.iloc[i]
            date = row["date_ist"]
            if date in fired:
                continue
            rng = ranges.get(date)
            if not rng:
                continue
            hi, lo, width = rng
            if width < 8.0 or width > 60.0:
                continue

            state = sweep_state.get(date)

            if state is None:
                if row["high"] >= hi + 2.0:
                    sweep_state[date] = ("swept_high", float(row["high"]))
                elif row["low"] <= lo - 2.0:
                    sweep_state[date] = ("swept_low", float(row["low"]))
                state = sweep_state.get(date)
                if state is None:
                    continue

            swept, wick = state

            if swept == "swept_high" and row["close"] <= hi - 1.0:
                entry = float(row["close"])
                sl    = wick + 2.0
                sl_dist = sl - entry
                if 5.0 <= sl_dist <= 22.0:
                    tp = lo
                    if tp < entry:
                        setups.append({
                            "engine":     "ASW",
                            "entry_time": row["datetime"],
                            "direction":  "short",
                            "entry":      entry,
                            "sl":         sl,
                            "tp":         tp,
                            "reason":     f"ASW {label} short | Asian {width:.1f}pt | sweep hi {wick:.2f}",
                        })
                        fired.add(date)
                        continue

            if swept == "swept_low" and row["close"] >= lo + 1.0:
                entry = float(row["close"])
                sl    = wick - 2.0
                sl_dist = entry - sl
                if 5.0 <= sl_dist <= 22.0:
                    tp = hi
                    if tp > entry:
                        setups.append({
                            "engine":     "ASW",
                            "entry_time": row["datetime"],
                            "direction":  "long",
                            "entry":      entry,
                            "sl":         sl,
                            "tp":         tp,
                            "reason":     f"ASW {label} long | Asian {width:.1f}pt | sweep lo {wick:.2f}",
                        })
                        fired.add(date)
    return setups


# ─── Trade simulator ───────────────────────────────────────────────────────

def simulate(m5: pd.DataFrame, setups: list[dict], use_be: bool = False) -> list[V7Trade]:
    """Execute setups bar-by-bar with funded-account guardrails.

    use_be=False runs pure SL→TP (default — highest edge for DOR).
    use_be=True  enables 1R-partial + BE-runner mechanic.
    """
    setups = sorted(setups, key=lambda s: s["entry_time"])
    trades: list[V7Trade] = []
    daily: dict[str, DailyState] = {}
    open_trade: Optional[V7Trade] = None

    m5_sorted = m5.sort_values("datetime").reset_index(drop=True)

    setup_idx = 0
    for i in range(len(m5_sorted)):
        bar = m5_sorted.iloc[i]
        bar_time = bar["datetime"]
        bar_high = float(bar["high"])
        bar_low  = float(bar["low"])

        # ── Update open trade ─────────────────────────────────────────────
        if open_trade is not None:
            t = open_trade
            sl_dist = abs(t.entry_price - t.sl)

            hit_sl = (
                (t.direction == "long"  and bar_low  <= t.sl) or
                (t.direction == "short" and bar_high >= t.sl)
            )
            hit_tp = (
                (t.direction == "long"  and bar_high >= t.tp) or
                (t.direction == "short" and bar_low  <= t.tp)
            )
            target_1r = (t.entry_price + sl_dist) if t.direction == "long" else (t.entry_price - sl_dist)
            hit_1r = (
                use_be and not t.partial_hit and (
                    (t.direction == "long"  and bar_high >= target_1r) or
                    (t.direction == "short" and bar_low  <= target_1r)
                )
            )

            if hit_sl:
                # Stop-order fills slip through the SL during fast moves
                sl_fill = t.sl - SL_SLIPPAGE_PT if t.direction == "long" \
                          else t.sl + SL_SLIPPAGE_PT
                t.exit_time  = bar_time
                t.exit_price = sl_fill
                pnl = (sl_fill - t.entry_price) * 100 * t.lots if t.direction == "long" \
                      else (t.entry_price - sl_fill) * 100 * t.lots
                commission = t.lots * 100 * COMMISSION_PER_001_LOT
                t.pnl       = pnl - commission + t.realized
                t.result    = "be" if t.partial_hit else "loss"
                trades.append(t)
                _daily_update(daily, t)
                open_trade = None
            elif hit_tp:
                # Limit-order TPs fill at price or better — TP_SLIPPAGE_PT defaults to 0
                tp_fill = t.tp - TP_SLIPPAGE_PT if t.direction == "long" \
                          else t.tp + TP_SLIPPAGE_PT
                t.exit_time  = bar_time
                t.exit_price = tp_fill
                pnl = (tp_fill - t.entry_price) * 100 * t.lots if t.direction == "long" \
                      else (t.entry_price - tp_fill) * 100 * t.lots
                commission = t.lots * 100 * COMMISSION_PER_001_LOT
                t.pnl       = pnl - commission + t.realized
                t.result    = "win"
                trades.append(t)
                _daily_update(daily, t)
                open_trade = None
            elif hit_1r:
                partial_lots = t.lots / 2.0
                partial_pnl  = sl_dist * partial_lots * 100
                commission   = partial_lots * 100 * COMMISSION_PER_001_LOT
                t.realized   = partial_pnl - commission
                t.lots       = partial_lots
                t.sl         = t.entry_price + (0.5 if t.direction == "long" else -0.5)
                t.partial_hit = True

        # ── Try to open a new setup ───────────────────────────────────────
        while setup_idx < len(setups) and setups[setup_idx]["entry_time"] <= bar_time:
            s = setups[setup_idx]; setup_idx += 1
            if open_trade is not None:
                continue
            if s["entry_time"] != bar_time:
                continue         # stale setup — bar already passed

            date = _date_ist(bar_time)
            day = daily.setdefault(date, DailyState(date=date))
            if day.locked or day.losses >= MAX_LOSSES_PER_DAY or day.trades >= MAX_TRADES_PER_DAY:
                continue
            if day.pnl <= -DAILY_LOSS_CAP or day.pnl >= DAILY_PROFIT_LOCK:
                day.locked = True; continue
            # Falling-knife guard: 2 same-side losses on this engine → cool that side
            side_key = f"{s['engine']}_{s['direction']}"
            if day.side_losses.get(side_key, 0) >= 2:
                continue
            # News blackout: skip entries within ±5/+15min of high-impact events.
            # Backtest uses NFP first-Friday rule; live passes today's calendar events.
            now_ist = bar_time.tz_convert(IST).to_pydatetime()
            blocked, _reason = is_news_blackout(now_ist, None)
            if blocked:
                continue

            sl_dist = abs(s["entry"] - s["sl"])
            if sl_dist < 4.0 or sl_dist > 30.0:
                continue
            lots = _size_lots(sl_dist)
            if sl_dist * lots * 100 > MAX_RISK_PER_TRADE + 0.5:
                continue

            # Apply entry slippage — fill is worse than signal price.
            # SL/TP remain at signal-time absolute prices (broker stores them
            # at exact levels), so realized R:R shifts unfavorably — this is
            # the realistic broker behavior we want to model.
            signal_entry = float(s["entry"])
            fill_price   = signal_entry + ENTRY_SLIPPAGE_PT if s["direction"] == "long" \
                           else signal_entry - ENTRY_SLIPPAGE_PT
            open_trade = V7Trade(
                engine=s["engine"],
                entry_time=bar_time,
                direction=s["direction"],
                entry_price=fill_price,
                sl=float(s["sl"]),
                tp=float(s["tp"]),
                lots=lots,
                risk_usd=sl_dist * lots * 100,
                reason=s.get("reason", ""),
                regime=s.get("regime", "unknown"),
                tf=s.get("tf", "M5"),
            )

    return trades


def _daily_update(daily: dict[str, DailyState], trade: V7Trade) -> None:
    date = _date_ist(trade.entry_time)
    day = daily.setdefault(date, DailyState(date=date))
    day.pnl    += trade.pnl
    day.trades += 1
    if trade.pnl < 0:
        day.losses += 1
        side_key = f"{trade.engine}_{trade.direction}"
        day.side_losses[side_key] = day.side_losses.get(side_key, 0) + 1


# ─── Reporting ─────────────────────────────────────────────────────────────

def _summary(trades: list[V7Trade]) -> dict:
    if not trades:
        return {"n": 0}
    wins    = [t for t in trades if t.result == "win"]
    losses  = [t for t in trades if t.result == "loss"]
    bes     = [t for t in trades if t.result == "be"]
    total_pnl = sum(t.pnl for t in trades)
    wr_full = len(wins) / len(trades) * 100
    wr_incl = (len(wins) + sum(1 for b in bes if b.realized > 0)) / len(trades) * 100
    first = min(t.entry_time for t in trades)
    last  = max(t.exit_time or t.entry_time for t in trades)
    weeks = max((last - first).days / 7.0, 1.0)
    return {
        "n":         len(trades),
        "wins":      len(wins),
        "losses":    len(losses),
        "be":        len(bes),
        "wr_full":   f"{wr_full:.1f}%",
        "wr_incl":   f"{wr_incl:.1f}%",
        "total_pnl": f"${total_pnl:.2f}",
        "weeks":     round(weeks, 1),
        "weekly":    f"${total_pnl / weeks:.2f}",
    }


def run(start_date: str, end_date: str, engines: list[str] | None = None,
        use_be: bool = False) -> dict:
    # Defaults set by post-slippage OOS validation (2025-11 / 2025-12 window):
    #   DOR + ORB + MR survives realistic 1.5pt entry / 1pt SL slippage
    #   PB (high-freq, 1.2:1 R:R) — net loss under slippage; opt-in only
    #   AS (Asian breakout)        — net loss OOS; opt-in only
    #   SW (M15 swing, long-only)  — small sample, marginal; opt-in only
    engines = engines or ["DOR", "ORB", "MR"]
    data_dir = config.BASE_DIR / "backtest" / "data"
    m5 = _load_csv(str(data_dir / "XAUUSD_5min.csv"))

    start_ts = pd.Timestamp(start_date, tz="UTC")
    end_ts   = pd.Timestamp(end_date,   tz="UTC") + pd.Timedelta(days=1)
    m5 = m5[(m5["datetime"] >= start_ts) & (m5["datetime"] < end_ts)].reset_index(drop=True)
    m5 = _enrich_ist(m5)

    m1 = _load_m1(data_dir)
    if m1 is not None:
        m1 = m1[(m1["datetime"] >= start_ts) & (m1["datetime"] < end_ts)].reset_index(drop=True)

    h4_path = str(data_dir / "XAUUSD_4h.csv")
    try:
        h4 = _load_csv(h4_path)
    except Exception:
        h4 = None

    h1_path = str(data_dir / "XAUUSD_1h.csv")
    try:
        h1 = _load_csv(h1_path)
        h1_adx = _adx_series(h1)
    except Exception:
        h1_adx = None

    setups: list[dict] = []
    if "DOR" in engines: setups.extend(_scan_dor(m5, m1, h4, h1_adx))
    if "ASW" in engines: setups.extend(_scan_asw(m5))
    if "ORB" in engines: setups.extend(_scan_orb(m5, m1, h4, h1_adx))
    if "MR"  in engines: setups.extend(_scan_mr (m5, m1, h4, h1_adx))
    if "PB"  in engines: setups.extend(_scan_pb (m5, m1, h4, h1_adx))
    if "AS"  in engines: setups.extend(_scan_as (m5, m1, h4, h1_adx))
    if "SW"  in engines: setups.extend(_scan_sw (m5, m1, h4, h1_adx))

    sim_bars = m1 if m1 is not None else m5
    trades = simulate(sim_bars, setups, use_be=use_be)
    by_engine = {
        eng: _summary([t for t in trades if t.engine == eng])
        for eng in engines
    }
    # Regime breakdown — WR and PnL per regime label, helps identify which environments
    # each engine has edge in (the "WHEN is this strategy good" question)
    regime_keys = sorted({t.regime for t in trades if t.regime})
    by_regime = {
        rk: _summary([t for t in trades if t.regime == rk])
        for rk in regime_keys
    }
    return {
        "summary":    _summary(trades),
        "by_engine":  by_engine,
        "by_regime":  by_regime,
        "trades":     trades,
        "raw_setups": len(setups),
    }


# ─── CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-11-01")
    parser.add_argument("--end",   default="2026-04-16")
    parser.add_argument("--engines", default="DOR,ORB,MR")
    parser.add_argument("--be", action="store_true",
                        help="Enable 1R partial + BE-runner mechanic (default off: pure SL/TP)")
    args = parser.parse_args()

    result = run(args.start, args.end, engines=args.engines.split(","), use_be=args.be)

    print("=" * 76)
    print(f"AURUM v7   {args.start} → {args.end}   engines={args.engines}")
    print("=" * 76)
    print(f"Raw setups scanned: {result['raw_setups']}")
    print(f"\nOVERALL")
    for k, v in result["summary"].items():
        print(f"  {k:<10} {v}")
    print(f"\nBY ENGINE")
    for eng, s in result["by_engine"].items():
        if s.get("n", 0) == 0:
            print(f"  {eng}: no trades")
            continue
        print(f"  {eng}: {s['n']} trades | WR {s['wr_incl']} (full {s['wr_full']}) | "
              f"PnL {s['total_pnl']} | weekly {s['weekly']}")
    print("\nSAMPLE TRADES (worst losers first)")
    sample = sorted(result["trades"], key=lambda t: t.pnl)[:10]
    for t in sample:
        print(f"  {t.engine} {t.direction:<5} {t.entry_time}  "
              f"pnl ${t.pnl:>7.2f}  {t.result:<5}  {t.reason}")

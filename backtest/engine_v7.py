"""
Aurum v7 — Mechanical engines (DOR + ASW).

Pure-rule engines. Pattern-based, not theory-based — they trade behaviors
gold exhibits repeatedly (high base-rate setups, not textbook ideas).

  DOR — Daily-Open Mean Reversion (range days)
    Fires in London session + NY killzone when price is ≥30pt displaced from
    the 00:00 UTC open and prints an M5 reversal bar. Target: daily open ±5pt.

  ASW — Asian Sweep + Reclaim (London open liquidity grab)
    At London open gold hunts Asian-session liquidity: wicks past Asian high
    or low, then reclaims the range. This engine fades that sweep.

Funded-account guardrails:
  - $25 max risk per trade
  - 2 losing trades/day → stop
  - $500 daily loss cap
  - $500 daily profit lock
  - One position at a time (no overlap)
"""

from __future__ import annotations

import argparse
import logging
import math
from dataclasses import dataclass
from typing import Optional

import pandas as pd

import config
from config import IST

logger = logging.getLogger(__name__)

# ─── Config constants ──────────────────────────────────────────────────────

MAX_RISK_PER_TRADE      = 25.0          # USD — QTFunded $10k guardrail
DAILY_LOSS_CAP          = 500.0
DAILY_PROFIT_LOCK       = 500.0
MAX_LOSSES_PER_DAY      = 2
MAX_TRADES_PER_DAY      = 8
COMMISSION_PER_001_LOT  = 0.07          # OANDA spread/commission per 0.01 lot per side

# Session windows (IST) — sourced from config.KILLZONES
NY_START    = config.KILLZONES["ny_open"]["start"]
NY_END      = config.KILLZONES["ny_extended"]["end"]

# ─── Data types ────────────────────────────────────────────────────────────

@dataclass
class V7Trade:
    engine:       str                      # "DOR" | "ASW"
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


@dataclass
class DailyState:
    date:    str
    pnl:     float = 0.0
    losses:  int   = 0
    trades:  int   = 0
    locked:  bool  = False


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


def _scan_dor(m5: pd.DataFrame, m1: pd.DataFrame | None = None) -> list[dict]:
    """
    Rules:
      - Fires during London Session (15:00-18:00 IST) or NY killzone
      - Price is ≥ 30pt displaced from daily open
      - Current M5 bar closes back toward daily open (reversal confirmation)
      - If M1 data available: refine entry via M1 FVG within next 10 min
        (tighter SL → more lots → higher PnL per win, +$20/wk vs pure M5)
      - Fallback to M5 bar close entry when no M1 FVG forms
      - SL: 1.5pt beyond FVG boundary (M1) or 2pt beyond bar extreme (M5)
      - TP: daily open ± 5pt buffer
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
        if abs(displacement) < 30.0:
            continue

        # Short fade: price ≥ do+30 and current bar closes red
        if displacement > 0 and row["close"] < prev["close"] and row["close"] < row["open"]:
            if m1 is not None:
                refined = _fvg_entry(m1, row["datetime"], is_short=True, do=do)
                if refined:
                    setups.append({
                        "engine": "DOR", **refined,
                        "reason": f"DOR short M1-FVG | +{displacement:.1f}pt above DO {do:.2f}",
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
                "engine":     "DOR",
                "entry_time": row["datetime"],
                "direction":  "short",
                "entry":      entry,
                "sl":         sl,
                "tp":         tp,
                "reason":     f"DOR short | +{displacement:.1f}pt above DO {do:.2f}",
            })
            continue

        # Long fade: price ≤ do-30 and current bar closes green
        if displacement < 0 and row["close"] > prev["close"] and row["close"] > row["open"]:
            if m1 is not None:
                refined = _fvg_entry(m1, row["datetime"], is_short=False, do=do)
                if refined:
                    setups.append({
                        "engine": "DOR", **refined,
                        "reason": f"DOR long M1-FVG | {displacement:.1f}pt below DO {do:.2f}",
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
                "engine":     "DOR",
                "entry_time": row["datetime"],
                "direction":  "long",
                "entry":      entry,
                "sl":         sl,
                "tp":         tp,
                "reason":     f"DOR long | {displacement:.1f}pt below DO {do:.2f}",
            })
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
                t.exit_time  = bar_time
                t.exit_price = t.sl
                pnl = (t.sl - t.entry_price) * 100 * t.lots if t.direction == "long" \
                      else (t.entry_price - t.sl) * 100 * t.lots
                commission = t.lots * 100 * COMMISSION_PER_001_LOT
                t.pnl       = pnl - commission + t.realized
                t.result    = "be" if t.partial_hit else "loss"
                trades.append(t)
                _daily_update(daily, t)
                open_trade = None
            elif hit_tp:
                t.exit_time  = bar_time
                t.exit_price = t.tp
                pnl = (t.tp - t.entry_price) * 100 * t.lots if t.direction == "long" \
                      else (t.entry_price - t.tp) * 100 * t.lots
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

            sl_dist = abs(s["entry"] - s["sl"])
            if sl_dist < 4.0 or sl_dist > 30.0:
                continue
            lots = _size_lots(sl_dist)
            if sl_dist * lots * 100 > MAX_RISK_PER_TRADE + 0.5:
                continue

            open_trade = V7Trade(
                engine=s["engine"],
                entry_time=bar_time,
                direction=s["direction"],
                entry_price=float(s["entry"]),
                sl=float(s["sl"]),
                tp=float(s["tp"]),
                lots=lots,
                risk_usd=sl_dist * lots * 100,
                reason=s.get("reason", ""),
            )

    return trades


def _daily_update(daily: dict[str, DailyState], trade: V7Trade) -> None:
    date = _date_ist(trade.entry_time)
    day = daily.setdefault(date, DailyState(date=date))
    day.pnl    += trade.pnl
    day.trades += 1
    if trade.pnl < 0:
        day.losses += 1


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
    engines = engines or ["DOR", "ASW"]
    data_dir = config.BASE_DIR / "backtest" / "data"
    m5 = _load_csv(str(data_dir / "XAUUSD_5min.csv"))

    start_ts = pd.Timestamp(start_date, tz="UTC")
    end_ts   = pd.Timestamp(end_date,   tz="UTC") + pd.Timedelta(days=1)
    m5 = m5[(m5["datetime"] >= start_ts) & (m5["datetime"] < end_ts)].reset_index(drop=True)
    m5 = _enrich_ist(m5)

    m1 = _load_m1(data_dir)
    if m1 is not None:
        m1 = m1[(m1["datetime"] >= start_ts) & (m1["datetime"] < end_ts)].reset_index(drop=True)

    setups: list[dict] = []
    if "DOR" in engines: setups.extend(_scan_dor(m5, m1))
    if "ASW" in engines: setups.extend(_scan_asw(m5))

    sim_bars = m1 if m1 is not None else m5
    trades = simulate(sim_bars, setups, use_be=use_be)
    by_engine = {
        eng: _summary([t for t in trades if t.engine == eng])
        for eng in engines
    }
    return {
        "summary":    _summary(trades),
        "by_engine":  by_engine,
        "trades":     trades,
        "raw_setups": len(setups),
    }


# ─── CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-11-01")
    parser.add_argument("--end",   default="2026-04-16")
    parser.add_argument("--engines", default="DOR,ASW")
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

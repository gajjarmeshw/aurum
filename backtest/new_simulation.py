"""
New Simulation Engine — Built on the Session Expansion strategy.

Replaces backtest/simulation_core.py + walk_forward_engine.py combo for
the purpose of generating trades. The old ICT engine is untouched (still
powers the live dashboard as informational display).

This file walks a historical M5 dataframe day-by-day and, for each day:
  1. At 13:30 IST bar: builds a DailyPlan (Asian range, bias, skip?)
  2. In London window: looks for a breakout-retest entry
  3. Simulates trade with TP1 (half close) + TP2 (runner, SL → BE)
  4. If London doesn't trade, looks for the same pattern in NY window
  5. Respects daily guardrails (max trades, stop after loss, profit target)

Public API
──────────
  run_session_backtest(full_df, start_date, end_date) -> dict
    returns { summary, trades, skipped, weekly_avg, daily_breakdown }
"""

import logging
from datetime import timezone, timedelta
from dataclasses import dataclass
from typing import Optional, Set

import pandas as pd

import config
from core import market_classifier
from strategies.session_expansion import (
    build_daily_plan, find_breakout_entry, Entry, _ist_minutes, _ist_date_str
)

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


# ── Trade result type ──────────────────────────────────────────────────────

@dataclass
class SimTrade:
    id: int
    entry_time: str
    entry_price: float
    sl: float
    tp1: float
    tp2: float
    direction: str
    session: str
    grade: str                 # "Session" for UI compatibility
    lots: float
    sl_dist: float

    # Execution result
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    result: str = "open"       # "win", "loss", "be", "partial"
    pnl: float = 0.0
    score: float = 0.0         # UI compatibility

    # Detailed Context (v5.0)
    setup_reason: str = ""
    exit_reason: str = ""
    risk_factors: str = ""
    timeframe: str = "M5"
    be_moved: bool = False
    tp1_hit: bool = False


# ── Helpers ─────────────────────────────────────────────────────────────────

def _risk_based_lots(sl_dist: float, s: dict, regime_lots: float = 0.05) -> float:
    """
    Size lots so max loss == risk_per_trade regardless of SL width.
    Clamped to [0.01, config.MAX_LOT_TRADE1].
    """
    raw = s["risk_per_trade"] / (sl_dist * 100)
    # Cap by both the global limit and the regime-specific limit
    limit = min(config.MAX_LOT_TRADE1, regime_lots)
    return max(0.01, min(limit, round(raw, 2)))


# ── Trade simulator (split TP logic) ────────────────────────────────────────

def _simulate_trade(
    full_df: pd.DataFrame,
    entry: Entry,
    lots: float,
    trade_id: int,
    commission_per_001: float = 0.07,
) -> SimTrade:
    """
    Execute one trade bar-by-bar. Returns a closed SimTrade.
    Rules:
      - SL hits first → full loss
      - TP1 hits first → close half, move SL to BE on runner
      - After BE: TP2 hit → half-win + half-break-even; SL hit → half-win + 0
    """
    is_long = entry.direction == "long"
    half_lots = round(lots / 2, 3)
    runner_lots = round(lots - half_lots, 3)

    t = SimTrade(
        id=trade_id,
        entry_time=str(entry.timestamp),
        entry_price=entry.price,
        sl=entry.sl,
        tp1=entry.tp1,
        tp2=entry.tp2,
        direction=entry.direction,
        session=entry.session,
        grade="Session",
        lots=lots,
        sl_dist=entry.sl_dist,
        setup_reason=entry.setup_reason,
        risk_factors=entry.risk_factors,
        timeframe=entry.timeframe
    )

    half_pnl = 0.0

    for i in range(entry.bar_index + 1, len(full_df)):
        bar = full_df.iloc[i]
        high = float(bar["high"])
        low = float(bar["low"])
        time = str(bar["datetime"])

        # Stop-loss hit
        if is_long and low <= t.sl:
            sl_pnl = (t.sl - t.entry_price) * 100 * (runner_lots if t.tp1_hit else lots)
            commission = lots * 100 * commission_per_001
            t.pnl = round(half_pnl + sl_pnl - commission, 2)
            t.exit_time = time
            t.exit_price = t.sl
            if t.tp1_hit:
                # Half won at TP1 + runner stopped at BE/SL → partial
                t.result = "partial" if t.pnl > 0 else ("be" if abs(t.pnl) < 1 else "loss")
                t.exit_reason = "Stopped at BE/Trailing SL"
            else:
                t.result = "loss"
                t.exit_reason = "Stop Loss Hit"
            return t

        if (not is_long) and high >= t.sl:
            sl_pnl = (t.entry_price - t.sl) * 100 * (runner_lots if t.tp1_hit else lots)
            commission = lots * 100 * commission_per_001
            t.pnl = round(half_pnl + sl_pnl - commission, 2)
            t.exit_time = time
            t.exit_price = t.sl
            if t.tp1_hit:
                t.result = "partial" if t.pnl > 0 else ("be" if abs(t.pnl) < 1 else "loss")
                t.exit_reason = "Stopped at BE/Trailing SL"
            else:
                t.result = "loss"
                t.exit_reason = "Stop Loss Hit"
            return t

        # TP1 hit (half exit)
        if not t.tp1_hit:
            if is_long and high >= t.tp1:
                half_pnl = (t.tp1 - t.entry_price) * 100 * half_lots
                t.tp1_hit = True
                t.sl = t.entry_price   # BE on runner
                t.be_moved = True
            elif (not is_long) and low <= t.tp1:
                half_pnl = (t.entry_price - t.tp1) * 100 * half_lots
                t.tp1_hit = True
                t.sl = t.entry_price
                t.be_moved = True

        # TP2 hit (runner takes full profit)
        if t.tp1_hit:
            if is_long and high >= t.tp2:
                tp2_pnl = (t.tp2 - t.entry_price) * 100 * runner_lots
                commission = lots * 100 * commission_per_001
                t.pnl = round(half_pnl + tp2_pnl - commission, 2)
                t.exit_time = time
                t.exit_price = t.tp2
                t.result = "win"
                t.exit_reason = "TP2 Target Hit"
                return t
            if (not is_long) and low <= t.tp2:
                tp2_pnl = (t.entry_price - t.tp2) * 100 * runner_lots
                commission = lots * 100 * commission_per_001
                t.pnl = round(half_pnl + tp2_pnl - commission, 2)
                t.exit_time = time
                t.exit_price = t.tp2
                t.result = "win"
                t.exit_reason = "TP2 Target Hit"
                return t

    # Ran out of data — close at last bar
    last = full_df.iloc[-1]
    close = float(last["close"])
    if t.tp1_hit:
        runner_pnl = ((close - t.entry_price) if is_long else (t.entry_price - close)) * 100 * runner_lots
        t.pnl = round(half_pnl + runner_pnl - lots * 100 * commission_per_001, 2)
    else:
        full_pnl = ((close - t.entry_price) if is_long else (t.entry_price - close)) * 100 * lots
        t.pnl = round(full_pnl - lots * 100 * commission_per_001, 2)
    t.exit_time = str(last["datetime"])
    t.exit_price = close
    t.result = "win" if t.pnl > 0 else ("loss" if t.pnl < 0 else "be")
    return t


# ── Main backtest runner ────────────────────────────────────────────────────

def run_session_backtest(
    full_df: pd.DataFrame,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """
    Walk the M5 dataframe day by day and generate trades using the
    Session Expansion strategy. Returns the same result shape as the
    old simulate_setups for drop-in compatibility.
    """
    s = config.SESSION_EXPANSION
    full_df = full_df.copy()
    full_df["datetime"] = pd.to_datetime(full_df["datetime"], errors='coerce')
    full_df = full_df.dropna(subset=['datetime'])
    full_df = full_df[full_df["datetime"].dt.dayofweek < 5].reset_index(drop=True)

    # Filter by date range
    if start_date:
        mask = full_df["datetime"] >= pd.to_datetime(start_date)
        full_df = full_df[mask].reset_index(drop=True)
    if end_date:
        end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1)
        full_df = full_df[full_df["datetime"] < end_dt].reset_index(drop=True)

    if len(full_df) < 100:
        return _empty_result("insufficient_data")

    # Pre-compute IST minutes and date for fast lookups
    full_df.loc[:, "_ist_date"] = full_df["datetime"].apply(_ist_date_str)
    full_df.loc[:, "_ist_min"] = full_df["datetime"].apply(
        lambda d: _ist_minutes(pd.to_datetime(d))
    )

    # Group bars by IST trading day
    trades: list[SimTrade] = []
    trade_id = 0
    daily_breakdown = {}
    skipped = {
        "range_too_tight": 0,
        "range_too_wide": 0,
        "atr_out_of_band": 0,
        "no_clear_bias": 0,
        "insufficient_data": 0,
        "no_london_entry": 0,
        "no_ny_entry": 0,
        "daily_loss_stop": 0,
        "daily_profit_stop": 0,
        "daily_trade_cap": 0,
        "daily_loss_streak": 0,
        "killzone_used": 0,
        "volatile_regime": 0,
        "dead_regime": 0,
    }

    unique_days = full_df["_ist_date"].unique()

    for day in unique_days:
        day_bars = full_df[full_df["_ist_date"] == day]
        if len(day_bars) < 50:
            continue

        # Find 13:30 IST bar (London window start)
        london_start = day_bars[day_bars["_ist_min"] >= s["london_window_start_min"]]
        if london_start.empty:
            continue
        london_start_idx = int(london_start.index[0])

        # Build plan at 13:30
        plan = build_daily_plan(full_df, london_start_idx)

        if plan.skip_reason:
            if "range_too_tight" in plan.skip_reason:
                skipped["range_too_tight"] += 1
            elif "range_too_wide" in plan.skip_reason:
                skipped["range_too_wide"] += 1
            elif "atr_out" in plan.skip_reason:
                skipped["atr_out_of_band"] += 1
            elif "no_clear_bias" in plan.skip_reason:
                skipped["no_clear_bias"] += 1
            elif "VOLATILE" in plan.skip_reason:
                skipped["volatile_regime"] += 1
            elif "DEAD" in plan.skip_reason:
                skipped["dead_regime"] += 1
            else:
                skipped["insufficient_data"] += 1
            daily_breakdown[day] = {"plan": plan.__dict__, "trades": 0, "pnl": 0.0, "skip": plan.skip_reason}
            continue

        # ── LONDON WINDOW ENTRY ─────────────────────────────────────
        london_end_bars = day_bars[day_bars["_ist_min"] <= s["london_window_end_min"]]
        if london_end_bars.empty:
            continue
        london_end_idx = int(london_end_bars.index[-1])

        day_pnl = 0.0
        day_trades = 0
        day_losses = 0
        killzones_used: Set[str] = set()

        london_entry = find_breakout_entry(
            full_df, plan, london_start_idx, london_end_idx, "London"
        )

        if london_entry is not None:
            regime_lots = market_classifier.get_config_for_regime(plan.regime).get("lots", 0.05)
            lots = _risk_based_lots(london_entry.sl_dist, s, regime_lots)
            trade_id += 1
            trade = _simulate_trade(full_df, london_entry, lots, trade_id)
            trades.append(trade)
            day_pnl += trade.pnl
            day_trades += 1
            killzones_used.add("London")
            if trade.pnl < -1:
                day_losses += 1
        else:
            skipped["no_london_entry"] += 1

        # ── NY WINDOW ENTRY (if guardrails allow) ──────────────────
        can_take_ny = (
            day_trades < s["max_trades_per_day"]
            and day_losses < 2  # 2-loss day-stop
            and "NY" not in killzones_used  # First-valid-per-killzone Rule
            and day_pnl < s["stop_after_profit_target"]
            and day_pnl > -config.DAILY_LOSS_HARD_CAP
        )
        
        # Stop after any loss rule (if enabled in config)
        if s.get("stop_after_loss", True) and day_losses > 0:
            can_take_ny = False

        if can_take_ny:
            ny_start_bars = day_bars[day_bars["_ist_min"] >= s["ny_window_start_min"]]
            ny_end_bars = day_bars[day_bars["_ist_min"] <= s["ny_window_end_min"]]

            if not ny_start_bars.empty and not ny_end_bars.empty:
                ny_start_idx = int(ny_start_bars.index[0])
                ny_end_idx = int(ny_end_bars.index[-1])

                if ny_end_idx > ny_start_idx:
                    # Use same plan — bias stays from H1 context at 13:30
                    ny_entry = find_breakout_entry(
                        full_df, plan, ny_start_idx, ny_end_idx, "NY"
                    )
                    if ny_entry is None:
                        skipped["no_ny_entry"] += 1
                    else:
                        regime_lots = market_classifier.get_config_for_regime(plan.regime).get("lots", 0.05)
                        lots = _risk_based_lots(ny_entry.sl_dist, s, regime_lots)
                        trade_id += 1
                        trade = _simulate_trade(full_df, ny_entry, lots, trade_id)
                        trades.append(trade)
                        day_pnl += trade.pnl
                        day_trades += 1
                        killzones_used.add("NY")
                        if trade.pnl < -1:
                            day_losses += 1
        elif day_losses > 0:
            skipped["daily_loss_stop"] += 1
        elif "NY" in killzones_used:
             skipped["killzone_used"] += 1

        daily_breakdown[day] = {
            "plan": {"bias": plan.bias, "range": plan.asian_range, "atr": plan.h1_atr},
            "trades": day_trades,
            "pnl": round(day_pnl, 2),
        }

    # ── Summarize ───────────────────────────────────────────────────
    wins = sum(1 for t in trades if t.result == "win")
    losses = sum(1 for t in trades if t.result == "loss")
    partials = sum(1 for t in trades if t.result == "partial")
    bes = sum(1 for t in trades if t.result == "be")
    total = len(trades)
    total_pnl = round(sum(t.pnl for t in trades), 2)
    win_rate = (wins + partials) / total * 100 if total > 0 else 0.0

    # Weeks from date range
    if total > 0:
        first_dt = pd.to_datetime(trades[0].entry_time)
        last_dt = pd.to_datetime(trades[-1].entry_time)
        weeks = max(1, round((last_dt - first_dt).days / 7))
    else:
        weeks = 1

    weekly_avg = round(total_pnl / weeks, 2)

    summary = {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "partials": partials,
        "be": bes,
        "win_rate": f"{win_rate:.1f}%",
        "total_pnl": f"${total_pnl:.2f}",
        "final_balance": f"${10000 + total_pnl:.2f}",
    }

    logger.info(
        f"Session backtest complete: {total} trades | "
        f"WR {summary['win_rate']} | PnL {summary['total_pnl']} | "
        f"Weekly ${weekly_avg} | Days: {len(daily_breakdown)}"
    )
    logger.info(f"Skipped: {skipped}")

    return {
        "summary": summary,
        "trades": trades,
        "skipped": skipped,
        "weekly_avg": f"${weekly_avg:.2f}",
        "daily_breakdown": daily_breakdown,
    }


def _empty_result(reason: str) -> dict:
    return {
        "summary": {
            "total_trades": 0, "wins": 0, "losses": 0, "partials": 0, "be": 0,
            "win_rate": "0%", "total_pnl": "$0.00", "final_balance": "$10000.00",
        },
        "trades": [],
        "skipped": {reason: 1},
        "weekly_avg": "$0.00",
        "daily_breakdown": {},
    }


if __name__ == "__main__":
    import logging
    import pandas as pd
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    # Run a default backtest for Feb-Apr 2026
    print("\n" + "="*60)
    print(" AURUM v5.0 MARKET REGIME BACKTEST AUDIT")
    print("="*60)
    
    # Load 5m data as base
    data_path = config.BACKTEST_DATA_DIR / "XAUUSD_5min.csv"
    if not data_path.exists():
        print(f"Error: {data_path} not found.")
    else:
        df = pd.read_csv(str(data_path))
        results = run_session_backtest(df)
        
        summary = results["summary"]
        skipped = results["skipped"]
        
        print(f"\nRESULTS SUMMARY:")
        print(f"  Total Trades:  {summary['total_trades']}")
        print(f"  Win Rate:      {summary['win_rate']}")
        print(f"  Total PnL:     {summary['total_pnl']}")
        print(f"  Weekly Avg:    {results['weekly_avg']}")
        print(f"  Days Audited:  {len(results['daily_breakdown'])}")
        
        print(f"\nREGIME-AWARE SKIPS:")
        print(f"  Volatile Locks: {skipped.get('volatile_regime', 0)}")
        print(f"  Dead Markets:   {skipped.get('dead_regime', 0)}")
        print(f"  ATR Out-Band:   {skipped.get('atr_out_of_band', 0)}")
        
        print("\n" + "="*60)
        print(" AUDIT COMPLETE")
        print("="*60)

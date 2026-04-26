"""
Side-by-side comparison: baseline vs Strategy v6.

Toggles config.STRATEGY_V6_ENABLED and re-runs the same engine on the
same data window so we can directly compare:
    total trades | WR | PnL | weekly avg | skipped counters
"""

import argparse
import logging

import pandas as pd

import config
from backtest.walk_forward_engine import run_all_timeframes
from backtest.simulation_core import simulate_setups

logging.basicConfig(level=logging.WARNING, format="%(message)s")


def run_one(label: str, start_date: str, end_date: str, v6_enabled: bool) -> dict:
    config.STRATEGY_V6_ENABLED = v6_enabled
    data_dir = str(config.BASE_DIR / "backtest" / "data")
    setups, engines = run_all_timeframes(data_dir, start_date, end_date)
    primary_engine = engines.get("15min") or next(iter(engines.values()))
    result = simulate_setups(setups, primary_engine.full_df, tf_label="M15+H1")

    trades = result["trades"]
    by_mode = {"Swing": [], "Momentum": [], "Scalp": []}
    for t in trades:
        by_mode.setdefault(t.grade, []).append(t)

    first = pd.to_datetime(trades[0].entry_time) if trades else pd.to_datetime(start_date)
    last  = pd.to_datetime(trades[-1].exit_time or trades[-1].entry_time) if trades else pd.to_datetime(end_date)
    weeks = max((last - first).days / 7.0, 1.0) if trades else 1.0

    return {
        "label":      label,
        "summary":    result["summary"],
        "skipped":    result["skipped"],
        "weekly_avg": result["weekly_avg"],
        "weeks":      weeks,
        "by_mode":    {mode: len(ts) for mode, ts in by_mode.items()},
        "pnl_by_mode": {mode: round(sum(t.pnl for t in ts), 2) for mode, ts in by_mode.items()},
    }


def _print_block(res: dict):
    s = res["summary"]
    print(f"\n── {res['label']} ──")
    print(f"  Total trades : {s['total_trades']}   ({res['weeks']:.1f} weeks)")
    print(f"  Full TP WR   : {s['win_rate_strict']}")
    print(f"  Incl. WR     : {s['win_rate']}")
    print(f"  Total PnL    : {s['total_pnl']}")
    print(f"  Weekly avg   : {res['weekly_avg']}")
    print(f"  By mode      : {res['by_mode']}")
    print(f"  PnL by mode  : {res['pnl_by_mode']}")
    keys = [k for k, v in res["skipped"].items() if v > 0]
    if keys:
        print("  Skipped      :")
        for k in sorted(keys, key=lambda x: -res['skipped'][x]):
            print(f"    {k:<28} {res['skipped'][k]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-11-01")
    parser.add_argument("--end",   default="2026-04-16")
    args = parser.parse_args()

    print("=" * 78)
    print(f"BASELINE vs V6   {args.start} → {args.end}")
    print("=" * 78)

    baseline = run_one("BASELINE (current)", args.start, args.end, v6_enabled=False)
    v6       = run_one("STRATEGY V6",        args.start, args.end, v6_enabled=True)

    _print_block(baseline)
    _print_block(v6)

    # Δ summary
    def pnl(x): return float(x["summary"]["total_pnl"].replace("$", "").replace(",", ""))
    def wr(x):  return float(x["summary"]["win_rate"].rstrip("%"))
    def wkly(x): return float(x["weekly_avg"].replace("$", "").replace(",", ""))
    print("\n── Δ (V6 − BASELINE) ──")
    print(f"  PnL      : ${pnl(v6) - pnl(baseline):+.2f}")
    print(f"  WR       : {wr(v6) - wr(baseline):+.1f} pts")
    print(f"  Weekly   : ${wkly(v6) - wkly(baseline):+.2f}")
    print(f"  Trades   : {v6['summary']['total_trades'] - baseline['summary']['total_trades']:+d}")

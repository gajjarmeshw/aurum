"""
CLI Backtest Audit — Restoration of the ICT Momentum Strategy.
Runs the unified simulation engine (simulation_core.py) which delivered
the $316 profit benchmark ($300+/week).
"""

import sys
import os
import pandas as pd
import logging

# Setup logging to avoid cluttering the audit output
logging.basicConfig(level=logging.ERROR)

sys.path.append(os.getcwd())

from backtest.walk_forward_engine import BacktestEngine
from backtest.simulation_core import simulate_setups


def run_audit(
    start_date: str = "2026-03-01",
    end_date: str = "2026-04-11",
    tf: str = "5min",
):
    print("─" * 60)
    print("  AURUM — ICT MOMENTUM BACKTEST (REVERSION)")
    print(f"  {start_date}  →  {end_date}  |  TF: {tf}")
    print("─" * 60)

    data_path = f"backtest/data/XAUUSD_{tf}.csv"
    if not os.path.exists(data_path):
        print(f"ERROR: Data file {data_path} not found.")
        return

    print(f"Initializing Backtest Engine …")
    engine = BacktestEngine(data_path, start_date=start_date, end_date=end_date)
    
    print("Scanning for ICT setups (Liquidity/BOS/FVG) …")
    setups = engine.run()
    
    print(f"Simulating trades for {len(setups)} setups …")
    result = simulate_setups(setups, engine.full_df)

    summary = result["summary"]
    trades = result["trades"]
    skipped = result["skipped"]

    print()
    print("─" * 60)
    print("  RESULTS (REVERTED)")
    print("─" * 60)
    print(f"  Trades    : {summary['total_trades']}  "
          f"(W:{summary['wins']} / Partial:{summary['partial_wins']} / L:{summary['losses']})")
    print(f"  Win Rate  : {summary['win_rate']} (TP-only: {summary['win_rate_strict']})")
    print(f"  Total PnL : {summary['total_pnl']}")
    print(f"  Weekly    : {result['weekly_avg']} / week")
    print(f"  Balance   : {summary['final_balance']}")
    print()
    print("  Skipped breakdown:")
    for reason, count in skipped.items():
        if count:
            print(f"    {reason:<24} {count}")
    print("─" * 60)

    print()
    print("  TRADE LOG")
    print(f"  {'Date/Time':<22} {'Dir':<6} {'Session':<12} {'Result':<8} {'PnL':>9}  Mode")
    print("  " + "─" * 68)
    for t in trades:
        entry_dt = str(pd.to_datetime(t.entry_time))[:19]
        print(
            f"  {entry_dt:<22} "
            f"{t.direction.upper():<6} "
            f"{t.session:<12} "
            f"{t.result.upper():<8} "
            f"${t.pnl:>8.2f}  "
            f"{t.grade}"
        )

    print("─" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2026-02-18")
    parser.add_argument("--end", default="2026-04-11")
    parser.add_argument("--timeframe", default="5min")
    args = parser.parse_args()
    
    run_audit(start_date=args.start, end_date=args.end, tf=args.timeframe)

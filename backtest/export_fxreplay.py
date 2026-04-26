"""
FXReplay Export — generates two files for replay testing:

  1. fxreplay_signals.csv  — all DOR+ASW entry signals (use as a checklist while replaying)
  2. fxreplay_trades.csv   — completed trades with entry/exit for performance review

FXReplay usage:
  - Load XAUUSD M5 chart
  - Start replay at the START_DATE below
  - At each signal time, place the trade manually with the given entry/SL/TP
  - Compare your fills to the backtest results

Run:
  python -m backtest.export_fxreplay
  python -m backtest.export_fxreplay --start 2026-01-01 --end 2026-04-16
"""

import argparse
import pandas as pd
from pathlib import Path

import config
from backtest.engine_v7 import (
    _load_csv, _enrich_ist, _load_m1, _scan_dor, _scan_asw, simulate, _summary,
)

IST = config.IST
OUT_DIR = config.BASE_DIR / "backtest" / "results"


def export(start_date: str, end_date: str):
    data_dir = config.BASE_DIR / "backtest" / "data"
    m5 = _load_csv(str(data_dir / "XAUUSD_5min.csv"))
    start_ts = pd.Timestamp(start_date, tz="UTC")
    end_ts   = pd.Timestamp(end_date,   tz="UTC") + pd.Timedelta(days=1)
    m5 = m5[(m5["datetime"] >= start_ts) & (m5["datetime"] < end_ts)].reset_index(drop=True)
    m5 = _enrich_ist(m5)

    m1 = _load_m1(data_dir)
    if m1 is not None:
        m1 = m1[(m1["datetime"] >= start_ts) & (m1["datetime"] < end_ts)].reset_index(drop=True)

    setups = _scan_dor(m5, m1) + _scan_asw(m5)
    sim_bars = m1 if m1 is not None else m5
    trades   = simulate(sim_bars, setups)
    summary  = _summary(trades)

    print("=" * 70)
    print(f"AURUM v7  {start_date} → {end_date}")
    print("=" * 70)
    print(f"Trades: {summary['n']}  |  WR: {summary['wr_full']}  |  Weekly: {summary['weekly']}")
    print()

    # ── File 1: signals (all raw setups before simulator filters) ──────────
    sig_rows = []
    for s in sorted(setups, key=lambda x: x["entry_time"]):
        ts_ist = pd.Timestamp(s["entry_time"]).tz_convert(IST)
        sig_rows.append({
            "date":        ts_ist.strftime("%Y-%m-%d"),
            "day":         ts_ist.strftime("%a"),
            "entry_time":  ts_ist.strftime("%H:%M"),
            "engine":      s["engine"],
            "direction":   s["direction"].upper(),
            "entry":       round(s["entry"], 2),
            "sl":          round(s["sl"], 2),
            "tp":          round(s["tp"], 2),
            "sl_dist_pt":  round(abs(s["entry"] - s["sl"]), 1),
            "tp_dist_pt":  round(abs(s["tp"] - s["entry"]), 1),
            "rr":          round(abs(s["tp"] - s["entry"]) / abs(s["entry"] - s["sl"]), 1),
            "reason":      s.get("reason", ""),
        })

    sig_df = pd.DataFrame(sig_rows)
    sig_path = OUT_DIR / f"fxreplay_signals_{start_date}_{end_date}.csv"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sig_df.to_csv(sig_path, index=False)
    print(f"Signals file : {sig_path}  ({len(sig_df)} setups)")

    # ── File 2: completed trades ────────────────────────────────────────────
    trade_rows = []
    for t in trades:
        entry_ist = pd.Timestamp(t.entry_time).tz_convert(IST)
        exit_ist  = pd.Timestamp(t.exit_time).tz_convert(IST) if t.exit_time else None
        trade_rows.append({
            "date":          entry_ist.strftime("%Y-%m-%d"),
            "day":           entry_ist.strftime("%a"),
            "entry_time":    entry_ist.strftime("%H:%M"),
            "exit_time":     exit_ist.strftime("%H:%M") if exit_ist else "",
            "engine":        t.engine,
            "direction":     t.direction.upper(),
            "entry":         round(t.entry_price, 2),
            "sl":            round(t.sl, 2),
            "tp":            round(t.tp, 2),
            "exit_price":    round(t.exit_price, 2) if t.exit_price else "",
            "lots":          t.lots,
            "result":        t.result.upper(),
            "pnl_usd":       round(t.pnl, 2),
            "reason":        t.reason,
        })

    trade_df = pd.DataFrame(trade_rows)
    trade_path = OUT_DIR / f"fxreplay_trades_{start_date}_{end_date}.csv"
    trade_df.to_csv(trade_path, index=False)
    print(f"Trades file  : {trade_path}  ({len(trade_df)} trades)")

    # ── Console summary by engine ───────────────────────────────────────────
    print()
    print("BY ENGINE")
    for eng in ["DOR", "ASW"]:
        et = [t for t in trades if t.engine == eng]
        if not et:
            continue
        wins = [t for t in et if t.result == "win"]
        pnl  = sum(t.pnl for t in et)
        wks  = summary["weeks"]
        print(f"  {eng}: {len(et):3d} trades  WR {len(wins)/len(et)*100:.1f}%  "
              f"PnL ${pnl:.2f}  weekly ${pnl/wks:.2f}")

    # ── Top 10 wins + worst 10 losses for FXReplay replay checklist ─────────
    print()
    print("TOP 10 WINS (replay these to build confidence):")
    for t in sorted(trades, key=lambda x: x.pnl, reverse=True)[:10]:
        ts = pd.Timestamp(t.entry_time).tz_convert(IST).strftime("%Y-%m-%d %H:%M")
        print(f"  {t.engine} {t.direction:<5} {ts} IST  "
              f"entry={t.entry_price:.2f}  sl={t.sl:.2f}  tp={t.tp:.2f}  +${t.pnl:.2f}")

    print()
    print("TOP 10 LOSSES (replay these to understand drawdowns):")
    for t in sorted(trades, key=lambda x: x.pnl)[:10]:
        ts = pd.Timestamp(t.entry_time).tz_convert(IST).strftime("%Y-%m-%d %H:%M")
        print(f"  {t.engine} {t.direction:<5} {ts} IST  "
              f"entry={t.entry_price:.2f}  sl={t.sl:.2f}  tp={t.tp:.2f}  ${t.pnl:.2f}")

    print()
    print(f"FXReplay tip: set chart to XAUUSD M5, replay from {start_date}.")
    print("At each signal time (IST), place the trade with the exact entry/SL/TP shown.")
    print("Use 'fxreplay_signals' as your checklist, 'fxreplay_trades' to verify fills.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-11-01")
    parser.add_argument("--end",   default="2026-04-16")
    args = parser.parse_args()
    export(args.start, args.end)

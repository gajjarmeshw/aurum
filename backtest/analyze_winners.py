"""
Empirical A+ Analyzer — find which features actually separate winners from losers.

Runs the walk-forward engine, simulates trades, then joins each closed trade
back to its originating setup to inspect the full feature set. For every
feature bucket we report WR_inclusive (full TP + 1R partial) and sample size.
A "real A+" bucket must have both high WR and enough samples to not be noise.

Usage:
    python -m backtest.analyze_winners --start 2026-04-01 --end 2026-04-22
"""

import argparse
import logging
from collections import defaultdict
from datetime import datetime, timezone

from backtest.walk_forward_engine import BacktestEngine, run_all_timeframes
from backtest.simulation_core import simulate_setups
import config

logging.basicConfig(level=logging.WARNING, format="%(message)s")


def _bucket_score(s: float) -> str:
    if s < 4.0:   return "3.8-4.0"
    if s < 4.5:   return "4.0-4.5"
    if s < 5.0:   return "4.5-5.0"
    if s < 5.5:   return "5.0-5.5"
    return "5.5+"


def _bucket_atr(a: float) -> str:
    if a < 12:  return "<12"
    if a < 16:  return "12-16"
    if a < 20:  return "16-20"
    if a < 25:  return "20-25"
    return "25+"


def _bucket_adx(a: float) -> str:
    if a < 15:  return "<15"
    if a < 20:  return "15-20"
    if a < 25:  return "20-25"
    if a < 30:  return "25-30"
    return "30+"


def _ist_hour(ts: int) -> int:
    dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
    return (dt_utc.hour + 5 + (1 if dt_utc.minute >= 30 else 0)) % 24


def _dow(ts: int) -> str:
    return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][
        datetime.fromtimestamp(ts, tz=timezone.utc).weekday()
    ]


def _dr_zone(setup: dict) -> str:
    """Where in the H4 dealing range did this trigger?"""
    levels = setup.get("levels", {})
    hi_list = levels.get("swing_highs_h4", [])
    lo_list = levels.get("swing_lows_h4", [])
    if not hi_list or not lo_list:
        return "unknown"
    dr_hi = hi_list[-1]["price"]
    dr_lo = lo_list[-1]["price"]
    if dr_hi <= dr_lo:
        return "unknown"
    pos = (setup["price"] - dr_lo) / (dr_hi - dr_lo)
    if pos < 0.3:  return "discount"   # bottom third
    if pos > 0.7:  return "premium"    # top third
    return "equilibrium"               # middle


def _aligned_dr(setup: dict) -> str:
    """ICT theory: longs in discount, shorts in premium == A+."""
    zone = _dr_zone(setup)
    is_long = "bullish" in setup.get("direction", "")
    if zone == "unknown":
        return "unknown"
    if is_long and zone == "discount":   return "aligned"
    if (not is_long) and zone == "premium": return "aligned"
    if zone == "equilibrium":           return "equilibrium"
    return "counter"   # long in premium / short in discount = chasing


def _feature_row(setup: dict, trade) -> dict:
    raw = setup.get("raw_score", {}) or {}
    swing = raw.get("swing", {}) if isinstance(raw, dict) else {}
    factors = swing.get("factors", {}) if isinstance(swing, dict) else {}
    return {
        "score":      float(setup.get("swing_score", 0.0)),
        "score_bkt":  _bucket_score(float(setup.get("swing_score", 0.0))),
        "mode":       trade.grade,
        "killzone":   setup.get("session", {}).get("killzone_name", "unknown"),
        "direction":  setup.get("direction", "unknown"),
        "tf":         setup.get("primary_tf", "M15"),
        "atr":        float(setup.get("atr", 0.0)),
        "atr_bkt":    _bucket_atr(float(setup.get("atr", 0.0))),
        "adx":        float(setup.get("adx", 0.0)),
        "adx_bkt":    _bucket_adx(float(setup.get("adx", 0.0))),
        "dow":        _dow(int(setup.get("timestamp", 0))),
        "hour_ist":   _ist_hour(int(setup.get("timestamp", 0))),
        "dr_zone":    _dr_zone(setup),
        "dr_align":   _aligned_dr(setup),
        "sweep_score":    factors.get("liquidity_sweep", {}).get("score", 0),
        "fvg_ob_score":   factors.get("fvg_ob_overlap", {}).get("score", 0),
        "bos_score":      factors.get("h1_bos", {}).get("score", 0),
    }


def _bucket_stats(rows: list, key: str) -> list:
    """Return list of dicts: {bucket, n, wins, partial, loss, wr_full, wr_incl, avg_pnl}."""
    g = defaultdict(list)
    for r in rows:
        g[r[key]].append(r)
    out = []
    for bkt, items in g.items():
        n = len(items)
        wins    = sum(1 for i in items if i["result"] == "win")
        partial = sum(1 for i in items if i["result"] == "be" and i["realized_pnl"] > 0)
        loss    = sum(1 for i in items if i["result"] == "loss")
        pnl_total = sum(i["pnl"] for i in items)
        out.append({
            "bucket":  str(bkt),
            "n":       n,
            "wins":    wins,
            "partial": partial,
            "loss":    loss,
            "wr_full": (wins / n * 100) if n else 0.0,
            "wr_incl": ((wins + partial) / n * 100) if n else 0.0,
            "avg_pnl": (pnl_total / n) if n else 0.0,
            "total_pnl": pnl_total,
        })
    return sorted(out, key=lambda x: -x["wr_incl"])


def _print_table(title: str, stats: list, min_n: int = 2):
    print(f"\n── {title} ── (showing buckets with n >= {min_n})")
    print(f"{'bucket':<20} {'n':>4} {'W':>3} {'P':>3} {'L':>3} "
          f"{'wr_full':>8} {'wr_incl':>8} {'avg_pnl':>9} {'total':>9}")
    print("-" * 84)
    for s in stats:
        if s["n"] < min_n:
            continue
        print(f"{s['bucket']:<20} {s['n']:>4} {s['wins']:>3} {s['partial']:>3} "
              f"{s['loss']:>3} {s['wr_full']:>7.1f}% {s['wr_incl']:>7.1f}% "
              f"${s['avg_pnl']:>7.2f} ${s['total_pnl']:>7.2f}")


def analyze(start_date: str, end_date: str, tf: str = "all"):
    data_dir = str(config.BASE_DIR / "backtest" / "data")

    # ── Collect setups + trades ─────────────────────────────────────────
    if tf == "all":
        setups, engines = run_all_timeframes(data_dir, start_date, end_date)
        primary_engine = engines.get("15min") or next(iter(engines.values()))
        full_df = primary_engine.full_df
        tf_label = "M15+H1"
    else:
        fname = {"M5": "XAUUSD_5min.csv", "M15": "XAUUSD_15min.csv",
                 "H1": "XAUUSD_1h.csv"}[tf]
        eng = BacktestEngine(f"{data_dir}/{fname}",
                             timeframe={"M5": "5min", "M15": "15min", "H1": "1h"}[tf],
                             start_date=start_date, end_date=end_date)
        setups = eng.run()
        full_df = eng.full_df
        tf_label = tf

    sim_result = simulate_setups(setups, full_df, tf_label=tf_label)
    trades = sim_result["trades"]
    summary = sim_result["summary"]
    setup_by_id = sim_result.get("setup_by_trade_id", {})

    rows = []
    for trade in trades:
        setup = setup_by_id.get(trade.id)
        if not setup:
            continue
        feat = _feature_row(setup, trade)
        feat["result"]       = trade.result
        feat["pnl"]          = trade.pnl
        feat["realized_pnl"] = trade.realized_pnl
        rows.append(feat)

    print("=" * 84)
    print(f"EMPIRICAL A+ ANALYSIS   {start_date} → {end_date}   TF={tf_label}")
    print("=" * 84)
    print(f"Total trades matched: {len(rows)} / {len(trades)} closed")
    print(f"Summary: {summary['total_trades']} trades | "
          f"WR {summary['win_rate']} | PnL {summary['total_pnl']}")

    if not rows:
        print("No trades to analyze.")
        return

    # Core buckets — does score actually separate winners?
    _print_table("SCORE BUCKET (is score ≥ 4.5 really A+?)",
                 _bucket_stats(rows, "score_bkt"), min_n=1)

    _print_table("KILLZONE (time of day edge)",
                 _bucket_stats(rows, "killzone"), min_n=2)

    _print_table("DAY OF WEEK",
                 _bucket_stats(rows, "dow"), min_n=2)

    _print_table("DIRECTION",
                 _bucket_stats(rows, "direction"), min_n=1)

    _print_table("MODE (Swing vs Scalp)",
                 _bucket_stats(rows, "mode"), min_n=1)

    _print_table("ATR BUCKET (volatility regime)",
                 _bucket_stats(rows, "atr_bkt"), min_n=2)

    _print_table("ADX BUCKET (trend strength)",
                 _bucket_stats(rows, "adx_bkt"), min_n=2)

    _print_table("DEALING RANGE ZONE (premium / discount / equilibrium)",
                 _bucket_stats(rows, "dr_zone"), min_n=1)

    _print_table("DR ALIGNMENT (long=discount / short=premium = A+?)",
                 _bucket_stats(rows, "dr_align"), min_n=1)

    _print_table("PRIMARY TF",
                 _bucket_stats(rows, "tf"), min_n=1)

    # Hour-of-day heat map
    _print_table("HOUR OF DAY (IST)",
                 _bucket_stats(rows, "hour_ist"), min_n=1)

    # Cross-tab: score × dr_align (true A+ candidate filter)
    combo = defaultdict(list)
    for r in rows:
        combo[f"{r['score_bkt']} × {r['dr_align']}"].append(r)
    out = []
    for k, items in combo.items():
        n = len(items)
        wins    = sum(1 for i in items if i["result"] == "win")
        partial = sum(1 for i in items if i["result"] == "be" and i["realized_pnl"] > 0)
        loss    = sum(1 for i in items if i["result"] == "loss")
        pnl     = sum(i["pnl"] for i in items)
        out.append({"bucket": k, "n": n, "wins": wins, "partial": partial,
                    "loss": loss, "wr_full": wins/n*100, "wr_incl": (wins+partial)/n*100,
                    "avg_pnl": pnl/n, "total_pnl": pnl})
    _print_table("SCORE × DR-ALIGNMENT (combined A+ filter)",
                 sorted(out, key=lambda x: -x["wr_incl"]), min_n=2)

    # Individual trades dump for manual review
    print("\n── INDIVIDUAL TRADES (sorted by pnl asc — worst losers first) ──")
    print(f"{'idx':>3} {'result':<7} {'pnl':>8} {'score':>5} {'tf':>3} "
          f"{'mode':<6} {'kz':<14} {'dr':<10} {'atr':>5} {'dow':<3} {'hr':>3}")
    for i, r in enumerate(sorted(rows, key=lambda x: x["pnl"])):
        print(f"{i:>3} {r['result']:<7} ${r['pnl']:>6.2f} {r['score']:>5.2f} "
              f"{r['tf']:>3} {r['mode']:<6} {r['killzone']:<14} {r['dr_align']:<10} "
              f"{r['atr']:>5.1f} {r['dow']:<3} {r['hour_ist']:>3}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2026-04-01")
    parser.add_argument("--end",   default="2026-04-22")
    parser.add_argument("--tf",    default="all", choices=["M5", "M15", "H1", "all"])
    args = parser.parse_args()
    analyze(args.start, args.end, args.tf)

"""
Unified Simulation Core — Single source of truth for backtest execution.

Used by BOTH:
  - backtest/run_audit.py  (CLI)
  - server/app.py          (GUI /api/backtest/run)

Rules enforced (must match live trading exactly):
  1. Session gate     — killzone_active required
  2. ATR gates        — swing: ATR_SWING_MIN (8) ≤ atr ≤ ATR_NORMAL_MAX (35); scalp: atr ≤ SCALP_ATR_GATE (22)
  3. Score gates      — swing >= SWING_SCORE_MIN_BACKTEST, scalp >= 3.0
  4. Short-term trend — DISABLED (momentum mode; _short_term_trend() available)
  5. Mode cooldown    — SWING_COOLDOWN / SCALP_COOLDOWN (stamped on SEEN)
  6. Daily caps       — DAILY_LOSS_HARD_CAP + DAILY_HARD_CAP
  7. Daily trade cap  — MAX_TRADES_PER_DAY (2 per plan)
  8. Loss-streak stop — 2 losses in a day → skip rest of day (1 recovery trade allowed)
  9. One per killzone — first valid setup only, no rebounds
 10. Lot sizing       — scalp 0.05, swing 0.03 (mode-specific)
 11. SL placement     — structural swing L/H with ATR floor + cap
 12. Next-bar confirm — require next bar close in direction of signal
 13. Entry            — market fill at confirmation bar close
 14. TP               — SL distance × RR (2.5 swing / 1.5 scalp)
"""

import math
import logging
import pandas as pd
from datetime import datetime, timezone

import config
from backtest.trade_simulator import TradeSimulator

logger = logging.getLogger(__name__)


def _bar_date(ts_or_str) -> str:
    """Return YYYY-MM-DD string from a unix timestamp or datetime string."""
    if isinstance(ts_or_str, (int, float)):
        return datetime.fromtimestamp(ts_or_str, tz=timezone.utc).strftime("%Y-%m-%d")
    try:
        return str(pd.to_datetime(ts_or_str).date())
    except Exception:
        return str(ts_or_str)[:10]


def _setup_dr_zone(setup: dict) -> str:
    """Return "discount" | "equilibrium" | "premium" | "unknown" from setup's H4 swings."""
    levels = setup.get("levels", {}) or {}
    hi_list = levels.get("swing_highs_h4", [])
    lo_list = levels.get("swing_lows_h4", [])
    if not hi_list or not lo_list:
        return "unknown"
    dr_hi = hi_list[-1]["price"]
    dr_lo = lo_list[-1]["price"]
    if dr_hi <= dr_lo:
        return "unknown"
    pos = (float(setup["price"]) - dr_lo) / (dr_hi - dr_lo)
    if pos < 0.3:
        return "discount"
    if pos > 0.7:
        return "premium"
    return "equilibrium"


def _short_term_trend(full_df: pd.DataFrame, bar_idx: int, lookback: int = 60) -> str:
    """
    Short-term trend over the last ~60 M5 bars (~5 hours).
    Compares mean of first half vs second half of window.
    Returns "up", "down", or "flat". Flat = no filter applied.

    This is responsive enough to flip with market structure, unlike the
    old 4-day H4 filter which froze out valid trades for weeks.
    """
    if bar_idx < lookback:
        return "flat"
    window = full_df.iloc[bar_idx - lookback: bar_idx + 1]
    closes = window["close"].values
    half = len(closes) // 2
    first = closes[:half].mean()
    second = closes[half:].mean()
    # 0.15% threshold — meaningful move, not noise
    if second > first * 1.0015:
        return "up"
    if second < first * 0.9985:
        return "down"
    return "flat"



def simulate_setups(setups: list, full_df: pd.DataFrame, tf_label: str = "M5") -> dict:
    """
    Run the unified simulation over a list of setups from the walk-forward engine.

    Parameters
    ----------
    setups   : output of BacktestEngine.run()
    full_df  : BacktestEngine.full_df  (needed for trade update loop)
    tf_label : timeframe label for reporting (e.g. "M15")

    Returns
    -------
    dict with keys: summary, trades, skipped_counts
    """
    sim = TradeSimulator()
    setup_by_trade_id: dict[int, dict] = {}

    # Cooldown tracking — updated when a setup is SEEN (not when trade closes).
    # This fixes the bug where back-to-back setups during an open trade would
    # skip the cooldown check and cluster losses.
    last_swing_ts: float = 0.0
    last_scalp_ts: float = 0.0

    # Daily accounting  {date_str: {"pnl", "trades", "losses", "killzones"}}
    daily: dict = {}

    # Diagnostic counters
    skipped = {
        "no_mode": 0,
        "atr_abnormal": 0,
        "scalp_low_score": 0,
        "swing_low_score": 0,
        "no_killzone": 0,
        "trend_counter": 0,
        "cooldown": 0,
        "daily_loss_cap": 0,
        "daily_profit_cap": 0,
        "daily_trade_cap": 0,
        "daily_loss_streak": 0,
        "killzone_used": 0,
        "concurrent_open": 0,
        "no_confirmation": 0,
        "missing_core_confluence": 0,
        "v6_skip_h1": 0,
        "v6_skip_london_open": 0,
        "v6_asian_scalp": 0,
        "v6_atr_band": 0,
        "v6_adx_band": 0,
        "v6_score_low": 0,
        "v6_dr_aligned": 0,
    }
    v6 = getattr(config, "STRATEGY_V6_ENABLED", False)

    for setup in setups:
        # ── 0. Block if a trade is still open (one trade at a time) ──────────
        if sim.open_trades:
            skipped["concurrent_open"] += 1
            continue

        is_swing    = setup.get("is_swing", False)
        is_scalp    = setup.get("is_scalp", False)
        is_momentum = setup.get("is_momentum", False) and v6
        # Priority: SWING > MOMENTUM > SCALP.  Same bar can qualify multiple
        # ways; we take the highest-grade label so sizing/TP rules are right.
        if is_swing:
            setup_mode = "SWING"
        elif is_momentum:
            setup_mode = "MOMENTUM"
        elif is_scalp:
            setup_mode = "SCALP"
        else:
            setup_mode = None

        if not setup_mode:
            skipped["no_mode"] += 1
            continue

        # ── V6 pre-filters (see config.V6_*) ───────────────────────────────
        if v6:
            if (config.V6_SKIP_H1_PRIMARY
                    and setup.get("primary_tf") == "H1"):
                skipped["v6_skip_h1"] += 1
                continue

            kz_name = setup.get("session", {}).get("killzone_name") or ""
            if config.V6_SKIP_LONDON_OPEN and kz_name == "London Open":
                skipped["v6_skip_london_open"] += 1
                continue
            if (setup_mode == "SCALP"
                    and config.V6_SKIP_ASIAN_SCALP
                    and kz_name == "Asian Session"):
                skipped["v6_asian_scalp"] += 1
                continue

            atr_v6 = float(setup.get("atr", 0.0) or 0.0)
            if any(lo <= atr_v6 < hi for (lo, hi) in config.V6_SKIP_ATR_BANDS):
                skipped["v6_atr_band"] += 1
                continue

            adx_v6 = float(setup.get("adx", 0.0) or 0.0)
            band_lo, band_hi = config.V6_SKIP_ADX_BAND
            if band_lo <= adx_v6 < band_hi:
                skipped["v6_adx_band"] += 1
                continue

            # Momentum bypasses the score floor — it's defined by structure + regime.
            if setup_mode == "SWING":
                if float(setup.get("swing_score", 0.0)) < config.V6_SWING_SCORE_MIN:
                    skipped["v6_score_low"] += 1
                    continue

            dr_zone = _setup_dr_zone(setup)
            if config.V6_SKIP_DR_ALIGNED:
                is_long_dir = "bullish" in setup.get("direction", "")
                if (is_long_dir and dr_zone == "discount") or \
                   ((not is_long_dir) and dr_zone == "premium"):
                    skipped["v6_dr_aligned"] += 1
                    continue
        else:
            dr_zone = None

        # ── 1. ATR sanity — skip low-vol AND extreme-volatility sessions ───────
        atr = setup.get("atr", 15.0) or 15.0
        if atr > config.ATR_NORMAL_MAX:
            skipped["atr_abnormal"] += 1
            continue
        # Swing-specific ATR floor: skip dead-market setups
        if setup_mode == "SWING" and atr < config.ATR_SWING_MIN:
            skipped["atr_abnormal"] += 1
            continue
        # Scalp-specific regime gate: skip scalps in elevated volatility
        # Gold's normal H1 ATR is 16-22pt; above the gate means expansion/trending, no scalp
        if setup_mode == "SCALP" and atr > config.SCALP_ATR_GATE:
            skipped["atr_abnormal"] += 1
            continue
        # Momentum requires high ATR by definition; re-check in case setup was
        # tagged from a different source
        if setup_mode == "MOMENTUM" and atr < config.V6_MOMENTUM_MIN_ATR:
            skipped["atr_abnormal"] += 1
            continue

        # ── 2. Score quality gates ───────────────────────────────────────────
        raw = setup.get("raw_score", {})
        if setup_mode == "SCALP":
            # is_valid already guarantees all 3 gates + killzone + sanity passed in walk_forward_engine.
            # score == 3.0 when all gates pass; score_min = 3.0 enforces full 3-gate requirement.
            scalp_score = raw.get("scalp", {}).get("score", 0) if isinstance(raw, dict) else 0
            scalp_valid_flag = raw.get("scalp", {}).get("is_valid", False) if isinstance(raw, dict) else False
            if not scalp_valid_flag or float(scalp_score) < config.SCALP_RISK.get("score_min", 3.0):
                skipped["scalp_low_score"] += 1
                continue
        elif setup_mode == "MOMENTUM":
            # Momentum bypasses the sweep requirement but still needs H1 BOS +
            # M15 FVG (checked upstream in walk_forward_engine).  No score gate.
            pass
        else:  # SWING
            swing_score = float(setup.get("swing_score", 0))
            if swing_score < config.SWING_SCORE_MIN_BACKTEST:
                skipped["swing_low_score"] += 1
                continue

            # ── ICT Hard Gates: sweep + FVG/OB are non-negotiable ────────────
            # Score 3.8 can be reached without a sweep (h1_bos+fvg_ob+killzone=4.0)
            # or without FVG/OB (sweep+h1_bos+killzone=4.5). Both are invalid ICT entries.
            swing_factors = raw.get("swing", {}).get("factors", {}) if isinstance(raw, dict) else {}
            has_sweep  = swing_factors.get("liquidity_sweep", {}).get("score", 0) > 0
            has_fvg_ob = swing_factors.get("fvg_ob_overlap",  {}).get("score", 0) > 0
            if not has_sweep or not has_fvg_ob:
                skipped["missing_core_confluence"] += 1
                continue

        # ── 3. Session gate — killzone required ──────────────────────────────
        session_info = setup.get("session", {})
        if not session_info.get("killzone_active"):
            skipped["no_killzone"] += 1
            continue

        killzone_name = session_info.get("killzone_name", "unknown")

        direction = setup.get("direction", "bullish")
        is_long = "bullish" in direction
        bar_idx = setup["bar_index"]
        setup_ts = float(setup.get("timestamp", 0))
        price = float(setup["price"])

        # ── 4. Trend filter — toggled by config.TREND_FILTER_ENABLED ────────
        # 5m : keep False — ICT 5m entries counter-momentum by design (sweep → reverse)
        # 15m: set True  — 15m structure aligns with trend, filter cuts 42% loss rate
        if config.TREND_FILTER_ENABLED:
            trend = _short_term_trend(full_df, bar_idx)
            if is_long and trend == "down":
                skipped["trend_counter"] += 1
                continue
            if not is_long and trend == "up":
                skipped["trend_counter"] += 1
                continue

        # ── 5. Mode cooldown (update on SEEN, not on close) ─────────────────
        # MOMENTUM shares the swing cooldown bucket — both are HTF structural
        # trades and clustering them would concentrate risk on one move.
        if setup_mode in ("SWING", "MOMENTUM"):
            if setup_ts - last_swing_ts < config.SWING_COOLDOWN_SECONDS:
                skipped["cooldown"] += 1
                continue
        else:
            if setup_ts - last_scalp_ts < config.SCALP_COOLDOWN_SECONDS:
                skipped["cooldown"] += 1
                continue

        if setup_mode in ("SWING", "MOMENTUM"):
            last_swing_ts = setup_ts
        else:
            last_scalp_ts = setup_ts

        # ── 6 & 7. Daily caps + trade count + loss-streak stop ──────────────
        trade_date = _bar_date(setup_ts)
        day = daily.setdefault(
            trade_date,
            {"pnl": 0.0, "trades": 0, "losses": 0, "killzones": set()},
        )

        if day["pnl"] <= -config.DAILY_LOSS_HARD_CAP:
            skipped["daily_loss_cap"] += 1
            continue
        if day["pnl"] >= config.DAILY_HARD_CAP:
            skipped["daily_profit_cap"] += 1
            continue
        if day["trades"] >= config.MAX_TRADES_PER_DAY:
            skipped["daily_trade_cap"] += 1
            continue
        # After 2 losses in a day, stop — 1 recovery trade allowed after first loss.
        # At $25 risk this is only $50 max drawdown vs $500 daily cap, well within rules.
        if day["losses"] >= 2:
            skipped["daily_loss_streak"] += 1
            continue

        # ── 7b. First-valid-per-killzone-session rule ───────────────────────
        # Once we've taken a trade in this killzone on this day, no rebounds.
        if killzone_name in day["killzones"]:
            skipped["killzone_used"] += 1
            continue

        # ── 8. SL calculation — H1 structural levels + ATR bounds ─────────────
        # NOTE: swing_highs_m15/swing_lows_m15 are NOT in indicators.to_dict().
        # Use H1 levels which ARE serialised — they are wider and more robust.
        levels   = setup.get("levels", {})
        h1_highs = levels.get("swing_highs_h1", [])
        h1_lows  = levels.get("swing_lows_h1", [])

        if setup_mode in ("SWING", "MOMENTUM"):
            rp       = config.SWING_RISK
            tp_rr    = rp.get("tp_rr", 2.5)
            # Floor = 0.75×ATR — outside routine H1 noise without over-sizing the stop
            sl_floor = atr * 0.75
            # Hard cap: never wider than 2×ATR (protects daily loss cap)
            sl_cap   = atr * 2.0

            if is_long:
                structural = h1_lows[-1]["price"] if h1_lows else (price - sl_floor)
                raw_sl_dist = max(price - structural, sl_floor)
            else:
                structural = h1_highs[-1]["price"] if h1_highs else (price + sl_floor)
                raw_sl_dist = max(structural - price, sl_floor)

            sl_dist = min(max(raw_sl_dist, rp.get("min_sl_distance", 8.0)), sl_cap)

        else:  # SCALP (only runs when ATR <= 15pt, checked above)
            rp      = config.SCALP_RISK
            tp_rr   = rp.get("tp_rr", 2.0)
            # Fixed 8pt SL in calm markets — clean and predictable
            sl_dist = float(rp.get("sl_distance", 8.0))

        # ── 9. Risk-based lot sizing — capped at MAX_RISK_TRADE1 ─────────────
        # Size lots so max loss == risk_per_trade regardless of SL width.
        mode_max = config.SCALP_RISK["lots"] if setup_mode == "SCALP" else config.SWING_RISK["lots"]
        risk_budget = config.SESSION_EXPANSION.get("risk_per_trade", config.MAX_RISK_TRADE1)
        lots_raw = risk_budget / (sl_dist * 100)
        lots     = min(math.ceil(lots_raw * 100) / 100, mode_max)
        lots     = max(lots, 0.01)

        # V6 Power Sizing: score + ATR + DR equilibrium triple-filter slice
        # earns permission to size up (see config.V6_POWER_*).
        if v6 and setup_mode in ("SWING", "MOMENTUM"):
            if (float(setup.get("swing_score", 0.0)) >= config.V6_POWER_MIN_SCORE
                    and atr >= config.V6_POWER_MIN_ATR
                    and dr_zone in config.V6_POWER_DR_ZONES):
                lots = min(config.V6_POWER_LOTS, mode_max)

        # Step down one tick if ceiling pushed us over the daily cap
        if sl_dist * lots * 100 > config.DAILY_LOSS_HARD_CAP:
            lots = max(lots - 0.01, 0.01)
        # If still over, skip — cannot fit within cap at minimum size
        if sl_dist * lots * 100 > config.DAILY_LOSS_HARD_CAP:
            continue

        if sl_dist < 4.0:   # degenerate SL — skip
            continue

        # ── 10. MT Entry — midpoint limit, 3-bar window ──────────────────────
        trigger_bar  = full_df.iloc[bar_idx]
        mt_price     = (trigger_bar["high"] + trigger_bar["low"]) / 2.0
        entry_price  = None
        triggered_bar_idx = None

        for look_idx in range(bar_idx + 1, min(bar_idx + 4, len(full_df))):
            look_bar = full_df.iloc[look_idx]
            if is_long     and look_bar["low"]  <= mt_price:
                entry_price = mt_price;  triggered_bar_idx = look_idx;  break
            if not is_long and look_bar["high"] >= mt_price:
                entry_price = mt_price;  triggered_bar_idx = look_idx;  break

        if entry_price is None:
            skipped["no_confirmation"] += 1
            continue

        # ── 11. Final SL/TP from MT entry price ──────────────────────────────
        trade_dir = "long" if is_long else "short"
        sl = (entry_price - sl_dist) if is_long else (entry_price + sl_dist)
        tp = (entry_price + sl_dist * tp_rr) if is_long else (entry_price - sl_dist * tp_rr)

        # ── Stamp killzone as used (prevents rebounds in same session) ─────
        day["killzones"].add(killzone_name)

        # ── Open the trade ───────────────────────────────────────────────────
        sim.open_trade(
            time=str(full_df.iloc[triggered_bar_idx]["datetime"]),
            price=entry_price,
            sl=sl,
            tp=tp,
            direction=trade_dir,
            lots=lots,
            session=session_info.get("session_label", "Unknown"),
            grade=setup_mode.title(),
            setup_reason=f"ICT {setup_mode} Confirmation",
            risk_factors=f"Score:{setup.get('swing_score', 0.0) if setup_mode == 'SWING' else 3.0}",
            timeframe=tf_label # I need to capture tf_label in simulate_setups scope
        )
        if sim.open_trades:
            setup_by_trade_id[sim.open_trades[-1].id] = setup

        # ── Walk forward until trade closes ──────────────────────────────────
        trades_before = len(sim.closed_trades)
        for k in range(triggered_bar_idx + 1, len(full_df)):
            bar = full_df.iloc[k]
            sim.update(
                str(bar["datetime"]), bar["high"], bar["low"], bar["close"],
                score=setup.get("swing_score", 0.0)
            )
            if not sim.open_trades: break

        # ── Update daily accounting — only if THIS trade actually closed ────
        if len(sim.closed_trades) > trades_before:
            last_trade = sim.closed_trades[-1]
            pnl = last_trade.pnl
            day["pnl"] = round(day["pnl"] + pnl, 2)
            day["trades"] += 1
            if pnl < 0:
                day["losses"] += 1

    summary = sim.get_summary()
    total_pnl_float = sum(t.pnl for t in sim.closed_trades)

    # Derive weeks from actual min/max across all closed trade timestamps.
    # trades may close out of entry-order once we have MOMENTUM setups that
    # run alongside swings; min/max is more robust than first/last.
    if sim.closed_trades:
        entry_series = pd.to_datetime([t.entry_time for t in sim.closed_trades])
        exit_series  = pd.to_datetime([t.exit_time or t.entry_time for t in sim.closed_trades])
        first_dt = entry_series.min()
        last_dt  = exit_series.max()
        weeks = max((last_dt - first_dt).days / 7.0, 1.0)
    else:
        weeks = 1.0

    logger.info(
        f"Simulation complete: {summary['total_trades']} trades | "
        f"WR {summary['win_rate']} | PnL {summary['total_pnl']}"
    )
    logger.info(f"Skipped: {skipped}")

    return {
        "summary": summary,
        "trades": sim.closed_trades,
        "skipped": skipped,
        "weekly_avg": f"${total_pnl_float / weeks:.2f}",
        "setup_by_trade_id": setup_by_trade_id,
    }

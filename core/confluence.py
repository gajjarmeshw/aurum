"""
Confluence Scorer — Weighted 12-point system.

Phase 1: Theory weights from config.
Phase 2: Auto-calibrated weights from journal data (after 30 trades).
"""

import logging

import config
from core.indicators import IndicatorResult, detect_swings

logger = logging.getLogger(__name__)


def compute_confluence(indicators: IndicatorResult, ict_result: dict,
                        dealing_range: dict, session_info: dict,
                        macro_data: dict, current_price: float) -> dict:
    """
    Dual-Mode Confluence Scorer:
    Mode 1: Swing (5 Factors, max 6.5)
    Mode 2: Scalp (3 Binary Gates: Bias, Setup, Trigger)
    """
    
    # ─── MODE 1: SWING (5-Factor Simplified) ──────────────────
    w = config.SWING_WEIGHTS
    factors = {}

    # 1. Liquidity sweep present (Recent: last 20 candles = 5 hours)
    last_ts = indicators.m15_candles[-1].get("timestamp", 0) if indicators.m15_candles else 0
    MAX_SWEEP_AGE = 5 * 3600 
    
    swept = False
    sweep_detail = "No recent sweep"
    if indicators.liquidity_pools:
        for p in indicators.liquidity_pools:
            if p.swept and (last_ts - p.sweep_timestamp) <= MAX_SWEEP_AGE:
                swept = True
                sweep_detail = f"Recent {p.type} sweep"
                break

    # BOS-as-sweep: if H1 BOS is confirmed with no unswept BSL above price,
    # the BOS itself proves BSL was already taken (ICT: BOS happens because price swept prior highs)
    if not swept and indicators.bos_h1:
        bos_direction = indicators.bos_h1[-1].direction
        no_bsl_above  = not any(p.type == "BSL" and not p.swept for p in indicators.liquidity_pools)
        if bos_direction == "bullish" and no_bsl_above:
            swept = True
            sweep_detail = f"BOS implies BSL swept (H1 BOS @ ${indicators.bos_h1[-1].price:.2f})"
        elif bos_direction == "bearish" and not any(p.type == "SSL" and not p.swept for p in indicators.liquidity_pools):
            swept = True
            sweep_detail = f"BOS implies SSL swept (H1 BOS @ ${indicators.bos_h1[-1].price:.2f})"

    factors["liquidity_sweep"] = {
        "weight": w.get("liquidity_sweep", 2.0),
        "score": w.get("liquidity_sweep", 2.0) if swept else 0.0,
        "status": "✅" if swept else "❌",
        "detail": sweep_detail,
    }

    # 2. H1 BOS confirmed
    has_bos = len(indicators.bos_h1) > 0
    factors["h1_bos"] = {
        "weight": w.get("h1_bos", 1.5),
        "score": w.get("h1_bos", 1.5) if has_bos else 0.0,
        "status": "✅" if has_bos else "❌",
        "detail": f"{indicators.bos_h1[-1].direction} @ ${indicators.bos_h1[-1].price:.2f}" if has_bos else "No BOS",
    }

    # 3. FVG + OB overlap
    fvg_ob_overlap = _check_fvg_ob_overlap(indicators, current_price)
    factors["fvg_ob_overlap"] = {
        "weight": w.get("fvg_ob_overlap", 1.5),
        "score": round(w.get("fvg_ob_overlap", 1.5) * fvg_ob_overlap.get("score_mult", 0.0), 2),
        "status": fvg_ob_overlap.get("status", "❌"),
        "detail": fvg_ob_overlap.get("detail", "No FVG+OB overlap"),
    }

    # 4. Killzone timing
    kz_active = session_info.get("killzone_active", False)
    factors["killzone_timing"] = {
        "weight": w.get("killzone_timing", 1.0),
        "score": w.get("killzone_timing", 1.0) if kz_active else 0.0,
        "status": "✅" if kz_active else "❌",
        "detail": session_info.get("killzone_name") or session_info.get("session_label") or "Outside killzone",
    }

    # 5. DXY alignment
    dxy_aligned = macro_data.get("dxy_aligned", False)
    factors["dxy_alignment"] = {
        "weight": w.get("dxy_alignment", 0.5),
        "score": w.get("dxy_alignment", 0.5) if dxy_aligned else 0.0,
        "status": "✅" if dxy_aligned else "❌",
        "detail": macro_data.get("dxy_detail", "No data"),
    }

    total_swing = round(sum(f["score"] for f in factors.values()), 1)
    
    # Baseline Price Sanity
    last_close = indicators.m5_candles[-2]["close"] if len(indicators.m5_candles) >= 2 else current_price
    price_delta = abs(current_price - last_close)
    sanity_ok = price_delta < 50.0

    swing_mode = {
        "score": total_swing,
        "max_score": config.SWING_SCORE_MAX,
        "is_valid": (total_swing >= config.SWING_SCORE_MIN_LIVE) and sanity_ok,
        "factors": factors
    }

    # ─── MODE 2: SCALP (3-Gate System) ────────────────────────
    
    # Gate 1: Direction (M5 Bias for maximum frequency)
    swing_highs_m5, swing_lows_m5 = detect_swings(indicators.m5_candles)
    m5_all = indicators.bos_m5 + indicators.choch_m5
    m5_all.sort(key=lambda x: x.index)
    m5_dir = m5_all[-1].direction if m5_all else "neutral"
    
    bias_dir = m5_dir
    is_bullish_bias = "bullish" in bias_dir
    is_bearish_bias = "bearish" in bias_dir
    gate1_pass = is_bullish_bias or is_bearish_bias

    # Gate 2: M15 Setup (FVG, OB, or Internal Sweep)
    # Relaxed for higher frequency: also accepts any M15 sweep as a valid "setup".
    setup_ok = False
    setup_str = "No M15 Setup"
    
    m15_swept_correct = any(p.swept for p in indicators.liquidity_pools)

    if indicators.fvgs_m15 and not indicators.fvgs_m15[-1].filled:
        setup_ok = True
        setup_str = "M15 FVG"
    elif indicators.obs_m15 and not indicators.obs_m15[-1].mitigated:
        setup_ok = True
        setup_str = "M15 OB"
    elif m15_swept_correct:
        setup_ok = True
        setup_str = "M15 Liquidity Sweep"
    
    gate2_pass = setup_ok

    # Gate 3: Trigger (M5 BOS + Displacement)
    gate3_pass = False
    trigger_detail = "Waiting for M5 break + FVG"
    
    has_m5_bos = False
    if indicators.bos_m5:
        last_m5_bos = indicators.bos_m5[-1].direction
        if (is_bullish_bias and last_m5_bos == "bullish") or (is_bearish_bias and last_m5_bos == "bearish"):
            has_m5_bos = True
            
    # Gate 3B: Displacement — FVG must be FRESH (within the last N M5 candles)
    # Using a lookback window instead of index comparison because BOS.index is
    # always stored as len(candles)-1, making direct index comparison unreliable.
    # A "fresh" FVG = formed within the last N M5 bars (e.g. 15 bars = ~75 minutes).
    has_displacement = False
    target_dir = "bullish" if is_bullish_bias else "bearish"
    lookback = config.SCALP_RISK.get("displacement_lookback", 20)

    if has_m5_bos and indicators.fvgs_m5:
        if indicators.m5_candles:
            min_fresh_index = max(0, len(indicators.m5_candles) - lookback)
        else:
            min_fresh_index = 0
        fresh_fvgs = [
            f for f in indicators.fvgs_m5
            if f.direction == target_dir
            and not f.filled
            and f.index >= min_fresh_index
        ]
        if fresh_fvgs:
            has_displacement = True

    if has_m5_bos and has_displacement:
        gate3_pass = True
        trigger_detail = f"✅ M5 {target_dir.title()} BOS + FVG"
    elif has_m5_bos:
        trigger_detail = "⚠️ BOS confirmed, waiting for FVG displacement"

    # ── SCALP KILLZONE GUARD ──────────────────────────────────────
    kz_active_for_scalp = session_info.get("killzone_active", False)

    # ── SCALP CONFLUENCE GUARD ────────────────────────────────────
    # Even if gates pass, we want some HTF confirmation (Confluence Score)
    # to avoid trading noise in weak market environments.
    confluence_ok = total_swing >= config.SCALP_RISK.get("min_confluence", 2.0)

    scalp_gates_passed = sum([gate1_pass, gate2_pass, gate3_pass])
    scalp_mode = {
        "is_valid": gate1_pass and gate2_pass and gate3_pass and sanity_ok and kz_active_for_scalp and confluence_ok,
        "score": float(scalp_gates_passed),   # 3.0 when all gates pass; gated at 3.0 in simulation
        "gates": {
             "bias": {
                 "pass": gate1_pass, 
                 "detail": bias_dir.title() if gate1_pass else "No Fractal Bias",
                 "status": "✅" if gate1_pass else "❌"
             },
             "setup": {
                 "pass": gate2_pass, 
                 "detail": setup_str,
                 "status": "✅" if gate2_pass else "❌"
             },
             "trigger": {
                 "pass": gate3_pass, 
                 "detail": trigger_detail,
                 "status": "✅" if gate3_pass else "❌"
             }
        }
    }

    # ── LONDON TRANSITION SIGNAL ─────────────────────────────────
    # Fires during dead zone IF a sweep already happened and M5 BOS
    # hasn't confirmed yet — tells you to prep for London open.
    is_dead = session_info.get("session_label", "").startswith("Dead Zone")
    target_type_for_london = "SSL" if is_bullish_bias else "BSL"
    london_sweep_ready = any(
        p.swept and p.type == target_type_for_london
        for p in indicators.liquidity_pools
    )
    london_potential = is_dead and london_sweep_ready and not gate3_pass

    return {
        "swing": swing_mode,
        "scalp": scalp_mode,
        # Legacy mappings for seamless UI transition
        "total": total_swing,
        "maximum": config.SWING_SCORE_MAX,
        "factors": factors,
        "tradeable": swing_mode["is_valid"] or scalp_mode["is_valid"],
        "direction": bias_dir,
        "london_potential": london_potential,
        "london_msg": "⏰ LONDON SETUP FORMING: Sweep confirmed. Waiting for MSS." if london_potential else ""
    }

def _check_fvg_ob_overlap(indicators: IndicatorResult, price: float) -> dict:
    """Check if any FVG overlaps with any OB near current price."""
    all_fvgs = indicators.fvgs_h1 + indicators.fvgs_m15
    all_obs = indicators.obs_h4 + indicators.obs_h1 + indicators.obs_m15

    for fvg in all_fvgs:
        if fvg.filled:
            continue
        for ob in all_obs:
            if ob.mitigated:
                continue
            
            if abs(fvg.low - price) > 500:
                continue

            overlap_high = min(fvg.high, ob.high)
            overlap_low = max(fvg.low, ob.low)

            dist = abs(overlap_low - price)
            if dist <= 15.0:
                score_mult = 1.0
                status = "✅"
            elif dist <= 40.0:
                score_mult = 0.5
                status = "⚠️"
            else:
                continue

            if overlap_high > overlap_low:
                status_txt = "Inside" if overlap_low <= price <= overlap_high else ("Approaching" if dist <= 40 else "Outside")
                return {
                    "overlaps": True,
                    "score_mult": score_mult,
                    "status": status,
                    "detail": f"${overlap_low:.2f}–${overlap_high:.2f} ({status_txt})",
                }

    return {"overlaps": False, "score_mult": 0.0, "status": "❌", "detail": "No FVG+OB overlap"}


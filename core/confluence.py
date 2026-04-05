"""
Confluence Scorer — Weighted 12-point system.

Phase 1: Theory weights from config.
Phase 2: Auto-calibrated weights from journal data (after 30 trades).
"""

import logging

import config
from core.indicators import IndicatorResult

logger = logging.getLogger(__name__)


def compute_confluence(indicators: IndicatorResult, ict_result: dict,
                        dealing_range: dict, session_info: dict,
                        macro_data: dict, current_price: float,
                        weights: dict | None = None) -> dict:
    """
    Compute the weighted 12-point confluence score.
    
    Returns dict with individual factor scores & total.
    """
    w = weights or config.CONFLUENCE_WEIGHTS
    factors = {}

    # 1. Liquidity sweep present
    swept = any(p.swept for p in indicators.liquidity_pools) if indicators.liquidity_pools else False
    factors["liquidity_sweep"] = {
        "weight": w["liquidity_sweep"],
        "score": w["liquidity_sweep"] if swept else 0.0,
        "status": "✅" if swept else "❌",
        "detail": "Liquidity swept" if swept else "No sweep detected",
    }

    # 2. FVG + OB overlap
    fvg_ob_overlap = _check_fvg_ob_overlap(indicators, current_price)
    factors["fvg_ob_overlap"] = {
        "weight": w["fvg_ob_overlap"],
        "score": w["fvg_ob_overlap"] if fvg_ob_overlap["overlaps"] else 0.0,
        "status": "✅" if fvg_ob_overlap["overlaps"] else "❌",
        "detail": fvg_ob_overlap.get("detail", ""),
    }

    # 3. ICT sequence grade
    grade = ict_result.get("grade", "None")
    steps = ict_result.get("steps_passed", 0)
    
    # Scale score based on grade quality
    ict_score = 0.0
    if grade == "A+":
        ict_score = w["ict_sequence"]
    elif grade == "A":
        ict_score = w["ict_sequence"] * 0.8  # 1.2/1.5
    elif grade == "B":
        ict_score = w["ict_sequence"] * 0.5  # 0.75/1.5
        
    factors["ict_sequence"] = {
        "weight": w["ict_sequence"],
        "score": round(ict_score, 2),
        "status": "✅" if steps >= 4 else ("⚠️" if steps >= 3 else "❌"),
        "detail": f"Grade {grade} ({steps}/6)",
    }

    # 4. H1 BOS confirmed
    has_bos = len(indicators.bos_h1) > 0
    factors["h1_bos"] = {
        "weight": w["h1_bos"],
        "score": w["h1_bos"] if has_bos else 0.0,
        "status": "✅" if has_bos else "❌",
        "detail": f"{indicators.bos_h1[-1].direction} @ ${indicators.bos_h1[-1].price:.2f}" if has_bos else "No BOS",
    }

    # 5. In OTE zone
    dr = dealing_range or {}
    in_ote = False
    if dr.get("is_valid"):
        in_ote = dr.get("ote_low", 0) <= current_price <= dr.get("ote_high", 0)
    factors["ote_zone"] = {
        "weight": w["ote_zone"],
        "score": w["ote_zone"] if in_ote else 0.0,
        "status": "✅" if in_ote else "❌",
        "detail": f"${current_price:.2f} in OTE" if in_ote else "Outside OTE",
    }

    # 6. DXY alignment
    dxy_aligned = macro_data.get("dxy_aligned", False)
    factors["dxy_alignment"] = {
        "weight": w["dxy_alignment"],
        "score": w["dxy_alignment"] if dxy_aligned else 0.0,
        "status": "✅" if dxy_aligned else "❌",
        "detail": macro_data.get("dxy_detail", "No data"),
    }

    # 7. Killzone timing
    kz_active = session_info.get("killzone_active", False)
    factors["killzone_timing"] = {
        "weight": w["killzone_timing"],
        "score": w["killzone_timing"] if kz_active else 0.0,
        "status": "✅" if kz_active else "❌",
        "detail": session_info.get("killzone_name", "Outside killzone"),
    }

    # 8. Premium/Discount correct
    correct_zone = False
    if dr.get("is_valid"):
        ict_dir = ict_result.get("direction", "")
        eq = dr.get("equilibrium", 0)
        if ict_dir == "bullish" and current_price < eq:
            correct_zone = True
        elif ict_dir == "bearish" and current_price > eq:
            correct_zone = True
    factors["premium_discount"] = {
        "weight": w["premium_discount"],
        "score": w["premium_discount"] if correct_zone else 0.0,
        "status": "✅" if correct_zone else "❌",
        "detail": "Correct zone" if correct_zone else "Wrong zone",
    }

    # 9. ATR normal
    atr = indicators.atr_h1
    atr_ok = config.ATR_NORMAL_MIN <= atr <= config.ATR_NORMAL_MAX
    factors["atr_normal"] = {
        "weight": w["atr_normal"],
        "score": w["atr_normal"] if atr_ok else 0.0,
        "status": "✅" if atr_ok else "⚠️",
        "detail": f"${atr:.2f}" + (" Normal" if atr_ok else " Abnormal"),
    }

    # 10. No news conflict
    news_clear = not session_info.get("news_conflict", False)
    factors["no_news_conflict"] = {
        "weight": w["no_news_conflict"],
        "score": w["no_news_conflict"] if news_clear else 0.0,
        "status": "✅" if news_clear else "⚠️",
        "detail": "Clear" if news_clear else session_info.get("news_detail", "News conflict"),
    }

    # Total
    total = sum(f["score"] for f in factors.values())
    maximum = sum(f["weight"] for f in factors.values())

    return {
        "factors": factors,
        "total": round(total, 1),
        "maximum": round(maximum, 1),
        "tradeable": total >= config.CONFLUENCE_MIN_LONDON_NY,
    }


def _check_fvg_ob_overlap(indicators: IndicatorResult, price: float) -> dict:
    """Check if any FVG overlaps with any OB near current price."""
    all_fvgs = indicators.fvgs_h1 + indicators.fvgs_m15
    all_obs = indicators.obs_h1 + indicators.obs_m15

    for fvg in all_fvgs:
        if fvg.filled:
            continue
        for ob in all_obs:
            if ob.mitigated:
                continue
            # Check overlap
            overlap_high = min(fvg.high, ob.high)
            overlap_low = max(fvg.low, ob.low)
            if overlap_high > overlap_low:
                return {
                    "overlaps": True,
                    "detail": f"${overlap_low:.2f} – ${overlap_high:.2f}",
                }

    return {"overlaps": False, "detail": "No FVG+OB overlap"}

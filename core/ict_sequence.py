"""
ICT Sequence Detector — Checks the 6-step bullish/bearish ICT sequence.
Grades setups as A+ (6/6), A (4-5/6), B (3/6), or None (<3).
"""

import logging
from dataclasses import dataclass, field

import config
from core.indicators import IndicatorResult

logger = logging.getLogger(__name__)


@dataclass
class ICTStep:
    """One step in the ICT sequence."""
    name: str
    passed: bool = False
    detail: str = ""


@dataclass
class ICTSequenceResult:
    """Complete ICT sequence evaluation."""
    direction: str = "neutral"      # "bullish" or "bearish"
    steps: list = field(default_factory=list)
    steps_passed: int = 0
    grade: str = "None"             # "A+", "A", "B", "None"

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "steps": [{"name": s.name, "passed": s.passed, "detail": s.detail} for s in self.steps],
            "steps_passed": self.steps_passed,
            "grade": self.grade,
        }


def check_ict_sequence(indicators: IndicatorResult, session_info: dict,
                        current_price: float, dealing_range: dict) -> ICTSequenceResult:
    """
    Check the full 6-step ICT sequence.
    
    Bullish sequence:
      1. Asian range clean (identifiable high + low)
      2. London open sweeps Asian low (SSL grab)
      3. Price returns to H1 FVG
      4. M15 BOS bullish confirmed
      5. M5 OB forms in discount zone
      6. Within killzone window
    
    Bearish sequence: mirror of above.
    """
    result = ICTSequenceResult()

    # Determine bias from BOS
    if indicators.bos_h1:
        last_bos = indicators.bos_h1[-1]
        result.direction = last_bos.direction
    elif indicators.choch_h1:
        last_choch = indicators.choch_h1[-1]
        result.direction = last_choch.direction
    else:
        result.direction = "neutral"

    is_bullish = result.direction == "bullish"

    # Step 1: Asian range clean
    step1 = ICTStep(name="Asian range clean")
    # We check if we have identifiable swing high/low from Asian session
    # Simplified: H4 swing high and low exist
    if indicators.swing_highs_h4 and indicators.swing_lows_h4:
        step1.passed = True
        sh = indicators.swing_highs_h4[-1]
        sl = indicators.swing_lows_h4[-1]
        step1.detail = f"High ${sh.price:.2f} / Low ${sl.price:.2f}"
    result.steps.append(step1)

    # Step 2: Liquidity sweep (SSL for bullish, BSL for bearish)
    step2 = ICTStep(name="Liquidity sweep")
    target_type = "SSL" if is_bullish else "BSL"
    swept_pools = [p for p in indicators.liquidity_pools if p.type == target_type and p.swept]
    if swept_pools:
        step2.passed = True
        step2.detail = f"{target_type} @ ${swept_pools[-1].price:.2f} swept"
    elif indicators.liquidity_pools:
        # Check if any pool is near current price (within $2)
        for pool in indicators.liquidity_pools:
            if pool.type == target_type and abs(pool.price - current_price) < 15.0:
                step2.passed = True
                step2.detail = f"{target_type} @ ${pool.price:.2f} near price"
                break
    result.steps.append(step2)

    # Step 3: Price returns to H1 FVG
    step3 = ICTStep(name="H1 FVG return")
    target_dir = "bullish" if is_bullish else "bearish"
    active_fvgs = [f for f in indicators.fvgs_h1
                   if f.direction == target_dir and not f.filled]
    if active_fvgs:
        fvg = active_fvgs[-1]
        if fvg.low <= current_price <= fvg.high:
            step3.passed = True
            step3.detail = f"${fvg.low:.2f} – ${fvg.high:.2f}"
        else:
            step3.detail = f"FVG at ${fvg.low:.2f} – ${fvg.high:.2f} (not in zone)"
    result.steps.append(step3)

    # Step 4: M15 BOS confirmed in direction
    step4 = ICTStep(name="M15 BOS confirmed")
    # We use H1 BOS as proxy (M15 BOS would need M15 swing calc)
    matching_bos = [b for b in indicators.bos_h1 if b.direction == result.direction]
    if matching_bos:
        step4.passed = True
        step4.detail = f"{result.direction} @ ${matching_bos[-1].price:.2f}"
    result.steps.append(step4)

    # Step 5: M5 OB in correct zone
    step5 = ICTStep(name="M5 OB in zone")
    target_ob_dir = "bullish" if is_bullish else "bearish"
    matching_obs = [ob for ob in indicators.obs_m5
                    if ob.direction == target_ob_dir and not ob.mitigated]
    if matching_obs:
        ob = matching_obs[-1]
        # Check if OB is in discount (bullish) or premium (bearish)
        in_correct_zone = True
        if dealing_range.get("is_valid"):
            eq = dealing_range.get("equilibrium", 0)
            if is_bullish and ob.low > eq:
                in_correct_zone = False  # OB should be in discount
            elif not is_bullish and ob.high < eq:
                in_correct_zone = False  # OB should be in premium
        if in_correct_zone:
            step5.passed = True
            step5.detail = f"${ob.low:.2f} – ${ob.high:.2f}"
    result.steps.append(step5)

    # Step 6: Killzone timing
    step6 = ICTStep(name="Killzone active")
    kz_active = session_info.get("killzone_active", False)
    kz_name = session_info.get("killzone_name", "")
    if kz_active:
        step6.passed = True
        step6.detail = kz_name
    result.steps.append(step6)

    # Grade
    result.steps_passed = sum(1 for s in result.steps if s.passed)
    if result.steps_passed >= 6:
        result.grade = "A+"
    elif result.steps_passed >= 4:
        result.grade = "A"
    elif result.steps_passed >= 3:
        result.grade = "B"
    else:
        result.grade = "None"

    return result

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
    setup_status: str = "Scanning"  # "Waiting for MSS", "Entry Ready", etc.

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "steps": [{"name": s.name, "passed": s.passed, "detail": s.detail} for s in self.steps],
            "steps_passed": self.steps_passed,
            "grade": self.grade,
            "setup_status": self.setup_status,
        }


def check_ict_sequence(indicators: IndicatorResult, session_info: dict,
                        current_price: float, dealing_range: dict) -> ICTSequenceResult:
    """
    Check the full 6-step ICT sequence with HTF Alignment.
    """
    result = ICTSequenceResult()
    
    # ── MANTATORY GATE: KILLZONE (Relaxed for UI visibility) ─────────────────────────────
    # We evaluate the steps anyway, but Step 6 will fail if not in a killzone.
    kz_active = session_info.get("killzone_active", False)
        
    # Determine bias from recent Draw on Liquidity (DOL)
    # The DOL is the nearest un-swept liquidity pool or H1 BOS target
    target_up = next((p for p in indicators.liquidity_pools if p.type == "BSL" and not p.swept), None)
    target_down = next((p for p in indicators.liquidity_pools if p.type == "SSL" and not p.swept), None)
    
    h1_all = indicators.bos_h1 + indicators.choch_h1
    h1_all.sort(key=lambda x: x.index)
    h1_dir = h1_all[-1].direction if h1_all else "neutral"

    # Bias Flow: H1 Structure + DOL Proximity
    if h1_dir == "bullish" and target_up:
        result.direction = "bullish (DOL: BSL)"
    elif h1_dir == "bearish" and target_down:
        result.direction = "bearish (DOL: SSL)"
    elif h1_dir != "neutral":
        result.direction = h1_dir
    else:
        # Fallback to M15 flow if H1 is sideways
        m15_all = indicators.bos_m15 + indicators.choch_m15
        if m15_all:
             m15_all.sort(key=lambda x: x.index)
             result.direction = m15_all[-1].direction
        else:
             return result

    is_bullish = "bullish" in result.direction

    # Step 1: HTF Structure Check (Asian/H4 range)
    step1 = ICTStep(name="HTF Structure Alignment")
    if dealing_range.get("is_valid"):
        step1.passed = True
        step1.detail = f"DR: {dealing_range.get('range_type', 'Valid')}"
    result.steps.append(step1)

    # Step 2: Liquidity sweep (Rejection is key)
    step2 = ICTStep(name="Liquidity sweep + Rejection")
    target_type = "SSL" if is_bullish else "BSL"
    swept_pools = [p for p in indicators.liquidity_pools if p.type == target_type and p.swept]
    if swept_pools:
        step2.passed = True
        step2.detail = f"{target_type} swept"
    result.steps.append(step2)

    # Step 3: FVG Confluence
    # Relaxed: price must be inside OR approaching within 5pts of the FVG edge.
    # In live trading you set a limit order at the FVG edge, so the signal fires
    # before you're already inside it — which is too late for a clean entry.
    step3 = ICTStep(name="FVG Confluence")
    target_dir = "bullish" if is_bullish else "bearish"
    active_fvgs = [f for f in indicators.fvgs_h1 if f.direction == target_dir and not f.filled]
    # Also consider M15 FVGs as secondary confirmation
    active_fvgs_m15 = [f for f in indicators.fvgs_m15 if f.direction == target_dir and not f.filled]
    all_fvgs_to_check = active_fvgs + active_fvgs_m15
    if all_fvgs_to_check:
        prox = config.FVG_PROXIMITY_PTS
        for fvg in all_fvgs_to_check:
            inside = fvg.low <= current_price <= fvg.high
            approaching_bullish = is_bullish and (fvg.low - prox) <= current_price <= fvg.high
            approaching_bearish = not is_bullish and fvg.low <= current_price <= (fvg.high + prox)
            if inside:
                step3.passed = True
                step3.detail = "H1/M15 FVG — inside"
                break
            elif approaching_bullish or approaching_bearish:
                step3.passed = True
                step3.detail = f"H1/M15 FVG — approaching ({abs(current_price - (fvg.low if is_bullish else fvg.high)):.1f}pts)"
                break
    result.steps.append(step3)

    # Step 4: M15 MSS (Market Structure Shift)
    step4 = ICTStep(name="M15 MSS confirmed")
    # MSS is just the first CHoCH in the setup direction. 
    # Use clean direction for matching (e.g. "bullish (reversal)" -> "bullish")
    clean_dir = "bullish" if is_bullish else "bearish"
    matching_choch = [b for b in indicators.choch_m15 if b.direction == clean_dir]
    if matching_choch:
        step4.passed = True
        step4.detail = f"MSS {clean_dir}"
    result.steps.append(step4)

    # Step 5: Dealing Range Discount/Premium
    step5 = ICTStep(name="Premium/Discount Entry")
    if dealing_range.get("is_valid"):
        eq = dealing_range.get("equilibrium", 0)
        if (is_bullish and current_price < eq) or (not is_bullish and current_price > eq):
            step5.passed = True
            step5.detail = "In entry zone"
    result.steps.append(step5)

    # Step 6: Killzone timing
    step6 = ICTStep(name="Killzone precision")
    step6.passed = kz_active
    step6.detail = session_info.get("killzone_name") if kz_active else "Outside Killzone"
    result.steps.append(step6)

    # Grade
    result.steps_passed = sum(1 for s in result.steps if s.passed)
    if result.steps_passed >= 6: result.grade = "A+"
    elif result.steps_passed >= 4: result.grade = "A"
    elif result.steps_passed >= 3: result.grade = "B"
    else: result.grade = "None"

    if result.steps_passed == 6:
        result.setup_status = "🎯 ENTRY READY"
    elif result.steps_passed >= 4:
        result.setup_status = "⏳ WAITING FOR TRIGGER"
    else:
        result.setup_status = "💤 NO ACTIVE SWING SETUP"

    return result

"""
Psychology Pre-Trade Check — 5-question gate before trading.

Enforces mental state requirements:
  - Q5 = "recover loss" → hard block
  - Q5 = "bored" → warning + double confirmation
  - Feeling < 4 → hard block
  - Feeling 4-6 + last loss → reduced lot size
  
All answers logged to state_history.json for analytics.
"""

import json
import time
import logging
from dataclasses import dataclass
from pathlib import Path

import config

logger = logging.getLogger(__name__)


Q5_OPTIONS = [
    "setup_alert",      # Setup alert fired — I'm here to execute
    "routine_check",    # Routine session check
    "bored",            # Bored and watching charts
    "recover_loss",     # Want to recover a loss
    "confident_win",    # Feeling confident after a win
]

Q5_LABELS = {
    "setup_alert": "Setup alert fired — I'm here to execute",
    "routine_check": "Routine session check",
    "bored": "Bored and watching charts",
    "recover_loss": "Want to recover a loss",
    "confident_win": "Feeling confident after a win",
}


@dataclass
class PsychCheckResult:
    """Result of psychology pre-trade check."""
    feeling: int = 0
    slept_well: bool = True
    financial_stress: bool = False
    last_trade: str = "none"         # "won", "lost", "none"
    reason: str = "setup_alert"
    blocked: bool = False
    block_reason: str = ""
    warning: str = ""
    lot_recommendation: float = 0.03
    assessment: str = ""

    def to_dict(self) -> dict:
        return {
            "feeling": self.feeling,
            "slept_well": self.slept_well,
            "financial_stress": self.financial_stress,
            "last_trade": self.last_trade,
            "reason": self.reason,
            "reason_label": Q5_LABELS.get(self.reason, self.reason),
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "warning": self.warning,
            "lot_recommendation": self.lot_recommendation,
            "assessment": self.assessment,
        }


def evaluate_psychology(feeling: int, slept_well: bool, financial_stress: bool,
                         last_trade: str, reason: str) -> PsychCheckResult:
    """
    Evaluate the 5 psychology questions and return gate decision.
    """
    result = PsychCheckResult(
        feeling=feeling,
        slept_well=slept_well,
        financial_stress=financial_stress,
        last_trade=last_trade,
        reason=reason,
    )

    # Hard blocks
    if reason == "recover_loss":
        result.blocked = True
        result.block_reason = "Revenge trading detected. Report locked. No override."
        result.assessment = "BLOCKED — revenge motivation"
        _save_state(result)
        return result

    if feeling < config.PSYCH_MIN_FEELING:
        result.blocked = True
        result.block_reason = f"Mental state {feeling}/10 — too low. Come back tomorrow."
        result.assessment = "BLOCKED — poor mental state"
        _save_state(result)
        return result

    # Warnings
    if reason == "bored":
        result.warning = "⚠️ Bored trading detected. Double confirmation required."

    # Lot size reduction
    if feeling <= config.PSYCH_REDUCED_LOT_FEELING and last_trade == "lost":
        result.lot_recommendation = config.MAX_LOT_TRADE2  # 0.02 — reduced
        result.warning += " Lot size reduced to 0.02 (low feeling + recent loss)."

    # Build assessment
    good_signs = []
    bad_signs = []

    if feeling >= 7:
        good_signs.append("high energy")
    elif feeling >= 4:
        bad_signs.append("moderate energy")

    if slept_well:
        good_signs.append("good sleep")
    else:
        bad_signs.append("poor sleep")

    if not financial_stress:
        good_signs.append("no stress")
    else:
        bad_signs.append("external stress")

    if reason == "setup_alert":
        good_signs.append("alert-driven entry")

    if good_signs and not bad_signs:
        result.assessment = f"OPTIMAL — {', '.join(good_signs)}"
    elif good_signs:
        result.assessment = f"ACCEPTABLE — {', '.join(good_signs)}; watch: {', '.join(bad_signs)}"
    else:
        result.assessment = f"CAUTION — {', '.join(bad_signs)}"

    _save_state(result)
    return result


def _save_state(result: PsychCheckResult):
    """Append psychology check to state history."""
    try:
        filepath = config.PSYCH_STATE_FILE
        filepath.parent.mkdir(parents=True, exist_ok=True)

        history = []
        if filepath.exists():
            try:
                history = json.loads(filepath.read_text())
            except json.JSONDecodeError:
                history = []

        entry = result.to_dict()
        entry["timestamp"] = time.time()
        history.append(entry)

        filepath.write_text(json.dumps(history, indent=2))
    except Exception as e:
        logger.error(f"Failed to save psychology state: {e}")


def get_state_history() -> list[dict]:
    """Load psychology state history."""
    filepath = config.PSYCH_STATE_FILE
    if filepath.exists():
        try:
            return json.loads(filepath.read_text())
        except json.JSONDecodeError:
            return []
    return []

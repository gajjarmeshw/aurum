"""
Cooldown Engine — Post-loss behavioral lock.

Enforces mandatory cooling periods after losses:
  1 loss: 30 min lock
  2 consecutive losses: 60 min lock
  Daily loss ≥ $35: confirmation required
  Daily loss ≥ $50: full lock — no trading today
"""

import time
import logging
from dataclasses import dataclass, field

import config

logger = logging.getLogger(__name__)


@dataclass
class CooldownState:
    """Current cooldown state."""
    active: bool = False
    reason: str = ""
    expires_at: float = 0.0
    consecutive_losses: int = 0
    daily_loss: float = 0.0
    hard_locked: bool = False       # $50 daily loss — full lock
    needs_confirmation: bool = False  # $35 daily loss — modal

    @property
    def remaining_seconds(self) -> float:
        if not self.active or self.hard_locked:
            return float("inf") if self.hard_locked else 0
        remaining = self.expires_at - time.time()
        return max(0, remaining)

    @property
    def remaining_minutes(self) -> int:
        return int(self.remaining_seconds / 60)

    def to_dict(self) -> dict:
        return {
            "active": self.active,
            "reason": self.reason,
            "remaining_minutes": self.remaining_minutes,
            "consecutive_losses": self.consecutive_losses,
            "daily_loss": round(self.daily_loss, 2),
            "hard_locked": self.hard_locked,
            "needs_confirmation": self.needs_confirmation,
        }


class CooldownEngine:
    """Manages post-loss cooldown periods."""

    def __init__(self):
        self.state = CooldownState()
        self._confirmation_given = False

    def record_trade_result(self, pnl: float):
        """
        Record a trade result and apply cooldown if needed.
        pnl: positive = win, negative = loss
        """
        if pnl >= 0:
            # Win — reset consecutive losses
            self.state.consecutive_losses = 0
            self.state.active = False
            self.state.reason = ""
            self._confirmation_given = False
            logger.info(f"Win recorded (+${pnl:.2f}). Cooldown cleared.")
            return

        # Loss
        self.state.consecutive_losses += 1
        self.state.daily_loss += abs(pnl)

        logger.warning(
            f"Loss recorded (-${abs(pnl):.2f}). "
            f"Consecutive: {self.state.consecutive_losses}. "
            f"Daily loss: ${self.state.daily_loss:.2f}"
        )

        # Check daily loss thresholds
        if self.state.daily_loss >= config.DAILY_LOSS_HARD_CAP:
            self.state.active = True
            self.state.hard_locked = True
            self.state.reason = f"Daily loss ${self.state.daily_loss:.2f} ≥ ${config.DAILY_LOSS_HARD_CAP} — NO TRADING TODAY"
            logger.warning(f"HARD LOCK: {self.state.reason}")
            return

        if self.state.daily_loss >= config.DAILY_LOSS_WARNING:
            self.state.needs_confirmation = True
            self._confirmation_given = False

        # Apply time-based cooldown
        if self.state.consecutive_losses >= 2:
            cooldown_min = config.COOLDOWN_2_LOSS_MINUTES
            self.state.reason = f"2 consecutive losses — {cooldown_min}min cooldown"
        else:
            cooldown_min = config.COOLDOWN_1_LOSS_MINUTES
            self.state.reason = f"1 loss — {cooldown_min}min cooldown"

        self.state.active = True
        self.state.expires_at = time.time() + (cooldown_min * 60)
        logger.info(f"Cooldown active: {self.state.reason}")

    def check_cooldown(self) -> CooldownState:
        """Check current cooldown state. Auto-expire time-based cooldowns."""
        if self.state.active and not self.state.hard_locked:
            if time.time() >= self.state.expires_at:
                self.state.active = False
                self.state.reason = "Cooldown expired"
                logger.info("Cooldown expired. Trading allowed.")
        return self.state

    def confirm_continue(self):
        """User confirms they want to continue after $35 daily loss warning."""
        self._confirmation_given = True
        self.state.needs_confirmation = False
        logger.info("User confirmed continuation after daily loss warning.")

    def is_blocked(self) -> bool:
        """Check if trading is currently blocked by cooldown."""
        state = self.check_cooldown()
        if state.hard_locked:
            return True
        if state.active and state.remaining_seconds > 0:
            return True
        if state.needs_confirmation and not self._confirmation_given:
            return True
        return False

    def reset_daily(self):
        """Reset daily counters — call at midnight IST."""
        self.state = CooldownState()
        self._confirmation_given = False
        logger.info("Daily cooldown state reset.")

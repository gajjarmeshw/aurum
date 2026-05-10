"""
Risk Manager — drawdown circuit breaker for live trading.

Halts new trade entries when:
  - 3 consecutive losing days, OR
  - Rolling 5-day PnL < -$500

State persists in risk_state.json (survives restart). Halt is sticky:
clearing requires explicit /api/risk/resume call (or CLI --resume).

Triggered on every trade close (record_trade); checked before every new entry
(is_halted). On halt trigger, sends a Telegram alert.

CLI:
  python -m pipeline.risk_manager --status    # show current state
  python -m pipeline.risk_manager --resume    # clear halt manually
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# ── Tuning ──────────────────────────────────────────────────────────────────
MAX_CONSECUTIVE_LOSING_DAYS = 3
ROLLING_WINDOW_DAYS         = 5
ROLLING_LOSS_THRESHOLD_USD  = -500.0
HISTORY_RETENTION_DAYS      = 30          # keep 30 days of daily PnL history

_STATE_FILE = config.BASE_DIR / "risk_state.json"


def _today_ist() -> str:
    """Today's IST date as YYYY-MM-DD."""
    return config.get_ist_now().date().isoformat()


def _load() -> dict:
    if not _STATE_FILE.exists():
        return {"daily_pnl": {}, "halted": False, "halt_reason": "", "halted_at": ""}
    try:
        return json.loads(_STATE_FILE.read_text())
    except Exception as e:
        logger.error(f"risk_state load failed: {e}; starting fresh")
        return {"daily_pnl": {}, "halted": False, "halt_reason": "", "halted_at": ""}


def _save(state: dict) -> None:
    # Prune history beyond retention window
    cutoff = (date.today() - timedelta(days=HISTORY_RETENTION_DAYS)).isoformat()
    state["daily_pnl"] = {d: v for d, v in state["daily_pnl"].items() if d >= cutoff}
    _STATE_FILE.write_text(json.dumps(state, indent=2))


def record_trade(pnl: float, trade_date: str | None = None) -> None:
    """Add a trade's PnL to today's running total. Idempotent per call."""
    state = _load()
    d = trade_date or _today_ist()
    state["daily_pnl"][d] = state["daily_pnl"].get(d, 0.0) + float(pnl)
    _save(state)
    # Re-evaluate halt conditions after every recorded trade
    _evaluate_halt(state)


def _evaluate_halt(state: dict) -> None:
    """Check halt conditions against current daily_pnl. Sets halted=True if triggered."""
    if state.get("halted"):
        return   # already halted; don't downgrade

    daily = state["daily_pnl"]
    sorted_days = sorted(daily.keys())
    if not sorted_days:
        return

    # Condition 1: N consecutive losing days (most recent N days, all negative)
    recent_n = sorted_days[-MAX_CONSECUTIVE_LOSING_DAYS:]
    if len(recent_n) == MAX_CONSECUTIVE_LOSING_DAYS \
            and all(daily[d] < 0 for d in recent_n):
        state["halted"]      = True
        state["halt_reason"] = (
            f"{MAX_CONSECUTIVE_LOSING_DAYS} consecutive losing days: "
            + ", ".join(f"{d}=${daily[d]:.0f}" for d in recent_n)
        )
        state["halted_at"]   = datetime.utcnow().isoformat() + "Z"
        _save(state)
        logger.warning(f"RISK HALT triggered: {state['halt_reason']}")
        return

    # Condition 2: rolling N-day window total PnL below threshold
    rolling = sorted_days[-ROLLING_WINDOW_DAYS:]
    rolling_pnl = sum(daily[d] for d in rolling)
    if len(rolling) >= ROLLING_WINDOW_DAYS and rolling_pnl < ROLLING_LOSS_THRESHOLD_USD:
        state["halted"]      = True
        state["halt_reason"] = (
            f"Rolling {ROLLING_WINDOW_DAYS}-day PnL ${rolling_pnl:.0f} "
            f"< ${ROLLING_LOSS_THRESHOLD_USD:.0f} threshold"
        )
        state["halted_at"]   = datetime.utcnow().isoformat() + "Z"
        _save(state)
        logger.warning(f"RISK HALT triggered: {state['halt_reason']}")


def is_halted() -> tuple[bool, str]:
    """Returns (halted, reason). Call before any new trade entry."""
    state = _load()
    return bool(state.get("halted")), state.get("halt_reason", "")


def resume() -> str:
    """Manually clear halt state. Returns previous halt reason for logging."""
    state = _load()
    prev = state.get("halt_reason", "")
    state["halted"]      = False
    state["halt_reason"] = ""
    state["halted_at"]   = ""
    _save(state)
    logger.info(f"Risk halt CLEARED (was: {prev or 'not halted'})")
    return prev


def get_status() -> dict:
    """Snapshot of current risk state for display/alerts."""
    state = _load()
    daily = state["daily_pnl"]
    sorted_days = sorted(daily.keys())[-ROLLING_WINDOW_DAYS:]
    rolling_pnl = sum(daily[d] for d in sorted_days) if sorted_days else 0.0
    consec_losses = 0
    for d in reversed(sorted_days):
        if daily[d] < 0:
            consec_losses += 1
        else:
            break
    return {
        "halted":           state.get("halted", False),
        "halt_reason":      state.get("halt_reason", ""),
        "halted_at":        state.get("halted_at", ""),
        "rolling_pnl_5d":   round(rolling_pnl, 2),
        "consec_losing_days": consec_losses,
        "recent_daily_pnl": {d: round(daily[d], 2) for d in sorted_days},
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true", help="Show current risk state")
    parser.add_argument("--resume", action="store_true", help="Manually clear halt state")
    args = parser.parse_args()

    if args.resume:
        prev = resume()
        print(f"Halt cleared. Previous reason: {prev or '(was not halted)'}")
    else:
        # Default: show status
        s = get_status()
        print(json.dumps(s, indent=2))

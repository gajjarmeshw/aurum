"""
News Blackout — block trade entries around high-impact economic events.

Rationale: high-impact news (NFP, FOMC, CPI, ECB) causes 50-200pt spikes on
XAUUSD that destroy mean-reversion and breakout-retest setups. The blackout
window is asymmetric — the spike often runs longer after release than the
pre-release lull.

Live path:    is_news_blackout(now_ist, get_todays_events())
Backtest path: is_news_blackout(now_ist, None) → uses NFP first-Friday rule
"""

from datetime import datetime, timedelta, time
import logging

logger = logging.getLogger(__name__)

# Window around each high-impact event when we refuse new trade entries
BLACKOUT_BEFORE_MIN = 5      # 5 min before scheduled release
BLACKOUT_AFTER_MIN  = 15     # 15 min after — covers typical reaction tail


def is_news_blackout(now_ist: datetime, events: list[dict] | None) -> tuple[bool, str]:
    """
    Returns (blocked, reason) — blocked=True means refuse entry now.

    `events` shape: [{"time_ist": "HH:MM", "event": str, "impact": "HIGH"|"MED"|"LOW", ...}]
    Pass None to fall back to deterministic NFP-first-Friday rule (backtest mode).
    """
    if events is None:
        return _backtest_blackout(now_ist)

    for ev in events:
        if ev.get("impact") != "HIGH":
            continue
        time_str = ev.get("time_ist", "")
        try:
            hh, mm = time_str.split(":")
            ev_dt = now_ist.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        except Exception:
            continue
        delta_min = (now_ist - ev_dt).total_seconds() / 60.0
        if -BLACKOUT_BEFORE_MIN <= delta_min <= BLACKOUT_AFTER_MIN:
            return True, f"News blackout: {ev.get('event', 'high-impact')} @ {time_str} IST (Δ{delta_min:+.0f}m)"
    return False, ""


def _backtest_blackout(now_ist: datetime) -> tuple[bool, str]:
    """
    Backtest fallback — covers the most predictable high-impact events:
      - NFP: first Friday of every month, 18:00 IST (release: 8:30 ET)
      - FOMC rate decisions are date-specific, not modeled here
    """
    if _is_first_friday(now_ist):
        nfp_release = now_ist.replace(hour=18, minute=0, second=0, microsecond=0)
        delta_min = (now_ist - nfp_release).total_seconds() / 60.0
        if -BLACKOUT_BEFORE_MIN <= delta_min <= BLACKOUT_AFTER_MIN:
            return True, f"NFP blackout (Δ{delta_min:+.0f}m)"
    return False, ""


def _is_first_friday(dt: datetime) -> bool:
    """First Friday of the month: Friday with day-of-month <= 7."""
    return dt.weekday() == 4 and dt.day <= 7

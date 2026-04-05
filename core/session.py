"""
Session Manager — IST killzone windows, status light, and countdown timer.

Manages trading session state based on India Standard Time (UTC+5:30).
"""

import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

import config

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class SessionInfo:
    """Current session state."""
    current_time_ist: str = ""
    status_light: str = "RED"            # GREEN, YELLOW, RED
    killzone_active: bool = False
    killzone_name: str = ""
    killzone_remaining_min: int = 0
    session_label: str = ""
    is_dead_zone: bool = False
    is_avoid_zone: bool = False
    news_conflict: bool = False
    news_detail: str = ""

    def to_dict(self) -> dict:
        return {
            "current_time_ist": self.current_time_ist,
            "status_light": self.status_light,
            "killzone_active": self.killzone_active,
            "killzone_name": self.killzone_name,
            "killzone_remaining_min": self.killzone_remaining_min,
            "session_label": self.session_label,
            "is_dead_zone": self.is_dead_zone,
            "is_avoid_zone": self.is_avoid_zone,
            "news_conflict": self.news_conflict,
            "news_detail": self.news_detail,
        }


def get_session_info(news_events: list[dict] | None = None) -> SessionInfo:
    """
    Determine current session state based on IST time.
    
    news_events: list of {"time_ist": "HH:MM", "event": str, "impact": "HIGH"|"MED"|"LOW"}
    """
    now = datetime.now(IST)
    current_minutes = now.hour * 60 + now.minute
    info = SessionInfo()
    info.current_time_ist = now.strftime("%H:%M IST")

    # Check which killzone we're in
    active_kz = None
    for kz_key, kz in config.KILLZONES.items():
        start_min = kz["start"][0] * 60 + kz["start"][1]
        end_min = kz["end"][0] * 60 + kz["end"][1]

        # Handle overnight windows (dead zone)
        if start_min > end_min:
            in_window = current_minutes >= start_min or current_minutes < end_min
        else:
            in_window = start_min <= current_minutes < end_min

        if in_window:
            if kz_key == "dead_zone":
                info.is_dead_zone = True
                info.session_label = kz["label"]
            elif kz_key == "avoid_zone":
                info.is_avoid_zone = True
                info.session_label = kz["label"]
            else:
                active_kz = kz
                info.killzone_active = True
                info.killzone_name = kz["label"]
                # Calculate remaining minutes
                remaining = end_min - current_minutes
                if remaining < 0:
                    remaining += 1440
                info.killzone_remaining_min = remaining
                info.session_label = kz["label"]
            break

    if not info.session_label:
        info.session_label = "Between Sessions"

    # Check news conflicts
    if news_events:
        for event in news_events:
            if event.get("impact") == "HIGH":
                event_time = event.get("time_ist", "")
                try:
                    parts = event_time.split(":")
                    event_min = int(parts[0]) * 60 + int(parts[1])
                    diff = event_min - current_minutes
                    if 0 <= diff <= config.NEWS_BLOCK_MINUTES:
                        info.news_conflict = True
                        info.news_detail = f"{event['event']} in {diff}min"
                        break
                    elif -30 <= diff < 0:
                        # Recent news — caution
                        info.news_detail = f"{event['event']} {abs(diff)}min ago"
                except (ValueError, IndexError):
                    pass

    # Determine status light
    if info.is_dead_zone or info.news_conflict:
        info.status_light = "RED"
    elif info.is_avoid_zone:
        info.status_light = "RED"
    elif info.killzone_active:
        if info.killzone_remaining_min <= 5:
            info.status_light = "YELLOW"  # killzone ending soon
        else:
            info.status_light = "GREEN"
    else:
        info.status_light = "YELLOW"  # between sessions

    return info


def should_block_trading(session_info: SessionInfo, daily_pnl: float = 0,
                          daily_loss: float = 0, confluence_score: float = 0,
                          psych_score: int = 10, cooldown_active: bool = False,
                          is_nfp_day: bool = False) -> dict:
    """
    Master gate: determine if trading should be blocked.
    Returns {"blocked": bool, "reasons": [...]}
    """
    reasons = []

    if session_info.is_dead_zone:
        reasons.append("Dead zone hours — NO TRADING")
    if is_nfp_day:
        reasons.append("NFP day — NO TRADING")
    if session_info.news_conflict:
        reasons.append(f"News < {config.NEWS_BLOCK_MINUTES}min away")
    if daily_loss >= config.DAILY_LOSS_HARD_CAP:
        reasons.append(f"Daily loss ≥ ${config.DAILY_LOSS_HARD_CAP}")
    if daily_pnl >= config.DAILY_HARD_CAP:
        reasons.append(f"Daily profit ≥ ${config.DAILY_HARD_CAP}")
    if cooldown_active:
        reasons.append("Cooldown active")
    if confluence_score < config.CONFLUENCE_MIN_LONDON_NY:
        reasons.append(f"Confluence {confluence_score} < {config.CONFLUENCE_MIN_LONDON_NY}")
    if psych_score < config.PSYCH_MIN_FEELING:
        reasons.append(f"Psychology score {psych_score} < {config.PSYCH_MIN_FEELING}")

    return {
        "blocked": len(reasons) > 0,
        "reasons": reasons,
        "status_light": "RED" if reasons else session_info.status_light,
    }

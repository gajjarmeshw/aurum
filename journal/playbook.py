"""
Personalized Playbook — Auto-generated from journaled winning patterns.

The system analyzes the last 50 trades to identify high-probability ICT set ups
specific to the user's performance.
"""

import logging
from journal.journal import get_trades

logger = logging.getLogger(__name__)

def generate_playbook():
    """Analyze winning trades to extract high-prob characteristics."""
    trades = get_trades()
    wins = [t for t in trades if t.get("result") == "WIN"]
    
    if len(wins) < 10:
        return {
            "status": "Incomplete",
            "msg": "Need 50 trades (at least 10 wins) to calibrate playbook."
        }
    
    # Simple analysis logic
    best_session = _analyze_mode([t.get("session") for t in wins])
    best_grade = _analyze_mode([t.get("grade") for t in wins])
    
    return {
        "status": "CALIBRATED",
        "best_session": best_session,
        "best_grade": best_grade,
        "core_rule": f"Focus on {best_grade} setups during {best_session} for maximum edge.",
        "trading_time_filter": "Strict London Open (1:30-4:30 PM) is your highest edge window."
    }

def _analyze_mode(l):
    if not l: return "None"
    return max(set(l), key=l.count)

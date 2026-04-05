"""
Alerts Manager — Logic for triggering Telegram notifications.

Listens for:
  - High confluence scores (>= 8)
  - Edge decay (rolling win rate < threshold)
  - London -> NY handoff (time-based)
"""

import logging
from alerts.telegram_bot import TelegramBot
from core.session_handoff import format_handoff_telegram
from journal.journal import get_journal_context

logger = logging.getLogger(__name__)

class AlertsManager:
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self.bot = TelegramBot()
        self._last_alert_time = 0
        self._alert_cooldown = 1800  # 30 minutes between setup alerts
        self._last_score = 0
        
    def handle_confluence_update(self, data):
        """Check if score warrants an alert."""
        score = data.get("total", 0)
        
        # Trigger alert if score >= 8 and we haven't alerted recently
        if score >= 8 and score > self._last_score:
            import time
            now = time.time()
            if now - self._last_alert_time > self._alert_cooldown:
                # Get latest price and session from somewhere?
                # Actually, data should probably include these for the alert.
                price = data.get("price", 0)
                killzone = data.get("killzone", "Unknown")
                grade = data.get("grade", "None")
                
                self.bot.alert_setup(score, grade, price, killzone)
                self._last_alert_time = now
        
        self._last_score = score

    def check_edge_decay(self):
        """Check rolling win rate and alert if decaying."""
        context = get_journal_context()
        win_rate = context.get("rolling_win_rate", 0)
        total_trades = context.get("total_trades", 0)
        
        if total_trades >= 10 and win_rate < 40:
            self.bot.alert_edge_decay(win_rate)

    def send_handoff(self, handoff_data):
        """Send the session handoff report."""
        report = format_handoff_telegram(handoff_data)
        if report:
            self.bot.alert_handoff(report)

"""
Alerts Manager — Logic for triggering Telegram notifications.

Listens for:
  - Valid Swing or Scalp setup inside a killzone
  - Edge decay (rolling win rate < threshold)
  - London -> NY handoff (time-based)
"""

import time
import logging
from alerts.telegram_bot import TelegramBot
from core.session_handoff import format_handoff_telegram

logger = logging.getLogger(__name__)

class AlertsManager:
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self.bot = TelegramBot()
        self._last_alert_time: float = 0.0

    def handle_confluence_update(self, data: dict):
        """
        Fire a setup awareness alert when a valid Swing or Scalp setup is detected.
        NOTE: actual trade entry alerts (with SL/TP/lots) are sent by live_strategy,
        not here. This is for dashboard-level awareness only — no cooldown needed.
        """
        if not data.get("tradeable"):
            return

        if not data.get("killzone_active"):
            return

        now = time.time()
        # 5-min cooldown only — prevents duplicate fires within the same M5 bar
        if now - self._last_alert_time < 300:
            return

        swing = data.get("swing", {})
        scalp = data.get("scalp", {})

        if swing.get("is_valid"):
            mode = "Swing"
            score = float(swing.get("score", 0))
        elif scalp.get("is_valid"):
            mode = "Scalp"
            score = float(scalp.get("score", data.get("total", 0)))
        else:
            return

        direction = data.get("direction", "neutral")
        if direction == "neutral":
            return

        price = float(data.get("price", 0))
        session = data.get("session_label", "Unknown")

        # SL/TP from pre-computed levels (optional — may be 0 if not available)
        sl = float(data.get("sl", 0.0))
        tp = float(data.get("tp", 0.0))

        logger.info(f"Trade alert: {direction.upper()} {mode} @ ${price:.2f} | Score {score:.1f} | {session}")
        self.bot.alert_trade_signal(direction, mode, price, score, session, sl=sl, tp=tp)
        self._last_alert_time = now

    def check_edge_decay(self, journal_context: dict):
        """Alert if rolling 10-trade win rate drops below 40%."""
        win_rate = journal_context.get("rolling_win_rate", 0)
        total_trades = journal_context.get("total_trades", 0)
        if total_trades >= 10 and win_rate < 40:
            self.bot.alert_edge_decay(win_rate)

    def send_handoff(self, handoff_data: dict):
        """Send the session handoff report."""
        report = format_handoff_telegram(handoff_data)
        if report:
            self.bot.alert_handoff(report)

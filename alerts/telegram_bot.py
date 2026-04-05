"""
Telegram Bot — Sends trade alerts and system notifications.

Alert Types:
  1. Setup Alert: Score >= 8 inside killzone
  2. Behavioral Warning: Negative pnl trend or poor sleep check
  3. Edge Decay: Rolling 10 win rate < 40%
  4. Feed Failover: Real-time notification if feed switches
"""

import logging
import asyncio
import requests
import config

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self):
        self.token = config.TELEGRAM_BOT_TOKEN
        raw_chat_id = config.TELEGRAM_CHAT_ID
        
        # Support multiple IDs (comma-separated)
        if raw_chat_id:
            self.chat_ids = [cid.strip() for cid in str(raw_chat_id).split(",") if cid.strip()]
        else:
            self.chat_ids = []
            
        self.enabled = bool(self.token and self.chat_ids)
        
        if not self.enabled:
            logger.warning("Telegram Bot disabled: Missing token or chat_id in .env")

    def send_message(self, text: str):
        """Send a synchronous message to all configured chat IDs."""
        if not self.enabled: return
        
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        
        for chat_id in self.chat_ids:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            }
            try:
                resp = requests.post(url, json=payload, timeout=10)
                resp.raise_for_status()
                logger.info(f"Telegram message sent to {chat_id}")
            except Exception as e:
                if "404" in str(e):
                    logger.error(f"Telegram Error (404) for {chat_id}: Invalid Token or ID.")
                else:
                    logger.error(f"Failed to send Telegram message to {chat_id}: {e}")

    async def send_message_async(self, text: str):
        """Send an asynchronous message."""
        if not self.enabled: return
        
        # In a real async bot, we'd use aiohttp, but requests is fine for low volume
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.send_message, text)

    def alert_setup(self, score: float, grade: str, price: float, killzone: str):
        """Send a high-confluence setup alert."""
        msg = (
            f"🎯 <b>XAUUSD SETUP ALERT</b>\n\n"
            f"Score: <b>{score}/12</b>\n"
            f"Grade: <b>{grade}</b>\n"
            f"Price: <b>${price:.2f}</b>\n"
            f"Killzone: <b>{killzone}</b>\n\n"
            f"Check dashboard for full ICT analysis."
        )
        self.send_message(msg)

    def alert_failover(self, event: str, source: str):
        """Send feed status alert."""
        try:
            timestamp = config.get_ist_now().strftime('%H:%M:%S IST')
        except AttributeError:
            # Fallback if config isn't refreshed
            from datetime import datetime, timezone, timedelta
            timestamp = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime('%H:%M:%S IST')

        msg = (
            f"⚠️ <b>SYSTEM ALERT: FEED FAILOVER</b>\n\n"
            f"Event: <b>{event}</b>\n"
            f"Current Source: <b>{source}</b>\n"
            f"Time: {timestamp}"
        )
        self.send_message(msg)

    def alert_edge_decay(self, win_rate: float):
        """Send alert when performance drops below threshold."""
        msg = (
            f"🛑 <b>EDGE DECAY WARNING</b>\n\n"
            f"Rolling 10-trade win rate has dropped to <b>{win_rate:.1f}%</b>.\n"
            f"Recommended Action: Review playbook and consider paper trading."
        )
        self.send_message(msg)

    def alert_handoff(self, report_text: str):
        """Send the London -> NY handoff report."""
        self.send_message(report_text)

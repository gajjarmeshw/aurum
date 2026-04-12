---
name: Trade_Alerts_Manager
description: Orchestrates the multi-channel notification system for trade signals and system health.
---

# Trade Alerts Manager Skill

This skill governs how AURUM communicates with the user via Telegram, Email, and the Web UI.

## Technical Specs

### 1. Telegram Bot: `alerts/telegram_bot.py`
- **Multi-ID Support**: `TELEGRAM_CHAT_ID` in `.env` is a string split by `,` (e.g., `ID1,ID2`).
- **Methods**: 
    - `send_alert(msg)`: General notifications.
    - `alert_failover(reason, target)`: Critical feed switches.
    - `send_handoff(html_data)`: Daily level summaries.

### 2. Email Summary: `alerts/email_summary.py`
- **Trigger**: Called by `FeedManager` daily at **4:30 PM IST (16:30)**.
- **Content**: Last 24h PnL, Win Rate, and total trades executed.

### 3. Alerts Orchestrator: `pipeline/alerts_manager.py`
- **Handled Themes**: `feed_failover`, `feed_restored`, `trade_signal`, `new_bsl_target`.
- **Routing**: Decisions are made based on the `type` key in the event dictionary.

## Key Events Logged
- **ICT Grade A+ / A**: Triggered when the confluence score exceeds thresholds.
- **Failover**: Notifies when the primary data feed drops.
- **Session Handoff**: Daily summary of key levels (BSL/SSL) before the NY session.

## Configuration
- `TELEGRAM_BOT_TOKEN`: The token from BotFather.
- `TELEGRAM_CHAT_ID`: Comma-separated list of IDs (e.g., `-5131169000`).
- `RECEIVER_EMAIL`: Defined in `config.py` for daily summaries.

## Adding New Alerts
To add a new notification type:
1. Define the alert condition in `pipeline/alerts_manager.py`.
2. Add a `send_...` method to `TelegramBot`.
3. Update the `on_alert` handler to route the message.

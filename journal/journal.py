"""
Trade Journal — Logs trades with all behavioral fields.

Stores trades to trades.json with:
  entry/exit prices, SL/TP, P&L, direction, grade, confluence score,
  psychology state, session, timestamp, notes.
"""

import json
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import config

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def log_trade(trade_data: dict) -> dict:
    """
    Log a completed trade to the journal.
    
    trade_data: {
        direction, entry, sl, tp, exit_price, result (WIN/LOSS),
        pnl, lot_size, grade, confluence_score, session, psychology,
        notes (optional)
    }
    """
    trades = _load_trades()

    entry = {
        "id": len(trades) + 1,
        "date": datetime.now(IST).strftime("%Y-%m-%d"),
        "time": datetime.now(IST).strftime("%H:%M"),
        "timestamp": time.time(),
        "direction": trade_data.get("direction", ""),
        "entry": trade_data.get("entry", 0),
        "sl": trade_data.get("sl", 0),
        "tp": trade_data.get("tp", 0),
        "exit_price": trade_data.get("exit_price", 0),
        "result": trade_data.get("result", ""),
        "pnl": trade_data.get("pnl", 0),
        "lot_size": trade_data.get("lot_size", 0.03),
        "grade": trade_data.get("grade", ""),
        "confluence_score": trade_data.get("confluence_score", 0),
        "session": trade_data.get("session", ""),
        "psychology_feeling": trade_data.get("psychology", {}).get("feeling", 0),
        "psychology_reason": trade_data.get("psychology", {}).get("reason", ""),
        "notes": trade_data.get("notes", ""),
        "screenshots": trade_data.get("screenshots", False),
    }

    trades.append(entry)
    _save_trades(trades)

    logger.info(f"Trade #{entry['id']} logged: {entry['result']} ${entry['pnl']:.2f}")
    return entry


def get_trades(count: int | None = None) -> list[dict]:
    """Get all or last N trades."""
    trades = _load_trades()
    if count:
        return trades[-count:]
    return trades


def get_today_trades() -> list[dict]:
    """Get trades from today."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    return [t for t in _load_trades() if t.get("date") == today]


def get_daily_pnl() -> float:
    """Get today's total P&L."""
    return sum(t.get("pnl", 0) for t in get_today_trades())


def get_weekly_pnl() -> float:
    """Get this week's total P&L (Mon-Fri)."""
    now = datetime.now(IST)
    monday = now - timedelta(days=now.weekday())
    monday_str = monday.strftime("%Y-%m-%d")
    trades = _load_trades()
    return sum(t.get("pnl", 0) for t in trades if t.get("date", "") >= monday_str)


def get_account_state() -> dict:
    """Get current account state for dashboard."""
    trades = _load_trades()
    today_trades = get_today_trades()
    total_pnl = sum(t.get("pnl", 0) for t in trades)

    return {
        "balance": config.ACCOUNT_SIZE + total_pnl,
        "daily_pnl": get_daily_pnl(),
        "trades_today": len(today_trades),
        "weekly_pnl": get_weekly_pnl(),
        "total_pnl": total_pnl,
        "total_trades": len(trades),
    }


def get_journal_context() -> dict:
    """Get journal context for the report generator."""
    trades = _load_trades()
    last_5 = trades[-5:] if trades else []

    # Rolling 10-trade win rate
    last_10 = trades[-10:] if len(trades) >= 10 else trades
    wins = sum(1 for t in last_10 if t.get("result") == "WIN")
    win_rate = (wins / len(last_10) * 100) if last_10 else 0

    if len(trades) < 10:
        edge_status = "Insufficient data"
    elif win_rate >= 65:
        edge_status = f"✅ Rolling 10 = {win_rate:.0f}% — Strong"
    elif win_rate >= 50:
        edge_status = f"🟡 Rolling 10 = {win_rate:.0f}% — Moderate"
    else:
        edge_status = f"⚠️ Rolling 10 = {win_rate:.0f}% — WEAK"

    return {
        "last_trades": last_5,
        "edge_status": edge_status,
        "total_trades": len(trades),
        "rolling_win_rate": round(win_rate, 1),
    }


def _load_trades() -> list[dict]:
    """Load trades from JSON file."""
    filepath = config.JOURNAL_FILE
    filepath.parent.mkdir(parents=True, exist_ok=True)
    if filepath.exists():
        try:
            return json.loads(filepath.read_text())
        except json.JSONDecodeError:
            return []
    return []


def _save_trades(trades: list[dict]):
    """Save trades to JSON file."""
    filepath = config.JOURNAL_FILE
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(json.dumps(trades, indent=2))

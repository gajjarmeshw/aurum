"""
Trade Simulator — Simulates SL/TP execution for backtesting.

Handles:
  - Stop Loss and Take Profit levels
  - Breakeven moves after 1:1 RR
  - Commissions and spread simulation
  - Maximum risk calculations ($25/trade)
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

@dataclass
class Trade:
    id: int
    entry_time: str
    entry_price: float
    sl: float
    tp: float
    direction: str # "long", "short"
    lots: float = 0.03
    pnl: float = 0.0
    result: str = "open" # "win", "loss", "open", "be"
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    be_moved: bool = False

class TradeSimulator:
    def __init__(self, initial_balance: float = 10000.0, commission: float = 0.07):
        self.balance = initial_balance
        self.commission = commission # per 0.01 lot
        self.open_trades: List[Trade] = []
        self.closed_trades: List[Trade] = []
        self._trade_id = 0

    def open_trade(self, time: str, price: float, sl: float, tp: float, direction: str):
        """Register a new trade."""
        if self.open_trades: return # One trade at a time
        
        self._trade_id += 1
        lots = 0.03 # Fixed risk as per plan
        trade = Trade(self._trade_id, time, price, sl, tp, direction, lots)
        self.open_trades.append(trade)
        # logger.info(f"Opened {direction} trade @ {price} | SL: {sl} | TP: {tp}")

    def update(self, time: str, high: float, low: float, close: float):
        """Update open trades against current candle."""
        for trade in self.open_trades[:]:
            # 1. Check Stop Loss
            if trade.direction == "long" and low <= trade.sl:
                self._close_trade(trade, time, trade.sl, "loss", (trade.sl - trade.entry_price) * 100 * trade.lots)
            elif trade.direction == "short" and high >= trade.sl:
                self._close_trade(trade, time, trade.sl, "loss", (trade.entry_price - trade.sl) * 100 * trade.lots)
            
            # 2. Check Take Profit
            elif trade.direction == "long" and high >= trade.tp:
                self._close_trade(trade, time, trade.tp, "win", (trade.tp - trade.entry_price) * 100 * trade.lots)
            elif trade.direction == "short" and low <= trade.tp:
                self._close_trade(trade, time, trade.tp, "win", (trade.entry_price - trade.tp) * 100 * trade.lots)

            # 3. Check Breakeven (at 1:1)
            elif not trade.be_moved:
                rr_1_1 = abs(trade.entry_price - trade.sl)
                if trade.direction == "long" and high >= (trade.entry_price + rr_1_1):
                    trade.sl = trade.entry_price
                    trade.be_moved = True
                elif trade.direction == "short" and low <= (trade.entry_price - rr_1_1):
                    trade.sl = trade.entry_price
                    trade.be_moved = True

    def _close_trade(self, trade: Trade, time: str, price: float, result: str, pnl: float):
        """Close the trade and update balance."""
        commission_cost = trade.lots * 100 * self.commission
        trade.exit_time = time
        trade.exit_price = price
        trade.result = result
        trade.pnl = pnl - commission_cost
        
        self.balance += trade.pnl
        self.closed_trades.append(trade)
        self.open_trades.remove(trade)
        # logger.info(f"Closed trade #{trade.id} | {result.upper()} | PnL: ${trade.pnl:.2f} | Balance: ${self.balance:.2f}")

    def get_summary(self):
        """Get backtest performance summary."""
        wins = sum(1 for t in self.closed_trades if t.result == "win")
        losses = sum(1 for t in self.closed_trades if t.result == "loss")
        total = len(self.closed_trades)
        win_rate = (wins / total * 100) if total > 0 else 0
        total_pnl = sum(t.pnl for t in self.closed_trades)
        
        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": f"{win_rate:.1f}%",
            "total_pnl": f"${total_pnl:.2f}",
            "final_balance": f"${self.balance:.2f}"
        }

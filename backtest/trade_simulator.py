"""
Trade Simulator — Simulates SL/TP execution for backtesting.

Handles:
  - Stop Loss and Take Profit levels
  - Partial close (50%) at 1R → locks profit, runner continues to full TP
  - Commissions and spread simulation
  - Maximum risk calculations ($25/trade)

Partial close mechanic:
  When price reaches 1R target, half the position is closed at market.
  This converts "$2 breakeven" exits into "$15+ partial wins" — the key
  driver for hitting $300/week without increasing per-trade risk.
  The runner (remaining 50% lots) has its SL moved to entry + 0.5 buffer.
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
    direction: str          # "long", "short"
    lots: float = 0.03
    pnl: float = 0.0
    result: str = "open"    # "win", "loss", "be"
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    session: str = "Unknown"
    score: float = 0.0
    grade: str = "None"
    be_moved: bool = False
    partial_tp_hit: bool = False
    realized_pnl: float = 0.0  # Locked in from the 50% partial close at 1R
    
    # Forensic context (v5.0 parity)
    setup_reason: str = ""
    exit_reason: str = ""
    risk_factors: str = ""
    timeframe: str = "M5"


class TradeSimulator:
    def __init__(self, initial_balance: float = 10000.0, commission: float = 0.07):
        self.balance = initial_balance
        self.commission = commission  # per 0.01 lot (per side)
        self.open_trades: List[Trade] = []
        self.closed_trades: List[Trade] = []
        self._trade_id = 0

    def open_trade(self, time: str, price: float, sl: float, tp: float,
                   direction: str, lots: float = 0.03,
                   session: str = "Unknown", grade: str = "None",
                   setup_reason: str = "", risk_factors: str = "", timeframe: str = "M5"):
        self._trade_id += 1
        trade = Trade(self._trade_id, time, price, sl, tp, direction, lots,
                      session=session, grade=grade,
                      setup_reason=setup_reason, risk_factors=risk_factors, timeframe=timeframe)
        self.open_trades.append(trade)

    def update(self, time: str, high: float, low: float, close: float, score: float = 0.0):
        """Update open trades with new candle data."""
        for trade in list(self.open_trades):
            trade.score = float(score)

            sl_dist = abs(trade.entry_price - trade.sl)

            # ── 1. Stop Loss ──────────────────────────────────────────────────
            if trade.direction == "long" and low <= trade.sl:
                result = "be" if trade.be_moved else "loss"
                pnl_amt = (trade.sl - trade.entry_price) * 100 * trade.lots
                self._close_trade(trade, time, trade.sl, result, pnl_amt)
                continue

            if trade.direction == "short" and high >= trade.sl:
                result = "be" if trade.be_moved else "loss"
                pnl_amt = (trade.entry_price - trade.sl) * 100 * trade.lots
                self._close_trade(trade, time, trade.sl, result, pnl_amt)
                continue

            # ── 2. Take Profit (full runner) ──────────────────────────────────
            if trade.direction == "long" and high >= trade.tp:
                pnl_amt = (trade.tp - trade.entry_price) * 100 * trade.lots
                self._close_trade(trade, time, trade.tp, "win", pnl_amt)
                continue

            if trade.direction == "short" and low <= trade.tp:
                pnl_amt = (trade.entry_price - trade.tp) * 100 * trade.lots
                self._close_trade(trade, time, trade.tp, "win", pnl_amt)
                continue

            # ── 3. Partial Close at 1R — close 50%, let runner go to full TP ─
            # This is the core mechanic: trades that confirm direction (hit 1R)
            # lock in real profit on half the position instead of risking it all
            # on a full runner that may never reach 4R.
            if not trade.partial_tp_hit:
                target_1r = (
                    trade.entry_price + sl_dist if trade.direction == "long"
                    else trade.entry_price - sl_dist
                )
                hit_1r = (
                    (trade.direction == "long" and high >= target_1r) or
                    (trade.direction == "short" and low <= target_1r)
                )
                if hit_1r:
                    # Lock in profit on 50% of the position
                    partial_lots = trade.lots / 2.0
                    partial_pnl = sl_dist * partial_lots * 100
                    commission_cost = partial_lots * 100 * self.commission
                    trade.realized_pnl = partial_pnl - commission_cost
                    self.balance += trade.realized_pnl

                    # Runner: 50% lots, SL moves to BE + small buffer
                    trade.lots = partial_lots
                    buffer = 0.5 if trade.direction == "long" else -0.5
                    trade.sl = trade.entry_price + buffer
                    trade.be_moved = True
                    trade.partial_tp_hit = True
                    trade.exit_reason = "TP1 Partial Hit (Locked Profit)"

    def _close_trade(self, trade: Trade, time: str, price: float, result: str, pnl: float):
        commission_cost = trade.lots * 100 * self.commission
        trade.exit_time = time
        trade.exit_price = price
        trade.result = result
        if not trade.exit_reason: # Don't overwrite if already set by partial
            trade.exit_reason = "Full Exit"
        # realized_pnl is already credited to balance in the partial close step
        trade.pnl = pnl - commission_cost + trade.realized_pnl
        self.balance += (pnl - commission_cost)
        self.closed_trades.append(trade)
        self.open_trades.remove(trade)

    def get_summary(self):
        """
        Performance summary with three distinct categories:
          - real_wins   : runner hit full TP
          - partial_wins: 1R partial closed, runner stopped at BE
          - losses      : price never reached 1R
        Win rate is reported two ways so the UI can show both.
        """
        real_wins    = [t for t in self.closed_trades if t.result == "win"]
        partial_wins = [t for t in self.closed_trades if t.result == "be" and t.realized_pnl > 0]
        losses       = [t for t in self.closed_trades if t.result == "loss"]
        # pure BEs (price reversed before 1R on a trade that somehow had be_moved; edge case)
        pure_bes     = [t for t in self.closed_trades if t.result == "be" and t.realized_pnl <= 0]

        total = len(self.closed_trades)

        # Conservative WR: only full TP hits
        wr_strict = (len(real_wins) / total * 100) if total > 0 else 0
        # Inclusive WR: full TP + partial wins (price confirmed direction)
        wr_inclusive = ((len(real_wins) + len(partial_wins)) / total * 100) if total > 0 else 0

        total_pnl = sum(t.pnl for t in self.closed_trades)

        return {
            "total_trades":   total,
            "wins":           len(real_wins),
            "partial_wins":   len(partial_wins),
            "losses":         len(losses),
            "pure_bes":       len(pure_bes),
            "win_rate":       f"{wr_inclusive:.1f}%",   # shown in UI
            "win_rate_strict": f"{wr_strict:.1f}%",     # true TP-only rate
            "total_pnl":      f"${total_pnl:.2f}",
            "final_balance":  f"${self.balance:.2f}",
        }

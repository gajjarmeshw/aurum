"""
Results Analyzer — Generates performance reports and equity curves for backtests.

Calculates:
  - Total P&L and ROI
  - Maximum Drawdown (MDD)
  - Profit Factor
  - Average Win vs Average Loss
  - Win Rate
  - Sortino / Sharpe ratios (optional)
"""

import logging
import pandas as pd
import config

logger = logging.getLogger(__name__)

class ResultsAnalyzer:
    def __init__(self, trades: list, initial_balance: float = 10000.0):
        self.trades = trades
        self.initial_balance = initial_balance
        self.df = pd.DataFrame(trades)
        
    def analyze(self):
        """Perform comprehensive analysis of backtest results."""
        if self.df.empty:
            return {"error": "No trades executed during backtest."}
            
        # 1. Equity Curve
        self.df["cumulative_pnl"] = self.df["pnl"].cumsum()
        self.df["equity"] = self.df["cumulative_pnl"] + self.initial_balance
        
        # 2. Key Metrics
        total_pnl = self.df["pnl"].sum()
        roi = (total_pnl / self.initial_balance) * 100
        
        wins = self.df[self.df["result"] == "win"]
        losses = self.df[self.df["result"] == "loss"]
        
        win_rate = (len(wins) / len(self.df)) * 100
        avg_win = wins["pnl"].mean() if not wins.empty else 0
        avg_loss = abs(losses["pnl"].mean()) if not losses.empty else 0
        risk_reward = (avg_win / avg_loss) if avg_loss != 0 else 0
        
        profit_factor = (wins["pnl"].sum() / abs(losses["pnl"].sum())) if not losses.empty else float('inf')
        
        # 3. Drawdown
        self.df["peak_equity"] = self.df["equity"].cummax()
        self.df["drawdown"] = (self.df["peak_equity"] - self.df["equity"]) / self.df["peak_equity"] * 100
        max_drawdown = self.df["drawdown"].max()
        
        summary = {
            "Total P&L": f"${total_pnl:.2f}",
            "ROI": f"{roi:.2f}%",
            "Win Rate": f"{win_rate:.1f}%",
            "Total Trades": len(self.df),
            "Profit Factor": f"{profit_factor:.2f}",
            "Avg Win": f"${avg_win:.2f}",
            "Avg Loss": f"${avg_loss:.2f}",
            "Risk/Reward": f"{risk_reward:.2f}",
            "Max Drawdown": f"{max_drawdown:.2f}%",
            "Final Balance": f"${self.df['equity'].iloc[-1]:.2f}"
        }
        
        # Save results to disk
        res_dir = config.BASE_DIR / "backtest" / "results"
        res_dir.mkdir(parents=True, exist_ok=True)
        self.df.to_csv(res_dir / "latest_backtest.csv", index=False)
        
        logger.info(f"Backtest Analysis Complete: {summary['ROI']} ROI, {summary['Win Rate']} Win Rate.")
        return summary

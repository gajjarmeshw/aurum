"""
Walk-Forward Engine — Bar-by-bar backtest replay.

Simulates the real-time pipeline using historical data.
Ensures zero look-ahead bias by recomputing indicators on each bar.
"""

import logging
import pandas as pd
from core.indicators import compute_indicators
from core.ict_sequence import check_ict_sequence
from core.confluence import score_confluence
from core.dealing_range import analyze_dealing_range
from core.session import get_session_info
import config

logger = logging.getLogger(__name__)

class BacktestEngine:
    def __init__(self, data_path: str, timeframe: str = "15min"):
        self.data_path = data_path
        self.timeframe = timeframe
        self.df = pd.read_csv(data_path)
        self.results = []
        self._current_idx = 50 
        self.mode = "auto" # or "manual"
        
    def run(self):
        """Run the bar-by-bar simulation."""
        logger.info(f"Starting walk-forward backtest on {self.data_path}...")
        
        for i in range(self._current_idx, len(self.df)):
            # slice data up to current bar (NO FUTURE LEAKAGE)
            hist = self.df.iloc[:i+1].to_dict('records')
            current_bar = hist[-1]
            
            # 1. Compute Indicators
            indicators = compute_indicators(hist)
            
            # 2. Analyze Dealing Range (using H4)
            # (In a real backtest, we'd need multi-timeframe CSVs loaded)
            # For simplicity here, we assume single timeframe for demo-engine
            dr = analyze_dealing_range(hist) 
            
            # 3. Check ICT Sequence
            ict = check_ict_sequence(indicators, current_bar['close'])
            
            # 4. Confluence Score
            session = get_session_info([]) # mock news
            score = score_confluence(indicators, ict, dr, session, current_bar['close'])
            
            # 5. Record state
            if score.total >= 8:
                self.results.append({
                    "timestamp": current_bar['datetime'],
                    "price": current_bar['close'],
                    "score": score.total,
                    "grade": ict.grade
                })
                
        logger.info(f"Backtest complete. Found {len(self.results)} potential setups.")
        return self.results

    def step(self):
        """Single step for manual mode — returns current state + check for trigger."""
        if self._current_idx >= len(self.df):
            return None
            
        hist = self.df.iloc[:self._current_idx+1].to_dict('records')
        current_bar = hist[-1]
        
        indicators = compute_indicators(hist)
        dr = analyze_dealing_range(hist)
        ict = check_ict_sequence(indicators, current_bar['close'])
        session = get_session_info([])
        score = score_confluence(indicators, ict, dr, session, current_bar['close'])
        
        state = {
            "candle": current_bar,
            "score": score.total,
            "grade": ict.grade,
            "indicators": {
                "fvg": [vars(f) for f in indicators.get("fvgs_h1", [])],
                "ob": [vars(o) for o in indicators.get("obs_m15", [])]
            }
        }
        
        self._current_idx += 1
        return state

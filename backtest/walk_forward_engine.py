"""
Walk-Forward Engine — Bar-by-bar backtest replay.

Simulates the real-time pipeline using historical data.
Ensures zero look-ahead bias by recomputing indicators on each bar.
"""

import logging
import warnings
import pandas as pd

# Suppress Pandas 3.0 internal deprecation warnings during resample/index operations
warnings.simplefilter(action='ignore', category=FutureWarning)

from core.indicators import compute_indicators
from core.ict_sequence import check_ict_sequence
from core.confluence import compute_confluence
from core.dealing_range import compute_dealing_range
from core.session import get_session_info
import config

logger = logging.getLogger(__name__)

class BacktestEngine:
    def __init__(self, data_path: str, timeframe: str = "15min", start_date: str = None, end_date: str = None):
        self.data_path = data_path
        self.timeframe = timeframe
        self.full_df = pd.read_csv(data_path)
        
        # Ensure datetime is sorted and converted
        self.full_df = self.full_df.copy()
        self.full_df['datetime'] = pd.to_datetime(self.full_df['datetime'])
        # Filter out weekend data (Sat=5, Sun=6) — forex markets are closed
        self.full_df = self.full_df[self.full_df['datetime'].dt.dayofweek < 5]
        self.full_df = self.full_df.sort_values('datetime').reset_index(drop=True)
        # Pre-calculate timestamp for indicators/resampling
        self.full_df['timestamp'] = self.full_df['datetime'].apply(lambda x: x.timestamp())
        logger.info(f"Loaded {len(self.full_df)} bars (weekends excluded)")
        
        # Find start index
        logger.info(f"Filtering data: {start_date} to {end_date}")
        min_dt = self.full_df['datetime'].min()
        max_dt = self.full_df['datetime'].max()
        
        if start_date:
            try:
                start_dt = pd.to_datetime(start_date)
                # Clamp to range
                if start_dt < min_dt: start_dt = min_dt
                if start_dt > max_dt: start_dt = max_dt
                
                start_mask = self.full_df['datetime'] >= start_dt
                self._current_idx = start_mask.idxmax() if start_mask.any() else len(self.full_df)
            except Exception as e:
                logger.error(f"Error parsing start_date {start_date}: {e}")
                self._current_idx = 0
        else:
            self._current_idx = min(100, len(self.full_df) - 1) if len(self.full_df) > 0 else 0
            
        # Find end index
        if end_date:
            try:
                end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1)
                # Clamp to range
                if end_dt > max_dt + pd.Timedelta(days=1): end_dt = max_dt + pd.Timedelta(days=1)
                
                end_mask = self.full_df['datetime'] >= end_dt
                self._end_idx = end_mask.idxmax() if end_mask.any() else len(self.full_df)
            except Exception as e:
                logger.error(f"Error parsing end_date {end_date}: {e}")
                self._end_idx = len(self.full_df)
        else:
            self._end_idx = len(self.full_df)
            
        # Final safety check: ensure start < end
        if self._current_idx >= self._end_idx and len(self.full_df) > 0:
            # If they are stuck at the end, give them the last few bars
            self._current_idx = max(0, self._end_idx - 100)
            
        logger.info(f"Final Range Indices: {self._current_idx} to {self._end_idx} (Total: {self._end_idx - self._current_idx} bars)")
            
        self._start_idx = self._current_idx  # Store original start for progress calculation
        self.results = []
        self.mode = "auto" 
        self.total_bars = self._end_idx - self._start_idx

    def run(self):
        """Run the bar-by-bar simulation."""
        if self._current_idx >= self._end_idx:
            logger.warning("No data found for the selected range.")
            return []
            
        logger.info(f"Starting walk-forward backtest... Range: {self._current_idx} to {self._end_idx}")
        
        last_setup_idx = -999  # Track index of last recorded setup for deduplication
        
        for i in range(self._current_idx, self._end_idx):
            # Take up to 1000 bars for warm-up history to cover Higher Timeframes
            start_lookback = max(0, i - 1000)
            hist_df = self.full_df.iloc[start_lookback : i+1].copy()
            
            # Add explicit timestamp column for indicators using safe assignment
            hist_df.loc[:, 'timestamp'] = hist_df['datetime'].apply(lambda x: x.timestamp())
            
            # Resample for higher timeframes
            hist_df.set_index('datetime', inplace=True)
            h1_df = hist_df.resample('1h').agg({
                'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'timestamp': 'last'
            }).dropna().reset_index()
            h4_df = hist_df.resample('4h').agg({
                'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'timestamp': 'last'
            }).dropna().reset_index()
            hist_df.reset_index(inplace=True)

            hist_m15 = hist_df.to_dict('records')
            hist_h1 = h1_df.to_dict('records')
            hist_h4 = h4_df.to_dict('records')
            current_bar = hist_m15[-1]
            
            # Indicators benefit from full hist_df
            indicators = compute_indicators(hist_h4, hist_h1, hist_m15, hist_m15)
            dr = compute_dealing_range(indicators.swing_highs_h4, indicators.swing_lows_h4) 
            session = get_session_info(hist_m15) 
            ict = check_ict_sequence(indicators, session.to_dict(), current_bar['close'], dr.to_dict())
            score = compute_confluence(indicators, ict.to_dict(), dr.to_dict(), session.to_dict(), {}, current_bar['close'])
            
            if score["total"] >= config.CONFLUENCE_MIN_LONDON_NY:
                # Deduplicate: enforce minimum 4-bar (60 min) gap between signals
                if i - last_setup_idx < 4:
                    continue
                last_setup_idx = i
                atr = indicators.atr_h1
                self.results.append({
                    "timestamp": str(current_bar['datetime']),
                    "price": current_bar['close'],
                    "score": score["total"],
                    "grade": ict.grade,
                    "direction": ict.direction,
                    "atr": round(atr, 2),
                    # Provide current bar OHLC for sim to consume
                    "high": current_bar['high'],
                    "low": current_bar['low'],
                    "bar_index": i,
                })
                
        return self.results

    def step(self):
        """Single step for manual mode."""
        if self._current_idx >= self._end_idx:
            return None
            
        hist_df = self.full_df.iloc[:self._current_idx + 1].copy()
        
        # Resample for higher timeframes
        hist_df.set_index('datetime', inplace=True)
        h1_df = hist_df.resample('1h').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'timestamp': 'last'
        }).dropna().reset_index()
        
        h4_df = hist_df.resample('4h').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'timestamp': 'last'
        }).dropna().reset_index()
        hist_df.reset_index(inplace=True)

        hist_m15 = hist_df.to_dict('records')
        hist_h1 = h1_df.to_dict('records')
        hist_h4 = h4_df.to_dict('records')
        current_bar = hist_m15[-1]
        
        # All required indicators
        indicators = compute_indicators(hist_h4, hist_h1, hist_m15, hist_m15)
        dr = compute_dealing_range(indicators.swing_highs_h4, indicators.swing_lows_h4)
        session = get_session_info(hist_m15)
        
        # ICT and Confluence
        self._last_ict = check_ict_sequence(indicators, session.to_dict(), current_bar['close'], dr.to_dict())
        self._last_confluence = compute_confluence(indicators, self._last_ict.to_dict(), dr.to_dict(), session.to_dict(), {}, current_bar['close'])
        
        candle_time = int(current_bar['datetime'].timestamp())
        
        state = {
            "candle": {
                "datetime": candle_time,
                "open": current_bar['open'],
                "high": current_bar['high'],
                "low": current_bar['low'],
                "close": current_bar['close']
            },
            "score": self._last_confluence["total"],
            "grade": self._last_ict.grade,
            "progress": {
                "current": self._current_idx - self._start_idx,
                "end": self._end_idx - self._start_idx,
                "total": self.total_bars
            },
            "indicators": {
                "fvg": [
                    {
                        "start_time": f.timestamp,
                        "end_time": candle_time,
                        "high": f.high,
                        "low": f.low,
                        "direction": f.direction
                    } for f in indicators.fvgs_h1
                ],
                "ob": [
                    {
                        "start_time": o.timestamp,
                        "end_time": candle_time,
                        "high": o.high,
                        "low": o.low,
                        "direction": o.direction
                    } for o in indicators.obs_m15
                ]
            }
        }
        
        self._current_idx += 1
        return state

    def get_current_ict_checklist(self):
        if not hasattr(self, '_last_ict'): return []
        # Return list of steps dynamically from the ICTSequenceResult
        steps = []
        for step in self._last_ict.steps:
            steps.append({
                "label": step.name,
                "checked": step.passed,
                "detail": step.detail
            })
        return steps

    def get_current_confluence(self):
        if not hasattr(self, '_last_confluence'): return []
        # Extract factors with names for the UI list
        factors = []
        for key, val in self._last_confluence.get("breakdown", {}).items():
            factors.append({
                "name": key.replace('_', ' ').capitalize(),
                "score": val
            })
        return factors

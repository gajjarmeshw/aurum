"""
Weight Calibrator — Auto-optimizes confluence weights based on live performance.

Adjusts config weights to favor factors that most frequently lead to wins,
reducing relevance of factors that fail.
"""

import logging
from journal.journal import get_trades

logger = logging.getLogger(__name__)

def calibrate_weights():
    """Adjust confluence weights based on rolling accuracy of each factor."""
    trades = get_trades()
    if len(trades) < 30:
        return None
        
    logger.info("Calibrating confluence weights based on last 30 trades...")
    
    # Future logic: 
    # 1. Take factor scores for each trade
    # 2. Correlate factor scores with Win/Loss result
    # 3. Increase weight of highly correlated factors
    
    return {
        "ict_sequence_weight": 4.5, # Slightly increased if accuracy is high
        "ote_confluence_weight": 2.5
    }

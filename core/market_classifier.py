"""
Market Regime Classification Engine (v5.0)
Classifies market conditions into 7 distinct regimes to select the optimal strategy.
"""

import logging
import config

logger = logging.getLogger(__name__)

from dataclasses import dataclass

@dataclass
class RegimeInfo:
    regime_type: str
    description: str
    hard_lock: bool
    is_tradeable: bool
    adx_h1: float
    ema_20_50_cross: str
    candle_body_to_range: float

class MarketRegime:
    STRONG_BULL = "STRONG_BULL"
    STRONG_BEAR = "STRONG_BEAR"
    WEAK_BULL = "WEAK_BULL"
    WEAK_BEAR = "WEAK_BEAR"
    TIGHT_RANGE = "TIGHT_RANGE"
    VOLATILE_RANGE = "VOLATILE_RANGE"
    NEWS_DRIVEN = "NEWS_DRIVEN"
    DEAD_MARKET = "DEAD_MARKET"

def classify_market(indicators) -> RegimeInfo:
    """Determines the market regime and returns a detailed info object."""
    adx = indicators.adx
    dmp = indicators.dmp
    dmn = indicators.dmn
    ema_20 = indicators.ema_20
    ema_50 = indicators.ema_50
    atr = indicators.atr_h1
    body_ratio = indicators.candle_body_ratio
    
    # Defaults
    regime_type = MarketRegime.TIGHT_RANGE
    description = "Normal market conditions."
    hard_lock = False
    is_tradeable = True
    
    # 1. Hard-Lock Volatility Filter
    if atr > config.ATR_H1_VOLATILE_CEILING:
        regime_type = MarketRegime.VOLATILE_RANGE
        description = "High volatility detected — safety lock active."
        hard_lock = True
        is_tradeable = False
    elif atr < config.ATR_H1_DEAD_FLOOR:
        regime_type = MarketRegime.DEAD_MARKET
        description = "Dead market conditions — liquidity warning."
        hard_lock = True
        is_tradeable = False
    # 2. News/Momentum Filter
    elif body_ratio > config.MOMENTUM_CANDLE_BODY_MIN and adx > 30:
        regime_type = MarketRegime.NEWS_DRIVEN
        description = "Impulsive expansion detected (News/Surge)."
    # 3. Trends
    elif adx > config.ADX_STRONG_TREND:
        if dmp > dmn and ema_20 > ema_50:
            regime_type = MarketRegime.STRONG_BULL
            description = "High-conviction bullish trend."
        elif dmn > dmp and ema_20 < ema_50:
            regime_type = MarketRegime.STRONG_BEAR
            description = "High-conviction bearish trend."
    elif adx > config.ADX_WEAK_TREND:
        if dmp > dmn:
            regime_type = MarketRegime.WEAK_BULL
            description = "Developing bullish momentum."
        elif dmn > dmp:
            regime_type = MarketRegime.WEAK_BEAR
            description = "Developing bearish momentum."

    cross = "bullish" if ema_20 > ema_50 else "bearish"
    
    return RegimeInfo(
        regime_type=regime_type,
        description=description,
        hard_lock=hard_lock,
        is_tradeable=is_tradeable,
        adx_h1=float(adx),
        ema_20_50_cross=cross,
        candle_body_to_range=float(body_ratio)
    )

def get_config_for_regime(regime_type: str) -> dict:
    """Returns strategy parameters (RR, Lots, etc) based on regime type."""
    return config.STRATEGY_CONFIGS.get(regime_type, {
        "target_rr": 1.5,
        "be_at_rr": 1.0,
        "lots": 0.05
    })

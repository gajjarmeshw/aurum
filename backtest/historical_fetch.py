"""
Historical Fetcher — Downloads high-resolution market data for backtesting.

Fetches data from Twelve Data REST API and saves to CSV/Parquet.
Handles multiple timeframes (M1, M5, M15, H1, H4).
"""

import os
import time
import logging
import pandas as pd
import requests
import config

logger = logging.getLogger(__name__)


def fetch_historical_data(symbol: str, interval: str, outputsize: int = 5000):
    """
    Fetch historical data from Twelve Data.
    
    symbol: "XAU/USD"
    interval: "1min", "5min", "15min", "1h", "4h"
    outputsize: number of bars (max 5000 in free tier)
    """
    logger.info(f"Fetching {outputsize} bars of {symbol} @ {interval}...")
    
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": config.TWELVE_DATA_API_KEY,
        "order": "ASC" # Oldest first for backtesting
    }
    
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        
        if "values" not in data:
            logger.error(f"Failed to fetch data: {data.get('message', 'Unknown error')}")
            return None
            
        df = pd.DataFrame(data["values"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].apply(pd.to_numeric)
        
        # Save to disk
        data_dir = config.BASE_DIR / "backtest" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{symbol.replace('/', '')}_{interval}.csv"
        filepath = data_dir / filename
        df.to_csv(filepath, index=False)
        
        logger.info(f"Saved {len(df)} bars to {filepath}")
        return df

    except Exception as e:
        logger.error(f"Exception during historical fetch: {e}")
        return None


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    fetch_historical_data("XAU/USD", "15min", 1000)
    fetch_historical_data("XAU/USD", "1h", 1000)

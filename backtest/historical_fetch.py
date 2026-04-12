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


def fetch_historical_data(symbol: str, interval: str, outputsize: int = 5000, start_date: str = None, end_date: str = None):
    """
    Fetch historical data from Twelve Data.
    
    symbol: "XAU/USD"
    interval: "1min", "5min", "15min", "1h", "4h"
    outputsize: number of bars (max 5000 in free tier)
    start_date/end_date: optional "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
    """
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": config.TWELVE_DATA_API_KEY,
        "order": "DESC" # Get most recent bars
    }
    
    if start_date: params["start_date"] = start_date
    if end_date: params["end_date"] = end_date
    
    logger.info(f"Fetching {interval} data for {symbol} (Range: {start_date} to {end_date or 'Recent'})...")
    
    url = "https://api.twelvedata.com/time_series"
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        if "values" not in data:
            logger.error(f"Failed to fetch {interval} data: {data.get('message', 'Unknown error')}")
            return None
            
        df = pd.DataFrame(data["values"]).copy()
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Save to disk
        data_dir = config.BASE_DIR / "backtest" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{symbol.replace('/', '')}_{interval}.csv"
        filepath = data_dir / filename
        
        # If file exists, merge and remove duplicates
        if filepath.exists():
            old_df = pd.read_csv(filepath)
            old_df["datetime"] = pd.to_datetime(old_df["datetime"])
            df = pd.concat([old_df, df]).drop_duplicates(subset=["datetime"]).sort_values("datetime")
            
        df.to_csv(filepath, index=False)
        logger.info(f"Updated {filepath} — Total bars: {len(df)}")
        return df

    except Exception as e:
        logger.error(f"Exception during historical fetch: {e}")
        return None


if __name__ == "__main__":
    # Example usage: python backtest/historical_fetch.py
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Fetch core timeframes required for backtesting and H4 analysis range
    fetch_historical_data("XAU/USD", "1min", 5000)
    fetch_historical_data("XAU/USD", "5min", 5000)
    fetch_historical_data("XAU/USD", "15min", 5000)
    fetch_historical_data("XAU/USD", "1h", 5000)
    fetch_historical_data("XAU/USD", "4h", 2000)
    
    print("\n✅ Initialization complete. Data saved to backtest/data/")

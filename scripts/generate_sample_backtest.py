import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def generate_sample_data(filename="XAUUSD_15min.csv", periods=200):
    """Generate synthetic XAUUSD M15 data for testing."""
    start_time = datetime.now() - timedelta(minutes=15 * periods)
    times = [start_time + timedelta(minutes=15 * i) for i in range(periods)]
    
    # Simple random walk for price
    price = 2350.0
    prices = []
    for _ in range(periods):
        price += np.random.normal(0, 5)
        prices.append(price)
        
    df = pd.DataFrame({
        "datetime": [t.strftime("%Y-%m-%d %H:%M:%S") for t in times],
        "open": prices,
        "high": [p + abs(np.random.normal(2)) for p in prices],
        "low": [p - abs(np.random.normal(2)) for p in prices],
        "close": [p + np.random.normal(1) for p in prices],
        "volume": np.random.randint(100, 1000, size=periods)
    })
    
    df.to_csv(filename, index=False)
    print(f"Generated {filename}")

if __name__ == "__main__":
    import os
    os.makedirs("backtest/data", exist_ok=True)
    generate_sample_data("backtest/data/XAUUSD_15min.csv")

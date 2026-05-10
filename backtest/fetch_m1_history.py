"""
Fetch full M1 history for XAUUSD from 2024-01-01 → 2025-11-02 (where existing
M1 data starts). Chunks into 2-day windows to stay safely under OANDA's
5000-bar-per-response cap.

Run: python -m backtest.fetch_m1_history
"""
import time
import logging
import pandas as pd

from backtest.historical_fetch import fetch_historical_data

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

START      = pd.Timestamp("2024-01-01")
END        = pd.Timestamp("2025-11-02")
CHUNK_DAYS = 2          # 2 days = ~2,880 M1 bars max — well under 5000
SLEEP_SEC  = 0.4        # gentle pacing for OANDA API

def main():
    cur = START
    chunk = 0
    total_chunks = (END - START).days // CHUNK_DAYS + 1
    while cur < END:
        chunk_end = min(cur + pd.Timedelta(days=CHUNK_DAYS), END)
        chunk += 1
        log.info(f"[{chunk}/{total_chunks}] {cur.strftime('%Y-%m-%d')} → {chunk_end.strftime('%Y-%m-%d')}")
        try:
            fetch_historical_data(
                "XAU/USD", "1min",
                outputsize=5000,
                start_date=cur.strftime("%Y-%m-%d"),
                end_date=chunk_end.strftime("%Y-%m-%d"),
            )
        except Exception as e:
            log.error(f"Chunk {chunk} failed: {e}")
        cur = chunk_end
        time.sleep(SLEEP_SEC)
    log.info("M1 history fetch complete.")


if __name__ == "__main__":
    main()

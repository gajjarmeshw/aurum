"""
Historical Fetcher — Downloads OHLCV data from OANDA practice API for backtesting.

Same data source as the live feed (OandaFeed) so backtest results match live behavior.
OANDA returns midpoint (bid+ask/2) candles — identical to what the live feed streams.

Saves to CSV with columns: datetime, open, high, low, close, volume
"""

import logging
import pandas as pd
import requests

import config

logger = logging.getLogger(__name__)

OANDA_REST   = "https://api-fxpractice.oanda.com"
INSTRUMENT   = "XAU_USD"
MAX_PER_REQ  = 5000   # OANDA max candles per request

# Map interval strings (used by backtest engine) to OANDA granularity
INTERVAL_MAP = {
    "1min":  "M1",
    "5min":  "M5",
    "15min": "M15",
    "1h":    "H1",
    "4h":    "H4",
}


def fetch_historical_data(
    symbol: str,  # noqa: ARG001 — kept for call-site compatibility
    interval: str,
    outputsize: int = 5000,
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame | None:
    """
    Fetch historical OHLCV candles from OANDA and save/merge to CSV.

    symbol:     ignored (always XAU_USD — kept for API compatibility)
    interval:   "5min", "15min", "1h", "4h"
    outputsize: max bars to fetch (capped at 5000 per request)
    start_date: "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS" — fetch from this datetime
    end_date:   "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS" — fetch up to this datetime
    """
    gran = INTERVAL_MAP.get(interval)
    if not gran:
        logger.error(f"Unknown interval '{interval}' — must be one of {list(INTERVAL_MAP)}")
        return None

    token      = config.OANDA_API_TOKEN
    account_id = config.OANDA_ACCOUNT_ID
    if not token or not account_id:
        logger.error("OANDA_API_TOKEN / OANDA_ACCOUNT_ID not set in .env")
        return None

    headers = {"Authorization": f"Bearer {token}"}
    url     = f"{OANDA_REST}/v3/instruments/{INSTRUMENT}/candles"

    params = {
        "granularity": gran,
        "price":       "M",                  # midpoint (bid+ask/2) — matches live feed
        "count":       min(outputsize, MAX_PER_REQ),
    }

    if start_date:
        params["from"] = _to_rfc3339(start_date)
        params.pop("count", None)            # can't use count with from+to
    if end_date:
        params["to"] = _to_rfc3339(end_date)

    logger.info(
        f"Fetching {interval} ({gran}) data for {INSTRUMENT} "
        f"(Range: {start_date or 'recent'} → {end_date or 'now'}, "
        f"up to {outputsize} bars)..."
    )

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        candles = data.get("candles", [])
        if not candles:
            logger.warning(f"OANDA returned 0 candles for {interval}")
            return None

        rows = []
        for c in candles:
            if not c.get("complete", True):
                continue                     # skip open (incomplete) bar
            mid = c.get("mid", {})
            if not mid:
                continue
            rows.append({
                "datetime": c["time"][:19].replace("T", " "),  # "2026-04-14 09:00:00"
                "open":     float(mid["o"]),
                "high":     float(mid["h"]),
                "low":      float(mid["l"]),
                "close":    float(mid["c"]),
                "volume":   int(c.get("volume", 0)),
            })

        if not rows:
            logger.warning(f"No complete candles returned for {interval}")
            return None

        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)

        # Save / merge with existing CSV
        data_dir  = config.BASE_DIR / "backtest" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        filename  = f"XAUUSD_{interval}.csv"
        filepath  = data_dir / filename

        if filepath.exists():
            old_df = pd.read_csv(filepath)
            old_df["datetime"] = pd.to_datetime(old_df["datetime"])
            df = (
                pd.concat([old_df, df])
                .drop_duplicates(subset=["datetime"])
                .sort_values("datetime")
                .reset_index(drop=True)
            )

        df.to_csv(filepath, index=False)
        logger.info(f"Updated {filepath} — Total bars: {len(df)}")
        return df

    except requests.HTTPError as e:
        logger.error(f"OANDA HTTP error fetching {interval}: {e} — {e.response.text[:200]}")
    except Exception as e:
        logger.error(f"Exception fetching {interval} from OANDA: {e}")
    return None


def _to_rfc3339(dt_str: str) -> str:
    """Convert 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS' to RFC3339 UTC string for OANDA."""
    try:
        dt = pd.Timestamp(dt_str)
        # Assume input is UTC
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    except Exception:
        return dt_str


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    fetch_historical_data("XAU/USD", "5min",  5000)
    fetch_historical_data("XAU/USD", "15min", 5000)
    fetch_historical_data("XAU/USD", "1h",    5000)
    fetch_historical_data("XAU/USD", "4h",    2000)
    print("\n✅ Backtest data ready (OANDA source)")

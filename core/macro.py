"""
Macro Context — DXY, US10Y yield, and gold sentiment data.

Fetches macro data from free APIs:
  - DXY direction: Twelve Data REST
  - US10Y real yield: FRED API (St. Louis Fed)
  - Gold sentiment: NewsAPI free tier
"""

import logging
import time
import requests

import config

logger = logging.getLogger(__name__)

# Cache macro data — refresh at most once per session
_cache = {"dxy": None, "yield": None, "sentiment": None, "last_fetch": 0}
CACHE_TTL = 3600  # 1 hour


def fetch_macro_data() -> dict:
    """
    Fetch all macro context. Returns a complete macro summary dict.
    Uses caching to stay within free tier limits.
    """
    now = time.time()
    if _cache["last_fetch"] and (now - _cache["last_fetch"]) < CACHE_TTL:
        return _build_summary()

    _cache["dxy"] = _fetch_dxy()
    _cache["yield"] = _fetch_us10y()
    _cache["sentiment"] = _fetch_sentiment()
    _cache["last_fetch"] = now

    return _build_summary()


def _fetch_dxy() -> dict:
    """Fetch DXY (US Dollar Index) direction from Twelve Data."""
    try:
        url = "https://api.twelvedata.com/time_series"
        params = {
            "symbol": "DXY",
            "interval": "1h",
            "outputsize": 5,
            "apikey": config.TWELVE_DATA_API_KEY,
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if "values" in data and len(data["values"]) >= 2:
            latest = float(data["values"][0]["close"])
            prev = float(data["values"][1]["close"])
            change = latest - prev
            pct = (change / prev) * 100 if prev else 0

            direction = "falling" if change < 0 else "rising"
            aligned = change < 0  # DXY falling = gold tailwind

            return {
                "value": round(latest, 2),
                "change": round(change, 2),
                "pct": round(pct, 2),
                "direction": direction,
                "aligned": aligned,
                "detail": f"DXY {direction} {abs(pct):.1f}% → {'Gold tailwind ✅' if aligned else 'Gold headwind ⚠️'}",
            }
    except Exception as e:
        logger.warning(f"DXY fetch failed: {e}")

    return {"value": 0, "direction": "unknown", "aligned": False, "detail": "DXY data unavailable"}


def _fetch_us10y() -> dict:
    """Fetch US 10-Year Treasury yield from FRED."""
    try:
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": "DGS10",
            "api_key": "DEMO_KEY",  # FRED allows demo key for basic access
            "file_type": "json",
            "sort_order": "desc",
            "limit": 5,
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        observations = data.get("observations", [])
        # Filter out '.' values
        valid = [o for o in observations if o.get("value", ".") != "."]

        if len(valid) >= 2:
            latest = float(valid[0]["value"])
            prev = float(valid[1]["value"])
            direction = "falling" if latest < prev else "rising"
            aligned = latest < prev  # falling yields = gold bullish

            return {
                "value": round(latest, 2),
                "prev": round(prev, 2),
                "direction": direction,
                "aligned": aligned,
                "detail": f"US10Y {latest:.2f}% ({direction} from {prev:.2f}%) {'✅ Bullish' if aligned else '⚠️ Bearish'}",
            }
    except Exception as e:
        logger.warning(f"US10Y fetch failed: {e}")

    return {"value": 0, "direction": "unknown", "aligned": False, "detail": "Yield data unavailable"}


def _fetch_sentiment() -> dict:
    """Fetch gold-related sentiment from NewsAPI."""
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": "gold price OR XAUUSD OR gold market",
            "sortBy": "publishedAt",
            "pageSize": 5,
            "language": "en",
            "apiKey": config.NEWSAPI_KEY,
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        articles = data.get("articles", [])
        if articles:
            headlines = [a.get("title", "") for a in articles[:5]]
            # Simple keyword-based sentiment
            bullish_keywords = ["surge", "rally", "gain", "rise", "high", "safe haven", "risk-off", "buy"]
            bearish_keywords = ["drop", "fall", "decline", "sell", "crash", "low"]

            bull_count = sum(1 for h in headlines for k in bullish_keywords if k.lower() in h.lower())
            bear_count = sum(1 for h in headlines for k in bearish_keywords if k.lower() in h.lower())

            if bull_count > bear_count:
                bias = "bullish"
            elif bear_count > bull_count:
                bias = "bearish"
            else:
                bias = "neutral"

            return {
                "bias": bias,
                "headlines": headlines[:3],
                "detail": f"Sentiment: {bias.upper()} ({bull_count} bull / {bear_count} bear signals)",
            }
    except Exception as e:
        logger.warning(f"Sentiment fetch failed: {e}")

    return {"bias": "neutral", "headlines": [], "detail": "Sentiment data unavailable"}


def _build_summary() -> dict:
    """Build complete macro summary from cached data."""
    dxy = _cache.get("dxy") or {}
    yld = _cache.get("yield") or {}
    sent = _cache.get("sentiment") or {}

    dxy_aligned = dxy.get("aligned", False)
    yield_aligned = yld.get("aligned", False)
    sent_bullish = sent.get("bias") == "bullish"

    aligned_count = sum([dxy_aligned, yield_aligned, sent_bullish])

    if aligned_count >= 3:
        macro_bias = "BULLISH — all 3 aligned"
    elif aligned_count >= 2:
        macro_bias = "BULLISH — 2/3 aligned"
    elif aligned_count == 1:
        macro_bias = "MIXED — 1/3 aligned"
    else:
        macro_bias = "BEARISH — 0/3 aligned"

    return {
        "dxy": dxy,
        "yield": yld,
        "sentiment": sent,
        "macro_bias": macro_bias,
        "dxy_aligned": dxy_aligned,
        "yield_aligned": yield_aligned,
        "all_aligned": aligned_count >= 2,
        "dxy_detail": dxy.get("detail", ""),
    }

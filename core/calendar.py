"""
Economic Calendar — ForexFactory scraper for high-impact events in IST.

Scrapes ForexFactory for today's economic events and converts to IST.
Falls back to empty list on failure — never blocks the system.
"""

import logging
import time
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
_cache = {"events": [], "last_fetch": 0}
CACHE_TTL = 1800  # 30 minutes


def get_todays_events() -> list[dict]:
    """
    Get today's high-impact economic events in IST.
    
    Returns list of:
      {"time_ist": "HH:MM", "event": str, "impact": "HIGH"|"MED"|"LOW", "currency": str}
    """
    now = time.time()
    if _cache["last_fetch"] and (now - _cache["last_fetch"]) < CACHE_TTL:
        return _cache["events"]

    try:
        events = _scrape_forex_factory()
        if not events:
            logger.info("ForexFactory failed or empty. Trying MyFXBook RSS failover...")
            events = _fetch_from_myfxbook()
            
        _cache["events"] = events
        _cache["last_fetch"] = now
        return events
    except Exception as e:
        logger.warning(f"Calendar fetch failed: {e}")
        return _cache["events"]  # return stale cache if available


def _scrape_forex_factory() -> list[dict]:
    """Scrape ForexFactory calendar for today's events."""
    url = "https://www.forexfactory.com/calendar"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-In-Special-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"ForexFactory request failed: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    events = []

    rows = soup.select("tr.calendar__row")
    for row in rows:
        try:
            impact_el = row.select_one(".calendar__impact span")
            if not impact_el:
                continue

            impact_class = " ".join(impact_el.get("class", []))
            if "high" in impact_class:
                impact = "HIGH"
            elif "medium" in impact_class:
                impact = "MED"
            else:
                continue  # Skip low impact

            currency_el = row.select_one(".calendar__currency")
            currency = currency_el.get_text(strip=True) if currency_el else ""

            # Only care about USD events (affect XAUUSD)
            if currency and currency.upper() != "USD":
                continue

            event_el = row.select_one(".calendar__event")
            event_name = event_el.get_text(strip=True) if event_el else "Unknown"

            time_el = row.select_one(".calendar__time")
            time_str = time_el.get_text(strip=True) if time_el else ""

            # Convert to IST (ForexFactory shows ET by default)
            ist_time = _convert_et_to_ist(time_str)

            events.append({
                "time_ist": ist_time,
                "event": event_name,
                "impact": impact,
                "currency": currency,
            })

        except Exception:
            continue

    logger.info(f"ForexFactory: {len(events)} USD high/med impact events today")
    return events


def _fetch_from_myfxbook() -> list[dict]:
    """Fallback fetcher using MyFXBook's public RSS calendar feed."""
    url = "https://www.myfxbook.com/rss/forex-calendar.xml"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        
        # Simple string-based XML parsing to avoid extra dependencies
        soup = BeautifulSoup(resp.text, "xml")
        items = soup.find_all("item")
        
        events = []
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        for item in items:
            title = item.title.text if item.title else ""
            desc = item.description.text if item.description else ""
            
            # Format usually: "USD - High - Event Name"
            if "USD" not in title: continue
            
            impact = "LOW"
            if "High" in title: impact = "HIGH"
            elif "Medium" in title: impact = "MED"
            else: continue # Skip low impact
            
            # Extract time (MyFXBook RSS uses UTC)
            pub_date = item.pubDate.text if item.pubDate else ""
            # Simple UTC to IST (+5:30)
            ist_time = ""
            if pub_date:
                try:
                    # e.g. "Mon, 06 Apr 2026 12:30:00 GMT"
                    dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z")
                    dt_ist = dt + timedelta(hours=5, minutes=30)
                    ist_time = dt_ist.strftime("%H:%M")
                except: pass
                
            events.append({
                "time_ist": ist_time,
                "event": title.split("-")[-1].strip(),
                "impact": impact,
                "currency": "USD",
            })
            
        return events
    except Exception as e:
        logger.warning(f"MyFXBook failover failed: {e}")
        return []


def _convert_et_to_ist(time_str: str) -> str:
    """Convert Eastern Time string to IST HH:MM format."""
    if not time_str or time_str.lower() in ("", "all day", "tentative"):
        return ""

    try:
        # Parse formats like "8:30am", "2:00pm"
        time_str = time_str.strip().lower()
        if "am" in time_str or "pm" in time_str:
            # Parse AM/PM
            is_pm = "pm" in time_str
            clean = time_str.replace("am", "").replace("pm", "").strip()
            parts = clean.split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0

            if is_pm and hour != 12:
                hour += 12
            elif not is_pm and hour == 12:
                hour = 0

            # ET to IST = +9:30 (ET is UTC-5, IST is UTC+5:30)
            total_min = hour * 60 + minute + 570  # +9h30m
            total_min %= 1440

            ist_hour = total_min // 60
            ist_minute = total_min % 60
            return f"{ist_hour:02d}:{ist_minute:02d}"

    except (ValueError, IndexError):
        pass

    return time_str


def is_nfp_day() -> bool:
    """Check if today is Non-Farm Payroll day (first Friday of month)."""
    now = datetime.now(IST)
    if now.weekday() != 4:  # Friday
        return False
    if now.day <= 7:  # First 7 days = first week
        events = get_todays_events()
        return any("Non-Farm" in e.get("event", "") or "NFP" in e.get("event", "")
                    for e in events)
    return False

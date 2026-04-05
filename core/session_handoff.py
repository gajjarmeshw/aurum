"""
Session Handoff — London close → NY open summary + retracement zones.

Auto-generates at 4:30 PM IST with:
  - London session summary (move, BOS, trade result)
  - NY watch zones (retracement, support, BSL targets)
  - NY thesis + invalidation
  - Killzone countdown
"""

import logging
from datetime import datetime, timezone, timedelta
from core.indicators import IndicatorResult

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def generate_handoff(indicators: IndicatorResult, candles_h1: list[dict],
                      current_price: float, trade_result: dict | None = None) -> dict:
    """
    Generate London → NY session handoff summary.
    
    Returns dict with all handoff data for display and Telegram.
    """
    now = datetime.now(IST)

    # London session data — analyze H1 candles from 13:30 to 16:30 IST
    london_candles = _get_london_candles(candles_h1)

    if not london_candles:
        return {"available": False, "reason": "No London session data"}

    london_open = london_candles[0]["open"]
    london_high = max(c["high"] for c in london_candles)
    london_low = min(c["low"] for c in london_candles)
    london_close = london_candles[-1]["close"]
    london_move = london_close - london_open
    direction = "Bullish" if london_move > 0 else "Bearish"

    # BOS in London
    bos_info = "None detected"
    if indicators.bos_h1:
        last_bos = indicators.bos_h1[-1]
        bos_info = f"Confirmed {last_bos.direction} @ ${last_bos.price:.2f}"

    # Trade result
    trade_summary = "No setup formed"
    if trade_result:
        result = "Win" if trade_result.get("pnl", 0) > 0 else "Loss"
        pnl = trade_result.get("pnl", 0)
        trade_summary = f"{'✅' if pnl > 0 else '❌'} {result} {'+' if pnl > 0 else ''}${pnl:.2f}"

    # NY Watch Zones
    # Primary retracement: last H1 FVG from London
    primary_retrace = None
    if indicators.fvgs_h1:
        unfilled = [f for f in indicators.fvgs_h1 if not f.filled]
        if unfilled:
            fvg = unfilled[-1]
            primary_retrace = {"low": fvg.low, "high": fvg.high}

    # Secondary support: recent swing level flipped
    secondary = None
    if indicators.swing_highs_h1 and london_move > 0:
        # Previous resistance now support
        recent_highs = [s for s in indicators.swing_highs_h1 if s.price < current_price]
        if recent_highs:
            secondary = {"price": recent_highs[-1].price}
    elif indicators.swing_lows_h1 and london_move < 0:
        recent_lows = [s for s in indicators.swing_lows_h1 if s.price > current_price]
        if recent_lows:
            secondary = {"price": recent_lows[-1].price}

    # BSL/SSL target
    bsl_target = None
    ssl_target = None
    for pool in indicators.liquidity_pools:
        if pool.type == "BSL" and not pool.swept:
            bsl_target = pool.price
            break
    for pool in indicators.liquidity_pools:
        if pool.type == "SSL" and not pool.swept:
            ssl_target = pool.price
            break

    # NY thesis
    if london_move > 0:
        thesis = "Bullish continuation — retracement entry preferred"
        invalidation = f"Clean break below ${london_low:.2f}"
    else:
        thesis = "Bearish continuation — retracement entry preferred"
        invalidation = f"Clean break above ${london_high:.2f}"

    # Killzone countdown
    ny_open_min = 18 * 60 + 30  # 18:30 IST
    current_min = now.hour * 60 + now.minute
    mins_to_ny = ny_open_min - current_min
    if mins_to_ny < 0:
        mins_to_ny += 1440

    hours = mins_to_ny // 60
    mins = mins_to_ny % 60

    return {
        "available": True,
        "timestamp": now.strftime("%H:%M IST"),
        "london_summary": {
            "direction": direction,
            "move": round(abs(london_move), 2),
            "open": round(london_open, 2),
            "close": round(london_close, 2),
            "high": round(london_high, 2),
            "low": round(london_low, 2),
            "bos": bos_info,
            "trade": trade_summary,
        },
        "ny_watch": {
            "primary_retrace": primary_retrace,
            "secondary": secondary,
            "bsl_target": round(bsl_target, 2) if bsl_target else None,
            "ssl_target": round(ssl_target, 2) if ssl_target else None,
        },
        "thesis": thesis,
        "invalidation": invalidation,
        "ny_countdown": f"{hours}h {mins}min",
    }


def _get_london_candles(candles_h1: list[dict]) -> list[dict]:
    """Filter H1 candles that fall within London session (13:30–16:30 IST)."""
    london_start = 13 * 60 + 30  # 13:30
    london_end = 16 * 60 + 30    # 16:30
    result = []

    for c in candles_h1:
        ts = c.get("timestamp", 0)
        if ts:
            dt = datetime.fromtimestamp(ts, tz=IST)
            candle_min = dt.hour * 60 + dt.minute
            if london_start <= candle_min < london_end:
                result.append(c)

    return result


def format_handoff_telegram(handoff: dict) -> str:
    """Format handoff data for Telegram alert."""
    if not handoff.get("available"):
        return ""

    ls = handoff["london_summary"]
    nw = handoff["ny_watch"]

    lines = [
        "📊 LONDON SESSION HANDOFF",
        f"Time: {handoff['timestamp']}",
        "",
        f"London: {ls['direction']} +${ls['move']} ({ls['open']}→{ls['close']})",
        f"BOS: {ls['bos']}",
        f"Trade: {ls['trade']}",
        "",
        "NY Watch Zones:",
    ]

    if nw.get("primary_retrace"):
        pr = nw["primary_retrace"]
        lines.append(f"  Primary: ${pr['low']:.2f} – ${pr['high']:.2f}")
    if nw.get("secondary"):
        lines.append(f"  Secondary: ${nw['secondary']['price']:.2f}")
    if nw.get("bsl_target"):
        lines.append(f"  BSL Target: ${nw['bsl_target']}")

    lines.extend([
        "",
        f"Thesis: {handoff['thesis']}",
        f"Invalidation: {handoff['invalidation']}",
        f"NY Opens: {handoff['ny_countdown']}",
    ])

    return "\n".join(lines)

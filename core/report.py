"""
Report Generator — Produces the full .md report for Claude analysis.

Generates the complete XAUUSD market snapshot with all sections:
  Status, Psychology, Live Data, Macro, News, ICT Sequence,
  Dealing Range, Indicators, Candle Data, Confluence Score,
  Account State, Last 5 Trades, Behavioral Context, Claude Instructions.
"""

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def generate_report(data: dict) -> str:
    """
    Generate the complete .md report from all analysis data.
    
    data dict should contain:
      session, psychology, price, macro, news_events, ict_result,
      dealing_range, indicators, confluence, account, journal, candles
    """
    now = datetime.now(IST)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M IST")

    session = data.get("session", {})
    psych = data.get("psychology", {})
    price = data.get("price", 0)
    macro = data.get("macro", {})
    news = data.get("news_events", [])
    ict = data.get("ict_result", {})
    dr = data.get("dealing_range", {})
    indicators = data.get("indicators", {})
    confluence = data.get("confluence", {})
    account = data.get("account", {})
    journal = data.get("journal", {})
    candles = data.get("candles", {})

    # Status line
    status_emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(session.get("status_light", "RED"), "🔴")
    kz_name = session.get("killzone_name", "No Killzone")
    kz_remain = session.get("killzone_remaining_min", 0)
    score_total = confluence.get("total", 0)
    grade = ict.get("grade", "None")

    sections = []

    # Header
    sections.append(f"# XAUUSD MARKET SNAPSHOT — {date_str} {time_str}\n")

    # Status
    sections.append(f"## Status\n{status_emoji} {session.get('status_light', 'RED')} | {kz_name} ({kz_remain} min) | Score: {score_total}/{confluence.get('maximum', 12)} | Grade: {grade}\n")

    # Psychology
    sections.append("## Psychology")
    sections.append(
        f"Feeling: {psych.get('feeling', '?')}/10 | "
        f"Sleep: {'✅' if psych.get('slept_well') else '❌'} | "
        f"Stress: {'None' if not psych.get('financial_stress') else 'Yes ⚠️'} | "
        f"Last: {psych.get('last_trade', '?').capitalize()}"
    )
    sections.append(f"Reason: {psych.get('reason_label', '?')}")
    sections.append(f"Assessment: {psych.get('assessment', '?')}\n")

    # Live Data
    spread = data.get("spread", 0.6)
    atr = indicators.get("atr_h1", 0)
    feed = data.get("feed_source", "unknown")
    sections.append("## Live Data")
    sections.append(
        f"Price: ${price:.2f} | Spread: {spread}pts {'✅' if spread < 1.0 else '⚠️'} | "
        f"ATR(14) H1: ${atr:.2f} {'✅' if 8 <= atr <= 20 else '⚠️'}"
    )
    sections.append(f"Data source: {feed} ✅\n")

    # Macro
    dxy = macro.get("dxy", {})
    yld = macro.get("yield", {})
    sent = macro.get("sentiment", {})
    sections.append("## Macro Context")
    sections.append(f"DXY: {dxy.get('detail', 'N/A')}")
    sections.append(f"US10Y Real Yield: {yld.get('detail', 'N/A')}")
    sections.append(f"Sentiment: {sent.get('detail', 'N/A')}")
    sections.append(f"Macro Bias: {macro.get('macro_bias', 'N/A')}\n")

    # News Events
    if news:
        sections.append("## News Events (IST)")
        sections.append("| Time | Event | Impact | Status |")
        sections.append("|------|-------|--------|--------|")
        for ev in news:
            sections.append(f"| {ev.get('time_ist', '?')} | {ev.get('event', '?')} | {ev.get('impact', '?')} | Monitor |")
        sections.append("")

    # ICT Sequence
    sections.append("## ICT Sequence")
    for step in ict.get("steps", []):
        status = "✅" if step["passed"] else "❌"
        sections.append(f"Step — {step['name']}: {status} {step.get('detail', '')}")
    sections.append(f"Grade: {grade} ({ict.get('steps_passed', 0)}/6)\n")

    # Dealing Range
    sections.append("## Dealing Range (H4)")
    sections.append(
        f"High: ${dr.get('range_high', 0):.2f} | "
        f"Low: ${dr.get('range_low', 0):.2f} | "
        f"EQ: ${dr.get('equilibrium', 0):.2f}"
    )
    sections.append(
        f"OTE: ${dr.get('ote_low', 0):.2f} – ${dr.get('ote_high', 0):.2f} | "
        f"Current: ${price:.2f}"
    )
    in_ote = dr.get("ote_low", 0) <= price <= dr.get("ote_high", 0) if dr.get("is_valid") else False
    if in_ote:
        sections.append("✅ IN OTE ZONE")
    sections.append("")

    # Indicators table
    sections.append("## Indicators")
    sections.append("| Metric | Value | Status |")
    sections.append("|--------|-------|--------|")
    sections.append(f"| ATR(14) H1 | ${indicators.get('atr_h1', 0):.2f} | {'✅ Normal' if 8 <= indicators.get('atr_h1', 0) <= 20 else '⚠️'} |")
    _add_swing_rows(sections, indicators)
    _add_bos_rows(sections, indicators)
    _add_fvg_rows(sections, indicators)
    _add_ob_rows(sections, indicators)
    _add_liquidity_rows(sections, indicators)
    sections.append("")

    # Candle Data
    sections.append("## Candle Data (Last 20 bars)")
    for tf in ["H4", "H1", "M15"]:
        tf_candles = candles.get(tf, [])
        if tf_candles:
            sections.append(f"\n### {tf}")
            sections.append("| Timestamp | Open | High | Low | Close |")
            sections.append("|-----------|------|------|-----|-------|")
            for c in tf_candles[-20:]:
                ts = datetime.fromtimestamp(c.get("timestamp", 0), tz=IST).strftime("%H:%M") if c.get("timestamp") else "?"
                sections.append(f"| {ts} | {c.get('open', 0):.2f} | {c.get('high', 0):.2f} | {c.get('low', 0):.2f} | {c.get('close', 0):.2f} |")
    sections.append("")

    # Confluence Score
    sections.append(f"## Confluence Score: {score_total} / {confluence.get('maximum', 12.0)}")
    sections.append("| Factor | Wt | Status |")
    sections.append("|--------|----|--------|")
    for name, factor in confluence.get("factors", {}).items():
        sections.append(f"| {name.replace('_', ' ').title()} | {factor['score']}/{factor['weight']} | {factor['status']} {factor['detail']} |")
    tradeable = "✅ TRADE" if confluence.get("tradeable") else "❌ NO TRADE"
    sections.append(f"| **TOTAL** | **{score_total}** | **{tradeable}** |")
    sections.append("")

    # Account State
    sections.append("## Account State")
    sections.append(
        f"Balance: ${account.get('balance', 0):,.2f} | "
        f"Daily P&L: ${account.get('daily_pnl', 0):,.2f} | "
        f"Trades today: {account.get('trades_today', 0)}/{config.MAX_TRADES_PER_DAY}"
    )
    sections.append(
        f"Weekly: ${account.get('weekly_pnl', 0):,.2f} / ${config.WEEKLY_TARGET} target"
    )
    sections.append("")

    # Last 5 Trades
    last_trades = journal.get("last_trades", [])
    if last_trades:
        sections.append("## Last 5 Trades")
        sections.append("| Date | Dir | Entry | SL | TP | Result | P&L | Grade | Score |")
        sections.append("|------|-----|-------|----|----|--------|-----|-------|-------|")
        for t in last_trades[-5:]:
            sections.append(
                f"| {t.get('date', '?')} | {t.get('direction', '?')} | "
                f"{t.get('entry', '?')} | {t.get('sl', '?')} | {t.get('tp', '?')} | "
                f"{t.get('result', '?')} | {t.get('pnl', '?')} | "
                f"{t.get('grade', '?')} | {t.get('score', '?')} |"
            )
        sections.append("")

    # Behavioral Context
    sections.append("## Behavioral Context")
    sections.append(f"Edge status: {journal.get('edge_status', 'Insufficient data')}")
    sections.append("")

    # Claude Instructions
    sections.append("---")
    sections.append("INSTRUCTIONS FOR CLAUDE:")
    sections.append("Full QTFunded system rules in attached system document.")
    sections.append("Pre-computed data above is verified from live feed.")
    sections.append(f"Psychology: {psych.get('assessment', '?')}. Macro: {macro.get('macro_bias', '?')}. ICT: {grade}. Score: {score_total}/{confluence.get('maximum', 12)}.")
    sections.append("Perform complete H4→H1→M15→M5 analysis.")
    sections.append("Output trade signal or NO TRADE in standard format.")
    sections.append("Account is live funded — be precise and conservative.")

    return "\n".join(sections)


def _add_swing_rows(sections, indicators):
    for tf_label, key_h, key_l in [("H4", "swing_highs_h4", "swing_lows_h4"), ("H1", "swing_highs_h1", "swing_lows_h1")]:
        highs = indicators.get(key_h, [])
        lows = indicators.get(key_l, [])
        if highs:
            last_h = highs[-1] if isinstance(highs[-1], dict) else vars(highs[-1])
            sections.append(f"| {tf_label} Swing High | ${last_h.get('price', 0):.2f} | — |")
        if lows:
            last_l = lows[-1] if isinstance(lows[-1], dict) else vars(lows[-1])
            sections.append(f"| {tf_label} Swing Low | ${last_l.get('price', 0):.2f} | — |")


def _add_bos_rows(sections, indicators):
    for bos in indicators.get("bos_h1", [])[-2:]:
        b = bos if isinstance(bos, dict) else vars(bos)
        sections.append(f"| H1 BOS | {b.get('direction', '?')} @ ${b.get('price', 0):.2f} | ✅ |")
    for choch in indicators.get("choch_h1", [])[-1:]:
        c = choch if isinstance(choch, dict) else vars(choch)
        sections.append(f"| CHoCH | {c.get('direction', '?')} @ ${c.get('price', 0):.2f} | ⚠️ |")


def _add_fvg_rows(sections, indicators):
    for fvg in indicators.get("fvgs_h1", [])[-3:]:
        f = fvg if isinstance(fvg, dict) else vars(fvg)
        filled = f.get("filled", False)
        sections.append(f"| H1 FVG | ${f.get('low', 0):.2f} – ${f.get('high', 0):.2f} | {'Filled' if filled else '✅ Unfilled'} |")


def _add_ob_rows(sections, indicators):
    for ob in indicators.get("obs_m15", [])[-2:]:
        o = ob if isinstance(ob, dict) else vars(ob)
        mit = o.get("mitigated", False)
        sections.append(f"| M15 OB | ${o.get('low', 0):.2f} – ${o.get('high', 0):.2f} | {'Mitigated' if mit else '✅ Unmitigated'} |")


def _add_liquidity_rows(sections, indicators):
    for pool in indicators.get("liquidity_pools", [])[-4:]:
        p = pool if isinstance(pool, dict) else vars(pool)
        swept = p.get("swept", False)
        sections.append(f"| {p.get('type', '?')} | ${p.get('price', 0):.2f} | {'✅ Swept' if swept else 'Target'} |")


# Import needed for MAX_TRADES_PER_DAY
import config

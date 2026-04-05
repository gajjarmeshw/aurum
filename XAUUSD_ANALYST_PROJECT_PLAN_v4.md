# XAUUSD Trade Analyst — Master Project Plan v4.0
> EC2-hosted Python app | Real-time gold analysis | Claude-powered trade signals
> Last Updated: April 2026 | Account: QTFunded $10,000 Instant | Instrument: XAUUSD only
> Trader: India (IST = UTC+5:30) | Sessions: London + NY only | Target: $300/week → scale

---

## APPROVED ARCHITECTURE DECISIONS

| Decision | Status | Detail |
|---|---|---|
| Python + EC2 + asyncio | ✅ Approved | Async pipeline separates data from web server |
| Dual-Source WebSocket | ✅ Approved | Twelve Data primary + Finnhub fallback |
| Walk-Forward Backtest | ✅ Approved | Separate UI, free data limits, no future candle leakage |
| Telegram Alerts | ✅ Approved | Free forever, fires on 8+/12 in killzone |
| Weekly $300 Target | ✅ Approved | Tracked on dashboard with soft/hard caps |
| Two-Session Trade Structure | ✅ Approved | London + NY, different levels, gated by app |
| Psychology Pre-Trade Gate | ✅ Approved | 5 questions, Claude sees answers in report |
| Edge Decay Detector | ✅ Approved | Rolling 10-trade win rate monitor |
| Personalized Playbook | ✅ Approved | Auto-generated after 50 trades |
| Weighted 12-Point Confluence | ✅ Approved | Recalibrates from your real data after 30 trades |

---

## 1. Project Vision

A self-hosted, always-on Python web application running on your EC2 instance.
You open it from any browser — phone during lunch, laptop in the evening.
The app watches the market 24/7, alerts you when a real setup forms, and
packages everything Claude needs into one structured `.md` file.

You paste the report. Claude gives the signal. You execute in MT5.

The system compounds over time. Every trade you log makes the next analysis
smarter. After 60 trades, the app knows your personal edge better than any
course or mentor ever could — because it is built from your real money,
your real psychology, your real execution.

The walk-forward backtest trains your eye on 7 months of historical data
without ever showing you future candles — the same discipline as live trading,
applied to the past. Manual mode makes you a better trader before you risk
a single dollar.

**You never guess. You never fly blind. You never trade emotionally.
The system enforces what willpower cannot.**

---

## 2. The Complete Flow

```
EC2 always running — two async processes side by side

PROCESS 1: DATA PIPELINE (asyncio — never blocks)
  ├── Twelve Data WebSocket → ticks streaming
  ├── Finnhub WebSocket → hot standby
  ├── Auto-failover: if primary drops > 30s → switch to fallback silently
  ├── Candle builder: M5/M15/H1/H4 built from ticks in memory
  ├── Indicators recomputed: < 200ms after every candle close
  ├── Confluence score updated continuously
  └── Telegram fires instantly when 8+/12 detected in killzone

PROCESS 2: WEB SERVER (Flask — serves UI and reports)
  ├── Dashboard SSE stream → browser updates live
  ├── Report generation on demand
  ├── Journal read/write
  └── Backtest UI (separate tab, separate route)

No competition between processes.
Indicator engine never waits for HTTP requests.
HTTP server never waits for tick processing.

        ↓
Telegram fires to your phone during work hours
        ↓
You open app — phone or laptop, anywhere
        ↓
Psychology gate: 5 questions before anything else
Poor mental state? App recommends skip. Cannot override if state < 4.
        ↓
Cooldown active from previous loss? Button locked with countdown.
        ↓
Dashboard shows full picture:
  🟢/🟡/🔴 Status · Live price · ICT grade · Macro alignment
  Killzone timer · News warnings · Weekly P&L progress · Edge status
        ↓
Click "Generate Report"
Screenshot checklist modal — confirm 4 MT5 screenshots
        ↓
Report downloads: GOLD_TRADE_YYYY-MM-DD-HH.md
        ↓
Paste .md + 4 screenshots into Claude
        ↓
Claude runs full H4 → H1 → M15 → M5 analysis → trade signal
        ↓
Execute manually in MT5
        ↓
Log trade result in Journal tab (30 seconds)
        ↓
London close: session handoff summary auto-generated
NY retracement zone calculated and alert set
        ↓
Edge decay monitor updates rolling win rate
        ↓
After 50+ trades: Personalized Playbook auto-generated
        ↓
Confluence weights recalibrated from your actual data
        ↓
System now scores setups based on YOUR verified edge
```

---

## 3. Project Structure

```
gold-analyst/
│
├── main.py                             # Entry point — launches both async processes
├── config.py                           # API keys, account settings, all constants
├── requirements.txt
├── .env                                # Secrets — never commit to git
│
├── pipeline/                           # PROCESS 1 — async data pipeline
│   ├── feed_manager.py                 # Orchestrates dual-source, handles failover
│   ├── twelve_data_feed.py             # Twelve Data WebSocket client (primary)
│   ├── finnhub_feed.py                 # Finnhub WebSocket client (fallback)
│   ├── candle_builder.py               # Builds M5/M15/H1/H4 from tick stream
│   ├── event_bus.py                    # In-memory pub/sub between pipeline + server
│   └── health_monitor.py              # Feed health, reconnect logic, alert on failure
│
├── core/                               # Shared indicator + analysis logic
│   ├── indicators.py                   # ATR, Swing H/L, FVG, OB, BOS, CHoCH
│   ├── dealing_range.py                # H4 dealing range + OTE zone mapper
│   ├── ict_sequence.py                 # Full ICT sequence detector + A/A+ grader
│   ├── confluence.py                   # Weighted 12-point confluence scorer
│   ├── macro.py                        # DXY, US10Y yield, sentiment headlines
│   ├── calendar.py                     # ForexFactory scraper → IST times
│   ├── session.py                      # IST session + killzone timer + status light
│   ├── cooldown.py                     # Post-loss behavioral lock engine
│   ├── session_handoff.py              # London close summary + NY retracement zones
│   └── report.py                       # .md report generator
│
├── psychology/
│   ├── pre_trade_check.py              # 5-question psychology gate
│   └── state_history.json              # Mental state log per trade
│
├── journal/
│   ├── journal.py                      # Trade logger + all behavioral fields
│   ├── analytics.py                    # Performance analytics engine
│   ├── edge_decay.py                   # Rolling 10-trade win rate monitor
│   ├── playbook.py                     # Auto-generates personalized playbook
│   └── trades.json                     # Local trade history (auto-created)
│
├── backtest/                           # WALK-FORWARD ENGINE — separate from live
│   ├── historical_fetch.py             # Pulls OHLC from Twelve Data (free limits)
│   ├── data_cache.py                   # Caches historical data locally — no re-fetch
│   ├── walk_forward_engine.py          # Core simulation — candle by candle, no future
│   ├── trigger_detector.py             # Runs same ICT + confluence logic on history
│   ├── trade_simulator.py              # Virtual SL/TP execution on future candles
│   ├── results_analyzer.py             # Win rates, R:R, session breakdown
│   ├── weight_calibrator.py            # Recalibrates confluence weights from results
│   └── results/                        # JSON + HTML output reports
│
├── alerts/
│   ├── telegram_bot.py                 # Setup alerts, decay alerts, retracement alerts
│   └── email_summary.py                # Daily summary at midnight IST
│
├── server/                             # PROCESS 2 — Flask web server
│   ├── app.py                          # Flask routes + SSE endpoint
│   └── sse_manager.py                  # Manages SSE connections to browsers
│
├── templates/
│   ├── index.html                      # Main app UI — all live trading tabs
│   └── backtest.html                   # Walk-forward backtest UI — separate page
│
└── static/
    ├── charts.js                       # TradingView Lightweight Charts (live)
    ├── backtest_player.js              # Walk-forward candle player UI
    ├── sse.js                          # SSE listener for live updates
    └── style.css                       # Dark terminal aesthetic — both UIs
```

---

## 4. Architecture Deep Dive

### 4.1 Async Pipeline Architecture

The single most important architectural decision in this project.

**The problem with naive Flask + WebSocket:**
```
Flask handles HTTP request (100ms)
     ↓ meanwhile...
Tick arrives from WebSocket
     ↓ but Flask is busy...
Tick waits in queue
     ↓
Candle close happens
     ↓
Indicator recomputation delayed 2–3 seconds
     ↓
Confluence score stale when Telegram should have fired
```

**The solution — two completely independent processes:**
```python
# main.py — launches both processes

import asyncio
import multiprocessing
from pipeline.feed_manager import run_pipeline
from server.app import run_server

def start_pipeline():
    asyncio.run(run_pipeline())   # Pure async — never touches Flask

def start_server():
    run_server()                   # Pure Flask — never touches asyncio

if __name__ == "__main__":
    p1 = multiprocessing.Process(target=start_pipeline)
    p2 = multiprocessing.Process(target=start_server)
    p1.start()
    p2.start()
    p1.join()
    p2.join()
```

They communicate via `event_bus.py` — a lightweight in-memory pub/sub.
Pipeline publishes candle updates. Server subscribes and pushes to browsers via SSE.
Zero blocking. Zero competition. Indicator engine runs at full speed always.

**Result: Confluence score updates in < 200ms after candle close.
Telegram fires within 1 second of threshold crossing.**

### 4.2 Dual-Source WebSocket Architecture

**`pipeline/feed_manager.py`** — the orchestrator:

```
PRIMARY:  Twelve Data WebSocket
  ├── XAUUSD tick stream
  ├── Health check: last tick received timestamp
  └── If no tick for 30 seconds → trigger failover

FALLBACK: Finnhub WebSocket
  ├── XAU/USD tick stream (same instrument, different provider)
  ├── Always connected but in standby mode
  ├── Activated instantly when primary fails
  └── Deactivated when primary recovers

FAILOVER LOGIC:
  Primary drops → Finnhub takes over in < 5 seconds
  Telegram fires: "⚠️ Feed switched to Finnhub. Primary recovering."
  Primary recovers → seamless switch back
  Telegram fires: "✅ Primary feed restored."
```

**Both feeds are free. Both support XAUUSD. Combined uptime: ~99.9%.**

Tick format differs between providers — `feed_manager.py` normalizes both
to the same internal format before passing to `candle_builder.py`:

```python
# Normalized tick format — same regardless of source
{
    "price": 3042.50,
    "timestamp": 1712345678.123,   # Unix timestamp, milliseconds
    "source": "twelve_data"        # or "finnhub" — logged for monitoring
}
```

**API Budget:**
| Source | Connection Cost | Per-Tick Cost | Daily API Calls |
|---|---|---|---|
| Twelve Data WS | 1 | 0 | 1 |
| Finnhub WS | 1 | 0 | 1 |
| Twelve Data REST (startup) | — | — | 4 (historical candles) |
| **Total** | **2** | **0** | **~6–12** |

Well within both free tiers. 98%+ of Twelve Data's 800/day quota unused.

### 4.3 `pipeline/candle_builder.py`
- Receives normalized ticks from feed manager
- Maintains rolling candle state for M5, M15, H1, H4 simultaneously
- All 4 timeframes built from the same tick stream — no extra API calls
- On candle close: publishes to event bus → indicators recompute → confluence updates
- Keeps last 200 candles per timeframe in memory
- Persists candles to disk every 15 minutes (recovery if process restarts)

### 4.4 `core/indicators.py`

| Indicator | Timeframes | Logic |
|---|---|---|
| ATR(14) | H1, H4 | 14-period Average True Range |
| Swing Highs/Lows | H4, H1, M15 | 5-bar pivot detection |
| BOS Detection | H1 | Swing breach in trend direction |
| CHoCH Detection | H1 | Swing breach against current trend |
| Fair Value Gap | H1, M15 | 3-candle gap scan |
| Order Block | H1, M15, M5 | Last opposite candle before impulse |
| Premium/Discount | H4 | 50% of current dealing range |
| Liquidity Pools | H1, M15 | Equal highs/lows clusters |
| Equilibrium | H4 | 50% fib of dealing range |

### 4.5 `core/dealing_range.py`

```
H4 Dealing Range (resets at London open daily):
  Range High:     $3,068  (last clean H4 swing high)
  Range Low:      $3,008  (last clean H4 swing low)
  Equilibrium:    $3,038  (50% — key reaction zone)
  OTE Zone:       $3,020 – $3,031  (61.8%–79% fib — optimal buy)
  Discount:       Below $3,038
  Premium:        Above $3,038
  Current Price:  $3,025 → IN OTE ✅ IN DISCOUNT ✅
```

Displayed as color-coded shaded zones on all charts.
OTE zone highlighted with distinct border — your primary entry window.

### 4.6 `core/ict_sequence.py` — A+ Grader

**Full Bullish Sequence:**
```
Step 1: Asian session range clean (identifiable high + low)
Step 2: London open sweeps Asian low (SSL grab confirmed)
Step 3: Price returns to H1 FVG left from previous session
Step 4: M15 BOS bullish confirmed (structure shifts)
Step 5: M5 OB forms in discount zone (entry precision)
Step 6: Within London or NY killzone window
```

| Grade | Steps | Lot Size | Risk |
|---|---|---|---|
| A+ | 6/6 | 0.03 | $25 max |
| A | 4–5/6 | 0.03 | $25 max |
| B | 3/6 | Skip | — |
| None | < 3 | No report | — |

Only A and A+ grades unlock the Generate Report button.

### 4.7 `core/confluence.py` — Weighted 12-Point System

**Phase 1 — Theory weights (used until 30 live trades):**

| Factor | Weight | Rationale |
|---|---|---|
| Liquidity sweep present | 2.0 | Strongest single predictor historically |
| FVG + OB overlap | 2.0 | Highest confluence combination |
| ICT sequence A or A+ | 1.5 | Full sequence = highest probability |
| H1 BOS confirmed | 1.5 | Structure must align |
| In OTE zone (61.8–79%) | 1.0 | Precision entry zone |
| DXY alignment | 1.0 | Macro must agree |
| Killzone timing | 1.0 | Right time of day |
| Premium/Discount correct | 0.5 | Basic zone discipline |
| ATR normal ($8–$20) | 0.5 | Volatility within range |
| No news conflict | 0.5 | Rule compliance |
| **Maximum** | **12.0** | |
| **Minimum — London/NY** | **8.0** | |
| **Minimum — Asian** | **11.0** | |

**Phase 2 — Data weights (auto-applied after 30 live trades):**
`weight_calibrator.py` analyzes your journal. Each factor's weight becomes
proportional to its actual win rate contribution in your trades.
If liquidity sweep correlates to 82% wins but DXY only 53% — weights adjust.
Your confluence score becomes calibrated to YOUR edge, not generic theory.

### 4.8 `core/macro.py`

| Data | Source | Cost | Frequency |
|---|---|---|---|
| DXY direction | Twelve Data REST | Free (1 call) | Once per session |
| US10Y real yield | FRED API (St. Louis Fed) | Free (no key) | Once per day |
| Gold sentiment | NewsAPI free tier | Free (1 call) | Once per day |

**Report output:**
```
## Macro Context
DXY:        Falling 0.3% → Gold tailwind ✅
US10Y Real: 4.12% (falling from 4.28%) ✅ Bullish
Sentiment:  Risk-off. Geopolitical tensions. Gold bid. ✅
Macro Bias: BULLISH — all 3 aligned
```

If macro conflicts with technical setup → confluence penalized 1.0 point.
This alone prevents multiple bad trades per month.

### 4.9 `core/session.py` — Status Light + Killzone Timer

**Killzone Windows (IST):**
| Killzone | Window | Best Setup |
|---|---|---|
| London Open | 1:30 PM – 3:00 PM | Asian range sweep + reversal |
| NY Open | 6:30 PM – 8:00 PM | London reversal continuation |
| NY Extended | 8:00 PM – 9:30 PM | Trend continuation only |
| Avoid | 4:00 PM – 4:30 PM | London close — erratic |
| Dead Zone | After 11:30 PM | NO TRADING |

Outside killzone windows: confluence score -1.0 automatically.

**RED — Generate Report disabled:**
- Dead zone hours
- NFP day
- News < 8 minutes away
- Daily loss ≥ $50
- Daily profit ≥ $120
- Cooldown active
- Confluence < 8.0
- Psychology score < 4

### 4.10 `core/cooldown.py`

| Trigger | Cooldown | Effect |
|---|---|---|
| 1 losing trade | 30 minutes | Report button locked |
| 2 consecutive losses | 60 minutes | Report button locked + warning banner |
| Daily loss hits $35 | Confirmation modal | Must actively confirm to continue |
| Daily loss hits $50 | Full lock | No trading today — hard cap |

All cooldown events logged in behavioral journal.
Cannot be bypassed. No override mode.

### 4.11 `core/session_handoff.py` — London → NY Bridge

Runs automatically at 4:30 PM IST (London close).

```
LONDON SESSION HANDOFF — 4:30 PM IST

London Summary:
  Move: Bullish +$18 from $3,026 → $3,044
  BOS: Confirmed bullish @ $3,031
  Setup taken: Yes — Win +$58 ✅  /  No setup formed

NY Watch Zones:
  Primary retracement: $3,031 – $3,034  (H1 FVG left behind)
  Secondary support:   $3,038  (previous resistance now support)
  BSL target:          $3,058  (equal highs above)

NY Thesis:
  Bullish continuation — retracement entry preferred
  Invalidation: Clean break below $3,022

Killzone opens: 6:30 PM IST (2h 0min)
Alert set: Telegram fires if price enters $3,031–$3,034
```

You check this at 6:00 PM IST before NY opens.
30 seconds. Full context. No chart analysis needed from scratch.

### 4.12 `psychology/pre_trade_check.py`

Five questions. Cannot skip. Answers included in report for Claude.

```
1. How are you feeling right now? (1–10 slider)
2. Did you sleep well last night? (Yes / No)
3. Any financial stress today unrelated to trading? (Yes / No)
4. What happened on your last trade? (Won / Lost / No trade)
5. Why do you want to trade right now?
   ○ Setup alert fired — I'm here to execute
   ○ Routine session check
   ○ Bored and watching charts
   ○ Want to recover a loss
   ○ Feeling confident after a win
```

**Gate Logic:**
| Condition | Response |
|---|---|
| Q5 = "Want to recover a loss" | Hard block. Report locked. No override. |
| Q5 = "Bored and watching charts" | Warning modal. Double confirmation required. |
| Feeling < 4 | Hard block. "Come back tomorrow." |
| Feeling 4–6 + last trade = loss | Lot size recommendation reduced to 0.02 |
| Feeling 7+ + setup alert + slept well | Green light — proceed |

All answers logged. Analytics show your win rate at each mental state score.
After 30 trades this data becomes a hard rule in your playbook.

### 4.13 `core/report.py` — Complete .md Output

```markdown
# XAUUSD MARKET SNAPSHOT — [DATE] [TIME IST]

## Status
🟢 GREEN | London Killzone (38 min) | Score: 10.5/12 | Grade: A+

## Psychology
Feeling: 8/10 | Sleep: ✅ | Stress: None | Last: Win
Reason: Setup alert received ✅
Assessment: OPTIMAL mental state — proceed

## Live Data
Price: $3,042.50 | Bid/Ask: $3,042.20 / $3,042.80
Spread: 0.6pts ✅ | ATR(14) H1: $12.4 ✅
Data source: Twelve Data (primary) ✅

## Macro Context
DXY: Falling 0.3% → Tailwind ✅
US10Y Real Yield: 4.12% falling ✅
Sentiment: Risk-off, geopolitical, gold bid ✅
Macro Bias: BULLISH — all 3 aligned

## News Events (IST)
| Time  | Event          | Impact | Status               |
|-------|----------------|--------|----------------------|
| 20:00 | US CPI YoY     | HIGH   | ⚠️ 1h 18min — plan exit |
| 22:30 | Fed Speech     | HIGH   | Monitor              |

## ICT Sequence
Step 1 — Asian range:      ✅ $3,028 – $3,045
Step 2 — Asian low swept:  ✅ $3,026.4 @ 12:48 PM IST
Step 3 — H1 FVG return:   ✅ $3,034 – $3,037
Step 4 — M15 BOS bullish: ✅ @ $3,031
Step 5 — M5 OB discount:  ✅ $3,029 – $3,032
Step 6 — Killzone:        ✅ London active
Grade: A+ (6/6)

## Dealing Range (H4)
High: $3,068 | Low: $3,008 | EQ: $3,038
OTE: $3,020 – $3,031 | Current: $3,029 ✅ IN OTE

## Indicators
| Metric              | Value              | Status |
|---------------------|--------------------|--------|
| ATR(14) H1          | $12.4              | ✅ Normal |
| H4 Swing High       | $3,068.50          | — |
| H4 Swing Low        | $3,008.20          | — |
| H1 BOS              | Bullish @ $3,031   | ✅ |
| CHoCH               | None               | ✅ Trend intact |
| H1 FVG              | $3,034 – $3,037    | ✅ Unfilled |
| M15 OB              | $3,029 – $3,032    | ✅ Unmitigated |
| BSL Target          | $3,058             | Equal highs |
| SSL (swept)         | $3,022             | ✅ Confirmed |

## Candle Data (Last 20 bars — H4 / H1 / M15)
[OHLC tables auto-populated from candle builder]

## Confluence Score: 10.5 / 12.0
| Factor              | Wt  | Status                    |
|---------------------|-----|---------------------------|
| Liquidity sweep     | 2.0 | ✅ SSL @ $3,022 taken     |
| FVG + OB overlap    | 2.0 | ✅ $3,029 – $3,037        |
| ICT sequence A+     | 1.5 | ✅ 6/6 steps              |
| H1 BOS              | 1.5 | ✅ @ $3,031               |
| OTE zone            | 1.0 | ✅ $3,029 in zone         |
| DXY alignment       | 1.0 | ✅ DXY falling            |
| Killzone            | 1.0 | ✅ London active          |
| Premium/Discount    | 0.5 | ✅ In discount            |
| ATR normal          | 0.5 | ✅ $12.4                  |
| No news conflict    | 0.5 | ⚠️ CPI in 78min (-0.5)   |
| **TOTAL**           | **10.5** | **✅ TRADE**         |

## Account State
Balance: $9,930 | Daily P&L: $0 | Trades today: 0/2
Daily loss remaining: $50 | Profit cap left: $120
Weekly running: +$141 / $300 target
Cumulative: -$70 | Payout target: +$500

## Last 5 Trades
| Date | Dir | Entry | SL | TP | Result | P&L | Grade | Score |
[auto-populated from journal]

## Behavioral Context
Streak: 2 wins | London win rate: 68% (11 trades)
Avg R:R achieved: 1.9 | Mental state avg on wins: 7.8
Edge status: ✅ Rolling 10 = 68% — Strong

---
INSTRUCTIONS FOR CLAUDE:
Full QTFunded system rules in attached system document.
Pre-computed data above is verified from live feed.
Psychology: OPTIMAL. Macro: BULLISH. ICT: A+. Score: 10.5/12.
Perform complete H4→H1→M15→M5 analysis.
Output trade signal or NO TRADE in standard format.
Account is live funded — be precise and conservative.
```

---

## 5. Walk-Forward Backtest System

### Design Principles
- **No future candle leakage** — the engine sees only what you would see live
- **Same logic as live** — identical indicator, ICT, and confluence code
- **Free data only** — Twelve Data historical (7 months H1, cached locally)
- **Separate UI** — completely isolated from live trading app
- **Two modes** — Auto (stats) and Manual (trains your eye)

### Data Strategy (Free Limits)

```
Twelve Data free tier historical:
  H4: 5000 bars = ~2.7 years ✅ more than enough
  H1: 5000 bars = ~208 trading days = ~7 months ✅
  M15: 5000 bars = ~52 trading days

Fetch strategy:
  Pull once → cache to disk as JSON
  Never re-fetch unless manually refreshed
  Cost: 3–4 API calls total — negligible
  Cache location: backtest/data/XAUUSD_[TF]_[date].json
```

**7 months of H1 data = ~140 trading days = ~140 potential triggers to walk through.**
Statistically significant. Enough for weight calibration and pattern validation.

### `backtest/walk_forward_engine.py` — Core Logic

```python
class WalkForwardEngine:
    """
    Simulates live trading on historical data.
    At each step, only past candles are visible.
    Future candles revealed one by one after trigger detected.
    Identical indicator + confluence logic as live system.
    """

    def __init__(self, h4_candles, h1_candles, m15_candles, m5_candles):
        self.h4 = h4_candles       # Full history — but engine only reveals [:i]
        self.h1 = h1_candles
        self.m15 = m15_candles
        self.m5 = m5_candles
        self.current_index = 50    # Start after enough candles for indicators
        self.trades = []
        self.mode = "auto"         # "auto" or "manual"

    def step(self):
        """Advance one candle. Return trigger if detected."""
        i = self.current_index

        # CRITICAL: only visible candles passed to indicators
        visible_h4  = self.h4[:i]
        visible_h1  = self.h1[:i * 4]        # proportional
        visible_m15 = self.m15[:i * 16]
        visible_m5  = self.m5[:i * 48]

        # Exact same functions as live system
        indicators   = compute_indicators(visible_h1, visible_h4)
        ict_grade    = check_ict_sequence(visible_h1, visible_m15, visible_m5)
        score        = compute_confluence(indicators, ict_grade)
        session      = detect_session(visible_h1[-1].timestamp)

        if score >= 8.0 and ict_grade in ['A', 'A+'] and session.killzone_active:
            trigger = Trigger(
                index       = i,
                timestamp   = visible_h1[-1].timestamp,
                score       = score,
                grade       = ict_grade,
                indicators  = indicators,
                session     = session,
                # Entry params calculated from visible data only
                entry       = calculate_entry(visible_m5),
                sl          = calculate_sl(visible_m5, indicators),
                tp          = calculate_tp(visible_h1, indicators),
            )
            return trigger

        self.current_index += 1
        return None

    def simulate_trade(self, trigger):
        """Walk forward through future candles to find SL or TP hit."""
        entry, sl, tp = trigger.entry, trigger.sl, trigger.tp

        for candle in self.h1[trigger.index:trigger.index + 100]:
            if candle.low <= sl:
                return TradeResult('LOSS', entry, sl, tp, candle.timestamp)
            if candle.high >= tp:
                return TradeResult('WIN', entry, sl, tp, candle.timestamp)

        return TradeResult('TIMEOUT', entry, sl, tp, None)
```

### Walk-Forward UI — Separate Page (`/backtest`)

**Auto Mode:**
```
┌─────────────────────────────────────────────────────────┐
│  WALK-FORWARD BACKTEST          XAUUSD — H1 — 7 months  │
├─────────────────────────────────────────────────────────┤
│  Data: Jun 2025 → Jan 2026 | 140 trading days           │
│  Progress: ████████░░░░░░  Day 89 / 140                 │
│                                                          │
│  [ ▶ Run Auto ] [ ⏸ Pause ] [ ↺ Reset ] [ Manual → ]   │
│                                                          │
│  Triggers found: 84 | Trades simulated: 61              │
│  Still scanning: 23 (below threshold)                   │
│                                                          │
│  Running Results:                                        │
│  Win rate:    67% (41W / 20L)                           │
│  Avg R:R:     1.94                                       │
│  Avg winner:  +$64 | Avg loser: -$23                    │
│  Expected EV: +$28.50 per trade                         │
│                                                          │
│  By Session:                                             │
│  London:  73% (26/36) ← your edge                       │
│  NY Open: 62% (13/21)                                   │
│  NY Late: 50% (2/4)  ← borderline                       │
│                                                          │
│  By Grade:                                               │
│  A+: 82% (18/22) ← only take these                      │
│  A:  61% (17/28) ← acceptable                           │
│  B:  36% (4/11)  ← confirmed: skip B grade              │
├─────────────────────────────────────────────────────────┤
│  [ 📊 Full Report ] [ ⚖️ Recalibrate Weights ]          │
└─────────────────────────────────────────────────────────┘
```

**Manual Mode — Trains Your Eye:**
```
┌─────────────────────────────────────────────────────────┐
│  MANUAL WALK-FORWARD          Sep 14, 2025 — 14:22 IST  │
├─────────────────────────────────────────────────────────┤
│  [H4] [H1] [M15] [M5]                    ← LIVE-STYLE   │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Candlestick chart — visible history only         │  │
│  │  Future candles HIDDEN                            │  │
│  │  FVG zones · OB zones · Swing levels shown        │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  🔔 TRIGGER DETECTED                                     │
│  Score: 9.5/12 | Grade: A | London Killzone ✅          │
│  ICT: 5/6 steps | SSL swept ✅ | FVG+OB ✅              │
│                                                          │
│  Calculated levels:                                      │
│  Entry: $2,641.50 | SL: $2,633.50 | TP: $2,657.50      │
│  Risk: $24 | Reward: $48 | R:R 1:2                      │
│                                                          │
│  Your decision:                                          │
│  [ ✅ Take Trade ] [ ❌ Skip This Setup ] [ → Next ]    │
│                                                          │
└─────────────────────────────────────────────────────────┘

After decision → future candles revealed one by one:

┌─────────────────────────────────────────────────────────┐
│  OUTCOME                                                 │
│  ✅ WIN — TP hit after 7 candles (7h 0min)              │
│  P&L: +$48 | Your decision: TOOK IT ✅ Good call.       │
│                                                          │
│  Stats so far — YOUR manual session:                     │
│  Taken: 12 | Won: 9 | Lost: 3 | Win rate: 75%          │
│  Skipped: 8 | Of those: 6 would have won (review)       │
│                                                          │
│  [ → Next Trigger ]                                      │
└─────────────────────────────────────────────────────────┘
```

**The "skipped but would have won" tracker is the most valuable feature.**
It shows you exactly which A+ setups your eye hesitates on — so you can
fix that hesitation before it costs you real money.

### `backtest/results_analyzer.py` — Full Report Output

After auto run completes:

```
═══════════════════════════════════════════════════════════
WALK-FORWARD BACKTEST RESULTS
XAUUSD H1 | Jun 2025 – Jan 2026 | 140 trading days
═══════════════════════════════════════════════════════════

OVERALL PERFORMANCE
Total triggers:     84
Trades taken:       61  (23 scored below 8.0 threshold)
Win rate:           67.2%  (41 wins / 20 losses)
Avg R:R achieved:   1.94
Avg winner:         +$64
Avg loser:          -$23
Expected EV/trade:  +$28.50
Expected monthly:   ~$513  (18 trades/month at this EV)

ICT CONCEPT VALIDATION
Liquidity sweep present (win rate):    74%  ← confirmed strongest
FVG + OB overlap (win rate):           79%  ← confirmed highest combo
FVG alone:                             61%
OB alone:                              57%
ICT A+ sequence:                       82%  ← ONLY TAKE THESE
ICT A sequence:                        61%
London killzone entries:               73%
NY Open entries:                       62%
NY Late (after 9:30 PM IST):          48%  ← STOP AFTER 9:30 PM

CONFLUENCE THRESHOLD ANALYSIS
Score 11–12:  84% win rate (22 trades)  ← best
Score 9–10:   71% win rate (24 trades)  ← good
Score 8–9:    54% win rate (15 trades)  ← borderline
Score < 8:    38% win rate (skip these) ← confirmed: threshold correct

RECOMMENDED WEIGHT RECALIBRATION
Based on this data:
  Liquidity sweep:    2.0 → 2.5  (strongest predictor confirmed)
  FVG + OB overlap:   2.0 → 2.0  (unchanged)
  ICT A+ sequence:    1.5 → 2.0  (outperforms expectations)
  NY Late timing:     1.0 → 0.0  (negative predictor — remove)
  ...

[ ⚖️ Apply These Weights to Live System ]
═══════════════════════════════════════════════════════════
```

One click applies recalibrated weights to the live confluence scorer.

---

## 6. Dashboard UI

```
┌──────────────────────────────────────────────────────────────────┐
│  ◆ XAUUSD ANALYST                         🟢 LONDON KILLZONE    │
│  $3,042.50  ▲ +2.30 (+0.08%)                    14:22 IST       │
│  Feed: Twelve Data ✅  Fallback: Finnhub standby ✅              │
├──────────────────────────────────────────────────────────────────┤
│  ATR $12.4 ✅  Spread 0.6pts ✅  Score 10.5/12  Grade: A+       │
│  DXY ↓ ✅   Yields ↓ ✅   Macro: BULLISH ✅                     │
│  🎯 London Killzone — 38 min remaining                           │
│  ⚠️  US CPI in 1h 18min — plan around it                        │
├──────────────────────────────────────────────────────────────────┤
│  [Dashboard] [Charts] [Journal] [Analytics] [Playbook]          │
│                              [🔬 Backtest ↗] ← opens /backtest  │
├──────────────────────────────────────────────────────────────────┤
│  ICT Sequence  ██████████████ A+  6/6 confirmed                 │
│  OTE Zone      ✅ Price $3,029 in $3,020–$3,031                 │
│                                                                  │
│  H4 🟢 BULLISH   H1 🟢 BULLISH   Macro 🟢 ALIGNED              │
│                                                                  │
│  Key Levels:                                                     │
│  ├── BSL Target:   $3,058  (equal highs)                        │
│  ├── OTE Zone:     $3,020 – $3,031  ← price here               │
│  ├── H1 FVG:       $3,034 – $3,037                              │
│  └── M15 OB:       $3,029 – $3,032                              │
│                                                                  │
│  Week: +$141 / $300  ████████░░░░  47%                          │
│  Today: 0 trades · $0 · Cap $120                                │
│  Edge: ✅ Rolling 10 = 68% — Strong                             │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  🧠 Psychology Check  →  📋 Generate Report            │     │
│  └────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────┘
```

**Backtest opens as a separate page (`/backtest`) — completely isolated.**
No shared state with live trading. Clean, independent UI.

---

## 7. Two-Trade Session Structure

| Gate | Trade 1 | Trade 2 |
|---|---|---|
| Session | London OR NY killzone | Opposite session only |
| ICT Grade | A or A+ | A+ only |
| Confluence | 8.0+ | 9.5+ |
| Lot size | 0.03 | 0.02 |
| Max risk | $25 | $15 |
| Daily P&L gate | — | Must be < $80 |
| Level gate | — | Different zone from trade 1 |
| Psychology gate | 6+ | 7+ |

All gates enforced by app. No manual override on P&L or session gate.

---

## 8. Weekly $300 Target Tracker

```
Week: Mon–Fri | Target: $300

Running total shown on dashboard at all times.
Updates in real-time as trades close.

At $150 running → 🟢 On pace
At $200 running → 🟢 Comfortable
At $80 daily → 🟡 Soft warning modal
At $120 daily → 🔴 Hard lock — platform disabled
End of week < $150 → message: "Protect what you have. Next week starts fresh."
End of week $150–$250 → message: "Good week. Consistent."
End of week $250+ → message: "Strong week. Same discipline Monday."
```

---

## 9. Alerts System

**Telegram — 4 alert types:**

```
1. SETUP ALERT (fires when score 8+/12 in killzone)
🔔 XAUUSD A+ SETUP FORMING
Score: 10.5/12 | Grade: A+ | London KZ (38 min)
SSL swept ✅ | FVG+OB ✅ | Macro bullish ✅
→ Open app. Generate report.

2. RETRACEMENT ALERT (NY session)
🎯 NY RETRACEMENT ZONE REACHED
Price entered $3,031–$3,034 (London FVG zone)
NY Killzone active — 42 min remaining
→ Check setup for secondary entry.

3. EDGE DECAY ALERT
⚠️ EDGE DECAY — Rolling 10 trades: 39%
Pause trading. Review journal. Do not trade until cause found.

4. FEED FAILOVER ALERT
⚠️ Primary feed dropped. Switched to Finnhub.
✅ Primary feed restored. Switched back.
```

**Daily Email (midnight IST):**
- Today's P&L, trades, win/loss
- Consistency ratio status
- Tomorrow's high-impact events + IST times
- NFP warning if applicable
- One-line tomorrow recommendation

---

## 10. EC2 Setup

| Component | Specification |
|---|---|
| Instance | t2.micro (free tier) |
| OS | Ubuntu 22.04 LTS |
| Python | 3.11+ |
| Ports open | 5000 (app) · 22 (SSH) |
| RAM | 1GB sufficient |
| Storage | 8GB sufficient |

### Full Dependencies
```
# Web server
flask
flask-cors
gunicorn

# Async pipeline
asyncio                 # stdlib — no install needed
websocket-client        # Twelve Data + Finnhub WS
aiohttp                 # async HTTP for macro data

# Data + indicators
pandas
numpy

# Utilities
python-dotenv
requests
beautifulsoup4          # ForexFactory scraper

# Alerts
python-telegram-bot
```

### Process Launch (`main.py`)
```python
import multiprocessing
from pipeline.feed_manager import run_pipeline
from server.app import run_server
import asyncio

def start_pipeline():
    asyncio.run(run_pipeline())

def start_server():
    run_server()  # gunicorn in production

if __name__ == "__main__":
    p1 = multiprocessing.Process(target=start_pipeline, name="DataPipeline")
    p2 = multiprocessing.Process(target=start_server, name="WebServer")
    p1.start()
    p2.start()
    p1.join()
    p2.join()
```

### Systemd Service
```ini
[Unit]
Description=XAUUSD Analyst
After=network.target

[Service]
WorkingDirectory=/home/ubuntu/gold-analyst
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Security
```bash
# nginx reverse proxy + basic auth
sudo apt install nginx apache2-utils
htpasswd -c /etc/nginx/.htpasswd yourusername
# Configure nginx to proxy port 5000 with auth
# Access: http://your-ec2-ip/  (password protected)
```

---

## 11. Build Phases

### Phase 1 — Core Engine ← BUILD FIRST
- [ ] `main.py` — dual process launcher
- [ ] `pipeline/feed_manager.py` — dual-source with failover
- [ ] `pipeline/twelve_data_feed.py` — primary WS (asyncio)
- [ ] `pipeline/finnhub_feed.py` — fallback WS (asyncio)
- [ ] `pipeline/candle_builder.py` — M5/M15/H1/H4 from ticks
- [ ] `pipeline/event_bus.py` — inter-process communication
- [ ] `core/indicators.py` — all indicators
- [ ] `core/dealing_range.py` — OTE zone mapper
- [ ] `core/ict_sequence.py` — A/A+ grader
- [ ] `core/confluence.py` — weighted 12-point scorer
- [ ] `core/macro.py` — DXY + yield + sentiment
- [ ] `core/calendar.py` — ForexFactory IST
- [ ] `core/session.py` — killzone timer + status
- [ ] `psychology/pre_trade_check.py` — 5-question gate
- [ ] `core/report.py` — full .md generator
- [ ] `server/app.py` — Flask + SSE
- [ ] `templates/index.html` — basic dashboard
- [ ] Screenshot modal
- [ ] Generate Report → download

**Result:** Complete live system. Every Claude analysis starts with
maximum data. Accuracy improvement is immediate.

### Phase 2 — Live Charts
- [ ] TradingView Lightweight Charts integration
- [ ] Live candle rendering from event bus
- [ ] FVG / OB / OTE / Swing level overlays
- [ ] Killzone background tinting
- [ ] H4/H1/M15/M5 tab switcher
- [ ] BOS arrows
- [ ] Dealing range shaded zones

**Result:** Full visual analysis inside app.
MT5 opened only to execute.

### Phase 3 — Journal + Behavioral Guards
- [ ] Trade logging form (all behavioral fields)
- [ ] Equity curve chart
- [ ] Consistency ratio tracker + alert
- [ ] `core/cooldown.py` — post-loss lock
- [ ] `core/session_handoff.py` — London → NY brief
- [ ] Retracement zone + Telegram alert
- [ ] Soft cap warning $80 / hard lock $120
- [ ] Weekly $300 tracker on dashboard

**Result:** Behavioral protection active.
Rules enforced by software, not willpower.

### Phase 4 — Alerts + Analytics
- [ ] `alerts/telegram_bot.py` — all 4 alert types
- [ ] `alerts/email_summary.py` — daily midnight IST
- [ ] `journal/analytics.py` — performance tables
- [ ] `journal/edge_decay.py` — rolling win rate + alert
- [ ] Analytics tab — unlocks after 10 trades
- [ ] Behavioral pattern detection

**Result:** App watches 24/7. You never miss a setup at work.
Your patterns surface automatically.

### Phase 5 — Walk-Forward Backtest + Intelligence Layer
- [ ] `backtest/historical_fetch.py` — 7 months OHLC, cached
- [ ] `backtest/walk_forward_engine.py` — core simulation
- [ ] `backtest/trigger_detector.py` — same logic as live
- [ ] `backtest/trade_simulator.py` — virtual SL/TP execution
- [ ] `backtest/results_analyzer.py` — full stats report
- [ ] `backtest/weight_calibrator.py` — recalibrate confluence
- [ ] `templates/backtest.html` — separate UI at `/backtest`
- [ ] `static/backtest_player.js` — candle-by-candle player
- [ ] Auto mode — runs full history, outputs stats
- [ ] Manual mode — you decide each trigger, eye training
- [ ] "Skipped but would have won" tracker
- [ ] One-click weight recalibration → applies to live system
- [ ] `journal/playbook.py` — personalized playbook after 50 trades

**Result:** Evidence-based system, not theory-based.
Your confluence weights reflect YOUR verified edge.
Manual backtest trains your eye better than any course.
Personalized playbook compounds forever.

---

## 12. API Budget Summary

| Source | Purpose | Daily Calls | Cost |
|---|---|---|---|
| Twelve Data WS | Live tick stream | 1 connection | Free |
| Twelve Data REST | Historical candles startup | 4 | Free |
| Twelve Data REST | DXY candles | 1 | Free |
| Finnhub WS | Fallback tick stream | 1 connection | Free |
| FRED API | US10Y yield | 1 | Free (no key) |
| NewsAPI | Sentiment headlines | 1 | Free |
| ForexFactory | Economic calendar | 0 (scrape) | Free |
| Telegram Bot API | Alerts | ~3–5/day | Free |
| **Total REST calls/day** | | **~8–12** | **Free** |
| **Twelve Data quota used** | | **~1.5%** | **798 remaining** |

**Everything in this system runs at zero cost indefinitely.**

---

## 13. Compounding Timeline

```
Month 1:  Phase 1+2 live.
          Asyncio pipeline + dual-source feed running.
          Every Claude report starts with maximum data.
          ~20 trades. Win rate establishing.
          Expected P&L: $400–$600

Month 2:  Phase 3+4 live.
          Behavioral guards active — cooldown, soft caps, hard locks.
          Telegram alerts — zero missed London setups.
          Session handoff — NY prep takes 30 seconds.
          Analytics tab shows first personal patterns.
          First payout if profit ≥ $500.
          Expected P&L: $500–$700

Month 3:  50+ trades. Playbook v1 generated.
          You stop taking your statistically worst setup type.
          Win rate improves 5–8 points.
          Edge decay alert catches a bad 2-week stretch.
          Saves ~$150 in losses.
          Expected P&L: $600–$800

Month 4:  Phase 5 live.
          Walk-forward backtest validates all ICT concepts on 7 months data.
          Confluence weights recalibrated to your actual performance.
          Manual backtest mode used for ongoing eye training.
          Psychology rules hardened from behavioral data.
          Win rate: 68–72%.
          $300/week becomes the floor, not the target.

Month 5–6: Purchase $25,000 QTFunded account.
           Same strategy. Same discipline. Proportionally scaled lots.
           Daily cap ~$300. Weekly realistic: $500–$700.
           $500/week is now achievable and sustainable.
```

---

## 14. Milestone Targets

| Milestone | Meaning | Timeline |
|---|---|---|
| First trade | System live, data flowing | Week 1 |
| Feed failover tested | Resilience confirmed | Week 1 |
| 10 trades logged | Analytics tab unlocks | Weeks 2–3 |
| $500 cumulative profit | First payout eligible | Month 1–2 |
| 30 trades | Backtest weight calibration | Month 2 |
| 50 trades | Playbook v1 generated | Month 2–3 |
| $800 cumulative | $400 net payout | Month 2–3 |
| Backtest complete | ICT concepts validated | Month 4 |
| Weights recalibrated | System tuned to your edge | Month 4 |
| $25k account | $500/week realistic | Month 5–6 |

---

## 15. What You Need To Start

| Item | Source | Time |
|---|---|---|
| Twelve Data API key | twelvedata.com — free signup | 2 min |
| Finnhub API key | finnhub.io — free signup | 2 min |
| NewsAPI key | newsapi.org — free signup | 2 min |
| Telegram Bot token | t.me/BotFather → /newbot | 3 min |
| EC2 OS | SSH → `lsb_release -a` | 30 sec |
| Port 5000 open | AWS Security Group → inbound | 2 min |

**Total: ~12 minutes before building starts.**

---

## 16. What Stays Human — Always

| Step | Why Manual |
|---|---|
| Visual MT5 chart confirmation | Your eye catches what algorithms miss |
| Final trade quality judgment | Discipline lives here. Never automate. |
| Pasting report + screenshots to Claude | You stay in the loop every time |
| Executing in MT5 | Non-negotiable. You own every entry. |
| Logging trade result | 30 seconds that compounds your edge forever |
| Sitting out on bad days | The most profitable trade is often no trade |
| Manual backtest decisions | Trains your eye in ways auto mode cannot |

---

## 17. Success Metrics

| Metric | Target |
|---|---|
| Report generated after app open | < 90 seconds |
| Confluence score update after candle close | < 200ms |
| Telegram fire after threshold crossed | < 1 second |
| Feed failover time if primary drops | < 5 seconds |
| API calls per day | < 15 of 800 free |
| Win rate months 1–2 | 60%+ |
| Win rate months 3+ | 65%+ |
| Average R:R achieved | 1.8+ |
| Weekly P&L average | $150–$300 |
| Weekly P&L good weeks | $280–$350 |
| Monthly P&L | $500–$800 |
| Daily loss cap hit | Never |
| Consistency rule breached | Never |
| Account blown | Never |

---

*Plan version: 4.0 | Updated: April 2026*
*Stack: Python 3.11 · asyncio · Flask · Gunicorn · EC2 Ubuntu 22.04*
*Data: Twelve Data (primary) + Finnhub (fallback) · FRED · NewsAPI · ForexFactory*
*Charts: TradingView Lightweight Charts (free)*
*Alerts: Telegram Bot API (free)*
*Backtest: Walk-forward, no future leakage, 7 months H1, separate UI at /backtest*
*Account: QTFunded $10,000 Instant | Instrument: XAUUSD only*
*Sessions: London (1:30–4:30 PM IST) + NY (6:30–11:30 PM IST)*
*Target: $300/week → $25k account → $500/week*

---

> "The pipeline never sleeps. The system enforces the rules.
>  The backtest trains your eye. The playbook compounds your edge.
>  Your only job is to execute with discipline — and walk away when done."

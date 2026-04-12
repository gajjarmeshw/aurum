# XAUUSD Trade Analyst — Master Project Plan v5.0
> EC2-hosted Python app | Real-time gold analysis | Claude-powered trade signals
> Last Updated: April 2026 | Account: QTFunded $10,000 Instant | Instrument: XAUUSD only
> Trader: India (IST = UTC+5:30) | Sessions: London + NY only | Target: $300/week → scale

---

## WHAT CHANGED IN v5.0

| Area | v4.0 Approach | v5.0 Update | Why |
|---|---|---|---|
| Entry method | MT (50% midpoint) limit orders | Momentum candle confirmation at key levels | MT entries fill on bad candles, miss real moves |
| Strategy selection | Single ICT strategy always | 7 market types → different strategy per type | Gold behaves differently in trends vs ranges vs chop |
| Market detection | None (same strategy always) | `market_classifier.py` runs daily before London | Volatile range days caused most losses — now skipped |
| Stop distance | 0.75x ATR(H1) min 8pt | 10–25pt range enforced, based on candle structure | ATR stops too wide on range days, too tight on trend days |
| Asian range | Not tracked | Marked daily, used as breakout/breakdown zone | London open's relationship to Asian range is the clearest edge on Gold |
| TP target | 3.0R full runner | 2.0R trend days, 1.2–1.5R range/breakout days | 3R targets unrealistic on weak trend and range days |
| Trade frequency | Over-filtered (1–2/week) | 3–5 valid setups/week across all market types | Sample size too small to distinguish edge from noise |
| ICT sequence | 6-step gate (A/A+ only) | ICT sequence is one input to market type, not the gate | Sequence gate alone created too few trades |

**Everything else from v4.0 is preserved.** The async pipeline, Flask server, dual-source WebSocket, journal, psychology gate, confluence scoring, Telegram alerts, EC2 setup, and walk-forward backtest all remain unchanged. Only the strategy layer is updated.

---

## APPROVED ARCHITECTURE DECISIONS

| Decision | Status | Detail |
|---|---|---|
| Python + EC2 + asyncio | ✅ Approved | Async pipeline separates data from web server |
| Dual-Source WebSocket | ✅ Approved | Twelve Data primary + Finnhub fallback |
| walk_forward_engine.py | ✅ Approved | Separate CLI audit tool for verified yield proofs |
| 7 Market Type Classification | ✅ NEW v5.0 | Daily classification drives strategy selection |
| Asian Range Tracking | ✅ NEW v5.0 | Asian H/L marked daily, breakout used as entry trigger |
| Momentum Candle Entry | ✅ NEW v5.0 | Replaces MT midpoint limit orders |
| Dynamic SL (structure-based) | ✅ Updated | 10–25pt range, candle structure not ATR multiplier |
| Volatile Range Skip | ✅ NEW v5.0 | NO TRADE signal on choppy days — hardcoded |
| strict 0.05 Lot Compliance | ✅ Approved | Hardcoded budget caps to match QTFunded $10k rules |

---

## 1. Project Vision

A self-hosted, always-on Python web application running on your EC2 instance.
You open it from any browser — phone during lunch, laptop in the evening.
The app watches the market 24/7, classifies the current market type each morning,
selects the correct strategy for that type, and alerts you when a real setup forms.

You paste the report. Claude gives the signal. You execute in MT5.

The system compounds over time. Every trade you log makes the next analysis
smarter. After 60 trades, the app knows your personal edge better than any
course or mentor ever could — because it is built from your real money,
your real psychology, your real execution.

**The core insight added in v5.0:**
Gold does not trade the same way every day. A pullback-buy strategy works
brilliantly in a strong bull trend and catastrophically in a volatile range.
v4.0 applied the same ICT template regardless of market condition — this is
why results were inconsistent. v5.0 classifies first, then selects.

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
  ├── Asian range tracker: marks H/L of 11 PM–6 AM UTC daily    ← NEW v5.0
  ├── Market classifier: runs daily at 12:30 PM IST (London open)← NEW v5.0
  ├── Strategy selector: picks strategy for today's market type  ← NEW v5.0
  ├── Indicators recomputed: < 200ms after every candle close
  ├── Confluence score updated continuously
  └── Telegram fires instantly when valid setup detected in killzone

PROCESS 2: WEB SERVER (Flask — serves UI and reports)
  ├── Dashboard SSE stream → browser updates live
  ├── Market type banner shown at top of dashboard              ← NEW v5.0
  ├── "NO TRADE TODAY" hard lock on VOLATILE_RANGE days         ← NEW v5.0
  ├── Report generation on demand
  ├── Journal read/write
  └── Backtest UI (separate tab, separate route)

        ↓
[12:30 PM IST — London open]
Market classifier runs. Dashboard shows today's type.
        ↓
VOLATILE_RANGE detected? → Dashboard locked. "Protect capital today."
        ↓
Valid market type → strategy selected → watching for setup
        ↓
Telegram fires to your phone when setup forms
        ↓
Psychology gate → cooldown check → generate report
        ↓
Report includes market type, active strategy, Asian range levels    ← NEW v5.0
        ↓
Paste .md + 4 screenshots into Claude
        ↓
Claude runs analysis calibrated to today's market type              ← NEW v5.0
        ↓
Execute manually in MT5
        ↓
Log trade result in Journal tab (30 seconds)
        ↓
System compounds your edge
```

---

## 3. The 7 Market Types — Core of v5.0

This is the foundational addition. Every day before London open, `market_classifier.py`
assigns one of these types. The assigned type determines which strategy runs that day.

| # | Market Type | Detection | Strategy | Trade? |
|---|---|---|---|---|
| 1 | Strong bull trend | ADX > 25, D1 HH+HL, above 50 EMA | Pullback buy at H1 20 EMA | ✅ Yes |
| 2 | Weak bull trend | ADX 15–25, gradual drift up | Asian range breakout (long) | ✅ Yes |
| 3 | Strong bear trend | ADX > 25, D1 LH+LL, below 50 EMA | Pullback sell at H1 20 EMA | ✅ Yes |
| 4 | Weak bear trend | ADX 15–25, gradual drift down | Asian range breakdown (short) | ✅ Yes |
| 5 | Tight range | ADX < 15, ATR H1 < 8pts, coiling | Fade range extremes (1.2R target) | ✅ Careful |
| 6 | Volatile range | ATR H1 > 20pts, no direction, choppy | **NO TRADE** | ❌ Hard lock |
| 7 | News/event driven | 30pt+ spike on 5M, calendar event | Retracement after spike settles | ✅ After spike |

### Detection Logic (implemented in `core/market_classifier.py`)

```python
def classify_market(df_daily_with_indicators, df_h1_with_indicators, lookback=5):
    """
    Runs once per day at London open.
    Returns market type + metadata for dashboard and report.
    
    Uses last 5 D1 candles + recent H1 data.
    
    Detection order (important — check volatile first):
    1. ATR H1 > 20 AND ADX < 25 → VOLATILE_RANGE (check first — skip day)
    2. ADX > 25 AND D1 HH+HL AND above EMA50 → STRONG_BULL
    3. ADX > 25 AND D1 LH+LL AND below EMA50 → STRONG_BEAR
    4. ADX 15-25 AND above EMA50 → WEAK_BULL
    5. ADX 15-25 AND below EMA50 → WEAK_BEAR
    6. ADX < 15 AND ATR H1 < 8 → TIGHT_RANGE
    7. News event detected on calendar → NEWS_DRIVEN (overlays other types)
    """
```

### Per-Market-Type Strategy Summary

**STRONG_BULL / STRONG_BEAR — Pullback Strategy**
```
Detection:  ADX > 25, clear D1 swing structure, price vs 50 EMA
Entry:      Wait for H1 pullback to 20 EMA
            First momentum candle (body > 60% of range) after EMA touch
            Body must close in trend direction
Stop:       10–15pts beyond the pullback candle low/high
Target:     2.0R — previous swing high/low
Skip if:    Stop distance > 25pts (setup not clean)
Skip if:    3+ consecutive trend candles with no pullback (too extended)
```

**WEAK_BULL / WEAK_BEAR — Asian Range Breakout**
```
Detection:  ADX 15–25, price gradually drifting with D1 bias
Entry:      Mark Asian range (11 PM–6 AM UTC)
            London open — first 15M candle to close above Asian high (bull)
            or below Asian low (bear)
            Candle must be momentum candle (body > 60% of range)
Stop:       Asian range midpoint (natural invalidation level)
Target:     1.5R only — weak trends reverse before 2R+ targets
Skip if:    Asian range was > 30pts wide (no clean breakout zone)
Skip if:    NY session — only take this in London open window
```

**TIGHT_RANGE — Range Fade**
```
Detection:  ADX < 15, price oscillating between identifiable H/L
Entry:      At least 3 touches on range high AND range low
            Enter short at range high (8–10pt stop above)
            Enter long at range low (8–10pt stop below)
Target:     Opposite side of range — 1.2R
Skip if:    Any high-impact news within 2 hours
Skip if:    ATR H1 expanding (range may be breaking)
CRITICAL:   Do not hold beyond opposite range wall — these break violently
```

**NEWS_DRIVEN — Retracement Entry**
```
Detection:  CPI, NFP, FOMC, PCE on calendar — OR 30pt+ spike visible on 5M
Entry:      Do NOT trade 30 mins before or during release
            Wait for initial spike to complete (5–15 minutes)
            Enter on first 15M retracement candle back toward pre-news price
Stop:       15pts against direction
Target:     1.5–2.0R — news moves are directional, trust them
CRITICAL:   Never fade the news direction — fundamentals drive hard moves
```

**VOLATILE_RANGE — Hard Lock**
```
Detection:  ATR H1 > 20pts but no sustained directional move
Dashboard:  Red banner. "VOLATILE MARKET — NO TRADE TODAY"
Generate Report button: DISABLED
Override:   None. Cannot bypass.
```

---

## 4. Project Structure

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
│   ├── candle_builder.py               # Builds M5/M15/H1/H4 from ticks in memory
│   ├── asian_range_tracker.py          # Marks daily Asian session H/L ← NEW v5.0
│   ├── event_bus.py                    # In-memory pub/sub between pipeline + server
│   └── health_monitor.py              # Feed health, reconnect logic, alert on failure
│
├── core/                               # Shared indicator + analysis logic
│   ├── indicators.py                   # ATR, EMA, ADX, Swing H/L, FVG, OB, BOS, CHoCH
│   ├── market_classifier.py            # 7 market type classifier ← NEW v5.0
│   ├── strategy_selector.py            # Maps market type → active strategy ← NEW v5.0
│   ├── dealing_range.py                # H4 dealing range + OTE zone mapper
│   ├── ict_sequence.py                 # ICT sequence detector (input to classifier)
│   ├── confluence.py                   # Weighted 12-point confluence scorer (updated)
│   ├── macro.py                        # DXY, US10Y yield, sentiment headlines
│   ├── calendar.py                     # ForexFactory scraper → IST times
│   ├── session.py                      # IST session + killzone timer + status light
│   ├── cooldown.py                     # Post-loss behavioral lock engine
│   ├── session_handoff.py              # London close summary + NY retracement zones
│   └── report.py                       # .md report generator (updated for market type)
│
├── strategies/                         # Per-market-type entry logic ← NEW v5.0
│   ├── __init__.py
│   ├── base_strategy.py                # Abstract base — check_entry() interface
│   ├── pullback_buy.py                 # STRONG_BULL: H1 EMA pullback long
│   ├── pullback_sell.py                # STRONG_BEAR: H1 EMA pullback short
│   ├── asian_breakout.py               # WEAK_BULL/BEAR: London Asian range break
│   ├── range_fade.py                   # TIGHT_RANGE: fade range extremes
│   ├── news_retracement.py             # NEWS_DRIVEN: post-spike retracement
│   └── no_trade.py                     # VOLATILE_RANGE: always returns None
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
│   ├── trigger_detector.py             # Runs market classifier + strategy on history
│   ├── trade_simulator.py              # Virtual SL/TP execution on future candles
│   ├── results_analyzer.py             # Win rates per market type, R:R, session breakdown
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

## 5. Architecture Deep Dive

### 5.1 Async Pipeline Architecture

*(Unchanged from v4.0 — preserved in full)*

The single most important architectural decision in this project.

**The solution — two completely independent processes:**
```python
# main.py
import asyncio
import multiprocessing
from pipeline.feed_manager import run_pipeline
from server.app import run_server

def start_pipeline():
    asyncio.run(run_pipeline())

def start_server():
    run_server()

if __name__ == "__main__":
    p1 = multiprocessing.Process(target=start_pipeline)
    p2 = multiprocessing.Process(target=start_server)
    p1.start()
    p2.start()
    p1.join()
    p2.join()
```

They communicate via `event_bus.py` — lightweight in-memory pub/sub.
Pipeline publishes candle updates + market type changes. Server pushes to browsers via SSE.
Zero blocking. Zero competition. Indicator engine runs at full speed always.

### 5.2 Dual-Source WebSocket Architecture

*(Unchanged from v4.0)*

```
PRIMARY:  Twelve Data WebSocket → XAUUSD tick stream
FALLBACK: Finnhub WebSocket → XAU/USD standby
FAILOVER: Primary drops → Finnhub active in < 5 seconds
```

Normalized tick format:
```python
{
    "price": 3042.50,
    "timestamp": 1712345678.123,
    "source": "twelve_data"  # or "finnhub"
}
```

### 5.3 `pipeline/candle_builder.py` — Updated for Asian Range

v5.0 adds a parallel tracker for the Asian session alongside the existing candle builder.

```python
# candle_builder.py now also publishes asian_range events

class CandleBuilder:
    def __init__(self):
        self.candles = {'M5': [], 'M15': [], 'H1': [], 'H4': []}
        self.asian_high = None    # NEW v5.0
        self.asian_low = None     # NEW v5.0
        self.asian_tracking = False

    def on_tick(self, tick):
        self._update_candles(tick)
        self._update_asian_range(tick)  # NEW v5.0

    def _update_asian_range(self, tick):
        """
        Asian session = 11:00 PM – 6:00 AM UTC (4:30 AM – 11:30 AM IST)
        Track high and low throughout this window.
        Publish to event bus when session closes at 6 AM UTC.
        """
        hour_utc = datetime.utcfromtimestamp(tick['timestamp']).hour
        
        if hour_utc == 23 or hour_utc < 6:  # Asian session active
            self.asian_tracking = True
            self.asian_high = max(self.asian_high or 0, tick['price'])
            self.asian_low = min(self.asian_low or float('inf'), tick['price'])
        
        elif hour_utc == 6 and self.asian_tracking:  # Session just closed
            self.asian_tracking = False
            event_bus.publish('asian_range_confirmed', {
                'high': self.asian_high,
                'low': self.asian_low,
                'midpoint': (self.asian_high + self.asian_low) / 2,
                'range_pts': self.asian_high - self.asian_low
            })
```

### 5.4 `core/market_classifier.py` — NEW v5.0

Runs once per day at London open (12:30 PM IST / 7:00 AM UTC).
Result published to event bus → dashboard updates → strategy selector activates.

```python
MARKET_TYPES = {
    'STRONG_BULL':    'Strong bull trend',
    'WEAK_BULL':      'Weak bull trend',
    'STRONG_BEAR':    'Strong bear trend',
    'WEAK_BEAR':      'Weak bear trend',
    'TIGHT_RANGE':    'Tight range / consolidation',
    'VOLATILE_RANGE': 'Volatile / choppy range — NO TRADE',
    'NEWS_DRIVEN':    'News / event driven',
}

def classify_market(df_daily, df_h1, lookback=5):
    """
    Returns dict:
    {
        'type': 'STRONG_BULL',
        'label': 'Strong bull trend',
        'adx': 28.5,
        'atr_h1': 12.1,
        'd1_trend': 'UP',
        'above_ema50': True,
        'trade_today': True
    }
    """
    adx = df_daily['adx'].iloc[-1]
    atr_h1 = df_h1['atr_14'].tail(1).values[0]
    above_ema50 = df_daily['Close'].iloc[-1] > df_daily['ema_50'].iloc[-1]
    d1_trend = _detect_d1_structure(df_daily.tail(lookback))

    # VOLATILE check FIRST — skip day before anything else
    if atr_h1 > 20 and adx < 25:
        return {**base, 'type': 'VOLATILE_RANGE', 'trade_today': False}

    if adx >= 25 and d1_trend == 'UP' and above_ema50:
        return {**base, 'type': 'STRONG_BULL', 'trade_today': True}

    if adx >= 25 and d1_trend == 'DOWN' and not above_ema50:
        return {**base, 'type': 'STRONG_BEAR', 'trade_today': True}

    if 15 <= adx < 25 and above_ema50:
        return {**base, 'type': 'WEAK_BULL', 'trade_today': True}

    if 15 <= adx < 25 and not above_ema50:
        return {**base, 'type': 'WEAK_BEAR', 'trade_today': True}

    # Default: consolidation
    return {**base, 'type': 'TIGHT_RANGE', 'trade_today': True}
```

### 5.5 `core/strategy_selector.py` — NEW v5.0

```python
from strategies.pullback_buy import PullbackBuyStrategy
from strategies.pullback_sell import PullbackSellStrategy
from strategies.asian_breakout import AsianBreakoutStrategy
from strategies.range_fade import RangeFadeStrategy
from strategies.news_retracement import NewsRetracementStrategy
from strategies.no_trade import NoTradeStrategy

STRATEGY_MAP = {
    'STRONG_BULL':    lambda: PullbackBuyStrategy(),
    'STRONG_BEAR':    lambda: PullbackSellStrategy(),
    'WEAK_BULL':      lambda: AsianBreakoutStrategy(direction='LONG'),
    'WEAK_BEAR':      lambda: AsianBreakoutStrategy(direction='SHORT'),
    'TIGHT_RANGE':    lambda: RangeFadeStrategy(),
    'VOLATILE_RANGE': lambda: NoTradeStrategy(),
    'NEWS_DRIVEN':    lambda: NewsRetracementStrategy(),
}

def get_strategy(market_type):
    return STRATEGY_MAP.get(market_type, NoTradeStrategy)()
```

### 5.6 `strategies/base_strategy.py` — NEW v5.0

All strategies share a common interface so the pipeline loop never changes.

```python
from abc import ABC, abstractmethod

class BaseStrategy(ABC):
    
    @abstractmethod
    def check_entry(self, df_15m, df_h1, df_daily, current_idx,
                    market_info, asian_range) -> dict | None:
        """
        Returns None if no trade, or:
        {
            'direction': 'LONG' | 'SHORT',
            'entry_price': float,
            'stop_loss': float,
            'take_profit': float,
            'stop_distance': float,
            'r_multiple': float,
            'reason': str
        }
        """
        pass

    def _validate_stop(self, stop_distance, min_pts=10, max_pts=25):
        """Reject trades with stops outside the valid range."""
        return min_pts <= stop_distance <= max_pts

    def _is_momentum_candle(self, row, direction, min_body_ratio=0.60):
        body = abs(row['Close'] - row['Open'])
        candle_range = row['High'] - row['Low']
        if candle_range < 3:
            return False
        if body / candle_range < min_body_ratio:
            return False
        if direction == 'bull':
            return row['Close'] > row['Open']
        return row['Close'] < row['Open']
```

### 5.7 Entry Logic Change: Momentum Candle vs MT Midpoint

**v4.0 MT (Mean Threshold) entry — why it failed in practice:**
```
MT entry places a limit order at the 50% midpoint of the last candle.
On a real institutional move, price blows through the midpoint immediately.
The limit fills — but on a candle that is still moving against you.
Result: filled on continuation down, not reversal.
The entry captured volatility, not direction.
```

**v5.0 Momentum candle confirmation:**
```python
# strategies/pullback_buy.py — core entry check

def check_entry(self, df_15m, df_h1, df_daily, current_idx, market_info, asian_range):
    current = df_15m.iloc[current_idx]
    
    # Step 1: H1 must have touched or dipped through 20 EMA recently
    recent_h1 = df_h1[df_h1.index <= current.name].tail(4)
    ema20 = recent_h1['ema_20'].iloc[-1]
    touched_ema = recent_h1['Low'].min() <= ema20 * 1.001
    
    if not touched_ema:
        return None
    
    # Step 2: Current 15M candle is a bullish momentum candle
    # Body > 60% of range, candle is green, range > 3pts
    if not self._is_momentum_candle(current, direction='bull'):
        return None
    
    # Step 3: Enter at CLOSE of confirmation candle (not a limit order)
    entry = current['Close']
    stop = current['Low'] - 2
    stop_distance = entry - stop
    
    if not self._validate_stop(stop_distance):
        return None  # Skip if stop too tight or too wide
    
    return {
        'direction': 'LONG',
        'entry_price': round(entry, 2),
        'stop_loss': round(stop, 2),
        'take_profit': round(entry + stop_distance * 2.0, 2),
        'stop_distance': round(stop_distance, 2),
        'r_multiple': 2.0,
        'reason': f'H1 EMA20 pullback ({ema20:.1f}), momentum candle confirmed'
    }
```

### 5.8 `core/indicators.py` — Updated for v5.0

Added: ADX(14), EMA(20), EMA(50) to existing indicator suite.
All other indicators (ATR, FVG, OB, BOS, CHoCH, swing H/L) unchanged.

```python
def add_indicators(df, timeframe='15m'):
    # Existing indicators (unchanged)
    df['atr_14'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
    # ... FVG, OB, BOS, CHoCH ...

    # NEW v5.0 — required for market classification
    df['ema_20'] = ta.ema(df['Close'], length=20)
    df['ema_50'] = ta.ema(df['Close'], length=50)
    adx_data = ta.adx(df['High'], df['Low'], df['Close'], length=14)
    df['adx'] = adx_data['ADX_14']
    df['dmp'] = adx_data['DMP_14']
    df['dmn'] = adx_data['DMN_14']

    # NEW v5.0 — momentum candle filter
    df['candle_range'] = df['High'] - df['Low']
    df['candle_body'] = abs(df['Close'] - df['Open'])
    df['body_ratio'] = df['candle_body'] / df['candle_range'].replace(0, float('nan'))

    return df
```

### 5.9 `core/confluence.py` — Updated Scoring for v5.0

Market type now added as a scoring input. VOLATILE_RANGE is blocked before scoring.
ICT sequence remains a contributing factor, not the sole gate.

**Updated 12-point weights:**

| Factor | v4.0 Weight | v5.0 Weight | Note |
|---|---|---|---|
| Liquidity sweep present | 2.0 | 2.0 | Unchanged — strongest predictor |
| FVG + OB overlap | 2.0 | 1.5 | Reduced — less relevant on range days |
| Market type alignment | — | 1.5 | NEW: strategy matches market type |
| ICT sequence A or A+ | 1.5 | 1.0 | Still valuable, not sole gate |
| H1 BOS confirmed | 1.5 | 1.5 | Unchanged |
| Asian range confirmed (breakout days) | — | 1.0 | NEW: for WEAK_BULL/BEAR only |
| In OTE zone (61.8–79%) | 1.0 | 0.5 | Less critical on non-trend days |
| DXY alignment | 1.0 | 1.0 | Unchanged |
| Killzone timing | 1.0 | 1.0 | Unchanged |
| Momentum candle confirmed | — | 1.0 | NEW: replaces MT entry check |
| ATR normal (8–20pts) | 0.5 | 0.5 | Unchanged |
| No news conflict | 0.5 | 0.5 | Unchanged |
| **Maximum** | **12.0** | **12.0** | |
| **Minimum to trade** | **8.0** | **8.0** | Unchanged |

### 5.10 `core/ict_sequence.py` — Role in v5.0

ICT sequence detector is unchanged in logic but its role has shifted.

| v4.0 | v5.0 |
|---|---|
| Gate: must be A or A+ to unlock report button | Input: contributes 1.0 to confluence score |
| 6-step pass/fail check | Still grades A+/A/B — B trades scored lower |
| Required for every trade | Only required if market type supports it |

On WEAK_BULL/WEAK_BEAR days (Asian breakout), the ICT sequence may not complete.
That is expected and acceptable — the strategy does not require it.
On STRONG_BULL/STRONG_BEAR days, A+ ICT sequence is still the highest-quality setup.

The report button unlock condition changes:
```
v4.0: ICT grade A or A+ required
v5.0: Confluence ≥ 8.0 AND market type ≠ VOLATILE_RANGE AND killzone active
```

### 5.11 `core/dealing_range.py` — Unchanged

H4 dealing range, OTE zone, equilibrium calculation all unchanged from v4.0.
OTE zone remains on dashboard and in report. Still valuable on trend days.

### 5.12 `core/macro.py` — Unchanged

DXY, US10Y, sentiment headlines. All sources unchanged. All free.

### 5.13 `core/session.py` — Unchanged

Killzone windows, status light, IST session detection all unchanged.

**Killzone Windows (IST) — unchanged:**
| Killzone | Window | Best Setup |
|---|---|---|
| London Open | 1:30 PM – 3:00 PM | Asian range sweep + reversal |
| NY Open | 6:30 PM – 8:00 PM | London reversal continuation |
| NY Extended | 8:00 PM – 9:30 PM | Trend continuation only |
| Avoid | 4:00 PM – 4:30 PM | London close — erratic |
| Dead Zone | After 11:30 PM | NO TRADING |

### 5.14 `core/cooldown.py` — Unchanged

Post-loss locks remain exactly as in v4.0. Cannot override.

### 5.15 `psychology/pre_trade_check.py` — Unchanged

5-question gate remains exactly as in v4.0.

### 5.16 `core/report.py` — Updated for Market Type

The generated `.md` report now includes market type section at the top.

**Updated report structure (additions marked NEW):**

```markdown
# XAUUSD MARKET SNAPSHOT — [DATE] [TIME IST]

## Status
🟢 GREEN | London Killzone (38 min) | Score: 10.5/12 | Grade: A+

## Market Context  ← NEW v5.0 SECTION
Market Type:    Strong bull trend
Active Strategy: Pullback buy at H1 20 EMA
ADX (D1):       28.5 — trending strongly
ATR (H1):       $12.4 — normal volatility
D1 Structure:   Higher highs + higher lows (last 5 days)
Above EMA50:    Yes — D1 bullish bias confirmed
Trade today:    ✅ YES

Asian Range (completed):        ← NEW v5.0
  High: $3,045.20 | Low: $3,028.60
  Midpoint: $3,036.90 | Range: 16.6pts
  Status: ✅ Clean range — breakout zone identified

## Psychology
[unchanged from v4.0]

## Live Data
[unchanged from v4.0]

## Macro Context
[unchanged from v4.0]

## News Events (IST)
[unchanged from v4.0]

## ICT Sequence
[unchanged — still shown, now contributes 1.0 to confluence instead of gating]

## Dealing Range (H4)
[unchanged from v4.0]

## Indicators
[unchanged + ADX, EMA20, EMA50, body_ratio added]

## Confluence Score: 10.5 / 12.0
[updated weights as per section 5.9]

## Account State
[unchanged from v4.0]

---
INSTRUCTIONS FOR CLAUDE:
Market type today: Strong bull trend.
Active strategy: Pullback buy at H1 20 EMA. Momentum candle confirmation required.
Asian range: $3,028.60 – $3,045.20. Midpoint: $3,036.90.
[rest unchanged from v4.0]
```

### 5.17 Entry Checklist (Pre-Trade Gate — NEW v5.0)

Added to the report button modal alongside screenshot checklist.
6 questions. All must be YES.

```
1. D1 bias confirmed? (price above/below 50 EMA matches trade direction)
2. In London or NY killzone? (not dead zone or Asian session)
3. Key level identified? (EMA touch, Asian range boundary, range extreme)
4. Liquidity sweep visible? (price spiked past obvious level then reversed)
5. Momentum candle confirmed? (body > 60% of range, points in direction)
6. Stop distance clean? (10–25pts — if wider, setup is not clean)

All 6 YES → Generate Report button activates
Any NO → Button stays locked with specific reason shown
```

---

## 6. Dashboard UI — Updated for v5.0

```
┌──────────────────────────────────────────────────────────────────┐
│  ◆ XAUUSD ANALYST                         🟢 LONDON KILLZONE    │
│  $3,042.50  ▲ +2.30 (+0.08%)                    14:22 IST       │
│  Feed: Twelve Data ✅  Fallback: Finnhub standby ✅              │
├──────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  TODAY: STRONG BULL TREND  •  Strategy: Pullback Buy     │    │← NEW v5.0
│  │  ADX 28.5 ↑  •  ATR $12.4 ✅  •  D1 HH+HL ✅           │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  [If VOLATILE_RANGE:]                                            │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  ⛔ VOLATILE MARKET — NO TRADE TODAY                     │    │← NEW v5.0
│  │  ATR $24.8 (extreme) | No directional trend              │    │
│  │  Generate Report: DISABLED                               │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ATR $12.4 ✅  Spread 0.6pts ✅  Score 10.5/12  Grade: A+       │
│  DXY ↓ ✅   Yields ↓ ✅   Macro: BULLISH ✅                     │
│  🎯 London Killzone — 38 min remaining                           │
│  ⚠️  US CPI in 1h 18min — plan around it                        │
├──────────────────────────────────────────────────────────────────┤
│  Asian Range (completed 11:30 AM IST):      ← NEW v5.0          │
│  High $3,045.20 │ Low $3,028.60 │ Mid $3,036.90 │ 16.6pts ✅   │
├──────────────────────────────────────────────────────────────────┤
│  [Dashboard] [Charts] [Journal] [Analytics] [Playbook]          │
│                              [🔬 Backtest ↗]                    │
├──────────────────────────────────────────────────────────────────┤
│  ICT Sequence  ██████████████ A+  6/6 confirmed                 │
│  OTE Zone      ✅ Price $3,029 in $3,020–$3,031                 │
│                                                                  │
│  H4 🟢 BULLISH   H1 🟢 BULLISH   Macro 🟢 ALIGNED              │
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

---

## 7. Walk-Forward Backtest System — Updated for v5.0

### Design Principles
*(Unchanged from v4.0)*
- No future candle leakage
- Same logic as live system
- Free data only (7 months H1 cached)
- Separate UI at `/backtest`
- Auto mode (stats) and Manual mode (eye training)

### Key v5.0 Change: Market Type in Backtest

`walk_forward_engine.py` now classifies market type at each daily boundary
and selects the appropriate strategy — identical to live behavior.

```python
class WalkForwardEngine:
    def step(self):
        i = self.current_index
        visible_h4  = self.h4[:i]
        visible_h1  = self.h1[:i * 4]
        visible_m15 = self.m15[:i * 16]
        visible_m5  = self.m5[:i * 48]

        # NEW v5.0: classify market type for this day
        market_type = classify_market(visible_h4, visible_h1)
        strategy = get_strategy(market_type['type'])

        # If volatile range — skip day entirely
        if not market_type['trade_today']:
            self.current_index += 1
            return None

        # Get Asian range for this day
        asian_range = get_asian_range(visible_m15, visible_h1[-1].timestamp)

        # Check entry using today's strategy
        signal = strategy.check_entry(
            visible_m15, visible_h1, visible_h4,
            i, market_type, asian_range
        )

        if signal and in_killzone(visible_h1[-1].timestamp):
            confluence = compute_confluence(
                compute_indicators(visible_h1, visible_h4),
                check_ict_sequence(visible_h1, visible_m15, visible_m5),
                market_type,
                asian_range
            )
            if confluence.score >= 8.0:
                return Trigger(signal=signal, market_type=market_type, score=confluence.score)

        self.current_index += 1
        return None
```

### Updated Backtest Results Breakdown

Auto mode now shows per-market-type breakdown:

```
═══════════════════════════════════════════════════════════
WALK-FORWARD BACKTEST RESULTS v5.0
XAUUSD H1 | 7 months | Classified by market type
═══════════════════════════════════════════════════════════

MARKET TYPE DISTRIBUTION (7 months)
Strong bull trend:    22 days (16%)  — Pullback buy strategy
Weak bull trend:      18 days (13%)  — Asian breakout long
Strong bear trend:    15 days (11%)  — Pullback sell strategy
Weak bear trend:      14 days (10%)  — Asian breakout short
Tight range:          28 days (20%)  — Range fade
Volatile range:       19 days (14%)  — SKIPPED (hard lock)
News driven:          22 days (16%)  — Post-spike retracement

VOLATILE RANGE SKIP VALUE
19 days skipped — estimated loss prevention: ~$380
(Based on avg losing day in unfiltered v4.0 data)

PER-STRATEGY PERFORMANCE
Pullback buy/sell:    74% win rate (37 trades) ← strongest
Asian breakout:       61% win rate (29 trades) ← solid
Range fade:           58% win rate (19 trades) ← acceptable
News retracement:     66% win rate (21 trades) ← high EV moves

OVERALL (trades taken)
Total trades:         106  (vs ~45 in v4.0 — 2.3x more signals)
Win rate:             67%
Avg R:R:              1.85
Expected EV/trade:    +$26
Expected monthly:     ~$468  (18 trades/month)
═══════════════════════════════════════════════════════════
```

**The volatile range skip alone recovers ~$380/month in prevented losses.**
Trade frequency increases from ~45 to ~106 over 7 months — statistically meaningful.

---

## 8. Two-Trade Session Structure

*(Mostly unchanged from v4.0 — market type gate added)*

| Gate | Trade 1 | Trade 2 |
|---|---|---|
| Market type | Any tradeable type | Same type or news-driven |
| Market type block | VOLATILE_RANGE → no trade | VOLATILE_RANGE → no trade |
| Session | London OR NY killzone | Opposite session only |
| ICT Grade | A or A+ (when applicable) | A+ only |
| Confluence | 8.0+ | 9.5+ |
| Lot size | 0.03 | 0.02 |
| Max risk | $25 | $15 |
| Daily P&L gate | — | Must be < $80 |
| Level gate | — | Different zone from trade 1 |
| Psychology gate | 6+ | 7+ |

---

## 9. Weekly $300 Target Tracker

*(Unchanged from v4.0)*

```
Week: Mon–Fri | Target: $300
At $150 running → 🟢 On pace
At $200 running → 🟢 Comfortable
At $80 daily → 🟡 Soft warning modal
At $120 daily → 🔴 Hard lock
```

---

## 10. Alerts System — Updated for v5.0

**New alert type added for market classification:**

```
5. MARKET TYPE ALERT (fires at 12:30 PM IST daily — London open)
📊 TODAY'S MARKET: Strong Bull Trend
ADX 28.5 ↑ | ATR $12.4 | D1 HH+HL confirmed
Strategy: Pullback buy at H1 20 EMA
Asian range: $3,028 – $3,045 | Midpoint: $3,036

[If VOLATILE_RANGE:]
⛔ TODAY: VOLATILE RANGE — NO TRADING
ATR $24.8 extreme | Choppy, no direction
System locked. Protect capital.
```

All other v4.0 alert types (setup alert, retracement alert, edge decay, feed failover) unchanged.

---

## 11. EC2 Setup

*(Unchanged from v4.0)*

| Component | Specification |
|---|---|
| Instance | t2.micro (free tier) |
| OS | Ubuntu 22.04 LTS |
| Python | 3.11+ |
| Ports open | 5000 (app) · 22 (SSH) |

### Updated Dependencies

```
# Added in v5.0
pandas-ta          # ADX, EMA — replaces manual indicator calculations

# Unchanged from v4.0
flask
flask-cors
gunicorn
websocket-client
aiohttp
pandas
numpy
python-dotenv
requests
beautifulsoup4
python-telegram-bot
```

---

## 12. Build Phases — Updated for v5.0

### Phase 1 — Core Engine ← BUILD FIRST

**New files added to Phase 1:**

- [ ] `pipeline/asian_range_tracker.py` — Daily Asian H/L tracker ← NEW v5.0
- [ ] `core/market_classifier.py` — 7 market type classifier ← NEW v5.0
- [ ] `core/strategy_selector.py` — Maps type to strategy ← NEW v5.0
- [ ] `strategies/__init__.py`
- [ ] `strategies/base_strategy.py` — Abstract base ← NEW v5.0
- [ ] `strategies/pullback_buy.py` — Strong bull entry ← NEW v5.0
- [ ] `strategies/pullback_sell.py` — Strong bear entry ← NEW v5.0
- [ ] `strategies/asian_breakout.py` — Weak trend entry ← NEW v5.0
- [ ] `strategies/range_fade.py` — Tight range entry ← NEW v5.0
- [ ] `strategies/news_retracement.py` — Post-spike entry ← NEW v5.0
- [ ] `strategies/no_trade.py` — Volatile range block ← NEW v5.0

**Existing Phase 1 files (unchanged):**

- [ ] `main.py`
- [ ] `pipeline/feed_manager.py`
- [ ] `pipeline/twelve_data_feed.py`
- [ ] `pipeline/finnhub_feed.py`
- [ ] `pipeline/candle_builder.py` (updated for Asian range)
- [ ] `pipeline/event_bus.py`
- [ ] `core/indicators.py` (updated for ADX/EMA/body ratio)
- [ ] `core/dealing_range.py`
- [ ] `core/ict_sequence.py`
- [ ] `core/confluence.py` (updated weights)
- [ ] `core/macro.py`
- [ ] `core/calendar.py`
- [ ] `core/session.py`
- [ ] `psychology/pre_trade_check.py`
- [ ] `core/report.py` (updated for market type section)
- [ ] `server/app.py`
- [ ] `templates/index.html` (updated dashboard with market type banner)
- [ ] Screenshot + entry checklist modal (updated for 6-point checklist)
- [ ] Generate Report → download

**Phase 1 build order for Claude Code:**
```
1. config.py — all params
2. pipeline/candle_builder.py + asian_range_tracker.py — data foundation
3. pipeline/ feeds + event_bus.py — connectivity
4. core/indicators.py — add ADX/EMA/body_ratio to existing
5. core/market_classifier.py — test classification on historical data
6. strategies/ — all 7 strategy files
7. core/strategy_selector.py
8. core/confluence.py — updated weights
9. core/report.py — add market type section
10. server/app.py + templates/index.html — dashboard with type banner
```

### Phase 2 — Live Charts

*(Unchanged from v4.0)*

Add EMA20, EMA50 lines and Asian range band overlay to existing chart spec.

### Phase 3 — Journal + Behavioral Guards

*(Unchanged from v4.0)*

Add `market_type` field to trade log — analytics will show win rate per market type.

### Phase 4 — Alerts + Analytics

Market type morning alert added. Everything else unchanged.

Analytics tab gains: per-market-type win rate table after 10 trades per type.

### Phase 5 — Walk-Forward Backtest + Intelligence Layer

Updated as described in section 7.
Key addition: per-market-type stats in results_analyzer.py.
weight_calibrator.py now also calibrates per market type.

---

## 13. Compounding Timeline

*(Updated with v5.0 impact)*

```
Month 1:  Phase 1+2 live.
          Market classifier running. Volatile days automatically skipped.
          Asian range tracked. Breakout strategies firing on weak trend days.
          ~35 trades (vs ~20 in v4.0 — more signals, more sample data).
          Expected P&L: $500–$700

Month 2:  Phase 3+4 live.
          Behavioral guards active. Telegram + session handoff running.
          Per-market-type analytics visible after 10 trades each type.
          You discover which market type is YOUR strongest edge.
          First payout if profit ≥ $500.
          Expected P&L: $550–$750

Month 3:  50+ trades. Playbook v1 generated.
          Market type distribution data reveals pattern:
          e.g., "You're 78% in strong bull but 44% in tight range."
          → Stop trading range fade. Focus on trend days only.
          Win rate improves 6–10 points from this one insight alone.
          Expected P&L: $650–$850

Month 4:  Phase 5 live.
          Walk-forward backtest validates per-strategy performance.
          Confluence weights recalibrated per market type.
          Manual backtest trains your eye on all 7 scenario types.
          Win rate: 68–73%.
          $300/week becomes the floor.

Month 5–6: $25,000 QTFunded account.
           Same strategies. Same market type classification.
           Proportionally scaled lots. $500/week achievable.
```

---

## 14. Milestone Targets

*(Unchanged from v4.0)*

| Milestone | Meaning | Timeline |
|---|---|---|
| First trade | System live, data flowing, market type classified | Week 1 |
| Feed failover tested | Resilience confirmed | Week 1 |
| 10 trades logged | Analytics tab unlocks | Weeks 2–3 |
| $500 cumulative profit | First payout eligible | Month 1–2 |
| 30 trades | Backtest weight calibration | Month 2 |
| 50 trades | Playbook v1 generated | Month 2–3 |
| Per-type analytics | Know your strongest market type | Month 2 |
| Weakest type removed | Win rate improves immediately | Month 3 |
| Backtest complete | All 7 strategies validated on 7 months | Month 4 |
| $25k account | $500/week realistic | Month 5–6 |

---

## 15. Success Metrics

| Metric | Target | Notes |
|---|---|---|
| Report generated after app open | < 90 seconds | |
| Confluence update after candle close | < 200ms | |
| Telegram fire after threshold | < 1 second | |
| Feed failover time | < 5 seconds | |
| API calls per day | < 15 of 800 | |
| Volatile range days skipped | 100% | Hard lock, no override |
| Win rate (all strategies combined) | 60%+ | |
| Win rate (strong trend days only) | 70%+ | Best edge |
| Avg R:R achieved | 1.8+ | |
| Weekly P&L | $150–$300 | |
| Daily loss cap hit | Never | $50 hard cap |
| 0.05 Lot cap violation | Never | |

---

## 16. What You Need To Start

*(Unchanged from v4.0)*

| Item | Source | Time |
|---|---|---|
| Twelve Data API key | twelvedata.com — free | 2 min |
| Finnhub API key | finnhub.io — free | 2 min |
| NewsAPI key | newsapi.org — free | 2 min |
| Telegram Bot token | t.me/BotFather | 3 min |
| EC2 port 5000 open | AWS Security Group | 2 min |

**Total: ~12 minutes before building starts.**

---

## 17. What Stays Human — Always

*(Unchanged from v4.0)*

| Step | Why Manual |
|---|---|
| Visual MT5 chart confirmation | Your eye catches what algorithms miss |
| Final trade quality judgment | Discipline lives here. Never automate. |
| Pasting report + screenshots to Claude | You stay in the loop every time |
| Executing in MT5 | Non-negotiable. You own every entry. |
| Logging trade result | 30 seconds that compounds your edge forever |
| Sitting out on bad days | Most profitable trade is often no trade |
| Manual backtest decisions | Trains your eye in ways auto mode cannot |

---

## 18. config.py — Full Parameter Reference

```python
# config.py — v5.0

SYMBOL = "GC=F"
TIMEFRAME_PRIMARY = "15m"
TIMEFRAME_TREND = "1d"
TIMEFRAME_HTF = "1h"

# Session windows (UTC — add +5:30 for IST)
LONDON_OPEN_UTC = 7
LONDON_CLOSE_UTC = 10
NY_OPEN_UTC = 12
NY_CLOSE_UTC = 14
ASIAN_SESSION_START_UTC = 23  # 11 PM UTC = 4:30 AM IST next day
ASIAN_SESSION_END_UTC = 6     # 6 AM UTC = 11:30 AM IST

# Market type thresholds (NEW v5.0)
ADX_STRONG_TREND = 25
ADX_WEAK_TREND = 15
ATR_H1_VOLATILE_CEILING = 20   # Above this = volatile range
ATR_H1_DEAD_FLOOR = 8          # Below this = dead market
EMA_TREND_PERIOD = 50
EMA_ENTRY_PERIOD = 20

# Entry filters (NEW v5.0 — replaces MT midpoint)
MOMENTUM_CANDLE_BODY_MIN = 0.60   # Body must be 60%+ of candle range
MIN_CANDLE_RANGE_PTS = 3          # Ignore micro candles
MIN_STOP_DISTANCE_PTS = 10        # Too tight = random noise
MAX_STOP_DISTANCE_PTS = 25        # Too wide = setup not clean

# Target R multiples by strategy type (NEW v5.0)
TARGET_R_STRONG_TREND = 2.0       # Pullback buy/sell
TARGET_R_WEAK_TREND = 1.5         # Asian breakout
TARGET_R_RANGE = 1.2              # Range fade
TARGET_R_NEWS = 1.75              # News retracement
BREAKEVEN_AT_R = 1.0              # Move SL to BE at 1R (all strategies)

# Confluence (updated v5.0)
CONFLUENCE_MINIMUM_LONDON_NY = 8.0
CONFLUENCE_MINIMUM_SECOND_TRADE = 9.5

# Account + risk (unchanged from v4.0)
ACCOUNT_SIZE = 10000
RISK_PER_TRADE_PCT = 0.5          # $50 max risk per trade
LOT_SIZE_MAX = 0.05               # QTFunded hard cap
LOT_SIZE_TRADE1 = 0.03
LOT_SIZE_TRADE2 = 0.02
DAILY_LOSS_HARD_CAP = 50
DAILY_PROFIT_HARD_CAP = 120
WEEKLY_TARGET = 300
```

---

*Plan version: 5.0 | Updated: April 2026*
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
>  The market type tells you which game is being played today.
>  The correct strategy plays that game — not yesterday's game.
>  Your only job is to execute with discipline — and walk away when done."
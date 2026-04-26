"""
XAUUSD Analyst v5.0 — Market Regime Classification Engine
All constants, API keys, session windows, and thresholds.
"""

import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

# ─── API Keys ───────────────────────────────────────────────
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
OANDA_API_TOKEN  = os.getenv("OANDA_API_TOKEN", "")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID", "")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

# ─── SSL Settings ───────────────────────────────────────────
SSL_NO_VERIFY = os.getenv("SSL_NO_VERIFY", "false").lower() == "true"

# ─── Server ─────────────────────────────────────────────────
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 5000))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# ─── Instrument ─────────────────────────────────────────────
SYMBOL = "XAUUSD"
TWELVE_DATA_SYMBOL = "XAU/USD"
FINNHUB_SYMBOL = "OANDA:XAU_USD"

# ─── Account Settings ───────────────────────────────────────
ACCOUNT_SIZE = 10_000          # QTFunded $10k Instant
MAX_LOT_TRADE1 = 0.08
MAX_LOT_TRADE2 = 0.02
MAX_RISK_TRADE1 = 25           # USD
MAX_RISK_TRADE2 = 15           # USD
MAX_TRADES_PER_DAY = 6
WEEKLY_TARGET = 300            # USD
DAILY_SOFT_CAP = 300            # USD profit — warning
DAILY_HARD_CAP = 1000           # USD profit — lock
DAILY_LOSS_WARNING = 150        # USD — confirmation modal
DAILY_LOSS_HARD_CAP = 500       # USD — full lock

# ─── Killzone Windows (IST = UTC+5:30) ──────────────────────
# Format: (hour, minute) tuples for start/end
KILLZONES = {
    "asian_open":     {"start": ( 5, 30), "end": (13, 30), "label": "Asian Session"},
    "london_open":    {"start": (13, 30), "end": (15,  0), "label": "London Open"},
    "london_close":   {"start": (15,  0), "end": (16, 30), "label": "London Session"},
    "avoid_zone":     {"start": (16,  0), "end": (16, 30), "label": "London Close — Avoid"},
    "ny_open":        {"start": (18, 30), "end": (20,  0), "label": "NY Open"},
    "ny_extended":    {"start": (20,  0), "end": (21, 30), "label": "NY Extended"},
    "dead_zone":      {"start": (23, 30), "end": ( 5, 30), "label": "Dead Zone — NO TRADE"},
}

LONDON_HANDOFF_TIME = (16, 30)  # IST — auto-generates session summary

IST = timezone(timedelta(hours=5, minutes=30))

def get_ist_now():
    """Get current time in IST (UTC+5:30)."""
    return datetime.now(IST)

# ─── Dual-Mode Strategy Settings ──────────────────────────────

# Mode 1: SWING MODE (5 factors, Max: 6.5 pts)
# Volatility Regime Filters (Applied in simulation_core.py)
ATR_NORMAL_MAX = 35.0  # Raised from 25 to capture normal weeks while filtering extreme 40+ outliers
ATR_SWING_MIN  = 12.0  # Regime gate — below 12pt H1 ATR, Gold sweeps are range noise not ICT structure
SCALP_ATR_GATE = 22.0  # Raised from 15 to allow scalps in normal 16-21 ATR regimes

SWING_WEIGHTS = {
    "liquidity_sweep":     2.0,  # Must have
    "h1_bos":              1.5,  # Must have
    "fvg_ob_overlap":      1.5,  # Must have
    "killzone_timing":     1.0,  # Important
    "dxy_alignment":       1.0,  # HARD GATE (Raised from 0.5)
}
SWING_SCORE_MAX = sum(SWING_WEIGHTS.values())
SWING_SCORE_MIN_LIVE = 3.8
SWING_SCORE_MIN_BACKTEST = 3.8

SWING_RISK = {
    "lots": 0.08,            # 0.08 × 10pt SL × 100 = $80 actual risk; gets 5m to ~$316/week
    "tp_rr": 3.0,            # 1:3.0 runner TP — with 50% partial at 1R, effective average RR = 2.0
    "sl_atr_multiplier": 0.6,
    "sl_atr_max": 1.5,
    "min_sl_distance": 8.0,
}

# Mode 2: SCALP MODE (Binary Gates)
SCALP_RISK = {
    "lots": 0.08,                  # Matched to swing — fixed 8pt SL with 0.08 lots = $64 actual risk
    "sl_distance": 8.0,            # Fixed gap for calm market scalps
    "tp_rr": 2.0,                  # 1:2.0 target — after 50% partial at 1R, runner to 2R
    "score_min": 3.0,              # Requires all 3 gates to pass (Gate1 + Gate2 + Gate3 = 3.0)
    "min_confluence": 2.0,         # Min swing score for HTF context check
    "displacement_lookback": 20,   # M5 bars — fresh FVG must form within last 20 bars (~100 min)
    "fvg_min_size": 1.0,           # Minimum FVG size in points (filters micro gaps)
}

# Cooldowns between same-type trades
# ─── Trend Filter ───────────────────────────────────────────
# 5m : set False — ICT 5m entries are inherently counter-momentum (sweep then reverse)
# 15m: set True  — 15m structure aligns with prevailing trend; filter cuts 42% loss rate
TREND_FILTER_ENABLED = False

SWING_COOLDOWN_SECONDS = 1 * 3600
SCALP_COOLDOWN_SECONDS = 15 * 60

# ─── Strategy v6 — Data-Driven A+ filters ───────────────────
# Empirically derived from the 6-month backtest (see backtest/analyze_winners.py);
# each flag drops a segment with verified negative expectancy.
STRATEGY_V6_ENABLED = True

V6_SKIP_H1_PRIMARY    = True
V6_SKIP_LONDON_OPEN   = True
V6_SKIP_ASIAN_SCALP   = True
V6_SWING_SCORE_MIN    = 5.5
V6_SKIP_ATR_BANDS     = [(0.0, 16.0), (20.0, 25.0)]
V6_SKIP_ADX_BAND      = (25.0, 30.0)
V6_SKIP_DR_ALIGNED    = True

# Power sizing — scale up inside the Score × ATR × DR-equilibrium slice.
V6_POWER_LOTS         = 0.04
V6_POWER_MIN_SCORE    = 5.5
V6_POWER_MIN_ATR      = 25.0
V6_POWER_DR_ZONES     = {"equilibrium"}

# Momentum Expansion — retained, but only on M15 primary.
V6_MOMENTUM_ENABLED   = True
V6_MOMENTUM_MIN_ATR   = 25.0
V6_MOMENTUM_MIN_ADX   = 30.0
SIGNAL_COOLDOWN_BARS = 0
SIGNAL_REDUNDANCY_CHECK = True

# ─── Session Expansion Strategy (PRIMARY) ───────────────────
# This is the strategy that actually drives trades.
# ICT confluence above is kept for dashboard display only.
SESSION_EXPANSION = {
    "lots": 0.05,

    # Asian range (5:30 IST → 13:30 IST)
    "asian_start_hour": 5,
    "asian_start_min": 30,
    "asian_end_hour": 13,
    "asian_end_min": 30,

    # London breakout window (13:30 → 15:30 IST)
    "london_window_start_min": 13 * 60 + 30,
    "london_window_end_min":   15 * 60 + 30,

    # NY pullback window (18:30 → 20:30 IST)
    "ny_window_start_min": 18 * 60 + 30,
    "ny_window_end_min":   20 * 60 + 30,

    # Range quality filter — RELATIVE to H1 ATR so it adapts to regime
    "asian_range_min_atr": 0.5,   # range must be >= 0.5 × ATR (real liquidity)
    "asian_range_max_atr": 6.0,   # range must be <= 6.0 × ATR (allow trending days)

    # Volatility filter — absolute (guards against dead/extreme markets)
    "atr_min": 5.0,
    "atr_max": 120.0,

    # H1 bias filter (distance from EMA50 to confirm direction)
    "bias_min_distance": 3.0,   # pts — within this = no clear bias, skip day

    # Risk — 0.75% of $10k account. At stop-after-2-losses + 0.07 lots, max daily exposure = $168.
    # Daily cap is $500 — 3× buffer. Well within funded account rules.
    "risk_per_trade": 75.0,
    "sl_atr_mult": 0.7,
    "sl_min": 8.0,
    "sl_max": 25.0,
    "tp1_rr": 1.0,              # Half exit (BE runner after this)
    "tp2_rr": 2.0,              # Runner target
    "tp1_close_pct": 0.5,

    # Daily guardrails
    "max_trades_per_day": 2,    # 1 London + 1 NY max
    "stop_after_loss": True,    # After any loss, day is over
    "stop_after_profit_target": 1000.0,
}

# Grade filtering (Legacy, mostly for logging now)
ALLOWED_GRADES = ["A+", "A", "B"]

# ─── Indicator Settings ─────────────────────────────────────
ATR_PERIOD = 14
SWING_LOOKBACK = 5             # 5-bar pivot detection
FVG_PROXIMITY_PTS = 5.0        # pts — price within this distance counts as "approaching" FVG
CANDLE_HISTORY_SIZE = 5000      # candles per timeframe in memory (Twelve Data Free Tier max)
CANDLE_PERSIST_INTERVAL = 120  # seconds (2 min)

# ─── Timeframes ─────────────────────────────────────────────
TIMEFRAMES = {
    "M5":  {"seconds": 300,   "label": "5 Min"},
    "M15": {"seconds": 900,   "label": "15 Min"},
    "H1":  {"seconds": 3600,  "label": "1 Hour"},
    "H4":  {"seconds": 14400, "label": "4 Hour"},
}

# ─── Feed Health ─────────────────────────────────────────────
FEED_TIMEOUT_SECONDS = 30      # no tick = failover trigger
FEED_RECONNECT_BASE = 2        # exponential backoff base (seconds)
FEED_RECONNECT_MAX = 60        # max backoff

# ─── Cooldown ────────────────────────────────────────────────
COOLDOWN_1_LOSS_MINUTES = 30
COOLDOWN_2_LOSS_MINUTES = 60

# ─── Psychology Gate ─────────────────────────────────────────
PSYCH_MIN_FEELING = 4          # below = hard block
PSYCH_REDUCED_LOT_FEELING = 6  # feeling 4-6 + last loss = reduced lot

# ─── Trade 2 Gates ──────────────────────────────────────────
TRADE2_MIN_GRADE = "A+"
TRADE2_MIN_CONFLUENCE = 9.5
TRADE2_MAX_DAILY_PNL = 80
TRADE2_MIN_PSYCH = 7

# ─── News Safety ─────────────────────────────────────────────
NEWS_BLOCK_MINUTES = 8         # no trading within 8 min of high-impact news

# ─── Market Regime Thresholds (v5.0) ─────────────────────────
ADX_STRONG_TREND = 25
ADX_WEAK_TREND = 15
ATR_H1_VOLATILE_CEILING = 35.0 # Raised from 20.0 to match Alpha profile
ATR_H1_DEAD_FLOOR = 6.0        # Relaxed from 8.0
EMA_TREND_PERIOD = 50          # D1/H1 Trend Filter
EMA_ENTRY_PERIOD = 20          # Pullback Anchor

# ─── Momentum Entry Filters (v5.0) ──────────────────────────
MOMENTUM_CANDLE_BODY_MIN = 0.20 # Relaxed from 0.60 for 5m TF
MIN_CANDLE_RANGE_PTS = 3.0      # Ignore micro candles
MIN_STOP_DISTANCE_PTS = 10.0    # Too tight = random noise
MAX_STOP_DISTANCE_PTS = 25.0    # Too wide = setup not clean

# ─── Strategy Settings by Market Type (v5.0) ────────────────
STRATEGY_CONFIGS = {
    'STRONG_BULL':    {'target_rr': 2.5, 'be_at_rr': 1.0, 'lots': 0.05},
    'STRONG_BEAR':    {'target_rr': 2.5, 'be_at_rr': 1.0, 'lots': 0.05},
    'WEAK_BULL':      {'target_rr': 2.0, 'be_at_rr': 1.0, 'lots': 0.05},
    'WEAK_BEAR':      {'target_rr': 2.0, 'be_at_rr': 1.0, 'lots': 0.05},
    'TIGHT_RANGE':    {'target_rr': 2.0, 'be_at_rr': 1.0, 'lots': 0.03},
    'NEWS_DRIVEN':    {'target_rr': 2.5, 'be_at_rr': 1.0, 'lots': 0.05},
    'VOLATILE_RANGE': {'target_rr': 2.5, 'be_at_rr': 1.0, 'lots': 0.05}, # Enabled for Trending Volatility
}

# ─── Paths ───────────────────────────────────────────────────
import pathlib
BASE_DIR = pathlib.Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CANDLE_CACHE_DIR = DATA_DIR / "candles"
JOURNAL_FILE = DATA_DIR / "trades.json"
PSYCH_STATE_FILE = BASE_DIR / "psychology" / "state_history.json"
BACKTEST_DATA_DIR = BASE_DIR / "backtest" / "data"
BACKTEST_RESULTS_DIR = BASE_DIR / "backtest" / "results"

# Ensure directories exist
for d in [DATA_DIR, CANDLE_CACHE_DIR, BACKTEST_DATA_DIR, BACKTEST_RESULTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

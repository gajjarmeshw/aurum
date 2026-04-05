"""
XAUUSD Analyst v4 — Central Configuration
All constants, API keys, session windows, and thresholds.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── API Keys ───────────────────────────────────────────────
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

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
MAX_LOT_TRADE1 = 0.03
MAX_LOT_TRADE2 = 0.02
MAX_RISK_TRADE1 = 25           # USD
MAX_RISK_TRADE2 = 15           # USD
MAX_TRADES_PER_DAY = 2
WEEKLY_TARGET = 300            # USD
DAILY_SOFT_CAP = 80            # USD profit — warning
DAILY_HARD_CAP = 120           # USD profit — lock
DAILY_LOSS_WARNING = 35        # USD — confirmation modal
DAILY_LOSS_HARD_CAP = 50       # USD — full lock

# ─── Killzone Windows (IST = UTC+5:30) ──────────────────────
# Format: (hour, minute) tuples for start/end
KILLZONES = {
    "london_open":   {"start": (13, 30), "end": (15,  0), "label": "London Open"},
    "london_close":  {"start": (15,  0), "end": (16, 30), "label": "London Session"},
    "avoid_zone":    {"start": (16,  0), "end": (16, 30), "label": "London Close — Avoid"},
    "ny_open":       {"start": (18, 30), "end": (20,  0), "label": "NY Open"},
    "ny_extended":   {"start": (20,  0), "end": (21, 30), "label": "NY Extended"},
    "dead_zone":     {"start": (23, 30), "end": ( 5, 30), "label": "Dead Zone — NO TRADE"},
}

LONDON_HANDOFF_TIME = (16, 30)  # IST — auto-generates session summary

# ─── Confluence Weights (Phase 1 — Theory) ──────────────────
CONFLUENCE_WEIGHTS = {
    "liquidity_sweep":     2.0,
    "fvg_ob_overlap":      2.0,
    "ict_sequence":        1.5,
    "h1_bos":              1.5,
    "ote_zone":            1.0,
    "dxy_alignment":       1.0,
    "killzone_timing":     1.0,
    "premium_discount":    0.5,
    "atr_normal":          0.5,
    "no_news_conflict":    0.5,
}
CONFLUENCE_MAX = 12.0
CONFLUENCE_MIN_LONDON_NY = 8.0
CONFLUENCE_MIN_ASIAN = 11.0

# ─── ICT Grading ────────────────────────────────────────────
ICT_GRADE_THRESHOLDS = {
    "A+": 6,   # 6/6 steps
    "A":  4,   # 4-5/6
    "B":  3,   # 3/6
}
TRADEABLE_GRADES = ["A+", "A"]

# ─── Indicator Settings ─────────────────────────────────────
ATR_PERIOD = 14
SWING_LOOKBACK = 5             # 5-bar pivot detection
ATR_NORMAL_MIN = 8.0           # USD
ATR_NORMAL_MAX = 20.0          # USD
CANDLE_HISTORY_SIZE = 200      # candles per timeframe in memory
CANDLE_PERSIST_INTERVAL = 900  # seconds (15 min)

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

"""
Walk-Forward Engine — Bar-by-bar backtest replay.

Simulates the real-time pipeline using historical data.
Ensures zero look-ahead bias by recomputing indicators on each bar.

Data parity with live:
  - Loads actual M5, M15, H1, H4 CSV files (same source as OANDA REST)
  - No resampling — broker candles are used directly, matching live feed
  - Macro data mocked as neutral (dxy_aligned=True) since historical DXY
    data is unavailable; live system uses real DXY — this is the one
    remaining difference, and it makes backtest slightly conservative
"""

import bisect
import logging
import warnings
import numpy as np
import pandas as pd

warnings.simplefilter(action='ignore', category=FutureWarning)

from core.indicators import compute_indicators
from core.ict_sequence import check_ict_sequence
from core.confluence import compute_confluence
from core.dealing_range import compute_dealing_range
from core.session import get_session_info_from_timestamp
import config

logger = logging.getLogger(__name__)

# Bars of history to pass per TF to compute_indicators (matches live OANDA seed)
_HIST = {"M5": 500, "M15": 300, "H1": 200, "H4": 100}

# Macro mock — neutral/bullish consistent value so DXY factor behaves the same
# as the current live environment (DXY falling → gold tailwind)
_MACRO_MOCK = {
    "dxy_aligned":  True,
    "macro_bias":   "bullish",
    "dxy_detail":   "Backtest mock — DXY falling assumed",
}


def _load_tf(path: str) -> tuple[pd.DataFrame, np.ndarray]:
    """Load a CSV and return (df, sorted unix timestamp array) for fast bisect lookup."""
    df = pd.read_csv(path)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df[df["datetime"].dt.dayofweek < 5]   # drop weekends
    df = df.sort_values("datetime").reset_index(drop=True)
    df["timestamp"] = df["datetime"].apply(lambda x: x.timestamp())
    ts_arr = df["timestamp"].to_numpy()
    return df, ts_arr


def _slice_up_to(df: pd.DataFrame, ts_arr: np.ndarray, cutoff_ts: float, n: int) -> list[dict]:
    """Return the last n rows of df whose timestamp <= cutoff_ts."""
    idx = bisect.bisect_right(ts_arr, cutoff_ts)   # first index > cutoff
    start = max(0, idx - n)
    return df.iloc[start:idx].to_dict("records")


# Map user-facing timeframe strings → CSV filenames and canonical TF key
_TF_CSV = {
    "5min":  ("XAUUSD_5min.csv",  "M5"),
    "15min": ("XAUUSD_15min.csv", "M15"),
    "1h":    ("XAUUSD_1h.csv",    "H1"),
}
# All sibling TFs needed for indicator computation
_ALL_TF_CSVS = {
    "M5":  "XAUUSD_5min.csv",
    "M15": "XAUUSD_15min.csv",
    "H1":  "XAUUSD_1h.csv",
    "H4":  "XAUUSD_4h.csv",
}


class BacktestEngine:
    def __init__(self, data_path: str, timeframe: str = "15min",
                 start_date: str = None, end_date: str = None,
                 primary_tf: str = None):
        """
        data_path   : path to the primary TF CSV
        timeframe   : "5min" | "15min" | "1h"  (also accepts "15min" as default)
        primary_tf  : override key e.g. "M15", "H1", "M5" — inferred from timeframe if None
        """
        import pathlib
        self.data_path = data_path
        self.timeframe = timeframe
        data_dir = pathlib.Path(data_path).parent

        # Determine which TF key is primary
        _, inferred_key = _TF_CSV.get(timeframe, ("", "M15"))
        self._primary_tf = primary_tf or inferred_key

        # ── Load primary TF ───────────────────────────────────────────────────
        self.full_df, self._primary_ts = _load_tf(data_path)
        logger.info(f"Loaded {len(self.full_df)} {self._primary_tf} bars (primary)")

        # ── Load all sibling TFs (skip primary to avoid double-load) ─────────
        self._tf_data: dict[str, tuple[pd.DataFrame, np.ndarray]] = {}
        for tf_key, fname in _ALL_TF_CSVS.items():
            if tf_key == self._primary_tf:
                continue                          # primary is handled separately
            path = data_dir / fname
            if path.exists():
                df, ts = _load_tf(str(path))
                self._tf_data[tf_key] = (df, ts)
                logger.info(f"Loaded {len(df)} {tf_key} bars from {fname}")
            else:
                logger.warning(f"{tf_key} CSV not found at {path}")

        # ── Date range filtering ──────────────────────────────────────────────
        min_dt = self.full_df["datetime"].min()
        max_dt = self.full_df["datetime"].max()

        if start_date:
            start_dt = max(pd.to_datetime(start_date), min_dt)
            mask = self.full_df["datetime"] >= start_dt
            self._current_idx = int(mask.idxmax()) if mask.any() else len(self.full_df)
        else:
            self._current_idx = min(100, len(self.full_df) - 1)

        if end_date:
            end_dt = min(pd.to_datetime(end_date) + pd.Timedelta(days=1),
                         max_dt + pd.Timedelta(days=1))
            mask = self.full_df["datetime"] >= end_dt
            self._end_idx = int(mask.idxmax()) if mask.any() else len(self.full_df)
        else:
            self._end_idx = len(self.full_df)

        if self._current_idx >= self._end_idx:
            self._current_idx = max(0, self._end_idx - 100)

        self._start_idx = self._current_idx
        self.results = []
        self.total_bars = self._end_idx - self._start_idx
        logger.info(f"Backtest range: {self._current_idx} → {self._end_idx} "
                    f"({self.total_bars} bars)")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_tf_bars(self, tf: str, cutoff_ts: float) -> list[dict]:
        """Return last N bars for a TF at or before cutoff_ts."""
        # Primary TF
        if tf == self._primary_tf:
            return _slice_up_to(self.full_df, self._primary_ts, cutoff_ts, _HIST[tf])
        # Sibling TFs loaded from CSV
        if tf in self._tf_data:
            df, ts_arr = self._tf_data[tf]
            return _slice_up_to(df, ts_arr, cutoff_ts, _HIST[tf])
        # Fallback: resample from primary (only used when a sibling CSV is missing)
        idx = bisect.bisect_right(self._primary_ts, cutoff_ts)
        start = max(0, idx - 1000)
        hist = self.full_df.iloc[start:idx].copy().set_index("datetime")
        rule = {"M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h"}.get(tf, "15min")
        resampled = hist.resample(rule).agg(
            {"open": "first", "high": "max", "low": "min",
             "close": "last", "timestamp": "last"}
        ).dropna().reset_index()
        return resampled.tail(_HIST.get(tf, 200)).to_dict("records")

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> list[dict]:
        """Bar-by-bar walk-forward scan. Returns list of setup dicts."""
        if self._current_idx >= self._end_idx:
            logger.warning("No data for selected range.")
            return []

        logger.info(f"Starting walk-forward backtest… (primary TF: {self._primary_tf})")
        last_primary_ts = None
        total_scanned = skipped_thresh = skipped_dup = 0

        for i in range(self._current_idx, self._end_idx):
            row = self.full_df.iloc[i]
            cutoff_ts = float(row["timestamp"])

            # ── Slice all 4 TFs up to this bar's close time ───────────────
            m5_bars  = self._get_tf_bars("M5",  cutoff_ts)
            m15_bars = self._get_tf_bars("M15", cutoff_ts)
            h1_bars  = self._get_tf_bars("H1",  cutoff_ts)
            h4_bars  = self._get_tf_bars("H4",  cutoff_ts)

            if not (h4_bars and h1_bars and m15_bars and m5_bars):
                continue

            # Current bar = the primary TF bar that just closed
            primary_map = {"M5": m5_bars, "M15": m15_bars, "H1": h1_bars, "H4": h4_bars}
            current_bar   = primary_map[self._primary_tf][-1]
            current_price = float(current_bar["close"])

            # ── Compute indicators — same call as live feed_manager ────────
            indicators = compute_indicators(h4_bars, h1_bars, m15_bars, m5_bars)
            indicators.m15_candles = m15_bars
            indicators.m5_candles  = m5_bars

            dr      = compute_dealing_range(indicators.swing_highs_h4, indicators.swing_lows_h4)
            session = get_session_info_from_timestamp(current_bar["datetime"])
            ict     = check_ict_sequence(indicators, session.to_dict(),
                                         current_price, dr.to_dict())
            score   = compute_confluence(indicators, ict.to_dict(), dr.to_dict(),
                                         session.to_dict(), _MACRO_MOCK, current_price)

            total_scanned += 1

            # ── Gate: score threshold ─────────────────────────────────────
            swing_score = score.get("swing", {}).get("score", 0)
            swing_valid = swing_score >= config.SWING_SCORE_MIN_BACKTEST
            scalp_valid = score.get("scalp", {}).get("is_valid", False)

            # ── Momentum Expansion (v6) — new entry type ──────────────────
            # Clean H1 BOS + M15 FVG in a high-ATR/ADX regime, no sweep req'd.
            # Direction comes from the most recent H1 BOS so the setup has
            # a real structural basis (not arbitrary bias).
            momentum_valid = False
            momentum_direction = "neutral"
            if getattr(config, "V6_MOMENTUM_ENABLED", False):
                atr_h1 = indicators.atr_h1 or 0.0
                adx_val = float(indicators.adx or 0.0)
                has_h1_bos = bool(indicators.bos_h1)
                has_m15_fvg = any(not f.filled for f in indicators.fvgs_m15)
                if (has_h1_bos and has_m15_fvg
                        and atr_h1 >= config.V6_MOMENTUM_MIN_ATR
                        and adx_val >= config.V6_MOMENTUM_MIN_ADX):
                    momentum_direction = indicators.bos_h1[-1].direction
                    momentum_valid = True

            if not swing_valid and not scalp_valid and not momentum_valid:
                skipped_thresh += 1
                continue

            # ── Gate: deduplicate on primary candle boundary ──────────────
            p_dt = current_bar.get("datetime")
            if p_dt == last_primary_ts:
                skipped_dup += 1
                continue
            last_primary_ts = p_dt

            # Momentum direction overrides only when swing/scalp don't already
            # supply one — otherwise we could accidentally flip a valid trade.
            effective_direction = ict.direction
            if momentum_valid and not swing_valid and not scalp_valid:
                effective_direction = momentum_direction

            self.results.append({
                "timestamp":   int(cutoff_ts),
                "price":       current_price,
                "swing_score": swing_score,
                "is_swing":    swing_valid,
                "is_scalp":    scalp_valid,
                "is_momentum": momentum_valid,
                "direction":   effective_direction,
                "atr":         round(indicators.atr_h1, 2),
                "adx":         round(float(indicators.adx or 0), 2),
                "action":      ict.setup_status,
                "high":        float(current_bar["high"]),
                "low":         float(current_bar["low"]),
                "bar_index":   i,
                "primary_tf":  self._primary_tf,
                "session":     session.to_dict(),
                "levels":      indicators.to_dict(),
                "raw_score":   score,
            })

        logger.info(
            f"Scan complete: {total_scanned} scanned, "
            f"{skipped_thresh} below threshold, "
            f"{skipped_dup} duplicates, "
            f"{len(self.results)} setups"
        )
        return self.results

    def step(self):
        """Single-step for manual / GUI mode."""
        if self._current_idx >= self._end_idx:
            return None

        row = self.full_df.iloc[self._current_idx]
        cutoff_ts = float(row["timestamp"])

        m15_bars = self._get_tf_bars("M15", cutoff_ts)
        m5_bars  = self._get_tf_bars("M5", cutoff_ts)
        h1_bars  = self._get_tf_bars("H1", cutoff_ts)
        h4_bars  = self._get_tf_bars("H4", cutoff_ts)

        if not (h4_bars and h1_bars and m15_bars and m5_bars):
            self._current_idx += 1
            return None

        current_bar   = m15_bars[-1]
        current_price = float(current_bar["close"])

        indicators = compute_indicators(h4_bars, h1_bars, m15_bars, m5_bars)
        indicators.m15_candles = m15_bars
        indicators.m5_candles  = m5_bars

        dr      = compute_dealing_range(indicators.swing_highs_h4, indicators.swing_lows_h4)
        session = get_session_info_from_timestamp(current_bar["datetime"])
        ict     = check_ict_sequence(indicators, session.to_dict(),
                                     current_price, dr.to_dict())
        score   = compute_confluence(indicators, ict.to_dict(), dr.to_dict(),
                                     session.to_dict(), _MACRO_MOCK, current_price)

        self._current_idx += 1
        progress = (self._current_idx - self._start_idx) / max(self.total_bars, 1)

        return {
            "timestamp":   int(cutoff_ts),
            "price":       current_price,
            "swing_score": score.get("swing", {}).get("score", 0),
            "is_swing":    score.get("swing", {}).get("score", 0) >= config.SWING_SCORE_MIN_BACKTEST,
            "is_scalp":    score.get("scalp", {}).get("is_valid", False),
            "direction":   ict.direction,
            "atr":         round(indicators.atr_h1, 2),
            "adx":         round(float(indicators.adx or 0), 2),
            "action":      ict.setup_status,
            "high":        float(current_bar["high"]),
            "low":         float(current_bar["low"]),
            "bar_index":   self._current_idx - 1,
            "session":     session.to_dict(),
            "levels":      indicators.to_dict(),
            "raw_score":   score,
            "progress":    round(progress * 100, 1),
        }


def run_all_timeframes(data_dir: str, start_date: str = None, end_date: str = None) -> tuple[list, dict]:
    """
    Run BacktestEngine on M15 and H1 primary TFs, merge setups, return combined.

    M15 is the main scanning TF (catches both swing and scalp via M5 gate).
    H1 adds higher-timeframe swing setups that M15 may miss.
    Setups are merged by timestamp — within-1h duplicates are dropped
    so the same market move doesn't count twice.

    Returns (merged_setups, full_df_by_tf) where full_df_by_tf is a dict
    keyed by primary TF for simulate_setups to use the correct bar index.
    """
    import pathlib
    data_dir_path = pathlib.Path(data_dir)

    engines = {}
    all_setups = []

    tf_configs = [
        ("15min", data_dir_path / "XAUUSD_15min.csv"),
        ("1h",    data_dir_path / "XAUUSD_1h.csv"),
    ]

    for tf, csv_path in tf_configs:
        if not csv_path.exists():
            logger.warning(f"Skipping {tf} — {csv_path} not found")
            continue
        eng = BacktestEngine(str(csv_path), timeframe=tf,
                             start_date=start_date, end_date=end_date)
        setups = eng.run()
        engines[tf] = eng
        all_setups.extend(setups)
        logger.info(f"{tf} engine: {len(setups)} setups")

    # ── Translate every setup's bar_index into the M15 full_df coordinate ──
    # system that simulate_setups will iterate on.  Without this, an H1 setup's
    # bar_index would point to the wrong row in the M15 df (different epochs),
    # and the MT-entry/update loops would scan unrelated bars.
    m15_engine = engines.get("15min")
    if m15_engine is not None:
        m15_ts = m15_engine._primary_ts
        for s in all_setups:
            if s.get("primary_tf") == "M15":
                continue
            idx = bisect.bisect_right(m15_ts, float(s["timestamp"])) - 1
            if 0 <= idx < len(m15_ts):
                s["bar_index"] = idx

    # Sort all setups by timestamp, then by TF name ('H1' < 'M15') so H1 wins ties
    all_setups.sort(key=lambda s: (s["timestamp"], s.get("primary_tf", "M15")))

    # Only remove exact-timestamp duplicates (same bar reported by two TF engines)
    # simulate_setups' 1h swing cooldown handles spacing between real trades
    seen: set[tuple] = set()
    deduped = []
    for s in all_setups:
        key = (s["timestamp"], s.get("direction", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(s)

    logger.info(f"All-TF merge: {len(all_setups)} raw → {len(deduped)} after dedup")
    return deduped, engines

"""
Live Strategy Runner — Session Expansion on live M5 candles.

Wraps the same strategy functions used by backtest/new_simulation.py so
live signals and backtest signals come from the identical code path.

Responsibilities
────────────────
  1. On each M5 close, check if we're past 13:30 IST (London window start)
  2. If no plan exists for today, build one from the accumulated Asian session
  3. During London/NY windows, call find_breakout_entry on the live bars
  4. When an entry fires, push a Telegram trade signal and stamp daily state
  5. Enforce daily guardrails (max trades, loss stop, profit cap)

State held
──────────
  self._today            — IST date string of the current trading day
  self._plan             — today's DailyPlan (None until 13:30 IST)
  self._london_done      — has a London entry fired today?
  self._ny_done          — has an NY entry fired today?
  self._day_pnl          — running realized PnL for the day
  self._day_losses       — loss count today (stop after 2, matches backtest)
"""

import json
import math
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd

import config
from journal import journal
from backtest.engine_v7 import (
    _enrich_ist, _daily_opens, _scan_dor, _scan_asw,
    MAX_RISK_PER_TRADE, MAX_LOSSES_PER_DAY, MAX_TRADES_PER_DAY,
    COMMISSION_PER_001_LOT, NY_START, NY_END, _size_lots,
)
from backtest.simulation_core import check_v6_filters

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_STATE_FILE = config.BASE_DIR / "live_trade_state.json"
_ALERT_LOG  = config.BASE_DIR / "live_alerts.json"   # rolling last 50 alerts


class LiveStrategyRunner:
    def __init__(self, telegram_bot):
        self.bot = telegram_bot
        self._today: Optional[str] = None
        self._day_pnl: float = 0.0
        self._day_losses: int = 0          # loss-streak counter (stop after 2, matches backtest)
        self._last_alert_minute: int = -1  # dedupe within same M5 bar
        self._open_signals = []
        self._pending_setup = None
        self._last_swing_ts: float = 0.0   # per-mode cooldown timestamps
        self._last_scalp_ts: float = 0.0
        self._alert_log: list = []         # last 50 trade events for UI feed

        # DOR+ASW state — same engine as backtest
        self._m5_buf: list[dict] = []
        self._fired_setup_keys: set[str] = set()   # dedup: "date|entry_time|direction"
        self._day_trades: int = 0                  # DOR+ASW trades taken today (cap = MAX_TRADES_PER_DAY)

        self._load_state()

    # ── State persistence ─────────────────────────────────────

    def _load_state(self):
        """Restore open signals and alert log from disk after restart."""
        try:
            if _STATE_FILE.exists():
                state = json.loads(_STATE_FILE.read_text())
                self._today       = state.get("today")
                self._day_pnl     = state.get("day_pnl", 0.0)
                self._day_losses  = state.get("day_losses", 0)
                self._open_signals = state.get("open_signals", [])
                logger.info(
                    f"[Live] Restored state: {len(self._open_signals)} open signal(s), "
                    f"day_pnl=${self._day_pnl:.2f}, losses={self._day_losses}"
                )
        except Exception as e:
            logger.warning(f"[Live] Could not load state: {e}")

        try:
            if _ALERT_LOG.exists():
                self._alert_log = json.loads(_ALERT_LOG.read_text())
        except Exception:
            self._alert_log = []

    def _save_state(self):
        """Persist open signals to disk so restarts don't lose trade tracking."""
        try:
            # Strip non-serialisable 'indicators' before saving
            signals_clean = [{k: v for k, v in s.items() if k != "indicators"}
                             for s in self._open_signals]
            state = {
                "today":        self._today,
                "day_pnl":      self._day_pnl,
                "day_losses":   self._day_losses,
                "open_signals": signals_clean,
            }
            _STATE_FILE.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.warning(f"[Live] Could not save state: {e}")

    def _log_alert(self, alert: dict):
        """Append alert to rolling log (last 50), save to disk."""
        self._alert_log.insert(0, alert)
        if len(self._alert_log) > 50:
            self._alert_log = self._alert_log[:50]
        try:
            _ALERT_LOG.write_text(json.dumps(self._alert_log, indent=2))
        except Exception:
            pass

    def get_live_trades_state(self) -> dict:
        """Return serialisable snapshot for UI / EventBus."""
        signals_clean = [{k: v for k, v in s.items() if k != "indicators"}
                         for s in self._open_signals]
        pending_clean = None
        if self._pending_setup:
            pending_clean = {k: v for k, v in self._pending_setup.items()
                             if k != "indicators"}
        return {
            "open_signals":  signals_clean,
            "pending_setup": pending_clean,
            "day_pnl":       round(self._day_pnl, 2),
            "day_losses":    self._day_losses,
            "alert_log":     self._alert_log,
        }

    # ── DOR + ASW scanner ─────────────────────────────────────

    def _bars_to_enriched_df(self, bars: list[dict]) -> pd.DataFrame:
        """Convert live bar list to enriched DataFrame for DOR/ASW scanners."""
        df = self._bars_to_df(bars)
        if df.empty:
            return df
        if df["datetime"].dt.tz is None:
            df["datetime"] = df["datetime"].dt.tz_localize("UTC")
        df = _enrich_ist(df)
        return df

    def _get_daily_open(self, m5_df: pd.DataFrame, date_ist: str) -> Optional[float]:
        """Return 00:00 UTC open for the given IST date."""
        opens = _daily_opens(m5_df)
        return opens.get(date_ist)

    def _check_dor_signal(self, m5_df: pd.DataFrame) -> Optional[dict]:
        """
        Check if the latest M5 bar is a DOR signal.
        Returns signal dict with direction/displacement/daily_open or None.
        """
        if len(m5_df) < 2:
            return None

        ls_start, ls_end = 15 * 60, 18 * 60
        ny_start = NY_START[0] * 60 + NY_START[1]
        ny_end   = NY_END[0]   * 60 + NY_END[1]

        row  = m5_df.iloc[-1]
        prev = m5_df.iloc[-2]
        minute_ist = int(row["minute_ist"])

        in_window = (ls_start <= minute_ist < ls_end) or (ny_start <= minute_ist < ny_end)
        if not in_window:
            return None

        date_ist = str(row["date_ist"])
        do = self._get_daily_open(m5_df, date_ist)
        if do is None:
            return None

        displacement = float(row["close"]) - do
        if abs(displacement) < 20.0:
            return None

        is_short = displacement > 0 and row["close"] < prev["close"] and row["close"] < row["open"]
        is_long  = displacement < 0 and row["close"] > prev["close"] and row["close"] > row["open"]
        if not is_short and not is_long:
            return None

        return {
            "direction":    "short" if is_short else "long",
            "displacement": displacement,
            "daily_open":   do,
            "m5_close_time": row["datetime"],
            "date_ist":     date_ist,
        }

    def _check_asw_signal(self, m5_df: pd.DataFrame) -> Optional[dict]:
        """Return first ASW setup from current M5 data, or None."""
        setups = _scan_asw(m5_df)
        if not setups:
            return None
        latest_bar_time = m5_df.iloc[-1]["datetime"]
        for s in reversed(setups):
            if s["entry_time"] == latest_bar_time:
                return s
        return None

    def on_m1_close(self, m1_bars: list[dict], event_bus) -> None:
        """No-op — M1 FVG is now handled inside _scan_dor on each M5 close."""
        pass

    def _fire_dor_alert(self, price, sl, tp, direction, lots, sl_dist,
                        displacement, daily_open, event_bus):
        is_long  = "bullish" in direction
        rr       = round(abs(tp - price) / sl_dist, 1)
        now_ist  = datetime.now(IST).strftime("%d/%m %H:%M IST")
        msg = (
            f"{'🟢' if is_long else '🔴'} <b>{'LONG' if is_long else 'SHORT'} XAUUSD — DOR+FVG</b>\n\n"
            f"Entry: <b>${price:.2f}</b>\n"
            f"SL:    <b>${sl:.2f}</b>  ({sl_dist:.1f}pt)\n"
            f"TP:    <b>${tp:.2f}</b>  (1:{rr}R)\n"
            f"Lots:  <b>{lots}</b>\n\n"
            f"Displacement: {displacement:+.1f}pt from DO {daily_open:.2f}\n"
            f"M1 FVG confirmed entry"
        )
        try:
            self.bot.send_message(msg)
        except Exception as e:
            logger.error(f"Telegram DOR alert failed: {e}")
        alert = {"type": "entry", "time": now_ist, "direction": direction,
                 "mode": "DOR", "price": price, "sl": sl, "tp": tp, "lots": lots}
        self._log_alert(alert)
        event_bus.publish("trade_signal", {
            "price": price, "sl": sl, "tp": tp,
            "direction": direction, "mode": "DOR", "lots": lots,
        })

    def _reset_day(self, date_str: str):
        self._today = date_str
        self._day_pnl = 0.0
        self._day_losses = 0
        self._day_trades = 0
        self._last_alert_minute = -1
        self._open_signals = []
        self._pending_setup = None
        self._fired_setup_keys = set()
        self._save_state()
        # cooldowns persist across days intentionally (3h swing cooldown spans midnight)

    def _bars_to_df(self, bars: list[dict]) -> pd.DataFrame:
        """Convert CandleBuilder M5 candles to a DataFrame the strategy expects."""
        if not bars:
            return pd.DataFrame()
        df = pd.DataFrame(bars)
        # CandleBuilder stores 'time' as unix seconds or datetime — normalize to 'datetime'
        if "datetime" not in df.columns:
            # Support both unix timestamp keys (OANDA: "timestamp", legacy: "time")
            ts_col = "timestamp" if "timestamp" in df.columns else ("time" if "time" in df.columns else None)
            if ts_col:
                df["datetime"] = pd.to_datetime(df[ts_col], unit="s", errors="coerce")
                mask = df["datetime"].isna()
                if mask.any():
                    df.loc[mask, "datetime"] = pd.to_datetime(df.loc[mask, ts_col])
            else:
                return pd.DataFrame()
        df["datetime"] = pd.to_datetime(df["datetime"])
        return df[["datetime", "open", "high", "low", "close"]].reset_index(drop=True)

    def _calc_sl_tp_lots(self, price: float, is_long: bool, mode: str,
                         atr: float, indicators) -> tuple[float, float, float, float]:
        """
        Mirrors simulation_core.py exactly:
          - Swing: structural H1 swing L/H with ATR floor (0.75×) and cap (2×), min 8pt
          - Scalp: fixed 8pt SL
          - Lot sizing: risk_per_trade / (sl_dist × 100), capped at mode_max
        Returns (sl_dist, sl, tp, lots).
        """
        if mode == "Scalp":
            rp      = config.SCALP_RISK
            sl_dist = float(rp.get("sl_distance", 8.0))
            tp_rr   = rp.get("tp_rr", 2.0)
        else:  # Swing
            rp       = config.SWING_RISK
            tp_rr    = rp.get("tp_rr", 3.0)
            sl_floor = atr * 0.75
            sl_cap   = atr * 2.0

            # Structural SL from H1 swing levels (same as simulation_core)
            h1_highs = []
            h1_lows  = []
            if indicators is not None:
                try:
                    levels   = indicators.to_dict()
                    h1_highs = levels.get("swing_highs_h1", [])
                    h1_lows  = levels.get("swing_lows_h1",  [])
                except Exception:
                    pass

            if is_long:
                structural  = h1_lows[-1]["price"] if h1_lows else (price - sl_floor)
                raw_sl_dist = max(price - structural, sl_floor)
            else:
                structural  = h1_highs[-1]["price"] if h1_highs else (price + sl_floor)
                raw_sl_dist = max(structural - price, sl_floor)

            sl_dist = min(max(raw_sl_dist, rp.get("min_sl_distance", 8.0)), sl_cap)

        # Lot sizing — risk_per_trade / (sl_dist × $100/lot), capped at mode_max (0.08)
        mode_max    = config.SCALP_RISK["lots"] if mode == "Scalp" else config.SWING_RISK["lots"]
        risk_budget = config.SESSION_EXPANSION.get("risk_per_trade", config.MAX_RISK_TRADE1)
        lots_raw    = risk_budget / (sl_dist * 100)
        lots        = min(math.ceil(lots_raw * 100) / 100, mode_max)
        lots        = max(lots, 0.01)
        # Step down if still over daily cap
        if sl_dist * lots * 100 > config.DAILY_LOSS_HARD_CAP:
            lots = max(lots - 0.01, 0.01)

        sl = (price - sl_dist) if is_long else (price + sl_dist)
        tp = (price + sl_dist * tp_rr) if is_long else (price - sl_dist * tp_rr)
        return sl_dist, sl, tp, lots

    def on_m5_close(self, m5_bars: list[dict], confluence: dict, ict: dict,  # noqa: PLR0912
                    event_bus, indicators=None, m1_bars: list[dict] | None = None):
        """
        Called once per M5 candle close.
        SL / TP / lot sizing mirrors simulation_core.py exactly.
        """
        if not m5_bars:
            return

        last_bar    = m5_bars[-1]
        bar_ts_unix = last_bar.get("timestamp") or last_bar.get("time")
        if bar_ts_unix and isinstance(bar_ts_unix, (int, float)):
            bar_ts = datetime.fromtimestamp(float(bar_ts_unix), tz=IST)
        else:
            bar_ts = datetime.now(IST)
        ist_date = bar_ts.strftime("%Y-%m-%d")
        ist_min  = bar_ts.hour * 100 + bar_ts.minute

        # ── Day rollover ──
        if ist_date != self._today:
            self._reset_day(ist_date)

        # ── Daily guardrails (mirrors simulation_core daily caps) ──
        if self._day_pnl <= -config.DAILY_LOSS_HARD_CAP:
            return
        if self._day_pnl >= config.DAILY_HARD_CAP:
            return
        if self._day_losses >= 2:   # 2-loss streak stop (matches backtest)
            return

        # ── 1. Check for NEW setup — apply all backtest gates before queuing ──
        now_ts = bar_ts.timestamp()
        if confluence.get("tradeable") and ist_min != self._last_alert_minute:

            # Gate A: killzone required
            if not confluence.get("killzone_active", False):
                pass  # fall through — no pending setup set

            else:
                mode  = ict.get("grade", "Scalp")
                atr   = confluence.get("atr_h1", 15.0) or 15.0
                is_swing = (mode != "Scalp")

                # Gate B: concurrent trade block
                gate_ok = len(self._open_signals) == 0 and self._pending_setup is None

                # Gate C: ATR regime gate (swing only, matches simulation_core ATR_SWING_MIN)
                if gate_ok and is_swing and atr < config.ATR_SWING_MIN:
                    gate_ok = False
                    logger.debug(f"[Live] Swing skipped — ATR {atr:.1f} < {config.ATR_SWING_MIN}")

                # Gate D: ATR ceiling
                if gate_ok and atr > config.ATR_NORMAL_MAX:
                    gate_ok = False
                    logger.debug(f"[Live] Setup skipped — ATR {atr:.1f} > {config.ATR_NORMAL_MAX}")

                # Gate E: scalp ATR gate
                if gate_ok and not is_swing and atr > config.SCALP_ATR_GATE:
                    gate_ok = False
                    logger.debug(f"[Live] Scalp skipped — ATR {atr:.1f} > {config.SCALP_ATR_GATE}")

                # Gate F: per-mode cooldown
                if gate_ok:
                    if is_swing and (now_ts - self._last_swing_ts) < config.SWING_COOLDOWN_SECONDS:
                        gate_ok = False
                        logger.debug("[Live] Swing in cooldown")
                    elif not is_swing and (now_ts - self._last_scalp_ts) < config.SCALP_COOLDOWN_SECONDS:
                        gate_ok = False
                        logger.debug("[Live] Scalp in cooldown")

                # Gate G: ICT hard gates for swing (sweep + FVG/OB both required)
                if gate_ok and is_swing:
                    swing_factors = confluence.get("swing", {}).get("factors", {})
                    has_sweep  = swing_factors.get("liquidity_sweep", {}).get("score", 0) > 0
                    has_fvg_ob = swing_factors.get("fvg_ob_overlap",  {}).get("score", 0) > 0
                    if not has_sweep or not has_fvg_ob:
                        gate_ok = False
                        logger.debug("[Live] Swing skipped — missing sweep or FVG/OB")

                # Gate H: V6 filters — shared with simulation_core for guaranteed parity
                if gate_ok and config.STRATEGY_V6_ENABLED:
                    setup_dict = {
                        "primary_tf":   ict.get("timeframe", "M15"),
                        "session":      {"killzone_name": confluence.get("session_label", "")},
                        "atr":          atr,
                        "adx":          indicators.adx if indicators else 0.0,
                        "swing_score":  float(confluence.get("swing", {}).get("score", 0.0)),
                        "entry_time":   bar_ts.isoformat(),
                        "direction":    ict.get("direction", "neutral"),
                        "levels":       indicators.to_dict() if indicators else {},
                    }
                    skip_reason = check_v6_filters(setup_dict, "SWING" if is_swing else "SCALP")
                    if skip_reason:
                        gate_ok = False
                        logger.debug(f"[Live] V6: {skip_reason}")

                if gate_ok:
                    # Stamp cooldown on SEEN (same as simulation_core)
                    if is_swing:
                        self._last_swing_ts = now_ts
                    else:
                        self._last_scalp_ts = now_ts

                    trigger_low  = last_bar["low"]
                    trigger_high = last_bar["high"]
                    mt_price     = (trigger_high + trigger_low) / 2.0

                    self._pending_setup = {
                        "mt_price":     mt_price,
                        "direction":    ict.get("direction", "neutral"),
                        "mode":         mode,
                        "tf":           "M5",
                        "confluence":   confluence.get("total", 0.0),
                        "bars_waited":  0,
                        "triggered_at": ist_min,
                        "time_ist":     bar_ts.strftime("%H:%M IST"),
                        "indicators":   indicators,
                        "atr":          atr,
                    }
                    self._last_alert_minute = ist_min
                    logger.info(f"[Live] {mode} setup detected. MT pullback at ${mt_price:.2f}")
                    event_bus.publish("live_trades", self.get_live_trades_state())

        # ── 2. Handle Pending MT Entry ──
        if self._pending_setup:
            self._pending_setup["bars_waited"] += 1
            is_long = "bullish" in self._pending_setup["direction"]

            touched = (is_long  and last_bar["low"]  <= self._pending_setup["mt_price"]) or \
                      (not is_long and last_bar["high"] >= self._pending_setup["mt_price"])

            if touched:
                setup = self._pending_setup
                price = setup["mt_price"]
                mode  = setup["mode"]
                atr   = setup["atr"] or 15.0

                sl_dist, sl, tp, lots = self._calc_sl_tp_lots(
                    price, is_long, mode, atr, setup["indicators"]
                )

                if sl_dist >= 4.0:   # degenerate SL guard (matches simulation_core)
                    self._fire_alert(price, sl, tp, setup["direction"], mode, lots, sl_dist, confluence, event_bus)
                    entry_time = bar_ts.strftime("%d/%m %H:%M IST")
                    tp_price   = (price + sl_dist * (config.SWING_RISK["tp_rr"] if mode != "Scalp" else config.SCALP_RISK["tp_rr"])) \
                                 if "bullish" in setup["direction"] \
                                 else (price - sl_dist * (config.SWING_RISK["tp_rr"] if mode != "Scalp" else config.SCALP_RISK["tp_rr"]))
                    self._open_signals.append({
                        "entry":       price,
                        "sl":          sl,
                        "tp":          tp_price,
                        "sl_dist":     sl_dist,
                        "tp_rr":       config.SWING_RISK["tp_rr"] if mode != "Scalp" else config.SCALP_RISK["tp_rr"],
                        "direction":   setup["direction"],
                        "be_moved":    False,
                        "partial_hit": False,
                        "lots":        lots,
                        "mode":        mode,
                        "tf":          setup.get("tf", "M5"),
                        "entry_time":  entry_time,
                    })
                    self._save_state()
                    event_bus.publish("live_trades", self.get_live_trades_state())
                else:
                    logger.info(f"[Live] Degenerate SL ({sl_dist:.1f}pt) — skipping entry.")

                self._pending_setup = None

            elif self._pending_setup["bars_waited"] > 3:
                logger.info("[Live] MT Entry expired (3 bars without pullback).")
                self._pending_setup = None
                event_bus.publish("live_trades", self.get_live_trades_state())

        # ── 3. Track open signals: partial TP → BE, full TP, and SL hit ──────────
        if self._open_signals:
            curr_high = last_bar["high"]
            curr_low  = last_bar["low"]
            to_remove = []

            for signal in self._open_signals:
                is_long = "bullish" in signal["direction"]
                tp_rr   = signal["tp_rr"]
                tp_price = (signal["entry"] + signal["sl_dist"] * tp_rr) if is_long \
                           else (signal["entry"] - signal["sl_dist"] * tp_rr)

                # A. Partial TP at 1R → SL to BE+0.5pt
                if not signal["partial_hit"]:
                    target_1r = (signal["entry"] + signal["sl_dist"]) if is_long \
                                else (signal["entry"] - signal["sl_dist"])
                    if (is_long and curr_high >= target_1r) or \
                       (not is_long and curr_low <= target_1r):
                        signal["partial_hit"] = True
                        signal["be_moved"]    = True
                        new_sl = signal["entry"] + (0.5 if is_long else -0.5)
                        signal["sl"] = new_sl
                        self._fire_partial_alert(signal, target_1r, new_sl, event_bus)

                # B. Full TP hit (runner closes)
                elif (is_long and curr_high >= tp_price) or \
                     (not is_long and curr_low <= tp_price):
                    pnl = signal["sl_dist"] * tp_rr * signal["lots"] * 100
                    self._fire_tp_alert(signal, tp_price, pnl, event_bus)
                    self._day_pnl += pnl
                    to_remove.append(signal)

                # C. SL hit
                elif (is_long and curr_low <= signal["sl"]) or \
                     (not is_long and curr_high >= signal["sl"]):
                    # If partial already taken, runner stopped at BE — small win not a loss
                    if signal["partial_hit"]:
                        partial_pnl = signal["sl_dist"] * signal["lots"] * 100
                        self._fire_be_exit_alert(signal, signal["sl"], partial_pnl, event_bus)
                        self._day_pnl += partial_pnl
                    else:
                        loss = -(signal["sl_dist"] * signal["lots"] * 100)
                        self._fire_sl_alert(signal, signal["sl"], loss, event_bus)
                        self._day_pnl += loss
                        self._day_losses += 1
                    to_remove.append(signal)

            for s in to_remove:
                self._open_signals.remove(s)

            if to_remove:
                self._save_state()
                event_bus.publish("live_trades", self.get_live_trades_state())

        # ── 4. DOR+ASW — identical engine to backtest (engine_v7._scan_dor/_scan_asw) ──
        self._m5_buf = m5_bars or self._m5_buf
        slot_free = len(self._open_signals) == 0 and self._pending_setup is None

        if slot_free and self._m5_buf and self._day_trades < MAX_TRADES_PER_DAY \
                and self._day_losses < MAX_LOSSES_PER_DAY:
            m5_df = self._bars_to_enriched_df(self._m5_buf)
            if not m5_df.empty:
                # Build M1 df (same as backtest)
                m1_df = None
                if m1_bars:
                    m1_df = self._bars_to_df(m1_bars)
                    if not m1_df.empty:
                        if m1_df["datetime"].dt.tz is None:
                            m1_df["datetime"] = m1_df["datetime"].dt.tz_localize("UTC")
                    else:
                        m1_df = None

                # Run same scan functions as backtest engine_v7
                setups = _scan_dor(m5_df, m1_df) + _scan_asw(m5_df)

                # Current bar window — only fire setups from the last M5 bar
                last_ts = m5_df.iloc[-1]["datetime"]
                if last_ts.tzinfo is None:
                    last_ts = last_ts.tz_localize("UTC")
                window_start = last_ts - pd.Timedelta(minutes=5)

                for setup in setups:
                    entry_t = pd.Timestamp(setup["entry_time"])
                    if entry_t.tzinfo is None:
                        entry_t = entry_t.tz_localize("UTC")
                    if entry_t < window_start:
                        continue   # older setup, already fired or skipped

                    key = f"{ist_date}|{setup['entry_time']}|{setup['direction']}"
                    if key in self._fired_setup_keys:
                        continue   # already alerted this exact setup

                    entry   = float(setup["entry"])
                    sl      = float(setup["sl"])
                    tp      = float(setup["tp"])
                    sl_dist = abs(entry - sl)
                    lots    = _size_lots(sl_dist, MAX_RISK_PER_TRADE)
                    if sl_dist < 4.0 or lots < 0.01:
                        continue

                    direction_str = "bearish" if setup["direction"] == "short" else "bullish"
                    self._fire_dor_alert(
                        entry, sl, tp, direction_str, lots, sl_dist,
                        0.0, 0.0, event_bus,
                    )
                    self._open_signals.append({
                        "entry":       entry,
                        "sl":          sl,
                        "tp":          tp,
                        "sl_dist":     sl_dist,
                        "tp_rr":       abs(tp - entry) / sl_dist,
                        "direction":   direction_str,
                        "be_moved":    False,
                        "partial_hit": False,
                        "lots":        lots,
                        "mode":        setup.get("engine", "DOR"),
                        "tf":          "M5",
                        "entry_time":  datetime.now(IST).strftime("%d/%m %H:%M IST"),
                    })
                    self._fired_setup_keys.add(key)
                    self._day_trades += 1
                    self._save_state()
                    event_bus.publish("live_trades", self.get_live_trades_state())
                    break  # one new signal per M5 close — same as backtest slot logic

    def _journal_trade(self, signal, exit_price, result, pnl, event_bus):
        """Log completed trade to journal and push updated account state to UI."""
        try:
            journal.log_trade({
                "direction":       signal["direction"],
                "entry":           signal["entry"],
                "sl":              signal["sl"],
                "tp":              signal.get("tp", 0),
                "exit_price":      exit_price,
                "result":          result,
                "pnl":             pnl,
                "lot_size":        signal["lots"],
                "grade":           signal.get("mode", "Swing"),
                "confluence_score": 0,
                "session":         "Live",
            })
        except Exception as e:
            logger.error(f"[Live] Journal write failed: {e}")
        # Push fresh account state to dashboard
        try:
            account = journal.get_account_state()
            event_bus.publish("account_update", account)
        except Exception as e:
            logger.error(f"[Live] Account state publish failed: {e}")

    def _fire_alert(self, price, sl, tp, direction, mode, lots, sl_dist, confluence, event_bus):
        """Send Telegram ICT signal + publish trade_signal event."""
        rr = config.SWING_RISK["tp_rr"] if mode != "Scalp" else config.SCALP_RISK["tp_rr"]
        msg_lines = [
            f"{'🟢' if 'bullish' in direction else '🔴'} "
            f"<b>{direction.upper()} XAUUSD — {mode}</b>",
            "",
            "💎 <b>ICT ENTRY (MT LIMIT)</b>",
            f"Entry: <b>${price:.2f}</b>",
            f"SL:    <b>${sl:.2f}</b>  ({sl_dist:.1f}pt)",
            f"TP:    <b>${tp:.2f}</b>  (1:{rr}R)",
            f"Lots:  <b>{lots}</b>",
            f"Partial: 50% close at 1R → runner to {rr}R",
            "",
            f"Confluence: {confluence.get('total', 0.0):.1f} | ATR: {confluence.get('atr_h1', 0):.1f}pt",
        ]
        text = "\n".join(msg_lines)
        now_ist = datetime.now(IST).strftime("%d/%m %H:%M IST")
        try:
            self.bot.send_message(text)
        except Exception as e:
            logger.error(f"Telegram alert failed: {e}")
        alert = {"type": "entry", "time": now_ist, "direction": direction,
                 "mode": mode, "price": price, "sl": sl, "tp": tp, "lots": lots}
        self._log_alert(alert)
        event_bus.publish("trade_signal", {
            "price": price, "sl": sl, "tp": tp,
            "direction": direction, "mode": mode, "lots": lots,
        })

    def _fire_partial_alert(self, signal, price, new_sl, event_bus):
        """50% closed at 1R — runner now risk-free."""
        now_ist = datetime.now(IST).strftime("%d/%m %H:%M IST")
        text = (
            f"💰 <b>PARTIAL PROFIT (1R HIT)</b>\n\n"
            f"✅ Close 50% of {signal['direction'].upper()} position @ <b>${price:.2f}</b>\n"
            f"🛡️ Move SL to <b>${new_sl:.2f}</b> (breakeven)\n\n"
            f"Runner targeting {signal['tp_rr']}R — let it run."
        )
        try:
            self.bot.send_message(text)
        except Exception as e:
            logger.error(f"Telegram Partial alert failed: {e}")
        alert = {"type": "partial_tp", "time": now_ist, "direction": signal["direction"],
                 "price": price, "new_sl": new_sl}
        self._log_alert(alert)
        event_bus.publish("alert", {"type": "partial_tp", "message": f"1R hit for {signal['direction']}"})

    def _fire_tp_alert(self, signal, price, pnl, event_bus):
        """Full TP (runner) hit."""
        now_ist = datetime.now(IST).strftime("%d/%m %H:%M IST")
        text = (
            f"🏆 <b>FULL TP HIT ({signal['tp_rr']}R)</b>\n\n"
            f"✅ Close remaining {signal['direction'].upper()} position @ <b>${price:.2f}</b>\n"
            f"💵 Runner P&L: <b>+${pnl:.2f}</b>\n\n"
            f"Trade complete. Well done."
        )
        try:
            self.bot.send_message(text)
        except Exception as e:
            logger.error(f"Telegram TP alert failed: {e}")
        alert = {"type": "tp_hit", "time": now_ist, "direction": signal["direction"],
                 "price": price, "pnl": round(pnl, 2)}
        self._log_alert(alert)
        self._journal_trade(signal, price, "WIN", round(pnl, 2), event_bus)
        event_bus.publish("alert", {"type": "tp_hit", "pnl": pnl})

    def _fire_sl_alert(self, signal, price, loss, event_bus):
        """Full stop loss hit — no partial was taken."""
        now_ist = datetime.now(IST).strftime("%d/%m %H:%M IST")
        text = (
            f"🛑 <b>STOP LOSS HIT</b>\n\n"
            f"❌ {signal['direction'].upper()} stopped @ <b>${price:.2f}</b>\n"
            f"💸 Loss: <b>${loss:.2f}</b>\n\n"
            f"Trade closed. Follow the plan."
        )
        try:
            self.bot.send_message(text)
        except Exception as e:
            logger.error(f"Telegram SL alert failed: {e}")
        alert = {"type": "sl_hit", "time": now_ist, "direction": signal["direction"],
                 "price": price, "pnl": round(loss, 2)}
        self._log_alert(alert)
        self._journal_trade(signal, price, "LOSS", round(loss, 2), event_bus)
        event_bus.publish("alert", {"type": "sl_hit", "pnl": loss})

    def _fire_be_exit_alert(self, signal, price, partial_pnl, event_bus):
        """Runner stopped at breakeven after partial was already taken."""
        now_ist = datetime.now(IST).strftime("%d/%m %H:%M IST")
        text = (
            f"⚪ <b>RUNNER CLOSED AT BREAKEVEN</b>\n\n"
            f"Remaining {signal['direction'].upper()} position exited @ <b>${price:.2f}</b>\n"
            f"💵 Partial profit already secured: <b>+${partial_pnl:.2f}</b>\n\n"
            f"Net result: positive trade."
        )
        try:
            self.bot.send_message(text)
        except Exception as e:
            logger.error(f"Telegram BE exit alert failed: {e}")
        alert = {"type": "be_exit", "time": now_ist, "direction": signal["direction"],
                 "price": price, "pnl": round(partial_pnl, 2)}
        self._log_alert(alert)
        self._journal_trade(signal, price, "BE", round(partial_pnl, 2), event_bus)
        event_bus.publish("alert", {"type": "be_exit", "pnl": partial_pnl})

"""
Session VWAP Mean Reversion Strategy
====================================
Intraday ES strategy (DEPRECATED — use `orb`). See strategies/session/DEPRECATED.md.

- **Fade VWAP extensions** in range-bound sessions (ADX cap, opening-range regime).
- **Session structure**: trade after opening range completes; flat before close.
- **Target VWAP** (institutional anchor); ATR-scaled stops.

Replaces abandoned Donchian breakout trend logic (see docs/strategy_pivot.md).
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from datetime import time

from strategies.base import Strategy
from strategies.bollinger.filters import apply_maintenance_filter, apply_rth_filter
from strategies.bollinger.indicators import calculate_adx, calculate_atr
from strategies.session.indicators import (
    calculate_opening_range,
    calculate_session_vwap,
    calculate_vwap_bands,
)
from strategies.session.parameters import get_param_value


class SessionVwapStrategy(Strategy):
    """RTH session VWAP mean-reversion with opening-range regime filter."""

    def __init__(self, params_dict):
        self.params_dict = params_dict
        self._extract_params()

    def _parse_time(self, time_str):
        try:
            return pd.to_datetime(time_str, format="%H:%M").time()
        except Exception:
            return time(9, 30)

    def _as_bool(self, val, default=False):
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(int(val))
        if isinstance(val, str):
            return val.strip().lower() in ("true", "1", "yes")
        return default

    def _extract_params(self):
        p = self.params_dict
        self.max_open_trades = int(get_param_value(p, "Max Open Trades", 1))
        self.enable_long = self._as_bool(get_param_value(p, "Enable Long Trades", True), True)
        self.enable_short = self._as_bool(get_param_value(p, "Enable Short Trades", True), True)
        self.timeframe = max(1, int(get_param_value(p, "Timeframe (minutes)", 5)))

        # Entry: VWAP extension + revert
        self.min_extension_pts = float(get_param_value(p, "Min VWAP Extension (pts)", 8.0))
        self.entry_atr_mult = float(get_param_value(p, "Entry Band ATR Multiplier", 1.5))
        self.reversion_confirm_bars = max(
            1, int(get_param_value(p, "Reversion Confirm Bars", 2))
        )
        self.atr_length = int(get_param_value(p, "ATR Length", 14))

        # Opening range regime
        self.opening_range_minutes = int(get_param_value(p, "Opening Range (minutes)", 30))
        self.min_or_width_pts = float(get_param_value(p, "Min OR Width (pts)", 4.0))
        self.max_or_width_pts = float(get_param_value(p, "Max OR Width (pts)", 35.0))

        # Regime filters
        self.enable_adx_filter = self._as_bool(get_param_value(p, "Enable ADX Filter", True), True)
        self.adx_period = int(get_param_value(p, "ADX Period", 14))
        self.max_adx = float(get_param_value(p, "Max ADX Threshold", 22.0))
        self.min_atr_pts = float(get_param_value(p, "Min ATR (pts)", 1.0))
        self.max_atr_pts = float(get_param_value(p, "Max ATR (pts)", 25.0))

        # Session time windows (minutes from RTH open)
        self.trade_start_minutes = int(get_param_value(p, "Trade Start After OR (min)", 0))
        self.trade_end_minutes = int(get_param_value(p, "Trade End Before RTH Close (min)", 30))

        # Exits
        self.stop_atr_mult = float(get_param_value(p, "Stop ATR Multiplier", 1.25))
        self.tp_vwap_buffer_pts = float(get_param_value(p, "TP VWAP Buffer (pts)", 1.0))
        self.max_hold_bars = int(get_param_value(p, "Max Hold (bars)", 36))
        self.enable_trailing = self._as_bool(get_param_value(p, "Enable Trailing Stop", False), False)
        self.trailing_delay = int(get_param_value(p, "Trailing Delay (bars)", 3))
        self.atr_mult_ts = float(get_param_value(p, "ATR Multiplier for Trailing Stop", 2.0))

        # RTH / maintenance
        self.enable_rth_filter = self._as_bool(get_param_value(p, "Enable RTH Filter", True), True)
        self.rth_start_str = get_param_value(p, "RTH Start (HH:MM)", "09:30")
        self.rth_end_str = get_param_value(p, "RTH End (HH:MM)", "16:00")
        self.rth_exit_buffer_minutes = int(get_param_value(p, "RTH Exit Buffer (minutes)", 15))
        self.enable_maintenance_filter = self._as_bool(
            get_param_value(p, "Enable Maintenance Filter", True), True
        )
        self.daily_maintenance_start_str = get_param_value(p, "Daily Maintenance Start (HH:MM)", "17:00")
        self.daily_maintenance_end_str = get_param_value(p, "Daily Maintenance End (HH:MM)", "17:30")
        self.weekend_maintenance_start_day = int(get_param_value(p, "Weekend Maintenance Start Day", 4))
        self.weekend_maintenance_start_time_str = get_param_value(
            p, "Weekend Maintenance Start Time (HH:MM)", "17:00"
        )
        self.weekend_maintenance_end_day = int(get_param_value(p, "Weekend Maintenance End Day", 6))
        self.weekend_maintenance_end_time_str = get_param_value(
            p, "Weekend Maintenance End Time (HH:MM)", "18:00"
        )
        self.maintenance_buffer_minutes = int(get_param_value(p, "Maintenance Buffer Minutes", 15))

        self.rth_start = self._parse_time(self.rth_start_str)
        self.rth_end = self._parse_time(self.rth_end_str)

    @property
    def min_bars_required(self) -> int:
        or_bars = max(1, self.opening_range_minutes // max(1, self.timeframe))
        return max(
            self.atr_length,
            self.adx_period,
            or_bars,
            self.reversion_confirm_bars,
        ) + 20

    def get_param_structure(self) -> dict:
        return {
            "Entry Criteria": {
                "Timeframe (minutes)": self.timeframe,
                "Min VWAP Extension (pts)": self.min_extension_pts,
                "Reversion Confirm Bars": self.reversion_confirm_bars,
                "Entry Band ATR Multiplier": self.entry_atr_mult,
                "Opening Range (minutes)": self.opening_range_minutes,
                "Min OR Width (pts)": self.min_or_width_pts,
                "Max OR Width (pts)": self.max_or_width_pts,
                "Max ADX Threshold": self.max_adx,
                "Enable ADX Filter": self.enable_adx_filter,
            },
            "Exit Criteria": {
                "Stop ATR Multiplier": self.stop_atr_mult,
                "TP VWAP Buffer (pts)": self.tp_vwap_buffer_pts,
                "Max Hold (bars)": self.max_hold_bars,
                "Enable Trailing Stop": self.enable_trailing,
            },
            "Session": {
                "RTH Start": self.rth_start_str,
                "RTH End": self.rth_end_str,
                "Trade End Before Close (min)": self.trade_end_minutes,
            },
        }

    def update_optimizable_params(self, params):
        mapping = {
            "Timeframe (minutes)": ("timeframe", int),
            "Min VWAP Extension (pts)": ("min_extension_pts", float),
            "Reversion Confirm Bars": ("reversion_confirm_bars", int),
            "Entry Band ATR Multiplier": ("entry_atr_mult", float),
            "Opening Range (minutes)": ("opening_range_minutes", int),
            "Min OR Width (pts)": ("min_or_width_pts", float),
            "Max OR Width (pts)": ("max_or_width_pts", float),
            "Max ADX Threshold": ("max_adx", float),
            "Enable ADX Filter": ("enable_adx_filter", self._as_bool),
            "Stop ATR Multiplier": ("stop_atr_mult", float),
            "TP VWAP Buffer (pts)": ("tp_vwap_buffer_pts", float),
            "Max Hold (bars)": ("max_hold_bars", int),
            "Enable Trailing Stop": ("enable_trailing", self._as_bool),
            "Trailing Delay (bars)": ("trailing_delay", int),
            "ATR Multiplier for Trailing Stop": ("atr_mult_ts", float),
            "ATR Length": ("atr_length", int),
        }
        for key, (attr, caster) in mapping.items():
            if key in params:
                val = params[key]
                if caster is self._as_bool:
                    setattr(self, attr, caster(val))
                elif caster is int:
                    setattr(self, attr, max(1, int(val)))
                else:
                    setattr(self, attr, caster(val))

    def apply_filters(self, df):
        df = apply_rth_filter(
            df,
            self.enable_rth_filter,
            self.rth_start,
            self.rth_end,
            self.rth_exit_buffer_minutes,
        )
        df = apply_maintenance_filter(
            df,
            self.enable_maintenance_filter,
            self.daily_maintenance_start_str,
            self.daily_maintenance_end_str,
            self.weekend_maintenance_start_day,
            self.weekend_maintenance_start_time_str,
            self.weekend_maintenance_end_day,
            self.weekend_maintenance_end_time_str,
            self.maintenance_buffer_minutes,
        )
        return df

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        in_rth = df["in_rth"] if "in_rth" in df.columns else pd.Series(True, index=df.index)

        df["atr"] = calculate_atr(df, self.atr_length)
        if self.enable_adx_filter:
            df["adx"] = calculate_adx(df, self.adx_period)

        df["vwap"] = calculate_session_vwap(df, in_rth)
        df["vwap_upper"], df["vwap_lower"] = calculate_vwap_bands(
            df, df["vwap"], df["atr"], self.entry_atr_mult
        )

        or_bars = max(1, int(round(self.opening_range_minutes / max(1, self.timeframe))))
        df["or_high"], df["or_low"], df["or_width"] = calculate_opening_range(
            df, in_rth, or_bars
        )

        # Minutes from RTH open per bar (for trade window)
        bar_mins = df.index.hour * 60 + df.index.minute
        open_mins = self.rth_start.hour * 60 + self.rth_start.minute
        df["mins_from_rth_open"] = (bar_mins - open_mins).where(in_rth, -1)
        rth_close_mins = self.rth_end.hour * 60 + self.rth_end.minute
        df["mins_to_rth_close"] = rth_close_mins - bar_mins

        return df

    def calculate_entry_signals(self, df: pd.DataFrame, verbose=False):
        in_rth = df["in_rth"] if "in_rth" in df.columns else pd.Series(True, index=df.index)
        in_maint = df["in_maintenance"] if "in_maintenance" in df.columns else pd.Series(False, index=df.index)

        dist = df["close"] - df["vwap"]

        # Revert toward VWAP after extension (fade, not chase).
        # Require N consecutive bars moving toward VWAP — skip the first touch bar.
        revert_up = (dist > dist.shift(1)) & (dist < 0)
        revert_down = (dist < dist.shift(1)) & (dist > 0)
        confirm_up = revert_up
        confirm_down = revert_down
        for lag in range(1, self.reversion_confirm_bars):
            confirm_up = confirm_up & revert_up.shift(lag)
            confirm_down = confirm_down & revert_down.shift(lag)

        lookback = self.reversion_confirm_bars
        extended_low = (
            (dist.shift(lookback) <= -self.min_extension_pts)
            | (df["low"].shift(lookback) <= df["vwap_lower"].shift(lookback))
        )
        extended_high = (
            (dist.shift(lookback) >= self.min_extension_pts)
            | (df["high"].shift(lookback) >= df["vwap_upper"].shift(lookback))
        )
        # Still extended enough to have a meaningful VWAP target (not already at mean).
        room_long = dist <= -max(1.0, self.tp_vwap_buffer_pts)
        room_short = dist >= max(1.0, self.tp_vwap_buffer_pts)

        long_sig = extended_low & confirm_up & room_long
        short_sig = extended_high & confirm_down & room_short

        # Regime: range day via ADX
        if self.enable_adx_filter and "adx" in df.columns:
            long_sig &= df["adx"] <= self.max_adx
            short_sig &= df["adx"] <= self.max_adx

        # ATR regime
        long_sig &= (df["atr"] >= self.min_atr_pts) & (df["atr"] <= self.max_atr_pts)
        short_sig &= (df["atr"] >= self.min_atr_pts) & (df["atr"] <= self.max_atr_pts)

        # Opening range: valid width = range day, not trend explosion
        if "or_width" in df.columns:
            or_ok = (df["or_width"] >= self.min_or_width_pts) & (
                df["or_width"] <= self.max_or_width_pts
            )
            or_ready = df["or_width"].notna()
            long_sig &= or_ok & or_ready
            short_sig &= or_ok & or_ready

        # Session timing
        or_complete_mins = self.opening_range_minutes + self.trade_start_minutes
        time_ok = (
            in_rth
            & ~in_maint
            & (df["mins_from_rth_open"] >= or_complete_mins)
            & (df["mins_to_rth_close"] >= self.trade_end_minutes)
        )
        long_sig &= time_ok
        short_sig &= time_ok

        if not self.enable_long:
            long_sig = pd.Series(False, index=df.index)
        if not self.enable_short:
            short_sig = pd.Series(False, index=df.index)

        return long_sig.fillna(False), short_sig.fillna(False)

    def setup_position(self, entry_price, direction, row, df=None):
        atr = float(row["atr"]) if "atr" in row and not pd.isna(row["atr"]) else 4.0
        vwap = float(row["vwap"]) if "vwap" in row and not pd.isna(row["vwap"]) else entry_price
        stop_dist = max(2.0, self.stop_atr_mult * atr)
        min_tp_dist = max(2.0, 0.35 * stop_dist)

        if direction == 1:
            stop = entry_price - stop_dist
            tp = vwap - self.tp_vwap_buffer_pts
            if tp <= entry_price + min_tp_dist:
                tp = entry_price + min_tp_dist
        else:
            stop = entry_price + stop_dist
            tp = vwap + self.tp_vwap_buffer_pts
            if tp >= entry_price - min_tp_dist:
                tp = entry_price - min_tp_dist

        return {
            "entry_time": row.Index if not isinstance(row, pd.Series) else row.name,
            "entry_price": entry_price,
            "direction": direction,
            "stop": stop,
            "tp": tp,
            "target_vwap": vwap,
            "bars_held": 0,
            "highest_high": entry_price if direction == 1 else -1,
            "lowest_low": entry_price if direction == -1 else 999999,
        }

    def check_exit(self, position, row, df):
        idx = row.Index if not isinstance(row, pd.Series) else row.name
        high = row.high if not isinstance(row, pd.Series) else row["high"]
        low = row.low if not isinstance(row, pd.Series) else row["low"]
        close = row.close if not isinstance(row, pd.Series) else row["close"]

        if isinstance(row, pd.Series):
            force_exit = bool(row.get("force_exit", False))
            force_exit_rth = bool(row.get("force_exit_rth", False))
            in_maintenance = bool(row.get("in_maintenance", False))
        else:
            force_exit = bool(getattr(row, "force_exit", False))
            force_exit_rth = bool(getattr(row, "force_exit_rth", False))
            in_maintenance = bool(getattr(row, "in_maintenance", False))

        if force_exit or in_maintenance:
            return True, "Maintenance Exit", close
        if force_exit_rth:
            return True, "RTH Exit", close

        dir_ = position["direction"]
        stop_price = position.get("stop", 0)
        tp_price = position.get("tp")
        bars_held = int(position.get("bars_held", 0) or 0)

        if bars_held >= self.max_hold_bars > 0:
            return True, "Time Exit", close

        # Stop
        if dir_ == 1 and low <= stop_price:
            return True, "Stop Loss", stop_price
        if dir_ == -1 and high >= stop_price:
            return True, "Stop Loss", stop_price

        # TP at VWAP target
        if tp_price is not None:
            if dir_ == 1 and high >= tp_price:
                return True, "Take Profit", tp_price
            if dir_ == -1 and low <= tp_price:
                return True, "Take Profit", tp_price

        # Dynamic VWAP touch (session anchor)
        vwap = row.get("vwap") if isinstance(row, pd.Series) else getattr(row, "vwap", None)
        if vwap is not None and not pd.isna(vwap):
            vwap = float(vwap)
            if dir_ == 1 and close >= vwap - self.tp_vwap_buffer_pts:
                return True, "VWAP Exit", close
            if dir_ == -1 and close <= vwap + self.tp_vwap_buffer_pts:
                return True, "VWAP Exit", close

        return False, None, None

    def update_trailing_stop(self, position, row, df):
        if not self.enable_trailing:
            return False

        high = row.high if not isinstance(row, pd.Series) else row["high"]
        low = row.low if not isinstance(row, pd.Series) else row["low"]
        atr = row.atr if not isinstance(row, pd.Series) else row["atr"]

        bars_held = int(position.get("bars_held", 0) or 0)
        if bars_held == 0:
            position["bars_held"] = 1
            return False

        position["bars_held"] = bars_held + 1
        if position["bars_held"] < self.trailing_delay:
            return False

        stop_before = position["stop"]
        if position["direction"] == 1:
            new_stop = high - (atr * self.atr_mult_ts)
            if new_stop > position["stop"]:
                position["stop"] = new_stop
        else:
            new_stop = low + (atr * self.atr_mult_ts)
            if new_stop < position["stop"]:
                position["stop"] = new_stop

        return bool(position["stop"] != stop_before)

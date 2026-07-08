"""
Opening Range Breakout + Acceptance Strategy
============================================
Intraday ES momentum after the opening range (OR):

- **Breakout:** close beyond OR high/low (+ optional buffer).
- **Acceptance:** N consecutive closes holding beyond the OR level (no fade on first poke).
- **Regime:** OR width band, min ADX (trend day), optional VWAP alignment, ATR band.
- **Exit:** stop at opposite OR side or ATR; target = measured move (k × OR width); time/RTH flat.

Replaces failed Session VWAP fade (see docs/strategy_pivot.md).
"""

from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd

from strategies.base import Strategy
from strategies.bollinger.filters import apply_maintenance_filter, apply_rth_filter
from strategies.bollinger.indicators import calculate_adx, calculate_atr
from strategies.orb.parameters import get_param_value
from strategies.session.indicators import calculate_opening_range, calculate_session_vwap


class OrbAcceptanceStrategy(Strategy):
    """RTH opening-range breakout with close acceptance confirmation."""

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

        self.opening_range_minutes = int(get_param_value(p, "Opening Range (minutes)", 30))
        self.acceptance_bars = max(1, int(get_param_value(p, "Acceptance Bars", 2)))
        self.breakout_buffer_pts = float(get_param_value(p, "Breakout Buffer (pts)", 0.5))
        self.atr_length = int(get_param_value(p, "ATR Length", 14))

        self.min_or_width_pts = float(get_param_value(p, "Min OR Width (pts)", 6.0))
        self.max_or_width_pts = float(get_param_value(p, "Max OR Width (pts)", 45.0))
        self.trade_start_minutes = int(get_param_value(p, "Trade Start After OR (min)", 0))
        self.trade_end_minutes = int(get_param_value(p, "Trade End Before RTH Close (min)", 30))
        self.max_entries_per_day = max(1, int(get_param_value(p, "Max Entries Per Day", 1)))

        self.enable_adx_filter = self._as_bool(get_param_value(p, "Enable ADX Filter", True), True)
        self.adx_period = int(get_param_value(p, "ADX Period", 14))
        self.min_adx = float(get_param_value(p, "Min ADX Threshold", 18.0))
        self.max_adx = float(get_param_value(p, "Max ADX Threshold", 45.0))
        self.min_atr_pts = float(get_param_value(p, "Min ATR (pts)", 1.0))
        self.max_atr_pts = float(get_param_value(p, "Max ATR (pts)", 25.0))
        self.enable_vwap_filter = self._as_bool(get_param_value(p, "Enable VWAP Filter", True), True)

        self.stop_atr_mult = float(get_param_value(p, "Stop ATR Multiplier", 1.25))
        self.use_or_stop = self._as_bool(get_param_value(p, "Use Opposite OR Stop", True), True)
        self.or_stop_buffer_pts = float(get_param_value(p, "OR Stop Buffer (pts)", 0.5))
        self.target_or_mult = float(get_param_value(p, "Target OR Width Multiple", 1.0))
        self.max_hold_bars = int(get_param_value(p, "Max Hold (bars)", 48))
        self.enable_trailing = self._as_bool(get_param_value(p, "Enable Trailing Stop", False), False)
        self.trailing_delay = int(get_param_value(p, "Trailing Delay (bars)", 4))
        self.atr_mult_ts = float(get_param_value(p, "ATR Multiplier for Trailing Stop", 2.0))

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
        return max(self.atr_length, self.adx_period, or_bars, self.acceptance_bars) + 20

    def get_param_structure(self) -> dict:
        return {
            "Entry Criteria": {
                "Timeframe (minutes)": self.timeframe,
                "Opening Range (minutes)": self.opening_range_minutes,
                "Acceptance Bars": self.acceptance_bars,
                "Breakout Buffer (pts)": self.breakout_buffer_pts,
                "Min OR Width (pts)": self.min_or_width_pts,
                "Max OR Width (pts)": self.max_or_width_pts,
                "Min ADX Threshold": self.min_adx,
                "Enable VWAP Filter": self.enable_vwap_filter,
            },
            "Exit Criteria": {
                "Stop ATR Multiplier": self.stop_atr_mult,
                "Use Opposite OR Stop": self.use_or_stop,
                "Target OR Width Multiple": self.target_or_mult,
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
            "Opening Range (minutes)": ("opening_range_minutes", int),
            "Acceptance Bars": ("acceptance_bars", int),
            "Breakout Buffer (pts)": ("breakout_buffer_pts", float),
            "Min OR Width (pts)": ("min_or_width_pts", float),
            "Max OR Width (pts)": ("max_or_width_pts", float),
            "Min ADX Threshold": ("min_adx", float),
            "Max ADX Threshold": ("max_adx", float),
            "Enable ADX Filter": ("enable_adx_filter", self._as_bool),
            "Enable VWAP Filter": ("enable_vwap_filter", self._as_bool),
            "Stop ATR Multiplier": ("stop_atr_mult", float),
            "Use Opposite OR Stop": ("use_or_stop", self._as_bool),
            "OR Stop Buffer (pts)": ("or_stop_buffer_pts", float),
            "Target OR Width Multiple": ("target_or_mult", float),
            "Max Hold (bars)": ("max_hold_bars", int),
            "Enable Trailing Stop": ("enable_trailing", self._as_bool),
            "Trailing Delay (bars)": ("trailing_delay", int),
            "ATR Multiplier for Trailing Stop": ("atr_mult_ts", float),
            "ATR Length": ("atr_length", int),
            "Max Entries Per Day": ("max_entries_per_day", int),
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

        or_bars = max(1, int(round(self.opening_range_minutes / max(1, self.timeframe))))
        df["or_high"], df["or_low"], df["or_width"] = calculate_opening_range(
            df, in_rth, or_bars
        )

        bar_mins = df.index.hour * 60 + df.index.minute
        open_mins = self.rth_start.hour * 60 + self.rth_start.minute
        df["mins_from_rth_open"] = (bar_mins - open_mins).where(in_rth, -1)
        rth_close_mins = self.rth_end.hour * 60 + self.rth_end.minute
        df["mins_to_rth_close"] = rth_close_mins - bar_mins

        return df

    def _consecutive_beyond(self, beyond: pd.Series, n: int) -> pd.Series:
        ok = beyond.fillna(False)
        combined = ok.copy()
        for lag in range(1, n):
            combined &= ok.shift(lag).fillna(False)
        return combined

    def calculate_entry_signals(self, df: pd.DataFrame, verbose=False):
        in_rth = df["in_rth"] if "in_rth" in df.columns else pd.Series(True, index=df.index)
        in_maint = df["in_maintenance"] if "in_maintenance" in df.columns else pd.Series(False, index=df.index)

        buf = self.breakout_buffer_pts
        above = df["close"] > (df["or_high"] + buf)
        below = df["close"] < (df["or_low"] - buf)

        long_accept = self._consecutive_beyond(above, self.acceptance_bars)
        short_accept = self._consecutive_beyond(below, self.acceptance_bars)

        # Fire once when acceptance completes (edge, not every bar beyond OR).
        long_sig = long_accept & ~long_accept.shift(1).fillna(False)
        short_sig = short_accept & ~short_accept.shift(1).fillna(False)

        if self.enable_adx_filter and "adx" in df.columns:
            adx_ok = (df["adx"] >= self.min_adx) & (df["adx"] <= self.max_adx)
            long_sig &= adx_ok
            short_sig &= adx_ok

        atr_ok = (df["atr"] >= self.min_atr_pts) & (df["atr"] <= self.max_atr_pts)
        long_sig &= atr_ok
        short_sig &= atr_ok

        if "or_width" in df.columns:
            or_ok = (df["or_width"] >= self.min_or_width_pts) & (
                df["or_width"] <= self.max_or_width_pts
            )
            or_ready = df["or_width"].notna()
            long_sig &= or_ok & or_ready
            short_sig &= or_ok & or_ready

        if self.enable_vwap_filter and "vwap" in df.columns:
            long_sig &= df["close"] >= df["vwap"]
            short_sig &= df["close"] <= df["vwap"]

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

        long_sig, short_sig = self._cap_entries_per_day(df, long_sig, short_sig)

        return long_sig.fillna(False), short_sig.fillna(False)

    def _cap_entries_per_day(self, df, long_sig, short_sig):
        """Limit new entries per calendar session day."""
        if self.max_entries_per_day <= 0:
            return long_sig, short_sig
        day = pd.Series(df.index.date, index=df.index)
        long_out = pd.Series(False, index=df.index)
        short_out = pd.Series(False, index=df.index)
        for _, idx in df.groupby(day, sort=False).groups.items():
            count = 0
            for i in idx:
                if count >= self.max_entries_per_day:
                    break
                if long_sig.loc[i]:
                    long_out.loc[i] = True
                    count += 1
                elif short_sig.loc[i]:
                    short_out.loc[i] = True
                    count += 1
        return long_out, short_out

    def setup_position(self, entry_price, direction, row, df=None):
        atr = float(row["atr"]) if "atr" in row and not pd.isna(row["atr"]) else 4.0
        or_width = float(row["or_width"]) if "or_width" in row and not pd.isna(row["or_width"]) else max(8.0, atr * 2)
        or_high = float(row["or_high"]) if "or_high" in row and not pd.isna(row["or_high"]) else entry_price
        or_low = float(row["or_low"]) if "or_low" in row and not pd.isna(row["or_low"]) else entry_price

        atr_stop_dist = max(2.0, self.stop_atr_mult * atr)
        target_dist = max(4.0, self.target_or_mult * or_width)

        if direction == 1:
            atr_stop = entry_price - atr_stop_dist
            or_stop = or_low - self.or_stop_buffer_pts
            stop = or_stop if self.use_or_stop else atr_stop
            if stop >= entry_price:
                stop = atr_stop
            tp = entry_price + target_dist
            if tp <= entry_price + 2.0:
                tp = entry_price + 2.0
        else:
            atr_stop = entry_price + atr_stop_dist
            or_stop = or_high + self.or_stop_buffer_pts
            stop = or_stop if self.use_or_stop else atr_stop
            if stop <= entry_price:
                stop = atr_stop
            tp = entry_price - target_dist
            if tp >= entry_price - 2.0:
                tp = entry_price - 2.0

        return {
            "entry_time": row.Index if not isinstance(row, pd.Series) else row.name,
            "entry_price": entry_price,
            "direction": direction,
            "stop": stop,
            "tp": tp,
            "target_or_width": or_width,
            "bars_held": 0,
            "highest_high": entry_price if direction == 1 else -1,
            "lowest_low": entry_price if direction == -1 else 999999,
        }

    def check_exit(self, position, row, df):
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

        if dir_ == 1 and low <= stop_price:
            return True, "Stop Loss", stop_price
        if dir_ == -1 and high >= stop_price:
            return True, "Stop Loss", stop_price

        if tp_price is not None:
            if dir_ == 1 and high >= tp_price:
                return True, "Take Profit", tp_price
            if dir_ == -1 and low <= tp_price:
                return True, "Take Profit", tp_price

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

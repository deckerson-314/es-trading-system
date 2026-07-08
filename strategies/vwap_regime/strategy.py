"""
VWAP Regime Strategy
====================
Regime-switching intraday ES logic:

- **Trend days:** VWAP pullback entries in the session-bias direction.
- **Range days:** VWAP deviation fade with rejection confirmation.

Reuses session VWAP/OR indicators. See docs/strategy_research.md.
"""

from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd

from strategies.base import Strategy
from strategies.bollinger.filters import apply_maintenance_filter, apply_rth_filter
from strategies.bollinger.indicators import calculate_adx, calculate_atr
from strategies.session.indicators import (
    calculate_opening_range,
    calculate_session_vwap,
    calculate_vwap_bands,
)
from strategies.vwap_regime.parameters import get_param_value


class VwapRegimeStrategy(Strategy):
    """RTH VWAP pullback (trend) + deviation fade (range) with regime gate."""

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
        self.min_or_width_pts = float(get_param_value(p, "Min OR Width (pts)", 4.0))
        self.max_or_width_pts = float(get_param_value(p, "Max OR Width (pts)", 40.0))
        self.trade_start_minutes = int(get_param_value(p, "Trade Start After OR (min)", 15))
        self.trade_end_minutes = int(get_param_value(p, "Trade End Before RTH Close (min)", 30))
        self.max_entries_per_day = max(1, int(get_param_value(p, "Max Entries Per Day", 3)))

        self.atr_length = int(get_param_value(p, "ATR Length", 14))
        self.adx_period = int(get_param_value(p, "ADX Period", 14))
        self.enable_adx_filter = self._as_bool(get_param_value(p, "Enable ADX Filter", True), True)
        self.min_trend_adx = float(get_param_value(p, "Min Trend ADX", 20.0))
        self.max_range_adx = float(get_param_value(p, "Max Range ADX", 22.0))
        self.min_atr_pts = float(get_param_value(p, "Min ATR (pts)", 1.0))
        self.max_atr_pts = float(get_param_value(p, "Max ATR (pts)", 25.0))

        self.trend_side_pct = float(get_param_value(p, "Trend Side Pct", 0.62))
        self.min_vwap_crosses = max(1, int(get_param_value(p, "Min VWAP Crosses", 2)))
        self.pullback_touch_pts = float(get_param_value(p, "Pullback Touch Buffer (pts)", 1.0))
        self.pullback_confirm_bars = max(1, int(get_param_value(p, "Pullback Confirm Bars", 1)))
        self.min_extension_pts = float(get_param_value(p, "Min VWAP Extension (pts)", 8.0))
        self.fade_band_atr_mult = float(get_param_value(p, "Fade Band ATR Multiplier", 1.75))
        self.fade_confirm_bars = max(1, int(get_param_value(p, "Fade Confirm Bars", 2)))

        self.stop_atr_mult = float(get_param_value(p, "Stop ATR Multiplier", 1.25))
        self.trend_target_rr = float(get_param_value(p, "Trend Target R Multiple", 1.5))
        self.tp_vwap_buffer_pts = float(get_param_value(p, "TP VWAP Buffer (pts)", 1.0))
        self.max_hold_bars = int(get_param_value(p, "Max Hold (bars)", 36))
        self.enable_trailing = self._as_bool(get_param_value(p, "Enable Trailing Stop", False), False)
        self.trailing_delay = int(get_param_value(p, "Trailing Delay (bars)", 3))
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
        return max(
            self.atr_length,
            self.adx_period,
            or_bars,
            self.fade_confirm_bars,
            self.pullback_confirm_bars,
        ) + 25

    def get_param_structure(self) -> dict:
        return {
            "Regime": {
                "Min Trend ADX": self.min_trend_adx,
                "Max Range ADX": self.max_range_adx,
                "Trend Side Pct": self.trend_side_pct,
                "Min VWAP Crosses": self.min_vwap_crosses,
            },
            "Trend Pullback": {
                "Pullback Touch Buffer (pts)": self.pullback_touch_pts,
                "Pullback Confirm Bars": self.pullback_confirm_bars,
                "Trend Target R Multiple": self.trend_target_rr,
            },
            "Range Fade": {
                "Min VWAP Extension (pts)": self.min_extension_pts,
                "Fade Band ATR Multiplier": self.fade_band_atr_mult,
                "Fade Confirm Bars": self.fade_confirm_bars,
            },
            "Session": {
                "Opening Range (minutes)": self.opening_range_minutes,
                "Max Entries Per Day": self.max_entries_per_day,
                "RTH Start": self.rth_start_str,
                "RTH End": self.rth_end_str,
            },
        }

    def update_optimizable_params(self, params):
        mapping = {
            "Timeframe (minutes)": ("timeframe", int),
            "Opening Range (minutes)": ("opening_range_minutes", int),
            "Min OR Width (pts)": ("min_or_width_pts", float),
            "Max OR Width (pts)": ("max_or_width_pts", float),
            "Max Entries Per Day": ("max_entries_per_day", int),
            "Min Trend ADX": ("min_trend_adx", float),
            "Max Range ADX": ("max_range_adx", float),
            "Trend Side Pct": ("trend_side_pct", float),
            "Min VWAP Crosses": ("min_vwap_crosses", int),
            "Pullback Touch Buffer (pts)": ("pullback_touch_pts", float),
            "Pullback Confirm Bars": ("pullback_confirm_bars", int),
            "Min VWAP Extension (pts)": ("min_extension_pts", float),
            "Fade Band ATR Multiplier": ("fade_band_atr_mult", float),
            "Fade Confirm Bars": ("fade_confirm_bars", int),
            "Stop ATR Multiplier": ("stop_atr_mult", float),
            "Trend Target R Multiple": ("trend_target_rr", float),
            "TP VWAP Buffer (pts)": ("tp_vwap_buffer_pts", float),
            "Max Hold (bars)": ("max_hold_bars", int),
            "Enable Trailing Stop": ("enable_trailing", self._as_bool),
            "Trailing Delay (bars)": ("trailing_delay", int),
            "ATR Multiplier for Trailing Stop": ("atr_mult_ts", float),
            "ATR Length": ("atr_length", int),
            "Enable ADX Filter": ("enable_adx_filter", self._as_bool),
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

    def _session_regime_features(self, df: pd.DataFrame, in_rth: pd.Series) -> pd.DataFrame:
        """Per-bar trend/range flags and pct time above VWAP since OR."""
        day = pd.Series(df.index.date, index=df.index)
        rth_num = in_rth.groupby(day, sort=False).cumsum()
        or_bars = max(1, int(round(self.opening_range_minutes / max(1, self.timeframe))))
        post_or = in_rth & (rth_num > or_bars)

        above = (df["close"] > df["vwap"]).where(post_or, False).astype(float)
        bar_count = post_or.groupby(day, sort=False).cumsum().replace(0, np.nan)
        pct_above = above.groupby(day, sort=False).cumsum() / bar_count

        sign = np.sign((df["close"] - df["vwap"]).where(post_or))
        cross = (sign != sign.shift(1)) & sign.notna() & sign.shift(1).notna()
        vwap_crosses = cross.groupby(day, sort=False).cumsum().where(post_or, 0)

        df["pct_above_vwap"] = pct_above
        df["vwap_cross_count"] = vwap_crosses.fillna(0)
        df["post_or"] = post_or

        bullish = pct_above >= self.trend_side_pct
        bearish = pct_above <= (1.0 - self.trend_side_pct)

        trend_adx_ok = True
        range_adx_ok = True
        if self.enable_adx_filter and "adx" in df.columns:
            trend_adx_ok = df["adx"] >= self.min_trend_adx
            range_adx_ok = df["adx"] <= self.max_range_adx

        or_ok = True
        if "or_width" in df.columns:
            or_ok = (df["or_width"] >= self.min_or_width_pts) & (
                df["or_width"] <= self.max_or_width_pts
            ) & df["or_width"].notna()

        df["regime_trend"] = post_or & trend_adx_ok & or_ok & (bullish | bearish)
        df["regime_range"] = (
            post_or
            & range_adx_ok
            & or_ok
            & (df["vwap_cross_count"] >= self.min_vwap_crosses)
            & ~df["regime_trend"]
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
            df, df["vwap"], df["atr"], self.fade_band_atr_mult
        )

        or_bars = max(1, int(round(self.opening_range_minutes / max(1, self.timeframe))))
        df["or_high"], df["or_low"], df["or_width"] = calculate_opening_range(
            df, in_rth, or_bars
        )

        bar_mins = df.index.hour * 60 + df.index.minute
        open_mins = self.rth_start.hour * 60 + self.rth_start.minute
        df["mins_from_rth_open"] = (bar_mins - open_mins).where(in_rth, -1)
        rth_close_mins = self.rth_end.hour * 60 + self.rth_end.minute
        df["mins_to_rth_close"] = rth_close_mins - bar_mins

        df = self._session_regime_features(df, in_rth)
        return df

    def _confirm_series(self, base: pd.Series, n: int) -> pd.Series:
        ok = base.fillna(False)
        out = ok.copy()
        for lag in range(1, n):
            out &= ok.shift(lag).fillna(False)
        return out

    def _trend_pullback_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        vwap = df["vwap"]
        touch = self.pullback_touch_pts
        bullish = df["pct_above_vwap"] >= self.trend_side_pct
        bearish = df["pct_above_vwap"] <= (1.0 - self.trend_side_pct)

        long_touch = (df["low"] <= vwap + touch) & (df["close"].shift(1) > vwap.shift(1))
        long_reject = (df["close"] > vwap) & (df["close"] >= df["open"])
        long_sig = df["regime_trend"] & bullish & long_touch & long_reject

        short_touch = (df["high"] >= vwap - touch) & (df["close"].shift(1) < vwap.shift(1))
        short_reject = (df["close"] < vwap) & (df["close"] <= df["open"])
        short_sig = df["regime_trend"] & bearish & short_touch & short_reject

        long_sig = self._confirm_series(long_sig, self.pullback_confirm_bars)
        short_sig = self._confirm_series(short_sig, self.pullback_confirm_bars)
        return long_sig.fillna(False), short_sig.fillna(False)

    def _range_fade_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        dist = df["close"] - df["vwap"]
        revert_up = (dist > dist.shift(1)) & (dist < 0)
        revert_down = (dist < dist.shift(1)) & (dist > 0)
        confirm_up = self._confirm_series(revert_up, self.fade_confirm_bars)
        confirm_down = self._confirm_series(revert_down, self.fade_confirm_bars)

        lookback = self.fade_confirm_bars
        extended_low = (
            (dist.shift(lookback) <= -self.min_extension_pts)
            | (df["low"].shift(lookback) <= df["vwap_lower"].shift(lookback))
        )
        extended_high = (
            (dist.shift(lookback) >= self.min_extension_pts)
            | (df["high"].shift(lookback) >= df["vwap_upper"].shift(lookback))
        )
        room_long = dist <= -max(1.0, self.tp_vwap_buffer_pts)
        room_short = dist >= max(1.0, self.tp_vwap_buffer_pts)

        long_sig = df["regime_range"] & extended_low & confirm_up & room_long
        short_sig = df["regime_range"] & extended_high & confirm_down & room_short
        return long_sig.fillna(False), short_sig.fillna(False)

    def calculate_entry_signals(self, df: pd.DataFrame, verbose=False):
        in_rth = df["in_rth"] if "in_rth" in df.columns else pd.Series(True, index=df.index)
        in_maint = df["in_maintenance"] if "in_maintenance" in df.columns else pd.Series(False, index=df.index)

        long_trend, short_trend = self._trend_pullback_signals(df)
        long_range, short_range = self._range_fade_signals(df)

        long_sig = long_trend | (long_range & ~long_trend & ~short_trend)
        short_sig = short_trend | (short_range & ~short_trend & ~long_trend)

        atr_ok = (df["atr"] >= self.min_atr_pts) & (df["atr"] <= self.max_atr_pts)
        long_sig &= atr_ok
        short_sig &= atr_ok

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

    def _entry_mode(self, row, direction: int) -> str:
        if isinstance(row, pd.Series):
            regime_trend = bool(row.get("regime_trend", False))
            regime_range = bool(row.get("regime_range", False))
            pct = float(row.get("pct_above_vwap", 0.5) or 0.5)
            close = float(row["close"])
            vwap = float(row["vwap"])
            low = float(row["low"])
            high = float(row["high"])
        else:
            regime_trend = bool(getattr(row, "regime_trend", False))
            regime_range = bool(getattr(row, "regime_range", False))
            pct = float(getattr(row, "pct_above_vwap", 0.5) or 0.5)
            close = float(row.close)
            vwap = float(row.vwap)
            low = float(row.low)
            high = float(row.high)

        if regime_trend:
            if direction == 1 and pct >= self.trend_side_pct and low <= vwap + self.pullback_touch_pts:
                return "trend"
            if direction == -1 and pct <= (1.0 - self.trend_side_pct) and high >= vwap - self.pullback_touch_pts:
                return "trend"
        if regime_range:
            return "range"
        return "range" if abs(close - vwap) >= self.min_extension_pts else "trend"

    def setup_position(self, entry_price, direction, row, df=None):
        atr = float(row["atr"]) if "atr" in row and not pd.isna(row["atr"]) else 4.0
        vwap = float(row["vwap"]) if "vwap" in row and not pd.isna(row["vwap"]) else entry_price
        mode = self._entry_mode(row, direction)
        stop_dist = max(2.0, self.stop_atr_mult * atr)

        if mode == "trend":
            if direction == 1:
                stop = min(entry_price - stop_dist, vwap - self.pullback_touch_pts)
                if stop >= entry_price - 1.0:
                    stop = entry_price - stop_dist
                risk = entry_price - stop
                tp = entry_price + max(4.0, self.trend_target_rr * risk)
            else:
                stop = max(entry_price + stop_dist, vwap + self.pullback_touch_pts)
                if stop <= entry_price + 1.0:
                    stop = entry_price + stop_dist
                risk = stop - entry_price
                tp = entry_price - max(4.0, self.trend_target_rr * risk)
        else:
            if direction == 1:
                stop = entry_price - stop_dist
                tp = vwap - self.tp_vwap_buffer_pts
                if tp <= entry_price + 2.0:
                    tp = entry_price + max(2.0, 0.35 * stop_dist)
            else:
                stop = entry_price + stop_dist
                tp = vwap + self.tp_vwap_buffer_pts
                if tp >= entry_price - 2.0:
                    tp = entry_price - max(2.0, 0.35 * stop_dist)

        return {
            "entry_time": row.Index if not isinstance(row, pd.Series) else row.name,
            "entry_price": entry_price,
            "direction": direction,
            "stop": stop,
            "tp": tp,
            "entry_mode": mode,
            "target_vwap": vwap,
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
        mode = position.get("entry_mode", "range")

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

        if mode == "range":
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

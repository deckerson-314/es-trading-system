"""
Multi-zone Support/Resistance Breakout (v1)
===========================================
Track up to 3 support + 3 resistance zones from causal swing pivots.
Zones have ATR-width bands, volume-seeded strength, survived-test boosts,
per-bar linear strength dissipation, and S↔R flip on close-through.

Strength lifecycle (each bar, in order):
  1. Dissipate existing zones: strength = max(0, strength - dissipation)
  2. Evict dead zones (strength ≈ 0)
  3. Survived-test boosts (reinforcement on this bar is not wiped by step 1)
  4. Flip / breakout entries on close-through
  5. Form new pivot zones (new zones start undissipated on their birth bar)

Example: strength=10, dissipation=1 → fades to 0 over 10 bars unless reinforced.

Entry: close beyond a strong zone with volume confirmation, plus optional
overlap-aware Entry Headroom (ATR) clearance to the next strong opposite zone
(0 = filter off). New entries also blocked within Maintenance Entry Buffer
minutes of RTH/maintenance force-flat clocks.
Exits: origin-zone stop → optional MFE→breakeven (separate from classic ATR
trail) → opposite strong zone (only if ≥ Min Opposite Zone Dist ATR from entry)
→ max hold / RTH / maintenance.

Chart zone snapshots (zone_s*/zone_r*) are taken at **decision time** — after
dissipation + tests, before flip — so overlays show the strength that gated
breakout entry (gold = ≥ threshold). Flipped geometry appears on the next bar.

No ADX / EMA / RSI. Clean gene space for diagnostic GA.
"""

from __future__ import annotations

from datetime import time
from typing import Any

import numpy as np
import pandas as pd

from strategies.base import Strategy
from strategies.bollinger.filters import apply_maintenance_filter, apply_rth_filter
from strategies.bollinger.indicators import calculate_atr
from strategies.sr_zones.parameters import get_param_value

# Fixed (not genes)
_ATR_LENGTH = 14
_VOL_MA_LENGTH = 20
_CAPACITY = 3
_TEST_BOOST = 2.0
_FLIP_STRENGTH_FRAC = 0.5

# Per-bar chart export: zone_s{i}_{lo,hi,str} / zone_r{i}_{lo,hi,str}
ZONE_EXPORT_SLOTS = _CAPACITY


def zone_geometry_column_names(capacity: int = ZONE_EXPORT_SLOTS) -> list[str]:
    """Column names written by calculate_indicators for candle-by-candle S/R overlays."""
    cols: list[str] = []
    for side in ("s", "r"):
        for i in range(capacity):
            cols.extend([f"zone_{side}{i}_lo", f"zone_{side}{i}_hi", f"zone_{side}{i}_str"])
    return cols


class SrZonesStrategy(Strategy):
    """Multi-zone S/R breakout with strength lifecycle."""

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

        self.zone_width_k = float(get_param_value(p, "Zone Width ATR Mult", 0.35))
        self.strength_threshold = float(get_param_value(p, "Strength Threshold", 2.0))
        self.vol_mult = float(get_param_value(p, "Volume Mult", 1.25))
        # Prefer new name; fall back if an old checkpoint still carries "Decay Rate".
        _diss = get_param_value(p, "Dissipation (per bar)", None)
        if _diss is None:
            _diss = get_param_value(p, "Decay Rate", 0.25)
        self.dissipation = float(_diss)
        self.stop_pad_atr = float(get_param_value(p, "Stop Pad ATR", 0.15))
        self.max_hold_bars = max(1, int(get_param_value(p, "Max Hold (bars)", 24)))
        # Opposite-zone TP must clear this much room from entry (ATR units).
        # Locked default 0.5 — blocks micro swing zones born right after entry.
        self.min_opp_zone_dist_atr = float(
            get_param_value(p, "Min Opposite Zone Dist (ATR)", 0.5)
        )
        # Overlap-aware clearance to next strong opposite zone at entry.
        # 0 = filter off (no headroom requirement).
        self.entry_headroom_atr = float(
            get_param_value(p, "Entry Headroom (ATR)", 0.5)
        )

        self.atr_length = _ATR_LENGTH
        self.enable_stop = True
        self.stop_atr_mult = 1.0  # unused; stop from zone edge
        self.enable_tp = False
        self.tp_atr_mult = 2.0
        self.enable_trailing = False
        self.trailing_delay = 1
        self.atr_mult_ts = 2.0
        # Separate from classic ATR trailing: MFE→breakeven (GA-discoverable).
        self.enable_breakeven = self._as_bool(
            get_param_value(p, "Enable Breakeven Stop", False), False
        )
        self.breakeven_trigger_atr = float(get_param_value(p, "Breakeven Trigger (ATR)", 0.5))
        self.breakeven_pad_atr = float(get_param_value(p, "Breakeven Pad (ATR)", 0.0))

        self.enable_rth_filter = self._as_bool(get_param_value(p, "Enable RTH Filter", True), True)
        self.rth_start_str = get_param_value(p, "RTH Start (HH:MM)", "09:30")
        self.rth_end_str = get_param_value(p, "RTH End (HH:MM)", "16:00")
        self.rth_exit_buffer_minutes = int(get_param_value(p, "RTH Exit Buffer (minutes)", 5))
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
        self.maintenance_buffer_minutes = int(get_param_value(p, "Maintenance Buffer Minutes", 22))
        # Block new entries N minutes before maint/RTH force-flat clocks.
        self.maintenance_entry_buffer_minutes = int(
            get_param_value(p, "Maintenance Entry Buffer (minutes)", 90)
        )

        self.rth_start = self._parse_time(self.rth_start_str)
        self.rth_end = self._parse_time(self.rth_end_str)
        self._clamp_params()

    def _clamp_params(self):
        self.timeframe = max(1, int(self.timeframe))
        self.zone_width_k = float(max(0.05, min(2.0, self.zone_width_k)))
        self.strength_threshold = float(max(0.1, self.strength_threshold))
        self.vol_mult = float(max(0.5, self.vol_mult))
        self.dissipation = float(max(0.0, min(2.0, self.dissipation)))
        self.stop_pad_atr = float(max(0.0, self.stop_pad_atr))
        self.max_hold_bars = max(1, int(self.max_hold_bars))
        self.min_opp_zone_dist_atr = float(max(0.0, min(3.0, self.min_opp_zone_dist_atr)))
        self.entry_headroom_atr = float(max(0.0, min(2.5, self.entry_headroom_atr)))
        self.maintenance_buffer_minutes = max(0, int(self.maintenance_buffer_minutes))
        self.maintenance_entry_buffer_minutes = max(0, int(self.maintenance_entry_buffer_minutes))
        self.breakeven_trigger_atr = float(max(0.0, min(5.0, self.breakeven_trigger_atr)))
        self.breakeven_pad_atr = float(max(0.0, min(1.0, self.breakeven_pad_atr)))

    @property
    def min_bars_required(self) -> int:
        return max(_ATR_LENGTH, _VOL_MA_LENGTH) + 10

    def get_param_structure(self) -> dict:
        return {
            "Entry Criteria": {
                "Timeframe (minutes)": self.timeframe,
                "Zone Width ATR Mult": self.zone_width_k,
                "Strength Threshold": self.strength_threshold,
                "Volume Mult": self.vol_mult,
                "Dissipation (per bar)": self.dissipation,
                "Entry Headroom (ATR)": self.entry_headroom_atr,
                "Maintenance Entry Buffer (minutes)": self.maintenance_entry_buffer_minutes,
            },
            "Exit Criteria": {
                "Stop Pad ATR": self.stop_pad_atr,
                "Max Hold (bars)": self.max_hold_bars,
                "Min Opposite Zone Dist (ATR)": self.min_opp_zone_dist_atr,
                "Enable Stop Loss": self.enable_stop,
                "Enable Breakeven Stop": self.enable_breakeven,
                "Breakeven Trigger (ATR)": self.breakeven_trigger_atr,
                "Maintenance Buffer Minutes": self.maintenance_buffer_minutes,
            },
        }

    def update_optimizable_params(self, params):
        mapping = {
            "Timeframe (minutes)": ("timeframe", int),
            "Zone Width ATR Mult": ("zone_width_k", float),
            "Strength Threshold": ("strength_threshold", float),
            "Volume Mult": ("vol_mult", float),
            "Dissipation (per bar)": ("dissipation", float),
            "Entry Headroom (ATR)": ("entry_headroom_atr", float),
            "Stop Pad ATR": ("stop_pad_atr", float),
            "Max Hold (bars)": ("max_hold_bars", int),
            "Min Opposite Zone Dist (ATR)": ("min_opp_zone_dist_atr", float),
            "Enable Long Trades": ("enable_long", self._as_bool),
            "Enable Short Trades": ("enable_short", self._as_bool),
            "Maintenance Buffer Minutes": ("maintenance_buffer_minutes", int),
            "Maintenance Entry Buffer (minutes)": ("maintenance_entry_buffer_minutes", int),
            "Enable Breakeven Stop": ("enable_breakeven", self._as_bool),
            "Breakeven Trigger (ATR)": ("breakeven_trigger_atr", float),
            "Breakeven Pad (ATR)": ("breakeven_pad_atr", float),
        }
        for key, (attr, caster) in mapping.items():
            if key not in params:
                continue
            val = params[key]
            if caster is self._as_bool:
                setattr(self, attr, caster(val))
            else:
                setattr(self, attr, caster(val))
        self.enable_stop = True
        self.enable_tp = False
        self.enable_trailing = False
        self._clamp_params()

    @staticmethod
    def _time_to_minutes(t: time) -> int:
        return int(t.hour) * 60 + int(t.minute)

    def _pre_force_window_mask(self, tod_mins: np.ndarray, force_clock: time, buffer_mins: int) -> np.ndarray:
        """True on bars in [force_clock - buffer, force_clock) by clock minutes."""
        if buffer_mins <= 0:
            return np.zeros(len(tod_mins), dtype=bool)
        end_m = self._time_to_minutes(force_clock)
        start_m = end_m - int(buffer_mins)
        if start_m >= 0:
            return (tod_mins >= start_m) & (tod_mins < end_m)
        # Window crosses midnight (unlikely for RTH/maint; handle anyway)
        start_m = (start_m % 1440 + 1440) % 1440
        return (tod_mins >= start_m) | (tod_mins < end_m)

    def _entry_blocked_by_force_clocks(self, df: pd.DataFrame) -> pd.Series:
        """Block new entries within Maintenance Entry Buffer of force-flat clocks.

        Clocks match exit buffers: RTH end, daily maintenance start, weekend
        maintenance start (Friday). Does not replace ``force_exit`` /
        ``force_exit_rth``; those remain exit triggers with their own buffers.
        """
        n = int(self.maintenance_entry_buffer_minutes)
        if n <= 0 or len(df) == 0:
            return pd.Series(False, index=df.index)

        tod_mins = (df.index.hour.to_numpy() * 60 + df.index.minute.to_numpy()).astype(int)
        blocked = np.zeros(len(df), dtype=bool)

        if self.enable_rth_filter:
            blocked |= self._pre_force_window_mask(tod_mins, self.rth_end, n)

        if self.enable_maintenance_filter:
            daily_start = self._parse_time(self.daily_maintenance_start_str)
            blocked |= self._pre_force_window_mask(tod_mins, daily_start, n)

            weekend_start = self._parse_time(self.weekend_maintenance_start_time_str)
            is_start_day = df.index.dayofweek.to_numpy() == int(self.weekend_maintenance_start_day)
            blocked |= is_start_day & self._pre_force_window_mask(tod_mins, weekend_start, n)

        return pd.Series(blocked, index=df.index)

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
        df = df.copy()
        df["entry_blocked_force"] = self._entry_blocked_by_force_clocks(df)
        return df

    # ------------------------------------------------------------------
    # Zone helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _new_zone(mid: float, half: float, strength: float, born_ts, side: str) -> dict[str, Any]:
        return {
            "mid": float(mid),
            "lo": float(mid - half),
            "hi": float(mid + half),
            "strength": float(strength),
            "born_ts": born_ts,
            "side": side,
        }

    @staticmethod
    def _overlaps(zones: list, mid: float, half: float) -> bool:
        lo, hi = mid - half, mid + half
        for z in zones:
            if not (hi < z["lo"] or lo > z["hi"]):
                return True
        return False

    def _evict(self, zones: list) -> list:
        if len(zones) <= _CAPACITY:
            return zones
        # Weakest first; oldest (earlier born_ts) on tie
        ranked = sorted(zones, key=lambda z: (z["strength"], z["born_ts"]))
        return ranked[-_CAPACITY:]

    def _dissipate_all(self, supports: list, resistances: list) -> None:
        """Subtract per-bar dissipation from every live zone (floor at 0)."""
        d = float(self.dissipation)
        if d <= 0:
            return
        for z in supports + resistances:
            z["strength"] = max(0.0, float(z["strength"]) - d)

    @staticmethod
    def _remove_dead(zones: list) -> list:
        return [z for z in zones if z["strength"] > 1e-6]

    def _nearest_strong_above(self, zones: list, price: float) -> tuple[float, float]:
        thr = self.strength_threshold
        cands = [z for z in zones if z["strength"] >= thr and z["lo"] >= price - 1e-9]
        if not cands:
            return np.nan, np.nan
        z = min(cands, key=lambda x: x["lo"])
        return z["lo"], z["hi"]

    def _nearest_strong_below(self, zones: list, price: float) -> tuple[float, float]:
        thr = self.strength_threshold
        cands = [z for z in zones if z["strength"] >= thr and z["hi"] <= price + 1e-9]
        if not cands:
            return np.nan, np.nan
        z = max(cands, key=lambda x: x["hi"])
        return z["lo"], z["hi"]

    @staticmethod
    def _same_band(a: dict, b: dict, tol: float = 1e-9) -> bool:
        return abs(float(a["lo"]) - float(b["lo"])) <= tol and abs(float(a["hi"]) - float(b["hi"])) <= tol

    def _headroom_blocked_long(
        self,
        close: float,
        atr: float,
        resistances: list,
        origin: dict | None,
        thr: float,
    ) -> bool:
        """True if a strong resistance still blocks overhead within headroom×ATR.

        Overlap-aware: gap = max(0, zone.lo - close). Zones with hi < close are
        already cleared (including the broken origin). headroom<=0 disables.
        """
        hr = float(self.entry_headroom_atr)
        if hr <= 0 or not np.isfinite(atr) or atr <= 0 or not np.isfinite(close):
            return False
        need = hr * float(atr)
        for z in resistances:
            if float(z["strength"]) < thr:
                continue
            if origin is not None and self._same_band(z, origin):
                continue
            if float(z["hi"]) < close:
                continue
            gap = max(0.0, float(z["lo"]) - close)
            if gap < need:
                return True
        return False

    def _headroom_blocked_short(
        self,
        close: float,
        atr: float,
        supports: list,
        origin: dict | None,
        thr: float,
    ) -> bool:
        """Symmetric underfoot check vs strong supports (headroom<=0 disables)."""
        hr = float(self.entry_headroom_atr)
        if hr <= 0 or not np.isfinite(atr) or atr <= 0 or not np.isfinite(close):
            return False
        need = hr * float(atr)
        for z in supports:
            if float(z["strength"]) < thr:
                continue
            if origin is not None and self._same_band(z, origin):
                continue
            if float(z["lo"]) > close:
                continue
            gap = max(0.0, close - float(z["hi"]))
            if gap < need:
                return True
        return False

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        if "in_rth" not in df.columns:
            df = self.apply_filters(df)

        in_rth = df["in_rth"].fillna(False).astype(bool)
        h = df["high"].astype(float).to_numpy()
        lo = df["low"].astype(float).to_numpy()
        c = df["close"].astype(float).to_numpy()
        if "volume" in df.columns:
            vol = df["volume"].astype(float).to_numpy()
        elif "Volume" in df.columns:
            vol = df["Volume"].astype(float).to_numpy()
        else:
            vol = np.ones(len(df), dtype=float)

        df["atr"] = calculate_atr(df, self.atr_length)
        atr = df["atr"].astype(float).to_numpy()
        vol_ma = (
            pd.Series(vol, index=df.index)
            .rolling(_VOL_MA_LENGTH, min_periods=max(5, _VOL_MA_LENGTH // 2))
            .mean()
            .to_numpy()
        )

        n = len(df)
        entry_long = np.zeros(n, dtype=bool)
        entry_short = np.zeros(n, dtype=bool)
        brk_lo = np.full(n, np.nan)
        brk_hi = np.full(n, np.nan)
        brk_str = np.full(n, np.nan)
        opp_long_lo = np.full(n, np.nan)
        opp_long_hi = np.full(n, np.nan)
        opp_short_lo = np.full(n, np.nan)
        opp_short_hi = np.full(n, np.nan)
        hit_strong_res = np.zeros(n, dtype=bool)
        hit_strong_sup = np.zeros(n, dtype=bool)
        # Farthest opposite-zone edge touched this bar (for min-dist exit gate).
        hit_res_lo = np.full(n, np.nan)
        hit_sup_hi = np.full(n, np.nan)
        n_sup = np.zeros(n, dtype=int)
        n_res = np.zeros(n, dtype=int)
        n_flips = np.zeros(n, dtype=int)
        n_tests = np.zeros(n, dtype=int)

        # Candle-by-candle zone geometry for trade charts (cheap vs zone loop).
        zone_bufs: dict[str, np.ndarray] = {
            name: np.full(n, np.nan) for name in zone_geometry_column_names(ZONE_EXPORT_SLOTS)
        }

        supports: list[dict] = []
        resistances: list[dict] = []
        index = df.index
        k = float(self.zone_width_k)
        thr = float(self.strength_threshold)
        vmult = float(self.vol_mult)

        for i in range(n):
            # Age existing zones at bar open, then tests may reinforce.
            self._dissipate_all(supports, resistances)
            supports = self._remove_dead(supports)
            resistances = self._remove_dead(resistances)

            atr_i = atr[i]
            half = k * atr_i if np.isfinite(atr_i) and atr_i > 0 else np.nan
            vma = vol_ma[i]
            vol_ok = np.isfinite(vma) and vma > 0 and vol[i] >= vmult * vma
            strength_seed = (vol[i] / vma) if (np.isfinite(vma) and vma > 0) else 1.0

            # --- Survived tests (wick into zone, close defensive) ---
            # Do this before breakout so a same-bar close-through is not also a test.
            if np.isfinite(half):
                for z in resistances:
                    wick_in = lo[i] <= z["hi"] and h[i] >= z["lo"]
                    closed_defensive = c[i] < z["lo"]
                    broke_through = c[i] > z["hi"]
                    if wick_in and closed_defensive and not broke_through:
                        boost = _TEST_BOOST * (1.0 + (vol[i] / vma if np.isfinite(vma) and vma > 0 else 0.0))
                        z["strength"] += boost
                        n_tests[i] += 1
                for z in supports:
                    wick_in = lo[i] <= z["hi"] and h[i] >= z["lo"]
                    closed_defensive = c[i] > z["hi"]
                    broke_through = c[i] < z["lo"]
                    if wick_in and closed_defensive and not broke_through:
                        boost = _TEST_BOOST * (1.0 + (vol[i] / vma if np.isfinite(vma) and vma > 0 else 0.0))
                        z["strength"] += boost
                        n_tests[i] += 1

            # Pre-flip: reach of a strong zone from the approach side
            # (long TP = resistance from below; short TP = support from above).
            # Record farthest touched edge so check_exit can require min room
            # from entry (skip micro zones formed just above/below entry).
            if i > 0:
                prev_c = c[i - 1]
                touched_res_lo = [
                    z["lo"]
                    for z in resistances
                    if z["strength"] >= thr and prev_c < z["lo"] and c[i] >= z["lo"]
                ]
                if touched_res_lo:
                    hit_strong_res[i] = True
                    hit_res_lo[i] = max(touched_res_lo)
                touched_sup_hi = [
                    z["hi"]
                    for z in supports
                    if z["strength"] >= thr and prev_c > z["hi"] and c[i] <= z["hi"]
                ]
                if touched_sup_hi:
                    hit_strong_sup[i] = True
                    hit_sup_hi[i] = min(touched_sup_hi)

            # --- Close-through: flip + optional breakout entry ---
            flip_to_sup: list[dict] = []
            flip_to_res: list[dict] = []
            keep_res: list[dict] = []
            keep_sup: list[dict] = []

            long_signal = False
            short_signal = False
            origin_lo = np.nan
            origin_hi = np.nan
            origin_str = np.nan

            # Decision-time geometry for charts: strength that gates breakout
            # (post-dissipation/tests, pre-flip). Flip would otherwise paint the
            # broken band as the opposite side at 50% strength on the entry bar.
            snap_sup = [dict(z) for z in supports]
            snap_res = [dict(z) for z in resistances]

            for z in resistances:
                if c[i] > z["hi"]:
                    # Break above resistance
                    if (
                        bool(in_rth.iloc[i])
                        and z["strength"] >= thr
                        and vol_ok
                        and not long_signal
                        and not short_signal
                        and not self._headroom_blocked_long(
                            float(c[i]), atr_i, resistances, origin=z, thr=thr
                        )
                    ):
                        long_signal = True
                        origin_lo, origin_hi = z["lo"], z["hi"]
                        origin_str = float(z["strength"])
                    z_flip = dict(z)
                    z_flip["side"] = "S"
                    z_flip["strength"] = max(1e-6, z["strength"] * _FLIP_STRENGTH_FRAC)
                    flip_to_sup.append(z_flip)
                    n_flips[i] += 1
                else:
                    keep_res.append(z)

            for z in supports:
                if c[i] < z["lo"]:
                    if (
                        bool(in_rth.iloc[i])
                        and z["strength"] >= thr
                        and vol_ok
                        and not long_signal
                        and not short_signal
                        and not self._headroom_blocked_short(
                            float(c[i]), atr_i, supports, origin=z, thr=thr
                        )
                    ):
                        short_signal = True
                        origin_lo, origin_hi = z["lo"], z["hi"]
                        origin_str = float(z["strength"])
                    z_flip = dict(z)
                    z_flip["side"] = "R"
                    z_flip["strength"] = max(1e-6, z["strength"] * _FLIP_STRENGTH_FRAC)
                    flip_to_res.append(z_flip)
                    n_flips[i] += 1
                else:
                    keep_sup.append(z)

            supports = keep_sup + flip_to_sup
            resistances = keep_res + flip_to_res

            if long_signal:
                entry_long[i] = True
                brk_lo[i] = origin_lo
                brk_hi[i] = origin_hi
                brk_str[i] = origin_str
            elif short_signal:
                entry_short[i] = True
                brk_lo[i] = origin_lo
                brk_hi[i] = origin_hi
                brk_str[i] = origin_str

            # --- Form new zones from confirmed pivots (prior bar) ---
            if i >= 2 and np.isfinite(half) and bool(in_rth.iloc[i]):
                # Swing high at i-1
                if h[i - 1] > h[i - 2] and h[i - 1] > h[i]:
                    mid = float(h[i - 1])
                    if not self._overlaps(resistances, mid, half):
                        seed = float(vol[i - 1] / vma if np.isfinite(vma) and vma > 0 else strength_seed)
                        resistances.append(
                            self._new_zone(mid, half, max(seed, 0.1), index[i - 1], "R")
                        )
                # Swing low at i-1
                if lo[i - 1] < lo[i - 2] and lo[i - 1] < lo[i]:
                    mid = float(lo[i - 1])
                    if not self._overlaps(supports, mid, half):
                        seed = float(vol[i - 1] / vma if np.isfinite(vma) and vma > 0 else strength_seed)
                        supports.append(
                            self._new_zone(mid, half, max(seed, 0.1), index[i - 1], "S")
                        )

            supports = self._evict(self._remove_dead(supports))
            resistances = self._evict(self._remove_dead(resistances))

            # Live counts / opposite-zone exits use post-flip state.
            n_sup[i] = len(supports)
            n_res[i] = len(resistances)
            price = c[i]
            opp_long_lo[i], opp_long_hi[i] = self._nearest_strong_above(resistances, price)
            opp_short_lo[i], opp_short_hi[i] = self._nearest_strong_below(supports, price)

            # Chart snapshot = decision-time bands (pre-flip strength/side).
            for side_key, zones in (("s", snap_sup), ("r", snap_res)):
                ranked = sorted(zones, key=lambda z: z["mid"])
                for slot in range(ZONE_EXPORT_SLOTS):
                    if slot >= len(ranked):
                        break
                    z = ranked[slot]
                    zone_bufs[f"zone_{side_key}{slot}_lo"][i] = z["lo"]
                    zone_bufs[f"zone_{side_key}{slot}_hi"][i] = z["hi"]
                    zone_bufs[f"zone_{side_key}{slot}_str"][i] = z["strength"]

        df["entry_long_sr"] = entry_long
        df["entry_short_sr"] = entry_short
        df["breakout_zone_lo"] = brk_lo
        df["breakout_zone_hi"] = brk_hi
        df["breakout_zone_str"] = brk_str
        df["opp_long_lo"] = opp_long_lo
        df["opp_long_hi"] = opp_long_hi
        df["opp_short_lo"] = opp_short_lo
        df["opp_short_hi"] = opp_short_hi
        df["hit_strong_res"] = hit_strong_res
        df["hit_strong_sup"] = hit_strong_sup
        df["hit_res_lo"] = hit_res_lo
        df["hit_sup_hi"] = hit_sup_hi
        df["n_support"] = n_sup
        df["n_resistance"] = n_res
        df["n_flips"] = n_flips
        df["n_tests"] = n_tests
        df["vol_ma"] = vol_ma
        df["strength_threshold"] = thr
        for col_name, arr in zone_bufs.items():
            df[col_name] = arr
        return df

    def calculate_entry_signals(self, df: pd.DataFrame, verbose=False):
        in_rth = df["in_rth"] if "in_rth" in df.columns else pd.Series(True, index=df.index)
        in_maint = (
            df["in_maintenance"] if "in_maintenance" in df.columns else pd.Series(False, index=df.index)
        )
        gate = in_rth & ~in_maint
        # Time-budget: no new entries near maint/RTH force-flat (entry buffer gene).
        if "entry_blocked_force" in df.columns:
            gate = gate & ~df["entry_blocked_force"].fillna(False)
        # Also respect exit force windows (covers entry_buffer < exit_buffer).
        if "force_exit" in df.columns:
            gate = gate & ~df["force_exit"].fillna(False).astype(bool)
        if "force_exit_rth" in df.columns:
            gate = gate & ~df["force_exit_rth"].fillna(False).astype(bool)
        long_raw = gate & df["entry_long_sr"].fillna(False)
        short_raw = gate & df["entry_short_sr"].fillna(False)

        if not self.enable_long:
            long_raw = pd.Series(False, index=df.index)
        if not self.enable_short:
            short_raw = pd.Series(False, index=df.index)

        conflict = long_raw & short_raw
        long_raw = long_raw & ~conflict
        short_raw = short_raw & ~conflict
        return long_raw.fillna(False), short_raw.fillna(False)

    @staticmethod
    def _row_field(row, key, default=np.nan):
        if isinstance(row, pd.Series):
            val = row[key] if key in row.index else default
        else:
            val = getattr(row, key, default)
        try:
            if val is None or pd.isna(val):
                return default
        except (TypeError, ValueError):
            pass
        return val

    def setup_position(self, entry_price, direction, row, df=None):
        atr_raw = self._row_field(row, "atr")
        atr = float(atr_raw) if not pd.isna(atr_raw) else 4.0
        pad = max(0.0, self.stop_pad_atr * atr)

        z_lo = self._row_field(row, "breakout_zone_lo")
        z_hi = self._row_field(row, "breakout_zone_hi")
        if pd.isna(z_lo) or pd.isna(z_hi):
            # Fallback: ATR stop from entry
            stop = entry_price - (1.0 * atr + pad) if direction == 1 else entry_price + (1.0 * atr + pad)
            origin_lo, origin_hi = entry_price - atr, entry_price + atr
        else:
            origin_lo, origin_hi = float(z_lo), float(z_hi)
            if direction == 1:
                # Long broke resistance → stop below origin zone
                stop = origin_lo - pad
            else:
                # Short broke support → stop above origin zone
                stop = origin_hi + pad

        # Decorative TP; opposite-zone exit is signal-based
        tp = entry_price + 500.0 if direction == 1 else entry_price - 500.0

        return {
            "entry_time": row.Index if not isinstance(row, pd.Series) else row.name,
            "entry_price": entry_price,
            "direction": direction,
            "stop": stop,
            "tp": tp,
            "origin_zone_lo": origin_lo,
            "origin_zone_hi": origin_hi,
            "entry_atr": atr,
            "bars_held": 0,
            "highest_high": entry_price if direction == 1 else -1,
            "lowest_low": entry_price if direction == -1 else 999999,
            "breakeven_armed": False,
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
        bars_held = int(position.get("bars_held", 0) or 0)

        # 1) Origin-zone stop
        if self.enable_stop:
            if dir_ == 1 and low <= stop_price:
                return True, "Stop Loss", stop_price
            if dir_ == -1 and high >= stop_price:
                return True, "Stop Loss", stop_price

        # 2) Opposite strong zone (pre-flip touch). Skip entry bar — breakout
        # itself touches the origin zone and would false-trigger.
        # Require target zone ≥ Min Opposite Zone Dist (ATR) from entry so a
        # post-entry micro swing (tiny dip → new R just above entry) cannot
        # clip the trade with almost no room.
        if bars_held >= 1:
            entry = float(position.get("entry_price", np.nan))
            atr_raw = self._row_field(row, "atr")
            atr = float(atr_raw) if not pd.isna(atr_raw) else np.nan
            min_dist = (
                float(self.min_opp_zone_dist_atr) * atr
                if np.isfinite(atr) and atr > 0
                else 0.0
            )
            if dir_ == 1 and bool(self._row_field(row, "hit_strong_res", False)):
                z_lo = self._row_field(row, "hit_res_lo")
                if not np.isfinite(z_lo):
                    z_lo = self._row_field(row, "opp_long_lo")
                if np.isfinite(entry) and np.isfinite(z_lo) and float(z_lo) >= entry + min_dist:
                    return True, "Opposite Zone Exit", close
            if dir_ == -1 and bool(self._row_field(row, "hit_strong_sup", False)):
                z_hi = self._row_field(row, "hit_sup_hi")
                if not np.isfinite(z_hi):
                    z_hi = self._row_field(row, "opp_short_hi")
                if np.isfinite(entry) and np.isfinite(z_hi) and float(z_hi) <= entry - min_dist:
                    return True, "Opposite Zone Exit", close

        # 3) Max hold
        if bars_held >= self.max_hold_bars > 0:
            return True, "Time Exit", close

        return False, None, None

    def update_trailing_stop(self, position, row, df):
        """Advance bars_held; optionally arm MFE→breakeven (not classic ATR trail)."""
        bars_held = int(position.get("bars_held", 0) or 0)
        first_bar = bars_held == 0
        position["bars_held"] = 1 if first_bar else bars_held + 1

        # Classic ATR trailing stays off for this strategy (GA gene locked 0).
        # Entry bar: no MFE ratchet (OHLC ordering ambiguity vs fill).
        if first_bar or not self.enable_breakeven:
            return False
        if position.get("breakeven_armed"):
            return False

        high = row.high if not isinstance(row, pd.Series) else row["high"]
        low = row.low if not isinstance(row, pd.Series) else row["low"]
        dir_ = int(position.get("direction", 0) or 0)
        entry = float(position.get("entry_price", np.nan))
        if not np.isfinite(entry) or dir_ not in (1, -1):
            return False

        atr_pos = position.get("entry_atr")
        try:
            atr = float(atr_pos) if atr_pos is not None and not pd.isna(atr_pos) else np.nan
        except (TypeError, ValueError):
            atr = np.nan
        if not np.isfinite(atr) or atr <= 0:
            atr_raw = self._row_field(row, "atr")
            atr = float(atr_raw) if not pd.isna(atr_raw) else np.nan
        if not np.isfinite(atr) or atr <= 0:
            return False

        trigger = float(self.breakeven_trigger_atr) * atr
        pad = float(self.breakeven_pad_atr) * atr
        stop_before = position.get("stop")

        if dir_ == 1:
            position["highest_high"] = max(float(position.get("highest_high", high)), float(high))
            mfe = float(position["highest_high"]) - entry
            if mfe < trigger:
                return False
            new_stop = entry + pad
            if new_stop > float(position.get("stop", new_stop - 1.0)):
                position["stop"] = new_stop
                position["breakeven_armed"] = True
        else:
            ll = float(position.get("lowest_low", low))
            position["lowest_low"] = float(low) if ll > 1e6 else min(ll, float(low))
            mfe = entry - float(position["lowest_low"])
            if mfe < trigger:
                return False
            new_stop = entry - pad
            if new_stop < float(position.get("stop", new_stop + 1.0)):
                position["stop"] = new_stop
                position["breakeven_armed"] = True

        return bool(position.get("stop") != stop_before)

    def generate_trade_report(self, trade: dict, df: pd.DataFrame, output_dir: str) -> str:
        try:
            from tools.reporting.unified_trade_report import generate_unified_trade_report

            return generate_unified_trade_report(
                trade,
                df,
                output_dir,
                version=self.params_dict.get("version", "sr-zones"),
                params_snapshot=trade.get("params_snapshot") if isinstance(trade, dict) else None,
            )
        except Exception as e:
            import logging

            logging.error("generate_trade_report failed: %s", e, exc_info=True)
            return ""

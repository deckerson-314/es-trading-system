"""Donchian channel display rules for live and trade charts."""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

ENTRY_DONCHIAN_COLS = ("donchian_high", "donchian_low")
EXIT_DONCHIAN_COLS = ("donchian_exit_high", "donchian_exit_low")


def _normalize_ts_for_index(ts: Any, index: pd.DatetimeIndex) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if index is None or len(index) == 0:
        return t
    ref = pd.Timestamp(index[0])
    if ref.tzinfo is None and t.tzinfo is not None:
        return pd.Timestamp(t.to_pydatetime().replace(tzinfo=None))
    if ref.tzinfo is not None and t.tzinfo is None:
        try:
            return t.tz_localize(ref.tz, ambiguous="infer", nonexistent="shift_forward")
        except (TypeError, ValueError):
            return t
    return t


def _window_mask(index: pd.DatetimeIndex, entry: Any, exit: Any) -> pd.Series:
    et = _normalize_ts_for_index(entry, index)
    xt = _normalize_ts_for_index(exit, index)
    return (index >= et) & (index <= xt)


def position_windows_from_sources(
    completed_trades: Optional[Sequence[dict]] = None,
    open_positions: Optional[Sequence[dict]] = None,
    chart_end: Any = None,
) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
    """Build (entry, exit) windows from closed trades and in-memory open brackets."""
    windows: List[Tuple[pd.Timestamp, pd.Timestamp]] = []

    for tr in completed_trades or []:
        et = tr.get("entry_time")
        xt = tr.get("exit_time")
        if et is None or xt is None:
            continue
        try:
            et_ts = pd.Timestamp(et)
            xt_ts = pd.Timestamp(xt)
        except Exception:
            continue
        if xt_ts <= et_ts:
            continue
        windows.append((et_ts, xt_ts))

    end = pd.Timestamp(chart_end) if chart_end is not None else None
    for bracket in open_positions or []:
        if bracket.get("_close_recorded"):
            continue
        et = bracket.get("entry_time")
        if et is None:
            continue
        try:
            et_ts = pd.Timestamp(et)
        except Exception:
            continue
        xt_ts = end if end is not None else et_ts
        windows.append((et_ts, xt_ts))

    return windows


def apply_donchian_position_mask(
    df: pd.DataFrame,
    position_windows: Iterable[Tuple[Any, Any]],
) -> pd.DataFrame:
    """
    Entry Donchian when flat; exit Donchian only while a position is open.

    Mutates a copy of ``df`` — entry cols are NaN in-position; exit cols are NaN flat.
    """
    if df is None or df.empty:
        return df

    entry_cols = [c for c in ENTRY_DONCHIAN_COLS if c in df.columns]
    exit_cols = [c for c in EXIT_DONCHIAN_COLS if c in df.columns]
    if not entry_cols and not exit_cols:
        return df

    out = df.copy()
    in_pos = pd.Series(False, index=out.index)
    for entry, exit in position_windows or []:
        if entry is None:
            continue
        if exit is None and len(out.index):
            exit = out.index[-1]
        try:
            in_pos |= _window_mask(out.index, entry, exit)
        except Exception:
            continue

    for col in entry_cols:
        out.loc[in_pos, col] = np.nan
    for col in exit_cols:
        out.loc[~in_pos, col] = np.nan
    return out

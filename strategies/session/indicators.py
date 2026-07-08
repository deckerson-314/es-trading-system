"""Session-specific indicators: RTH VWAP, opening range, deviation bands."""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.bollinger.indicators import calculate_adx, calculate_atr


def _calendar_day(index: pd.DatetimeIndex) -> pd.Series:
    """Calendar date per bar (groupby key for session resets)."""
    return pd.Series(index.date, index=index)


def calculate_session_vwap(df: pd.DataFrame, in_rth: pd.Series) -> pd.Series:
    """VWAP reset each calendar day, accumulated on RTH bars only."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].replace(0, np.nan).fillna(1.0)
    day = _calendar_day(df.index)
    in_rth = in_rth.reindex(df.index).fillna(False).astype(bool)

    pv = (tp * vol).where(in_rth, 0.0)
    vv = vol.where(in_rth, 0.0)
    cum_pv = pv.groupby(day, sort=False).cumsum()
    cum_vv = vv.groupby(day, sort=False).cumsum()
    vwap = (cum_pv / cum_vv.replace(0, np.nan)).where(in_rth)
    return vwap.ffill()


def calculate_opening_range(
    df: pd.DataFrame,
    in_rth: pd.Series,
    or_bars: int,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Opening range high/low per session day; width in points.
    Values are NaN until OR window completes.
    """
    or_bars = max(1, int(or_bars))
    day = _calendar_day(df.index)
    in_rth = in_rth.reindex(df.index).fillna(False).astype(bool)

    rth_num = in_rth.groupby(day, sort=False).cumsum()
    rth_count = in_rth.groupby(day, sort=False).sum()
    valid_day = rth_count >= or_bars

    in_or_build = in_rth & (rth_num <= or_bars)
    hi = df["high"].where(in_or_build).groupby(day, sort=False).max()
    lo = df["low"].where(in_or_build).groupby(day, sort=False).min()
    width = hi - lo

    after_or = in_rth & (rth_num > or_bars)
    is_valid_after = after_or & day.map(valid_day).fillna(False)

    or_high = pd.Series(np.nan, index=df.index, dtype=float)
    or_low = pd.Series(np.nan, index=df.index, dtype=float)
    or_width = pd.Series(np.nan, index=df.index, dtype=float)
    mapped_day = day[is_valid_after]
    or_high.loc[is_valid_after] = mapped_day.map(hi).values
    or_low.loc[is_valid_after] = mapped_day.map(lo).values
    or_width.loc[is_valid_after] = mapped_day.map(width).values

    return or_high, or_low, or_width


def calculate_vwap_bands(
    df: pd.DataFrame,
    vwap: pd.Series,
    atr: pd.Series,
    atr_mult: float,
) -> tuple[pd.Series, pd.Series]:
    upper = vwap + atr_mult * atr
    lower = vwap - atr_mult * atr
    return upper, lower

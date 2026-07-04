"""Session-specific indicators: RTH VWAP, opening range, deviation bands."""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.bollinger.indicators import calculate_adx, calculate_atr


def calculate_session_vwap(df: pd.DataFrame, in_rth: pd.Series) -> pd.Series:
    """VWAP reset each calendar day, accumulated on RTH bars only."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].replace(0, np.nan).fillna(1.0)
    dates = pd.Series(df.index.date, index=df.index)
    vwap = pd.Series(np.nan, index=df.index, dtype=float)
    for day in dates.unique():
        mask = (dates == day) & in_rth
        if not mask.any():
            continue
        vp = (tp.loc[mask] * vol.loc[mask]).cumsum()
        vv = vol.loc[mask].cumsum()
        vwap.loc[mask] = vp / vv.replace(0, np.nan)
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
    or_high = pd.Series(np.nan, index=df.index, dtype=float)
    or_low = pd.Series(np.nan, index=df.index, dtype=float)
    or_width = pd.Series(np.nan, index=df.index, dtype=float)
    dates = pd.Series(df.index.date, index=df.index)
    or_bars = max(1, int(or_bars))

    for day in dates.unique():
        day_mask = dates == day
        rth_idx = df.index[day_mask & in_rth]
        if len(rth_idx) < or_bars:
            continue
        window = rth_idx[:or_bars]
        hi = float(df.loc[window, "high"].max())
        lo = float(df.loc[window, "low"].min())
        width = hi - lo
        after = rth_idx[or_bars:]
        or_high.loc[after] = hi
        or_low.loc[after] = lo
        or_width.loc[after] = width

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

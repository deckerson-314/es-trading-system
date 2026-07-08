"""Parity and correctness tests for vectorized session indicators."""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath("."))

from strategies.session.indicators import calculate_opening_range, calculate_session_vwap


def _legacy_session_vwap(df, in_rth):
    """Reference implementation (pre-vectorization)."""
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


def _legacy_opening_range(df, in_rth, or_bars):
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


def _sample_df():
    idx = pd.DatetimeIndex(
        [
            "2024-06-03 09:30",
            "2024-06-03 09:35",
            "2024-06-03 09:40",
            "2024-06-03 16:00",
            "2024-06-03 18:00",
            "2024-06-04 09:30",
            "2024-06-04 09:35",
            "2024-06-04 09:40",
            "2024-06-04 09:45",
        ]
    )
    df = pd.DataFrame(
        {
            "open": [5000, 5001, 5002, 5003, 5004, 5010, 5011, 5012, 5013],
            "high": [5002, 5003, 5005, 5006, 5007, 5012, 5014, 5015, 5016],
            "low": [4998, 4999, 5000, 5001, 5002, 5008, 5009, 5010, 5011],
            "close": [5001, 5002, 5004, 5005, 5006, 5011, 5013, 5014, 5015],
            "volume": [1000, 2000, 1500, 1200, 800, 1100, 1300, 1400, 900],
        },
        index=idx,
    )
    in_rth = pd.Series(
        [True, True, True, True, False, True, True, True, True],
        index=idx,
    )
    return df, in_rth


def test_session_vwap_matches_legacy():
    df, in_rth = _sample_df()
    expected = _legacy_session_vwap(df, in_rth)
    actual = calculate_session_vwap(df, in_rth)
    pd.testing.assert_series_equal(actual, expected, check_names=False)


def test_opening_range_matches_legacy():
    df, in_rth = _sample_df()
    for or_bars in (1, 2, 3):
        exp = _legacy_opening_range(df, in_rth, or_bars)
        act = calculate_opening_range(df, in_rth, or_bars)
        for i in range(3):
            pd.testing.assert_series_equal(act[i], exp[i], check_names=False)


def test_vwap_resets_each_day():
    df, in_rth = _sample_df()
    vwap = calculate_session_vwap(df, in_rth)
    day1_first = vwap.iloc[0]
    day2_first = vwap.iloc[5]
    assert day1_first != day2_first


def test_or_nan_until_window_complete():
    df, in_rth = _sample_df()
    hi, lo, width = calculate_opening_range(df, in_rth, or_bars=2)
    assert np.isnan(hi.iloc[0])
    assert not np.isnan(hi.iloc[2])
    assert hi.iloc[2] == df["high"].iloc[:2].max()

"""Tests for SessionVwapStrategy signal and indicator logic."""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath("."))

from strategies.session.strategy import SessionVwapStrategy


def _session_params():
    return {
        "Max Open Trades": {"value": 1},
        "Enable Long Trades": {"value": True},
        "Enable Short Trades": {"value": True},
        "Timeframe (minutes)": {"value": 5},
        "Min VWAP Extension (pts)": {"value": 5.0},
        "Entry Band ATR Multiplier": {"value": 1.5},
        "Opening Range (minutes)": {"value": 15},
        "Min OR Width (pts)": {"value": 2.0},
        "Max OR Width (pts)": {"value": 50.0},
        "Max ADX Threshold": {"value": 30.0},
        "Enable ADX Filter": {"value": 0},
        "Enable RTH Filter": {"value": 0},
        "Enable Maintenance Filter": {"value": 0},
        "ATR Length": {"value": 5},
    }


def _synthetic_session_df(n_days=2, bars_per_day=80):
    idx = []
    data = []
    base = 5000.0
    for d in range(n_days):
        day = 3 + d
        for i in range(bars_per_day):
            ts = pd.Timestamp(f"2024-06-{day:02d} 09:30") + pd.Timedelta(minutes=5 * i)
            close = base + 10 * np.sin(i / 8.0)
            idx.append(ts)
            data.append(
                {
                    "open": close - 0.5,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close,
                    "volume": 1000 + i,
                }
            )
    df = pd.DataFrame(data, index=pd.DatetimeIndex(idx))
    df["in_rth"] = True
    df["in_maintenance"] = False
    return df


def test_factory_loads_session():
    from strategies.factory import StrategyFactory

    s = StrategyFactory.get_strategy("session", _session_params())
    assert s.__class__.__name__ == "SessionVwapStrategy"


def test_indicators_add_vwap_and_or():
    strat = SessionVwapStrategy(_session_params())
    df = _synthetic_session_df()
    out = strat.calculate_indicators(df)
    assert "vwap" in out.columns
    assert "or_width" in out.columns
    assert out["vwap"].notna().any()


def test_entry_signals_are_boolean_series():
    strat = SessionVwapStrategy(_session_params())
    df = _synthetic_session_df()
    df = strat.calculate_indicators(df)
    long_sig, short_sig = strat.calculate_entry_signals(df)
    assert len(long_sig) == len(df)
    assert long_sig.dtype == bool or str(long_sig.dtype) == "bool"

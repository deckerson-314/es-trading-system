"""Tests for OrbAcceptanceStrategy signal and indicator logic."""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath("."))

from strategies.orb.strategy import OrbAcceptanceStrategy


def _orb_params():
    return {
        "Max Open Trades": {"value": 1},
        "Enable Long Trades": {"value": True},
        "Enable Short Trades": {"value": True},
        "Timeframe (minutes)": {"value": 5},
        "Opening Range (minutes)": {"value": 15},
        "Acceptance Bars": {"value": 2},
        "Breakout Buffer (pts)": {"value": 0.0},
        "Min OR Width (pts)": {"value": 2.0},
        "Max OR Width (pts)": {"value": 50.0},
        "Min ADX Threshold": {"value": 0.0},
        "Max ADX Threshold": {"value": 99.0},
        "Enable ADX Filter": {"value": 0},
        "Enable VWAP Filter": {"value": 0},
        "Enable RTH Filter": {"value": 0},
        "Enable Maintenance Filter": {"value": 0},
        "Stop ATR Multiplier": {"value": 1.0},
        "Use Opposite OR Stop": {"value": 1},
        "Target OR Width Multiple": {"value": 1.0},
        "ATR Length": {"value": 5},
        "Max Entries Per Day": {"value": 1},
    }


def _synthetic_orb_df():
    """Two days: day1 range, day2 breakout above OR."""
    idx = []
    data = []
    for d, base in [(3, 5000.0), (4, 5010.0)]:
        for i in range(40):
            ts = pd.Timestamp(f"2024-06-{d:02d} 09:30") + pd.Timedelta(minutes=5 * i)
            if d == 4 and i >= 10:
                close = base + 2.0 * (i - 9)
            else:
                close = base + np.sin(i / 5.0)
            idx.append(ts)
            data.append(
                {
                    "open": close - 0.25,
                    "high": close + 0.5,
                    "low": close - 0.5,
                    "close": close,
                    "volume": 2000,
                }
            )
    df = pd.DataFrame(data, index=pd.DatetimeIndex(idx))
    df["in_rth"] = True
    df["in_maintenance"] = False
    return df


def test_factory_loads_orb():
    from strategies.factory import StrategyFactory

    s = StrategyFactory.get_strategy("orb", _orb_params())
    assert s.__class__.__name__ == "OrbAcceptanceStrategy"


def test_indicators_add_or_and_vwap():
    strat = OrbAcceptanceStrategy(_orb_params())
    df = _synthetic_orb_df()
    out = strat.calculate_indicators(df)
    assert "or_high" in out.columns
    assert "or_width" in out.columns
    assert "vwap" in out.columns
    assert out["or_width"].notna().any()


def test_entry_signals_are_boolean_series():
    strat = OrbAcceptanceStrategy(_orb_params())
    df = strat.calculate_indicators(_synthetic_orb_df())
    long_sig, short_sig = strat.calculate_entry_signals(df)
    assert len(long_sig) == len(df)
    assert long_sig.dtype == bool or str(long_sig.dtype) == "bool"


def test_acceptance_bars_require_consecutive_closes():
    p1 = _orb_params()
    p1["Acceptance Bars"] = {"value": 1}
    p2 = _orb_params()
    p2["Acceptance Bars"] = {"value": 3}
    df = _synthetic_orb_df()
    s1 = OrbAcceptanceStrategy(p1)
    s2 = OrbAcceptanceStrategy(p2)
    d1 = s1.calculate_indicators(df.copy())
    d2 = s2.calculate_indicators(df.copy())
    l1, _ = s1.calculate_entry_signals(d1)
    l2, _ = s2.calculate_entry_signals(d2)
    assert l1.sum() >= l2.sum()


def test_setup_position_tp_on_breakout_side():
    strat = OrbAcceptanceStrategy(_orb_params())
    df = strat.calculate_indicators(_synthetic_orb_df())
    row = df.iloc[25]
    long_pos = strat.setup_position(float(row["close"]), 1, row, df)
    short_pos = strat.setup_position(float(row["close"]), -1, row, df)
    assert long_pos["tp"] > long_pos["entry_price"]
    assert short_pos["tp"] < short_pos["entry_price"]
    assert long_pos["stop"] < long_pos["entry_price"]
    assert short_pos["stop"] > short_pos["entry_price"]


def test_check_exit_flattens_in_maintenance():
    strat = OrbAcceptanceStrategy(_orb_params())
    pos = {"direction": 1, "stop": 4900.0, "tp": 5100.0, "bars_held": 2}
    row = pd.Series(
        {
            "high": 5010.0,
            "low": 5000.0,
            "close": 5005.0,
            "force_exit": False,
            "force_exit_rth": False,
            "in_maintenance": True,
        },
        name=pd.Timestamp("2024-06-03 17:05"),
    )
    should_exit, reason, price = strat.check_exit(pos, row, None)
    assert should_exit
    assert reason == "Maintenance Exit"

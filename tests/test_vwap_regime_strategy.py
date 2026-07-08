"""Tests for VwapRegimeStrategy signal and indicator logic."""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath("."))

from strategies.vwap_regime.strategy import VwapRegimeStrategy


def _params():
    return {
        "Max Open Trades": {"value": 1},
        "Enable Long Trades": {"value": True},
        "Enable Short Trades": {"value": True},
        "Timeframe (minutes)": {"value": 5},
        "Opening Range (minutes)": {"value": 15},
        "Min OR Width (pts)": {"value": 1.0},
        "Max OR Width (pts)": {"value": 50.0},
        "Min Trend ADX": {"value": 0.0},
        "Max Range ADX": {"value": 99.0},
        "Enable ADX Filter": {"value": 0},
        "Trend Side Pct": {"value": 0.55},
        "Min VWAP Crosses": {"value": 1},
        "Pullback Touch Buffer (pts)": {"value": 2.0},
        "Pullback Confirm Bars": {"value": 1},
        "Min VWAP Extension (pts)": {"value": 3.0},
        "Fade Band ATR Multiplier": {"value": 1.5},
        "Fade Confirm Bars": {"value": 1},
        "Enable RTH Filter": {"value": 0},
        "Enable Maintenance Filter": {"value": 0},
        "Stop ATR Multiplier": {"value": 1.0},
        "Trend Target R Multiple": {"value": 1.5},
        "TP VWAP Buffer (pts)": {"value": 0.5},
        "ATR Length": {"value": 5},
        "Max Entries Per Day": {"value": 3},
        "Trade Start After OR (min)": {"value": 0},
    }


def _synthetic_df():
    """Two days with post-OR trend pullback on day 2."""
    idx = []
    data = []
    for d, drift in [(3, 0.0), (4, 0.15)]:
        for i in range(36):
            ts = pd.Timestamp(f"2024-06-{d:02d} 09:30") + pd.Timedelta(minutes=5 * i)
            close = 5000.0 + drift * i + np.sin(i / 4.0) * 0.5
            if d == 4 and i >= 12:
                close = 5000.0 + 0.2 * i
            idx.append(ts)
            data.append(
                {
                    "open": close - 0.1,
                    "high": close + 0.4,
                    "low": close - 0.4,
                    "close": close,
                    "volume": 3000,
                }
            )
    df = pd.DataFrame(data, index=pd.DatetimeIndex(idx))
    df["in_rth"] = True
    df["in_maintenance"] = False
    return df


def test_factory_loads_vwap_regime():
    from strategies.factory import StrategyFactory

    s = StrategyFactory.get_strategy("vwap_regime", _params())
    assert s.__class__.__name__ == "VwapRegimeStrategy"


def test_indicators_add_regime_columns():
    strat = VwapRegimeStrategy(_params())
    out = strat.calculate_indicators(_synthetic_df())
    for col in ("vwap", "or_width", "regime_trend", "regime_range", "pct_above_vwap"):
        assert col in out.columns


def test_entry_signals_are_boolean():
    strat = VwapRegimeStrategy(_params())
    df = strat.calculate_indicators(_synthetic_df())
    long_sig, short_sig = strat.calculate_entry_signals(df)
    assert len(long_sig) == len(df)
    assert long_sig.dtype == bool or str(long_sig.dtype) == "bool"
    assert short_sig.dtype == bool or str(short_sig.dtype) == "bool"


def test_setup_position_trend_has_rr_target():
    strat = VwapRegimeStrategy(_params())
    df = strat.calculate_indicators(_synthetic_df())
    row = df.iloc[20].copy()
    row["regime_trend"] = True
    row["pct_above_vwap"] = 0.7
    pos = strat.setup_position(float(row["close"]), 1, row, df)
    assert pos["entry_mode"] in ("trend", "range")
    assert pos["tp"] > pos["entry_price"]
    assert pos["stop"] < pos["entry_price"]


def test_max_entries_per_day_cap():
    p = _params()
    p["Max Entries Per Day"] = {"value": 1}
    strat = VwapRegimeStrategy(p)
    df = strat.calculate_indicators(_synthetic_df())
    long_sig, short_sig = strat.calculate_entry_signals(df)
    day = pd.Series(df.index.date, index=df.index)
    for _, idx in df.groupby(day).groups.items():
        assert int(long_sig.loc[idx].sum() + short_sig.loc[idx].sum()) <= 1


def test_check_exit_respects_stop():
    strat = VwapRegimeStrategy(_params())
    pos = {"direction": 1, "stop": 4990.0, "tp": 5100.0, "bars_held": 2, "entry_mode": "trend"}
    row = pd.Series({"high": 5005.0, "low": 4988.0, "close": 4992.0, "vwap": 5000.0})
    hit, reason, _ = strat.check_exit(pos, row, None)
    assert hit and reason == "Stop Loss"

"""Regression: final GA dashboard must keep IS/OOS split analysis tables."""

import os
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import optimize as o


def _tiny_period(start="2024-01-02 09:30", bars=8):
    idx = pd.date_range(start, periods=bars, freq="5min")
    return pd.DataFrame(
        {
            "open": np.linspace(5000, 5004, bars),
            "high": np.linspace(5001, 5005, bars),
            "low": np.linspace(4999, 5003, bars),
            "close": np.linspace(5000.5, 5004.5, bars),
            "volume": np.full(bars, 1000.0),
        },
        index=idx,
    )


def _fake_backtest(params, df, param_dict, suppress_output=True, **kwargs):
    n = max(1, len(df) // 4)
    trades = pd.DataFrame(
        {
            "pnl": [10.0] * n,
            "entry_time": list(df.index[:n]),
            "exit_time": list(df.index[1 : n + 1]),
        }
    )
    return {
        "sortino": 1.0,
        "max_drawdown": 100.0,
        "profit_factor": 1.2,
        "avg_trades_day": 0.5,
        "total_profit": float(trades["pnl"].sum()),
        "avg_trade_duration_min": 10.0,
        "trades_df": trades,
    }


def test_final_dashboard_keeps_split_period_tables(tmp_path):
    """is_final=True must still render Individual IS/OOS Period Statistics when periods are passed."""
    is_p = [_tiny_period("2024-01-02 09:30"), _tiny_period("2024-02-01 09:30")]
    oos_p = [_tiny_period("2024-01-15 09:30"), _tiny_period("2024-02-15 09:30")]
    html_path = tmp_path / "ga_dashboard_v4.html"
    diag = tmp_path / "diag"
    diag.mkdir()

    class _Fit:
        values = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
        valid = True

    class _Ind(list):
        fitness = _Fit()
        generation_found = 1

    ind = _Ind([1.0, 2.0])
    logbook = o.tools.Logbook()
    logbook.header = ["gen", "avg_sortino", "avg_dd", "avg_pf", "pareto_size"]
    logbook.record(gen=0, avg_sortino=0.0, avg_dd=0.0, avg_pf=0.0, pareto_size=1)

    with patch.object(o, "run_backtest", side_effect=_fake_backtest), patch.object(
        o, "webbrowser"
    ):
        o.generate_html_dashboard(
            hof=[ind],
            best=ind,
            best_params={"Timeframe (minutes)": 5},
            best_fitness=ind.fitness.values,
            param_keys=["Timeframe (minutes)"],
            param_dict={
                "Timeframe (minutes)": {
                    "min": 3,
                    "max": 15,
                    "type": "int",
                    "value": 5,
                }
            },
            logbook=logbook,
            is_res={
                "sortino": 1.0,
                "max_drawdown": 100.0,
                "profit_factor": 1.2,
                "avg_trades_day": 0.5,
                "total_profit": 20.0,
            },
            oos_res={
                "sortino": 0.8,
                "max_drawdown": 120.0,
                "profit_factor": 1.1,
                "avg_trades_day": 0.4,
                "total_profit": 10.0,
            },
            trades_is=pd.DataFrame(),
            trades_oos=pd.DataFrame(),
            html_path=str(html_path),
            diag_dir=str(diag),
            current_gen=200,
            total_gen=200,
            is_final=True,
            auto_launch=False,
            is_periods=is_p,
            oos_periods=oos_p,
            pop=[ind],
        )

    html = html_path.read_text(encoding="utf-8")
    assert "Individual In-Sample Period Statistics" in html
    assert "Individual OOS Period Statistics" in html
    assert "Data Split Information" in html
    assert "In-Sample" in html and "Out-of-Sample" in html


def test_final_dashboard_without_periods_omits_split_tables(tmp_path):
    """If periods are omitted (the old final-call bug), split tables must not appear."""
    html_path = tmp_path / "ga_dashboard_v4.html"
    diag = tmp_path / "diag"
    diag.mkdir()

    class _Fit:
        values = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
        valid = True

    class _Ind(list):
        fitness = _Fit()
        generation_found = 1

    ind = _Ind([1.0])
    logbook = o.tools.Logbook()
    logbook.header = ["gen", "avg_sortino"]
    logbook.record(gen=0, avg_sortino=0.0)

    with patch.object(o, "run_backtest", side_effect=_fake_backtest), patch.object(
        o, "webbrowser"
    ):
        o.generate_html_dashboard(
            hof=[ind],
            best=ind,
            best_params={"Timeframe (minutes)": 5},
            best_fitness=ind.fitness.values,
            param_keys=["Timeframe (minutes)"],
            param_dict={
                "Timeframe (minutes)": {
                    "min": 3,
                    "max": 15,
                    "type": "int",
                    "value": 5,
                }
            },
            logbook=logbook,
            is_res={
                "sortino": 0,
                "max_drawdown": 0,
                "profit_factor": 0,
                "avg_trades_day": 0,
                "total_profit": 0,
            },
            oos_res={
                "sortino": 0,
                "max_drawdown": 0,
                "profit_factor": 0,
                "avg_trades_day": 0,
                "total_profit": 0,
            },
            trades_is=pd.DataFrame(),
            trades_oos=pd.DataFrame(),
            html_path=str(html_path),
            diag_dir=str(diag),
            is_final=True,
            auto_launch=False,
            is_periods=None,
            oos_periods=None,
            pop=[ind],
        )

    html = html_path.read_text(encoding="utf-8")
    assert "Individual In-Sample Period Statistics" not in html
    assert "Individual OOS Period Statistics" not in html


def test_final_generate_html_call_site_passes_periods():
    """Guard the completion call site so periods are not dropped again."""
    src = open(os.path.join(PROJECT_ROOT, "optimize.py"), encoding="utf-8").read()
    # Last is_final=True block (completion dashboard) must pass periods.
    idx = src.rfind("is_final=True")
    assert idx > 0
    chunk = src[idx - 1200 : idx + 900]
    assert "is_periods=" in chunk
    assert "oos_periods=" in chunk
    assert "Generating Interactive HTML Dashboard" in chunk

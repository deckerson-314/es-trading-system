"""Unit tests for core.trade_attribution excursion and quadrant math."""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath("."))

from core.trade_attribution import (
    AttributionConfig,
    Quadrant,
    TradeLeg,
    build_sr_legs,
    direction_diagnostics,
    enrich_legs,
    excursion_window,
    exit_at_hold,
    load_trades_csv,
    run_attribution,
    trades_to_ss_legs,
)


def _synthetic_ohlcv() -> pd.DataFrame:
    idx = pd.date_range("2024-01-02 09:30", periods=120, freq="1min")
    # Uptrend: close rises 1 pt per bar
    close = 5000.0 + pd.Series(range(120), index=idx)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000,
        },
        index=idx,
    )


def test_excursion_window_long_uptrend():
    ohlcv = _synthetic_ohlcv()
    entry = ohlcv.index[0]
    exit_ = ohlcv.index[10]
    mfe, mae, _, _, mae_first = excursion_window(ohlcv, entry, exit_, 5000.0, 1)
    assert mfe >= 9.0
    assert mae <= 1.0


def test_exit_at_hold_long_profit():
    ohlcv = _synthetic_ohlcv()
    cfg = AttributionConfig(transaction_cost=0.0)
    leg = exit_at_hold(ohlcv, ohlcv.index[0], 5000.0, 1, 10.0, cfg)
    assert leg.pnl_pts > 0


def test_ss_legs_from_csv_roundtrip(tmp_path):
    csv = tmp_path / "t.csv"
    csv.write_text(
        "entry_time,entry_price,direction,exit_time,exit_price,pnl,reason\n"
        "2024-01-02 09:30:00,5000,1,2024-01-02 09:40:00,5010,500,Stop Loss\n"
    )
    trades = load_trades_csv(csv)
    cfg = AttributionConfig(transaction_cost=15.0)
    legs = trades_to_ss_legs(trades, cfg)
    assert len(legs) == 1
    assert legs[0].pnl_pts == 10.0
    assert legs[0].pnl_usd == 10.0 * 50 - 15


def test_sr_preserves_entry():
    ohlcv = _synthetic_ohlcv()
    cfg = AttributionConfig(seed=1)
    ss = [
        TradeLeg(
            entry_time=ohlcv.index[5],
            exit_time=ohlcv.index[15],
            entry_price=5005.0,
            exit_price=5015.0,
            direction=1,
            quadrant=Quadrant.SS,
        )
    ]
    ss[0].compute_pnl(cfg)
    import random

    sr = build_sr_legs(ss, ohlcv, cfg, random.Random(1))
    assert sr[0].entry_time == ss[0].entry_time
    assert sr[0].direction == ss[0].direction


def test_direction_diagnostics_opposite_wins_on_downtrend_leg():
    cfg = AttributionConfig(transaction_cost=0.0, seed=0)
    legs = [
        TradeLeg(
            entry_time=pd.Timestamp("2024-01-02 09:30"),
            exit_time=pd.Timestamp("2024-01-02 09:40"),
            entry_price=100.0,
            exit_price=90.0,
            direction=1,
            quadrant=Quadrant.SS,
        )
    ]
    legs[0].compute_pnl(cfg)
    import random

    d = direction_diagnostics(legs, cfg, random.Random(0), 50)
    assert d.opposite_net_pnl_usd > 0
    assert d.pct_strategy_beats_opposite == 0.0


def test_run_attribution_smoke():
    ohlcv = _synthetic_ohlcv()
    oos_mask = pd.Series(True, index=ohlcv.index)
    trades = pd.DataFrame(
        {
            "entry_time": [ohlcv.index[0], ohlcv.index[20]],
            "exit_time": [ohlcv.index[10], ohlcv.index[30]],
            "entry_price": [5000.0, 5020.0],
            "exit_price": [5010.0, 5015.0],
            "direction": [1, -1],
            "pnl": [500, -250],
            "reason": ["Maintenance Exit", "Stop Loss"],
        }
    )
    cfg = AttributionConfig(mc_runs=20, seed=0)
    report = run_attribution(trades, ohlcv, oos_mask, cfg=cfg)
    assert set(report.quadrants.keys()) == {"SS", "SR", "RS", "RR"}
    assert report.quadrants["SS"].trade_count == 2
    assert report.quadrants["RR"].mc_median_usd is not None

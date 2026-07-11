"""GA OOS/IS evaluation must use full-history warmup + masks."""
from __future__ import annotations

import numpy as np
import pandas as pd

from optimize import (
    build_ga_training_bundle,
    run_backtest_period,
    _period_eval_mask,
)


def _tiny_ohlcv(n: int = 120) -> pd.DataFrame:
    idx = pd.date_range("2020-01-02 09:30", periods=n, freq="1min")
    close = 3000.0 + np.linspace(0, 10, n)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100,
        },
        index=idx,
    )


def test_period_eval_mask_matches_period_index():
    df = _tiny_ohlcv(100)
    period = df.iloc[40:60]
    mask = _period_eval_mask(df, period)
    assert mask.sum() == 20
    assert mask.iloc[40:60].all()
    assert not mask.iloc[:40].any()
    assert not mask.iloc[60:].any()


def test_build_ga_training_bundle_returns_full_oos_and_mask(monkeypatch, tmp_path):
    """oos frame is full window; oos_mask == ~is_mask (not a sliced OOS-only frame)."""
    csv_path = tmp_path / "tiny.csv"
    df = _tiny_ohlcv(200)
    # CSV format expected by build_ga_training_bundle: no header, datetime + OHLCV
    out = df.reset_index()
    out.columns = ["datetime", "open", "high", "low", "close", "volume"]
    out.to_csv(csv_path, header=False, index=False)

    param_dict = {}
    in_sample, oos, is_mask, is_periods, oos_periods, oos_mask = build_ga_training_bundle(
        param_dict,
        ga_start_date="2020-01-02",
        ga_end_date="2020-01-03",
        data_splits=0.65,
        data_size=0,
        use_interleaved=True,
        num_periods=4,
        data_csv=str(csv_path),
        verbose=False,
    )

    assert len(in_sample) == len(oos)
    assert in_sample.index.equals(oos.index)
    assert oos_mask.equals(~is_mask)
    assert is_mask.sum() + oos_mask.sum() == len(in_sample)
    assert len(is_periods) >= 1
    assert len(oos_periods) >= 1
    # Legacy bug: oos was df[~is_mask] (fewer rows). Must not regress.
    assert len(oos) == len(in_sample)


def test_run_backtest_period_uses_full_df_when_provided(monkeypatch):
    """When df_full is set, period eval builds a mask on the full index."""
    calls = []

    def fake_run_backtest(params, df_in, param_dict, suppress_output=True, mask=None, **kwargs):
        calls.append({"n": len(df_in), "mask_sum": None if mask is None else int(mask.sum())})
        return {"sortino": 0, "trades_df": pd.DataFrame()}

    import optimize as opt

    monkeypatch.setattr(opt, "run_backtest", fake_run_backtest)
    df = _tiny_ohlcv(80)
    period = df.iloc[20:40]
    opt.run_backtest_period({}, period, {}, df_full=df)
    assert len(calls) == 1
    assert calls[0]["n"] == 80
    assert calls[0]["mask_sum"] == 20

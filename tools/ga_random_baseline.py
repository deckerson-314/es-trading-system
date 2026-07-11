#!/usr/bin/env python3
"""
Random-genome baseline vs Jul-03 GA HoF under full fidelity.

Answers: "Would uniform random params in the search box beat the failed GA region?"
"""
from __future__ import annotations

import os
import random
import statistics
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["STRATEGY"] = "trend"

from optimize import build_ga_training_bundle, run_backtest  # noqa: E402
from strategies.trend.parameters import load_params  # noqa: E402

PARAM_CSV = ROOT / "strategies/trend/parameters/trend_strategy_params.csv"
DATA = ROOT / "Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv"
JUL03_BEST_OOS = -33_480.5
N_RANDOM = 40
SEED = 42


def load_ohlcv(start: str, end: str) -> pd.DataFrame:
    df = pd.read_csv(DATA, parse_dates=True, index_col=0)
    df.columns = [str(c).lower().strip() for c in df.columns]
    if not all(c in df.columns for c in ["open", "high", "low", "close", "volume"]):
        df = pd.read_csv(DATA, header=None, parse_dates=True, index_col=0)
        df.columns = ["open", "high", "low", "close", "volume"]
    return df[["open", "high", "low", "close", "volume"]].dropna().loc[start:end]


def random_genome(param_dict, rng: random.Random) -> dict:
    skip = {"POP_SIZE", "NUM_GEN", "MIN_TRADES", "LIMIT_", "DATA_", "NORM_", "WEIGHT_"}
    p = {}
    for k, meta in param_dict.items():
        if not isinstance(meta, dict) or meta.get("type") not in ("int", "float"):
            continue
        if str(k).startswith("GA_") or "WEIGHT" in str(k):
            continue
        if any(str(k).startswith(s) for s in skip):
            continue
        mn, mx = meta.get("min"), meta.get("max")
        if mn is None or mx is None or mn == mx:
            continue
        if meta["type"] == "int":
            p[k] = rng.randint(int(mn), int(mx))
        else:
            p[k] = rng.uniform(float(mn), float(mx))
    return p


def eval_oos_pnl(params, df_in, param_dict, oos_mask):
    res = run_backtest(params, df_in, param_dict, suppress_output=True, mask=oos_mask)
    tr = res.get("trades_df")
    if tr is None or tr.empty:
        return 0.0, 0
    col = "pnl_currency" if "pnl_currency" in tr.columns else "pnl"
    return float(tr[col].sum()), len(tr)


def main():
    random.seed(SEED)
    param_dict, _ = load_params(str(PARAM_CSV), return_dataframe=True)
    param_dict["strategy_name"] = "trend"
    start = str(param_dict["GA_START_DATE"]["value"])
    end = str(param_dict["GA_END_DATE"]["value"])
    ohlcv = load_ohlcv(start, end)
    in_sample, oos_df, is_mask, _, _, oos_mask = build_ga_training_bundle(
        param_dict,
        ga_start_date=start,
        ga_end_date=end,
        data_splits=float(param_dict["DATA_SPLITS"]["value"]),
        data_size=int(param_dict["DATA_SIZE"]["value"] or 0),
        use_interleaved=str(param_dict["USE_INTERLEAVED_SPLIT"]["value"]).lower() in ("true", "1", "yes"),
        num_periods=int(param_dict["NUM_SPLIT_PERIODS"]["value"]),
        verbose=False,
    )

    pnls = []
    print(f"Random baseline: {N_RANDOM} genomes from {PARAM_CSV.name}")
    print(f"Window: {start} .. {end}  |  Jul-03 best OOS: ${JUL03_BEST_OOS:,.0f}\n")
    for i in range(N_RANDOM):
        genome = random_genome(param_dict, random)
        pnl, n = eval_oos_pnl(genome, in_sample, param_dict, oos_mask)
        pnls.append(pnl)
        print(f"  #{i:2d}  OOS=${pnl:>10,.0f}  trades={n:4d}  TF={genome.get('Timeframe (minutes)', '?')}")

    pos = sum(1 for p in pnls if p > 0)
    print(f"\nSummary:")
    print(f"  OOS>0:        {pos}/{N_RANDOM}")
    print(f"  OOS median:   ${statistics.median(pnls):,.0f}")
    print(f"  OOS best:     ${max(pnls):,.0f}")
    print(f"  OOS worst:    ${min(pnls):,.0f}")
    print(f"  Jul-03 best:  ${JUL03_BEST_OOS:,.0f}")
    if statistics.median(pnls) > JUL03_BEST_OOS:
        print("  => Random median beats Jul-03 GA best (search region likely broken).")
    elif max(pnls) > JUL03_BEST_OOS:
        print("  => Some random genomes beat Jul-03 GA best.")
    else:
        print("  => Jul-03 GA best still beats random sample (GA found local structure).")


if __name__ == "__main__":
    main()

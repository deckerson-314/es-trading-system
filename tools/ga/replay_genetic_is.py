#!/usr/bin/env python3
"""
Replay GA in-sample aggregate metrics for one column from genetic_results_*.csv.

The GA evaluates with run_backtest(params, in_sample, mask=is_mask). A plain backtest on
the full CSV without that mask will not match exported statistics.

Usage:
  python tools/ga/replay_genetic_is.py ^
    --params strategies/trend/parameters/trend_strategy_params.csv ^
    --results Trend/parameters/genetic_results_2026-04-26-2.csv ^
    --solution 159
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from strategies.bollinger.parameters import load_params  # noqa: E402
import optimize as opt  # noqa: E402


def _cfg(param_dict, name, default):
    d = param_dict.get(name, {})
    v = d.get("value") if isinstance(d, dict) else None
    if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
        return default
    return v


def _read_solution_column(results_csv: str, col: str, param_dict: dict) -> dict:
    df = pd.read_csv(results_csv)
    if col not in df.columns:
        raise SystemExit(f"Missing column {col} in {results_csv}")
    t = df["Type"].fillna("").astype(str)
    name = df["Name"]
    skip = (
        t.isin({"statistic", "robustness", "split_detail"})
        | name.astype(str).str.startswith("==", na=False)
        | name.astype(str).str.startswith("---", na=False)
        | name.astype(str).str.startswith("  ", na=False)
    )
    raw = {}
    for _, row in df[~skip].iterrows():
        n = row["Name"]
        if n not in param_dict or not isinstance(param_dict[n], dict):
            continue
        cell = row[col]
        if pd.isna(cell) or str(cell).strip() == "":
            # Export often leaves blanks for defaults — use the template Value from the same row
            base = row.get("Value")
            if base is None or str(base).strip() == "" or (isinstance(base, float) and pd.isna(base)):
                base = param_dict[n].get("value")
            if base is None or (isinstance(base, float) and pd.isna(base)):
                continue
            cell = base
        typ = param_dict[n].get("type", "float")
        s = str(cell).strip()
        try:
            if typ == "bool":
                raw[n] = s.lower() in ("true", "1", "yes")
            elif typ == "int":
                raw[n] = int(round(float(s)))
            elif typ == "float":
                raw[n] = float(s)
            else:
                raw[n] = cell
        except (TypeError, ValueError):
            continue

    for n, d in param_dict.items():
        if not isinstance(d, dict):
            continue
        v = raw.get(n)
        if v is not None and not (isinstance(v, float) and pd.isna(v)):
            continue
        vv = d.get("value")
        if vv is None or (isinstance(vv, float) and pd.isna(vv)):
            continue
        typ = d.get("type", "float")
        try:
            if typ == "bool":
                s = str(vv).strip().lower()
                raw[n] = s in ("true", "1", "yes")
            elif typ == "int":
                raw[n] = int(round(float(vv)))
            elif typ == "float":
                raw[n] = float(vv)
            else:
                raw[n] = vv
        except (TypeError, ValueError):
            continue
    return raw


def main():
    p = argparse.ArgumentParser(description="Replay GA IS aggregate for one genetic_results column")
    p.add_argument("--params", required=True, help="Parameter CSV used for the GA run (e.g. trend_strategy_params.csv)")
    p.add_argument("--results", required=True, help="genetic_results_*.csv path")
    p.add_argument("--solution", type=int, required=True, help="Solution index N for column Solution_N")
    p.add_argument("--data-csv", default=None, help="Override ES 1m CSV (default: same as optimize.py)")
    p.add_argument(
        "--strategy",
        default="",
        help="trend or bollinger (default: infer from --params path)",
    )
    args = p.parse_args()

    col = f"Solution_{args.solution}"
    param_dict, _ = load_params(args.params, return_dataframe=True)
    strat = (args.strategy or "").strip().lower()
    if not strat:
        pl = args.params.replace("\\", "/").lower()
        strat = "trend" if "/trend/" in pl else "bollinger"
    param_dict["strategy_name"] = strat

    ga_start = str(_cfg(param_dict, "GA_START_DATE", "2024-01-01"))
    ga_end = str(_cfg(param_dict, "GA_END_DATE", "2024-12-31"))
    data_splits = float(_cfg(param_dict, "DATA_SPLITS", 0.7))
    data_size = int(_cfg(param_dict, "DATA_SIZE", 100000))
    use_interleaved = bool(_cfg(param_dict, "USE_INTERLEAVED_SPLIT", True))
    num_periods = int(_cfg(param_dict, "NUM_SPLIT_PERIODS", 5))

    in_sample, _oos, is_mask, _isp, _osp = opt.build_ga_training_bundle(
        param_dict,
        ga_start_date=ga_start,
        ga_end_date=ga_end,
        data_splits=data_splits,
        data_size=data_size,
        use_interleaved=use_interleaved,
        num_periods=num_periods,
        data_csv=args.data_csv,
        verbose=True,
    )

    raw = _read_solution_column(args.results, col, param_dict)
    params = opt.finalize_ga_solution_params(raw, param_dict)
    res = opt.run_backtest(params, in_sample, param_dict, suppress_output=True, mask=is_mask)

    print("\n=== Replay (IS aggregate, masked) ===")
    for k in ("sortino", "max_drawdown", "profit_factor", "avg_trades_day", "total_profit"):
        print(f"  {k}: {res.get(k, 0)}")
    print(f"  trades: {len(res.get('trades_df', []))}")


if __name__ == "__main__":
    main()

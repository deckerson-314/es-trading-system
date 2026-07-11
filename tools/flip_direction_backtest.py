#!/usr/bin/env python3
"""Quick opposite-direction replay for a GA solution (diagnostic)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if "--strategy" not in sys.argv:
    sys.argv[1:1] = ["--strategy", "session"]

from optimize import (  # noqa: E402
    build_ga_training_bundle,
    build_solution_export_params,
    run_backtest,
)
from strategies.bollinger.parameters import load_params  # noqa: E402
from strategies.session.strategy import SessionVwapStrategy  # noqa: E402

GA_CRITERIA = {
    "POP_SIZE", "NUM_GEN", "CX_PB", "MUT_PB", "MUT_MU", "MUT_SIGMA",
    "TARGET_TRADES_DAY", "TRADES_PENALTY_WEIGHT", "DD_WEIGHT",
    "DATA_SPLITS", "DATA_SIZE", "USE_INTERLEAVED_SPLIT", "NUM_SPLIT_PERIODS",
    "MIN_TRADES_DAY", "MIN_TRADES_PEN_WEIGHT", "GA_START_DATE", "GA_END_DATE",
    "GA_LIVE_STYLE_ENTRY", "GA_CONSERVATIVE_STOP_SLIPPAGE",
    "GA_CONSERVATIVE_ENTRY_SLIPPAGE", "GA_CONSERVATIVE_CHANNEL_SLIPPAGE",
    "GA_PESSIMISTIC_STOPS", "ENABLE_FILTER_STACK_TRADE_PENALTY",
    "INTERACTION_PENALTY_STRENGTH", "INTERACTION_LOW_TRADES_BASE",
    "INTERACTION_LOW_TRADES_PER_FILTER", "INTERACTION_MIN_FILTERS",
    "WEIGHT_SORTINO", "WEIGHT_DRAWDOWN", "WEIGHT_PF", "WEIGHT_TRADES",
    "WEIGHT_PNL", "WEIGHT_PPT", "MIN_TRADE_DURATION", "MAX_WIN_RATE_CAP",
    "LIMIT_MAX_LOSS", "LIMIT_MIN_SORTINO", "MIN_WIN_RATE", "SORTINO_CAP",
    "NORM_SORTINO_MAX", "NORM_DD_MAX", "NORM_PF_MAX", "NORM_TRADES_MAX",
    "NORM_PNL_MAX", "NORM_PROFIT_TRADE_MAX",
}


def _param_keys(param_dict: dict) -> list[str]:
    keys: list[str] = []
    for name, meta in param_dict.items():
        if not isinstance(meta, dict) or name.startswith("__"):
            continue
        if name in GA_CRITERIA:
            continue
        if meta.get("type") not in ("int", "float"):
            continue
        if meta.get("min") == meta.get("max"):
            continue
        keys.append(name)
    return keys


def _load_solution(solution: int, ga_csv: Path, param_csv: Path):
    param_dict, param_df = load_params(str(param_csv), return_dataframe=True)
    param_dict["strategy_name"] = "session"
    keys = _param_keys(param_dict)

    ga_df = pd.read_csv(ga_csv)
    col = f"Solution_{solution}_SELECTED"
    if col not in ga_df.columns:
        col = f"Solution_{solution}"
    if col not in ga_df.columns:
        raise ValueError(f"No solution column for index {solution}")

    raw: dict = {}
    for key in keys:
        row = ga_df.loc[ga_df["Name"] == key]
        if row.empty:
            continue
        val = row.iloc[0][col]
        if pd.isna(val) or str(val).strip() == "":
            val = row.iloc[0]["Value"]
        raw[key] = float(val)

    _, effective = build_solution_export_params(raw, param_dict, param_df, keys)
    return effective, param_dict, col


def _run(effective, param_dict, df_in, *, invert: bool, mask=None):
    orig = SessionVwapStrategy.calculate_entry_signals

    def _calc(self, frame, verbose=False):
        long_sig, short_sig = orig(self, frame, verbose)
        if invert:
            return short_sig, long_sig
        return long_sig, short_sig

    SessionVwapStrategy.calculate_entry_signals = _calc
    try:
        return run_backtest(
            effective, df_in, param_dict, suppress_output=True, mask=mask,
        )
    finally:
        SessionVwapStrategy.calculate_entry_signals = orig


def _summarize(res) -> dict:
    tdf = res.get("trades_df")
    if tdf is None or tdf.empty:
        return {"trades": 0, "pnl": 0.0, "pf": 0.0, "wr": 0.0, "sortino": 0.0}
    return {
        "trades": len(tdf),
        "pnl": float(tdf["pnl"].sum()),
        "pf": float(res.get("profit_factor", 0)),
        "wr": float((tdf["pnl"] > 0).mean() * 100),
        "sortino": float(res.get("sortino", 0)),
    }


def _print_row(label: str, s: dict) -> None:
    print(
        f"{label:12}  trades={s['trades']:4d}  "
        f"pnl=${s['pnl']:,.0f}  pf={s['pf']:.2f}  "
        f"wr={s['wr']:.1f}%  sortino={s['sortino']:.2f}"
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Opposite-direction backtest diagnostic.")
    p.add_argument("--strategy", default="session")
    p.add_argument(
        "--ga-file",
        default=str(ROOT / "Session/parameters/genetic_results_2026-07-04-1.csv"),
    )
    p.add_argument(
        "--param-csv",
        default=str(ROOT / "strategies/session/parameters/session_strategy_params.csv"),
    )
    p.add_argument("--solution", type=int, default=0)
    args = p.parse_args()

    ga_csv = Path(args.ga_file)
    param_csv = Path(args.param_csv)
    if not ga_csv.is_file():
        print(f"GA file not found: {ga_csv}", file=sys.stderr)
        return 1

    effective, param_dict, col = _load_solution(args.solution, ga_csv, param_csv)
    in_sample, oos, is_mask, _, _, oos_mask = build_ga_training_bundle(
        param_dict,
        ga_start_date=str(param_dict["GA_START_DATE"]["value"]),
        ga_end_date=str(param_dict["GA_END_DATE"]["value"]),
        data_splits=float(param_dict["DATA_SPLITS"]["value"]),
        data_size=int(param_dict["DATA_SIZE"]["value"] or 0),
        use_interleaved=str(param_dict["USE_INTERLEAVED_SPLIT"]["value"]).lower()
        in ("true", "1", "yes"),
        num_periods=int(param_dict["NUM_SPLIT_PERIODS"]["value"]),
        verbose=False,
    )

    print(f"Solution column: {col}")
    print(f"Window: {param_dict['GA_START_DATE']['value']} -> {param_dict['GA_END_DATE']['value']}")
    print("(OOS replay uses full-history warmup + OOS mask, same as GA trade export.)")
    print()

    base_oos = _summarize(_run(effective, param_dict, oos, invert=False, mask=oos_mask))
    flip_oos = _summarize(_run(effective, param_dict, oos, invert=True, mask=oos_mask))
    base_is = _summarize(_run(effective, param_dict, in_sample, invert=False, mask=is_mask))
    flip_is = _summarize(_run(effective, param_dict, in_sample, invert=True, mask=is_mask))

    print("OOS (exported holdout slices):")
    _print_row("Baseline", base_oos)
    _print_row("Opposite", flip_oos)
    print(f"  Delta PnL: ${flip_oos['pnl'] - base_oos['pnl']:,.0f}")
    print()
    print("IS (interleaved in-sample slices, GA fitness path):")
    _print_row("Baseline", base_is)
    _print_row("Opposite", flip_is)
    print(f"  Delta PnL: ${flip_is['pnl'] - base_is['pnl']:,.0f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

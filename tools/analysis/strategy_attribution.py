#!/usr/bin/env python3
"""
CLI: four-quadrant strategy attribution report.

Example:
  python tools/analysis/strategy_attribution.py \\
    --trades Trend/output/genetic_trades_oos_2026-07-03-1.csv \\
    --output results/attribution_jul03.md
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.trade_attribution import (  # noqa: E402
    AttributionConfig,
    format_report_text,
    load_trades_csv,
    run_attribution,
    write_report_json,
    write_report_markdown,
)
from optimize import build_ga_training_bundle  # noqa: E402
from strategies.trend.parameters import load_params  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Four-quadrant entry/exit attribution with MFE/MAE diagnostics.",
    )
    p.add_argument(
        "--trades",
        required=True,
        help="Trade export CSV (entry/exit times, prices, direction, pnl, reason).",
    )
    p.add_argument(
        "--param-csv",
        default=str(ROOT / "strategies/trend/parameters/trend_strategy_params.csv"),
        help="Strategy param CSV for GA window and OOS mask.",
    )
    p.add_argument("--output", help="Write markdown report to this path.")
    p.add_argument("--json", help="Write JSON report to this path.")
    p.add_argument("--mc-runs", type=int, default=200)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--multiplier", type=float, default=50.0)
    p.add_argument("--transaction-cost", type=float, default=15.0)
    p.add_argument(
        "--strategy",
        default=os.environ.get("STRATEGY", "trend"),
        help="Strategy name (sets STRATEGY env for optimize imports).",
    )
    return p.parse_args()


def load_ga_context(param_csv: str):
    param_dict, _ = load_params(param_csv, return_dataframe=True)
    start = str(param_dict["GA_START_DATE"]["value"])
    end = str(param_dict["GA_END_DATE"]["value"])
    in_sample, _, is_mask, _, _, _ = build_ga_training_bundle(
        param_dict,
        ga_start_date=start,
        ga_end_date=end,
        data_splits=float(param_dict["DATA_SPLITS"]["value"]),
        data_size=int(param_dict["DATA_SIZE"]["value"] or 0),
        use_interleaved=str(param_dict["USE_INTERLEAVED_SPLIT"]["value"]).lower()
        in ("true", "1", "yes"),
        num_periods=int(param_dict["NUM_SPLIT_PERIODS"]["value"]),
        verbose=False,
    )
    return in_sample, ~is_mask


def main() -> int:
    args = parse_args()
    os.environ["STRATEGY"] = args.strategy

    trades_path = Path(args.trades)
    if not trades_path.is_file():
        print(f"Trades file not found: {trades_path}", file=sys.stderr)
        return 1

    print("Loading OHLCV and OOS mask...")
    ohlcv, oos_mask = load_ga_context(args.param_csv)
    trades = load_trades_csv(trades_path)

    cfg = AttributionConfig(
        point_multiplier=args.multiplier,
        transaction_cost=args.transaction_cost,
        mc_runs=args.mc_runs,
        seed=args.seed,
    )
    report = run_attribution(
        trades,
        ohlcv,
        oos_mask,
        source=str(trades_path),
        cfg=cfg,
    )
    text = format_report_text(report)
    print(text)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        write_report_markdown(report, out)
        print(f"\nWrote markdown: {out}")
    if args.json:
        jout = Path(args.json)
        jout.parent.mkdir(parents=True, exist_ok=True)
        write_report_json(report, jout)
        print(f"Wrote JSON: {jout}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

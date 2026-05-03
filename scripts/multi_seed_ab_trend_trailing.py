"""
Multi-seed A/B: Trend GA baseline (no Trailing Delay (minutes) row) vs context (full prod copy).

For each seed, runs baseline and context with the same --seed, isolated --run-tag, then
writes per-seed metrics and aggregate mean/median/std by arm.

Usage (from repo root):
  python scripts/multi_seed_ab_trend_trailing.py --seeds 101,202,303 --pop 80 --gen 5 --cores 4

Heuristic wall budgets (3 seeds => 6 serial legs); see scripts/multi_seed_ab_time_budget.txt:
  ~12h: --pop 58 --gen 58 --cores 12
  ~24h: --pop 82 --gen 82 --cores 12

Env:
  TRADING_DATA_CSV / TRADING_GA_NO_BROWSER forwarded to children.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _selected_column(df: pd.DataFrame) -> str:
    cols = [c for c in df.columns if c.startswith("Solution_")]
    sel = [c for c in cols if c.endswith("_SELECTED")]
    return sel[0] if sel else cols[0]


def _to_float(x) -> float:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return float("nan")
    s = str(x).strip()
    s = s.replace("$", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def extract_metrics(genetic_csv: Path) -> dict:
    df = pd.read_csv(genetic_csv)
    col = _selected_column(df)

    def cell(name: str):
        row = df[df["Name"] == name]
        return row[col].iloc[0] if len(row) else None

    def _cell_float(name: str) -> float:
        return _to_float(cell(name))

    return {
        "sortino_is": _cell_float("Sortino Ratio (IS aggregate)"),
        "pf_is": _cell_float("Profit Factor (IS aggregate)"),
        "pnl_is": cell("Total Profit ($) (IS aggregate)"),
        "pnl_is_num": _cell_float("Total Profit ($) (IS aggregate)"),
        "dd_is": cell("Max Drawdown ($) (IS aggregate)"),
        "dd_is_num": _cell_float("Max Drawdown ($) (IS aggregate)"),
        "trades_day_is": _cell_float("Avg Trades/Day (IS aggregate)"),
        "ppt_is": cell("Avg Profit/Trade ($) (IS aggregate)"),
        "ppt_is_num": _cell_float("Avg Profit/Trade ($) (IS aggregate)"),
        "sortino_oos": _cell_float("Aggregate OOS Sortino"),
        "pf_oos": _cell_float("Profit Factor (OOS aggregate)"),
        "pnl_oos": cell("Total Profit ($) (OOS aggregate)"),
        "pnl_oos_num": _cell_float("Total Profit ($) (OOS aggregate)"),
        "dd_oos": cell("Max Drawdown ($) (OOS aggregate)"),
        "dd_oos_num": _cell_float("Max Drawdown ($) (OOS aggregate)"),
        "trades_day_oos": _cell_float("Avg Trades/Day (OOS aggregate)"),
        "ppt_oos": cell("Avg Profit/Trade ($) (OOS aggregate)"),
        "ppt_oos_num": _cell_float("Avg Profit/Trade ($) (OOS aggregate)"),
    }


def _find_genetic_results(trend_params: Path, tag: str) -> Path:
    pat = f"genetic_results_*-{tag}.csv"
    matches = sorted(trend_params.glob(pat), key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        raise FileNotFoundError(f"No file matching {pat} under {trend_params}")
    return matches[0]


def _run_optimize(
    *,
    repo: Path,
    py: Path,
    optimize: Path,
    params: Path,
    seed: int,
    run_tag: str,
    pop: int,
    gen: int,
    cores: int,
    data_csv: str | None,
    log_path: Path,
) -> int:
    cmd = [
        str(py),
        str(optimize),
        "--strategy",
        "trend",
        "--fresh",
        "--cores",
        str(cores),
        "--gen",
        str(gen),
        "--pop",
        str(pop),
        "--seed",
        str(seed),
        "--params",
        str(params),
        "--run-tag",
        run_tag,
    ]
    if data_csv:
        cmd += ["--data-csv", data_csv]

    env = os.environ.copy()
    env.setdefault("TRADING_GA_NO_BROWSER", "1")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8", errors="replace") as logf:
        p = subprocess.run(
            cmd,
            cwd=str(repo),
            env=env,
            stdout=logf,
            stderr=subprocess.STDOUT,
        )
    return p.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="Multi-seed trailing A/B (baseline vs context)")
    ap.add_argument("--repo", type=Path, default=_repo_root(), help="Trading repo root")
    ap.add_argument("--seeds", type=str, default="101,202,303", help="Comma-separated integers")
    ap.add_argument("--pop", type=int, default=80)
    ap.add_argument("--gen", type=int, default=5)
    ap.add_argument("--cores", type=int, default=4)
    ap.add_argument(
        "--parallel-legs",
        action="store_true",
        help="Run baseline+context in parallel per seed (uses ~2x cores during each seed)",
    )
    args = ap.parse_args()

    repo = args.repo.resolve()
    seeds = [int(x.strip()) for x in args.seeds.split(",") if x.strip()]
    if not seeds:
        print("No seeds", file=sys.stderr)
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    outdir = repo / "results" / f"multi_seed_ab_{stamp}"
    outdir.mkdir(parents=True, exist_ok=True)

    prod = repo / "strategies" / "trend" / "parameters" / "trend_strategy_params.csv"
    if not prod.is_file():
        print(f"Missing {prod}", file=sys.stderr)
        return 2

    baseline_csv = outdir / "baseline_params.csv"
    context_csv = outdir / "context_params.csv"
    context_csv.write_text(prod.read_text(encoding="utf-8"), encoding="utf-8")
    lines = prod.read_text(encoding="utf-8").splitlines()
    baseline_lines = [ln for ln in lines if not re.match(r"^Trailing Delay \(minutes\),", ln)]
    baseline_csv.write_text("\n".join(baseline_lines) + "\n", encoding="utf-8")

    py = repo / "venv" / "Scripts" / "python.exe"
    if not py.is_file():
        py = Path(sys.executable)
    optimize = repo / "optimize.py"
    trend_params = repo / "Trend" / "parameters"
    data_csv = os.environ.get("TRADING_DATA_CSV")

    meta = [
        f"multi_seed_ab_trailing",
        f"utc_stamp: {stamp}",
        f"repo: {repo}",
        f"seeds: {seeds}",
        f"pop: {args.pop}  gen: {args.gen}  cores: {args.cores}",
        f"parallel_legs: {args.parallel_legs}",
        f"TRADING_GA_NO_BROWSER: {os.environ.get('TRADING_GA_NO_BROWSER', '1 (set by child env default)')}",
    ]
    if data_csv:
        meta.append(f"TRADING_DATA_CSV: {data_csv}")
    (outdir / "RUN_META.txt").write_text("\n".join(meta) + "\n", encoding="utf-8")

    rows = []
    for seed in seeds:
        tag_b = f"ms_{stamp}_s{seed}_baseline"
        tag_c = f"ms_{stamp}_s{seed}_context"
        log_b = outdir / "logs" / f"seed_{seed}_baseline.log"
        log_c = outdir / "logs" / f"seed_{seed}_context.log"

        if args.parallel_legs:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def run_b():
                return "baseline", _run_optimize(
                    repo=repo,
                    py=py,
                    optimize=optimize,
                    params=baseline_csv,
                    seed=seed,
                    run_tag=tag_b,
                    pop=args.pop,
                    gen=args.gen,
                    cores=args.cores,
                    data_csv=data_csv,
                    log_path=log_b,
                )

            def run_c():
                return "context", _run_optimize(
                    repo=repo,
                    py=py,
                    optimize=optimize,
                    params=context_csv,
                    seed=seed,
                    run_tag=tag_c,
                    pop=args.pop,
                    gen=args.gen,
                    cores=args.cores,
                    data_csv=data_csv,
                    log_path=log_c,
                )

            with ThreadPoolExecutor(max_workers=2) as ex:
                futs = [ex.submit(run_b), ex.submit(run_c)]
                rc = {}
                for fut in as_completed(futs):
                    name, code = fut.result()
                    rc[name] = code
            if rc.get("baseline", 1) != 0 or rc.get("context", 1) != 0:
                print(f"Seed {seed} failed: exit codes {rc}", file=sys.stderr)
                return 1
        else:
            rc_b = _run_optimize(
                repo=repo,
                py=py,
                optimize=optimize,
                params=baseline_csv,
                seed=seed,
                run_tag=tag_b,
                pop=args.pop,
                gen=args.gen,
                cores=args.cores,
                data_csv=data_csv,
                log_path=log_b,
            )
            if rc_b != 0:
                print(f"Seed {seed} baseline failed: {rc_b}", file=sys.stderr)
                return 1
            rc_c = _run_optimize(
                repo=repo,
                py=py,
                optimize=optimize,
                params=context_csv,
                seed=seed,
                run_tag=tag_c,
                pop=args.pop,
                gen=args.gen,
                cores=args.cores,
                data_csv=data_csv,
                log_path=log_c,
            )
            if rc_c != 0:
                print(f"Seed {seed} context failed: {rc_c}", file=sys.stderr)
                return 1

        path_b = _find_genetic_results(trend_params, tag_b)
        path_c = _find_genetic_results(trend_params, tag_c)
        m_b = extract_metrics(path_b)
        m_c = extract_metrics(path_c)

        rows.append(
            {
                "seed": seed,
                "arm": "baseline",
                "genetic_results": str(path_b.relative_to(repo)),
                **{f"metric_{k}": v for k, v in m_b.items()},
            }
        )
        rows.append(
            {
                "seed": seed,
                "arm": "context",
                "genetic_results": str(path_c.relative_to(repo)),
                **{f"metric_{k}": v for k, v in m_c.items()},
            }
        )

    per = pd.DataFrame(rows)
    per_path = outdir / "per_seed_metrics.csv"
    per.to_csv(per_path, index=False)

    num_cols = [
        "metric_sortino_is",
        "metric_pf_is",
        "metric_pnl_is_num",
        "metric_dd_is_num",
        "metric_trades_day_is",
        "metric_ppt_is_num",
        "metric_sortino_oos",
        "metric_pf_oos",
        "metric_pnl_oos_num",
        "metric_dd_oos_num",
        "metric_trades_day_oos",
        "metric_ppt_oos_num",
    ]
    agg = per.groupby("arm")[num_cols].agg(["mean", "median", "std"])
    agg_path = outdir / "aggregate_by_arm.csv"
    agg.to_csv(agg_path)

    print(per.to_string(index=False))
    print("\nWrote", per_path)
    print("Wrote", agg_path)
    print("Outdir:", outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

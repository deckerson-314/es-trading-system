"""
Two-phase Trend GA: phase A optimizes structure/filters; phase B freezes A at the
selected solution and optimizes exits/risk. Each phase uses --fresh (different genome size).

  python scripts/phased_ga_trend.py --phase-a-gen 40 --phase-b-gen 40 --cores 4

Optional: --phases-json scripts/phased_trend_phases.json (default uses that path if present).

Env: TRADING_DATA_CSV, TRADING_GA_NO_BROWSER (defaults to 1 for children).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from strategies.trend.phased_search import (  # noqa: E402
    DEFAULT_PHASE_A,
    DEFAULT_PHASE_B,
    build_phase1_dataframe,
    build_phase2_dataframe,
    load_phase_sets_json,
    validate_disjoint,
    winner_from_genetic_csv,
)


def _default_phases_json() -> Path:
    return REPO / "scripts" / "phased_trend_phases.json"


def _run_optimize(
    *,
    repo: Path,
    py: Path,
    params: Path,
    run_tag: str,
    pop: int,
    gen: int,
    cores: int,
    seed: int | None,
    data_csv: str | None,
    log_path: Path,
) -> int:
    cmd = [
        str(py),
        str(repo / "optimize.py"),
        "--strategy",
        "trend",
        "--fresh",
        "--cores",
        str(cores),
        "--gen",
        str(gen),
        "--pop",
        str(pop),
        "--params",
        str(params),
        "--run-tag",
        run_tag,
    ]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    if data_csv:
        cmd += ["--data-csv", data_csv]

    env = os.environ.copy()
    env.setdefault("TRADING_GA_NO_BROWSER", "1")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8", errors="replace") as logf:
        p = subprocess.run(cmd, cwd=str(repo), env=env, stdout=logf, stderr=subprocess.STDOUT)
    return p.returncode


def _find_genetic_results(trend_params: Path, tag: str) -> Path:
    pat = f"genetic_results_*-{tag}.csv"
    matches = sorted(trend_params.glob(pat), key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        raise FileNotFoundError(f"No file matching {pat} under {trend_params}")
    return matches[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="Phased Trend GA (structure then exits)")
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument(
        "--base-csv",
        type=Path,
        default=REPO / "strategies" / "trend" / "parameters" / "trend_strategy_params.csv",
    )
    ap.add_argument("--phases-json", type=Path, default=None, help="Override phase A/B gene lists")
    ap.add_argument("--outdir", type=Path, default=None, help="Defaults to results/phased_ga_<utc>")
    ap.add_argument("--phase-a-gen", type=int, default=60, help="Generations for phase A (structure)")
    ap.add_argument("--phase-b-gen", type=int, default=60, help="Generations for phase B (exits)")
    ap.add_argument("--pop-a", type=int, default=None, help="Override POP for phase A (else CSV)")
    ap.add_argument("--pop-b", type=int, default=None, help="Override POP for phase B (else CSV)")
    ap.add_argument("--cores", type=int, default=4)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    repo = args.repo.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    outdir = args.outdir or (repo / "results" / f"phased_ga_{stamp}")
    outdir.mkdir(parents=True, exist_ok=True)

    pj = args.phases_json
    if pj is None and _default_phases_json().is_file():
        pj = _default_phases_json()
    if pj is not None:
        phase_a, phase_b = load_phase_sets_json(Path(pj).resolve())
    else:
        phase_a, phase_b = DEFAULT_PHASE_A, DEFAULT_PHASE_B
    validate_disjoint(phase_a, phase_b)

    base_df = pd.read_csv(args.base_csv)
    phase1_df = build_phase1_dataframe(base_df, phase_a)
    p1_csv = outdir / "phase_a_params.csv"
    p2_csv = outdir / "phase_b_params.csv"
    phase1_df.to_csv(p1_csv, index=False)

    py = repo / "venv" / "Scripts" / "python.exe"
    if not py.is_file():
        py = Path(sys.executable)

    data_csv = os.environ.get("TRADING_DATA_CSV")
    tag_a = f"phased_{stamp}_p1"
    tag_b = f"phased_{stamp}_p2"

    pop_a = args.pop_a
    pop_b = args.pop_b
    if pop_a is None or pop_b is None:
        # Read POP_SIZE from base CSV row
        pop_row = base_df[base_df["Name"] == "POP_SIZE"]
        default_pop = int(pop_row["Value"].iloc[0]) if not pop_row.empty else 80
        pop_a = pop_a if pop_a is not None else default_pop
        pop_b = pop_b if pop_b is not None else default_pop

    meta_lines = [
        f"utc_stamp: {stamp}",
        f"repo: {repo}",
        f"base_csv: {args.base_csv}",
        f"phase_a: {sorted(phase_a)}",
        f"phase_b: {sorted(phase_b)}",
        f"phase_a_gen: {args.phase_a_gen}  pop: {pop_a}",
        f"phase_b_gen: {args.phase_b_gen}  pop: {pop_b}",
        f"cores: {args.cores}",
        f"seed: {args.seed}",
    ]
    if data_csv:
        meta_lines.append(f"TRADING_DATA_CSV: {data_csv}")
    (outdir / "RUN_META.txt").write_text("\n".join(meta_lines) + "\n", encoding="utf-8")

    rc_a = _run_optimize(
        repo=repo,
        py=py,
        params=p1_csv,
        run_tag=tag_a,
        pop=pop_a,
        gen=args.phase_a_gen,
        cores=args.cores,
        seed=args.seed,
        data_csv=data_csv,
        log_path=outdir / "logs" / "phase_a.log",
    )
    if rc_a != 0:
        print(f"Phase A failed with exit {rc_a}", file=sys.stderr)
        return 1

    trend_params = repo / "Trend" / "parameters"
    gpath = _find_genetic_results(trend_params, tag_a)
    winner = winner_from_genetic_csv(gpath)
    (outdir / "phase_a_genetic_results.txt").write_text(
        f"source: {gpath.relative_to(repo)}\n", encoding="utf-8"
    )

    phase2_df = build_phase2_dataframe(base_df, phase_a, phase_b, winner)
    phase2_df.to_csv(p2_csv, index=False)

    rc_b = _run_optimize(
        repo=repo,
        py=py,
        params=p2_csv,
        run_tag=tag_b,
        pop=pop_b,
        gen=args.phase_b_gen,
        cores=args.cores,
        seed=args.seed,
        data_csv=data_csv,
        log_path=outdir / "logs" / "phase_b.log",
    )
    if rc_b != 0:
        print(f"Phase B failed with exit {rc_b}", file=sys.stderr)
        return 1

    gpath_b = _find_genetic_results(trend_params, tag_b)
    (outdir / "phase_b_genetic_results.txt").write_text(
        f"source: {gpath_b.relative_to(repo)}\n", encoding="utf-8"
    )
    print(f"Done. Artifacts: {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

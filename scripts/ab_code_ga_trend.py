"""
Code A/B: run Trend GA from a baseline *git branch* vs the *current* checkout.

- **baseline** = same repo path as a `git worktree` on `--baseline-branch` (default: `master`).
  Uses that tree's `optimize.py` (and strategy code) exactly.
- **branch** = this checkout's `optimize.py`, with `--run-tag` so checkpoints/results do not
  collide with anything else under `Trend/parameters/`.

Same absolute `--params` CSV, same `--seed` / `--pop` / `--gen` / `--cores` for both arms.

The worktree must see the ES OHLC CSV. If `Bollinger/data/` is missing there, this script
creates a directory junction (Windows) or symlink (Unix) from the main repo's
`Bollinger/data` into the worktree.

Usage (from repo root, on your feature branch):
  python scripts/ab_code_ga_trend.py --seeds 101,202,303 --pop 12 --gen 2 --cores 8

Env:
  TRADING_GA_NO_BROWSER (default 1 in children)
  TRADING_DATA_CSV — optional absolute path; set for both arms if your data is not under
  Bollinger/data in the main repo.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Reuse metric extraction from the trailing CSV A/B script (no CSV manipulation there).
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import multi_seed_ab_trend_trailing as _ms  # noqa: E402

extract_metrics = _ms.extract_metrics
_find_genetic_results = _ms._find_genetic_results


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _current_branch(repo: Path) -> str:
    p = _git(repo, "rev-parse", "--abbrev-ref", "HEAD", check=True)
    return p.stdout.strip()


def _path_slash(p: Path) -> str:
    """Normalize for comparison with `git worktree list` (forward slashes)."""
    return str(p.resolve()).replace("\\", "/")


def _ensure_worktree(repo: Path, worktree: Path, branch: str) -> None:
    if worktree.is_dir() and (worktree / ".git").is_file():
        # Existing worktree: confirm it lists this path and branch matches
        wt = _git(repo, "worktree", "list", "--porcelain", check=True).stdout
        wt_norm = wt.replace("\\", "/")
        needle = _path_slash(worktree)
        if needle not in wt_norm and (needle.rstrip("/") not in wt_norm):
            raise SystemExit(
                f"Directory {worktree} exists but is not registered as a worktree for {repo}. "
                "Remove it or pick a different --worktree path."
            )
        br = _git(worktree, "rev-parse", "--abbrev-ref", "HEAD", check=True).stdout.strip()
        if br != branch:
            raise SystemExit(
                f"Worktree {worktree} is on branch {br!r}, expected {branch!r}. "
                f"Run: git -C {worktree} checkout {branch}"
            )
        return
    if worktree.exists():
        raise SystemExit(f"{worktree} exists and is not a valid worktree — remove or use --worktree")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    p = _git(repo, "worktree", "add", str(worktree), branch, check=False)
    if p.returncode != 0:
        raise SystemExit(
            f"git worktree add failed:\n{p.stderr or p.stdout}\n"
            f"If the branch {branch!r} is missing locally: git fetch && git branch {branch} origin/{branch}"
        )


def _default_data_csv(repo: Path) -> Path:
    env = os.environ.get("TRADING_DATA_CSV")
    if env:
        return Path(env).resolve()
    return (repo / "Bollinger" / "data" / "ES_full_1min_continuous_ratio_adjusted.csv").resolve()


def _ensure_worktree_data_link(repo: Path, worktree: Path, data_csv: Path) -> None:
    """So baseline optimize (relative Bollinger/data/...) finds the file from cwd=worktree."""
    wt_bollinger_data = worktree / "Bollinger" / "data"
    repo_bollinger_data = repo / "Bollinger" / "data"
    marker = wt_bollinger_data / "ES_full_1min_continuous_ratio_adjusted.csv"

    if marker.is_file():
        return

    repo_bollinger_data.mkdir(parents=True, exist_ok=True)
    wt_bollinger_data.parent.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        if wt_bollinger_data.exists():
            raise SystemExit(
                f"Cannot create junction: {wt_bollinger_data} already exists. Remove it or fix manually."
            )
        r = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(wt_bollinger_data), str(repo_bollinger_data)],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            raise SystemExit(f"mklink /J failed: {r.stderr or r.stdout}")
    else:
        if wt_bollinger_data.is_symlink() or wt_bollinger_data.is_dir():
            if wt_bollinger_data.resolve() == repo_bollinger_data.resolve():
                return
            raise SystemExit(f"Refusing to replace existing {wt_bollinger_data}")
        os.symlink(repo_bollinger_data, wt_bollinger_data, target_is_directory=True)


def _run_optimize(
    *,
    cwd: Path,
    py: Path,
    optimize_py: Path,
    params_abs: Path,
    seed: int,
    pop: int,
    gen: int,
    cores: int,
    run_tag: str | None,
    data_csv_cli: Path | None,
    data_csv_env: Path | None,
    log_path: Path,
) -> int:
    cmd = [
        str(py),
        str(optimize_py),
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
        str(params_abs),
    ]
    if run_tag:
        cmd += ["--run-tag", run_tag]
    supports = _optimize_supports(optimize_py)
    if data_csv_cli and "--data-csv" in supports:
        cmd += ["--data-csv", str(data_csv_cli)]

    env = os.environ.copy()
    env.setdefault("TRADING_GA_NO_BROWSER", "1")
    if data_csv_env:
        env["TRADING_DATA_CSV"] = str(data_csv_env)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8", errors="replace") as logf:
        p = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=logf,
            stderr=subprocess.STDOUT,
        )
    return p.returncode


def _optimize_supports(optimize_py: Path) -> set[str]:
    text = optimize_py.read_text(encoding="utf-8", errors="replace")
    flags: set[str] = set()
    if "'--data-csv'" in text or '"--data-csv"' in text:
        flags.add("--data-csv")
    if "'--run-tag'" in text or '"--run-tag"' in text:
        flags.add("--run-tag")
    return flags


def _newest_genetic_csv(params_dir: Path, after_mono: float) -> Path:
    cands = [
        p
        for p in params_dir.glob("genetic_results_*.csv")
        if p.stat().st_mtime >= after_mono - 3.0
    ]
    if not cands:
        cands = list(params_dir.glob("genetic_results_*.csv"))
    if not cands:
        raise FileNotFoundError(f"No genetic_results_*.csv under {params_dir}")
    return max(cands, key=lambda p: p.stat().st_mtime)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="A/B Trend GA: baseline-branch code (worktree) vs current branch code"
    )
    ap.add_argument("--repo", type=Path, default=_repo_root())
    ap.add_argument("--baseline-branch", type=str, default="master", help="Git branch for baseline code")
    ap.add_argument(
        "--worktree",
        type=Path,
        default=None,
        help="Path for git worktree (default: sibling dir <reponame>_wt_<branch>)",
    )
    ap.add_argument("--seeds", type=str, default="101,202,303")
    ap.add_argument("--pop", type=int, default=12)
    ap.add_argument("--gen", type=int, default=2)
    ap.add_argument("--cores", type=int, default=4)
    ap.add_argument(
        "--params",
        type=Path,
        default=None,
        help="Absolute path to trend param CSV shared by both arms (default: repo strategies/.../trend_strategy_params.csv)",
    )
    args = ap.parse_args()

    repo = args.repo.resolve()
    head = _current_branch(repo)
    if head == args.baseline_branch:
        print(
            f"Current branch is {head!r}, same as --baseline-branch. "
            "Checkout your feature branch first (or use a different baseline).",
            file=sys.stderr,
        )
        return 2

    wt = args.worktree
    if wt is None:
        slug = args.baseline_branch.replace("/", "_")
        wt = repo.parent / f"{repo.name}_wt_{slug}"
    else:
        wt = wt.resolve()

    params_abs = (args.params or (repo / "strategies" / "trend" / "parameters" / "trend_strategy_params.csv")).resolve()
    if not params_abs.is_file():
        print(f"Missing params file: {params_abs}", file=sys.stderr)
        return 2

    data_csv = _default_data_csv(repo)
    if not data_csv.is_file():
        print(f"Missing GA data CSV: {data_csv}", file=sys.stderr)
        return 2

    _ensure_worktree(repo, wt, args.baseline_branch)
    _ensure_worktree_data_link(repo, wt, data_csv)

    py = repo / "venv" / "Scripts" / "python.exe"
    if not py.is_file():
        py = Path(sys.executable)

    optimize_repo = repo / "optimize.py"
    optimize_wt = wt / "optimize.py"
    if not optimize_wt.is_file():
        print(f"Missing {optimize_wt}", file=sys.stderr)
        return 2

    trend_params_repo = repo / "Trend" / "parameters"
    trend_params_wt = wt / "Trend" / "parameters"

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    outdir = repo / "results" / f"ab_code_ga_{stamp}"
    outdir.mkdir(parents=True, exist_ok=True)

    seeds = [int(x.strip()) for x in args.seeds.split(",") if x.strip()]
    if not seeds:
        print("No seeds", file=sys.stderr)
        return 2

    meta = [
        "ab_code_ga_trend (baseline branch code vs current branch code)",
        f"utc_stamp: {stamp}",
        f"repo: {repo}",
        f"current_branch (branch arm): {head}",
        f"baseline_branch (baseline arm): {args.baseline_branch}",
        f"worktree: {wt}",
        f"shared_params: {params_abs}",
        f"data_csv: {data_csv}",
        f"seeds: {seeds}",
        f"pop: {args.pop}  gen: {args.gen}  cores: {args.cores}",
    ]
    (outdir / "RUN_META.txt").write_text("\n".join(meta) + "\n", encoding="utf-8")

    rows: list[dict] = []
    data_arg = data_csv if data_csv.exists() else None

    for seed in seeds:
        tag_b = f"abcode_{stamp}_s{seed}_baseline_{args.baseline_branch.replace('/', '_')}"
        tag_c = f"abcode_{stamp}_s{seed}_branch_{head.replace('/', '_')}"

        log_b = outdir / "logs" / f"seed_{seed}_baseline.log"
        log_c = outdir / "logs" / f"seed_{seed}_branch.log"

        wt_supports = _optimize_supports(optimize_wt)
        repo_supports = _optimize_supports(optimize_repo)
        baseline_run_tag = tag_b if "--run-tag" in wt_supports else None

        t0_wall = time.time()
        rc_b = _run_optimize(
            cwd=wt,
            py=py,
            optimize_py=optimize_wt,
            params_abs=params_abs,
            seed=seed,
            pop=args.pop,
            gen=args.gen,
            cores=args.cores,
            run_tag=baseline_run_tag,
            data_csv_cli=data_arg if "--data-csv" in wt_supports else None,
            data_csv_env=data_arg,
            log_path=log_b,
        )
        if rc_b != 0:
            print(f"Seed {seed} baseline ({args.baseline_branch}) failed: {rc_b}", file=sys.stderr)
            return 1

        if baseline_run_tag:
            path_b = _find_genetic_results(trend_params_wt, tag_b)
        else:
            path_b = _newest_genetic_csv(trend_params_wt, t0_wall)

        rc_c = _run_optimize(
            cwd=repo,
            py=py,
            optimize_py=optimize_repo,
            params_abs=params_abs,
            seed=seed,
            pop=args.pop,
            gen=args.gen,
            cores=args.cores,
            run_tag=tag_c,
            data_csv_cli=data_arg if "--data-csv" in repo_supports else None,
            data_csv_env=data_arg,
            log_path=log_c,
        )
        if rc_c != 0:
            print(f"Seed {seed} branch ({head}) failed: {rc_c}", file=sys.stderr)
            return 1

        path_c = _find_genetic_results(trend_params_repo, tag_c)

        m_b = extract_metrics(path_b)
        m_c = extract_metrics(path_c)

        rows.append(
            {
                "seed": seed,
                "arm": f"baseline_{args.baseline_branch}",
                "genetic_results": str(path_b.relative_to(wt)),
                **{f"metric_{k}": v for k, v in m_b.items()},
            }
        )
        rows.append(
            {
                "seed": seed,
                "arm": f"branch_{head}",
                "genetic_results": str(path_c.relative_to(repo)),
                **{f"metric_{k}": v for k, v in m_c.items()},
            }
        )

    per = pd.DataFrame(rows)
    per_path = outdir / "per_seed_metrics.csv"
    per.to_csv(per_path, index=False)

    # Only *_num / float metrics — formatted $ columns break groupby mean.
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
    num_cols = [c for c in num_cols if c in per.columns]
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

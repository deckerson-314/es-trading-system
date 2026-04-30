#!/usr/bin/env python3
"""
Fair comparison: load GA params once (current backtest.load_ga_params), pickle them,
then run the same pickled dict through backtest.run_backtest in two repo roots
(e.g. current vs git worktree at 7cd832e).

Does not change your branch; creates/removes a sibling worktree by default.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import subprocess
import sys


def _param_fingerprint(params: dict) -> str:
    """Stable hash over sorted keys and primitive values (for logging only)."""
    flat = {}
    for k in sorted(params.keys()):
        if k == "verbose":
            continue
        v = params[k]
        if isinstance(v, dict) and "value" in v:
            flat[k] = v["value"]
        else:
            flat[k] = v
    blob = json.dumps(flat, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _ensure_worktree(trading_root: str, worktree: str, commit: str) -> None:
    if os.path.isdir(worktree):
        subprocess.run(
            ["git", "worktree", "remove", worktree, "--force"],
            cwd=trading_root,
            check=False,
        )
    subprocess.run(
        ["git", "worktree", "add", worktree, commit],
        cwd=trading_root,
        check=True,
    )


def _run_pickled(venv_py: str, runner: str, repo_root: str, pkl: str, strategy: str, data: str, start: str, end: str) -> dict[str, float]:
    cmd = [venv_py, runner, repo_root, pkl, strategy, data, start, end]
    out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
    lines = [x.strip() for x in out.splitlines() if "=" in x]
    kv = {}
    for ln in lines:
        a, b = ln.split("=", 1)
        kv[a] = float(b) if a != "TRADES" else float(int(float(b)))
    return kv  # type: ignore[return-value]


def main() -> None:
    ap = argparse.ArgumentParser(description="Fair backtest A/B with identical pickled params.")
    ap.add_argument("--trading-root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--worktree", default="", help="Path for baseline checkout (default: sibling Trading_cmp_<short>)")
    ap.add_argument("--commit", default="7cd832e")
    ap.add_argument("--strategy", default="trend")
    ap.add_argument("--data", required=True)
    ap.add_argument("--ga-file", required=True)
    ap.add_argument("--solution", type=int, default=159)
    ap.add_argument("--start", default="2020-01-02")
    ap.add_argument("--end", default="2020-07-14")
    ap.add_argument("--keep-worktree", action="store_true")
    args = ap.parse_args()

    root = os.path.abspath(args.trading_root)
    short = args.commit[:7]
    wt = args.worktree or os.path.join(os.path.dirname(root), f"Trading_cmp_{short}")
    venv_py = os.path.join(root, "venv", "Scripts", "python.exe")
    if not os.path.isfile(venv_py):
        print("Missing venv python:", venv_py, file=sys.stderr)
        sys.exit(1)
    runner = os.path.join(root, "tools", "_run_pickled_backtest.py")
    pkl = os.path.join(root, "results", f"fair_compare_sol{args.solution}_{short}.pkl")

    os.makedirs(os.path.join(root, "results"), exist_ok=True)

    _ensure_worktree(root, wt, args.commit)

    old_cwd = os.getcwd()
    try:
        sys.path.insert(0, root)
        os.chdir(root)
        from backtest import load_ga_params  # noqa: E402

        params, col = load_ga_params(args.ga_file, args.solution)
        params.pop("verbose", None)
        fp = _param_fingerprint(params)
        with open(pkl, "wb") as f:
            pickle.dump(params, f)
        print(f"Loaded {col}: {len(params)} keys, fingerprint={fp}")
        print(f"Pickle: {pkl}")
    finally:
        os.chdir(old_cwd)

    data_abs = os.path.abspath(args.data)
    cur = _run_pickled(venv_py, runner, root, pkl, args.strategy, data_abs, args.start, args.end)
    base = _run_pickled(venv_py, runner, wt, pkl, args.strategy, data_abs, args.start, args.end)

    print()
    print(f"{'Label':<12} {'PnL $':>14} {'Trades':>8} {'WR%':>8} {'PF':>8} {'MaxDD':>12}")
    print("-" * 62)
    for label, d in [("current", cur), (f"@{args.commit}", base)]:
        print(
            f"{label:<12} {d['TOTAL_PNL']:>14,.2f} {int(d['TRADES']):>8d} "
            f"{d['WIN_RATE']:>8.2f} {d['PF']:>8.3f} {d['MAX_DD']:>12,.2f}"
        )

    if not args.keep_worktree:
        subprocess.run(["git", "worktree", "remove", wt, "--force"], cwd=root, check=False)
        print(f"\nRemoved worktree: {wt}")
    else:
        print(f"\nKept worktree: {wt}")


if __name__ == "__main__":
    main()

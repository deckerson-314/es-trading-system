#!/usr/bin/env python3
"""
Run backtest.run_backtest with a pickled params dict (fair A/B across repo checkouts).

Usage:
  python _run_pickled_backtest.py <repo_root> <params.pkl> <strategy> <data_csv> [start] [end]
"""
import os
import pickle
import sys


def main() -> None:
    if len(sys.argv) < 6:
        print("Usage: _run_pickled_backtest.py <repo_root> <params.pkl> <strategy> <data_csv> [start] [end]", file=sys.stderr)
        sys.exit(2)
    root = os.path.abspath(sys.argv[1])
    pkl = os.path.abspath(sys.argv[2])
    strategy = sys.argv[3]
    data_csv = os.path.abspath(sys.argv[4])
    start = sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] else None
    end = sys.argv[6] if len(sys.argv) > 6 and sys.argv[6] else None

    sys.path.insert(0, root)
    os.chdir(root)

    from backtest import run_backtest  # noqa: E402

    with open(pkl, "rb") as f:
        params = pickle.load(f)

    r = run_backtest(
        strategy,
        data_csv,
        params,
        suppress_log=True,
        start_date=start,
        end_date=end,
    )
    n = len(r["trades_df"]) if r.get("trades_df") is not None else 0
    print(f"TOTAL_PNL={float(r.get('total_pnl', 0.0))}")
    print(f"TRADES={n}")
    print(f"WIN_RATE={float(r.get('win_rate', 0.0))}")
    print(f"PF={float(r.get('pf', 0.0))}")
    print(f"MAX_DD={float(r.get('max_dd', 0.0))}")


if __name__ == "__main__":
    main()

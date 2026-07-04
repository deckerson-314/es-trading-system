#!/usr/bin/env python3
"""
Legacy wrapper — prefer tools/analysis/strategy_attribution.py.

Runs RR-quadrant random-trading null + friction floor from Jul-03 defaults.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("STRATEGY", "trend")

from tools.analysis.strategy_attribution import load_ga_context, main as _full_main  # noqa: E402

GA_JUL03 = ROOT / "Trend/parameters/genetic_results_2026-07-03-1.csv"
TRADES = ROOT / "Trend/output/genetic_trades_oos_2026-07-03-1.csv"


def main() -> int:
    trades = TRADES if TRADES.is_file() else None
    if trades is None:
        print(f"Missing trade export: {TRADES}")
        print("Run: python tools/analysis/strategy_attribution.py --trades <path>")
        return 1
    sys.argv = [
        "strategy_attribution.py",
        "--trades",
        str(trades),
    ]
    return _full_main()


if __name__ == "__main__":
    raise SystemExit(main())

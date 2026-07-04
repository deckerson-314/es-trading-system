#!/usr/bin/env python3
"""
Legacy wrapper — prefer tools/analysis/strategy_attribution.py.

Runs full four-quadrant report on Jul-03 OOS export (includes MFE/MAE study).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("STRATEGY", "trend")

TRADES = ROOT / "Trend/output/genetic_trades_oos_2026-07-03-1.csv"


def main() -> int:
    from tools.analysis.strategy_attribution import main as _full_main

    if not TRADES.is_file():
        print(f"Missing trade export: {TRADES}")
        return 1
    sys.argv = ["strategy_attribution.py", "--trades", str(TRADES)]
    return _full_main()


if __name__ == "__main__":
    raise SystemExit(main())

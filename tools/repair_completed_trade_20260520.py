"""One-off repair: merge Broker Stop log reason into 2026-05-20 completed_trades row."""
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.completed_trades import dedupe_completed_trades_near_fills, merge_trade_records
from core.execution import _live_exit_type

LOG = "paper_logs/trend_paper_execution.log"
OUT = "paper_logs/completed_trades.json"
PAT = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \w+ TRADE CLOSE: (.*?) @ \$([0-9.]+), PNL: \$([0-9,.-]+)"
)


def _ser(t):
    o = dict(t)
    for k in ("entry_time", "exit_time"):
        v = o.get(k)
        if hasattr(v, "isoformat"):
            o[k] = v.isoformat()
    return o


def main():
    log_row = None
    with open(LOG, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = PAT.match(line.strip())
            if not m:
                continue
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            if ts.date() != datetime(2026, 5, 20).date():
                continue
            reason = m.group(2).strip()
            log_row = {
                "exit_time": ts,
                "exit_price": float(m.group(3)),
                "pnl": float(m.group(4).replace(",", "")),
                "reason": reason,
                "live_exit_type": _live_exit_type(reason),
            }

    if not log_row:
        print("No TRADE CLOSE line for 2026-05-20 in log")
        return

    csv_row = {
        "exit_time": datetime(2026, 5, 20, 9, 30, 0),
        "entry_time": datetime(2026, 5, 20, 8, 40, 8),
        "direction": "LONG",
        "qty": 1.0,
        "entry_price": 7410.5,
        "exit_price": 7394.5,
        "pnl": -800.0,
        "reason": "Backfilled (CSV Match)",
        "duration": "Backfilled",
        "report_url": "trades/trade_report_20260520_093000.html",
    }
    merged = merge_trade_records([csv_row, log_row])
    merged["duration"] = "49m 52s"

    existing = []
    if os.path.exists(OUT):
        with open(OUT, "r", encoding="utf-8") as f:
            existing = json.load(f)

    for i, t in enumerate(existing):
        if str(t.get("exit_time", "")).startswith("2026-05-20T09:30"):
            existing[i] = _ser(merged)
            break
    else:
        existing.append(_ser(merged))

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(existing[-1000:], f, indent=2)
    print(f"Updated: reason={merged['reason']}, live_exit_type={merged.get('live_exit_type')}")


if __name__ == "__main__":
    main()

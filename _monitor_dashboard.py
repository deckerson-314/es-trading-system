"""Periodic dashboard health check — run alongside main.py."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
CHART = os.path.join(ROOT, "web", "dashboard_paper_chart.json")
STATUS = os.path.join(ROOT, "web", "paper_status.js")
HTML = os.path.join(ROOT, "web", "dashboard_paper.html")
LOG = os.path.join(ROOT, "paper_logs", "trend_paper_execution.log")
INTERVAL_SEC = 60
ROUNDS = 10


def _mtime(path: str):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _check(round_n: int) -> dict:
    now = time.time()
    chart_m = _mtime(CHART)
    status_m = _mtime(STATUS)
    html_m = _mtime(HTML)

    chart_age = round(now - chart_m, 1) if chart_m else None
    status_age = round(now - status_m, 1) if status_m else None
    html_age = round(now - html_m, 1) if html_m else None

    donchian_ok = False
    seq = None
    pts = None
    last_bar = None
    try:
        with open(CHART, encoding="utf-8") as f:
            w = json.load(f)
        seq = w.get("write_seq")
        pts = w.get("chart_points")
        c = w.get("chart") or {}
        last_bar = (c.get("times") or [None])[-1]
        dh = c.get("donchian_high") or []
        donchian_ok = any(x is not None for x in dh)
    except Exception as exc:
        return {
            "round": round_n,
            "ok": False,
            "error": str(exc),
            "chart_age_sec": chart_age,
            "status_age_sec": status_age,
        }

    ok = (
        chart_age is not None
        and chart_age <= 90
        and status_age is not None
        and status_age <= 10
        and donchian_ok
        and pts and pts >= 2
    )
    return {
        "round": round_n,
        "ok": ok,
        "ts": datetime.now().strftime("%H:%M:%S"),
        "chart_seq": seq,
        "chart_pts": pts,
        "last_bar": last_bar,
        "donchian": donchian_ok,
        "chart_age_sec": chart_age,
        "status_age_sec": status_age,
        "html_age_sec": html_age,
    }


def main() -> int:
    print(f"Monitoring dashboard every {INTERVAL_SEC}s for {ROUNDS} rounds...", flush=True)
    fails = 0
    for i in range(1, ROUNDS + 1):
        if i > 1:
            time.sleep(INTERVAL_SEC)
        r = _check(i)
        line = (
            f"[{r.get('ts')}] round {i}/{ROUNDS} "
            f"ok={r.get('ok')} chart_age={r.get('chart_age_sec')}s "
            f"status_age={r.get('status_age_sec')}s seq={r.get('chart_seq')} "
            f"pts={r.get('chart_pts')} donchian={r.get('donchian')} "
            f"last_bar={r.get('last_bar')}"
        )
        if r.get("error"):
            line += f" ERR={r['error']}"
        print(line, flush=True)
        if not r.get("ok"):
            fails += 1
    print(f"Done: {ROUNDS - fails}/{ROUNDS} checks passed", flush=True)
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

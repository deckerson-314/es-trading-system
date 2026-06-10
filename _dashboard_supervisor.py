"""3-hour dashboard + bot supervisor — monitors, restarts, deduplicates main.py."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(ROOT, "venv", "Scripts", "python.exe")
MAIN = os.path.join(ROOT, "main.py")
CHART = os.path.join(ROOT, "web", "dashboard_paper_chart.json")
STATUS = os.path.join(ROOT, "web", "paper_status.js")
HTML = os.path.join(ROOT, "web", "dashboard_paper.html")
LOG = os.path.join(ROOT, "paper_logs", "dashboard_supervisor.log")
BOT_LOG = os.path.join(ROOT, "paper_logs", "trend_paper_execution.log")
LOCK = os.path.join(ROOT, "paper_logs", "bot_paper_4002.lock")

BOT_CMD = [
    PYTHON,
    MAIN,
    "--strategy",
    "trend",
    "--port",
    "4002",
    "--mode",
    "PAPER",
    "--output_dir",
    "paper_logs",
    "--client_id",
    "100",
]

DURATION_SEC = 3 * 60 * 60
INTERVAL_SEC = 60
CHART_MAX_AGE = 90
STATUS_MAX_AGE = 15
HTML_MAX_AGE_FLAT = 300


def _log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _mtime(path: str) -> float | None:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _list_main_pids() -> list[int]:
    try:
        out = subprocess.check_output(
            [
                "wmic",
                "process",
                "where",
                "CommandLine like '%main.py%' and CommandLine like '%4002%'",
                "get",
                "ProcessId",
            ],
            text=True,
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
        )
        pids = []
        for line in out.strip().splitlines()[1:]:
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
        return sorted(set(pids))
    except Exception as exc:
        _log(f"WARN list_main_pids failed: {exc}")
        return []


def _kill_pids(pids: list[int], reason: str) -> None:
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                check=False,
                capture_output=True,
            )
            _log(f"KILLED pid={pid} ({reason})")
        except Exception as exc:
            _log(f"WARN kill pid={pid} failed: {exc}")


def _check_dashboard() -> dict:
    now = time.time()
    chart_m = _mtime(CHART)
    status_m = _mtime(STATUS)
    html_m = _mtime(HTML)
    chart_age = round(now - chart_m, 1) if chart_m else None
    status_age = round(now - status_m, 1) if status_m else None
    html_age = round(now - html_m, 1) if html_m else None

    seq = None
    donchian_ok = False
    err = None
    try:
        with open(CHART, encoding="utf-8") as f:
            w = json.load(f)
        seq = w.get("write_seq")
        dh = (w.get("chart") or {}).get("donchian_high") or []
        donchian_ok = any(x is not None for x in dh)
    except Exception as exc:
        err = str(exc)

    ok = (
        err is None
        and chart_age is not None
        and chart_age <= CHART_MAX_AGE
        and status_age is not None
        and status_age <= STATUS_MAX_AGE
        and donchian_ok
    )
    return {
        "ok": ok,
        "chart_age": chart_age,
        "status_age": status_age,
        "html_age": html_age,
        "seq": seq,
        "donchian": donchian_ok,
        "error": err,
    }


def _start_bot() -> None:
    _log("START bot: " + " ".join(BOT_CMD))
    subprocess.Popen(
        BOT_CMD,
        cwd=ROOT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )


def _ensure_single_bot(force_restart: bool = False) -> int:
    pids = _list_main_pids()
    if len(pids) > 1:
        keep = min(pids)
        kill = [p for p in pids if p != keep]
        _kill_pids(kill, "duplicate bot")
        pids = [keep]
    if not pids or force_restart:
        if pids:
            _kill_pids(pids, "unhealthy restart")
            time.sleep(3)
        try:
            if os.path.isfile(LOCK):
                os.remove(LOCK)
        except OSError:
            pass
        _start_bot()
        time.sleep(25)
        pids = _list_main_pids()
    return len(pids)


def main() -> int:
    end = datetime.now() + timedelta(seconds=DURATION_SEC)
    _log(f"Supervisor started — runs until {end.strftime('%H:%M:%S')} ({DURATION_SEC // 3600}h)")
    round_n = 0
    fails = 0
    restarts = 0

    while datetime.now() < end:
        round_n += 1
        if round_n > 1:
            time.sleep(INTERVAL_SEC)

        bot_count = _ensure_single_bot(force_restart=False)
        health = _check_dashboard()
        line = (
            f"round={round_n} bots={bot_count} ok={health['ok']} "
            f"chart_age={health['chart_age']}s status_age={health['status_age']}s "
            f"html_age={health['html_age']}s seq={health['seq']} donchian={health['donchian']}"
        )
        if health.get("error"):
            line += f" err={health['error']}"
        _log(line)

        need_restart = False
        if bot_count == 0:
            need_restart = True
            _log("ACTION: no bot running")
        elif not health["ok"]:
            fails += 1
            if fails >= 2:
                need_restart = True
                _log("ACTION: dashboard unhealthy 2 rounds — restarting bot")
                fails = 0
        else:
            fails = 0
            html_age = health.get("html_age")
            if html_age is not None and html_age > HTML_MAX_AGE_FLAT:
                _log(f"NOTE: HTML stale ({html_age}s) — chart/status OK; light refresh should catch up")

        if need_restart:
            restarts += 1
            _ensure_single_bot(force_restart=True)

    _log(f"Supervisor finished after {round_n} rounds, {restarts} restarts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

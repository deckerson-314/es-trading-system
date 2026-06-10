"""Spawn main.py and verify Ctrl+C triggers cooperative shutdown within a timeout."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(ROOT, "main.py")
PYTHON = os.path.join(ROOT, "venv", "Scripts", "python.exe")
if not os.path.isfile(PYTHON):
    PYTHON = sys.executable
TIMEOUT_START_SEC = 90
SHUTDOWN_DEADLINE_SEC = 15
IB_PORT = os.environ.get("IB_TEST_PORT", "4002")


def _reader(stream, bucket: list[str]) -> None:
    for line in stream:
        bucket.append(line.rstrip("\n"))
        print(f"[bot] {line.rstrip()}")


def _send_interrupt(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        # Same mechanism as Ctrl+C in a shared console process group.
        proc.send_signal(signal.CTRL_C_EVENT)
    else:
        proc.send_signal(signal.SIGINT)


def main() -> int:
    cmd = [
        PYTHON,
        MAIN,
        "--strategy",
        "trend",
        "--port",
        IB_PORT,
        "--mode",
        "PAPER",
        "--output_dir",
        "paper_logs",
        "--client_id",
        "105",
    ]
    print("Starting bot:", " ".join(cmd))
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        env=env,
    )

    started = time.monotonic()
    ready_markers = (
        "Subscribed to market data",
        "[1-min bar]",
        "Running startup protection checks",
    )
    fail_markers = (
        "Failed to connect",
        "Connection error",
        "All client IDs",
    )

    ready = False
    while time.monotonic() - started < TIMEOUT_START_SEC:
        if proc.poll() is not None:
            print(f"Bot exited early with code {proc.returncode}")
            return proc.returncode or 1
        time.sleep(0.5)
        if time.monotonic() - started >= 35:
            ready = True
            break

    print("Sending Ctrl+C (SIGINT)...")
    try:
        _send_interrupt(proc)
    except Exception as exc:
        print(f"First interrupt failed: {exc}")
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
            print("Sent CTRL_BREAK_EVENT fallback.")
        except Exception as exc2:
            print(f"Fallback interrupt failed: {exc2}")

    deadline = time.monotonic() + SHUTDOWN_DEADLINE_SEC
    while time.monotonic() < deadline:
        code = proc.poll()
        if code is not None:
            print(f"Bot exited with code {code} in {time.monotonic() - started:.1f}s")
            return 0 if code in (0, 130) else 2
        time.sleep(0.2)

    print(f"Bot still running after {SHUTDOWN_DEADLINE_SEC}s — sending force kill.")
    proc.kill()
    proc.wait(timeout=5)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())

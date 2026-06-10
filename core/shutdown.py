"""Cooperative shutdown helpers for Ctrl+C while sync IB work runs on the event loop."""
from __future__ import annotations

import time as time_module
from typing import Callable, Optional

_shutdown_checker: Optional[Callable[[], bool]] = None


class ShutdownRequested(Exception):
    """Raised when Ctrl+C was requested during blocking startup/IB work."""


def register_shutdown_checker(checker: Callable[[], bool]) -> None:
    global _shutdown_checker
    _shutdown_checker = checker


def is_shutdown_requested() -> bool:
    checker = _shutdown_checker
    return bool(checker and checker())


def interruptible_sleep(seconds: float, step: float = 0.25) -> None:
    """Sleep in slices so Ctrl+C is honored during sync retry/backoff loops."""
    if seconds <= 0:
        return
    end = time_module.monotonic() + seconds
    while True:
        if is_shutdown_requested():
            raise ShutdownRequested()
        remaining = end - time_module.monotonic()
        if remaining <= 0:
            return
        time_module.sleep(min(step, remaining))

"""GA / backtest execution fidelity helpers (live-parity stop modeling)."""
from __future__ import annotations

import os
from typing import Any, Optional


def truthy_ga_flag(val) -> bool:
    if val is None or (isinstance(val, float) and __import__("pandas").isna(val)):
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return int(val) != 0
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _param_flag(param_dict_local: Optional[dict], key: str, env_key: str) -> bool:
    if param_dict_local and key in param_dict_local:
        return truthy_ga_flag(param_dict_local[key].get("value"))
    raw = os.environ.get(env_key, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def ga_pessimistic_stops_enabled(param_dict_local=None) -> bool:
    """Pessimistic stop sim: no same-bar trail+stop; market-style stop fills."""
    return _param_flag(param_dict_local, "GA_PESSIMISTIC_STOPS", "GA_PESSIMISTIC_STOPS")


def ga_conservative_stop_slippage_pts(param_dict_local=None) -> float:
    if param_dict_local and "GA_CONSERVATIVE_STOP_SLIPPAGE" in param_dict_local:
        v = param_dict_local["GA_CONSERVATIVE_STOP_SLIPPAGE"].get("value")
        if v is not None and not (isinstance(v, float) and __import__("pandas").isna(v)) and str(v).strip() != "":
            try:
                return max(0.0, float(v))
            except (TypeError, ValueError):
                pass
    raw = os.environ.get("GA_CONSERVATIVE_STOP_SLIPPAGE", "").strip()
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 0.0


def apply_conservative_stop_slippage(
    price: float, direction: int, reason: str, param_dict_local=None,
) -> float:
    slip = ga_conservative_stop_slippage_pts(param_dict_local)
    if slip <= 0 or not reason or "stop" not in str(reason).lower():
        return price
    return price - slip * int(direction)


def resolve_ga_stop_exit_price(
    price: float,
    direction: int,
    reason: str,
    row: Any,
    param_dict_local=None,
    *,
    stop_updated_same_bar: bool = False,
) -> float:
    """
    Adjust model stop exit price for GA fidelity.

    When pessimistic mode is on, stop exits fill at bar close (market backup)
    instead of the exact stop trigger — except same-bar trail+stop which the
    caller must skip entirely.
    """
    if not reason or "stop" not in str(reason).lower():
        return price
    if ga_pessimistic_stops_enabled(param_dict_local) and not stop_updated_same_bar:
        close = row.close if not isinstance(row, dict) else row.get("close")
        if close is not None:
            price = float(close)
    return apply_conservative_stop_slippage(price, direction, reason, param_dict_local)


def should_skip_same_bar_stop_after_trail(
    should_exit: bool,
    reason: Optional[str],
    stop_updated_same_bar: bool,
    param_dict_local=None,
) -> bool:
    """True when pessimistic sim should defer stop to next bar after trail ratchet."""
    if not should_exit or not reason:
        return False
    if "stop" not in str(reason).lower():
        return False
    return stop_updated_same_bar and ga_pessimistic_stops_enabled(param_dict_local)

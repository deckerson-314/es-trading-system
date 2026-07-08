"""GA / backtest execution fidelity helpers (live-parity stop modeling)."""

from __future__ import annotations



import os

from typing import Any, Optional



import pandas as pd





def truthy_ga_flag(val) -> bool:

    if val is None or (isinstance(val, float) and pd.isna(val)):

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





def _param_float(param_dict_local: Optional[dict], key: str, env_key: str) -> float:

    if param_dict_local and key in param_dict_local:

        v = param_dict_local[key].get("value")

        if v is not None and not (isinstance(v, float) and pd.isna(v)) and str(v).strip() != "":

            try:

                return max(0.0, float(v))

            except (TypeError, ValueError):

                pass

    raw = os.environ.get(env_key, "").strip()

    if not raw:

        return 0.0

    try:

        return max(0.0, float(raw))

    except (TypeError, ValueError):

        return 0.0





def ga_pessimistic_stops_enabled(param_dict_local=None) -> bool:

    """Pessimistic stop sim: no same-bar trail+stop; market-style stop fills."""

    return _param_flag(param_dict_local, "GA_PESSIMISTIC_STOPS", "GA_PESSIMISTIC_STOPS")





def ga_live_style_entry_enabled(param_dict_local=None) -> bool:

    """Enter at signal-bar close (live market-on-signal parity)."""

    return _param_flag(param_dict_local, "GA_LIVE_STYLE_ENTRY", "GA_LIVE_STYLE_ENTRY")





def ga_conservative_stop_slippage_pts(param_dict_local=None) -> float:

    return _param_float(param_dict_local, "GA_CONSERVATIVE_STOP_SLIPPAGE", "GA_CONSERVATIVE_STOP_SLIPPAGE")





def ga_conservative_entry_slippage_pts(param_dict_local=None) -> float:

    return _param_float(

        param_dict_local, "GA_CONSERVATIVE_ENTRY_SLIPPAGE", "GA_CONSERVATIVE_ENTRY_SLIPPAGE",

    )





def ga_conservative_channel_slippage_pts(param_dict_local=None) -> float:

    return _param_float(

        param_dict_local, "GA_CONSERVATIVE_CHANNEL_SLIPPAGE", "GA_CONSERVATIVE_CHANNEL_SLIPPAGE",

    )





def _row_close(row: Any) -> Optional[float]:

    if row is None:

        return None

    close = row.close if not isinstance(row, dict) else row.get("close")

    if close is None or (isinstance(close, float) and pd.isna(close)):

        return None

    return float(close)





def apply_conservative_entry_slippage(

    price: float, direction: int, param_dict_local=None,

) -> float:

    """Long entries pay more; short entries receive less (market vs bar-close)."""

    slip = ga_conservative_entry_slippage_pts(param_dict_local)

    if slip <= 0:

        return float(price)

    return float(price) + slip * int(direction)





def apply_conservative_stop_slippage(

    price: float, direction: int, reason: str, param_dict_local=None,

) -> float:

    slip = ga_conservative_stop_slippage_pts(param_dict_local)

    if slip <= 0 or not reason or "stop" not in str(reason).lower():

        return price

    return price - slip * int(direction)





def resolve_ga_channel_exit_price(

    trigger_price: float,

    direction: int,

    row: Any,

    param_dict_local=None,

) -> float:

    """

    Channel exit fill model: limit at trigger, market backup via bar close, then slip.



    Long exits (sell): min(trigger, close) - slip.

    Short exits (cover): max(trigger, close) + slip.

    """

    price = float(trigger_price)

    close = _row_close(row)

    if close is not None:

        if int(direction) == 1:

            price = min(price, close)

        else:

            price = max(price, close)

    slip = ga_conservative_channel_slippage_pts(param_dict_local)

    if slip > 0:

        price = price - slip * int(direction)

    return price





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

        close = _row_close(row)

        if close is not None:

            price = close

    return apply_conservative_stop_slippage(price, direction, reason, param_dict_local)





def resolve_ga_exit_price(

    price: float,

    direction: int,

    reason: str,

    row: Any,

    param_dict_local=None,

    *,

    stop_updated_same_bar: bool = False,

) -> float:

    """Unified exit fill model for GA / backtest / paper parity replay."""

    if not reason:

        return price

    reason_l = str(reason).lower()

    if "stop" in reason_l:

        return resolve_ga_stop_exit_price(

            price,

            direction,

            reason,

            row,

            param_dict_local,

            stop_updated_same_bar=stop_updated_same_bar,

        )

    if "channel" in reason_l:

        return resolve_ga_channel_exit_price(price, direction, row, param_dict_local)

    return price





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





def _align_ts_naive_et(ts):

    """Normalize timestamps to naive US/Eastern for bar-index comparisons."""

    if ts is None:

        return None

    t = pd.Timestamp(ts)

    if t.tz is not None:

        t = t.tz_convert("US/Eastern").tz_localize(None)

    return t





def eval_row_for_exit(position: dict, row: Any) -> Any:

    """

    Match live ``_eval_row_for_exit``: on the entry bar, clamp OHLC to close so

    historical wicks cannot instant-stop or channel-exit on the open fill bar.

    """

    entry_time = position.get("entry_time")

    bar_time = row.name if isinstance(row, pd.Series) else getattr(row, "Index", None)

    eval_row = row

    if entry_time and bar_time is not None:

        bar_ts = _align_ts_naive_et(bar_time)

        ent_ts = _align_ts_naive_et(entry_time)

        if bar_ts is not None and ent_ts is not None:

            ent_cmp = ent_ts.replace(second=0, microsecond=0)

            if bar_ts <= ent_cmp:

                if isinstance(row, pd.Series):

                    eval_row = row.copy()

                    eval_row["high"] = eval_row["low"] = eval_row["close"]

                elif hasattr(row, "_replace"):

                    c = float(row.close)

                    eval_row = row._replace(high=c, low=c)

                elif isinstance(row, dict):

                    eval_row = dict(row)

                    eval_row["high"] = eval_row["low"] = eval_row["close"]

    return eval_row





def simulate_bar_exit(
    strategy,
    pos: dict,
    row: Any,
    df: Any,
    param_dict_local=None,
) -> tuple[bool, Optional[str], Optional[float]]:
    """
    Evaluate one bar's exit for an open position (live-parity order and fill model).

    Returns ``(should_exit, reason, exit_price)``.
    """
    stop_updated = strategy.update_trailing_stop(pos, row, df)
    eval_row = eval_row_for_exit(pos, row)
    should_exit, reason, price = strategy.check_exit(pos, eval_row, df)
    if should_skip_same_bar_stop_after_trail(
        should_exit, reason, stop_updated, param_dict_local,
    ):
        return False, None, None
    if not should_exit:
        return False, None, None
    price = resolve_ga_exit_price(
        price,
        pos["direction"],
        reason,
        eval_row,
        param_dict_local,
        stop_updated_same_bar=stop_updated,
    )
    return True, reason, price


def bar_active_for_paper_bot(bar_time, active_ranges) -> bool:

    """True when ``bar_time`` falls inside a live bot subscription window."""

    if not active_ranges:

        return True

    ts = _align_ts_naive_et(bar_time)

    if ts is None:

        return True

    for start, end in active_ranges:

        if start <= ts <= end:

            return True

    return False



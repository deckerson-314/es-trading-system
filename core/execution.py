"""
core/execution.py - Trade Entry & Exit Logic
Ported from ib_deployment_v4.py lines 2250-3185
"""
import logging
import traceback
import time
import pandas as pd
import numpy as np
import os
import copy
from typing import Any, Optional
from datetime import datetime, timedelta, date
from core.charting import create_trade_chart
from ib_insync import MarketOrder, StopOrder, LimitOrder
import pytz

from core.account import get_account_summary, format_duration, add_to_live_tracker
from core.protection import (
    cancel_residual_orders_when_flat_on_contract,
    ensure_bracket_protective_stop,
    ensure_bracket_stop_armed,
    mark_trail_replace_grace,
    replace_oca_exit_pair_zero_gap,
    replace_trailing_stop_zero_gap,
    stop_order_is_armed,
    stop_order_is_pending,
    trail_replace_grace_active,
    trail_stop_protection_pending,
    wire_bracket_entry_from_ib,
    _find_protective_stop_trade_for_position,
    _find_trade_for_order,
    _ib_fill_to_naive_et,
)


def _finite_stop_scalar(x):
    try:
        v = float(x)
        if not np.isfinite(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def _quantize_es_tick(price):
    """Quarter-tick price for ES; ``None`` if not finite (avoids ``int(inf)`` inside IB)."""
    v = _finite_stop_scalar(price)
    if v is None:
        return None
    return round(float(v) * 4) / 4


def _es_synthetic_pnl_usd(entry_price, exit_price, direction, qty):
    """Gross futures PnL in USD from ES price move (× $50/pt × qty × direction)."""
    try:
        ep = float(entry_price or 0)
        xp = float(exit_price or 0)
        q = float(qty or 0)
        d = int(direction) if direction is not None else 1
        if ep <= 0 or xp <= 0 or q <= 0:
            return 0.0
        return (xp - ep) * float(d) * 50.0 * q
    except (TypeError, ValueError):
        return 0.0


def _pnl_from_fills_or_synthetic(fills, entry_price, exit_price, direction, qty, log_label="trade"):
    """
    Prefer sum(commissionReport.realizedPNL) when it matches price-based economics.
    Paper / FIFO / single-leg reports sometimes disagree with the open→close price path;
    in that case use synthetic gross minus commissions on these fills.
    """
    synthetic = _es_synthetic_pnl_usd(entry_price, exit_price, direction, qty)
    if not fills:
        return synthetic

    ib_parts = []
    comm = 0.0
    for f in fills:
        cr = getattr(f, "commissionReport", None)
        if cr is None:
            continue
        try:
            if getattr(cr, "commission", None) is not None:
                comm += float(cr.commission or 0)
        except (TypeError, ValueError):
            pass
        try:
            if getattr(cr, "realizedPNL", None) is not None:
                ib_parts.append(float(cr.realizedPNL))
        except (TypeError, ValueError):
            pass

    if not ib_parts:
        return synthetic - comm if comm else synthetic

    ib_net = float(sum(ib_parts))
    if not np.isfinite(ib_net):
        return synthetic - comm if comm else synthetic

    tol = max(35.0, 0.2 * max(abs(synthetic), abs(ib_net), 1.0))
    same_sign = (synthetic == 0.0) or (ib_net * synthetic >= 0.0)
    close_enough = abs(ib_net - synthetic) <= tol

    if same_sign and close_enough:
        return ib_net

    logging.warning(
        "%s PnL: IB realizedPNL sum (%.2f) vs price-based (%.2f); using synthetic minus "
        "commissions on this order (%.2f)",
        log_label,
        ib_net,
        synthetic,
        comm,
    )
    return synthetic - comm if comm else synthetic


def _wait_oca_pair_cancelled(ib, perm_stop: int, perm_tp: int, timeout: float = 5.0) -> str:
    """
    After ``cancelOrder`` on both legs of an OCA exit pair, wait until both are gone/cancelled
    or one fills. IB often cancels the sibling when only one leg is cancelled; we cancel both
    explicitly then wait here.
    """
    terminal = ("Cancelled", "Inactive", "ApiCancelled")

    def _status(perm: int):
        if perm <= 0:
            return None
        tr = next((t for t in ib.trades() if t.order.permId == perm), None)
        if not tr or not tr.orderStatus:
            return "missing"
        return getattr(tr.orderStatus, "status", "") or ""

    def _leg_done(perm: int, st):
        if perm <= 0:
            return True
        if st is None:
            return False
        if st == "Filled":
            return False  # handled separately
        return st in terminal or st == "missing"

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ss, ts = _status(perm_stop), _status(perm_tp)
        if ss == "Filled" or ts == "Filled":
            return "filled"
        if _leg_done(perm_stop, ss) and _leg_done(perm_tp, ts):
            return "cancelled"
        ib.sleep(0.12)
    return "timeout"


def _wait_oca_pair_cancelled_with_retries(
    ib, perm_stop: int, perm_tp: int, timeout: float = 5.0, max_attempts: int = 3,
) -> str:
    """Retry cancel-wait when IB is slow to acknowledge OCA leg cancellation."""
    last = "timeout"
    for attempt in range(1, max_attempts + 1):
        last = _wait_oca_pair_cancelled(ib, perm_stop, perm_tp, timeout=timeout)
        if last in ("cancelled", "filled"):
            return last
        if attempt < max_attempts:
            logging.warning(
                "OCA cancel wait attempt %s/%s outcome=%s; retrying",
                attempt, max_attempts, last,
            )
            ib.sleep(0.35)
    return last


def _exit_path(reason: str) -> str:
    """Normalized exit path for GA/live divergence analysis (architecture review P3)."""
    lit = _live_exit_type(reason)
    if lit == "software_stop_backup":
        return "software_backup"
    if lit == "broker_stop":
        return "broker_stop"
    if lit == "broker_tp":
        return "broker_tp"
    if "channel" in lit:
        return "channel_signal"
    if lit in ("maintenance", "rth"):
        return lit
    if lit == "trail_replace_pending":
        return "trail_replace_pending"
    return lit or "other"


def _exit_slippage_metrics(
    dir_: int,
    exit_price: float,
    working_stop: Optional[float],
    working_tp: Optional[float],
    reason: str,
    qty: float = 1.0,
    broker_stop_at_exit: Optional[float] = None,
    model_stop_at_exit: Optional[float] = None,
) -> dict:
    """
    Compare fill vs last known broker protective level (§9.3 reporting).
    Positive slippage_pts = better than reference for the position direction.
    """
    out = {
        "slippage_pts": None,
        "slippage_usd": None,
        "slippage_reference": None,
        "model_stop_at_exit": model_stop_at_exit if model_stop_at_exit is not None else working_stop,
        "broker_stop_at_exit": broker_stop_at_exit,
    }
    if exit_price <= 0:
        return out
    ref = None
    rlow = str(reason or "").lower()
    if working_stop and ("stop" in rlow or "broker stop" in rlow or "software" in rlow):
        ref = float(working_stop)
        out["slippage_reference"] = (
            "broker_stop" if "broker stop" in rlow else "model_stop"
        )
    elif working_tp and ("profit" in rlow or "broker take" in rlow):
        ref = float(working_tp)
        out["slippage_reference"] = "broker_tp"
    if ref is None:
        return out
    slip_pts = (exit_price - ref) * int(dir_)
    out["slippage_pts"] = round(slip_pts, 2)
    out["slippage_usd"] = round(slip_pts * 50.0 * float(qty or 1), 2)
    return out


def _broker_stop_trigger_price(stop_order):
    """
    Stop trigger level as IB reports on the order object (auxPrice / stopPrice).

    Do not merge with ``position_dict['stop']``: after a failed trail modify (e.g. IB
    10326) strategy memory can ratchet while the working order still shows the prior
    level — using the max for breach / PreSubmitted checks caused false manual closes.
    """
    if not stop_order:
        return None
    for attr in ("auxPrice", "stopPrice"):
        v = _finite_stop_scalar(getattr(stop_order, attr, None))
        if v is not None and v > 0:
            return v
    return None


def _effective_bracket_stop(stop_order, bracket, direction: int):
    """
    Single working stop level for live logic, snapshots, and reporting.

    Strategy exits use ``position_dict['stop']`` (includes trailing ratchet). IB
    ``StopOrder`` updates often land on ``stopPrice`` while ``auxPrice`` can stay
    at the original submission value — reading aux first made reports show the
    initial stop even when the strategy had trailed and exited near the true level.
    """
    candidates = []
    pd = (bracket or {}).get("position_dict") or {}
    v = _finite_stop_scalar(pd.get("stop"))
    if v is not None:
        candidates.append(v)
    if stop_order:
        for attr in ("stopPrice", "auxPrice"):
            v = _finite_stop_scalar(getattr(stop_order, attr, None))
            if v is not None:
                candidates.append(v)
    if not candidates:
        return None
    if direction == 1:
        return max(candidates)
    if direction == -1:
        return min(candidates)
    return candidates[0]


def _env_bool(name: str, default: bool = True) -> bool:
  """Read LIVE_* rollback flags from the environment."""
  raw = os.environ.get(name)
  if raw is None or str(raw).strip() == "":
    return default
  return str(raw).strip().lower() not in ("0", "false", "no", "off")


def broker_authoritative_exits_enabled() -> bool:
  """Phase 2: defer SL/TP to broker legs when active (see execution design §6)."""
  return _env_bool("LIVE_BROKER_AUTHORITATIVE_EXIT", True)


def strategy_bar_trailing_only() -> bool:
  """Phase 1: trail only on strategy bars unless explicitly disabled."""
  return _env_bool("LIVE_TRAIL_STRATEGY_BAR_ONLY", True)


def _protective_order_active(trade) -> bool:
  if not trade:
    return False
  if trade.isActive():
    return True
  st = getattr(trade.orderStatus, "status", "") if trade.orderStatus else ""
  return st in ("PreSubmitted", "Submitted", "PendingSubmit", "ApiPending")


def _live_exit_type(reason: str) -> str:
  """Map completed-trade reason strings to reporting vocabulary (§6.6)."""
  if not reason:
    return "unknown"
  r = str(reason)
  if r in ("Broker Stop", "Broker Take Profit", "Channel Exit (signal)",
           "Software Stop (backup)", "Maintenance Exit", "RTH Exit"):
    return r.lower().replace(" ", "_").replace("(", "").replace(")", "")
  if r.startswith("Strategy Exit ("):
    inner = r[len("Strategy Exit (") : -1]
    if inner == "Stop Loss":
      return "software_stop"
    if inner == "Take Profit":
      return "software_tp"
    if "Channel" in inner:
      return "channel_signal"
    return "strategy_signal"
  if r == "Stop Loss":
    return "broker_stop"
  if r == "Take Profit":
    return "broker_tp"
  if "Manual Close" in r or "PreSubmitted" in r:
    return "software_backup"
  if r.startswith("Maintenance"):
    return "maintenance"
  if r.startswith("RTH"):
    return "rth"
  return "other"


def _canonical_broker_fill_reason(reason: str) -> str:
  if reason == "Stop Loss":
    return "Broker Stop"
  if reason == "Take Profit":
    return "Broker Take Profit"
  return reason


def _model_stop_breached(dir_: int, price: float, stop_level: float) -> bool:
  if stop_level <= 0:
    return False
  return (price <= stop_level) if dir_ == 1 else (price >= stop_level)


def _eval_row_for_exit(bracket, latest_row):
  """Clamp entry-bar OHLC to close so historical wicks do not instant-stop."""
  entry_time = bracket.get("entry_time")
  bar_time = latest_row.name if hasattr(latest_row, "name") else None
  eval_row = latest_row
  if entry_time and bar_time:
    bar_ts = _align_ts_naive_et(bar_time)
    ent_ts = _align_ts_naive_et(entry_time)
    if bar_ts is not None and ent_ts is not None:
      ent_cmp = ent_ts.replace(second=0, microsecond=0) if hasattr(ent_ts, "replace") else ent_ts
      if bar_ts <= ent_cmp:
        if isinstance(latest_row, pd.Series):
          eval_row = latest_row.copy()
          eval_row["high"] = eval_row["low"] = eval_row["close"]
        elif isinstance(latest_row, dict):
          eval_row = latest_row.copy()
          eval_row["high"] = eval_row["low"] = eval_row["close"]
  return eval_row


def _handle_protective_backup(
    ib,
    bracket_contract,
    bracket,
    positions,
    completed_trades,
    live_tracker,
    send_email_fn,
    entry_trade,
    latest_row,
    data,
    strategy,
    stop_trade,
    dir_,
    stop_should_trigger: bool,
    stop_price_for_breach: float,
    trail_grace_active: bool = False,
) -> bool:
  """
  Backup flatten when price breached stop but the broker leg cannot protect.
  When broker-authoritative: defer to armed Submitted stops (industry standard).
  Returns True if a close was initiated.
  """
  if not stop_should_trigger:
    return False

  if trail_grace_active:
    st = stop_trade.orderStatus.status if stop_trade and stop_trade.orderStatus else "?"
    logging.info(
      "Protective backup deferred: awaiting broker stop arm "
      "(stop %.2f, status=%s)",
      stop_price_for_breach,
      st,
    )
    return False

  stop_armed = stop_order_is_armed(stop_trade)
  stop_status = stop_trade.orderStatus.status if stop_trade and stop_trade.orderStatus else None
  why_held = getattr(stop_trade.orderStatus, "whyHeld", "") if stop_trade and stop_trade.orderStatus else ""

  breach_px = latest_row.get("low") if dir_ == 1 else latest_row.get("high")
  if breach_px is None:
    breach_px = latest_row["close"]

  if broker_authoritative_exits_enabled():
    if stop_armed:
      logging.info(
        "Broker-authoritative: deferring protective backup to armed stop "
        "(breach %.2f vs stop %.2f, status=%s)",
        breach_px,
        stop_price_for_breach,
        stop_status,
      )
      return False
    if stop_order_is_pending(stop_trade) and "trigger" in str(why_held).lower():
      logging.warning(
        "Software Stop (backup): price %.2f breached stop %.2f; stop PreSubmitted "
        "(whyHeld=%s); forcing market close",
        breach_px,
        stop_price_for_breach,
        why_held or "trigger",
      )
      _force_close_position(
        ib, bracket_contract, bracket, positions, completed_trades,
        live_tracker, send_email_fn, entry_trade, latest_row["close"],
        "Software Stop (backup)", data=data, strategy=strategy,
      )
      return True
    logging.warning(
      "Software Stop (backup): price %.2f breached stop %.2f; stop not armed "
      "(%s / %s); forcing market close",
      breach_px,
      stop_price_for_breach,
      stop_status or "missing",
      why_held or "no whyHeld",
    )
    _force_close_position(
      ib, bracket_contract, bracket, positions, completed_trades,
      live_tracker, send_email_fn, entry_trade, latest_row["close"],
      "Software Stop (backup)", data=data, strategy=strategy,
    )
    return True

  # Legacy: PreSubmitted-only manual path
  if stop_status == "PreSubmitted" and "trigger" in str(why_held).lower():
    logging.warning(
      "CRITICAL: Stop %.2f breached, order PreSubmitted. Manual close.",
      stop_price_for_breach,
    )
    _force_close_position(
      ib, bracket_contract, bracket, positions, completed_trades,
      live_tracker, send_email_fn, entry_trade, latest_row["close"],
      "Manual Close (PreSubmitted Stop)", data=data, strategy=strategy,
    )
    return True
  return False


def _exit_channel_signal(
    ib,
    bracket_contract,
    bracket,
    positions,
    completed_trades,
    live_tracker,
    send_email_fn,
    entry_trade,
    exit_price_hint,
    data,
    strategy,
    dir_,
):
  """Channel / signal exit: cancel bracket legs, prefer limit at hint, else market."""
  stop_order = bracket.get("stopLoss")
  tp_order = bracket.get("takeProfit")
  for order in (stop_order, tp_order):
    if order:
      try:
        ib.cancelOrder(order)
      except Exception:
        pass
  ib.sleep(0.15)

  qty = 1.0
  if stop_order and hasattr(stop_order, "totalQuantity"):
    qty = abs(float(stop_order.totalQuantity or 1))
  close_action = "SELL" if dir_ == 1 else "BUY"
  hint = _quantize_es_tick(exit_price_hint) if exit_price_hint is not None else None
  used_limit = False
  if hint is not None and hint > 0:
    try:
      lmt = LimitOrder(action=close_action, totalQuantity=qty, lmtPrice=hint, tif="DAY", transmit=True)
      ib.placeOrder(bracket_contract, lmt)
      ib.sleep(1.5)
      es_pos = [p for p in ib.positions() if p.contract.conId == bracket_contract.conId]
      if not es_pos or es_pos[0].position == 0:
        used_limit = True
        latest_row = (
            data.iloc[-1]
            if data is not None and not data.empty
            else {"close": float(hint or 0)}
        )
        stop_trade, stop_order = _resolve_stop_trade_for_bracket(
            ib, bracket_contract, bracket,
        )
        tp_trade = (
            _find_trade_for_order(ib, bracket_contract, tp_order)
            if tp_order
            else None
        )
        _record_trade_close(
            ib, bracket_contract, bracket, entry_trade, stop_order, tp_order,
            stop_trade, tp_trade, dir_, latest_row, positions,
            completed_trades, live_tracker, send_email_fn, data,
            reason="Channel Exit (signal)", strategy=strategy,
        )
        return
    except Exception as e:
      logging.warning("Channel limit @ %.2f failed (%s); falling back to market", hint, e)

  if not used_limit:
    _force_close_position(
      ib, bracket_contract, bracket, positions, completed_trades,
      live_tracker, send_email_fn, entry_trade, hint or 0.0,
      "Channel Exit (signal)", data=data, strategy=strategy,
    )


def _handle_strategy_signal_exit(
    ib,
    bracket_contract,
    bracket,
    positions,
    completed_trades,
    live_tracker,
    send_email_fn,
    entry_trade,
    latest_row,
    data,
    strategy,
    stop_trade,
    tp_trade,
    dir_,
    exit_reason: str,
    exit_price_hint,
    stop_active: bool,
    tp_active: bool,
    trail_grace_active: bool = False,
    trail_ratchet_this_bar: bool = False,
) -> bool:
  """Route check_exit reasons; returns True if position close was initiated."""
  price = latest_row["close"]
  logging.info("STRATEGY SIGNAL EXIT: %s triggered @ %.2f", exit_reason, price)

  if exit_reason == "Stop Loss":
    if trail_grace_active:
      logging.info(
        "Deferring strategy Stop Loss: post-trail grace (model stop active)",
      )
      return False
    if trail_ratchet_this_bar:
      logging.info(
        "Deferring strategy Stop Loss: same bar as trail ratchet (bars_held=%s)",
        bracket.get("position_dict", {}).get("bars_held"),
      )
      return False

  if broker_authoritative_exits_enabled():
    stop_armed = stop_active  # caller passes stop_order_is_armed(stop_trade)
    if exit_reason == "Stop Loss" and stop_armed:
      st = stop_trade.orderStatus.status if stop_trade and stop_trade.orderStatus else "?"
      logging.info(
        "Broker-authoritative: deferring strategy Stop Loss to armed stop "
        "(status=%s); protective backup handles unarmed breach",
        st,
      )
      return False
    if exit_reason == "Stop Loss" and stop_trade and stop_order_is_pending(stop_trade):
      why_held = getattr(stop_trade.orderStatus, "whyHeld", "") if stop_trade.orderStatus else ""
      if "trigger" in str(why_held).lower():
        logging.info(
          "Deferring strategy Stop Loss: stop pending broker replace (whyHeld=%s)",
          why_held or "trigger",
        )
        return False
    if exit_reason == "Take Profit" and tp_active:
      st = tp_trade.orderStatus.status if tp_trade and tp_trade.orderStatus else "?"
      logging.info(
        "Broker-authoritative: deferring Take Profit to working limit (status=%s)",
        st,
      )
      return False
    if exit_reason == "Stop Loss":
      _force_close_position(
        ib, bracket_contract, bracket, positions, completed_trades,
        live_tracker, send_email_fn, entry_trade, price,
        "Software Stop (backup)", data=data, strategy=strategy,
      )
      return True
    if exit_reason == "Take Profit":
      _force_close_position(
        ib, bracket_contract, bracket, positions, completed_trades,
        live_tracker, send_email_fn, entry_trade, price,
        "Software Stop (backup)", data=data, strategy=strategy,
      )
      return True
    if exit_reason and "Channel" in exit_reason:
      _exit_channel_signal(
        ib, bracket_contract, bracket, positions, completed_trades,
        live_tracker, send_email_fn, entry_trade, exit_price_hint,
        data, strategy, dir_,
      )
      return True

  # Legacy soft exit for all signals
  _force_close_position(
    ib, bracket_contract, bracket, positions, completed_trades,
    live_tracker, send_email_fn, entry_trade, price,
    f"Strategy Exit ({exit_reason})", data=data, strategy=strategy,
  )
  return True


def _snapshot_strategy_params(strategy) -> dict:
    """Capture a stable, serializable parameter snapshot at entry time."""
    snap = {}
    try:
        if hasattr(strategy, "params_dict") and isinstance(strategy.params_dict, dict):
            snap = copy.deepcopy(strategy.params_dict)
        else:
            attrs = [
                "timeframe", "lookback_buy", "lookback_sell", "initial_sl_pct", "tp_mult_atr",
                "enable_trailing", "atr_mult_ts", "atr_length_ts", "trailing_delay",
                "enable_adx_filter", "adx_period", "min_adx", "min_atr_points", "atr_filter_period",
                "enable_rsi_filter", "rsi_period", "rsi_max_buy", "rsi_min_sell",
                "enable_sma_filter", "sma_period", "enable_vol_filter", "vol_ma_length", "min_vol_mult",
                "enable_vwap_filter", "enable_rth_filter", "rth_start_str", "rth_end_str",
                "rth_exit_buffer_minutes", "enable_maintenance_filter",
                "daily_maintenance_start_str", "daily_maintenance_end_str",
                "weekend_maintenance_start_day", "weekend_maintenance_start_time_str",
                "weekend_maintenance_end_day", "weekend_maintenance_end_time_str",
                "maintenance_buffer_minutes",
            ]
            for name in attrs:
                if hasattr(strategy, name):
                    snap[name] = getattr(strategy, name)
    except Exception:
        return {}
    return snap


def _row_bool(row, key: str) -> bool:
    if isinstance(row, pd.Series):
        return bool(row.get(key, False))
    if isinstance(row, dict):
        return bool(row.get(key, False))
    return bool(getattr(row, key, False))


def _in_rth_flatten_window_wall_clock(strategy) -> bool:
    """True during [RTH_end - buffer, RTH_end): block new entries (matches flatten policy)."""
    if not getattr(strategy, 'enable_rth_filter', False):
        return False
    buf = int(getattr(strategy, 'rth_exit_buffer_minutes', 0) or 0)
    if buf <= 0:
        return False
    rth_end = getattr(strategy, 'rth_end', None)
    if rth_end is None:
        return False
    et = pytz.timezone('US/Eastern')
    now_t = datetime.now(et).time()
    ref = datetime.combine(date.today(), rth_end)
    start_buf = (ref - timedelta(minutes=buf)).time()
    return start_buf <= now_t < rth_end


def _align_ts_naive_et(ts):
    """Normalize bar/entry timestamps to naive US/Eastern for safe comparison."""
    if ts is None:
        return None
    t = pd.Timestamp(ts)
    if getattr(t, 'tzinfo', None) is not None:
        t = t.tz_convert('America/New_York').tz_localize(None)
    return t


_completed_trade_persist_hook = None


def register_completed_trade_persist_hook(fn) -> None:
    """Register callback to flush completed_trades to disk immediately after a close."""
    global _completed_trade_persist_hook
    _completed_trade_persist_hook = fn


def _invoke_completed_trade_persist_hook() -> None:
    fn = _completed_trade_persist_hook
    if not fn:
        return
    try:
        fn()
    except Exception as e:
        logging.error("completed_trades persist hook failed: %s", e, exc_info=True)


def _append_completed_trade_record(completed_trades: list, record: dict, max_keep: int = 1000) -> None:
    from core.completed_trades import merge_trade_records, same_fill_event

    for i, existing in enumerate(completed_trades):
        if same_fill_event(existing, record):
            completed_trades[i] = merge_trade_records([existing, record])
            if len(completed_trades) > max_keep:
                del completed_trades[:-max_keep]
            _invoke_completed_trade_persist_hook()
            return
    completed_trades.append(record)
    if len(completed_trades) > max_keep:
        del completed_trades[:-max_keep]
    _invoke_completed_trade_persist_hook()


def _find_entry_trade(ib, contract, order_id: int, perm_id: int):
    """Locate entry trade by orderId first, then permId."""
    for t in ib.trades():
        if t.contract.conId != contract.conId:
            continue
        if order_id and getattr(t.order, 'orderId', 0) == order_id:
            return t
        if perm_id and getattr(t.order, 'permId', 0) == perm_id:
            return t
    return None


def _entry_still_pending(entry_trade) -> bool:
    """True when parent entry has not completed fill (wait before exit/trail logic)."""
    if entry_trade is None:
        return True
    try:
        if entry_trade.filled():
            return False
    except Exception:
        pass
    try:
        st = (getattr(entry_trade.orderStatus, "status", None) or "").strip()
        if st == "Filled":
            return False
    except Exception:
        pass
    try:
        return bool(entry_trade.isActive())
    except Exception:
        return False


def _bracket_can_proceed_without_entry_trade(ib, bracket_contract, bracket) -> bool:
    """Adopted/restored bracket with live IB position — trail/exit without entry trade object."""
    if not bracket.get("position_verified"):
        return False
    return _ib_open_position_matches_bracket(ib, bracket_contract, bracket)


def _resolve_stop_trade_for_bracket(ib, bracket_contract, bracket):
    """
    Resolve the live IB stop trade for a bracket and refresh the tracked stop handle.

    ib.trades() can omit or stale-match protective legs after adopt/reconnect; fall back
    to position-scoped discovery so trailing can still sync to the broker.
    """
    stop_order = bracket.get("stopLoss")
    if not stop_order:
        return None, stop_order
    bc = bracket.get("contract") or bracket_contract
    trade = _find_trade_for_order(ib, bc, stop_order)
    if trade is None:
        direction = int(bracket.get("direction") or 0)
        try:
            for p in ib.positions():
                if getattr(p.contract, "conId", None) != getattr(bc, "conId", None):
                    continue
                pos = float(p.position or 0)
                if pos == 0:
                    continue
                if (direction > 0 and pos > 0) or (direction < 0 and pos < 0):
                    trade = _find_protective_stop_trade_for_position(ib, p)
                    break
        except Exception:
            trade = None
    if trade is not None:
        stop_order = trade.order
        bracket["stopLoss"] = stop_order
        live_perm = int(getattr(stop_order, "permId", 0) or 0)
        if live_perm:
            try:
                stop_order.permId = live_perm
            except Exception:
                pass
        px = _broker_stop_trigger_price(stop_order)
        if px is not None and px > 0:
            bracket["entry_stop_price"] = px
    return trade, stop_order


def _bracket_stop_is_actionable(stop_trade, stop_order, bracket) -> bool:
    """True when an open bracket has a working protective stop on IB (or a valid handle)."""
    if _protective_order_active(stop_trade):
        return True
    if bracket.get("position_verified"):
        px = _broker_stop_trigger_price(stop_order)
        if px is not None and px > 0:
            return True
    return False


def _wait_for_entry_fill(ib, contract, order_id: int, perm_id: int,
                         timeout_sec: float = 8.0, poll_sec: float = 0.25):
    """Poll until parent entry is filled or timeout (fast fills often arrive after first ib.sleep)."""
    deadline = time.monotonic() + timeout_sec
    trade = _find_entry_trade(ib, contract, order_id, perm_id)
    while time.monotonic() < deadline:
        if trade and trade.filled():
            return trade
        ib.sleep(poll_sec)
        trade = _find_entry_trade(ib, contract, order_id, perm_id)
    return trade if (trade and trade.filled()) else trade


def _send_trade_open_notification(
    bracket, direction: int, entry_price: float, stop_price: float, tp,
    qty: float, entry_time, ib, data, contract, send_email_fn, live_tracker,
    dashboard_state=None, strategy=None, positions=None,
) -> None:
    if bracket.get('open_notified'):
        return
    account = get_account_summary(ib, data, contract)
    contract_multiplier = 50
    risk_dollars = abs(entry_price - stop_price) * contract_multiplier * qty
    reward_dollars = abs(entry_price - tp) * contract_multiplier * qty if tp else None
    rr_ratio = reward_dollars / risk_dollars if (tp and risk_dollars > 0) else None

    msg_lines = [
        f"TRADE OPEN - {'LONG' if direction == 1 else 'SHORT'}",
        f"{'=' * 50}",
        f"Entry Price: ${entry_price:.2f}",
        f"Stop Loss: ${stop_price:.2f} (Risk: ${risk_dollars:,.2f})",
        f"Take Profit: ${tp:.2f} (Reward: ${reward_dollars:,.2f})" if tp else "Take Profit: None",
        f"Risk/Reward: {rr_ratio:.2f}:1" if rr_ratio else "Risk/Reward: N/A",
        f"Position Size: {qty} contract(s)",
        f"",
        f"Account: NetLiq=${account.get('NetLiquidation', 'N/A')}, "
        f"Cash=${account.get('TotalCashValue', 'N/A')}",
        f"Time: {entry_time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    dir_str = 'L' if direction == 1 else 'S'
    subj = f"[BB] O: {dir_str} {qty}@{entry_price:.2f}"
    send_email_fn(subj, "\n".join(msg_lines))
    tp_str = f"${tp:.2f}" if tp else "None"
    logging.info(
        f"TRADE OPEN: {'LONG' if direction == 1 else 'SHORT'} @ {entry_price:.2f}, "
        f"SL: {stop_price:.2f}, TP: {tp_str}"
    )
    if live_tracker is not None:
        add_to_live_tracker(
            live_tracker, 'trade',
            f"TRADE OPEN: {'LONG' if direction == 1 else 'SHORT'} @ ${entry_price:.2f}, SL: ${stop_price:.2f}",
        )
    bracket['open_notified'] = True
    if dashboard_state is not None:
        dashboard_state.request_full_refresh = True
    if strategy is not None and positions is not None:
        _confirm_bracket_stop_after_open(
            ib, contract, bracket, strategy, data, positions, live_tracker,
        )


def _confirm_bracket_stop_after_open(
    ib, contract, bracket, strategy, data, positions, live_tracker,
) -> None:
    """Verify broker stop leg survived entry; re-protect immediately if flat-book race removed it."""
    try:
        ensure_bracket_protective_stop(
            ib, contract, bracket, strategy, data, positions, live_tracker,
        )
    except Exception as e:
        logging.error("Post-open stop verification failed: %s", e)


def _maybe_send_trade_open_for_bracket(
    bracket, ib, contract, data, send_email_fn, live_tracker, dashboard_state=None,
    strategy=None, positions=None,
) -> None:
    """Deferred TRADE OPEN when fill lands after the entry-placement poll window."""
    if bracket.get('open_notified'):
        return
    entry_trade = _entry_trade_for_bracket(ib, contract, bracket)
    if not entry_trade or not entry_trade.filled() or not entry_trade.fills:
        return
    try:
        fill_px = float(entry_trade.fills[0].execution.price)
    except Exception:
        fill_px = float(bracket.get('entry_price') or 0)
    if fill_px > 0:
        bracket['entry_price'] = fill_px
    _send_trade_open_notification(
        bracket,
        int(bracket.get('direction') or 0),
        float(bracket.get('entry_price') or fill_px),
        float(bracket.get('entry_stop_price') or bracket.get('position_dict', {}).get('stop') or 0),
        bracket.get('entry_tp_price'),
        abs(float(getattr(bracket.get('stopLoss'), 'totalQuantity', 1) or 1)),
        bracket.get('entry_time') or datetime.now(),
        ib, data, contract, send_email_fn, live_tracker, dashboard_state,
        strategy=strategy, positions=positions,
    )


def _entry_trade_for_bracket(ib, contract, bracket, strategy=None) -> Optional[Any]:
    entry = bracket.get('entry')
    if not entry:
        return None
    bc = bracket.get('contract') or contract
    oid = int(bracket.get('entryOrderId') or getattr(entry, 'orderId', 0) or 0)
    perm = int(getattr(entry, 'permId', 0) or 0)
    trade = _find_entry_trade(ib, bc, oid, perm)
    if trade is not None:
        return trade
    if bracket.get('restored_from_ib') or bracket.get('adopted_foreign_client') is not None:
        try:
            for p in ib.positions():
                if getattr(p.contract, 'conId', None) == getattr(bc, 'conId', None) and p.position != 0:
                    wire_bracket_entry_from_ib(ib, p, bracket, strategy=strategy)
                    oid = int(bracket.get('entryOrderId') or getattr(entry, 'orderId', 0) or 0)
                    perm = int(getattr(bracket.get('entry'), 'permId', 0) or 0)
                    return _find_entry_trade(ib, bc, oid, perm)
        except Exception:
            pass
    return None


def _ib_open_position_matches_bracket(ib, contract, bracket) -> bool:
    """
    True when IB still reports an open futures position consistent with this bracket.

    Used so we never prune a bracket just because ib.trades() no longer lists the entry
    leg (cache/eviction) while the portfolio row is still non-flat.
    """
    direction = int(bracket.get('direction') or 0)
    if direction == 0 or contract is None:
        return False
    bc = bracket.get('contract') or contract
    try:
        want_id = int(getattr(bc, 'conId', 0) or getattr(contract, 'conId', 0) or 0)
    except (TypeError, ValueError):
        want_id = int(getattr(contract, 'conId', 0) or 0)
    if not want_id:
        return False
    try:
        for p in ib.positions():
            if getattr(p.contract, 'conId', 0) != want_id:
                continue
            pos = float(p.position or 0)
            if pos == 0:
                continue
            if (direction > 0 and pos > 0) or (direction < 0 and pos < 0):
                return True
    except Exception:
        pass
    return False


def _cancel_bracket_working_orders(ib, contract, bracket) -> None:
    """Best-effort cancel entry/SL/TP legs for a bracket being torn down."""
    targets = []
    for key in ('entry', 'stopLoss', 'takeProfit'):
        order = bracket.get(key)
        if order:
            targets.append((getattr(order, 'permId', 0), getattr(order, 'orderId', 0)))
    for trade in ib.trades():
        if trade.contract.conId != contract.conId:
            continue
        o = trade.order
        op, oid = getattr(o, 'permId', 0), getattr(o, 'orderId', 0)
        if not any((op and op == t[0]) or (oid and oid == t[1]) for t in targets):
            continue
        st = getattr(trade.orderStatus, 'status', '') or ''
        if trade.isActive() or st in ('Inactive', 'PreSubmitted', 'Submitted', 'PendingSubmit'):
            try:
                ib.cancelOrder(o)
            except Exception:
                pass


def purge_closed_brackets(positions, live_tracker=None) -> int:
    """Drop brackets already recorded as closed (ghost rows after channel exit races)."""
    if not positions:
        return 0
    n = 0
    for bracket in positions[:]:
        if not bracket.get("_close_recorded"):
            continue
        positions.remove(bracket)
        n += 1
    if n:
        logging.info("Purged %s closed bracket(s) from in-memory tracking", n)
        if live_tracker is not None:
            add_to_live_tracker(live_tracker, "info", f"Purged {n} closed bracket(s)")
    return n


def bracket_counts_as_open_exposure(ib, contract, bracket) -> bool:
    """True when a tracked bracket still represents live market risk."""
    if not bracket or bracket.get("_close_recorded"):
        return False
    if int(bracket.get("direction") or 0) == 0:
        return False
    trade = _entry_trade_for_bracket(ib, contract, bracket)
    if not (trade and trade.filled()):
        return False
    bracket_contract = bracket.get("contract", contract)
    if bracket_contract:
        try:
            for p in ib.positions():
                if p.contract.conId == bracket_contract.conId:
                    return abs(float(p.position or 0)) >= 1
        except Exception:
            pass
    return False


def prune_dead_brackets(ib, contract, positions, live_tracker=None) -> int:
    """
    Drop in-memory brackets whose entry never filled (cancelled/rejected parent).

    Without this, check_entries can append a bracket before fill, the entry is cancelled
    (e.g. flat-book cleanup), and the bot still thinks max_open_trades is reached while IB is flat.
    """
    if not contract or not positions:
        return 0
    now = datetime.now(pytz.utc)
    pruned = 0
    for bracket in positions[:]:
        try:
            trade = _entry_trade_for_bracket(ib, contract, bracket)
            if trade and trade.filled():
                continue
            if bracket.get('position_verified') or _ib_open_position_matches_bracket(ib, contract, bracket):
                continue
            guard_until = bracket.get('guard_until')
            if guard_until is not None:
                gu = guard_until if guard_until.tzinfo else pytz.utc.localize(guard_until)
                if now < gu:
                    continue
            if trade and trade.isActive():
                continue
            st = getattr(trade.orderStatus, 'status', 'no_trade') if trade else 'no_trade'
            _cancel_bracket_working_orders(ib, contract, bracket)
            positions.remove(bracket)
            pruned += 1
            d = bracket.get('direction')
            logging.warning(
                "Pruned dead bracket: entry never filled (status=%s, dir=%s)",
                st,
                'LONG' if d == 1 else 'SHORT' if d == -1 else d,
            )
            if live_tracker is not None:
                add_to_live_tracker(live_tracker, 'warning', f"Pruned unfilled bracket ({st})")
        except Exception as e:
            logging.warning("prune_dead_brackets: skipped one bracket (%s)", e, exc_info=True)
    return pruned


def _ohlcv_resample_for_timeframe(df: pd.DataFrame, timeframe_mins: int) -> pd.DataFrame:
    """Resample 1-minute OHLCV to strategy timeframe (same rules as core.monitoring.resample_data)."""
    base_cols = ['open', 'high', 'low', 'close', 'volume']
    for c in base_cols:
        if c not in df.columns:
            raise ValueError(f"Missing column {c} for resample")
    ohlcv = df[base_cols].copy()
    tf = max(1, int(timeframe_mins or 1))
    if tf <= 1:
        return ohlcv
    logic = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
    resampled = ohlcv.resample(f'{tf}min', closed='right', label='right').agg(logic)
    return resampled.dropna()


def check_entries(strategy, ib, contract, data, positions, params_dict, 
                  live_tracker, dashboard_state, send_email_fn, idx, latest_row):
    """Check entry signals and place bracket orders if triggered."""
    # --- Re-entrancy & Bar Debounce Guards ---
    if getattr(check_entries, 'is_processing', False):
        logging.debug("Entry check already in progress, skipping.")
        return
    
    if getattr(check_entries, 'last_idx', None) == idx:
        logging.debug(f"Already processed bar {idx} for entries. Skipping.")
        return

    sg = getattr(dashboard_state, "security_guard", None) if dashboard_state else None
    if sg is not None and getattr(sg, "flattened_today", False):
        logging.info(
            "Entry blocked: daily PnL emergency flatten active (no new trades until next session day)"
        )
        return

    from core.client_id_guard import trading_orders_allowed
    if not trading_orders_allowed():
        logging.error(
            "Entry blocked: clientId integrity halt — %s",
            getattr(dashboard_state, "client_id_violation_detail", None) or "see logs",
        )
        return

    # Extra Safety: Check for active orders for this contract to prevent double entry
    active_orders = [t for t in ib.trades() if t.contract.conId == contract.conId and t.isActive()]
    if active_orders:
        logging.info(f"Entry blocked: {len(active_orders)} active orders already exist for {contract.localSymbol}")
        return

    # --- Position Count Check (THE STORM FIX) ---
    max_trades = getattr(strategy, 'max_open_trades', 1)
    if len(positions) >= max_trades:
        logging.info(f"Entry blocked: Max trades ({len(positions)}/{max_trades}) already open")
        return

    if _in_rth_flatten_window_wall_clock(strategy):
        logging.info("Entry blocked: RTH end flatten window (wall-clock Eastern)")
        return
    if _row_bool(latest_row, 'force_exit_rth') or _row_bool(latest_row, 'force_exit'):
        logging.info("Entry blocked: force-exit window on signal row (RTH/maintenance)")
        return

    # --- Signal Check ---
    # Check filters
    in_maint = latest_row.get('in_maintenance', False)
    if not (latest_row.get('in_rth', True) and latest_row.get('atr_filter', True) and
            latest_row.get('volume_filter', True) and not in_maint):
        return

    # Strategy-agnostic entry check
    if hasattr(strategy, 'check_entry'):
        triggered, direction_str, _ = strategy.check_entry(latest_row, data)
        enter_long = triggered and direction_str == 'Long'
        enter_short = triggered and direction_str == 'Short'
    elif hasattr(strategy, 'calculate_entry_signals'):
        try:
            tf = max(1, int(getattr(strategy, 'timeframe', 1) or 1))
            htf = _ohlcv_resample_for_timeframe(data, tf)
            data_ind = strategy.calculate_indicators(htf.copy())
            if hasattr(strategy, 'apply_filters'):
                data_ind = strategy.apply_filters(data_ind)
            sigs = strategy.calculate_entry_signals(data_ind)
            if len(sigs) == 3:
                long_sig, short_sig, _ = sigs
            else:
                long_sig, short_sig = sigs
            if idx not in long_sig.index or idx not in short_sig.index:
                logging.debug(f"Entry signal index {idx} not in HTF signal range (tf={tf}).")
                return
            enter_long = bool(long_sig.loc[idx])
            enter_short = bool(short_sig.loc[idx])
        except Exception:
            logging.exception("calculate_entry_signals failed in check_entries")
            return
    else:
        return

    if not (enter_long or enter_short):
        return

    # Record this bar as processed once a signal is detected or we reach this point
    check_entries.last_idx = idx
    check_entries.is_processing = True
    
    try:
        direction = 1 if enter_long else -1
        action = 'BUY' if direction == 1 else 'SELL'
        qty = strategy.qty if hasattr(strategy, 'qty') else 1

        # Setup position using strategy
        entry_price = latest_row['close']
        position_dict = strategy.setup_position(entry_price, direction, latest_row, data)
        stop_price = position_dict['stop']
        tp = position_dict.get('tp')

        # Round to ES tick size (0.25) and validate
        entry_price = round(float(entry_price) * 4) / 4
        
        # SL Validation
        if stop_price is None or pd.isna(stop_price) or stop_price <= 0:
            logging.error(f"CRITICAL: Invalid Stop Price ({stop_price}). Cannot enter trade.")
            add_to_live_tracker(live_tracker, 'error', "Entry blocked: Invalid SL price")
            return
        stop_price = round(float(stop_price) * 4) / 4

        # TP Validation
        valid_tp = False
        if tp is not None and not pd.isna(tp) and tp > 0:
            tp = round(float(tp) * 4) / 4
            if (direction == 1 and tp > entry_price) or (direction == -1 and tp < entry_price):
                valid_tp = True
            
            if not valid_tp:
                logging.warning(f"Invalid TP price {tp} relative to entry {entry_price}. TP disabled.")
                tp = None
        else:
            tp = None

        # Create bracket order
        oca_group = f"bracket_{datetime.now().strftime('%M%S%f')}"
        
        # Explicitly set TIF to GTC to avoid 10349 rejection from IBKR presets
        entry_order = MarketOrder(action=action, totalQuantity=qty, transmit=False, tif='GTC')
        
        if not trading_orders_allowed():
            logging.error("Entry aborted: clientId integrity halt")
            return

        # Place entry order
        trade = ib.placeOrder(contract, entry_order)
        
        # --- ATOMIC TRACKING ---
        # Add to positions list IMMEDIATELY to prevent re-entrant checks from seeing empty list
        entry_time = datetime.now(pytz.timezone("US/Eastern")).replace(tzinfo=None)
        bracket = {
            'entry': entry_order, 'stopLoss': None, 'takeProfit': None,
            'direction': direction, 'position_dict': position_dict,
            'entry_time': entry_time, 'entry_price': entry_price,
            'entry_stop_price': stop_price,
            'entry_tp_price': tp,
            'params_snapshot': _snapshot_strategy_params(strategy),
            'ocaGroup': oca_group,  # Store for protection logic
            'contract': contract,
            'open_notified': False,
            # Guard cleanup logic against race/callback timing for newly submitted bracket.
            'created_at': datetime.now(pytz.utc),
            'guard_until': datetime.now(pytz.utc) + timedelta(seconds=30),
        }
        positions.append(bracket)

        # Wait brief moment for IB to assign OrderId/PermID
        ib.sleep(1)

        entry_order_id = entry_order.orderId
        if entry_order_id == 0 and trade and trade.order:
            entry_order_id = trade.order.orderId
        if entry_order_id == 0:
            logging.error("Failed to get entry orderId, cannot link bracket orders accurately")
        else:
            bracket['entryOrderId'] = entry_order_id

        # Stop loss
        stop_action = 'SELL' if direction == 1 else 'BUY'
        stop_order = StopOrder(
            action=stop_action, totalQuantity=qty, stopPrice=stop_price,
            parentId=entry_order_id, tif='GTC',
            ocaGroup=oca_group if tp is not None else None,
            ocaType=1 if tp is not None else None,
            transmit=False if tp is not None else True
        )
        bracket['stopLoss'] = stop_order

        # Take profit
        tp_order = None
        if tp is not None:
            tp_action = 'SELL' if direction == 1 else 'BUY'
            tp_order = LimitOrder(
                action=tp_action, totalQuantity=qty, lmtPrice=tp,
                parentId=entry_order_id, tif='GTC',
                ocaGroup=oca_group, ocaType=1,
                transmit=True
            )
            bracket['takeProfit'] = tp_order
            ib.placeOrder(contract, stop_order)
            ib.placeOrder(contract, tp_order)
        else:
            ib.placeOrder(contract, stop_order)

    except Exception as e:
        logging.error(f"Failed to place orders: {e}")
        logging.error(traceback.format_exc())
        if 'bracket' in locals() and bracket in positions:
            positions.remove(bracket)
    finally:
        check_entries.is_processing = False

    # Entry notifications only after parent fill (poll — fills often land just after first sleep).
    entry_perm = getattr(entry_order, 'permId', 0)
    oid = entry_order_id if 'entry_order_id' in locals() else 0
    confirmed_trade = _wait_for_entry_fill(ib, contract, oid, entry_perm, timeout_sec=8.0)
    if confirmed_trade and confirmed_trade.filled():
        if confirmed_trade.fills:
            try:
                entry_price = float(confirmed_trade.fills[0].execution.price)
                bracket['entry_price'] = entry_price
            except Exception:
                pass
            converted = _ib_fill_to_naive_et(confirmed_trade.fills[0])
            if converted is not None:
                bracket['entry_time'] = converted
                entry_time = converted
        _send_trade_open_notification(
            bracket, direction, entry_price, stop_price, tp, qty, entry_time,
            ib, data, contract, send_email_fn, live_tracker, dashboard_state,
            strategy=strategy, positions=positions,
        )
    else:
        logging.warning(
            "Entry parent not filled yet/rejected; TRADE OPEN deferred until fill confirms "
            f"(orderId={oid}, permId={entry_perm})"
        )
    
    # Double check order placement success
    ib.sleep(0.5)
    if stop_order and not ib.trades()[-1].isActive() and ib.trades()[-1].orderStatus.status == 'Rejected':
        logging.error(f"CRITICAL: Stop order REJECTED: {ib.trades()[-1].orderStatus.statusReason}")
        send_email_fn("CRITICAL ERROR: Stop Loss Rejected", 
                      f"Stop Loss for {'LONG' if direction==1 else 'SHORT'} @ {entry_price} was rejected.\n"
                      f"Reason: {ib.trades()[-1].orderStatus.statusReason}")
    


def _record_flatten_close_from_market_order(
    ib, bracket_contract, bracket, entry_trade, close_trade,
    dir_, qty, reason_label, stop_at_close_snap, tp_at_close_snap,
    completed_trades, live_tracker, send_email_fn, data, strategy=None,
    send_close_email: bool = False,
):
    """
    Record a completed trade after RTH/maintenance (or similar) forced market flatten.
    Snapshots SL/TP prices must be taken before those orders were cancelled.
    """
    reason = f"{reason_label} (forced close)"
    entry_price = float(bracket.get('entry_price', 0) or 0)
    entry_time = bracket.get('entry_time')
    if not entry_price and entry_trade and getattr(entry_trade, 'fills', None):
        try:
            entry_price = float(entry_trade.fills[0].execution.price)
        except Exception:
            pass

    exit_price = 0.0
    pnl = 0.0
    if close_trade and close_trade.fills:
        try:
            exit_price = float(close_trade.fills[-1].execution.price)
        except Exception:
            exit_price = 0.0
        pnl = _pnl_from_fills_or_synthetic(
            close_trade.fills, entry_price, exit_price, dir_, qty, log_label="flatten_close"
        )
    else:
        expected_side = 'SLD' if dir_ == 1 else 'BOT'
        is_aware = entry_time and getattr(entry_time, 'tzinfo', None) is not None
        ref_time = entry_time
        for f in reversed(ib.fills()):
            if f.contract.conId != bracket_contract.conId:
                continue
            if not hasattr(f, 'execution') or f.execution.side != expected_side:
                continue
            f_time = f.execution.time
            if is_aware and f_time.tzinfo is None:
                f_time = pytz.utc.localize(f_time)
            elif not is_aware and f_time.tzinfo is not None:
                f_time = f_time.replace(tzinfo=None)
            if ref_time and f_time < (ref_time - pd.Timedelta(seconds=5)):
                continue
            if abs(f.execution.shares) < qty:
                continue
            exit_price = float(f.execution.price)
            pnl = _pnl_from_fills_or_synthetic(
                [f], entry_price, exit_price, dir_, qty, log_label="flatten_scan"
            )
            break

    if exit_price <= 0 and data is not None and not data.empty:
        exit_price = float(data['close'].iloc[-1])
        if entry_price > 0 and pnl == 0:
            pnl = (exit_price - entry_price) * dir_ * 50 * qty

    is_aware = entry_time and getattr(entry_time, 'tzinfo', None) is not None
    exit_time = datetime.now()
    if is_aware:
        exit_time = exit_time.astimezone(pytz.utc)

    duration_str = format_duration((exit_time - entry_time).total_seconds()) if entry_time else "N/A"

    curr_stop = float(stop_at_close_snap) if stop_at_close_snap is not None else 0.0
    initial_risk = abs(entry_price - curr_stop) * 50 * qty if curr_stop else 0
    r_multiple = pnl / initial_risk if initial_risk > 0 else 0

    report_url = ""
    if strategy:
        try:
            trades_dir = os.path.join(os.getcwd(), 'web', 'trades')
            os.makedirs(trades_dir, exist_ok=True)
            report_path = strategy.generate_trade_report(
                {
                    'entry_time': entry_time, 'exit_time': exit_time,
                    'direction': dir_, 'entry_price': entry_price,
                    'exit_price': exit_price, 'pnl': pnl, 'qty': qty,
                    'reason': reason,
                    'stop_at_close': stop_at_close_snap,
                    'tp_at_close': tp_at_close_snap,
                    'stop_at_open': bracket.get('entry_stop_price'),
                    'tp_at_open': bracket.get('entry_tp_price'),
                    'params_snapshot': bracket.get('params_snapshot') or {},
                },
                data, trades_dir
            )
            if report_path:
                report_url = f"trades/{os.path.basename(report_path)}"
        except Exception as e:
            logging.error(f"Failed to generate HTML report (flatten): {e}")

    if send_close_email:
        _send_trade_close_notification(
            ib, bracket, dir_, entry_price, exit_price, pnl, qty, reason,
            duration_str, exit_time, data, send_email_fn, live_tracker,
            report_url=report_url
        )

    logging.info(f"TRADE CLOSE: {reason} @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")
    add_to_live_tracker(live_tracker, 'trade',
                        f"CLOSE ({reason}): @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")

    _append_completed_trade_record(completed_trades, {
        'exit_time': exit_time, 'entry_time': entry_time,
        'direction': 'LONG' if dir_ == 1 else 'SHORT',
        'qty': qty, 'entry_price': entry_price, 'exit_price': exit_price,
        'pnl': pnl, 'r_multiple': r_multiple, 'reason': reason,
        'live_exit_type': _live_exit_type(reason),
        'duration': duration_str,
        'report_url': report_url,
        'params_snapshot': bracket.get('params_snapshot') or {},
        'stop_at_open': bracket.get('entry_stop_price'),
        'tp_at_open': bracket.get('entry_tp_price'),
        'stop_at_close': stop_at_close_snap,
        'tp_at_close': tp_at_close_snap,
        'entry_order_id': bracket.get('entryOrderId'),
    })

    try:
        cancel_residual_orders_when_flat_on_contract(ib, bracket_contract, live_tracker)
    except Exception as e:
        logging.error(f"Error during flatten orphan cleanup: {e}")


def _close_all_positions(reason_label, ib, contract, positions, data,
                         live_tracker, send_email_fn, strategy=None, account_fn=None,
                         completed_trades=None):
    """Close all tracked positions with market orders; record completed_trades like other exits."""
    for bracket in positions[:]:
        try:
            entry_order = bracket['entry']
            entry_trade = next((t for t in ib.trades() if t.order.permId == entry_order.permId), None)

            # If entry trade is not filled yet, cancel it
            if entry_trade and entry_trade.isActive():
                ib.cancelOrder(entry_trade.order)
                logging.info(f"Cancelled active entry order during {reason_label} exit")

            # Use bracket's contract if available, fallback to global
            bracket_contract = bracket.get('contract', contract)
            es_positions = [p for p in ib.positions() if p.contract.conId == bracket_contract.conId]

            if not es_positions or es_positions[0].position == 0:
                if bracket in positions:
                    positions.remove(bracket)
                continue

            actual_pos = es_positions[0].position
            actual_qty = abs(actual_pos)
            dir_ = 1 if actual_pos > 0 else -1
            close_action = 'SELL' if actual_pos > 0 else 'BUY'

            stop_order = bracket.get('stopLoss')
            tp_order = bracket.get('takeProfit')
            stop_snap = _effective_bracket_stop(stop_order, bracket, dir_)
            tp_snap = None
            if tp_order:
                raw_tp = getattr(tp_order, 'lmtPrice', None)
                if raw_tp is not None:
                    try:
                        tp_snap = float(raw_tp)
                    except (TypeError, ValueError):
                        tp_snap = None

            for order in [stop_order, tp_order]:
                if order:
                    try:
                        ib.cancelOrder(order)
                    except Exception:
                        pass

            if bracket in positions:
                positions.remove(bracket)

            close_mkt = MarketOrder(
                action=close_action, totalQuantity=actual_qty, transmit=True, tif="DAY"
            )
            close_trade = ib.placeOrder(bracket_contract, close_mkt)
            ib.sleep(3)
            if not close_trade.fills:
                ib.sleep(2)

            es_after = [p for p in ib.positions() if p.contract.conId == bracket_contract.conId]
            if (not es_after or es_after[0].position == 0) and completed_trades is not None:
                _record_flatten_close_from_market_order(
                    ib, bracket_contract, bracket, entry_trade, close_trade,
                    dir_, actual_qty, reason_label, stop_snap, tp_snap,
                    completed_trades, live_tracker, send_email_fn, data, strategy=strategy,
                )
            elif es_after and es_after[0].position != 0:
                logging.error(f"{reason_label} market close may not have filled; position still open for {bracket_contract.localSymbol}")

            logging.info(f"Tracked position closed ({reason_label}): {close_action} {actual_qty} {bracket_contract.localSymbol}")
            if live_tracker and completed_trades is None:
                add_to_live_tracker(live_tracker, 'trade', f"{reason_label} EXIT: {bracket_contract.localSymbol}")
        except Exception as e:
            logging.error(f"Error closing tracked position ({reason_label}): {e}")

    # --- NEW: Close any UNTRACKED ES positions (Safety Catch) ---
    try:
        all_es_pos = [p for p in ib.positions() if p.contract.symbol == 'ES' and p.position != 0]
        for pos in all_es_pos:
            # We already tried to close tracked ones. If any ES position remains, it's either
            # one we just placed an order for (wait for fill) or a truly untracked one.
            # To be safe, we check if there are active orders for this contract.
            active_for_this = [t for t in ib.trades() if t.contract.conId == pos.contract.conId and t.isActive()]
            if not active_for_this:
                logging.warning(f"UNTRACKED ES POSITION FOUND during {reason_label} exit: {pos.position} {pos.contract.localSymbol}. Closing...")
                close_action = 'SELL' if pos.position > 0 else 'BUY'
                close_order = MarketOrder(
                    action=close_action, totalQuantity=abs(pos.position), transmit=True, tif="DAY"
                )
                ib.placeOrder(pos.contract, close_order)
                if live_tracker:
                    add_to_live_tracker(live_tracker, 'warning', f"Closed untracked {pos.contract.localSymbol} ({reason_label})")
    except Exception as e:
        logging.error(f"Error closing untracked positions during {reason_label}: {e}")

    # Send notification email
    try:
        account = account_fn() if account_fn else {}
        msg = (f"{reason_label} - All Positions Closed\n{'='*50}\n"
               f"NetLiq: ${account.get('NetLiquidation', 0):,.2f}\n"
               f"Realized PNL: ${account.get('RealizedPNL', 0):,.2f}\n"
               f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        send_email_fn(f"BB Strategy - {reason_label}", msg)
    except Exception as e:
        logging.error(f"Error sending {reason_label} email: {e}")


def check_exits(strategy, ib, contract, data, positions, completed_trades,
                live_tracker, send_email_fn, idx, latest_row, allow_strategy_exit=False,
                skip_trailing=False):
    """Exit logic: RTH, maintenance, broker fill detection, optional strategy exits, trailing.

    Phase 1 clock: call with ``skip_trailing=True`` on 1-min monitor ticks; trail + ``bars_held``
    only when ``allow_strategy_exit=True`` on a completed strategy bar (``completed_row``).

    Phase 2 (``LIVE_BROKER_AUTHORITATIVE_EXIT``, default on): on strategy bars, trail → TP sync →
    defer SL/TP ``check_exit`` when broker legs are active; channel exits use ``Channel Exit (signal)``.
    Roll back with ``LIVE_BROKER_AUTHORITATIVE_EXIT=0`` (and ``LIVE_TRAIL_STRATEGY_BAR_ONLY=0`` for 1-min trail).
    """
    
    # --- RTH Force Exit ---
    if getattr(strategy, 'enable_rth_filter', False) and getattr(strategy, 'rth_exit_buffer_minutes', 0) > 0:
        force_exit_rth = latest_row.get('force_exit_rth', False) if isinstance(latest_row, dict) else getattr(latest_row, 'force_exit_rth', False)
        if force_exit_rth:
            es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
            has_open = any(abs(p.position) > 0 for p in es_positions)
            if has_open or len(positions) > 0:
                if not hasattr(check_exits, '_rth_warned'):
                    logging.warning(f"⚠️ RTH ENDING - Closing all positions ({getattr(strategy, 'rth_exit_buffer_minutes', 0)} min buffer)")
                    add_to_live_tracker(live_tracker, 'warning', 'RTH: Closing all positions')
                    check_exits._rth_warned = True
                acct_fn = lambda: get_account_summary(ib, data, contract)
                # Check for ANY ES position during RTH end
                rth_es_pos = [p for p in ib.positions() if p.contract.symbol == 'ES']
                if rth_es_pos:
                    logging.warning(f"⚠️ RTH ENDING - Closing {len(rth_es_pos)} ES position(s)")
                    _close_all_positions(
                        "RTH End", ib, contract, positions, data, live_tracker, send_email_fn,
                        strategy=strategy, account_fn=acct_fn, completed_trades=completed_trades,
                    )
            else:
                if hasattr(check_exits, '_rth_warned'):
                    delattr(check_exits, '_rth_warned')
            return

    # --- Maintenance Force Exit ---
    if getattr(strategy, 'enable_maintenance_filter', False):
        force_exit = latest_row.get('force_exit', False) if isinstance(latest_row, dict) else getattr(latest_row, 'force_exit', False)
        if force_exit:
            es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
            has_open = any(abs(p.position) > 0 for p in es_positions)
            if has_open or len(positions) > 0:
                if not hasattr(check_exits, '_maint_warned'):
                    current_time = datetime.now(pytz.timezone('America/New_York')).time()
                    logging.warning(f"⚠️ MAINTENANCE APPROACHING - Closing all positions ({current_time.strftime('%H:%M:%S')} ET)")
                    add_to_live_tracker(live_tracker, 'warning', 'MAINTENANCE: Closing all positions')
                    check_exits._maint_warned = True
                acct_fn = lambda: get_account_summary(ib, data, contract)
                # Filter for ANY ES position during maintenance
                maint_es_pos = [p for p in ib.positions() if p.contract.symbol == 'ES']
                if maint_es_pos:
                    _close_all_positions(
                        "Maintenance", ib, contract, positions, data, live_tracker, send_email_fn,
                        strategy=strategy, account_fn=acct_fn, completed_trades=completed_trades,
                    )
            else:
                if hasattr(check_exits, '_maint_warned'):
                    delattr(check_exits, '_maint_warned')
            return

    purge_closed_brackets(positions, live_tracker)
    prune_dead_brackets(ib, contract, positions, live_tracker)

    # --- Per-bracket exit checks ---
    for bracket in positions[:]:
        entry_order = bracket['entry']
        stop_order = bracket['stopLoss']
        tp_order = bracket['takeProfit']
        dir_ = bracket['direction']

        bracket_contract = bracket.get('contract', contract)
        entry_trade = _entry_trade_for_bracket(ib, bracket_contract, bracket, strategy=strategy)
        if entry_trade and entry_trade.fills:
            corrected_et = _ib_fill_to_naive_et(entry_trade.fills[0])
            if corrected_et is not None:
                bracket['entry_time'] = corrected_et
        if _entry_still_pending(entry_trade):
            if entry_trade is None and _ib_open_position_matches_bracket(ib, bracket_contract, bracket):
                try:
                    open_pos = next(
                        p for p in ib.positions()
                        if getattr(p.contract, 'conId', None) == getattr(bracket_contract, 'conId', None)
                        and p.position != 0
                    )
                    wire_bracket_entry_from_ib(ib, open_pos, bracket, strategy=strategy)
                    entry_trade = _entry_trade_for_bracket(ib, bracket_contract, bracket, strategy=strategy)
                except StopIteration:
                    pass
            if _entry_still_pending(entry_trade):
                if not _bracket_can_proceed_without_entry_trade(ib, bracket_contract, bracket):
                    continue
        fill = (
            entry_trade.fills[0].execution
            if entry_trade and entry_trade.fills
            else None
        )
        if not fill and not _ib_open_position_matches_bracket(ib, bracket_contract, bracket):
            continue

        _maybe_send_trade_open_for_bracket(
            bracket, ib, bracket_contract, data, send_email_fn, live_tracker,
            strategy=strategy, positions=positions,
        )

        # Find stop/TP trades (refresh stop handle from IB — trades cache can be stale after adopt)
        stop_trade, stop_order = _resolve_stop_trade_for_bracket(ib, bracket_contract, bracket)
        bracket["stopLoss"] = stop_order
        tp_trade = (
            _find_trade_for_order(ib, bracket_contract, tp_order)
            if tp_order
            else None
        )

        # Use the specific contract for this bracket (handles roll-over)
        bracket_contract = bracket.get('contract', contract)
        
        # --- Check if position closed (TP or Stop filled) ---
        # Look specifically for the contract associated with this bracket
        pos_for_bracket = [p for p in ib.positions() if p.contract.conId == bracket_contract.conId]
        current_pos = sum(p.position for p in pos_for_bracket)
        
        # Determine if we've successfully seen this position in the portfolio yet
        if not bracket.get('position_verified'):
            if current_pos != 0:
                bracket['position_verified'] = True
            else:
                # Fast exit edge case: if TP/Stop hit perfectly before broker positions sync
                stop_filled = stop_trade and getattr(stop_trade, 'orderStatus', None) and stop_trade.orderStatus.status == 'Filled'
                tp_filled = tp_trade and getattr(tp_trade, 'orderStatus', None) and tp_trade.orderStatus.status == 'Filled'
                if not (stop_filled or tp_filled):
                    continue  # Wait for ib.positions() to sync
        
        position_still_open = (current_pos != 0)
        
        if not position_still_open:
            _record_trade_close(ib, bracket_contract, bracket, entry_trade, stop_order, tp_order,
                               stop_trade, tp_trade, dir_, latest_row, positions,
                               completed_trades, live_tracker, send_email_fn, data,
                               strategy=strategy)
            if bracket in positions:
                positions.remove(bracket)
            continue

        current_price = latest_row['close']
        trail_ratchet_this_bar = False

        # --- Trailing stop update (strategy bar first: trail → broker sync → exits) ---
        if position_still_open:
            position_dict = bracket.get('position_dict', {})
            if not position_dict:
                eff = _effective_bracket_stop(stop_order, bracket, dir_)
                current_stop = float(eff) if eff is not None else 0.0
                position_dict = {
                    'direction': dir_, 'bars_held': 0, 'stop': current_stop,
                    'max_high': latest_row['high'] if dir_ == 1 else None,
                    'min_low': latest_row['low'] if dir_ == -1 else None
                }
                bracket['position_dict'] = position_dict

            if not skip_trailing and allow_strategy_exit:
                # Trail only on completed strategy bars (not 1-min monitor passes).
                strat_pos = bracket.get('position_dict', position_dict)
                _sb = _finite_stop_scalar(strat_pos.get("stop"))
                if _sb is None:
                    _sb = _finite_stop_scalar(bracket.get("entry_stop_price"))
                if _sb is None:
                    _sb = _effective_bracket_stop(stop_order, bracket, dir_)
                stop_before_trail_update = float(_sb) if _sb is not None else 0.0

                stop_updated = strategy.update_trailing_stop(strat_pos, latest_row, data)
                if stop_updated:
                    trail_ratchet_this_bar = True

                # Strategy may write NaN/inf into stop on bad bar data; clamp before IB / round().
                _trail_raw = _finite_stop_scalar(strat_pos.get("stop"))
                if _trail_raw is None:
                    _trail_raw = _finite_stop_scalar(position_dict.get("stop"))
                if _trail_raw is None:
                    _trail_raw = _effective_bracket_stop(stop_order, bracket, dir_)
                if _trail_raw is not None:
                    q = _quantize_es_tick(_trail_raw)
                    if q is not None:
                        strat_pos["stop"] = q
                        position_dict["stop"] = q

                if stop_updated:
                    logging.info(
                        "Trailing model: %.2f -> %.2f (dir=%s bars_held=%s)",
                        stop_before_trail_update,
                        float(strat_pos.get("stop") or stop_before_trail_update),
                        dir_,
                        strat_pos.get("bars_held"),
                    )

                stop_active = _bracket_stop_is_actionable(stop_trade, stop_order, bracket)
                if stop_updated and not stop_active:
                    logging.warning(
                        "Trailing: model stop %.2f but IB stop not actionable "
                        "(stop_trade=%s permId=%s); attempting broker replace anyway",
                        float(strat_pos.get("stop") or 0),
                        "found" if stop_trade else "missing",
                        getattr(stop_order, "permId", 0),
                    )
                    stop_active = _broker_stop_trigger_price(stop_order) is not None

                if stop_updated and stop_active:
                    new_stop = _quantize_es_tick(position_dict.get("stop"))
                    if new_stop is None:
                        logging.error(
                            "Trailing: stop is not finite after update_trailing_stop; skipping broker update"
                        )
                    else:
                        live_ord = (stop_trade.order if stop_trade else stop_order)
                        brk_lv = _broker_stop_trigger_price(live_ord)
                        curr_working = (
                            float(brk_lv)
                            if brk_lv is not None
                            else float(_effective_bracket_stop(stop_order, bracket, dir_) or 0.0)
                        )
                        if not np.isfinite(curr_working):
                            curr_working = float(new_stop)
                        should_update = (dir_ == 1 and new_stop > curr_working) or (
                            dir_ == -1 and new_stop < curr_working
                        )
                        if stop_updated and not should_update:
                            logging.debug(
                                "Trailing: model stop=%.4f vs working=%.4f (dir=%s); no broker tighten",
                                new_stop,
                                curr_working,
                                dir_,
                            )
                        if should_update:
                            stop_action = "SELL" if dir_ == 1 else "BUY"
                            qty_trail = float(getattr(stop_order, "totalQuantity", 1) or 1)
                            parent_id = int(bracket.get("entryOrderId") or 0)
                            og = bracket.get("ocaGroup")
                            # IB rejects in-place modify on OCA-linked exits (error 10326).
                            # Prefer standalone stop zero-gap replace whenever bracket exits exist.
                            use_stop_replace = bool(tp_order or og or getattr(stop_order, "parentId", 0))
                            try:
                                if use_stop_replace:
                                    tp_lmt = _finite_stop_scalar(
                                        getattr(tp_order, "lmtPrice", None)
                                    )
                                    if tp_lmt is None:
                                        tp_lmt = _finite_stop_scalar(bracket.get("entry_tp_price"))
                                    use_oca_pair = bool(
                                        tp_order and tp_lmt is not None and og
                                    )
                                    if use_oca_pair:
                                        ok = replace_oca_exit_pair_zero_gap(
                                            ib,
                                            bracket_contract,
                                            bracket,
                                            new_stop,
                                            tp_lmt,
                                            dir_,
                                            stop_order,
                                            tp_order,
                                            live_tracker=live_tracker,
                                            timeout=5.0,
                                        )
                                    else:
                                        ok = replace_trailing_stop_zero_gap(
                                            ib,
                                            bracket_contract,
                                            bracket,
                                            new_stop,
                                            dir_,
                                            stop_order,
                                            live_tracker=live_tracker,
                                            timeout=5.0,
                                        )
                                    if not ok:
                                        strat_pos["stop"] = stop_before_trail_update
                                        position_dict["stop"] = stop_before_trail_update
                                        logging.error(
                                            "Trailing stop replace failed; reverted strategy stop "
                                            "%.2f -> %.2f",
                                            new_stop,
                                            stop_before_trail_update,
                                        )
                                else:
                                    stop_order.stopPrice = new_stop
                                    if hasattr(stop_order, "auxPrice"):
                                        stop_order.auxPrice = new_stop
                                    if hasattr(stop_order, "ocaGroup"):
                                        stop_order.ocaGroup = ""
                                    if hasattr(stop_order, "ocaType"):
                                        stop_order.ocaType = 0
                                    stop_order.transmit = True
                                    if hasattr(stop_order, "parentId"):
                                        stop_order.parentId = 0
                                    ib.placeOrder(bracket_contract, stop_order)
                                    ib.sleep(0.2)
                                    if not ensure_bracket_stop_armed(
                                        ib, bracket_contract, bracket, live_tracker,
                                    ):
                                        strat_pos["stop"] = stop_before_trail_update
                                        logging.error(
                                            "Trailing stop modify: could not arm stop @ %.2f; reverted model",
                                            new_stop,
                                        )
                                    else:
                                        logging.info(
                                            f"Trailing stop modified: {curr_working:.2f} -> {new_stop:.2f}"
                                        )
                                        add_to_live_tracker(
                                            live_tracker, "order", f"Trailing stop -> ${new_stop:.2f}"
                                        )
                            except Exception as e:
                                strat_pos["stop"] = stop_before_trail_update
                                logging.error(f"Error updating trailing stop: {e}")
                                if use_stop_replace and parent_id > 0 and og:
                                    try:
                                        tp_lmt = _finite_stop_scalar(
                                            getattr(tp_order, "lmtPrice", None)
                                        )
                                        if tp_lmt is None:
                                            tp_lmt = _finite_stop_scalar(bracket.get("entry_tp_price"))
                                        sl_px = _quantize_es_tick(stop_before_trail_update)
                                        tp_px = _quantize_es_tick(tp_lmt) if tp_lmt is not None else None
                                        if sl_px is not None and tp_px is not None:
                                            tp_action = "SELL" if dir_ == 1 else "BUY"
                                            restore_sl = StopOrder(
                                                action=stop_action,
                                                totalQuantity=qty_trail,
                                                stopPrice=sl_px,
                                                parentId=parent_id,
                                                tif="GTC",
                                                ocaGroup=og,
                                                ocaType=1,
                                                transmit=False,
                                            )
                                            restore_tp = LimitOrder(
                                                action=tp_action,
                                                totalQuantity=qty_trail,
                                                lmtPrice=tp_px,
                                                parentId=parent_id,
                                                tif="GTC",
                                                ocaGroup=og,
                                                ocaType=1,
                                                transmit=True,
                                            )
                                            ib.placeOrder(bracket_contract, restore_sl)
                                            ib.placeOrder(bracket_contract, restore_tp)
                                            bracket["stopLoss"] = restore_sl
                                            bracket["takeProfit"] = restore_tp
                                            logging.warning(
                                                "Restored OCA SL+TP after trail replace failure "
                                                "(SL %.2f TP %.2f)",
                                                sl_px,
                                                tp_px,
                                            )
                                    except Exception as re:
                                        logging.critical(
                                            "Trail replace failed and could not restore OCA pair: %s", re
                                        )

            # --- Opposite BB TP update (strategy bar, after trail) ---
            if allow_strategy_exit and position_still_open and getattr(strategy, 'opposite_bb_tp', False) and tp_order:
                _update_opposite_bb_tp(ib, bracket_contract, data, bracket, tp_order, dir_, live_tracker)

            # Refresh order handles after trail / TP sync
            stop_trade, stop_order = _resolve_stop_trade_for_bracket(ib, bracket_contract, bracket)
            bracket["stopLoss"] = stop_order
            if tp_order:
                tp_trade = _find_trade_for_order(ib, bracket_contract, tp_order) or tp_trade
            stop_active = _protective_order_active(stop_trade)
            stop_armed = stop_order_is_armed(stop_trade)
            tp_active = _protective_order_active(tp_trade)
            trail_stop_pending = trail_stop_protection_pending(
                bracket,
                stop_trade,
                trail_ratchet_this_bar=trail_ratchet_this_bar,
            )

            # Post-trail breach uses refreshed broker stop (not pre-trail snapshot).
            live_stop_order = stop_trade.order if stop_trade else stop_order
            broker_px = _broker_stop_trigger_price(live_stop_order)
            stop_price_for_breach = (
                broker_px
                if (broker_px is not None and broker_px > 0)
                else (_effective_bracket_stop(stop_order, bracket, dir_) or 0.0)
            )
            if allow_strategy_exit:
                breach_row = _eval_row_for_exit(bracket, latest_row)
                hi = float(
                    breach_row.get("high", current_price)
                    if hasattr(breach_row, "get")
                    else breach_row["high"]
                )
                lo = float(
                    breach_row.get("low", current_price)
                    if hasattr(breach_row, "get")
                    else breach_row["low"]
                )
                breach_px = lo if dir_ == 1 else hi
            else:
                breach_px = current_price
            stop_should_trigger = _model_stop_breached(dir_, breach_px, stop_price_for_breach)

            if _handle_protective_backup(
                ib, bracket_contract, bracket, positions, completed_trades,
                live_tracker, send_email_fn, entry_trade, latest_row, data, strategy,
                stop_trade, dir_, stop_should_trigger, stop_price_for_breach,
                trail_grace_active=trail_stop_pending,
            ):
                continue

            if allow_strategy_exit:
                try:
                    strat_pos = bracket.get('position_dict', bracket)
                    eval_row = _eval_row_for_exit(bracket, latest_row)
                    exit_triggered, exit_reason, exit_price_hint = strategy.check_exit(
                        strat_pos, eval_row, data
                    )
                    if exit_triggered:
                        closed = _handle_strategy_signal_exit(
                            ib, bracket_contract, bracket, positions, completed_trades,
                            live_tracker, send_email_fn, entry_trade, latest_row, data, strategy,
                            stop_trade, tp_trade, dir_, exit_reason, exit_price_hint,
                            stop_armed, tp_active,
                            trail_grace_active=trail_stop_pending,
                            trail_ratchet_this_bar=trail_ratchet_this_bar,
                        )
                        if closed:
                            continue
                except Exception as e:
                    logging.error(f"Error checking strategy signal exit: {e}")


def _force_close_position(ib, contract, bracket, positions, completed_trades,
                          live_tracker, send_email_fn, entry_trade, current_price, reason, data=None, strategy=None):
    """Force close a position with market order (PreSubmitted stop handler)."""
    try:
        stop_order = bracket.get('stopLoss')
        tp_order = bracket.get('takeProfit')

        # Use bracket's contract for closing
        bracket_contract = bracket.get('contract', contract)
        es_pos = [p for p in ib.positions() if p.contract.conId == bracket_contract.conId]
        if not es_pos or es_pos[0].position == 0:
            # Broker may have already flattened (e.g. trailed stop filled) before software exit runs.
            entry_trade = entry_trade or _entry_trade_for_bracket(
                ib, bracket_contract, bracket, strategy=strategy,
            )
            had_real_entry = (
                (entry_trade is not None and entry_trade.filled())
                or bool(bracket.get('position_verified'))
            )
            if had_real_entry:
                stop_trade, stop_order = _resolve_stop_trade_for_bracket(
                    ib, bracket_contract, bracket,
                )
                tp_order = bracket.get('takeProfit')
                tp_trade = (
                    _find_trade_for_order(ib, bracket_contract, tp_order)
                    if tp_order else None
                )
                dir_ = int(bracket.get('direction') or 0)
                latest_row = None
                if data is not None and not data.empty:
                    latest_row = data.iloc[-1]
                elif current_price is not None:
                    latest_row = {'close': current_price}
                logging.info(
                    "Force close skipped: IB already flat; recording completed trade "
                    "(dir=%s entry=%.2f)",
                    'LONG' if dir_ == 1 else 'SHORT' if dir_ == -1 else dir_,
                    float(bracket.get('entry_price') or 0),
                )
                _record_trade_close(
                    ib, bracket_contract, bracket, entry_trade, stop_order, tp_order,
                    stop_trade, tp_trade, dir_, latest_row, positions,
                    completed_trades, live_tracker, send_email_fn, data,
                    reason='Unknown', strategy=strategy,
                )
                return
            if bracket in positions:
                positions.remove(bracket)
            return

        actual_pos = es_pos[0].position
        dir_ = 1 if actual_pos > 0 else -1
        stop_at_close_snap = _effective_bracket_stop(stop_order, bracket, dir_)
        tp_at_close_snap = getattr(tp_order, 'lmtPrice', None) if tp_order else None
        broker_stop_at_exit = _broker_stop_trigger_price(stop_order)
        model_stop_at_exit = (bracket.get("position_dict") or {}).get("stop")
        if model_stop_at_exit is not None:
            model_stop_at_exit = _finite_stop_scalar(model_stop_at_exit)

        # Cancel existing orders (snapshot SL/TP first for reporting)
        for order in [bracket.get('stopLoss'), bracket.get('takeProfit')]:
            if order:
                try: ib.cancelOrder(order)
                except: pass

        close_action = 'SELL' if actual_pos > 0 else 'BUY'
        close_order = MarketOrder(
            action=close_action, totalQuantity=abs(actual_pos), transmit=True, tif="DAY"
        )
        
        # Remove bracket proactively before sleep yields to event loop to avoid re-entrancy duplications
        if bracket in positions:
            positions.remove(bracket)
            
        close_trade = ib.placeOrder(bracket_contract, close_order)
        ib.sleep(3)

        # Check result
        es_after = [p for p in ib.positions() if p.contract.conId == bracket_contract.conId]
        if not es_after or es_after[0].position == 0:
            entry_price = bracket.get('entry_price', 0)
            exit_price = close_trade.fills[0].execution.price if close_trade.fills else current_price
            qty = abs(actual_pos)
            pnl = _pnl_from_fills_or_synthetic(
                close_trade.fills, entry_price, exit_price, dir_, qty, log_label="force_close"
            )

            # Metadata for reporting
            exit_time = datetime.now()
            entry_time = bracket.get('entry_time')
            duration_str = format_duration((exit_time - entry_time).total_seconds()) if entry_time else "N/A"
            
            # Use unified reporting helper
            report_url = ""
            slip = _exit_slippage_metrics(
                dir_, exit_price, stop_at_close_snap, tp_at_close_snap, reason, qty,
                broker_stop_at_exit=broker_stop_at_exit,
                model_stop_at_exit=model_stop_at_exit,
            )
            if strategy:
                try:
                    # Save to web/trades/
                    trades_dir = os.path.join(os.getcwd(), 'web', 'trades')
                    os.makedirs(trades_dir, exist_ok=True)
                    report_path = strategy.generate_trade_report(
                        {
                            'entry_time': entry_time, 'exit_time': exit_time,
                            'direction': dir_, 'entry_price': entry_price,
                            'exit_price': exit_price, 'pnl': pnl, 'qty': qty,
                            'reason': reason,
                            'stop_at_close': stop_at_close_snap,
                            'tp_at_close': tp_at_close_snap,
                            'stop_at_open': bracket.get('entry_stop_price'),
                            'tp_at_open': bracket.get('entry_tp_price'),
                            'params_snapshot': bracket.get('params_snapshot') or {},
                            'live_exit_type': _live_exit_type(reason),
                            'exit_path': _exit_path(reason),
                            'slippage_pts': slip.get('slippage_pts'),
                            'slippage_usd': slip.get('slippage_usd'),
                            'slippage_reference': slip.get('slippage_reference'),
                            'broker_stop_at_exit': broker_stop_at_exit,
                            'model_stop_at_exit': model_stop_at_exit,
                        },
                        data, trades_dir
                    )
                    if report_path:
                        report_url = f"trades/{os.path.basename(report_path)}"
                except Exception as e:
                    logging.error(f"Failed to generate HTML report: {e}")

            logging.info(f"TRADE CLOSE: {reason} @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")
            if live_tracker is not None:
                add_to_live_tracker(
                    live_tracker, 'trade',
                    f"CLOSE ({reason}): @ ${exit_price:.2f}, PNL: ${pnl:,.2f}",
                )

            _send_trade_close_notification(
                ib, bracket, dir_, entry_price, exit_price, pnl, qty, reason, 
                duration_str, exit_time, data, send_email_fn, live_tracker,
                report_url=report_url
            )
            
            # Record in completed trades for dashboard
            _append_completed_trade_record(completed_trades, {
                'exit_time': exit_time, 'entry_time': entry_time,
                'direction': 'LONG' if dir_ == 1 else 'SHORT',
                'qty': qty, 'entry_price': entry_price, 'exit_price': exit_price,
                'pnl': pnl, 'reason': reason,
                'live_exit_type': _live_exit_type(reason),
                'exit_path': _exit_path(reason),
                'duration': duration_str,
                'report_url': report_url,
                'params_snapshot': bracket.get('params_snapshot') or {},
                'stop_at_open': bracket.get('entry_stop_price'),
                'tp_at_open': bracket.get('entry_tp_price'),
                'stop_at_close': stop_at_close_snap,
                'tp_at_close': tp_at_close_snap,
                'entry_order_id': bracket.get('entryOrderId'),
                'slippage_pts': slip.get('slippage_pts'),
                'slippage_usd': slip.get('slippage_usd'),
                'slippage_reference': slip.get('slippage_reference'),
                'model_stop_at_exit': slip.get('model_stop_at_exit'),
                'broker_stop_at_exit': slip.get('broker_stop_at_exit'),
            })
        else:
            logging.error(f"Force close failed: Position still exists for {bracket_contract.localSymbol}")

    except Exception as e:
        logging.error(f"CRITICAL: Failed to force close: {e}")
        import traceback
        logging.error(traceback.format_exc())


def _update_opposite_bb_tp(ib, contract, data, bracket, tp_order, dir_, live_tracker):
    """Update TP to track opposite Bollinger Band."""
    if 'upper' not in data.columns or 'lower' not in data.columns or len(data) == 0:
        return
    new_tp_raw = data['upper'].iloc[-1] if dir_ == 1 else data['lower'].iloc[-1]
    if pd.isna(new_tp_raw) or np.isnan(new_tp_raw):
        return

    new_tp = round(float(new_tp_raw) * 4) / 4
    current_tp = getattr(tp_order, 'lmtPrice', 0)

    if abs(new_tp - current_tp) < 0.25:
        return

    # Find TP trade
    tp_trade = next((t for t in ib.trades()
                     if hasattr(tp_order, 'permId') and t.order.permId == tp_order.permId), None)
    if tp_trade is None:
        tp_action = 'SELL' if dir_ == 1 else 'BUY'
        tp_trade = next((t for t in ib.trades()
                         if t.contract.conId == contract.conId and
                         isinstance(t.order, LimitOrder) and t.order.action == tp_action and
                         abs(getattr(t.order, 'lmtPrice', 0) - current_tp) < 0.01), None)

    tp_active = False
    if tp_trade:
        tp_active = tp_trade.isActive() or (tp_trade.orderStatus and
            tp_trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending'])

    if tp_active:
        try:
            tp_order.lmtPrice = new_tp
            tp_order.transmit = True
            ib.placeOrder(contract, tp_order)
            logging.info(f"Opposite BB TP modified: {current_tp:.2f} -> {new_tp:.2f}")
            add_to_live_tracker(live_tracker, 'order', f"Opposite BB TP -> ${new_tp:.2f}")
        except Exception as e:
            logging.error(f"Failed to modify TP order: {e}")


def _calculate_trade_metrics(entry_time, exit_time, dir_, entry_price, exit_price, pnl, qty, data, curr_stop, tp_price):
    """Calculate MFE, MAE, Risk, Reward, and R-Multiple for a trade."""
    mfe_pts = 0
    mae_pts = 0
    if entry_time and data is not None and not data.empty:
        try:
            # Standardize index to compare with naive times if needed
            idx = data.index
            localized_entry = entry_time
            localized_exit = exit_time
            if idx.tz is not None:
                if localized_entry.tzinfo is None: localized_entry = pd.Timestamp(localized_entry).tz_localize(idx.tz)
                if localized_exit.tzinfo is None: localized_exit = pd.Timestamp(localized_exit).tz_localize(idx.tz)
            else:
                if localized_entry.tzinfo is not None: localized_entry = localized_entry.replace(tzinfo=None)
                if localized_exit.tzinfo is not None: localized_exit = localized_exit.replace(tzinfo=None)

            # Slice data during trade duration
            trade_mask = (idx >= localized_entry) & (idx <= localized_exit)
            tdf = data.loc[trade_mask]
            if not tdf.empty:
                if dir_ == 1: # LONG
                    mfe_pts = tdf['high'].max() - entry_price
                    mae_pts = tdf['low'].min() - entry_price
                else: # SHORT
                    mfe_pts = entry_price - tdf['low'].min()
                    mae_pts = entry_price - tdf['high'].max()
        except Exception as e:
            logging.warning(f"Failed to calculate MAE/MFE: {e}")

    contract_multiplier = 50
    risk_dollars = abs(entry_price - curr_stop) * contract_multiplier * qty if curr_stop else 0
    reward_dollars = abs(entry_price - tp_price) * contract_multiplier * qty if tp_price else None
    rr_ratio = reward_dollars / risk_dollars if (reward_dollars and risk_dollars > 0) else None
    r_multiple = pnl / risk_dollars if risk_dollars > 0 else 0
    
    return {
        'mfe_pts': mfe_pts,
        'mae_pts': mae_pts,
        'mfe_dollars': mfe_pts * contract_multiplier * qty,
        'mae_dollars': mae_pts * contract_multiplier * qty,
        'risk_dollars': risk_dollars,
        'reward_dollars': reward_dollars,
        'rr_ratio': rr_ratio,
        'r_multiple': r_multiple
    }

def _build_trade_report_lines(metrics, account, status_label, dir_, qty, entry_price, exit_price, duration_str, exit_time, entry_time):
    """Build the list of message lines for the email report."""
    msg_lines = [
        f"TRADE {status_label.upper()}",
        f"{'='*60}",
        f"Signal:      {'LONG' if dir_==1 else 'SHORT'}",
        f"Volume:      {qty} contract(s)",
        f"Entry:       ${entry_price:.2f} ({entry_time.strftime('%H:%M:%S') if entry_time else 'N/A'})",
        f"Current/Exit: ${exit_price:.2f} ({exit_time.strftime('%H:%M:%S')})",
        f"Duration:    {duration_str}",
        f"Status:      {status_label}",
        f"",
        f"EXCURSION STATS",
        f"{'-'*30}",
        f"MFE (Max Fav): +${metrics['mfe_dollars']:,.2f} (+{metrics['mfe_pts']:.2f} pts)",
        f"MAE (Max Adv): ${metrics['mae_dollars']:,.2f} ({metrics['mae_pts']:.2f} pts)",
        f"",
        f"FINANCIAL PERFORMANCE",
        f"{'-'*30}",
        f"PnL:         ${metrics.get('pnl', 0):,.2f}",
        f"R-Multiple:  {metrics['r_multiple']:.2f}R",
        f"Initial Risk: ${metrics['risk_dollars']:,.2f}",
        f"Risk/Reward: {metrics['rr_ratio']:.2f}:1" if metrics['rr_ratio'] else "Risk/Reward: N/A",
        f"",
        f"ACCOUNT CONTEXT",
        f"{'-'*30}",
        f"Net Liquidity: ${account.get('NetLiquidation', 0):,.2f}",
        f"Session PnL:   ${account.get('RealizedPNL', 0):,.2f}",
        f"Equity Value:  ${account.get('EquityWithLoanValue', 0):,.2f}",
        f"Timestamp:     {exit_time.strftime('%Y-%m-%d %H:%M:%S')}"
    ]
    return msg_lines

def _send_trade_close_notification(ib, bracket, dir_, entry_price, exit_price, pnl, qty, reason, 
                                   duration_str, exit_time, data, send_email_fn, live_tracker,
                                   report_url=None):
    """Unified helper for detailed trade closure reporting with analytics and charting."""
    entry_time = bracket.get('entry_time')
    stop_order = bracket.get('stopLoss')
    tp_order = bracket.get('takeProfit')
    curr_stop = _effective_bracket_stop(stop_order, bracket, dir_) or 0
    tp_price = getattr(tp_order, 'lmtPrice', None) if tp_order else None

    # Calculate metrics
    metrics = _calculate_trade_metrics(entry_time, exit_time, dir_, entry_price, exit_price, pnl, qty, data, curr_stop, tp_price)
    metrics['pnl'] = pnl

    # Build report
    account = get_account_summary(ib, data, bracket.get('contract'))
    msg_lines = _build_trade_report_lines(metrics, account, reason, dir_, qty, entry_price, exit_price, duration_str, exit_time, entry_time)
    
    dir_code = "L" if dir_ == 1 else "S"
    subj = f"C: {dir_code} {qty}@{exit_price:.2f} ({'+' if pnl>0 else ''}${pnl:.0f})"
    
    # Charting
    os.makedirs('temp', exist_ok=True)
    chart_path = os.path.join(os.getcwd(), 'temp', f'trade_chart_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png')
    chart_attached = False
    if data is not None and not data.empty:
        try:
            chart_attached = create_trade_chart(
                data, entry_time, exit_time, dir_code, chart_path,
                sl_price=curr_stop, tp_price=tp_price, entry_price=entry_price
            )
        except Exception as e:
            logging.error(f"Chart generation failed: {e}")
            
    # Dispatch Email
    try:
        report_msg = f"\n\nInteractive Report: http://127.0.0.1:8000/{report_url}" if report_url else ""
        full_body = "\n".join(msg_lines) + report_msg
        
        if chart_attached:
            send_email_fn(subj, full_body, attachment_path=chart_path)
            # We don't delete immediately here as multiple calls might happen, 
            # but usually it's fine. We'll let OS cleanup or handle in main.
        else:
            send_email_fn(subj, full_body)
    except Exception as e:
        logging.error(f"Failed to dispatch close email: {e}")

def send_composite_status_notification(ib, positions, data, account_info, send_email_fn):
    """Send a single status email with reports and charts for all active positions."""
    open_positions = [
        b for b in (positions or []) if not b.get("_close_recorded")
    ]
    if not open_positions:
        return

    now = datetime.now()
    all_reports = []
    chart_paths = []

    os.makedirs('temp', exist_ok=True)

    for i, bracket in enumerate(open_positions):
        try:
            dir_ = bracket.get('direction', 0)
            entry_price = bracket.get('entry_price', 0)
            entry_time = bracket.get('entry_time')
            qty = 1 # Default
            
            # Try to get qty from order
            stop_order = bracket.get('stopLoss')
            if stop_order and hasattr(stop_order, 'totalQuantity'):
                qty = stop_order.totalQuantity
            
            current_price = data['close'].iloc[-1] if not data.empty else entry_price
            pnl = (current_price - entry_price) * dir_ * 50 * qty
            
            duration_str = format_duration((now - entry_time).total_seconds()) if entry_time else "N/A"
            
            tp_order = bracket.get('takeProfit')
            curr_stop = _effective_bracket_stop(stop_order, bracket, dir_) or 0
            tp_price = getattr(tp_order, 'lmtPrice', None) if tp_order else None

            metrics = _calculate_trade_metrics(entry_time, now, dir_, entry_price, current_price, pnl, qty, data, curr_stop, tp_price)
            metrics['pnl'] = pnl
            
            report_lines = _build_trade_report_lines(metrics, account_info, "OPEN STATUS", dir_, qty, entry_price, current_price, duration_str, now, entry_time)
            all_reports.append("\n".join(report_lines))

            # Generate chart
            dir_code = "L" if dir_ == 1 else "S"
            chart_filename = f'status_chart_{i}_{now.strftime("%H%M%S")}.png'
            chart_path = os.path.join(os.getcwd(), 'temp', chart_filename)
            
            if create_trade_chart(data, entry_time, now, dir_code, chart_path, sl_price=curr_stop, tp_price=tp_price, entry_price=entry_price):
                chart_paths.append(chart_path)
                
        except Exception as e:
            logging.error(f"Failed to generate status for position {i}: {e}")

    if all_reports:
        # Subject summary
        total_pnl = sum(
            (data['close'].iloc[-1] - b.get('entry_price', 0)) * b.get('direction', 0) * 50
            for b in open_positions
            if not data.empty
        )
        pos_summary = "/".join(
            ["L" if b.get('direction') == 1 else "S" for b in open_positions]
        )
        subj = f"STAT: {pos_summary} PNL:${total_pnl:,.0f}"
        
        body = "\n\n" + ("\n" + "="*60 + "\n").join(all_reports)
        
        try:
            send_email_fn(subj, body, attachment_paths=chart_paths)
            logging.info("Composite status email sent.")
        except Exception as e:
            logging.error(f"Failed to send composite status email: {e}")
        
        # Cleanup charts
        for cp in chart_paths:
            try: os.remove(cp)
            except: pass



def _record_trade_close(ib, contract, bracket, entry_trade, stop_order, tp_order,
                        stop_trade, tp_trade, dir_, latest_row, positions,
                        completed_trades, live_tracker, send_email_fn, data, 
                        reason='Unknown', strategy=None):
    """Record a completed trade and clean up. Improved reason discovery."""
    if bracket.get("_close_recorded"):
        logging.info(
            "Skipping duplicate trade close record (already recorded: %s)",
            bracket.get("_close_reason") or reason,
        )
        if bracket in positions:
            positions.remove(bracket)
        return
    bracket["_close_recorded"] = True
    try:
        exit_trade = _record_trade_close_body(
            ib, contract, bracket, entry_trade, stop_order, tp_order,
            stop_trade, tp_trade, dir_, latest_row, positions,
            completed_trades, live_tracker, send_email_fn, data,
            reason=reason, strategy=strategy,
        )
    finally:
        if bracket in positions:
            positions.remove(bracket)


def _record_trade_close_body(ib, contract, bracket, entry_trade, stop_order, tp_order,
                        stop_trade, tp_trade, dir_, latest_row, positions,
                        completed_trades, live_tracker, send_email_fn, data, 
                        reason='Unknown', strategy=None):
    """Inner close recorder; caller must set ``_close_recorded`` and purge ``positions``."""
    # Determine exit reason from orders if not explicitly provided or marked as Manual
    exit_trade = None
    entry_perm = (
        getattr(entry_trade.order, 'permId', 0)
        if entry_trade and getattr(entry_trade, 'order', None)
        else 0
    )
    if reason in ['Unknown', 'Manual / External']:
        # 1. Check current session trades
        for trade in ib.trades():
            if trade.contract.conId == contract.conId and trade.filled():
                if tp_order and trade.order.permId == getattr(tp_order, 'permId', 0):
                    exit_trade = trade; reason = 'Broker Take Profit'; break
                elif stop_order and trade.order.permId == getattr(stop_order, 'permId', 0):
                    exit_trade = trade; reason = 'Broker Stop'; break
        
        # 1b. Trail-replaced stops: working leg permId may differ from bracket handle
        if reason in ['Unknown', 'Manual / External'] and exit_trade is None:
            for trade in ib.trades():
                if trade.contract.conId != contract.conId or not trade.filled():
                    continue
                o = trade.order
                if entry_perm and getattr(o, 'permId', 0) == entry_perm:
                    continue
                ot = str(getattr(o, 'orderType', '') or '').upper()
                if 'STP' in ot or isinstance(o, StopOrder):
                    exit_trade = trade
                    reason = 'Broker Stop'
                    break

        # 2. Deep Search: Check recent fills (crucial for ghost-bracket reconciliation)
        if reason in ['Unknown', 'Manual / External']:
            for fill in reversed(ib.fills()):
                if fill.contract.conId == contract.conId:
                    p_id = getattr(fill.execution, 'permId', 0)
                    if tp_order and p_id != 0 and p_id == getattr(tp_order, 'permId', -1):
                        reason = 'Broker Take Profit'; break
                    elif stop_order and p_id != 0 and p_id == getattr(stop_order, 'permId', -1):
                        reason = 'Broker Stop'; break
                    elif exit_trade is None and p_id != 0 and entry_perm and p_id != entry_perm:
                        side = getattr(fill.execution, 'side', '')
                        if (dir_ == 1 and side == 'SLD') or (dir_ == -1 and side == 'BOT'):
                            reason = 'Broker Stop'
                            break
        
        # 3. Check for specific IB errors or rejections (Ghost-Bracket Sync)
        if reason in ['Unknown', 'Manual / External']:
            # Search recent log entries for rejects or cancels related to this bracket's fills
            for trade in ib.trades():
                 if trade.contract.conId != contract.conId:
                     continue
                 status = getattr(trade.orderStatus, 'status', '') or ''
                 why = getattr(trade.orderStatus, 'whyHeld', '') or ''
                 reason_text = why if why else status
                 if status == 'Rejected' or 'discarded' in str(reason_text).lower():
                     reason = f"Rejected: {str(reason_text)[:30]}"
                     break

        # Final fallback: if position is closed but no fill found, it's external
        if reason in ['Unknown', 'Manual / External']:
            reason = 'Manual / External'

    entry_price = bracket.get('entry_price', 0)
    entry_time = bracket.get('entry_time')
    # Determine if we should work with aware or naive based on entry_time
    is_aware = entry_time and entry_time.tzinfo is not None

    if not entry_price and entry_trade and entry_trade.fills:
        entry_price = entry_trade.fills[0].execution.price

    qty = abs(stop_order.totalQuantity) if stop_order and hasattr(stop_order, 'totalQuantity') else 1

    exit_price = 0
    if exit_trade and exit_trade.fills:
        exit_price = exit_trade.fills[0].execution.price
        pnl = _pnl_from_fills_or_synthetic(
            exit_trade.fills, entry_price, exit_price, dir_, qty, log_label="bracket_exit"
        )
    else:
        # Fallback 1: Scan recent fills for this contract to find the actual manual/untracked execution
        fallback_fill = None
        expected_side = 'SLD' if dir_ == 1 else 'BOT'
        
        # Ensure entry_time is comparable (aware vs naive)
        ref_time = entry_time

        for f in reversed(ib.fills()):
            if f.contract.conId == contract.conId and hasattr(f, 'execution') and f.execution.side == expected_side:
                f_time = f.execution.time
                if is_aware and f_time.tzinfo is None:
                    f_time = pytz.utc.localize(f_time)
                elif not is_aware and f_time.tzinfo is not None:
                    f_time = f_time.replace(tzinfo=None)
                
                # Only consider fills that happened AFTER this trade was initiated
                if ref_time and f_time < (ref_time - pd.Timedelta(seconds=5)):
                    continue

                if abs(f.execution.shares) >= qty:
                    fallback_fill = f; break
                
        if fallback_fill:
            exit_price = fallback_fill.execution.price
            pnl = (exit_price - entry_price) * dir_ * 50 * qty if entry_price > 0 else 0
        else:
            # Fallback 2: Guess using price
            exit_price = latest_row['close'] if latest_row is not None and (isinstance(latest_row, dict) and 'close' in latest_row or hasattr(latest_row, 'close')) else 0
            if exit_price == 0 and data is not None and not data.empty:
                exit_price = data['close'].iloc[-1]
            pnl = (exit_price - entry_price) * dir_ * 50 * qty if entry_price > 0 else 0

    # Duration and Notification
    exit_time = datetime.now()
    if is_aware:
        exit_time = exit_time.astimezone(pytz.utc)
    
    duration_str = format_duration((exit_time - entry_time).total_seconds()) if entry_time else "N/A"

    curr_stop = _effective_bracket_stop(stop_order, bracket, dir_) or 0
    broker_stop_at_exit = _broker_stop_trigger_price(stop_order)
    model_stop_at_exit = (bracket.get("position_dict") or {}).get("stop")
    if model_stop_at_exit is not None:
        model_stop_at_exit = _finite_stop_scalar(model_stop_at_exit)

    # Generate HTML report if possible
    report_url = ""
    if strategy:
        try:
            # Save to web/trades/
            trades_dir = os.path.join(os.getcwd(), 'web', 'trades')
            os.makedirs(trades_dir, exist_ok=True)
            tp_close_px = getattr(tp_order, 'lmtPrice', None) if tp_order else None
            slip_pre = _exit_slippage_metrics(
                dir_, exit_price, curr_stop or None, tp_close_px, reason, qty=qty,
                broker_stop_at_exit=broker_stop_at_exit,
                model_stop_at_exit=model_stop_at_exit,
            )
            report_path = strategy.generate_trade_report(
                {
                    'entry_time': entry_time, 'exit_time': exit_time,
                    'direction': dir_, 'entry_price': entry_price,
                    'exit_price': exit_price, 'pnl': pnl, 'qty': qty,
                    'reason': reason,
                    'live_exit_type': _live_exit_type(reason),
                    'exit_path': _exit_path(reason),
                    'stop_at_close': curr_stop or None,
                    'tp_at_close': tp_close_px,
                    'stop_at_open': bracket.get('entry_stop_price'),
                    'tp_at_open': bracket.get('entry_tp_price'),
                    'params_snapshot': bracket.get('params_snapshot') or {},
                    'slippage_pts': slip_pre.get('slippage_pts'),
                    'slippage_usd': slip_pre.get('slippage_usd'),
                    'slippage_reference': slip_pre.get('slippage_reference'),
                    'broker_stop_at_exit': broker_stop_at_exit,
                    'model_stop_at_exit': model_stop_at_exit,
                },
                data, trades_dir
            )
            if report_path:
                report_url = f"trades/{os.path.basename(report_path)}"
        except Exception as e:
            logging.error(f"Failed to generate HTML report: {e}")

    _send_trade_close_notification(
        ib, bracket, dir_, entry_price, exit_price, pnl, qty, reason, 
        duration_str, exit_time, data, send_email_fn, live_tracker,
        report_url=report_url
    )

    logging.info(f"TRADE CLOSE: {reason} @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")
    bracket["_close_reason"] = reason
    add_to_live_tracker(live_tracker, 'trade',
        f"CLOSE ({reason}): @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")
    
    # Risk calculation for completed record
    initial_risk = abs(entry_price - curr_stop) * 50 * qty if curr_stop else 0
    r_multiple = pnl / initial_risk if initial_risk > 0 else 0
    tp_close_px = getattr(tp_order, 'lmtPrice', None) if tp_order else None
    slip = _exit_slippage_metrics(
        dir_, exit_price, curr_stop or None, tp_close_px, reason, qty=qty,
        broker_stop_at_exit=broker_stop_at_exit,
        model_stop_at_exit=model_stop_at_exit,
    )

    _append_completed_trade_record(completed_trades, {
        'exit_time': exit_time, 'entry_time': entry_time,
        'direction': 'LONG' if dir_ == 1 else 'SHORT',
        'qty': qty, 'entry_price': entry_price, 'exit_price': exit_price,
        'pnl': pnl, 'r_multiple': r_multiple, 'reason': reason,
        'live_exit_type': _live_exit_type(reason),
        'exit_path': _exit_path(reason),
        'duration': duration_str,
        'report_url': report_url,
        'params_snapshot': bracket.get('params_snapshot') or {},
        'stop_at_open': bracket.get('entry_stop_price'),
        'tp_at_open': bracket.get('entry_tp_price'),
        'stop_at_close': curr_stop or None,
        'tp_at_close': tp_close_px,
        'entry_order_id': bracket.get('entryOrderId'),
        'slippage_pts': slip.get('slippage_pts'),
        'slippage_usd': slip.get('slippage_usd'),
        'slippage_reference': slip.get('slippage_reference'),
        'model_stop_at_exit': slip.get('model_stop_at_exit'),
        'broker_stop_at_exit': slip.get('broker_stop_at_exit'),
    })

    # Remove any non-terminal legs on this conId (includes **Inactive** TP after OCA replace races).
    try:
        cancel_residual_orders_when_flat_on_contract(ib, contract, live_tracker)
    except Exception as e:
        logging.error(f"Error during final orphan cleanup: {e}")
    return exit_trade

"""
core/protection.py - Position Protection & Orphan Management
Ported from ib_deployment_v4.py lines 1575-3752
"""
import logging
import asyncio
import time
import pandas as pd
from datetime import datetime
from ib_insync import MarketOrder, StopOrder, LimitOrder

from core.account import get_account_summary, add_to_live_tracker
from core.client_id_guard import (
    log_placement_blocked,
    run_client_id_integrity_check,
    trading_orders_allowed,
)
import pytz


def _ib_refresh_open_orders(ib):
    """Ensure ib.trades() includes working orders from all API clients (not only this session)."""
    try:
        ib.reqAllOpenOrders()
        ib.sleep(0.2)
    except Exception:
        try:
            ib.reqOpenOrders()
            ib.sleep(0.15)
        except Exception:
            pass


def _session_client_id(ib) -> int:
    try:
        return int(getattr(getattr(ib, "client", None), "clientId", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _order_belongs_to_session(ib, order) -> bool:
    cid = _session_client_id(ib)
    if cid <= 0:
        return True
    try:
        return int(getattr(order, "clientId", 0) or 0) in (0, cid)
    except (TypeError, ValueError):
        return True


# IB "Inactive" (e.g. rejected bracket TP after OCA replace) is NOT in OrderStatus.DoneStates,
# but isActive() is often False — code that only scans isActive() leaves these on the blotter forever.
_IB_TERMINAL_BLOTTER = frozenset({"Filled", "Cancelled", "ApiCancelled"})
# PreSubmitted/trigger is NOT armed on the exchange — only Submitted stops can fill.
_ARMED_STOP_STATUSES = frozenset({"Submitted"})
_PENDING_STOP_STATUSES = frozenset({"PreSubmitted", "PendingSubmit", "ApiPending"})
# Minimum seconds between placeOrder re-protect attempts per (conId, direction).
_REPROTECT_MIN_INTERVAL_SEC = 90.0
_reprotect_last_attempt: dict = {}


def bracket_guard_blocks_flat_cleanup(positions, contract) -> bool:
    """
    True when flat-book cleanup must not run — bracket entry in flight or guard window active.
    IB position can still read 0 for ~500ms after a market entry fill.
    """
    if not positions or contract is None:
        return False
    now = datetime.now(pytz.utc)
    cid = contract.conId
    for bracket in positions:
        bc = bracket.get("contract")
        if bc is not None and getattr(bc, "conId", None) != cid:
            continue
        guard_until = bracket.get("guard_until")
        if guard_until is not None:
            gu = guard_until if getattr(guard_until, "tzinfo", None) else pytz.utc.localize(guard_until)
            if now < gu:
                return True
        if bracket.get("direction") and not bracket.get("open_notified"):
            return True
        created = bracket.get("created_at")
        if created is not None and not bracket.get("open_notified"):
            ca = created if getattr(created, "tzinfo", None) else pytz.utc.localize(created)
            if (now - ca).total_seconds() < 45:
                return True
    return False


def trade_order_needs_flat_book_cancel(trade) -> bool:
    """True if we should send cancelOrder when intentionally flattening the book for a contract/account."""
    st = (getattr(trade.orderStatus, "status", None) or "").strip()
    if st in _IB_TERMINAL_BLOTTER:
        return False
    return True


def cancel_residual_orders_when_flat_on_contract(
    ib, contract, live_tracker=None, positions=None,
) -> int:
    """
    When position size is 0 for ``contract``, cancel every non-terminal order on that conId.

    Catches **Inactive** take-profit / OCA legs that ``trade.isActive()`` skips.
    Returns number of cancelOrder calls issued (may include already-dead orders; errors swallowed).

    Skipped while ``positions`` has an in-flight bracket (``guard_until`` / unfilled entry) so
    flat-book cleanup cannot cancel bracket legs before IB reports the fill.
    """
    if contract is None or not ib.isConnected():
        return 0
    if bracket_guard_blocks_flat_cleanup(positions, contract):
        logging.debug(
            "Flat-book cleanup skipped (%s): bracket entry guard active",
            getattr(contract, "localSymbol", contract),
        )
        return 0
    try:
        _ib_refresh_open_orders(ib)
        pos = 0.0
        for p in ib.positions():
            if p.contract.conId == contract.conId:
                pos = float(p.position)
                break
        if abs(pos) > 1e-9:
            return 0
        n = 0
        for trade in list(ib.trades()):
            if trade.contract.conId != contract.conId:
                continue
            if not trade_order_needs_flat_book_cancel(trade):
                continue
            try:
                ib.cancelOrder(trade.order)
                n += 1
                logging.info(
                    "Flat-book cleanup (%s): cancelled %s %s permId=%s status=%s",
                    contract.localSymbol,
                    getattr(trade.order, "orderType", "?"),
                    getattr(trade.order, "action", "?"),
                    getattr(trade.order, "permId", 0),
                    getattr(trade.orderStatus, "status", ""),
                )
            except Exception as e:
                logging.debug(
                    "Flat-book cleanup skip permId=%s: %s",
                    getattr(trade.order, "permId", 0),
                    e,
                )
        if n and live_tracker:
            add_to_live_tracker(
                live_tracker,
                "info",
                f"Flat cleanup: removed {n} residual order(s) on {contract.localSymbol}",
            )
        return n
    except Exception as e:
        logging.error("cancel_residual_orders_when_flat_on_contract: %s", e)
        return 0


def cancel_residual_es_orders_when_no_es_position(ib, live_tracker=None) -> int:
    """When no ES contract has non-zero size, cancel every non-terminal ES order (any expiry)."""
    if not ib.isConnected():
        return 0
    try:
        _ib_refresh_open_orders(ib)
        if any(abs(float(p.position)) > 1e-9 for p in ib.positions() if p.contract.symbol == "ES"):
            return 0
        n = 0
        for trade in list(ib.trades()):
            if getattr(trade.contract, "symbol", None) != "ES":
                continue
            if not trade_order_needs_flat_book_cancel(trade):
                continue
            try:
                ib.cancelOrder(trade.order)
                n += 1
            except Exception:
                pass
        if n:
            logging.warning("No ES position: cancelled %s residual ES order(s)", n)
            if live_tracker:
                add_to_live_tracker(
                    live_tracker,
                    "warning",
                    f"No ES exposure: removed {n} residual ES order(s)",
                )
        return n
    except Exception as e:
        logging.error("cancel_residual_es_orders_when_no_es_position: %s", e)
        return 0


def _trade_non_terminal(trade) -> bool:
    try:
        if hasattr(trade, "isDone") and trade.isDone():
            return False
    except Exception:
        pass
    st = getattr(trade.orderStatus, "status", "") or ""
    return st not in ("Filled", "Cancelled", "Inactive", "ApiCancelled")


def stop_order_is_armed(trade) -> bool:
    """True when IB stop is Submitted (armed on server and can fill)."""
    if not trade or not _order_looks_like_protective_stop(trade.order):
        return False
    st = (getattr(trade.orderStatus, "status", None) or "").strip()
    return st in _ARMED_STOP_STATUSES


def stop_order_is_pending(trade) -> bool:
    """True for PreSubmitted / trigger stops that are not yet armed."""
    if not trade or not _order_looks_like_protective_stop(trade.order):
        return False
    st = (getattr(trade.orderStatus, "status", None) or "").strip()
    if st in _IB_TERMINAL_BLOTTER or st in ("Inactive", "PendingCancel"):
        return False
    return st in _PENDING_STOP_STATUSES


def _trade_has_working_protective_stop(trade) -> bool:
    """True only for **armed** stop orders (Submitted) — not PreSubmitted/trigger."""
    return stop_order_is_armed(trade)


def _order_looks_like_protective_stop(order) -> bool:
    """IB often delivers STP as generic Order(orderType='STP'), not StopOrder."""
    if isinstance(order, StopOrder):
        return True
    ot = str(getattr(order, "orderType", "") or "").upper()
    if "STP" in ot or ot in ("TRAIL", "TRAIL LIMIT", "TRAIL MIT"):
        return True
    try:
        ap = float(getattr(order, "auxPrice", 0) or 0)
    except (TypeError, ValueError):
        ap = 0.0
    try:
        lp = float(getattr(order, "lmtPrice", 0) or 0)
    except (TypeError, ValueError):
        lp = 0.0
    try:
        sp = float(getattr(order, "stopPrice", 0) or 0)
    except (TypeError, ValueError):
        sp = 0.0
    if sp > 0 and abs(lp) < 1e-9:
        return True
    return ap > 0 and abs(lp) < 1e-9


def _stop_trigger_price(order, bracket=None) -> float:
    """Best-effort stop trigger from order object or bracket snapshot."""
    for attr in ("auxPrice", "stopPrice"):
        try:
            v = float(getattr(order, attr, 0) or 0)
            if v > 0:
                return round(v * 4) / 4
        except (TypeError, ValueError):
            pass
    if bracket:
        for key in ("entry_stop_price",):
            try:
                v = float(bracket.get(key) or 0)
                if v > 0:
                    return round(v * 4) / 4
            except (TypeError, ValueError):
                pass
        pd_stop = (bracket.get("position_dict") or {}).get("stop")
        try:
            v = float(pd_stop or 0)
            if v > 0:
                return round(v * 4) / 4
        except (TypeError, ValueError):
            pass
    return 0.0


def _find_trade_for_order(ib, contract, order):
    if not order:
        return None
    cid = getattr(contract, "conId", None)
    perm = int(getattr(order, "permId", 0) or 0)
    oid = int(getattr(order, "orderId", 0) or 0)
    for trade in ib.trades():
        if cid is not None and trade.contract.conId != cid:
            continue
        o = trade.order
        if perm and o.permId == perm:
            return trade
        if oid and o.orderId == oid:
            return trade
    return None


def _wait_stop_submitted(
    ib, order, contract=None, timeout: float = 2.0, accept_pending: bool = False,
) -> bool:
    """Poll until stop order reaches Submitted (armed) or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        trade = _find_trade_for_order(ib, contract, order)
        if trade and stop_order_is_armed(trade):
            if getattr(trade.order, "permId", 0):
                order.permId = trade.order.permId
            return True
        if accept_pending and trade and stop_order_is_pending(trade):
            if getattr(trade.order, "permId", 0):
                order.permId = trade.order.permId
            return True
        ib.sleep(0.12)
    return False


def _mark_trail_replace_started(bracket) -> None:
    if bracket is not None:
        bracket["trail_replace_started_at"] = datetime.now(pytz.utc)


def _clear_trail_replace_started(bracket) -> None:
    if bracket is not None:
        bracket.pop("trail_replace_started_at", None)


def trail_replace_in_progress(positions) -> bool:
    """True while a trailing stop zero-gap replace is in flight."""
    now = datetime.now(pytz.utc)
    for bracket in positions or []:
        t0 = bracket.get("trail_replace_started_at")
        if t0 is None:
            continue
        t0 = t0 if getattr(t0, "tzinfo", None) else pytz.utc.localize(t0)
        if (now - t0).total_seconds() < 45:
            return True
    return False


def _fresh_trail_oca_group(contract, direction: int) -> str:
    """Unique OCA group — IB rejects new legs while an existing group is occupied."""
    con_id = getattr(contract, "conId", 0) or 0
    return f"trail_{con_id}_{direction}_{int(time.time() * 1000)}"


def _cancel_order_quiet(ib, order) -> None:
    if not order:
        return
    try:
        ib.cancelOrder(order)
    except Exception:
        pass


def _contract_for_order(contract):
    """IB rejects futures orders without exchange (Error 321)."""
    if contract is None:
        return contract
    if not getattr(contract, "exchange", None):
        contract.exchange = getattr(contract, "primaryExchange", None) or "CME"
    if not getattr(contract, "primaryExchange", None):
        contract.primaryExchange = contract.exchange or "CME"
    return contract


def _place_standalone_exit_pair(
    ib,
    contract,
    direction: int,
    qty: float,
    stop_px: float,
    tp_lmt=None,
    oca_group: str = None,
):
    """Standalone SL (+ optional OCA-linked TP). Returns (stop_order, tp_order|None)."""
    if not trading_orders_allowed():
        log_placement_blocked("standalone SL/TP")
        return None, None
    stop_action = "SELL" if direction == 1 else "BUY"
    new_stop = StopOrder(
        action=stop_action,
        totalQuantity=qty,
        stopPrice=stop_px,
        tif="GTC",
        transmit=False,
        parentId=0,
    )
    new_tp = None
    if tp_lmt is not None and oca_group:
        tp_action = "SELL" if direction == 1 else "BUY"
        new_stop.ocaGroup = oca_group
        new_stop.ocaType = 1
        new_tp = LimitOrder(
            action=tp_action,
            totalQuantity=qty,
            lmtPrice=tp_lmt,
            tif="GTC",
            ocaGroup=oca_group,
            ocaType=1,
            transmit=True,
            parentId=0,
        )
    else:
        new_stop.transmit = True
    ib.placeOrder(contract, new_stop)
    if new_tp:
        ib.placeOrder(contract, new_tp)
    ib.sleep(0.25)
    return new_stop, new_tp


def promote_bracket_stop_to_standalone(
    ib, contract, bracket, live_tracker=None, timeout: float = 2.0,
) -> bool:
    """
    If bracket stop is PreSubmitted/trigger, place standalone armed stop (+ TP if OCA),
    verify Submitted, then cancel old child legs.
    """
    if not ib.isConnected() or bracket is None:
        return False
    bc = bracket.get("contract") or contract
    stop_order = bracket.get("stopLoss")
    if not stop_order:
        return False

    stop_trade = _find_trade_for_order(ib, bc, stop_order)
    if stop_trade and stop_order_is_armed(stop_trade):
        return True

    direction = int(bracket.get("direction", 1))
    qty = abs(float(getattr(stop_order, "totalQuantity", 1) or 1))
    stop_px = _stop_trigger_price(stop_order, bracket)
    if stop_px <= 0:
        logging.error("promote_bracket_stop_to_standalone: no valid stop price")
        return False

    tp_order = bracket.get("takeProfit")
    tp_lmt = None
    if tp_order:
        try:
            tp_lmt = round(float(getattr(tp_order, "lmtPrice", 0) or 0) * 4) / 4
            if tp_lmt <= 0:
                tp_lmt = None
        except (TypeError, ValueError):
            tp_lmt = None
    if tp_lmt is None:
        try:
            raw = bracket.get("entry_tp_price")
            if raw is not None and float(raw) > 0:
                tp_lmt = round(float(raw) * 4) / 4
        except (TypeError, ValueError):
            tp_lmt = None

    oca_group = bracket.get("ocaGroup") if tp_lmt else None
    old_stop, old_tp = stop_order, tp_order

    new_stop, new_tp = _place_standalone_exit_pair(
        ib, bc, direction, qty, stop_px, tp_lmt=tp_lmt, oca_group=oca_group,
    )
    if not _wait_stop_submitted(ib, new_stop, bc, timeout=timeout, accept_pending=True):
        logging.warning(
            "Stop promote failed: new leg not Submitted within %.1fs (target %.2f); cancelling new legs",
            timeout,
            stop_px,
        )
        _cancel_order_quiet(ib, new_stop)
        _cancel_order_quiet(ib, new_tp)
        return False

    _cancel_order_quiet(ib, old_stop)
    _cancel_order_quiet(ib, old_tp)
    ib.sleep(0.2)

    bracket["stopLoss"] = new_stop
    if new_tp:
        bracket["takeProfit"] = new_tp

    sym = getattr(bc, "localSymbol", bc)
    logging.info("Stop promoted to standalone Submitted on %s @ %.2f", sym, stop_px)
    if live_tracker:
        add_to_live_tracker(
            live_tracker,
            "order",
            f"Stop armed (Submitted) @ ${stop_px:,.2f} on {sym}",
        )
    return True


def replace_trailing_stop_zero_gap(
    ib,
    contract,
    bracket,
    new_stop_px: float,
    direction: int,
    old_stop_order,
    live_tracker=None,
    timeout: float = 5.0,
) -> bool:
    """
    Trailing update: place a standalone stop at the new price, wait until live on IB,
    then cancel the old stop only (TP unchanged). Avoids reusing an occupied OCA group.
    """
    if not ib.isConnected() or bracket is None:
        return False
    bc = _contract_for_order(bracket.get("contract") or contract)
    qty = abs(float(getattr(old_stop_order, "totalQuantity", 1) or 1))
    new_stop_px = round(float(new_stop_px) * 4) / 4
    old_px = _stop_trigger_price(old_stop_order, bracket)
    _mark_trail_replace_started(bracket)
    try:
        if not trading_orders_allowed():
            log_placement_blocked("trailing stop replace")
            return False
        stop_action = "SELL" if direction == 1 else "BUY"
        new_stop = StopOrder(
            action=stop_action,
            totalQuantity=qty,
            stopPrice=new_stop_px,
            tif="GTC",
            transmit=True,
            parentId=0,
        )
        ib.placeOrder(bc, new_stop)
        ib.sleep(0.2)
        if not _wait_stop_submitted(
            ib, new_stop, bc, timeout=timeout, accept_pending=True,
        ):
            logging.error(
                "Trailing stop replace: new stop %.2f not live within %.1fs; keeping old leg @ %.2f",
                new_stop_px,
                timeout,
                old_px,
            )
            _cancel_order_quiet(ib, new_stop)
            return False

        _cancel_order_quiet(ib, old_stop_order)
        ib.sleep(0.2)

        bracket["stopLoss"] = new_stop
        pd = bracket.get("position_dict")
        if isinstance(pd, dict):
            pd["stop"] = new_stop_px
        logging.info(
            "Trailing stop zero-gap replace: %.2f -> %.2f (stop only, TP unchanged)",
            old_px,
            new_stop_px,
        )
        if live_tracker:
            add_to_live_tracker(
                live_tracker,
                "order",
                f"Trailing stop -> ${new_stop_px:.2f}",
            )
        return True
    finally:
        _clear_trail_replace_started(bracket)


def replace_oca_exit_pair_zero_gap(
    ib,
    contract,
    bracket,
    new_stop_px: float,
    tp_lmt_px: float,
    direction: int,
    old_stop_order,
    old_tp_order,
    live_tracker=None,
    timeout: float = 5.0,
) -> bool:
    """
    Full OCA SL+TP replace when both legs must move. Uses a fresh OCA group — IB rejects
    new orders while the existing bracket group still has live members.
    """
    bc = bracket.get("contract") or contract
    qty = abs(float(getattr(old_stop_order, "totalQuantity", 1) or 1))
    oca_group = _fresh_trail_oca_group(bc, direction)
    new_stop_px = round(float(new_stop_px) * 4) / 4
    tp_lmt_px = round(float(tp_lmt_px) * 4) / 4

    _mark_trail_replace_started(bracket)
    try:
        new_stop, new_tp = _place_standalone_exit_pair(
            ib, bc, direction, qty, new_stop_px, tp_lmt=tp_lmt_px, oca_group=oca_group,
        )
        if not _wait_stop_submitted(
            ib, new_stop, bc, timeout=timeout, accept_pending=True,
        ):
            logging.error(
                "Zero-gap OCA replace: new stop %.2f not live; keeping old legs",
                new_stop_px,
            )
            _cancel_order_quiet(ib, new_stop)
            _cancel_order_quiet(ib, new_tp)
            return False

        _cancel_order_quiet(ib, old_stop_order)
        _cancel_order_quiet(ib, old_tp_order)
        ib.sleep(0.2)

        bracket["stopLoss"] = new_stop
        bracket["takeProfit"] = new_tp
        bracket["ocaGroup"] = oca_group
        logging.info(
            "Trailing OCA zero-gap replace: SL -> %.2f, TP %.2f (new group %s)",
            new_stop_px,
            tp_lmt_px,
            oca_group,
        )
        if live_tracker:
            add_to_live_tracker(
                live_tracker,
                "order",
                f"Trailing SL+TP (zero-gap) SL ${new_stop_px:.2f} TP ${tp_lmt_px:.2f}",
            )
        return True
    finally:
        _clear_trail_replace_started(bracket)


def ensure_bracket_stop_armed(ib, contract, bracket, live_tracker=None) -> bool:
    """Ensure bracket stop is Submitted; accept pending session stop; promote only if missing."""
    if not ib.isConnected() or bracket is None:
        return False
    stop_order = bracket.get("stopLoss")
    if not stop_order:
        return False
    bc = bracket.get("contract") or contract
    stop_trade = _find_trade_for_order(ib, bc, stop_order)
    if stop_trade and stop_order_is_armed(stop_trade):
        return True

    # Bracket handle may point at a cancelled leg after consolidate — prefer live IB stop
    try:
        open_pos = [
            p for p in ib.positions()
            if p.contract.conId == bc.conId and abs(float(p.position)) > 1e-9
        ]
    except Exception:
        open_pos = []
    if open_pos:
        live = _find_protective_stop_trade_for_position(ib, open_pos[0])
        if live and (stop_order_is_armed(live) or stop_order_is_pending(live)):
            bracket["stopLoss"] = live.order
            px = _stop_trigger_price(live.order, bracket)
            if px > 0:
                bracket["entry_stop_price"] = px
            return True

    last_promote = bracket.get("last_stop_promote_ts")
    if last_promote is not None:
        lp = last_promote if getattr(last_promote, "tzinfo", None) else pytz.utc.localize(last_promote)
        if (datetime.now(pytz.utc) - lp).total_seconds() < 45:
            return False

    direction = int(bracket.get("direction", 1))
    stop_px = _stop_trigger_price(stop_order, bracket)
    stop_action = "SELL" if direction == 1 else "BUY"
    if stop_px > 0:
        for t in ib.trades():
            if t.contract.conId != bc.conId:
                continue
            if not _order_looks_like_protective_stop(t.order):
                continue
            if getattr(t.order, "action", "") != stop_action:
                continue
            px = _stop_trigger_price(t.order, None)
            if px > 0 and abs(px - stop_px) <= 0.26:
                bracket["stopLoss"] = t.order
                if stop_order_is_armed(t):
                    return True
                if stop_order_is_pending(t):
                    logging.debug(
                        "Stop acceptable (pending) @ %.2f on %s — skip promote",
                        px,
                        getattr(bc, "localSymbol", bc),
                    )
                    return True
                logging.debug(
                    "Stop promote skipped: session already has stop @ %.2f (status=%s)",
                    px,
                    getattr(t.orderStatus, "status", "?"),
                )
                return False

    bracket["last_stop_promote_ts"] = datetime.now(pytz.utc)
    return promote_bracket_stop_to_standalone(
        ib, bc, bracket, live_tracker=live_tracker, timeout=2.0,
    )


def ensure_all_bracket_stops_armed(ib, contract, positions, live_tracker=None) -> int:
    """Promote pending stops on all tracked brackets. Returns count armed/promoted."""
    if not ib.isConnected() or not positions:
        return 0
    n = 0
    for bracket in positions:
        if not bracket.get("stopLoss"):
            continue
        bc = bracket.get("contract") or contract
        if ensure_bracket_stop_armed(ib, bc, bracket, live_tracker):
            n += 1
    return n


def _stop_tightness_rank(px: float, direction: int) -> int:
    """Higher = tighter protective stop for this direction (dominates duplicate resolution)."""
    if px <= 0:
        return 0
    if direction == 1:
        return int(round(px * 100))
    if direction == -1:
        return int(round((10000.0 - px) * 100))
    return 0


def _exit_leg_rank(
    trade,
    tracked_perm_ids: set,
    session_cid: int,
    is_stop: bool,
    ib,
    reference_stop_px: float = 0.0,
    direction: int = 0,
) -> int:
    """Higher = prefer keeping this exit leg (tighter stop / armed / tracked)."""
    score = 0
    if is_stop:
        px = _stop_trigger_price(trade.order, None)
        score += _stop_tightness_rank(px, direction)
        if stop_order_is_armed(trade):
            score += 2000
        elif stop_order_is_pending(trade):
            score += 200
    else:
        st = (getattr(trade.orderStatus, "status", None) or "").strip()
        if st == "Submitted":
            score += 2000
        elif st in _PENDING_STOP_STATUSES:
            score += 200
    perm = int(getattr(trade.order, "permId", 0) or 0)
    if perm in tracked_perm_ids:
        score += 800
    if perm > 0:
        score += max(0, 300 - perm // 10_000_000)
    if reference_stop_px > 0 and is_stop and direction == 0:
        px = _stop_trigger_price(trade.order, None)
        if px > 0:
            score += max(0, 250 - int(abs(px - reference_stop_px) * 20))
    try:
        if int(getattr(trade.order, "clientId", 0) or 0) == session_cid:
            score += 50
    except (TypeError, ValueError):
        pass
    if _order_belongs_to_session(ib, trade.order):
        score += 25
    return score


def _reference_stop_px_for_position(positions, pos) -> float:
    direction = 1 if pos.position > 0 else -1
    con_id = pos.contract.conId
    for bracket in positions or []:
        if bracket.get("direction") != direction:
            continue
        bc = bracket.get("contract")
        if bc is not None and getattr(bc, "conId", None) not in (None, con_id):
            continue
        pd_stop = (bracket.get("position_dict") or {}).get("stop")
        entry_stop = bracket.get("entry_stop_price") or _stop_trigger_price(
            bracket.get("stopLoss"), bracket,
        )
        candidates = []
        for raw in (pd_stop, entry_stop):
            try:
                v = float(raw or 0)
                if v > 0:
                    candidates.append(v)
            except (TypeError, ValueError):
                pass
        if not candidates:
            continue
        if direction == 1:
            return max(candidates)
        return min(candidates)
    return 0.0


def _reprotect_throttle_ok(con_id: int, direction: int) -> bool:
    key = (int(con_id), int(direction))
    now = time.monotonic()
    last = _reprotect_last_attempt.get(key, 0.0)
    if now - last < _REPROTECT_MIN_INTERVAL_SEC:
        return False
    _reprotect_last_attempt[key] = now
    return True


def consolidate_duplicate_protective_orders(ib, contract, positions, live_tracker=None) -> int:
    """
    Keep at most one stop + one TP per open ES exposure; cancel duplicate session legs.
    Returns number of cancelOrder calls issued.
    """
    if not ib.isConnected():
        return 0
    if trail_replace_in_progress(positions):
        logging.debug("Consolidate skipped: trailing stop replace in progress")
        return 0
    _ib_refresh_open_orders(ib)
    tracked_perm_ids = set()
    for bracket in positions or []:
        for key in ("entry", "stopLoss", "takeProfit"):
            order = bracket.get(key)
            if order and getattr(order, "permId", 0):
                tracked_perm_ids.add(int(order.permId))

    session_cid = _session_client_id(ib)
    cancelled = 0
    try:
        es_open = [p for p in ib.positions() if p.contract.symbol == "ES" and p.position != 0]
    except Exception as e:
        logging.error("consolidate_duplicate_protective_orders: %s", e)
        return 0

    for pos in es_open:
        direction = 1 if pos.position > 0 else -1
        qty = abs(float(pos.position))
        need_action = "SELL" if direction == 1 else "BUY"
        cid = pos.contract.conId
        ref_stop_px = _reference_stop_px_for_position(positions, pos)

        stops, limits, dead = [], [], []
        for trade in ib.trades():
            if trade.contract.conId != cid:
                continue
            order = trade.order
            if getattr(order, "action", "") != need_action:
                continue
            try:
                tq = abs(float(getattr(order, "totalQuantity", 0) or 0))
            except (TypeError, ValueError):
                continue
            if abs(tq - qty) > 1e-9:
                continue
            st = (getattr(trade.orderStatus, "status", None) or "").strip()
            if st in _IB_TERMINAL_BLOTTER:
                continue
            if st in ("Inactive", "PendingCancel"):
                dead.append(trade)
                continue
            if _order_looks_like_protective_stop(order):
                stops.append(trade)
            elif (
                str(getattr(order, "orderType", "") or "").upper() in ("LMT", "LIMIT")
                or float(getattr(order, "lmtPrice", 0) or 0) > 0
            ):
                limits.append(trade)

        for trade in dead:
            if _order_belongs_to_session(ib, trade.order):
                _cancel_order_quiet(ib, trade.order)
                cancelled += 1

        for bucket, is_stop in ((stops, True), (limits, False)):
            if len(bucket) <= 1:
                continue
            ranked = sorted(
                bucket,
                key=lambda t: _exit_leg_rank(
                    t,
                    tracked_perm_ids,
                    session_cid,
                    is_stop,
                    ib,
                    ref_stop_px if is_stop else 0.0,
                    direction,
                ),
                reverse=True,
            )
            keeper = ranked[0]
            kperm = getattr(keeper.order, "permId", 0)
            kpx = _stop_trigger_price(keeper.order, None) if is_stop else getattr(keeper.order, "lmtPrice", 0)
            for trade in ranked[1:]:
                if not _order_belongs_to_session(ib, trade.order):
                    continue
                if getattr(trade.order, "permId", 0) == kperm:
                    continue
                perm = getattr(trade.order, "permId", 0)
                logging.info(
                    "Consolidate: cancelling duplicate %s permId=%s (keeping permId=%s @ %s)",
                    "stop" if is_stop else "TP",
                    perm,
                    kperm,
                    kpx,
                )
                _cancel_order_quiet(ib, trade.order)
                cancelled += 1

        session_stops = [t for t in stops if _order_belongs_to_session(ib, t.order)]
        foreign_stops = [t for t in stops if not _order_belongs_to_session(ib, t.order)]
        if len(session_stops) > 1 and foreign_stops:
            logging.info(
                "%s: keeping foreign stop clientId(s) %s; cancelled %s duplicate session leg(s)",
                getattr(pos.contract, "localSymbol", "ES"),
                sorted({getattr(t.order, "clientId", "?") for t in foreign_stops}),
                max(0, len(session_stops) - 1),
            )

    if cancelled and live_tracker:
        add_to_live_tracker(
            live_tracker,
            "info",
            f"Consolidated protective orders: cancelled {cancelled} duplicate leg(s)",
        )
    if cancelled:
        ib.sleep(0.3)
    return cancelled


def _find_protective_stop_trade_for_position(ib, pos):
    """Best stop trade for this ES exposure (armed preferred, then oldest permId)."""
    qty = abs(pos.position)
    direction = 1 if pos.position > 0 else -1
    need_action = "SELL" if direction == 1 else "BUY"
    cid = pos.contract.conId
    candidates = []
    for trade in ib.trades():
        if trade.contract.conId != cid:
            continue
        if not _order_looks_like_protective_stop(trade.order):
            continue
        order = trade.order
        if getattr(order, "action", "") != need_action:
            continue
        try:
            tq = abs(float(getattr(order, "totalQuantity", 0) or 0))
        except (TypeError, ValueError):
            continue
        if tq != qty:
            continue
        st = (getattr(trade.orderStatus, "status", None) or "").strip()
        if st in _IB_TERMINAL_BLOTTER or st in ("Inactive", "PendingCancel"):
            continue
        if stop_order_is_armed(trade) or stop_order_is_pending(trade):
            candidates.append(trade)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    def _rank(t):
        score = 0
        if stop_order_is_armed(t):
            score += 1000
        perm = int(getattr(t.order, "permId", 0) or 0)
        if perm > 0:
            score += max(0, 500 - perm // 10_000_000)
        return score

    return max(candidates, key=_rank)


def _ensure_strategy_indicators(strategy, data) -> None:
    """Indicators required by setup_position (atr, etc.) may be missing before first bar."""
    if data is None or data.empty or strategy is None:
        return
    if "atr" in data.columns and not pd.isna(data["atr"].iloc[-1]):
        return
    try:
        from core.monitoring import update_indicators
        update_indicators(strategy, data)
    except Exception as e:
        logging.warning("Could not compute indicators for protection: %s", e)


def _try_promote_pending_stop_for_position(ib, pos, positions, live_tracker=None) -> bool:
    """Promote PreSubmitted stop on IB to standalone Submitted without duplicating legs."""
    trade = _find_protective_stop_trade_for_position(ib, pos)
    if trade is None or stop_order_is_armed(trade):
        return bool(trade and stop_order_is_armed(trade))
    if not _order_belongs_to_session(ib, trade.order):
        return adopt_ib_protection_for_position(ib, positions, pos, live_tracker=live_tracker)

    direction = 1 if pos.position > 0 else -1
    qty = abs(pos.position)
    con_id = pos.contract.conId
    stop_order = trade.order
    oca_group = getattr(stop_order, "ocaGroup", None) or None
    tp_order = None
    need_action = "SELL" if direction == 1 else "BUY"
    for t in ib.trades():
        if t.contract.conId != con_id:
            continue
        o = t.order
        ot = str(getattr(o, "orderType", "") or "").upper()
        if ot not in ("LMT", "LIMIT"):
            continue
        if getattr(o, "action", "") != need_action:
            continue
        try:
            tq = abs(float(getattr(o, "totalQuantity", 0) or 0))
        except (TypeError, ValueError):
            continue
        if tq != qty:
            continue
        st = (getattr(t.orderStatus, "status", None) or "").strip()
        if st in _IB_TERMINAL_BLOTTER or st in ("Inactive", "PendingCancel"):
            continue
        if oca_group and getattr(o, "ocaGroup", None) == oca_group:
            tp_order = o
            break

    stop_px = _stop_trigger_price(stop_order, None)
    bracket = {
        "stopLoss": stop_order,
        "takeProfit": tp_order,
        "direction": direction,
        "ocaGroup": oca_group,
        "contract": pos.contract,
        "entry_stop_price": stop_px,
        "entry_tp_price": getattr(tp_order, "lmtPrice", None) if tp_order else None,
    }
    if promote_bracket_stop_to_standalone(ib, pos.contract, bracket, live_tracker=live_tracker):
        if not _bracket_already_tracked(positions, direction, qty, con_id):
            positions.append({
                "entry": MarketOrder(
                    action="BUY" if direction == 1 else "SELL", totalQuantity=qty, tif="GTC",
                ),
                "stopLoss": bracket["stopLoss"],
                "takeProfit": bracket.get("takeProfit"),
                "direction": direction,
                "position_dict": {"direction": direction, "stop": stop_px},
                "entry_time": datetime.now(),
                "entry_price": float(getattr(pos, "avgCost", 0) or 0) / 50.0,
                "entry_stop_price": stop_px,
                "entry_tp_price": bracket.get("entry_tp_price"),
                "contract": pos.contract,
                "ocaGroup": oca_group,
                "open_notified": True,
                "restored_from_ib": True,
            })
        return True
    return False


def es_position_has_protective_exit_orders(ib, pos, refresh: bool = True) -> bool:
    """True if an **armed** (Submitted) stop matches this ES exposure."""
    if refresh:
        _ib_refresh_open_orders(ib)
    qty = abs(pos.position)
    direction = 1 if pos.position > 0 else -1
    need_action = "SELL" if direction == 1 else "BUY"
    cid = pos.contract.conId
    for trade in ib.trades():
        if trade.contract.conId != cid or not _trade_has_working_protective_stop(trade):
            continue
        order = trade.order
        if getattr(order, "action", "") != need_action:
            continue
        try:
            tq = abs(float(getattr(order, "totalQuantity", 0) or 0))
        except (TypeError, ValueError):
            continue
        if tq != qty:
            continue
        return True
    return False


def es_position_has_acceptable_stop(ib, pos, refresh: bool = True, session_only: bool = False) -> bool:
    """
    True when the position has a protective stop that is good enough to skip re-protect.

    By default checks **all** API clientIds on the account (critical after reconnect when
    clientId rotates). Armed (Submitted) or PreSubmitted/trigger both count.
    """
    if es_position_has_protective_exit_orders(ib, pos, refresh=refresh):
        return True
    if refresh:
        _ib_refresh_open_orders(ib)
    trade = _find_protective_stop_trade_for_position(ib, pos)
    if trade is None or not stop_order_is_pending(trade):
        return False
    if session_only and not _order_belongs_to_session(ib, trade.order):
        return False
    return True


def _find_filled_entry_trade_for_position(ib, pos):
    """Most recent filled entry trade for an open ES position (restart/adopt wiring)."""
    direction = 1 if pos.position > 0 else -1
    want_action = "BUY" if direction == 1 else "SELL"
    try:
        qty = abs(float(pos.position))
    except (TypeError, ValueError):
        return None
    cid = pos.contract.conId
    candidates = []
    for trade in ib.trades():
        if trade.contract.conId != cid:
            continue
        st = (getattr(trade.orderStatus, "status", None) or "").strip()
        if not trade.filled() and st != "Filled":
            continue
        order = trade.order
        if getattr(order, "action", "") != want_action:
            continue
        ot = str(getattr(order, "orderType", "") or "").upper()
        if ot not in ("MKT", "MARKET", "LMT", "LIMIT"):
            continue
        try:
            tq = abs(float(getattr(order, "totalQuantity", 0) or 0))
        except (TypeError, ValueError):
            continue
        if abs(tq - qty) > 1e-9:
            continue
        candidates.append(trade)
    if not candidates:
        return None

    def _fill_ts(t):
        if not t.fills:
            return datetime.min.replace(tzinfo=pytz.utc)
        ft = _fill_timestamp_from_ib_fill(t.fills[0])
        if ft is None:
            return datetime.min.replace(tzinfo=pytz.utc)
        if getattr(ft, "tzinfo", None) is None:
            return pytz.utc.localize(ft)
        return ft

    return max(candidates, key=_fill_ts)


def _fill_timestamp_from_ib_fill(fill):
    """
    Best-effort UTC timestamp from an ib_insync Fill.

    Paper IB Gateway often sets ``execution.time`` ~4h ahead of ``fill.time``.
    ``main.log_execution`` uses ``fill.time``; bracket wiring must match.
    """
    if fill is None:
        return None
    for candidate in (
        getattr(fill, "time", None),
        getattr(getattr(fill, "execution", None), "time", None),
    ):
        if candidate is None:
            continue
        try:
            if pd.Timestamp(candidate) is pd.NaT:
                continue
        except Exception:
            continue
        return candidate
    return None


def _ib_fill_time_to_naive_et(ft):
    """IB fill timestamps are UTC; store naive US/Eastern for charts/reports."""
    if ft is None:
        return None
    try:
        ts = pd.Timestamp(ft)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert("America/New_York").tz_localize(None).to_pydatetime()
    except Exception:
        try:
            if getattr(ft, "tzinfo", None) is not None:
                return ft.astimezone(pytz.timezone("America/New_York")).replace(tzinfo=None)
        except Exception:
            pass
        return ft


def _ib_fill_to_naive_et(fill):
    """Convert an ib_insync Fill to naive US/Eastern (same clock as live_trades.csv)."""
    return _ib_fill_time_to_naive_et(_fill_timestamp_from_ib_fill(fill))


def _estimate_bars_held_since_entry(entry_time, timeframe_minutes: int) -> int:
    """Approximate strategy bars held for trailing delay after restart."""
    if entry_time is None or not timeframe_minutes or timeframe_minutes <= 0:
        return 0
    try:
        et = entry_time
        if getattr(et, "tzinfo", None) is not None:
            et = et.astimezone(pytz.timezone("America/New_York")).replace(tzinfo=None)
        now_et = datetime.now(pytz.timezone("America/New_York")).replace(tzinfo=None)
        mins = (now_et - et).total_seconds() / 60.0
        return max(0, int(mins // timeframe_minutes))
    except Exception:
        return 0


def wire_bracket_entry_from_ib(ib, pos, bracket, strategy=None) -> bool:
    """
    Link adopted/restored bracket to the filled IB entry so check_exits can trail and close.
    Returns True when entry metadata was wired (or was already present).
    """
    if bracket is None or pos is None:
        return False

    entry_trade = _find_filled_entry_trade_for_position(ib, pos)
    if entry_trade is None:
        return bool(bracket.get("entryOrderId"))

    entry_order = entry_trade.order
    bracket["entry"] = entry_order
    bracket["entryOrderId"] = int(getattr(entry_order, "orderId", 0) or 0)
    if entry_trade.fills:
        try:
            bracket["entry_price"] = float(entry_trade.fills[0].execution.price)
        except (TypeError, ValueError):
            pass
        converted = _ib_fill_to_naive_et(entry_trade.fills[0])
        if converted is not None:
            bracket["entry_time"] = converted

    stop_px = _stop_trigger_price(bracket.get("stopLoss"), bracket)
    tf = int(getattr(strategy, "timeframe", 13) or 13) if strategy else 13
    bars_held = _estimate_bars_held_since_entry(bracket.get("entry_time"), tf)
    pd = bracket.get("position_dict") or {}
    pd.setdefault("direction", bracket.get("direction"))
    if stop_px > 0:
        pd["stop"] = stop_px
    pd["bars_held"] = max(int(pd.get("bars_held") or 0), bars_held)
    bracket["position_dict"] = pd
    bracket["position_verified"] = True
    bracket["open_notified"] = True
    if not bracket.get("entry_wired"):
        logging.info(
            "Wired bracket entry from IB: orderId=%s permId=%s entry=%.2f bars_held≈%s",
            bracket.get("entryOrderId"),
            getattr(entry_order, "permId", 0),
            float(bracket.get("entry_price") or 0),
            pd.get("bars_held"),
        )
        bracket["entry_wired"] = True
    return True


def adopt_ib_protection_for_position(
    ib, positions, pos, strategy=None, data=None, live_tracker=None,
) -> bool:
    """
    Bind in-memory bracket to existing IB protective orders (any clientId).
    Never places new orders — used after reconnect / clientId change.
    """
    if pos.position == 0:
        return False
    direction = 1 if pos.position > 0 else -1
    qty = abs(int(pos.position))
    con_id = pos.contract.conId
    if _bracket_already_tracked(positions, direction, qty, con_id):
        _sync_positions_stop_handles_from_ib(ib, positions, pos)
        for bracket in positions or []:
            if bracket.get("direction") != direction:
                continue
            bc = bracket.get("contract")
            if bc is not None and getattr(bc, "conId", None) not in (None, con_id):
                continue
            wire_bracket_entry_from_ib(ib, pos, bracket, strategy=strategy)
        return True

    stop_trade = _find_protective_stop_trade_for_position(ib, pos)
    if stop_trade is None:
        return False

    need_exit_action = "SELL" if direction == 1 else "BUY"
    stop_order = stop_trade.order
    tp_order = None
    oca_group = getattr(stop_order, "ocaGroup", None) or None

    for trade in ib.trades():
        if trade.contract.conId != con_id:
            continue
        order = trade.order
        if getattr(order, "action", "") != need_exit_action:
            continue
        try:
            tq = abs(int(getattr(order, "totalQuantity", 0) or 0))
        except (TypeError, ValueError):
            continue
        if tq != qty:
            continue
        ot = str(getattr(order, "orderType", "") or "").upper()
        if ot in ("LMT", "LIMIT"):
            st = (getattr(trade.orderStatus, "status", None) or "").strip()
            if st not in _IB_TERMINAL_BLOTTER and st not in ("Inactive", "PendingCancel"):
                tp_order = order
                oca_group = getattr(order, "ocaGroup", None) or oca_group

    try:
        entry_price = float(getattr(pos, "avgCost", 0) or 0) / 50.0
    except (TypeError, ValueError):
        entry_price = 0.0
    if entry_price <= 0 and data is not None and not data.empty:
        entry_price = float(data["close"].iloc[-1])

    stop_px = _stop_trigger_price(stop_order, None)
    sym = getattr(pos.contract, "localSymbol", "ES")
    cid = getattr(stop_order, "clientId", "?")
    ost = getattr(stop_trade.orderStatus, "status", "?")

    tf = int(getattr(strategy, "timeframe", 13) or 13) if strategy else 13
    entry_time = None
    entry_trade = _find_filled_entry_trade_for_position(ib, pos)
    entry_order = MarketOrder(
        action="BUY" if direction == 1 else "SELL", totalQuantity=qty, tif="GTC",
    )
    entry_order_id = 0
    if entry_trade is not None:
        entry_order = entry_trade.order
        entry_order_id = int(getattr(entry_order, "orderId", 0) or 0)
        if entry_trade.fills:
            try:
                entry_price = float(entry_trade.fills[0].execution.price)
            except (TypeError, ValueError):
                pass
            ft = entry_trade.fills[0].execution.time or getattr(entry_trade.fills[0], "time", None)
            entry_time = _ib_fill_time_to_naive_et(ft)

    position_dict = {"direction": direction, "stop": stop_px}
    if entry_time is not None:
        position_dict["bars_held"] = _estimate_bars_held_since_entry(entry_time, tf)
    elif strategy is not None and data is not None and not data.empty:
        try:
            _ensure_strategy_indicators(strategy, data)
            position_dict = strategy.setup_position(
                entry_price, direction, data.iloc[-1], data,
            )
            position_dict["stop"] = stop_px
        except Exception:
            pass

    bracket = {
        "entry": entry_order,
        "stopLoss": stop_order,
        "takeProfit": tp_order,
        "direction": direction,
        "position_dict": position_dict,
        "entry_time": entry_time or datetime.now(),
        "entry_price": entry_price,
        "entry_stop_price": stop_px,
        "entry_tp_price": getattr(tp_order, "lmtPrice", None) if tp_order else None,
        "contract": pos.contract,
        "ocaGroup": oca_group,
        "open_notified": True,
        "restored_from_ib": True,
        "adopted_foreign_client": not _order_belongs_to_session(ib, stop_order),
        "position_verified": True,
    }
    if entry_order_id:
        bracket["entryOrderId"] = entry_order_id
    wire_bracket_entry_from_ib(ib, pos, bracket, strategy=strategy)
    positions.append(bracket)
    logging.info(
        "Adopted IB protection for %s %s @ %s (SL %.2f clientId=%s status=%s) — no new orders",
        "LONG" if direction == 1 else "SHORT",
        qty,
        sym,
        stop_px,
        cid,
        ost,
    )
    if live_tracker:
        add_to_live_tracker(
            live_tracker,
            "info",
            f"Adopted existing stop @ ${stop_px:,.2f} on {sym} (clientId {cid})",
        )
    return True


def _sync_positions_stop_handles_from_ib(ib, positions, pos) -> None:
    """Refresh tracked bracket stopLoss when IB still has a live pending/armed stop."""
    trade = _find_protective_stop_trade_for_position(ib, pos)
    if not trade:
        return
    direction = 1 if pos.position > 0 else -1
    for bracket in positions or []:
        if bracket.get("direction") != direction:
            continue
        bc = bracket.get("contract")
        if bc is not None and getattr(bc, "conId", None) not in (None, pos.contract.conId):
            continue
        bracket["stopLoss"] = trade.order
        px = _stop_trigger_price(trade.order, bracket)
        if px > 0:
            bracket["entry_stop_price"] = px
        break


def _bracket_already_tracked(positions, direction: int, qty: int, con_id: int) -> bool:
    for bracket in positions:
        if bracket.get('direction') != direction:
            continue
        bc = bracket.get('contract')
        if bc is not None and getattr(bc, 'conId', None) not in (None, con_id):
            continue
        bracket_qty = 0
        for k in ('stopLoss', 'entry', 'takeProfit'):
            order = bracket.get(k)
            if order is not None and hasattr(order, 'totalQuantity'):
                bracket_qty = abs(int(order.totalQuantity or 0))
                break
        if bracket_qty == qty:
            return True
    return False


def restore_tracked_brackets_from_ib(ib, contract, positions, strategy, data, live_tracker=None) -> int:
    """
    After restart, rebuild in-memory bracket tracking from IB open orders + position.
    Without this, protect/exit logic sees an empty positions list despite live risk on IB.
    """
    if not ib.isConnected():
        return 0
    _ib_refresh_open_orders(ib)
    restored = 0
    try:
        es_positions = [p for p in ib.positions() if p.contract.symbol == 'ES' and p.position != 0]
    except Exception as e:
        logging.error("restore_tracked_brackets_from_ib: positions fetch failed: %s", e)
        return 0

    for pos in es_positions:
        direction = 1 if pos.position > 0 else -1
        qty = abs(int(pos.position))
        con_id = pos.contract.conId
        if _bracket_already_tracked(positions, direction, qty, con_id):
            continue
        stop_trade = _find_protective_stop_trade_for_position(ib, pos)
        if stop_trade is None:
            continue

        need_exit_action = 'SELL' if direction == 1 else 'BUY'
        stop_order = None
        tp_order = None
        entry_order = None
        entry_price = None
        entry_time = None
        oca_group = None

        stop_order = stop_trade.order
        oca_group = getattr(stop_order, 'ocaGroup', None) or oca_group

        for trade in ib.trades():
            if trade.contract.conId != con_id:
                continue
            order = trade.order
            action = str(getattr(order, 'action', '') or '')
            try:
                tq = abs(int(getattr(order, 'totalQuantity', 0) or 0))
            except (TypeError, ValueError):
                continue
            if tq != qty:
                continue
            ot = str(getattr(order, 'orderType', '') or '').upper()
            if ot in ('LMT', 'LIMIT') and action == need_exit_action:
                st = (getattr(trade.orderStatus, 'status', None) or '').strip()
                if st not in _IB_TERMINAL_BLOTTER and st not in ('Inactive', 'PendingCancel'):
                    tp_order = order
                    oca_group = getattr(order, 'ocaGroup', None) or oca_group
            elif ot == 'MKT' and trade.filled() and action == ('BUY' if direction == 1 else 'SELL'):
                entry_order = order
                if trade.fills:
                    entry_price = float(trade.fills[0].execution.price)
                    entry_time = _ib_fill_to_naive_et(trade.fills[0])

        if stop_order is None:
            continue

        if entry_price is None:
            try:
                entry_price = float(getattr(pos, 'avgCost', 0) or 0) / 50.0
            except (TypeError, ValueError):
                entry_price = 0.0
        if entry_price <= 0 and data is not None and not data.empty:
            entry_price = float(data['close'].iloc[-1])

        if entry_order is None:
            entry_order = MarketOrder(
                action='BUY' if direction == 1 else 'SELL',
                totalQuantity=qty,
                tif='GTC',
            )

        position_dict = {}
        if strategy is not None and data is not None and not data.empty:
            try:
                _ensure_strategy_indicators(strategy, data)
                position_dict = strategy.setup_position(
                    entry_price, direction, data.iloc[-1], data
                )
            except Exception:
                position_dict = {}

        stop_px = getattr(stop_order, 'stopPrice', None) or getattr(stop_order, 'auxPrice', None)
        tp_px = getattr(tp_order, 'lmtPrice', None) if tp_order is not None else None

        bracket = {
            'entry': entry_order,
            'stopLoss': stop_order,
            'takeProfit': tp_order,
            'direction': direction,
            'position_dict': position_dict,
            'entry_time': entry_time or datetime.now(),
            'entry_price': entry_price,
            'entry_stop_price': stop_px,
            'entry_tp_price': tp_px,
            'contract': pos.contract,
            'ocaGroup': oca_group,
            'open_notified': True,
            'restored_from_ib': True,
            'position_verified': True,
        }
        if entry_order is not None:
            eoid = int(getattr(entry_order, 'orderId', 0) or 0)
            if eoid:
                bracket['entryOrderId'] = eoid
        if entry_time is not None and strategy is not None:
            tf = int(getattr(strategy, 'timeframe', 13) or 13)
            bh = _estimate_bars_held_since_entry(entry_time, tf)
            if isinstance(bracket.get('position_dict'), dict):
                bracket['position_dict']['bars_held'] = max(
                    int(bracket['position_dict'].get('bars_held') or 0), bh,
                )
        positions.append(bracket)
        restored += 1
        sym = getattr(pos.contract, 'localSymbol', 'ES')
        logging.info(
            "Restored in-memory bracket from IB: %s %s @ %s (SL %s%s)",
            'LONG' if direction == 1 else 'SHORT',
            qty,
            sym,
            stop_px,
            f", TP {tp_px}" if tp_px else "",
        )
        if live_tracker:
            add_to_live_tracker(
                live_tracker,
                'info',
                f"Restored tracked bracket for {qty} {sym} from IB orders",
            )

    return restored


def _open_position_on_contract(ib, con_id):
    for p in ib.positions():
        if p.contract.conId == con_id and p.position != 0:
            return p
    return None


def _order_likely_bracket_exit_leg(order, open_pos):
    """STP/LMT with parentId while exposure exists — do not cancel as API orphan."""
    if open_pos is None:
        return False
    pid = int(getattr(order, "parentId", 0) or 0)
    if pid == 0:
        return False
    ot = str(getattr(order, "orderType", "") or "").upper()
    if "STP" in ot or "TRAIL" in ot:
        return True
    if ot in ("LMT", "LIMIT") or float(getattr(order, "lmtPrice", 0) or 0) > 0:
        return True
    return False


def cancel_all_pending(ib, contract, live_tracker=None):
    """Cancel pending orders surgically, preserving protective orders for specific contract."""
    try:
        # 1. Fetch fresh positions to avoid stale 'has_open' logic
        # We look for ALL ES positions to be safe during roll weeks
        es_positions = [p for p in ib.positions() if p.contract.symbol == 'ES']
        has_open = any(abs(p.position) > 0 for p in es_positions)

        # No ES exposure anywhere: remove ALL non-terminal ES orders (includes **Inactive** legs).
        if not has_open:
            cancel_residual_es_orders_when_no_es_position(ib, live_tracker)
            return

        # 2. Identify working orders when we still have ES risk on the book
        active_trades = [t for t in ib.trades() if t.isActive() or (t.orderStatus and 
                         t.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending'])]

        if not active_trades:
            return

        # 3. Surgical cancellation — only non-protective orders on the traded contract
        for trade in active_trades:
            # We ONLY touch orders for the contract being targeted if it HAS a position
            if contract and trade.contract.conId == contract.conId:
                order = trade.order
                is_protective = (isinstance(order, StopOrder) or isinstance(order, LimitOrder) or
                                getattr(order, 'auxPrice', 0) > 0 or getattr(order, 'lmtPrice', 0) > 0)
                
                # If it's a market order or something without prices, it's likely a target for cleanup
                if not is_protective:
                    logging.info(f"Surgical Cleanup: Cancelling non-protective order {trade.order.orderType} for {contract.localSymbol}")
                    ib.cancelOrder(trade.order)

    except Exception as e:
        logging.error(f"Error in surgical cancel_all_pending: {e}")


def cleanup_orphaned_orders(ib, contract, positions):
    """Cancel active ES orders that don't belong to any tracked position."""
    if contract is None:
        return

    _ib_refresh_open_orders(ib)

    tracked_perm_ids = set()
    tracked_order_ids = set()
    for bracket in positions:
        for key in ['entry', 'stopLoss', 'takeProfit']:
            order = bracket.get(key)
            if order:
                if hasattr(order, 'permId') and order.permId != 0:
                    tracked_perm_ids.add(order.permId)
                if hasattr(order, 'orderId') and order.orderId != 0:
                    tracked_order_ids.add(order.orderId)

    orphaned = []
    for trade in ib.trades():
        if trade.contract.conId == contract.conId and trade.isActive():
            perm_id = trade.order.permId
            order_id = trade.order.orderId
            parent_id = getattr(trade.order, 'parentId', 0)

            # Order is NOT orphaned if its PermID or OrderID is explicitly tracked
            if perm_id in tracked_perm_ids or order_id in tracked_order_ids:
                continue

            # Order is NOT orphaned if its parent OrderID is explicitly tracked
            if parent_id != 0 and parent_id in tracked_order_ids:
                continue
            
            # --- NEW: GRACE PERIOD FOR NEW ORDERS ---
            # If an order was JUST placed, its ID might not be in the positions list 
            # due to race conditions or IB delay. Skip if < 10s old.
            if trade.log:
                # First log entry is usually the creation time
                creation_time = trade.log[0].time
                if (datetime.now(pytz.utc) - creation_time).total_seconds() < 10:
                    logging.debug(f"Skipping orphan check for new order {order_id} ({(datetime.now(pytz.utc) - creation_time).total_seconds():.1f}s old)")
                    continue

            open_pos = _open_position_on_contract(ib, trade.contract.conId)
            if open_pos is not None and _order_likely_bracket_exit_leg(trade.order, open_pos):
                if perm_id in tracked_perm_ids:
                    continue

            # If no tracking match found, it's an orphan
            orphaned.append(trade)

    for trade in orphaned:
        try:
            ib.cancelOrder(trade.order)
            logging.info(f"Cancelled orphaned order: {trade.order.orderType} "
                        f"{trade.order.action} {trade.order.totalQuantity} "
                        f"(PermID: {trade.order.permId})")
        except Exception as e:
            logging.warning(f"Error cancelling orphaned order: {e}")

    cancel_residual_orders_when_flat_on_contract(ib, contract, None, positions=positions)


def ensure_bracket_protective_stop(ib, contract, bracket, strategy, data, positions, live_tracker=None):
    """After entry fill: arm stop (Submitted) or re-place if missing."""
    if not ib.isConnected() or bracket is None or data is None or data.empty:
        return
    bc = bracket.get("contract") or contract
    if bc is None:
        return
    try:
        open_pos = [
            p for p in ib.positions()
            if p.contract.conId == bc.conId and abs(float(p.position)) > 1e-9
        ]
    except Exception as e:
        logging.error("ensure_bracket_protective_stop: positions fetch failed: %s", e)
        return
    if not open_pos:
        return
    pos = open_pos[0]
    if ensure_bracket_stop_armed(ib, bc, bracket, live_tracker):
        return
    if es_position_has_acceptable_stop(ib, pos, refresh=True):
        _sync_positions_stop_handles_from_ib(ib, positions, pos)
        return
    logging.warning(
        "Missing broker stop after entry on %s — re-protecting from bracket snapshot",
        getattr(bc, "localSymbol", bc),
    )
    protect_existing_positions(ib, bc, positions, strategy, data, live_tracker)


def close_orphaned_positions(ib, contract, positions, live_tracker=None, completed_trades=None, data=None):
    """Close positions that don't match any tracked bracket."""
    if contract is None:
        return

    _ib_refresh_open_orders(ib)

    # Filter for symbol ES to handle roll periods
    es_positions = [p for p in ib.positions() if p.contract.symbol == 'ES']
    for pos in es_positions:
        if pos.position == 0:
            continue

        # Check if this position is tracked (with correct direction and quantity)
        is_tracked = False
        for bracket in positions:
            bracket_dir = bracket.get('direction')
            # Check quantity via stopLoss or entry order
            bracket_qty = 0
            for k in ['stopLoss', 'entry', 'takeProfit']:
                if bracket.get(k) and hasattr(bracket[k], 'totalQuantity'):
                    bracket_qty = abs(bracket[k].totalQuantity)
                    break
            
            if bracket_dir == (1 if pos.position > 0 else -1) and bracket_qty == abs(pos.position):
                is_tracked = True
                break

        if not is_tracked:
            if es_position_has_acceptable_stop(ib, pos, refresh=False):
                logging.info(
                    f"Skipping orphan close: {pos.position} {pos.contract.localSymbol} has working protective "
                    f"orders on IB but no in-memory bracket (restart). Leaving position intact."
                )
                continue
            logging.warning(f"ORPHANED POSITION: {pos.position} contracts, not tracked. Closing...")
            close_action = 'SELL' if pos.position > 0 else 'BUY'
            close_order = MarketOrder(action=close_action, totalQuantity=abs(pos.position), transmit=True)
            try:
                # CRITICAL: Use the position's OWN contract (March/June/etc); IB rejects market orders
                # without exchange (Error 321).
                cc = pos.contract
                if not getattr(cc, 'exchange', None):
                    cc.exchange = 'CME'
                close_trade = ib.placeOrder(cc, close_order)
                ib.sleep(2)  # Wait slightly longer for fill
                logging.info(f"Orphaned {pos.contract.localSymbol} position closed")
                if live_tracker:
                    add_to_live_tracker(live_tracker, 'warning',
                        f"Closed orphaned position: {pos.position} contracts")
                        
                # --- NEW: Record orphaned closure to dashboard ---
                if completed_trades is not None:
                    exit_price = close_trade.fills[0].execution.price if close_trade and close_trade.fills else (data['close'].iloc[-1] if data is not None and not data.empty else 0)
                    pnl = 0
                    if close_trade and close_trade.fills:
                        for f in close_trade.fills:
                            if f.commissionReport and hasattr(f.commissionReport, 'realizedPNL'):
                                pnl = f.commissionReport.realizedPNL; break

                    entry_price = getattr(pos, 'avgCost', 0) / 50.0  # ES multiplier
                    completed_trades.append({
                        'exit_time': datetime.now(), 'entry_time': None,
                        'direction': 'LONG' if pos.position > 0 else 'SHORT',
                        'qty': abs(pos.position), 'entry_price': entry_price, 'exit_price': exit_price,
                        'pnl': pnl, 'r_multiple': 0, 'reason': 'Orphan Auto-Close',
                        'duration': 'Auto-Closed',
                        'stop_at_close': None, 'tp_at_close': None,
                    })
                    if len(completed_trades) > 1000:
                        del completed_trades[:-1000]

            except Exception as e:
                logging.error(f"Failed to close orphaned position: {e}")


def protect_existing_positions(ib, contract, positions, strategy, data, live_tracker=None):
    """Add stop loss to any unprotected positions."""
    if contract is None or data is None or data.empty:
        return

    _ensure_strategy_indicators(strategy, data)

    # Look for ALL ES positions to ensure legacy ones stay protected during roll
    try:
        es_pos_list = [p for p in ib.positions() if p.contract.symbol == 'ES']
    except Exception as e:
        logging.error(f"Error fetching positions in protect_existing: {e}")
        return

    _ib_refresh_open_orders(ib)

    for pos in es_pos_list:
        if pos.position == 0:
            continue
            
        qty = abs(pos.position)
        direction = 1 if pos.position > 0 else -1

        if es_position_has_acceptable_stop(ib, pos, refresh=False):
            adopt_ib_protection_for_position(
                ib, positions, pos, strategy=strategy, data=data, live_tracker=live_tracker,
            )
            _sync_positions_stop_handles_from_ib(ib, positions, pos)
            continue

        if not _reprotect_throttle_ok(pos.contract.conId, direction):
            logging.debug(
                "Re-protect throttled for %s (%.0fs cooldown)",
                pos.contract.localSymbol,
                _REPROTECT_MIN_INTERVAL_SEC,
            )
            continue

        logging.warning(
            "UNPROTECTED POSITION: %s %s contracts — no stop on IB; placing protective stop",
            qty,
            pos.contract.localSymbol,
        )
            
        # baseline for SL: Use position's avgCost if it's a legacy contract, 
        # otherwise use current market price.
        avg_cost = getattr(pos, 'avgCost', 0) / 50.0  # Convert to index points
        if avg_cost <= 0:
            avg_cost = data['close'].iloc[-1]
        
        # Strategy expects current_price to calculate distances
        pos_dict = strategy.setup_position(avg_cost, direction, data.iloc[-1], data)

        if pd.isna(pos_dict['stop']) or pos_dict['stop'] <= 0:
            logging.error(f"Cannot recreate stop: Invalid stop price calculated.")
            continue

        tracked_stop_px = _reference_stop_px_for_position(positions, pos)
        calc_stop = float(
            tracked_stop_px if tracked_stop_px > 0 else pos_dict["stop"]
        )
        curr_px = float(data['close'].iloc[-1])
        if direction == 1:
            valid_stop = min(calc_stop, curr_px - 0.25)
        else:
            valid_stop = max(calc_stop, curr_px + 0.25)

        oca_group = f"bracket_{pos.contract.conId}_{direction}"
        stop_order = StopOrder(
            action='SELL' if direction == 1 else 'BUY',
            totalQuantity=qty,
            stopPrice=round(valid_stop * 4) / 4,
            tif='GTC',
            transmit=True,
            parentId=0,
        )
        
        if not trading_orders_allowed():
            log_placement_blocked(f"re-protect {pos.contract.localSymbol}")
            continue

        # Place on the SPECIFIC contract of the position (March or June)
        try:
            # Ensure exchange is set for validation
            pos.contract.exchange = 'CME'
            ib.placeOrder(pos.contract, stop_order)
            sl_px = getattr(stop_order, "stopPrice", None) or getattr(stop_order, "auxPrice", None)
            logging.info(f"Re-protected {pos.contract.localSymbol} at SL: {sl_px}")

            new_bracket = {
                'entry': MarketOrder(action='BUY' if direction == 1 else 'SELL', totalQuantity=qty),
                'stopLoss': stop_order, 'takeProfit': None,
                'direction': direction, 'position_dict': pos_dict,
                'entry_time': datetime.now(), 'entry_price': avg_cost,
                'contract': pos.contract,
                'entry_stop_price': sl_px,
                'open_notified': True,
            }
            positions.append(new_bracket)
            if not ensure_bracket_stop_armed(ib, pos.contract, new_bracket, live_tracker):
                logging.warning(
                    "Re-protect stop placed but not yet Submitted on %s @ %s",
                    pos.contract.localSymbol, sl_px,
                )
            if live_tracker:
                add_to_live_tracker(live_tracker, 'warning',
                    f"Added protective stop for {pos.contract.localSymbol} at ${float(sl_px):,.2f}")
        except Exception as e:
            logging.error(f"Failed to place protective order for legacy contract: {e}")


def enforce_stop_invariant(ib, positions, strategy, data, live_tracker=None, contract=None):
    """
    Hard safety invariant: every open ES position must have a protective stop on IB.

    Submitted stops are ideal; session PreSubmitted/trigger stops are accepted (paper IB
    often never arms bracket children). Re-protect only when no stop exists at all.
    """
    if not ib.isConnected() or data is None or data.empty:
        return
    try:
        es_open = [p for p in ib.positions() if p.contract.symbol == 'ES' and p.position != 0]
    except Exception as e:
        logging.error(f"Failed to fetch positions for stop invariant: {e}")
        return

    if not es_open:
        return

    _ib_refresh_open_orders(ib)

    for pos in es_open:
        qty = abs(pos.position)
        if es_position_has_acceptable_stop(ib, pos, refresh=False):
            adopt_ib_protection_for_position(
                ib, positions, pos, strategy=strategy, data=data, live_tracker=live_tracker,
            )
            _sync_positions_stop_handles_from_ib(ib, positions, pos)
            continue

        direction = 1 if pos.position > 0 else -1
        if not _reprotect_throttle_ok(pos.contract.conId, direction):
            logging.warning(
                "STOP INVARIANT: %s %s has no stop but re-protect throttled (%.0fs)",
                qty,
                pos.contract.localSymbol,
                _REPROTECT_MIN_INTERVAL_SEC,
            )
            continue

        logging.error(
            "STOP INVARIANT BREACH: %s %s has no protective stop on IB. Re-protecting now.",
            qty,
            pos.contract.localSymbol,
        )
        protect_existing_positions(ib, pos.contract, positions, strategy, data, live_tracker=live_tracker)


def check_and_recreate_tp_orders(ib, contract, positions, strategy, data, live_tracker=None):
    """Recreate missing TP orders for tracked positions that should have one."""
    if contract is None or data is None or data.empty:
        return

    for bracket in positions[:]:
        direction = bracket.get('direction', 0)
        tp_order = bracket.get('takeProfit')

        # Skip if no TP expected
        if not getattr(strategy, 'opposite_bb_tp', False) and not bracket.get('position_dict', {}).get('tp'):
            continue

        # 1. Check if TP handle in bracket is active
        tp_active = False
        if tp_order:
            for trade in ib.trades():
                if trade.order.permId == tp_order.permId and trade.contract.conId == contract.conId:
                    tp_active = trade.isActive() or (trade.orderStatus and
                        trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending'])
                    break

        # 2. Safety: Look for ANY active Limit order for this contract with correct parentId
        if not tp_active:
            entry_order = bracket.get('entry')
            entry_id = entry_order.orderId if entry_order and hasattr(entry_order, 'orderId') else 0
            
            for trade in ib.trades():
                if trade.contract.conId == contract.conId and trade.isActive():
                    order = trade.order
                    is_limit = isinstance(order, LimitOrder) or getattr(order, 'lmtPrice', 0) > 0
                    
                    # Match by parentId (strongest link)
                    if is_limit and entry_id != 0 and getattr(order, 'parentId', 0) == entry_id:
                        tp_active = True
                        bracket['takeProfit'] = order # Repair the handle
                        logging.info(f"Repaired TP handle for tracked position (parent link: {entry_id})")
                        break
                    
                    # Match by Action and Quantity (fallback for when parentId is lost or not yet assigned)
                    action = 'SELL' if direction == 1 else 'BUY'
                    if (is_limit and order.action == action and 
                        abs(order.totalQuantity) == 1 and # Adjust if handling multi-lot
                        trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                        tp_active = True
                        bracket['takeProfit'] = order
                        logging.debug(f"Assumed active order {order.permId} is the TP for bracket")
                        break

        if tp_active:
            continue

        # TP is missing — recreate it
        try:
            current_price = data['close'].iloc[-1]

            # Calculate TP from strategy
            if getattr(strategy, 'opposite_bb_tp', False) and 'upper' in data.columns:
                tp = data['upper'].iloc[-1] if direction == 1 else data['lower'].iloc[-1]
            else:
                pos_dict = bracket.get('position_dict', {})
                tp = pos_dict.get('tp')

            if tp is None or pd.isna(tp) or tp <= 0:
                continue

            tp = round(float(tp) * 4) / 4
            
            # Final sanity check: TP must be on the correct side of current price
            if (direction == 1 and tp <= current_price) or (direction == -1 and tp >= current_price):
                logging.warning(f"Skipping TP recreation: price {tp} is already reached or on wrong side of {current_price}")
                continue
            qty = 1
            stop_order = bracket.get('stopLoss')
            if stop_order and hasattr(stop_order, 'totalQuantity'):
                qty = abs(stop_order.totalQuantity)

            tp_action = 'SELL' if direction == 1 else 'BUY'
            
            # Deterministic group naming to ensure linkage with existing SL
            oca_group = bracket.get('ocaGroup', f"bracket_{contract.conId}_{direction}")
            
            new_tp_order = LimitOrder(
                action=tp_action, totalQuantity=qty, lmtPrice=tp,
                tif='GTC', ocaGroup=oca_group, ocaType=1, transmit=True
            )

            if not trading_orders_allowed():
                log_placement_blocked("TP recreate")
                continue

            logging.info(f"Recreating TP order: {tp_action} {qty} @ {tp:.2f}")
            tp_trade = ib.placeOrder(contract, new_tp_order)
            ib.sleep(0.5)

            # Verify active
            if tp_trade and tp_trade.order:
                is_active = tp_trade.isActive() or (tp_trade.orderStatus and
                    tp_trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending'])
                if is_active:
                    bracket['takeProfit'] = new_tp_order
                    logging.info(f"Successfully recreated TP at {tp:.2f}")
                    if live_tracker:
                        add_to_live_tracker(live_tracker, 'order', f"Recreated TP at ${tp:.2f}")
                else:
                    logging.error("Failed to recreate TP - order not active")
        except Exception as e:
            logging.error(f"Error recreating TP: {e}")


def reconcile_positions(ib, contract, positions, live_tracker=None, 
                        completed_trades=None, send_email_fn=None, data=None, strategy=None):
    """
    SELF-HEALING: Sync internal 'positions' list with actual IBKR positions.
    Purges 'Ghost Brackets' that exist in our tracking but not in TWS.
    """
    if not ib.isConnected():
        return

    # Import lazy-load to avoid circular dependency
    from core.execution import _record_trade_close

    try:
        # 1. Get all actual ES positions
        # Use symbol 'ES' to handle roll-over contracts safely
        actual_es_pos = [p for p in ib.positions() if p.contract.symbol == 'ES']
        
        # 2. Iterate through our internal tracking list
        for bracket in positions[:]:
            direction = bracket.get('direction')
            qty = 0
            # Resolve quantity from available order handles
            for k in ['stopLoss', 'entry', 'takeProfit']:
                if bracket.get(k) and hasattr(bracket[k], 'totalQuantity'):
                    qty = abs(bracket[k].totalQuantity)
                    break
            
            # Find matching actual position
            match = next((p for p in actual_es_pos 
                        if (1 if p.position > 0 else -1) == direction and abs(p.position) == qty), None)
            
            if match is None:
                # 30-SECOND GRACE PERIOD: 
                # Don't immediately purge. A fill might have just happened and we're waiting for the event.
                first_missing = bracket.get('first_missing_time')
                if first_missing is None:
                    bracket['first_missing_time'] = datetime.now()
                    continue # Wait for next cycle
                
                missing_duration = (datetime.now() - first_missing).total_seconds()
                if missing_duration < 30:
                    logging.debug(f"Position {direction} missing from TWS for {missing_duration:.1f}s. Waiting for grace period...")
                    continue

                # This is a GHOST BRACKET (tracked but not in TWS for > 30s)
                logging.warning(f"GHOST POSITION DETECTED: Tracked {'LONG' if direction==1 else 'SHORT'} "
                             f"({qty} contracts) but not found in TWS for {missing_duration:.1f}s. Recording as Manual Close...")
                
                # Cleanup associated orders immediately to prevent 'improper price' storm
                for order_key in ['stopLoss', 'takeProfit']:
                    order = bracket.get(order_key)
                    if order:
                        # Find and cancel any active trades for this order
                        for trade in ib.trades():
                            if trade.order.permId == getattr(order, 'permId', 0) and trade.isActive():
                                try:
                                    ib.cancelOrder(trade.order)
                                    logging.info(f"Cancelled orphaned {order_key} for ghost bracket: {trade.order.permId}")
                                except: pass

                # Record the trade as "Unknown" (triggers deep-search in execution.py)
                try:
                    # Mock row for price discovery
                    latest_row = {'close': 0}
                    if data is not None and not data.empty:
                        latest_row = data.iloc[-1]
                    
                    _record_trade_close(
                        ib, contract, bracket, 
                        bracket.get('entry'), bracket.get('stopLoss'), bracket.get('takeProfit'),
                        None, None, direction, latest_row, positions,
                        completed_trades, live_tracker, send_email_fn, data,
                        reason='Unknown', strategy=strategy
                    )
                except Exception as e:
                    logging.error(f"Failed to record ghost bracket closure: {e}")

                if bracket in positions:
                    positions.remove(bracket)
                if live_tracker:
                    add_to_live_tracker(live_tracker, 'warning', f"Purged ghost position ({qty} contracts)")
            else:
                # Position found in TWS - reset the missing timer
                bracket.pop('first_missing_time', None)

    except Exception as e:
        logging.error(f"Error in reconcile_positions: {e}")

    # Positions on IB with no in-memory bracket (common after gateway outage / clientId change)
    try:
        actual_es_pos = [p for p in ib.positions() if p.contract.symbol == "ES" and p.position != 0]
        for pos in actual_es_pos:
            direction = 1 if pos.position > 0 else -1
            qty = abs(int(pos.position))
            if _bracket_already_tracked(positions, direction, qty, pos.contract.conId):
                continue
            if adopt_ib_protection_for_position(
                ib, positions, pos, strategy=strategy, data=data, live_tracker=live_tracker,
            ):
                continue
            logging.warning(
                "IB position %s %s @ %s not tracked and no protective orders to adopt",
                "LONG" if direction == 1 else "SHORT",
                qty,
                getattr(pos.contract, "localSymbol", "ES"),
            )
    except Exception as e:
        logging.error("reconcile_positions adopt pass failed: %s", e)


async def periodic_protection_check(ib, contract, positions, strategy, data, live_tracker=None,
                                 send_email_fn=None, close_all_fn=None, completed_trades=None,
                                 expected_client_id: int = 100, dashboard_state=None):
    """Every-20s async task: maintenance -> cleanup -> protect -> stop invariant -> recreate TP."""
    from core.execution import prune_dead_brackets

    while True:
        await asyncio.sleep(20)
        if not ib.isConnected() or contract is None:
            continue
            
        try:
            prune_dead_brackets(ib, contract, positions, live_tracker)
            # --- 1. Maintenance & RTH Force Exit Check (Robust Safety) ---
            # We recreate a dummy single-row DF to check current filters
            if strategy and hasattr(strategy, 'apply_filters'):
                now_et = datetime.now(pytz.timezone('US/Eastern'))
                dummy_df = pd.DataFrame(index=[now_et])
                # Fill with enough dummy data to avoid strategy crashes
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    dummy_df[col] = 0
                
                try:
                    # Apply filters to current time
                    filtered = strategy.apply_filters(dummy_df)
                    
                    # Also reconcile positions with TWS every minute
                    reconcile_positions(ib, contract, positions, live_tracker, 
                                      completed_trades=completed_trades, send_email_fn=send_email_fn, data=data, strategy=strategy)
                    if not filtered.empty:
                        row = filtered.iloc[0]
                        force_maint = row.get('force_exit', False)
                        force_rth = row.get('force_exit_rth', False)
                        
                        if force_maint or force_rth:
                            reason = "Maintenance" if force_maint else "RTH End"
                            # Check if ANY ES position exists (tracked or orphaned)
                            es_pos = [p for p in ib.positions() if p.contract.symbol == 'ES' and p.position != 0]
                            if es_pos or positions:
                                if close_all_fn and send_email_fn:
                                    logging.warning(f"⚠️ {reason.upper()} APPROACHING (Periodic Check) - Closing all ES positions")
                                    acct_fn = lambda: get_account_summary(ib, data, contract)
                                    close_all_fn(
                                        reason, ib, contract, positions, data,
                                        live_tracker, send_email_fn, strategy=strategy,
                                        account_fn=acct_fn, completed_trades=completed_trades,
                                    )
                except Exception as e:
                    logging.error(f"Error checking maintenance in periodic loop: {e}")

            # --- 2. Standard Protection Checks (adopt before place) ---
            run_client_id_integrity_check(
                ib,
                expected_client_id,
                contract,
                send_email_fn=send_email_fn,
                live_tracker=live_tracker,
                dashboard_state=dashboard_state,
                label="periodic",
            )
            try:
                for pos in [p for p in ib.positions() if p.contract.symbol == "ES" and p.position != 0]:
                    adopt_ib_protection_for_position(
                        ib, positions, pos, strategy=strategy, data=data, live_tracker=live_tracker,
                    )
            except Exception as e:
                logging.error("Periodic adopt pass failed: %s", e)
            consolidate_duplicate_protective_orders(ib, contract, positions, live_tracker)
            cleanup_orphaned_orders(ib, contract, positions)
            close_orphaned_positions(ib, contract, positions, live_tracker, completed_trades, data)
            protect_existing_positions(ib, contract, positions, strategy, data, live_tracker)
            check_and_recreate_tp_orders(ib, contract, positions, strategy, data, live_tracker)
            enforce_stop_invariant(ib, positions, strategy, data, live_tracker, contract=contract)
        except Exception as e:
            logging.error(f"Error in periodic protection check: {e}")


def run_reconnection_safety_sequence(
    ib,
    contract,
    positions,
    strategy,
    data,
    live_tracker=None,
    completed_trades=None,
    expected_client_id: int = 100,
    send_email_fn=None,
    dashboard_state=None,
):
    """Post-reconnection: adopt existing IB protection before placing anything new."""
    logging.info("Running post-reconnection safety sequence...")
    _ib_refresh_open_orders(ib)
    if not run_client_id_integrity_check(
        ib,
        expected_client_id,
        contract,
        send_email_fn=send_email_fn,
        live_tracker=live_tracker,
        dashboard_state=dashboard_state,
        label="reconnect",
    ):
        logging.critical(
            "Post-reconnect: new order placement halted until only clientId %s has ES orders",
            expected_client_id,
        )
    reconcile_positions(
        ib, contract, positions, live_tracker, strategy=strategy, data=data,
    )
    n = restore_tracked_brackets_from_ib(ib, contract, positions, strategy, data, live_tracker)
    if n:
        logging.info("Post-reconnect: restored %s bracket(s) from IB", n)
    try:
        for pos in [p for p in ib.positions() if p.contract.symbol == "ES" and p.position != 0]:
            adopt_ib_protection_for_position(
                ib, positions, pos, strategy=strategy, data=data, live_tracker=live_tracker,
            )
    except Exception as e:
        logging.error("Post-reconnect adopt pass failed: %s", e)

    n_consolidated = consolidate_duplicate_protective_orders(ib, contract, positions, live_tracker)
    if n_consolidated:
        logging.info("Post-reconnect: cancelled %s duplicate protective order(s)", n_consolidated)

    cleanup_orphaned_orders(ib, contract, positions)
    close_orphaned_positions(ib, contract, positions, live_tracker, completed_trades, data)
    protect_existing_positions(ib, contract, positions, strategy, data, live_tracker)
    check_and_recreate_tp_orders(ib, contract, positions, strategy, data, live_tracker)
    enforce_stop_invariant(ib, positions, strategy, data, live_tracker, contract=contract)
    logging.info("Safety sequence complete")

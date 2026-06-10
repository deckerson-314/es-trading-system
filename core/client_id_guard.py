"""
Single API clientId enforcement for the trading bot.

Multiple clientIds with live orders on the same account is treated as a critical
safety failure (duplicate bot sessions or clientId rotation). The bot must never
open a second API slot; it waits for ghost release on the configured id only.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Set


def _session_client_id(ib) -> int:
    try:
        return int(getattr(getattr(ib, "client", None), "clientId", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _ib_refresh_open_orders(ib) -> None:
    try:
        ib.reqAllOpenOrders()
        ib.sleep(0.2)
    except Exception:
        try:
            ib.reqOpenOrders()
            ib.sleep(0.15)
        except Exception:
            pass


# Non-terminal order statuses (working or pending cancel still counts as exposure).
_ACTIVE_ORDER_STATUSES = frozenset({
    "PendingSubmit",
    "ApiPending",
    "PreSubmitted",
    "Submitted",
    "PendingCancel",
})
_ALERT_COOLDOWN_SEC = 1800.0

_trading_halted = False
_halt_reason = ""
_last_audit: Optional["ClientIdAudit"] = None
_last_alert_monotonic = 0.0


@dataclass
class ClientIdAudit:
    expected_client_id: int
    session_client_id: int
    active_bot_client_ids: Set[int] = field(default_factory=set)
    foreign_client_ids: Set[int] = field(default_factory=set)
    foreign_order_count: int = 0
    session_mismatch: bool = False
    violation: bool = False
    violation_reason: str = ""

    def summary(self) -> str:
        if not self.violation:
            return f"OK (clientId={self.expected_client_id})"
        return self.violation_reason or "clientId integrity violation"


class ClientIdInUseError(RuntimeError):
    """Configured clientId is still held by a ghost or another process."""


def trading_orders_allowed() -> bool:
    """False when multi-clientId or foreign-order exposure requires manual fix."""
    return not _trading_halted


def trading_halt_reason() -> str:
    return _halt_reason


def last_client_id_audit() -> Optional[ClientIdAudit]:
    return _last_audit


def _order_is_active(trade) -> bool:
    st = (getattr(getattr(trade, "orderStatus", None), "status", None) or "").strip()
    if st in ("Inactive",):
        return False
    if st in ("Filled", "Cancelled", "ApiCancelled"):
        return False
    if st in _ACTIVE_ORDER_STATUSES:
        return True
    try:
        return bool(trade.isActive())
    except Exception:
        return False


def collect_es_order_client_ids(ib, es_con_id: Optional[int] = None) -> dict[int, int]:
    """
    Map clientId -> count of active non-manual orders on ES (symbol ES).
    Excludes clientId 0 (manual/TWS discretionary).
    """
    _ib_refresh_open_orders(ib)
    counts: dict[int, int] = {}
    for trade in ib.trades():
        contract = trade.contract
        if getattr(contract, "symbol", "") != "ES":
            continue
        if es_con_id is not None and getattr(contract, "conId", None) not in (None, es_con_id):
            continue
        if not _order_is_active(trade):
            continue
        cid = int(getattr(trade.order, "clientId", 0) or 0)
        if cid <= 0:
            continue
        counts[cid] = counts.get(cid, 0) + 1
    return counts


def audit_client_id_integrity(
    ib,
    expected_client_id: int,
    es_con_id: Optional[int] = None,
) -> ClientIdAudit:
    session_cid = _session_client_id(ib)
    counts = collect_es_order_client_ids(ib, es_con_id)
    active_ids = set(counts.keys())
    foreign = {c for c in active_ids if c != int(expected_client_id)}
    foreign_n = sum(counts.get(c, 0) for c in foreign)

    violation = False
    reason = ""

    if session_cid != int(expected_client_id):
        violation = True
        reason = (
            f"API session clientId={session_cid} != configured {expected_client_id}. "
            "Refusing to trade; restart bot with a single --client_id only."
        )
    elif len(active_ids) > 1:
        violation = True
        reason = (
            f"Multiple API clientIds have active ES orders: {sorted(active_ids)}. "
            f"Only clientId {expected_client_id} is allowed. Cancel stray orders in TWS "
            "and ensure no second bot process is running."
        )
    elif foreign:
        violation = True
        reason = (
            f"Foreign API clientId(s) {sorted(foreign)} have {foreign_n} active ES order(s); "
            f"bot requires exclusive clientId {expected_client_id}. "
            "Cancel those orders in TWS before resuming."
        )

    return ClientIdAudit(
        expected_client_id=int(expected_client_id),
        session_client_id=session_cid,
        active_bot_client_ids=active_ids,
        foreign_client_ids=foreign,
        foreign_order_count=foreign_n,
        session_mismatch=(session_cid != int(expected_client_id)),
        violation=violation,
        violation_reason=reason,
    )


def _set_halt(audit: ClientIdAudit) -> None:
    global _trading_halted, _halt_reason, _last_audit
    _trading_halted = True
    _halt_reason = audit.summary()
    _last_audit = audit


def _clear_halt() -> None:
    global _trading_halted, _halt_reason
    _trading_halted = False
    _halt_reason = ""


def clear_trading_halt() -> None:
    """Clear halt flag (tests / operator ack after manual TWS cleanup)."""
    _clear_halt()


def sync_dashboard_client_id_state(dashboard_state) -> None:
    if dashboard_state is None:
        return
    audit = _last_audit
    dashboard_state.client_id_trading_halted = _trading_halted
    dashboard_state.client_id_expected = int(audit.expected_client_id) if audit else 0
    dashboard_state.client_id_active_on_account = (
        sorted(audit.active_bot_client_ids) if audit else []
    )
    dashboard_state.client_id_violation_detail = _halt_reason if _trading_halted else ""


def _maybe_alert(
    audit: ClientIdAudit,
    send_email_fn: Optional[Callable] = None,
    live_tracker=None,
    label: str = "",
) -> None:
    global _last_alert_monotonic
    if not audit.violation:
        return
    now = time.monotonic()
    if now - _last_alert_monotonic < _ALERT_COOLDOWN_SEC:
        return
    _last_alert_monotonic = now
    body = (
        f"{audit.violation_reason}\n\n"
        f"Session clientId: {audit.session_client_id}\n"
        f"Expected: {audit.expected_client_id}\n"
        f"Active API clientIds on ES: {sorted(audit.active_bot_client_ids) or 'none'}\n"
        f"Foreign orders: {audit.foreign_order_count}\n\n"
        "New entries and new protective orders are BLOCKED until only the configured "
        "clientId has working ES orders. Cancel duplicates in TWS; kill duplicate bot "
        "processes; restart IB Gateway if a ghost holds the clientId slot."
    )
    logging.critical("CLIENT ID INTEGRITY [%s]: %s", label, audit.violation_reason)
    if live_tracker is not None:
        try:
            from core.account import add_to_live_tracker
            add_to_live_tracker(live_tracker, "error", audit.violation_reason[:200])
        except Exception:
            pass
    if send_email_fn:
        try:
            send_email_fn("CLIENT ID INTEGRITY HALT", body)
        except Exception as e:
            logging.warning("ClientId alert email failed: %s", e)


def run_client_id_integrity_check(
    ib,
    expected_client_id: int,
    contract=None,
    *,
    send_email_fn: Optional[Callable] = None,
    live_tracker=None,
    dashboard_state=None,
    label: str = "check",
) -> bool:
    """
    Audit IB for multi-clientId exposure. Returns True if new order placement is allowed.
    """
    global _last_audit
    es_con_id = getattr(contract, "conId", None) if contract is not None else None
    audit = audit_client_id_integrity(ib, expected_client_id, es_con_id)
    _last_audit = audit
    if audit.violation:
        _set_halt(audit)
        _maybe_alert(audit, send_email_fn, live_tracker, label=label)
    else:
        _clear_halt()
    sync_dashboard_client_id_state(dashboard_state)
    return trading_orders_allowed()


def assert_session_client_id(ib, expected_client_id: int) -> None:
    """Fail fast if connected session is not the configured clientId."""
    session_cid = _session_client_id(ib)
    if session_cid != int(expected_client_id):
        raise RuntimeError(
            f"Connected IB session clientId={session_cid} but --client_id={expected_client_id}. "
            "This build never rotates clientId; aborting."
        )


def log_placement_blocked(action: str) -> None:
    logging.error(
        "BLOCKED %s: clientId integrity halt — %s",
        action,
        _halt_reason or "multi-clientId exposure",
    )

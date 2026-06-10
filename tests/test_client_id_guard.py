"""Single clientId integrity policy."""
from unittest.mock import MagicMock

from core.client_id_guard import (
    audit_client_id_integrity,
    trading_orders_allowed,
    run_client_id_integrity_check,
    clear_trading_halt,
)


def _trade(cid: int, symbol: str = "ES", status: str = "Submitted", con_id: int = 1):
    t = MagicMock()
    t.contract.symbol = symbol
    t.contract.conId = con_id
    t.order.clientId = cid
    t.orderStatus.status = status
    t.isActive.return_value = True
    return t


def test_audit_ok_single_expected_client():
    clear_trading_halt()
    ib = MagicMock()
    ib.client.clientId = 100
    ib.trades.return_value = [_trade(100)]
    audit = audit_client_id_integrity(ib, 100, es_con_id=1)
    assert not audit.violation
    assert audit.active_bot_client_ids == {100}


def test_audit_violation_foreign_client_orders():
    clear_trading_halt()
    ib = MagicMock()
    ib.client.clientId = 100
    ib.trades.return_value = [_trade(100), _trade(101)]
    audit = audit_client_id_integrity(ib, 100, es_con_id=1)
    assert audit.violation
    assert 101 in audit.foreign_client_ids


def test_audit_violation_session_mismatch():
    ib = MagicMock()
    ib.client.clientId = 102
    ib.trades.return_value = []
    audit = audit_client_id_integrity(ib, 100)
    assert audit.violation
    assert audit.session_mismatch


def test_run_check_halts_and_clears():
    clear_trading_halt()
    ib = MagicMock()
    ib.client.clientId = 100
    ib.trades.return_value = [_trade(101)]
    assert not run_client_id_integrity_check(ib, 100, label="test")
    assert not trading_orders_allowed()
    ib.trades.return_value = [_trade(100)]
    assert run_client_id_integrity_check(ib, 100, label="test-clear")
    assert trading_orders_allowed()

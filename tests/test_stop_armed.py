"""Tests for armed (Submitted) stop promotion and protection invariant."""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.protection import (
    stop_order_is_armed,
    stop_order_is_pending,
    es_position_has_protective_exit_orders,
    es_position_has_acceptable_stop,
    _trade_has_working_protective_stop,
)


def _stop_trade(status, why_held="", aux=7575.25):
    order = MagicMock()
    order.auxPrice = aux
    order.lmtPrice = 0.0
    order.stopPrice = aux
    order.action = "SELL"
    order.totalQuantity = 1.0
    trade = MagicMock()
    trade.order = order
    trade.orderStatus = MagicMock(status=status, whyHeld=why_held)
    return trade


class TestStopArmed:
    def test_submitted_is_armed(self):
        t = _stop_trade("Submitted")
        assert stop_order_is_armed(t) is True
        assert stop_order_is_pending(t) is False
        assert _trade_has_working_protective_stop(t) is True

    def test_presubmitted_trigger_not_armed(self):
        t = _stop_trade("PreSubmitted", why_held="trigger")
        assert stop_order_is_armed(t) is False
        assert stop_order_is_pending(t) is True
        assert _trade_has_working_protective_stop(t) is False

    def test_es_position_requires_submitted_stop(self):
        ib = MagicMock()
        pos = MagicMock()
        pos.contract.conId = 99
        pos.position = 1.0

        pending = _stop_trade("PreSubmitted", why_held="trigger")
        pending.contract = pos.contract
        ib.trades.return_value = [pending]

        assert es_position_has_protective_exit_orders(ib, pos, refresh=False) is False

        armed = _stop_trade("Submitted")
        armed.contract = pos.contract
        ib.trades.return_value = [armed]
        assert es_position_has_protective_exit_orders(ib, pos, refresh=False) is True

    def test_acceptable_stop_includes_presubmitted(self):
        ib = MagicMock()
        pos = MagicMock()
        pos.contract.conId = 99
        pos.position = 1.0

        pending = _stop_trade("PreSubmitted", why_held="trigger")
        pending.contract = pos.contract
        pending.order.clientId = 100
        ib.trades.return_value = [pending]
        ib.client = MagicMock(clientId=100)

        assert es_position_has_acceptable_stop(ib, pos, refresh=False) is True
        assert es_position_has_protective_exit_orders(ib, pos, refresh=False) is False

    def test_acceptable_stop_includes_foreign_client_id(self):
        ib = MagicMock()
        pos = MagicMock()
        pos.contract.conId = 99
        pos.position = -1.0

        pending = _stop_trade("PreSubmitted", why_held="trigger", aux=7556.75)
        pending.order.action = "BUY"
        pending.contract = pos.contract
        pending.order.clientId = 101
        ib.trades.return_value = [pending]
        ib.client = MagicMock(clientId=102)

        assert es_position_has_acceptable_stop(ib, pos, refresh=False) is True

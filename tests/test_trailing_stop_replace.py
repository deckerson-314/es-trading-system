"""Trailing stop broker replace and duplicate-stop consolidation."""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.protection import (
    _exit_leg_rank,
    _reference_stop_px_for_position,
    _stop_tightness_rank,
    trail_replace_in_progress,
    replace_trailing_stop_zero_gap,
)


def _stop_trade(status, aux, perm_id=0, client_id=100):
    order = MagicMock()
    order.auxPrice = aux
    order.lmtPrice = 0.0
    order.stopPrice = aux
    order.action = "SELL"
    order.totalQuantity = 1.0
    order.permId = perm_id
    order.clientId = client_id
    order.orderType = "STP"
    trade = MagicMock()
    trade.order = order
    trade.orderStatus = MagicMock(status=status, whyHeld="trigger" if status == "PreSubmitted" else "")
    return trade


class TestStopTightnessRank:
    def test_long_prefers_higher_stop(self):
        assert _stop_tightness_rank(7457.0, 1) > _stop_tightness_rank(7376.0, 1)

    def test_short_prefers_lower_stop(self):
        assert _stop_tightness_rank(6500.0, -1) > _stop_tightness_rank(6600.0, -1)


class TestExitLegRank:
    def test_long_trailing_stop_beats_tracked_initial(self):
        ib = MagicMock()
        ib.client = MagicMock(clientId=100)
        tracked = {560370323}
        tight = _stop_trade("PreSubmitted", 7457.0, perm_id=0)
        loose = _stop_trade("PreSubmitted", 7376.0, perm_id=560370323)
        tight_score = _exit_leg_rank(tight, tracked, 100, True, ib, 7376.0, direction=1)
        loose_score = _exit_leg_rank(loose, tracked, 100, True, ib, 7376.0, direction=1)
        assert tight_score > loose_score


class TestReferenceStopPx:
    def test_uses_model_stop_when_tighter_than_entry(self):
        pos = MagicMock()
        pos.position = 1.0
        pos.contract.conId = 99
        positions = [{
            "direction": 1,
            "contract": pos.contract,
            "entry_stop_price": 7376.0,
            "position_dict": {"stop": 7457.0},
        }]
        assert _reference_stop_px_for_position(positions, pos) == 7457.0


class TestTrailReplaceGuard:
    def test_in_progress_flag_blocks_consolidate_window(self):
        from datetime import datetime
        import pytz

        bracket = {"trail_replace_started_at": datetime.now(pytz.utc)}
        assert trail_replace_in_progress([bracket]) is True
        assert trail_replace_in_progress([]) is False


class TestReplaceTrailingStopZeroGap:
    def test_places_standalone_and_cancels_old_on_presubmitted(self):
        ib = MagicMock()
        ib.isConnected.return_value = True
        contract = MagicMock(conId=649180671)
        old_stop = MagicMock()
        old_stop.totalQuantity = 1.0
        old_stop.auxPrice = 7376.0
        old_stop.stopPrice = 7376.0
        bracket = {
            "contract": contract,
            "direction": 1,
            "position_dict": {"stop": 7457.0},
            "stopLoss": old_stop,
        }

        placed = []

        def _place(c, order):
            placed.append(order)
            order.orderId = 2001
            order.permId = 9001

        ib.placeOrder.side_effect = _place

        new_trade = _stop_trade("PreSubmitted", 7457.0, perm_id=9001)
        new_trade.order.orderId = 2001
        new_trade.contract = contract
        ib.trades.return_value = [new_trade]

        ok = replace_trailing_stop_zero_gap(
            ib, contract, bracket, 7457.0, 1, old_stop, timeout=0.5,
        )
        assert ok is True
        assert bracket["stopLoss"] is placed[0]
        assert bracket["position_dict"]["stop"] == 7457.0
        ib.cancelOrder.assert_called_with(old_stop)
        assert trail_replace_in_progress([bracket]) is False

    def test_failure_reverts_and_cancels_new_order(self):
        ib = MagicMock()
        ib.isConnected.return_value = True
        contract = MagicMock(conId=1)
        old_stop = MagicMock(totalQuantity=1.0, auxPrice=7376.0, stopPrice=7376.0)
        new_order = MagicMock()
        bracket = {"contract": contract, "position_dict": {"stop": 7457.0}}

        def _place(c, order):
            nonlocal new_order
            new_order = order
            order.orderId = 99

        ib.placeOrder.side_effect = _place
        ib.trades.return_value = []

        ok = replace_trailing_stop_zero_gap(
            ib, contract, bracket, 7457.0, 1, old_stop, timeout=0.25,
        )
        assert ok is False
        ib.cancelOrder.assert_called_with(new_order)

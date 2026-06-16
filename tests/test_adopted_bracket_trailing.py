"""Trailing and exit path for adopted/restored IB brackets."""
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.execution import check_exits
from core.protection import (
    adopt_ib_protection_for_position,
    wire_bracket_entry_from_ib,
    _estimate_bars_held_since_entry,
    _ib_fill_time_to_naive_et,
    _ib_fill_to_naive_et,
)


def _filled_entry_trade(con_id, order_id=1470, perm_id=560370322, price=7446.5):
    order = MagicMock()
    order.orderId = order_id
    order.permId = perm_id
    order.action = "BUY"
    order.orderType = "MKT"
    order.totalQuantity = 1.0
    trade = MagicMock()
    trade.contract = MagicMock(conId=con_id)
    trade.order = order
    trade.filled.return_value = True
    trade.isActive.return_value = False
    fill = MagicMock()
    fill.execution.price = price
    fill.execution.time = datetime(2026, 6, 10, 17, 58, 6, tzinfo=pytz.utc)
    fill.time = datetime(2026, 6, 10, 13, 58, 6, tzinfo=pytz.utc)
    trade.fills = [fill]
    return trade


def _stop_trade(con_id, perm_id=560370323, aux=7376.0):
    order = MagicMock()
    order.permId = perm_id
    order.orderId = 1471
    order.auxPrice = aux
    order.stopPrice = aux
    order.action = "SELL"
    order.totalQuantity = 1.0
    order.orderType = "STP"
    order.parentId = 1470
    order.clientId = 100
    trade = MagicMock()
    trade.contract = MagicMock(conId=con_id)
    trade.order = order
    trade.isActive.return_value = True
    trade.orderStatus = MagicMock(status="PreSubmitted")
    return trade


class TestBarsHeldEstimate:
    def test_estimates_from_entry_time(self):
        entry = datetime(2026, 6, 10, 9, 58, 0)
        assert _estimate_bars_held_since_entry(entry, 13) >= 4


class TestIbFillTimeConversion:
    def test_utc_fill_converts_to_eastern_naive(self):
        # 16:15 ET (EDT) == 20:15 UTC same calendar day
        utc_fill = datetime(2026, 6, 10, 20, 15, 6, tzinfo=pytz.utc)
        et = _ib_fill_time_to_naive_et(utc_fill)
        assert et == datetime(2026, 6, 10, 16, 15, 6)

    def test_prefers_fill_time_over_execution_time(self):
        """Paper IB: execution.time can be ~4h ahead of fill.time (live_trades uses fill.time)."""
        fill = MagicMock()
        fill.time = datetime(2026, 6, 11, 15, 16, 7, tzinfo=pytz.utc)
        fill.execution.time = datetime(2026, 6, 11, 19, 16, 7, tzinfo=pytz.utc)
        assert _ib_fill_to_naive_et(fill) == datetime(2026, 6, 11, 11, 16, 7)

    def test_wire_bracket_entry_sets_eastern_entry_time(self):
        ib = MagicMock()
        pos = MagicMock(position=-1, contract=MagicMock(conId=649180671))
        bracket = {"direction": -1, "position_dict": {}}
        entry_trade = _filled_entry_trade(649180671, order_id=1498, perm_id=560370353, price=7329.75)
        entry_trade.order.action = "SELL"
        entry_trade.fills[0].time = datetime(2026, 6, 10, 15, 16, 6, tzinfo=pytz.utc)
        entry_trade.fills[0].execution.time = datetime(2026, 6, 10, 19, 16, 6, tzinfo=pytz.utc)
        with patch("core.protection._find_filled_entry_trade_for_position", return_value=entry_trade):
            assert wire_bracket_entry_from_ib(ib, pos, bracket) is True
        assert bracket["entry_time"] == datetime(2026, 6, 10, 11, 16, 6)


class TestWireBracketEntry:
    def test_wires_entry_order_id_and_bars_held(self):
        ib = MagicMock()
        con_id = 649180671
        pos = MagicMock()
        pos.position = 1.0
        pos.contract = MagicMock(conId=con_id)
        entry_trade = _filled_entry_trade(con_id)
        stop_trade = _stop_trade(con_id)
        ib.trades.return_value = [entry_trade, stop_trade]

        strategy = MagicMock()
        strategy.timeframe = 13

        bracket = {
            "entry": MagicMock(),
            "stopLoss": stop_trade.order,
            "takeProfit": None,
            "direction": 1,
            "position_dict": {"direction": 1, "stop": 7376.0},
            "restored_from_ib": True,
        }

        assert wire_bracket_entry_from_ib(ib, pos, bracket, strategy=strategy) is True
        assert bracket["entryOrderId"] == 1470
        assert bracket["entry_price"] == 7446.5
        assert bracket["position_dict"]["bars_held"] >= 4
        assert bracket["position_verified"] is True


class TestAdoptProtection:
    def test_adopt_wires_entry_for_trailing(self):
        ib = MagicMock()
        con_id = 649180671
        pos = MagicMock()
        pos.position = 1.0
        pos.contract = MagicMock(conId=con_id, localSymbol="ESU6")
        pos.avgCost = 372327.25

        entry_trade = _filled_entry_trade(con_id)
        stop_trade = _stop_trade(con_id)
        ib.trades.return_value = [stop_trade, entry_trade]

        strategy = MagicMock()
        strategy.timeframe = 13

        positions = []
        assert adopt_ib_protection_for_position(ib, positions, pos, strategy=strategy) is True
        assert len(positions) == 1
        b = positions[0]
        assert b["entryOrderId"] == 1470
        assert b["position_dict"].get("bars_held", 0) >= 0
        assert b["position_verified"] is True


class TestCheckExitsAdoptedBracket:
    def test_trailing_runs_on_adopted_bracket_without_prior_entry_order_id(self):
        strategy = MagicMock()
        strategy.check_exit.return_value = (False, None, None)
        def _tighten_stop(pos, row, data):
            pos["stop"] = 7420.0
            return True

        strategy.update_trailing_stop.side_effect = _tighten_stop
        strategy.enable_rth_filter = False
        strategy.enable_maintenance_filter = False
        strategy.opposite_bb_tp = False
        strategy.timeframe = 13

        ib = MagicMock()
        con_id = 649180671
        contract = MagicMock(conId=con_id, symbol="ES")

        entry_trade = _filled_entry_trade(con_id)
        stop_trade = _stop_trade(con_id)
        tp_order = MagicMock()
        tp_order.permId = 560370324
        tp_order.orderId = 1472
        tp_order.lmtPrice = 7514.5
        tp_order.action = "SELL"
        tp_order.totalQuantity = 1.0
        tp_order.orderType = "LMT"
        tp_order.parentId = 1470
        tp_trade = MagicMock()
        tp_trade.order = tp_order
        tp_trade.contract = MagicMock(conId=con_id)
        tp_trade.isActive.return_value = True
        tp_trade.orderStatus = MagicMock(status="Submitted")

        ib.trades.return_value = [entry_trade, stop_trade, tp_trade]

        pos = MagicMock()
        pos.contract.conId = con_id
        pos.position = 1.0
        ib.positions.return_value = [pos]

        data = pd.DataFrame(
            {"close": [7427.0], "high": [7454.0], "low": [7423.0], "atr": [14.8]},
            index=pd.DatetimeIndex([pd.Timestamp("2026-06-10 10:53:00")]),
        )

        bracket = {
            "entry": MagicMock(permId=0, orderId=0),
            "stopLoss": stop_trade.order,
            "takeProfit": tp_order,
            "direction": 1,
            "position_dict": {"direction": 1, "stop": 7376.0, "bars_held": 4},
            "entry_price": 7446.5,
            "entry_stop_price": 7376.0,
            "entry_tp_price": 7514.5,
            "ocaGroup": "560370322",
            "restored_from_ib": True,
            "position_verified": True,
            "open_notified": True,
            "contract": contract,
        }
        positions = [bracket]

        with patch("core.execution.replace_oca_exit_pair_zero_gap", return_value=True) as mock_replace:
            check_exits(
                strategy,
                ib,
                contract,
                data,
                positions,
                [],
                [],
                MagicMock(),
                data.index[-1],
                data.iloc[-1],
                allow_strategy_exit=True,
                skip_trailing=False,
            )
            mock_replace.assert_called_once()

        strategy.update_trailing_stop.assert_called_once()

    def test_trailing_syncs_broker_when_stop_missing_from_ib_trades_cache(self):
        """Model trail must reach IB even if ib.trades() omits the protective stop leg."""
        strategy = MagicMock()
        strategy.check_exit.return_value = (False, None, None)
        strategy.enable_rth_filter = False
        strategy.enable_maintenance_filter = False
        strategy.opposite_bb_tp = False

        def _tighten_stop(pos, row, data):
            pos["stop"] = 7381.5
            return True

        strategy.update_trailing_stop.side_effect = _tighten_stop

        ib = MagicMock()
        con_id = 649180671
        contract = MagicMock(conId=con_id, symbol="ES", localSymbol="ESU6")

        entry_order = MagicMock(orderId=1487, permId=560370334, action="SELL", totalQuantity=1.0)
        entry_trade = _filled_entry_trade(con_id, order_id=1487, perm_id=560370334, price=7398.25)
        entry_trade.order = entry_order

        stop_order = MagicMock(
            permId=560370335,
            orderId=1488,
            auxPrice=7472.5,
            action="BUY",
            totalQuantity=1.0,
            parentId=1487,
        )
        tp_order = MagicMock(permId=560370336, lmtPrice=7312.5, parentId=1487)

        # Entry only — stop leg absent from ib.trades() (stale cache after adopt)
        ib.trades.return_value = [entry_trade]

        pos = MagicMock()
        pos.contract.conId = con_id
        pos.position = -1.0
        ib.positions.return_value = [pos]

        data = pd.DataFrame(
            {"close": [7382.0], "high": [7391.75], "low": [7379.75], "atr": [17.6]},
            index=pd.DatetimeIndex([pd.Timestamp("2026-06-10 12:24:00")]),
        )

        bracket = {
            "entry": entry_order,
            "entryOrderId": 1487,
            "stopLoss": stop_order,
            "takeProfit": tp_order,
            "direction": -1,
            "position_dict": {"direction": -1, "stop": 7472.5, "bars_held": 1},
            "entry_price": 7398.25,
            "entry_stop_price": 7472.5,
            "entry_tp_price": 7312.5,
            "ocaGroup": "560370334",
            "restored_from_ib": True,
            "position_verified": True,
            "contract": contract,
        }

        with patch("core.execution.replace_oca_exit_pair_zero_gap", return_value=True) as mock_replace:
            check_exits(
                strategy,
                ib,
                contract,
                data,
                [bracket],
                [],
                MagicMock(),
                MagicMock(),
                data.index[-1],
                data.iloc[-1],
                allow_strategy_exit=True,
            )
            mock_replace.assert_called_once()
            assert bracket["position_dict"]["stop"] == 7381.5

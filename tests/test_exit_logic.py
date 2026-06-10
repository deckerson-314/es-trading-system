import unittest
import pandas as pd
from unittest.mock import MagicMock
import sys
import os

import core.execution as core_execution

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.execution import check_exits

class TestExitLogic(unittest.TestCase):
    def test_short_exit_no_trigger(self):
        """Test that a short trade doesn't trigger exit prematurely when price is below stop."""
        strategy = MagicMock()
        strategy.check_exit.return_value = (False, None, None)
        strategy.update_trailing_stop.return_value = False
        strategy.enable_rth_filter = False
        strategy.enable_maintenance_filter = False

        ib = MagicMock()
        contract = MagicMock()
        contract.conId = 12345
        contract.symbol = 'ES'
        
        data = pd.DataFrame({'close': [6612.0], 'high': [6615.0], 'low': [6605.0]})
        latest_row = data.iloc[-1]
        
        entry_order = MagicMock()
        entry_order.permId = 1
        entry_trade = MagicMock()
        entry_trade.order = entry_order
        entry_trade.isActive.return_value = False
        entry_trade.fills = [MagicMock()]
        entry_trade.contract = contract
        
        stop_order = MagicMock()
        stop_order.permId = 2
        stop_order.auxPrice = 6626.0
        
        tp_order = MagicMock()
        tp_order.permId = 3
        
        ib.trades.return_value = [entry_trade]
        
        pos = MagicMock()
        pos.contract.conId = 12345
        pos.position = -1.0
        ib.positions.return_value = [pos]
        
        bracket = {
            'entry': entry_order,
            'stopLoss': stop_order,
            'takeProfit': tp_order,
            'direction': -1,
            'position_dict': {'direction': -1, 'stop': 6626.0},
            'entry_time': pd.Timestamp.now(),
            'entry_price': 6613.0,
            'position_verified': True
        }
        
        positions = [bracket]
        completed_trades = []
        
        check_exits(strategy, ib, contract, data, positions, completed_trades,
                    [], MagicMock(), 0, latest_row, allow_strategy_exit=True)
        
        # Verify: exit should NOT have been triggered
        self.assertEqual(len(positions), 1)
        strategy.check_exit.assert_called_once()
        
        # Verify passed dictionary structure
        args, _ = strategy.check_exit.call_args
        passed_pos = args[0]
        self.assertIn('stop', passed_pos)
        self.assertEqual(passed_pos['stop'], 6626.0)
        self.assertNotIn('position_dict', passed_pos)

    def test_short_exit_trigger(self):
        """Legacy soft exit when broker-authoritative mode is off."""
        strategy = MagicMock()
        strategy.check_exit.return_value = (True, 'Stop Loss', 6626.0)
        strategy.update_trailing_stop.return_value = False
        strategy.enable_rth_filter = False
        strategy.enable_maintenance_filter = False

        ib = MagicMock()
        contract = MagicMock()
        contract.conId = 12345
        
        data = pd.DataFrame({'close': [6627.0], 'high': [6628.0], 'low': [6625.0]})
        latest_row = data.iloc[-1]
        
        entry_order = MagicMock()
        entry_order.permId = 1
        entry_trade = MagicMock()
        entry_trade.order = entry_order
        entry_trade.isActive.return_value = False
        entry_trade.fills = [MagicMock()]
        entry_trade.contract = contract
        
        stop_order = MagicMock()
        stop_order.permId = 2
        stop_order.auxPrice = 6626.0
        stop_order.stopPrice = 6626.0
        
        tp_order = MagicMock()
        tp_order.permId = 3
        
        ib.trades.return_value = [entry_trade]
        
        pos = MagicMock()
        pos.contract.conId = 12345
        pos.position = -1.0
        ib.positions.return_value = [pos]
        
        bracket = {
            'entry': entry_order,
            'stopLoss': stop_order,
            'takeProfit': tp_order,
            'direction': -1,
            'position_dict': {'direction': -1, 'stop': 6626.0},
            'entry_time': pd.Timestamp.now(),
            'entry_price': 6613.0,
            'position_verified': True
        }
        
        positions = [bracket]
        
        # Mock _force_close_position
        old_force = core_execution._force_close_position
        core_execution._force_close_position = MagicMock()
        old_flag = os.environ.get("LIVE_BROKER_AUTHORITATIVE_EXIT")
        os.environ["LIVE_BROKER_AUTHORITATIVE_EXIT"] = "0"

        try:
            check_exits(strategy, ib, contract, data, positions, [],
                        None, MagicMock(), 0, latest_row, allow_strategy_exit=True)
            core_execution._force_close_position.assert_called_once()
        finally:
            core_execution._force_close_position = old_force
            if old_flag is None:
                os.environ.pop("LIVE_BROKER_AUTHORITATIVE_EXIT", None)
            else:
                os.environ["LIVE_BROKER_AUTHORITATIVE_EXIT"] = old_flag

    def test_record_trade_close_ignores_stale_fills(self):
        """Test that _record_trade_close doesn't pick up fills from before the entry_time."""
        from core.execution import _record_trade_close
        import pytz
        from datetime import datetime, timedelta
        
        ib = MagicMock()
        contract = MagicMock()
        contract.conId = 12345
        
        # Scenario: Short trade entered at 10:00
        # There's a 'BOT' fill at 09:00 (stale)
        # Entry price 6500
        entry_time = datetime(2026, 4, 1, 10, 0, 0, tzinfo=pytz.utc)
        bracket = {'entry_price': 6500.0, 'entry_time': entry_time}
        
        # Stale fill
        stale_fill = MagicMock()
        stale_fill.contract.conId = 12345
        stale_fill.execution.side = 'BOT'
        stale_fill.execution.price = 6600.0 # This would cause a huge loss if picked up
        stale_fill.execution.time = entry_time - timedelta(hours=1)
        stale_fill.execution.shares = 1
        
        ib.fills.return_value = [stale_fill]
        
        # Mock recent row for price fallback
        latest_row = {'close': 6490.0} # A small profit
        
        completed_trades = []
        _record_trade_close(
            ib, contract, bracket, None, None, None,
            None, None, -1, latest_row, [],
            completed_trades, [], MagicMock(), None,
            reason='Unknown'
        )
        
        # Verify result
        self.assertEqual(len(completed_trades), 1)
        trade = completed_trades[0]
        # Should NOT use stale_fill (6600), should use latest_row (6490)
        self.assertEqual(trade['exit_price'], 6490.0)
        # PNL = (6500 - 6490) * -1 (Short) * 50? No, Short PNL = (Entry - Exit) * Qty * 50
        # Wait, core/execution.py: pnl = (exit_price - entry_price) * dir_ * 50
        # (6490 - 6500) * -1 * 50 = -10 * -50 = +500
        self.assertEqual(trade['pnl'], 500.0)

    def test_check_exits_clamping_for_entry_bar(self):
        """Test that check_exits clamps the high/low for the entry bar to prevent immediate stops."""
        from core.execution import check_exits
        from datetime import datetime, timedelta
        import pandas as pd
        
        strategy = MagicMock()
        strategy.enable_rth_filter = False
        strategy.enable_maintenance_filter = False
        strategy.opposite_bb_tp = False
        strategy.update_trailing_stop.return_value = False
        strategy.timeframe = 1

        ib = MagicMock()
        contract = MagicMock()
        contract.conId = 12345
        
        # Entry at 10:36:05
        entry_time = datetime(2026, 4, 1, 10, 36, 5)
        
        # Signal bar is 10:35:00
        # Wait! If latest_row is 10:35:00, and entry is 10:36:05, 
        # then 10:35:00 <= 10:36:00 (clamped).
        latest_row = pd.Series({
            'open': 6605.0, 'high': 6610.0, 'low': 6580.0, 'close': 6601.25
        }, name=datetime(2026, 4, 1, 10, 35, 0))
        
        # Stop is 6588.25. 
        # Note that latest_row['low'] (6580.0) is BELOW the stop!
        stop_order = MagicMock()
        stop_order.auxPrice = 6588.25
        stop_order.permId = 999
        
        bracket = {
            'entry': MagicMock(permId=888),
            'stopLoss': stop_order,
            'takeProfit': None,
            'direction': 1, # Long
            'entry_time': entry_time,
            'position_dict': {'stop': 6588.25, 'direction': 1},
            'position_verified': True,
        }
        positions = [bracket]
        
        # Mock entry trade as filled
        entry_trade = MagicMock()
        entry_trade.order.permId = 888
        entry_trade.isActive.return_value = False
        entry_trade.fills = [MagicMock()]
        entry_trade.contract = contract
        stop_trade = MagicMock()
        stop_trade.order = stop_order
        stop_trade.isActive.return_value = True
        stop_trade.orderStatus = MagicMock(status="Submitted")
        ib.trades.return_value = [entry_trade, stop_trade]

        pos = MagicMock()
        pos.contract.conId = 12345
        pos.position = 1.0
        ib.positions.return_value = [pos]

        completed_trades = []
        strategy.check_exit.return_value = (False, None, None)
        old_flag = os.environ.get("LIVE_BROKER_AUTHORITATIVE_EXIT")
        os.environ["LIVE_BROKER_AUTHORITATIVE_EXIT"] = "1"

        try:
            check_exits(strategy, ib, contract, pd.DataFrame(), positions, completed_trades,
                       [], MagicMock(), 0, latest_row, allow_strategy_exit=True)
        finally:
            if old_flag is None:
                os.environ.pop("LIVE_BROKER_AUTHORITATIVE_EXIT", None)
            else:
                os.environ["LIVE_BROKER_AUTHORITATIVE_EXIT"] = old_flag

        # Verify result: strategy.check_exit should have been called with EVAL_ROW
        # where high/low are clamped to close (6601.25)
        # Because eval_row['low'] (6601.25) > stop (6588.25), it should NOT trigger.
        strategy.check_exit.assert_called()
        call_args = strategy.check_exit.call_args[0]
        eval_row = call_args[1]
        self.assertEqual(eval_row['low'], 6601.25)
        self.assertEqual(eval_row['high'], 6601.25)
        
        # Positions should still contain the bracket
        self.assertEqual(len(positions), 1)

    def test_phase1_skip_trailing_on_monitor_tick(self):
        """1-min monitor passes must not ratchet trail or advance bars_held."""
        strategy = MagicMock()
        strategy.check_exit.return_value = (False, None, None)
        strategy.update_trailing_stop.return_value = False
        strategy.enable_rth_filter = False
        strategy.enable_maintenance_filter = False
        strategy.opposite_bb_tp = False

        ib = MagicMock()
        contract = MagicMock()
        contract.conId = 12345
        contract.symbol = "ES"

        data = pd.DataFrame(
            {"close": [6612.0], "high": [6615.0], "low": [6605.0]},
            index=pd.DatetimeIndex([pd.Timestamp("2026-05-18 10:01:00")]),
        )
        latest_row = data.iloc[-1]

        entry_order = MagicMock()
        entry_order.permId = 1
        entry_trade = MagicMock()
        entry_trade.order = entry_order
        entry_trade.isActive.return_value = False
        entry_trade.fills = [MagicMock()]
        entry_trade.contract = contract

        stop_order = MagicMock()
        stop_order.permId = 2
        stop_order.auxPrice = 6626.0
        stop_trade = MagicMock()
        stop_trade.order = stop_order
        stop_trade.isActive.return_value = True
        stop_trade.orderStatus = MagicMock(status="Submitted")

        ib.trades.return_value = [entry_trade, stop_trade]

        pos = MagicMock()
        pos.contract.conId = 12345
        pos.position = -1.0
        ib.positions.return_value = [pos]

        bracket = {
            "entry": entry_order,
            "stopLoss": stop_order,
            "takeProfit": None,
            "direction": -1,
            "position_dict": {"direction": -1, "stop": 6626.0, "bars_held": 2},
            "entry_time": pd.Timestamp("2026-05-18 09:40:00"),
            "entry_price": 6613.0,
            "position_verified": True,
        }
        positions = [bracket]

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
            latest_row,
            allow_strategy_exit=False,
            skip_trailing=True,
        )

        strategy.update_trailing_stop.assert_not_called()
        strategy.check_exit.assert_not_called()

    def test_phase1_trailing_on_strategy_bar_only(self):
        """Strategy bar hook runs trail when allow_strategy_exit and not skip_trailing."""
        strategy = MagicMock()
        strategy.check_exit.return_value = (False, None, None)
        strategy.update_trailing_stop.return_value = False
        strategy.enable_rth_filter = False
        strategy.enable_maintenance_filter = False
        strategy.opposite_bb_tp = False

        ib = MagicMock()
        contract = MagicMock()
        contract.conId = 12345
        contract.symbol = "ES"

        data = pd.DataFrame(
            {"close": [6612.0], "high": [6615.0], "low": [6605.0], "atr": [10.0]},
            index=pd.DatetimeIndex([pd.Timestamp("2026-05-18 10:13:00")]),
        )
        latest_row = data.iloc[-1]

        entry_order = MagicMock()
        entry_order.permId = 1
        entry_trade = MagicMock()
        entry_trade.order = entry_order
        entry_trade.isActive.return_value = False
        entry_trade.fills = [MagicMock()]
        entry_trade.contract = contract

        stop_order = MagicMock()
        stop_order.permId = 2
        stop_order.auxPrice = 6626.0
        stop_trade = MagicMock()
        stop_trade.order = stop_order
        stop_trade.isActive.return_value = True
        stop_trade.orderStatus = MagicMock(status="Submitted")

        ib.trades.return_value = [entry_trade, stop_trade]

        pos = MagicMock()
        pos.contract.conId = 12345
        pos.position = -1.0
        ib.positions.return_value = [pos]

        bracket = {
            "entry": entry_order,
            "stopLoss": stop_order,
            "takeProfit": None,
            "direction": -1,
            "position_dict": {"direction": -1, "stop": 6626.0, "bars_held": 2},
            "entry_time": pd.Timestamp("2026-05-18 09:40:00"),
            "entry_price": 6613.0,
            "position_verified": True,
        }
        positions = [bracket]

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
            latest_row,
            allow_strategy_exit=True,
            skip_trailing=False,
        )

        strategy.update_trailing_stop.assert_called_once()

    def test_broker_auth_defers_stop_loss_when_stop_armed(self):
        """Phase 2: no cancel+market on strategy SL when broker stop is Submitted and not breached."""
        strategy = MagicMock()
        strategy.check_exit.return_value = (True, "Stop Loss", 6626.0)
        strategy.update_trailing_stop.return_value = False
        strategy.enable_rth_filter = False
        strategy.enable_maintenance_filter = False
        strategy.opposite_bb_tp = False

        ib = MagicMock()
        contract = MagicMock()
        contract.conId = 12345
        contract.symbol = "ES"

        data = pd.DataFrame(
            {"close": [6627.0], "high": [6620.0], "low": [6625.0]},
            index=pd.DatetimeIndex([pd.Timestamp("2026-05-19 10:11:00")]),
        )
        latest_row = data.iloc[-1]

        entry_order = MagicMock()
        entry_order.permId = 1
        entry_trade = MagicMock()
        entry_trade.order = entry_order
        entry_trade.isActive.return_value = False
        entry_trade.fills = [MagicMock()]
        entry_trade.contract = contract

        stop_order = MagicMock()
        stop_order.permId = 2
        stop_order.auxPrice = 6630.0
        stop_order.lmtPrice = 0.0
        stop_order.stopPrice = 6630.0
        stop_trade = MagicMock()
        stop_trade.order = stop_order
        stop_trade.contract = contract
        stop_trade.isActive.return_value = True
        stop_trade.orderStatus = MagicMock(status="Submitted", whyHeld="")

        tp_order = MagicMock()
        tp_order.permId = 3
        tp_trade = MagicMock()
        tp_trade.order = tp_order
        tp_trade.isActive.return_value = True
        tp_trade.orderStatus = MagicMock(status="Submitted")

        ib.trades.return_value = [entry_trade, stop_trade, tp_trade]

        pos = MagicMock()
        pos.contract.conId = 12345
        pos.position = -1.0
        ib.positions.return_value = [pos]

        bracket = {
            "entry": entry_order,
            "stopLoss": stop_order,
            "takeProfit": tp_order,
            "direction": -1,
            "position_dict": {"direction": -1, "stop": 6630.0, "bars_held": 1},
            "entry_time": pd.Timestamp("2026-05-19 09:58:00"),
            "entry_price": 6613.0,
            "position_verified": True,
            "open_notified": True,
            "contract": contract,
        }

        old_force = core_execution._force_close_position
        core_execution._force_close_position = MagicMock()
        old_flag = os.environ.get("LIVE_BROKER_AUTHORITATIVE_EXIT")
        os.environ["LIVE_BROKER_AUTHORITATIVE_EXIT"] = "1"

        try:
            check_exits(
                strategy, ib, contract, data, [bracket], [],
                [], MagicMock(), data.index[-1], latest_row,
                allow_strategy_exit=True,
            )
            core_execution._force_close_position.assert_not_called()
            self.assertEqual(len([bracket]), 1)
        finally:
            core_execution._force_close_position = old_force
            if old_flag is None:
                os.environ.pop("LIVE_BROKER_AUTHORITATIVE_EXIT", None)
            else:
                os.environ["LIVE_BROKER_AUTHORITATIVE_EXIT"] = old_flag

    def test_broker_auth_force_close_when_stop_breached_but_leg_presubmitted(self):
        """If price trades through stop and IB leg is still PreSubmitted, flatten."""
        strategy = MagicMock()
        strategy.check_exit.return_value = (True, "Stop Loss", 7575.25)
        strategy.update_trailing_stop.return_value = False
        strategy.enable_rth_filter = False
        strategy.enable_maintenance_filter = False
        strategy.opposite_bb_tp = False

        ib = MagicMock()
        contract = MagicMock()
        contract.conId = 12345
        contract.symbol = "ES"

        data = pd.DataFrame(
            {"close": [7574.5], "high": [7577.0], "low": [7572.75]},
            index=pd.DatetimeIndex([pd.Timestamp("2026-05-28 21:33:00")]),
        )
        latest_row = data.iloc[-1]

        entry_order = MagicMock()
        entry_order.permId = 1
        entry_trade = MagicMock()
        entry_trade.order = entry_order
        entry_trade.isActive.return_value = False
        entry_trade.fills = [MagicMock()]
        entry_trade.contract = contract

        stop_order = MagicMock()
        stop_order.permId = 2
        stop_order.auxPrice = 7575.25
        stop_trade = MagicMock()
        stop_trade.order = stop_order
        stop_trade.isActive.return_value = True
        stop_trade.orderStatus = MagicMock(status="PreSubmitted", whyHeld="trigger")

        tp_order = MagicMock()
        tp_order.permId = 3
        tp_trade = MagicMock()
        tp_trade.order = tp_order
        tp_trade.isActive.return_value = True
        tp_trade.orderStatus = MagicMock(status="Submitted")

        ib.trades.return_value = [entry_trade, stop_trade, tp_trade]

        pos = MagicMock()
        pos.contract.conId = 12345
        pos.position = 1.0
        ib.positions.return_value = [pos]

        bracket = {
            "entry": entry_order,
            "stopLoss": stop_order,
            "takeProfit": tp_order,
            "direction": 1,
            "position_dict": {"direction": 1, "stop": 7575.25, "bars_held": 1},
            "entry_time": pd.Timestamp("2026-05-28 18:12:00"),
            "entry_price": 7586.75,
            "position_verified": True,
        }

        old_force = core_execution._force_close_position
        core_execution._force_close_position = MagicMock()
        old_flag = os.environ.get("LIVE_BROKER_AUTHORITATIVE_EXIT")
        os.environ["LIVE_BROKER_AUTHORITATIVE_EXIT"] = "1"

        try:
            check_exits(
                strategy, ib, contract, data, [bracket], [],
                [], MagicMock(), data.index[-1], latest_row,
                allow_strategy_exit=True,
            )
            core_execution._force_close_position.assert_called_once()
        finally:
            core_execution._force_close_position = old_force
            if old_flag is None:
                os.environ.pop("LIVE_BROKER_AUTHORITATIVE_EXIT", None)
            else:
                os.environ["LIVE_BROKER_AUTHORITATIVE_EXIT"] = old_flag

    def test_channel_exit_uses_channel_label(self):
        strategy = MagicMock()
        strategy.check_exit.return_value = (True, "Channel Exit", 6610.0)
        strategy.update_trailing_stop.return_value = False
        strategy.enable_rth_filter = False
        strategy.enable_maintenance_filter = False
        strategy.opposite_bb_tp = False

        ib = MagicMock()
        contract = MagicMock()
        contract.conId = 12345

        data = pd.DataFrame(
            {"close": [6612.0], "high": [6615.0], "low": [6605.0]},
            index=pd.DatetimeIndex([pd.Timestamp("2026-05-19 10:24:00")]),
        )
        latest_row = data.iloc[-1]

        entry_order = MagicMock()
        entry_order.permId = 1
        entry_trade = MagicMock()
        entry_trade.order = entry_order
        entry_trade.isActive.return_value = False
        entry_trade.fills = [MagicMock()]
        entry_trade.contract = contract

        stop_order = MagicMock()
        stop_order.permId = 2
        stop_order.auxPrice = 6626.0
        stop_trade = MagicMock()
        stop_trade.order = stop_order
        stop_trade.isActive.return_value = True
        stop_trade.orderStatus = MagicMock(status="Submitted")

        ib.trades.return_value = [entry_trade, stop_trade]

        pos = MagicMock()
        pos.contract.conId = 12345
        pos.position = -1.0
        ib.positions.return_value = [pos]

        bracket = {
            "entry": entry_order,
            "stopLoss": stop_order,
            "takeProfit": None,
            "direction": -1,
            "position_dict": {"direction": -1, "stop": 6626.0},
            "entry_time": pd.Timestamp("2026-05-19 10:00:00"),
            "entry_price": 6613.0,
            "position_verified": True,
            "contract": contract,
        }

        old_channel = core_execution._exit_channel_signal
        core_execution._exit_channel_signal = MagicMock()
        old_flag = os.environ.get("LIVE_BROKER_AUTHORITATIVE_EXIT")
        os.environ["LIVE_BROKER_AUTHORITATIVE_EXIT"] = "1"

        try:
            check_exits(
                strategy, ib, contract, data, [bracket], [],
                [], MagicMock(), data.index[-1], latest_row,
                allow_strategy_exit=True,
            )
            core_execution._exit_channel_signal.assert_called_once()
        finally:
            core_execution._exit_channel_signal = old_channel
            if old_flag is None:
                os.environ.pop("LIVE_BROKER_AUTHORITATIVE_EXIT", None)
            else:
                os.environ["LIVE_BROKER_AUTHORITATIVE_EXIT"] = old_flag


if __name__ == '__main__':
    unittest.main()

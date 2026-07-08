"""Tests for completed-trade dedupe/merge and TRADE OPEN fill helpers."""
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.completed_trades import (
    merge_trade_records,
    dedupe_completed_trades_near_fills,
    completed_trade_quality_score,
)
from core.execution import (
    _wait_for_entry_fill,
    _send_trade_open_notification,
    register_completed_trade_persist_hook,
    _append_completed_trade_record,
)


class TestCompletedTradesMerge(unittest.TestCase):
    def test_merge_csv_and_log_prefers_broker_reason(self):
        exit_ts = datetime(2026, 5, 20, 9, 30, 0)
        entry_ts = datetime(2026, 5, 20, 8, 40, 8)
        csv_row = {
            "exit_time": exit_ts,
            "entry_time": entry_ts,
            "direction": "LONG",
            "qty": 1.0,
            "entry_price": 7410.5,
            "exit_price": 7394.5,
            "pnl": -800.0,
            "r_multiple": 0.0,
            "reason": "Backfilled (CSV Match)",
            "duration": "Backfilled",
            "report_url": "",
            "stop_at_close": None,
            "tp_at_close": None,
        }
        log_row = {
            "exit_time": exit_ts,
            "entry_time": None,
            "direction": "N/A",
            "qty": 1,
            "entry_price": 0.0,
            "exit_price": 7394.5,
            "pnl": -804.5,
            "r_multiple": 0.0,
            "reason": "Broker Stop",
            "live_exit_type": "broker_stop",
            "duration": "Backfilled",
            "report_url": "",
            "stop_at_close": None,
            "tp_at_close": None,
        }
        merged = merge_trade_records([csv_row, log_row])
        self.assertEqual(merged["reason"], "Broker Stop")
        self.assertEqual(merged["entry_price"], 7410.5)
        self.assertEqual(merged["direction"], "LONG")
        self.assertEqual(merged["live_exit_type"], "broker_stop")

    def test_dedupe_near_fills_unions_rows(self):
        exit_ts = datetime(2026, 5, 20, 9, 30, 0)
        rows = [
            {
                "exit_time": exit_ts,
                "entry_time": datetime(2026, 5, 20, 8, 40, 8),
                "direction": "LONG",
                "entry_price": 7410.5,
                "exit_price": 7394.5,
                "pnl": -800.0,
                "reason": "Backfilled (CSV Match)",
            },
            {
                "exit_time": exit_ts,
                "entry_time": None,
                "direction": "N/A",
                "entry_price": 0.0,
                "exit_price": 7394.5,
                "pnl": -804.5,
                "reason": "Broker Stop",
                "live_exit_type": "broker_stop",
            },
        ]
        out = dedupe_completed_trades_near_fills(rows, window_sec=120, max_keep=10)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["reason"], "Broker Stop")
        self.assertGreater(
            completed_trade_quality_score(out[0]),
            completed_trade_quality_score(rows[0]),
        )

    def test_suppress_phantom_orphan_after_broker_tp(self):
        rows = [
            {
                "exit_time": "2026-06-22T09:30:40",
                "entry_time": "2026-06-22T06:32:07",
                "direction": "LONG",
                "exit_price": 7583.5,
                "pnl": 1220.5,
                "reason": "Broker Take Profit",
            },
            {
                "exit_time": "2026-06-22T09:31:14",
                "entry_time": None,
                "direction": "SHORT",
                "exit_price": 7585.5,
                "pnl": 70.5,
                "reason": "Orphan Auto-Close",
            },
            {
                "exit_time": "2026-06-22T09:31:34",
                "entry_time": "2026-06-22T06:32:07",
                "direction": "LONG",
                "exit_price": 7583.5,
                "pnl": 1220.5,
                "reason": "Broker Take Profit",
            },
        ]
        out = dedupe_completed_trades_near_fills(rows, window_sec=120, max_keep=10)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["direction"], "LONG")
        self.assertEqual(out[0]["reason"], "Broker Take Profit")
    def test_wait_for_entry_fill_polls_until_filled(self):
        ib = MagicMock()
        contract = MagicMock()
        contract.conId = 1
        trade = MagicMock()
        trade.filled.side_effect = [False, True, True]
        trade.fills = [MagicMock()]
        trade.fills[0].execution.price = 7410.5

        with patch("core.execution._find_entry_trade", return_value=trade):
            with patch("core.execution.time.monotonic", side_effect=[0.0, 0.1, 10.0]):
                got = _wait_for_entry_fill(ib, contract, 89, 0, timeout_sec=1.0, poll_sec=0.01)
        self.assertIs(got, trade)
        self.assertTrue(got.filled())

    def test_trade_open_notification_once(self):
        bracket = {"open_notified": False, "entry_price": 7410.5, "entry_stop_price": 7395.0}
        send = MagicMock()
        _send_trade_open_notification(
            bracket, 1, 7410.5, 7395.0, 7428.5, 1.0, datetime.now(),
            MagicMock(), MagicMock(), MagicMock(), send, [],
        )
        self.assertTrue(bracket["open_notified"])
        send.assert_called_once()
        send.reset_mock()
        _send_trade_open_notification(
            bracket, 1, 7410.5, 7395.0, 7428.5, 1.0, datetime.now(),
            MagicMock(), MagicMock(), MagicMock(), send, [],
        )
        send.assert_not_called()

    def test_persist_hook_on_append(self):
        hook = MagicMock()
        register_completed_trade_persist_hook(hook)
        rows = []
        _append_completed_trade_record(rows, {"reason": "Broker Stop", "pnl": -1.0})
        self.assertEqual(len(rows), 1)
        hook.assert_called_once()
        register_completed_trade_persist_hook(None)


if __name__ == "__main__":
    unittest.main()

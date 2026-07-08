"""Ghost-bracket / stale-dashboard regression tests."""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.execution import (
    purge_closed_brackets,
    bracket_counts_as_open_exposure,
    send_composite_status_notification,
    _record_trade_close,
)


class TestPurgeClosedBrackets(unittest.TestCase):
    def test_removes_close_recorded_brackets(self):
        positions = [
            {"direction": 1, "_close_recorded": True},
            {"direction": 1},
        ]
        n = purge_closed_brackets(positions)
        self.assertEqual(n, 1)
        self.assertEqual(len(positions), 1)
        self.assertNotIn("_close_recorded", positions[0] or {})


class TestBracketOpenExposure(unittest.TestCase):
    def test_close_recorded_never_open(self):
        ib = MagicMock()
        bracket = {"direction": 1, "_close_recorded": True, "entry": MagicMock()}
        self.assertFalse(bracket_counts_as_open_exposure(ib, MagicMock(), bracket))

    def test_filled_entry_flat_ib_not_open(self):
        ib = MagicMock()
        contract = MagicMock(conId=42)
        entry = MagicMock(orderId=1)
        trade = MagicMock()
        trade.filled.return_value = True
        ib.trades.return_value = [trade]
        ib.positions.return_value = []
        bracket = {
            "direction": 1,
            "entry": entry,
            "entryOrderId": 1,
            "contract": contract,
        }
        with unittest.mock.patch(
            "core.execution._entry_trade_for_bracket", return_value=trade,
        ):
            self.assertFalse(bracket_counts_as_open_exposure(ib, contract, bracket))


class TestCompositeStatusSkipsClosed(unittest.TestCase):
    def test_no_email_when_only_closed_brackets(self):
        send = MagicMock()
        send_composite_status_notification(
            MagicMock(),
            [{"direction": 1, "_close_recorded": True, "entry_price": 100}],
            MagicMock(empty=False, iloc=[MagicMock(close=100)]),
            {},
            send,
        )
        send.assert_not_called()


class TestRecordTradeCloseAlwaysPurges(unittest.TestCase):
    def test_bracket_removed_even_when_not_previously_in_list(self):
        ib = MagicMock()
        ib.trades.return_value = []
        ib.fills.return_value = []
        contract = MagicMock(conId=1)
        bracket = {"direction": 1, "entry_price": 100.0, "entry_time": None}
        positions = [bracket]
        _record_trade_close(
            ib, contract, bracket, None, None, None,
            None, None, 1, {"close": 99.0}, positions,
            [], [], MagicMock(), None,
            reason="Channel Exit (signal)",
        )
        self.assertEqual(positions, [])
        self.assertTrue(bracket.get("_close_recorded"))


if __name__ == "__main__":
    unittest.main()

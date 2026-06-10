"""Phase 3 + dashboard bundle tests (no live trade required)."""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if "dotenv" not in sys.modules:
    sys.modules["dotenv"] = __import__("unittest").mock.MagicMock()
    sys.modules["dotenv"].load_dotenv = lambda *a, **k: None

import sys as _sys
_sys.argv = ["test_phase3_bundle.py", "--port", "4002"]

from core.execution import (
    _exit_slippage_metrics,
    _wait_oca_pair_cancelled_with_retries,
)
from main import _has_open_market_exposure, collect_all_ib_open_orders


class TestSlippageMetrics(unittest.TestCase):
    def test_long_stop_slippage_negative_when_through_stop(self):
        m = _exit_slippage_metrics(1, 7394.5, 7395.0, None, "Broker Stop", qty=1)
        self.assertEqual(m["slippage_reference"], "broker_stop")
        self.assertEqual(m["slippage_pts"], -0.5)
        self.assertEqual(m["slippage_usd"], -25.0)

    def test_short_stop_slippage_sign(self):
        m = _exit_slippage_metrics(-1, 6610.0, 6615.0, None, "Broker Stop", qty=1)
        self.assertEqual(m["slippage_pts"], 5.0)


class TestOcaCancelRetries(unittest.TestCase):
    def test_retries_until_cancelled(self):
        ib = MagicMock()
        ib.sleep = MagicMock()
        with unittest.mock.patch("core.execution._wait_oca_pair_cancelled", side_effect=["timeout", "cancelled"]):
            out = _wait_oca_pair_cancelled_with_retries(ib, 1, 2, timeout=1.0, max_attempts=3)
        self.assertEqual(out, "cancelled")


class TestOpenOrdersFlatSkip(unittest.TestCase):
    def test_no_req_open_orders_when_refresh_disabled(self):
        global _last_req_open_orders_mono
        import main as main_mod

        ib = MagicMock()
        ib.trades.return_value = []
        main_mod._last_req_open_orders_mono = 0.0
        collect_all_ib_open_orders(ib, refresh_remote=False)
        ib.reqOpenOrders.assert_not_called()

    def test_has_open_exposure_from_bracket(self):
        ib = MagicMock()
        contract = MagicMock()
        contract.conId = 99
        entry = MagicMock(orderId=1, permId=1)
        trade = MagicMock()
        trade.filled.return_value = True
        trade.order = entry
        trade.contract.conId = 99
        ib.trades.return_value = [trade]
        ib.positions.return_value = []
        bracket = {
            "direction": 1,
            "entry": entry,
            "entryOrderId": 1,
            "contract": contract,
        }
        self.assertTrue(_has_open_market_exposure(ib, contract, [bracket]))


if __name__ == "__main__":
    unittest.main()

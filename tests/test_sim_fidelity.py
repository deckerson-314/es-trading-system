import os
import unittest

import pandas as pd

from core.sim_fidelity import (
    apply_conservative_stop_slippage,
    ga_pessimistic_stops_enabled,
    resolve_ga_stop_exit_price,
    should_skip_same_bar_stop_after_trail,
)


class TestSimFidelity(unittest.TestCase):
    def test_pessimistic_flag_from_param_dict(self):
        params = {"GA_PESSIMISTIC_STOPS": {"value": 1}}
        self.assertTrue(ga_pessimistic_stops_enabled(params))
        params["GA_PESSIMISTIC_STOPS"]["value"] = 0
        self.assertFalse(ga_pessimistic_stops_enabled(params))

    def test_pessimistic_flag_from_env(self):
        old = os.environ.get("GA_PESSIMISTIC_STOPS")
        os.environ["GA_PESSIMISTIC_STOPS"] = "1"
        try:
            self.assertTrue(ga_pessimistic_stops_enabled())
        finally:
            if old is None:
                os.environ.pop("GA_PESSIMISTIC_STOPS", None)
            else:
                os.environ["GA_PESSIMISTIC_STOPS"] = old

    def test_skip_same_bar_stop_after_trail(self):
        params = {"GA_PESSIMISTIC_STOPS": {"value": 1}}
        self.assertTrue(
            should_skip_same_bar_stop_after_trail(
                True, "Stop Loss", True, params,
            )
        )
        self.assertFalse(
            should_skip_same_bar_stop_after_trail(
                True, "Stop Loss", False, params,
            )
        )
        self.assertFalse(
            should_skip_same_bar_stop_after_trail(
                True, "Take Profit", True, params,
            )
        )

    def test_resolve_stop_uses_bar_close_when_pessimistic(self):
        params = {
            "GA_PESSIMISTIC_STOPS": {"value": 1},
            "GA_CONSERVATIVE_STOP_SLIPPAGE": {"value": 0},
        }
        row = pd.Series({"close": 6625.0})
        price = resolve_ga_stop_exit_price(
            6630.0, -1, "Stop Loss", row, params, stop_updated_same_bar=False,
        )
        self.assertEqual(price, 6625.0)

    def test_resolve_stop_applies_slippage(self):
        params = {
            "GA_PESSIMISTIC_STOPS": {"value": 0},
            "GA_CONSERVATIVE_STOP_SLIPPAGE": {"value": 1.0},
        }
        row = pd.Series({"close": 6625.0})
        long_price = resolve_ga_stop_exit_price(
            6620.0, 1, "Stop Loss", row, params,
        )
        short_price = resolve_ga_stop_exit_price(
            6630.0, -1, "Stop Loss", row, params,
        )
        self.assertEqual(long_price, 6619.0)
        self.assertEqual(short_price, 6631.0)

    def test_apply_conservative_slippage_non_stop_unchanged(self):
        params = {"GA_CONSERVATIVE_STOP_SLIPPAGE": {"value": 2.0}}
        self.assertEqual(
            apply_conservative_stop_slippage(100.0, 1, "Take Profit", params),
            100.0,
        )


if __name__ == "__main__":
    unittest.main()

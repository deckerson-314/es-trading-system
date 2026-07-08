import os
import unittest

import pandas as pd

from core.sim_fidelity import (
    apply_conservative_entry_slippage,
    apply_conservative_stop_slippage,
    ga_live_style_entry_enabled,
    ga_pessimistic_stops_enabled,
    resolve_ga_channel_exit_price,
    resolve_ga_exit_price,
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

    def test_live_style_entry_flag(self):
        params = {"GA_LIVE_STYLE_ENTRY": {"value": 1}}
        self.assertTrue(ga_live_style_entry_enabled(params))
        params["GA_LIVE_STYLE_ENTRY"]["value"] = 0
        self.assertFalse(ga_live_style_entry_enabled(params))

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

    def test_entry_slippage_long_pays_more(self):
        params = {"GA_CONSERVATIVE_ENTRY_SLIPPAGE": {"value": 1.0}}
        self.assertEqual(apply_conservative_entry_slippage(7500.0, 1, params), 7501.0)
        self.assertEqual(apply_conservative_entry_slippage(7500.0, -1, params), 7499.0)

    def test_channel_exit_uses_close_backup_and_slippage(self):
        params = {"GA_CONSERVATIVE_CHANNEL_SLIPPAGE": {"value": 0.25}}
        row = pd.Series({"close": 7535.75})
        # Long: trigger 7541.75, close lower -> fill at close - slip
        price = resolve_ga_channel_exit_price(7541.75, 1, row, params)
        self.assertEqual(price, 7535.5)
        # Short: trigger 7541.75, close lower -> fill at trigger + slip
        price = resolve_ga_channel_exit_price(7541.75, -1, row, params)
        self.assertEqual(price, 7542.0)

    def test_resolve_ga_exit_routes_channel(self):
        params = {"GA_CONSERVATIVE_CHANNEL_SLIPPAGE": {"value": 0.0}}
        row = pd.Series({"close": 7530.0})
        price = resolve_ga_exit_price(7540.0, 1, "Channel Exit", row, params)
        self.assertEqual(price, 7530.0)


if __name__ == "__main__":
    unittest.main()

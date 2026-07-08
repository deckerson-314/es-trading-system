"""Donchian chart masking tests."""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.reporting.chart_donchian import (
    apply_donchian_position_mask,
    position_windows_from_sources,
)


class TestDonchianMask(unittest.TestCase):
    def _sample_df(self):
        idx = pd.date_range("2026-06-01 10:00", periods=6, freq="14min")
        return pd.DataFrame(
            {
                "open": [100.0] * 6,
                "high": [101.0] * 6,
                "low": [99.0] * 6,
                "close": [100.5] * 6,
                "donchian_high": [102.0, 102.1, 102.2, 102.3, 102.4, 102.5],
                "donchian_low": [98.0, 98.1, 98.2, 98.3, 98.4, 98.5],
                "donchian_exit_high": [101.5, 101.6, 101.7, 101.8, 101.9, 102.0],
                "donchian_exit_low": [98.5, 98.6, 98.7, 98.8, 98.9, 99.0],
            },
            index=idx,
        )

    def test_flat_shows_entry_only(self):
        masked = apply_donchian_position_mask(self._sample_df(), [])
        self.assertTrue(masked["donchian_high"].notna().all())
        self.assertTrue(masked["donchian_exit_high"].isna().all())

    def test_in_trade_shows_exit_only(self):
        df = self._sample_df()
        entry = df.index[1]
        exit = df.index[4]
        masked = apply_donchian_position_mask(df, [(entry, exit)])
        self.assertTrue(np.isnan(masked.loc[entry, "donchian_high"]))
        self.assertFalse(np.isnan(masked.loc[entry, "donchian_exit_high"]))
        self.assertFalse(np.isnan(masked.loc[df.index[0], "donchian_high"]))
        self.assertTrue(np.isnan(masked.loc[df.index[0], "donchian_exit_high"]))
        self.assertFalse(np.isnan(masked.loc[df.index[-1], "donchian_high"]))
        self.assertTrue(np.isnan(masked.loc[df.index[-1], "donchian_exit_high"]))

    def test_open_position_window_to_chart_end(self):
        df = self._sample_df()
        entry = df.index[2]
        windows = position_windows_from_sources(
            open_positions=[{"entry_time": entry, "direction": 1}],
            chart_end=df.index[-1],
        )
        self.assertEqual(len(windows), 1)
        masked = apply_donchian_position_mask(df, windows)
        self.assertTrue(np.isnan(masked.loc[df.index[-1], "donchian_high"]))
        self.assertFalse(np.isnan(masked.loc[df.index[-1], "donchian_exit_low"]))


if __name__ == "__main__":
    unittest.main()

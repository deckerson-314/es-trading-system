"""Tests for IB subscribe HTF seed (VWAP / intraday parity)."""
import unittest

import pandas as pd

from core.monitoring import ib_htf_seed_at_subscribe, resample_data


class TestIbHtfSeed(unittest.TestCase):
    def test_includes_connect_day_pre_connect_bars(self):
        # 1-min bars across one day; connect mid-day should keep morning HTF for VWAP.
        idx = pd.date_range("2026-07-02 00:00", periods=600, freq="1min")
        df1 = pd.DataFrame(
            {
                "open": 7500.0,
                "high": 7510.0,
                "low": 7490.0,
                "close": 7505.0,
                "volume": 100.0,
            },
            index=idx,
        )
        connect = pd.Timestamp("2026-07-02 09:45:00")
        seed = ib_htf_seed_at_subscribe(df1, connect, timeframe=14, seed_n=600)
        self.assertFalse(seed.empty)
        same_day = seed[seed.index.date == connect.date()]
        self.assertFalse(same_day.empty)
        self.assertTrue((same_day.index <= connect).all())
        # Old bug stripped all same-day rows.
        self.assertGreater(len(same_day), 0)


if __name__ == "__main__":
    unittest.main()

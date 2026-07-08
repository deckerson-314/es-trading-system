"""Tests for live-parity HTF bar pipeline (resample + HTF-native detection)."""
import os
import tempfile
import unittest

import pandas as pd

from core.monitoring import (
    PAPER_WARMUP_MAX_BARS,
    extract_one_minute_ohlcv,
    is_htf_native_ohlcv,
    load_paper_1min_ohlcv,
    median_bar_spacing_minutes,
    parse_1min_bars_from_execution_log,
    prepare_paper_parity_ohlcv,
    prepare_strategy_ohlcv,
    resample_data,
)


def _make_1m(start, n, step_min=1):
    idx = pd.date_range(start, periods=n, freq=f"{step_min}min")
    return pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 10.0,
        },
        index=idx,
    )


class TestBarPipeline(unittest.TestCase):
    def test_median_spacing_1m(self):
        df = _make_1m("2026-06-22 06:00", 60)
        self.assertAlmostEqual(median_bar_spacing_minutes(df.index), 1.0, places=3)

    def test_median_spacing_14m_htf_log(self):
        idx = pd.date_range("2026-06-22 06:06", periods=10, freq="14min")
        df = _make_1m("2026-06-22 06:06", 1).reindex(idx, method="ffill")
        df.index = idx
        self.assertAlmostEqual(median_bar_spacing_minutes(df.index), 14.0, places=3)
        self.assertTrue(is_htf_native_ohlcv(df, 14))

    def test_prepare_skips_htf_native(self):
        idx = pd.date_range("2026-06-22 06:06", periods=5, freq="14min")
        htf = pd.DataFrame(
            {
                "open": [7562.0, 7564.0, 7560.0, 7562.0, 7568.0],
                "high": [7564.75, 7564.5, 7561.75, 7577.75, 7578.0],
                "low": [7561.5, 7558.75, 7557.0, 7560.0, 7567.5],
                "close": [7564.0, 7559.75, 7561.75, 7562.25, 7570.0],
                "volume": [2044.0, 100.0, 50.0, 200.0, 5000.0],
            },
            index=idx,
        )
        out, native = prepare_strategy_ohlcv(htf, 14)
        self.assertTrue(native)
        pd.testing.assert_frame_equal(out, htf)

    def test_prepare_resamples_1m_with_right_label(self):
        df1 = _make_1m("2026-06-22 06:00", 28)
        df1["high"] = df1.index.minute + 7560.0
        expected = resample_data(df1, 14)
        out, native = prepare_strategy_ohlcv(df1, 14)
        self.assertFalse(native)
        pd.testing.assert_frame_equal(out, expected)

    def test_prepare_assume_htf_native_flag(self):
        df1 = _make_1m("2026-06-22 06:00", 28)
        out, native = prepare_strategy_ohlcv(df1, 14, assume_htf_native=True)
        self.assertTrue(native)
        self.assertEqual(len(out), 28)

    def test_live_data_jun22_signal_bar_not_shifted(self):
        """HTF-native live_data row @ 06:20 must not become 06:18 after prepare."""
        ts = pd.Timestamp("2026-06-22 06:20:00")
        row = pd.DataFrame(
            {
                "open": [7562.0],
                "high": [7564.75],
                "low": [7561.5],
                "close": [7564.0],
                "volume": [2044.0],
            },
            index=[ts],
        )
        idx = pd.date_range("2026-06-22 06:06", periods=4, freq="14min")
        htf = row.reindex(idx).ffill().bfill()
        htf.loc[ts, ["open", "high", "low", "close", "volume"]] = [
            7562.0,
            7564.75,
            7561.5,
            7564.0,
            2044.0,
        ]
        out, native = prepare_strategy_ohlcv(htf, 14)
        self.assertTrue(native)
        self.assertIn(ts, out.index)
        self.assertEqual(out.loc[ts, "close"], 7564.0)

    def test_prepare_paper_parity_truncates_warmup_window(self):
        df1 = _make_1m("2026-06-22 06:00", 200)
        class _S:
            timeframe = 14
            maintenance_buffer_minutes = 0
            daily_maintenance_end_str = "17:30"
            min_bars_required = 10
            enable_sma_filter = False
            sma_period = 0
            lookback_buy = 5
            lookback_sell = 5

        out = prepare_paper_parity_ohlcv(
            df1, _S(), end_time=pd.Timestamp("2026-06-22 09:00"), max_bars=60
        )
        used = df1[df1.index <= "2026-06-22 09:00"].iloc[-60:]
        self.assertEqual(len(used), 60)
        self.assertGreater(len(out), 0)

    def test_overlay_replaces_session_resample_bars(self):
        """Session dates must use live HTF grid only — no phantom resampled bars."""
        from core.monitoring import overlay_live_htf_log
        import tempfile
        import os

        class _S:
            timeframe = 14

        df1 = _make_1m("2026-06-30 06:00", 120)
        resampled = prepare_paper_parity_ohlcv(df1, _S(), end_time=pd.Timestamp("2026-06-30 12:00"))
        live_idx = pd.DatetimeIndex(
            ["2026-06-30 08:54:00", "2026-06-30 09:08:00", "2026-06-30 09:22:00"]
        )
        live_htf = pd.DataFrame(
            {
                "open": [7500.0, 7510.0, 7520.0],
                "high": [7510.0, 7520.0, 7530.0],
                "low": [7490.0, 7500.0, 7510.0],
                "close": [7505.0, 7515.0, 7525.0],
                "volume": [100.0, 100.0, 100.0],
            },
            index=live_idx,
        )
        orig_session_n = len(resampled[resampled.index.date == pd.Timestamp("2026-06-30").date()])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "live_data.csv")
            live_htf.to_csv(path)
            out = overlay_live_htf_log(
                resampled,
                path,
                _S(),
                {pd.Timestamp("2026-06-30").date()},
            )
        session = out[out.index.date == pd.Timestamp("2026-06-30").date()]
        self.assertEqual(len(session), len(live_idx))
        self.assertLess(len(session), orig_session_n)
        self.assertNotIn(pd.Timestamp("2026-06-30 12:56:00"), session.index)

    def test_active_ranges_multi_day_disconnect(self):
        from core.monitoring import merge_timestamp_ranges, parse_paper_bot_active_ranges
        import tempfile
        import os

        log = """\
2026-07-01 08:00:00,000 INFO Subscribed to market data (100 bars)
2026-07-01 10:00:00,000 INFO Disconnecting
2026-07-01 12:00:00,000 INFO Subscribed to market data (200 bars)
2026-07-02 09:00:00,000 INFO Disconnecting
"""
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False, encoding="utf-8") as fh:
            fh.write(log)
            path = fh.name
        try:
            ranges = parse_paper_bot_active_ranges(
                path,
                dates={pd.Timestamp("2026-07-01").date(), pd.Timestamp("2026-07-02").date()},
                end_time=pd.Timestamp("2026-07-02 23:59"),
            )
        finally:
            os.remove(path)
        self.assertEqual(len(ranges), 2)
        self.assertEqual(ranges[0][0], pd.Timestamp("2026-07-01 08:00:00"))
        self.assertEqual(ranges[0][1], pd.Timestamp("2026-07-01 10:00:00"))
        self.assertEqual(ranges[1][0], pd.Timestamp("2026-07-01 12:00:00"))
        merged = merge_timestamp_ranges([
            (pd.Timestamp("2026-07-01 08:00"), pd.Timestamp("2026-07-01 10:00")),
            (pd.Timestamp("2026-07-01 09:00"), pd.Timestamp("2026-07-01 11:00")),
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0][1], pd.Timestamp("2026-07-01 11:00"))

    def test_merge_short_active_gaps(self):
        from core.monitoring import merge_short_active_gaps

        merged = merge_short_active_gaps([
            (pd.Timestamp("2026-07-01 00:00"), pd.Timestamp("2026-07-01 03:00:06")),
            (pd.Timestamp("2026-07-01 03:00:24"), pd.Timestamp("2026-07-01 23:59")),
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0][0], pd.Timestamp("2026-07-01 00:00"))
        self.assertEqual(merged[0][1], pd.Timestamp("2026-07-01 23:59"))

    def test_extract_one_minute_drops_htf_rows(self):
        one = _make_1m("2026-06-22 06:00", 30)
        htf = resample_data(one, 14)
        mixed = pd.concat([one, htf]).sort_index()
        kept = extract_one_minute_ohlcv(mixed)
        self.assertAlmostEqual(median_bar_spacing_minutes(kept.index), 1.0, places=2)
        self.assertGreater(len(kept), len(one) * 0.8)

    def test_parse_htf_bar_label_rolls_back_after_midnight(self):
        from core.paper_backtest import parse_htf_bar_events

        line = (
            "2026-07-03 00:00:07,301 INFO [14-min] 23:48:00 | "
            "O: 7552.75 H: 7553.25 L: 7548.00 C: 7551.50 | Vol: 844"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as fh:
            fh.write(line + "\n")
            path = fh.name
        try:
            events = parse_htf_bar_events(path, timeframe=14, include_ohlc=True)
        finally:
            os.unlink(path)
        self.assertEqual(len(events), 1)
        bar_label, wall_time, ohlc = events[0]
        self.assertEqual(bar_label, pd.Timestamp("2026-07-02 23:48:00"))
        self.assertEqual(wall_time, pd.Timestamp("2026-07-03 00:00:07"))
        self.assertAlmostEqual(ohlc["low"], 7548.0)


if __name__ == "__main__":
    unittest.main()

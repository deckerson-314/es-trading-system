"""Tests for live maintenance-window helpers used by main.py data-stall backoff."""
import pandas as pd
import pytest

from strategies.bollinger.filters import is_in_maintenance_window_now, is_strategy_in_maintenance_window


def test_is_in_maintenance_window_now_disabled():
    assert not is_in_maintenance_window_now(
        False, '16:50', '18:00', 4, '17:00', 6, '18:00', 5,
        now=pd.Timestamp('2026-05-19 17:00:00', tz='US/Eastern'),
    )


def test_is_in_maintenance_window_now_matches_apply_filter():
  ts = pd.Timestamp('2026-05-19 17:00:00', tz='US/Eastern')
  assert is_in_maintenance_window_now(
      True, '16:50', '18:00', 4, '17:00', 6, '18:00', 5, now=ts,
  )
  assert not is_in_maintenance_window_now(
      True, '16:50', '18:00', 4, '17:00', 6, '18:00', 5,
      now=pd.Timestamp('2026-05-19 12:00:00', tz='US/Eastern'),
  )


class _MaintStrategy:
    enable_maintenance_filter = True
    daily_maintenance_start_str = '16:50'
    daily_maintenance_end_str = '18:00'
    weekend_maintenance_start_day = 4
    weekend_maintenance_start_time_str = '17:00'
    weekend_maintenance_end_day = 6
    weekend_maintenance_end_time_str = '18:00'
    maintenance_buffer_minutes = 5


def test_is_strategy_in_maintenance_window_wrapper():
    s = _MaintStrategy()
    assert is_strategy_in_maintenance_window(
        s, pd.Timestamp('2026-05-19 17:00:00', tz='US/Eastern'),
    )
    assert not is_strategy_in_maintenance_window(
        s, pd.Timestamp('2026-05-19 10:00:00', tz='US/Eastern'),
    )

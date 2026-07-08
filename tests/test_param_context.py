"""GA parameter context helpers (trailing, RSI, ADX/SMA/VOL, RTH, maintenance dead dimensions)."""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import optimize as o


def test_apply_rsi_param_context_drops_when_disabled():
    d = {
        'Enable RSI Filter': 0,
        'RSI Period': 99,
        'RSI Max Buy Threshold': 12.0,
        'RSI Min Sell Threshold': 88.0,
    }
    pd = {'Enable RSI Filter': {'value': 1}}
    o.apply_rsi_param_context(d, pd)
    assert 'RSI Period' not in d
    assert 'RSI Max Buy Threshold' not in d
    assert d.get('Enable RSI Filter') == 0


def test_apply_rsi_param_context_keeps_when_enabled():
    d = {
        'Enable RSI Filter': 1,
        'RSI Period': 14,
        'RSI Max Buy Threshold': 70.0,
        'RSI Min Sell Threshold': 30.0,
    }
    pd = {'Enable RSI Filter': {'value': 0}}
    o.apply_rsi_param_context(d, pd)
    assert d['RSI Period'] == 14


def test_apply_trailing_and_rsi_independent():
    d = {
        'Enable Trailing Stop': 0,
        'Trailing Delay (minutes)': 120,
        'Enable RSI Filter': 0,
        'RSI Period': 5,
    }
    pd = {
        'Enable Trailing Stop': {'value': 1},
        'Enable RSI Filter': {'value': 1},
    }
    o.apply_trailing_param_context(d, pd)
    o.apply_rsi_param_context(d, pd)
    assert 'Trailing Delay (minutes)' not in d
    assert 'RSI Period' not in d


def test_describe_effective_rsi_band_off():
    d = {'Enable RSI Filter': 0, 'RSI Period': 14}
    pd = {'Enable RSI Filter': {'value': 1}}
    assert o.describe_effective_rsi_band(d, pd) == 'filter off (RSI not applied to entries)'


def test_describe_effective_rsi_band_on():
    d = {
        'Enable RSI Filter': 1,
        'RSI Period': 10,
        'RSI Max Buy Threshold': 65.0,
        'RSI Min Sell Threshold': 35.5,
    }
    pd = {'RSI Max Buy Threshold': {'type': 'float', 'min': 1, 'max': 99}}
    assert o.describe_effective_rsi_band(d, pd) == (
        'on (Trend gates): period=10, long if RSI<65.0, short if RSI>35.5'
    )


def test_describe_effective_rsi_band_bollinger():
    d = {
        'Enable RSI Filter': 1,
        'RSI Period': 14,
        'RSI Overbought': 72,
        'RSI Oversold': 28,
    }
    pd = {'RSI Overbought': {'type': 'int', 'min': 50, 'max': 90}}
    assert o.describe_effective_rsi_band(d, pd) == (
        'on (mean reversion): period=14, long if RSI<28, short if RSI>72'
    )


def test_apply_adx_param_context_drops_when_disabled():
    d = {'Enable ADX Filter': 0, 'ADX Period': 99, 'Min ADX Threshold': 5.0}
    pd = {'Enable ADX Filter': {'value': 1}}
    o.apply_adx_param_context(d, pd)
    assert 'ADX Period' not in d
    assert 'Min ADX Threshold' not in d


def test_apply_sma_and_volume_context():
    d = {
        'Enable SMA Filter': 0,
        'SMA Period': 12,
        'Enable Volume Filter': 0,
        'Volume MA Length': 5,
        'Min Volume Multiplier': 2.0,
    }
    pd = {'Enable SMA Filter': {'value': 1}, 'Enable Volume Filter': {'value': 1}}
    o.apply_sma_param_context(d, pd)
    o.apply_volume_param_context(d, pd)
    assert 'SMA Period' not in d
    assert 'Volume MA Length' not in d


def test_apply_rth_param_context_drops_when_disabled():
    d = {'Enable RTH Filter': 0, 'RTH Exit Buffer (minutes)': 55}
    pd = {'Enable RTH Filter': {'value': 1}}
    o.apply_rth_param_context(d, pd)
    assert 'RTH Exit Buffer (minutes)' not in d
    assert d.get('Enable RTH Filter') == 0


def test_apply_maintenance_param_context_drops_when_disabled():
    d = {'Enable Maintenance Filter': False, 'Maintenance Buffer Minutes': 99}
    pd = {'Enable Maintenance Filter': {'value': True}}
    o.apply_maintenance_param_context(d, pd)
    assert 'Maintenance Buffer Minutes' not in d
    assert d.get('Enable Maintenance Filter') is False


def test_build_solution_export_params_preserves_genome_when_trailing_off():
  """Inactive trailing child genes must export raw genome slots, not template fill."""
  pd = {
      'Enable Trailing Stop': {'type': 'int', 'min': 0, 'max': 1, 'value': 1},
      'Trailing Delay (bars)': {'type': 'int', 'min': 3, 'max': 50, 'value': 28},
      'ATR Multiplier for Trailing Stop': {'type': 'float', 'min': 0.5, 'max': 8, 'value': 3.7652},
      'ATR Length for Trailing Stop': {'type': 'int', 'min': 1, 'max': 100, 'value': 1},
      'Timeframe (minutes)': {'type': 'int', 'min': 1, 'max': 20, 'value': 14},
  }
  import pandas as pdi
  param_df = pdi.DataFrame([
      {'Name': k, 'Value': v['value'], 'Min': v['min'], 'Max': v['max'], 'Type': v['type']}
      for k, v in pd.items()
  ])
  raw = {
      'Enable Trailing Stop': 0,
      'Trailing Delay (bars)': 17,
      'ATR Multiplier for Trailing Stop': 2.25,
      'ATR Length for Trailing Stop': 22,
      'Timeframe (minutes)': 14,
  }
  keys = list(raw.keys())
  export, effective = o.build_solution_export_params(raw, pd, param_df, keys)
  assert export['Enable Trailing Stop'] == 0
  assert export['Trailing Delay (bars)'] == 17
  assert export['ATR Multiplier for Trailing Stop'] == 2.25
  assert export['ATR Length for Trailing Stop'] == 22
  assert 'Trailing Delay (bars)' not in effective
  assert effective.get('Enable Trailing Stop') == 0


def test_param_context_groups_cover_trailing_children():
    children = set(o.context_child_param_keys())
    for key in o._TRAILING_CONTEXT_KEYS:
        assert key in children


def test_apply_rth_and_maintenance_independent():
    d = {
        'Enable RTH Filter': 0,
        'RTH Exit Buffer (minutes)': 30,
        'Enable Maintenance Filter': 0,
        'Maintenance Buffer Minutes': 40,
    }
    pd = {
        'Enable RTH Filter': {'value': 1},
        'Enable Maintenance Filter': {'value': 1},
    }
    o.apply_rth_param_context(d, pd)
    o.apply_maintenance_param_context(d, pd)
    assert 'RTH Exit Buffer (minutes)' not in d
    assert 'Maintenance Buffer Minutes' not in d


def test_resolve_lookback_bars_from_minutes():
    p = {'Buy Lookback (minutes)': 110, 'Timeframe (minutes)': 11, 'Buy Lookback': 999}
    assert o.resolve_buy_lookback_bars(p) == 10
    p2 = {'Timeframe (minutes)': 5, 'Buy Lookback': 40}
    assert o.resolve_buy_lookback_bars(p2) == 40


def test_trailing_delay_active_gene_prefers_minutes_when_both_optimizable():
    from strategies.trend.parameters import (
        TRAILING_DELAY_BARS,
        TRAILING_DELAY_MINUTES,
        active_trailing_delay_gene_key,
        exclude_trailing_delay_from_param_ranges,
    )

    param_dict = {
        TRAILING_DELAY_MINUTES: {'type': 'int', 'min': 0, 'max': 300, 'value': 13},
        TRAILING_DELAY_BARS: {'type': 'int', 'min': 3, 'max': 50, 'value': 1},
    }
    assert active_trailing_delay_gene_key(param_dict) == TRAILING_DELAY_MINUTES
    assert exclude_trailing_delay_from_param_ranges(TRAILING_DELAY_BARS, param_dict)
    assert not exclude_trailing_delay_from_param_ranges(TRAILING_DELAY_MINUTES, param_dict)


def test_trailing_delay_bars_gene_when_minutes_fixed():
    from strategies.trend.parameters import (
        TRAILING_DELAY_BARS,
        TRAILING_DELAY_MINUTES,
        active_trailing_delay_gene_key,
        resolve_trailing_delay_bars,
    )

    param_dict = {
        TRAILING_DELAY_MINUTES: {'type': 'int', 'min': 0, 'max': 0, 'value': 13},
        TRAILING_DELAY_BARS: {'type': 'int', 'min': 3, 'max': 50, 'value': 1},
    }
    assert active_trailing_delay_gene_key(param_dict) == TRAILING_DELAY_BARS
    params = {'Timeframe (minutes)': 12, TRAILING_DELAY_BARS: 5}
    assert resolve_trailing_delay_bars(params, param_dict, 12) == 5


def test_trailing_delay_bars_gene_ignores_template_minutes():
    from strategies.trend.parameters import (
        TRAILING_DELAY_BARS,
        TRAILING_DELAY_MINUTES,
        resolve_trailing_delay_bars,
    )

    param_dict = {
        TRAILING_DELAY_MINUTES: {'type': 'int', 'min': 0, 'max': 0, 'value': 13},
        TRAILING_DELAY_BARS: {'type': 'int', 'min': 3, 'max': 50, 'value': 1},
    }
    params = {
        'Timeframe (minutes)': 12,
        TRAILING_DELAY_BARS: 5,
        TRAILING_DELAY_MINUTES: 13,
    }
    assert resolve_trailing_delay_bars(params, param_dict, 12) == 5


def test_trailing_delay_minutes_gene_converts_to_bars():
    from strategies.trend.parameters import resolve_trailing_delay_bars

    param_dict = {
        'Trailing Delay (minutes)': {'type': 'int', 'min': 0, 'max': 300, 'value': 13},
        'Trailing Delay (bars)': {'type': 'int', 'min': 3, 'max': 50, 'value': 1},
    }
    params = {'Timeframe (minutes)': 13, 'Trailing Delay (minutes)': 26, 'Trailing Delay (bars)': 99}
    assert resolve_trailing_delay_bars(params, param_dict, 13) == 2


def test_sync_trailing_delay_params_bars_gene():
    from strategies.trend.parameters import sync_trailing_delay_params

    param_dict = {
        'Trailing Delay (minutes)': {'type': 'int', 'min': 0, 'max': 0, 'value': 13},
        'Trailing Delay (bars)': {'type': 'int', 'min': 3, 'max': 50, 'value': 1},
    }
    params = {'Timeframe (minutes)': 10, 'Trailing Delay (bars)': 4}
    sync_trailing_delay_params(params, param_dict, 10)
    assert params['Trailing Delay (bars)'] == 4
    assert params['Trailing Delay (minutes)'] == 40


def test_resolve_channel_exit_lookbacks_fallback_to_entry():
    from strategies.trend.parameters import (
        resolve_channel_exit_buy_lookback,
        resolve_channel_exit_sell_lookback,
        resolve_channel_exit_atr_offset,
    )

    assert resolve_channel_exit_sell_lookback({}, None, 7) == 7
    assert resolve_channel_exit_buy_lookback({}, None, 9) == 9
    assert resolve_channel_exit_atr_offset({}, None) == 0.0


def test_resolve_channel_exit_lookbacks_from_template():
    from strategies.trend.parameters import (
        resolve_channel_exit_buy_lookback,
        resolve_channel_exit_sell_lookback,
        resolve_channel_exit_atr_offset,
    )

    param_dict = {
        'Channel Exit Sell Lookback (bars)': {'type': 'int', 'min': 3, 'max': 50, 'value': 12},
        'Channel Exit Buy Lookback (bars)': {'type': 'int', 'min': 3, 'max': 50, 'value': 15},
        'Channel Exit ATR Offset': {'type': 'float', 'min': 0, 'max': 2, 'value': 0.5},
    }
    assert resolve_channel_exit_sell_lookback({}, param_dict, 7) == 12
    assert resolve_channel_exit_buy_lookback({}, param_dict, 9) == 15
    assert resolve_channel_exit_atr_offset({}, param_dict) == 0.5


def test_apply_channel_exit_lookbacks_mirrors_entry_when_absent():
    param_dict = {
        'Buy Lookback (minutes)': {'type': 'float', 'min': 10, 'max': 5000, 'value': 140},
        'Sell Lookback (minutes)': {'type': 'float', 'min': 10, 'max': 5000, 'value': 98},
        'Timeframe (minutes)': {'type': 'int', 'min': 1, 'max': 20, 'value': 14},
    }
    params = {'Timeframe (minutes)': 14}
    o.apply_lookback_bars_from_minutes(params, param_dict)
    assert params['Buy Lookback'] == 10
    assert params['Sell Lookback'] == 7
    assert params['Channel Exit Buy Lookback (bars)'] == 10
    assert params['Channel Exit Sell Lookback (bars)'] == 7

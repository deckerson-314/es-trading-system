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

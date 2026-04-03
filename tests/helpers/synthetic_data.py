"""
Synthetic Data Generators for Strategy Functional Testing
=========================================================
Provides factory functions to create artificial OHLCV DataFrames
for use in the Test Bench (STRATEGY_FUNCTIONAL_TEST_PLAN.md).

All generators return pandas DataFrames with a DatetimeIndex and
columns: open, high, low, close, volume.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from strategies.trend.strategy import TrendStrategy
from strategies.trend.parameters import get_param_value


# ---------------------------------------------------------------------------
# Default Parameters
# ---------------------------------------------------------------------------

_BASE_PARAMS = {
    # Config
    'Enable Long Trades':       {'value': True,  'type': 'bool'},
    'Enable Short Trades':      {'value': True,  'type': 'bool'},
    'Max Open Trades':          {'value': 1,     'type': 'int'},
    'Timeframe (minutes)':      {'value': 1,     'type': 'int'},
    'Transaction Cost (Per Trade)': {'value': 15, 'type': 'float'},
    # Entry
    'Buy Lookback':             {'value': 5,     'type': 'int'},
    'Sell Lookback':            {'value': 5,     'type': 'int'},
    # Filters — all OFF by default
    'Enable ADX Filter':        {'value': 0,     'type': 'int'},
    'ADX Period':               {'value': 14,    'type': 'int'},
    'Min ADX Threshold':        {'value': 20.0,  'type': 'float'},
    'ATR Filter Period':        {'value': 3,     'type': 'int'},
    'Min ATR (Points)':         {'value': 0.0,   'type': 'float'},
    'Enable SMA Filter':        {'value': False, 'type': 'bool'},
    'SMA Period':               {'value': 20,    'type': 'int'},
    'Enable Volume Filter':     {'value': False, 'type': 'bool'},
    'Volume MA Length':         {'value': 5,     'type': 'int'},
    'Min Volume Multiplier':    {'value': 1.5,   'type': 'float'},
    'Enable RSI Filter':        {'value': 0,     'type': 'int'},
    'RSI Period':               {'value': 14,    'type': 'int'},
    'RSI Max Buy Threshold':    {'value': 70.0,  'type': 'float'},
    'RSI Min Sell Threshold':   {'value': 30.0,  'type': 'float'},
    'Enable VWAP Filter':       {'value': 0,     'type': 'int'},
    # Time filters — OFF for synthetic tests
    'Enable RTH Filter':        {'value': 0,     'type': 'int'},
    'RTH Start (HH:MM)':       {'value': '09:30','type': 'str'},
    'RTH End (HH:MM)':         {'value': '16:00','type': 'str'},
    'RTH Exit Buffer (minutes)':{'value': 0,     'type': 'int'},
    'Enable Maintenance Filter':{'value': False, 'type': 'bool'},
    'Daily Maintenance Start (HH:MM)': {'value': '17:00', 'type': 'str'},
    'Daily Maintenance End (HH:MM)':   {'value': '17:30', 'type': 'str'},
    'Weekend Maintenance Start Day':   {'value': 4, 'type': 'int'},
    'Weekend Maintenance Start Time (HH:MM)': {'value': '17:00', 'type': 'str'},
    'Weekend Maintenance End Day':     {'value': 6, 'type': 'int'},
    'Weekend Maintenance End Time (HH:MM)':   {'value': '18:00', 'type': 'str'},
    'Maintenance Buffer Minutes':      {'value': 5, 'type': 'int'},
    # Exit
    'Initial Stop Loss (%)':    {'value': 2.0,   'type': 'float'},
    'Enable Trailing Stop':     {'value': 0,     'type': 'int'},
    'ATR Length for Trailing Stop': {'value': 14, 'type': 'int'},
    'ATR Multiplier for Trailing Stop': {'value': 3.0, 'type': 'float'},
    'Trailing Delay (bars)':    {'value': 5,     'type': 'int'},
    'Take Profit ATR Multiplier': {'value': 0.0, 'type': 'float'},
}

_BASE_START = datetime(2025, 6, 1, 10, 0)  # Eastern, during RTH


# ---------------------------------------------------------------------------
# Helper: Build a TrendStrategy from overrides
# ---------------------------------------------------------------------------

def make_strategy(**overrides):
    """
    Create a TrendStrategy with base defaults + any overrides.
    
    Usage:
        s = make_strategy(**{'Enable ADX Filter': 1, 'Min ADX Threshold': 20})
    """
    params = {k: dict(v) for k, v in _BASE_PARAMS.items()}  # deep copy
    for key, val in overrides.items():
        if key in params:
            params[key]['value'] = val
        else:
            # Infer type from value
            typ = 'float' if isinstance(val, float) else 'int' if isinstance(val, int) else 'str'
            params[key] = {'value': val, 'type': typ}
    return TrendStrategy(params)


# ---------------------------------------------------------------------------
# OHLCV Generators
# ---------------------------------------------------------------------------

def make_ohlcv(n, base_price=100.0, trend=0.0, volatility=1.0, volume=1000,
               start=None):
    """
    Generate n bars of synthetic OHLCV data.

    Args:
        n:          Number of bars.
        base_price: Starting close price.
        trend:      Per-bar price drift (positive = uptrend).
        volatility: Half-range of high/low around the close.
        volume:     Constant volume per bar.
        start:      Start datetime (default: 2025-06-01 10:00 ET).

    Returns:
        pd.DataFrame with DatetimeIndex and columns [open, high, low, close, volume].
    """
    if start is None:
        start = _BASE_START

    times = [start + timedelta(minutes=i) for i in range(n)]
    closes = [base_price + trend * i for i in range(n)]

    data = {
        'open':   [c - trend * 0.5 if trend != 0 else c for c in closes],
        'high':   [c + volatility for c in closes],
        'low':    [c - volatility for c in closes],
        'close':  closes,
        'volume': [volume] * n,
    }
    return pd.DataFrame(data, index=pd.DatetimeIndex(times))


def make_breakout_scenario(lookback=5, warmup_extra=30, breakout_magnitude=5.0,
                           base_price=100.0, volatility=1.0, volume=1000):
    """
    Generate OHLCV data with a clean Donchian breakout.

    Structure:
      - (lookback + warmup_extra) flat bars at base_price  (warm-up / indicator seeding)
      - 1 bar that breaks above the rolling high           (breakout bar)
      - 3 additional bars that stay above the channel       (post-breakout)

    warmup_extra should be >= max indicator period (e.g. ATR=14, ADX=14*2=28)
    to ensure rows survive calculate_indicators() dropna().

    Returns:
        (df, breakout_idx): DataFrame and the integer index of the breakout bar.
    """
    n_flat = lookback + warmup_extra
    n_total = n_flat + 1 + 3  # flat + breakout + post

    times = [_BASE_START + timedelta(minutes=i) for i in range(n_total)]

    opens, highs, lows, closes, volumes = [], [], [], [], []

    # Warm-up bars: sine-wave oscillation around base_price.
    # This creates consistent movement for ADX/RSI (unlike flat bars which produce ADX=0/NaN)
    # but stays strictly bounded so no Donchian crossover signals fire during warm-up.
    # Amplitude of 0.3 keeps prices within [base_price - 0.3, base_price + 0.3].
    for i in range(n_flat):
        osc = 0.3 * np.sin(2 * np.pi * i / 7)  # period=7 bars
        c = base_price + osc
        opens.append(c - 0.02)
        highs.append(c + volatility)
        lows.append(c - volatility)
        closes.append(c)
        volumes.append(volume)

    # Donchian High = max high over the last `lookback` bars of the warm-up
    donchian_high = max(highs[-lookback:])

    # Breakout bar: high exceeds the donchian_high
    breakout_close = donchian_high + breakout_magnitude
    opens.append(base_price + 0.5)
    highs.append(breakout_close + volatility)
    lows.append(base_price)
    closes.append(breakout_close)
    volumes.append(volume)

    # Post-breakout bars: stay above channel (no re-trigger)
    for i in range(3):
        c = breakout_close + (i + 1) * 0.5
        opens.append(c - 0.3)
        highs.append(c + volatility)
        lows.append(c - volatility)
        closes.append(c)
        volumes.append(volume)

    df = pd.DataFrame({
        'open': opens, 'high': highs, 'low': lows,
        'close': closes, 'volume': volumes
    }, index=pd.DatetimeIndex(times))

    return df, n_flat  # breakout_idx is the first bar after flat period


def make_trending_scenario(entry_price=100.0, up_bars=8, dip_bars=4,
                           resume_bars=5, up_step=2.0, dip_step=1.0,
                           volatility=0.5, volume=1000, warmup_bars=30):
    """
    Generate a controlled price path for trailing stop tests.

    Structure:
      Phase 0: Warm-up flat bars at entry_price  (for indicator seeding)
      Phase 1: Uptrend       (entry_price → entry_price + up_bars*up_step)
      Phase 2: Pullback dip  (price drops by dip_step per bar)
      Phase 3: Resume up     (price rises again)

    Returns:
        pd.DataFrame with DatetimeIndex.
    """
    n_total = warmup_bars + up_bars + dip_bars + resume_bars
    times = [_BASE_START + timedelta(minutes=i) for i in range(n_total)]

    closes = []
    # Phase 0: Warm-up (flat)
    for i in range(warmup_bars):
        closes.append(entry_price + np.random.uniform(-0.2, 0.2))
    # Phase 1: Up
    for i in range(up_bars):
        closes.append(entry_price + (i + 1) * up_step)
    peak = closes[-1]
    # Phase 2: Dip
    for i in range(dip_bars):
        closes.append(peak - (i + 1) * dip_step)
    dip_bottom = closes[-1]
    # Phase 3: Resume
    for i in range(resume_bars):
        closes.append(dip_bottom + (i + 1) * up_step)

    data = {
        'open':   [c - 0.3 for c in closes],
        'high':   [c + volatility for c in closes],
        'low':    [c - volatility for c in closes],
        'close':  closes,
        'volume': [volume] * n_total,
    }
    return pd.DataFrame(data, index=pd.DatetimeIndex(times))

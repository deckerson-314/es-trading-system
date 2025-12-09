"""
Bollinger Band Trading Strategy - Shared Module
================================================
This module provides a unified implementation of the Bollinger Band trading strategy
for use across backtesting, optimization, and live trading.

Usage:
    from bollinger_strategy import BollingerBandStrategy, BollingerBandStrategyV4, load_params
    
    params = load_params('path/to/parameters.csv')
    strategy = BollingerBandStrategyV4(params)
    
    # Calculate indicators
    df = strategy.calculate_indicators(df)
    df = strategy.apply_filters(df)
    
    # Vectorized Signals (V4)
    entry_long, entry_short = strategy.calculate_entry_signals(df)
    
    # Check entries/exits (Legacy/Live)
    enter_long, enter_short = strategy.check_entry(row, df)
    should_exit, reason, price = strategy.check_exit(position, row, df)
"""

from .strategy import BollingerBandStrategy
from .strategy_v4 import BollingerBandStrategyV4
from .parameters import load_params

__all__ = ['BollingerBandStrategy', 'BollingerBandStrategyV4', 'load_params']
__version__ = '4.0.0'

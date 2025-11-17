"""
Bollinger Band Trading Strategy - Shared Module
================================================
This module provides a unified implementation of the Bollinger Band trading strategy
for use across backtesting, optimization, and live trading.

Usage:
    from bollinger_strategy import BollingerBandStrategy, load_params
    
    params = load_params('path/to/parameters.csv')
    strategy = BollingerBandStrategy(params)
    
    # Calculate indicators
    df = strategy.calculate_indicators(df)
    df = strategy.apply_filters(df)
    
    # Check entries/exits
    enter_long, enter_short = strategy.check_entry(row, df)
    should_exit, reason, price = strategy.check_exit(position, row, df)
"""

from .strategy import BollingerBandStrategy
from .parameters import load_params

__all__ = ['BollingerBandStrategy', 'load_params']
__version__ = '1.0.0'


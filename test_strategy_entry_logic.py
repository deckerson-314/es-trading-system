"""
Test the strategy entry logic to see why trades are generated when all entry methods are disabled.
"""

import pandas as pd
from bollinger_strategy.strategy import BollingerBandStrategy
from bollinger_strategy.parameters import load_params

# Load parameters
param_dict, _ = load_params('Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv', return_dataframe=True)

# Create strategy
strategy = BollingerBandStrategy(param_dict)

# Check initial values
print("="*80)
print("INITIAL STRATEGY VALUES (from param_dict)")
print("="*80)
print(f"enable_long: {strategy.enable_long}")
print(f"enable_short: {strategy.enable_short}")
print(f"long_wick_touch: {strategy.long_wick_touch}")
print(f"long_body_zone: {strategy.long_body_zone}")
print(f"short_wick_touch: {strategy.short_wick_touch}")
print(f"short_body_zone: {strategy.short_body_zone}")

# Update with all entry methods disabled
print("\n" + "="*80)
print("UPDATING WITH ALL ENTRY METHODS DISABLED")
print("="*80)
params = {
    'Long Entry on Body in Zone': 0,
    'Long Entry on Wick Touch': 0,
    'Short Entry on Body in Zone': 0,
    'Short Entry on Wick Touch': 0,
    'Enable Long Trades': True,  # Still enabled
    'Enable Short Trades': True,  # Still enabled
}

strategy.update_optimizable_params(params)

print(f"\nAfter update_optimizable_params:")
print(f"enable_long: {strategy.enable_long}")
print(f"enable_short: {strategy.enable_short}")
print(f"long_wick_touch: {strategy.long_wick_touch}")
print(f"long_body_zone: {strategy.long_body_zone}")
print(f"short_wick_touch: {strategy.short_wick_touch}")
print(f"short_body_zone: {strategy.short_body_zone}")

# Check if update_optimizable_params handles entry methods
print("\n" + "="*80)
print("CHECKING update_optimizable_params FUNCTION")
print("="*80)
import inspect
source = inspect.getsource(strategy.update_optimizable_params)
print(source)

print("\n" + "="*80)
print("CONCLUSION")
print("="*80)
print("If update_optimizable_params doesn't update entry method parameters,")
print("then the strategy will use the default values from param_dict,")
print("which might allow trades even when we think all entry methods are disabled.")


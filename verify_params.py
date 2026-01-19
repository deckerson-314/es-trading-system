
import sys
import os
import pandas as pd

# Add project root
sys.path.append(r'c:\Trading')
from bollinger_strategy.parameters import load_params
from bollinger_strategy.strategy_v4 import BollingerBandStrategyV4

params_path = r"c:\Trading\Bollinger\parameters\live_params.csv"

try:
    print(f"Loading params from {params_path}...")
    params = load_params(params_path)
    
    print("\n--- Params Loaded (Raw) ---")
    keys_to_check = ['Min ATR Filter (Points)', 'Max ATR Filter (Points)', 'ATR Length for Filter', 'Volume MA Length']
    for k in keys_to_check:
        if k in params:
            print(f"{k}: {params[k]}")
        else:
            print(f"{k}: NOT FOUND")
            
    print("\n--- Strategy Defaults vs Loaded ---")
    strategy = BollingerBandStrategyV4(params)
    
    # Check attributes
    print(f"Strategy.min_atr_points_opt: {getattr(strategy, 'min_atr_points_opt', 'missing')}")
    print(f"Strategy.min_atr_points: {strategy.min_atr_points}")
    print(f"Strategy.max_atr_points_opt: {getattr(strategy, 'max_atr_points_opt', 'missing')}")
    
    # Check effective usage
    min_to_use = getattr(strategy, 'min_atr_points_opt', strategy.min_atr_points)
    print(f"EFFECTIVE MIN ATR USE: {min_to_use}")

except Exception as e:
    print(f"Error: {e}")


import pandas as pd
import numpy as np
import sys
import os

# Add project root
sys.path.append(r'c:\Trading')
from bollinger_strategy.strategy_v4 import BollingerBandStrategyV4
from bollinger_strategy.parameters import load_params
from bollinger_strategy.filters import apply_atr_filter

# 1. Load Params
params_path = r"c:\Trading\Bollinger\parameters\live_params.csv"
print(f"Loading params from {params_path}...")
params = load_params(params_path)

strategy = BollingerBandStrategyV4(params)
min_atr = getattr(strategy, 'min_atr_points_opt', strategy.min_atr_points)
max_atr = getattr(strategy, 'max_atr_points_opt', 4.0)

print(f"Strategy Params -> Min: {min_atr}, Max: {max_atr}")

# 2. Create Synthetic Data
# Need ATR(14) = 1.61 (Valid)
# ATR is smoothed TR.
# We can just inject 'atr_filter_values' directly to test the filter logic.
df = pd.DataFrame({
    'close': [100.0] * 10,
    'atr_filter_values': [1.2, 1.4, 1.48, 1.54, 1.61, 1.73, 1.84, 4.0, 4.02, 4.16]
}, index=pd.date_range('2025-01-01', periods=10))

# 3. Apply Filter directly
print("\n--- Applying atr_filter logic ---")
try:
    df_filtered = apply_atr_filter(df, max_atr_points=max_atr, min_atr_points=min_atr)
    
    # Print Results
    for idx, row in df_filtered.iterrows():
        val = row['atr_filter_values']
        status = row['atr_filter']
        print(f"ATR: {val:.2f} -> Pass? {status}")
        
except Exception as e:
    print(f"Error: {e}")

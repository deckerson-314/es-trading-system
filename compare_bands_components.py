
import pandas as pd
import numpy as np
import sys
import os

# Add project root
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from bollinger_strategy.strategy_v4 import BollingerBandStrategyV4
from bollinger_strategy.parameters import load_params

# 1. Backtest Data & Calc
print("Loading Hist Data...")
hist_path = r"c:\Trading\ES_1min_Dec29_31_EXTENDED.csv"
df_hist = pd.read_csv(hist_path)
df_hist.columns = [c.lower() for c in df_hist.columns]
df_hist['datetime'] = pd.to_datetime(df_hist['datetime']).dt.tz_localize(None)
df_hist.set_index('datetime', inplace=True)

# Params (Need exact params to match Length/StdDev)
params_path = r"c:\Trading\Bollinger\parameters\live_params.csv"
params = load_params(params_path)
strategy = BollingerBandStrategyV4(params)

# Calc Indicators (This handles resampling to 2T)
print("Calculating Hist Indicators...")
df_hist_calc = strategy.calculate_indicators(df_hist.copy())

# Target Window (CT): 12:36 to 12:16 (Wait, 12:36 is AFTER?)
# Target is Exit at 13:16 ET = 12:16 CT.
# Window: 11:36 CT to 12:16 CT (40 mins prior).
start_ct = pd.Timestamp("2025-12-30 11:36:00")
end_ct = pd.Timestamp("2025-12-30 12:16:00")

hist_subset = df_hist_calc.loc[(df_hist_calc.index >= start_ct) & (df_hist_calc.index <= end_ct)].copy()

# Derive Hist components
hist_subset['hist_mean'] = hist_subset['mid']
hist_subset['hist_std'] = hist_subset['std']

# 2. Live Data
print("Loading Live Log...")
live_path = r"c:\Trading\live_logs\live_data.csv"
df_live = pd.read_csv(live_path, on_bad_lines='skip')
# Clean Log
df_live['datetime'] = pd.to_datetime(df_live['datetime'], utc=True).dt.tz_convert('US/Eastern').dt.tz_localize(None)

# Target Window (ET): 12:36 ET to 13:16 ET
start_et = pd.Timestamp("2025-12-30 12:36:00")
end_et = pd.Timestamp("2025-12-30 13:16:00")

live_subset = df_live[(df_live['datetime'] >= start_et) & (df_live['datetime'] <= end_et)].copy()

# Derive Live components from Upper/Lower
# Upper = Mean + 2*Std
# Lower = Mean - 2*Std
# Mean = (Upper + Lower) / 2
# Range = Upper - Lower = 4*Std -> Std = (Upper - Lower) / 4

live_subset['live_mean'] = (live_subset['upper'] + live_subset['lower']) / 2
live_subset['live_std'] = (live_subset['upper'] - live_subset['lower']) / 4
live_subset.set_index('datetime', inplace=True)

# 3. Align and Compare
# Shift Hist Index by +1 Hour to match ET for merge
hist_subset.index = hist_subset.index + pd.Timedelta(hours=1)

merged = pd.merge(
    live_subset[['live_mean', 'live_std', 'close']], 
    hist_subset[['hist_mean', 'hist_std', 'close']], 
    left_index=True, right_index=True, 
    suffixes=('_live', '_hist'), how='outer'
)

merged['mean_diff'] = merged['live_mean'] - merged['hist_mean']
merged['std_diff'] = merged['live_std'] - merged['hist_std']
merged['close_diff'] = merged['close_live'] - merged['close_hist']

print("\n--- Components Comparison (Last 10 rows) ---")
print(merged[['live_mean', 'hist_mean', 'mean_diff', 'live_std', 'hist_std', 'std_diff', 'close_diff']].tail(10))

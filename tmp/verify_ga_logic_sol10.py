
import pandas as pd
import numpy as np
import sys
import os

# Ensure the project root is in sys.path
root_dir = r'c:\Trading'
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Mock sys.argv before importing optimize
sys.argv = ['optimize.py', '--strategy', 'trend', '--cores', '1']

import optimize
from optimize import load_params, run_backtest as ga_backtest

# Load Solution_10 parameters from the GA results
results_file = os.path.join(root_dir, 'Trend', 'parameters', 'genetic_results_2026-04-14-13.csv')
results_df = pd.read_csv(results_file)
col_name = 'Solution_10'

# Extract parameters into dict
param_file = os.path.join(root_dir, 'strategies', 'trend', 'parameters', 'trend_strategy_params.csv')
param_dict, _ = load_params(param_file, return_dataframe=True)

# !!! CRITICAL FIX: Set strategy name for Factory !!!
param_dict['strategy_name'] = 'trend'

# Manual mapping for ga_backtest
sol_params = {}
for idx, row in results_df.iterrows():
    name = row['Name']
    val = row[col_name]
    
    # Filter: Skip headers, statistics, and empty/NaN values
    if pd.isna(name) or str(name).startswith('==='):
        continue
    if row.get('Type') == 'statistic':
        continue
    if pd.isna(val) or val == '':
        continue
        
    try:
        sol_params[name] = float(val)
    except:
        sol_params[name] = val

# !!! CRITICAL DISCREPANCY FIX !!!
# The GA result reports Timeframe as 13, but the strategy likely ignored it and used default 30.
# We test 30m bars to see if it matches GA results.
sol_params['Timeframe (minutes)'] = 30.0
if 'Timeframe (minutes)' in param_dict:
    if isinstance(param_dict['Timeframe (minutes)'], dict):
        param_dict['Timeframe (minutes)']['value'] = 30
    else:
        param_dict['Timeframe (minutes)'] = 30
else:
    param_dict['Timeframe (minutes)'] = 30

print(f"\nEvaluating Solution_10 with Forced Timeframe=30")
print(f"Parameters: {sol_params}")

# Load Data the same way GA does
DATA_CSV = os.path.join(root_dir, 'Bollinger', 'data', 'ES_full_1min_continuous_ratio_adjusted.csv')
df = pd.read_csv(DATA_CSV, header=None, names=['datetime', 'open', 'high', 'low', 'close', 'volume'])
df['datetime'] = pd.to_datetime(df['datetime'])
df['datetime'] = df['datetime'].dt.tz_localize('UTC').dt.tz_convert('US/Eastern').dt.tz_localize(None)
df.set_index('datetime', inplace=True)

# GA range
GA_START_DATE = '2020-01-02'
GA_END_DATE = '2025-10-10'
df = df.loc[GA_START_DATE:GA_END_DATE]

# Apply Interleaved Mask (exactly like optimize.py)
NUM_PERIODS = 11
period_size = len(df) // NUM_PERIODS
is_mask = pd.Series(False, index=df.index)
for i in range(NUM_PERIODS):
    if i % 2 == 0:
        is_mask.iloc[i * period_size : (i + 1) * period_size if i < NUM_PERIODS - 1 else len(df)] = True

# Run GA's backtest
print("Running GA Backtester on IS periods (Strategy: Trend)...")
is_res = ga_backtest(sol_params, df, param_dict, mask=is_mask, suppress_output=False)
print(f"IS Results: PF={is_res['pf']:.4f}, Sortino={is_res['sortino']:.4f}, PnL=${is_res['pnl']:,.2f}, Trades={len(is_res.get('trades_df', []))}")

print("\nRunning GA Backtester on OOS periods (Strategy: Trend)...")
oos_res = ga_backtest(sol_params, df, param_dict, mask=~is_mask, suppress_output=False)
print(f"OOS Results: PF={oos_res['pf']:.4f}, Sortino={oos_res['sortino']:.4f}, PnL=${oos_res['pnl']:,.2f}, Trades={len(oos_res.get('trades_df', []))}")

print("\nRunning GA Backtester on FULL RANGE (Strategy: Trend)...")
full_res = ga_backtest(sol_params, df, param_dict, mask=None, suppress_output=False)
print(f"Full Results: PF={full_res['pf']:.4f}, Sortino={full_res['sortino']:.4f}, PnL=${full_res['pnl']:,.2f}, Trades={len(full_res.get('trades_df', []))}")

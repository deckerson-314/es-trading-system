#!/usr/bin/env python3
"""
Test GA evaluation function with locked parameters to verify trade frequency calculation.
"""

import pandas as pd
import sys
import os

# Add current directory to path
sys.path.insert(0, os.getcwd())

from bollinger_strategy import load_params
from BB_Genetic_v3 import run_backtest

DIAGNOSTIC_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12_DIAGNOSTIC.csv'
DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'

print("="*80)
print("TESTING GA EVALUATION WITH LOCKED PARAMETERS")
print("="*80)

# Load diagnostic parameters
param_dict, _ = load_params(DIAGNOSTIC_CSV, return_dataframe=True)

# Build params dict
ga_params = {}
for key in param_dict.keys():
    if key.startswith('===') or key.startswith('__'):
        continue
    ga_params[key] = param_dict[key].get('value')

print(f"\nTesting with locked parameters from: {DIAGNOSTIC_CSV}")
print(f"Key parameters:")
key_params = ['Min ATR Filter (Points)', 'Min Volume Multiplier', 
              'Long Trigger (% From Lower Band)', 'Short Trigger (% From Upper Band)',
              'Enable Long Trades', 'Enable Short Trades', 'Bollinger Band StdDev',
              'Bollinger Band Length']
for key in key_params:
    if key in ga_params:
        print(f"  {key}: {ga_params[key]}")

# Load data sample (first 1M rows for speed)
print(f"\nLoading data sample (first 1M rows for speed)...")
df = pd.read_csv(DATA_CSV, header=None, nrows=1000000)
df.columns = ['datetime', 'open', 'high', 'low', 'close', 'volume']
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.set_index('datetime')

print(f"Data: {len(df)} rows, {df.index.min()} to {df.index.max()}")

# Test GA backtest function
print(f"\n{'='*80}")
print("RUNNING GA BACKTEST EVALUATION")
print("="*80)
try:
    result = run_backtest(ga_params, df, param_dict, suppress_output=True, debug=False)
    
    trades_df = result.get('trades_df', pd.DataFrame())
    num_trades = len(trades_df)
    avg_trades_day = result.get('avg_trades_day', 0.0)
    sortino = result.get('sortino', 0.0)
    pf = result.get('profit_factor', 0.0)
    max_dd = result.get('max_drawdown', 0.0)
    total_profit = result.get('total_profit', 0.0)
    
    print(f"\nGA Backtest Results:")
    print(f"  Total Trades: {num_trades}")
    print(f"  Avg Trades/Day: {avg_trades_day:.6f}")
    print(f"  Sortino: {sortino:.6f}")
    print(f"  Profit Factor: {pf:.6f}")
    print(f"  Max Drawdown: ${max_dd:,.2f}")
    print(f"  Total Profit: ${total_profit:,.2f}")
    
    if num_trades == 0:
        print(f"\n🔴 CRITICAL: GA BACKTEST PRODUCED ZERO TRADES!")
        print(f"   This confirms the GA evaluation function is broken.")
        print(f"   Even with known-good parameters, it's not generating trades.")
    elif avg_trades_day < 0.1:
        print(f"\n🔴 CRITICAL: GA BACKTEST PRODUCED VERY FEW TRADES ({avg_trades_day:.6f} trades/day)")
        print(f"   Expected: ~40 trades/day from your backtest")
        print(f"   This suggests the GA evaluation function has a bug.")
    elif avg_trades_day > 10:
        print(f"\n✓ GA BACKTEST PRODUCED REASONABLE TRADES ({avg_trades_day:.6f} trades/day)")
        print(f"   This is closer to your expected ~40 trades/day")
        print(f"   The GA evaluation function appears to be working.")
    else:
        print(f"\n⚠️  GA BACKTEST PRODUCED {avg_trades_day:.6f} trades/day")
        print(f"   This is less than your expected ~40 trades/day")
        print(f"   May be due to data sample size or date range differences.")
        
except Exception as e:
    print(f"🔴 ERROR in GA backtest: {e}")
    import traceback
    traceback.print_exc()

print(f"\n{'='*80}")
print("DIAGNOSIS")
print("="*80)
print(f"\nIf avg_trades_day is near zero with locked parameters:")
print(f"  → The GA evaluation function has a fundamental bug")
print(f"  → Parameters may not be passed correctly to the strategy")
print(f"  → Entry conditions may be evaluated differently")
print(f"  → Data filtering may be different")
print(f"\nIf avg_trades_day matches your backtest (~40/day):")
print(f"  → The GA evaluation function is working correctly")
print(f"  → The issue is with parameter optimization (GA finding bad parameters)")
print(f"  → Need to investigate why GA converges to conservative values")
print(f"\n{'='*80}")


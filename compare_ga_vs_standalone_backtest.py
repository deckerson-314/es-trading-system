#!/usr/bin/env python3
"""
Compare GA backtest evaluation vs standalone backtest to find why GA finds no trades.
"""

import pandas as pd
from bollinger_strategy import load_params
from BB_Genetic_v3 import run_backtest
from BB_Strategy_v3 import run_backtest as standalone_backtest

PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_optimized.csv'
DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'

print("="*80)
print("COMPARING GA BACKTEST vs STANDALONE BACKTEST")
print("="*80)

# Load optimized parameters (what user is testing)
param_dict, _ = load_params(PARAM_CSV, return_dataframe=True)

# Build params dict for GA backtest
ga_params = {}
for key in param_dict.keys():
    if key.startswith('===') or key.startswith('__'):
        continue
    ga_params[key] = param_dict[key].get('value')

print(f"\nTesting with parameters from: {PARAM_CSV}")
print(f"Key parameters:")
key_params = ['Min ATR Filter (Points)', 'Min Volume Multiplier', 
              'Long Trigger (% From Lower Band)', 'Short Trigger (% From Upper Band)',
              'Enable Long Trades', 'Enable Short Trades', 'Bollinger Band StdDev']
for key in key_params:
    if key in ga_params:
        print(f"  {key}: {ga_params[key]}")

# Load data sample
print(f"\nLoading data sample (first 100K rows for speed)...")
df = pd.read_csv(DATA_CSV, header=None, nrows=100000)
df.columns = ['datetime', 'open', 'high', 'low', 'close', 'volume']
df['datetime'] = pd.to_datetime(df['datetime'])
df = df = df.set_index('datetime')

print(f"Data: {len(df)} rows, {df.index.min()} to {df.index.max()}")

# Test 1: GA backtest function
print(f"\n{'='*80}")
print("TEST 1: GA BACKTEST FUNCTION (run_backtest)")
print("="*80)
try:
    ga_result = run_backtest(ga_params, df, param_dict, suppress_output=False, debug=False)
    ga_trades = ga_result.get('trades_df', pd.DataFrame())
    ga_num_trades = len(ga_trades)
    ga_avg_trades_day = ga_result.get('avg_trades_day', 0.0)
    
    print(f"\nGA Backtest Results:")
    print(f"  Total Trades: {ga_num_trades}")
    print(f"  Avg Trades/Day: {ga_avg_trades_day:.6f}")
    print(f"  Sortino: {ga_result.get('sortino', 0):.6f}")
    print(f"  Profit Factor: {ga_result.get('profit_factor', 0):.6f}")
    
    if ga_num_trades == 0:
        print(f"\n🔴 GA BACKTEST PRODUCED ZERO TRADES!")
    elif ga_avg_trades_day < 0.1:
        print(f"\n⚠️  GA BACKTEST PRODUCED VERY FEW TRADES ({ga_avg_trades_day:.6f} trades/day)")
    else:
        print(f"\n✓ GA BACKTEST PRODUCED REASONABLE TRADES ({ga_avg_trades_day:.6f} trades/day)")
        
except Exception as e:
    print(f"🔴 ERROR in GA backtest: {e}")
    import traceback
    traceback.print_exc()

# Test 2: Standalone backtest (what user is using)
print(f"\n{'='*80}")
print("TEST 2: STANDALONE BACKTEST (BB_Strategy_v3.run_backtest)")
print("="*80)
try:
    # Standalone backtest might use different parameter format
    # Let's check what it expects
    standalone_result = standalone_backtest(ga_params, df, param_dict)
    standalone_trades = standalone_result.get('trades_df', pd.DataFrame())
    standalone_num_trades = len(standalone_trades)
    
    # Calculate avg trades/day manually for standalone
    if not standalone_trades.empty:
        unique_dates = set(standalone_trades['exit_time'].dt.date)
        trading_days = len(unique_dates) or 1
        standalone_avg_trades_day = standalone_num_trades / trading_days
    else:
        # Use full data period
        unique_dates = set(df.index.date)
        trading_days = len(unique_dates) or 1
        standalone_avg_trades_day = 0.0
    
    print(f"\nStandalone Backtest Results:")
    print(f"  Total Trades: {standalone_num_trades}")
    print(f"  Avg Trades/Day: {standalone_avg_trades_day:.6f}")
    print(f"  Sortino: {standalone_result.get('sortino', 0):.6f}")
    print(f"  Profit Factor: {standalone_result.get('profit_factor', 0):.6f}")
    
    if standalone_num_trades == 0:
        print(f"\n🔴 STANDALONE BACKTEST PRODUCED ZERO TRADES!")
    elif standalone_avg_trades_day < 0.1:
        print(f"\n⚠️  STANDALONE BACKTEST PRODUCED VERY FEW TRADES ({standalone_avg_trades_day:.6f} trades/day)")
    else:
        print(f"\n✓ STANDALONE BACKTEST PRODUCED REASONABLE TRADES ({standalone_avg_trades_day:.6f} trades/day)")
        
except Exception as e:
    print(f"🔴 ERROR in standalone backtest: {e}")
    import traceback
    traceback.print_exc()

# Comparison
print(f"\n{'='*80}")
print("COMPARISON")
print("="*80)

if 'ga_num_trades' in locals() and 'standalone_num_trades' in locals():
    print(f"\nTrade Count Comparison:")
    print(f"  GA Backtest: {ga_num_trades} trades")
    print(f"  Standalone: {standalone_num_trades} trades")
    print(f"  Difference: {standalone_num_trades - ga_num_trades} trades")
    
    if abs(standalone_num_trades - ga_num_trades) > 5:
        print(f"\n🔴 CRITICAL: Significant difference in trade counts!")
        print(f"   This suggests the GA backtest function is broken or using different logic!")
    
    print(f"\nAvg Trades/Day Comparison:")
    print(f"  GA Backtest: {ga_avg_trades_day:.6f} trades/day")
    print(f"  Standalone: {standalone_avg_trades_day:.6f} trades/day")
    print(f"  Difference: {standalone_avg_trades_day - ga_avg_trades_day:.6f} trades/day")
    
    if abs(standalone_avg_trades_day - ga_avg_trades_day) > 0.1:
        print(f"\n🔴 CRITICAL: Significant difference in avg trades/day!")
        print(f"   This confirms the GA backtest is calculating differently!")

print(f"\n{'='*80}")
print("DIAGNOSIS")
print("="*80)

print(f"\nIf standalone shows 40+ trades/day but GA shows near-zero:")
print(f"  1. 🔴 GA backtest function may have a bug")
print(f"  2. 🔴 Parameters may be getting corrupted in GA evaluation")
print(f"  3. 🔴 Entry conditions may be evaluated differently")
print(f"  4. 🔴 Data filtering may be different between the two")
print(f"  5. 🔴 Strategy instance may be initialized differently")

print(f"\n{'='*80}")


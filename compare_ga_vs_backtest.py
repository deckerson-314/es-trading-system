#!/usr/bin/env python3
"""
Compare how GA processes data vs BB_Strategy_v3 to find discrepancies.
"""

import pandas as pd
import sys
from bollinger_strategy import load_params, BollingerBandStrategy

# GA settings
DATA_SIZE = 5095390
PARAM_CSV_GA = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'
PARAM_CSV_BACKTEST = 'Bollinger/parameters/BB_Strategy_Parameters_optimized.csv'

# Test period
FROM_DATE = '2025-04-01'
TO_DATE = '2025-08-01'

print("="*80)
print("COMPARING GA vs BB_Strategy_v3 DATA PROCESSING")
print("="*80)

# Load data the way GA does
print("\n1. GA DATA LOADING:")
print(f"   Loading full dataset...")
df_full = pd.read_csv('Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv', 
                       header=None,
                       names=['datetime', 'open', 'high', 'low', 'close', 'volume'],
                       parse_dates=['datetime'], index_col='datetime')
print(f"   Total rows: {len(df_full):,}")
print(f"   Date range: {df_full.index[0]} to {df_full.index[-1]}")

if DATA_SIZE > 0:
    df_ga = df_full.tail(DATA_SIZE)
    print(f"   Using last {DATA_SIZE:,} rows (GA method)")
    print(f"   GA data range: {df_ga.index[0]} to {df_ga.index[-1]}")
    print(f"   Test period ({FROM_DATE} to {TO_DATE}) is in GA data: {df_ga.index[0] <= pd.Timestamp(FROM_DATE) <= df_ga.index[-1]}")
else:
    df_ga = df_full

# Load data the way BB_Strategy_v3 does
print("\n2. BB_Strategy_v3 DATA LOADING:")
df_backtest = df_full.loc[FROM_DATE:TO_DATE].copy()
print(f"   Using date range: {FROM_DATE} to {TO_DATE}")
print(f"   Rows: {len(df_backtest):,}")
print(f"   Date range: {df_backtest.index[0]} to {df_backtest.index[-1]}")

# Check if test period is in GA's OOS periods
print("\n3. CHECKING IF TEST PERIOD IS IN GA OOS PERIODS:")
NUM_PERIODS = 4
period_size = len(df_ga) // NUM_PERIODS
for i in range(NUM_PERIODS):
    start_idx = i * period_size
    end_idx = (i + 1) * period_size if i < NUM_PERIODS - 1 else len(df_ga)
    period = df_ga.iloc[start_idx:end_idx]
    if i % 2 == 1:  # OOS periods
        print(f"   OOS Period {i//2 + 1}: {period.index[0]} to {period.index[-1]}")
        test_start = pd.Timestamp(FROM_DATE)
        test_end = pd.Timestamp(TO_DATE)
        if period.index[0] <= test_start <= period.index[-1] and period.index[0] <= test_end <= period.index[-1]:
            print(f"     [OK] Test period IS within this OOS period")
        else:
            print(f"     [NO] Test period is NOT within this OOS period")

# Load parameters
print("\n4. PARAMETER COMPARISON:")
param_dict_ga, _ = load_params(PARAM_CSV_GA, return_dataframe=True)
param_dict_backtest, _ = load_params(PARAM_CSV_BACKTEST, return_dataframe=True)

# Key parameters to compare
key_params = ['Long Trigger (% From Lower Band)', 'Short Trigger (% From Upper Band)',
              'Bollinger Band Length', 'Bollinger Band StdDev', 'Timeframe (minutes)',
              'Min ATR Filter (Points)', 'Min Volume Multiplier', 'Enable RTH Filter']

print("   Comparing key parameters:")
for param in key_params:
    if param in param_dict_ga and param in param_dict_backtest:
        ga_val = param_dict_ga[param]['value']
        bt_val = param_dict_backtest[param]['value']
        match = "[OK]" if ga_val == bt_val else "[NO]"
        print(f"   {match} {param}:")
        print(f"      GA: {ga_val}")
        print(f"      Backtest: {bt_val}")

# Test strategy on both datasets
print("\n5. TESTING STRATEGY ON BOTH DATASETS:")
print("   Creating strategy instances...")
strategy_ga = BollingerBandStrategy(param_dict_backtest)  # Use optimized params
strategy_backtest = BollingerBandStrategy(param_dict_backtest)

# Process data
print("   Processing GA data subset (test period only)...")
df_ga_subset = df_ga.loc[FROM_DATE:TO_DATE].copy()
if len(df_ga_subset) > 0:
    df_ga_processed = strategy_ga.calculate_indicators(df_ga_subset)
    df_ga_processed = strategy_ga.apply_filters(df_ga_processed)
    print(f"   GA subset after processing: {len(df_ga_processed):,} rows")
else:
        print(f"   [NO] GA subset is empty!")

print("   Processing BB_Strategy_v3 data...")
df_backtest_processed = strategy_backtest.calculate_indicators(df_backtest)
df_backtest_processed = strategy_backtest.apply_filters(df_backtest_processed)
print(f"   Backtest data after processing: {len(df_backtest_processed):,} rows")

# Compare results
print("\n6. COMPARISON RESULTS:")
if len(df_ga_subset) > 0:
    print(f"   GA subset original rows: {len(df_ga_subset):,}")
    print(f"   GA subset processed rows: {len(df_ga_processed):,}")
    print(f"   Backtest original rows: {len(df_backtest):,}")
    print(f"   Backtest processed rows: {len(df_backtest_processed):,}")
    
    if len(df_ga_processed) != len(df_backtest_processed):
        print(f"   [NO] ROW COUNT MISMATCH!")
    else:
        print(f"   [OK] Row counts match")
        
    # Check if data is identical
    if len(df_ga_processed) > 0 and len(df_backtest_processed) > 0:
        # Align indices
        common_idx = df_ga_processed.index.intersection(df_backtest_processed.index)
        if len(common_idx) > 0:
            df_ga_aligned = df_ga_processed.loc[common_idx]
            df_backtest_aligned = df_backtest_processed.loc[common_idx]
            
            # Compare key columns
            for col in ['close', 'upper', 'lower', 'atr_ts']:
                if col in df_ga_aligned.columns and col in df_backtest_aligned.columns:
                    diff = (df_ga_aligned[col] - df_backtest_aligned[col]).abs()
                    max_diff = diff.max()
                    if max_diff > 0.01:
                        print(f"   [NO] {col} values differ (max diff: {max_diff:.4f})")
                    else:
                        print(f"   [OK] {col} values match")
else:
    print(f"   [NO] GA subset is empty - test period not in GA data range!")

print("\n" + "="*80)


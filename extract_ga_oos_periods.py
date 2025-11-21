#!/usr/bin/env python3
"""
Extract OOS period date ranges from GA run.
This helps identify which date ranges the GA actually tested on.
"""

import pandas as pd
import sys

# Load the same data the GA uses
DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'
DATA_SIZE = 5095390
NUM_SPLIT_PERIODS = 4
USE_INTERLEAVED = True

print("Loading data...")
df = pd.read_csv(DATA_CSV, header=None,
                 names=['datetime', 'open', 'high', 'low', 'close', 'volume'],
                 parse_dates=['datetime'], index_col='datetime')

if DATA_SIZE > 0:
    df = df.tail(DATA_SIZE)
    print(f"Using last {DATA_SIZE:,} rows")
    print(f"Date range: {df.index[0]} to {df.index[-1]}")

if USE_INTERLEAVED and NUM_SPLIT_PERIODS > 1:
    print(f"\n=== Interleaved Data Split (NUM_PERIODS={NUM_SPLIT_PERIODS}) ===")
    df = df.sort_index()
    
    period_size = len(df) // NUM_SPLIT_PERIODS
    is_periods = []
    oos_periods = []
    
    for i in range(NUM_SPLIT_PERIODS):
        start_idx = i * period_size
        end_idx = (i + 1) * period_size if i < NUM_SPLIT_PERIODS - 1 else len(df)
        period = df.iloc[start_idx:end_idx].copy()
        
        if i % 2 == 0:
            is_periods.append(period)
            print(f"  Period {i+1}: IS ({len(period):,} rows)")
            print(f"    Date range: {period.index[0]} to {period.index[-1]}")
        else:
            oos_periods.append(period)
            print(f"  Period {i+1}: OOS ({len(period):,} rows)")
            print(f"    Date range: {period.index[0]} to {period.index[-1]}")
    
    print(f"\n=== OOS PERIODS FOR TESTING ===")
    for i, period in enumerate(oos_periods, 1):
        print(f"OOS Period {i}: {period.index[0].strftime('%Y-%m-%d')} to {period.index[-1].strftime('%Y-%m-%d')}")
        print(f"  Use in BB_Strategy_v3.py:")
        print(f"    FROM_DATE = '{period.index[0].strftime('%Y-%m-%d')}'")
        print(f"    TO_DATE = '{period.index[-1].strftime('%Y-%m-%d')}'")
        print()
    
    # Combined OOS
    oos_combined = pd.concat(oos_periods).sort_index() if oos_periods else pd.DataFrame()
    print(f"Combined OOS: {oos_combined.index[0]} to {oos_combined.index[-1]}")
else:
    print("Using simple split (not interleaved)")


#!/usr/bin/env python3
"""
Diagnose the trade frequency calculation issue.
"""

import pandas as pd
import numpy as np

DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'

print("="*80)
print("TRADE FREQUENCY CALCULATION DIAGNOSTIC")
print("="*80)

# Load a sample of data
print("\nLoading data sample...")
df = pd.read_csv(DATA_CSV, header=None, nrows=100000)
df.columns = ['datetime', 'open', 'high', 'low', 'close', 'volume']
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.set_index('datetime')

print(f"Data loaded: {len(df)} rows")
print(f"Date range: {df.index.min()} to {df.index.max()}")

# Calculate days using different methods
data_start = df.index.min()
data_end = df.index.max()
calendar_days = (data_end - data_start).days or 1

# Count unique dates (trading days)
unique_dates = df.index.date
trading_days = len(set(unique_dates))

# Count weekdays only
weekdays = df[df.index.weekday < 5]  # Monday=0, Friday=4
weekday_dates = len(set(weekdays.index.date))

print(f"\nDay Calculations:")
print(f"  Calendar Days (data_end - data_start): {calendar_days} days")
print(f"  Unique Dates (trading days): {trading_days} days")
print(f"  Weekdays Only: {weekday_dates} days")
print(f"  Difference: {calendar_days - trading_days} days")

# Simulate trade frequency calculation
print(f"\n{'='*80}")
print("SIMULATED TRADE FREQUENCY CALCULATIONS")
print("="*80)

# Simulate different numbers of trades
for num_trades in [10, 50, 100, 200, 500]:
    print(f"\nIf {num_trades} trades occurred:")
    print(f"  Using Calendar Days: {num_trades / calendar_days:.6f} trades/day")
    print(f"  Using Trading Days: {num_trades / trading_days:.6f} trades/day")
    print(f"  Using Weekdays: {num_trades / weekday_dates:.6f} trades/day")
    
    # Normalize
    TRADES_MAX = 5.0
    norm_cal = (num_trades / calendar_days) / TRADES_MAX
    norm_trade = (num_trades / trading_days) / TRADES_MAX
    norm_week = (num_trades / weekday_dates) / TRADES_MAX
    
    print(f"  Normalized (Calendar): {norm_cal:.6f}")
    print(f"  Normalized (Trading): {norm_trade:.6f}")
    print(f"  Normalized (Weekdays): {norm_week:.6f}")
    
    # Weighted contribution
    weight = 100.0
    contrib_cal = norm_cal * weight
    contrib_trade = norm_trade * weight
    contrib_week = norm_week * weight
    
    print(f"  Weighted Contribution (Calendar): {contrib_cal:.3f}")
    print(f"  Weighted Contribution (Trading): {contrib_trade:.3f}")
    print(f"  Weighted Contribution (Weekdays): {contrib_week:.3f}")

print(f"\n{'='*80}")
print("DIAGNOSIS")
print("="*80)
print(f"\n🔴 ISSUE IDENTIFIED:")
print(f"   The code uses CALENDAR DAYS (data_end - data_start).days")
print(f"   This includes weekends and holidays, making avg_trades_day artificially low!")
print(f"\n   Example:")
print(f"   - 100 trades over 3650 calendar days = 0.027 trades/day")
print(f"   - 100 trades over 2520 trading days = 0.040 trades/day")
print(f"   - The difference makes normalized values even smaller!")
print(f"\n   Solution: Use TRADING DAYS, not calendar days!")

print(f"\n{'='*80}")


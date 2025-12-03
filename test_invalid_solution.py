"""
Test what happens when all entry methods are disabled.
This will help us understand why invalid solutions aren't being eliminated naturally.
"""

import pandas as pd
from bollinger_strategy.parameters import load_params
from BB_Genetic_v3 import run_backtest

# Load a small sample of data
DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'
df = pd.read_csv(DATA_CSV, header=None,
                 names=['datetime', 'open', 'high', 'low', 'close', 'volume'],
                 parse_dates=['datetime'], index_col='datetime')
df = df.tail(10000)  # Small sample for testing

# Load parameters
param_dict, _ = load_params('Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv', return_dataframe=True)

# Test 1: All entry methods disabled
print("="*80)
print("TEST 1: All Entry Methods Disabled")
print("="*80)
params_all_disabled = {
    'Long Entry on Body in Zone': 0,
    'Long Entry on Wick Touch': 0,
    'Short Entry on Body in Zone': 0,
    'Short Entry on Wick Touch': 0,
    'Enable Long Trades': True,  # Still enabled, but no entry methods
    'Enable Short Trades': True,  # Still enabled, but no entry methods
}

result = run_backtest(params_all_disabled, df, param_dict, suppress_output=False, debug=True)
print(f"\nResult:")
print(f"  Trades: {len(result.get('trades_df', pd.DataFrame()))}")
print(f"  Avg Trades/Day: {result.get('avg_trades_day', 0)}")
print(f"  Sortino: {result.get('sortino', 0)}")
print(f"  Profit Factor: {result.get('profit_factor', 0)}")
print(f"  Total Profit: {result.get('total_profit', 0)}")

# Test 2: Only one entry method enabled (should work)
print("\n" + "="*80)
print("TEST 2: One Entry Method Enabled (Short Body)")
print("="*80)
params_one_enabled = {
    'Long Entry on Body in Zone': 0,
    'Long Entry on Wick Touch': 0,
    'Short Entry on Body in Zone': 1,  # Enabled
    'Short Entry on Wick Touch': 0,
    'Enable Long Trades': True,
    'Enable Short Trades': True,
}

result2 = run_backtest(params_one_enabled, df, param_dict, suppress_output=False, debug=True)
print(f"\nResult:")
print(f"  Trades: {len(result2.get('trades_df', pd.DataFrame()))}")
print(f"  Avg Trades/Day: {result2.get('avg_trades_day', 0)}")
print(f"  Sortino: {result2.get('sortino', 0)}")
print(f"  Profit Factor: {result2.get('profit_factor', 0)}")
print(f"  Total Profit: {result2.get('total_profit', 0)}")

print("\n" + "="*80)
print("CONCLUSION")
print("="*80)
print("If Test 1 shows avg_trades_day = 0, then invalid solutions SHOULD be eliminated")
print("by the hard constraint: if avg_trades_day < MIN_TRADES_DAY, return poor fitness.")
print("If Test 1 shows avg_trades_day > 0, there's a bug in the backtest logic.")


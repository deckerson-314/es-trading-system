import pandas as pd
import numpy as np
import os
from bollinger_strategy import BollingerBandStrategyV4
from bollinger_strategy import load_params

DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'
PARAM_CSV = 'Bollinger/parameters/backtest_params.csv'

def debug_backtest():
    print("Loading parameters...")
    if os.path.exists(PARAM_CSV):
        param_dict = load_params(PARAM_CSV)
        print(f"Loaded {len(param_dict)} parameters from {PARAM_CSV}")
    else:
        print("Param file not found, using defaults.")
        # Minimal defaults
        param_dict = {
            'Bollinger Band Length': {'value': 20, 'type': 'int', 'min': 10, 'max': 100},
            'Bollinger Band StdDev': {'value': 2.0, 'type': 'float', 'min': 1.0, 'max': 4.0},
            'Enable Long Trades': {'value': 1.0},
            'Enable Short Trades': {'value': 1.0},
            'Timeframe (minutes)': {'value': 1},
        }

    # Flatten params for strategy
    params_flat = {k: v['value'] if isinstance(v, dict) else v for k, v in param_dict.items()}
    
    print("Loading data...")
    if not os.path.exists(DATA_CSV):
        print(f"ERROR: Data file {DATA_CSV} not found.")
        return

    # Load a subset for speed, handle no header
    df = pd.read_csv(DATA_CSV, nrows=100000, header=None,
                     names=['datetime', 'open', 'high', 'low', 'close', 'volume'],
                     parse_dates=['datetime'], index_col='datetime')
    # df['datetime'] = pd.to_datetime(df['datetime']) # Handled by parse_dates
    # df.set_index('datetime', inplace=True) # Handled by index_col
    print(f"Loaded {len(df)} rows. Range: {df.index[0]} to {df.index[-1]}")

    print("Initializing Strategy V4...")
    strategy = BollingerBandStrategyV4(param_dict)
    strategy.update_optimizable_params(params_flat)
    
    print("Calculating Indicators...")
    df = strategy.calculate_indicators(df)
    
    print("Applying Filters...")
    len_before = len(df)
    df = strategy.apply_filters(df)
    len_after = len(df)
    print(f"Rows after filters: {len_after} (Dropped {len_before - len_after})")
    
    print("Columns in DF:", df.columns.tolist())

    # Filter Diagnostics
    for col in ['in_rth', 'volume_filter', 'atr_filter', 'in_maintenance']:
        if col in df.columns:
            true_count = df[col].sum()
            print(f"Filter '{col}' True count: {true_count}/{len(df)} ({true_count/len(df)*100:.1f}%)")

    # Check if bands are NaN
    if 'upper' in df.columns:
        nulls = df['upper'].isnull().sum()
        print(f"Upper Band Nulls: {nulls}/{len(df)}")
    else:
        print("ERROR: 'upper' column missing from dataframe.")
    
    print("Calculating Signals...")
    entry_long, entry_short = strategy.calculate_entry_signals(df)
    
    print(f"Entry Long Signals: {entry_long.sum()}")
    print(f"Entry Short Signals: {entry_short.sum()}")
    
    if entry_long.sum() == 0 and entry_short.sum() == 0:
        print("(!) NO SIGNALS GENERATED.")
        if 'lower' in df.columns:
            cross_lower = (df['close'] < df['lower']).sum()
            print(f"Close < Lower Band occurrences: {cross_lower}")
            
            # Check 0.5% threshold
            trig_lower = df['lower'] * (1 - 0.005)
            cross_trigger = (df['close'] < trig_lower).sum()
            print(f"Close < Lower Band * 0.995 (Trigger): {cross_trigger}") # Expecting this to be 0
        else:
            print("'lower' col missing, cannot check range.")
        return

    # Simulating trades (simplified)
    # Just checking signal generation is usually enough to diagnose "All 0"
    
if __name__ == "__main__":
    debug_backtest()

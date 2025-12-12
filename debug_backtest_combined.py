
import pandas as pd
import numpy as np
import os
from bollinger_strategy import BollingerBandStrategyV4
from bollinger_strategy import load_params

DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'
PARAM_CSV = 'Bollinger/parameters/backtest_params.csv'

def debug_combined_filters():
    print("Loading data...")
    if not os.path.exists(DATA_CSV):
        print(f"ERROR: Data file {DATA_CSV} not found.")
        return

    # Load data
    df_raw = pd.read_csv(DATA_CSV, nrows=50000, header=None,
                     names=['datetime', 'open', 'high', 'low', 'close', 'volume'],
                     parse_dates=['datetime'], index_col='datetime')
    
    # Load base params
    if os.path.exists(PARAM_CSV):
        param_dict = load_params(PARAM_CSV)
    else:
        param_dict = {}

    # Define runs
    runs = [
        {
            'name': 'Baseline (No Filters)',
            'params': {'Enable Trend Filter': 0, 'Enable ADX Filter': 0}
        },
        {
            'name': 'Trend Filter Only (EMA 200)',
            'params': {'Enable Trend Filter': 1, 'Trend EMA Length': 200, 'Enable ADX Filter': 0}
        },
        {
            'name': 'ADX Filter Only (Thresh 20)',
            'params': {'Enable Trend Filter': 0, 'Enable ADX Filter': 1, 'Max ADX Threshold': 20, 'ADX Period': 14}
        },
        {
            'name': 'COMBINED (Trend + ADX)',
            'params': {'Enable Trend Filter': 1, 'Trend EMA Length': 200, 'Enable ADX Filter': 1, 'Max ADX Threshold': 20}
        }
    ]
    
    results = {}
    
    print(f"\nRunning {len(runs)} Test Cases...")
    print("-" * 70)
    print(f"{'Run Name':<30} | {'Longs':>6} | {'Shorts':>6} | {'Total':>6}")
    print("-" * 70)
    
    base_params_flat = {k: v['value'] if isinstance(v, dict) else v for k, v in param_dict.items()}
    
    # Common relaxed settings
    base_params_flat['Enable RTH Filter'] = 0
    base_params_flat['Max ATR Filter (Points)'] = 100.0
    base_params_flat['Max Volume Multiplier'] = 100.0
    
    # Force standard bands to ensure signals exist
    base_params_flat['Bollinger Band StdDev'] = 2.0 
    base_params_flat['Long Entry on Wick Touch'] = 1
    base_params_flat['Short Entry on Wick Touch'] = 1
    
    for run in runs:
        # Update params
        run_params = base_params_flat.copy()
        run_params.update(run['params'])
        
        # Initialize strategy
        strategy = BollingerBandStrategyV4(param_dict)
        strategy.update_optimizable_params(run_params)
        
        # Run
        df = strategy.calculate_indicators(df_raw.copy())
        df = strategy.apply_filters(df)
        longs, shorts = strategy.calculate_entry_signals(df)
        
        n_long = longs.sum()
        n_short = shorts.sum()
        total = n_long + n_short
        
        results[run['name']] = total
        
        print(f"{run['name']:<30} | {n_long:>6} | {n_short:>6} | {total:>6}")

    print("-" * 70)
    
    # Verification Logic
    base = results['Baseline (No Filters)']
    trend = results['Trend Filter Only (EMA 200)']
    adx = results['ADX Filter Only (Thresh 20)']
    combined = results['COMBINED (Trend + ADX)']
    
    print("\nVerification Checks:")
    
    pass_trend = trend < base
    print(f"1. Trend Filter Reduces Trades:   {'PASS' if pass_trend else 'FAIL'} ({base} -> {trend})")
    
    pass_adx = adx < base
    print(f"2. ADX Filter Reduces Trades:     {'PASS' if pass_adx else 'FAIL'} ({base} -> {adx})")
    
    pass_combo = (combined <= trend) and (combined <= adx)
    print(f"3. Combined is Most Restrictive:  {'PASS' if pass_combo else 'FAIL'} (Combined: {combined})")
    
    if pass_trend and pass_adx and pass_combo:
        print("\nSUCCESS: Combined Logic verified. The Kitchen Sink works.")
    else:
        print("\nWARNING: Logic verification failed.")

if __name__ == "__main__":
    debug_combined_filters()

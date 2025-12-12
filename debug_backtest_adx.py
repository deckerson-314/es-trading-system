
import pandas as pd
import numpy as np
import os
from bollinger_strategy import BollingerBandStrategyV4
from bollinger_strategy import load_params

DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'
PARAM_CSV = 'Bollinger/parameters/backtest_params.csv'

def debug_adx_filter():
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
        {'name': 'BASELINE (No Filter)', 'filter': 0, 'thresh': 100},
        {'name': 'TEST (ADX Filter ON)', 'filter': 1, 'thresh': 20}
    ]
    
    results = {}

    for run in runs:
        print(f"\n--- Running {run['name']} ---")
        
        # Override params
        params_flat = {k: v['value'] if isinstance(v, dict) else v for k, v in param_dict.items()}
        params_flat['Enable ADX Filter'] = run['filter']
        params_flat['Max ADX Threshold'] = run['thresh']
        params_flat['ADX Period'] = 14
        params_flat['Bollinger Band StdDev'] = 2.0 # Force standard bands
        
        # Relax other filters to ensure signals exist
        params_flat['Enable RTH Filter'] = 0
        params_flat['Max ATR Filter (Points)'] = 100.0
        params_flat['Max Volume Multiplier'] = 100.0
        params_flat['Long Entry on Wick Touch'] = 1
        params_flat['Short Entry on Wick Touch'] = 1
        params_flat['Long Entry on Body in Zone'] = 1
        params_flat['Short Entry on Body in Zone'] = 1
        
        # Init Strategy
        strategy = BollingerBandStrategyV4(param_dict)
        strategy.update_optimizable_params(params_flat)
        
        # Calc
        df = strategy.calculate_indicators(df_raw.copy())
        
        # Debug Filter Drops
        before = len(df)
        df = strategy.apply_filters(df)
        after = len(df)
        print(f"Rows after generic filters: {after}/{before}")
        
        longs, shorts = strategy.calculate_entry_signals(df)
        
        count_long = longs.sum()
        count_short = shorts.sum()
        
        print(f"Long Signals: {count_long}")
        print(f"Short Signals: {count_short}")
        
        if run['filter'] == 0:
            results['base_long'] = count_long
            results['base_short'] = count_short
        else:
            results['test_long'] = count_long
            results['test_short'] = count_short


    # Validation
    print("\n=== VERIFICATION RESULTS ===")
    print(f"Baseline Longs: {results['base_long']} -> Test Longs: {results['test_long']}")
    print(f"Baseline Shorts: {results['base_short']} -> Test Shorts: {results['test_short']}")
    
    if results['test_long'] < results['base_long'] or results['test_short'] < results['base_short']:
        print("PASS: ADX Filter successfully reduced signals.")
    elif results['test_long'] == results['base_long'] and results['test_short'] == results['base_short']:
        print("WARNING: Signal counts identical. Filter might be inactive or useless.")
    else:
        print("FAIL: Logical error in filter.")

if __name__ == "__main__":
    debug_adx_filter()

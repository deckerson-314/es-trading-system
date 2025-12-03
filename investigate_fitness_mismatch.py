"""
Investigate why fitness values don't match parameters.
This will help us understand the root cause.
"""

import pickle
import os
from bollinger_strategy.parameters import load_params
from BB_Genetic_v3 import run_backtest, clamp_individual

def investigate_mismatch():
    checkpoint_file = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'
    
    if not os.path.exists(checkpoint_file):
        print(f"ERROR: Checkpoint file not found: {checkpoint_file}")
        return
    
    # Load checkpoint
    with open(checkpoint_file, 'rb') as f:
        checkpoint = pickle.load(f)
    
    hof = checkpoint.get('hall_of_fame', [])
    param_dict, _ = load_params('Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv', return_dataframe=True)
    
    # Get optimizable parameter keys (same logic as GA)
    ga_criteria_params = set(['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                              'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                              'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                              'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT'])
    
    param_keys = []
    for n, d in param_dict.items():
        if n.startswith('===') or n.startswith('__'):
            continue
        if n in ga_criteria_params:
            continue
        ptype = d.get('type', '')
        pmin = d.get('min')
        pmax = d.get('max')
        if ptype in ('int', 'float') and pmin is not None and pmax is not None:
            if pmin != pmax:
                param_keys.append(n)
    
    print("="*80)
    print("INVESTIGATING FITNESS-PARAMETER MISMATCH")
    print("="*80)
    
    if len(hof) == 0:
        print("Hall of Fame is empty!")
        return
    
    # Test the best solution
    best = hof[0]
    fitness = best.fitness.values
    
    print(f"\nBest Solution Fitness:")
    print(f"  Sortino: {fitness[0]:.4f}")
    print(f"  Drawdown: {fitness[1]:.4f}")
    print(f"  Profit Factor: {fitness[2]:.4f}")
    print(f"  Trades/Day: {fitness[3]:.4f}")
    print(f"  Total Profit: {fitness[4]:.4f}")
    
    # Extract parameters from individual (as stored)
    raw_params = dict(zip(param_keys, best))
    print(f"\nRaw Parameters (as stored in individual):")
    entry_params = ['Long Entry on Body in Zone', 'Long Entry on Wick Touch', 
                    'Short Entry on Body in Zone', 'Short Entry on Wick Touch',
                    'Enable Long Trades', 'Enable Short Trades']
    for p in entry_params:
        if p in raw_params:
            print(f"  {p}: {raw_params[p]}")
        else:
            # Check if it's in param_dict (might be fixed, not optimized)
            if p in param_dict:
                val = param_dict[p].get('value', 'N/A')
                print(f"  {p}: {val} (FIXED, not optimized)")
    
    # Clamp parameters (same as in evaluation)
    clamped_params = {}
    for n, v in raw_params.items():
        if n not in param_dict:
            continue
        mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
        v = max(mn, min(v, mx))
        if typ == 'int':
            clamped_params[n] = int(round(v))
        else:
            clamped_params[n] = float(v)
    
    print(f"\nClamped Parameters (as used in evaluation):")
    for p in entry_params:
        if p in clamped_params:
            print(f"  {p}: {clamped_params[p]}")
    
    # Check if parameters changed after clamping
    print(f"\nParameter Changes After Clamping:")
    changed = False
    for p in entry_params:
        if p in raw_params and p in clamped_params:
            if raw_params[p] != clamped_params[p]:
                print(f"  {p}: {raw_params[p]} → {clamped_params[p]} (CHANGED)")
                changed = True
    if not changed:
        print("  No changes (parameters were already valid)")
    
    # Now re-evaluate with the RAW parameters (not clamped)
    print(f"\n" + "="*80)
    print("RE-EVALUATING WITH RAW PARAMETERS")
    print("="*80)
    
    # Load a small sample of data
    import pandas as pd
    DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'
    df = pd.read_csv(DATA_CSV, header=None,
                     names=['datetime', 'open', 'high', 'low', 'close', 'volume'],
                     parse_dates=['datetime'], index_col='datetime')
    df = df.tail(10000)  # Small sample
    
    # Re-evaluate with RAW parameters (as stored in individual)
    print("\nRe-evaluating with RAW parameters (as stored in individual):")
    result_raw = run_backtest(raw_params, df, param_dict, suppress_output=False)
    print(f"  Trades: {len(result_raw.get('trades_df', pd.DataFrame()))}")
    print(f"  Avg Trades/Day: {result_raw.get('avg_trades_day', 0)}")
    print(f"  Sortino: {result_raw.get('sortino', 0)}")
    
    # Re-evaluate with CLAMPED parameters (as used during GA evaluation)
    print("\nRe-evaluating with CLAMPED parameters (as used during GA evaluation):")
    result_clamped = run_backtest(clamped_params, df, param_dict, suppress_output=False)
    print(f"  Trades: {len(result_clamped.get('trades_df', pd.DataFrame()))}")
    print(f"  Avg Trades/Day: {result_clamped.get('avg_trades_day', 0)}")
    print(f"  Sortino: {result_clamped.get('sortino', 0)}")
    
    # Compare
    print(f"\n" + "="*80)
    print("COMPARISON")
    print("="*80)
    print(f"Fitness from GA: trades/day = {fitness[3]:.4f}")
    print(f"Re-evaluation with RAW params: trades/day = {result_raw.get('avg_trades_day', 0):.4f}")
    print(f"Re-evaluation with CLAMPED params: trades/day = {result_clamped.get('avg_trades_day', 0):.4f}")
    
    if abs(fitness[3] - result_clamped.get('avg_trades_day', 0)) < 0.01:
        print("\n✓ Fitness matches CLAMPED parameters (expected)")
    else:
        print("\n✗ Fitness does NOT match CLAMPED parameters (unexpected!)")
    
    if abs(fitness[3] - result_raw.get('avg_trades_day', 0)) < 0.01:
        print("✓ Fitness matches RAW parameters (unexpected - should not happen)")
    else:
        print("✓ Fitness does NOT match RAW parameters (expected)")
    
    print("\n" + "="*80)
    print("CONCLUSION")
    print("="*80)
    print("If fitness matches CLAMPED but not RAW:")
    print("  → The GA evaluates with clamped parameters (correct)")
    print("  → But displays RAW parameters (incorrect - shows invalid values)")
    print("  → Solution: Display CLAMPED parameters, not RAW parameters")
    print("\nIf fitness matches RAW but not CLAMPED:")
    print("  → The GA evaluates with raw parameters (incorrect)")
    print("  → Parameters are not being clamped before evaluation")
    print("  → Solution: Clamp parameters BEFORE evaluation")

if __name__ == '__main__':
    investigate_mismatch()


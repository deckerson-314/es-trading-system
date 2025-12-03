#!/usr/bin/env python3
"""
Check actual parameter values in the Hall of Fame to understand the discrepancy.
"""

import pickle
import os
import pandas as pd
import numpy as np
from bollinger_strategy.parameters import load_params

CHECKPOINT_FILE = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'
PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'

def check_actual_values():
    """Check actual parameter values in checkpoint."""
    
    # Load checkpoint
    if not os.path.exists(CHECKPOINT_FILE):
        print(f"ERROR: Checkpoint not found: {CHECKPOINT_FILE}")
        return
    
    with open(CHECKPOINT_FILE, 'rb') as f:
        checkpoint = pickle.load(f)
    
    hof = checkpoint.get('hall_of_fame', [])
    
    print("="*80)
    print("ACTUAL PARAMETER VALUES IN HALL OF FAME")
    print("="*80)
    print(f"Hall of Fame size: {len(hof)}")
    print()
    
    # Load parameter dictionary
    param_dict, param_df = load_params(PARAM_CSV, return_dataframe=True)
    
    # Get parameter keys (optimizable parameters)
    param_keys = []
    for n, d in param_dict.items():
        if n.startswith('===') or n.startswith('__'):
            continue
        # Skip GA criteria parameters
        if n in ['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                 'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                 'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                 'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT', 'NORM_SORTINO_MAX', 'NORM_DD_MAX',
                 'NORM_PF_MAX', 'NORM_TRADES_MAX', 'NORM_PNL_MAX', 'MIN_WIN_RATE', 'SORTINO_CAP']:
            continue
        ptype = d.get('type', '')
        pmin = d.get('min')
        pmax = d.get('max')
        if ptype in ('int', 'float') and pmin is not None and pmax is not None:
            if pmin != pmax:  # Not fixed
                param_keys.append(n)
    
    # Extract parameter values from Hall of Fame
    param_data = []
    for i, ind in enumerate(hof):
        if hasattr(ind, 'fitness') and ind.fitness.valid:
            row = {}
            for j, param_name in enumerate(param_keys):
                if j < len(ind):
                    row[param_name] = ind[j]
            if row:
                param_data.append(row)
    
    if not param_data:
        print("No valid individuals in Hall of Fame")
        return
    
    param_df = pd.DataFrame(param_data)
    
    # Check specific problematic parameters
    problem_params = ['Min ATR Filter (Points)', 'Short Trigger (% From Upper Band)', 
                      'Min Volume Multiplier', 'Long Trigger (% From Lower Band)']
    
    print("PROBLEMATIC PARAMETERS:")
    print()
    
    for param_name in problem_params:
        if param_name in param_df.columns:
            values = param_df[param_name]
            if param_name in param_dict:
                param_info = param_dict[param_name]
                param_min = param_info.get('min', None)
                param_max = param_info.get('max', None)
                
                print(f"{param_name}:")
                print(f"  Range: [{param_min}, {param_max}]")
                print(f"  Mean: {values.mean():.6f}")
                print(f"  Min: {values.min():.6f}")
                print(f"  Max: {values.max():.6f}")
                print(f"  Std: {values.std():.6f}")
                
                # Count violations
                below = (values < param_min).sum()
                above = (values > param_max).sum()
                if below > 0 or above > 0:
                    print(f"  ⚠️  VIOLATIONS: {below} below min, {above} above max")
                else:
                    print(f"  ✅ All values within range")
                
                # Show distribution
                print(f"  Percentiles: 25%={values.quantile(0.25):.6f}, 50%={values.quantile(0.50):.6f}, 75%={values.quantile(0.75):.6f}, 95%={values.quantile(0.95):.6f}")
                print()
    
    # Check all parameters for violations
    print("="*80)
    print("ALL PARAMETERS - RANGE CHECK")
    print("="*80)
    
    violations_found = False
    for param_name in param_keys:
        if param_name in param_df.columns:
            values = param_df[param_name]
            if param_name in param_dict:
                param_info = param_dict[param_name]
                param_min = param_info.get('min', None)
                param_max = param_info.get('max', None)
                
                if param_min is not None and param_max is not None:
                    below = (values < param_min).sum()
                    above = (values > param_max).sum()
                    if below > 0 or above > 0:
                        violations_found = True
                        print(f"{param_name}:")
                        print(f"  Range: [{param_min}, {param_max}]")
                        print(f"  Actual: [{values.min():.6f}, {values.max():.6f}]")
                        print(f"  ⚠️  VIOLATIONS: {below} below min, {above} above max")
                        print()
    
    if not violations_found:
        print("✅ All parameters are within valid ranges!")
    
    # Check integer parameters
    print("="*80)
    print("INTEGER PARAMETERS - ROUNDING CHECK")
    print("="*80)
    
    integer_issues = False
    for param_name in param_keys:
        if param_name in param_df.columns:
            if param_name in param_dict:
                param_info = param_dict[param_name]
                param_type = param_info.get('type', 'float')
                
                if param_type == 'int':
                    values = param_df[param_name]
                    # Check if values are integers
                    non_integer = []
                    for v in values:
                        if not isinstance(v, (int, np.integer)) and abs(v - round(v)) > 0.001:
                            non_integer.append(v)
                    
                    if non_integer:
                        integer_issues = True
                        print(f"{param_name}:")
                        print(f"  ⚠️  {len(non_integer)} non-integer values found")
                        print(f"  Examples: {non_integer[:5]}")
                        print()
    
    if not integer_issues:
        print("✅ All integer parameters are properly rounded!")

if __name__ == '__main__':
    check_actual_values()


#!/usr/bin/env python3
"""
Check if parameter clamping is working correctly in the current GA run.
"""

import pickle
import os
import pandas as pd
import numpy as np
from bollinger_strategy.parameters import load_params

CHECKPOINT_FILE = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'
PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'

def check_clamping():
    """Check if parameters in checkpoint are properly clamped."""
    
    # Load checkpoint
    if not os.path.exists(CHECKPOINT_FILE):
        print(f"ERROR: Checkpoint not found: {CHECKPOINT_FILE}")
        return
    
    with open(CHECKPOINT_FILE, 'rb') as f:
        checkpoint = pickle.load(f)
    
    hof = checkpoint.get('hall_of_fame', [])
    pop = checkpoint.get('population', [])
    gen = checkpoint.get('generation', 0)
    
    print("="*80)
    print("PARAMETER CLAMPING VERIFICATION")
    print("="*80)
    print(f"Generation: {gen}")
    print(f"Hall of Fame size: {len(hof)}")
    print(f"Population size: {len(pop)}")
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
    
    print(f"Total optimizable parameters: {len(param_keys)}")
    print()
    
    # Check Hall of Fame
    print("="*80)
    print("HALL OF FAME PARAMETER CHECK")
    print("="*80)
    
    violations = []
    integer_issues = []
    
    for i, ind in enumerate(hof[:100]):  # Check first 100 solutions
        if hasattr(ind, 'fitness') and ind.fitness.valid:
            for j, param_name in enumerate(param_keys):
                if j < len(ind):
                    value = ind[j]
                    if param_name in param_dict:
                        param_info = param_dict[param_name]
                        param_min = param_info.get('min', None)
                        param_max = param_info.get('max', None)
                        param_type = param_info.get('type', 'float')
                        
                        # Check if value is within range
                        if param_min is not None and param_max is not None:
                            if value < param_min or value > param_max:
                                violations.append({
                                    'solution': i,
                                    'parameter': param_name,
                                    'value': value,
                                    'min': param_min,
                                    'max': param_max,
                                    'type': param_type
                                })
                        
                        # Check if integer parameters are rounded
                        if param_type == 'int':
                            if not isinstance(value, (int, np.integer)) and abs(value - round(value)) > 0.001:
                                integer_issues.append({
                                    'solution': i,
                                    'parameter': param_name,
                                    'value': value,
                                    'rounded': round(value),
                                    'type': param_type
                                })
    
    # Report violations
    if violations:
        print(f"\n⚠️  FOUND {len(violations)} RANGE VIOLATIONS:")
        print()
        
        # Group by parameter
        param_violations = {}
        for v in violations:
            param = v['parameter']
            if param not in param_violations:
                param_violations[param] = []
            param_violations[param].append(v)
        
        for param, v_list in sorted(param_violations.items(), key=lambda x: len(x[1]), reverse=True):
            print(f"  {param}:")
            print(f"    Range: [{v_list[0]['min']}, {v_list[0]['max']}]")
            print(f"    Violations: {len(v_list)} solutions")
            sample = v_list[:5]
            for v in sample:
                direction = "BELOW" if v['value'] < v['min'] else "ABOVE"
                boundary = v['min'] if v['value'] < v['min'] else v['max']
                print(f"      Solution {v['solution']}: {v['value']:.6f} ({direction} {boundary})")
            if len(v_list) > 5:
                print(f"      ... and {len(v_list) - 5} more")
            print()
    else:
        print("✅ All parameters are within valid ranges!")
    
    # Report integer issues
    if integer_issues:
        print(f"\n⚠️  FOUND {len(integer_issues)} INTEGER ROUNDING ISSUES:")
        print()
        
        # Group by parameter
        param_integer_issues = {}
        for v in integer_issues:
            param = v['parameter']
            if param not in param_integer_issues:
                param_integer_issues[param] = []
            param_integer_issues[param].append(v)
        
        for param, v_list in sorted(param_integer_issues.items(), key=lambda x: len(x[1]), reverse=True):
            print(f"  {param}:")
            print(f"    Issues: {len(v_list)} solutions")
            sample = v_list[:5]
            for v in sample:
                print(f"      Solution {v['solution']}: {v['value']:.6f} (should be {v['rounded']})")
            if len(v_list) > 5:
                print(f"      ... and {len(v_list) - 5} more")
            print()
    else:
        print("✅ All integer parameters are properly rounded!")
    
    # Check population
    print("="*80)
    print("POPULATION PARAMETER CHECK")
    print("="*80)
    
    pop_violations = []
    pop_integer_issues = []
    
    for i, ind in enumerate(pop[:50]):  # Check first 50 in population
        for j, param_name in enumerate(param_keys):
            if j < len(ind):
                value = ind[j]
                if param_name in param_dict:
                    param_info = param_dict[param_name]
                    param_min = param_info.get('min', None)
                    param_max = param_info.get('max', None)
                    param_type = param_info.get('type', 'float')
                    
                    # Check if value is within range
                    if param_min is not None and param_max is not None:
                        if value < param_min or value > param_max:
                            pop_violations.append({
                                'individual': i,
                                'parameter': param_name,
                                'value': value,
                                'min': param_min,
                                'max': param_max
                            })
                    
                    # Check if integer parameters are rounded
                    if param_type == 'int':
                        if not isinstance(value, (int, np.integer)) and abs(value - round(value)) > 0.001:
                            pop_integer_issues.append({
                                'individual': i,
                                'parameter': param_name,
                                'value': value,
                                'rounded': round(value)
                            })
    
    if pop_violations:
        print(f"\n⚠️  FOUND {len(pop_violations)} RANGE VIOLATIONS IN POPULATION:")
        param_pop_violations = {}
        for v in pop_violations:
            param = v['parameter']
            if param not in param_pop_violations:
                param_pop_violations[param] = []
            param_pop_violations[param].append(v)
        
        for param, v_list in sorted(param_pop_violations.items(), key=lambda x: len(x[1]), reverse=True)[:5]:
            print(f"  {param}: {len(v_list)} violations")
    else:
        print("✅ All population parameters are within valid ranges!")
    
    if pop_integer_issues:
        print(f"\n⚠️  FOUND {len(pop_integer_issues)} INTEGER ROUNDING ISSUES IN POPULATION")
    else:
        print("✅ All population integer parameters are properly rounded!")
    
    # Summary
    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Hall of Fame violations: {len(violations)}")
    print(f"Hall of Fame integer issues: {len(integer_issues)}")
    print(f"Population violations: {len(pop_violations)}")
    print(f"Population integer issues: {len(pop_integer_issues)}")
    print()
    
    if violations or integer_issues or pop_violations or pop_integer_issues:
        print("⚠️  CLAMPING IS NOT WORKING CORRECTLY!")
        print("   Recommendation: Restart GA with --fresh flag to ensure all individuals are properly clamped.")
    else:
        print("✅ CLAMPING IS WORKING CORRECTLY!")
        print("   All parameters are within valid ranges and integer parameters are rounded.")

if __name__ == '__main__':
    check_clamping()


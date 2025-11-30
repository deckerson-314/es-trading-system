#!/usr/bin/env python3
"""Check if PARAM_RANGES are being built correctly from CSV."""

from bollinger_strategy import load_params

PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'

param_dict, param_df = load_params(PARAM_CSV, return_dataframe=True)

print("Checking parameter ranges...")
print("="*80)

# Check specific problematic parameters
problem_params = ['Min ATR Filter (Points)', 'Min Volume Multiplier']

for key in problem_params:
    if key in param_dict:
        pdata = param_dict[key]
        print(f"\n{key}:")
        print(f"  Type: {pdata.get('type')}")
        print(f"  Min: {pdata.get('min')} (type: {type(pdata.get('min'))})")
        print(f"  Max: {pdata.get('max')} (type: {type(pdata.get('max'))})")
        print(f"  Value: {pdata.get('value')}")
        
        # Check CSV directly
        row = param_df[param_df['Name'] == key]
        if not row.empty:
            print(f"  CSV Min: {row.iloc[0]['Min']} (type: {type(row.iloc[0]['Min'])})")
            print(f"  CSV Max: {row.iloc[0]['Max']} (type: {type(row.iloc[0]['Max'])})")

print("\n" + "="*80)
print("Building PARAM_RANGES (as GA does)...")
print("="*80)

ga_criteria_params = set(['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                          'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                          'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                          'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT'])

PARAM_RANGES = {}
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
            PARAM_RANGES[n] = (pmin, pmax)

print(f"\nTotal optimizable parameters: {len(PARAM_RANGES)}")
print(f"\nProblem parameters in PARAM_RANGES:")
for key in problem_params:
    if key in PARAM_RANGES:
        lo, hi = PARAM_RANGES[key]
        print(f"  {key}: ({lo}, {hi})")


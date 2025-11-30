#!/usr/bin/env python3
"""
Verify that optimized parameters fall within valid GA limits.
"""

import pandas as pd
import sys

OPTIMIZED_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_optimized.csv'
GA_PARAMS_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'

print("="*80)
print("PARAMETER RANGE VERIFICATION")
print("="*80)

# Load both CSV files
try:
    optimized_df = pd.read_csv(OPTIMIZED_CSV)
    ga_params_df = pd.read_csv(GA_PARAMS_CSV)
except Exception as e:
    print(f"ERROR loading CSV files: {e}")
    sys.exit(1)

print(f"\nLoaded optimized parameters from: {OPTIMIZED_CSV}")
print(f"Loaded GA parameter ranges from: {GA_PARAMS_CSV}")

# Create a dictionary from GA params for easy lookup
ga_params_dict = {}
for _, row in ga_params_df.iterrows():
    name = row['Name']
    if name.startswith('===') or name.startswith('__'):
        continue
    ga_params_dict[name] = {
        'min': row.get('Min'),
        'max': row.get('Max'),
        'type': row.get('Type', ''),
        'value': row.get('Value')
    }

# Check each parameter in optimized file
print(f"\n{'='*80}")
print("CHECKING PARAMETER VALUES AGAINST GA RANGES")
print("="*80)

issues = []
warnings = []
checked = 0
skipped = 0

for _, row in optimized_df.iterrows():
    name = row['Name']
    
    # Skip section headers and metadata
    if name.startswith('===') or name.startswith('__'):
        skipped += 1
        continue
    
    # Skip if not in GA params (might be a statistic row)
    if name not in ga_params_dict:
        skipped += 1
        continue
    
    checked += 1
    opt_value = row.get('Value')
    ga_param = ga_params_dict[name]
    ga_min = ga_param['min']
    ga_max = ga_param['max']
    param_type = ga_param['type']
    
    # Skip if value is not numeric or is NaN
    try:
        if pd.isna(opt_value):
            warnings.append(f"{name}: Value is NaN (skipped)")
            continue
        
        # Convert to appropriate type
        if param_type == 'int':
            opt_value = int(float(opt_value))
            ga_min = int(float(ga_min)) if pd.notna(ga_min) else None
            ga_max = int(float(ga_max)) if pd.notna(ga_max) else None
        elif param_type == 'float':
            opt_value = float(opt_value)
            ga_min = float(ga_min) if pd.notna(ga_min) else None
            ga_max = float(ga_max) if pd.notna(ga_max) else None
        elif param_type == 'bool' or param_type == 'int':  # Boolean params are stored as 0/1
            opt_value = int(float(opt_value))
            ga_min = int(float(ga_min)) if pd.notna(ga_min) else None
            ga_max = int(float(ga_max)) if pd.notna(ga_max) else None
        else:
            # String or other types - just check if they match
            if opt_value == ga_param['value']:
                print(f"✓ {name}: {opt_value} (matches default)")
            else:
                warnings.append(f"{name}: {opt_value} (different from default {ga_param['value']}, but type is {param_type})")
            continue
    except (ValueError, TypeError) as e:
        warnings.append(f"{name}: Cannot convert value '{opt_value}' to {param_type}: {e}")
        continue
    
    # Check if parameter is fixed (min == max)
    if pd.notna(ga_min) and pd.notna(ga_max) and ga_min == ga_max:
        if opt_value == ga_min:
            print(f"✓ {name}: {opt_value} (fixed parameter, matches)")
        else:
            issues.append(f"🔴 {name}: {opt_value} (should be {ga_min} - fixed parameter)")
        continue
    
    # Check range
    if pd.notna(ga_min) and opt_value < ga_min:
        issues.append(f"🔴 {name}: {opt_value} < MIN ({ga_min})")
    elif pd.notna(ga_max) and opt_value > ga_max:
        issues.append(f"🔴 {name}: {opt_value} > MAX ({ga_max})")
    elif pd.notna(ga_min) and pd.notna(ga_max):
        print(f"✓ {name}: {opt_value} (within range [{ga_min}, {ga_max}])")
    elif pd.notna(ga_min):
        if opt_value >= ga_min:
            print(f"✓ {name}: {opt_value} (>= MIN {ga_min})")
        else:
            issues.append(f"🔴 {name}: {opt_value} < MIN ({ga_min})")
    elif pd.notna(ga_max):
        if opt_value <= ga_max:
            print(f"✓ {name}: {opt_value} (<= MAX {ga_max})")
        else:
            issues.append(f"🔴 {name}: {opt_value} > MAX ({ga_max})")
    else:
        warnings.append(f"{name}: No min/max defined in GA params")

# Summary
print(f"\n{'='*80}")
print("SUMMARY")
print("="*80)
print(f"Parameters checked: {checked}")
print(f"Parameters skipped: {skipped}")
print(f"Issues found: {len(issues)}")
print(f"Warnings: {len(warnings)}")

if issues:
    print(f"\n{'='*80}")
    print("🔴 ISSUES FOUND - PARAMETERS OUT OF RANGE")
    print("="*80)
    for issue in issues:
        print(f"  {issue}")
    print(f"\n⚠️  These parameters are OUTSIDE the valid GA ranges!")
    print(f"   The GA would not have generated these values.")
    print(f"   You may need to:")
    print(f"   1. Check if the optimized CSV was manually edited")
    print(f"   2. Verify the GA parameter ranges are correct")
    print(f"   3. Re-run the GA if these values are incorrect")
else:
    print(f"\n✓ All parameters are within valid GA ranges!")

if warnings:
    print(f"\n{'='*80}")
    print("⚠️  WARNINGS")
    print("="*80)
    for warning in warnings:
        print(f"  {warning}")

print(f"\n{'='*80}")


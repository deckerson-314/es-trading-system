#!/usr/bin/env python3
"""
Create a diagnostic parameter file with all optimizable parameters locked to backtest values.
This will force the GA to use exactly the same parameters as the backtest, allowing us to
verify that the GA evaluation function can produce the expected trade frequency.
"""

import pandas as pd

OPTIMIZED_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_optimized.csv'
GA_PARAMS_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'
DIAGNOSTIC_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12_DIAGNOSTIC.csv'

print("="*80)
print("CREATING DIAGNOSTIC PARAMETER FILE")
print("="*80)
print(f"Source (backtest values): {OPTIMIZED_CSV}")
print(f"Template (GA ranges): {GA_PARAMS_CSV}")
print(f"Output: {DIAGNOSTIC_CSV}")
print()

# Load both files
optimized_df = pd.read_csv(OPTIMIZED_CSV)
ga_params_df = pd.read_csv(GA_PARAMS_CSV)

# Create dictionary of optimized values
optimized_dict = {}
for _, row in optimized_df.iterrows():
    name = row['Name']
    if name.startswith('===') or name.startswith('__'):
        continue
    optimized_dict[name] = row.get('Value')

# Create diagnostic parameter file
diagnostic_rows = []

for _, row in ga_params_df.iterrows():
    name = row['Name']
    param_type = row.get('Type', '')
    description = row.get('Description', '')
    
    # Copy section headers and metadata as-is
    if name.startswith('===') or name.startswith('__'):
        diagnostic_rows.append({
            'Name': name,
            'Value': row.get('Value', ''),
            'Min': row.get('Min', ''),
            'Max': row.get('Max', ''),
            'Type': param_type,
            'Description': description
        })
        continue
    
    # Check if this parameter has an optimized value
    if name in optimized_dict:
        opt_value = optimized_dict[name]
        
        # For optimizable parameters (int/float with min != max), lock to optimized value
        ga_min = row.get('Min')
        ga_max = row.get('Max')
        
        # Check if parameter is optimizable (has valid min/max and they're different)
        is_optimizable = (param_type in ('int', 'float') and 
                         pd.notna(ga_min) and pd.notna(ga_max) and 
                         ga_min != ga_max)
        
        if is_optimizable:
            # Lock parameter: min = max = optimized value
            try:
                # Convert to appropriate type
                if param_type == 'int':
                    opt_value = int(float(opt_value))
                elif param_type == 'float':
                    opt_value = float(opt_value)
                
                diagnostic_rows.append({
                    'Name': name,
                    'Value': opt_value,
                    'Min': opt_value,  # Lock to optimized value
                    'Max': opt_value,  # Lock to optimized value
                    'Type': param_type,
                    'Description': f"{description} [LOCKED FOR DIAGNOSTIC - matches backtest]"
                })
                print(f"✓ Locked {name}: {opt_value} (was [{ga_min}, {ga_max}])")
            except (ValueError, TypeError) as e:
                # If conversion fails, keep original
                print(f"⚠️  Could not lock {name}: {e}")
                diagnostic_rows.append({
                    'Name': name,
                    'Value': row.get('Value', ''),
                    'Min': ga_min,
                    'Max': ga_max,
                    'Type': param_type,
                    'Description': description
                })
        else:
            # Not optimizable or fixed - keep as-is
            diagnostic_rows.append({
                'Name': name,
                'Value': row.get('Value', ''),
                'Min': ga_min,
                'Max': ga_max,
                'Type': param_type,
                'Description': description
            })
    else:
        # Parameter not in optimized file - keep GA default
        diagnostic_rows.append({
            'Name': name,
            'Value': row.get('Value', ''),
            'Min': row.get('Min', ''),
            'Max': row.get('Max', ''),
            'Type': param_type,
            'Description': description
        })

# Create DataFrame and save
diagnostic_df = pd.DataFrame(diagnostic_rows)
diagnostic_df.to_csv(DIAGNOSTIC_CSV, index=False)

print()
print("="*80)
print("DIAGNOSTIC PARAMETER FILE CREATED")
print("="*80)
print(f"File: {DIAGNOSTIC_CSV}")
print()
print("This file locks all optimizable parameters to the backtest values.")
print("When you run the GA with this file:")
print("  1. All individuals will have identical parameters (matching backtest)")
print("  2. The GA should report the same trade frequency as your backtest")
print("  3. If it doesn't, there's a bug in the GA evaluation function")
print()
print("To use this file:")
print("  1. Backup your current v1.12.csv")
print("  2. Copy DIAGNOSTIC file to v1.12.csv (or modify BB_Genetic_v3.py to use DIAGNOSTIC)")
print("  3. Run GA for 1-2 generations")
print("  4. Check if avg_trades_day matches your backtest (~40 trades/day)")
print()
print("="*80)


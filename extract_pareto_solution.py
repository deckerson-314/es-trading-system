#!/usr/bin/env python3
"""
Utility script to extract and save any Pareto-optimal solution from a GA checkpoint.

Usage:
    python extract_pareto_solution.py [solution_index]
    
    If solution_index is not provided, lists all solutions and prompts for selection.
    Solution index 0 = highest Sortino (selected solution)
    Solution index 1 = second highest Sortino, etc.
"""

import os
import sys
import pickle
import pandas as pd
from bollinger_strategy import load_params

CHECKPOINT_FILE = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'
PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'
OUTPUT_DIR = 'Bollinger/parameters'

def load_checkpoint():
    """Load GA checkpoint."""
    if not os.path.exists(CHECKPOINT_FILE):
        print(f"ERROR: Checkpoint file not found: {CHECKPOINT_FILE}")
        print("Please run the GA first to generate a checkpoint.")
        return None
    
    with open(CHECKPOINT_FILE, 'rb') as f:
        checkpoint = pickle.load(f)
    
    return checkpoint

def extract_solution_params(ind, param_keys, param_dict):
    """Extract and format parameters from an individual."""
    params = dict(zip(param_keys, ind))
    
    # Clamp & cast parameters
    for n, v in params.items():
        if n not in param_dict:
            continue
        mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
        v = max(mn, min(v, mx))
        if typ == 'int':
            params[n] = int(round(v))
        else:
            params[n] = float(v)
    
    # Convert boolean parameters (0/1 int) to actual booleans
    for n in list(params.keys()):
        if n in param_dict:
            original_type = param_dict[n].get('type', '')
            if original_type == 'bool' and isinstance(params[n], (int, float)):
                params[n] = bool(int(round(params[n])))
    
    # Handle TP method selection (mutually exclusive)
    if 'TP Method' in params:
        tp_method = int(round(params['TP Method']))
        params['Fixed BB at Entry TP'] = (tp_method == 0)
        params['Fixed ATR TP'] = (tp_method == 1)
        params['Opposite Bollinger Band TP'] = (tp_method == 2)
        params.pop('TP Method', None)
    
    # Ensure critical integer parameters
    if 'Bollinger Band Length' in params:
        params['Bollinger Band Length'] = max(1, int(round(params['Bollinger Band Length'])))
    if 'ATR Length for Trailing Stop' in params:
        params['ATR Length for Trailing Stop'] = max(1, int(round(params['ATR Length for Trailing Stop'])))
    if 'ATR Length for TP' in params:
        params['ATR Length for TP'] = max(1, int(round(params['ATR Length for TP'])))
    if 'Trailing Delay (bars)' in params:
        params['Trailing Delay (bars)'] = max(0, int(round(params['Trailing Delay (bars)'])))
    params['Timeframe (minutes)'] = max(1, int(round(params.get('Timeframe (minutes)', 15))))
    if 'Max Open Trades' in params:
        params['Max Open Trades'] = max(1, int(round(params['Max Open Trades'])))
    
    return params

def save_solution_to_csv(params, param_dict, output_path):
    """Save solution parameters to CSV file."""
    # Load original CSV structure
    param_df = pd.read_csv(PARAM_CSV)
    
    # Update values
    for idx, row in param_df.iterrows():
        param_name = row['Name']
        if param_name in params:
            param_df.at[idx, 'Value'] = params[param_name]
    
    # Save to output path
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    param_df.to_csv(output_path, index=False)
    print(f"Solution saved to: {output_path}")

def main():
    # Load checkpoint
    checkpoint = load_checkpoint()
    if checkpoint is None:
        return
    
    hof = checkpoint['hall_of_fame']
    if len(hof) == 0:
        print("ERROR: No Pareto-optimal solutions found in checkpoint.")
        return
    
    # Load parameter dictionary
    param_dict, param_df = load_params(PARAM_CSV, return_dataframe=True)
    param_keys = [k for k in param_dict.keys() if not k.startswith('__') and k != '=== ENTRY CRITERIA ===' 
                  and k != '=== TAKE PROFIT CRITERIA ===' and k != '=== STOP LOSS CRITERIA ===' 
                  and k != '=== GA CRITERIA ===']
    
    # Sort solutions by Sortino (descending)
    solutions = []
    for i, ind in enumerate(hof):
        if hasattr(ind, 'fitness') and ind.fitness.valid:
            sortino = ind.fitness.values[0]
            dd = ind.fitness.values[1]
            pf = ind.fitness.values[2]
            trades = ind.fitness.values[3] if len(ind.fitness.values) > 3 else 0
            solutions.append((i, ind, sortino, dd, pf, trades))
    
    solutions.sort(key=lambda x: x[2], reverse=True)  # Sort by Sortino
    
    # Display all solutions
    print("\n" + "="*80)
    print("PARETO-OPTIMAL SOLUTIONS")
    print("="*80)
    print(f"{'#':<4} {'Sortino':<10} {'Drawdown':<12} {'Profit Factor':<15} {'Avg Trades/Day':<15} {'Status'}")
    print("-"*80)
    
    for rank, (orig_idx, ind, sortino, dd, pf, trades) in enumerate(solutions):
        status = "★ SELECTED" if rank == 0 else ""
        print(f"{rank:<4} {sortino:<10.2f} ${dd:<11,.2f} {pf:<15.2f} {trades:<15.2f} {status}")
    
    print("="*80)
    
    # Get solution index from command line or prompt
    if len(sys.argv) > 1:
        try:
            solution_idx = int(sys.argv[1])
        except ValueError:
            print(f"ERROR: Invalid solution index: {sys.argv[1]}")
            return
    else:
        print(f"\nEnter solution index (0-{len(solutions)-1}) to extract, or 'q' to quit:")
        user_input = input().strip()
        if user_input.lower() == 'q':
            return
        try:
            solution_idx = int(user_input)
        except ValueError:
            print("ERROR: Invalid input")
            return
    
    if solution_idx < 0 or solution_idx >= len(solutions):
        print(f"ERROR: Solution index must be between 0 and {len(solutions)-1}")
        return
    
    # Extract selected solution
    orig_idx, ind, sortino, dd, pf, trades = solutions[solution_idx]
    params = extract_solution_params(ind, param_keys, param_dict)
    
    print(f"\nExtracting Solution #{solution_idx}:")
    print(f"  Sortino: {sortino:.2f}")
    print(f"  Drawdown: ${dd:,.2f}")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Avg Trades/Day: {trades:.2f}")
    
    # Save to CSV
    if solution_idx == 0:
        output_path = os.path.join(OUTPUT_DIR, 'BB_Strategy_Parameters_optimized_v3.csv')
    else:
        output_path = os.path.join(OUTPUT_DIR, f'BB_Strategy_Parameters_solution_{solution_idx}_v3.csv')
    
    save_solution_to_csv(params, param_dict, output_path)
    
    print(f"\n✓ Solution #{solution_idx} extracted and saved!")
    print(f"  You can now use this CSV file with BB_Strategy_v3.py to backtest this solution.")

if __name__ == '__main__':
    main()


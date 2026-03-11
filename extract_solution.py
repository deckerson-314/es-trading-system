#!/usr/bin/env python3
"""
extract_solution.py - Extract a specific solution from GA genetic_results CSV.

Usage:
  python extract_solution.py --csv <results_csv> --solution <N> [--output <output.json>]

Examples:
  python extract_solution.py --csv strategies/bollinger/parameters/genetic_results.csv --solution 3
  python extract_solution.py --csv Bollinger/parameters/genetic_results_2025-12-11-1.csv --solution 0 --output best_params.json
"""

import pandas as pd
import json
import argparse
import os
import sys


def extract_solution(csv_path, solution_num, output_path=None):
    """Extract parameters for a given solution number from genetic_results CSV."""
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found: {csv_path}")
        return None

    df = pd.read_csv(csv_path)

    # Determine which column holds the solution
    sol_col = f'Solution_{solution_num}'
    if sol_col not in df.columns:
        available = [c for c in df.columns if c.startswith('Solution_')]
        print(f"Error: Column '{sol_col}' not found. Available solutions: {available}")
        return None

    params = {}
    for _, row in df.iterrows():
        name = str(row['Name']).strip()
        if not name or name.startswith('===') or name == 'nan':
            continue

        # Get value from target solution column, fallback to 'Value' column
        val_str = str(row[sol_col]).strip()
        if val_str.lower() == 'nan' or val_str == '':
            val_str = str(row['Value']).strip()

        # Determine type from 'Type' column
        dtype = str(row.get('Type', '')).strip().lower()

        if dtype == 'int':
            try:
                val = int(float(val_str))
            except (ValueError, TypeError):
                continue
        elif dtype == 'float':
            try:
                val = float(val_str)
            except (ValueError, TypeError):
                try:
                    val = float(row['Value'])
                except (ValueError, TypeError):
                    continue
        elif dtype == 'bool':
            val = val_str.lower() in ['true', '1', 'yes']
        else:
            val = val_str

        params[name] = val

    print(f"Extracted {len(params)} parameters for Solution #{solution_num}:")
    print(json.dumps(params, indent=4))

    # Determine output path
    if output_path is None:
        base = os.path.splitext(os.path.basename(csv_path))[0]
        output_path = f'{base}_solution_{solution_num}.json'

    with open(output_path, 'w') as f:
        json.dump(params, f, indent=4)
    print(f"\nSaved to {output_path}")

    return params


def main():
    parser = argparse.ArgumentParser(
        description='Extract a specific solution from GA genetic_results CSV.',
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--csv', required=True, help='Path to genetic_results CSV file')
    parser.add_argument('--solution', type=str, required=True, help='Solution number to extract (e.g. 0, 1, 3, or 0_SELECTED)')
    parser.add_argument('--output', default=None, help='Output JSON path (default: auto-named)')

    args = parser.parse_args()
    extract_solution(args.csv, args.solution, args.output)


if __name__ == '__main__':
    main()

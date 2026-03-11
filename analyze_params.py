
import pandas as pd
import sys

# File path
results_file = r'c:\Trading\Trend\parameters\genetic_results_2026-02-08-4.csv'
output_file = r'c:\Trading\params_report.txt'

with open(output_file, 'w') as f:
    sys.stdout = f # Redirect stdout to file
    
    try:
        # Read the CSV
        df = pd.read_csv(results_file)
        
        print(f"Analyzing Parameters from: {results_file}")
        
        # Filter for relevant parameters
        target_params = [
            'Enable SMA Filter', 
            'SMA Period', 
            'Enable Volume Filter', 
            'Volume MA Length', 
            'Min Volume Multiplier',
            'Buy Lookback',
            'Sell Lookback'
        ]
        
        print("\n=== Top Solution (Solution_0_SELECTED) ===")
        for param in target_params:
            row = df[df['Name'] == param]
            if not row.empty:
                val = row['Solution_0_SELECTED'].values[0]
                print(f"{param:<25}: {val}")
            else:
                print(f"{param:<25}: Not Found")
                
        # Check prevalence in top 10 solutions
        print("\n=== Prevalence in Top 10 Solutions ===")
        sol_cols = [c for c in df.columns if c.startswith('Solution_') and c != 'Solution_0_SELECTED'][:10]
        
        for param in ['Enable SMA Filter', 'Enable Volume Filter']:
            row = df[df['Name'] == param]
            if not row.empty:
                # Get values for first 10 solutions
                vals = row[sol_cols].values[0]
                true_count = 0
                for v in vals:
                    if str(v).lower() == 'true': true_count += 1
                print(f"{param:<25}: {true_count}/{len(sol_cols)} solutions enabled it")

    except Exception as e:
        print(f"Error: {e}")

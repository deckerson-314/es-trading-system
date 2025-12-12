import pandas as pd
import json
import os

import sys

# Default to the previous run if no arg provided, but prefer arg
DEFAULT_CSV = r"c:\Trading\Bollinger\parameters\genetic_results_2025-12-11-5.csv"

def analyze():
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        csv_path = DEFAULT_CSV
        
    print(f"Loading {csv_path}...")
    try:
        # Load CSV, assuming header is on row 0
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"Error loading CSV: {e}")
        return

    # Inspect column names
    # Expect: Name, Value, Min, Max, Type, Description, Solution_0_SELECTED, Solution_1, ...
    
    # 1. Capture Fixed/Base Parameters (Value column) + Type
    param_info = {}
    for idx, row in df.iterrows():
        name = str(row['Name']).strip()
        val = row.get('Value', None)
        
        # Capture NORM_PNL_MAX if present
        if 'NORM_PNL_MAX' in name:
            print(f"Found Normalization Factor: {name} = {val}")
        
        if pd.notna(val) and name not in ['Total Profit', 'Sortino Ratio', 'Max Drawdown', 'Total Trades', 'Avg Trades/Day']:
             param_info[name] = val

    # 2. Extract Solution Columns
    sol_cols = [c for c in df.columns if c.startswith('Solution_')]
    print(f"Found {len(sol_cols)} solutions.")

    # 3. Find Statistic Rows
    # We look for rows where 'Name' matches specific metrics
    stats_map = {
        'Total Profit': None, 
        'Total Profit (norm)': None,
        'Sortino Ratio': None, 
        'Max Drawdown': None,
        'Total Trades': None,
        'Avg Trades/Day': None,
        'Win Rate': None
    }
    
    # Transpose for easier processing? No, select rows by Name
    
    # Mapping exact row names from file (fuzzy match)
    df['Name_Clean'] = df['Name'].astype(str).str.strip()
    
    results = []
    
    # Pre-fetch stat rows index
    stat_rows = {}
    for key in stats_map.keys():
        # Find row closest to key
        matches = df[df['Name_Clean'].str.contains(key, case=False, regex=False)]
        if not matches.empty:
            stat_rows[key] = matches.index[0]
            print(f"Mapped '{key}' to row index {stat_rows[key]} ('{df.loc[stat_rows[key], 'Name']}')")
    
    # Need at least Profit and Trades/Sortino
    if 'Sortino Ratio' not in stat_rows and 'Total Profit' not in stat_rows:
        print("CRITICAL: Could not find Profit or Sortino rows.")
        # Print all names to debug
        print("Available Names:", df['Name_Clean'].unique())
        return

    for col in sol_cols:
        res = {'Solution': col}
        
        # Extract Params for this solution (if needed, skipping for speed now)
        
        # Extract Stats
        valid_data = True
        for stat_name, row_idx in stat_rows.items():
            val = df.loc[row_idx, col]
            try:
                res[stat_name] = float(val)
            except:
                res[stat_name] = 0.0 # or NaN
        
        # Calculate Avg Profit per Trade
        # Prefer 'Total Profit' (absolute) if available, else 'Total Profit (norm)'
        profit_norm = res.get('Total Profit (norm)', 0.0)
        profit = res.get('Total Profit', profit_norm * 465000.0) # Use 465k denorm if needed
        
        trades = res.get('Total Trades', 0.0)
        
        # Estimate trades if missing
        if trades == 0 and res.get('Avg Trades/Day', 0) > 0:
             # approx 17.5 years (2008-2025) * 252 days
             est_days = 4400 
             trades = res.get('Avg Trades/Day', 0) * est_days
             res['Total Trades (Est)'] = trades
             
        if trades > 0:
            res['Avg Profit/Trade'] = profit / trades
        else:
            res['Avg Profit/Trade'] = 0.0
            
        results.append(res)

    results_df = pd.DataFrame(results)
    
    # Columns to print (check what exists)
    cols_to_print = ['Solution', 'Avg Profit/Trade', 'Total Profit (norm)', 'Sortino Ratio', 'Max Drawdown', 'Avg Trades/Day']
    if 'Total Trades' in results_df.columns:
        cols_to_print.append('Total Trades')
    elif 'Total Trades (Est)' in results_df.columns:
        cols_to_print.append('Total Trades (Est)')

    # Sort by Avg Profit/Trade
    print("\n--- TOP 5 High Profit/Trade Solutions ---")
    top_profit = results_df.sort_values(by='Avg Profit/Trade', ascending=False).head(5)
    print(top_profit[cols_to_print].to_string())

    # Sort by Sortino
    print("\n--- TOP 5 Sortino Solutions ---")
    top_sortino = results_df.sort_values(by='Sortino Ratio', ascending=False).head(5)
    print(top_sortino[cols_to_print].to_string())
    
    # Save Best Solution Parameters to JSON (Solution_0_SELECTED usually best Sortino, pick highest profit one too)
    best_profit_sol = top_profit.iloc[0]['Solution']
    print(f"\nExtracting parameters for {best_profit_sol}...")
    
    # Extract params logic
    # (Simplified version of extract_solution.py)
    best_params = {}
    for idx, row in df.iterrows():
        if row['Type'] in ['int', 'float', 'bool']:
            p_name = row['Name']
            p_val = row[best_profit_sol]
            # Fallback to Fixed Value if empty
            if pd.isna(p_val) or str(p_val).strip() == '':
                p_val = row['Value']
            
            # Type cast
            try:
                if row['Type'] == 'int':
                    best_params[p_name] = int(float(p_val))
                elif row['Type'] == 'float':
                    best_params[p_name] = float(p_val)
                elif row['Type'] == 'bool':
                    best_params[p_name] = (str(p_val).lower() == 'true')
            except:
                pass
                
    with open('best_profit_solution.json', 'w') as f:
        json.dump(best_params, f, indent=4)
    print("Saved best_profit_solution.json")

if __name__ == "__main__":
    analyze()

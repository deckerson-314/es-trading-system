import pandas as pd
import numpy as np

CSV_PATH = r"c:\Trading\Bollinger\parameters\genetic_results_2025-12-11-5.csv"

def check_limits():
    try:
        df = pd.read_csv(CSV_PATH)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    # Filter for parameter rows (Type is int or float, and not statistics)
    # The 'Type' column in the results CSV might be 'int', 'float', 'bool', or 'statistic'
    # We only care about int/float that have ranges
    
    param_df = df[df['Type'].isin(['int', 'float'])].copy()
    
    # We want to look at the top solutions. Let's pick Solution_0 (Best) and maybe Solution_92 (Sniper) if it exists
    solutions_to_check = ['Solution_0']
    
    # Check if Solution_92 exists (Sniper) - column might be named Solution_92 or Solution_92_SELECTED
    cols = df.columns
    for c in cols:
        if c.startswith('Solution_92'):
            solutions_to_check.append(c)
            break
            
    print(f"Analyzing Limits for: {solutions_to_check}\n")
    
    for sol_col in solutions_to_check:
        if sol_col not in df.columns:
            print(f"Column {sol_col} not found.")
            continue
            
        print(f"--- {sol_col} ---")
        at_min = []
        at_max = []
        
        for _, row in param_df.iterrows():
            name = row['Name']
            
            # Skip if Min/Max are NaN
            if pd.isna(row['Min']) or pd.isna(row['Max']):
                continue
                
            p_min = float(row['Min'])
            p_max = float(row['Max'])
            
            # If min == max, it's fixed, skip
            if p_min == p_max:
                continue
                
            try:
                val = float(row[sol_col])
            except ValueError:
                continue
            
            # Check proximity (within 1% of range or exact match for ints)
            tolerance = (p_max - p_min) * 0.01
            if tolerance == 0: tolerance = 1e-9
            
            if val <= p_min + tolerance:
                at_min.append(f"{name}: {val} (Min: {p_min})")
            elif val >= p_max - tolerance:
                at_max.append(f"{name}: {val} (Max: {p_max})")
                
        if at_min:
            print("HITTING MIN LIMIT:")
            for s in at_min: print(f"  - {s}")
        else:
            print("No parameters at Min limit.")
            
        if at_max:
            print("HITTING MAX LIMIT:")
            for s in at_max: print(f"  - {s}")
        else:
            print("No parameters at Max limit.")
        print("")

if __name__ == "__main__":
    check_limits()

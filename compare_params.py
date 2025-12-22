import pandas as pd
import sys
import os

def check_compatibility():
    ga_file = r"Bollinger\parameters\genetic_results_2025-12-11-5.csv"
    params_file = r"Bollinger\parameters\backtest_params.csv"
    
    # 1. Load Sol 302
    try:
        df_ga = pd.read_csv(ga_file)
        target_col = 'Solution_302'
        if target_col not in df_ga.columns:
            print(f"Error: {target_col} not found in GA file.")
            sys.exit(1)
            
        sol_params = {}
        for _, row in df_ga.iterrows():
            name = row['Name']
            if pd.isna(name) or str(name).startswith('==='): continue
            
            val = row[target_col]
            if pd.isna(val): continue
            
            # Type conversion
            p_type = row['Type']
            if p_type == 'int':
                try: val = int(float(val))
                except: continue
            elif p_type == 'float':
                try: val = float(val)
                except: continue
            elif p_type == 'bool':
                continue # Bools usually match, focus on numeric ranges
                
            sol_params[name] = val
            
    except Exception as e:
        print(f"Error reading GA file: {e}")
        sys.exit(1)

    # 2. Load Current Params
    try:
        df_params = pd.read_csv(params_file)
        
        print(f"\nComparing Solution 302 against Current Ranges ({params_file})...\n")
        print(f"{'PARAMETER':<40} | {'SOL 302':<10} | {'RANGE (Min-Max)':<20} | {'STATUS'}")
        print("-" * 90)
        
        all_ok = True
        
        for _, row in df_params.iterrows():
            name = row['Name']
            if name not in sol_params:
                continue
                
            curr_min = row['Min']
            curr_max = row['Max']
            sol_val = sol_params[name]
            
            # skip non-numeric
            if str(row['Type']).strip() not in ['int', 'float']:
                continue
            
            try:
                curr_min = float(curr_min)
                curr_max = float(curr_max)
            except:
                continue # Skip if Min/Max are not numbers
                
            is_valid = (sol_val >= curr_min) and (sol_val <= curr_max)
            status = "OK" if is_valid else "OUT OF BOUNDS"
            
            if not is_valid:
                all_ok = False
                print(f"{name:<40} | {sol_val:<10} | {curr_min}-{curr_max:<18} | {status} <---")
            else:
                 # Optional: print everything or just errors? User wants confirmation.
                 # Let's print everything for transparency but highlight errors.
                 pass
                 # print(f"{name:<40} | {sol_val:<10} | {curr_min}-{curr_max:<18} | {status}")

        if all_ok:
            print("\nSUCCESS: Solution 302 is completely contained within the current parameter space.")
        else:
            print("\nWARNING: Some parameters are OUTSIDE the current search space.")

    except Exception as e:
        print(f"Error reading Params file: {e}")
        sys.exit(1)

if __name__ == "__main__":
    check_compatibility()


import pickle
import sys
import os
import pandas as pd
import numpy as np
from deap import base, creator, tools

# Add current directory to path to import local modules if needed
sys.path.append(os.getcwd())

# We need to import BB_Genetic_v4 to ensure the DEAP creator classes (Fitness, Individual) 
# are defined in the namespace for unpickling.
# WRAPPER: BB_Genetic_v4 parses args at top level, so we must hide our args during import.
try:
    _original_argv = sys.argv
    sys.argv = [sys.argv[0]] # Hide custom arguments
    import BB_Genetic_v4
    sys.argv = _original_argv # Restore arguments
    print("Successfully imported BB_Genetic_v4 module.")
except ImportError as e:
    print(f"Warning: Could not import BB_Genetic_v4: {e}")
    # Fallback: Define classes manually if import fails (might not work if pickle expects exact module path)
    # But usually DEAP pickles depend on the names being in the creator module
    if not hasattr(creator, "FitnessMulti"):
        creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 1.0, 2.0, 2.0))
    if not hasattr(creator, "Individual"):
        creator.create("Individual", list, fitness=creator.FitnessMulti)

def load_checkpoint(filepath):
    if not os.path.exists(filepath):
        print(f"Error: Checkpoint file not found: {filepath}")
        return None
        
    try:
        with open(filepath, "rb") as cp_file:
            cp = pickle.load(cp_file)
        return cp
    except Exception as e:
        print(f"Error loading checkpoint: {e}")
        return None

def log(msg, file_obj):
    print(msg) # Still print to console for debugging
    if file_obj:
        file_obj.write(msg + "\n")

def analyze_history(cp, param_names):
    # Log function handles logging to file if provided
    f = sys.stdout # Since we redirected stdout, print goes to file
    
    log("\n" + "="*60, None) # Using None for file obj because stdout IS the file
    log("GA RUN ANALYSIS", None)
    log("="*60, None)
    
    # 1. Generation Statistics (Logbook)
    if "logbook" in cp:
        logbook = cp["logbook"]
        log(f"\n[Generation Statistics] (Total Gens: {len(logbook)})", f)
        
        data = []
        for record in logbook:
            row = {'gen': record.get('gen')}
            
            # Dynamic key handling
            for key, value in record.items():
                if key == 'gen': continue
                if key == 'nevals': continue
                
                if hasattr(value, '__len__') and not isinstance(value, str):
                    for i, v in enumerate(value):
                        suffixes = ['Sortino', 'DD', 'PF', 'Trades', 'PnL', 'PPT']
                        col_name = f"{key}_{suffixes[i]}" if i < len(suffixes) else f"{key}_{i}"
                        row[col_name] = v
                else:
                    row[key] = value

            data.append(row)
        
        df_log = pd.DataFrame(data)
        
        # Format display
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)
        pd.set_option('display.max_rows', 20)
        
        # Using print directly since redirected
        print(df_log.tail(15).to_string())
        
        print("\n[Convergence Trends]")
        if not df_log.empty:
            print(f"Start Gen {df_log.iloc[0]['gen']} -> End Gen {df_log.iloc[-1]['gen']}")

    # 3. Population Analysis (Current State)
    if "population" in cp:
        pop = cp["population"]
        if not pop:
            print("Population is empty.")
        else:
            print(f"\n[Final Population Analysis] (Size: {len(pop)})")
            
            if param_names:
                pop_data = []
                for ind in pop:
                    if len(ind) == len(param_names):
                        p_dict = dict(zip(param_names, ind))
                        pop_data.append(p_dict)
                    else:
                        print(f"Warning: Length Mismatch! Ind: {len(ind)}, Params: {len(param_names)}")
                        break
                
                if pop_data:
                    df_pop = pd.DataFrame(pop_data)
                    
                    print("\nParameter Convergence (Standard Deviation):")
                    stats = df_pop.describe().transpose()
                    with open("convergence.txt", "w") as cf:
                        if 'max' in stats.columns and 'min' in stats.columns:
                            stats['range'] = stats['max'] - stats['min']
                            stats['std_pct'] = stats['std'] / stats['range'].replace(0, 1)
                            
                            cf.write("Top 5 Converged Parameters (Lowest Variance):\n")
                            cf.write(stats.sort_values('std_pct').head(5)[['mean', 'std', 'min', 'max']].to_string() + "\n")
                            
                            cf.write("\nTop 5 Divergent Parameters (Highest Variance):\n")
                            cf.write(stats.sort_values('std_pct', ascending=False).head(5)[['mean', 'std', 'min', 'max']].to_string() + "\n")
                            print("Convergence data written to convergence.txt")

    # 4. Hall of Fame
    if "halloffame" in cp:
        hof = cp["halloffame"]
        print(f"\n[Hall of Fame] (Top {len(hof)} Solutions found across run)")
        
        for i, ind in enumerate(hof[:5]):
            print(f"\n=== Solution #{i} ===")
            print(f"Fitness: {ind.fitness.values}")
            if param_names:
                print("  Key Params:")
                interesting = ['Bollinger Band Length', 'Bollinger Band StdDev', 'Timeframe (minutes)', 
                                'Max ATR Filter (Points)', 'Enable RTH Filter', 'Volume MA Length',
                                'Long Entry on Wick Touch', 'Short Entry on Wick Touch',
                                'Long Entry on Body in Zone', 'Short Entry on Body in Zone',
                                'Enable Long Trades', 'Enable Short Trades']
                
                for name in interesting:
                    if name in param_names:
                        idx = param_names.index(name)
                        if idx < len(ind):
                            val = ind[idx]
                            if isinstance(val, float): val = f"{val:.4f}"
                            print(f"    {str(name).ljust(30)}: {val}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        CHECKPOINT_FILE = sys.argv[1]
    else:
        CHECKPOINT_FILE = r"ga_diagnostics_v4\ga_checkpoint_v4.pkl"
    print(f"Analyzing checkpoint: {CHECKPOINT_FILE}")
    
    # Try to load parameter names from the CSV if possible, or define fallback
    # Reading from backtest_params.csv to get names is best practice
    PARAM_FILE = r"Bollinger\parameters\backtest_params.csv"
    param_names = []
    # Valid parameter loading
    if not param_names:
        try:
            df_params = pd.read_csv(PARAM_FILE)
            # Load keys similar to how BB_Genetic_v4.py does it (lines 2423-2449)
            if 'Name' in df_params.columns:
                 # 1. Define explicit exclusions
                 ga_criteria_params = set([
                    'POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                    'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                    'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                    'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT'
                 ])
                 
                 param_names = []
                 for index, row in df_params.iterrows():
                     n = row['Name']
                     # Exclude metadata/sections
                     if str(n).startswith('===') or str(n).startswith('__'):
                         continue
                     # Exclude GA config
                     if n in ga_criteria_params:
                         continue
                     
                     # Check valid numeric range
                     # CSV columns: Name, Value, Min, Max, Type
                     try:
                         pmin = float(row['Min'])
                         pmax = float(row['Max'])
                         ptype = str(row['Type']).lower() # int or float
                     except:
                         continue # Skip invalid/empty rows
                         
                     if ptype in ('int', 'float'):
                         if pmin != pmax:
                             param_names.append(n)
                             
                 print(f"Loaded {len(param_names)} param names using strict GA logic.")
        except Exception as e:
            print(f"Could not load param names from CSV: {e}")

    # If module didn't provide keys (it clears them), try to reconstruct
    if not param_names:
        # Fallback: Read keys from genetic_results CSV header if available
        RESULTS_FILE = r"Bollinger\parameters\genetic_results_2025-12-06-4.csv" # Most recent
        if os.path.exists(RESULTS_FILE):
             try:
                 df_res = pd.read_csv(RESULTS_FILE)
                 # Columns after Description and up to Solution_0...
                 # Actually the format is rows=params. 
                 # Name column contains param names.
                 # We need them in the *order* they were in the individual.
                 # This search is hard without the `param_keys` list used during creation.
                 # Let's rely on printing them by index if names fail.
                 pass
             except: pass

    cp = load_checkpoint(CHECKPOINT_FILE)
    if cp:
        # 1. Try to get param_keys from checkpoint root (some versions save it)
        if "param_keys" in cp:
            param_names = cp["param_keys"]
            print(f"Loaded {len(param_names)} param names from Checkpoint root.")
            
        # 2. Try to get from config dict
        elif "config" in cp and isinstance(cp["config"], dict):
            if "param_keys" in cp["config"]:
                param_names = cp["config"]["param_keys"]
                print(f"Loaded {len(param_names)} param names from Checkpoint Config.")
            elif "PARAM_KEYS" in cp["config"]:
                param_names = cp["config"]["PARAM_KEYS"]
                print(f"Loaded {len(param_names)} param names from Checkpoint Config (CAPS).")
        
        if not param_names:
            print("Warning: param_keys not found in checkpoint. Using CSV logic (risky).")
            # ... CSV logic remains as fallback ...
        
        # Redirect output to file
        print(f"Writing analysis report to analysis_report.txt...")
        original_stdout = sys.stdout
        try:
            with open("analysis_report.txt", "w") as f:
                sys.stdout = f
                analyze_history(cp, param_names)
        finally:
            sys.stdout = original_stdout
        print("Analysis complete.")

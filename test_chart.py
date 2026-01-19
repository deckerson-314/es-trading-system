import pickle
import os
import sys
import pandas as pd
from deap import base, creator

# Import restoration script
from restore_param_analysis import generate_interactive_analysis

# --- 1. SETUP DEAP CREATOR ---
try:
    creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 1.0, 2.0, 2.0))
    creator.create("Individual", list, fitness=creator.FitnessMulti)
    print("DEAP Creator setup complete.")
except Exception as e:
    print(f"DEAP Creator setup warning: {e}")

# --- 2. LOAD CHECKPOINT ---
cp_path = r"c:\Trading\ga_diagnostics_v4\ga_checkpoint_2026-01-06-2.pkl"
try:
    with open(cp_path, "rb") as f:
        cp = pickle.load(f)
    print("Checkpoint loaded successfully.")
except Exception as e:
    print(f"Error loading checkpoint: {e}")
    sys.exit(1)

# --- 3. EXTRACT DATA ---
hof = cp.get('hall_of_fame')
param_keys = cp.get('param_keys')
param_dict = cp.get('param_dict')
current_gen = cp.get('generation', 0)

if not hof:
    print("Error: No Hall of Fame found in checkpoint.")
    sys.exit(1)

# --- FALLBACK LOADING OF PARAMS ---
if not param_keys or not param_dict:
    print("Warning: param_keys/param_dict missing in checkpoint. Loading from CSV...")
    csv_path = r"c:\Trading\Bollinger\parameters\backtest_params.csv"
    try:
        df = pd.read_csv(csv_path)
        
        # Build param_dict
        param_dict = {}
        # Identify optimizable params (Min != Max or specific logic from GA)
        # GA typically includes ALL params in the genome that are marked optimizable?
        # Actually GA includes params where Min != Max.
        
        filtered_keys = []
        for _, row in df.iterrows():
            name = row['Name']
            if str(name).startswith('==') or pd.isna(name):
                continue
                
            p_val = row['Value']
            p_min = row['Min']
            p_max = row['Max']
            p_type = row['Type']
            
            # Create dict entry
            param_dict[name] = {
                'value': p_val,
                'min': p_min,
                'max': p_max,
                'type': p_type
            }
            
            # Check if optimizable (this logic must match BB_Genetic_v4.py exactly to match genome length)
            # BB_Genetic_v4.py logic usually: if min != max, it's gene.
            if p_min != p_max:
                filtered_keys.append(name)
                
        param_keys = filtered_keys
        print(f"Loaded {len(param_keys)} keys from CSV.")
        
        # Verify length matches Individual
        ind_len = len(hof[0])
        if len(param_keys) != ind_len:
            print(f"CRITICAL WARNING: Genome length ({ind_len}) != Params from CSV ({len(param_keys)}). Mapping will be wrong!")
            # Attempt to use all keys? Or just truncate?
            # If CSV has more keys, we might be in trouble.
    except Exception as e:
        print(f"Error loading CSV fallback: {e}")
        sys.exit(1)

# --- 4. GENERATE CHART ---
print(f"Generating Interactive Analysis for {len(hof)} solutions...")
try:
    div, script = generate_interactive_analysis(hof, param_keys, param_dict, current_gen)
except Exception as e:
    print(f"Error in generate_interactive_analysis: {e}")
    # Print stack trace
    import traceback
    traceback.print_exc()
    sys.exit(1)

if not div or not script:
    print("Error: Generated HTML components are empty.")
    sys.exit(1)

# --- 5. WRITE HTML ---
html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Test Interactive Chart</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{ font-family: sans-serif; padding: 20px; }}
        .container {{ width: 90%; margin: auto; border: 1px solid #ccc; padding: 10px; }}
    </style>
</head>
<body>
    <h1>Test Interactive Chart (Fast Gen)</h1>
    <p>Using checkpoint: {os.path.basename(cp_path)}</p>
    <div class="container">
        {div}
    </div>
    {script}
</body>
</html>
"""

out_path = r"c:\Trading\web\test_chart.html"
with open(out_path, "w") as f:
    f.write(html_content)

print(f"Done. Open {out_path} to verify.")

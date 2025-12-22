import pickle
import numpy as np
import pandas as pd
from bollinger_strategy.parameters import load_params

CHECKPOINT_FILE = 'ga_diagnostics_v4/ga_checkpoint_v4.pkl'
PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'

def analyze_gen_225():
    print(f"Loading {CHECKPOINT_FILE}...")
    with open(CHECKPOINT_FILE, 'rb') as f:
        checkpoint = pickle.load(f)
    
    logbook = checkpoint.get('logbook', [])
    pop = checkpoint.get('population', [])
    
    # Find Gen 225
    gen_225_record = None
    for record in logbook:
        if record['gen'] == 225:
            gen_225_record = record
            break
            
    if not gen_225_record:
        print("Generation 225 not found in logbook!")
        return

    print("="*60)
    print("ANALYSIS OF GENERATION 225")
    print("="*60)
    
    # metrics
    keys = ['avg_trades_day', 'max_trades_day', 'avg_sortino', 'max_sortino', 'avg_pf', 'max_pf', 'avg_dd', 'min_dd', 'pareto_size']
    for k in keys:
        val = gen_225_record.get(k, 'N/A')
        if isinstance(val, float):
             print(f"{k}: {val:.4f}")
        else:
             print(f"{k}: {val}")

    # Compare with trends (last 10 vs 225)
    # We can look at 215 for comparison if available
    gen_215_record = None
    for record in logbook:
        if record['gen'] == 215:
            gen_215_record = record
            break
    
    if gen_215_record:
        print("-" * 30)
        print("Trend (Gen 215 -> 225):")
        for k in ['avg_sortino', 'avg_trades_day', 'avg_pf']:
            try:
                v1 = gen_215_record.get(k, 0)
                v2 = gen_225_record.get(k, 0)
                change = v2 - v1
                print(f"  {k}: {v1:.4f} -> {v2:.4f} ({change:+.4f})")
            except:
                pass
    
    # Inspect Population if available (this is current pop, which is likely 226, but close enough)
    # Actually pop in checkpoint is the FINAL population (Gen 226). 
    # Calculating parameter stats from current population as proxy for 225 (only 1 gen difference)
    
    print("-" * 30)
    print("Current Population Parameter Stats (Gen ~226):")
    
    # Load param defs
    try:
        if os.path.exists(PARAM_CSV):
             param_dict, _ = load_params(PARAM_CSV, return_dataframe=True)
             
             # We need to know which indices map to which params. 
             # Assuming standard order (excluding fixed params). 
             # This part is tricky without exact mapping logic that matches GA.
             # I'll skip detailed per-param analysis here to avoid misalignment risk without verifying mapping.
             # But I can show top solutions if they are in 'hall_of_fame'
             
             hof = checkpoint.get('hall_of_fame', [])
             if hof:
                 print(f"Hall of Fame size: {len(hof)}")
                 print(f"Best Sortino in HoF: {hof[0].fitness.values[0] if hof[0].fitness.valid else 'N/A'}")
             
    except Exception as e:
        print(f"Could not load parameters or analyze population details: {e}")

if __name__ == "__main__":
    import os
    analyze_gen_225()

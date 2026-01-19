
import pickle
import os
import sys

# Add local directory to path to find modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from deap import base, creator

# Try to import strategy to ensure class definitions exist (if pickled)
try:
    from bollinger_strategy.strategy_v4 import BollingerBandStrategyV4
except:
    pass

# Ensure DEAP classes exist
if not hasattr(creator, "FitnessMulti"):
    creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 1.0, 2.0, 2.0))
if not hasattr(creator, "Individual"):
    creator.create("Individual", list, fitness=creator.FitnessMulti)

CHECKPOINT_FILE = os.path.join('ga_diagnostics_v4', 'ga_checkpoint_v4.pkl')

def inspect_pnl():
    if not os.path.exists(CHECKPOINT_FILE):
        print(f"Checkpoint not found: {CHECKPOINT_FILE}")
        # Try finding any checkpoint
        import glob
        files = glob.glob('ga_diagnostics_v4/ga_checkpoint_*.pkl')
        if files:
            CHECKPOINT_FILE = files[-1] # Use latest
            print(f"Using alternative checkpoint: {CHECKPOINT_FILE}")
        else:
            return

    try:
        with open(CHECKPOINT_FILE, "rb") as f:
            cp = pickle.load(f)
        
        pop = cp.get("population", [])
        hof = cp.get("halloffame", [])
        
        all_inds = list(pop) + list(hof)
        
        pnls = []
        dds = []
        for ind in all_inds:
            if ind.fitness.valid:
                # [4] is PnL, [1] is Drawdown
                pnls.append(ind.fitness.values[4])
                dds.append(ind.fitness.values[1])
                
        if not pnls:
             print("No valid fitness values found.")
             return

        print(f"Analyzed {len(pnls)} individuals.")
        print("\n--- PnL (Index 4) ---")
        print(f"Max: {max(pnls)}")
        print(f"Min: {min(pnls)}")
        print(f"Avg: {sum(pnls)/len(pnls)}")
        
        print("\n--- Drawdown (Index 1) ---")
        print(f"Max: {max(dds)}")
        print(f"Min: {min(dds)}")
        print(f"Avg: {sum(dds)/len(dds)}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_pnl()


import pickle
import sys

CHECKPOINT_FILE = r"C:\Trading\ga_diagnostics_v4\ga_checkpoint_2025-12-09-1.pkl"

try:
    with open(CHECKPOINT_FILE, "rb") as cp_file:
        cp = pickle.load(cp_file)
    
    print("Checkpoint Loaded Successfully.")
    print(f"Keys in checkpoint: {list(cp.keys())}")
    
    if "param_keys" in cp:
        print(f"Param Keys in Checkpoint: {len(cp['param_keys'])}")
        print(cp['param_keys'])
    else:
        print("NO 'param_keys' in checkpoint.")
        
    pop = cp.get("population", [])
    if pop:
        print(f"First Ind Length: {len(pop[0])}")
        print(f"First Ind Values: {pop[0]}")
        
except Exception as e:
    print(f"Error: {e}")

import pickle
import os

checkpoint_path = r"c:\Trading\Trend\diagnostics\ga_checkpoint_2026-04-24-1.pkl"
if os.path.exists(checkpoint_path):
    with open(checkpoint_path, "rb") as f:
        cp = pickle.load(f)
        print("Keys in checkpoint:", cp.keys())
        if 'halloffame' in cp:
            print("Found 'halloffame'")
        if 'hof' in cp:
            print("Found 'hof'")
else:
    print("Checkpoint not found")

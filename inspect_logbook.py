import pickle
import os

CHECKPOINT_FILE = 'Bollinger/diagnostics/ga_checkpoint_2026-04-17-1.pkl'

if os.path.exists(CHECKPOINT_FILE):
    with open(CHECKPOINT_FILE, 'rb') as f:
        checkpoint = pickle.load(f)
        logbook = checkpoint.get('logbook', {})
        if logbook:
            print("Logbook Header:", logbook.header)
            if len(logbook) > 0:
                print("First Generation record keys:", list(logbook[0].keys()))
        else:
            print("No logbook found in checkpoint.")
else:
    print(f"File not found: {CHECKPOINT_FILE}")


import pickle
import os

CHECKPOINT_FILE = 'Trend/diagnostics/ga_checkpoint_2026-04-12-2.pkl'

if os.path.exists(CHECKPOINT_FILE):
    with open(CHECKPOINT_FILE, 'rb') as f:
        checkpoint = pickle.load(f)
        
        gen = checkpoint.get('generation', 'Unknown')
        config = checkpoint.get('config', {})
        pop = checkpoint.get('population', [])
        
        print(f"Checkpoint Gen: {gen}")
        if 'Timeframe (minutes)' in config:
            tf = config['Timeframe (minutes)']
            print(f"Timeframe (minutes) in saved_config: {tf}")
        else:
            print("Timeframe (minutes) not found in saved_config")
            
        # Check actual values in population
        if pop:
            # Need to know the index of Timeframe.
            # It's better to just check the first individual's raw values if we can guess the index.
            # But wait! I'll check 'PARAM_CSV' in config.
            print(f"PARAM_CSV used in checkpoint: {config.get('PARAM_CSV', 'Unknown')}")
            
        # Print all config keys to see what's there
        print(f"Config Keys: {list(config.keys())}")
        
        # Look for normalization constants
        for k in ['NORM_PF_MAX', 'NORM_PNL_MAX']:
             if k in config:
                 print(f"{k}: {config[k]}")
else:
    print(f"File not found: {CHECKPOINT_FILE}")

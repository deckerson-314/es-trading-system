import pickle
import sys
import os

CHECKPOINT_FILE = 'ga_diagnostics_v4/ga_checkpoint_v4.pkl'
if len(sys.argv) > 1:
    CHECKPOINT_FILE = sys.argv[1]

print(f"Inspecting: {CHECKPOINT_FILE}")

try:
    with open(CHECKPOINT_FILE, 'rb') as f:
        cp = pickle.load(f)
    
    hof = cp.get('hall_of_fame', [])
    print(f"HOF Size: {len(hof)}")
    
    if 'config' in cp:
        print(f"Config Keys: {list(cp['config'].keys())}")
        if 'param_keys' in cp['config']:
            param_keys = cp['config']['param_keys']
        else:
            print("param_keys NOT in config. Attempting fallback load...")
            import pandas as pd
            try:
                # Load from default params file
                param_df = pd.read_csv('c:/Trading/Bollinger/parameters/backtest_params.csv')
                
                ga_criteria_params = set(['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                              'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                              'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                              'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT'])
                              
                valid_keys = []
                for idx, row in param_df.iterrows():
                    n = row['Name']
                    if n.startswith('===') or n.startswith('__'):
                        continue
                    if n in ga_criteria_params:
                        continue
                    # Check range and type
                    ptype = row['Type']
                    pmin = row['Min']
                    pmax = row['Max']
                    if ptype in ('int', 'float') and pmin != pmax:
                        valid_keys.append(n)
                        
                param_keys = valid_keys
                print(f"Loaded {len(param_keys)} keys from CSV using GA logic.")
            except Exception as e:
                print(f"Fallback failed: {e}")
                param_keys = []
    else:
        print("Config not found in checkpoint.")
        param_keys = []

    print("\n=== Top 10 Solutions Parameters ===")
    for i in range(min(10, len(hof))):
        ind = hof[i]
        params = dict(zip(param_keys, ind))
        print(f"\nRank {i+1}:")
        if 'Bollinger Band Length' in params:
            print(f"  BB Length: {params['Bollinger Band Length']}")
        if 'Bollinger Band StdDev' in params:
             print(f"  BB StdDev: {params['Bollinger Band StdDev']}")
        if 'Timeframe (minutes)' in params:
            print(f"  Timeframe: {params['Timeframe (minutes)']}")
        if 'Start Trading Hour' in params:
            print(f"  Start Hour: {params['Start Trading Hour']}")
        
        vals = ind.fitness.values
        # vals: Sortino, DD, PF, Trades, PnL
        print(f"  Fitness: Sortino={vals[0]:.4f}, TradeScore={vals[3]:.4f}")

except Exception as e:
    print(f"Error: {e}")

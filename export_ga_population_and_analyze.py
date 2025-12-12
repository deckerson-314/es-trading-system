
import pickle
import sys
import os
import pandas as pd
import numpy as np
from deap import base, creator, tools

# Ensure DEAP classes exist
if not hasattr(creator, "FitnessMulti"):
    creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 1.0, 2.0, 2.0))
if not hasattr(creator, "Individual"):
    creator.create("Individual", list, fitness=creator.FitnessMulti)

CHECKPOINT_FILE = r"C:\Trading\ga_diagnostics_v4\ga_checkpoint_2025-12-09-2.pkl"

def load_checkpoint(filepath):
    try:
        with open(filepath, "rb") as cp_file:
            cp = pickle.load(cp_file)
        return cp
    except Exception as e:
        print(f"Error loading checkpoint: {e}")
        return None

def analyze_population():
    print(f"Loading checkpoint: {CHECKPOINT_FILE}...")
    cp = load_checkpoint(CHECKPOINT_FILE)
    if not cp: return


    # Get Data
    pop = cp.get("population", [])
    hof = cp.get("halloffame", [])
    param_keys = cp.get("param_keys", [])
    
    if not param_keys and "config" in cp:
        param_keys = cp["config"].get("param_keys", [])

    # Dynamic CSV Loading Fallback
    if not param_keys:
        try:
            print("Loading param keys from backtest_params.csv...")
            df_params = pd.read_csv(r"C:\Trading\Bollinger\parameters\backtest_params.csv")
            
            # Exclusion list from BB_Genetic_v4.py (Modified to match Checkpoint 2025-12-08 structure)
            ga_criteria_params = set([
                'POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT',
                'NORM_SORTINO_MAX', 'NORM_DD_MAX', 'NORM_PF_MAX', 'NORM_TRADES_MAX', 
                'NORM_PNL_MAX', 'NORM_PROFIT_TRADE_MAX', 'MIN_WIN_RATE', 'SORTINO_CAP'
            ])
            
            param_keys = []
            for index, row in df_params.iterrows():
                n = row['Name']
                if str(n).startswith('===') or str(n).startswith('__'): continue
                if n in ga_criteria_params: continue
                
                try:
                    pmin = float(row['Min'])
                    pmax = float(row['Max'])
                    ptype = str(row['Type']).lower()
                    if ptype in ('int', 'float') and pmin != pmax:
                        param_keys.append(n)
                except: continue
                
            print(f"Loaded {len(param_keys)} keys from CSV.")
            print(f"Keys: {param_keys}")
            
        except Exception as e:
            print(f"Error loading params from CSV: {e}")

    # Fallback if CSV fails
    if not param_keys:
        # Debugging: check length of first ind to approximate
        if pop:
            print(f"DEBUG: Individual Length is {len(pop[0])}")
            # Generate dummy keys
            param_keys = [f"Param_{i}" for i in range(len(pop[0]))]
            # Try to map known indices for clustering
            # 1 = StdDev, 0 = Length? We'll see.
            print("Using dummy keys.")

    print(f"Loaded Population: {len(pop)} | Hall of Fame: {len(hof)}")
    print(f"Parameter Names: {len(param_keys)}")



    # Combine Pop + HOF for analysis (unique only)
    all_inds = pop + hof
    data = []
    
    # DEBUG parameter mismatch
    if all_inds:
        print(f"DEBUG: First Individual Length: {len(all_inds[0])}")
        print(f"DEBUG: Expected Param Keys Length: {len(param_keys)}")
    
    for i, ind in enumerate(all_inds):
        # Safety check for param length
        if len(ind) != len(param_keys):
            if i < 3: print(f"Skipping Ind {i}: Len {len(ind)} != Keys {len(param_keys)}")
            continue
            
        f = ind.fitness.values

        # (sortino, max_dd_penalty, profit_factor, n_trades, total_net_profit, avg_profit_trade)
        
        row = {k: v for k, v in zip(param_keys, ind)}
        row['Fitness_Sortino'] = f[0]
        row['Fitness_PnL'] = f[4] 
        row['Fitness_Trades'] = f[3]
        data.append(row)

    df = pd.DataFrame(data)
    # Remove duplicates
    subset_cols = [c for c in param_keys if c in df.columns]
    df = df.drop_duplicates(subset=subset_cols)
    
    print(f"Unique Solutions Analyzed: {len(df)}")
    
    if len(df) < 5:
        print("Not enough data for clustering.")
        return

    # --- CLUSTER ANALYSIS (Manual Binning) ---
    print("\n" + "="*60)
    print("STRATEGY CLUSTER ANALYSIS (Manual Groups)")
    print("="*60)

    # Define Manual Clusters
    def classify(row):
        std = row.get('Bollinger Band StdDev', 2.0)
        atr_filt = row.get('Max ATR Filter (Points)', 100)
        
        if std >= 3.0: return 'Sniper (Extreme Reversion)'
        elif std <= 2.5: return 'Conventional (Standard Bands)'
        else: return 'Hybrid (Wide Bands)'

    df['Strategy_Type'] = df.apply(classify, axis=1)
    
    grouped = df.groupby('Strategy_Type')
    
    for name, group in grouped:
        print(f"\n[CLUSTER: {name}] - Size: {len(group)}")
        print(f"  Avg PnL: ${group['Fitness_PnL'].mean():,.2f} | Avg Sortino: {group['Fitness_Sortino'].mean():.2f}")
        print(f"  Avg Trades: {group['Fitness_Trades'].mean():.1f}")
        
        # Best within cluster
        best_sol = group.sort_values('Fitness_Sortino', ascending=False).iloc[0]
        print(f"  Representative (Best) Solution:")
        print(f"    Sortino: {best_sol['Fitness_Sortino']:.4f} | PnL: ${best_sol['Fitness_PnL']:,.2f}")
        
        # Print Key Params for the best
        params_to_show = ['Bollinger Band StdDev', 'Bollinger Band Length', 'ATR Multiplier for TP', 'Max ATR Filter (Points)', 'Enable ADX Filter', 'Max ADX Threshold', 'ADX Period']
        for p in params_to_show:
            if p in best_sol:
                print(f"    {p}: {best_sol[p]}")

if __name__ == "__main__":
    analyze_population()

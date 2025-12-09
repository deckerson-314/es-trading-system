import pickle
import sys
import os
import pandas as pd
import numpy as np
from deap import base, creator, tools

# Define DEAP classes (required for unpickling)
if hasattr(creator, "FitnessMulti"):
    del creator.FitnessMulti
if hasattr(creator, "Individual"):
    del creator.Individual

# Attempt to recreate Creator classes
try:
    creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 1.0, 2.0, 2.0))
    creator.create("Individual", list, fitness=creator.FitnessMulti)
except:
    pass

CHECKPOINT_FILE = r"c:\Trading\ga_diagnostics_v4\ga_checkpoint_v4.pkl"

def analyze_checkpoint():
    if not os.path.exists(CHECKPOINT_FILE):
        print(f"Checkpoint file not found: {CHECKPOINT_FILE}")
        return

    print(f"Analyzing Checkpoint: {os.path.basename(CHECKPOINT_FILE)}")
    
    try:
        with open(CHECKPOINT_FILE, 'rb') as f:
            cp = pickle.load(f)
            
        print(f"Generation: {cp.get('generation', 'Unknown')}")
        
        hof = cp.get('hall_of_fame', [])
        print(f"Hall of Fame Size: {len(hof)}")
        
        if not hof:
            print("HOF is empty.")
            return

        # Extract data from HOF
        data = []
        for i, ind in enumerate(hof):
            if hasattr(ind, 'fitness') and ind.fitness.valid:
                vals = ind.fitness.values
                # vals order: Sortino, DD, PF, Trades, Total PnL, Avg PnL/Trade
                
                trade_val = vals[3] if len(vals) > 3 else 0
                avg_pnl_trade_norm = vals[5] if len(vals) > 5 else 0
                
                row = {
                    'Rank': i+1,
                    'Sortino': vals[0],
                    'MaxDD_Norm': vals[1],
                    'ProfitFactor': vals[2],
                    'TradeScore': trade_val,
                    'TotalProfit_Norm': vals[4] if len(vals) > 4 else 0,
                    'AvgProfitTrade_Norm': avg_pnl_trade_norm,
                    'BB_Length': ind[0] if len(ind) > 0 else 0,
                    'BB_StdDev': ind[1] if len(ind) > 1 else 0
                }
                data.append(row)
        
        df = pd.DataFrame(data)
        
        print("\n=== Top 10 Solutions (HOF) ===")
        print(df.head(10).to_string(index=False))
        
        print("\n=== Performance Stats (HOF) ===")
        print(df.describe())
        
        # Analyze Avg Profit Trade
        print("\n=== Avg Profit/Trade Analysis ===")
        print(f"Max Norm Score: {df['AvgProfitTrade_Norm'].max():.4f}")
        print(f"Avg Norm Score: {df['AvgProfitTrade_Norm'].mean():.4f}")
        
        print("\n=== BB Length Distribution (Top 20) ===")
        print(df.head(20)['BB_Length'].value_counts())
        
        print("\n=== BB StdDev Distribution (Top 20) ===")
        print(df.head(20)['BB_StdDev'].value_counts())

    except Exception as e:
        print(f"Error reading checkpoint: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    analyze_checkpoint()

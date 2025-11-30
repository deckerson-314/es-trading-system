#!/usr/bin/env python3
"""
Analyze discrepancies between fitness values and actual backtest results in GA run.
"""

import pickle
import os
import pandas as pd
import numpy as np
from deap import creator, base

CHECKPOINT_FILE = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'

print("="*80)
print("ANALYZING GA DISCREPANCIES")
print("="*80)

# Load checkpoint
if not os.path.exists(CHECKPOINT_FILE):
    print(f"ERROR: Checkpoint not found: {CHECKPOINT_FILE}")
    exit(1)

with open(CHECKPOINT_FILE, 'rb') as f:
    checkpoint = pickle.load(f)

hof = checkpoint.get('hall_of_fame', [])
logbook = checkpoint.get('logbook', None)
gen = checkpoint.get('generation', 0)

print(f"Generation: {gen}")
print(f"Pareto Solutions: {len(hof)}")
print()

# Analyze logbook records
if logbook:
    print("="*80)
    print("LOGBOOK ANALYSIS (Convergence Chart Data)")
    print("="*80)
    
    gens = logbook.select("gen")
    if len(gens) > 0:
        last_gen = gens[-1]
        last_record = logbook[last_gen]
        
        print(f"Last Generation ({last_gen}) Logbook Record:")
        print(f"  avg_sortino: {last_record.get('avg_sortino', 'N/A')}")
        print(f"  max_sortino: {last_record.get('max_sortino', 'N/A')}")
        print(f"  avg_pf: {last_record.get('avg_pf', 'N/A')}")
        print(f"  max_pf: {last_record.get('max_pf', 'N/A')}")
        print(f"  avg_trades_day: {last_record.get('avg_trades_day', 'N/A')}")
        print(f"  avg_total_profit: {last_record.get('avg_total_profit', 'N/A')}")
        print()
        print("⚠️  NOTE: These are NORMALIZED FITNESS VALUES (0-1 range), not actual backtest results!")
        print("   - Sortino: normalized to 0-1 (actual = normalized × NORM_SORTINO_MAX)")
        print("   - Drawdown: normalized and inverted (0-1, where 1 = best)")
        print("   - Profit Factor: normalized to 0-1 (actual = normalized × NORM_PF_MAX)")
        print("   - Trades/Day: RAW value (not normalized after our fix)")
        print("   - Total Profit: normalized to 0-1 (actual = normalized × NORM_PNL_MAX)")
        print()
        print("When solutions hit hard constraints (negative Sortino, negative PNL, win rate < 40%):")
        print("   - Fitness values become -inf (or -1000 if there's an error)")
        print("   - This is why convergence charts show -1000 for Sortino")
        print()

# Analyze Hall of Fame (All Solutions section)
if hof and len(hof) > 0:
    print("="*80)
    print("HALL OF FAME ANALYSIS (All Solutions Section)")
    print("="*80)
    
    print(f"Analyzing {len(hof)} Pareto-optimal solutions...")
    print()
    
    solutions = []
    for i, ind in enumerate(hof):
        if hasattr(ind, 'fitness') and ind.fitness.valid:
            fitness = ind.fitness.values
            if len(fitness) >= 5:
                solutions.append({
                    'index': i,
                    'sortino_fitness': fitness[0],
                    'dd_fitness': fitness[1],
                    'pf_fitness': fitness[2],
                    'trades_fitness': fitness[3],
                    'pnl_fitness': fitness[4]
                })
    
    if solutions:
        solutions_df = pd.DataFrame(solutions)
        
        print("Fitness Values (what's shown in 'All Solutions' section):")
        print(f"  Sortino: Min={solutions_df['sortino_fitness'].min():.6f}, Max={solutions_df['sortino_fitness'].max():.6f}, Mean={solutions_df['sortino_fitness'].mean():.6f}")
        print(f"  Drawdown: Min={solutions_df['dd_fitness'].min():.6f}, Max={solutions_df['dd_fitness'].max():.6f}, Mean={solutions_df['dd_fitness'].mean():.6f}")
        print(f"  Profit Factor: Min={solutions_df['pf_fitness'].min():.6f}, Max={solutions_df['pf_fitness'].max():.6f}, Mean={solutions_df['pf_fitness'].mean():.6f}")
        print(f"  Trades/Day: Min={solutions_df['trades_fitness'].min():.6f}, Max={solutions_df['trades_fitness'].max():.6f}, Mean={solutions_df['trades_fitness'].mean():.6f}")
        print(f"  Total Profit: Min={solutions_df['pnl_fitness'].min():.6f}, Max={solutions_df['pnl_fitness'].max():.6f}, Mean={solutions_df['pnl_fitness'].mean():.6f}")
        print()
        
        # Check for hard constraint penalties
        hard_constraint_count = sum(1 for s in solutions if s['sortino_fitness'] == float('-inf') or (s['sortino_fitness'] < -100 and s['sortino_fitness'] != float('-inf')))
        if hard_constraint_count > 0:
            print(f"🔴 {hard_constraint_count} solutions hit hard constraints (Sortino = -inf or < -100)")
            print(f"   These solutions are eliminated from optimization")
            print(f"   They may still appear in 'All Solutions' but with invalid fitness values")
        print()
        
        print("⚠️  CRITICAL UNDERSTANDING:")
        print("   'All Solutions' section shows FITNESS VALUES (normalized 0-1), not actual backtest results!")
        print("   - Sortino fitness = normalized Sortino (0-1 range)")
        print("   - Drawdown fitness = normalized and inverted (1 = best, 0 = worst)")
        print("   - Profit Factor fitness = normalized PF (0-1 range)")
        print("   - Trades/Day = RAW value (actual trades/day after our fix)")
        print("   - Total Profit fitness = normalized PNL (0-1 range)")
        print()
        print("   To see ACTUAL backtest results, look at 'Actual Backtest Results (In-Sample)' section")
        print("   which runs a real backtest on the selected solution.")

print("="*80)
print("ROOT CAUSE")
print("="*80)
print()
print("The discrepancies you're seeing are because:")
print()
print("1. **Convergence Charts**: Use normalized fitness values from logbook")
print("   - These are 0-1 range for optimization")
print("   - When solutions hit hard constraints, they get -inf (shows as -1000)")
print("   - This is why Sortino shows -1000 (solution hit hard constraint)")
print()
print("2. **'All Solutions' Section**: Uses fitness.values directly")
print("   - These are normalized fitness values, not actual backtest results")
print("   - Sortino -1000 = hard constraint penalty (solution eliminated)")
print("   - Profit Factor 0 = normalized value is 0 (actual might be different)")
print()
print("3. **'Actual Backtest Results' Section**: Runs real backtest")
print("   - This shows ACTUAL metrics from running the strategy")
print("   - Sortino 0.271443 = real Sortino Ratio")
print("   - Profit Factor 0.810510 = real Profit Factor")
print()
print("4. **Total Profit showing 0**:")
print("   - Convergence chart uses avg_total_profit from logbook")
print("   - This is normalized fitness[4] (0-1 range)")
print("   - If all solutions hit hard constraints, this becomes 0")
print("   - Actual backtest shows real PNL (which is negative)")
print()
print("="*80)
print("RECOMMENDATION")
print("="*80)
print()
print("The HTML should:")
print("1. Add clear notes explaining fitness values vs actual backtest results")
print("2. For 'All Solutions', either:")
print("   a) Run actual backtests for each solution (expensive but accurate)")
print("   b) Denormalize fitness values to show approximate actual values")
print("   c) Add a note explaining these are normalized fitness values")
print("3. For convergence charts, add a note that these are normalized fitness values")
print("   used for optimization, not actual backtest results")
print()
print("="*80)


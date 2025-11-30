#!/usr/bin/env python3
"""
Analyze whether hard constraints are preventing GA exploration.
"""

import pickle
import os
import pandas as pd
import numpy as np
from deap import creator, base

CHECKPOINT_FILE = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'

print("="*80)
print("ANALYZING HARD CONSTRAINTS IMPACT ON GA EXPLORATION")
print("="*80)

# Load checkpoint
if not os.path.exists(CHECKPOINT_FILE):
    print(f"ERROR: Checkpoint not found: {CHECKPOINT_FILE}")
    exit(1)

with open(CHECKPOINT_FILE, 'rb') as f:
    checkpoint = pickle.load(f)

hof = checkpoint.get('hall_of_fame', [])
pop = checkpoint.get('population', [])
gen = checkpoint.get('generation', 0)

print(f"Generation: {gen}")
print(f"Population Size: {len(pop)}")
print(f"Pareto Solutions: {len(hof)}")
print()

# Analyze population fitness values
if pop and len(pop) > 0:
    print("="*80)
    print("POPULATION FITNESS ANALYSIS")
    print("="*80)
    
    fitness_values = []
    for ind in pop:
        if hasattr(ind, 'fitness') and ind.fitness.valid:
            fitness = ind.fitness.values
            if len(fitness) >= 5:
                fitness_values.append({
                    'sortino': fitness[0],
                    'dd': fitness[1],
                    'pf': fitness[2],
                    'trades': fitness[3],
                    'pnl': fitness[4]
                })
    
    if fitness_values:
        df = pd.DataFrame(fitness_values)
        
        # Count hard constraint violations
        hard_constraint_count = sum(1 for f in fitness_values if f['sortino'] == float('-inf') or (f['sortino'] < -100 and f['sortino'] != float('-inf')))
        valid_count = len(fitness_values) - hard_constraint_count
        
        print(f"Total Individuals: {len(fitness_values)}")
        print(f"Hard Constraint Violations: {hard_constraint_count} ({hard_constraint_count/len(fitness_values)*100:.1f}%)")
        print(f"Valid Solutions: {valid_count} ({valid_count/len(fitness_values)*100:.1f}%)")
        print()
        
        if hard_constraint_count == len(fitness_values):
            print("🔴 CRITICAL: ALL solutions hit hard constraints!")
            print("   This means the GA cannot explore the solution space.")
            print("   Every solution it tries gets eliminated immediately.")
            print()
            print("   Why this happens:")
            print("   1. Hard constraints are too strict")
            print("   2. Initial population is all unprofitable")
            print("   3. GA cannot evolve from unprofitable to profitable")
            print("   4. No solutions survive to next generation")
            print()
            print("   This is a classic GA problem: premature elimination prevents exploration.")
            print()
        
        # Analyze trade frequency distribution
        print("Trade Frequency Distribution:")
        valid_trades = [f['trades'] for f in fitness_values if f['trades'] > 0]
        if valid_trades:
            print(f"  Solutions with trades > 0: {len(valid_trades)}")
            print(f"  Min trades/day: {min(valid_trades):.6f}")
            print(f"  Max trades/day: {max(valid_trades):.6f}")
            print(f"  Mean trades/day: {np.mean(valid_trades):.6f}")
            print(f"  Median trades/day: {np.median(valid_trades):.6f}")
        else:
            print("  ⚠️  No solutions with trades > 0!")
            print("     This suggests hard constraints are eliminating solutions")
            print("     before they can be evaluated properly.")
        print()
        
        # Analyze fitness value ranges
        print("Fitness Value Ranges (excluding hard constraint violations):")
        valid_fitness = [f for f in fitness_values if f['sortino'] != float('-inf') and f['sortino'] > -100]
        if valid_fitness:
            valid_df = pd.DataFrame(valid_fitness)
            print(f"  Sortino: Min={valid_df['sortino'].min():.6f}, Max={valid_df['sortino'].max():.6f}, Mean={valid_df['sortino'].mean():.6f}")
            print(f"  Drawdown: Min={valid_df['dd'].min():.6f}, Max={valid_df['dd'].max():.6f}, Mean={valid_df['dd'].mean():.6f}")
            print(f"  Profit Factor: Min={valid_df['pf'].min():.6f}, Max={valid_df['pf'].max():.6f}, Mean={valid_df['pf'].mean():.6f}")
            print(f"  Trades/Day: Min={valid_df['trades'].min():.6f}, Max={valid_df['trades'].max():.6f}, Mean={valid_df['trades'].mean():.6f}")
        else:
            print("  ⚠️  No valid solutions to analyze!")
            print("     All solutions hit hard constraints.")

# Analyze Hall of Fame
if hof and len(hof) > 0:
    print()
    print("="*80)
    print("HALL OF FAME ANALYSIS")
    print("="*80)
    
    hof_fitness = []
    for ind in hof:
        if hasattr(ind, 'fitness') and ind.fitness.valid:
            fitness = ind.fitness.values
            if len(fitness) >= 5:
                hof_fitness.append({
                    'sortino': fitness[0],
                    'dd': fitness[1],
                    'pf': fitness[2],
                    'trades': fitness[3],
                    'pnl': fitness[4]
                })
    
    if hof_fitness:
        hof_df = pd.DataFrame(hof_fitness)
        
        hard_constraint_hof = sum(1 for f in hof_fitness if f['sortino'] == float('-inf') or (f['sortino'] < -100 and f['sortino'] != float('-inf')))
        
        print(f"Pareto Solutions: {len(hof_fitness)}")
        print(f"Hard Constraint Violations: {hard_constraint_hof} ({hard_constraint_hof/len(hof_fitness)*100:.1f}%)")
        print()
        
        if hard_constraint_hof == len(hof_fitness):
            print("🔴 CRITICAL: ALL Pareto solutions hit hard constraints!")
            print("   This means the GA found NO valid solutions.")
            print("   The entire Pareto front consists of eliminated solutions.")
            print()
        
        # Trade frequency in Pareto front
        hof_trades = [f['trades'] for f in hof_fitness if f['trades'] > 0]
        if hof_trades:
            print(f"Trade Frequency in Pareto Front:")
            print(f"  Solutions with trades > 0: {len(hof_trades)}")
            print(f"  Min: {min(hof_trades):.6f}, Max: {max(hof_trades):.6f}, Mean: {np.mean(hof_trades):.6f}")
        else:
            print("⚠️  No Pareto solutions with trades > 0")
            print("   This confirms hard constraints are preventing exploration")

print()
print("="*80)
print("ROOT CAUSE ANALYSIS")
print("="*80)
print()
print("The locked parameter test reveals a critical issue:")
print()
print("1. **Hard Constraints Are Too Strict**")
print("   - Solutions that are unprofitable are immediately eliminated")
print("   - The GA cannot explore from unprofitable → profitable")
print("   - This prevents evolution and exploration")
print()
print("2. **Initial Population Problem**")
print("   - If initial random population is all unprofitable")
print("   - And hard constraints eliminate all unprofitable solutions")
print("   - Then the GA has nothing to work with")
print("   - It cannot evolve because there are no survivors")
print()
print("3. **Exploration vs Exploitation Trade-off**")
print("   - Hard constraints favor exploitation (only keep good solutions)")
print("   - But GAs need exploration (try bad solutions to find good ones)")
print("   - Too strict constraints prevent exploration")
print()
print("4. **Why GA Can't Find Solutions with Reasonable Trades**")
print("   - If all solutions with reasonable trades are unprofitable initially")
print("   - Hard constraints eliminate them immediately")
print("   - GA cannot evolve them to become profitable")
print("   - GA is forced to find solutions with very few trades (which may")
print("     pass constraints but are not useful)")
print()
print("="*80)
print("RECOMMENDATIONS")
print("="*80)
print()
print("1. **Convert Hard Constraints to Soft Penalties**")
print("   - Instead of eliminating solutions (-inf fitness)")
print("   - Apply heavy penalties (reduce fitness significantly)")
print("   - This allows GA to explore unprofitable regions")
print("   - GA can evolve from unprofitable → profitable")
print()
print("2. **Relax Hard Constraints Temporarily**")
print("   - Start with lenient constraints (e.g., allow negative Sortino)")
print("   - Let GA explore and find promising regions")
print("   - Gradually tighten constraints as GA converges")
print()
print("3. **Use Graduated Penalties**")
print("   - Small violations: small penalty")
print("   - Large violations: large penalty")
print("   - Extreme violations: very large penalty (but not elimination)")
print("   - This allows exploration while still discouraging bad solutions")
print()
print("4. **Separate Exploration and Exploitation Phases**")
print("   - Phase 1: Exploration (lenient constraints, find promising regions)")
print("   - Phase 2: Exploitation (strict constraints, refine good solutions)")
print()
print("5. **Monitor Constraint Violation Rate**")
print("   - If >90% of solutions hit constraints, constraints are too strict")
print("   - Adjust constraints dynamically based on violation rate")
print()
print("="*80)


#!/usr/bin/env python3
"""
Diagnostic to understand why weight=100.0 on trades/day isn't working.
This addresses the fundamental issue: are we treating symptoms vs disease?
"""

import os
import pickle
import pandas as pd
import numpy as np
from deap import creator, base

CHECKPOINT_FILE = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'

def load_checkpoint():
    """Load GA checkpoint."""
    if not os.path.exists(CHECKPOINT_FILE):
        print(f"ERROR: Checkpoint file not found: {CHECKPOINT_FILE}")
        return None
    
    with open(CHECKPOINT_FILE, 'rb') as f:
        checkpoint = pickle.load(f)
    
    return checkpoint

def diagnose_weight_issue():
    """Comprehensive diagnostic on why weights aren't working."""
    checkpoint = load_checkpoint()
    if checkpoint is None:
        return
    
    pop = checkpoint.get('population', [])
    hof = checkpoint.get('hall_of_fame', [])
    gen = checkpoint.get('generation', 0)
    
    print("="*80)
    print("FUNDAMENTAL DIAGNOSTIC: WHY ISN'T WEIGHT=100.0 WORKING?")
    print("="*80)
    print(f"Generation: {gen}")
    print()
    
    # Get weights
    if hasattr(creator, 'FitnessMulti'):
        weights = creator.FitnessMulti.weights
        print(f"Current Fitness Weights: {weights}")
        print(f"  Sortino: {weights[0]}")
        print(f"  Drawdown: {weights[1]} (minimize)")
        print(f"  Profit Factor: {weights[2]}")
        print(f"  Avg Trades/Day: {weights[3]} ⚠️")
        print(f"  Total Profit: {weights[4]}")
        print()
    else:
        print("ERROR: FitnessMulti not found!")
        return
    
    if pop and len(pop) > 0:
        print("="*80)
        print("ANALYZING POPULATION: WHY WEIGHTS AREN'T WORKING")
        print("="*80)
        
        # Analyze fitness values
        solutions = []
        for i, ind in enumerate(pop):
            if hasattr(ind, 'fitness') and ind.fitness.valid:
                fitness = ind.fitness.values
                if len(fitness) >= 5:
                    # These are NORMALIZED values (0-1 range)
                    sortino_norm = fitness[0]
                    dd_norm = fitness[1]
                    pf_norm = fitness[2]
                    trades_norm = fitness[3]
                    pnl_norm = fitness[4]
                    
                    # Calculate weighted contributions
                    sortino_contrib = sortino_norm * weights[0]
                    dd_contrib = dd_norm * weights[1]  # Negative weight, so this is negative
                    pf_contrib = pf_norm * weights[2]
                    trades_contrib = trades_norm * weights[3]
                    pnl_contrib = pnl_norm * weights[4]
                    
                    # Total weighted fitness (if NSGA-II used weighted sum, which it doesn't)
                    weighted_sum = sortino_contrib + dd_contrib + pf_contrib + trades_contrib + pnl_contrib
                    
                    solutions.append({
                        'idx': i,
                        'sortino_norm': sortino_norm,
                        'dd_norm': dd_norm,
                        'pf_norm': pf_norm,
                        'trades_norm': trades_norm,
                        'pnl_norm': pnl_norm,
                        'sortino_contrib': sortino_contrib,
                        'dd_contrib': dd_contrib,
                        'pf_contrib': pf_contrib,
                        'trades_contrib': trades_contrib,
                        'pnl_contrib': pnl_contrib,
                        'weighted_sum': weighted_sum
                    })
        
        if solutions:
            solutions_df = pd.DataFrame(solutions)
            
            print(f"\nPopulation Analysis ({len(solutions)} valid solutions):")
            print(f"\nNormalized Values (what NSGA-II sees):")
            print(f"  Sortino: Min={solutions_df['sortino_norm'].min():.6f}, Max={solutions_df['sortino_norm'].max():.6f}, Mean={solutions_df['sortino_norm'].mean():.6f}")
            print(f"  Drawdown: Min={solutions_df['dd_norm'].min():.6f}, Max={solutions_df['dd_norm'].max():.6f}, Mean={solutions_df['dd_norm'].mean():.6f}")
            print(f"  Profit Factor: Min={solutions_df['pf_norm'].min():.6f}, Max={solutions_df['pf_norm'].max():.6f}, Mean={solutions_df['pf_norm'].mean():.6f}")
            print(f"  Trades/Day: Min={solutions_df['trades_norm'].min():.6f}, Max={solutions_df['trades_norm'].max():.6f}, Mean={solutions_df['trades_norm'].mean():.6f} ⚠️")
            print(f"  Total Profit: Min={solutions_df['pnl_norm'].min():.6f}, Max={solutions_df['pnl_norm'].max():.6f}, Mean={solutions_df['pnl_norm'].mean():.6f}")
            
            print(f"\nWeighted Contributions (if NSGA-II used weighted sum):")
            print(f"  Sortino: Min={solutions_df['sortino_contrib'].min():.6f}, Max={solutions_df['sortino_contrib'].max():.6f}, Mean={solutions_df['sortino_contrib'].mean():.6f}")
            print(f"  Drawdown: Min={solutions_df['dd_contrib'].min():.6f}, Max={solutions_df['dd_contrib'].max():.6f}, Mean={solutions_df['dd_contrib'].mean():.6f}")
            print(f"  Profit Factor: Min={solutions_df['pf_contrib'].min():.6f}, Max={solutions_df['pf_contrib'].max():.6f}, Mean={solutions_df['pf_contrib'].mean():.6f}")
            print(f"  Trades/Day: Min={solutions_df['trades_contrib'].min():.6f}, Max={solutions_df['trades_contrib'].max():.6f}, Mean={solutions_df['trades_contrib'].mean():.6f} ⚠️")
            print(f"  Total Profit: Min={solutions_df['pnl_contrib'].min():.6f}, Max={solutions_df['pnl_contrib'].max():.6f}, Mean={solutions_df['pnl_contrib'].mean():.6f}")
            
            # Check if trades contribution is actually dominating
            max_trades_contrib = solutions_df['trades_contrib'].max()
            max_sortino_contrib = solutions_df['sortino_contrib'].max()
            max_pf_contrib = solutions_df['pf_contrib'].max()
            
            print(f"\n{'='*80}")
            print("CRITICAL ANALYSIS")
            print("="*80)
            print(f"\nMaximum Contributions:")
            print(f"  Trades/Day: {max_trades_contrib:.6f} (weight={weights[3]})")
            print(f"  Sortino: {max_sortino_contrib:.6f} (weight={weights[0]})")
            print(f"  Profit Factor: {max_pf_contrib:.6f} (weight={weights[2]})")
            
            if max_trades_contrib > max_sortino_contrib and max_trades_contrib > max_pf_contrib:
                print(f"\n✓ Trades contribution IS the largest")
                print(f"  But NSGA-II doesn't use weighted sum - it uses Pareto dominance!")
            else:
                print(f"\n🔴 Trades contribution is NOT the largest!")
                print(f"  Even with weight=100.0, trades contribution ({max_trades_contrib:.6f}) is smaller than")
                print(f"  Sortino ({max_sortino_contrib:.6f}) or PF ({max_pf_contrib:.6f})")
                print(f"  This is because normalized trade frequency is SO SMALL!")
            
            # Show top solutions
            solutions_df = solutions_df.sort_values('trades_contrib', ascending=False)
            print(f"\n{'='*80}")
            print("TOP 10 SOLUTIONS BY TRADE FREQUENCY CONTRIBUTION")
            print("="*80)
            print(f"{'Rank':<6} {'Trades Contrib':<18} {'Trades Norm':<15} {'Sortino Contrib':<18} {'Sortino Norm':<15} {'Weighted Sum':<15}")
            print("-"*90)
            for rank, (idx, row) in enumerate(solutions_df.head(10).iterrows(), 1):
                print(f"{rank:<6} {row['trades_contrib']:<18.6f} {row['trades_norm']:<15.6f} {row['sortino_contrib']:<18.6f} {row['sortino_norm']:<15.6f} {row['weighted_sum']:<15.6f}")
            
            # Check Pareto front
            if hof and len(hof) > 0:
                print(f"\n{'='*80}")
                print("PARETO FRONT ANALYSIS")
                print("="*80)
                print(f"Pareto Solutions: {len(hof)}")
                
                pareto_trades = []
                pareto_sortino = []
                for ind in hof:
                    if hasattr(ind, 'fitness') and ind.fitness.valid:
                        fitness = ind.fitness.values
                        if len(fitness) >= 5:
                            trades_norm = fitness[3]
                            sortino_norm = fitness[0]
                            trades_contrib = trades_norm * weights[3]
                            sortino_contrib = sortino_norm * weights[0]
                            pareto_trades.append(trades_contrib)
                            pareto_sortino.append(sortino_contrib)
                
                if pareto_trades:
                    print(f"\nPareto Front Weighted Contributions:")
                    print(f"  Trades/Day: Max={max(pareto_trades):.6f}, Mean={np.mean(pareto_trades):.6f}")
                    print(f"  Sortino: Max={max(pareto_sortino):.6f}, Mean={np.mean(pareto_sortino):.6f}")
                    
                    if max(pareto_trades) > max(pareto_sortino):
                        print(f"\n✓ Pareto front DOES have solutions with high trade contribution")
                    else:
                        print(f"\n🔴 Pareto front does NOT prioritize trade frequency!")
                        print(f"   Even in Pareto-optimal solutions, Sortino contribution is higher")
    
    # Root cause analysis
    print(f"\n{'='*80}")
    print("ROOT CAUSE ANALYSIS")
    print("="*80)
    
    print(f"\n🔴 THE FUNDAMENTAL PROBLEM:")
    print(f"   NSGA-II uses PARETO DOMINANCE, not weighted sum!")
    print(f"   ")
    print(f"   How NSGA-II works:")
    print(f"   1. Solutions are ranked by Pareto dominance (not weighted sum)")
    print(f"   2. Solution A dominates B if A is better in AT LEAST ONE objective")
    print(f"      AND A is not worse in ANY objective")
    print(f"   3. Weights only affect SELECTION PRESSURE, not dominance")
    print(f"   ")
    print(f"   Example:")
    print(f"   Solution A: Sortino=0.2, Trades=0.01 (contrib: 0.2 + 1.0 = 1.2)")
    print(f"   Solution B: Sortino=0.1, Trades=0.02 (contrib: 0.1 + 2.0 = 2.1)")
    print(f"   ")
    print(f"   Even though B has higher weighted sum (2.1 > 1.2),")
    print(f"   A may still be in Pareto front if it's not dominated!")
    print(f"   ")
    print(f"   If ALL solutions have low trade frequency (< 0.01 normalized),")
    print(f"   then trade frequency becomes a 'tie-breaker' but doesn't drive selection!")
    
    print(f"\n{'='*80}")
    print("WHY NORMALIZATION IS THE REAL PROBLEM")
    print("="*80)
    
    print(f"\n   If actual trade frequency is 0.1 trades/day:")
    print(f"   - Normalized: 0.1 / 3.0 = 0.033")
    print(f"   - Weighted: 0.033 × 100 = 3.3")
    print(f"   ")
    print(f"   If Sortino is 0.2 (normalized):")
    print(f"   - Weighted: 0.2 × 1.0 = 0.2")
    print(f"   ")
    print(f"   Even with weight=100, trades contribution (3.3) is only 16.5× Sortino (0.2)")
    print(f"   But if ALL solutions have trades < 0.01 normalized, then:")
    print(f"   - Max trades contribution = 0.01 × 100 = 1.0")
    print(f"   - This is still small compared to other objectives!")
    
    print(f"\n{'='*80}")
    print("RECOMMENDED SOLUTIONS")
    print("="*80)
    
    print(f"\n1. 🔴 REMOVE NORMALIZATION for trade frequency:")
    print(f"   - Use actual trades/day directly (0.1, 0.5, 1.0, etc.)")
    print(f"   - This makes the scale match other objectives")
    print(f"   - Weight=100.0 will then have real impact")
    
    print(f"\n2. 🔴 OR: Use much smaller normalization range:")
    print(f"   - If max is 0.5 trades/day, use NORM_TRADES_MAX = 0.5")
    print(f"   - Then 0.1 trades/day normalizes to 0.2 (not 0.033)")
    print(f"   - Weighted: 0.2 × 100 = 20 (much better!)")
    
    print(f"\n3. 🔴 OR: Remove normalization entirely:")
    print(f"   - Use raw values with appropriate weights")
    print(f"   - Sortino: 0-10 range, weight=1.0")
    print(f"   - Trades: 0-1 range, weight=10.0 (not 100.0)")
    print(f"   - This is more intuitive and easier to tune")
    
    print(f"\n4. ⚠️  OR: Accept that NSGA-II maintains diversity:")
    print(f"   - It will keep solutions across the Pareto front")
    print(f"   - Not just those with highest trade frequency")
    print(f"   - This is by design - it finds trade-offs")
    
    print(f"\n{'='*80}")

if __name__ == '__main__':
    diagnose_weight_issue()


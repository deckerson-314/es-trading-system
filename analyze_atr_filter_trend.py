#!/usr/bin/env python3
"""
Analyze why Min ATR Filter is trending conservative and its impact on trade frequency.
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

def analyze_atr_filter():
    """Analyze ATR filter trends and impact."""
    checkpoint = load_checkpoint()
    if checkpoint is None:
        return
    
    pop = checkpoint.get('population', [])
    hof = checkpoint.get('hall_of_fame', [])
    logbook = checkpoint.get('logbook', None)
    gen = checkpoint.get('generation', 0)
    
    print("="*80)
    print("MIN ATR FILTER ANALYSIS")
    print("="*80)
    print(f"Current Generation: {gen}")
    print()
    
    # Load parameter info
    from bollinger_strategy import load_params
    PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'
    param_dict, _ = load_params(PARAM_CSV, return_dataframe=True)
    
    # Get ATR filter range
    atr_param = param_dict.get('Min ATR Filter (Points)', {})
    atr_min = atr_param.get('min', 2.0)
    atr_max = atr_param.get('max', 10.0)
    
    print(f"Parameter Range: {atr_min} - {atr_max}")
    print(f"Current Value: 8.7516 ({((8.7516 - atr_min) / (atr_max - atr_min) * 100):.1f}% of range)")
    print()
    
    # Analyze population
    if pop and len(pop) > 0:
        # Get param_keys to find ATR filter index
        ga_criteria_params = set(['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                                  'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                                  'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                                  'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT'])
        
        PARAM_RANGES = {}
        for n, d in param_dict.items():
            if n.startswith('===') or n.startswith('__'):
                continue
            if n in ga_criteria_params:
                continue
            ptype = d.get('type', '')
            pmin = d.get('min')
            pmax = d.get('max')
            if ptype in ('int', 'float') and pmin is not None and pmax is not None:
                if pmin != pmax:
                    PARAM_RANGES[n] = (pmin, pmax)
        
        param_keys = list(PARAM_RANGES.keys())
        
        if 'Min ATR Filter (Points)' in param_keys:
            atr_idx = param_keys.index('Min ATR Filter (Points)')
            
            # Collect ATR values and corresponding fitness
            atr_values = []
            trade_freqs = []
            sortinos = []
            pfs = []
            
            for ind in pop:
                if hasattr(ind, 'fitness') and ind.fitness.valid and atr_idx < len(ind):
                    atr_val = ind[atr_idx]
                    fitness = ind.fitness.values
                    atr_values.append(atr_val)
                    trade_freqs.append(fitness[3] if len(fitness) > 3 else 0.0)
                    sortinos.append(fitness[0])
                    pfs.append(fitness[2])
            
            if atr_values:
                print("="*80)
                print("POPULATION ANALYSIS")
                print("="*80)
                print(f"Population Size: {len(atr_values)}")
                print(f"\nATR Filter Statistics:")
                print(f"  Min: {min(atr_values):.4f}")
                print(f"  Max: {max(atr_values):.4f}")
                print(f"  Mean: {np.mean(atr_values):.4f}")
                print(f"  Median: {np.median(atr_values):.4f}")
                print(f"  Std Dev: {np.std(atr_values):.4f}")
                
                # Correlation analysis
                atr_arr = np.array(atr_values)
                trades_arr = np.array(trade_freqs)
                sortino_arr = np.array(sortinos)
                pf_arr = np.array(pfs)
                
                corr_trades = np.corrcoef(atr_arr, trades_arr)[0, 1] if len(atr_arr) > 1 else 0
                corr_sortino = np.corrcoef(atr_arr, sortino_arr)[0, 1] if len(atr_arr) > 1 else 0
                corr_pf = np.corrcoef(atr_arr, pf_arr)[0, 1] if len(atr_arr) > 1 else 0
                
                print(f"\nCorrelations:")
                print(f"  vs Trade Frequency: {corr_trades:+.3f}")
                print(f"  vs Sortino: {corr_sortino:+.3f}")
                print(f"  vs Profit Factor: {corr_pf:+.3f}")
                
                # Analyze by ATR ranges
                print(f"\nPerformance by ATR Filter Range:")
                print(f"{'Range':<20} {'Count':<10} {'Avg Trades':<15} {'Avg Sortino':<15} {'Avg PF':<15}")
                print("-"*75)
                
                ranges = [
                    (atr_min, atr_min + (atr_max - atr_min) * 0.33, "Low (0-33%)"),
                    (atr_min + (atr_max - atr_min) * 0.33, atr_min + (atr_max - atr_min) * 0.67, "Mid (33-67%)"),
                    (atr_min + (atr_max - atr_min) * 0.67, atr_max, "High (67-100%)")
                ]
                
                for lo, hi, label in ranges:
                    mask = (atr_arr >= lo) & (atr_arr < hi) if hi < atr_max else (atr_arr >= lo) & (atr_arr <= hi)
                    count = np.sum(mask)
                    if count > 0:
                        avg_trades = np.mean(trades_arr[mask])
                        avg_sortino = np.mean(sortino_arr[mask])
                        avg_pf = np.mean(pf_arr[mask])
                        print(f"{label:<20} {count:<10} {avg_trades:<15.4f} {avg_sortino:<15.4f} {avg_pf:<15.4f}")
                
                # Pareto front analysis
                if hof and len(hof) > 0:
                    print(f"\n{'='*80}")
                    print("PARETO FRONT ANALYSIS")
                    print("="*80)
                    
                    pareto_atr = []
                    pareto_trades = []
                    pareto_sortino = []
                    
                    for ind in hof:
                        if hasattr(ind, 'fitness') and ind.fitness.valid and atr_idx < len(ind):
                            atr_val = ind[atr_idx]
                            fitness = ind.fitness.values
                            pareto_atr.append(atr_val)
                            pareto_trades.append(fitness[3] if len(fitness) > 3 else 0.0)
                            pareto_sortino.append(fitness[0])
                    
                    if pareto_atr:
                        print(f"Pareto Solutions: {len(pareto_atr)}")
                        print(f"\nATR Filter in Pareto Front:")
                        print(f"  Min: {min(pareto_atr):.4f}")
                        print(f"  Max: {max(pareto_atr):.4f}")
                        print(f"  Mean: {np.mean(pareto_atr):.4f}")
                        print(f"  Median: {np.median(pareto_atr):.4f}")
                        
                        # Top solutions
                        solutions = list(zip(pareto_atr, pareto_trades, pareto_sortino))
                        solutions.sort(key=lambda x: x[2], reverse=True)  # Sort by Sortino
                        
                        print(f"\nTop 10 Solutions (by Sortino):")
                        print(f"{'Rank':<6} {'ATR Filter':<15} {'Trades/Day':<15} {'Sortino':<15}")
                        print("-"*55)
                        for rank, (atr, trades, sortino) in enumerate(solutions[:10], 1):
                            pct = ((atr - atr_min) / (atr_max - atr_min) * 100)
                            conservative = "⚠️" if pct > 70 else ""
                            print(f"{rank:<6} {atr:<15.4f} {trades:<15.4f} {sortino:<15.4f} {conservative}")
    
    # Recommendations
    print(f"\n{'='*80}")
    print("ANALYSIS & RECOMMENDATIONS")
    print(f"{'='*80}")
    
    print(f"\nWhy ATR Filter is Trending Conservative:")
    print(f"  1. Higher ATR filter = fewer but potentially higher quality trades")
    print(f"  2. GA may be finding that filtering out low-volatility trades improves Sortino/PF")
    print(f"  3. Trade frequency weight (100.0) may not be strong enough to overcome this")
    print(f"  4. Low-volatility trades may be less profitable, so GA filters them out")
    
    print(f"\nImpact on Trade Frequency:")
    print(f"  - ATR filter of 8.75 is 87.5% of max range (very conservative)")
    print(f"  - This will filter out most low-volatility periods")
    print(f"  - Combined with other conservative parameters, trade frequency collapses")
    
    print(f"\nRecommended Solutions:")
    print(f"  1. Reduce ATR Filter max range: Change from 10.0 to 5.0 or 6.0")
    print(f"     - This prevents the GA from going too conservative")
    print(f"     - Still allows filtering but not extreme")
    print(f"  2. Add penalty for conservative ATR values:")
    print(f"     - Penalize ATR > 70% of range in fitness function")
    print(f"  3. Add hard constraint: Max ATR Filter <= 6.0")
    print(f"  4. Increase trade frequency weight even more (currently 100.0)")
    print(f"  5. Add explicit trade frequency constraint: Min 0.5 trades/day")
    
    print(f"\n{'='*80}")

if __name__ == '__main__':
    analyze_atr_filter()


#!/usr/bin/env python3
"""
Analyze parameter trends in GA run to see if they're becoming too conservative.
"""

import os
import pickle
import pandas as pd
import numpy as np
from collections import defaultdict
from deap import creator, base

CHECKPOINT_FILE = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'
PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'

def load_checkpoint():
    """Load GA checkpoint."""
    if not os.path.exists(CHECKPOINT_FILE):
        print(f"ERROR: Checkpoint file not found: {CHECKPOINT_FILE}")
        return None
    
    with open(CHECKPOINT_FILE, 'rb') as f:
        checkpoint = pickle.load(f)
    
    return checkpoint

def load_params():
    """Load parameter dictionary."""
    from bollinger_strategy import load_params
    param_dict, _ = load_params(PARAM_CSV, return_dataframe=True)
    return param_dict

def analyze_parameter_trends():
    """Analyze how parameters are trending."""
    checkpoint = load_checkpoint()
    if checkpoint is None:
        return
    
    param_dict = load_params()
    
    pop = checkpoint.get('population', [])
    hof = checkpoint.get('hall_of_fame', [])
    logbook = checkpoint.get('logbook', None)
    gen = checkpoint.get('generation', 0)
    
    print("="*80)
    print("PARAMETER TREND ANALYSIS - CONSERVATIVE VALUES CHECK")
    print("="*80)
    print(f"Current Generation: {gen}")
    print(f"Population Size: {len(pop)}")
    print(f"Pareto Solutions: {len(hof)}")
    print()
    
    # Get parameter keys (optimizable parameters)
    param_keys = []
    for key in param_dict.keys():
        if key.startswith('===') or key.startswith('__'):
            continue
        pdata = param_dict[key]
        pmin = pdata.get('min')
        pmax = pdata.get('max')
        if pmin is not None and pmax is not None and pmin != pmax:
            param_keys.append(key)
    
    print(f"Optimizable Parameters: {len(param_keys)}")
    print()
    
    # Analyze current population
    if pop and len(pop) > 0:
        print("="*80)
        print("CURRENT POPULATION PARAMETER ANALYSIS")
        print("="*80)
        
        # Collect parameter values from population
        param_values = defaultdict(list)
        param_fitness = defaultdict(list)
        
        for ind in pop:
            if hasattr(ind, 'fitness') and ind.fitness.valid:
                fitness = ind.fitness.values
                avg_trades = fitness[3] if len(fitness) > 3 else 0.0
                
                for i, key in enumerate(param_keys):
                    if i < len(ind):
                        val = ind[i]
                        param_values[key].append(val)
                        param_fitness[key].append(avg_trades)
        
        # Analyze each parameter
        print("\nParameter Analysis (sorted by trade frequency correlation):")
        print(f"{'Parameter':<40} {'Mean Value':<15} {'Range':<20} {'Trade Corr':<12} {'Conservative?'}")
        print("-"*100)
        
        conservative_params = []
        param_correlations = []
        
        for key in param_keys:
            if key not in param_values or len(param_values[key]) == 0:
                continue
            
            values = np.array(param_values[key])
            trades = np.array(param_fitness[key])
            
            # Get parameter info
            pdata = param_dict[key]
            pmin = pdata.get('min')
            pmax = pdata.get('max')
            default = pdata.get('value')
            ptype = pdata.get('type', 'float')
            
            mean_val = np.mean(values)
            std_val = np.std(values)
            
            # Calculate correlation with trade frequency
            if len(trades) > 1 and std_val > 0:
                correlation = np.corrcoef(values, trades)[0, 1]
                if np.isnan(correlation):
                    correlation = 0.0
            else:
                correlation = 0.0
            
            param_correlations.append((key, correlation, mean_val, pmin, pmax, default))
            
            # Check if parameter is trending conservative
            is_conservative = False
            conservative_reason = ""
            
            # Entry trigger parameters - higher = more conservative (harder to enter)
            if 'Trigger' in key and '%' in key:
                if mean_val > (pmin + (pmax - pmin) * 0.7):  # In top 30% of range
                    is_conservative = True
                    conservative_reason = "High trigger = harder entry"
            
            # ATR filter - higher = more conservative (fewer trades)
            if 'ATR' in key and 'Filter' in key:
                if mean_val > (pmin + (pmax - pmin) * 0.7):
                    is_conservative = True
                    conservative_reason = "High ATR filter = fewer trades"
            
            # Volume filter - higher = more conservative
            if 'Volume' in key:
                if mean_val > (pmin + (pmax - pmin) * 0.7):
                    is_conservative = True
                    conservative_reason = "High volume filter = fewer trades"
            
            # Stop loss - tighter = more conservative (exits faster)
            if 'Stop Loss' in key:
                if mean_val < (pmin + (pmax - pmin) * 0.3):  # In bottom 30%
                    is_conservative = True
                    conservative_reason = "Tight stop = exits faster"
            
            # Bollinger Band settings - wider = more conservative
            if 'Bollinger Band StdDev' in key:
                if mean_val > (pmin + (pmax - pmin) * 0.7):
                    is_conservative = True
                    conservative_reason = "Wide bands = fewer touches"
            
            if is_conservative:
                conservative_params.append((key, conservative_reason, mean_val, pmin, pmax))
            
            # Format value
            if ptype == 'int':
                val_str = f"{int(round(mean_val))}"
                range_str = f"{int(pmin)}-{int(pmax)}"
            else:
                val_str = f"{mean_val:.4f}"
                range_str = f"{pmin:.4f}-{pmax:.4f}"
            
            # Format correlation
            corr_str = f"{correlation:+.3f}" if not np.isnan(correlation) else "N/A"
            
            # Mark if conservative
            conservative_mark = "⚠️ YES" if is_conservative else ""
            
            print(f"{key:<40} {val_str:<15} {range_str:<20} {corr_str:<12} {conservative_mark}")
        
        # Sort by correlation to see which parameters most affect trade frequency
        param_correlations.sort(key=lambda x: abs(x[1]), reverse=True)
        
        print(f"\n{'='*80}")
        print("PARAMETERS MOST CORRELATED WITH TRADE FREQUENCY")
        print(f"{'='*80}")
        print(f"{'Parameter':<40} {'Correlation':<15} {'Mean Value':<15} {'Impact'}")
        print("-"*85)
        for key, corr, mean_val, pmin, pmax, default in param_correlations[:10]:
            impact = "POSITIVE" if corr > 0.1 else "NEGATIVE" if corr < -0.1 else "NEUTRAL"
            print(f"{key:<40} {corr:+.3f}          {mean_val:.4f}          {impact}")
        
        # Conservative parameters summary
        if conservative_params:
            print(f"\n{'='*80}")
            print("⚠️  CONSERVATIVE PARAMETERS DETECTED")
            print(f"{'='*80}")
            for key, reason, mean_val, pmin, pmax in conservative_params:
                pct = ((mean_val - pmin) / (pmax - pmin) * 100) if pmax != pmin else 0
                print(f"  {key}:")
                print(f"    Value: {mean_val:.4f} ({pct:.1f}% of range)")
                print(f"    Issue: {reason}")
                print()
        else:
            print(f"\n✓ No obviously conservative parameters detected")
    
    # Analyze Pareto front (best solutions)
    if hof and len(hof) > 0:
        print(f"\n{'='*80}")
        print("PARETO FRONT (BEST SOLUTIONS) PARAMETER ANALYSIS")
        print(f"{'='*80}")
        
        # Get top 5 solutions by Sortino
        solutions = []
        for i, ind in enumerate(hof):
            if hasattr(ind, 'fitness') and ind.fitness.valid:
                fitness = ind.fitness.values
                solutions.append((i, ind, fitness[0], fitness[3] if len(fitness) > 3 else 0.0))
        
        solutions.sort(key=lambda x: x[2], reverse=True)  # Sort by Sortino
        
        print(f"\nTop 5 Solutions Parameter Values:")
        print(f"{'Parameter':<40} {'Sol 1':<12} {'Sol 2':<12} {'Sol 3':<12} {'Sol 4':<12} {'Sol 5':<12}")
        print("-"*100)
        
        # Analyze key parameters that affect trade frequency
        key_params = [
            'Long Trigger (% From Lower Band)',
            'Short Trigger (% From Upper Band)',
            'Min ATR Filter (Points)',
            'Min Volume Multiplier',
            'Bollinger Band StdDev',
            'Initial Stop Loss (%)'
        ]
        
        for key in key_params:
            if key not in param_keys:
                continue
            
            idx = param_keys.index(key)
            values = []
            trades = []
            
            for rank, (orig_idx, ind, sortino, avg_trades) in enumerate(solutions[:5], 1):
                if idx < len(ind):
                    val = ind[idx]
                    values.append(val)
                    trades.append(avg_trades)
                else:
                    values.append(0)
                    trades.append(0)
            
            # Check if trending conservative
            pdata = param_dict[key]
            pmin = pdata.get('min')
            pmax = pdata.get('max')
            
            val_strs = []
            for val in values:
                if pdata.get('type') == 'int':
                    val_strs.append(f"{int(round(val))}")
                else:
                    val_strs.append(f"{val:.4f}")
            
            # Mark if conservative
            mean_val = np.mean(values)
            if 'Trigger' in key and mean_val > (pmin + (pmax - pmin) * 0.7):
                mark = "⚠️"
            elif 'ATR' in key and 'Filter' in key and mean_val > (pmin + (pmax - pmin) * 0.7):
                mark = "⚠️"
            elif 'Volume' in key and mean_val > (pmin + (pmax - pmin) * 0.7):
                mark = "⚠️"
            else:
                mark = ""
            
            print(f"{key:<40} {val_strs[0]:<12} {val_strs[1]:<12} {val_strs[2]:<12} {val_strs[3]:<12} {val_strs[4]:<12} {mark}")
        
        # Check trade frequency of top solutions
        print(f"\nTrade Frequency of Top Solutions:")
        print(f"{'Rank':<6} {'Sortino':<10} {'Trades/Day (norm)':<18} {'Assessment'}")
        print("-"*50)
        for rank, (orig_idx, ind, sortino, avg_trades) in enumerate(solutions[:5], 1):
            if avg_trades < 0.01:
                assessment = "🔴 CRITICAL - Near zero"
            elif avg_trades < 0.05:
                assessment = "⚠️  LOW"
            else:
                assessment = "✓ Acceptable"
            print(f"{rank:<6} {sortino:<10.4f} {avg_trades:<18.4f} {assessment}")
    
    # Recommendations
    print(f"\n{'='*80}")
    print("RECOMMENDATIONS")
    print(f"{'='*80}")
    
    if conservative_params:
        print("\n🔴 ISSUE: Parameters are trending toward conservative values!")
        print("\nSuggested fixes:")
        print("1. Tighten parameter ranges to prevent conservative values")
        print("2. Add hard constraint: Min Avg Trades/Day >= 0.5")
        print("3. Review entry trigger ranges - may be too wide")
        print("4. Check ATR filter ranges - may allow values that filter out all trades")
        print("5. Consider adding penalty for parameters in conservative ranges")
    else:
        print("\n✓ Parameters don't appear to be trending conservative")
        print("  But trade frequency is still low - investigate other causes:")
        print("  - Hard constraints may be eliminating high-frequency solutions")
        print("  - Normalization may be making trade frequency values too small")
        print("  - NSGA-II may not be using weights correctly")
    
    print(f"\n{'='*80}")

if __name__ == '__main__':
    analyze_parameter_trends()


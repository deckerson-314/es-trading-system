#!/usr/bin/env python3
"""
Comprehensive analysis of ongoing GA run.
"""

import pickle
import os
import pandas as pd
import numpy as np
from datetime import datetime
from bollinger_strategy.parameters import load_params

CHECKPOINT_FILE = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'
PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'

def analyze_ga_run():
    """Comprehensive analysis of ongoing GA run."""
    
    if not os.path.exists(CHECKPOINT_FILE):
        print("ERROR: No checkpoint file found")
        return
    
    with open(CHECKPOINT_FILE, 'rb') as f:
        checkpoint = pickle.load(f)
    
    gen = checkpoint.get('generation', 0)
    hof = checkpoint.get('hall_of_fame', [])
    pop = checkpoint.get('population', [])
    logbook = checkpoint.get('logbook', None)
    config = checkpoint.get('config', {})
    
    # Load parameters
    param_dict, _ = load_params(PARAM_CSV, return_dataframe=True)
    
    # Get parameter keys
    param_keys = []
    for n, d in param_dict.items():
        if n.startswith('===') or n.startswith('__'):
            continue
        if n in ['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                 'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                 'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                 'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT', 'NORM_SORTINO_MAX', 'NORM_DD_MAX',
                 'NORM_PF_MAX', 'NORM_TRADES_MAX', 'NORM_PNL_MAX', 'MIN_WIN_RATE', 'SORTINO_CAP']:
            continue
        ptype = d.get('type', '')
        pmin = d.get('min')
        pmax = d.get('max')
        if ptype in ('int', 'float') and pmin is not None and pmax is not None:
            if pmin != pmax:
                param_keys.append(n)
    
    print("="*80)
    print("COMPREHENSIVE GA RUN ANALYSIS")
    print("="*80)
    print(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Current Generation: {gen}/{config.get('NUM_GEN', 0)}")
    print(f"Progress: {gen/config.get('NUM_GEN', 1)*100:.1f}%")
    print(f"Population Size: {len(pop)}")
    print(f"Pareto Solutions: {len(hof)}")
    print()
    
    # ========================================================================
    # 1. FITNESS METRICS ANALYSIS
    # ========================================================================
    print("="*80)
    print("1. FITNESS METRICS ANALYSIS")
    print("="*80)
    
    if logbook and len(logbook) > 0:
        records = logbook
        
        # Extract metrics
        gens = [r.get('gen', i) for i, r in enumerate(records)]
        trades = [r.get('avg_trades_day', 0) for r in records]
        sortino_avg = [r.get('avg_sortino', 0) for r in records]
        sortino_max = [r.get('max_sortino', 0) for r in records]
        pf_avg = [r.get('avg_pf', 0) for r in records]
        pf_max = [r.get('max_pf', 0) for r in records]
        dd_avg = [r.get('avg_dd', 0) for r in records]
        dd_min = [r.get('min_dd', 0) for r in records]
        pareto_sizes = [r.get('pareto_size', 0) for r in records]
        
        latest = records[-1]
        
        print(f"Latest Generation ({latest.get('gen', 'N/A')}):")
        print(f"  Avg Trades/Day: {latest.get('avg_trades_day', 0):.3f}")
        print(f"  Max Trades/Day: {latest.get('max_trades_day', 0):.3f}")
        print(f"  Avg Sortino: {latest.get('avg_sortino', 0):.6f}")
        print(f"  Max Sortino: {latest.get('max_sortino', 0):.6f}")
        print(f"  Avg Profit Factor: {latest.get('avg_pf', 0):.6f}")
        print(f"  Max Profit Factor: {latest.get('max_pf', 0):.6f}")
        print(f"  Avg Drawdown: {latest.get('avg_dd', 0):.2f}")
        print(f"  Min Drawdown: {latest.get('min_dd', 0):.2f}")
        print(f"  Pareto Front Size: {latest.get('pareto_size', 0)}")
        print()
        
        # Trend analysis
        if len(records) >= 5:
            early_5 = records[:5]
            recent_5 = records[-5:]
            
            early_trades = np.mean([r.get('avg_trades_day', 0) for r in early_5])
            recent_trades = np.mean([r.get('avg_trades_day', 0) for r in recent_5])
            trades_change = recent_trades - early_trades
            
            early_sortino = np.mean([r.get('avg_sortino', 0) for r in early_5])
            recent_sortino = np.mean([r.get('avg_sortino', 0) for r in recent_5])
            sortino_change = recent_sortino - early_sortino
            
            early_pf = np.mean([r.get('avg_pf', 0) for r in early_5])
            recent_pf = np.mean([r.get('avg_pf', 0) for r in recent_5])
            pf_change = recent_pf - early_pf
            
            print("Trend Analysis (First 5 vs Last 5 Generations):")
            print(f"  Trades/Day: {early_trades:.3f} → {recent_trades:.3f} ({trades_change:+.3f})")
            print(f"  Sortino: {early_sortino:.6f} → {recent_sortino:.6f} ({sortino_change:+.6f})")
            print(f"  Profit Factor: {early_pf:.6f} → {recent_pf:.6f} ({pf_change:+.6f})")
            print()
            
            # Assessment
            print("Assessment:")
            if recent_trades > 10:
                print(f"  ⚠️  TRADE FREQUENCY TOO HIGH: {recent_trades:.1f} trades/day (target: 2-5)")
                print("     → Max Volume/ATR filters may be too permissive")
            elif recent_trades > 0.5:
                print(f"  ✅ Trade frequency reasonable: {recent_trades:.1f} trades/day")
            else:
                print(f"  🔴 Trade frequency too low: {recent_trades:.1f} trades/day")
            
            if recent_sortino > 0.1:
                print(f"  ✅ Sortino improving: {recent_sortino:.6f}")
            elif recent_sortino > 0:
                print(f"  ⚠️  Sortino positive but low: {recent_sortino:.6f}")
            else:
                print(f"  🔴 Sortino still negative: {recent_sortino:.6f}")
            
            if recent_pf > 0.5:
                print(f"  ✅ Profit Factor improving: {recent_pf:.6f}")
            elif recent_pf > 0.1:
                print(f"  ⚠️  Profit Factor low: {recent_pf:.6f}")
            else:
                print(f"  🔴 Profit Factor very low: {recent_pf:.6f}")
    
    # ========================================================================
    # 2. PARAMETER CONVERGENCE ANALYSIS
    # ========================================================================
    print()
    print("="*80)
    print("2. PARAMETER CONVERGENCE ANALYSIS")
    print("="*80)
    
    if hof and len(hof) > 0:
        # Extract parameter values from Hall of Fame
        param_data = []
        for ind in hof:
            if hasattr(ind, 'fitness') and ind.fitness.valid:
                row = {}
                for j, param_name in enumerate(param_keys):
                    if j < len(ind):
                        row[param_name] = ind[j]
                if row:
                    param_data.append(row)
        
        if param_data:
            param_df = pd.DataFrame(param_data)
            
            # Key parameters to monitor
            key_params = ['Max Volume Multiplier', 'Max ATR Filter (Points)', 
                         'Min ATR Filter (Points)', 'Long Trigger (% From Lower Band)',
                         'Short Trigger (% From Upper Band)', 'Bollinger Band Length',
                         'Bollinger Band StdDev']
            
            print("Key Parameter Statistics:")
            print()
            for param in key_params:
                if param in param_df.columns:
                    values = param_df[param]
                    if param in param_dict:
                        param_info = param_dict[param]
                        param_min = param_info.get('min', None)
                        param_max = param_info.get('max', None)
                        
                        mean_val = values.mean()
                        median_val = values.median()
                        std_val = values.std()
                        min_val = values.min()
                        max_val = values.max()
                        
                        # Check if hitting boundaries
                        at_min = (values <= param_min * 1.01).sum() if param_min else 0
                        at_max = (values >= param_max * 0.99).sum() if param_max else 0
                        
                        print(f"{param}:")
                        print(f"  Range: [{param_min}, {param_max}]")
                        print(f"  Mean: {mean_val:.4f}, Median: {median_val:.4f}, Std: {std_val:.4f}")
                        print(f"  Actual: [{min_val:.4f}, {max_val:.4f}]")
                        
                        if at_min > len(values) * 0.1:
                            print(f"  ⚠️  {at_min} solutions ({100*at_min/len(values):.1f}%) at MIN boundary")
                        if at_max > len(values) * 0.1:
                            print(f"  ⚠️  {at_max} solutions ({100*at_max/len(values):.1f}%) at MAX boundary")
                        
                        # Special assessment for key filters
                        if param == 'Max Volume Multiplier':
                            if mean_val > 2.5:
                                print(f"  ⚠️  Mean ({mean_val:.2f}) is high - filter may be too permissive")
                            elif mean_val < 0.8:
                                print(f"  ✅ Mean ({mean_val:.2f}) is reasonable for mean reversion")
                        
                        if param == 'Max ATR Filter (Points)':
                            if mean_val > 5.0:
                                print(f"  ⚠️  Mean ({mean_val:.2f}) is high - filter may be too permissive")
                            elif mean_val < 3.0:
                                print(f"  ✅ Mean ({mean_val:.2f}) is reasonable for mean reversion")
                        
                        print()
    
    # ========================================================================
    # 3. BEST SOLUTION ANALYSIS
    # ========================================================================
    print("="*80)
    print("3. BEST SOLUTION ANALYSIS")
    print("="*80)
    
    if hof and len(hof) > 0:
        # Find best solution (highest Sortino)
        best_ind = None
        best_sortino = -float('inf')
        
        for ind in hof:
            if hasattr(ind, 'fitness') and ind.fitness.valid:
                if len(ind.fitness.values) >= 1:
                    sortino_val = ind.fitness.values[0]
                    if sortino_val > best_sortino:
                        best_sortino = sortino_val
                        best_ind = ind
        
        if best_ind:
            print("Best Solution (Highest Sortino):")
            print(f"  Fitness: {best_ind.fitness.values}")
            print()
            print("Key Parameters:")
            
            for j, param_name in enumerate(param_keys):
                if j < len(best_ind):
                    value = best_ind[j]
                    if param_name in param_dict:
                        param_info = param_dict[param_name]
                        param_min = param_info.get('min', None)
                        param_max = param_info.get('max', None)
                        
                        # Clamp and round if needed
                        if param_min is not None and param_max is not None:
                            clamped = max(param_min, min(value, param_max))
                            param_type = param_info.get('type', 'float')
                            if param_type == 'int':
                                clamped = int(round(clamped))
                            
                            # Show key parameters
                            if param_name in ['Max Volume Multiplier', 'Max ATR Filter (Points)', 
                                            'Min ATR Filter (Points)', 'Long Trigger (% From Lower Band)',
                                            'Short Trigger (% From Upper Band)', 'Bollinger Band Length',
                                            'Bollinger Band StdDev', 'TP Method', 'Enable Trailing Stop',
                                            'Initial Stop Loss (%)', 'ATR Multiplier for Trailing Stop']:
                                pct_of_range = ((clamped - param_min) / (param_max - param_min) * 100) if (param_max - param_min) > 0 else 0
                                print(f"  {param_name}: {clamped:.4f} ({pct_of_range:.1f}% of range)")
    
    # ========================================================================
    # 4. CONVERGENCE ASSESSMENT
    # ========================================================================
    print()
    print("="*80)
    print("4. CONVERGENCE ASSESSMENT")
    print("="*80)
    
    if logbook and len(logbook) >= 10:
        records = logbook
        recent_10 = records[-10:]
        
        # Check if metrics are stabilizing
        trades_recent = [r.get('avg_trades_day', 0) for r in recent_10]
        sortino_recent = [r.get('avg_sortino', 0) for r in recent_10]
        
        trades_std = np.std(trades_recent)
        sortino_std = np.std(sortino_recent)
        
        print("Recent Stability (Last 10 Generations):")
        print(f"  Trades/Day Std Dev: {trades_std:.3f}")
        print(f"  Sortino Std Dev: {sortino_std:.6f}")
        print()
        
        if trades_std < 1.0:
            print("  ✅ Trade frequency is stabilizing")
        else:
            print("  ⚠️  Trade frequency is still volatile")
        
        if sortino_std < 0.01:
            print("  ✅ Sortino is stabilizing")
        else:
            print("  ⚠️  Sortino is still volatile")
    
    # ========================================================================
    # 5. RECOMMENDATIONS
    # ========================================================================
    print()
    print("="*80)
    print("5. RECOMMENDATIONS")
    print("="*80)
    
    if logbook and len(logbook) > 0:
        latest = logbook[-1]
        recent_trades = latest.get('avg_trades_day', 0)
        recent_sortino = latest.get('avg_sortino', 0)
        recent_pf = latest.get('avg_pf', 0)
        
        recommendations = []
        
        if recent_trades > 10:
            recommendations.append({
                'priority': 'HIGH',
                'issue': f'Trade frequency too high ({recent_trades:.1f} trades/day)',
                'action': 'Tighten Max Volume Multiplier and/or Max ATR Filter ranges (reduce max values)'
            })
        elif recent_trades < 0.5:
            recommendations.append({
                'priority': 'HIGH',
                'issue': f'Trade frequency too low ({recent_trades:.1f} trades/day)',
                'action': 'Widen Max Volume Multiplier and/or Max ATR Filter ranges (increase max values)'
            })
        
        if recent_sortino < 0.01:
            recommendations.append({
                'priority': 'MEDIUM',
                'issue': f'Sortino very low ({recent_sortino:.6f})',
                'action': 'Monitor for improvement. May need more generations or fitness weight adjustments'
            })
        
        if recent_pf < 0.2:
            recommendations.append({
                'priority': 'MEDIUM',
                'issue': f'Profit Factor very low ({recent_pf:.6f})',
                'action': 'Strategies are still unprofitable. Monitor for improvement over next 20-30 generations'
            })
        
        if gen < 30:
            recommendations.append({
                'priority': 'LOW',
                'issue': f'Early stage ({gen} generations)',
                'action': 'Continue running. Early generations are exploratory. Reassess after 30-50 generations'
            })
        
        if recommendations:
            for i, rec in enumerate(recommendations, 1):
                print(f"{i}. [{rec['priority']}] {rec['issue']}")
                print(f"   → {rec['action']}")
                print()
        else:
            print("✅ No major issues detected. Continue monitoring.")
    
    print()
    print("="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)

if __name__ == '__main__':
    analyze_ga_run()


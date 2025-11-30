#!/usr/bin/env python3
"""
Comprehensive analysis of latest GA run with recommendations for next overnight run.
"""

import os
import pickle
import pandas as pd
import numpy as np
from datetime import datetime
from bollinger_strategy.parameters import load_params

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

def analyze_latest_run():
    """Comprehensive analysis with recommendations."""
    checkpoint = load_checkpoint()
    if checkpoint is None:
        return
    
    param_dict, param_df = load_params(PARAM_CSV, return_dataframe=True)
    
    pop = checkpoint.get('population', [])
    hof = checkpoint.get('hall_of_fame', [])
    logbook = checkpoint.get('logbook', None)
    gen = checkpoint.get('generation', 0)
    config = checkpoint.get('config', {})
    start_time = checkpoint.get('start_time', None)
    
    print("="*80)
    print("COMPREHENSIVE GA RUN ANALYSIS - NEXT RUN RECOMMENDATIONS")
    print("="*80)
    print(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if start_time:
        elapsed = datetime.now() - start_time
        print(f"Run Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Elapsed Time: {elapsed}")
    print(f"Current Generation: {gen}/{config.get('NUM_GEN', 'Unknown')}")
    print(f"Progress: {100*gen/config.get('NUM_GEN', 1):.1f}%")
    print(f"Population Size: {len(pop)}")
    print(f"Pareto Solutions: {len(hof)}")
    print()
    
    # Extract fitness and parameters from Hall of Fame
    solutions = []
    param_keys = [k for k in param_dict.keys() if param_dict[k].get('type') != 'fixed']
    
    for i, ind in enumerate(hof):
        if hasattr(ind, 'fitness') and ind.fitness.valid:
            fitness = ind.fitness.values
            if len(fitness) >= 5:
                row = {
                    'solution_id': i,
                    'sortino_norm': fitness[0],
                    'drawdown_norm': fitness[1],
                    'profit_factor_norm': fitness[2],
                    'avg_trades_day': fitness[3],
                    'total_profit_norm': fitness[4]
                }
                # Add parameters
                for j, key in enumerate(param_keys):
                    if j < len(ind):
                        row[key] = ind[j]
                solutions.append(row)
    
    if not solutions:
        print("ERROR: No valid solutions found in Hall of Fame!")
        return
    
    df = pd.DataFrame(solutions)
    print(f"Analyzing {len(df)} Pareto-optimal solutions")
    print()
    
    # ====================================================================
    # 1. FITNESS ANALYSIS
    # ====================================================================
    print("="*80)
    print("1. FITNESS ANALYSIS")
    print("="*80)
    
    print(f"\nNormalized Fitness Ranges (0-1 scale):")
    print(f"  Sortino:     {df['sortino_norm'].min():.6f} to {df['sortino_norm'].max():.6f} (avg: {df['sortino_norm'].mean():.6f})")
    print(f"  Drawdown:    {df['drawdown_norm'].min():.6f} to {df['drawdown_norm'].max():.6f} (avg: {df['drawdown_norm'].mean():.6f})")
    print(f"  Profit Factor: {df['profit_factor_norm'].min():.6f} to {df['profit_factor_norm'].max():.6f} (avg: {df['profit_factor_norm'].mean():.6f})")
    print(f"  Avg Trades/Day: {df['avg_trades_day'].min():.3f} to {df['avg_trades_day'].max():.3f} (avg: {df['avg_trades_day'].mean():.3f})")
    print(f"  Total Profit: {df['total_profit_norm'].min():.6f} to {df['total_profit_norm'].max():.6f} (avg: {df['total_profit_norm'].mean():.6f})")
    
    # Best solution
    best_idx = df['sortino_norm'].idxmax()
    best = df.loc[best_idx]
    print(f"\nBest Solution (Highest Sortino):")
    print(f"  Sortino: {best['sortino_norm']:.6f}")
    print(f"  Drawdown: {best['drawdown_norm']:.6f}")
    print(f"  Profit Factor: {best['profit_factor_norm']:.6f}")
    print(f"  Avg Trades/Day: {best['avg_trades_day']:.3f}")
    print(f"  Total Profit: {best['total_profit_norm']:.6f}")
    
    # Trade frequency analysis
    low_trades = (df['avg_trades_day'] < 1.0).sum()
    medium_trades = ((df['avg_trades_day'] >= 1.0) & (df['avg_trades_day'] < 3.0)).sum()
    high_trades = (df['avg_trades_day'] >= 3.0).sum()
    
    print(f"\nTrade Frequency Distribution:")
    print(f"  < 1 trade/day: {low_trades} solutions ({100*low_trades/len(df):.1f}%)")
    print(f"  1-3 trades/day: {medium_trades} solutions ({100*medium_trades/len(df):.1f}%)")
    print(f"  >= 3 trades/day: {high_trades} solutions ({100*high_trades/len(df):.1f}%)")
    
    # ====================================================================
    # 2. PARAMETER CONVERGENCE ANALYSIS
    # ====================================================================
    print("\n" + "="*80)
    print("2. PARAMETER CONVERGENCE ANALYSIS")
    print("="*80)
    
    # Analyze parameter distributions
    param_stats = []
    for param in param_keys:
        if param in df.columns:
            param_info = param_dict.get(param, {})
            param_type = param_info.get('type', 'float')
            param_min = param_info.get('min', None)
            param_max = param_info.get('max', None)
            
            # Only analyze numeric parameters
            if param_type in ['int', 'float'] and param_min is not None and param_max is not None:
                try:
                    # Try to convert to numeric
                    param_min = float(param_min)
                    param_max = float(param_max)
                    
                    values = pd.to_numeric(df[param], errors='coerce')
                    values = values.dropna()
                    
                    if len(values) > 0:
                        mean_val = values.mean()
                        std_val = values.std()
                        range_used = (values.max() - values.min()) / (param_max - param_min) * 100 if param_max != param_min else 0
                        convergence = std_val / (param_max - param_min) * 100 if param_max != param_min else 0
                        
                        param_stats.append({
                            'parameter': param,
                            'mean': mean_val,
                            'std': std_val,
                            'min': values.min(),
                            'max': values.max(),
                            'range_used_pct': range_used,
                            'convergence_pct': convergence,
                            'param_min': param_min,
                            'param_max': param_max
                        })
                except (TypeError, ValueError):
                    pass  # Skip non-numeric parameters
    
    param_stats_df = pd.DataFrame(param_stats)
    param_stats_df = param_stats_df.sort_values('convergence_pct', ascending=False)
    
    print(f"\nTop 10 Most Converged Parameters (Low Variation):")
    print(param_stats_df.head(10)[['parameter', 'mean', 'convergence_pct', 'range_used_pct']].to_string(index=False))
    
    print(f"\nTop 10 Most Variable Parameters (High Variation):")
    print(param_stats_df.tail(10)[['parameter', 'mean', 'convergence_pct', 'range_used_pct']].to_string(index=False))
    
    # Check for parameters at boundaries
    at_min = []
    at_max = []
    for _, row in param_stats_df.iterrows():
        try:
            range_size = row['param_max'] - row['param_min']
            if range_size > 0:
                if row['min'] <= row['param_min'] + 0.01 * range_size:
                    at_min.append(row['parameter'])
                if row['max'] >= row['param_max'] - 0.01 * range_size:
                    at_max.append(row['parameter'])
        except (TypeError, ValueError):
            pass  # Skip if comparison fails
    
    if at_min:
        print(f"\n⚠️  Parameters at MIN boundary (may need lower min): {', '.join(at_min[:5])}")
    if at_max:
        print(f"⚠️  Parameters at MAX boundary (may need higher max): {', '.join(at_max[:5])}")
    
    # ====================================================================
    # 3. CONVERGENCE TRENDS (from logbook)
    # ====================================================================
    print("\n" + "="*80)
    print("3. CONVERGENCE TRENDS")
    print("="*80)
    
    if logbook and len(logbook) > 0:
        logbook_df = pd.DataFrame(logbook)
        
        if 'avg_sortino' in logbook_df.columns:
            recent_avg = logbook_df['avg_sortino'].tail(10).mean()
            early_avg = logbook_df['avg_sortino'].head(10).mean()
            improvement = (recent_avg - early_avg) / early_avg * 100 if early_avg > 0 else 0
            
            print(f"\nSortino Convergence:")
            print(f"  Early generations (0-9): {early_avg:.6f}")
            print(f"  Recent generations (last 10): {recent_avg:.6f}")
            print(f"  Improvement: {improvement:+.1f}%")
            
            if improvement < 1.0:
                print(f"  ⚠️  WARNING: Sortino appears to have converged (minimal improvement)")
        
        if 'avg_trades_day' in logbook_df.columns:
            recent_trades = logbook_df['avg_trades_day'].tail(10).mean()
            early_trades = logbook_df['avg_trades_day'].head(10).mean()
            
            print(f"\nTrade Frequency Trend:")
            print(f"  Early generations: {early_trades:.3f} trades/day")
            print(f"  Recent generations: {recent_trades:.3f} trades/day")
            print(f"  Change: {recent_trades - early_trades:+.3f} trades/day")
            
            if recent_trades < 1.0:
                print(f"  ⚠️  WARNING: Trade frequency is critically low (< 1 trade/day)")
        
        if 'pareto_size' in logbook_df.columns:
            recent_pareto = logbook_df['pareto_size'].tail(10).mean()
            print(f"\nPareto Front Size:")
            print(f"  Recent average: {recent_pareto:.1f} solutions")
            if recent_pareto < 50:
                print(f"  ⚠️  WARNING: Small Pareto front suggests limited diversity")
    
    # ====================================================================
    # 4. PARAMETER-METRIC CORRELATIONS
    # ====================================================================
    print("\n" + "="*80)
    print("4. PARAMETER-METRIC CORRELATIONS")
    print("="*80)
    
    # Calculate correlations
    correlations = []
    for param in param_keys:
        if param in df.columns:
            try:
                corr_sortino = np.corrcoef(df[param], df['sortino_norm'])[0, 1]
                corr_trades = np.corrcoef(df[param], df['avg_trades_day'])[0, 1]
                if not np.isnan(corr_sortino) and not np.isnan(corr_trades):
                    correlations.append({
                        'parameter': param,
                        'sortino_corr': corr_sortino,
                        'trades_corr': corr_trades,
                        'abs_sortino_corr': abs(corr_sortino),
                        'abs_trades_corr': abs(corr_trades)
                    })
            except:
                pass
    
    if correlations:
        corr_df = pd.DataFrame(correlations)
        corr_df = corr_df.sort_values('abs_sortino_corr', ascending=False)
        
        print(f"\nTop 10 Parameters Correlated with Sortino:")
        print(corr_df.head(10)[['parameter', 'sortino_corr']].to_string(index=False))
        
        corr_df = corr_df.sort_values('abs_trades_corr', ascending=False)
        print(f"\nTop 10 Parameters Correlated with Trade Frequency:")
        print(corr_df.head(10)[['parameter', 'trades_corr']].to_string(index=False))
    
    # ====================================================================
    # 5. RECOMMENDATIONS FOR NEXT RUN
    # ====================================================================
    print("\n" + "="*80)
    print("5. RECOMMENDATIONS FOR NEXT OVERNIGHT RUN")
    print("="*80)
    
    recommendations = []
    
    # Check trade frequency
    avg_trades = df['avg_trades_day'].mean()
    if avg_trades < 1.5:
        recommendations.append({
            'priority': 'HIGH',
            'issue': f'Low trade frequency (avg: {avg_trades:.2f} trades/day)',
            'recommendation': 'Consider: (1) Reduce Min ATR Filter max range, (2) Reduce Min Volume Multiplier, (3) Increase weight on avg_trades_day'
        })
    
    # Check convergence
    if logbook and len(logbook) > 0:
        logbook_df = pd.DataFrame(logbook)
        if 'avg_sortino' in logbook_df.columns:
            recent_avg = logbook_df['avg_sortino'].tail(5).mean()
            early_avg = logbook_df['avg_sortino'].head(5).mean()
            if abs(recent_avg - early_avg) / early_avg < 0.05:
                recommendations.append({
                    'priority': 'MEDIUM',
                    'issue': 'Sortino appears converged (minimal improvement)',
                    'recommendation': 'Consider: (1) Increase mutation rate, (2) Increase population size, (3) Widen parameter ranges'
                })
    
    # Check parameter boundaries
    if at_min or at_max:
        recommendations.append({
            'priority': 'MEDIUM',
            'issue': f'Parameters hitting boundaries ({len(at_min)} at min, {len(at_max)} at max)',
            'recommendation': 'Consider widening parameter ranges for parameters at boundaries'
        })
    
    # Check Pareto front size
    if len(hof) < 100:
        recommendations.append({
            'priority': 'LOW',
            'issue': f'Small Pareto front ({len(hof)} solutions)',
            'recommendation': 'Consider: (1) Increase population size, (2) Increase generations, (3) Adjust selection pressure'
        })
    
    # Parameter range recommendations
    print(f"\n📊 PARAMETER RANGE RECOMMENDATIONS:")
    print(f"\nBased on current distributions, consider adjusting:")
    
    # Find parameters that might benefit from range adjustments
    for _, row in param_stats_df.head(15).iterrows():
        param = row['parameter']
        mean_val = row['mean']
        param_min = row['param_min']
        param_max = row['param_max']
        range_used = row['range_used_pct']
        
        # If parameter is highly converged and not using full range
        if row['convergence_pct'] < 10 and range_used < 50:
            # Suggest narrowing range around current mean
            suggested_min = max(param_min, mean_val - (param_max - param_min) * 0.3)
            suggested_max = min(param_max, mean_val + (param_max - param_min) * 0.3)
            print(f"  {param}:")
            print(f"    Current: [{param_min:.3f}, {param_max:.3f}]")
            print(f"    Suggested: [{suggested_min:.3f}, {suggested_max:.3f}] (mean: {mean_val:.3f})")
    
    print(f"\n🎯 ACTION ITEMS:")
    if recommendations:
        for i, rec in enumerate(recommendations, 1):
            print(f"\n{i}. [{rec['priority']}] {rec['issue']}")
            print(f"   → {rec['recommendation']}")
    else:
        print("  ✓ No critical issues found. Current run appears healthy.")
    
    print(f"\n💡 GENERAL RECOMMENDATIONS:")
    print(f"  1. Current run: {gen}/{config.get('NUM_GEN', 50)} generations")
    print(f"     → Consider increasing to 75-100 generations for better convergence")
    print(f"  2. Population size: {config.get('POP_SIZE', 120)}")
    print(f"     → Current size is good. Consider 150-200 for more diversity if time allows")
    print(f"  3. Trade frequency: {avg_trades:.2f} trades/day")
    print(f"     → Target: 2-5 trades/day. Current is {'BELOW' if avg_trades < 2 else 'WITHIN'} target range")
    print(f"  4. Pareto front: {len(hof)} solutions")
    print(f"     → Good diversity. Consider exploring different regions of the front")
    
    print(f"\n📝 NEXT RUN CONFIGURATION SUGGESTIONS:")
    print(f"  NUM_GEN: {max(75, config.get('NUM_GEN', 50) + 25)}  # Increase for better convergence")
    print(f"  POP_SIZE: {config.get('POP_SIZE', 120)}  # Keep current or increase to 150")
    print(f"  NUM_WORKERS: {config.get('NUM_WORKERS', 8)}  # Keep current")
    
    # Check if parameter ranges need adjustment
    print(f"\n🔧 PARAMETER RANGE ADJUSTMENTS TO CONSIDER:")
    critical_params = ['Min ATR Filter (Points)', 'Min Volume Multiplier', 'Long Trigger (% From Lower Band)', 'Short Trigger (% From Upper Band)']
    for param in critical_params:
        if param in param_stats_df['parameter'].values:
            row = param_stats_df[param_stats_df['parameter'] == param].iloc[0]
            if row['avg_trades_day'] < 2.0 if 'avg_trades_day' in row else False:
                print(f"  {param}: Current range may be too restrictive")
                print(f"    → Consider reducing max value to encourage more trades")
    
    print("\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)

if __name__ == '__main__':
    analyze_latest_run()


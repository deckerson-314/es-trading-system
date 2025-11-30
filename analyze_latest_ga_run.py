#!/usr/bin/env python3
"""
Comprehensive analysis of the latest GA run checkpoint.
"""

import os
import pickle
import pandas as pd
import numpy as np
from datetime import datetime
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
    from bollinger_strategy.parameters import load_params
    param_dict, param_df = load_params(PARAM_CSV, return_dataframe=True)
    return param_dict, param_df

def analyze_latest_run():
    """Comprehensive analysis of latest GA run."""
    checkpoint = load_checkpoint()
    if checkpoint is None:
        return
    
    param_dict, param_df = load_params()
    
    pop = checkpoint.get('population', [])
    hof = checkpoint.get('hall_of_fame', [])
    logbook = checkpoint.get('logbook', None)
    gen = checkpoint.get('generation', 0)
    config = checkpoint.get('config', {})
    start_time = checkpoint.get('start_time', None)
    
    print("="*80)
    print("COMPREHENSIVE GA RUN ANALYSIS")
    print("="*80)
    print(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if start_time:
        elapsed = datetime.now() - start_time
        print(f"Run Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Elapsed Time: {elapsed}")
    print(f"Current Generation: {gen}")
    print(f"Target Generations: {config.get('NUM_GEN', 'Unknown')}")
    print(f"Progress: {gen}/{config.get('NUM_GEN', 1)} ({100*gen/config.get('NUM_GEN', 1):.1f}%)")
    print(f"Population Size: {len(pop)}")
    print(f"Pareto Solutions: {len(hof)}")
    print()
    
    # Check fitness format
    if pop and len(pop) > 0:
        first_ind = pop[0]
        if hasattr(first_ind, 'fitness') and first_ind.fitness.valid:
            fitness_len = len(first_ind.fitness.values)
            print(f"Fitness Format: {fitness_len} objectives")
            if hasattr(creator, 'FitnessMulti'):
                weights = creator.FitnessMulti.weights
                print(f"Fitness Weights: {weights}")
                print(f"  - Sortino: {weights[0]} (maximize)")
                print(f"  - Drawdown: {weights[1]} (minimize)")
                print(f"  - Profit Factor: {weights[2]} (maximize)")
                print(f"  - Avg Trades/Day: {weights[3]} (maximize)")
                print(f"  - Total Profit: {weights[4]} (maximize)")
    print()
    
    # Logbook analysis - convergence trends
    if logbook:
        print("="*80)
        print("CONVERGENCE ANALYSIS")
        print("="*80)
        gens = logbook.select("gen")
        if len(gens) > 0:
            print(f"Generations Completed: {len(gens)}")
            
            # Extract all metrics
            metrics = {}
            if 'avg_sortino' in logbook.header:
                metrics['Sortino (Avg)'] = logbook.select("avg_sortino")
                if 'max_sortino' in logbook.header:
                    metrics['Sortino (Best)'] = logbook.select("max_sortino")
            
            if 'avg_dd' in logbook.header:
                metrics['Drawdown (Avg)'] = logbook.select("avg_dd")
                if 'min_dd' in logbook.header:
                    metrics['Drawdown (Best)'] = logbook.select("min_dd")
            
            if 'avg_pf' in logbook.header:
                metrics['Profit Factor (Avg)'] = logbook.select("avg_pf")
                if 'max_pf' in logbook.header:
                    metrics['Profit Factor (Best)'] = logbook.select("max_pf")
            
            if 'avg_trades_day' in logbook.header:
                metrics['Trades/Day (Avg)'] = logbook.select("avg_trades_day")
                if 'max_trades_day' in logbook.header:
                    metrics['Trades/Day (Best)'] = logbook.select("max_trades_day")
            
            if 'avg_total_profit' in logbook.header:
                metrics['Total Profit (Avg)'] = logbook.select("avg_total_profit")
                if 'max_total_profit' in logbook.header:
                    metrics['Total Profit (Best)'] = logbook.select("max_total_profit")
            
            # Show first, middle, and last generation
            if len(gens) >= 3:
                first_gen = 0
                mid_gen = len(gens) // 2
                last_gen = len(gens) - 1
                
                print(f"\nGeneration Comparison:")
                print(f"  {'Metric':<25} {'Gen 0':<15} {'Gen {mid_gen}':<15} {'Gen {last_gen}':<15} {'Trend':<10}")
                print(f"  {'-'*80}")
                
                for metric_name, values in metrics.items():
                    if len(values) > last_gen:
                        first_val = values[first_gen]
                        mid_val = values[mid_gen]
                        last_val = values[last_gen]
                        
                        # Calculate trend
                        if len(values) >= 10:
                            recent = np.mean(values[-5:])
                            prev = np.mean(values[-10:-5])
                            if prev != 0:
                                trend_pct = ((recent - prev) / abs(prev)) * 100
                                if abs(trend_pct) < 1:
                                    trend = "→ Stable"
                                elif trend_pct > 0:
                                    trend = f"↑ +{trend_pct:.1f}%"
                                else:
                                    trend = f"↓ {trend_pct:.1f}%"
                            else:
                                trend = "N/A"
                        else:
                            trend = "N/A"
                        
                        print(f"  {metric_name:<25} {first_val:<15.4f} {mid_val:<15.4f} {last_val:<15.4f} {trend:<10}")
            
            # Critical analysis for trades/day
            if 'avg_trades_day' in logbook.header:
                avg_trades = logbook.select("avg_trades_day")
                max_trades = logbook.select("max_trades_day") if 'max_trades_day' in logbook.header else []
                
                print(f"\n{'='*80}")
                print("TRADE FREQUENCY ANALYSIS (CRITICAL)")
                print(f"{'='*80}")
                
                if len(avg_trades) > 0:
                    print(f"Current Avg Trades/Day (population avg): {avg_trades[-1]:.4f}")
                    if len(max_trades) > 0:
                        print(f"Best Trades/Day (best individual): {max_trades[-1]:.4f}")
                    
                    # Trend analysis
                    if len(avg_trades) >= 10:
                        recent_5 = np.mean(avg_trades[-5:])
                        prev_5 = np.mean(avg_trades[-10:-5])
                        if prev_5 != 0:
                            improvement = ((recent_5 - prev_5) / abs(prev_5)) * 100
                            print(f"Recent Trend (last 5 vs prev 5 gens): {improvement:+.2f}%")
                            
                            if improvement > 5:
                                print(f"  ✓ GOOD: Trade frequency improving significantly")
                            elif improvement > 0:
                                print(f"  → SLOW: Trade frequency improving slowly")
                            elif improvement > -5:
                                print(f"  ⚠️  STABLE: Trade frequency stable (may have converged)")
                            else:
                                print(f"  🔴 DECLINING: Trade frequency getting worse")
                    
                    # Critical threshold check
                    current_avg = avg_trades[-1]
                    if current_avg < 0.01:
                        print(f"\n🔴 CRITICAL: Average trade frequency is extremely low (< 0.01)")
                        print(f"   This suggests the GA is converging to solutions with no trades")
                    elif current_avg < 0.1:
                        print(f"\n⚠️  WARNING: Average trade frequency is low (< 0.1)")
                        print(f"   This may indicate overly conservative parameters")
                    elif current_avg < 1.0:
                        print(f"\n⚠️  CAUTION: Average trade frequency is below target (< 1.0)")
                        print(f"   Target is typically 3+ trades/day")
                    else:
                        print(f"\n✓ ACCEPTABLE: Average trade frequency is reasonable (>= 1.0)")
    
    # Hall of Fame analysis
    if hof and len(hof) > 0:
        print(f"\n{'='*80}")
        print("PARETO FRONT ANALYSIS")
        print(f"{'='*80}")
        print(f"Total Pareto-Optimal Solutions: {len(hof)}")
        
        # Extract fitness values and parameters
        solutions = []
        param_keys = [k for k in param_dict.keys() if param_dict[k].get('type') != 'fixed']
        
        for i, ind in enumerate(hof):
            if hasattr(ind, 'fitness') and ind.fitness.valid:
                fitness = ind.fitness.values
                if len(fitness) >= 5:
                    # Extract and clamp parameters (same logic as _evaluate_worker)
                    params = {}
                    for j, key in enumerate(param_keys):
                        if j < len(ind):
                            raw_value = ind[j]
                            # Clamp to valid range (same as _evaluate_worker)
                            if key in param_dict:
                                param_info = param_dict[key]
                                param_min = param_info.get('min', None)
                                param_max = param_info.get('max', None)
                                param_type = param_info.get('type', 'float')
                                
                                # Only clamp numeric parameters
                                if param_type in ['int', 'float'] and param_min is not None and param_max is not None:
                                    try:
                                        # Clamp value
                                        clamped_value = max(param_min, min(raw_value, param_max))
                                        
                                        # Cast to appropriate type
                                        if param_type == 'int':
                                            clamped_value = int(round(clamped_value))
                                        else:
                                            clamped_value = float(clamped_value)
                                        
                                        params[key] = clamped_value
                                    except (TypeError, ValueError):
                                        # If clamping fails, use raw value
                                        params[key] = raw_value
                                else:
                                    # Non-numeric or fixed parameters - use as-is
                                    params[key] = raw_value
                            else:
                                params[key] = raw_value
                    
                    solutions.append({
                        'index': i,
                        'sortino': fitness[0],
                        'drawdown': fitness[1],
                        'profit_factor': fitness[2],
                        'avg_trades_day': fitness[3],
                        'total_profit': fitness[4],
                        **params
                    })
        
        if solutions:
            solutions_df = pd.DataFrame(solutions)
            
            print(f"\nTop 10 Solutions (sorted by Sortino):")
            print(f"{'Rank':<6} {'Sortino':<10} {'Drawdown':<12} {'PF':<8} {'Trades/Day':<12} {'Total Profit':<12}")
            print(f"{'-'*70}")
            
            solutions_sorted = solutions_df.sort_values('sortino', ascending=False)
            for rank, (idx, row) in enumerate(solutions_sorted.head(10).iterrows(), 1):
                mark = "★" if rank == 1 else " "
                print(f"{mark} {rank:<4} {row['sortino']:<10.4f} ${row['drawdown']:<11,.2f} {row['profit_factor']:<8.4f} {row['avg_trades_day']:<12.4f} {row['total_profit']:<12.4f}")
            
            print(f"\nKey Statistics Across All Pareto Solutions:")
            print(f"  Sortino: Min={solutions_df['sortino'].min():.4f}, Max={solutions_df['sortino'].max():.4f}, Mean={solutions_df['sortino'].mean():.4f}, Std={solutions_df['sortino'].std():.4f}")
            print(f"  Drawdown: Min=${solutions_df['drawdown'].min():,.2f}, Max=${solutions_df['drawdown'].max():,.2f}, Mean=${solutions_df['drawdown'].mean():,.2f}")
            print(f"  Profit Factor: Min={solutions_df['profit_factor'].min():.4f}, Max={solutions_df['profit_factor'].max():.4f}, Mean={solutions_df['profit_factor'].mean():.4f}")
            print(f"  Avg Trades/Day: Min={solutions_df['avg_trades_day'].min():.4f}, Max={solutions_df['avg_trades_day'].max():.4f}, Mean={solutions_df['avg_trades_day'].mean():.4f}")
            print(f"  Total Profit: Min={solutions_df['total_profit'].min():.4f}, Max={solutions_df['total_profit'].max():.4f}, Mean={solutions_df['total_profit'].mean():.4f}")
            
            # Parameter analysis - find which parameters are trending conservative
            print(f"\n{'='*80}")
            print("PARAMETER TREND ANALYSIS")
            print(f"{'='*80}")
            
            # Key parameters that affect trade frequency
            key_params = [
                'Min ATR Filter (Points)',
                'Min Volume Multiplier',
                'Long Trigger (% From Lower Band)',
                'Short Trigger (% From Upper Band)',
                'Initial Stop Loss (%)',
                'Bollinger Band Length',
                'Bollinger Band StdDev'
            ]
            
            print(f"\nKey Parameter Values (Best Solution by Sortino):")
            best_solution = solutions_sorted.iloc[0]
            for param in key_params:
                if param in best_solution:
                    value = best_solution[param]
                    param_info = param_dict.get(param, {})
                    param_min = param_info.get('min', 'N/A')
                    param_max = param_info.get('max', 'N/A')
                    param_range = param_max - param_min if isinstance(param_max, (int, float)) and isinstance(param_min, (int, float)) else None
                    
                    if param_range:
                        pct_of_range = ((value - param_min) / param_range) * 100
                        print(f"  {param:<35} {value:<10.4f} ({pct_of_range:.1f}% of range, min={param_min}, max={param_max})")
                    else:
                        print(f"  {param:<35} {value:<10.4f}")
            
            # Check for conservative trends
            print(f"\nConservative Parameter Check:")
            conservative_warnings = []
            
            if 'Min ATR Filter (Points)' in best_solution:
                atr_val = best_solution['Min ATR Filter (Points)']
                atr_info = param_dict.get('Min ATR Filter (Points)', {})
                atr_max = atr_info.get('max', 4.0)
                if atr_val > atr_max * 0.7:
                    conservative_warnings.append(f"Min ATR Filter ({atr_val:.2f}) is >70% of max ({atr_max}) - very conservative")
            
            if 'Min Volume Multiplier' in best_solution:
                vol_val = best_solution['Min Volume Multiplier']
                vol_info = param_dict.get('Min Volume Multiplier', {})
                vol_max = vol_info.get('max', 3.0)
                if vol_val > vol_max * 0.7:
                    conservative_warnings.append(f"Min Volume Multiplier ({vol_val:.2f}) is >70% of max ({vol_max}) - very conservative")
            
            if 'Long Trigger (% From Lower Band)' in best_solution:
                long_trig = best_solution['Long Trigger (% From Lower Band)']
                if long_trig > 2.0:
                    conservative_warnings.append(f"Long Trigger ({long_trig:.2f}%) is high - more restrictive")
            
            if 'Short Trigger (% From Upper Band)' in best_solution:
                short_trig = best_solution['Short Trigger (% From Upper Band)']
                if short_trig > 2.0:
                    conservative_warnings.append(f"Short Trigger ({short_trig:.2f}%) is high - more restrictive")
            
            if conservative_warnings:
                print(f"  ⚠️  WARNINGS:")
                for warning in conservative_warnings:
                    print(f"    - {warning}")
            else:
                print(f"  ✓ No overly conservative parameters detected")
            
            # Parameter distribution analysis
            print(f"\nParameter Distribution (Top 25% vs Bottom 25% by Sortino):")
            top_25_pct = int(len(solutions_df) * 0.25)
            top_solutions = solutions_sorted.head(max(1, top_25_pct))
            bottom_solutions = solutions_sorted.tail(max(1, top_25_pct))
            
            for param in key_params:
                if param in solutions_df.columns:
                    top_mean = top_solutions[param].mean()
                    bottom_mean = bottom_solutions[param].mean()
                    diff_pct = ((top_mean - bottom_mean) / bottom_mean * 100) if bottom_mean != 0 else 0
                    print(f"  {param:<35} Top25%: {top_mean:<8.4f}  Bottom25%: {bottom_mean:<8.4f}  Diff: {diff_pct:+.1f}%")
    
    # Overall assessment
    print(f"\n{'='*80}")
    print("OVERALL ASSESSMENT")
    print(f"{'='*80}")
    
    assessment_points = []
    
    if logbook and 'avg_trades_day' in logbook.header:
        avg_trades = logbook.select("avg_trades_day")
        if len(avg_trades) > 0:
            current_trades = avg_trades[-1]
            if current_trades < 0.01:
                assessment_points.append("🔴 CRITICAL: Trade frequency is near zero - GA may be broken")
            elif current_trades < 0.1:
                assessment_points.append("⚠️  WARNING: Trade frequency is very low - parameters too conservative")
            elif current_trades < 1.0:
                assessment_points.append("⚠️  CAUTION: Trade frequency below target - needs improvement")
            else:
                assessment_points.append("✓ Trade frequency is acceptable")
    
    if hof and len(hof) > 0:
        solutions_df = pd.DataFrame(solutions)
        max_trades = solutions_df['avg_trades_day'].max()
        if max_trades < 0.01:
            assessment_points.append("🔴 CRITICAL: Best solution has near-zero trades")
        elif max_trades < 1.0:
            assessment_points.append("⚠️  WARNING: Best solution has low trade frequency")
        else:
            assessment_points.append("✓ Best solution has reasonable trade frequency")
    
    if logbook and 'avg_sortino' in logbook.header:
        avg_sortino = logbook.select("avg_sortino")
        if len(avg_sortino) >= 10:
            recent = np.mean(avg_sortino[-5:])
            prev = np.mean(avg_sortino[-10:-5])
            if prev != 0:
                improvement = ((recent - prev) / abs(prev)) * 100
                if improvement > 1:
                    assessment_points.append("✓ Sortino is improving")
                elif improvement < -1:
                    assessment_points.append("⚠️  Sortino is declining")
                else:
                    assessment_points.append("→ Sortino has converged")
    
    for point in assessment_points:
        print(f"  {point}")
    
    print(f"\n{'='*80}")

if __name__ == '__main__':
    # Initialize DEAP creator if needed
    try:
        creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 100.0, 2.0))
    except:
        pass
    
    try:
        creator.create("Individual", list, fitness=creator.FitnessMulti)
    except:
        pass
    
    analyze_latest_run()

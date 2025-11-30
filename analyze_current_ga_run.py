#!/usr/bin/env python3
"""
Analyze the current GA run in progress to determine if it's worth continuing.
"""

import os
import pickle
import pandas as pd
import numpy as np
from datetime import datetime

CHECKPOINT_FILE = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'

def load_checkpoint():
    """Load GA checkpoint."""
    if not os.path.exists(CHECKPOINT_FILE):
        print(f"ERROR: Checkpoint file not found: {CHECKPOINT_FILE}")
        return None
    
    with open(CHECKPOINT_FILE, 'rb') as f:
        checkpoint = pickle.load(f)
    
    return checkpoint

def analyze_current_run():
    """Analyze current GA run and provide recommendation."""
    checkpoint = load_checkpoint()
    if checkpoint is None:
        return
    
    pop = checkpoint.get('population', [])
    hof = checkpoint.get('hall_of_fame', [])
    logbook = checkpoint.get('logbook', None)
    gen = checkpoint.get('generation', 0)
    config = checkpoint.get('config', {})
    
    print("="*80)
    print("CURRENT GA RUN ANALYSIS - CONTINUATION RECOMMENDATION")
    print("="*80)
    print(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Current Generation: {gen}")
    print(f"Target Generations: {config.get('NUM_GEN', 'Unknown')}")
    print(f"Progress: {gen}/{config.get('NUM_GEN', 'Unknown')} ({gen/config.get('NUM_GEN', 1)*100:.1f}%)")
    print()
    
    # Check fitness format
    if pop and len(pop) > 0:
        first_ind = pop[0]
        if hasattr(first_ind, 'fitness') and first_ind.fitness.valid:
            fitness_len = len(first_ind.fitness.values)
            print(f"Fitness Format: {fitness_len} objectives")
            if hasattr(creator, 'FitnessMulti'):
                weights = creator.FitnessMulti.weights
                print(f"Current Weights: {weights}")
                print(f"  - Sortino: {weights[0]}")
                print(f"  - Drawdown: {weights[1]} (minimize)")
                print(f"  - Profit Factor: {weights[2]}")
                print(f"  - Avg Trades/Day: {weights[3]} (INCREASED)")
                print(f"  - Total Profit: {weights[4]} (INCREASED)")
    
    print(f"\nCurrent Status:")
    print(f"  Population Size: {len(pop)}")
    print(f"  Pareto-Optimal Solutions: {len(hof)}")
    
    # Logbook analysis - check convergence trends
    if logbook:
        gens = logbook.select("gen")
        if len(gens) > 0:
            print(f"\n{'='*80}")
            print("CONVERGENCE TREND ANALYSIS")
            print(f"{'='*80}")
            print(f"Generations Completed: {len(gens)}")
            
            # Analyze recent vs early generations
            if len(gens) >= 10:
                early_gen = max(0, len(gens) // 4)  # First 25%
                mid_gen = len(gens) // 2  # Middle
                recent_gen = len(gens) - 1  # Latest
                
                print(f"\n  Generation Comparison:")
                print(f"    Early (Gen {gens[early_gen]}):")
                print(f"    Mid (Gen {gens[mid_gen]}):")
                print(f"    Recent (Gen {gens[recent_gen]}):")
                
                # Sortino
                if 'avg_sortino' in logbook.header:
                    avg_sortino = logbook.select("avg_sortino")
                    max_sortino = logbook.select("max_sortino") if 'max_sortino' in logbook.header else []
                    if len(avg_sortino) > 0:
                        print(f"\n  Sortino Ratio (normalized):")
                        print(f"    Early: {avg_sortino[early_gen]:.4f}")
                        print(f"    Mid: {avg_sortino[mid_gen]:.4f}")
                        print(f"    Recent: {avg_sortino[recent_gen]:.4f}")
                        if len(max_sortino) > 0:
                            print(f"    Best (Recent): {max_sortino[recent_gen]:.4f}")
                        
                        # Check if still improving
                        recent_window = 10
                        if len(avg_sortino) >= recent_window:
                            recent_avg = np.mean(avg_sortino[-recent_window:])
                            prev_avg = np.mean(avg_sortino[-recent_window*2:-recent_window])
                            improvement = ((recent_avg - prev_avg) / abs(prev_avg) * 100) if prev_avg != 0 else 0
                            print(f"    Recent Trend (last {recent_window} gens): {improvement:+.2f}%")
                            if abs(improvement) < 1.0:
                                print(f"    ⚠️  CONVERGED: Improvement < 1%")
                            elif improvement > 0:
                                print(f"    ✓ Still improving")
                            else:
                                print(f"    ⚠️  DECLINING: Getting worse")
                
                # Trade Frequency - CRITICAL METRIC
                if 'avg_trades_day' in logbook.header:
                    avg_trades = logbook.select("avg_trades_day")
                    max_trades = logbook.select("max_trades_day") if 'max_trades_day' in logbook.header else []
                    if len(avg_trades) > 0:
                        print(f"\n  Avg Trades/Day (normalized) - CRITICAL:")
                        print(f"    Early: {avg_trades[early_gen]:.4f}")
                        print(f"    Mid: {avg_trades[mid_gen]:.4f}")
                        print(f"    Recent: {avg_trades[recent_gen]:.4f}")
                        if len(max_trades) > 0:
                            print(f"    Best (Recent): {max_trades[recent_gen]:.4f}")
                        
                        # Check trend
                        recent_window = 10
                        if len(avg_trades) >= recent_window:
                            recent_avg = np.mean(avg_trades[-recent_window:])
                            prev_avg = np.mean(avg_trades[-recent_window*2:-recent_window])
                            improvement = ((recent_avg - prev_avg) / abs(prev_avg) * 100) if prev_avg != 0 else 0
                            print(f"    Recent Trend (last {recent_window} gens): {improvement:+.2f}%")
                            
                            # Critical threshold check
                            if avg_trades[recent_gen] < 0.01:
                                print(f"    🔴 CRITICAL: Trade frequency still very low (< 0.01)")
                            elif avg_trades[recent_gen] < 0.05:
                                print(f"    ⚠️  WARNING: Trade frequency low (< 0.05)")
                            else:
                                print(f"    ✓ Trade frequency acceptable (>= 0.05)")
                            
                            if abs(improvement) < 1.0:
                                print(f"    ⚠️  CONVERGED: No improvement in trade frequency")
                            elif improvement > 5.0:
                                print(f"    ✓ GOOD: Trade frequency improving significantly")
                            elif improvement > 0:
                                print(f"    ✓ Improving slowly")
                            else:
                                print(f"    🔴 DECLINING: Trade frequency getting worse")
                
                # Profit Factor
                if 'avg_pf' in logbook.header:
                    avg_pf = logbook.select("avg_pf")
                    max_pf = logbook.select("max_pf") if 'max_pf' in logbook.header else []
                    if len(avg_pf) > 0:
                        print(f"\n  Profit Factor (normalized):")
                        print(f"    Early: {avg_pf[early_gen]:.4f}")
                        print(f"    Mid: {avg_pf[mid_gen]:.4f}")
                        print(f"    Recent: {avg_pf[recent_gen]:.4f}")
                        if len(max_pf) > 0:
                            print(f"    Best (Recent): {max_pf[recent_gen]:.4f}")
                        
                        # Check if profitable
                        if avg_pf[recent_gen] < 0.2:  # 0.2 normalized = 1.0 actual (if max=5.0)
                            print(f"    🔴 CRITICAL: PF below profitability threshold")
                        elif avg_pf[recent_gen] < 0.4:
                            print(f"    ⚠️  WARNING: PF marginal")
                        else:
                            print(f"    ✓ PF acceptable")
                
                # Total Profit
                if 'avg_total_profit' in logbook.header:
                    avg_profit = logbook.select("avg_total_profit")
                    if len(avg_profit) > 0:
                        print(f"\n  Total Profit (normalized):")
                        print(f"    Early: {avg_profit[early_gen]:.4f}")
                        print(f"    Mid: {avg_profit[mid_gen]:.4f}")
                        print(f"    Recent: {avg_profit[recent_gen]:.4f}")
                        
                        if avg_profit[recent_gen] < 0.01:
                            print(f"    🔴 CRITICAL: Total profit very low")
                        elif avg_profit[recent_gen] < 0.1:
                            print(f"    ⚠️  WARNING: Total profit low")
                        else:
                            print(f"    ✓ Total profit acceptable")
    
    # Hall of Fame analysis
    if hof and len(hof) > 0:
        print(f"\n{'='*80}")
        print("CURRENT PARETO FRONT ANALYSIS")
        print(f"{'='*80}")
        print(f"Total Solutions: {len(hof)}")
        
        # Extract fitness values
        solutions = []
        for i, ind in enumerate(hof):
            if hasattr(ind, 'fitness') and ind.fitness.valid:
                fitness = ind.fitness.values
                if len(fitness) >= 5:
                    solutions.append({
                        'index': i,
                        'sortino': fitness[0],
                        'drawdown': fitness[1],
                        'profit_factor': fitness[2],
                        'avg_trades_day': fitness[3],
                        'total_profit': fitness[4]
                    })
        
        if solutions:
            solutions_df = pd.DataFrame(solutions)
            solutions_df = solutions_df.sort_values('sortino', ascending=False)
            
            print(f"\n  Top 5 Solutions (by Sortino):")
            print(f"    {'Rank':<6} {'Sortino':<10} {'Drawdown':<12} {'PF':<8} {'Trades/Day':<12} {'Total Profit':<12}")
            print(f"    {'-'*70}")
            for rank, (idx, row) in enumerate(solutions_df.head(5).iterrows(), 1):
                mark = "★" if rank == 1 else " "
                print(f"    {mark} {rank:<4} {row['sortino']:<10.4f} ${row['drawdown']:<11,.2f} {row['profit_factor']:<8.4f} {row['avg_trades_day']:<12.4f} {row['total_profit']:<12.4f}")
            
            print(f"\n  Key Statistics:")
            print(f"    Avg Trades/Day: Min={solutions_df['avg_trades_day'].min():.4f}, Max={solutions_df['avg_trades_day'].max():.4f}, Mean={solutions_df['avg_trades_day'].mean():.4f}")
            print(f"    Total Profit: Min={solutions_df['total_profit'].min():.4f}, Max={solutions_df['total_profit'].max():.4f}, Mean={solutions_df['total_profit'].mean():.4f}")
            print(f"    Sortino: Mean={solutions_df['sortino'].mean():.4f}, Max={solutions_df['sortino'].max():.4f}")
            print(f"    Profit Factor: Mean={solutions_df['profit_factor'].mean():.4f}, Max={solutions_df['profit_factor'].max():.4f}")
            
            # Critical checks
            max_trades = solutions_df['avg_trades_day'].max()
            mean_trades = solutions_df['avg_trades_day'].mean()
            max_profit = solutions_df['total_profit'].max()
            mean_profit = solutions_df['total_profit'].mean()
            
            print(f"\n  Critical Metrics Assessment:")
            if max_trades < 0.01:
                print(f"    🔴 Trade Frequency: CRITICAL - Max is {max_trades:.4f} (near zero)")
            elif max_trades < 0.05:
                print(f"    ⚠️  Trade Frequency: LOW - Max is {max_trades:.4f}")
            else:
                print(f"    ✓ Trade Frequency: ACCEPTABLE - Max is {max_trades:.4f}")
            
            if mean_trades < 0.01:
                print(f"    🔴 Mean Trade Frequency: CRITICAL - {mean_trades:.4f}")
            elif mean_trades < 0.05:
                print(f"    ⚠️  Mean Trade Frequency: LOW - {mean_trades:.4f}")
            else:
                print(f"    ✓ Mean Trade Frequency: ACCEPTABLE - {mean_trades:.4f}")
            
            if max_profit < 0.01:
                print(f"    🔴 Total Profit: CRITICAL - Max is {max_profit:.4f}")
            elif max_profit < 0.1:
                print(f"    ⚠️  Total Profit: LOW - Max is {max_profit:.4f}")
            else:
                print(f"    ✓ Total Profit: ACCEPTABLE - Max is {max_profit:.4f}")
    
    # Recommendation
    print(f"\n{'='*80}")
    print("RECOMMENDATION")
    print(f"{'='*80}")
    
    # Calculate remaining generations
    target_gen = config.get('NUM_GEN', 150)
    remaining = target_gen - gen
    
    # Make recommendation based on analysis
    recommendation = []
    score = 0
    
    if logbook and len(gens) >= 10:
        # Check if metrics are improving
        if 'avg_trades_day' in logbook.header:
            avg_trades = logbook.select("avg_trades_day")
            if len(avg_trades) >= 20:
                recent_avg = np.mean(avg_trades[-10:])
                prev_avg = np.mean(avg_trades[-20:-10])
                trades_improving = recent_avg > prev_avg * 1.01  # 1% improvement
                
                if avg_trades[-1] < 0.01:
                    recommendation.append("🔴 Trade frequency is CRITICALLY LOW (< 0.01) - increased weights not helping")
                    score -= 3
                elif avg_trades[-1] < 0.05:
                    recommendation.append("⚠️  Trade frequency is LOW (< 0.05) - needs improvement")
                    score -= 1
                else:
                    recommendation.append("✓ Trade frequency is acceptable")
                    score += 1
                
                if trades_improving:
                    recommendation.append("✓ Trade frequency is IMPROVING - worth continuing")
                    score += 2
                else:
                    recommendation.append("⚠️  Trade frequency NOT improving - may have converged")
                    score -= 1
        
        if 'avg_sortino' in logbook.header:
            avg_sortino = logbook.select("avg_sortino")
            if len(avg_sortino) >= 20:
                recent_avg = np.mean(avg_sortino[-10:])
                prev_avg = np.mean(avg_sortino[-20:-10])
                sortino_improving = recent_avg > prev_avg * 1.01
                
                if sortino_improving:
                    recommendation.append("✓ Sortino is improving - worth continuing")
                    score += 1
                else:
                    recommendation.append("⚠️  Sortino has converged - limited benefit from more generations")
                    score -= 1
    
    # Final recommendation
    print(f"\nRemaining Generations: {remaining}")
    print(f"\nAssessment Score: {score}/5")
    print(f"\nRecommendations:")
    for rec in recommendation:
        print(f"  {rec}")
    
    print(f"\n{'='*80}")
    if score >= 2:
        print("✓ RECOMMENDATION: CONTINUE - Metrics are improving or acceptable")
    elif score >= 0:
        print("⚠️  RECOMMENDATION: MARGINAL - Some improvement, but concerns remain")
    else:
        print("🔴 RECOMMENDATION: STOP - Critical issues not improving, consider restarting with different parameters")
    print(f"{'='*80}")

if __name__ == '__main__':
    # Import creator to check weights
    from deap import creator, base
    analyze_current_run()


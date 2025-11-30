#!/usr/bin/env python3
"""
Comprehensive diagnostic to find fundamental issues in GA fitness calculation.
"""

import os
import pickle
import pandas as pd
import numpy as np
from deap import creator, base
from bollinger_strategy import load_params

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

def diagnose_fundamental_issues():
    """Comprehensive diagnostic of GA fitness calculation."""
    checkpoint = load_checkpoint()
    if checkpoint is None:
        return
    
    pop = checkpoint.get('population', [])
    hof = checkpoint.get('hall_of_fame', [])
    gen = checkpoint.get('generation', 0)
    
    print("="*80)
    print("COMPREHENSIVE GA DIAGNOSTIC - FUNDAMENTAL ISSUES CHECK")
    print("="*80)
    print(f"Generation: {gen}")
    print()
    
    # Load parameters
    param_dict, _ = load_params(PARAM_CSV, return_dataframe=True)
    
    # Check 1: Fitness weights
    print("="*80)
    print("CHECK 1: FITNESS WEIGHTS")
    print("="*80)
    if hasattr(creator, 'FitnessMulti'):
        weights = creator.FitnessMulti.weights
        print(f"FitnessMulti weights: {weights}")
        print(f"  Expected: (1.0, -1.0, 1.0, 100.0, 2.0)")
        print(f"  Sortino (obj 0): {weights[0]} (should be 1.0)")
        print(f"  Drawdown (obj 1): {weights[1]} (should be -1.0)")
        print(f"  Profit Factor (obj 2): {weights[2]} (should be 1.0)")
        print(f"  Avg Trades/Day (obj 3): {weights[3]} (should be 100.0) ⚠️ CRITICAL")
        print(f"  Total Profit (obj 4): {weights[4]} (should be 2.0)")
        
        if weights[3] != 100.0:
            print(f"\n🔴 CRITICAL: Trades/Day weight is {weights[3]}, expected 100.0!")
            print(f"   This means the weight change didn't take effect!")
        else:
            print(f"\n✓ Trades/Day weight is correct (100.0)")
    else:
        print("🔴 ERROR: FitnessMulti class not found!")
    
    # Check 2: Sample fitness values from population
    print(f"\n{'='*80}")
    print("CHECK 2: SAMPLE FITNESS VALUES FROM POPULATION")
    print("="*80)
    
    if pop and len(pop) > 0:
        sample_size = min(10, len(pop))
        print(f"Analyzing {sample_size} random individuals from population:")
        print(f"{'Index':<8} {'Sortino':<12} {'Drawdown':<12} {'PF':<12} {'Trades/Day':<15} {'Total Profit':<15} {'Fitness Length'}")
        print("-"*90)
        
        for i in range(sample_size):
            ind = pop[i]
            if hasattr(ind, 'fitness') and ind.fitness.valid:
                fitness = ind.fitness.values
                print(f"{i:<8} {fitness[0]:<12.6f} {fitness[1]:<12.6f} {fitness[2]:<12.6f} {fitness[3] if len(fitness) > 3 else 'N/A':<15.6f} {fitness[4] if len(fitness) > 4 else 'N/A':<15.6f} {len(fitness)}")
            else:
                print(f"{i:<8} INVALID FITNESS")
        
        # Analyze trade frequency values
        trade_freqs = []
        for ind in pop:
            if hasattr(ind, 'fitness') and ind.fitness.valid:
                fitness = ind.fitness.values
                if len(fitness) > 3:
                    trade_freqs.append(fitness[3])
        
        if trade_freqs:
            print(f"\nTrade Frequency Statistics (normalized values):")
            print(f"  Min: {min(trade_freqs):.6f}")
            print(f"  Max: {max(trade_freqs):.6f}")
            print(f"  Mean: {np.mean(trade_freqs):.6f}")
            print(f"  Median: {np.median(trade_freqs):.6f}")
            
            # Check if values are in expected range (0-1 normalized)
            if max(trade_freqs) > 1.0:
                print(f"  ⚠️  WARNING: Max trade frequency > 1.0 (normalization issue?)")
            if max(trade_freqs) < 0.01:
                print(f"  🔴 CRITICAL: Max trade frequency < 0.01 (all solutions have near-zero trades)")
    
    # Check 3: Verify NSGA-II is using weights correctly
    print(f"\n{'='*80}")
    print("CHECK 3: NSGA-II WEIGHT USAGE")
    print("="*80)
    
    if pop and len(pop) > 0:
        # Check if individuals are sorted by weighted fitness
        # NSGA-II should rank by dominance, but weights affect selection
        print("Checking if trade frequency weight affects solution ranking...")
        
        # Get top solutions by different criteria
        solutions = []
        for i, ind in enumerate(pop):
            if hasattr(ind, 'fitness') and ind.fitness.valid:
                fitness = ind.fitness.values
                if len(fitness) >= 5:
                    # Calculate weighted fitness (how NSGA-II sees it)
                    weights = creator.FitnessMulti.weights
                    weighted_fitness = (
                        fitness[0] * weights[0] +  # Sortino
                        fitness[1] * weights[1] +  # Drawdown (negated)
                        fitness[2] * weights[2] +  # PF
                        fitness[3] * weights[3] +  # Trades/Day (should dominate)
                        fitness[4] * weights[4]    # Total Profit
                    )
                    solutions.append((i, ind, fitness, weighted_fitness))
        
        if solutions:
            # Sort by weighted fitness
            solutions.sort(key=lambda x: x[3], reverse=True)
            
            print(f"\nTop 5 Solutions by Weighted Fitness:")
            print(f"{'Rank':<6} {'Weighted Fit':<15} {'Trades/Day':<15} {'Sortino':<12} {'Contribution'}")
            print("-"*75)
            
            for rank, (idx, ind, fitness, wf) in enumerate(solutions[:5], 1):
                trades = fitness[3]
                sortino = fitness[0]
                weights = creator.FitnessMulti.weights
                trades_contrib = trades * weights[3]
                sortino_contrib = sortino * weights[0]
                print(f"{rank:<6} {wf:<15.6f} {trades:<15.6f} {sortino:<12.6f} Trades:{trades_contrib:.3f} Sortino:{sortino_contrib:.3f}")
            
            # Check if trade frequency is dominating
            top_trades = solutions[0][2][3]
            top_wf = solutions[0][3]
            weights = creator.FitnessMulti.weights
            trades_contrib = top_trades * weights[3]
            
            if trades_contrib > top_wf * 0.5:
                print(f"\n✓ Trade frequency IS dominating weighted fitness ({trades_contrib:.3f} out of {top_wf:.3f})")
            else:
                print(f"\n🔴 CRITICAL: Trade frequency is NOT dominating!")
                print(f"   Trade contribution: {trades_contrib:.3f}")
                print(f"   Total weighted fitness: {top_wf:.3f}")
                print(f"   Trade frequency weight may not be working!")
    
    # Check 4: Verify normalization ranges
    print(f"\n{'='*80}")
    print("CHECK 4: NORMALIZATION RANGES")
    print("="*80)
    
    # Check what normalization ranges are being used in the code
    print("Expected normalization ranges (from code):")
    print("  Sortino: 0-10.0 (SORTINO_MAX = 10.0)")
    print("  Drawdown: 0-100000.0 (DD_MAX = 100000.0)")
    print("  Profit Factor: 0-5.0 (PF_MAX = 5.0)")
    print("  Avg Trades/Day: 0-5.0 (TRADES_MAX = 5.0)")
    print("  Total Profit: 0-200000.0 (PNL_MAX = 200000.0)")
    print()
    print("⚠️  If actual trade frequency is very low (e.g., 0.001 trades/day),")
    print("   normalized value = 0.001 / 5.0 = 0.0002")
    print("   Even with weight 100.0, contribution = 0.0002 * 100.0 = 0.02")
    print("   This is still very small compared to other objectives!")
    
    # Check 5: Actual vs Normalized trade frequency
    print(f"\n{'='*80}")
    print("CHECK 5: ACTUAL VS NORMALIZED TRADE FREQUENCY")
    print("="*80)
    
    if pop and len(pop) > 0:
        # We need to run a backtest to get actual trade frequency
        # But we can check what the normalized values suggest
        print("Analyzing normalized trade frequency values...")
        
        trade_freqs_norm = []
        for ind in pop[:20]:  # Sample first 20
            if hasattr(ind, 'fitness') and ind.fitness.valid:
                fitness = ind.fitness.values
                if len(fitness) > 3:
                    trade_freqs_norm.append(fitness[3])
        
        if trade_freqs_norm:
            max_norm = max(trade_freqs_norm)
            mean_norm = np.mean(trade_freqs_norm)
            
            # Reverse normalize to estimate actual
            TRADES_MAX = 5.0  # From code
            max_actual_est = max_norm * TRADES_MAX
            mean_actual_est = mean_norm * TRADES_MAX
            
            print(f"Normalized trade frequency (from fitness):")
            print(f"  Max: {max_norm:.6f}")
            print(f"  Mean: {mean_norm:.6f}")
            print(f"\nEstimated actual trade frequency (reverse normalized):")
            print(f"  Max: {max_actual_est:.6f} trades/day")
            print(f"  Mean: {mean_actual_est:.6f} trades/day")
            
            if max_actual_est < 0.1:
                print(f"\n🔴 CRITICAL: Estimated actual trade frequency < 0.1 trades/day")
                print(f"   This means strategies are barely trading!")
                print(f"   Normalized value = {max_actual_est/TRADES_MAX:.6f}")
                print(f"   Even with weight 100.0, contribution = {max_actual_est/TRADES_MAX * 100.0:.3f}")
                print(f"   This is still very small!")
    
    # Check 6: Parameter values and their impact
    print(f"\n{'='*80}")
    print("CHECK 6: PARAMETER VALUES AND TRADE FREQUENCY")
    print("="*80)
    
    if pop and len(pop) > 0:
        # Build PARAM_RANGES to get parameter order
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
        
        # Check key parameters
        key_params = ['Min ATR Filter (Points)', 'Min Volume Multiplier', 
                     'Long Trigger (% From Lower Band)', 'Short Trigger (% From Upper Band)']
        
        print("Key parameters affecting trade frequency:")
        for key in key_params:
            if key in param_keys:
                idx = param_keys.index(key)
                values = []
                trade_freqs = []
                
                for ind in pop:
                    if hasattr(ind, 'fitness') and ind.fitness.valid and idx < len(ind):
                        val = ind[idx]
                        fitness = ind.fitness.values
                        values.append(val)
                        if len(fitness) > 3:
                            trade_freqs.append(fitness[3])
                
                if values:
                    pdata = param_dict[key]
                    pmin = pdata.get('min')
                    pmax = pdata.get('max')
                    mean_val = np.mean(values)
                    pct = ((mean_val - pmin) / (pmax - pmin) * 100) if pmax != pmin else 0
                    
                    conservative = "⚠️ CONSERVATIVE" if pct > 70 else ""
                    print(f"  {key}:")
                    print(f"    Mean: {mean_val:.4f} ({pct:.1f}% of range) {conservative}")
                    print(f"    Range: {pmin} - {pmax}")
                    
                    if trade_freqs:
                        corr = np.corrcoef(values, trade_freqs)[0, 1] if len(values) > 1 else 0
                        print(f"    Correlation with trade freq: {corr:+.3f}")
    
    # Check 7: Verify fitness calculation is correct
    print(f"\n{'='*80}")
    print("CHECK 7: FITNESS CALCULATION VERIFICATION")
    print("="*80)
    
    print("Checking if fitness values match expected format...")
    print("Expected: (normalized_sortino, normalized_dd, normalized_pf, normalized_trades, normalized_pnl)")
    print("All values should be in 0-1 range (except drawdown which is inverted)")
    
    if pop and len(pop) > 0:
        invalid_count = 0
        for ind in pop[:20]:  # Sample
            if hasattr(ind, 'fitness') and ind.fitness.valid:
                fitness = ind.fitness.values
                if len(fitness) >= 5:
                    # Check if values are in expected range
                    if fitness[0] < 0 or fitness[0] > 1.5:  # Sortino might exceed 1.0 if not capped
                        invalid_count += 1
                    if fitness[2] < 0 or fitness[2] > 1.5:  # PF
                        invalid_count += 1
                    if fitness[3] < 0 or fitness[3] > 1.5:  # Trades
                        invalid_count += 1
                    if fitness[4] < 0 or fitness[4] > 1.5:  # Profit
                        invalid_count += 1
        
        if invalid_count > 0:
            print(f"⚠️  WARNING: {invalid_count} individuals have values outside 0-1.5 range")
            print(f"   This suggests normalization may not be working correctly")
        else:
            print(f"✓ All sampled individuals have values in expected range")
    
    # Final diagnosis
    print(f"\n{'='*80}")
    print("DIAGNOSIS SUMMARY")
    print(f"{'='*80}")
    
    issues = []
    
    if hasattr(creator, 'FitnessMulti'):
        if creator.FitnessMulti.weights[3] != 100.0:
            issues.append("🔴 Trades/Day weight is not 100.0")
    
    if pop and len(pop) > 0:
        trade_freqs = [ind.fitness.values[3] for ind in pop if hasattr(ind, 'fitness') and ind.fitness.valid and len(ind.fitness.values) > 3]
        if trade_freqs and max(trade_freqs) < 0.01:
            issues.append("🔴 All solutions have near-zero trade frequency (< 0.01 normalized)")
            issues.append("   This suggests actual trade frequency is < 0.05 trades/day")
            issues.append("   Normalization makes this even smaller (0.05/5.0 = 0.01)")
            issues.append("   Even with weight 100.0, contribution = 0.01 * 100 = 1.0")
            issues.append("   But if Sortino is 0.2, contribution = 0.2 * 1.0 = 0.2")
            issues.append("   Trade frequency still doesn't dominate!")
    
    if issues:
        print("\n🔴 CRITICAL ISSUES FOUND:")
        for issue in issues:
            print(f"  {issue}")
    else:
        print("\n✓ No obvious critical issues found in basic checks")
        print("  May need to investigate actual backtest results")
    
    print(f"\n{'='*80}")

if __name__ == '__main__':
    diagnose_fundamental_issues()


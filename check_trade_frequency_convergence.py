#!/usr/bin/env python3
"""
Check trade frequency convergence in the GA run.
"""

import pickle
import os
import pandas as pd
import numpy as np

CHECKPOINT_FILE = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'

def check_trade_convergence():
    """Check trade frequency convergence."""
    
    # Load checkpoint
    if not os.path.exists(CHECKPOINT_FILE):
        print(f"ERROR: Checkpoint not found: {CHECKPOINT_FILE}")
        return
    
    with open(CHECKPOINT_FILE, 'rb') as f:
        checkpoint = pickle.load(f)
    
    logbook = checkpoint.get('logbook', None)
    gen = checkpoint.get('generation', 0)
    
    print("="*80)
    print("TRADE FREQUENCY CONVERGENCE ANALYSIS")
    print("="*80)
    print(f"Current Generation: {gen}")
    print()
    
    if logbook is None:
        print("No logbook data available")
        return
    
    # Extract trade frequency data from logbook
    if 'avg_trades_day' in logbook.chapters:
        trades_chapter = logbook.chapters['avg_trades_day']
        
        print("GENERATION-BY-GENERATION TRADE FREQUENCY:")
        print()
        print(f"{'Gen':<6} {'Best':<12} {'Avg':<12} {'Max':<12} {'Min':<12}")
        print("-" * 60)
        
        # Show first 5, last 10, and every 10th in between
        gens_to_show = set(range(min(5, len(trades_chapter))))
        if len(trades_chapter) > 10:
            gens_to_show.update(range(len(trades_chapter) - 10, len(trades_chapter)))
        for i in range(0, len(trades_chapter), 10):
            gens_to_show.add(i)
        
        for gen_idx in sorted(gens_to_show):
            if gen_idx < len(trades_chapter):
                entry = trades_chapter[gen_idx]
                gen_num = entry.get('gen', gen_idx)
                best = entry.get('best', 0)
                avg = entry.get('avg', 0)
                max_val = entry.get('max', 0)
                min_val = entry.get('min', 0)
                print(f"{gen_num:<6} {best:<12.3f} {avg:<12.3f} {max_val:<12.3f} {min_val:<12.3f}")
        
        print()
        print("="*80)
        print("TREND ANALYSIS")
        print("="*80)
        
        # Early vs recent
        if len(trades_chapter) >= 10:
            early_entries = trades_chapter[:10]
            recent_entries = trades_chapter[-10:]
            
            early_avg = np.mean([e.get('avg', 0) for e in early_entries])
            recent_avg = np.mean([e.get('avg', 0) for e in recent_entries])
            early_best = np.mean([e.get('best', 0) for e in early_entries])
            recent_best = np.mean([e.get('best', 0) for e in recent_entries])
            
            print(f"Early generations (0-9):")
            print(f"  Average: {early_avg:.3f} trades/day")
            print(f"  Best: {early_best:.3f} trades/day")
            print()
            print(f"Recent generations (last 10):")
            print(f"  Average: {recent_avg:.3f} trades/day")
            print(f"  Best: {recent_best:.3f} trades/day")
            print()
            print(f"Change:")
            print(f"  Average: {recent_avg - early_avg:+.3f} trades/day")
            print(f"  Best: {recent_best - early_best:+.3f} trades/day")
        
        # Latest generation
        if trades_chapter:
            latest = trades_chapter[-1]
            print()
            print("="*80)
            print("LATEST GENERATION")
            print("="*80)
            print(f"Generation: {latest.get('gen', 'N/A')}")
            print(f"Best: {latest.get('best', 0):.3f} trades/day")
            print(f"Average: {latest.get('avg', 0):.3f} trades/day")
            print(f"Max: {latest.get('max', 0):.3f} trades/day")
            print(f"Min: {latest.get('min', 0):.3f} trades/day")
    
    # Also check Hall of Fame distribution
    hof = checkpoint.get('hall_of_fame', [])
    if hof:
        print()
        print("="*80)
        print("HALL OF FAME TRADE FREQUENCY DISTRIBUTION")
        print("="*80)
        
        # Extract avg_trades_day from fitness values
        # Fitness tuple: (sortino, drawdown, pf, trades_day, total_profit)
        trades_values = []
        for ind in hof:
            if hasattr(ind, 'fitness') and ind.fitness.valid:
                if len(ind.fitness.values) >= 4:
                    trades_values.append(ind.fitness.values[3])  # 4th element is trades/day
        
        if trades_values:
            trades_array = np.array(trades_values)
            print(f"Total solutions: {len(trades_values)}")
            print(f"Mean: {trades_array.mean():.3f} trades/day")
            print(f"Median: {np.median(trades_array):.3f} trades/day")
            print(f"Min: {trades_array.min():.3f} trades/day")
            print(f"Max: {trades_array.max():.3f} trades/day")
            print(f"Std: {trades_array.std():.3f} trades/day")
            print()
            
            # Distribution buckets
            below_1 = (trades_array < 1.0).sum()
            between_1_3 = ((trades_array >= 1.0) & (trades_array < 3.0)).sum()
            between_3_5 = ((trades_array >= 3.0) & (trades_array < 5.0)).sum()
            above_5 = (trades_array >= 5.0).sum()
            
            print("Distribution:")
            print(f"  < 1 trade/day: {below_1} solutions ({100*below_1/len(trades_values):.1f}%)")
            print(f"  1-3 trades/day: {between_1_3} solutions ({100*between_1_3/len(trades_values):.1f}%)")
            print(f"  3-5 trades/day: {between_3_5} solutions ({100*between_3_5/len(trades_values):.1f}%)")
            print(f"  >= 5 trades/day: {above_5} solutions ({100*above_5/len(trades_values):.1f}%)")
            
            # Top 10 solutions
            top_indices = np.argsort(trades_array)[-10:][::-1]
            print()
            print("Top 10 solutions by trade frequency:")
            for i, idx in enumerate(top_indices, 1):
                print(f"  {i}. Solution {idx}: {trades_array[idx]:.3f} trades/day")

if __name__ == '__main__':
    check_trade_convergence()


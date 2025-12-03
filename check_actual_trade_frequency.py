#!/usr/bin/env python3
"""
Check actual (non-normalized) trade frequency from logbook.
"""

import pickle
import os
import pandas as pd
import numpy as np

CHECKPOINT_FILE = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'

def check_actual_trades():
    """Check actual trade frequency from logbook."""
    
    # Load checkpoint
    if not os.path.exists(CHECKPOINT_FILE):
        print(f"ERROR: Checkpoint not found: {CHECKPOINT_FILE}")
        return
    
    with open(CHECKPOINT_FILE, 'rb') as f:
        checkpoint = pickle.load(f)
    
    logbook = checkpoint.get('logbook', None)
    gen = checkpoint.get('generation', 0)
    
    print("="*80)
    print("ACTUAL TRADE FREQUENCY FROM LOGBOOK")
    print("="*80)
    print(f"Current Generation: {gen}")
    print()
    
    if logbook is None:
        print("No logbook data available")
        return
    
    # Check what chapters exist
    print("Available logbook chapters:")
    for chapter_name in logbook.chapters.keys():
        print(f"  - {chapter_name}")
    print()
    
    # Check the main logbook records
    if logbook:
        print("="*80)
        print("GENERATION-BY-GENERATION DATA")
        print("="*80)
        
        # Get all records
        records = logbook
        
        # Show available keys in first record
        if records:
            print("Available keys in logbook records:")
            for key in records[0].keys():
                print(f"  - {key}")
            print()
            
            # Show trade frequency data
            print(f"{'Gen':<6} {'avg_trades_day':<18} {'max_trades_day':<18}")
            print("-" * 50)
            
            # Show first 5, last 15, and every 10th in between
            gens_to_show = set(range(min(5, len(records))))
            if len(records) > 15:
                gens_to_show.update(range(len(records) - 15, len(records)))
            for i in range(0, len(records), 10):
                gens_to_show.add(i)
            
            for gen_idx in sorted(gens_to_show):
                if gen_idx < len(records):
                    entry = records[gen_idx]
                    gen_num = entry.get('gen', gen_idx)
                    avg_trades = entry.get('avg_trades_day', 'N/A')
                    max_trades = entry.get('max_trades_day', 'N/A')
                    print(f"{gen_num:<6} {str(avg_trades):<18} {str(max_trades):<18}")
            
            print()
            print("="*80)
            print("TREND ANALYSIS")
            print("="*80)
            
            # Early vs recent
            if len(records) >= 10:
                early_entries = records[:10]
                recent_entries = records[-10:]
                
                early_avg = np.mean([e.get('avg_trades_day', 0) for e in early_entries if isinstance(e.get('avg_trades_day'), (int, float))])
                recent_avg = np.mean([e.get('avg_trades_day', 0) for e in recent_entries if isinstance(e.get('avg_trades_day'), (int, float))])
                
                print(f"Early generations (0-9):")
                print(f"  Average: {early_avg:.3f} trades/day")
                print()
                print(f"Recent generations (last 10):")
                print(f"  Average: {recent_avg:.3f} trades/day")
                print()
                print(f"Change: {recent_avg - early_avg:+.3f} trades/day")
            
            # Latest generation
            if records:
                latest = records[-1]
                print()
                print("="*80)
                print("LATEST GENERATION")
                print("="*80)
                print(f"Generation: {latest.get('gen', 'N/A')}")
                print(f"Average trades/day: {latest.get('avg_trades_day', 'N/A')}")
                print(f"Max trades/day: {latest.get('max_trades_day', 'N/A')}")
                
                # Check for actual metrics if available
                if 'actual_avg_trades_day' in latest:
                    print(f"Actual average trades/day: {latest.get('actual_avg_trades_day', 'N/A')}")
                if 'actual_sortino_best' in latest:
                    print(f"Actual Sortino (best): {latest.get('actual_sortino_best', 'N/A')}")

if __name__ == '__main__':
    check_actual_trades()


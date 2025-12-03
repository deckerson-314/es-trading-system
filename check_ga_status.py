#!/usr/bin/env python3
"""Quick check of current GA run status."""

import pickle
import os
from datetime import datetime

CHECKPOINT_FILE = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'

if not os.path.exists(CHECKPOINT_FILE):
    print("No checkpoint file found - GA may not be running or hasn't started yet.")
    exit(0)

with open(CHECKPOINT_FILE, 'rb') as f:
    checkpoint = pickle.load(f)

gen = checkpoint.get('generation', 0)
hof = checkpoint.get('hall_of_fame', [])
pop = checkpoint.get('population', [])
logbook = checkpoint.get('logbook', None)
config = checkpoint.get('config', {})

print("="*80)
print("GA RUN STATUS")
print("="*80)
print(f"Generation: {gen}")
if 'NUM_GEN' in config:
    total_gen = config.get('NUM_GEN', 0)
    progress = (gen / total_gen * 100) if total_gen > 0 else 0
    print(f"Total Generations: {total_gen}")
    print(f"Progress: {progress:.1f}%")
print(f"Hall of Fame size: {len(hof)}")
print(f"Population size: {len(pop)}")
print()

if logbook:
    records = logbook
    if len(records) > 0:
        latest = records[-1]
        print("="*80)
        print("LATEST GENERATION METRICS")
        print("="*80)
        print(f"Generation: {latest.get('gen', 'N/A')}")
        print(f"Avg Trades/Day: {latest.get('avg_trades_day', 0):.3f}")
        print(f"Max Trades/Day: {latest.get('max_trades_day', 0):.3f}")
        print(f"Avg Sortino: {latest.get('avg_sortino', 0):.6f}")
        print(f"Max Sortino: {latest.get('max_sortino', 0):.6f}")
        print(f"Avg Drawdown: {latest.get('avg_dd', 0):.2f}")
        print(f"Min Drawdown: {latest.get('min_dd', 0):.2f}")
        print(f"Avg Profit Factor: {latest.get('avg_pf', 0):.6f}")
        print(f"Max Profit Factor: {latest.get('max_pf', 0):.6f}")
        print(f"Pareto Front Size: {latest.get('pareto_size', 0)}")
        print()
        
        if len(records) >= 5:
            early = records[0]
            print("="*80)
            print("TREND ANALYSIS (Generation 0 vs Latest)")
            print("="*80)
            early_trades = early.get('avg_trades_day', 0)
            latest_trades = latest.get('avg_trades_day', 0)
            trades_change = latest_trades - early_trades
            trades_pct = (trades_change / early_trades * 100) if early_trades > 0 else 0
            
            early_sortino = early.get('avg_sortino', 0)
            latest_sortino = latest.get('avg_sortino', 0)
            sortino_change = latest_sortino - early_sortino
            
            early_pf = early.get('avg_pf', 0)
            latest_pf = latest.get('avg_pf', 0)
            pf_change = latest_pf - early_pf
            
            print(f"Trades/Day: {early_trades:.3f} → {latest_trades:.3f} ({trades_change:+.3f}, {trades_pct:+.1f}%)")
            print(f"Sortino: {early_sortino:.6f} → {latest_sortino:.6f} ({sortino_change:+.6f})")
            print(f"Profit Factor: {early_pf:.6f} → {latest_pf:.6f} ({pf_change:+.6f})")
            print()
            
            # Check if trades/day is improving
            if latest_trades > 0.5:
                print("✅ Trade frequency looks reasonable (> 0.5 trades/day)")
            elif latest_trades > 0.1:
                print("⚠️  Trade frequency is low (0.1-0.5 trades/day)")
            else:
                print("🔴 Trade frequency is very low (< 0.1 trades/day)")
            
            # Check Sortino trend
            if sortino_change > 0:
                print("✅ Sortino is improving")
            elif sortino_change > -0.1:
                print("⚠️  Sortino is stable (minimal change)")
            else:
                print("🔴 Sortino is declining")
            
            # Check Pareto front growth
            early_pareto = early.get('pareto_size', 0)
            latest_pareto = latest.get('pareto_size', 0)
            if latest_pareto > early_pareto * 2:
                print("✅ Pareto front is growing (good diversity)")
            elif latest_pareto > early_pareto:
                print("⚠️  Pareto front is growing slowly")
            else:
                print("🔴 Pareto front is not growing (possible convergence)")

print()
print("="*80)
print("KEY OBSERVATIONS")
print("="*80)
print("With the new Max Volume and Max ATR filters:")
print("  - Volume filter now allows LOW volume (good for mean reversion)")
print("  - ATR filter now allows LOW volatility (good for mean reversion)")
print("  - Strategy should now correctly identify exhausted moves")
print()
print("Monitor:")
print("  1. Trade frequency - should be > 1 trade/day (target: 2-5)")
print("  2. Sortino ratio - should be improving and positive")
print("  3. Parameter convergence - check if Max Volume/ATR are reasonable")
print("  4. Pareto front size - should be growing (indicates diversity)")


#!/usr/bin/env python3
"""
Verify Sortino calculation by running the exact same backtest as the dashboard.
"""

import pickle
import os
import sys
import pandas as pd
import numpy as np
from bollinger_strategy.parameters import load_params
from BB_Genetic_v3 import run_backtest

CHECKPOINT_FILE = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'
PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'
DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'

def verify_sortino():
    """Verify Sortino calculation matches dashboard."""
    
    # Load checkpoint
    if not os.path.exists(CHECKPOINT_FILE):
        print(f"ERROR: Checkpoint not found: {CHECKPOINT_FILE}")
        return
    
    with open(CHECKPOINT_FILE, 'rb') as f:
        checkpoint = pickle.load(f)
    
    hof = checkpoint.get('hall_of_fame', [])
    gen = checkpoint.get('generation', 0)
    
    print("="*80)
    print("SORTINO CALCULATION VERIFICATION")
    print("="*80)
    print(f"Generation: {gen}")
    print(f"Hall of Fame size: {len(hof)}")
    print()
    
    if not hof:
        print("No solutions in Hall of Fame")
        return
    
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
    
    # Find best solution (highest Sortino) - same logic as dashboard
    best_ind = None
    best_sortino_fitness = -float('inf')
    
    for ind in hof:
        if hasattr(ind, 'fitness') and ind.fitness.valid:
            if len(ind.fitness.values) >= 1:
                sortino_val = ind.fitness.values[0]
                if sortino_val > best_sortino_fitness:
                    best_sortino_fitness = sortino_val
                    best_ind = ind
    
    if best_ind is None:
        print("No valid solution found")
        return
    
    print("Best Solution (Highest Sortino Fitness):")
    print(f"  Normalized Sortino (fitness): {best_sortino_fitness:.6f}")
    print()
    
    # Reconstruct parameters - same as dashboard
    params = {}
    for i, key in enumerate(param_keys):
        if i < len(best_ind):
            params[key] = best_ind[i]
    
    # Clamp parameters - same as dashboard
    for n, v in params.items():
        if n in param_dict:
            mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
            v = max(mn, min(v, mx))
            if typ == 'int':
                params[n] = int(round(v))
            else:
                params[n] = float(v)
    
    # Load data - same as GA
    print("Loading data...")
    df = pd.read_csv(DATA_CSV, header=None,
                    names=['datetime', 'open', 'high', 'low', 'close', 'volume'],
                    parse_dates=['datetime'], index_col='datetime')
    
    # Get in-sample data - same split logic as GA
    # Check if interleaved split is used
    USE_INTERLEAVED = param_dict.get('USE_INTERLEAVED_SPLIT', {}).get('value', 0)
    NUM_PERIODS = param_dict.get('NUM_SPLIT_PERIODS', {}).get('value', 1)
    
    if USE_INTERLEAVED and NUM_PERIODS > 1:
        print(f"Using interleaved split with {NUM_PERIODS} periods")
        df = df.sort_index()
        period_size = len(df) // NUM_PERIODS
        is_periods = []
        for i in range(NUM_PERIODS):
            if i % 2 == 0:  # Even periods are IS
                start_idx = i * period_size
                end_idx = (i + 1) * period_size if i < NUM_PERIODS - 1 else len(df)
                is_periods.append(df.iloc[start_idx:end_idx].copy())
        in_sample = pd.concat(is_periods).sort_index() if is_periods else df.iloc[:int(len(df)*0.6)]
    else:
        # Simple 60/40 split
        split_idx = int(len(df) * 0.6)
        in_sample = df.iloc[:split_idx].copy()
    
    print(f"In-sample data: {len(in_sample):,} rows")
    print(f"Date range: {in_sample.index[0]} to {in_sample.index[-1]}")
    print()
    
    # Run backtest - same as dashboard
    print("Running backtest (same as dashboard)...")
    result = run_backtest(params, in_sample, param_dict, suppress_output=True)
    
    print()
    print("="*80)
    print("BACKTEST RESULTS")
    print("="*80)
    print(f"Sortino Ratio: {result.get('sortino', 0):.6f}")
    print(f"Max Drawdown: ${result.get('max_drawdown', 0):,.2f}")
    print(f"Profit Factor: {result.get('profit_factor', 0):.6f}")
    print(f"Total Profit: ${result.get('total_profit', 0):,.2f}")
    print(f"Avg Trades/Day: {result.get('avg_trades_day', 0):.3f}")
    print()
    
    # Detailed Sortino calculation breakdown
    trades_df = result.get('trades_df', pd.DataFrame())
    if not trades_df.empty:
        print("="*80)
        print("DETAILED SORTINO CALCULATION")
        print("="*80)
        
        # Replicate the exact calculation from run_backtest
        min_d = trades_df['exit_time'].min().date()
        max_d = trades_df['exit_time'].max().date()
        daily_pnl = trades_df.groupby(trades_df['exit_time'].dt.date)['pnl'].sum()\
                             .reindex(pd.date_range(min_d, max_d), fill_value=0)
        equity = 50000 + daily_pnl.cumsum()
        rets = equity.pct_change().dropna()
        
        print(f"Total trades: {len(trades_df)}")
        print(f"Trading days: {len(daily_pnl)}")
        print(f"Daily returns calculated: {len(rets)}")
        print()
        
        print("Return Statistics:")
        print(f"  Mean daily return: {rets.mean():.6f} ({rets.mean()*100:.4f}%)")
        print(f"  Std of returns: {rets.std():.6f}")
        print(f"  Annualized return: {rets.mean() * 252:.6f} ({rets.mean() * 252 * 100:.2f}%)")
        print()
        
        # Downside returns
        downside_rets = rets[rets < 0]
        print("Downside Statistics:")
        print(f"  Number of negative return days: {len(downside_rets)}")
        if len(downside_rets) > 0:
            print(f"  Mean downside return: {downside_rets.mean():.6f}")
            print(f"  Downside std: {downside_rets.std():.6f}")
        else:
            print(f"  ⚠️  NO NEGATIVE RETURN DAYS!")
        print()
        
        # Sortino calculation
        if len(rets) < 2:
            calculated_sortino = 0.0
            print("Sortino: 0.0 (insufficient data)")
        else:
            if len(downside_rets) == 0 or downside_rets.std() == 0:
                print("⚠️  NO DOWNSIDE VOLATILITY - Using special calculation:")
                min_downside_std = 0.001  # 0.1% daily downside volatility floor
                annualized_return = rets.mean() * 252
                calculated_sortino = (annualized_return / min_downside_std) if rets.mean() > 0 else 0.0
                sortino_cap = param_dict.get('SORTINO_CAP', {}).get('value', 10.0)
                calculated_sortino = min(calculated_sortino, sortino_cap)
                print(f"  Annualized return: {annualized_return:.6f}")
                print(f"  Min downside std (floor): {min_downside_std:.6f}")
                print(f"  Un-capped Sortino: {annualized_return / min_downside_std:.6f}")
                print(f"  Sortino cap: {sortino_cap:.2f}")
                print(f"  Final Sortino: {calculated_sortino:.6f}")
            else:
                downside_std = downside_rets.std()
                calculated_sortino = (rets.mean() / downside_std * np.sqrt(252)) if downside_std != 0 else 0.0
                sortino_cap = param_dict.get('SORTINO_CAP', {}).get('value', 10.0)
                calculated_sortino = min(calculated_sortino, sortino_cap)
                print(f"  Mean return: {rets.mean():.6f}")
                print(f"  Downside std: {downside_std:.6f}")
                print(f"  Annualized: {rets.mean() * np.sqrt(252):.6f}")
                print(f"  Un-capped Sortino: {rets.mean() / downside_std * np.sqrt(252):.6f}")
                print(f"  Sortino cap: {sortino_cap:.2f}")
                print(f"  Final Sortino: {calculated_sortino:.6f}")
        
        print()
        print("="*80)
        print("VERIFICATION")
        print("="*80)
        print(f"Calculated Sortino: {calculated_sortino:.6f}")
        print(f"Result Sortino: {result.get('sortino', 0):.6f}")
        if abs(calculated_sortino - result.get('sortino', 0)) < 0.0001:
            print("✅ Sortino calculation matches!")
        else:
            print(f"⚠️  DISCREPANCY: Difference of {abs(calculated_sortino - result.get('sortino', 0)):.6f}")
        
        # Check if this matches dashboard value
        print()
        print("Expected dashboard value: 4.166570")
        print(f"Actual calculated value: {calculated_sortino:.6f}")
        if abs(calculated_sortino - 4.166570) < 0.0001:
            print("✅ Matches dashboard value!")
        else:
            print(f"⚠️  Does NOT match dashboard. Difference: {abs(calculated_sortino - 4.166570):.6f}")
            print()
            print("Possible reasons:")
            print("  1. Dashboard is showing a different solution")
            print("  2. Dashboard is using different data split")
            print("  3. Dashboard calculation has a bug")
            print("  4. Dashboard value is from a cached/old result")

if __name__ == '__main__':
    verify_sortino()


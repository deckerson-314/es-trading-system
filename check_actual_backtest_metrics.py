#!/usr/bin/env python3
"""
Check actual backtest results for the best solution to understand Sortino vs Profit relationship.
"""

import pickle
import os
import sys
import pandas as pd
from bollinger_strategy.parameters import load_params
from BB_Genetic_v3 import run_backtest

CHECKPOINT_FILE = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'
PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'

def check_actual_metrics():
    """Check actual backtest metrics for best solution."""
    
    # Load checkpoint
    if not os.path.exists(CHECKPOINT_FILE):
        print(f"ERROR: Checkpoint not found: {CHECKPOINT_FILE}")
        return
    
    with open(CHECKPOINT_FILE, 'rb') as f:
        checkpoint = pickle.load(f)
    
    hof = checkpoint.get('hall_of_fame', [])
    gen = checkpoint.get('generation', 0)
    
    print("="*80)
    print("ACTUAL BACKTEST METRICS ANALYSIS")
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
    
    if best_ind is None:
        print("No valid solution found")
        return
    
    print("Best Solution (Highest Sortino):")
    print(f"  Normalized Sortino (fitness): {best_sortino:.6f}")
    print()
    
    # Reconstruct parameters
    params = {}
    for i, key in enumerate(param_keys):
        if i < len(best_ind):
            params[key] = best_ind[i]
    
    # Load data (same way as GA)
    print("Loading data and running actual backtest...")
    try:
        DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'
        df = pd.read_csv(DATA_CSV, header=None,
                        names=['datetime', 'open', 'high', 'low', 'close', 'volume'],
                        parse_dates=['datetime'], index_col='datetime')
        
        # Get in-sample data (60% split, same as GA)
        total_rows = len(df)
        split_idx = int(total_rows * 0.6)  # 60% in-sample
        in_sample_df = df.iloc[:split_idx].copy()
        
        # Run actual backtest
        result = run_backtest(params, in_sample_df, param_dict, suppress_output=True)
        
        print()
        print("="*80)
        print("ACTUAL BACKTEST RESULTS (IN-SAMPLE)")
        print("="*80)
        print(f"Sortino Ratio: {result.get('sortino', 0):.6f}")
        print(f"Max Drawdown: ${result.get('max_drawdown', 0):,.2f}")
        print(f"Profit Factor: {result.get('profit_factor', 0):.6f}")
        print(f"Total Profit: ${result.get('total_profit', 0):,.2f}")
        print(f"Avg Trades/Day: {result.get('avg_trades_day', 0):.3f}")
        
        # Get trades dataframe for more details
        trades_df = result.get('trades_df', None)
        if trades_df is not None and not trades_df.empty:
            num_trades = len(trades_df)
            wins = (trades_df['pnl'] > 0).sum()
            losses = (trades_df['pnl'] < 0).sum()
            win_rate = (wins / num_trades * 100) if num_trades > 0 else 0
            avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean() if wins > 0 else 0
            avg_loss = trades_df[trades_df['pnl'] < 0]['pnl'].mean() if losses > 0 else 0
            
            print()
            print("Trade Statistics:")
            print(f"  Total Trades: {num_trades}")
            print(f"  Wins: {wins} ({win_rate:.1f}%)")
            print(f"  Losses: {losses}")
            print(f"  Avg Win: ${avg_win:,.2f}")
            print(f"  Avg Loss: ${avg_loss:,.2f}")
            
            # Calculate return on capital
            initial_capital = 100000  # Default
            if 'initial_capital' in result:
                initial_capital = result['initial_capital']
            
            total_profit = result.get('total_profit', 0)
            return_pct = (total_profit / initial_capital * 100) if initial_capital > 0 else 0
            
            print()
            print("Return Analysis:")
            print(f"  Initial Capital: ${initial_capital:,.2f}")
            print(f"  Total Profit: ${total_profit:,.2f}")
            print(f"  Return: {return_pct:.2f}%")
            print(f"  Max Drawdown: ${result.get('max_drawdown', 0):,.2f} ({result.get('max_drawdown', 0)/initial_capital*100:.2f}%)")
            
            # Sortino analysis
            sortino = result.get('sortino', 0)
            print()
            print("Sortino Analysis:")
            print(f"  Sortino Ratio: {sortino:.6f}")
            if sortino > 0:
                # Sortino = (Return - Risk-free) / Downside Deviation
                # High Sortino with low profit suggests:
                # 1. Very low downside volatility (good)
                # 2. Small but consistent positive returns (good risk-adjusted, but low absolute)
                # 3. Or very few losing days (low downside deviation)
                print(f"  Interpretation:")
                print(f"    - High Sortino ({sortino:.2f}) indicates good risk-adjusted returns")
                print(f"    - Low absolute profit (${total_profit:,.2f}) suggests small but consistent gains")
                print(f"    - This is common when:")
                print(f"      * Win rate is high but average win size is small")
                print(f"      * Drawdowns are minimal (low downside volatility)")
                print(f"      * Strategy is conservative (few trades, small positions)")
                
                if num_trades > 0:
                    trades_per_year = result.get('avg_trades_day', 0) * 252
                    profit_per_trade = total_profit / num_trades
                    print()
                    print(f"  Trade Efficiency:")
                    print(f"    Profit per trade: ${profit_per_trade:,.2f}")
                    print(f"    Estimated trades/year: {trades_per_year:.1f}")
                    print(f"    Estimated annual profit: ${profit_per_trade * trades_per_year:,.2f}")
        
    except Exception as e:
        print(f"ERROR running backtest: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    check_actual_metrics()


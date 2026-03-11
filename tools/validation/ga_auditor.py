"""
tools/validation/ga_auditor.py
==============================
Diagnostics tool to verify that the ultra-fast, vectorized fitness evaluation
used inside the Genetic Algorithm exactly matches the results of the standard 
step-by-step or localized backtesting engine.

Usage:
  python tools/validation/ga_auditor.py --strategy bollinger --params path/to/params.csv --data path/to/data.csv
"""

import pandas as pd
import sys
import os
import argparse

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from strategies.factory import StrategyFactory
from backtest import run_backtest
from optimize import Optimizer 

def compare_ga_vs_standalone(strategy_name, params_path, data_path, nrows=100000):
    print("="*80)
    print(f"COMPARING GA BACKTEST vs STANDALONE BACKTEST ({strategy_name.upper()})")
    print("="*80)

    try:
        strategy = StrategyFactory.get_strategy(strategy_name, params_path)
    except Exception as e:
        print(f"Failed to load strategy: {e}")
        return

    print(f"\nLoading data sample (first {nrows} rows for speed)...")
    try:
        df = pd.read_csv(data_path, header=None, nrows=nrows)
        # Handle standard historical formats
        if len(df.columns) >= 6:
            df.columns = ['datetime', 'open', 'high', 'low', 'close', 'volume'] + list(df.columns[6:])
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.set_index('datetime')
        print(f"Data: {len(df)} rows, {df.index.min()} to {df.index.max()}")
    except Exception as e:
         print(f"Failed to load data: {e}")
         return

    # Extract dynamic param structure for GA
    param_dict = strategy.get_param_structure()
    ga_params = {}
    for group, group_params in param_dict.items():
        if isinstance(group_params, dict):
             for key, val in group_params.items():
                 if isinstance(val, dict) and 'value' in val:
                      ga_params[key] = val['value']
                 else:
                      ga_params[key] = val

    # Test 1: GA Engine Implementation (Vectorized/Fast Evaluation)
    print(f"\n{'='*80}")
    print("TEST 1: GA OPTIMIZER ENGINE")
    print("="*80)
    
    try:
        # Initialize an Optimizer purely for accessing its internal evaluator
        opt = Optimizer(strategy_name=strategy_name, data_path=data_path)
        # We manually process the subset DF instead of loading the full CSV normally
        opt.df = df
        opt.strategy = strategy
        
        ga_fitness, ga_result = opt.evaluate_solution(list(ga_params.values()), list(ga_params.keys()), return_full=True)
        
        ga_trades = ga_result.get('trades_df', pd.DataFrame())
        ga_num_trades = len(ga_trades)
        ga_avg_trades_day = ga_result.get('avg_trades_day', 0.0)
        
        print(f"\nGA Fast-Eval Results:")
        print(f"  Total Trades: {ga_num_trades}")
        print(f"  Avg Trades/Day: {ga_avg_trades_day:.6f}")
        print(f"  Sortino: {ga_result.get('sortino', 0):.6f}")
        print(f"  Profit Factor: {ga_result.get('profit_factor', 0):.6f}")
        
    except Exception as e:
        print(f"🔴 ERROR in GA evaluate_solution route: {e}")
        import traceback
        traceback.print_exc()
        ga_num_trades = 0
        ga_avg_trades_day = 0

    # Test 2: Standalone Backtest
    print(f"\n{'='*80}")
    print("TEST 2: STANDALONE BACKTEST PIPELINE")
    print("="*80)
    try:
        # Using the standard unified pipeline
        # Note: We save a temp CSV since run_backtest expects a file path usually, 
        # or we update run_backtest to accept a DF. For now, writing temp file.
        temp_data = "temp_audit_data.csv"
        df.to_csv(temp_data, header=False) # Or match your standard CSV format
        
        standalone_result = run_backtest(temp_data, strategy_name, params_path, suppress_log=True)
        standalone_trades = standalone_result.get('trades_df', pd.DataFrame())
        standalone_num_trades = len(standalone_trades)
        
        if not standalone_trades.empty:
            unique_dates = set(standalone_trades['exit_time'].dt.date)
            trading_days = len(unique_dates) or 1
            standalone_avg_trades_day = standalone_num_trades / trading_days
        else:
            standalone_avg_trades_day = 0.0
        
        print(f"\nStandalone Backtest Results:")
        print(f"  Total Trades: {standalone_num_trades}")
        print(f"  Avg Trades/Day: {standalone_avg_trades_day:.6f}")
        print(f"  Sortino: {standalone_result.get('metrics', {}).get('Sortino Ratio', 0):.6f}")
        print(f"  Profit Factor: {standalone_result.get('metrics', {}).get('Profit Factor', 0):.6f}")
        
        if os.path.exists(temp_data):
            os.remove(temp_data)
            
    except Exception as e:
        print(f"🔴 ERROR in standalone backtest: {e}")
        import traceback
        traceback.print_exc()
        standalone_num_trades = 0
        standalone_avg_trades_day = 0

    # Comparison
    print(f"\n{'='*80}")
    print("COMPARISON")
    print("="*80)

    print(f"\nTrade Count Comparison:")
    print(f"  GA Backtest: {ga_num_trades} trades")
    print(f"  Standalone: {standalone_num_trades} trades")
    print(f"  Difference: {standalone_num_trades - ga_num_trades} trades")
    
    if abs(standalone_num_trades - ga_num_trades) > 5:
        print(f"\n🔴 CRITICAL: Significant difference in trade counts!")
        print(f"   This suggests the GA vectorization logic does not perfectly align with the step-by-step logic!")
    
    if abs(standalone_avg_trades_day - ga_avg_trades_day) > 0.1:
        print(f"\n🔴 CRITICAL: Significant difference in avg trades/day!")

    print(f"\n{'='*80}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare GA evaluation against standard backtesting.")
    parser.add_argument('--strategy', type=str, required=True, help="Strategy to audit (e.g., bollinger, trend)")
    parser.add_argument('--params', type=str, required=True, help="Path to param config CSV")
    parser.add_argument('--data', type=str, required=True, help="Path to historical data CSV")
    parser.add_argument('--nrows', type=int, default=100000, help="Number of rows to test")
    args = parser.parse_args()
    
    compare_ga_vs_standalone(args.strategy, args.params, args.data, args.nrows)

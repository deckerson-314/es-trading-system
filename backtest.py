#!/usr/bin/env python3
"""
backtest.py - Unified Backtesting Entry Point
=============================================
Uses StrategyFactory to load strategy logic.
Supports single-run and multi-solution comparison modes.
"""

import sys
import os
import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import warnings
import glob

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from strategies.factory import StrategyFactory
from strategies.bollinger.parameters import load_params 
# Eventually we want a generic reporting module in core/ or tools/
# For now, we still rely on the bollinger_strategy package for reporting helpers if needed,
# or we move generate_dashboard to tools/dashboard/reporting.py (Planned in Phase 5)
try:
    from strategies.bollinger.reporting import generate_dashboard
except ImportError:
    print("Warning: Could not import generate_dashboard from strategies.bollinger.reporting")
    generate_dashboard = None

warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, 'logs')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

def log(msg, file=None):
    print(msg)
    if file:
        file.write(msg + "\n")

def find_latest_ga_file(search_dir='strategies/bollinger/parameters'): 
    # Update default search path to new structure if possible, but old files are likely in Bollinger/parameters
    # We will check both.
    candidates = []
    candidates.extend(glob.glob(os.path.join(search_dir, 'genetic_results_*-*.csv')))
    if not candidates:
        # Fallback to legacy path
        candidates.extend(glob.glob(os.path.join('Bollinger/parameters', 'genetic_results_*-*.csv')))
    
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)

def load_ga_params(ga_file, solution_idx):
    """Load CA params from CSV (Legacy format support)"""
    try:
        df = pd.read_csv(ga_file)
        col_name = f"Solution_{solution_idx}"
        if col_name + "_SELECTED" in df.columns:
            col_name += "_SELECTED"
            
        if col_name not in df.columns:
             raise ValueError(f"Solution column '{col_name}' not found.")
             
        params = {}
        for _, row in df.iterrows():
            name = row['Name']
            if pd.isna(name) or str(name).startswith('==='): continue
            row_type = row.get('Type', '')
            if row_type == 'statistic': continue
            val = row[col_name]
            if pd.isna(val) or val == '': continue
            
            if row_type == 'int':
                try: val = int(float(val))
                except: pass
            elif row_type == 'float':
                try: val = float(val)
                except: pass
            elif row_type == 'bool':
                if str(val).lower() == 'true': val = True
                elif str(val).lower() == 'false': val = False
            
            params[name] = {'value': val, 'type': row_type}
            
        return params, col_name
    except Exception as e:
        print(f"Error parsing GA params: {e}")
        raise

def run_backtest(strategy_name, data_path, params_dict, suppress_log=False, start_date=None, end_date=None):
    """
    Run backtest using StrategyFactory.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_name = f'backtest_{strategy_name}_{timestamp}.txt' if not suppress_log else 'backtest_debug.txt'
    log_file_path = os.path.join(LOG_DIR, log_name)
    
    result_package = {
        'total_pnl': 0.0, 'win_rate': 0.0, 'pf': 0.0, 'max_dd': 0.0, 'sortino': 0.0,
        'trades_df': pd.DataFrame(), 'equity_curve': pd.Series(), 'df': None
    }
    
    with open(log_file_path, 'w') as log_file:
        if not suppress_log:
            log(f"Starting Backtest ({strategy_name}) at {timestamp}", log_file)
        
        # 1. Load Data
        if not os.path.exists(data_path):
            log(f"ERROR: Data file not found: {data_path}", log_file)
            return result_package
        
        try:
            df = pd.read_csv(data_path, parse_dates=True, index_col=0)
            df.columns = [str(c).lower().strip() for c in df.columns]
            
            # Headerless fallback logic
            if len(df.columns) == 5 and not all(c in df.columns for c in ['open','high','low','close','volume']):
                 df = pd.read_csv(data_path, header=None, parse_dates=True, index_col=0)
                 df.columns = ['open', 'high', 'low', 'close', 'volume']
            
            if start_date: df = df.loc[start_date:]
            if end_date: df = df.loc[:end_date]
            
            if not suppress_log:
                log(f"Loaded {len(df)} bars from {data_path}", log_file)
        except Exception as e:
            log(f"ERROR loading data: {e}", log_file)
            return result_package

        # 2. Init Strategy
        try:
            strategy = StrategyFactory.get_strategy(strategy_name, params_dict)
        except Exception as e:
            log(f"ERROR initializing strategy: {e}", log_file)
            return result_package

        # 3. Calculate Indicators & Filters
        if not suppress_log: log("Calculating indicators...", log_file)
        df = strategy.calculate_indicators(df)
        
        # Note: Strategy Base doesn't enforce apply_filters, but Bollinger has it.
        # We can check if method exists or if it's integrated into entry_signals.
        if hasattr(strategy, 'apply_filters'):
             df = strategy.apply_filters(df)

        # 4. Signals
        if not suppress_log: log("Generating signals...", log_file)
        long_sigs, short_sigs = strategy.calculate_entry_signals(df)
        df['entry_long_signal'] = long_sigs
        df['entry_short_signal'] = short_sigs
        
        # 5. Simulation Loop
        if not suppress_log: log("Simulating trades...", log_file)
        
        positions = []
        open_positions = []
        rows = df.itertuples()
        
        transaction_cost = params_dict.get('Transaction Cost (Per Trade)', {'value': 0.0})['value'] if isinstance(params_dict.get('Transaction Cost (Per Trade)'), dict) else 0.0
        
        # Optimized loop (similar to v5)
        # Note: Ideally this simulation logic should be in core/engine.py or strategy.backtest()
        # But keeping it here for continuity.
        
        pending_entry = None
        
        for row in rows:
            # A. Execute Pending Entry
            if pending_entry:
                 pos = strategy.setup_position(row.open, pending_entry['direction'], row, df)
                 open_positions.append(pos)
                 pending_entry = None
            
            # B. Check Exits
            for i, pos in enumerate(open_positions[:]):
                strategy.update_trailing_stop(pos, row, df)
                should_exit, reason, price = strategy.check_exit(pos, row, df)
                
                if should_exit:
                    exit_time = row.Index + pd.Timedelta(minutes=5) # Approx timeframe
                    pnl_points = (price - pos['entry_price']) * pos['direction']
                    pnl_currency = pnl_points * 50 - transaction_cost # Hardcoded ES multiplier
                    
                    positions.append({
                        'entry_time': pos['entry_time'],
                        'exit_time': exit_time,
                        'pnl_currency': pnl_currency,
                        'pnl_points': pnl_points,
                        'direction': pos['direction'],
                        'entry_price': pos['entry_price'],
                        'exit_price': price,
                        'reason': reason
                    })
                    open_positions.pop(i)
            
            # C. Check Entries
            if not open_positions:
                 if row.entry_long_signal:
                     pending_entry = {'direction': 1}
                 elif row.entry_short_signal:
                     pending_entry = {'direction': -1}
                     
        # 6. Results
        if positions:
            trades_df = pd.DataFrame(positions)
            total_pnl = trades_df['pnl_currency'].sum()
            win_rate = (trades_df['pnl_currency'] > 0).mean() * 100
            
            trades_df['cum_pnl'] = trades_df['pnl_currency'].cumsum()
            trades_df['drawdown'] = trades_df['cum_pnl'].cummax() - trades_df['cum_pnl']
            max_dd = trades_df['drawdown'].max()
            
            gross_win = trades_df[trades_df['pnl_currency'] > 0]['pnl_currency'].sum()
            gross_loss = abs(trades_df[trades_df['pnl_currency'] < 0]['pnl_currency'].sum())
            pf = gross_win / gross_loss if gross_loss > 0 else float('inf')
            
            equity_curve = trades_df.set_index('exit_time')['cum_pnl']
            
            result_package.update({
                'total_pnl': total_pnl, 'win_rate': win_rate, 'pf': pf,
                'max_dd': max_dd, 'trades_df': trades_df, 'equity_curve': equity_curve,
                'df': df
            })
            
            if not suppress_log:
                log(f"Total PnL: ${total_pnl:,.2f} | WR: {win_rate:.1f}% | PF: {pf:.2f}", log_file)
        
        # Generate Dashboard if single run
        if not suppress_log and generate_dashboard:
             try:
                 generate_dashboard([{'name': 'Backtest', 'params': params_dict, 
                                     'trades_df': result_package['trades_df'], 
                                     'equity_curve': result_package['equity_curve'],
                                     'df': df}])
             except: pass
             
    return result_package

def main():
    parser = argparse.ArgumentParser(description='Unified Backtester')
    parser.add_argument('--strategy', type=str, default='bollinger')
    parser.add_argument('--data', type=str, required=True, help='Path to market data CSV')
    parser.add_argument('--params', type=str, help='Path to parameters CSV')
    parser.add_argument('--ga-file', type=str, help='Path to GA results')
    parser.add_argument('--solutions', type=str, help='Comparison mode: Solution IDs (e.g. 0,1,2)')
    parser.add_argument('--start', type=str)
    parser.add_argument('--end', type=str)
    
    args = parser.parse_args()
    
    # 1. Parameter Loading Logic
    params_dict = {}
    
    # 1. Parameter Loading Logic
    params_dict = {}
    
    # 1a. Handle GA File (Explicit or implicit via --params + --solutions)
    # If --solutions is present, we assume --params points to a GA file if --ga-file is not set
    ga_file = args.ga_file
    if not ga_file and args.solutions and args.params:
        ga_file = args.params
        print(f"Note: Using {ga_file} as GA results file.")
        
    if ga_file:
        if ga_file.lower() == 'latest':
            ga_file = find_latest_ga_file()
            if not ga_file:
                print("Error: Could not find latest GA file.")
                sys.exit(1)
        
        if args.solutions:
            # Comparison Mode
            try:
                sol_list = [int(x) for x in args.solutions.split(',')]
            except ValueError:
                print("Error: --solutions must be a comma-separated list of integers (e.g. 0,1,2)")
                sys.exit(1)
                
            solutions_data = []
            
            print(f"Comparing solutions {sol_list} from {ga_file}...")
            
            for idx in sol_list:
                try:
                    p, name = load_ga_params(ga_file, idx)
                    # DEBUG: Print a few key params to verify loading
                    print(f"Running Sol {idx} with {len(p)} params. BB Len: {p.get('Bollinger Band Length', {}).get('value','N/A')}")
                    
                    res = run_backtest(args.strategy, args.data, p, suppress_log=True, start_date=args.start, end_date=args.end)
                    solutions_data.append({
                        'name': f"Sol {idx}",
                        'params': p,
                        'trades_df': res['trades_df'],
                        'equity_curve': res['equity_curve'],
                        'df': res['df']
                    })
                    print(f"Sol {idx}: ${res['total_pnl']:,.0f} ({len(res['trades_df'])} trades)")
                except Exception as e:
                    print(f"Error running solution {idx}: {e}")
                
            if generate_dashboard:
                try:
                    generate_dashboard(solutions_data)
                    print("Dashboard generated.")
                except Exception as e:
                    print(f"Error generating dashboard: {e}")
            return

        else:
            # Single Solution from GA
            print(f"Loading Solution 0 from {ga_file}...")
            params_dict, _ = load_ga_params(ga_file, 0) # Default to 0
            
    elif args.params:
        print(f"Loading parameters from {args.params}...")
        params_dict = load_params(args.params)
        # Check if loaded anything
        if not params_dict:
             print("Warning: Loaded empty parameters. Is the CSV format correct? (Name, Value, Type)")
        else:
             print(f"Loaded {len(params_dict)} parameters.")
             
    else:
        # Default fallback: strategies/<strategy_name>/parameters/backtest_params.csv
        # This makes the default dynamic based on the strategy argument
        default_params = os.path.join('strategies', args.strategy, 'parameters', 'backtest_params.csv')
        if os.path.exists(default_params):
             print(f"Using default parameters: {default_params}")
             params_dict = load_params(default_params)
        else:
             print(f"Warning: No parameters provided and default not found at {default_params}. Using internal strategy defaults.")
    
    # 2. Run Single Backtest
    run_backtest(args.strategy, args.data, params_dict, start_date=args.start, end_date=args.end)

if __name__ == '__main__':
    main()

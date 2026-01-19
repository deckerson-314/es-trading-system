#!/usr/bin/env python3
"""
Bollinger Band Trading Strategy Backtester - Version 4.0
========================================================
Uses shared bollinger_strategy module (V4) with vectorized signal generation.
Provides detailed trade logging and analysis.
"""

import sys
import os
import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import warnings

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from bollinger_strategy import BollingerBandStrategyV4, load_params
from bollinger_strategy.reporting import generate_dashboard

# Suppress warnings
warnings.filterwarnings("ignore")

# === Configuration ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def find_default_data_file():
    """Find a valid data file in common locations."""
    candidates = [
        os.path.join(BASE_DIR, 'market_data.csv'),
        os.path.join(BASE_DIR, 'Backtrader', 'data', 'ES_full_1min_continuous_ratio_adjusted.csv'),
        os.path.join(BASE_DIR, 'Backtrader', 'data', 'ES_full_1min_cleaned.csv'),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return os.path.join(BASE_DIR, 'market_data.csv') # Fallback

DATA_FILE = find_default_data_file()
PARAMS_CSV = os.path.join(BASE_DIR, 'best_parameters.csv') # Default params
LOG_DIR = os.path.join(BASE_DIR, 'logs')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

def log(msg, file=None):
    """Log message to console and optional file."""
    print(msg)
    if file:
        file.write(msg + "\n")

import glob

def find_latest_ga_file(search_dir='Bollinger/parameters'):
    """Find the latest genetic_results csv file."""
    files = glob.glob(os.path.join(search_dir, 'genetic_results_*-*.csv'))
    if not files:
        return None
    return max(files, key=os.path.getmtime)

def load_ga_params(ga_file, solution_idx):
    """Load parameters for a specific solution from GA results CSV."""
    try:
        df = pd.read_csv(ga_file)
        col_name = f"Solution_{solution_idx}"
        if col_name + "_SELECTED" in df.columns:
            col_name += "_SELECTED"
            
        if col_name not in df.columns:
            # Fallback for simple numbering if exists
            pass
            
        if col_name not in df.columns:
            raise ValueError(f"Solution column '{col_name}' not found in {ga_file}")
            
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
            
            # WRAP VALUE to match structure expected by get_param_value: params[name]['value']
            params[name] = {'value': val, 'type': row_type}
                
        return params, col_name
    except Exception as e:
        print(f"Error parse GA params: {e}")
        raise

def run_backtest_v4(data_path, params_source, suppress_log=False, start_date=None, end_date=None):
    """
    Run detailed backtest using V4 strategy.
    
    Args:
        data_path (str): Path to market data
        params_source (str or dict): Path to params CSV OR dict of parameters
        suppress_log (bool): If True, minimizes console output
        start_date (str, optional): Start date YYYY-MM-DD
        end_date (str, optional): End date YYYY-MM-DD
        
    Returns:
        dict: Results including 'pnl', 'sortino', 'trades_df', etc.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_name = f'backtest_log_v4_{timestamp}.txt' if not suppress_log else 'backtest_debug.txt'
    log_file_path = os.path.join(LOG_DIR, log_name)
    
    result_package = {
        'total_pnl': 0.0,
        'win_rate': 0.0,
        'pf': 0.0,
        'max_dd': 0.0,
        'sortino': 0.0,
        'trades_df': pd.DataFrame(),
        'equity_curve': pd.Series()
    }
    
    with open(log_file_path, 'w') as log_file:
        if not suppress_log:
            log(f"Starting V4 Backtest at {timestamp}", log_file)
        
        # 1. Load Data
        if not os.path.exists(data_path):
            log(f"ERROR: Data file not found: {data_path}", log_file)
            return result_package
        
        try:
            # First attempt: assume standard header
            df = pd.read_csv(data_path, parse_dates=True, index_col=0)
            df.columns = [str(c).lower().strip() for c in df.columns]
            
            
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            
            # Check if columns are missing
            if not all(c in df.columns for c in required_cols):
                # Fallback: Assume headerless OHLCV if we have 5 columns left
                if len(df.columns) == 5:
                    if not suppress_log:
                        log("Warning: Columns missing. Retrying as headerless OHLCV...", log_file)
                    df = pd.read_csv(data_path, header=None, parse_dates=True, index_col=0)
                    df.columns = ['open', 'high', 'low', 'close', 'volume']
                else:
                    log(f"ERROR: Data must contain columns: {required_cols}. Found: {list(df.columns)}", log_file)
                    return result_package
            
            if not suppress_log:
                log(f"Loaded {len(df)} bars from {data_path}", log_file)

            # --- DATE FILTERING (Moved after load) ---
            if start_date or end_date:
                original_len = len(df)
                if start_date:
                    df = df.loc[start_date:]
                if end_date:
                    df = df.loc[:end_date]
                
                if not suppress_log:
                    log(f"Date Filter Applied: {start_date} to {end_date}", log_file)
                    log(f"Bars Reduced: {original_len} -> {len(df)}", log_file)
            # ----------------------

        except Exception as e:
            log(f"ERROR loading data: {e}", log_file)
            return result_package

        # 2. Load Parameters
        params_dict = {}
        if isinstance(params_source, dict):
            params_dict = params_source
            if not suppress_log:
                log(f"Loaded parameters from Dictionary ({len(params_dict)} items)", log_file)
        elif os.path.exists(params_source):
            try:
                params_dict = load_params(params_source)
                if not suppress_log:
                    log(f"Loaded parameters from {params_source}", log_file)
            except Exception as e:
                log(f"ERROR loading parameters: {e}", log_file)
                return result_package
        else:
            log(f"ERROR: Parameters source invalid: {params_source}", log_file)
            return result_package

        # 3. Initialize Strategy
        strategy = BollingerBandStrategyV4(params_dict)

        # 4. Calculation Pipeline
        if not suppress_log:
            log("Calculating indicators...", log_file)
        df = strategy.calculate_indicators(df)
        df = strategy.apply_filters(df)
        
        if not suppress_log:
            log("Generating signals (Vectorized)...", log_file)
            
        # DEBUG DUMP
        try:
             df.to_csv('c:\\Trading\\debug_processed_df.csv')
        except: pass
        
        entry_long_signals, entry_short_signals = strategy.calculate_entry_signals(df)
        df['entry_long_signal'] = entry_long_signals
        df['entry_short_signal'] = entry_short_signals

        # 5. Simulation Loop
        if not suppress_log:
            log("Simulating trades...", log_file)
        
        positions = [] 
        open_positions = [] 
        pending_entry = None # Track pending entry for Next Bar Open execution
        
        rows = df.itertuples()
        
        # Get Transaction Cost
        transaction_cost = params_dict.get('Transaction Cost (Per Trade)', {'value': 20.0})['value']
        
        # DEBUG PRE-LOOP
        log(f"DEBUG: df length before loop: {len(df)}", log_file)
        check_ts = pd.Timestamp("2026-01-15 09:12:00")
        if check_ts in df.index:
             log(f"DEBUG: 09:12 IS IN INDEX! Row: {df.loc[check_ts]}", log_file)
        else:
             log(f"DEBUG: 09:12 IS NOT IN INDEX!", log_file)
        
        for row in rows:
            # DEBUG ZOMBIE / SIGNAL
            if str(row.Index).startswith('2026-01-15 09'):
                log(f"[DEBUG LOOP] {row.Index} (Type={type(row.Index)}) - OpenPos={len(open_positions)} ShortSig={getattr(row, 'entry_short_signal', 'MISSING')}", log_file)

            # 1. Process Pending Entry (Execute at Open of THIS bar)
            if pending_entry:
                if str(row.Index).startswith('2026-01-15 09:1'):
                    log(f"[DEBUG LOOP] EXECUTING PENDING at {row.Index}", log_file)
                direction = pending_entry['direction']
                # Use OPEN price of proper next bar
                # Note: setup_position logic should use row.open
                pos = strategy.setup_position(row.open, direction, row, df)
                open_positions.append(pos)
                pending_entry = None

            # 2. Check Exits (on existing positions)
            for i, pos in enumerate(open_positions[:]):
                strategy.update_trailing_stop(pos, row, df)
                should_exit, reason, price = strategy.check_exit(pos, row, df)
                
                if should_exit:
                    # Set Exit Time to END of bar to represent duration
                    # (Avoids 0-second duration for same-bar exits)
                    exit_time = row.Index + pd.Timedelta(minutes=strategy.timeframe)
                    duration = (exit_time - pos['entry_time'])
                    trade = {
                        'entry_time': pos['entry_time'],
                        'entry_price': pos['entry_price'],
                        'direction': pos['direction'],
                        'exit_time': exit_time,
                        'exit_price': price,
                        'reason': reason,
                        'pnl_points': (price - pos['entry_price']) * pos['direction'],
                        # Assuming ES multiplier 50 
                        'pnl_currency': (price - pos['entry_price']) * pos['direction'] * 50 - transaction_cost, 
                        'duration': duration,
                        'max_high': pos['max_high'],
                        'min_low': pos['min_low'],
                        'tp': pos.get('tp'),
                        'sl': pos.get('stop'),
                        'stop_history': pos.get('stop_history')
                    }
                    positions.append(trade)
                    open_positions.pop(i) 
            
            # 3. Check Entries
            if not open_positions:
                 if row.entry_long_signal:
                     pending_entry = {'direction': 1, 'signal_time': row.Index}
                     if str(row.Index).startswith('2026-01-15 09:1'):
                         log(f"[DEBUG LOOP] PENDING LONG SET at {row.Index}", log_file)
                 elif row.entry_short_signal:
                     pending_entry = {'direction': -1, 'signal_time': row.Index}
                     if str(row.Index).startswith('2026-01-15 09:1'):
                         log(f"[DEBUG LOOP] PENDING SHORT SET at {row.Index}", log_file)
            
            # 1. Process Pending Entry (Execute at Open of THIS bar)
            # (Note: This block is at START of loop, so it executes for PREVIOUS bar's signal)
            # But here in Python loop, we are at step i.
            # If pending_entry was set at step i-1, it should execute at step i.
            
            # WAIT! The Pending Entry block is at the TOP of the loop (Line 232).
            # The Check Entries block is at the BOTTOM (Line 251).
            # So:
            # Iteration 09:12 (Step i):
            #   Top: pending_entry is None.
            #   Bottom: entry_short_signal True. pending_entry set.
            # Iteration 09:14 (Step i+1):
            #   Top: pending_entry is NOT None. Execute.
            
            # Let's verify execution block print.
        
        # 6. Reporting
        if not suppress_log:
            log(f"Simulation Complete. Total Trades: {len(positions)}", log_file)
        
        if positions:
            trades_df = pd.DataFrame(positions)
            total_pnl = trades_df['pnl_currency'].sum()
            win_rate = (trades_df['pnl_points'] > 0).mean() * 100
            
            # Metrics
            trades_df['cum_pnl'] = trades_df['pnl_currency'].cumsum()
            trades_df['peak'] = trades_df['cum_pnl'].cummax()
            trades_df['drawdown'] = trades_df['peak'] - trades_df['cum_pnl']
            max_dd = trades_df['drawdown'].max()
            
            gross_win = trades_df[trades_df['pnl_currency'] > 0]['pnl_currency'].sum()
            gross_loss = abs(trades_df[trades_df['pnl_currency'] < 0]['pnl_currency'].sum())
            pf = gross_win / gross_loss if gross_loss > 0 else float('inf')
            
            daily_returns = trades_df.set_index('exit_time')['pnl_currency'].resample('D').sum().fillna(0)
            downside_std = daily_returns[daily_returns < 0].std()
            sortino = (daily_returns.mean() / downside_std * np.sqrt(252)) if downside_std > 0 else 0
            
            equity_curve = trades_df.set_index('exit_time')['cum_pnl']
            
            result_package = {
                'total_pnl': total_pnl,
                'win_rate': win_rate,
                'pf': pf,
                'max_dd': max_dd,
                'sortino': sortino,
                'trades_df': trades_df,
                'equity_curve': equity_curve,
                'df': df  # Return dataframe for plotting
            }

            if not suppress_log:
                log(f"Total PnL: ${total_pnl:,.2f}", log_file)
                log(f"Win Rate: {win_rate:.1f}%", log_file)
                log(f"PF: {pf:.2f} | DD: ${max_dd:,.2f}", log_file)
                
                trades_csv_path = os.path.join(RESULTS_DIR, f'trades_v4_{timestamp}.csv')
                trades_df.to_csv(trades_csv_path)
                log(f"Trades saved to: {trades_csv_path}", log_file)
            
        else:
            if not suppress_log:
                log("No trades generated.", log_file)
            
            trades_df = pd.DataFrame(columns=['entry_time', 'exit_time', 'pnl_currency', 'pnl_points', 'direction', 'entry_price', 'exit_price', 'duration'])
            result_package = {
                'total_pnl': 0,
                'win_rate': 0,
                'pf': 0,
                'max_dd': 0,
                'sortino': 0,
                'trades_df': trades_df,
                'equity_curve': pd.Series(dtype=float),
                'df': df # Return dataframe even if no trades
            }
    
    # Generate HTML Dashboard (if not suppressed)
    if not suppress_log:
        try:
            from bollinger_strategy.reporting import generate_dashboard
            # Ensure pnl_currency exists
            if 'pnl_currency' not in trades_df.columns and 'pnl' in trades_df.columns:
                trades_df['pnl_currency'] = trades_df['pnl']
            
            # Use trade-based equity curve if continuous one not available
            eq_curve = result_package['equity_curve'] if 'equity_curve' in result_package else pd.Series(dtype=float)
            
            # Prepare single solution package
            sol_data = [{
                'name': 'Backtest',
                'params': params_dict,
                'trades_df': trades_df,
                'equity_curve': eq_curve,
                'df': df
            }]
            
            generate_dashboard(
                solutions_data=sol_data,
                version='4.0',
            )
        except Exception as e:
            # log(f"WARNING: Could not generate HTML dashboard: {e}", log_file)
            print(f"WARNING: Could not generate HTML dashboard: {e}")
            import traceback
            traceback.print_exc()

    return result_package

def run_comparison_mode(data_path, ga_file, solutions, start_date=None, end_date=None):
    """Run backtests for multiple solutions and compare results."""
    print(f"\n=== Running Comparison Mode ===")
    print(f"Data: {data_path}")
    print(f"GA File: {ga_file}")
    print(f"Solutions: {solutions}")
    if start_date or end_date:
        print(f"Date Filter: {start_date} to {end_date}")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_results = []
    equity_curves = {}
    solutions_data = [] # New list for dashboard data
    
    for sol_idx in solutions:
        print(f"  > Processing Solution {sol_idx}...", end='', flush=True)
        # try:
        params, name = load_ga_params(ga_file, sol_idx)
        # FIX: Pass date filters to backtester
        res = run_backtest_v4(data_path, params, suppress_log=True, start_date=start_date, end_date=end_date)

        # Add to dashboard data
        solutions_data.append({
            'name': f"Sol {sol_idx}",
            'params': params,
            'trades_df': res['trades_df'],
            'equity_curve': res['equity_curve'],
            'df': res['df'] # FIX: Pass dataframe for plotting individual trade charts
        })
        
        summary_results.append({
            'Solution': sol_idx,
            'Name': name,
            'PnL': res['total_pnl'],
            'Trades': len(res['trades_df']),
            'WinRate%': res['win_rate'],
            'PF': res['pf'],
            'MaxDD': res['max_dd'],
            'Sortino': res['sortino']
        })
        
        if not res['equity_curve'].empty:
            equity_curves[f"Sol {sol_idx}"] = res['equity_curve']
        
        print(f" Done. PnL: ${res['total_pnl']:,.0f}")
        # except Exception as e:
        #     print(f" Failed! Error: {e}")
            
    if summary_results:
        summary_df = pd.DataFrame(summary_results)
        summary_path = os.path.join(RESULTS_DIR, f'comparison_summary_{timestamp}.csv')
        summary_df.to_csv(summary_path, index=False)
        print(f"\nSummary Report: {summary_path}")
        print(summary_df.to_string())
        
        # Call Unified Dashboard Generator
        try:
            generate_dashboard(solutions_data)
        except Exception as e:
            print(f"Error generating comparison dashboard: {e}")
            import traceback
            traceback.print_exc()
        
    if equity_curves:
        plt.figure(figsize=(12, 6))
        for label, curve in equity_curves.items():
            plt.plot(curve.index, curve.values, label=f"{label} (${curve.values[-1]:,.0f})", linewidth=2)
            
        plt.title(f"Equity Curve Comparison - {os.path.basename(ga_file)}")
        plt.xlabel("Date")
        plt.ylabel("Cumulative PnL ($)")
        plt.legend()
        plt.grid(True, alpha=0.3)
        
        plot_path = os.path.join(RESULTS_DIR, f'comparison_equity_{timestamp}.png')
        plt.savefig(plot_path)
        print(f"Comparison Plot: {plot_path}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ['?', '-?', '/?', '--help', '-h']:
        print(f"""
================================================================================
             BOLLINGER BAND STRATEGY BACKTESTER (V4)
================================================================================

DESCRIPTION:
  Runs a detailed backtest of the Bollinger Band Strategy (V4) using vectorization.
  Can run in two modes:
  1. Single Solution: Test one specific parameter set.
  2. Comparison Mode: Test multiple solutions and compare them side-by-side.

USAGE:
  python BB_Strategy_v4.py [ARGUMENTS]

CRITICAL ARGUMENTS:
  --data FILE             Path to market data CSV (OHLCV).
                          (Default: tries to find 'market_data.csv' or 'ES_full_1min_clean.csv').

  --ga-file FILE          Path to Genetic Algorithm Results CSV (e.g. 'Bollinger/parameters/genetic_results_X.csv').
                          * TIP: Use 'latest' to automatically find the newest results file.

  --solutions LIST        Comma-separated list of Solution IDs to test.
                          * Example: "0" (Best), "0,1,2" (Top 3), "5,10" (Specific).
                          * REQUIRES --ga-file.

  --params FILE           (Legacy) Path to a single parameter file (e.g. 'backtest_params.csv').
                          Used if --ga-file is not provided.

EXAMPLES:
  Test Best Solution:     python BB_Strategy_v4.py --ga-file latest --solutions 0
  Compare Top 3:          python BB_Strategy_v4.py --ga-file latest --solutions 0,1,2
  Legacy Backtest:        python BB_Strategy_v4.py --params Bollinger/parameters/backtest_params.csv

================================================================================
""")
        sys.exit(0)

print_help_end = True # Marker

if __name__ == "__main__":
    # Remove the duplicate check if needed, but structure above is cleaner if we merge.
    # Actually, I will replace the original main block header with this logic.
    pass

    parser = argparse.ArgumentParser(description='Bollinger Band Strategy V4 Backtester')
    parser.add_argument('--data', type=str, default=DATA_FILE, help='Path to market data CSV')
    parser.add_argument('--params', type=str, default='Bollinger/parameters/backtest_params.csv', help='Path to parameters CSV (Legacy)')
    parser.add_argument('--ga-file', type=str, help='Path to GA results CSV (or "latest")')
    parser.add_argument('--solutions', type=str, help='Comma-separated list of solution IDs to test (e.g. "0,1,5")')
    parser.add_argument('--start', type=str, help='Start Date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='End Date (YYYY-MM-DD)')
    
    args = parser.parse_args()
    
    # Check Data
    if not os.path.exists(args.data):
        print(f"Error: Market data not found at {args.data}")
        sys.exit(1)
        
    # Logic Branching
    if args.ga_file:
        # Resolve GA File
        ga_file = args.ga_file
        if ga_file.lower() == 'latest':
            ga_file = find_latest_ga_file()
            if not ga_file:
                print("Error: No 'genetic_results' file found in Bollinger/parameters/")
                sys.exit(1)
            print(f"Resolved 'latest' to: {ga_file}")
            
        if not os.path.exists(ga_file):
            print(f"Error: GA file not found: {ga_file}")
            sys.exit(1)
            
        # Parse Solutions
        if args.solutions:
            try:
                # Handle "0,1,2" -> [0, 1, 2]
                sol_list = [int(x.strip()) for x in args.solutions.split(',')]
            except ValueError:
                print("Error: --solutions must be integer list (e.g. 0,1,2)")
                sys.exit(1)
        else:
            # Default to Solution 0 if not specified
            sol_list = [0]
            
        if len(sol_list) > 1:
            # Comparison Mode
            run_comparison_mode(args.data, ga_file, sol_list, start_date=args.start, end_date=args.end)
        else:
            # Single Solution Mode
            sol_idx = sol_list[0]
            print(f"Running Single Backtest for Solution {sol_idx} from {ga_file}")
            if args.start or args.end:
                 print(f"Date Filter: {args.start} to {args.end}")
            try:
                params, name = load_ga_params(ga_file, sol_idx)
                run_backtest_v4(args.data, params, start_date=args.start, end_date=args.end)
            except Exception as e:
                print(f"Error loading params: {e}")
                
    else:
        # Legacy Mode (using --params file)
        if os.path.exists(args.params):
            print(f"Running Legacy Backtest with params: {args.params}")
            if args.start or args.end:
                 print(f"Date Filter: {args.start} to {args.end}")
            run_backtest_v4(args.data, args.params, start_date=args.start, end_date=args.end)
        else:
            print(f"Error: Could not find params file '{args.params}'")
            print("Usage: python BB_Strategy_v4.py --data ... [--params ... OR --ga-file ...]")


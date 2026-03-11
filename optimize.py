#!/usr/bin/env python3

import os
import sys
import argparse
import warnings
import random
import pickle
import multiprocessing
import signal
import time
import glob
import array
from datetime import datetime, timedelta
import traceback


# Import Restoration Script for Interactive Dashboard
from restore_param_analysis import generate_interactive_analysis, extract_chart_html

import hashlib

# HELP SUPPORT: Detailed Manual
def print_help():
    print(f"""
================================================================================
             BOLLINGER BAND GENETIC ALGORITHM OPTIMIZER (V4)
================================================================================

DESCRIPTION:
  Evolves trading strategies using NSGA-II to optimize for Sortino Ratio, 
  Drawdown, Profit Factor, Trade Frequency, and Profitability.

USAGE:
  python BB_Genetic_v4.py [ARGUMENTS]

CRITICAL ARGUMENTS:
  --cores N               Number of CPU cores to use (Default: All - 1).
                          Example: --cores 4

  --params FILE           Path to parameter configuration CSV (Default: 'Bollinger/parameters/backtest_params.csv').
                          Defines ranges for optimization (min, max, type).

  --dashboard-from FILE   Generate Dashboard ONLY from an existing Checkpoint (.pkl).
                          * INPUT: Must be a .pkl file (e.g., 'ga_diagnostics_v4/ga_checkpoint_v4.pkl')
                          * DOES NOT RUN OPTIMIZATION. Generates HTML and exits.

  --fresh / -f            Force a fresh start (Ignores existing checkpoints).
                          WARNING: Will overwrite previous run logs if filenames collide.

COMMON QUESTIONS:
  Q: How do I resume a run?
  A: Just run `python BB_Genetic_v4.py`. It automatically detects the latest checkpoint 
     in `ga_diagnostics_v4/` and resumes from the last saved generation.

  Q: What file does --dashboard-from take?
  A: It takes the PICKLE (.pkl) checkpoint file, NOT the CSV.
     Example: `python BB_Genetic_v4.py --dashboard-from ga_diagnostics_v4/ga_checkpoint_v4.pkl`

  Q: How many solutions?
  A: The population size is defined in 'backtest_params.csv' (POP_SIZE).
     Standard is 50-100. The Hall of Fame (HOF) keeps the best solutions found so far.

EXAMPLES:
  Standard Run:           python BB_Genetic_v4.py --cores 6
  Fresh Run:              python BB_Genetic_v4.py --fresh
  Generate Report:        python BB_Genetic_v4.py --dashboard-from ga_diagnostics_v4/ga_checkpoint_2025-12-13-1.pkl

================================================================================
""")
    sys.exit(0)

# Intercept help text
if len(sys.argv) > 1 and ('?' in sys.argv or '-?' in sys.argv or '/?' in sys.argv or '--help' in sys.argv or '-h' in sys.argv):
    print_help()
def get_file_info():
    try:
        fpath = os.path.abspath(__file__)
        mtime = datetime.fromtimestamp(os.path.getmtime(fpath)).strftime('%Y-%m-%d %H:%M:%S')
        with open(fpath, 'rb') as f:
            content = f.read()
            md5_hash = hashlib.md5(content).hexdigest()[:8]
        return mtime, md5_hash
    except:
        return "Unknown", "Unknown"

# Only print if we are the main process (prevent spam in multiprocessing)
if __name__ == "__main__":
    _mtime, _hash = get_file_info()
    print(f"\n{'='*60}")
    print(f"STARTING BB_GENETIC_V4")
    print(f"LAST MODIFIED: {_mtime}")
    print(f"FILE HASH ID : {_hash}")
    print(f"{'='*60}\n")

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.offline as pyo
import plotly.offline as pyo
import webbrowser
from deap import base, creator, tools, algorithms
from strategies.factory import StrategyFactory
# from bollinger_strategy.strategy_v5 import BollingerBandStrategyV5 as BollingerBandStrategy # REMOVED

from strategies.bollinger.parameters import load_params # Updated Import
# from bollinger_strategy import load_params # REMOVED

warnings.filterwarnings("ignore")

# Windows-specific: Set multiprocessing start method for better Ctrl+C handling
if sys.platform == 'win32':
    multiprocessing.set_start_method('spawn', force=True)

# Global flag for interrupt handling
interrupt_flag = multiprocessing.Event()

def signal_handler(signum, frame):
    print("\n\n(!)  Interrupt signal received. Will save checkpoint after current generation completes...")
    interrupt_flag.set()
    interrupt_flag.set()

# Register signal handler for Ctrl+C
signal.signal(signal.SIGINT, signal_handler)
if hasattr(signal, 'SIGTERM'):
    signal.signal(signal.SIGTERM, signal_handler)

# ----------------------------------------------------------------------
# CSV INPUT / OUTPUT
# ----------------------------------------------------------------------
# Default paths (can be overridden by CLI args)
DEFAULT_PARAM_CSV = os.path.join('strategies', 'bollinger', 'parameters', 'backtest_params.csv')

# Parse Command Line Arguments
parser = argparse.ArgumentParser(description='Genetic Optimization for Bollinger Band Strategy')
parser.add_argument('--params', type=str, default=DEFAULT_PARAM_CSV, help='Path to parameter CSV file')
parser.add_argument('--cores', type=int, default=12, help='Number of processor cores to use (default: 12)')
parser.add_argument('--strategy', type=str, default='bollinger', help='Strategy to optimize (default: bollinger)')
parser.add_argument('--dashboard-from', type=str, help='Path to an old checkpoint file to generate dashboard from (skips optimization)', default=None)
parser.add_argument('--visualize-json', type=str, help='Generate dashboard for a specific solution from a JSON parameter file', default=None)
parser.add_argument('--fresh', '-f', action='store_true', help='Force start fresh (ignore checkpoints)')
parser.add_argument('--pop', type=int, help='Override Population Size', default=None)
parser.add_argument('--gen', type=int, help='Override Number of Generations', default=None)
args = parser.parse_args()

import glob

# Defines strategy-specific defaults
strategy_name_cap = args.strategy.capitalize()

if args.params == DEFAULT_PARAM_CSV:
    if args.strategy == 'trend':
        PARAM_CSV = os.path.join('strategies', 'trend', 'parameters', 'trend_strategy_params.csv')
    else:
        PARAM_CSV = args.params
else:
    PARAM_CSV = args.params
    
print(f"Using Strategy: {args.strategy}")
print(f"Using Parameter File: {PARAM_CSV}")

# Generate Unique Output Filename (Date + Sequence Number)
today_str = datetime.now().strftime('%Y-%m-%d')
output_dir = os.path.join(strategy_name_cap, 'parameters')
os.makedirs(output_dir, exist_ok=True)

# Find next sequence number
existing_files = glob.glob(os.path.join(output_dir, f'genetic_results_{today_str}-*.csv'))
max_seq = 0
for f in existing_files:
    try:
        # Extract number from end of filename (assuming format ...-N.csv)
        base_name = os.path.basename(f)
        # remove extension
        name_no_ext = os.path.splitext(base_name)[0]
        # split by '-' and take last part
        seq_part = name_no_ext.split('-')[-1]
        seq = int(seq_part)
        max_seq = max(max_seq, seq)
    except (ValueError, IndexError):
        continue

next_seq = max_seq + 1
suffix = f"{today_str}-{next_seq}"

OUTPUT_CSV = os.path.join(output_dir, f'genetic_results_{suffix}.csv')
print(f"Generated Output Filename: {OUTPUT_CSV}")

# Also version the trade logs to keep them associated
TRADES_OOS_CSV = os.path.join(strategy_name_cap, 'output', f'genetic_trades_oos_{suffix}.csv')
TRADES_IS_CSV = os.path.join(strategy_name_cap, 'output', f'genetic_trades_is_{suffix}.csv')
DIAG_DIR = os.path.join(strategy_name_cap, 'diagnostics')
# If generating dashboard from old checkpoint, override paths
if args.dashboard_from:
    CHECKPOINT_FILE = args.dashboard_from
    print(f"!!! DASHBOARD ONLY MODE: Using checkpoint {CHECKPOINT_FILE} !!!")
    
    # Try to infer date/suffix from checkpoint filename for output files
    try:
        base_name = os.path.basename(CHECKPOINT_FILE)
        # Checkpoint name format: ga_checkpoint_YYYY-MM-DD-N.pkl
        if base_name.startswith('ga_checkpoint_') and base_name.endswith('.pkl'):
             suffix_part = base_name.replace('ga_checkpoint_', '').replace('.pkl', '')
             if suffix_part != 'v4': # Don't use v4 as suffix if possible
                 suffix = suffix_part
                 print(f"Inferred suffix from checkpoint: {suffix}")
    except:
        pass
else:
    # Dynamic Checkpoint Path based on strategy (defaulting to bollinger for now)
    # Ideally should use args.strategy but args not available here yet (defined below)
    # So we used a fixed path relative to strategies/bollinger for now
    # We will refine this in main() if needed
    # Dynamic Checkpoint Path based on strategy
    CHECKPOINT_DIR = os.path.join('strategies', strategy_name_cap.lower(), 'checkpoints')
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    CHECKPOINT_FILE = os.path.join(CHECKPOINT_DIR, 'ga_checkpoint_v4.pkl')
START_TIME_FILE = os.path.join(DIAG_DIR, 'ga_start_time.txt')
HTML_DIR = os.path.join(DIAG_DIR, 'html')
HTML_DASHBOARD = os.path.join(HTML_DIR, 'ga_dashboard_v4.html')
WEB_DIR = os.path.join(os.getcwd(), 'web')  # Common web directory
WEB_DASHBOARD = os.path.join(WEB_DIR, 'ga_dashboard_v4.html')
os.makedirs(DIAG_DIR, exist_ok=True)
os.makedirs(HTML_DIR, exist_ok=True)
os.makedirs(os.path.dirname(TRADES_IS_CSV), exist_ok=True)
os.makedirs(os.path.dirname(TRADES_OOS_CSV), exist_ok=True)

# ----------------------------------------------------------------------
# Load Parameters (will be loaded in main() to avoid worker process printing)
# ----------------------------------------------------------------------
# param_dict and param_df will be loaded in main() function

# ----------------------------------------------------------------------
# GA configuration (will be set in main() after loading params)
# ----------------------------------------------------------------------
# These will be set as global variables in main() after loading parameters
POP_SIZE = None
NUM_GEN = None
CX_PB = None
MUT_PB = None
MUT_MU = None
MUT_SIGMA = None
TARGET_TRADES_DAY = None
TRADES_PENALTY_WEIGHT = None
DD_WEIGHT = None
DATA_SPLITS = None
DATA_SIZE = None
MIN_TRADES_DAY = None
MIN_TRADES_PEN_WEIGHT = None

# Multi-core configuration
# Calculate optimal number of workers (use all cores minus 1 to leave one for system)
# This will be recalculated in main() after multiprocessing is properly initialized
NUM_WORKERS = None  # Will be set in main() based on CPU count

# Global variables that will be set in main()
param_dict = None
param_df = None
PARAM_RANGES = None
param_keys = None
param_keys = []

# ----------------------------------------------------------------------
# Back-tester using shared strategy module
# ----------------------------------------------------------------------
def run_backtest(params, df_in, param_dict_local, suppress_output=True, debug=False):
    default_result = {'sortino': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0, 'total_profit': 0,
                     'trades_df': pd.DataFrame(), 'monthly_profit_stats': {'max_monthly_profit': 0, 'min_monthly_profit': 0, 'avg_monthly_profit': 0}}
    
    if len(df_in) == 0:
        return default_result.copy()
    
    # Create strategy instance (V4) -> Logic moved to Factory
    try:
        # Use factory to get strategy. defaulting to 'bollinger' if not specified in params (or passed globally)
        # For now, we assume 'bollinger' as that's what this script was built for, 
        # but ideally we pass strategy_name to run_backtest
        strategy_name = param_dict_local.get('strategy_name', 'bollinger')
        strategy = StrategyFactory.get_strategy(strategy_name, param_dict_local)
    except Exception as e:
        if not suppress_output: print(f"Factory Error: {e}")
        return default_result.copy()
    
    # strategy = BollingerBandStrategy(param_dict_local) # REMOVED
    strategy.update_optimizable_params(params)
    
    try:
        # Calculate indicators & signals (Vectorized)
        df = strategy.calculate_indicators(df_in)
        df = strategy.apply_filters(df)
        
        # New V4 Vectorized Signal Generation
        # (Aliased class has this method)
        entry_long, entry_short = strategy.calculate_entry_signals(df)
        df['entry_long_signal'] = entry_long
        df['entry_short_signal'] = entry_short
        
    except Exception as e:
        if not suppress_output:
            print(f"ERROR in strategy calc: {e}")
        return default_result.copy()
    
    if len(df) == 0:
        return default_result.copy()
        
    # Simulation (Optimized Loop)
    positions = []
    trades = []
    pending_entry = None # Track pending entry
    
    # Pre-calculate signals (already in columns)
    # Using itertuples is efficient enough for Python loop
    
    # Get Transaction Cost
    transaction_cost = param_dict_local.get('Transaction Cost (Per Trade)', {'value': 20.0})['value']
    
    for row in df.itertuples():
        # 1. Process Pending (Execute at Next Open)
        if pending_entry:
            dir_ = pending_entry['direction']
            # Execute at OPEN
            pos = strategy.setup_position(row.open, dir_, row, df)
            if 'stop' not in pos: pos['stop'] = 0.0 # Safety init
            positions.append(pos)
            pending_entry = None

        # 2. Check exits first
        for pos in positions[:]:
            strategy.update_trailing_stop(pos, row, df)
            should_exit, reason, price = strategy.check_exit(pos, row, df)
            
            if should_exit:
                pnl = (price - pos['entry_price']) * pos['direction'] * 50 - transaction_cost
                # Use End of Bar for Exit Time to match BB_Strategy_v4.py logic
                exit_time = row.Index + pd.Timedelta(minutes=strategy.timeframe)
                trades.append(pos | {
                    'exit_time': exit_time,
                    'exit_price': price,
                    'pnl': pnl,
                    'reason': reason
                })
                positions.remove(pos)
        
        # 3. Check entries (Vectorized lookup)
        # Note: If we just executed a pending entry, we CANNOT generate another signal in the same bar (usually)
        # But even if we could, we would just set pending_entry again for the NEXT bar.
        if len(positions) < strategy.max_open_trades and pending_entry is None:
            if row.entry_long_signal:
                pending_entry = {'direction': 1, 'entry_price': row.close, 'stop': 0.0} # Init fields
            elif row.entry_short_signal:
                pending_entry = {'direction': -1, 'entry_price': row.close, 'stop': 0.0}
    
    # Final cleanup (close open positions at end)
    for pos in positions:
        exit_price = df.iloc[-1].close
        pnl = (exit_price - pos['entry_price']) * pos['direction'] * 50 - transaction_cost
        trades.append(pos | {
            'exit_time': df.index[-1],
            'exit_price': exit_price,
            'pnl': pnl,
            'reason': 'End of Data'
        })

        
    # Calculate Metrics (Same as v3)
    if not trades:
        return default_result.copy()
        
    try:
        trades_df = pd.DataFrame(trades)
    except Exception:
        return default_result.copy()
    
    total_profit = trades_df['pnl'].sum()
    
    # Drawdown
    trades_df['cum_pnl'] = trades_df['pnl'].cumsum()
    trades_df['peak'] = trades_df['cum_pnl'].cummax()
    trades_df['drawdown'] = trades_df['peak'] - trades_df['cum_pnl']
    max_drawdown = trades_df['drawdown'].max()
    if pd.isna(max_drawdown): max_drawdown = 0
    
    # Sortino
    risk_free_rate = 0
    downside_returns = trades_df[trades_df['pnl'] < 0]['pnl']
    downside_std = downside_returns.std()
    
    if downside_std == 0 or pd.isna(downside_std):
        sortino = 0
    else:
        avg_return = trades_df['pnl'].mean()
        sortino = (avg_return - risk_free_rate) / downside_std * (252**0.5) 
        
    # Profit Factor
    gross_profit = trades_df[trades_df['pnl'] > 0]['pnl'].sum()
    gross_loss = abs(trades_df[trades_df['pnl'] < 0]['pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999.0
    
    # Trade Frequency
    if not df_in.empty:
         # Approximate total days from data
         # This assumes index is datetime
         try:
             total_days = len(set(df_in.index.date)) or 1
         except:
             total_days = 1
    else:
         total_days = 1

    avg_trades_day = len(trades) / total_days
    
    # Monthly stats
    monthly_stats = {'max_monthly_profit': 0, 'min_monthly_profit': 0, 'avg_monthly_profit': 0}
    if not trades_df.empty and 'exit_time' in trades_df.columns:
        try:
            trades_df['year_month'] = pd.to_datetime(trades_df['exit_time']).dt.to_period('M')
            monthly_pnl = trades_df.groupby('year_month')['pnl'].sum()
            if len(monthly_pnl) > 0:
                monthly_stats = {
                    'max_monthly_profit': float(monthly_pnl.max()),
                    'min_monthly_profit': float(monthly_pnl.min()),
                    'avg_monthly_profit': float(monthly_pnl.mean())
                }
        except:
             pass
    
    return {
        'sortino': sortino,
        'max_drawdown': max_drawdown,
        'avg_trades_day': avg_trades_day,
        'profit_factor': profit_factor,
        'total_profit': total_profit,
        'trades_df': trades_df,
        'monthly_profit_stats': monthly_stats
    }

# ----------------------------------------------------------------------
# Multi-objective GA setup
# ----------------------------------------------------------------------
# Clear any existing creator classes to avoid conflicts
if hasattr(creator, "FitnessMulti"):
    del creator.FitnessMulti
if hasattr(creator, "Individual"):
    del creator.Individual

# Multi-objective fitness: (maximize Sortino, minimize Drawdown, maximize Profit Factor, maximize Avg Trades/Day, maximize Total Profit, maximize Avg Profit/Trade)
# Weights: (1.0, -1.0, 1.0, 1.0, 2.0, 2.0)
# - Sortino: maximize (higher is better)
# - Max Drawdown: minimize (negated, so -1.0 weight means minimize)
# - Profit Factor: maximize (higher is better)
# - Avg Trades/Day: maximize (1.0 - Reduced from 5.0 to discourage noise)
# - Total Profit: maximize (higher is better - direct optimization for profitability)
# - Avg Profit/Trade: maximize (2.0 - New objective to prioritize quality trades/expectancy)
creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 1.0, 2.0, 2.0))
creator.create("Individual", list, fitness=creator.FitnessMulti)

def create_fitness_with_correct_weights():
    # Check if FitnessMulti class has correct weights
    if hasattr(creator, 'FitnessMulti') and len(creator.FitnessMulti.weights) == 6:
        return creator.FitnessMulti()
    else:
        # Recreate the class if it has wrong weights
        if hasattr(creator, "FitnessMulti"):
            del creator.FitnessMulti
        creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 1.0, 2.0, 2.0))
        return creator.FitnessMulti()

def clamp_individual(ind):
    global PARAM_RANGES, param_keys, param_dict
    if PARAM_RANGES is None or param_keys is None:
        return ind  # Can't clamp if not initialized
    for i, key in enumerate(param_keys):
        if i < len(ind) and key in PARAM_RANGES:
            lo, hi = PARAM_RANGES[key]
            # Clamp to range
            clamped_value = max(lo, min(ind[i], hi))
            # Round integer parameters to nearest integer
            if param_dict is not None and key in param_dict:
                param_type = param_dict[key].get('type', 'float')
                if param_type == 'int':
                    clamped_value = int(round(clamped_value))
                    # Ensure it's still within bounds after rounding (use integer bounds)
                    clamped_value = max(int(lo), min(int(hi), clamped_value))
            ind[i] = clamped_value
            
            # Additional clamping for known integer types V5
            if param_dict is not None and key in ['RSI Period', 'RSI Overbought', 'RSI Oversold']:
                 ind[i] = int(round(ind[i]))
    return ind

def create_individual():
    global PARAM_RANGES, param_keys
    if PARAM_RANGES is None:
        raise RuntimeError("PARAM_RANGES not initialized. Call main() first.")
    if param_keys is None:
        raise RuntimeError("param_keys not initialized. Call main() first.")
    # CRITICAL: Use param_keys to ensure correct order
    ind = creator.Individual(random.uniform(PARAM_RANGES[key][0], PARAM_RANGES[key][1]) for key in param_keys)
    # Clamp to ensure values are within range (shouldn't be needed, but safety check)
    return clamp_individual(ind)

def custom_mutate(ind):
    global PARAM_RANGES, param_keys, MUT_MU, MUT_SIGMA
    if PARAM_RANGES is None:
        raise RuntimeError("PARAM_RANGES not initialized. Call main() first.")
    if param_keys is None:
        raise RuntimeError("param_keys not initialized. Call main() first.")
    tools.mutGaussian(ind, mu=MUT_MU, sigma=MUT_SIGMA, indpb=0.3)  # Increased from 0.2 to 0.3 for more parameter mutations
    # Clamp after mutation to ensure values stay within valid ranges
    clamp_individual(ind)
    return ind,

def evaluate_multi_objective(ind_and_df):
    global param_keys, param_dict
    ind, df = ind_and_df
    params = dict(zip(param_keys, ind))
    
    # Clamp & cast - ensure integer parameters are properly rounded
    for n, v in params.items():
        if n not in param_dict:
            continue
        mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
        v = max(mn, min(v, mx))
        if typ == 'int':
            # Round to nearest integer for all int parameters
            params[n] = int(round(v))
        else:
            params[n] = float(v)
    
    # Convert boolean parameters (0/1 int) to actual booleans
    # Check if parameter was originally bool type but optimized as 0/1 int
    for n in list(params.keys()):
        if n in param_dict:
            original_type = param_dict[n].get('type', '')
            # If original type was bool but we have an int value (0 or 1), convert it
            if original_type == 'bool' and isinstance(params[n], (int, float)):
                params[n] = bool(int(round(params[n])))
    
    # Handle TP method selection (mutually exclusive)
    # If 'TP Method' parameter exists, convert to individual boolean flags
    if 'TP Method' in params:
        tp_method = int(round(params['TP Method']))
        # 0 = Fixed BB at Entry TP, 1 = Fixed ATR TP, 2 = Opposite Bollinger Band TP
        params['Fixed BB at Entry TP'] = (tp_method == 0)
        params['Fixed ATR TP'] = (tp_method == 1)
        params['Opposite Bollinger Band TP'] = (tp_method == 2)
        # Remove the TP Method parameter as it's not used directly by strategy
        params.pop('TP Method', None)
    
    # Ensure critical integer parameters are properly set
    # Bollinger Band Length
    if 'Bollinger Band Length' in params:
        params['Bollinger Band Length'] = max(1, int(round(params['Bollinger Band Length'])))
    # ATR Lengths
    if 'ATR Length for Trailing Stop' in params:
        params['ATR Length for Trailing Stop'] = max(1, int(round(params['ATR Length for Trailing Stop'])))
    if 'ATR Length for TP' in params:
        params['ATR Length for TP'] = max(1, int(round(params['ATR Length for TP'])))
    # Trailing Delay
    if 'Trailing Delay (bars)' in params:
        params['Trailing Delay (bars)'] = max(0, int(round(params['Trailing Delay (bars)'])))
    # Timeframe
    params['Timeframe (minutes)'] = max(1, int(round(params.get('Timeframe (minutes)',
                                                         param_dict['Timeframe (minutes)']['value']))))
    # Max Open Trades
    if 'Max Open Trades' in params:
        params['Max Open Trades'] = max(1, int(round(params['Max Open Trades'])))
        
    # [NEW] V5 Integer Parameters
    if 'RSI Period' in params:
        params['RSI Period'] = max(5, int(round(params['RSI Period'])))
    if 'RSI Overbought' in params:
        params['RSI Overbought'] = max(50, int(round(params['RSI Overbought'])))
    if 'RSI Oversold' in params:
        params['RSI Oversold'] = max(1, int(round(params['RSI Oversold'])))
    
    metrics = run_backtest(params, df, param_dict, suppress_output=True)
    
    # Get base metrics
    sortino_raw = metrics['sortino']  # Keep raw value for checks
    sortino = metrics['sortino']
    max_dd = metrics['max_drawdown']
    pf = metrics['profit_factor']
    trades_df = metrics.get('trades_df', pd.DataFrame())
    
    # Calculate total PNL and win rate for constraints
    total_pnl = trades_df['pnl'].sum() if not trades_df.empty else 0
    win_rate = (trades_df['pnl'] > 0).sum() / len(trades_df) if not trades_df.empty else 0.0
    
    # Check trade frequency constraints (use values from param_dict)
    target_trades = param_dict.get('TARGET_TRADES_DAY', {'value': 2})['value']
    min_trades = param_dict.get('MIN_TRADES_DAY', {'value': 1.0})['value']
    avg_trades_day = metrics['avg_trades_day']
    
    # ====================================================================
    # COMPLIANCE: Hard Constraints have been removed in favor of Graduated Penalties below
    # to avoid evolutionary dead-ends for the Genetic Algorithm.
    # ====================================================================
    
    # ====================================================================
    # GRADUATED PENALTIES - Allow exploration while discouraging bad solutions
    # CRITICAL FIX: Converted from hard constraints to graduated penalties
    # Hard constraints were preventing exploration - 100% of solutions were eliminated
    # Graduated penalties allow GA to explore unprofitable regions and evolve toward profitability
    # ====================================================================
    
    # Penalty factor accumulates all penalties multiplicatively
    constraint_penalty_factor = 1.0
    
    # CONSTRAINT 1: Minimum win rate (40%) - Graduated penalty
    # Small violations get small penalty, large violations get large penalty
    if not trades_df.empty and len(trades_df) >= 10:  # Need enough trades to evaluate
        min_win_rate = param_dict.get('MIN_WIN_RATE', {'value': 0.40})['value']  # Configurable from CSV
        if win_rate < min_win_rate:
            # Graduated penalty: 0% violation = no penalty, 100% violation (0% win rate) = 90% penalty
            violation_pct = (min_win_rate - win_rate) / min_win_rate  # 0 to 1 scale
            # Penalty increases quadratically: small violations penalized lightly, large violations heavily
            penalty = violation_pct ** 1.5  # Quadratic scaling
            constraint_penalty_factor *= (1.0 - penalty * 0.9)  # Up to 90% reduction for severe violations
    
    # CONSTRAINT 2: Must be profitable (positive PNL) - Graduated penalty
    # Allow exploration of unprofitable solutions but heavily penalize them
    if total_pnl < 0:
        # Graduated penalty based on loss magnitude
        loss_magnitude = abs(total_pnl)
        if loss_magnitude > 50000:  # Very large loss
            penalty = 0.95  # 95% penalty
        elif loss_magnitude > 10000:  # Large loss
            penalty = 0.80 + (loss_magnitude - 10000) / 40000 * 0.15  # 80-95% penalty
        elif loss_magnitude > 1000:  # Moderate loss
            penalty = 0.50 + (loss_magnitude - 1000) / 9000 * 0.30  # 50-80% penalty
        else:  # Small loss
            penalty = 0.20 + (loss_magnitude / 1000) * 0.30  # 20-50% penalty
        constraint_penalty_factor *= (1.0 - penalty)
    
    # CONSTRAINT 3: Negative Sortino - Graduated penalty
    # Allow exploration but heavily penalize negative Sortino
    if sortino_raw < 0:
        # Graduated penalty: more negative = larger penalty
        # Sortino of -1.0 gets 50% penalty, -5.0 gets 90% penalty
        sortino_magnitude = abs(sortino_raw)
        if sortino_magnitude > 5.0:
            penalty = 0.95  # 95% penalty for very negative Sortino
        elif sortino_magnitude > 2.0:
            penalty = 0.80 + (sortino_magnitude - 2.0) / 3.0 * 0.15  # 80-95% penalty
        elif sortino_magnitude > 1.0:
            penalty = 0.50 + (sortino_magnitude - 1.0) / 1.0 * 0.30  # 50-80% penalty
        else:
            penalty = 0.30 + (sortino_magnitude / 1.0) * 0.20  # 30-50% penalty
        constraint_penalty_factor *= (1.0 - penalty)
        # Also cap Sortino at small positive value to prevent extreme negatives from dominating
        sortino = max(0.01, sortino_raw * (1.0 - penalty * 0.5))  # Reduce but don't eliminate
    
    # Apply constraint penalties BEFORE other penalties
    sortino *= constraint_penalty_factor
    pf *= constraint_penalty_factor
    
    # ====================================================================
    # SOFT PENALTIES - Apply to non-critical violations
    # Applied BEFORE normalization and cap/floor
    # ====================================================================
    
    # Penalty factor accumulates all penalties multiplicatively
    penalty_factor = 1.0
    
    # 1. Trade frequency penalty (GRADUAL - allows exploration near threshold)
    if avg_trades_day < min_trades:
        # Penalty increases as we get further from minimum
        penalty_factor_trades = 1.0 - (avg_trades_day / min_trades)  # 0 to 1 scale
        # Aggressive penalty: reduce by up to 60% for very low trade frequency
        penalty_factor *= (1.0 - penalty_factor_trades * 0.6)
    # Additional penalty for very low trades (near zero)
    if avg_trades_day < 0.5:
        # Extra penalty for extremely low trade frequency
        extra_penalty = (0.5 - avg_trades_day) / 0.5  # 0 to 1 scale
        penalty_factor *= (1.0 - extra_penalty * 0.4)  # Additional 0-40% reduction
    
    # 1b. Penalty for EXCESS trades (above target) - discourage over-trading
    # Target range: 2-5 trades/day (ideal: 3.5 trades/day)
    if avg_trades_day > target_trades:
        # Calculate excess above target
        excess = avg_trades_day - target_trades
        # Penalty increases with excess trades
        # At 2x target (e.g., 7 trades/day when target is 3.5): 50% penalty
        # At 3x target (e.g., 10.5 trades/day): 75% penalty
        # At 4x target (e.g., 14 trades/day): 90% penalty
        excess_ratio = excess / target_trades  # How many times over target
        if excess_ratio >= 3.0:  # 4x target or more
            penalty_factor *= 0.1  # 90% penalty (very severe)
        elif excess_ratio >= 2.0:  # 3x target
            penalty_factor *= 0.25  # 75% penalty
        elif excess_ratio >= 1.0:  # 2x target
            penalty_factor *= 0.5  # 50% penalty
        else:  # Between target and 2x target
            # Gradual penalty: 0% at target, 50% at 2x target
            penalty_factor *= (1.0 - (excess_ratio - 1.0) * 0.5)
    
    # 2. Unrealistic high win rate (overfitting indicator)
    if not trades_df.empty and win_rate > 0.95:
        # Gradual penalty based on how unrealistic
        excess_wr = (win_rate - 0.95) / 0.05  # 0 to 1 scale (95% to 100%)
        penalty_factor *= (1.0 - excess_wr * 0.3)  # Reduce by up to 30%
    

    # ====================================================================
    # GRADUATED PENALTY: Minimum trades per day
    # OLD: Hard constraint (< 1.0 = -Infinity) -> CAUSED EVOLUTIONARY DEAD END
    # NEW: Graduated penalty (0.9 is better than 0.0)
    # ====================================================================
    # Ensure min_trades is defined
    min_trades = param_dict.get('MIN_TRADES_DAY', {'value': 1.0})['value']
    
    # Define penalty variable (default 0)
    low_trade_penalty = 0.0
    if avg_trades_day < min_trades:
        shortfall = min_trades - avg_trades_day
        # Penalty scaling: 100.0 per trade deficit
        # e.g. 0.99 deficit (1 trade total) -> Penalty 99.0
        # This is enough to crush Sortino (range 0-1) into negative territory
        low_trade_penalty = shortfall * 100.0
        
    # ====================================================================
    # GRADUATED PENALTIES - Allow exploration while discouraging bad solutions

    no_tp = (not params.get('Opposite Bollinger Band TP', False) and 
             not params.get('Fixed ATR TP', False) and 
             not params.get('Fixed BB at Entry TP', False))
    if no_tp:
        # Reduce fitness but don't eliminate
        penalty_factor *= 0.3  # Reduce by 70%
    
    # 5. Max ATR Filter too high (allows high volatility - bad for mean reversion)
    max_atr = params.get('Max ATR Filter (Points)', 10.0)
    # Get ATR filter range from param_dict
    atr_min = param_dict.get('Max ATR Filter (Points)', {}).get('min', 1.0)
    atr_max = param_dict.get('Max ATR Filter (Points)', {}).get('max', 6.0)
    if max_atr > atr_min + (atr_max - atr_min) * 0.7:  # Above 70% of range
        # Penalty increases as Max ATR gets higher (allows more high volatility)
        # At 70% of range: no penalty, at 100% of range: 50% penalty
        high_vol_pct = (max_atr - (atr_min + (atr_max - atr_min) * 0.7)) / ((atr_max - atr_min) * 0.3)
        high_vol_pct = min(1.0, max(0.0, high_vol_pct))  # Clamp 0-1
        penalty_factor *= (1.0 - high_vol_pct * 0.5)  # Reduce by up to 50%
    
    # 6. Max ATR Filter too low (very restrictive - may reduce trade frequency too much)
    if max_atr < atr_min + (atr_max - atr_min) * 0.2:  # Below 20% of range
        # Gradual penalty based on how low
        restrictive_pct = ((atr_min + (atr_max - atr_min) * 0.2) - max_atr) / ((atr_max - atr_min) * 0.2)
        restrictive_pct = min(1.0, max(0.0, restrictive_pct))  # Clamp 0-1
        penalty_factor *= (1.0 - restrictive_pct * 0.2)  # Reduce by up to 20% for very conservative ATR
    
    # Apply penalty factor to metrics
    sortino *= penalty_factor
    pf *= penalty_factor
    
    # ====================================================================
    # NORMALIZATION & FINAL CALCULATION
    # Normalize objectives to 0-1 range before weighting.
    # Prevents one objective from dominating.
    # ====================================================================
    
    # Normalization ranges - loaded from CSV for configurability
    SORTINO_MAX = param_dict.get('NORM_SORTINO_MAX', {'value': 10.0})['value']
    DD_MAX = param_dict.get('NORM_DD_MAX', {'value': 100000.0})['value']
    PF_MAX = param_dict.get('NORM_PF_MAX', {'value': 5.0})['value']
    TRADES_MAX = param_dict.get('NORM_TRADES_MAX', {'value': 3.0})['value']
    PNL_MAX = param_dict.get('NORM_PNL_MAX', {'value': 200000.0})['value']
    
    # Normalize (No Floors)
    normalized_sortino = sortino / SORTINO_MAX
    normalized_dd = 1.0 - (max_dd / DD_MAX)
    normalized_pf = pf / PF_MAX
    normalized_trades = avg_trades_day  # Raw
    normalized_pnl = total_pnl / PNL_MAX
    
    # Apply Penalties to ALL objectives to enforce constraints
    # This implements "Constrained Dominance" via penalty functions
    # A solution that fails constraints must be worse than any feasible solution
    
    # Apply specific Low Trade Penalty (Subtract from positive metrics, Add to negative/minimized ones)
    normalized_trades -= low_trade_penalty
    normalized_sortino -= low_trade_penalty
    normalized_pf -= low_trade_penalty
    normalized_pnl -= low_trade_penalty
    # Note: normalized_ppt penalty applied after its definition below (line ~830)
    
    # For Drawdown (Minimized, where 1.0 is Best/NoDD and 0.0 is Worst/MaxDD)
    # Wait, normalized_dd is 1.0 - (DD/Max). So 1.0 is Good.
    # So we should SUBTRACT penalty from it too?
    # Yes, make it lower (worse).
    normalized_dd -= low_trade_penalty
    
    # Apply generic penalty factor logic (multiplicative)

    normalized_pnl *= penalty_factor
    normalized_dd *= penalty_factor
    normalized_sortino *= penalty_factor
    normalized_pf *= penalty_factor
    
    # Cast
    normalized_sortino = float(normalized_sortino)
    normalized_dd = float(normalized_dd)
    normalized_pf = float(normalized_pf)
    normalized_trades = float(normalized_trades)
    normalized_pnl = float(normalized_pnl)

    
    # CRITICAL FIX: Apply penalty to Trade Score too!
    # (Applied above before normalization, or we apply here if normalization resets it?)
    # Wait, we normalized 'avg_trades_day' into 'normalized_trades' on line 665
    # Then we missed applying penalty_factor to it if lines 635-636 are BEFORE 665!
    # Let's check block structure. 635 is BEFORE 665.
    # So we must apply penalty AFTER normalization to be safe.
    # CRITICAL FIX: Apply penalty to ALL metrics (Trades, PnL, DD) to ensure bad strategies are punished
    # CRITICAL FIX: Apply penalty to ALL metrics (Trades, PnL, DD) to ensure bad strategies are punished
    # Apply the specific Low Trade Penalty
    normalized_trades = avg_trades_day - low_trade_penalty
    
    # Apply generic penalty factor
    normalized_trades *= penalty_factor
    normalized_pnl *= penalty_factor
    normalized_dd *= penalty_factor
    
    normalized_trades = float(normalized_trades)
    normalized_pnl = float(normalized_pnl)
    normalized_dd = float(normalized_dd)
    
    # Calculate Avg Profit Per Trade (new metrics)
    total_trades_count = len(metrics['trades_df']) if 'trades_df' in metrics else 0
    avg_profit_per_trade = 0.0
    if total_trades_count > 0:
        avg_profit_per_trade = total_pnl / total_trades_count
    
    # Normalize Avg Profit Per Trade
    # Range: 0 to NORM_PROFIT_TRADE_MAX (e.g. 200)
    norm_profit_trade_max = param_dict.get('NORM_PROFIT_TRADE_MAX', {'value': 250.0})['value']
    normalized_ppt = min(avg_profit_per_trade / norm_profit_trade_max, 1.0)
    
    # Apply penalty to this too (bad strategies shouldn't get credit for high ppt if they fail basic checks)
    normalized_ppt *= penalty_factor
    normalized_ppt -= low_trade_penalty  # Deferred from normalization block above
    normalized_ppt = max(0.0001, normalized_ppt)
    normalized_ppt = float(normalized_ppt)

    # Return 6-objective fitness: (Sortino, DD, PF, Trades/Day, Total Profit, Avg Profit/Trade)
    # DEAP will apply weights: (1.0, -1.0, 1.0, 1.0, 2.0, 2.0)
    return (normalized_sortino, normalized_dd, normalized_pf, normalized_trades, normalized_pnl, normalized_ppt)

# Setup toolbox
toolbox = base.Toolbox()
toolbox.register("individual", create_individual)
toolbox.register("population", tools.initRepeat, list, toolbox.individual)
toolbox.register("evaluate", evaluate_multi_objective)
toolbox.register("mate", tools.cxBlend, alpha=0.5)
toolbox.register("mutate", custom_mutate)

# NSGA-II selection
toolbox.register("select", tools.selNSGA2)

# ----------------------------------------------------------------------
# Parallel evaluation setup
# ----------------------------------------------------------------------
# Global variables for worker processes (Shared memory optimization)
_worker_df = None
_worker_param_dict = None
_worker_keys = None

def init_worker(df_shared, param_dict_shared, keys_shared):
    """
    Initialize worker process with shared data to avoid pickling overhead on every task.
    """
    global _worker_df, _worker_param_dict, _worker_keys
    _worker_df = df_shared
    _worker_param_dict = param_dict_shared
    _worker_keys = keys_shared

# Module-level function for multiprocessing (must be at module level to be picklable)
def _evaluate_worker(ind):
    # Use shared memory globals if available (Initialized via init_worker), 
    # otherwise fall back to old slow method (handling legacy logic if any, but we are rewriting caller too)
    
    # NOTE: Calling function must now pass ONLY 'ind', not a tuple of args!
    # If caller still passes tuple, we must handle it (Backwards compatibility check)
    if isinstance(ind, tuple) and len(ind) == 4 and _worker_df is None:
         # Legacy mode (Slow, causes WinError 1450 on large data)
         ind, df_local, param_dict_local, param_keys_local = ind
    else:
         # Optimized mode
         df_local = _worker_df
         param_dict_local = _worker_param_dict
         param_keys_local = _worker_keys
    
    args = (ind, df_local, param_dict_local, param_keys_local)

    
    # Use the passed parameters instead of globals
    params = dict(zip(param_keys_local, ind))
    
    # Clamp & cast - ensure integer parameters are properly rounded
    for n, v in params.items():
        if n not in param_dict_local:
            continue
        mn, mx, typ = param_dict_local[n]['min'], param_dict_local[n]['max'], param_dict_local[n]['type']
        v = max(mn, min(v, mx))
        if typ == 'int':
            # Round to nearest integer for all int parameters
            params[n] = int(round(v))
        else:
            params[n] = float(v)
    
    # Convert boolean parameters (0/1 int) to actual booleans
    # Check if parameter was originally bool type but optimized as 0/1 int
    for n in list(params.keys()):
        if n in param_dict_local:
            original_type = param_dict_local[n].get('type', '')
            # If original type was bool but we have an int value (0 or 1), convert it
            if original_type == 'bool' and isinstance(params[n], (int, float)):
                params[n] = bool(int(round(params[n])))
    
    # Handle TP method selection (mutually exclusive)
    # If 'TP Method' parameter exists, convert to individual boolean flags
    if 'TP Method' in params:
        tp_method = int(round(params['TP Method']))
        # 0 = Fixed BB at Entry TP, 1 = Fixed ATR TP, 2 = Opposite Bollinger Band TP
        params['Fixed BB at Entry TP'] = (tp_method == 0)
        params['Fixed ATR TP'] = (tp_method == 1)
        params['Opposite Bollinger Band TP'] = (tp_method == 2)
        # Remove the TP Method parameter as it's not used directly by strategy
        params.pop('TP Method', None)
    
    # Ensure critical integer parameters are properly set
    # Bollinger Band Length
    if 'Bollinger Band Length' in params:
        params['Bollinger Band Length'] = max(1, int(round(params['Bollinger Band Length'])))
    # ATR Lengths
    if 'ATR Length for Trailing Stop' in params:
        params['ATR Length for Trailing Stop'] = max(1, int(round(params['ATR Length for Trailing Stop'])))
    if 'ATR Length for TP' in params:
        params['ATR Length for TP'] = max(1, int(round(params['ATR Length for TP'])))
    # Trailing Delay
    if 'Trailing Delay (bars)' in params:
        params['Trailing Delay (bars)'] = max(0, int(round(params['Trailing Delay (bars)'])))
    # Timeframe
    params['Timeframe (minutes)'] = max(1, int(round(params.get('Timeframe (minutes)',
                                                         param_dict_local['Timeframe (minutes)']['value']))))
    # Max Open Trades
    if 'Max Open Trades' in params:
        params['Max Open Trades'] = max(1, int(round(params['Max Open Trades'])))
        
    # [NEW] V5 Integer Parameters
    if 'RSI Period' in params:
        params['RSI Period'] = max(5, int(round(params['RSI Period'])))
    if 'RSI Overbought' in params:
        params['RSI Overbought'] = max(50, int(round(params['RSI Overbought'])))
    if 'RSI Oversold' in params:
        params['RSI Oversold'] = max(1, int(round(params['RSI Oversold'])))
    
    metrics = run_backtest(params, df_local, param_dict_local, suppress_output=True)
    
    # Get base metrics
    sortino_raw = metrics['sortino']  # Keep raw value for checks
    sortino = metrics['sortino']
    max_dd = metrics['max_drawdown']
    pf = metrics['profit_factor']
    trades_df = metrics.get('trades_df', pd.DataFrame())
    
    # Calculate total PNL and win rate for constraints
    total_pnl = trades_df['pnl'].sum() if not trades_df.empty else 0
    win_rate = (trades_df['pnl'] > 0).sum() / len(trades_df) if not trades_df.empty else 0.0
    
    # Calculate avg_trades_day
    avg_trades_day = metrics.get('avg_trades_day', 0.0)
    
    # ====================================================================
    # GRADUATED PENALTY: Minimum trades per day
    # OLD: Hard constraint (< 1.0 = -Infinity) -> CAUSED EVOLUTIONARY DEAD END
    # NEW: Graduated penalty (0.9 is better than 0.0)
    # ====================================================================
    min_trades = param_dict_local.get('MIN_TRADES_DAY', {'value': 1.0})['value']
    target_trades = param_dict_local.get('TARGET_TRADES_DAY', {'value': 2})['value']
    
    # We do NOT return immediately anymore. We calculate a penalty.
    low_trade_penalty = 0.0
    if avg_trades_day < min_trades:
        # Distance from requirement (e.g. 1.0 - 0.2 = 0.8 shortfall)
        shortfall = min_trades - avg_trades_day
        # Penalty scaling: A severe penalty, but not infinite
        # e.g. 0.8 shortfall * 100 = Score -80.0
        # e.g. 0.1 shortfall * 100 = Score -10.0
        low_trade_penalty = shortfall * 100.0

    
    # ====================================================================
    # GRADUATED PENALTIES - Allow exploration while discouraging bad solutions
    # CRITICAL FIX: Converted from hard constraints to graduated penalties
    # Hard constraints were preventing exploration - 100% of solutions were eliminated
    
    constraint_penalty_factor = 1.0
    
    # CONSTRAINT 1: Minimum win rate - Graduated penalty
    if not trades_df.empty and len(trades_df) >= 10:
        min_win_rate = param_dict_local.get('MIN_WIN_RATE', {}).get('value', 0.40)  # Configurable from CSV
        if win_rate < min_win_rate:
            violation_pct = (min_win_rate - win_rate) / min_win_rate
            penalty = violation_pct ** 1.5
            constraint_penalty_factor *= (1.0 - penalty * 0.9)
    
    # CONSTRAINT 2: Must be profitable - Graduated penalty
    if total_pnl < 0:
        loss_magnitude = abs(total_pnl)
        if loss_magnitude > 50000:
            penalty = 0.95
        elif loss_magnitude > 10000:
            penalty = 0.80 + (loss_magnitude - 10000) / 40000 * 0.15
        elif loss_magnitude > 1000:
            penalty = 0.50 + (loss_magnitude - 1000) / 9000 * 0.30
        else:
            penalty = 0.20 + (loss_magnitude / 1000) * 0.30
        constraint_penalty_factor *= (1.0 - penalty)
    
    # CONSTRAINT 3: Negative Sortino - Graduated penalty
    if sortino_raw < 0:
        sortino_magnitude = abs(sortino_raw)
        if sortino_magnitude > 5.0:
            penalty = 0.95
        elif sortino_magnitude > 2.0:
            penalty = 0.80 + (sortino_magnitude - 2.0) / 3.0 * 0.15
        elif sortino_magnitude > 1.0:
            penalty = 0.50 + (sortino_magnitude - 1.0) / 1.0 * 0.30
        else:
            penalty = 0.30 + (sortino_magnitude / 1.0) * 0.20
        constraint_penalty_factor *= (1.0 - penalty)
        sortino = max(0.01, sortino_raw * (1.0 - penalty * 0.5))
    
    # Apply constraint penalties BEFORE other penalties
    sortino *= constraint_penalty_factor
    pf *= constraint_penalty_factor
    
    # ====================================================================
    # SOFT PENALTIES - Apply to non-critical violations
    # ====================================================================
    
    penalty_factor = 1.0
    
    # 1. Trade frequency penalty
    if avg_trades_day < min_trades:
        penalty_factor_trades = 1.0 - (avg_trades_day / min_trades)
        penalty_factor *= (1.0 - penalty_factor_trades * 0.6)
    if avg_trades_day < 0.5:
        extra_penalty = (0.5 - avg_trades_day) / 0.5
        penalty_factor *= (1.0 - extra_penalty * 0.4)
    
    # 1b. Penalty for EXCESS trades (above target) - discourage over-trading
    # Target range: 2-5 trades/day (ideal: 3.5 trades/day)
    if avg_trades_day > target_trades:
        # Calculate excess above target
        excess = avg_trades_day - target_trades
        # Penalty increases with excess trades
        # At 2x target (e.g., 7 trades/day when target is 3.5): 50% penalty
        # At 3x target (e.g., 10.5 trades/day): 75% penalty
        # At 4x target (e.g., 14 trades/day): 90% penalty
        excess_ratio = excess / target_trades  # How many times over target
        if excess_ratio >= 3.0:  # 4x target or more
            penalty_factor *= 0.1  # 90% penalty (very severe)
        elif excess_ratio >= 2.0:  # 3x target
            penalty_factor *= 0.25  # 75% penalty
        elif excess_ratio >= 1.0:  # 2x target
            penalty_factor *= 0.5  # 50% penalty
        else:  # Between target and 2x target
            # Gradual penalty: 0% at target, 50% at 2x target
            penalty_factor *= (1.0 - (excess_ratio - 1.0) * 0.5)
    
    # 2. Unrealistic high win rate
    if not trades_df.empty and win_rate > 0.95:
        excess_wr = (win_rate - 0.95) / 0.05
        penalty_factor *= (1.0 - excess_wr * 0.3)
    
    # 3. Very short average trade duration
    if not trades_df.empty and 'entry_time' in trades_df.columns and 'exit_time' in trades_df.columns:
        durations = (trades_df['exit_time'] - trades_df['entry_time']).dt.total_seconds() / 60
        avg_duration = durations.mean() if len(durations) > 0 else 0
        if avg_duration < 2.0:
            penalty = (2.0 - avg_duration) / 2.0
            penalty_factor *= (1.0 - penalty * 0.2)
    
    # 4. No TP enabled
    no_tp = (not params.get('Opposite Bollinger Band TP', False) and 
             not params.get('Fixed ATR TP', False) and 
             not params.get('Fixed BB at Entry TP', False))
    if no_tp:
        penalty_factor *= 0.3
    
    # 5. Max ATR Filter too high (allows high volatility - bad for mean reversion)
    max_atr = params.get('Max ATR Filter (Points)', 10.0)
    # Get ATR filter range from param_dict
    atr_min = param_dict_local.get('Max ATR Filter (Points)', {}).get('min', 1.0)
    atr_max = param_dict_local.get('Max ATR Filter (Points)', {}).get('max', 6.0)
    if max_atr > atr_min + (atr_max - atr_min) * 0.7:  # Above 70% of range
        # Penalty increases as Max ATR gets higher (allows more high volatility)
        # At 70% of range: no penalty, at 100% of range: 50% penalty
        high_vol_pct = (max_atr - (atr_min + (atr_max - atr_min) * 0.7)) / ((atr_max - atr_min) * 0.3)
        high_vol_pct = min(1.0, max(0.0, high_vol_pct))  # Clamp 0-1
        penalty_factor *= (1.0 - high_vol_pct * 0.5)  # Reduce by up to 50%
    
    # 6. Max ATR Filter too low (very restrictive - may reduce trade frequency too much)
    if max_atr < atr_min + (atr_max - atr_min) * 0.2:  # Below 20% of range
        # Gradual penalty based on how low
        restrictive_pct = ((atr_min + (atr_max - atr_min) * 0.2) - max_atr) / ((atr_max - atr_min) * 0.2)
        restrictive_pct = min(1.0, max(0.0, restrictive_pct))  # Clamp 0-1
        penalty_factor *= (1.0 - restrictive_pct * 0.2)  # Reduce by up to 20%
    
    # Apply penalty factor
    sortino *= penalty_factor
    pf *= penalty_factor
    
    # ====================================================================
    # NORMALIZATION & FINAL CALCULATION
    # ====================================================================
    
    # Load Constants
    SORTINO_MAX = param_dict_local.get('NORM_SORTINO_MAX', {}).get('value', 10.0)
    DD_MAX = param_dict_local.get('NORM_DD_MAX', {}).get('value', 100000.0)
    PF_MAX = param_dict_local.get('NORM_PF_MAX', {}).get('value', 5.0)
    TRADES_MAX = param_dict_local.get('NORM_TRADES_MAX', {}).get('value', 3.0)
    PNL_MAX = param_dict_local.get('NORM_PNL_MAX', {}).get('value', 200000.0)
    norm_profit_trade_max = param_dict_local.get('NORM_PROFIT_TRADE_MAX', {'value': 250.0})['value']
    
    # Calculate PPT
    total_trades_count = len(metrics['trades_df']) if 'trades_df' in metrics else 0
    avg_profit_per_trade = 0.0
    if total_trades_count > 0:
        avg_profit_per_trade = total_pnl / total_trades_count

    

    
    # Calculate Avg Profit Per Trade (new metrics)
    total_trades_count = len(metrics['trades_df']) if 'trades_df' in metrics else 0
    avg_profit_per_trade = 0.0
    if total_trades_count > 0:
        avg_profit_per_trade = total_pnl / total_trades_count
    
    # Normalize Avg Profit Per Trade
    # Range: 0 to NORM_PROFIT_TRADE_MAX (e.g. 200)
    norm_profit_trade_max = param_dict_local.get('NORM_PROFIT_TRADE_MAX', {'value': 250.0})['value']
    normalized_ppt = min(avg_profit_per_trade / norm_profit_trade_max, 1.0)
    
    # Apply penalty to this too (bad strategies shouldn't get credit for high ppt if they fail basic checks)
    normalized_ppt *= penalty_factor
    normalized_ppt = max(0.0001, normalized_ppt)
    normalized_ppt = float(normalized_ppt)

    # Normalize metrics (higher is better for all, except DD which is minimized by weight)
    # CRITICAL CHANGE: Removed max(0.0001) floor. Allow negative values to preserve gradient.
    
    # 1. Sortino: Range [-Inf, CAP]. 
    # If negative, it flows through directly.
    normalized_sortino = min(sortino / SORTINO_MAX, 1.0) # Assuming 1.0 is the cap
    
    # 2. Drawdown: Range [0, Inf]. Minimization objective.
    # We pass the raw normalized ratio. Weight is -1.0, so higher DD = lower fitness.
    normalized_dd = max_dd / DD_MAX
    
    # 3. Profit Factor: Range [0, CAP]. 
    normalized_pf = min(pf / PF_MAX, 1.0)
    
    # 4. Trades: Range [0, CAP]. 
    normalized_trades = min(avg_trades_day / TRADES_MAX, 1.0)
    
    # 5. Total PnL: Range [-Inf, CAP]. 
    normalized_pnl = min(total_pnl / PNL_MAX, 1.0)
    
    # 6. Avg PPT: Range [-Inf, CAP]. 
    normalized_ppt = min(avg_profit_per_trade / norm_profit_trade_max, 1.0)
    
    # Final check: Apply penalty for constraints
    # If penalty_factor < 1.0, we reduce the positive scores.
    # For negative scores, multiplying by 0.5 makes them "less bad" (closer to 0), which is WRONG.
    # We want Bad * Penalty = WORSE.
    # So if Score > 0: Score * Penalty.
    # If Score < 0: Score / Penalty (make it more negative)? Or Score - Penalty?
    # Simple approach: Apply penalty as a scalar reduction to everything.
    
    # CRITICAL FIX: Apply specific Low Trade Penalty to ALL objectives
    # This prevents "1-Trade Wonders" (High Sortino/PF, Low Trades) from surviving
    normalized_trades -= low_trade_penalty
    normalized_sortino -= low_trade_penalty
    normalized_pf -= low_trade_penalty
    normalized_pnl -= low_trade_penalty
    normalized_ppt -= low_trade_penalty
    
    # For DD (minimized, 0.0 is Best), ADD penalty (make it worse/larger)
    normalized_dd += low_trade_penalty

    if constraint_penalty_factor < 1.0:
        penalty_hit = (1.0 - constraint_penalty_factor) # e.g. 0.2
        # Apply strict reduction
        normalized_sortino -= penalty_hit
        normalized_pf -= penalty_hit
        normalized_trades -= penalty_hit
        normalized_pnl -= penalty_hit
        normalized_ppt -= penalty_hit
        # For DD (minimized), ADD penalty
        normalized_dd += penalty_hit


    # Return 6-objective fitness
    return (normalized_sortino, normalized_dd, normalized_pf, normalized_trades, normalized_pnl, normalized_ppt)

def parallel_evaluate(individuals, df, param_dict_local, param_keys_local, pool=None):
    # Check if interrupt was requested
    if interrupt_flag.is_set():
        raise KeyboardInterrupt("Interrupt requested")
    
    # Use provided pool or create a new one
    create_new_pool = (pool is None)
    if create_new_pool:
        pool = multiprocessing.Pool(processes=NUM_WORKERS)
    
    try:
        # Use map_async with timeout for better interrupt handling
        # Pass only individuals (workers use shared memory globals)
        # NOTE: This assumes pool was created with init_worker!
        async_result = pool.map_async(_evaluate_worker, individuals)
        # Wait with timeout to allow interruption - check flag periodically
        try:
            # Use shorter timeout and check interrupt flag
            timeout = 60  # Check every 60 seconds
            while not async_result.ready():
                if interrupt_flag.is_set():
                    print("\n  Interrupt received, terminating workers...")
                    if create_new_pool:
                        pool.terminate()
                        pool.join()
                    raise KeyboardInterrupt("Interrupt requested")
                async_result.wait(timeout=timeout)
            results = async_result.get(timeout=1)  # Get results immediately since ready
        except KeyboardInterrupt:
            print("\n  Interrupt received, terminating workers...")
            if create_new_pool:
                pool.terminate()
                pool.join()
            raise
        return results
    finally:
        # Only close/join if we created the pool (not if it's persistent)
        if create_new_pool:
            pool.close()
            pool.join()

# ----------------------------------------------------------------------
# HTML Dashboard Generation
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# Parameter Analysis
# ----------------------------------------------------------------------
def generate_parameter_analysis(hof, param_keys, param_dict, current_gen):
    if not hof or len(hof) < 1:
        return "<p>No solutions to analyze.</p>", ""

    # Extract data for analysis
    data = []
    for ind in hof:
        params = dict(zip(param_keys, ind))
        # Clamp params
        clamped_params = clamp_params(params, param_dict)
        
        # Get fitness values and De-Normalize
        if hasattr(ind, 'fitness') and ind.fitness.valid:
            # Fitness structure: (Sortino, MaxDD, ProfitFactor, NumTrades, TotalPnL, AvgPPT)
            # Weights: (1.0, -1.0, 1.0, 1.0, 2.0, 2.0)
            
            vals = ind.fitness.values
            
            # De-normalize (approximate) - Using defaults if NORM constants changed
            # Note: These constants match the user's current config context
            NORM_SORTINO_MAX = 10.0
            NORM_DD_MAX = 50000.0 # From fitness function
            NORM_PF_MAX = 5.0
            NORM_TRADES_MAX = 200.0
            NORM_PNL_MAX = 50000.0
            NORM_PPT_MAX = 200.0
            
            # Extract metrics
            sortino = vals[0] * NORM_SORTINO_MAX
            max_dd = vals[1] * NORM_DD_MAX # This might be negative if penalized? No, usually Abs(DD).
            pf = vals[2] * NORM_PF_MAX
            trades = vals[3] * NORM_TRADES_MAX
            pnl = vals[4] * NORM_PNL_MAX
            ppt = vals[5] * NORM_PPT_MAX
            
            row = clamped_params.copy()
            row['Sortino'] = sortino
            row['Max DD'] = max_dd
            row['Profit Factor'] = pf
            row['Trades'] = trades
            row['Total PnL'] = pnl
            row['Avg Profit/Trade'] = ppt
            
            data.append(row)
    
    if not data:
        return "<p>No valid data for analysis.</p>", ""

    df_analysis = pd.DataFrame(data)
    print(f"DEBUG: Parameter Analysis Data Size: {len(df_analysis)} rows") 
    
    if len(df_analysis) < 5:
        return f"<p class='text-danger'>Not enough data points for analysis (Found {len(df_analysis)}, need 5+). GA might be filtering too aggressively.</p>", ""
    
    # PERFORMANCE OPTIMIZATION: Downsample if too many points
    # Plotting thousands of points makes dashboard generation slow and HTML huge
    max_points = 300
    if len(df_analysis) > max_points:
        # Keep top sorted by Sortino to see the "frontier", plus some randoms?
        # Actually random sample is best to see distribution density
        df_analysis = df_analysis.sample(n=max_points, random_state=42)
    
    # Identify top important parameters (high variance in top solutions)
    # Simple heuristic: sort by variance relative to range
    importance = {}
    for col in param_keys:
        if col in df_analysis.columns and col in param_dict:
            # Check if numeric
            if pd.api.types.is_numeric_dtype(df_analysis[col]):
                p_min = param_dict[col]['min']
                p_max = param_dict[col]['max']
                p_range = p_max - p_min
                if p_range > 0:
                    std = df_analysis[col].std()
                    importance[col] = std / p_range
    
    # Get all parameters sorted by CSV order (param_keys) as requested
    # Filter to include only those present in analysis
    top_param_names = [p for p in param_keys if p in df_analysis.columns and p in param_dict]

    # Use importance only for logging or fallback
    # top_params = sorted(importance.items(), key=lambda x: x[1], reverse=True)
    # top_param_names = [p[0] for p in top_params]
    
    if not top_param_names:
        return "<p>Not enough variation to analyze parameters.</p>", ""

    # Create subplots (2x3 grid or more)
    rows = (len(top_param_names) + 2) // 3
    # Cap rows if too many? No, user requested all.
    fig = make_subplots(rows=rows, cols=3, subplot_titles=top_param_names, vertical_spacing=0.05)
    
    for i, param in enumerate(top_param_names):
        row = (i // 3) + 1
        col = (i % 3) + 1
        
        fig.add_trace(
            go.Scatter(
                x=df_analysis[param].tolist(), # Force list serialization (no binary)
                y=df_analysis['Sortino'].tolist(),
                mode='markers',
                marker=dict(
                    size=8,
                    color=df_analysis['Sortino'].tolist(),
                    colorscale='Viridis',
                    showscale=False
                ),
                name=param
            ),
            row=row, col=col
        )
        # Add simpler trendline if enough points
        if len(df_analysis) > 5:
             try:
                 x_fit = df_analysis[param]
                 y_fit = df_analysis['Sortino']
                 
                 # Drop NaNs/Infs
                 mask = np.isfinite(x_fit) & np.isfinite(y_fit)
                 x_fit = x_fit[mask]
                 y_fit = y_fit[mask]
                 
                 # Robust check: Variance > 0 and enough points
                 if len(x_fit) > 1 and x_fit.std() > 1e-9:
                     z = np.polyfit(x_fit, y_fit, 1)
                     p = np.poly1d(z)
                     x_range = np.linspace(x_fit.min(), x_fit.max(), 10)
                     fig.add_trace(
                         go.Scatter(x=x_range.tolist(), y=p(x_range).tolist(), mode='lines', line=dict(color='red', width=2, dash='dash'), showlegend=False),
                         row=row, col=col
                     )
                 else:
                     fig.add_trace(go.Scatter(x=[], y=[], mode='lines', line=dict(color='red'), showlegend=False), row=row, col=col)
             except Exception:
                # Add empty trace to maintain index sync for dropdown updates
                fig.add_trace(go.Scatter(x=[], y=[], mode='lines', line=dict(color='red'), showlegend=False), row=row, col=col)
                # Add empty trace to maintain index sync for dropdown updates
                fig.add_trace(go.Scatter(x=[], y=[], mode='lines', line=dict(color='red'), showlegend=False), row=row, col=col)
        else:
             # Add empty trace to maintain index sync
             fig.add_trace(go.Scatter(x=[], y=[], mode='lines', line=dict(color='red'), showlegend=False), row=row, col=col)

    # Create updatemenus for metric selection
    # Metrics: Sortino, Max DD, Profit Factor, Num Trades, Total PnL, Avg Profit/Trade
    metrics_info = [
        {'name': 'Sortino Ratio', 'col': 'Sortino', 'color': 'Viridis', 'is_price': False},
        {'name': 'Total PnL ($)', 'col': 'Total PnL', 'color': 'Portland', 'is_price': True},
        {'name': 'Max Drawdown ($)', 'col': 'Max DD', 'color': 'Reds', 'is_price': True},
        {'name': 'Profit Factor', 'col': 'Profit Factor', 'color': 'Greens', 'is_price': False},
        {'name': 'Num Trades', 'col': 'Trades', 'color': 'Bluered', 'is_price': False},
        {'name': 'Avg Profit/Trade ($)', 'col': 'Avg Profit/Trade', 'color': 'Tealgrn', 'is_price': True}
    ]

    updatemenus = [dict(
        buttons=[],
        direction="down",
        pad={"r": 10, "t": 10},
        showactive=True,
        x=0.1,
        xanchor="left",
        y=1.1,
        yanchor="top"
    )]

    # Calculate trendlines for ALL metrics for ALL parameters upfront
    # This is needed because 'update' method needs new data for all traces
    
    # Store data in a structured way: metric -> param_index -> {x, y, trend_x, trend_y}
    # But Plotly update args are flat lists matching trace order.
    # Trace order: Param 1 Scatter, Param 1 Trend, Param 2 Scatter, Param 2 Trend...
    
    for m_idx, metric in enumerate(metrics_info):
        m_name = metric['name']
        m_col = metric['col']
        m_colorscale = metric['color']
        
        # Build the 'y' data and 'marker.color' data for this metric
        new_y = []
        new_marker_color = []
        new_trend_y = [] # Not used in 'y' update, trendlines are separate traces
        
        # We need a flat list of updates corresponding to traces
        # Current traces loop: for i, param in enumerate(top_param_names):
        # Trace 2*i: Scatter
        # Trace 2*i+1: Trendline (if exists) -> Wait, trendline is conditional "if len > 5"
        # This makes indexing tricky. We must guarantee trendline exists or handle it.
        # FIX: Always add a trendline trace, even if empty, to keep index consistent.
        
        update_y = []
        update_color = []
        
        for p_idx, param in enumerate(top_param_names):
            # Scatter Data
            y_data = df_analysis[m_col].fillna(0).tolist()
            update_y.append(y_data) # Scatter Y
            update_color.append(y_data) # Scatter Color
            
            # Trendline Data
            if len(df_analysis) > 5:
                try:
                    # Robust polyfit
                    x_vals = df_analysis[param]
                    y_vals = df_analysis[m_col]
                    
                    # Drop NaNs
                    mask = np.isfinite(x_vals) & np.isfinite(y_vals)
                    x_vals = x_vals[mask]
                    y_vals = y_vals[mask]

                    if len(x_vals) > 1 and x_vals.std() > 1e-9:
                        z = np.polyfit(x_vals, y_vals, 1)
                        p = np.poly1d(z)
                        x_range = np.linspace(x_vals.min(), x_vals.max(), 10)
                        trend_y = p(x_range).tolist()
                        update_y.append(trend_y)
                    else:
                         update_y.append([])
                except:
                    update_y.append([]) # Empty trend
            else:
                update_y.append([]) # Empty trend

        # Create Button
        button = dict(
            args=[{
                'y': update_y,
                'marker.color': update_color # Only applies to Scatter traces, but Plotly ignores extra args for Line traces usually? 
                                             # Actually, 'marker.color' on a Line trace might be valid but ignored.
                                             # To be safe, we should construct a list of colors where trendlines get 'red' (unchanged)
            }, {
                'title': f"Top Parameters vs {m_name}" 
            }],
            label=m_name,
            method="update"
        )
        
        # Fix marker.color to only apply to scatters
        # The list must match trace count. 
        # Trace 0 (Scatter): New Color Data
        # Trace 1 (Trend): Old Color (Red) - keep existing?
        # 'update' updates attributes provided. If we provide a list of N colors, it applies to first N traces?
        # No, 'marker.color' needs to be a list of lists? OR a list of values?
        # For multiple traces, use a list of arrays.
        # But trendlines don't use 'marker.color' (they use 'line.color').
        # So we can pass 'red' or None for trendlines.
        
        final_colors = []
        for _ in top_param_names:
            final_colors.append(df_analysis[m_col].tolist()) # Scatter
            final_colors.append('red') # Trendline (ignored by marker.color? or creates error?)
            # Actually Scatter 'mode=markers' uses marker.color.
            # Scatter 'mode=lines' uses line.color.
            # If we update 'marker.color' on a line trace, it might do nothing, which is fine.
        
        button['args'][0]['marker.color'] = final_colors
        button['args'][0]['marker.colorscale'] = m_colorscale
        
        updatemenus[0]['buttons'].append(button)

    fig.update_layout(
        height=300 * rows, 
        title_text="Top Parameters vs Sortino Ratio (Default)", 
        showlegend=False,
        updatemenus=updatemenus
    )
    
    # Convert to HTML
    plot_html = fig.to_html(include_plotlyjs=False, full_html=False, div_id='param_analysis_plot')
    
    return plot_html, ""

# Helper function to clamp parameters
def clamp_params(raw_params, param_dict_local):
    clamped = {}
    for n, v in raw_params.items():
        if n not in param_dict_local:
            continue
        mn, mx, typ = param_dict_local[n]['min'], param_dict_local[n]['max'], param_dict_local[n]['type']
        v = max(mn, min(v, mx))  # Clamp to valid range
        if typ == 'int':
            clamped[n] = int(round(v))
        else:
            clamped[n] = float(v)
    
    # Ensure critical integer parameters
    if 'Bollinger Band Length' in clamped:
        clamped['Bollinger Band Length'] = max(1, int(round(clamped['Bollinger Band Length'])))
    if 'ATR Length for Trailing Stop' in clamped:
        clamped['ATR Length for Trailing Stop'] = max(1, int(round(clamped['ATR Length for Trailing Stop'])))
    if 'ATR Length for TP' in clamped:
        clamped['ATR Length for TP'] = max(1, int(round(clamped['ATR Length for TP'])))
    if 'Trailing Delay (bars)' in clamped:
        clamped['Trailing Delay (bars)'] = max(0, int(round(clamped['Trailing Delay (bars)'])))
    if 'Timeframe (minutes)' in clamped:
        clamped['Timeframe (minutes)'] = max(1, int(round(clamped['Timeframe (minutes)'])))
    if 'Max Open Trades' in clamped:
        clamped['Max Open Trades'] = max(1, int(round(clamped['Max Open Trades'])))
    return clamped

# Helper function to extract chart HTML (moved to global scope)
def extract_chart_html(html_snippet):
    if not html_snippet or len(html_snippet) == 0:
        return "", ""
    
    # Find the inner chart div with id attribute (the actual chart container)
    chart_div_start = html_snippet.find('<div id=')
    if chart_div_start == -1:
        # Fallback: find any div
        chart_div_start = html_snippet.find('<div')
    if chart_div_start == -1:
        return "", ""
    
    # Find the closing tag for the chart div
    chart_div_end = html_snippet.find('>', chart_div_start)
    if chart_div_end == -1:
        return "", ""
    
    # Check if it's self-closing
    if html_snippet[chart_div_end-1] == '/':
        # Self-closing: <div ... />
        div_part = html_snippet[chart_div_start:chart_div_end + 1]
    else:
        # Regular div: find matching closing tag
        div_end_pos = chart_div_start
        depth = 0
        i = chart_div_start
        while i < len(html_snippet):
            if html_snippet[i:i+4] == '<div':
                tag_end = html_snippet.find('>', i)
                if tag_end != -1:
                    if html_snippet[tag_end-1] != '/':
                        depth += 1
                    i = tag_end + 1
                else:
                    i += 1
            elif html_snippet[i:i+6] == '</div>':
                depth -= 1
                if depth == 0:
                    div_end_pos = i + 6
                    break
                i += 6
            else:
                i += 1
        div_part = html_snippet[chart_div_start:div_end_pos] if div_end_pos > chart_div_start else ""
    
    # Extract script separately
    script_start = html_snippet.find('<script')
    if script_start == -1:
        return div_part, ""
    
    script_end = html_snippet.find('</script>', script_start)
    if script_end == -1:
        return div_part, ""
    
    script_part = html_snippet[script_start:script_end + 9]
    return div_part, script_part

# ----------------------------------------------------------------------
# Helper: Convergence Analysis
# ----------------------------------------------------------------------
def generate_convergence_html(pop, param_keys, param_dict, chosen_params=None):
    """
    Generates an HTML section for parameter convergence analysis.
    Calculates Standard Deviation % for each parameter to show what has converged.
    """
    if not pop or len(pop) < 2 or not param_keys:
        return ""
        
    try:
        # Convert population to DataFrame
        data = []
        for ind in pop:
            # Safely zip
            if len(ind) == len(param_keys):
                p_dict = dict(zip(param_keys, ind))
                data.append(p_dict)
        
        if not data:
            return ""
            
        df = pd.DataFrame(data)
        stats = df.describe().transpose()
        
        # Calculate StdDev % (StdDev / Range) for ranking
        if 'max' in stats.columns and 'min' in stats.columns:
            stats['observed_range'] = stats['max'] - stats['min']
            stats['std_pct'] = stats['std'] / stats['observed_range'].replace(0, 1)
        
        # Define Groups (Matching CSV Structure)
        groups = {
            'Entry Criteria': [],
            'Take Profit Criteria': [],
            'Stop Loss Criteria': [],
            'GA Criteria': [],
            'Other': []
        }
        
        # Hardcoded lists to ensure correct categorization
        entry_params = ['Enable Long Trades', 'Enable Short Trades', 'Bollinger Band Length', 
                        'Bollinger Band StdDev', 'Long Entry on Wick Touch', 'Long Entry on Body in Zone',
                        'Long Trigger (% From Lower Band)', 'Short Entry on Wick Touch', 
                        'Short Entry on Body in Zone', 'Short Trigger (% From Upper Band)',
                        'ATR Length for Filter', 'Max ATR Filter (Points)', 'Min ATR Filter (Points)', 
                        'Enable Trend Filter', 'Trend EMA Length',
                        'Enable ADX Filter', 'ADX Period', 'Max ADX Threshold',
                        'RTH Start (HH:MM)', 'RTH End (HH:MM)',
                        'Enable RTH Filter', 'Volume MA Length', 'Max Volume Multiplier', 'Timeframe (minutes)',
                        'Max Open Trades', 'RTH Exit Buffer (minutes)', 'Enable Maintenance Filter',
                        'Daily Maintenance Start (HH:MM)', 'Daily Maintenance End (HH:MM)',
                        'Weekend Maintenance Start Day', 'Weekend Maintenance Start Time (HH:MM)',
                        'Weekend Maintenance End Day', 'Weekend Maintenance End Time (HH:MM)',
                        'Maintenance Buffer Minutes']
        
        tp_params = ['TP Method', 'Opposite Bollinger Band TP', 'Fixed ATR TP', 'Fixed BB at Entry TP',
                    'ATR Length for TP', 'ATR Multiplier for TP']
        
        sl_params = ['Initial Stop Loss (%)', 'Enable Trailing Stop', 
                     'ATR Length for Trailing Stop', 'ATR Multiplier for Trailing Stop',
                     'Trailing Delay (bars)']
                     
        ga_params = ['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                     'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                     'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                     'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT']

        # Determine optimized params set for quick lookup
        optimized_params = set(param_keys)

        # Iterate through param_dict to fill groups in order
        for pname in param_dict.keys():
             if pname.startswith('===') or pname.startswith('__'): continue
             
             # Only include if it is optimized OR if the user wants to see fixed ones too?
             # User said "all of the parameters", but convergence only makes sense for optimized ones.
             # However, showing fixed ones helps context.
             # Let's show optimized ones with stats, and fixed ones as just value.
             
             target_group = 'Other'
             if pname in entry_params: target_group = 'Entry Criteria'
             elif pname in tp_params: target_group = 'Take Profit Criteria'
             elif pname in sl_params: target_group = 'Stop Loss Criteria'
             elif pname in ga_params: target_group = 'GA Criteria'
             
             groups[target_group].append(pname)

        # Build HTML
        html = """
        <div class="card mb-4">
            <div class="card-header bg-primary text-white">
                <h5 class="mb-0">Parameter Convergence Analysis (Full List)</h5>
            </div>
            <div class="card-body">
                <p class="text-muted">
                    Displaying convergence statistics for all optimized parameters. 
                    <span style="color:green; font-weight:bold;">●</span> = Highly Converged (Top 25%), 
                    <span style="color:red; font-weight:bold;">●</span> = Divergent/Searching (Bottom 25%).
                </p>
        """
        
        # Calculate thresholds for ranking symbols (only for optimized parameters)
        if 'std_pct' in stats.columns:
            sorted_pct = stats['std_pct'].sort_values()
            n = len(sorted_pct)
            if n > 0:
                q25 = sorted_pct.iloc[int(n*0.25)]
                q75 = sorted_pct.iloc[int(n*0.75)]
            else:
                q25 = 0; q75 = 0
                
        for group_name, p_list in groups.items():
            if not p_list: continue
            
            # Filter p_list to only include items that exist in param_dict
            valid_list = [p for p in p_list if p in param_dict]
            if not valid_list: continue

            html += f"""
                <h6 class="mt-4" style="border-bottom: 2px solid #eee; padding-bottom: 5px;">{group_name}</h6>
                <div class="table-responsive">
                    <table class="table table-sm table-hover">
                        <thead class="thead-light"><tr><th>Status</th><th>Parameter</th><th>Input Range</th><th>Mean</th><th>StdDev</th><th>Range (Gen)</th><th>Chosen Value</th></tr></thead>
                        <tbody>
            """
            
            for pname in valid_list:
                # Get Input Range & Value safely
                p_data = param_dict[pname]
                if isinstance(p_data, dict):
                    p_min = p_data.get('min', 'N/A')
                    p_max = p_data.get('max', 'N/A')
                    val = p_data.get('value', 'N/A')
                else:
                    p_min = 'N/A'
                    p_max = 'N/A'
                    val = str(p_data)
                    
                input_range = f"[{p_min} - {p_max}]" if (p_min != 'N/A' and p_max != 'N/A') else "Fixed"
                
                # Check if optimized
                if pname in optimized_params and pname in stats.index:
                    row = stats.loc[pname]
                    mean_val = f"{row['mean']:.4f}"
                    std_val = f"{row['std']:.4f}"
                    gen_range = f"[{row['min']:.2f} - {row['max']:.2f}]"
                    
                    # Determine Symbol
                    std_pct = row['std_pct']
                    if std_pct <= q25:
                        symbol = '<span style="color:green; font-weight:bold;" title="Converged">●</span>'
                    elif std_pct >= q75:
                        symbol = '<span style="color:red; font-weight:bold;" title="Divergent">●</span>'
                    else:
                        symbol = '<span style="color:gray;" title="Stable">○</span>'
                else:
                    # Fixed Parameter
                    mean_val = str(val)
                    std_val = "-"
                    gen_range = "-"
                    symbol = ""
                    chosen_val = str(val) # Fixed param value

                # If optimized, overwrite chosen_val with actual chosen individual's value if available
                if chosen_params and pname in chosen_params:
                     # Format if float
                     v = chosen_params[pname]
                     if isinstance(v, float):
                         chosen_val = f"{v:.4f}"
                     else:
                         chosen_val = str(v)
                     
                     # Highlight if chosen value is far from mean? (Optional, skipping for now)

                html += f"""
                        <tr>
                            <td style="text-align:center;">{symbol}</td>
                            <td>{pname}</td>
                            <td>{input_range}</td>
                            <td>{mean_val}</td>
                            <td>{std_val}</td>
                            <td>{gen_range}</td>
                            <td><strong>{chosen_val}</strong></td>
                        </tr>
                """
            
            html += "</tbody></table></div>"
            
        html += "</div></div>"
        return html
            
    except Exception as e:
        print(f"Warning: Failed to generate convergence HTML: {e}")
        return f"<p class='text-danger'>Error generating table: {e}</p>"

def generate_html_dashboard(hof, best, best_params, best_fitness, param_keys, param_dict,
                            logbook, is_res, oos_res, trades_is, trades_oos,
                            html_path, diag_dir, current_gen=None, total_gen=None, 
                            is_final=False, auto_launch=False, is_periods=None, oos_periods=None,
                            in_sample=None, best_gen_found=None, pop=None): # Added pop argument

    
    # print(f"DEBUG: oos_res['sortino']: {oos_res.get('sortino')}")
    # print(f"DEBUG: trades_oos len: {len(trades_oos) if isinstance(trades_oos, pd.DataFrame) else 'Not a DF'}")
    # Ensure is_res and oos_res are always dicts with required keys
    # This prevents issues where None or incomplete dicts are passed
    required_keys = ['sortino', 'max_drawdown', 'avg_trades_day', 'profit_factor', 'total_profit']
    
    if not isinstance(is_res, dict):
        is_res = {key: 0 for key in required_keys}
    else:
        # Ensure all required keys exist
        for key in required_keys:
            if key not in is_res:
                is_res[key] = 0
    
    if not isinstance(oos_res, dict):
        oos_res = {key: 0 for key in required_keys}
    else:
        # Ensure all required keys exist
        for key in required_keys:
            if key not in oos_res:
                oos_res[key] = 0
    
    # Ensure trades_is and trades_oos are DataFrames
    if not isinstance(trades_is, pd.DataFrame):
        trades_is = pd.DataFrame()
    if not isinstance(trades_oos, pd.DataFrame):
        trades_oos = pd.DataFrame()
    
    # Helper function 'clamp_params' moved to global scope
    # Ensure trades_is and trades_oos are DataFrames
    if not isinstance(trades_is, pd.DataFrame):
        trades_is = pd.DataFrame()
    if not isinstance(trades_oos, pd.DataFrame):
        trades_oos = pd.DataFrame()
    
    # Extract Pareto front data with clamped parameters
    # FIX: Run actual backtests to get real metrics instead of using cached fitness values
    pareto_data = []
    
    # Get in-sample data for backtesting (use the same data that was used for evaluation)
    # If in_sample is provided, use it; otherwise, we can't run backtests
    can_run_backtests = in_sample is not None and len(in_sample) > 0
    
    # PERFORMANCE: Only run expensive backtests for all solutions on final generation
    # For intermediate generations, only run backtests for top 5 solutions to save time
    # This prevents 10-20 minute delays when Hall of Fame has 50+ solutions
    # For final generation, limit to top 50 solutions to prevent excessive delays
    # PERFORMANCE OPTIMIZATION:
    # Only run expensive backtests on final generation.
    # Intermediate generations should be "Lite Mode" to avoid blocking processing.
    if is_final:
        max_backtests = min(50, len(hof))
        if len(hof) > 50:
            print(f"  Note: Limiting backtests to top 50 solutions (out of {len(hof)} total) for performance.")
    else:
        # Lite Mode: Do NOT run backtests during intermediate updates
        max_backtests = 0
    
    if is_final and max_backtests > 10:
        print(f"  Generating dashboard: Running backtests for {max_backtests} solutions...")
        print(f"  This may take a few minutes. Progress will be shown every 10 solutions.")
    
    for i, ind in enumerate(hof):
        # Progress logging for final generation
        if is_final and max_backtests > 10 and i < max_backtests and (i + 1) % 10 == 0:
            print(f"    Progress: {i + 1}/{max_backtests} solutions processed...")
        raw_params = dict(zip(param_keys, ind))
        clamped_params = clamp_params(raw_params, param_dict)
        fitness = ind.fitness.values
        
        # Get generation number for debugging
        generation_found = getattr(ind, 'generation_found', None)
        if generation_found is None:
            generation_found = 0
        
        # Try to get actual metrics by running fresh backtest
        actual_sortino = None
        actual_dd = None
        actual_pf = None
        actual_trades = None
        actual_pnl = None
        
        # Only run backtest if we're within the limit (all solutions on final, top 5 on intermediate)
        if can_run_backtests and i < max_backtests:
            try:
                # Convert parameters the same way as final backtest (TP Method, booleans, etc.)
                test_params = clamped_params.copy()
                
                # Convert TP Method to boolean flags if needed
                if 'TP Method' in test_params:
                    tp_method = int(round(test_params['TP Method']))
                    test_params['Fixed BB at Entry TP'] = (tp_method == 0)
                    test_params['Fixed ATR TP'] = (tp_method == 1)
                    test_params['Opposite Bollinger Band TP'] = (tp_method == 2)
                    test_params.pop('TP Method', None)
                
                # Convert boolean parameters (0/1 int) to actual booleans
                for n in list(test_params.keys()):
                    if n in param_dict:
                        original_type = param_dict[n].get('type', '')
                        if original_type == 'bool' and isinstance(test_params[n], (int, float)):
                            test_params[n] = bool(int(round(test_params[n])))
                
                # Run actual backtest
                actual_metrics = run_backtest(test_params, in_sample, param_dict, suppress_output=True)
                if isinstance(actual_metrics, dict):
                    actual_sortino = actual_metrics.get('sortino', 0)
                    actual_dd = actual_metrics.get('max_drawdown', 0)
                    actual_pf = actual_metrics.get('profit_factor', 0)
                    actual_trades = actual_metrics.get('avg_trades_day', 0)
                    actual_pnl = actual_metrics.get('total_profit', 0)
                    trades_df = actual_metrics.get('trades_df', pd.DataFrame())
                    actual_ppt = actual_pnl / len(trades_df) if not trades_df.empty else 0.0
            except Exception as e:
                # If backtest fails, fall back to fitness values (but mark as normalized)
                pass
        
        # Use actual metrics if available, otherwise fall back to normalized fitness values
        # Note: avg_trades_day from fitness[3] is already raw (not normalized)
        # But total_profit from fitness[4] is normalized
        if actual_sortino is not None:
            # We have actual metrics from fresh backtest
            pareto_data.append({
                'index': i,
                'sortino': actual_sortino,
                'max_dd': actual_dd,
                'profit_factor': actual_pf,
                'avg_trades_day': actual_trades if actual_trades is not None else (fitness[3] if len(fitness) > 3 else 0.0),
                'total_profit': actual_pnl,
                'avg_profit_trade': actual_ppt if 'actual_ppt' in locals() else 0.0,
                'params': clamped_params,
                'is_selected': (ind == best),
                'generation': generation_found,
                'is_actual': True  # Flag to indicate these are actual metrics
            })
        else:
            # Fall back to normalized fitness values (from cached evaluation)
            avg_trades_day = fitness[3] if len(fitness) > 3 else 0.0
            total_profit = fitness[4] if len(fitness) > 4 else 0.0
            pareto_data.append({
                'index': i,
                'sortino': fitness[0],  # Normalized
                'max_dd': fitness[1],  # Normalized
                'profit_factor': fitness[2],  # Normalized
                'avg_trades_day': avg_trades_day,  # Raw (not normalized)
                'total_profit': total_profit,  # Normalized
                'avg_profit_trade': fitness[5] if len(fitness) > 5 else 0.0,  # Normalized
                'params': clamped_params,
                'is_selected': (ind == best),
                'generation': generation_found,
                'is_actual': False  # Flag to indicate these are normalized fitness values
            })
    
    pareto_df = pd.DataFrame(pareto_data)
    
    # Sort by different criteria for top candidates
    top_sortino = pareto_df.nlargest(5, 'sortino')
    top_pf = pareto_df.nlargest(5, 'profit_factor')
    top_dd = pareto_df.nsmallest(5, 'max_dd')
    
    # Create convergence plots (5 objectives: Sortino, Drawdown, Profit Factor, Avg Trades/Day, Total Profit)
    gens = logbook.select("gen")
    fig_convergence = make_subplots(rows=3, cols=2,
        subplot_titles=('Sortino Convergence', 'Drawdown Convergence', 'Profit Factor Convergence', 'Avg Trades/Day Convergence', 'Total Profit Convergence', 'Avg Profit/Trade Convergence'))
    
    # Sortino (row 1, col 1) - Show ACTUAL Sortino if available, otherwise normalized
    if 'actual_sortino_best' in logbook.header:
        # Show actual Sortino (from best individual each generation)
        actual_sortino_values = logbook.select("actual_sortino_best")
        # Filter out invalid values (inf, -inf, nan) but keep 0.0 if it's a real value
        # Check if all values are 0.0 (might indicate missing data from old checkpoint)
        all_zero = all(v == 0.0 or v is None for v in actual_sortino_values if isinstance(v, (int, float)))
        
        if not all_zero and len(actual_sortino_values) > 0:
            # We have valid actual values
            actual_sortino_values = [v if isinstance(v, (int, float)) and not (np.isinf(v) or np.isnan(v)) else None for v in actual_sortino_values]
            fig_convergence.add_trace(go.Scatter(x=gens, y=actual_sortino_values, name='Best (Actual)', line=dict(width=2, color='blue'), showlegend=False), row=1, col=1)
            # Also show normalized for comparison (dashed line)
            avg_sortino_norm = logbook.select("avg_sortino")
            # Filter out penalty values (-1000, -inf) for display
            avg_sortino_norm = [v if isinstance(v, (int, float)) and v > -500 and not np.isinf(v) else None for v in avg_sortino_norm]
            fig_convergence.add_trace(go.Scatter(x=gens, y=avg_sortino_norm, name='Avg (Normalized)', line=dict(dash='dash', color='gray'), showlegend=False), row=1, col=1)
        else:
            # All zeros or missing - fall back to normalized, but try to use is_res for final generation
            avg_sortino = logbook.select("avg_sortino")
            max_sortino = logbook.select("max_sortino")
            # Filter out -1000 penalty values and -inf for cleaner display
            avg_sortino = [v if isinstance(v, (int, float)) and v > -500 and not np.isinf(v) else None for v in avg_sortino]
            max_sortino = [v if isinstance(v, (int, float)) and v > -500 and not np.isinf(v) else None for v in max_sortino]
            
            # If we have is_res with actual Sortino, use it for the final generation
            if is_res and isinstance(is_res, dict) and 'sortino' in is_res and is_res['sortino'] > 0:
                # Replace the last value with actual Sortino from backtest
                if len(max_sortino) > 0:
                    max_sortino[-1] = is_res['sortino']
            
            fig_convergence.add_trace(go.Scatter(x=gens, y=avg_sortino, name='Avg (Normalized)', line=dict(dash='dash'), showlegend=False), row=1, col=1)
            fig_convergence.add_trace(go.Scatter(x=gens, y=max_sortino, name='Best (Actual if available)', line=dict(width=2), showlegend=False), row=1, col=1)
    else:
        # Fallback: show normalized values, filtering out penalty values
        avg_sortino = logbook.select("avg_sortino")
        max_sortino = logbook.select("max_sortino")
        # Filter out -1000 penalty values and -inf for cleaner display
        avg_sortino = [v if isinstance(v, (int, float)) and v > -500 and not np.isinf(v) else None for v in avg_sortino]
        max_sortino = [v if isinstance(v, (int, float)) and v > -500 and not np.isinf(v) else None for v in max_sortino]
        
        # If we have is_res with actual Sortino, use it for the final generation
        if is_res and isinstance(is_res, dict) and 'sortino' in is_res and is_res['sortino'] > 0:
            # Replace the last value with actual Sortino from backtest
            if len(max_sortino) > 0:
                max_sortino[-1] = is_res['sortino']
        
        fig_convergence.add_trace(go.Scatter(x=gens, y=avg_sortino, name='Avg (Normalized)', line=dict(dash='dash'), showlegend=False), row=1, col=1)
        fig_convergence.add_trace(go.Scatter(x=gens, y=max_sortino, name='Best (Actual if available)', line=dict(width=2), showlegend=False), row=1, col=1)
    
    # Drawdown (row 1, col 2) - Show ACTUAL drawdown in dollars if available, otherwise normalized
    if 'actual_dd_best' in logbook.header:
        # Show actual drawdown in dollars (from best individual)
        actual_dd_values = logbook.select("actual_dd_best")
        # Filter out invalid values
        actual_dd_values = [v if isinstance(v, (int, float)) and not (np.isinf(v) or np.isnan(v)) else 0.0 for v in actual_dd_values]
        fig_convergence.add_trace(go.Scatter(x=gens, y=actual_dd_values, name='Best (Actual $)', line=dict(width=2, color='blue'), showlegend=False), row=1, col=2)
        # Also show normalized for comparison (dashed line) - but only if values are reasonable
        avg_dd_norm = logbook.select("avg_dd")
        avg_dd_norm = [v if isinstance(v, (int, float)) and not np.isinf(v) and v >= 0 and v <= 1 else None for v in avg_dd_norm]
        fig_convergence.add_trace(go.Scatter(x=gens, y=avg_dd_norm, name='Avg (Normalized 0-1)', line=dict(dash='dash', color='gray'), showlegend=False), row=1, col=2)
    else:
        # Fallback: show normalized values
        avg_dd = logbook.select("avg_dd")
        min_dd = logbook.select("min_dd")
        # Filter to ensure values are in 0-1 range (normalized)
        avg_dd = [v if isinstance(v, (int, float)) and not np.isinf(v) and v >= 0 and v <= 1 else None for v in avg_dd]
        min_dd = [v if isinstance(v, (int, float)) and not np.isinf(v) and v >= 0 and v <= 1 else None for v in min_dd]
        fig_convergence.add_trace(go.Scatter(x=gens, y=avg_dd, name='Avg (Normalized 0-1)', line=dict(dash='dash'), showlegend=False), row=1, col=2)
        fig_convergence.add_trace(go.Scatter(x=gens, y=min_dd, name='Best (Normalized 0-1)', line=dict(width=2), showlegend=False), row=1, col=2)
    
    # Profit Factor (row 2, col 1)
    fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("avg_pf"), name='Avg', line=dict(dash='dash'), showlegend=False), row=2, col=1)
    fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("max_pf"), name='Best', line=dict(width=2), showlegend=False), row=2, col=1)
    
    # Avg Trades/Day (row 2, col 2)
    fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("avg_trades_day"), name='Avg', line=dict(dash='dash'), showlegend=False), row=2, col=2)
    fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("max_trades_day"), name='Best', line=dict(width=2), showlegend=False), row=2, col=2)
    
    # Total Profit (row 3, col 1)
    if 'avg_total_profit' in logbook.header:
        fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("avg_total_profit"), name='Avg', line=dict(dash='dash'), showlegend=False), row=3, col=1)
        # For max, we'll use the same as avg for now (logbook doesn't track max_total_profit separately)
        # In practice, this will be similar to avg since we're tracking normalized values
        fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("avg_total_profit"), name='Best', line=dict(width=2), showlegend=False), row=3, col=1)
    else:
        # Fallback: use zeros if logbook doesn't have it yet
        fig_convergence.add_trace(go.Scatter(x=gens, y=[0]*len(gens), name='Avg', line=dict(dash='dash'), showlegend=False), row=3, col=1)
        fig_convergence.add_trace(go.Scatter(x=gens, y=[0]*len(gens), name='Best', line=dict(width=2), showlegend=False), row=3, col=1)

    # Avg Profit Per Trade (row 3, col 2)
    if 'avg_profit_per_trade' in logbook.header:
        fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("avg_profit_per_trade"), name='Avg', line=dict(dash='dash'), showlegend=False), row=3, col=2)
        fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("avg_profit_per_trade"), name='Best', line=dict(width=2), showlegend=False), row=3, col=2)
    else:
         # Fallback
        fig_convergence.add_trace(go.Scatter(x=gens, y=[0]*len(gens), name='Avg', line=dict(dash='dash'), showlegend=False), row=3, col=2)
        fig_convergence.add_trace(go.Scatter(x=gens, y=[0]*len(gens), name='Best', line=dict(width=2), showlegend=False), row=3, col=2)
    
    fig_convergence.update_layout(height=900, showlegend=True, title_text="Convergence Plots")
    fig_convergence.update_xaxes(title_text="Generation", row=2, col=1)
    fig_convergence.update_xaxes(title_text="Generation", row=2, col=2)
    fig_convergence.update_xaxes(title_text="Generation", row=3, col=1)
    fig_convergence.update_xaxes(title_text="Generation", row=3, col=2)
    # Update axis labels based on what data is being shown
    # Check if we're actually showing actual values (not all zeros)
    showing_actual = False
    if 'actual_sortino_best' in logbook.header:
        actual_vals = logbook.select("actual_sortino_best")
        # Check if we have any non-zero actual values
        if any(v and isinstance(v, (int, float)) and v > 0.01 and not np.isinf(v) and not np.isnan(v) for v in actual_vals):
            showing_actual = True
    # Also check if we used is_res for the final generation
    if is_res and isinstance(is_res, dict) and 'sortino' in is_res and is_res['sortino'] > 0:
        showing_actual = True
    
    # Calculate max Sortino value for y-axis upper bound
    sortino_max = 1.0  # Default minimum upper bound
    if 'actual_sortino_best' in logbook.header:
        actual_vals = logbook.select("actual_sortino_best")
        valid_vals = [v for v in actual_vals if isinstance(v, (int, float)) and not (np.isinf(v) or np.isnan(v)) and v > -500]
        if valid_vals:
            sortino_max = max(max(valid_vals), 1.0)  # At least show up to 1.0
    else:
        # Use normalized values
        max_vals = logbook.select("max_sortino")
        valid_vals = [v for v in max_vals if isinstance(v, (int, float)) and v > -500 and not np.isinf(v)]
        if valid_vals:
            sortino_max = max(max(valid_vals), 1.0)
    
    # Add 20% padding to upper bound, but ensure minimum of 1.0
    sortino_max = max(sortino_max * 1.2, 1.0)
    
    if showing_actual:
        # Fix lower bound at -1 so negative Sortino values remain visible and scale doesn't zoom excessively
        fig_convergence.update_yaxes(title_text="Sortino Ratio (Actual)", row=1, col=1, range=[-1, sortino_max])
    else:
        fig_convergence.update_yaxes(title_text="Sortino (Normalized 0-1)", row=1, col=1, range=[-1, sortino_max])
    
    if 'actual_dd_best' in logbook.header:
        fig_convergence.update_yaxes(title_text="Max Drawdown ($)", row=1, col=2)
    else:
        fig_convergence.update_yaxes(title_text="Drawdown (Normalized 0-1, inverted)", row=1, col=2)
    fig_convergence.update_yaxes(title_text="Profit Factor", row=2, col=1)
    fig_convergence.update_yaxes(title_text="Avg Trades/Day (Score 0-1)", row=2, col=2)
    fig_convergence.update_yaxes(title_text="Total Profit (norm)", row=3, col=1)
    
    # Pareto front 3D (only if we have solutions)
    if len(hof) > 0:
        sortinos = [ind.fitness.values[0] for ind in hof]
        dds = [ind.fitness.values[1] for ind in hof]
        pfs = [ind.fitness.values[2] for ind in hof]
        is_selected = [ind == best for ind in hof] if best is not None else [False] * len(hof)
    else:
        sortinos = []
        dds = []
        pfs = []
        is_selected = []
    
    fig_pareto_3d = go.Figure(data=go.Scatter3d(
        x=dds, y=sortinos, z=pfs, mode='markers',
        marker=dict(size=8, color=sortinos, colorscale='Viridis', showscale=True,
                   line=dict(width=2, color=[('red' if sel else 'black') for sel in is_selected])),
        text=[f"Sol {i}: S={s:.3f}, DD={d:.1f}, PF={p:.3f}" for i, (s, d, p) in enumerate(zip(sortinos, dds, pfs))],
        hovertemplate="<b>%{text}</b><br>" +
                      "Sortino: %{y:.3f}<br>" +
                      "Drawdown: $%{x:,.2f}<br>" +
                      "Profit Factor: %{z:.3f}<extra></extra>"
    ))
    fig_pareto_3d.add_trace(go.Scatter3d(
        x=[best_fitness[1]], y=[best_fitness[0]], z=[best_fitness[2]],
        mode='markers', marker=dict(size=15, color='red', symbol='diamond'),
        name='Selected', hovertemplate=f"Selected: S={best_fitness[0]:.3f}, DD={best_fitness[1]:.1f}, PF={best_fitness[2]:.3f}<extra></extra>"
    ))
    fig_pareto_3d.update_layout(
        title="Pareto Front 3D: Sortino vs Drawdown vs Profit Factor",
        scene=dict(xaxis_title="Max Drawdown", yaxis_title="Sortino", zaxis_title="Profit Factor"),
        height=600
    )
    
    # Pareto 2D projections
    fig_pareto_2d = make_subplots(rows=1, cols=3,
        subplot_titles=('Sortino vs DD', 'Sortino vs PF', 'DD vs PF'))
    fig_pareto_2d.add_trace(go.Scatter(x=dds, y=sortinos, mode='markers', name='Solutions',
        marker=dict(size=8, color=sortinos, colorscale='Viridis', showscale=False,
                   line=dict(width=2, color=[('red' if sel else 'black') for sel in is_selected]))), row=1, col=1)
    fig_pareto_2d.add_trace(go.Scatter(x=[best_fitness[1]], y=[best_fitness[0]], mode='markers',
        marker=dict(size=15, color='red', symbol='diamond'), name='Selected', showlegend=False), row=1, col=1)
    fig_pareto_2d.add_trace(go.Scatter(x=sortinos, y=pfs, mode='markers', showlegend=False,
        marker=dict(size=8, color=sortinos, colorscale='Viridis', showscale=False,
                   line=dict(width=2, color=[('red' if sel else 'black') for sel in is_selected]))), row=1, col=2)
    fig_pareto_2d.add_trace(go.Scatter(x=[best_fitness[0]], y=[best_fitness[2]], mode='markers',
        marker=dict(size=15, color='red', symbol='diamond'), showlegend=False), row=1, col=2)
    fig_pareto_2d.add_trace(go.Scatter(x=dds, y=pfs, mode='markers', showlegend=False,
        marker=dict(size=8, color=sortinos, colorscale='Viridis', showscale=False,
                   line=dict(width=2, color=[('red' if sel else 'black') for sel in is_selected]))), row=1, col=3)
    fig_pareto_2d.add_trace(go.Scatter(x=[best_fitness[1]], y=[best_fitness[2]], mode='markers',
        marker=dict(size=15, color='red', symbol='diamond'), showlegend=False), row=1, col=3)
    fig_pareto_2d.update_xaxes(title_text="Drawdown", row=1, col=1)
    fig_pareto_2d.update_xaxes(title_text="Sortino", row=1, col=2)
    fig_pareto_2d.update_xaxes(title_text="Drawdown", row=1, col=3)
    fig_pareto_2d.update_yaxes(title_text="Sortino", row=1, col=1)
    fig_pareto_2d.update_yaxes(title_text="Profit Factor", row=1, col=2)
    fig_pareto_2d.update_yaxes(title_text="Profit Factor", row=1, col=3)
    fig_pareto_2d.update_layout(height=400)
    
    # Pareto size
    fig_pareto_size = go.Figure()
    if len(gens) > 0:
        fig_pareto_size.add_trace(go.Scatter(x=gens, y=logbook.select("pareto_size"), mode='lines+markers', name='Size'))
    fig_pareto_size.update_layout(title="Pareto Front Size", xaxis_title="Generation", yaxis_title="Solutions", height=300)
    
    # Generate HTML tables and content
    # avg_trades_day is already calculated in pareto_data extraction above
    # Check if we're showing actual or normalized values
    showing_actual = any(sol.get('is_actual', False) for sol in pareto_data)
    
    if showing_actual:
        pareto_table_html = "<table class='pareto-table'><thead><tr><th>Rank</th><th>Gen</th><th>Sortino (Actual)</th><th>Max DD (Actual)</th><th>PF (Actual)</th><th>Avg Trades/Day (Actual)</th><th>Total Profit (Actual)</th><th>Avg P/T (Actual)</th><th>Selected</th></tr></thead><tbody>"
    else:
        pareto_table_html = "<table class='pareto-table'><thead><tr><th>Rank</th><th>Gen</th><th>Sortino (Norm 0-1)</th><th>Max DD (Norm 0-1)</th><th>PF (Norm 0-1)</th><th>Avg Trades/Day (Score 0-1)</th><th>Total Profit (Norm 0-1)</th><th>Avg P/T (Norm 0-1)</th><th>Selected</th></tr></thead><tbody>"
    
    pareto_sorted = sorted(pareto_data, key=lambda x: x['sortino'], reverse=True)
    for rank, sol in enumerate(pareto_sorted, 1):
        mark = "*" if sol['is_selected'] else ""
        avg_trades = sol.get('avg_trades_day', 0.0)
        total_profit = sol.get('total_profit', 0.0)
        ppt = sol.get('avg_profit_trade', 0.0)
        generation = sol.get('generation', 0)
        
        if showing_actual:
            # Format actual values
            sortino_str = f"{sol['sortino']:.6f}" if sol['sortino'] is not None else "N/A"
            dd_str = f"${sol['max_dd']:,.2f}" if sol['max_dd'] is not None else "N/A"
            pf_str = f"{sol['profit_factor']:.6f}" if sol['profit_factor'] is not None else "N/A"
            trades_str = f"{avg_trades:.3f}" if avg_trades is not None else "N/A"
            pnl_str = f"${total_profit:,.2f}" if total_profit is not None else "N/A"
            ppt_str = f"${ppt:,.2f}" if ppt is not None else "N/A"
            pareto_table_html += f"<tr class='{'selected-row' if sol['is_selected'] else ''}'><td>{rank}</td><td>{generation}</td><td>{sortino_str}</td><td>{dd_str}</td><td>{pf_str}</td><td>{trades_str}</td><td>{pnl_str}</td><td>{ppt_str}</td><td>{mark}</td></tr>"
        else:
            # Format normalized values
            pareto_table_html += f"<tr class='{'selected-row' if sol['is_selected'] else ''}'><td>{rank}</td><td>{generation}</td><td>{sol['sortino']:.4f}</td><td>{sol['max_dd']:.2f}</td><td>{sol['profit_factor']:.4f}</td><td>{avg_trades:.3f}</td><td>{total_profit:.4f}</td><td>{ppt:.4f}</td><td>{mark}</td></tr>"

    pareto_table_html += "</tbody></table>"
    
    
    # ====================================================================
    # PARAMETER ANALYSIS VISUALIZATIONS
    # ====================================================================
    # Generate parameter analysis charts (correlation, importance, distributions)
    # Use same pattern as working charts: separate divs and scripts, place scripts at end
    # SKIP parameter analysis for intermediate generations (is_final=False) to save time
    # Parameter analysis is expensive and only needed for final results
    param_analysis_html = ""
    param_analysis_scripts = ""  # Will be placed before </body> like other charts
    
    # Only generate parameter analysis for final generation or every generation if requested
    # Run parameter analysis every generation (it is relatively cheap now)
    # This combines convergence analysis with parameter values as requested
    generate_param_analysis = True 
    
    if generate_param_analysis:
        try:
             # Pass current generation number for context
             p_div, p_script = generate_interactive_analysis(hof, param_keys, param_dict, current_gen)
             param_analysis_html = p_div
             param_analysis_scripts = p_script
        except Exception as e:
            print(f"Error generating parameter analysis: {e}")
            param_analysis_html = f"<p>Error generating parameter analysis: {str(e)}</p>"
    
    # Original parameter analysis code (commented out until indentation is fixed)
    # DISABLED: Commented out entire section due to indentation errors
    # Parameter analysis disabled due to indentation issues in legacy code
    pass
    def group_parameters(param_keys_local, param_dict_local):
        # Group parameters into logical categories
        groups = {
            'Entry Criteria': [],
            'Take Profit Criteria': [],
            'Stop Loss Criteria': [],
            'GA Criteria': [],
            'Other': []
        }
        
        # Define parameter groups
        entry_params = ['Enable Long Trades', 'Enable Short Trades', 'Bollinger Band Length', 
                        'Bollinger Band StdDev', 'Long Entry on Wick Touch', 'Long Entry on Body in Zone',
                        'Long Trigger (% From Lower Band)', 'Short Entry on Wick Touch', 
                        'Short Entry on Body in Zone', 'Short Trigger (% From Upper Band)',
                        'ATR Length for Filter', 'Max ATR Filter (Points)', 'Min ATR Filter (Points)', 
                        'Enable Trend Filter', 'Trend EMA Length',
                        'Enable ADX Filter', 'ADX Period', 'Max ADX Threshold',
                        'RTH Start (HH:MM)', 'RTH End (HH:MM)',
                        'Enable RTH Filter', 'Volume MA Length', 'Max Volume Multiplier', 'Timeframe (minutes)',
                        'Max Open Trades', 'RTH Exit Buffer (minutes)', 'Enable Maintenance Filter',
                        'Daily Maintenance Start (HH:MM)', 'Daily Maintenance End (HH:MM)',
                        'Weekend Maintenance Start Day', 'Weekend Maintenance Start Time (HH:MM)',
                        'Weekend Maintenance End Day', 'Weekend Maintenance End Time (HH:MM)',
                        'Maintenance Buffer Minutes']
        
        tp_params = ['TP Method', 'Opposite Bollinger Band TP', 'Fixed ATR TP', 'Fixed BB at Entry TP',
                    'ATR Length for TP', 'ATR Multiplier for TP']
        
        sl_params = ['Initial Stop Loss (%)', 'Enable Trailing Stop', 
                     'ATR Length for Trailing Stop', 'ATR Multiplier for Trailing Stop',
                     'Trailing Delay (bars)']
        
        ga_params = ['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                     'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                     'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                     'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT']
        
        # Group ALL parameters from param_dict (not just optimizable ones)
        for pname in param_dict_local.keys():
            # Skip section headers and metadata
            if pname.startswith('===') or pname.startswith('__'):
                continue
            
            if pname in entry_params:
                groups['Entry Criteria'].append(pname)
            elif pname in tp_params:
                groups['Take Profit Criteria'].append(pname)
            elif pname in sl_params:
                groups['Stop Loss Criteria'].append(pname)
            elif pname in ga_params:
                groups['GA Criteria'].append(pname)
            else:
                # Default to Other if not found
                groups['Other'].append(pname)
        
        return groups
    
    param_groups = group_parameters(param_keys, param_dict)
    
    # Define GA Criteria parameters (these are NOT optimized, even if they have min/max)
    ga_criteria_params = set(['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                              'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                              'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                              'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT'])
    
    # Determine which parameters are optimizable
    # Parameters in param_keys are optimizable (they were used to build PARAM_RANGES)
    # Also check for parameters that have min/max and are int/float, but exclude:
    # 1. GA Criteria parameters
    # 2. Parameters where min==max (effectively fixed)
    optimizable_params = set(param_keys)  # Start with known optimizable params
    for pname, pdata in param_dict.items():
        if pname.startswith('===') or pname.startswith('__'):
            continue
        if pname in ga_criteria_params:
            continue
        
        # FIX: Ensure pdata is a dictionary
        if not isinstance(pdata, dict):
            continue
            
        ptype = pdata.get('type', '')
        pmin = pdata.get('min')
        pmax = pdata.get('max')
        # Include int/float parameters with valid min/max where min != max
        if ptype in ('int', 'float') and pmin is not None and pmax is not None and pmin != pmax:
            optimizable_params.add(pname)
    
    # Add generation info at the top of parameters section
    gen_info_html = ""
    if best_gen_found is not None:
        gen_info_html = f"<div class='info-section' style='background: #e8f4f8; padding: 10px; border-radius: 5px; margin-bottom: 20px;'><strong>Solution Information:</strong><br>This solution was found in <strong>Generation {best_gen_found}</strong> (out of {total_gen if total_gen else '?'} total generations).<br><small>To see this solution performance in the convergence plots, look at generation {best_gen_found} - the Best line at that generation shows the best individual from that specific generation. This Selected Solution is the overall best across ALL generations (Hall of Fame best).</small></div>"
    
    best_params_html = gen_info_html
    for group_name, params_list in param_groups.items():
        if params_list:  # Only show group if it has parameters
            # Add note for GA Criteria group
            if group_name == 'GA Criteria':
                best_params_html += f"<h3 style='margin-top: 20px; color: #555; border-bottom: 2px solid #ddd; padding-bottom: 5px;'>{group_name}<span class='tooltip-icon' style='margin-left: 10px;'>?</span><span class='tooltip'>These are GA configuration parameters that control how the optimization runs. They are NOT optimized by the GA - they are set manually in the parameter CSV file. The min/max values shown are just valid ranges for manual configuration.</span></h3>"
            else:
                best_params_html += f"<h3 style='margin-top: 20px; color: #555; border-bottom: 2px solid #ddd; padding-bottom: 5px;'>{group_name}</h3>"
            best_params_html += "<table class='params-table'><thead><tr><th>Parameter</th><th>Range</th><th>Optimized Value</th></tr></thead><tbody>"
            for pname in sorted(params_list):
                if pname in param_dict:
                    pdata = param_dict[pname]
                    
                    # FIX: Ensure pdata is a dictionary
                    if not isinstance(pdata, dict):
                        continue
                        
                    ptype = pdata.get('type', '')
                    pmin = pdata.get('min')
                    pmax = pdata.get('max')
                    default_val = pdata.get('value')
                    
                    # Check if optimizable
                    is_optimizable = pname in optimizable_params
                    
                    if is_optimizable:
                        # Show range and optimized value
                        if pmin is not None and pmax is not None:
                            if ptype == 'int':
                                range_str = f"{int(pmin)} - {int(pmax)}"
                            else:
                                range_str = f"{float(pmin):.4f} - {float(pmax):.4f}"
                        else:
                            range_str = "N/A"
                        
                        # Get optimized value from best_params if available
                        if pname in best_params:
                            opt_val = best_params[pname]
                            if pname == 'TP Method':
                                # Special handling for TP Method - show human-readable value
                                tp_method_val = int(round(opt_val))
                                tp_method_names = {0: 'Fixed BB at Entry', 1: 'Fixed ATR', 2: 'Opposite BB'}
                                opt_val_str = f"{tp_method_val} ({tp_method_names.get(tp_method_val, 'Unknown')})"
                            elif ptype == 'int':
                                opt_val_str = str(int(round(opt_val)))
                            else:
                                opt_val_str = f"{opt_val:.4f}"
                        else:
                            opt_val_str = "N/A"
                        
                        best_params_html += f"<tr><td>{pname}</td><td>{range_str}</td><td><strong>{opt_val_str}</strong></td></tr>"
                    else:
                        # Fixed parameter - show single value
                        if default_val is not None:
                            if ptype == 'bool':
                                # Handle both boolean and string representations
                                if isinstance(default_val, bool):
                                    val_str = 'True' if default_val else 'False'
                                elif isinstance(default_val, str):
                                    val_str = default_val.capitalize()
                                else:
                                    val_str = 'True' if default_val else 'False'
                            elif ptype == 'int':
                                try:
                                    val_str = str(int(default_val))
                                except (ValueError, TypeError):
                                    val_str = str(default_val)
                            elif ptype == 'float':
                                try:
                                    val_str = f"{float(default_val):.4f}"
                                except (ValueError, TypeError):
                                    val_str = str(default_val)
                            else:
                                # String or other types
                                val_str = str(default_val)
                        else:
                            val_str = "N/A"
                        
                        best_params_html += f"<tr><td>{pname}</td><td><em>Fixed</em></td><td>{val_str}</td></tr>"
            best_params_html += "</tbody></table>"
    
    # Comparison table - match console output exactly
    comparison_html = "<table class='comparison-table'><thead><tr><th>Metric</th><th>In-Sample</th><th>OOS</th><th>Difference</th></tr></thead><tbody>"
    
    # Ensure is_res and oos_res are dicts with required keys
    if not isinstance(is_res, dict):
        is_res = {'sortino': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0, 'total_profit': 0}
    if not isinstance(oos_res, dict):
        oos_res = {'sortino': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0, 'total_profit': 0}
    
    # Ensure all required keys exist
    required_keys = ['sortino', 'max_drawdown', 'avg_trades_day', 'profit_factor', 'total_profit', 'avg_profit_per_trade']
    for key in required_keys:
        if key not in is_res:
             # Try to calculate if missing
             if key == 'avg_profit_per_trade':
                 tp = is_res.get('total_profit', 0)
                 count = len(trades_is) if 'trades_is' in locals() else 0
                 is_res[key] = tp / count if count > 0 else 0
             else:
                 is_res[key] = 0
        if key not in oos_res:
             if key == 'avg_profit_per_trade':
                 tp = oos_res.get('total_profit', 0)
                 count = len(trades_oos) if 'trades_oos' in locals() else 0
                 oos_res[key] = tp / count if count > 0 else 0
             else:
                 oos_res[key] = 0
    
    # Calculate Standard Daily Sortino (Time-Based) for Reporting
    def calc_daily_sortino(trades):
        if not isinstance(trades, pd.DataFrame) or trades.empty: return 0.0
        try:
             # Create copy to avoid SettingWithCopy warnings
             t = trades.copy()
             if 'exit_time' not in t.columns: return 0.0
             
             if not pd.api.types.is_datetime64_any_dtype(t['exit_time']):
                 t['exit_time'] = pd.to_datetime(t['exit_time'])
             
             # Resample to Daily PnL (including 0 days if range allows, but here simply by trade days + intermediate)
             # Note: proper 0-filling requires start/end dates, here we approximate with min/max trade dates
             daily_pnl = t.set_index('exit_time')['pnl'].resample('D').sum().fillna(0)
             
             avg_daily = daily_pnl.mean()
             neg_daily = daily_pnl[daily_pnl < 0]
             
             # Std Dev of negative returns
             downside_std = neg_daily.std()
             if pd.isna(downside_std) or downside_std == 0:
                 return 0.0
                 
             return (avg_daily / downside_std) * (252**0.5)
        except Exception as e:
             # print(f"Sortino calc error: {e}")
             return 0.0

    is_res['daily_sortino'] = calc_daily_sortino(trades_is)
    oos_res['daily_sortino'] = calc_daily_sortino(trades_oos)

    # Metrics to compare (matching console output)
    metrics_to_compare = [
        ('sortino', 'Sortino (Trade Proxy)', False),  # Renamed for clarity
        ('daily_sortino', 'Sortino (Daily Std)', False), # New Standard Metric
        ('max_drawdown', 'Max Drawdown', True),
        ('avg_trades_day', 'Avg Trades/Day', False),
        ('profit_factor', 'Profit Factor', False),
        ('avg_profit_per_trade', 'Avg Profit/Trade', False), # NEW: Requested by User
        ('total_profit', 'Total Profit', False)  # NEW: 5th objective
    ]
    
    for metric_key, metric_name, lower_is_better in metrics_to_compare:
        # Get values from backtest results (these should match console output)
        is_val = is_res.get(metric_key, 0)
        oos_val = oos_res.get(metric_key, 0)
        
        # Calculate difference (for drawdown, lower is better, so flip the diff)
        if lower_is_better:
            diff = is_val - oos_val  # Positive diff means OOS is better (lower drawdown)
        else:
            diff = oos_val - is_val  # Positive diff means OOS is better (higher value)
        
        diff_class = 'positive' if diff > 0 else 'negative' if diff < 0 else ''
        diff_pct = (diff / is_val * 100) if is_val != 0 else 0
        
        # Format values appropriately to match console output
        if metric_key == 'max_drawdown':
            is_str = f"{is_val:.6f}"  # Match console format
            oos_str = f"{oos_val:.6f}"
            diff_str = f"{diff:+.6f} ({diff_pct:+.1f}%)"
        elif metric_key == 'total_profit':
            is_str = f"${is_val:,.2f}"  # Format as currency
            oos_str = f"${oos_val:,.2f}"
            diff_str = f"${diff:+,.2f} ({diff_pct:+.1f}%)"
        elif metric_key == 'avg_trades_day':
            is_str = f"{is_val:.6f}"
            oos_str = f"{oos_val:.6f}"
            diff_str = f"{diff:+.6f} ({diff_pct:+.1f}%)"
        elif metric_key == 'avg_profit_per_trade':
            is_str = f"${is_val:,.2f}"
            oos_str = f"${oos_val:,.2f}"
            diff_str = f"${diff:+,.2f} ({diff_pct:+.1f}%)"
        else:
            is_str = f"{is_val:.6f}"
            oos_str = f"{oos_val:.6f}"
            diff_str = f"{diff:+.6f} ({diff_pct:+.1f}%)"
        
        comparison_html += f"<tr><td>{metric_name}</td><td>{is_str}</td><td>{oos_str}</td><td class='{diff_class}'>{diff_str}</td></tr>"
    
    comparison_html += "</tbody></table>"
    
    # Add summary statistics matching console output
    summary_html = '<h3>Performance Summary</h3> <div class="info-section"> <strong>Summary Metrics:</strong> These metrics provide a quick overview of strategy performance. Compare IS vs OOS to assess generalization. Large differences indicate potential overfitting. </div> <table class=\'summary-table\'><thead><tr> <th>Dataset<span class="tooltip-icon">?</span><span class="tooltip">In-Sample (training) or OOS (validation) dataset.</span></th> <th>PNL<span class="tooltip-icon">?</span><span class="tooltip">Total Profit and Loss in dollars. Sum of all trade PNLs.</span></th> <th>Win Rate<span class="tooltip-icon">?</span><span class="tooltip">Percentage of profitable trades. Higher is generally better, but not always (depends on risk/reward).</span></th> <th>Profit Factor<span class="tooltip-icon">?</span><span class="tooltip">Gross Profit / Gross Loss. >1.0 = profitable, >2.0 = excellent. Shows dollar efficiency.</span></th> <th>Calmar Ratio<span class="tooltip-icon">?</span><span class="tooltip">Total PNL / Max Drawdown. Higher is better. Measures return per unit of maximum risk.</span></th> <th>Max Monthly<span class="tooltip-icon">?</span><span class="tooltip">Best performing month in dollars. Shows maximum profit achieved in any single month.</span></th> <th>Min Monthly<span class="tooltip-icon">?</span><span class="tooltip">Worst performing month in dollars. Shows maximum loss (or minimum profit) in any single month.</span></th> <th>Avg Monthly<span class="tooltip-icon">?</span><span class="tooltip">Average monthly profit in dollars. Mean of all monthly PNL values. Helps assess consistency.</span></th> </tr></thead><tbody>'
    
    # is_res and oos_res are already validated at function start, so they're guaranteed to be dicts
    for label, trades, res in [('In-Sample', trades_is, is_res), ('OOS', trades_oos, oos_res)]:
        
        if not trades.empty:
            total_pnl = trades['pnl'].sum()
            win_rate = (trades['pnl'] > 0).mean() * 100
            pf = abs(trades[trades['pnl'] > 0]['pnl'].sum() / trades[trades['pnl'] < 0]['pnl'].sum()) if (trades['pnl'] < 0).any() else np.inf
            max_dd = res.get('max_drawdown', 0)
            calmar = total_pnl / max_dd if max_dd > 0 else np.inf
            
            # Calculate monthly profit stats
            monthly_stats = res.get('monthly_profit_stats', {})
            max_monthly = monthly_stats.get('max_monthly_profit', 0) if isinstance(monthly_stats, dict) else 0
            min_monthly = monthly_stats.get('min_monthly_profit', 0) if isinstance(monthly_stats, dict) else 0
            avg_monthly = monthly_stats.get('avg_monthly_profit', 0) if isinstance(monthly_stats, dict) else 0
            
            summary_html += f"<tr><td>{label}</td><td>${total_pnl:,.0f}</td><td>{win_rate:.1f}%</td><td>{pf:.2f}</td><td>{calmar:.2f}</td><td>${max_monthly:,.0f}</td><td>${min_monthly:,.0f}</td><td>${avg_monthly:,.0f}</td></tr>"
        else:
            summary_html += f"<tr><td>{label}</td><td>N/A</td><td>N/A</td><td>N/A</td><td>N/A</td><td>N/A</td><td>N/A</td><td>N/A</td></tr>"
    
    summary_html += "</tbody></table>"
    
    # Generate HTML snippets for charts
    conv_html = fig_convergence.to_html(include_plotlyjs=False, div_id='conv_chart')
    pareto3d_html = fig_pareto_3d.to_html(include_plotlyjs=False, div_id='pareto3d_chart')
    pareto2d_html = fig_pareto_2d.to_html(include_plotlyjs=False, div_id='pareto2d_chart')
    paretosize_html = fig_pareto_size.to_html(include_plotlyjs=False, div_id='paretosize_chart')
    
    # Extract div and script from each chart (extract_chart_html is defined earlier)
    conv_div, conv_script = extract_chart_html(conv_html)
    pareto3d_div, pareto3d_script = extract_chart_html(pareto3d_html)
    pareto2d_div, pareto2d_script = extract_chart_html(pareto2d_html)
    paretosize_div, paretosize_script = extract_chart_html(paretosize_html)
    print("DEBUG: extract_chart_html END")
    
    # Progress information with time tracking
    progress_html = ""
    if current_gen is not None and total_gen is not None:
        progress_pct = (current_gen / total_gen * 100) if total_gen > 0 else 0
        status = "COMPLETE" if is_final else "IN PROGRESS"
        status_color = "#4CAF50" if is_final else "#FF9800"
        
        # Calculate elapsed time and predicted completion
        elapsed_time_str = "N/A"
        predicted_completion_str = "N/A"
        
        # Try to read start time from file
        start_time = None
        START_TIME_FILE = os.path.join(diag_dir, 'ga_start_time.txt')
        if os.path.exists(START_TIME_FILE):
            try:
                with open(START_TIME_FILE, 'r') as f:
                    start_time = float(f.read().strip())
            except:
                pass
        
        if start_time is not None:
            elapsed_seconds = time.time() - start_time
            elapsed_td = timedelta(seconds=int(elapsed_seconds))
            # Format as HH:MM:SS
            hours, remainder = divmod(elapsed_td.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            elapsed_time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            if elapsed_td.days > 0:
                elapsed_time_str = f"{elapsed_td.days}d {elapsed_time_str}"
            
            # Calculate predicted completion time
            if current_gen > 0 and not is_final:
                avg_time_per_gen = elapsed_seconds / current_gen
                remaining_gens = total_gen - current_gen
                predicted_seconds = avg_time_per_gen * remaining_gens
                predicted_completion = datetime.now() + timedelta(seconds=int(predicted_seconds))
                predicted_completion_str = predicted_completion.strftime('%Y-%m-%d %H:%M:%S')
                
        # Status Banner HTML
        progress_html = f"""
        <div style="background-color: #333; color: white; padding: 15px; text-align: center; margin-bottom: 20px; border-radius: 5px;">
            <h2 style="margin: 0; color: {status_color};">{status} - Generation {current_gen}/{total_gen} ({progress_pct:.1f}%)</h2>
            <div style="margin-top: 10px; font-size: 0.9em;">
                <span>Elapsed: {elapsed_time_str}</span> | 
                <span>Est. Completion: {predicted_completion_str}</span>
            </div>
            <div style="width: 100%; background-color: #555; height: 10px; margin-top: 10px; border-radius: 5px; overflow: hidden;">
                <div style="width: {progress_pct}%; background-color: {status_color}; height: 100%;"></div>
            </div>
        </div>
        """
    fitness_weights_html = "<h2>Fitness Function Configuration</h2><div class='info-section'><table class='params-table'><thead><tr><th>Objective</th><th>Weight</th><th>Direction</th><th>Normalization Range</th><th>Notes</th></tr></thead><tbody>"
    
    # Get weights from creator.FitnessMulti
    from deap import creator
    if hasattr(creator, 'FitnessMulti'):
        weights = creator.FitnessMulti.weights
        weight_names = ['Sortino Ratio', 'Max Drawdown', 'Profit Factor', 'Avg Trades/Day', 'Total Profit', 'Avg Profit/Trade']
        directions = ['Maximize', 'Minimize', 'Maximize', 'Maximize', 'Maximize', 'Maximize']
        
        # Get normalization ranges from param_dict with safety check
        def get_p_val(key, default):
            item = param_dict.get(key)
            if isinstance(item, dict):
                return item.get('value', default)
            return default

        norm_ranges = {
            'Sortino Ratio': get_p_val('NORM_SORTINO_MAX', 10.0),
            'Max Drawdown': get_p_val('NORM_DD_MAX', 100000.0),
            'Profit Factor': get_p_val('NORM_PF_MAX', 5.0),
            'Avg Trades/Day': get_p_val('NORM_TRADES_MAX', 3.0),
            'Total Profit': get_p_val('NORM_PNL_MAX', 200000.0),
            'Avg Profit/Trade': get_p_val('NORM_PROFIT_TRADE_MAX', 250.0)
        }
        
        notes = [
            '<strong>Constraint:</strong> No Floor (Negative Values Allowed). Goal: Maximize. Penalized if < 0.',
            '<strong>Constraint:</strong> Minimize. Penalty: Geometric increase if DD > Limit.',
            '<strong>Constraint:</strong> Maximize. Penalty: Small linear penalty if < 1.0.',
            '<strong>Hard Constraint:</strong> <code>-Infinity</code> if < 1 trade/day.<br><strong>Soft Constraint:</strong> Penalty if trades > Target.',
            '<strong>Goal:</strong> Maximize Profit ($).<br>No Floor. Negative PnL allowed to preserve gradient.',
            '<strong>Goal:</strong> High quality trades (> $250/trade).<br>Graduated Penalty if WinRate < 40%.'
        ]
        
        for i, (name, weight, direction, note) in enumerate(zip(weight_names, weights, directions, notes)):
            norm_range = norm_ranges.get(name, 'N/A')
            if isinstance(norm_range, float):
                norm_range_str = f"{norm_range:,.0f}" if norm_range >= 1000 else f"{norm_range:.1f}"
            else:
                norm_range_str = str(norm_range)
            
            weight_str = f"{weight:.1f}"
            if weight == 100.0:
                weight_str = f"<strong style='color: red; font-size: 1.1em;'>{weight:.1f} (!) DIAGNOSTIC</strong>"
            elif abs(weight) > 10:
                weight_str = f"<strong>{weight:.1f}</strong>"
            
            fitness_weights_html += f"<tr><td>{name}</td><td>{weight_str}</td><td>{direction}</td><td>{norm_range_str}</td><td>{note}</td></tr>"
    
    fitness_weights_html += "</tbody></table><p><em>Weights influence selection pressure.</em></p><p><em>Trade scores are normalized.</em></p></div>"
    
    # Generate full HTML with tooltips and auto-refresh
    # Use JavaScript refresh that preserves scroll position instead of meta refresh
    refresh_script = ''
    if not is_final:
        refresh_script = " <script> // Auto-refresh every 30 seconds, preserving scroll position (function() { let scrollPosition = sessionStorage.getItem('ga_dashboard_scroll'); if (scrollPosition) { window.scrollTo(0, parseInt(scrollPosition)); }  // Save scroll position before refresh window.addEventListener('beforeunload', function() { sessionStorage.setItem('ga_dashboard_scroll', window.pageYOffset || document.documentElement.scrollTop); });  // Auto-refresh after 30 seconds setTimeout(function() { sessionStorage.setItem('ga_dashboard_scroll', window.pageYOffset || document.documentElement.scrollTop); location.reload(); }, 30000); })(); </script>"
    
    # Refactored HTML generation to avoid f-string limits
    
    # Restore pre-calculated values for HTML generation - MOVED HERE TO FIX SCOPE
    s_val = is_res.get('sortino', 0) if isinstance(is_res, dict) else 0
    d_val = is_res.get('max_drawdown', 0) if isinstance(is_res, dict) else 0
    pf_val = is_res.get('profit_factor', 0) if isinstance(is_res, dict) else 0
    trades_val = is_res.get('avg_trades_day', 0) if isinstance(is_res, dict) else 0
    tp_val = is_res.get('total_profit', 0) if isinstance(is_res, dict) else 0
    ppt_val = is_res.get('avg_profit_per_trade', 0) if isinstance(is_res, dict) else 0
    
    m_stats = is_res.get('monthly_profit_stats', {}) if isinstance(is_res, dict) else {}
    if not isinstance(m_stats, dict): m_stats = {}
    m_max = m_stats.get('max_monthly_profit', 0)
    m_min = m_stats.get('min_monthly_profit', 0)
    m_avg = m_stats.get('avg_monthly_profit', 0)
    
    html_content = "<!DOCTYPE html>\n"
    html_content += "<html><head><title>GA Dashboard v4.0</title>\n"
    html_content += f"{refresh_script}\n"
    html_content += "<script src='https://cdn.plot.ly/plotly-latest.min.js'></script>\n"
    html_content += "<style> body { font-family: Arial; margin: 0; padding: 0; background: #f5f5f5; padding-top: 60px; } .container { max-width: 1400px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; } h1 { color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; } h2 { color: #555; margin-top: 30px; border-bottom: 2px solid #ddd; position: relative; } h2 .tooltip-icon { display: inline-block; width: 18px; height: 18px; background: #4CAF50; color: white; border-radius: 50%; text-align: center; line-height: 18px; font-size: 12px; margin-left: 8px; cursor: help; vertical-align: middle; } h2 .tooltip { visibility: hidden; width: 300px; background-color: #333; color: #fff; text-align: left; border-radius: 6px; padding: 10px; position: absolute; z-index: 1; bottom: 125%; left: 0; font-size: 12px; line-height: 1.4; box-shadow: 0 2px 8px rgba(0,0,0,0.3); } h2 .tooltip-icon:hover + .tooltip { visibility: visible; } table { width: 100%; border-collapse: collapse; margin: 15px 0; } th { background: #4CAF50; color: white; padding: 10px; text-align: left; position: relative; } th .tooltip-icon { display: inline-block; width: 16px; height: 16px; background: rgba(255,255,255,0.3); color: white; border-radius: 50%; text-align: center; line-height: 16px; font-size: 11px; margin-left: 5px; cursor: help; vertical-align: middle; } th .tooltip { visibility: hidden; width: 280px; background-color: #333; color: #fff; text-align: left; border-radius: 6px; padding: 8px; position: absolute; z-index: 1; bottom: 125%; left: 0; font-size: 11px; line-height: 1.3; box-shadow: 0 2px 8px rgba(0,0,0,0.3); } th .tooltip-icon:hover + .tooltip { visibility: visible; } td { padding: 8px; border: 1px solid #ddd; } tr:nth-child(even) { background: #f9f9f9; } .selected-row { background: #fff3cd !important; font-weight: bold; } .positive { color: green; } .negative { color: red; } .metric-box { display: inline-block; background: #4CAF50; color: white; padding: 10px 20px; margin: 5px; border-radius: 5px; font-weight: bold; position: relative; cursor: help; } .metric-box .tooltip { visibility: hidden; width: 250px; background-color: #333; color: #fff; text-align: left; border-radius: 6px; padding: 8px; position: absolute; z-index: 1; bottom: 125%; left: 50%; transform: translateX(-50%); font-size: 11px; line-height: 1.3; box-shadow: 0 2px 8px rgba(0,0,0,0.3); } .metric-box:hover .tooltip { visibility: visible; } .info-section { background: #e3f2fd; border-left: 4px solid #2196F3; padding: 12px; margin: 15px 0; border-radius: 4px; font-size: 0.9em; line-height: 1.5; } .chart-container { margin: 20px 0; padding: 20px 0; border-top: 1px solid #ddd; border-bottom: 1px solid #ddd; } .chart-container .plotly-graph-div { margin: 20px 0; display: block; min-height: 400px; } .return-button { display: inline-block; margin-bottom: 20px; padding: 10px 20px; background: #667eea; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; } .return-button:hover { background: #5568d3; } </style></head><body>\n"
    html_content += f"{progress_html}\n"
    html_content += "<div class='container'>\n"
    html_content += "<a href='index.html' class='return-button'>&larr; Back to Main Dashboard</a>\n"
    html_content += "<h1>GA Optimization Dashboard - v4.0</h1>\n"
    html_content += f"<p><strong>Generated:</strong> {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}</p>\n"
    html_content += f"<div class='metric-box'>Pareto Solutions: {len(hof)}<span class='tooltip'>Number of non-dominated solutions found.</span></div>\n"
    html_content += f"<div class='metric-box'>Generations: {len(gens)}<span class='tooltip'>Total number of generations completed.</span></div>\n"
    html_content += f"{fitness_weights_html}\n"
    html_content += "<h2>Performance Metrics</h2>\n"
    gen_found_text = f"Generation {best_gen_found}" if best_gen_found is not None else ""
    html_content += f"<div class='info-section'><strong>Generation:</strong> {gen_found_text} | <strong>Values:</strong> {'Actual Backtest' if is_final else 'Normalized Fitness (In-Sample)'}</div>\n"
    
    # Combined Parameter & Analysis Table (Requested by User)
    # REDUNDANT: Removed "Selected Parameters" section as it duplicates data in "Parameter Analysis & Convergence"
    
    # Metrics Summary
    html_content += f"<div class='metric-box'>Sortino: {s_val:.4f}</div>\n"
    html_content += f"<div class='metric-box'>Max DD: {(d_val if d_val < 1000 else float(d_val)):.2f}</div>\n"
    html_content += f"<div class='metric-box'>PF: {pf_val:.4f}</div>\n"
    html_content += f"<div class='metric-box'>Avg Trades/Day: {trades_val:.4f}</div>\n"
    
    # NEW: Parameter Analysis (from analyze_checkpoint logic)
    # Updated to pass best_params for the Chosen Value column
    param_conv_html = generate_convergence_html(pop, param_keys, param_dict, chosen_params=best_params)
    # Merged into main Parameter Analysis section below
        
    html_content += "<h2>Fitness Convergence</h2>\n"
    html_content += f"{conv_div}\n"
    html_content += "<h2>Pareto Front 3D</h2>\n"
    html_content += f"{pareto3d_div}\n"
    html_content += "<h2>Pareto Front 2D</h2>\n"
    html_content += f"{pareto2d_div}\n"
    html_content += "<h2>Pareto Size</h2>\n"
    html_content += f"{paretosize_div}\n"

    # Deep Dive Analysis Links (New for V4 Upgrade)
    html_content += "<h2>Deep Dive Analysis</h2>\n"
    html_content += "<div class='info-section'>\n"
    html_content += "  <p>View detailed parameter analysis reports (generated separately):</p>\n"
    html_content += "  <ul>\n"
    html_content += "    <li><a href='parameter_analysis/parameter_correlation.html' target='_blank'>Correlation Heatmap (Parameters vs Metrics)</a></li>\n"
    html_content += "    <li><a href='parameter_analysis/parameter_importance_TotalPnL.html' target='_blank'>Parameter Importance (Total PnL)</a></li>\n"
    html_content += "    <li><a href='parameter_analysis/parameter_interactions.html' target='_blank'>Parameter Interactions (Scatter Matrix)</a></li>\n"
    html_content += "  </ul>\n"
    html_content += "</div>\n"

    html_content += "<h2>Data Split Information</h2>\n"
    html_content += "<div class='info-section'>Data split into IS and OOS periods.</div>\n"
    
    # Add IS and OOS period dates
    if is_periods is not None and oos_periods is not None:
        periods_html = "<table class='periods-table'><thead><tr> <th>Period Type</th> <th>Period #</th> <th>Start Date</th> <th>End Date</th> <th>Rows</th> </tr></thead><tbody>"
        
        for i, period in enumerate(is_periods, 1):
            periods_html += f"<tr><td>In-Sample</td><td>{i}</td><td>{period.index[0]}</td><td>{period.index[-1]}</td><td>{len(period):,}</td></tr>"
        
        for i, period in enumerate(oos_periods, 1):
            periods_html += f"<tr><td>Out-of-Sample</td><td>{i}</td><td>{period.index[0]}</td><td>{period.index[-1]}</td><td>{len(period):,}</td></tr>"
        
        periods_html += "</tbody></table>"
        html_content += periods_html
        
    # Add individual OOS period statistics if we have best_params
    if best_params and oos_periods and len(oos_periods) > 0:
            html_content += ' <h2>Individual OOS Period Statistics<span class="tooltip-icon">?</span> <span class="tooltip">Performance statistics for each individual Out-of-Sample period. This helps identify if the strategy performs consistently across different time periods or if it\'s overfitted to specific market conditions.</span> </h2> <div class="info-section"> <strong>Period-by-Period Analysis:</strong> If performance varies significantly across OOS periods, the strategy may be overfitted to the training data. Consistent performance across periods is a good sign of robustness. </div> '
            
            oos_period_stats_html = "<table class='oos-periods-table'><thead><tr> <th>Period #</th> <th>Date Range</th> <th>Total PNL</th> <th>Trades</th> <th>Win Rate</th> <th>Profit Factor</th> <th>Sortino</th> <th>Max DD</th> <th>Avg Trades/Day</th> <th>Avg Profit/Trade</th> </tr></thead><tbody>"
            
            for i, oos_period in enumerate(oos_periods, 1):
                try:
                    # Run backtest on this individual OOS period
                    period_res = run_backtest(best_params, oos_period, param_dict, suppress_output=True)
                    period_trades = period_res.pop('trades_df')
                    
                    if not period_trades.empty:
                        total_pnl = period_trades['pnl'].sum()
                        num_trades = len(period_trades)
                        win_rate = (period_trades['pnl'] > 0).mean() * 100
                        avg_win = period_trades[period_trades['pnl'] > 0]['pnl'].mean() if (period_trades['pnl'] > 0).any() else 0
                        avg_loss = period_trades[period_trades['pnl'] < 0]['pnl'].mean() if (period_trades['pnl'] < 0).any() else 0
                        pf = abs(avg_win / avg_loss) if avg_loss != 0 else np.inf
                        sortino = period_res.get('sortino', 0)
                        max_dd = period_res.get('max_drawdown', 0)
                        # Use avg_trades_day from period_res (already calculated correctly using full data period)
                        avg_trades_day = period_res.get('avg_trades_day', 0)
                        # Fallback calculation if not in period_res (shouldn't happen, but safety check)
                        if avg_trades_day == 0 and num_trades > 0:
                            period_start = oos_period.index.min()
                            period_end = oos_period.index.max()
                            days = (period_end - period_start).days or 1
                            avg_trades_day = num_trades / days if days > 0 else 0
                        
                        # Calculate Avg Profit/Trade
                        avg_profit_trade = total_pnl / num_trades if num_trades > 0 else 0

                        oos_period_stats_html += f"<tr> <td>{i}</td> <td>{oos_period.index[0].strftime('%Y-%m-%d')} to {oos_period.index[-1].strftime('%Y-%m-%d')}</td> <td class=\"{'positive' if total_pnl > 0 else 'negative'}\">${total_pnl:,.2f}</td> <td>{num_trades}</td> <td>{win_rate:.1f}%</td> <td>{pf:.2f}</td> <td>{sortino:.2f}</td> <td>${max_dd:,.2f}</td> <td>{avg_trades_day:.2f}</td> <td class=\"{'positive' if avg_profit_trade > 0 else 'negative'}\">${avg_profit_trade:,.2f}</td> </tr>"
                    else:
                        oos_period_stats_html += f"<tr> <td>{i}</td> <td>{oos_period.index[0].strftime('%Y-%m-%d')} to {oos_period.index[-1].strftime('%Y-%m-%d')}</td> <td colspan=\"7\" style=\"text-align: center; color: #999;\">No trades</td> </tr>"
                except Exception as e:
                    oos_period_stats_html += f"<tr> <td>{i}</td> <td>{oos_period.index[0].strftime('%Y-%m-%d')} to {oos_period.index[-1].strftime('%Y-%m-%d')}</td> <td colspan=\"7\" style=\"text-align: center; color: #f00;\">Error: {str(e)}</td> </tr>"
            
            oos_period_stats_html += "</tbody></table>"
            html_content += oos_period_stats_html
    
    html_content += ' <h2>In-Sample vs OOS Comparison<span class="tooltip-icon">?</span> <span class="tooltip">Comparison of strategy performance between in-sample (training) and out-of-sample (validation) data. This is critical for detecting overfitting. Good generalization: IS and OOS metrics are similar. Overfitting: IS is much better than OOS. Green differences indicate OOS is better (good sign), red indicates OOS is worse (potential overfitting).</span> </h2> <div class="info-section"> <strong>Overfitting Detection:</strong> If OOS performance is significantly worse than IS, the strategy may be overfitted to the training data. Look for: (1) Sortino dropping >50% in OOS, (2) Drawdown increasing >100% in OOS, (3) Trade frequency dropping dramatically. Small differences (<20%) are normal and acceptable. </div> '
    html_content += comparison_html
    html_content += summary_html
    # All Solutions Table moved to bottom
    pass
    html_content += ' </div> <h2>Parameter Analysis & Convergence<span class="tooltip-icon">?</span> <span class="tooltip">Analysis of how strategy parameters affect performance metrics. Includes both Convergence Stability (consensus) and Correlation Analysis (impact).</span> </h2> <div class="info-section"> <strong>Understanding Parameter Analysis:</strong> <ul> <li><strong>Convergence Analysis:</strong> Shows which parameters the GA has "agreed" on (Low Variance) vs. which are still debated (High Variance). Converged parameters are likely critical "Structural Edges".</li> <li><strong>Correlation Heatmap:</strong> Shows how each parameter correlates with each metric. Positive (blue) = parameter increases with metric, Negative (red) = parameter decreases with metric.</li> <li><strong>Parameter Importance:</strong> Combines correlation, top-bottom difference, range utilization, and variability to identify the most important parameters.</li> <li><strong>Parameter Distributions (Top vs Bottom):</strong> Compares parameter values in top 25% vs bottom 25% solutions. Shows which parameters distinguish good from bad solutions.</li> <li><strong>Parameter Interactions:</strong> 2D scatter plots showing how top parameters interact. Color = Sortino (darker = better). Helps identify parameter combinations that work together.</li> <li><strong>Parameter Distribution Histograms:</strong> Shows distribution of all parameter values with valid ranges marked. <strong style="color: red;">Red bars = values OUTSIDE valid range</strong>, Blue bars = values within range. Green/Red dashed lines = min/max boundaries. Use this to detect parameter clamping issues!</li> <li><strong>Focus on High-Importance Parameters:</strong> These are the parameters that most distinguish good solutions from bad ones.</li> </ul> <strong>Note:</strong> GA meta-parameters (POP_SIZE, NUM_GEN, etc.) are excluded from this analysis as they control the optimization algorithm, not the trading strategy. </div> <div class="chart-container"> '
    if param_conv_html:
        html_content += f"<h3>Convergence Analysis</h3>{param_conv_html}<hr>"
    html_content += "<h3>Correlation & Importance Analysis</h3>"
    html_content += param_analysis_html
    html_content += ' </div> '
    html_content += conv_script + ' ' + pareto3d_script + ' ' + pareto2d_script + ' ' + paretosize_script + ' ' + param_analysis_scripts
    
    # All Solutions Table (Moved to bottom)
    html_content += ' <h2>All Solutions<span class="tooltip-icon">?</span> <span class="tooltip">Complete list of all Pareto-optimal solutions ranked by Sortino Ratio.</span> </h2> <div class="info-section"> '
    if showing_actual:
        html_content += '<strong> This table shows ACTUAL BACKTEST RESULTS from fresh backtests of each solution.</strong>'
    else:
        html_content += '<strong>(!) IMPORTANT: This table shows NORMALIZED FITNESS VALUES, not actual backtest results!</strong>'
    html_content += '</div>'
    html_content += pareto_table_html
    
    html_content += ' </body></html>'
    
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    # Auto-launch only if requested (first update or final update)
    if auto_launch:
        try:
            # Try to use web server URL if available, otherwise use file://
            # Check if web server is running by trying to access it
            import urllib.request
            import urllib.error
            web_url = None
            try:
                # Try to connect to local web server
                response = urllib.request.urlopen('http://127.0.0.1:8000/', timeout=1)
                # If successful, use web server URL
                html_filename = os.path.basename(html_path)
                web_url = f'http://127.0.0.1:8000/{html_filename}'
            except (urllib.error.URLError, OSError, Exception):
                # Web server not available, use file://
                web_url = f'file://{os.path.abspath(html_path)}'
            
            webbrowser.open(web_url)
        except:
            pass

# ----------------------------------------------------------------------
# Checkpoint Functions
# ----------------------------------------------------------------------
def save_checkpoint(pop, hof, logbook, gen, config):
    " Save GA state to checkpoint file.  Args: pop: Current population hof: Hall of Fame logbook: Logbook with statistics gen: Current generation number config: Configuration dictionary (for verification) "
    checkpoint = {
        'population': pop,
        'hall_of_fame': hof,
        'logbook': logbook,
        'generation': gen,
        'config': config,
        'random_state': random.getstate(),
        'numpy_random_state': np.random.get_state()
    }
    with open(CHECKPOINT_FILE, 'wb') as f:
        pickle.dump(checkpoint, f)
    print(f"Checkpoint saved: Generation {gen}  {CHECKPOINT_FILE}")

def load_checkpoint():
    " Load GA state from checkpoint file if it exists.  Returns: tuple: (pop, hof, logbook, start_gen, config) or None if no checkpoint "
    if not os.path.exists(CHECKPOINT_FILE):
        return None
    
    try:
        with open(CHECKPOINT_FILE, 'rb') as f:
            checkpoint = pickle.load(f)
        
        # Validate checkpoint format - check if fitness is multi-objective (v3) or scalar (v2)
        pop = checkpoint['population']
        if pop and len(pop) > 0:
            # Check first individual's fitness format
            first_ind = pop[0]
            if hasattr(first_ind, 'fitness') and first_ind.fitness.valid:
                fitness_len = len(first_ind.fitness.values)
                if fitness_len == 4:
                    # Old checkpoint with 4 objectives (before total profit was added)
                    print(f"\n=== CHECKPOINT INCOMPATIBLE (OLD 4-OBJECTIVE VERSION) ===")
                    print(f"Checkpoint contains individuals with 4 fitness values.")
                    print(f"v3 now requires 5 fitness values (added total_profit as 5th objective).")
                    print(f"Starting fresh run...")
                    print("=" * 50)
                    return None
                elif fitness_len != 6:
                    print(f"\n=== CHECKPOINT INCOMPATIBLE ===")
                    print(f"Checkpoint contains individuals with {fitness_len} fitness values.")
                    print(f"v4 requires 6 fitness values (added Avg Profit/Trade).")
                    print(f"This checkpoint appears to be from an older version.")
                    print(f"Starting fresh run...")
                    print("=" * 50)
                    return None
                
                # Check if fitness values are normalized (new fitness function) or not (old)
                # New fitness function uses normalized values (0-1 range)
                # Old fitness function had Sortino values > 1.0
                fitness_vals = first_ind.fitness.values
                if fitness_len >= 1 and fitness_vals[0] > 1.0:
                    # Sortino > 1.0 indicates old (non-normalized) fitness function
                    print(f"\n=== CHECKPOINT INCOMPATIBLE ===")
                    print(f"Checkpoint contains non-normalized fitness values (Sortino = {fitness_vals[0]:.2f}).")
                    print(f"New fitness function uses normalized values (0-1 range).")
                    print(f"This checkpoint is from before the fitness function update.")
                    print(f"Starting fresh run...")
                    print("=" * 50)
                    return None
        
        # Restore random states
        random.setstate(checkpoint['random_state'])
        np.random.set_state(checkpoint['numpy_random_state'])
        
        print(f"\n=== CHECKPOINT FOUND ===")
        print(f"Resuming from Generation {checkpoint['generation']}")
        print(f"Checkpoint file: {CHECKPOINT_FILE}")
        print("=" * 50)
        
        return (
            checkpoint['population'],
            checkpoint['hall_of_fame'],
            checkpoint['logbook'],
            checkpoint['generation'] + 1,  # Start from next generation
            checkpoint['config']
        )
    except Exception as e:
        print(f"Error loading checkpoint: {e}")
        print("Starting fresh run...")
        return None

def verify_config_compatibility(saved_config, current_config):
    # Verify that saved checkpoint config matches current config
    # Note: NUM_GEN is excluded from critical check to allow extending runs
    critical_params = ['POP_SIZE', 'CX_PB', 'MUT_PB', 'DATA_SPLITS', 'DATA_SIZE']
    for param in critical_params:
        if saved_config.get(param) != current_config.get(param):
            print(f"WARNING: Config mismatch for {param}")
            print(f"  Saved: {saved_config.get(param)}")
            print(f"  Current: {current_config.get(param)}")
            return False
    
    # Warn but allow NUM_GEN change
    if saved_config.get('NUM_GEN') != current_config.get('NUM_GEN'):
        print(f"NOTICE: Generation count changed from {saved_config.get('NUM_GEN')} to {current_config.get('NUM_GEN')}. Resuming extended run.")
        
    return True

# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
def main():
    global POP_SIZE, NUM_GEN, CX_PB, MUT_PB, MUT_MU, MUT_SIGMA
    
    # CRITICAL: Ensure FitnessMulti class has correct weights (5) before starting
    # This fixes issues where the class might have been created with old 4-weight definition
    if hasattr(creator, 'FitnessMulti'):
        if len(creator.FitnessMulti.weights) != 6:
            print(f"WARNING: FitnessMulti has {len(creator.FitnessMulti.weights)} weights, expected 6. Recreating...")
            del creator.FitnessMulti
            if hasattr(creator, "Individual"):
                del creator.Individual
            creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 1.0, 2.0, 2.0))
            creator.create("Individual", list, fitness=creator.FitnessMulti)
            print(f"FitnessMulti recreated with weights: {creator.FitnessMulti.weights}")
    else:
        # Create if it doesn't exist
        creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 1.0, 2.0, 2.0))
        if not hasattr(creator, "Individual"):
            creator.create("Individual", list, fitness=creator.FitnessMulti)
    global TARGET_TRADES_DAY, TRADES_PENALTY_WEIGHT, DD_WEIGHT
    global DATA_SPLITS, DATA_SIZE, MIN_TRADES_DAY, MIN_TRADES_PEN_WEIGHT
    global PARAM_RANGES, param_keys, param_dict, param_df
    
    print("# Genetic Optimization for Bollinger Band Strategy - Version 3.0")
    print("# Multi-core parallelization | Multi-objective (NSGA-II) | Sortino Ratio")
    print("# Checkpoint/Resume enabled - saves after each generation")
    print("# Use --fresh or -f flag to force a fresh start (ignores checkpoint)")
    
    # Load Parameters (only in main process, not in workers)
    param_dict, param_df = load_params(PARAM_CSV, return_dataframe=True)

    # Inject strategy name from CLI args
    param_dict['strategy_name'] = args.strategy
    print(f"Goal: Optimize Strategy '{args.strategy}'")
    
    # Print the exact parameter file that will be used (grouped)
    print("\n=== PARAMETER FILE USED (grouped by category) ===")
    
    def group_and_print_params(param_df_local):
        "Group and print parameters by category."
        groups = {
            'Entry Criteria': ['Enable Long Trades', 'Enable Short Trades', 'Bollinger Band Length', 
                              'Bollinger Band StdDev', 'Long Entry on Wick Touch', 'Long Entry on Body in Zone',
                              'Long Trigger (% From Lower Band)', 'Short Entry on Wick Touch', 
                              'Short Entry on Body in Zone', 'Short Trigger (% From Upper Band)',
                               'ATR Length for Filter', 'Max ATR Filter (Points)', 'Min ATR Filter (Points)', 
                               'Enable ADX Filter', 'ADX Period', 'Max ADX Threshold',
                               'RTH Start (HH:MM)', 'RTH End (HH:MM)',
                              'Enable RTH Filter', 'Volume MA Length', 'Max Volume Multiplier', 'Timeframe (minutes)',
                              'Max Open Trades'],
            'Take Profit Criteria': ['TP Method', 'Opposite Bollinger Band TP', 'Fixed ATR TP', 'Fixed BB at Entry TP',
                                    'ATR Length for TP', 'ATR Multiplier for TP'],
            'Stop Loss Criteria': ['Initial Stop Loss (%)', 'Enable Trailing Stop', 
                                  'ATR Length for Trailing Stop', 'ATR Multiplier for Trailing Stop',
                                  'Trailing Delay (bars)'],
            'GA Criteria': ['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                           'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                           'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                           'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT']
        }
        
        # Filter out section headers
        param_df_filtered = param_df_local[~param_df_local['Name'].str.startswith('===').fillna(False)]
        
        for group_name, param_list in groups.items():
            group_df = param_df_filtered[param_df_filtered['Name'].isin(param_list)]
            if not group_df.empty:
                print(f"\n--- {group_name} ---")
                print(group_df[['Name', 'Value', 'Min', 'Max', 'Type']].to_string(index=False))
        
        # Print any remaining parameters not in groups
        all_grouped = []
        for param_list in groups.values():
            all_grouped.extend(param_list)
        remaining = param_df_filtered[~param_df_filtered['Name'].isin(all_grouped + ['__indicatorName'])]
        if not remaining.empty:
            print(f"\n--- Other Parameters ---")
            print(remaining[['Name', 'Value', 'Min', 'Max', 'Type']].to_string(index=False))
    
    group_and_print_params(param_df)
    print("\n========================================\n")
    
    # Set GA configuration from parameters
    POP_SIZE = param_dict.get('POP_SIZE', {'value': 20})['value']
    if args.pop:
        POP_SIZE = args.pop
        print(f"Override: POP_SIZE set to {POP_SIZE}")

    NUM_GEN = param_dict.get('NUM_GEN', {'value': 10})['value']
    if args.gen:
        NUM_GEN = args.gen
        print(f"Override: NUM_GEN set to {NUM_GEN}")
    CX_PB = param_dict.get('CX_PB', {'value': 0.7})['value']
    MUT_PB = param_dict.get('MUT_PB', {'value': 0.2})['value']
    MUT_MU = param_dict.get('MUT_MU', {'value': 0.0})['value']
    MUT_SIGMA = param_dict.get('MUT_SIGMA', {'value': 0.1})['value']
    TARGET_TRADES_DAY = param_dict.get('TARGET_TRADES_DAY', {'value': 2})['value']
    TRADES_PENALTY_WEIGHT = param_dict.get('TRADES_PENALTY_WEIGHT', {'value': 0.5})['value']
    DD_WEIGHT = param_dict.get('DD_WEIGHT', {'value': 0.3})['value']
    DATA_SPLITS = param_dict.get('DATA_SPLITS', {'value': 0.7})['value']
    DATA_SIZE = param_dict.get('DATA_SIZE', {'value': 100000})['value']
    USE_INTERLEAVED = param_dict.get('USE_INTERLEAVED_SPLIT', {'value': True})['value'] if 'USE_INTERLEAVED_SPLIT' in param_dict else True
    NUM_PERIODS = param_dict.get('NUM_SPLIT_PERIODS', {'value': 5})['value'] if 'NUM_SPLIT_PERIODS' in param_dict else 5
    MIN_TRADES_DAY = param_dict.get('MIN_TRADES_DAY', {'value': 1.0})['value']
    MIN_TRADES_PEN_WEIGHT = param_dict.get('MIN_TRADES_PEN_WEIGHT', {'value': -100.0})['value']
    
    # Set numeric ranges for the GA
    # Include int/float parameters, but exclude:
    # 1. GA Criteria parameters (configuration, not optimization)
    # 2. Parameters where min==max (effectively fixed values)
    ga_criteria_params = set(['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                              'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                              'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                              'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT',
                              'NORM_SORTINO_MAX', 'NORM_DD_MAX', 'NORM_PF_MAX', 'NORM_TRADES_MAX', 
                              'NORM_PNL_MAX', 'NORM_PROFIT_TRADE_MAX', 'MIN_WIN_RATE', 'SORTINO_CAP'])
    
    global PARAM_RANGES, param_keys
    PARAM_RANGES = {}
    for n, d in param_dict.items():
        if not isinstance(d, dict):
            continue
        if n.startswith('===') or n.startswith('__'):
            continue
        if n in ga_criteria_params:
            continue
        ptype = d.get('type', '')
        pmin = d.get('min')
        pmax = d.get('max')
        # Include int/float parameters with valid min/max
        # Include int/float parameters with valid min/max
        if ptype in ('int', 'float') and pmin is not None and pmax is not None:
             # Exclude if min==max (effectively fixed)
            if pmin != pmax:
                PARAM_RANGES[n] = (pmin, pmax)
    
    param_keys = list(PARAM_RANGES.keys())

    # Set NUM_WORKERS based on CPU count OR CLI argument
    global NUM_WORKERS
    max_cores = multiprocessing.cpu_count()
    
    if args.cores > max_cores:
        print(f"WARNING: Requested {args.cores} cores, but only {max_cores} available. Using {max_cores}.")
        NUM_WORKERS = max_cores
    elif args.cores < 1:
        print(f"WARNING: Requested {args.cores} cores. Using 1.")
        NUM_WORKERS = 1
    else:
        NUM_WORKERS = args.cores
        
    print(f"Multi-core: Using {NUM_WORKERS} workers (CPU count: {max_cores})")
    
    # Save current configuration
    current_config = {
        'POP_SIZE': POP_SIZE,
        'NUM_GEN': NUM_GEN,
        'CX_PB': CX_PB,
        'MUT_PB': MUT_PB,
        'DATA_SPLITS': DATA_SPLITS,
        'DATA_SIZE': DATA_SIZE,
        'PARAM_CSV': PARAM_CSV,
        'NUM_WORKERS': NUM_WORKERS
    }
    
    DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'
    df = pd.read_csv(DATA_CSV, header=None,
                     names=['datetime', 'open', 'high', 'low', 'close', 'volume'],
                     parse_dates=['datetime'], index_col='datetime')
    if DATA_SIZE > 0:
        df = df.tail(DATA_SIZE)
    
    # Check if we should use interleaved periods or simple split
    # USE_INTERLEAVED and NUM_PERIODS are already loaded above
    if USE_INTERLEAVED and NUM_PERIODS > 1:
        # Interleaved approach: Split into alternating IS/OOS periods
        # Example with 5 periods: IS-OOS-IS-OOS-IS (3 IS, 2 OOS)
        # This ensures the strategy is tested across different market conditions
        print(f"\n=== Using Interleaved Data Split ===")
        print(f"Number of periods: {NUM_PERIODS}")
        print(f"Pattern: Alternating IS-OOS-IS-OOS...")
        
        # Ensure data is sorted by index (chronological order)
        df = df.sort_index()
        
        period_size = len(df) // NUM_PERIODS
        is_periods = []
        oos_periods = []
        
        for i in range(NUM_PERIODS):
            start_idx = i * period_size
            end_idx = (i + 1) * period_size if i < NUM_PERIODS - 1 else len(df)
            period = df.iloc[start_idx:end_idx].copy()
            
            # Alternate: even indices (0, 2, 4...) are IS, odd (1, 3, 5...) are OOS
            if i % 2 == 0:
                is_periods.append(period)
                print(f"  Period {i+1}: IS ({len(period):,} rows, {period.index[0]} to {period.index[-1]})")
            else:
                oos_periods.append(period)
                print(f"  Period {i+1}: OOS ({len(period):,} rows, {period.index[0]} to {period.index[-1]})")
        
        # Combine all IS periods and all OOS periods (will maintain chronological order)
        in_sample = pd.concat(is_periods).sort_index() if is_periods else pd.DataFrame()
        oos = pd.concat(oos_periods).sort_index() if oos_periods else pd.DataFrame()
        
        print(f"\nCombined IS: {len(in_sample):,} rows ({len(in_sample)/len(df)*100:.1f}%)")
        if len(in_sample) > 0:
            print(f"  Date range: {in_sample.index[0]} to {in_sample.index[-1]}")
        else:
            print("  WARNING: Combined IS data is empty!")
        print(f"Combined OOS: {len(oos):,} rows ({len(oos)/len(df)*100:.1f}%)")
        if len(oos) > 0:
            print(f"  Date range: {oos.index[0]} to {oos.index[-1]}")
        else:
            print("  WARNING: Combined OOS data is empty!")
            print("  This may indicate an issue with the interleaved split configuration.")
            print(f"  Number of OOS periods: {len(oos_periods)}")
        print("=" * 50)
    else:
        # Simple chronological split (original approach)
        split = int(len(df) * DATA_SPLITS)
        in_sample, oos = df.iloc[:split], df.iloc[split:]
        print(f"\n=== Using Simple Chronological Split ===")
        print(f"IS: {len(in_sample)} rows ({len(in_sample)/len(df)*100:.1f}%)")
        print(f"OOS: {len(oos)} rows ({len(oos)/len(df)*100:.1f}%)")
        print("=" * 50)
    
    # Check for --fresh flag to force fresh start
    force_fresh = ('--fresh' in sys.argv or '-f' in sys.argv) and not args.dashboard_from
    
    # DASHBOARD ONLY MODE (FROM JSON)
    if args.visualize_json:
        if not os.path.exists(args.visualize_json):
            print(f"ERROR: JSON file not found: {args.visualize_json}")
            return
            
        print(f"!!! VISUALIZATION MODE: Using parameters from {args.visualize_json} !!!")
        import json
        with open(args.visualize_json, 'r') as f:
            params_loaded = json.load(f)
            
        # Convert params to individual
        # We need the param_keys order from standard logic
        
        # RELOAD PARAMETERS to ensure we have the latest configuration from the CSV
        # This fixes the issue where the dashboard configuration table doesn't update
        print(f"Reloading parameters from {PARAM_CSV} to ensure latest configuration...")
        param_dict, _ = load_params(PARAM_CSV, return_dataframe=True)
        
        # Filter for optimized keys and create individual values
        ind_values = []
        for k in param_keys:
             if k in params_loaded:
                 ind_values.append(params_loaded[k])
             else:
                 # Fallback: use min value from param_dict if key is missing in JSON
                 # This should ideally not happen if JSON is well-formed from a previous run
                 print(f"WARNING: Parameter '{k}' not found in JSON. Using min value from param_dict.")
                 ind_values.append(param_dict[k]['min'])
                 
        # Create Dummy Individual
        best_ind = creator.Individual(ind_values)
        # Assign a dummy fitness with 6 values (matching FitnessMulti weights)
        best_ind.fitness.values = (1.0, 1.0, 1.0, 1.0, 1.0, 1.0) 
        
        # Run backtests to get actual metrics for the dashboard
        print("Running backtests for the specified solution...")
        is_res = run_backtest(params_loaded, in_sample, param_dict, suppress_output=False)
        oos_res = run_backtest(params_loaded, oos, param_dict, suppress_output=False)
        
        trades_is = is_res.pop('trades_df')
        trades_oos = oos_res.pop('trades_df')
        
        # Create dummy logbook and hof for dashboard generation
        logbook = tools.Logbook()
        logbook.header = "gen", "evals", "avg_sortino", "avg_dd", "avg_pf", "pareto_size", "avg_trades_day", "max_trades_day", "avg_total_profit", "avg_profit_per_trade", "actual_dd_best", "actual_sortino_best", "actual_pf_best", "actual_pnl_best"
        logbook.record(gen=0, evals=1, avg_sortino=is_res['sortino'], avg_dd=is_res['max_drawdown'], avg_pf=is_res['profit_factor'],
                       pareto_size=1, avg_trades_day=is_res['avg_trades_day'], max_trades_day=is_res['avg_trades_day'],
                       avg_total_profit=is_res['total_profit'], avg_profit_per_trade=is_res.get('avg_profit_per_trade', 0),
                       actual_dd_best=is_res['max_drawdown'], actual_sortino_best=is_res['sortino'],
                       actual_pf_best=is_res['profit_factor'], actual_pnl_best=is_res['total_profit'])
        
        hof = tools.ParetoFront()
        hof.update([best_ind]) # Add the single best individual to hof
        
        # Generate dashboard
        dashboard_html_path = os.path.join(HTML_DIR, 'ga_dashboard_json_solution.html')
        generate_html_dashboard(
            hof=hof,
            best=best_ind,
            best_params=params_loaded, # Use the loaded params directly
            best_fitness=best_ind.fitness.values,
            param_keys=param_keys,
            param_dict=param_dict,
            logbook=logbook,
            is_res=is_res,
            oos_res=oos_res,
            trades_is=trades_is,
            trades_oos=trades_oos,
            html_path=dashboard_html_path,
            diag_dir=DIAG_DIR,
            current_gen=0,
            total_gen=0,
            is_final=True, # Treat as final for full dashboard features
            auto_launch=True,
            is_periods=is_periods,
            oos_periods=oos_periods,
            in_sample=in_sample,
            best_gen_found=0,
            pop=[best_ind] # Pass the single individual as population for convergence analysis
        )
        print(f"Dashboard generated: {dashboard_html_path}")
        return

    # DASHBOARD ONLY MODE (FROM CHECKPOINT)
    if args.dashboard_from:
         print(f"\n=== DASHBOARD GENERATION MODE ===")
         print(f"Loading checkpoint: {args.dashboard_from}")
         checkpoint_data = load_checkpoint()
         if checkpoint_data is None:
             print("ERROR: Could not load specified checkpoint. Exiting.")
             return
    elif force_fresh:
        print("\n=== FORCING FRESH START (--fresh flag) ===")
        if os.path.exists(CHECKPOINT_FILE):
            # Backup old checkpoint instead of deleting
            backup_file = CHECKPOINT_FILE.replace('.pkl', '_backup.pkl')
            try:
                import shutil
                shutil.move(CHECKPOINT_FILE, backup_file)
                print(f"Old checkpoint backed up to: {backup_file}")
            except Exception as e:
                print(f"Warning: Could not backup checkpoint: {e}")
        checkpoint_data = None
    else:
        # Try to load checkpoint
        checkpoint_data = load_checkpoint()
    
    if checkpoint_data is not None:
        pop, hof, logbook, start_gen, saved_config = checkpoint_data
        
        # CRITICAL FIX: Clamp all individuals in loaded population to valid parameter ranges
        # Checkpoint may contain individuals with values outside valid ranges
        for ind in pop:
            clamp_individual(ind)
        # Also clamp Hall of Fame individuals
        for ind in hof:
            clamp_individual(ind)
        
        # Validate all individuals in loaded population have correct fitness format
        invalid_individuals = []
        for i, ind in enumerate(pop):
            if not hasattr(ind, 'fitness') or not ind.fitness.valid:
                invalid_individuals.append(i)
            elif len(ind.fitness.values) == 4:
                # Old checkpoint with 4 objectives (before total profit was added)
                invalid_individuals.append(i)
            elif len(ind.fitness.values) == 5:
                 # Checkpoint with 5 objectives (before avg profit/trade added) - could potentially migrate, but for now flag as incompatible if strict
                 # Or just allow it? Let's strictly enforce 6 for consistency with current code
                 invalid_individuals.append(i)
            elif len(ind.fitness.values) != 6:
                invalid_individuals.append(i)
        
        if invalid_individuals:
            print(f"\n=== CHECKPOINT INCOMPATIBLE ===")
            print(f"Found {len(invalid_individuals)} individuals with invalid fitness format.")
            print(f"Current version requires 6 fitness values (multi-objective: sortino, max_dd, pf, avg_trades_day, total_profit, avg_profit_trade).")
            print(f"This checkpoint appears to be from an older version.")
            print(f"Starting fresh run...")
            print("=" * 50)
            # Start fresh
            pop = toolbox.population(n=POP_SIZE)
            # CRITICAL FIX: Clamp initial population to ensure all values are within valid ranges
            for ind in pop:
                clamp_individual(ind)
            hof = tools.ParetoFront()  # Store Pareto-optimal solutions
            logbook = tools.Logbook()
            logbook.header = "gen", "evals", "avg_sortino", "avg_dd", "avg_pf", "pareto_size", "avg_trades_day", "max_trades_day", "avg_total_profit", "actual_dd_best", "actual_sortino_best", "actual_pf_best", "actual_pnl_best"
            start_gen = 0
        elif not verify_config_compatibility(saved_config, current_config):
            print("\nWARNING: Config mismatch detected!")
            print("Continuing with saved checkpoint despite config mismatch...")
            print("(Delete checkpoint file to start fresh if needed)")
    else:
        # Start fresh
        pop = toolbox.population(n=POP_SIZE)
        # CRITICAL FIX: Clamp initial population to ensure all values are within valid ranges
        for ind in pop:
            clamp_individual(ind)
        hof = tools.ParetoFront()  # Store Pareto-optimal solutions
        logbook = tools.Logbook()
        logbook.header = "gen", "evals", "avg_sortino", "avg_dd", "avg_pf", "pareto_size", "avg_trades_day", "max_trades_day", "avg_total_profit", "avg_profit_per_trade", "actual_dd_best", "actual_sortino_best", "actual_pf_best", "actual_pnl_best"
        start_gen = 0
        print("\nStarting fresh run...")
    
    # Statistics for multi-objective
    stats = tools.Statistics(lambda ind: ind.fitness.values)
    stats.register("avg_sortino", lambda x: np.mean([f[0] for f in x]))
    stats.register("avg_dd", lambda x: np.mean([f[1] for f in x]))  # Normalized drawdown (0-1, inverted)
    stats.register("avg_pf", lambda x: np.mean([f[2] for f in x]))
    stats.register("avg_trades_day", lambda x: np.mean([f[3] for f in x]))  # 4th objective
    stats.register("avg_total_profit", lambda x: np.mean([f[4] for f in x if len(f) > 4]))  # 5th objective
    stats.register("avg_profit_per_trade", lambda x: np.mean([f[5] for f in x if len(f) > 5]))  # 6th objective
    stats.register("min_dd", lambda x: np.min([f[1] for f in x]))  # Normalized drawdown (0-1, inverted)
    # Note: Normalized drawdown is inverted: 0.0 = worst ($100K), 1.0 = best ($0)
    # We'll track actual drawdown separately by re-running backtests for the best individual
    stats.register("max_sortino", lambda x: np.max([f[0] for f in x]))
    stats.register("max_pf", lambda x: np.max([f[2] for f in x]))
    stats.register("max_trades_day", lambda x: np.max([f[3] for f in x]))  # Max avg trades/day
    
    if start_gen == 0:
        print(logbook.header)
    
    print(f"\nConfiguration:")
    print(f"  NUM_GEN: {NUM_GEN}")
    print(f"  POP_SIZE: {POP_SIZE}")
    print(f"  NUM_WORKERS: {NUM_WORKERS}")
    print(f"  Starting from generation: {start_gen}")
    print(f"  Will run generations: {list(range(start_gen, NUM_GEN))}")
    print()
    
    # Record start time (only if starting fresh or resuming from checkpoint)
    # This allows time tracking across runs
    if start_gen == 0 or not os.path.exists(START_TIME_FILE):
        start_time = time.time()
        with open(START_TIME_FILE, 'w') as f:
            f.write(str(start_time))
        print(f"Start time recorded: {datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        # If resuming, try to keep original start time, or update if file is missing
        try:
            with open(START_TIME_FILE, 'r') as f:
                start_time = float(f.read().strip())
            print(f"Resuming from previous run. Original start: {datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')}")
        except:
            start_time = time.time()
            with open(START_TIME_FILE, 'w') as f:
                f.write(str(start_time))
            print(f"Start time recorded: {datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Create persistent pool for all generations (more efficient than creating/destroying each time)
    print(f"  Creating worker pool with {NUM_WORKERS} workers (Shared Memory Mode)...")
    # Initialize workers with global data (in_sample dataframe) so we don't pickle it every task
    persistent_pool = multiprocessing.Pool(processes=NUM_WORKERS, 
                                          initializer=init_worker, 
                                          initargs=(in_sample, param_dict, param_keys))
    
    # Main evolution loop with NSGA-II
    # If in dashboard mode, skip loop by setting NUM_GEN = start_gen
    if args.dashboard_from:
        print("Skipping evolution loop (Dashboard Mode)...")
        NUM_GEN = start_gen

    try:
        for gen in range(start_gen, NUM_GEN):
            # Check interrupt flag at start of each generation
            if interrupt_flag.is_set():
                raise KeyboardInterrupt("Interrupt requested")
            
            print(f"Generation {gen} starting...")
            print(f"  (Press Ctrl+C to interrupt - will save checkpoint after current generation)")
            
            # Create offspring using variation operators
            offspring = algorithms.varAnd(pop, toolbox, CX_PB, MUT_PB)
            
            # CRITICAL FIX: Clamp all offspring to valid parameter ranges
            # Crossover (cxBlend) can create values outside valid ranges, so we must clamp
            for ind in offspring:
                clamp_individual(ind)
            
            # CRITICAL FIX: Ensure all offspring have fitness objects with correct weights (5)
            # Offspring created by varAnd inherit parent fitness objects which may have old 4-weight fitness
            # Also ensure FitnessMulti class itself has correct weights
            # Verify FitnessMulti class has correct weights
            if not hasattr(creator, 'FitnessMulti'):
                creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 1.0, 2.0, 2.0))
            elif len(creator.FitnessMulti.weights) != 6:
                print(f"  WARNING: FitnessMulti class has {len(creator.FitnessMulti.weights)} weights, recreating with 6...")
                del creator.FitnessMulti
                creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 1.0, 2.0, 2.0))
                # Also recreate Individual class to use new FitnessMulti
                if hasattr(creator, "Individual"):
                    del creator.Individual
                creator.create("Individual", list, fitness=creator.FitnessMulti)
                print(f"  FitnessMulti recreated with weights: {creator.FitnessMulti.weights}")
            
            for ind in offspring:
                if hasattr(ind, 'fitness') and hasattr(ind.fitness, 'weights'):
                    if len(ind.fitness.weights) != 5:
                        # Recreate fitness object with correct weights (class should now have 6)
                        ind.fitness = creator.FitnessMulti()
                        # Verify it worked
                        if len(ind.fitness.weights) != 6:
                            print(f"  ERROR: After recreation, fitness still has {len(ind.fitness.weights)} weights!")
                            print(f"  Class weights: {creator.FitnessMulti.weights if hasattr(creator, 'FitnessMulti') else 'N/A'}")
                elif not hasattr(ind, 'fitness'):
                    # No fitness object - create one
                    ind.fitness = creator.FitnessMulti()
            
            # Evaluate with parallel processing
            print(f"  [{datetime.now().strftime('%H:%M:%S')}] starting parallel evaluation of {len(offspring)} individuals...")
            start_eval = datetime.now()
            print(f"  Evaluating {len(offspring)} individuals in parallel ({NUM_WORKERS} workers)...")
            try:
                fits = parallel_evaluate(offspring, in_sample, param_dict, param_keys, pool=persistent_pool)
                eval_duration = (datetime.now() - start_eval).total_seconds()
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] parallel evaluation finished (took {eval_duration:.1f}s)")
                
                # Validate all fitness tuples have correct length BEFORE assignment
                invalid_fits = []
                for idx, fit in enumerate(fits):
                    if len(fit) != 6:
                        invalid_fits.append((idx, fit, len(fit)))
                
                if invalid_fits:
                    print(f"  (!)  ERROR: Found {len(invalid_fits)} fitness tuples with wrong length:")
                    for idx, fit, length in invalid_fits[:5]:  # Show first 5
                        print(f"    Individual {idx}: length={length}, values={fit}")
                    # Fix them
                    for idx, fit, length in invalid_fits:
                        fits[idx] = (-1000.0, 100000.0, 0.0, 0.0, 0.0, 0.0)
                    print(f"  Fixed {len(invalid_fits)} invalid fitness tuples.")
                
                # Diagnostic: Check if all solutions are getting penalized
                penalty_count = sum(1 for f in fits if f[0] < 0)  # Count negative Sortino (penalties)
                if penalty_count == len(fits) and gen % 5 == 0:  # Only print every 5 generations to avoid spam
                    print(f"  (!)  WARNING: All {len(fits)} solutions are getting penalized (likely failing MIN_TRADES_DAY={MIN_TRADES_DAY})")
                    # Sample a few to see what avg_trades_day values are
                    sample_indices = [0, len(fits)//4, len(fits)//2]
                    try:
                        for idx in sample_indices:
                            if idx >= len(offspring): continue
                            sample_params = dict(zip(param_keys, offspring[idx]))
                            # Run a quick diagnostic
                            sample_metrics = run_backtest(sample_params, in_sample, param_dict, suppress_output=True)
                            trades_df = sample_metrics.get('trades_df', pd.DataFrame())
                            total_trades = len(trades_df)
                            days = (trades_df['exit_time'].max() - trades_df['entry_time'].min()).days if not trades_df.empty and len(trades_df) > 1 else 0
                            print(f"    Sample {idx}: avg_trades_day={sample_metrics['avg_trades_day']:.3f}, "
                                  f"total_trades={total_trades}, days={days}")
                    except Exception as e:
                        print(f"    ERROR in diagnostic sample: {str(e)}")
                        traceback.print_exc()
            except KeyboardInterrupt:
                print("\n\nInterrupted during evaluation. Saving checkpoint...")
                save_checkpoint(pop, hof, logbook, gen, current_config)
                print(f"Completed {gen + 1} out of {NUM_GEN} generations.")
                return
            except Exception as e:
                print(f"  ERROR in parallel evaluation: {e}")
                # Fallback to sequential evaluation
                print(f"  Falling back to sequential evaluation...")
                fits = []
                for i, (ind, df) in enumerate([(ind, in_sample) for ind in offspring]):
                    try:
                        fit = toolbox.evaluate((ind, df))
                        fits.append(fit)
                    except KeyboardInterrupt:
                        print("\n\nInterrupted during sequential evaluation. Saving checkpoint...")
                        save_checkpoint(pop, hof, logbook, gen, current_config)
                        print(f"Completed {gen + 1} out of {NUM_GEN} generations.")
                        return
                    except Exception as e2:
                        print(f"  ERROR evaluating individual {i}: {e2}")
                        print(f"  ERROR evaluating individual {i}: {e2}")
                        fits.append((-1000.0, 100000.0, 0.0, 0.0, 0.0, 0.0))  # Very poor fitness (6 objectives)
            
            # Assign fitness values
            for idx, (fit, ind) in enumerate(zip(fits, offspring)):
                # Safety check: ensure fitness has correct number of values
                if len(fit) != 6:
                    print(f"  ERROR: Individual {idx} has fitness tuple with {len(fit)} values, expected 6.")
                    print(f"  Fitness values: {fit}")
                    print(f"  Assigning poor fitness instead.")
                    fit = (-1000.0, 100000.0, 0.0, 0.0, 0.0, 0.0)  # 6 objectives
                # Convert numpy types to Python floats (DEAP requires native Python types)
                fit = tuple(float(x) for x in fit)
                
                # Check if individual's fitness object has correct weights BEFORE assignment
                if hasattr(ind.fitness, 'weights') and len(ind.fitness.weights) != 6:
                    print(f"  WARNING: Individual {idx} has fitness with {len(ind.fitness.weights)} weights, expected 6.")
                    print(f"  Recreating fitness object with correct weights...")
                    # CRITICAL: First ensure the class itself has correct weights
                    if not hasattr(creator, 'FitnessMulti') or len(creator.FitnessMulti.weights) != 6:
                        print(f"    Class also has wrong weights ({len(creator.FitnessMulti.weights) if hasattr(creator, 'FitnessMulti') else 0}), recreating class...")
                        if hasattr(creator, "FitnessMulti"):
                            del creator.FitnessMulti
                        if hasattr(creator, "Individual"):
                            del creator.Individual
                        creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 1.0, 2.0, 2.0))
                        creator.create("Individual", list, fitness=creator.FitnessMulti)
                        print(f"    Class recreated with weights: {creator.FitnessMulti.weights}")
                    # Now create new fitness object (should have 6 weights now)
                    ind.fitness = creator.FitnessMulti()
                    # Verify it worked
                    if len(ind.fitness.weights) != 6:
                        print(f"    FATAL: After class recreation, fitness still has {len(ind.fitness.weights)} weights!")
                        raise RuntimeError(f"Cannot fix fitness object - class has {len(creator.FitnessMulti.weights)} weights, expected 6")
                
                try:
                    ind.fitness.values = fit
                except AssertionError as e:
                    print(f"  FATAL ERROR assigning fitness to individual {idx}:")
                    print(f"    Fitness tuple: {fit}")
                    print(f"    Tuple length: {len(fit)}")
                    print(f"    Fitness weights: {ind.fitness.weights if hasattr(ind.fitness, 'weights') else 'N/A'}")
                    print(f"    Expected length: 6 (matching weights)")
                    print(f"    Error: {e}")
                    # Force recreate fitness object and try again
                    # CRITICAL: Ensure FitnessMulti class has correct weights first
                    if not hasattr(creator, 'FitnessMulti') or len(creator.FitnessMulti.weights) != 6:
                        print(f"    Recreating FitnessMulti class (has {len(creator.FitnessMulti.weights) if hasattr(creator, 'FitnessMulti') else 0} weights)...")
                        if hasattr(creator, "FitnessMulti"):
                            del creator.FitnessMulti
                        if hasattr(creator, "Individual"):
                            del creator.Individual
                        creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 1.0, 2.0, 2.0))
                        creator.create("Individual", list, fitness=creator.FitnessMulti)
                        print(f"    Class recreated. New weights: {creator.FitnessMulti.weights}")
                    # Create new fitness object
                    ind.fitness = creator.FitnessMulti()
                    # Double-check it has correct weights
                    if len(ind.fitness.weights) != 6:
                        print(f"    FATAL: New fitness object still has {len(ind.fitness.weights)} weights!")
                        print(f"    This indicates a deeper issue with DEAP creator classes.")
                        raise RuntimeError(f"Cannot create fitness with 6 weights - class definition is corrupted")
                    ind.fitness.values = fit
                    print(f"  Fixed by recreating fitness object (now has {len(ind.fitness.weights)} weights).")
            
            # Validate all individuals have proper multi-objective fitness (4 values)
            all_individuals = offspring + pop
            for ind in all_individuals:
                if not ind.fitness.valid:
                    # Invalid fitness - assign poor fitness
                    ind.fitness.values = (-1000.0, 100000.0, 0.0, 0.0, 0.0, 0.0)  # 6 objectives
                elif len(ind.fitness.values) != 6:
                    # Wrong fitness format - this shouldn't happen but handle it
                    print(f"WARNING: Individual has {len(ind.fitness.values)} fitness values, expected 6. Assigning poor fitness.")
                    ind.fitness.values = (-1000.0, 100000.0, 0.0, 0.0, 0.0, 0.0)  # 6 objectives
            
            # Select next generation using NSGA-II
            pop = toolbox.select(all_individuals, POP_SIZE)
            
            # Update Pareto front
            # Track which generation each solution was found in
            # CRITICAL: Set generation_found on ALL individuals in pop BEFORE updating Hall of Fame
            # This ensures new solutions that enter the Hall of Fame have the correct generation
            old_hof_individuals = set(id(ind) for ind in hof)  # Track which individuals were already in Hall of Fame
            
            for ind in pop:
                ind.generation_found = gen  # Always set - individuals in pop are from current generation
            
            # Update Hall of Fame (may add new solutions or replace old ones)
            hof.update(pop)
            
            # After update, mark any NEW individuals that entered the Hall of Fame with current generation
            # Old individuals that remain in Hall of Fame keep their original generation_found
            for ind in hof:
                ind_id = id(ind)
                if ind_id not in old_hof_individuals:
                    # This is a NEW individual that just entered the Hall of Fame
                    ind.generation_found = gen
                # If ind_id is in old_hof_individuals, it was already in Hall of Fame, so keep its original generation_found
            
            # Record statistics
            record = stats.compile(pop)
            record['pareto_size'] = len(hof)
            
            # Calculate avg_trades_day for best individual (for tracking)
            # Use current generation best for convergence plots (shows progress per generation)
            best_ind = max(pop, key=lambda ind: ind.fitness.values[0]) if pop else None
            if best_ind:
                try:
                    # Get best individual's parameters for actual backtest
                    # CRITICAL: Use the same parameter conversion logic as final backtest to ensure metrics match
                    best_params_temp = dict(zip(param_keys, best_ind))
                    
                    # Step 1: Clamp parameters to valid ranges
                    for n, v in best_params_temp.items():
                        if n in param_dict:
                            mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
                            v = max(mn, min(v, mx))
                            if typ == 'int':
                                best_params_temp[n] = int(round(v))
                            else:
                                best_params_temp[n] = float(v)
                    
                    # Step 2: Convert TP Method to boolean flags (same as final backtest)
                    if 'TP Method' in best_params_temp:
                        tp_method = int(round(best_params_temp['TP Method']))
                        best_params_temp['Fixed BB at Entry TP'] = (tp_method == 0)
                        best_params_temp['Fixed ATR TP'] = (tp_method == 1)
                        best_params_temp['Opposite Bollinger Band TP'] = (tp_method == 2)
                        best_params_temp.pop('TP Method', None)
                    
                    # Step 3: Convert boolean parameters (0/1 int) to actual booleans (same as final backtest)
                    for n in list(best_params_temp.keys()):
                        if n in param_dict:
                            original_type = param_dict[n].get('type', '')
                            if original_type == 'bool' and isinstance(best_params_temp[n], (int, float)):
                                best_params_temp[n] = bool(int(round(best_params_temp[n])))
                    
                    # Now run backtest with fully converted parameters (same logic as final backtest)
                    best_metrics = run_backtest(best_params_temp, in_sample, param_dict, suppress_output=True)
                    record['avg_trades_day'] = best_metrics.get('avg_trades_day', 0.0)
                    record['max_trades_day'] = best_metrics.get('avg_trades_day', 0.0)  # For best individual, same as avg
                    # Store ACTUAL metrics (in real units) for the best individual from current generation
                    record['actual_dd_best'] = best_metrics.get('max_drawdown', 0.0)
                    record['actual_sortino_best'] = best_metrics.get('sortino', 0.0)
                    record['actual_pf_best'] = best_metrics.get('profit_factor', 0.0)
                    record['actual_pnl_best'] = best_metrics.get('total_profit', 0.0)
                except Exception as e:
                    record['avg_trades_day'] = 0.0
                    record['max_trades_day'] = 0.0
                    record['actual_dd_best'] = 0.0
                    record['actual_sortino_best'] = 0.0
                    record['actual_pf_best'] = 0.0
                    record['actual_pnl_best'] = 0.0
            else:
                record['avg_trades_day'] = 0.0
                record['max_trades_day'] = 0.0
                record['actual_dd_best'] = 0.0
                record['actual_sortino_best'] = 0.0
                record['actual_pf_best'] = 0.0
                record['actual_pnl_best'] = 0.0
            
            logbook.record(gen=gen, evals=len(pop), **record)
            
            print(f"{gen}\t{len(pop)}\t{round(record['avg_sortino'], 4)}\t{round(record['avg_dd'], 2)}\t{round(record['avg_pf'], 4)}\t{len(hof)}")
            actual_dd_str = f", Actual DD=${record.get('actual_dd_best', 0):,.0f}" if 'actual_dd_best' in record else ""
            print(f"  Best: Sortino={round(record['max_sortino'], 4)}, DD={round(record['min_dd'], 2)} (norm){actual_dd_str}, PF={round(record['max_pf'], 4)}")
            if 'avg_trades_day' in record:
                print(f"  Avg Trades/Day: {record['avg_trades_day']:.3f}")
            
            # Diagnostic: If all solutions are penalized, show more info
            if record['max_sortino'] < 0 and gen % 5 == 0:  # Only print every 5 generations
                print(f"  (!)  All solutions appear to be penalized (Sortino < 0)")
                print(f"     This suggests MIN_TRADES_DAY constraint ({MIN_TRADES_DAY}) may be too strict")
                print(f"     Consider reducing MIN_TRADES_DAY in the parameter CSV or relaxing filters")
            
            # Save checkpoint after each generation
            start_save = datetime.now()
            save_checkpoint(pop, hof, logbook, gen, current_config)
            save_duration = (datetime.now() - start_save).total_seconds()
            print(f"  [{datetime.now().strftime('%H:%M:%S')}] checkpoint saved (took {save_duration:.1f}s)")
            
            # Update HTML dashboard after each generation (with progress info)
            # Select best solution for display (highest Sortino, with tie-breaker if capped)
            if len(hof) > 0:
                max_sortino = max(ind.fitness.values[0] for ind in hof)
                if max_sortino >= 30.0:  # Sortino is capped, need tie-breaker
                    candidates = [ind for ind in hof if abs(ind.fitness.values[0] - max_sortino) < 0.01]
                    best_for_display = min(candidates, key=lambda ind: (ind.fitness.values[1], -ind.fitness.values[2]))
                else:
                    best_for_display = max(hof, key=lambda ind: ind.fitness.values[0])
                best_params_display = dict(zip(param_keys, best_for_display))
                # Clamp parameters
                for n, v in best_params_display.items():
                    if n in param_dict:
                        mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
                        v = max(mn, min(v, mx))
                        if typ == 'int':
                            best_params_display[n] = int(round(v))
                        else:
                            best_params_display[n] = float(v)
                
                best_fitness_display = best_for_display.fitness.values
                # Track which generation this solution was found in
                best_gen_found = getattr(best_for_display, 'generation_found', None)
                
                # If generation_found is 0 or None (from old checkpoint), try to infer from logbook
                if best_gen_found is None or best_gen_found == 0:
                    # Find which generation had the best normalized Sortino that matches this solution
                    best_sortino = best_for_display.fitness.values[0]
                    if logbook is not None and 'max_sortino' in logbook.header:
                        max_sortinos = logbook.select("max_sortino")
                        gens = logbook.select("gen")
                        # Find generation with Sortino closest to best solution's Sortino
                        best_match_gen = None
                        best_match_diff = float('inf')
                        for g, s in zip(gens, max_sortinos):
                            if isinstance(s, (int, float)) and s > -500 and not np.isinf(s):
                                diff = abs(s - best_sortino)
                                if diff < best_match_diff:
                                    best_match_diff = diff
                                    best_match_gen = g
                        if best_match_gen is not None and best_match_diff < 0.01:  # Very close match
                            best_gen_found = best_match_gen
                            # Also update the solution's generation_found attribute for future reference
                            best_for_display.generation_found = best_match_gen
            else:
                # No solutions yet - use placeholder
                best_for_display = None
                best_params_display = {}
                best_fitness_display = (0.0, 0.0, 0.0, 0.0, 0.0)  # 5 objectives
                best_gen_found = None
            
            # Update dashboard every generation for real-time tracking
            should_update_dashboard = True
            
            # Only run expensive backtests when we're actually updating the dashboard
            is_res_display = {'sortino': 0, 'max_drawdown': 0, 'profit_factor': 0, 'avg_trades_day': 0, 'total_profit': 0}
            trades_is_display = pd.DataFrame()
            oos_res_display = {'sortino': 0, 'max_drawdown': 0, 'profit_factor': 0, 'avg_trades_day': 0, 'total_profit': 0}
            trades_oos_display = pd.DataFrame()
            
            if should_update_dashboard:
                # For intermediate generations, run actual backtest to get real metrics (not normalized fitness)
                # This ensures HTML shows actual trades/day, not normalized values
                if best_for_display is not None and len(in_sample) > 0:
                    try:
                        # Convert parameters the same way evaluation does (TP Method, booleans, etc.)
                        is_params = best_params_display.copy()
                        
                        # Convert TP Method to boolean flags if needed
                        if 'TP Method' in is_params:
                            tp_method = int(round(is_params['TP Method']))
                            is_params['Fixed BB at Entry TP'] = (tp_method == 0)
                            is_params['Fixed ATR TP'] = (tp_method == 1)
                            is_params['Opposite Bollinger Band TP'] = (tp_method == 2)
                            is_params.pop('TP Method', None)
                        
                        # Convert boolean parameters (0/1 int) to actual booleans
                        for n in list(is_params.keys()):
                            if n in param_dict:
                                original_type = param_dict[n].get('type', '')
                                if original_type == 'bool' and isinstance(is_params[n], (int, float)):
                                    is_params[n] = bool(int(round(is_params[n])))
                        
                        # Run actual backtest to get real metrics
                        is_res_actual = run_backtest(is_params, in_sample, param_dict, suppress_output=True)
                        if isinstance(is_res_actual, dict):
                            # Calculate avg profit per trade for display
                            ppt_val = 0.0
                            if isinstance(is_res_actual.get('trades_df'), pd.DataFrame) and not is_res_actual['trades_df'].empty:
                                ppt_val = is_res_actual.get('total_profit', 0) / len(is_res_actual['trades_df'])
                            
                            is_res_display = {
                                'sortino': is_res_actual.get('sortino', 0),
                                'max_drawdown': is_res_actual.get('max_drawdown', 0),
                                'profit_factor': is_res_actual.get('profit_factor', 0),
                                'avg_trades_day': is_res_actual.get('avg_trades_day', 0),
                                'total_profit': is_res_actual.get('total_profit', 0),
                                'avg_profit_per_trade': ppt_val
                            }
                            trades_is_display = is_res_actual.get('trades_df', pd.DataFrame())
                    except Exception as e:
                        print(f"  Warning: Could not run IS backtest for display: {e}")
                        # Fallback to fitness values (but these are normalized, so not ideal)
                        is_res_display = {'sortino': best_fitness_display[0], 'max_drawdown': best_fitness_display[1], 
                                         'profit_factor': best_fitness_display[2], 'avg_trades_day': best_fitness_display[3] if len(best_fitness_display) > 3 else 0, 
                                         'total_profit': best_fitness_display[4] if len(best_fitness_display) > 4 else 0,
                                         'avg_profit_per_trade': best_fitness_display[5] if len(best_fitness_display) > 5 else 0}
                
                # Calculate OOS every 3 generations (or on first generation) to show progress without slowing down too much
                if len(hof) > 0 and (gen % 3 == 0 or gen == start_gen) and len(oos) > 0:
                    # Run OOS backtest on best solution for intermediate progress tracking
                    try:
                        # Convert TP Method to boolean flags if needed
                        oos_params = best_params_display.copy()
                        if 'TP Method' in oos_params:
                            tp_method = int(round(oos_params['TP Method']))
                            oos_params['Fixed BB at Entry TP'] = (tp_method == 0)
                            oos_params['Fixed ATR TP'] = (tp_method == 1)
                            oos_params['Opposite Bollinger Band TP'] = (tp_method == 2)
                            oos_params.pop('TP Method', None)
                        
                        # Convert boolean parameters (0/1 int) to actual booleans
                        for n in list(oos_params.keys()):
                            if n in param_dict:
                                original_type = param_dict[n].get('type', '')
                                if original_type == 'bool' and isinstance(oos_params[n], (int, float)):
                                    oos_params[n] = bool(int(round(oos_params[n])))
                        
                        oos_res_actual = run_backtest(oos_params, oos, param_dict, suppress_output=True)
                        if isinstance(oos_res_actual, dict):
                            oos_res_display = {
                                'sortino': oos_res_actual.get('sortino', 0),
                                'max_drawdown': oos_res_actual.get('max_drawdown', 0),
                                'profit_factor': oos_res_actual.get('profit_factor', 0),
                                'avg_trades_day': oos_res_actual.get('avg_trades_day', 0),
                                'total_profit': oos_res_actual.get('total_profit', 0)
                            }
                            trades_oos_display = oos_res_actual.get('trades_df', pd.DataFrame())
                        else:
                            oos_res_display = {'sortino': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0, 'total_profit': 0}
                            trades_oos_display = pd.DataFrame()
                        # Ensure all required keys exist
                        required_keys = ['sortino', 'max_drawdown', 'avg_trades_day', 'profit_factor']
                        for key in required_keys:
                            if key not in oos_res_display:
                                oos_res_display[key] = 0
                    except Exception as e:
                        # Silent fail for intermediate generations - don't spam console
                        oos_res_display = {'sortino': 0, 'max_drawdown': 0, 'profit_factor': 0, 'avg_trades_day': 0}
                        trades_oos_display = pd.DataFrame()
            
            # Auto-launch on first generation only (gen == start_gen means first generation of this run)
            auto_launch_now = (gen == start_gen)
            
            if should_update_dashboard:
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] updating dashboard...")
                start_dash = datetime.now()
                try:
                    # Write directly to web directory
                    os.makedirs(WEB_DIR, exist_ok=True)
                    generate_html_dashboard(
                        hof, best_for_display, best_params_display, best_fitness_display,
                        param_keys, param_dict, logbook,
                        is_res_display, oos_res_display, trades_is_display, trades_oos_display,
                        WEB_DASHBOARD, DIAG_DIR,  # Write to web directory as primary location
                        current_gen=gen + 1, total_gen=NUM_GEN, is_final=False, auto_launch=auto_launch_now,
                        is_periods=is_periods if 'is_periods' in locals() else None, 
                        oos_periods=oos_periods if 'oos_periods' in locals() else None,
                        in_sample=in_sample if 'in_sample' in locals() else None,
                        best_gen_found=best_gen_found if 'best_gen_found' in locals() else None,
                        pop=pop
                    )
                    dash_duration = (datetime.now() - start_dash).total_seconds()
                    print(f"  [{datetime.now().strftime('%H:%M:%S')}] dashboard updated (took {dash_duration:.1f}s)")
                    # Also copy to diagnostics directory for backup
                    try:
                        import shutil
                        if os.path.exists(WEB_DASHBOARD):
                            shutil.copy2(WEB_DASHBOARD, HTML_DASHBOARD)
                    except Exception as e:
                        pass  # Silent fail for backup copy
                    
                    if auto_launch_now:
                        print(f"  HTML Dashboard updated and opened  {WEB_DASHBOARD}")
                    else:
                        print(f"  HTML Dashboard updated  {WEB_DASHBOARD}")
                except Exception as e:
                    print(f"  WARNING: Failed to update HTML dashboard: {e}")
                import traceback
                traceback.print_exc()
            
            print(f"Generation {gen} completed.\n")
            
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Saving checkpoint...")
        if 'gen' in locals():
            save_checkpoint(pop, hof, logbook, gen, current_config)
            print(f"Completed {gen + 1} out of {NUM_GEN} generations.")
        else:
            print("No progress to save.")
        return
    except Exception as e:
        print(f"\n\nERROR during evolution:")
        if 'gen' in locals():
            print(f"Error occurred at generation {gen}")
        print(f"Exception: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        print(f"\nCheckpoint saved. Resume by running the script again.")
        # Clean up persistent pool
        if 'persistent_pool' in locals():
            try:
                persistent_pool.terminate()
                persistent_pool.join()
            except:
                pass
        return
    finally:
        # Clean up persistent pool when done
        if 'persistent_pool' in locals():
            try:
                print("\n  Closing worker pool...")
                persistent_pool.close()
                persistent_pool.join()
                print("  Worker pool closed.")
            except Exception as e:
                print(f"  Warning: Error closing pool: {e}")
                try:
                    persistent_pool.terminate()
                    persistent_pool.join()
                except:
                    pass
    
    # Check if we have any results
    if len(hof) == 0:
        print("\nERROR: No individuals in Pareto Front. Cannot proceed.")
        print("This may indicate all evaluations failed.")
        return
    
    # Select best solution from Pareto front
    # Strategy: Choose solution with highest Sortino Ratio (primary objective)
    # If multiple solutions have capped Sortino (30.0), use tie-breaker: lower drawdown, then higher PF
    max_sortino = max(ind.fitness.values[0] for ind in hof)
    if max_sortino >= 30.0:  # Sortino is capped, need tie-breaker
        # Find all solutions with max Sortino
        candidates = [ind for ind in hof if abs(ind.fitness.values[0] - max_sortino) < 0.01]
        # Among candidates, prefer: lower drawdown (fitness[1]), then higher PF (fitness[2]), then higher trades/day (fitness[3]), then higher total_profit (fitness[4])
        best = min(candidates, key=lambda ind: (ind.fitness.values[1], -ind.fitness.values[2], -ind.fitness.values[3], -ind.fitness.values[4] if len(ind.fitness.values) > 4 else 0))
        print(f"  Note: Multiple solutions have capped Sortino ({max_sortino:.2f}). Selected based on lower drawdown.")
    else:
        best = max(hof, key=lambda ind: ind.fitness.values[0])
    
    # Track which generation this solution was found in
    best_gen_found = getattr(best, 'generation_found', None)
    
    # If generation_found is 0 or None (from old checkpoint), try to infer from logbook
    if best_gen_found is None or best_gen_found == 0:
        # Find which generation had the best normalized Sortino that matches this solution
        best_sortino = best.fitness.values[0]
        if logbook is not None and 'max_sortino' in logbook.header:
            max_sortinos = logbook.select("max_sortino")
            gens = logbook.select("gen")
            # Find generation with Sortino closest to best solution's Sortino
            best_match_gen = None
            best_match_diff = float('inf')
            for g, s in zip(gens, max_sortinos):
                if isinstance(s, (int, float)) and s > -500 and not np.isinf(s):
                    diff = abs(s - best_sortino)
                    if diff < best_match_diff:
                        best_match_diff = diff
                        best_match_gen = g
            if best_match_gen is not None and best_match_diff < 0.01:  # Very close match
                best_gen_found = best_match_gen
                # Also update the solution's generation_found attribute for future reference
                best.generation_found = best_match_gen
    
    # Clamp and format best parameters properly
    best_params_raw = dict(zip(param_keys, best))
    best_params = {}
    for n, v in best_params_raw.items():
        mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
        v = max(mn, min(v, mx))  # Clamp to valid range
        if typ == 'int':
            best_params[n] = int(round(v))
        else:
            best_params[n] = float(v)
    
    # Ensure critical integer parameters are properly set
    if 'Bollinger Band Length' in best_params:
        best_params['Bollinger Band Length'] = max(1, int(round(best_params['Bollinger Band Length'])))
    
    if 'ATR Length for Trailing Stop' in best_params:
        best_params['ATR Length for Trailing Stop'] = max(1, int(round(best_params['ATR Length for Trailing Stop'])))
    if 'ATR Length for TP' in best_params:
        best_params['ATR Length for TP'] = max(1, int(round(best_params['ATR Length for TP'])))
    if 'Trailing Delay (bars)' in best_params:
        best_params['Trailing Delay (bars)'] = max(0, int(round(best_params['Trailing Delay (bars)'])))
    if 'Timeframe (minutes)' in best_params:
        best_params['Timeframe (minutes)'] = max(1, int(round(best_params['Timeframe (minutes)'])))
    if 'Max Open Trades' in best_params:
        best_params['Max Open Trades'] = max(1, int(round(best_params['Max Open Trades'])))
    
    best_fitness = best.fitness.values
    
    print("\n=== BEST SOLUTION FROM PARETO FRONT ===")
    print(f"Selected based on highest Sortino Ratio")
    total_profit = best_fitness[4] if len(best_fitness) > 4 else 0.0
    print(f"Fitness: Sortino={best_fitness[0]:.4f}, MaxDD={best_fitness[1]:.2f}, PF={best_fitness[2]:.4f}, Trades/Day={best_fitness[3]:.4f}, TotalProfit={total_profit:.4f}")
    print(f"Parameters (grouped by category):")
    
    # Group parameters for display
    def group_params_for_display(params_dict_local):
        "Group parameters into logical categories."
        groups = {
            'Entry Criteria': ['Enable Long Trades', 'Enable Short Trades', 'Bollinger Band Length', 
                              'Bollinger Band StdDev', 'Long Entry on Wick Touch', 'Long Entry on Body in Zone',
                              'Long Trigger (% From Lower Band)', 'Short Entry on Wick Touch', 
                              'Short Entry on Body in Zone', 'Short Trigger (% From Upper Band)',
                              'ATR Length for Filter', 'Max ATR Filter (Points)', 'Min ATR Filter (Points)', 'RTH Start (HH:MM)', 'RTH End (HH:MM)',
                              'Enable RTH Filter', 'Volume MA Length', 'Max Volume Multiplier', 'Timeframe (minutes)',
                              'Max Open Trades'],
            'Take Profit Criteria': ['TP Method', 'Opposite Bollinger Band TP', 'Fixed ATR TP', 'Fixed BB at Entry TP',
                                    'ATR Length for TP', 'ATR Multiplier for TP'],
            'Stop Loss Criteria': ['Initial Stop Loss (%)', 'Enable Trailing Stop', 
                                  'ATR Length for Trailing Stop', 'ATR Multiplier for Trailing Stop',
                                  'Trailing Delay (bars)'],
            'GA Criteria': ['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                           'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                           'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                           'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT']
        }
        
        grouped = {}
        for group_name, param_list in groups.items():
            grouped[group_name] = {k: v for k, v in params_dict_local.items() if k in param_list}
        
        return grouped
    
    grouped_params = group_params_for_display(best_params)
    for group_name, params in grouped_params.items():
        if params:
            print(f"\n  {group_name}:")
            for k, v in params.items():
                print(f"    {k}: {round(v, 4) if isinstance(v, float) else v}")
    
    print(f"\n=== PARETO FRONT SUMMARY ===")
    print(f"Total Pareto-optimal solutions: {len(hof)}")
    print(f"Sortino range: {min(ind.fitness.values[0] for ind in hof):.4f} to {max(ind.fitness.values[0] for ind in hof):.4f}")
    print(f"Drawdown range: {min(ind.fitness.values[1] for ind in hof):.2f} to {max(ind.fitness.values[1] for ind in hof):.2f}")
    print(f"Profit Factor range: {min(ind.fitness.values[2] for ind in hof):.4f} to {max(ind.fitness.values[2] for ind in hof):.4f}")
    
    # ------------------------------------------------------------------
    # In-sample & OOS validation
    # ------------------------------------------------------------------
    print("\n=== Running Final Validation Backtests ===")
    print(f"In-Sample data: {len(in_sample):,} rows")
    if len(in_sample) > 0:
        print(f"  Date range: {in_sample.index[0]} to {in_sample.index[-1]}")
    else:
        print("  WARNING: In-Sample data is empty!")
    
    print(f"OOS data: {len(oos):,} rows")
    if len(oos) > 0:
        print(f"  Date range: {oos.index[0]} to {oos.index[-1]}")
    else:
        print("  WARNING: OOS data is empty!")
    
    # Run IS backtest with error handling
    try:
        # Convert parameters the same way evaluation does (TP Method, booleans, etc.)
        # This ensures Selected Solution Performance matches the Optimized Values
        is_params_final = best_params.copy()
        
        # Convert TP Method to boolean flags if needed
        if 'TP Method' in is_params_final:
            tp_method = int(round(is_params_final['TP Method']))
            is_params_final['Fixed BB at Entry TP'] = (tp_method == 0)
            is_params_final['Fixed ATR TP'] = (tp_method == 1)
            is_params_final['Opposite Bollinger Band TP'] = (tp_method == 2)
            is_params_final.pop('TP Method', None)
        
        # Convert boolean parameters (0/1 int) to actual booleans
        for n in list(is_params_final.keys()):
            if n in param_dict:
                original_type = param_dict[n].get('type', '')
                if original_type == 'bool' and isinstance(is_params_final[n], (int, float)):
                    is_params_final[n] = bool(int(round(is_params_final[n])))
        
        is_res = run_backtest(is_params_final, in_sample, param_dict, suppress_output=False, debug=True)
        if not isinstance(is_res, dict):
            print("ERROR: is_res is not a dict!")
            is_res = {'sortino': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0, 'trades_df': pd.DataFrame()}
        trades_is = is_res.pop('trades_df', pd.DataFrame())
        if not isinstance(trades_is, pd.DataFrame):
            trades_is = pd.DataFrame()
        print(f"In-Sample backtest: {len(trades_is)} trades")
        trades_is.to_csv(TRADES_IS_CSV, index=False)
    except Exception as e:
        print(f"ERROR during In-Sample backtest: {e}")
        import traceback
        traceback.print_exc()
        is_res = {'sortino': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0, 'total_profit': 0}
        trades_is = pd.DataFrame()
    
    # Run OOS backtest with error handling
    try:
        if len(oos) == 0:
            print("WARNING: OOS data is empty, skipping OOS backtest")
            oos_res = {'sortino': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0, 'total_profit': 0}
            trades_oos = pd.DataFrame()
        else:
            # Use the same converted parameters for OOS backtest (ensures consistency)
            oos_res = run_backtest(is_params_final, oos, param_dict, suppress_output=False)
            if not isinstance(oos_res, dict):
                print("ERROR: oos_res is not a dict!")
                oos_res = {'sortino': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0, 'trades_df': pd.DataFrame()}
            trades_oos = oos_res.pop('trades_df', pd.DataFrame())
            if not isinstance(trades_oos, pd.DataFrame):
                trades_oos = pd.DataFrame()
            print(f"OOS backtest: {len(trades_oos)} trades")
            trades_oos.to_csv(TRADES_OOS_CSV, index=False)
    except Exception as e:
        print(f"ERROR during OOS backtest: {e}")
        import traceback
        traceback.print_exc()
        oos_res = {'sortino': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0, 'total_profit': 0}
        trades_oos = pd.DataFrame()
    
    print("\n=== In-Sample vs OOS Comparison ===")
    comp = pd.DataFrame([is_res, oos_res], index=['In-Sample', 'OOS'])
    print(comp)
    
    for label, trades in [('In-Sample', trades_is), ('OOS', trades_oos)]:
        if not trades.empty:
            total_pnl = trades['pnl'].sum()
            win_rate = (trades['pnl'] > 0).mean() * 100
            pf = abs(trades[trades['pnl'] > 0]['pnl'].sum() /
                     trades[trades['pnl'] < 0]['pnl'].sum()) if (trades['pnl'] < 0).any() else np.inf
            calmar = total_pnl / comp.loc[label, 'max_drawdown'] if comp.loc[label, 'max_drawdown'] else np.inf
            print(f"{label}: PNL={total_pnl:,.0f} | Win%={win_rate:.1f} | PF={pf:.2f} | Calmar={calmar:.2f}")
    
    # ------------------------------------------------------------------
    # DIAGNOSTIC PLOTS  ga_diagnostics/
    # ------------------------------------------------------------------
    # Convergence plots for each objective
    plt.figure(figsize=(12, 4))
    plt.subplot(1, 3, 1)
    plt.plot(logbook.select("gen"), logbook.select("avg_sortino"), label='Avg Sortino')
    plt.plot(logbook.select("gen"), logbook.select("max_sortino"), label='Best Sortino')
    plt.title('Sortino Ratio Convergence')
    plt.xlabel('Generation')
    plt.ylabel('Sortino')
    plt.legend()
    plt.grid()
    
    plt.subplot(1, 3, 2)
    plt.plot(logbook.select("gen"), logbook.select("avg_dd"), label='Avg Drawdown')
    plt.plot(logbook.select("gen"), logbook.select("min_dd"), label='Min Drawdown')
    plt.title('Max Drawdown Convergence')
    plt.xlabel('Generation')
    plt.ylabel('Drawdown')
    plt.legend()
    plt.grid()
    
    plt.subplot(1, 3, 3)
    plt.plot(logbook.select("gen"), logbook.select("avg_pf"), label='Avg Profit Factor')
    plt.plot(logbook.select("gen"), logbook.select("max_pf"), label='Max Profit Factor')
    plt.title('Profit Factor Convergence')
    plt.xlabel('Generation')
    plt.ylabel('Profit Factor')
    plt.legend()
    plt.grid()
    
    plt.tight_layout()
    plt.savefig(f'{DIAG_DIR}/convergence_multi_objective.png', dpi=150)
    plt.close()
    print(f"Plot  {DIAG_DIR}/convergence_multi_objective.png")
    
    # Pareto front visualization
    if len(hof) > 1:
        plt.figure(figsize=(15, 5))
        
        # Sortino vs Drawdown
        plt.subplot(1, 3, 1)
        sortinos = [ind.fitness.values[0] for ind in hof]
        dds = [ind.fitness.values[1] for ind in hof]
        plt.scatter(dds, sortinos, alpha=0.6, s=50)
        plt.scatter(best_fitness[1], best_fitness[0], color='red', s=200, marker='*', 
                   label='Selected', zorder=5)
        plt.xlabel('Max Drawdown')
        plt.ylabel('Sortino Ratio')
        plt.title('Pareto Front: Sortino vs Drawdown')
        plt.legend()
        plt.grid(alpha=0.3)
        
        # Sortino vs Profit Factor
        plt.subplot(1, 3, 2)
        pfs = [ind.fitness.values[2] for ind in hof]
        plt.scatter(sortinos, pfs, alpha=0.6, s=50)
        plt.scatter(best_fitness[0], best_fitness[2], color='red', s=200, marker='*', 
                   label='Selected', zorder=5)
        plt.xlabel('Sortino Ratio')
        plt.ylabel('Profit Factor')
        plt.title('Pareto Front: Sortino vs Profit Factor')
        plt.legend()
        plt.grid(alpha=0.3)
        
        # Drawdown vs Profit Factor
        plt.subplot(1, 3, 3)
        plt.scatter(dds, pfs, alpha=0.6, s=50)
        plt.scatter(best_fitness[1], best_fitness[2], color='red', s=200, marker='*', 
                   label='Selected', zorder=5)
        plt.xlabel('Max Drawdown')
        plt.ylabel('Profit Factor')
        plt.title('Pareto Front: Drawdown vs Profit Factor')
        plt.legend()
        plt.grid(alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(f'{DIAG_DIR}/pareto_front.png', dpi=150)
        plt.close()
        print(f"Plot  {DIAG_DIR}/pareto_front.png")
    
    # Pareto front size over generations
    plt.figure(figsize=(8, 4))
    plt.plot(logbook.select("gen"), logbook.select("pareto_size"), marker='o')
    plt.title('Pareto Front Size Over Generations')
    plt.xlabel('Generation')
    plt.ylabel('Number of Pareto-Optimal Solutions')
    plt.grid()
    plt.tight_layout()
    plt.savefig(f'{DIAG_DIR}/pareto_size.png', dpi=150)
    plt.close()
    print(f"Plot  {DIAG_DIR}/pareto_size.png")
    
    # Parameter evolution (for best solution)
    os.makedirs(f'{DIAG_DIR}/param_evolution', exist_ok=True)
    for i, pname in enumerate(param_keys):
        # Get parameter value from best solution
        val = best[i]
        plt.figure(figsize=(6, 3))
        plt.axhline(y=val, color='r', linestyle='--', label=f'Final: {val:.4f}')
        plt.title(f'Best {pname}')
        plt.xlabel('(Single best solution)')
        plt.ylabel(pname)
        plt.legend()
        plt.grid()
        plt.tight_layout()
        plt.savefig(f'{DIAG_DIR}/param_evolution/{pname.replace(" ", "_")}.png')
        plt.close()
    print(f"Parameter plots  {DIAG_DIR}/param_evolution/")
    
    # OOS trade-level plots
    if not trades_oos.empty:
        plt.figure(figsize=(8, 4))
        trades_oos['pnl'].hist(bins=20)
        plt.title('OOS PNL Histogram')
        plt.xlabel('PNL')
        plt.ylabel('Count')
        plt.grid()
        plt.tight_layout()
        plt.savefig(f'{DIAG_DIR}/oos_pnl_hist.png')
        plt.close()
        print(f"Plot  {DIAG_DIR}/oos_pnl_hist.png")
        
        plt.figure(figsize=(8, 4))
        plt.scatter(trades_oos.index, trades_oos['pnl'], c=np.where(trades_oos['pnl'] > 0, 'g', 'r'))
        plt.title('OOS Wins (Green) / Losses (Red)')
        plt.ylabel('PNL')
        plt.grid()
        plt.tight_layout()
        plt.savefig(f'{DIAG_DIR}/oos_win_loss.png')
        plt.close()
        print(f"Plot  {DIAG_DIR}/oos_win_loss.png")
        
        trades_oos['duration'] = (trades_oos['exit_time'] - trades_oos['entry_time']).dt.total_seconds() / 60
        plt.figure(figsize=(8, 4))
        trades_oos['duration'].hist(bins=20)
        plt.title('OOS Trade Duration (min)')
        plt.xlabel('Minutes')
        plt.ylabel('Count')
        plt.grid()
        plt.tight_layout()
        plt.savefig(f'{DIAG_DIR}/oos_trade_duration.png')
        plt.close()
        print(f"Plot  {DIAG_DIR}/oos_trade_duration.png")
        
        equity = 50000 + trades_oos.groupby(trades_oos['exit_time'].dt.date)['pnl'].sum().cumsum()
        plt.figure(figsize=(10, 4))
        equity.plot()
        plt.title('OOS Equity Curve')
        plt.ylabel('Equity')
        plt.grid()
        plt.tight_layout()
        plt.savefig(f'{DIAG_DIR}/oos_equity.png')
        plt.close()
        print(f"OOS equity  {DIAG_DIR}/oos_equity.png")
        if len(set(equity)) == 1:
            print("OOS equity is suspicious (straight line) - no trades or zero variation")
    
    # ------------------------------------------------------------------
    # Generate Interactive HTML Dashboard
    # ------------------------------------------------------------------
    print("\n=== Generating Interactive HTML Dashboard ===")
    # Generate final HTML dashboard with complete results - write directly to web directory
    os.makedirs(WEB_DIR, exist_ok=True)
    generate_html_dashboard(hof, best, best_params, best_fitness, param_keys, param_dict, 
                            logbook, is_res, oos_res, trades_is, trades_oos,
                            WEB_DASHBOARD, DIAG_DIR,  # Write to web directory as primary location
                            current_gen=NUM_GEN, total_gen=NUM_GEN, is_final=True, auto_launch=True,
                            in_sample=in_sample if 'in_sample' in locals() else None,
                            best_gen_found=best_gen_found,
                            pop=pop)
    print(f"HTML Dashboard (FINAL)  {WEB_DASHBOARD}")
    
    # Also copy to diagnostics directory for backup
    try:
        import shutil
        if os.path.exists(WEB_DASHBOARD):
            shutil.copy2(WEB_DASHBOARD, HTML_DASHBOARD)
            print(f"Dashboard backup copied to diagnostics directory: {HTML_DASHBOARD}")
    except Exception as e:
        print(f"Warning: Could not copy to diagnostics directory: {e}")
    
    # Clean up start time file after completion
    if os.path.exists(START_TIME_FILE):
        try:
            os.remove(START_TIME_FILE)
            print("Start time file cleaned up.")
        except:
            pass
    
    # ------------------------------------------------------------------
    # Write optimized CSV with ALL Pareto solutions as columns
    # ------------------------------------------------------------------
    # Sort all solutions by Sortino (descending) for consistent ordering
    solutions_data = []
    for i, ind in enumerate(hof):
        raw_params = dict(zip(param_keys, ind))
        # Clamp parameters
        clamped_params = {}
        for n, v in raw_params.items():
            if n not in param_dict:
                continue
            mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
            v = max(mn, min(v, mx))
            if typ == 'int':
                clamped_params[n] = int(round(v))
            else:
                clamped_params[n] = float(v)
        
        # Handle boolean and TP method conversions
        for n in list(clamped_params.keys()):
            if n in param_dict:
                original_type = param_dict[n].get('type', '')
                if original_type == 'bool' and isinstance(clamped_params[n], (int, float)):
                    clamped_params[n] = bool(int(round(clamped_params[n])))
        
        if 'TP Method' in clamped_params:
            tp_method = int(round(clamped_params['TP Method']))
            clamped_params['Fixed BB at Entry TP'] = (tp_method == 0)
            clamped_params['Fixed ATR TP'] = (tp_method == 1)
            clamped_params['Opposite Bollinger Band TP'] = (tp_method == 2)
            clamped_params.pop('TP Method', None)
        
        # Ensure critical integer parameters
        if 'Bollinger Band Length' in clamped_params:
            clamped_params['Bollinger Band Length'] = max(1, int(round(clamped_params['Bollinger Band Length'])))
        if 'ATR Length for Trailing Stop' in clamped_params:
            clamped_params['ATR Length for Trailing Stop'] = max(1, int(round(clamped_params['ATR Length for Trailing Stop'])))
        if 'ATR Length for TP' in clamped_params:
            clamped_params['ATR Length for TP'] = max(1, int(round(clamped_params['ATR Length for TP'])))
        if 'Trailing Delay (bars)' in clamped_params:
            clamped_params['Trailing Delay (bars)'] = max(0, int(round(clamped_params['Trailing Delay (bars)'])))
        clamped_params['Timeframe (minutes)'] = max(1, int(round(clamped_params.get('Timeframe (minutes)', 15))))
        if 'Max Open Trades' in clamped_params:
            clamped_params['Max Open Trades'] = max(1, int(round(clamped_params['Max Open Trades'])))
        if 'Enable ADX Filter' in clamped_params:
            clamped_params['Enable ADX Filter'] = int(round(clamped_params['Enable ADX Filter']))
        if 'ADX Period' in clamped_params:
            clamped_params['ADX Period'] = max(1, int(round(clamped_params['ADX Period'])))
        if 'Enable Trend Filter' in clamped_params:
            clamped_params['Enable Trend Filter'] = int(round(clamped_params['Enable Trend Filter']))
        if 'Trend EMA Length' in clamped_params:
            clamped_params['Trend EMA Length'] = max(1, int(round(clamped_params['Trend EMA Length'])))
        
        # [NEW] V5 Clamping
        if 'RSI Period' in clamped_params:
            clamped_params['RSI Period'] = max(2, int(round(clamped_params['RSI Period'])))
        if 'RSI Overbought' in clamped_params:
            clamped_params['RSI Overbought'] = max(50, int(round(clamped_params['RSI Overbought'])))
        if 'RSI Oversold' in clamped_params:
            clamped_params['RSI Oversold'] = max(1, int(round(clamped_params['RSI Oversold'])))
        if 'Use RSI Filter' in clamped_params:
             clamped_params['Use RSI Filter'] = int(round(clamped_params['Use RSI Filter']))
        if 'Use VWAP Filter' in clamped_params:
             clamped_params['Use VWAP Filter'] = int(round(clamped_params['Use VWAP Filter']))
        
        fitness = ind.fitness.values
        solutions_data.append({
            'params': clamped_params,
            'sortino': fitness[0],
            'max_dd': fitness[1],
            'profit_factor': fitness[2],
            'avg_trades_day': fitness[3] if len(fitness) > 3 else 0.0,
            'total_profit': fitness[4] if len(fitness) > 4 else 0.0,
            'is_selected': (ind == best)
        })
    
    # Sort by Sortino (descending)
    solutions_data.sort(key=lambda x: x['sortino'], reverse=True)
    
    # Start with original CSV structure
    output_df = param_df.copy()
    
    # Add columns for each solution
    num_solutions = len(solutions_data)
    for sol_idx, sol_data in enumerate(solutions_data):
        col_name = f"Solution_{sol_idx}"
        if sol_data['is_selected']:
            col_name += "_SELECTED"
        
        # Initialize column with empty values
        output_df[col_name] = ""
        
        # Fill in parameter values
        for name, val in sol_data['params'].items():
            matching_rows = output_df[output_df['Name'] == name]
            if not matching_rows.empty:
                idx = matching_rows.index[0]
                typ = param_dict[name]['type']
                if typ == 'bool':
                    # Convert boolean to string for CSV (True/False)
                    output_df.at[idx, col_name] = str(val)
                elif typ == 'int':
                    output_df.at[idx, col_name] = int(val)
                elif typ == 'float':
                    output_df.at[idx, col_name] = round(val, 4)
                else:
                    output_df.at[idx, col_name] = val
    
    # Add statistics rows at the end
    stats_rows = []
    
    # Add separator row
    stats_rows.append({
        'Name': '=== SOLUTION STATISTICS ===',
        'Value': '', 'Min': '', 'Max': '', 'Type': '', 'Description': ''
    })
    for sol_idx in range(num_solutions):
        col_name = f"Solution_{sol_idx}"
        if solutions_data[sol_idx]['is_selected']:
            col_name += "_SELECTED"
        stats_rows[-1][col_name] = ''
    
    # Add metric rows
    metrics = [
        ('Sortino Ratio', 'sortino', '{:.4f}'),
        ('Max Drawdown ($)', 'max_dd', '${:,.2f}'),
        ('Profit Factor', 'profit_factor', '{:.4f}'),
        ('Avg Trades/Day', 'avg_trades_day', '{:.3f}'),
        ('Total Profit (norm)', 'total_profit', '{:.4f}'),  # Normalized (0-1 range)
    ]
    
    for metric_name, metric_key, format_str in metrics:
        row = {
            'Name': metric_name,
            'Value': '', 'Min': '', 'Max': '', 'Type': 'statistic', 'Description': f'{metric_name} for each solution'
        }
        for sol_idx, sol_data in enumerate(solutions_data):
            col_name = f"Solution_{sol_idx}"
            if sol_data['is_selected']:
                col_name += "_SELECTED"
            row[col_name] = format_str.format(sol_data[metric_key])
        stats_rows.append(row)
    
    # Add solution ranking row
    rank_row = {
        'Name': 'Solution Rank',
        'Value': '', 'Min': '', 'Max': '', 'Type': 'statistic', 'Description': 'Rank by Sortino (0 = highest)'
    }
    for sol_idx in range(num_solutions):
        col_name = f"Solution_{sol_idx}"
        if solutions_data[sol_idx]['is_selected']:
            col_name += "_SELECTED"
        rank_row[col_name] = f"#{sol_idx}" + (" (SELECTED)" if solutions_data[sol_idx]['is_selected'] else "")
    stats_rows.append(rank_row)
    
    # Append statistics rows to dataframe
    stats_df = pd.DataFrame(stats_rows)
    output_df = pd.concat([output_df, stats_df], ignore_index=True)
    
    # Save to CSV
    output_df.to_csv(OUTPUT_CSV, index=False)
    print(f"Optimized CSV with {num_solutions} solutions  {OUTPUT_CSV}")
    print(f"  Solution_0_SELECTED = Best solution (highest Sortino)")
    print(f"  Solution_1, Solution_2, ... = Other Pareto-optimal solutions")
    print(f"  Statistics rows added at bottom showing metrics for each solution")
    
    # Archive checkpoint file by renaming it to match output suffix
    # This prevents the next run from resuming (starting fresh) while preserving the data
    if os.path.exists(CHECKPOINT_FILE):
        archive_checkpoint = os.path.join(DIAG_DIR, f'ga_checkpoint_{suffix}.pkl')
        try:
            # If an archive with this name already exists (unlikely given generated suffix), overwrite it
            if os.path.exists(archive_checkpoint):
                os.remove(archive_checkpoint)
            
            os.rename(CHECKPOINT_FILE, archive_checkpoint)
            print(f"Run Complete: Checkpoint archived to {archive_checkpoint}")
            print("Next run will start fresh automatically.")
        except Exception as e:
            print(f"WARNING: Could not archive checkpoint: {e}")
            print("You may need to delete 'ga_checkpoint_v3.pkl' manually to start fresh.")


if __name__ == "__main__":
    # Required for Windows multiprocessing
    multiprocessing.freeze_support()
    main()


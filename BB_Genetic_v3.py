#!/usr/bin/env python3
"""
Genetic Optimization for Bollinger Band Strategy - Version 3.0
==============================================================
Uses shared bollinger_strategy module for unified strategy logic.

IMPROVEMENTS OVER V2:
  • Multi-core parallelization (8-16x speedup)
  • Multi-objective optimization (NSGA-II) - explores Pareto frontier
  • Sortino Ratio instead of Sharpe Ratio (better for trading)

FINAL PRODUCTION SCRIPT
  • Prints the exact CSV used
  • All diagnostics → ga_diagnostics/
  • Multi-objective: Maximize Sortino, Minimize Drawdown, Maximize Profit Factor
  • Enforces TARGET_TRADES_DAY=4, MIN_TRADES_DAY=2
  • Optimizable Trailing Delay (bars) to control quick wins via TP
  • CHECKPOINT/RESUME: Saves state after each generation
    - Automatically resumes from interruption
    - Checkpoint file: ga_diagnostics/ga_checkpoint.pkl
    - Delete checkpoint file to start fresh
"""

import os
import sys
import warnings
import random
import pickle
import multiprocessing
import signal
import time
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.offline as pyo
import webbrowser
from deap import base, creator, tools, algorithms
from bollinger_strategy import BollingerBandStrategy, load_params

warnings.filterwarnings("ignore")

# Windows-specific: Set multiprocessing start method for better Ctrl+C handling
if sys.platform == 'win32':
    multiprocessing.set_start_method('spawn', force=True)

# Global flag for interrupt handling
interrupt_flag = multiprocessing.Event()

def signal_handler(signum, frame):
    """Handle Ctrl+C signal."""
    print("\n\n⚠️  Interrupt signal received. Will save checkpoint after current generation completes...")
    interrupt_flag.set()

# Register signal handler for Ctrl+C
signal.signal(signal.SIGINT, signal_handler)
if hasattr(signal, 'SIGTERM'):
    signal.signal(signal.SIGTERM, signal_handler)

# ----------------------------------------------------------------------
# CSV INPUT / OUTPUT
# ----------------------------------------------------------------------
# Use diagnostic file for testing - locks all parameters to backtest values
PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'
# PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12_DIAGNOSTIC.csv'  # Diagnostic file (locked parameters)
OUTPUT_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_optimized_v3.csv'
TRADES_OOS_CSV = 'Bollinger/output/trades_oos_v3.csv'
TRADES_IS_CSV = 'Bollinger/output/trades_is_v3.csv'
DIAG_DIR = 'ga_diagnostics_v3'
CHECKPOINT_FILE = os.path.join(DIAG_DIR, 'ga_checkpoint_v3.pkl')
START_TIME_FILE = os.path.join(DIAG_DIR, 'ga_start_time.txt')
HTML_DIR = os.path.join(DIAG_DIR, 'html')
HTML_DASHBOARD = os.path.join(HTML_DIR, 'ga_dashboard_v3.html')
WEB_DIR = os.path.join(os.getcwd(), 'web')  # Common web directory
WEB_DASHBOARD = os.path.join(WEB_DIR, 'ga_dashboard_v3.html')
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
NUM_WORKERS = 8  # Fixed to 8 workers to leave resources for other tasks

# Global variables that will be set in main()
param_dict = None
param_df = None
PARAM_RANGES = None
param_keys = None
param_keys = []

# ----------------------------------------------------------------------
# Back-tester using shared strategy module
# ----------------------------------------------------------------------
def run_backtest(params, df, param_dict_local, suppress_output=True, debug=False):
    """
    Run backtest using shared strategy module.
    
    Args:
        params: Dictionary of optimizable parameters
        df: DataFrame with OHLCV data
        param_dict_local: Parameter dictionary (passed to avoid global access)
        suppress_output: If False, print progress
        debug: If True, print detailed filter statistics
        
    Returns:
        dict with metrics: sortino, max_drawdown, avg_trades_day, profit_factor, total_profit, trades_df
    """
    # Default return value (used for errors or empty data)
    default_result = {'sortino': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0, 'total_profit': 0,
                     'trades_df': pd.DataFrame()}
    
    if len(df) == 0:
        if not suppress_output:
            print("WARNING: Empty DataFrame passed to run_backtest")
        return default_result.copy()
    
    # Debug counters
    if debug:
        debug_stats = {
            'total_bars': 0,
            'passed_rth': 0,
            'passed_atr': 0,
            'passed_volume': 0,
            'passed_maintenance': 0,
            'price_touched_trigger': 0,
            'entries_made': 0,
            'filtered_by_rth': 0,
            'filtered_by_atr': 0,
            'filtered_by_volume': 0,
            'filtered_by_maintenance': 0,
            'filtered_by_position_limit': 0
        }
    
    # Create strategy instance
    strategy = BollingerBandStrategy(param_dict_local)
    
    # Update optimizable parameters
    strategy.update_optimizable_params(params)
    
    # Calculate indicators
    try:
        df = strategy.calculate_indicators(df)
    except Exception as e:
        if not suppress_output:
            print(f"ERROR in calculate_indicators: {e}")
        return default_result.copy()
    
    if len(df) == 0:
        if not suppress_output:
            print("WARNING: DataFrame empty after calculate_indicators")
        return default_result.copy()
    
    # Apply filters
    try:
        df = strategy.apply_filters(df)
    except Exception as e:
        if not suppress_output:
            print(f"ERROR in apply_filters: {e}")
        return default_result.copy()
    
    if len(df) == 0:
        if not suppress_output:
            print("WARNING: DataFrame empty after apply_filters")
        return default_result.copy()
    
    # Simulation
    positions = []
    trades = []
    
    for row in df.itertuples():
        # Check exits first
        for pos in positions[:]:
            # Update trailing stop
            strategy.update_trailing_stop(pos, row, df)
            
            # Check exit
            should_exit, reason, price = strategy.check_exit(pos, row, df)
            
            if should_exit:
                pnl = (price - pos['entry_price']) * pos['direction'] * 50
                trades.append(pos | {
                    'exit_time': row.Index,
                    'exit_price': price,
                    'pnl': pnl,
                    'reason': reason
                })
                positions.remove(pos)
        
        # Check entries
        if len(positions) >= strategy.max_open_trades:
            if debug:
                debug_stats['filtered_by_position_limit'] += 1
            continue
        
        # Debug: Check filter status before entry check
        if debug:
            if hasattr(row, 'in_rth'):
                if row.in_rth:
                    debug_stats['passed_rth'] += 1
                else:
                    debug_stats['filtered_by_rth'] += 1
            if hasattr(row, 'atr_filter'):
                if row.atr_filter:
                    debug_stats['passed_atr'] += 1
                else:
                    debug_stats['filtered_by_atr'] += 1
            if hasattr(row, 'volume_filter'):
                if row.volume_filter:
                    debug_stats['passed_volume'] += 1
                else:
                    debug_stats['filtered_by_volume'] += 1
            # Check maintenance (may be named differently)
            in_maintenance = getattr(row, 'in_maintenance', False) or getattr(row, 'in_maintenance_', False)
            if not in_maintenance:
                debug_stats['passed_maintenance'] += 1
            else:
                debug_stats['filtered_by_maintenance'] += 1
        
        enter_long, enter_short = strategy.check_entry(row, df)
        
        if debug and (enter_long or enter_short):
            debug_stats['price_touched_trigger'] += 1
        
        if enter_long or enter_short:
            if debug:
                debug_stats['entries_made'] += 1
            direction = 1 if enter_long else -1
            entry_price = row.close
            position = strategy.setup_position(entry_price, direction, row, df)
            positions.append(position)
    
    # Final close
    for pos in positions:
        price = df.iloc[-1]['close']
        pnl = (price - pos['entry_price']) * pos['direction'] * 50
        trades.append(pos | {
            'exit_time': df.index[-1],
            'exit_price': price,
            'pnl': pnl,
            'reason': 'EOD'
        })
    
    # Metrics
    try:
        trades_df = pd.DataFrame(trades)
    except Exception as e:
        if not suppress_output:
            print(f"ERROR creating trades_df: {e}")
        return default_result.copy()
    
    if trades_df.empty:
        if not suppress_output:
            print("WARNING: No trades executed in backtest")
        result = default_result.copy()
        result['trades_df'] = trades_df
        return result
    
    # Daily equity (fill zero-PNL days)
    min_d = trades_df['exit_time'].min().date()
    max_d = trades_df['exit_time'].max().date()
    daily_pnl = trades_df.groupby(trades_df['exit_time'].dt.date)['pnl'].sum()\
                         .reindex(pd.date_range(min_d, max_d), fill_value=0)
    equity = 50000 + daily_pnl.cumsum()
    rets = equity.pct_change().dropna()
    
    # Calculate Sortino Ratio (only penalizes downside volatility)
    if len(rets) < 2:
        sortino = 0.0
    else:
        # Only consider negative returns for downside deviation
        downside_rets = rets[rets < 0]
        if len(downside_rets) == 0 or downside_rets.std() == 0:
            # No downside volatility - very good, but cap at reasonable maximum
            # Use a conservative estimate: assume minimal downside std (e.g., 0.001 = 0.1% daily)
            # This prevents unrealistic Sortino values while still rewarding low downside volatility
            min_downside_std = 0.001  # 0.1% daily downside volatility floor
            annualized_return = rets.mean() * 252
            sortino = (annualized_return / min_downside_std) if rets.mean() > 0 else 0.0
            # Cap Sortino to prevent extreme values (configurable from CSV)
            sortino_cap = param_dict_local.get('SORTINO_CAP', {}).get('value', 10.0)
            sortino = min(sortino, sortino_cap)
        else:
            downside_std = downside_rets.std()
            sortino = (rets.mean() / downside_std * np.sqrt(252)) if downside_std != 0 else 0.0
            # Cap Sortino to prevent extreme values (configurable from CSV)
            sortino_cap = param_dict_local.get('SORTINO_CAP', {}).get('value', 10.0)
            sortino = min(sortino, sortino_cap)
    
    # Max drawdown
    peak = 50000
    dd = 0
    for p in equity:
        if p > peak:
            peak = p
        else:
            dd = max(dd, peak - p)
    
    # Calculate avg_trades_day using TRADING DAYS, not calendar days
    # This gives accurate trades/day by excluding weekends and holidays
    # CRITICAL FIX: Use unique trading dates, not calendar days
    if not df.empty and hasattr(df.index, 'min') and hasattr(df.index, 'max'):
        # Count unique trading dates (excludes weekends/holidays)
        unique_dates = set(df.index.date)
        total_days = len(unique_dates) or 1
    elif not trades_df.empty:
        # Fallback: use unique dates from trades
        unique_dates = set()
        if 'entry_time' in trades_df.columns:
            unique_dates.update(trades_df['entry_time'].dt.date)
        if 'exit_time' in trades_df.columns:
            unique_dates.update(trades_df['exit_time'].dt.date)
        total_days = len(unique_dates) or 1
    else:
        total_days = 1
    
    avg_trades_day = len(trades_df) / total_days if total_days > 0 else 0
    
    # Profit factor
    avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean() if (trades_df['pnl'] > 0).any() else 0
    avg_loss = trades_df[trades_df['pnl'] < 0]['pnl'].mean() if (trades_df['pnl'] < 0).any() else 0
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    
    # Total profit (sum of all PNL)
    total_profit = trades_df['pnl'].sum() if not trades_df.empty else 0
    
    # Ensure all required keys are present
    result = {
        'sortino': sortino,
        'max_drawdown': dd,
        'avg_trades_day': avg_trades_day,
        'profit_factor': profit_factor,
        'total_profit': total_profit,
        'trades_df': trades_df
    }
    
    # Validate result has all required keys
    required_keys = ['sortino', 'max_drawdown', 'avg_trades_day', 'profit_factor', 'total_profit', 'trades_df']
    for key in required_keys:
        if key not in result:
            if not suppress_output:
                print(f"WARNING: Missing key '{key}' in result, using default")
            if key == 'trades_df':
                result[key] = pd.DataFrame()
            else:
                result[key] = 0
    
    return result

# ----------------------------------------------------------------------
# Multi-objective GA setup
# ----------------------------------------------------------------------
# Clear any existing creator classes to avoid conflicts
if hasattr(creator, "FitnessMulti"):
    del creator.FitnessMulti
if hasattr(creator, "Individual"):
    del creator.Individual

# Multi-objective fitness: (maximize Sortino, minimize Drawdown, maximize Profit Factor, maximize Avg Trades/Day, maximize Total Profit)
# Weights: (1.0, -1.0, 1.0, 5.0, 2.0)
# - Sortino: maximize (higher is better)
# - Max Drawdown: minimize (negated, so -1.0 weight means minimize)
# - Profit Factor: maximize (higher is better)
# - Avg Trades/Day: maximize (higher is better - we want more trades) - Weighted 5x to encourage trade frequency
# - Total Profit: maximize (higher is better - direct optimization for profitability) - Weighted 2x to incentivize profitability
creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 5.0, 2.0))
creator.create("Individual", list, fitness=creator.FitnessMulti)

def create_fitness_with_correct_weights():
    """Create a fitness object with 5 weights, ensuring compatibility."""
    # Check if FitnessMulti class has correct weights
    if hasattr(creator, 'FitnessMulti') and len(creator.FitnessMulti.weights) == 5:
        return creator.FitnessMulti()
    else:
        # Recreate the class if it has wrong weights
        if hasattr(creator, "FitnessMulti"):
            del creator.FitnessMulti
        creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 3.0, 1.0))
        return creator.FitnessMulti()

def clamp_individual(ind):
    """Clamp all parameters in an individual to their valid ranges and round integer parameters."""
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
    """
    Evaluate individual with multi-objective fitness.
    
    Returns:
        tuple: (sortino, -max_drawdown, profit_factor, avg_trades_day, total_profit)
        Note: Drawdown is negated because we want to minimize it (weights=-1.0)
        All other objectives are maximized (weights=1.0)
    """
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
    # ====================================================================
    # HARD CONSTRAINT: Minimum trades per day (< 1.0 = eliminated)
    # Solutions with < 1 trade/day are completely useless and must be eliminated
    # This is the ONLY hard constraint - all others use graduated penalties
    # ====================================================================
    min_trades = param_dict.get('MIN_TRADES_DAY', {'value': 1.0})['value']
    if avg_trades_day < min_trades:
        # Hard constraint: eliminate solutions with < 1 trade/day
        return (-float('inf'), float('inf'), -float('inf'), -float('inf'), -float('inf'))
    
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
    
    # 2. Unrealistic high win rate (overfitting indicator)
    if not trades_df.empty and win_rate > 0.95:
        # Gradual penalty based on how unrealistic
        excess_wr = (win_rate - 0.95) / 0.05  # 0 to 1 scale (95% to 100%)
        penalty_factor *= (1.0 - excess_wr * 0.3)  # Reduce by up to 30%
    
    # 3. Very short average trade duration (potential data issues)
    if not trades_df.empty and 'entry_time' in trades_df.columns and 'exit_time' in trades_df.columns:
        durations = (trades_df['exit_time'] - trades_df['entry_time']).dt.total_seconds() / 60
        avg_duration = durations.mean() if len(durations) > 0 else 0
        if avg_duration < 2.0:
            # Gradual penalty for very short trades
            penalty = (2.0 - avg_duration) / 2.0  # 0 to 1 scale
            penalty_factor *= (1.0 - penalty * 0.2)  # Reduce by up to 20%
    
    # 4. No TP enabled (gradual penalty, not elimination)
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
    # NORMALIZATION - Normalize objectives to 0-1 range before weighting
    # Based on research: Prevents one objective from dominating
    # Using reasonable fixed ranges (since we don't have population stats)
    # ====================================================================
    
    # Normalization ranges - loaded from CSV for configurability
    SORTINO_MAX = param_dict.get('NORM_SORTINO_MAX', {'value': 10.0})['value']
    DD_MAX = param_dict.get('NORM_DD_MAX', {'value': 100000.0})['value']
    PF_MAX = param_dict.get('NORM_PF_MAX', {'value': 5.0})['value']
    TRADES_MAX = param_dict.get('NORM_TRADES_MAX', {'value': 3.0})['value']
    PNL_MAX = param_dict.get('NORM_PNL_MAX', {'value': 200000.0})['value']
    
    # Normalize Sortino (0-1, higher is better)
    normalized_sortino = min(1.0, max(0.0, sortino / SORTINO_MAX))
    
    # Normalize Drawdown (0-1, inverted - lower is better)
    # Inverted: $0 DD = 1.0, $100K DD = 0.0
    normalized_dd = 1.0 - min(1.0, max(0.0, max_dd / DD_MAX))
    
    # Normalize Profit Factor (0-1, higher is better)
    normalized_pf = min(1.0, max(0.0, pf / PF_MAX))
    
    # Use RAW Avg Trades/Day (no normalization) - higher is better
    # CRITICAL: Removing normalization to make weight=100.0 actually effective
    # Target is 3.0 trades/day, so raw values (0.1, 0.5, 1.0, 3.0) are meaningful
    # If strategy can produce 40+ trades/day, raw values will be much larger
    normalized_trades = avg_trades_day  # Use raw value directly (not normalized)
    
    # Normalize Total Profit (0-1, higher is better)
    # Clamp to reasonable range to prevent extreme values from dominating
    normalized_pnl = min(1.0, max(0.0, total_pnl / PNL_MAX))
    
    # ====================================================================
    # CAP EXTREME VALUES (after normalization, before final return)
    # ====================================================================
    
    # Cap infinite or extreme profit factor
    if pf == float('inf') or pf > PF_MAX * 2:
        normalized_pf = 1.0  # Cap at maximum normalized value
    
    # Handle zero drawdown (add small artificial drawdown to prevent zero)
    if max_dd == 0.0 and not trades_df.empty and len(trades_df) > 10:
        # Add small penalty, but don't eliminate
        max_dd = 100.0  # Small artificial drawdown
        normalized_dd = 1.0 - (max_dd / DD_MAX)  # Re-normalize
    
    # ====================================================================
    # FINAL FLOOR VALUES - Apply at very end to ensure positive values
    # Reduced from 0.01 to 0.0001 to allow penalties to work
    # ====================================================================
    
    # Ensure positive values (but much smaller floor to allow penalties to work)
    normalized_sortino = max(0.0001, normalized_sortino)
    normalized_pf = max(0.0001, normalized_pf)
    normalized_dd = max(0.0001, normalized_dd)  # For minimization, this is fine
    # Floor for trades (raw value, so use actual minimum like 0.01)
    # Floor for trades (raw value, so use actual minimum like 0.01 trades/day)
    normalized_trades = max(0.01, normalized_trades)
    normalized_pnl = max(0.0001, normalized_pnl)  # Ensure positive for NSGA-II
    
    # Convert numpy types to Python floats (DEAP requires native Python types)
    normalized_sortino = float(normalized_sortino)
    normalized_dd = float(normalized_dd)
    normalized_pf = float(normalized_pf)
    normalized_trades = float(normalized_trades)
    normalized_pnl = float(normalized_pnl)
    
    # Return 5-objective fitness: (maximize sortino, minimize drawdown, maximize profit_factor, maximize avg_trades_day, maximize total_profit)
    # Note: normalized_dd is already inverted (lower DD = higher value), so we return it as-is for minimization
    # DEAP will apply weights: (1.0, -1.0, 1.0, 3.0, 1.0)
    return (normalized_sortino, normalized_dd, normalized_pf, normalized_trades, normalized_pnl)

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
# Module-level function for multiprocessing (must be at module level to be picklable)
def _evaluate_worker(args):
    """
    Worker function for parallel evaluation. Must be at module level for pickling.
    
    Args:
        args: Tuple of (individual, df, param_dict, param_keys)
        
    Returns:
        Fitness tuple: (sortino, max_dd, pf, avg_trades_day, total_profit)
    """
    ind, df_local, param_dict_local, param_keys_local = args
    
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
    # HARD CONSTRAINT: Minimum trades per day (< 1.0 = eliminated)
    # Solutions with < 1 trade/day are completely useless and must be eliminated
    # This is the ONLY hard constraint - all others use graduated penalties
    # ====================================================================
    min_trades = param_dict_local.get('MIN_TRADES_DAY', {'value': 1.0})['value']
    if avg_trades_day < min_trades:
        # Hard constraint: eliminate solutions with < 1 trade/day
        return (-float('inf'), float('inf'), -float('inf'), -float('inf'), -float('inf'))
    
    # Check trade frequency constraints (use values from param_dict_local)
    target_trades = param_dict_local.get('TARGET_TRADES_DAY', {'value': 2})['value']
    min_trades = param_dict_local.get('MIN_TRADES_DAY', {'value': 1.0})['value']
    avg_trades_day = metrics['avg_trades_day']
    
    # ====================================================================
    # HARD CONSTRAINT: Minimum trades per day (< 1.0 = eliminated)
    # Solutions with < 1 trade/day are completely useless and must be eliminated
    # This is the ONLY hard constraint - all others use graduated penalties
    # ====================================================================
    if avg_trades_day < min_trades:
        # Hard constraint: eliminate solutions with < 1 trade/day
        return (-float('inf'), float('inf'), -float('inf'), -float('inf'), -float('inf'))
    
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
    # NORMALIZATION - Normalize objectives to 0-1 range
    # ====================================================================
    
    # Normalization ranges - loaded from param_dict (passed from main process)
    SORTINO_MAX = param_dict_local.get('NORM_SORTINO_MAX', {}).get('value', 10.0)
    DD_MAX = param_dict_local.get('NORM_DD_MAX', {}).get('value', 100000.0)
    PF_MAX = param_dict_local.get('NORM_PF_MAX', {}).get('value', 5.0)
    TRADES_MAX = param_dict_local.get('NORM_TRADES_MAX', {}).get('value', 3.0)
    PNL_MAX = param_dict_local.get('NORM_PNL_MAX', {}).get('value', 200000.0)
    
    normalized_sortino = min(1.0, max(0.0, sortino / SORTINO_MAX))
    normalized_dd = 1.0 - min(1.0, max(0.0, max_dd / DD_MAX))
    normalized_pf = min(1.0, max(0.0, pf / PF_MAX))
    normalized_trades = min(1.0, max(0.0, avg_trades_day / TRADES_MAX))
    normalized_pnl = min(1.0, max(0.0, total_pnl / PNL_MAX))
    
    # ====================================================================
    # CAP EXTREME VALUES
    # ====================================================================
    
    if pf == float('inf') or pf > PF_MAX * 2:
        normalized_pf = 1.0
    
    if max_dd == 0.0 and not trades_df.empty and len(trades_df) > 10:
        max_dd = 100.0
        normalized_dd = 1.0 - (max_dd / DD_MAX)
    
    # ====================================================================
    # FINAL FLOOR VALUES
    # ====================================================================
    
    normalized_sortino = max(0.0001, normalized_sortino)
    normalized_pf = max(0.0001, normalized_pf)
    normalized_dd = max(0.0001, normalized_dd)
    # Floor for trades (raw value, so use actual minimum like 0.01)
    # Floor for trades (raw value, so use actual minimum like 0.01 trades/day)
    normalized_trades = max(0.01, normalized_trades)
    normalized_pnl = max(0.0001, normalized_pnl)  # Ensure positive for NSGA-II
    
    # Convert numpy types to Python floats (DEAP requires native Python types)
    normalized_sortino = float(normalized_sortino)
    normalized_dd = float(normalized_dd)
    normalized_pf = float(normalized_pf)
    normalized_trades = float(normalized_trades)
    normalized_pnl = float(normalized_pnl)
    
    return (normalized_sortino, normalized_dd, normalized_pf, normalized_trades, normalized_pnl)

def parallel_evaluate(individuals, df, param_dict_local, param_keys_local):
    """
    Evaluate individuals in parallel.
    
    Args:
        individuals: List of individuals to evaluate
        df: DataFrame with market data
        param_dict_local: Parameter dictionary (passed to avoid global access in workers)
        param_keys_local: Parameter keys (passed to avoid global access in workers)
        
    Returns:
        List of fitness tuples
    """
    # Check if interrupt was requested
    if interrupt_flag.is_set():
        raise KeyboardInterrupt("Interrupt requested")
    
    pool = multiprocessing.Pool(processes=NUM_WORKERS)
    try:
        # Use map_async with timeout for better interrupt handling
        # Pass all necessary data to the worker function
        async_result = pool.map_async(_evaluate_worker, 
                                     [(ind, df, param_dict_local, param_keys_local) for ind in individuals])
        # Wait with timeout to allow interruption - check flag periodically
        try:
            # Use shorter timeout and check interrupt flag
            timeout = 60  # Check every 60 seconds
            while not async_result.ready():
                if interrupt_flag.is_set():
                    print("\n  Interrupt received, terminating workers...")
                    pool.terminate()
                    pool.join()
                    raise KeyboardInterrupt("Interrupt requested")
                async_result.wait(timeout=timeout)
            results = async_result.get(timeout=1)  # Get results immediately since ready
        except KeyboardInterrupt:
            print("\n  Interrupt received, terminating workers...")
            pool.terminate()
            pool.join()
            raise
        return results
    finally:
        pool.close()
        pool.join()

# ----------------------------------------------------------------------
# HTML Dashboard Generation
# ----------------------------------------------------------------------
def generate_html_dashboard(hof, best, best_params, best_fitness, param_keys, param_dict,
                            logbook, is_res, oos_res, trades_is, trades_oos,
                            html_path, diag_dir, current_gen=None, total_gen=None, 
                            is_final=False, auto_launch=False, is_periods=None, oos_periods=None,
                            in_sample=None):
    """
    Generate comprehensive interactive HTML dashboard for GA results.
    
    Args:
        current_gen: Current generation number (for progress tracking)
        total_gen: Total number of generations
        is_final: Whether this is the final generation
        auto_launch: Whether to auto-launch the HTML file
    """
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
    
    # Helper function to clamp parameters
    def clamp_params(raw_params, param_dict_local):
        """Clamp parameters to valid ranges."""
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
    
    # Extract Pareto front data with clamped parameters
    pareto_data = []
    
    for i, ind in enumerate(hof):
        raw_params = dict(zip(param_keys, ind))
        clamped_params = clamp_params(raw_params, param_dict)
        fitness = ind.fitness.values
        
        # avg_trades_day is the 4th element in fitness tuple (fitness[3])
        # total_profit is the 5th element in fitness tuple (fitness[4])
        # No need to recalculate - they're already in the fitness values
        avg_trades_day = fitness[3] if len(fitness) > 3 else 0.0
        total_profit = fitness[4] if len(fitness) > 4 else 0.0
        
        pareto_data.append({
            'index': i,
            'sortino': fitness[0],
            'max_dd': fitness[1],
            'profit_factor': fitness[2],
            'avg_trades_day': avg_trades_day,
            'total_profit': total_profit,
            'params': clamped_params,  # Use clamped parameters
            'is_selected': (ind == best)
        })
    
    pareto_df = pd.DataFrame(pareto_data)
    
    # Sort by different criteria for top candidates
    top_sortino = pareto_df.nlargest(5, 'sortino')
    top_pf = pareto_df.nlargest(5, 'profit_factor')
    top_dd = pareto_df.nsmallest(5, 'max_dd')
    
    # Create convergence plots (5 objectives: Sortino, Drawdown, Profit Factor, Avg Trades/Day, Total Profit)
    gens = logbook.select("gen")
    fig_convergence = make_subplots(rows=3, cols=2,
        subplot_titles=('Sortino Convergence', 'Drawdown Convergence', 'Profit Factor Convergence', 'Avg Trades/Day Convergence', 'Total Profit Convergence', ''))
    
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
    
    fig_convergence.update_layout(height=900, showlegend=True, title_text="Convergence Plots")
    fig_convergence.update_xaxes(title_text="Generation", row=2, col=1)
    fig_convergence.update_xaxes(title_text="Generation", row=2, col=2)
    fig_convergence.update_xaxes(title_text="Generation", row=3, col=1)
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
    
    if showing_actual:
        fig_convergence.update_yaxes(title_text="Sortino Ratio (Actual)", row=1, col=1)
    else:
        fig_convergence.update_yaxes(title_text="Sortino (Normalized 0-1)", row=1, col=1)
    
    if 'actual_dd_best' in logbook.header:
        fig_convergence.update_yaxes(title_text="Max Drawdown ($)", row=1, col=2)
    else:
        fig_convergence.update_yaxes(title_text="Drawdown (Normalized 0-1, inverted)", row=1, col=2)
    fig_convergence.update_yaxes(title_text="Profit Factor", row=2, col=1)
    fig_convergence.update_yaxes(title_text="Avg Trades/Day", row=2, col=2)
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
    pareto_table_html = """<table class='pareto-table'><thead><tr>
        <th>Rank<span class="tooltip-icon">?</span><span class="tooltip">Ranking by Sortino Ratio (highest to lowest). Lower rank = better risk-adjusted returns.</span></th>
        <th>Sortino<span class="tooltip-icon">?</span><span class="tooltip">Sortino Ratio (NORMALIZED FITNESS VALUE, 0-1 range, NOT actual Sortino). Values of -1000 indicate hard constraint penalty (solution eliminated). To see actual Sortino, check 'Actual Backtest Results' section.</span></th>
        <th>Max DD<span class="tooltip-icon">?</span><span class="tooltip">Max Drawdown (NORMALIZED FITNESS VALUE, 0-1 range, NOT actual dollars). Lower is better. To see actual drawdown, check 'Actual Backtest Results' section.</span></th>
        <th>PF<span class="tooltip-icon">?</span><span class="tooltip">Profit Factor (NORMALIZED FITNESS VALUE, 0-1 range, NOT actual PF). To see actual Profit Factor, check 'Actual Backtest Results' section.</span></th>
        <th>Avg Trades/Day<span class="tooltip-icon">?</span><span class="tooltip">Average trades per day (RAW VALUE, actual trades/day). This is NOT normalized and shows real trade frequency.</span></th>
        <th>Total Profit<span class="tooltip-icon">?</span><span class="tooltip">Total Profit (NORMALIZED FITNESS VALUE, 0-1 range, NOT actual dollars). To see actual PNL, check 'Actual Backtest Results' section.</span></th>
        <th>Selected<span class="tooltip-icon">?</span><span class="tooltip">★ indicates the solution selected for use (highest Sortino Ratio).</span></th>
    </tr></thead><tbody>"""
    pareto_sorted = sorted(pareto_data, key=lambda x: x['sortino'], reverse=True)
    for rank, sol in enumerate(pareto_sorted, 1):
        mark = "★" if sol['is_selected'] else ""
        avg_trades = sol.get('avg_trades_day', 0.0)
        total_profit = sol.get('total_profit', 0.0)
        pareto_table_html += f"<tr class='{'selected-row' if sol['is_selected'] else ''}'><td>{rank}</td><td>{sol['sortino']:.4f}</td><td>{sol['max_dd']:.2f}</td><td>{sol['profit_factor']:.4f}</td><td>{avg_trades:.3f}</td><td>{total_profit:.4f}</td><td>{mark}</td></tr>"
    pareto_table_html += "</tbody></table>"
    
    # Helper function to extract chart HTML (needed for parameter analysis)
    def extract_chart_html(html_snippet):
        """Extract div and script tags from Plotly HTML output.
        
        Plotly's to_html() returns HTML like:
        <div>
            <div id="chart_id" class="plotly-graph-div"></div>
            <script>...</script>
        </div>
        
        We extract:
        - The inner chart div (with id attribute) for placement in the page
        - The script separately for placement before </body>
        """
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
        
        # Extract script separately - search the entire snippet
        # Plotly HTML has the script AFTER the div, so search from after the div
        script_start = html_snippet.find('<script')
        if script_start == -1:
            # Try case-insensitive search
            html_lower = html_snippet.lower()
            script_start_lower = html_lower.find('<script')
            if script_start_lower != -1:
                script_start = script_start_lower
            else:
                return div_part, ""
        
        # Find the closing script tag
        script_end = html_snippet.find('</script>', script_start)
        if script_end == -1:
            # Try case-insensitive
            script_end_lower = html_snippet.lower().find('</script>', script_start)
            if script_end_lower != -1:
                script_end = script_end_lower
            else:
                return div_part, ""
        
        script_part = html_snippet[script_start:script_end + 9]
        return div_part, script_part
    
    # ====================================================================
    # PARAMETER ANALYSIS VISUALIZATIONS
    # ====================================================================
    # Generate parameter analysis charts (correlation, importance, distributions)
    # Use same pattern as working charts: separate divs and scripts, place scripts at end
    param_analysis_html = ""
    param_analysis_scripts = ""  # Will be placed before </body> like other charts
    
    try:
        # Filter out GA criteria parameters
        GA_CRITERIA_PARAMS = {
            'POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
            'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
            'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
            'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT', 'NORM_SORTINO_MAX', 'NORM_DD_MAX',
            'NORM_PF_MAX', 'NORM_TRADES_MAX', 'NORM_PNL_MAX', 'MIN_WIN_RATE', 'SORTINO_CAP'
        }
        
        # Extract parameter values and fitness from Hall of Fame
        # If param_keys is not provided or empty, derive it from param_dict
        if not param_keys or len(param_keys) == 0:
            param_keys_local = [k for k in param_dict.keys() if param_dict[k].get('type') != 'fixed']
        else:
            param_keys_local = param_keys
        
        param_data = []
        for i, ind in enumerate(hof):
            if hasattr(ind, 'fitness') and ind.fitness.valid:
                fitness = ind.fitness.values
                if len(fitness) >= 5:
                    row = {
                        'solution_id': i,
                        'sortino': fitness[0],
                        'drawdown': fitness[1],
                        'profit_factor': fitness[2],
                        'avg_trades_day': fitness[3],
                        'total_profit': fitness[4]
                    }
                    # Add parameter values (only strategy parameters) - CLAMP them like in _evaluate_worker
                    for j, param_name in enumerate(param_keys_local):
                        if j < len(ind) and param_name not in GA_CRITERIA_PARAMS:
                            raw_value = ind[j]
                            # Clamp to valid range (same as _evaluate_worker)
                            if param_name in param_dict:
                                param_info = param_dict[param_name]
                                param_min = param_info.get('min', None)
                                param_max = param_info.get('max', None)
                                param_type = param_info.get('type', 'float')
                                
                                # Only clamp numeric parameters
                                if param_type in ['int', 'float'] and param_min is not None and param_max is not None:
                                    try:
                                        # Clamp value
                                        clamped_value = max(param_min, min(raw_value, param_max))
                                        
                                        # Cast to appropriate type
                                        if param_type == 'int':
                                            clamped_value = int(round(clamped_value))
                                        else:
                                            clamped_value = float(clamped_value)
                                        
                                        row[param_name] = clamped_value
                                    except (TypeError, ValueError):
                                        # If clamping fails, use raw value
                                        row[param_name] = raw_value
                                else:
                                    # Non-numeric or fixed parameters - use as-is
                                    row[param_name] = raw_value
                            else:
                                row[param_name] = raw_value
                    param_data.append(row)
        
        if len(param_data) > 5:  # Need enough solutions for meaningful analysis
            param_df_analysis = pd.DataFrame(param_data)
            
            # Filter to only parameters that exist in dataframe and have variation
            available_params = []
            for p in param_keys_local:
                if p in param_df_analysis.columns and p not in GA_CRITERIA_PARAMS:
                    # Check if parameter has variation (not all same value)
                    if param_df_analysis[p].nunique() > 1:  # At least 2 unique values
                        available_params.append(p)
            
            # Debug output
            print(f"  Parameter Analysis Debug:")
            print(f"    Total solutions: {len(param_data)}")
            print(f"    DataFrame shape: {param_df_analysis.shape}")
            print(f"    DataFrame columns: {list(param_df_analysis.columns)[:10]}...")
            print(f"    Metrics in dataframe: sortino={('sortino' in param_df_analysis.columns)}, drawdown={('drawdown' in param_df_analysis.columns)}, profit_factor={('profit_factor' in param_df_analysis.columns)}")
            
            # Check if metrics have variation
            if 'sortino' in param_df_analysis.columns:
                print(f"    Sortino range: {param_df_analysis['sortino'].min():.6f} to {param_df_analysis['sortino'].max():.6f}")
                print(f"    Sortino unique values: {param_df_analysis['sortino'].nunique()}")
            if 'drawdown' in param_df_analysis.columns:
                print(f"    Drawdown range: {param_df_analysis['drawdown'].min():.6f} to {param_df_analysis['drawdown'].max():.6f}")
            if 'profit_factor' in param_df_analysis.columns:
                print(f"    Profit Factor range: {param_df_analysis['profit_factor'].min():.6f} to {param_df_analysis['profit_factor'].max():.6f}")
            
            print(f"    Total param_keys: {len(param_keys_local)}")
            print(f"    Available params (with variation): {len(available_params)}")
            if len(available_params) > 0:
                print(f"    Sample available params: {available_params[:5]}")
                # Show sample values for first available param
                first_param = available_params[0]
                print(f"    Sample values for '{first_param}': min={param_df_analysis[first_param].min():.3f}, max={param_df_analysis[first_param].max():.3f}, unique={param_df_analysis[first_param].nunique()}")
            else:
                print(f"    WARNING: No parameters with variation found!")
                print(f"    Checking first few param_keys: {param_keys_local[:10]}")
                print(f"    Checking first few columns in df: {list(param_df_analysis.columns)[:10]}")
                # Show why params don't have variation
                for p in param_keys_local[:5]:
                    if p in param_df_analysis.columns:
                        print(f"      '{p}': unique={param_df_analysis[p].nunique()}, sample values={list(param_df_analysis[p].unique()[:3])}")
            
            if len(available_params) > 0:
                print(f"    Generating charts for {len(available_params)} parameters with variation")
                # 1. Correlation Heatmap
                metrics = ['sortino', 'drawdown', 'profit_factor', 'avg_trades_day', 'total_profit']
                correlation_matrix = pd.DataFrame(index=available_params, columns=metrics)
                
                for param in available_params:
                    for metric in metrics:
                        try:
                            corr = np.corrcoef(param_df_analysis[param], param_df_analysis[metric])[0, 1]
                            if not np.isnan(corr):
                                correlation_matrix.loc[param, metric] = corr
                            else:
                                correlation_matrix.loc[param, metric] = 0.0
                        except:
                            correlation_matrix.loc[param, metric] = 0.0
                
                correlation_matrix = correlation_matrix.astype(float)
                
                # DEBUG: Check if correlation matrix has valid data
                print(f"    Correlation matrix shape: {correlation_matrix.shape}")
                print(f"    Correlation matrix non-null count: {correlation_matrix.notna().sum().sum()}")
                print(f"    Correlation matrix min/max: {correlation_matrix.min().min():.3f} / {correlation_matrix.max().max():.3f}")
                print(f"    Sample correlation values (first 3x3):")
                print(correlation_matrix.iloc[:3, :3])
                
                # Check if all values are zero or NaN
                if correlation_matrix.isna().all().all() or (correlation_matrix == 0).all().all():
                    print(f"    WARNING: Correlation matrix is all zeros or NaN! Charts will be empty.")
                    print(f"    This suggests parameter values or metrics are not varying.")
                
                # Convert to lists/arrays for Plotly
                z_values = correlation_matrix.values.tolist()
                x_labels = correlation_matrix.columns.tolist()
                y_labels = correlation_matrix.index.tolist()
                text_values = correlation_matrix.values.round(2).tolist()
                
                fig_corr = go.Figure(data=go.Heatmap(
                    z=z_values,
                    x=x_labels,
                    y=y_labels,
                    colorscale='RdBu',
                    zmid=0,
                    text=text_values,
                    texttemplate='%{text}',
                    textfont={"size": 9},
                    colorbar=dict(title="Correlation")
                ))
                
                fig_corr.update_layout(
                    title="Parameter-Metric Correlation Heatmap",
                    xaxis_title="Metrics",
                    yaxis_title="Parameters",
                    height=max(400, len(available_params) * 15),
                    width=700
                )
                
                # DEBUG: Check figure data before JSON conversion
                print(f"    Figure data length: {len(fig_corr.data)}")
                if len(fig_corr.data) > 0:
                    z_data = fig_corr.data[0].z
                    print(f"    Heatmap z data shape: {z_data.shape if hasattr(z_data, 'shape') else 'N/A'}")
                    print(f"    Heatmap z data type: {type(z_data)}")
                    if hasattr(z_data, '__len__') and len(z_data) > 0:
                        print(f"    Heatmap z data sample (first row): {z_data[0] if hasattr(z_data, '__getitem__') else 'N/A'}")
                
                # Use JSON format and create chart with JavaScript directly (more reliable)
                corr_json = fig_corr.to_json()
                
                # DEBUG: Check JSON size
                print(f"    Correlation chart JSON size: {len(corr_json)} chars")
                if len(corr_json) < 1000:
                    print(f"    WARNING: JSON is very small, may be empty!")
                # Check if JSON contains actual data
                if '"z":null' in corr_json or '"z":[]' in corr_json:
                    print(f"    WARNING: JSON contains null or empty z data!")
                corr_div = '<div id="param_correlation_chart" class="plotly-graph-div" style="height:400px; width:700px;"></div>'
                corr_script = f'''<script type="text/javascript">
                console.log("=== PARAM CORRELATION CHART SCRIPT LOADED ===");
                (function() {{
                    function renderCorrelationChart() {{
                        console.log("renderCorrelationChart() executing...");
                        var chartDiv = document.getElementById("param_correlation_chart");
                            console.log("Chart div found:", chartDiv !== null);
                            console.log("Plotly available:", typeof Plotly !== 'undefined');
                            if (!chartDiv) {{
                                console.error("ERROR: param_correlation_chart div not found!");
                                return;
                            }}
                            if (typeof Plotly === 'undefined') {{
                                console.error("ERROR: Plotly is not defined!");
                                return;
                            }}
                            console.log("Div dimensions BEFORE render:", chartDiv.offsetWidth, "x", chartDiv.offsetHeight);
                            console.log("Div computed style BEFORE render:", window.getComputedStyle(chartDiv).display);
                            try {{
                                console.log("Creating figure from JSON...");
                                var figure = JSON.parse({corr_json!r});
                                console.log("Figure created. Data length:", figure.data ? figure.data.length : 0);
                                console.log("Calling Plotly.newPlot...");
                                Plotly.newPlot("param_correlation_chart", figure.data, figure.layout, {{"responsive": true}});
                                console.log("SUCCESS: param_correlation_chart rendered!");
                                // Check dimensions AFTER render
                                setTimeout(function() {{
                                    var div = document.getElementById("param_correlation_chart");
                                    if (div) {{
                                        console.log("Div dimensions AFTER render:", div.offsetWidth, "x", div.offsetHeight);
                                        console.log("Div computed style AFTER render:", window.getComputedStyle(div).display);
                                        var plotlyDiv = div.querySelector(".js-plotly-plot");
                                        if (plotlyDiv) {{
                                            console.log("Plotly inner div found, dimensions:", plotlyDiv.offsetWidth, "x", plotlyDiv.offsetHeight);
                                        }} else {{
                                            console.warn("Plotly inner div NOT found!");
                                        }}
                                    }}
                                }}, 100);
                            }} catch(e) {{
                                console.error("EXCEPTION rendering param_correlation_chart:", e);
                                console.error("Stack:", e.stack);
                            }}
                    }}
                    console.log("Document readyState:", document.readyState);
                    if (document.readyState === 'loading') {{
                        console.log("Waiting for DOMContentLoaded...");
                        document.addEventListener('DOMContentLoaded', function() {{
                            console.log("DOMContentLoaded fired, calling renderCorrelationChart");
                            renderCorrelationChart();
                        }});
                    }} else {{
                        console.log("DOM already ready, calling renderCorrelationChart immediately");
                        renderCorrelationChart();
                    }}
                }})();
                </script>'''
                param_analysis_html += corr_div + "\n"
                param_analysis_scripts += corr_script
                
                # 1b. Parameter Convergence vs Sortino (Top 12 most variable parameters)
                try:
                    # Select top parameters to visualize (most variable)
                    param_variance = param_df_analysis[available_params].var().sort_values(ascending=False)
                    top_12_params = param_variance.head(12).index.tolist()
                    
                    if len(top_12_params) > 0:
                        fig_conv = make_subplots(
                            rows=4, cols=3,
                            subplot_titles=[f'{p}' for p in top_12_params],
                            vertical_spacing=0.08,
                            horizontal_spacing=0.1
                        )
                        
                        for idx, param in enumerate(top_12_params):
                            row = (idx // 3) + 1
                            col = (idx % 3) + 1
                            
                            # Scatter: parameter value vs Sortino
                            # Convert pandas Series to lists for Plotly
                            x_values = param_df_analysis[param].tolist()
                            y_values = param_df_analysis['sortino'].tolist()
                            color_values = param_df_analysis['avg_trades_day'].tolist()
                            
                            fig_conv.add_trace(
                                go.Scatter(
                                    x=x_values,
                                    y=y_values,
                                    mode='markers',
                                    marker=dict(size=5, opacity=0.6, color=color_values, 
                                              colorscale='Viridis', showscale=(idx==0),
                                              colorbar=dict(title="Trades/Day", x=1.02)),
                                    name=param,
                                    showlegend=False
                                ),
                                row=row, col=col
                            )
                            
                            # Add trend line
                            try:
                                x_vals = param_df_analysis[param].values
                                y_vals = param_df_analysis['sortino'].values
                                z = np.polyfit(x_vals, y_vals, 1)
                                p = np.poly1d(z)
                                x_trend = np.linspace(x_vals.min(), x_vals.max(), 100)
                                fig_conv.add_trace(
                                    go.Scatter(
                                        x=x_trend,
                                        y=p(x_trend),
                                        mode='lines',
                                        line=dict(color='red', width=2, dash='dash'),
                                        name='Trend',
                                        showlegend=False
                                    ),
                                    row=row, col=col
                                )
                            except:
                                pass  # Skip trend line if can't fit
                            
                            fig_conv.update_xaxes(title_text=param, row=row, col=col)
                            fig_conv.update_yaxes(title_text="Sortino", row=row, col=col)
                        
                        fig_conv.update_layout(
                            height=1000,
                            title_text="Parameter vs Sortino (Top 12 Most Variable Parameters)",
                            showlegend=False
                        )
                        
                        # Use JSON format and create chart with JavaScript directly
                        conv_json = fig_conv.to_json()
                        conv_div = '<div id="param_convergence_chart" class="plotly-graph-div" style="height:1000px; width:100%;"></div>'
                        conv_script = f'''<script type="text/javascript">
                        console.log("=== PARAM CONVERGENCE CHART SCRIPT LOADED ===");
                        (function() {{
                            function renderConvergenceChart() {{
                                console.log("renderConvergenceChart() executing...");
                                var chartDiv = document.getElementById("param_convergence_chart");
                                console.log("Chart div found:", chartDiv !== null);
                                if (chartDiv) {{
                                console.log("Div dimensions:", chartDiv.offsetWidth, "x", chartDiv.offsetHeight);
                                console.log("Div computed style display:", window.getComputedStyle(chartDiv).display);
                                console.log("Div computed style visibility:", window.getComputedStyle(chartDiv).visibility);
                                console.log("Div computed style height:", window.getComputedStyle(chartDiv).height);
                                console.log("Div computed style width:", window.getComputedStyle(chartDiv).width);
                                }}
                                if (chartDiv && typeof Plotly !== 'undefined') {{
                                    try {{
                                        var figure = JSON.parse({conv_json!r});
                                        console.log("Calling Plotly.newPlot for convergence chart...");
                                        Plotly.newPlot("param_convergence_chart", figure.data, figure.layout, {{"responsive": true}});
                                        console.log("SUCCESS: param_convergence_chart rendered!");
                                    }} catch(e) {{
                                        console.error("EXCEPTION rendering param_convergence_chart:", e);
                                    }}
                                }}
                            }}
                            if (document.readyState === 'loading') {{
                                document.addEventListener('DOMContentLoaded', renderConvergenceChart);
                            }} else {{
                                renderConvergenceChart();
                            }}
                        }})();
                        </script>'''
                        param_analysis_html += "\n" + conv_div + "\n"
                        param_analysis_scripts += conv_script
                except Exception as e:
                    print(f"  Warning: Could not generate parameter convergence chart: {e}")
                
                # 2. Parameter Importance (Top 10)
                top_10 = None
                sensitivity_df = None
                try:
                    sensitivity_data = []
                    df_sorted = param_df_analysis.sort_values('sortino', ascending=False)
                    top_25_pct = df_sorted.head(max(1, len(df_sorted) // 4))
                    bottom_25_pct = df_sorted.tail(max(1, len(df_sorted) // 4))
                    
                    for param in available_params:
                        # Skip non-numeric parameters (strings, etc.)
                        if param_df_analysis[param].dtype not in ['int64', 'float64', 'int32', 'float32']:
                            try:
                                # Try to convert to numeric, skip if fails
                                pd.to_numeric(param_df_analysis[param], errors='raise')
                            except:
                                continue  # Skip this parameter
                        
                        try:
                            corr_sortino = np.corrcoef(param_df_analysis[param], param_df_analysis['sortino'])[0, 1]
                            if np.isnan(corr_sortino):
                                corr_sortino = 0.0
                        except:
                            corr_sortino = 0.0
                        
                        if len(top_25_pct) > 0 and len(bottom_25_pct) > 0:
                            try:
                                top_mean = top_25_pct[param].mean()
                                bottom_mean = bottom_25_pct[param].mean()
                                param_range = param_df_analysis[param].max() - param_df_analysis[param].min()
                                if param_range > 1e-10:
                                    diff_pct = abs((top_mean - bottom_mean) / param_range) * 100
                                else:
                                    diff_pct = 0
                            except:
                                diff_pct = 0
                        else:
                            diff_pct = 0
                        
                        try:
                            param_min = param_dict.get(param, {}).get('min', 0)
                            param_max = param_dict.get(param, {}).get('max', 1)
                            param_range_actual = param_max - param_min
                            if param_range_actual > 1e-10:
                                range_used = (param_df_analysis[param].max() - param_df_analysis[param].min()) / param_range_actual * 100
                                std_pct = (param_df_analysis[param].std() / param_range_actual) * 100
                            else:
                                range_used = 0
                                std_pct = 0
                        except:
                            range_used = 0
                            std_pct = 0
                        
                        importance_score = abs(corr_sortino) * 0.4 + diff_pct * 0.3 + range_used * 0.2 + std_pct * 0.1
                        
                        sensitivity_data.append({
                            'parameter': param,
                            'importance_score': importance_score,
                            'correlation_with_sortino': abs(corr_sortino)
                        })
                    
                    if len(sensitivity_data) > 0:
                        sensitivity_df = pd.DataFrame(sensitivity_data)
                        sensitivity_df = sensitivity_df.sort_values('importance_score', ascending=False)
                        top_10 = sensitivity_df.head(10)
                    
                        fig_importance = go.Figure()
                        fig_importance.add_trace(go.Bar(
                            y=top_10['parameter'],
                            x=top_10['importance_score'],
                            orientation='h',
                            marker=dict(color=top_10['importance_score'], colorscale='Viridis'),
                            text=[f"{s:.2f}" for s in top_10['importance_score']],
                            textposition='outside'
                        ))
                        
                        fig_importance.update_layout(
                            title="Parameter Importance (Top 10)",
                            xaxis_title="Importance Score",
                            yaxis_title="Parameter",
                            height=400,
                            width=700
                        )
                        
                        # Use JSON format and create chart with JavaScript directly
                        imp_json = fig_importance.to_json()
                        imp_div = '\n<div id="param_importance_chart" class="plotly-graph-div" style="height:400px; width:700px;"></div>\n'
                        imp_script = f'''<script type="text/javascript">
                        console.log("=== PARAM IMPORTANCE CHART SCRIPT LOADED ===");
                        (function() {{
                            function renderImportanceChart() {{
                                console.log("renderImportanceChart() executing...");
                                var chartDiv = document.getElementById("param_importance_chart");
                                console.log("Chart div found:", chartDiv !== null);
                                if (chartDiv && typeof Plotly !== 'undefined') {{
                                    try {{
                                        var figure = JSON.parse({imp_json!r});
                                        console.log("Calling Plotly.newPlot for importance chart...");
                                        Plotly.newPlot("param_importance_chart", figure.data, figure.layout, {{"responsive": true}});
                                        console.log("SUCCESS: param_importance_chart rendered!");
                                    }} catch(e) {{
                                        console.error("EXCEPTION rendering param_importance_chart:", e);
                                    }}
                                }}
                            }}
                            if (document.readyState === 'loading') {{
                                document.addEventListener('DOMContentLoaded', renderImportanceChart);
                            }} else {{
                                renderImportanceChart();
                            }}
                        }})();
                        </script>'''
                        param_analysis_html += imp_div
                        param_analysis_scripts += imp_script
                except Exception as e:
                    import traceback
                    print(f"  Warning: Could not generate parameter importance chart: {e}")
                    print(f"  Traceback: {traceback.format_exc()}")
                
                # 3. Parameter Distributions (Top 6 most important parameters)
                try:
                    if top_10 is not None and len(top_10) >= 3 and len(top_25_pct) > 0 and len(bottom_25_pct) > 0:
                        top_6_params = sensitivity_df.head(6)['parameter'].tolist()
                        fig_dist = make_subplots(
                            rows=2, cols=3,
                            subplot_titles=[f'{p}' for p in top_6_params],
                            vertical_spacing=0.12,
                            horizontal_spacing=0.1
                        )
                        
                        for idx, param in enumerate(top_6_params):
                            row = (idx // 3) + 1
                            col = (idx % 3) + 1
                            
                            # Top 25% solutions - convert to list
                            fig_dist.add_trace(
                                go.Histogram(
                                    x=top_25_pct[param].tolist(),
                                    name='Top 25%',
                                    opacity=0.7,
                                    marker_color='green',
                                    nbinsx=15,
                                    showlegend=(idx==0)
                                ),
                                row=row, col=col
                            )
                            
                            # Bottom 25% solutions - convert to list
                            fig_dist.add_trace(
                                go.Histogram(
                                    x=bottom_25_pct[param].tolist(),
                                    name='Bottom 25%',
                                    opacity=0.7,
                                    marker_color='red',
                                    nbinsx=15,
                                    showlegend=(idx==0)
                                ),
                                row=row, col=col
                            )
                            
                            fig_dist.update_xaxes(title_text=param, row=row, col=col)
                            fig_dist.update_yaxes(title_text="Count", row=row, col=col)
                        
                        fig_dist.update_layout(
                            height=600,
                            title_text="Parameter Distributions: Top 25% vs Bottom 25% Solutions (Top 6 Parameters)",
                            barmode='overlay'
                        )
                        
                        # Use JSON format and create chart with JavaScript directly
                        dist_json = fig_dist.to_json()
                        dist_div = '\n<div id="param_distributions_chart" class="plotly-graph-div" style="height:600px; width:100%;"></div>\n'
                        dist_script = f'''<script type="text/javascript">
                        console.log("=== PARAM DISTRIBUTIONS CHART SCRIPT LOADED ===");
                        (function() {{
                            function renderDistributionsChart() {{
                                console.log("renderDistributionsChart() executing...");
                                var chartDiv = document.getElementById("param_distributions_chart");
                                console.log("Chart div found:", chartDiv !== null);
                                if (chartDiv && typeof Plotly !== 'undefined') {{
                                    try {{
                                        var figure = JSON.parse({dist_json!r});
                                        console.log("Calling Plotly.newPlot for distributions chart...");
                                        Plotly.newPlot("param_distributions_chart", figure.data, figure.layout, {{"responsive": true}});
                                        console.log("SUCCESS: param_distributions_chart rendered!");
                                    }} catch(e) {{
                                        console.error("EXCEPTION rendering param_distributions_chart:", e);
                                    }}
                                }}
                            }}
                            if (document.readyState === 'loading') {{
                                document.addEventListener('DOMContentLoaded', renderDistributionsChart);
                            }} else {{
                                renderDistributionsChart();
                            }}
                        }})();
                        </script>'''
                        param_analysis_html += dist_div
                        param_analysis_scripts += dist_script
                except Exception as e:
                    print(f"  Warning: Could not generate parameter distributions chart: {e}")
                
                # 4. Parameter Interactions (Top 5 parameters)
                try:
                    if top_10 is not None and len(top_10) >= 2 and len(param_df_analysis) > 0:
                        top_5_params = sensitivity_df.head(5)['parameter'].tolist()
                        
                        # Create 2D scatter plots for top parameter pairs
                        fig_interactions = make_subplots(
                            rows=2, cols=2,
                            subplot_titles=[f'{top_5_params[i]} vs {top_5_params[i+1]}' 
                                          for i in range(min(4, len(top_5_params)-1))],
                            vertical_spacing=0.15,
                            horizontal_spacing=0.15
                        )
                        
                        for idx in range(min(4, len(top_5_params)-1)):
                            row = (idx // 2) + 1
                            col = (idx % 2) + 1
                            param1 = top_5_params[idx]
                            param2 = top_5_params[idx + 1]
                            
                            # Convert pandas Series to lists for Plotly
                            x_vals = param_df_analysis[param1].tolist()
                            y_vals = param_df_analysis[param2].tolist()
                            color_vals = param_df_analysis['sortino'].tolist()
                            sortino_vals = param_df_analysis['sortino'].tolist()
                            trades_vals = param_df_analysis['avg_trades_day'].tolist()
                            
                            fig_interactions.add_trace(
                                go.Scatter(
                                    x=x_vals,
                                    y=y_vals,
                                    mode='markers',
                                    marker=dict(
                                        size=6,
                                        color=color_vals,
                                        colorscale='Viridis',
                                        showscale=(idx==0),
                                        colorbar=dict(title="Sortino", x=1.02) if idx==0 else None
                                    ),
                                    text=[f"Sortino: {s:.3f}<br>Trades/Day: {t:.2f}" 
                                          for s, t in zip(sortino_vals, trades_vals)],
                                    hovertemplate='%{text}<extra></extra>',
                                    showlegend=False
                                ),
                                row=row, col=col
                            )
                            
                            fig_interactions.update_xaxes(title_text=param1, row=row, col=col)
                            fig_interactions.update_yaxes(title_text=param2, row=row, col=col)
                        
                        fig_interactions.update_layout(
                            height=700,
                            title_text="Parameter Interactions (Top 5 Parameters) - Color = Sortino",
                            showlegend=False
                        )
                        
                        # Use JSON format and create chart with JavaScript directly
                        int_json = fig_interactions.to_json()
                        int_div = '\n<div id="param_interactions_chart" class="plotly-graph-div" style="height:700px; width:100%;"></div>\n'
                        int_script = f'''<script type="text/javascript">
                        console.log("=== PARAM INTERACTIONS CHART SCRIPT LOADED ===");
                        (function() {{
                            function renderInteractionsChart() {{
                                console.log("renderInteractionsChart() executing...");
                                var chartDiv = document.getElementById("param_interactions_chart");
                                console.log("Chart div found:", chartDiv !== null);
                                if (chartDiv && typeof Plotly !== 'undefined') {{
                                    try {{
                                        var figure = JSON.parse({int_json!r});
                                        console.log("Calling Plotly.newPlot for interactions chart...");
                                        Plotly.newPlot("param_interactions_chart", figure.data, figure.layout, {{"responsive": true}});
                                        console.log("SUCCESS: param_interactions_chart rendered!");
                                    }} catch(e) {{
                                        console.error("EXCEPTION rendering param_interactions_chart:", e);
                                    }}
                                }}
                            }}
                            if (document.readyState === 'loading') {{
                                document.addEventListener('DOMContentLoaded', renderInteractionsChart);
                            }} else {{
                                renderInteractionsChart();
                            }}
                        }})();
                        </script>'''
                        param_analysis_html += int_div
                        param_analysis_scripts += int_script
                except Exception as e:
                    print(f"  Warning: Could not generate parameter interactions chart: {e}")
                
                # 5. Parameter Distribution Histograms (All Parameters with Valid Ranges)
                try:
                    if len(available_params) > 0:
                        # Show ALL parameters to detect any issues (no limit)
                        top_params = available_params
                        
                        # Calculate grid size (4 columns)
                        n_params = len(top_params)
                        n_cols = 4
                        n_rows = (n_params + n_cols - 1) // n_cols
                        
                        # make_subplots is already imported at module level
                        fig_dist = make_subplots(
                            rows=n_rows, cols=n_cols,
                            subplot_titles=top_params,
                            vertical_spacing=0.08,
                            horizontal_spacing=0.06
                        )
                        
                        # Color scheme: values in range = blue, out of range = red
                        for idx, param in enumerate(top_params):
                            row = (idx // n_cols) + 1
                            col = (idx % n_cols) + 1
                            
                            # Get parameter values (use raw values from individuals to detect clamping issues)
                            param_values = []
                            if param in param_keys_local:
                                param_idx = param_keys_local.index(param)
                                for i, ind in enumerate(hof):
                                    if hasattr(ind, 'fitness') and ind.fitness.valid:
                                        if param_idx < len(ind):
                                            raw_value = ind[param_idx]
                                            # Round integer parameters for display
                                            if param in param_dict:
                                                param_type = param_dict[param].get('type', 'float')
                                                if param_type == 'int':
                                                    raw_value = int(round(raw_value))
                                            param_values.append(raw_value)
                            
                            if len(param_values) > 0:
                                param_values = [float(v) for v in param_values if isinstance(v, (int, float)) and not pd.isna(v)]
                                
                                if len(param_values) > 0:
                                    # Get valid range from param_dict
                                    param_min = None
                                    param_max = None
                                    if param in param_dict:
                                        param_info = param_dict[param]
                                        param_type = param_info.get('type', 'float')
                                        if param_type in ['int', 'float']:
                                            param_min = param_info.get('min', None)
                                            param_max = param_info.get('max', None)
                                    
                                    # Separate values into in-range and out-of-range
                                    in_range_values = []
                                    out_of_range_values = []
                                    
                                    if param_min is not None and param_max is not None:
                                        for v in param_values:
                                            if param_min <= v <= param_max:
                                                in_range_values.append(v)
                                            else:
                                                out_of_range_values.append(v)
                                    else:
                                        in_range_values = param_values
                                    
                                    # Create histogram for in-range values
                                    if len(in_range_values) > 0:
                                        fig_dist.add_trace(
                                            go.Histogram(
                                                x=in_range_values,
                                                name='In Range',
                                                marker_color='rgba(31, 119, 180, 0.7)',
                                                nbinsx=20,
                                                showlegend=(idx == 0)
                                            ),
                                            row=row, col=col
                                        )
                                    
                                    # Create histogram for out-of-range values (if any)
                                    if len(out_of_range_values) > 0:
                                        fig_dist.add_trace(
                                            go.Histogram(
                                                x=out_of_range_values,
                                                name='Out of Range',
                                                marker_color='rgba(214, 39, 40, 0.7)',
                                                nbinsx=20,
                                                showlegend=(idx == 0)
                                            ),
                                            row=row, col=col
                                        )
                                    
                                    # Add vertical lines for valid range boundaries
                                    if param_min is not None and param_max is not None:
                                        # Min boundary
                                        fig_dist.add_vline(
                                            x=param_min, line_dash="dash", line_color="green",
                                            annotation_text=f"Min: {param_min:.2f}", annotation_position="top",
                                            row=row, col=col
                                        )
                                        # Max boundary
                                        fig_dist.add_vline(
                                            x=param_max, line_dash="dash", line_color="red",
                                            annotation_text=f"Max: {param_max:.2f}", annotation_position="top",
                                            row=row, col=col
                                        )
                                    
                                    # Update axis labels
                                    fig_dist.update_xaxes(title_text=param, row=row, col=col)
                                    fig_dist.update_yaxes(title_text="Count", row=row, col=col)
                        
                        # Update layout
                        fig_dist.update_layout(
                            height=200 * n_rows,
                            title_text=f"Parameter Distributions with Valid Ranges (All {len(top_params)} Parameters)",
                            title_x=0.5,
                            showlegend=True,
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                        )
                        
                        # Convert to JSON and create JavaScript
                        dist_json = fig_dist.to_json()
                        dist_div = '<div id="param_distributions_all_chart" class="plotly-graph-div" style="height:600px; width:100%;"></div>'
                        dist_script = f'''<script type="text/javascript">
                        console.log("param_distributions_all_chart script loaded");
                        document.addEventListener("DOMContentLoaded", function() {{
                            if (typeof Plotly !== 'undefined' && document.getElementById("param_distributions_all_chart")) {{
                                try {{
                                    var figure = JSON.parse({dist_json!r});
                                    Plotly.newPlot("param_distributions_all_chart", figure.data, figure.layout, {{"responsive": true}});
                                    console.log("SUCCESS: param_distributions_all_chart rendered!");
                                }} catch (e) {{
                                    console.error("Error rendering param_distributions_all_chart:", e);
                                }}
                            }} else {{
                                console.warn("param_distributions_all_chart: Plotly not available or div not found");
                            }}
                        }});
                        </script>'''
                        param_analysis_html += dist_div + "\n"
                        param_analysis_scripts += dist_script
                        
                        print(f"  Generated parameter distribution chart for {len(top_params)} parameters")
                except Exception as e:
                    import traceback
                    print(f"  Warning: Could not generate parameter distribution chart: {e}")
                    print(f"  Traceback: {traceback.format_exc()}")
                
    except Exception as e:
        import traceback
        print(f"  Warning: Could not generate parameter analysis: {e}")
        print(f"  Traceback: {traceback.format_exc()}")
        param_analysis_html = f"<p>Parameter analysis not available: {str(e)}<br>Need at least 5 solutions with valid fitness values.</p>"
        param_analysis_scripts = ""
    
    # Debug: verify scripts were collected
    if param_analysis_scripts:
        script_count = param_analysis_scripts.count('Plotly.newPlot')
        print(f"  Parameter analysis: Collected {script_count} chart scripts (total length: {len(param_analysis_scripts)} chars)")
    else:
        print(f"  WARNING: Parameter analysis scripts are EMPTY! Charts may not render.")
    
    # Best params table - grouped by category
    def group_parameters(param_keys_local, param_dict_local):
        """Group parameters into logical categories."""
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
                        'Max ATR Filter (Points)', 'RTH Start (HH:MM)', 'RTH End (HH:MM)',
                        'Enable RTH Filter', 'Max Volume Multiplier', 'Timeframe (minutes)',
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
        ptype = pdata.get('type', '')
        pmin = pdata.get('min')
        pmax = pdata.get('max')
        # Include int/float parameters with valid min/max where min != max
        if ptype in ('int', 'float') and pmin is not None and pmax is not None and pmin != pmax:
            optimizable_params.add(pname)
    
    best_params_html = ""
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
    comparison_html = """<table class='comparison-table'><thead><tr>
        <th>Metric<span class="tooltip-icon">?</span><span class="tooltip">Performance metric being compared between training (IS) and validation (OOS) data.</span></th>
        <th>In-Sample<span class="tooltip-icon">?</span><span class="tooltip">Performance on training data used for optimization. This is what the GA optimized for.</span></th>
        <th>OOS<span class="tooltip-icon">?</span><span class="tooltip">Out-of-Sample performance on validation data not seen during optimization. This tests generalization.</span></th>
        <th>Difference<span class="tooltip-icon">?</span><span class="tooltip">OOS - IS. Green = OOS better (good generalization), Red = OOS worse (potential overfitting).</span></th>
    </tr></thead><tbody>"""
    
    # Ensure is_res and oos_res are dicts with required keys
    if not isinstance(is_res, dict):
        is_res = {'sortino': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0, 'total_profit': 0}
    if not isinstance(oos_res, dict):
        oos_res = {'sortino': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0, 'total_profit': 0}
    
    # Ensure all required keys exist
    required_keys = ['sortino', 'max_drawdown', 'avg_trades_day', 'profit_factor', 'total_profit']
    for key in required_keys:
        if key not in is_res:
            is_res[key] = 0
        if key not in oos_res:
            oos_res[key] = 0
    
    # Metrics to compare (matching console output)
    metrics_to_compare = [
        ('sortino', 'Sortino Ratio', False),  # (key, display_name, lower_is_better)
        ('max_drawdown', 'Max Drawdown', True),
        ('avg_trades_day', 'Avg Trades/Day', False),
        ('profit_factor', 'Profit Factor', False),
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
        else:
            is_str = f"{is_val:.6f}"
            oos_str = f"{oos_val:.6f}"
            diff_str = f"{diff:+.6f} ({diff_pct:+.1f}%)"
        
        comparison_html += f"<tr><td>{metric_name}</td><td>{is_str}</td><td>{oos_str}</td><td class='{diff_class}'>{diff_str}</td></tr>"
    
    comparison_html += "</tbody></table>"
    
    # Add summary statistics matching console output
    summary_html = """<h3>Performance Summary</h3>
    <div class="info-section">
        <strong>Summary Metrics:</strong> These metrics provide a quick overview of strategy performance. Compare IS vs OOS to assess generalization. Large differences indicate potential overfitting.
    </div>
    <table class='summary-table'><thead><tr>
        <th>Dataset<span class="tooltip-icon">?</span><span class="tooltip">In-Sample (training) or OOS (validation) dataset.</span></th>
        <th>PNL<span class="tooltip-icon">?</span><span class="tooltip">Total Profit and Loss in dollars. Sum of all trade PNLs.</span></th>
        <th>Win Rate<span class="tooltip-icon">?</span><span class="tooltip">Percentage of profitable trades. Higher is generally better, but not always (depends on risk/reward).</span></th>
        <th>Profit Factor<span class="tooltip-icon">?</span><span class="tooltip">Gross Profit / Gross Loss. >1.0 = profitable, >2.0 = excellent. Shows dollar efficiency.</span></th>
        <th>Calmar Ratio<span class="tooltip-icon">?</span><span class="tooltip">Total PNL / Max Drawdown. Higher is better. Measures return per unit of maximum risk.</span></th>
    </tr></thead><tbody>"""
    
    # is_res and oos_res are already validated at function start, so they're guaranteed to be dicts
    for label, trades, res in [('In-Sample', trades_is, is_res), ('OOS', trades_oos, oos_res)]:
        
        if not trades.empty:
            total_pnl = trades['pnl'].sum()
            win_rate = (trades['pnl'] > 0).mean() * 100
            pf = abs(trades[trades['pnl'] > 0]['pnl'].sum() / trades[trades['pnl'] < 0]['pnl'].sum()) if (trades['pnl'] < 0).any() else np.inf
            max_dd = res.get('max_drawdown', 0)
            calmar = total_pnl / max_dd if max_dd > 0 else np.inf
            summary_html += f"<tr><td>{label}</td><td>${total_pnl:,.0f}</td><td>{win_rate:.1f}%</td><td>{pf:.2f}</td><td>{calmar:.2f}</td></tr>"
        else:
            summary_html += f"<tr><td>{label}</td><td>N/A</td><td>N/A</td><td>N/A</td><td>N/A</td></tr>"
    
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
            elif is_final:
                predicted_completion_str = "Complete"
        
        # Fixed status banner at top
        progress_html = f"""
<div id="status-banner" style="position: fixed; top: 0; left: 0; right: 0; background: {status_color}; color: white; padding: 8px 15px; z-index: 10000; box-shadow: 0 2px 5px rgba(0,0,0,0.2); display: flex; align-items: center; justify-content: space-between; font-size: 13px; font-family: Arial, sans-serif;">
    <div style="display: flex; align-items: center; gap: 15px; flex: 1; min-width: 0;">
        <span><strong>Status:</strong> {status}</span>
        <span><strong>Gen:</strong> {current_gen}/{total_gen}</span>
        <div style="flex: 1; max-width: 250px; min-width: 150px; background: rgba(255,255,255,0.3); border-radius: 3px; height: 18px; position: relative; margin: 0 10px;">
            <div style="background: white; height: 100%; width: {progress_pct}%; border-radius: 3px; transition: width 0.3s;"></div>
            <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-weight: bold; color: {status_color}; font-size: 10px; white-space: nowrap;">
                {progress_pct:.1f}%
            </div>
        </div>
    </div>
    <div style="display: flex; align-items: center; gap: 15px; font-size: 11px; white-space: nowrap;">
        <span><strong>Elapsed:</strong> {elapsed_time_str}</span>
        <span><strong>ETA:</strong> {predicted_completion_str}</span>
    </div>
</div>
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin: 10px 0; font-size: 0.9em;">
        <div><strong>Last Updated:</strong> {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
        <div><strong>Elapsed Time:</strong> {elapsed_time_str}</div>
        <div><strong>Predicted Completion:</strong> {predicted_completion_str}</div>
        <div><strong>Elapsed Generations:</strong> {len(gens)}</div>
        <div><strong>Pareto Solutions Found:</strong> {len(hof)}</div>
    </div>
</div>"""
    
    # Build fitness weights HTML section
    fitness_weights_html = """<h2>Fitness Function Configuration<span class="tooltip-icon">?</span>
    <span class="tooltip">Multi-objective fitness weights used by NSGA-II. These determine how objectives are prioritized. Higher weights mean higher priority. <strong>CRITICAL:</strong> NSGA-II uses Pareto dominance, not weighted sum, so weights affect selection pressure but don't guarantee optimization for highest-weighted objectives.</span>
</h2>
<div class="info-section">
    <table class='params-table'><thead><tr>
        <th>Objective</th>
        <th>Weight</th>
        <th>Direction</th>
        <th>Normalization Range</th>
        <th>Notes</th>
    </tr></thead><tbody>"""
    
    # Get weights from creator.FitnessMulti
    from deap import creator
    if hasattr(creator, 'FitnessMulti'):
        weights = creator.FitnessMulti.weights
        weight_names = ['Sortino Ratio', 'Max Drawdown', 'Profit Factor', 'Avg Trades/Day', 'Total Profit']
        directions = ['Maximize', 'Minimize', 'Maximize', 'Maximize', 'Maximize']
        
        # Get normalization ranges from param_dict
        norm_ranges = {
            'Sortino Ratio': param_dict.get('NORM_SORTINO_MAX', {}).get('value', 10.0),
            'Max Drawdown': param_dict.get('NORM_DD_MAX', {}).get('value', 100000.0),
            'Profit Factor': param_dict.get('NORM_PF_MAX', {}).get('value', 5.0),
            'Avg Trades/Day': 'Raw (no normalization)',
            'Total Profit': param_dict.get('NORM_PNL_MAX', {}).get('value', 200000.0)
        }
        
        notes = [
            'Risk-adjusted return (downside volatility only)',
            'Largest peak-to-trough decline (minimize)',
            'Gross profit / Gross loss',
            'Average trades per trading day',
            'Total profit and loss in dollars'
        ]
        
        for i, (name, weight, direction, note) in enumerate(zip(weight_names, weights, directions, notes)):
            norm_range = norm_ranges.get(name, 'N/A')
            if isinstance(norm_range, float):
                norm_range_str = f"{norm_range:,.0f}" if norm_range >= 1000 else f"{norm_range:.1f}"
            else:
                norm_range_str = str(norm_range)
            
            weight_str = f"{weight:.1f}"
            if weight == 100.0:
                weight_str = f"<strong style='color: red; font-size: 1.1em;'>{weight:.1f} ⚠️ DIAGNOSTIC</strong>"
            elif abs(weight) > 10:
                weight_str = f"<strong>{weight:.1f}</strong>"
            
            fitness_weights_html += f"<tr><td>{name}</td><td>{weight_str}</td><td>{direction}</td><td>{norm_range_str}</td><td>{note}</td></tr>"
    
    fitness_weights_html += """</tbody></table>
    <p><em><strong>⚠️ CRITICAL UNDERSTANDING:</strong> NSGA-II uses <strong>Pareto dominance</strong>, not weighted sum. Weights influence selection pressure but don't guarantee optimization for highest-weighted objectives. A solution with high trade frequency may still be dominated by one with higher Sortino if it's better in ALL objectives.</em></p>
    <p><em><strong>Why weight=100.0 may not work:</strong> Even with high weight, if normalized trade frequency is very small (e.g., 0.01), the weighted contribution (0.01 × 100 = 1.0) may still be small compared to other objectives. Normalization is the real issue - it makes trade frequency values tiny.</em></p>
</div>"""
    
    # Generate full HTML with tooltips and auto-refresh
    # Use JavaScript refresh that preserves scroll position instead of meta refresh
    refresh_script = ''
    if not is_final:
        refresh_script = '''
<script>
// Auto-refresh every 30 seconds, preserving scroll position
(function() {
    let scrollPosition = sessionStorage.getItem('ga_dashboard_scroll');
    if (scrollPosition) {
        window.scrollTo(0, parseInt(scrollPosition));
    }
    
    // Save scroll position before refresh
    window.addEventListener('beforeunload', function() {
        sessionStorage.setItem('ga_dashboard_scroll', window.pageYOffset || document.documentElement.scrollTop);
    });
    
    // Auto-refresh after 30 seconds
    setTimeout(function() {
        sessionStorage.setItem('ga_dashboard_scroll', window.pageYOffset || document.documentElement.scrollTop);
        location.reload();
    }, 30000);
})();
</script>'''
    
    html_content = f"""<!DOCTYPE html>
<html><head><title>GA Dashboard v3.0</title>
{refresh_script}
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
<style>
body {{ font-family: Arial; margin: 0; padding: 0; background: #f5f5f5; padding-top: 60px; }}
.container {{ max-width: 1400px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }}
h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }}
h2 {{ color: #555; margin-top: 30px; border-bottom: 2px solid #ddd; position: relative; }}
h2 .tooltip-icon {{ 
    display: inline-block; 
    width: 18px; 
    height: 18px; 
    background: #4CAF50; 
    color: white; 
    border-radius: 50%; 
    text-align: center; 
    line-height: 18px; 
    font-size: 12px; 
    margin-left: 8px; 
    cursor: help;
    vertical-align: middle;
}}
h2 .tooltip {{ 
    visibility: hidden; 
    width: 300px; 
    background-color: #333; 
    color: #fff; 
    text-align: left; 
    border-radius: 6px; 
    padding: 10px; 
    position: absolute; 
    z-index: 1; 
    bottom: 125%; 
    left: 0; 
    font-size: 12px;
    line-height: 1.4;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}}
h2 .tooltip-icon:hover + .tooltip {{ visibility: visible; }}
table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
th {{ background: #4CAF50; color: white; padding: 10px; text-align: left; position: relative; }}
th .tooltip-icon {{ 
    display: inline-block; 
    width: 16px; 
    height: 16px; 
    background: rgba(255,255,255,0.3); 
    color: white; 
    border-radius: 50%; 
    text-align: center; 
    line-height: 16px; 
    font-size: 11px; 
    margin-left: 5px; 
    cursor: help;
    vertical-align: middle;
}}
th .tooltip {{ 
    visibility: hidden; 
    width: 280px; 
    background-color: #333; 
    color: #fff; 
    text-align: left; 
    border-radius: 6px; 
    padding: 8px; 
    position: absolute; 
    z-index: 1; 
    bottom: 125%; 
    left: 0; 
    font-size: 11px;
    line-height: 1.3;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}}
th .tooltip-icon:hover + .tooltip {{ visibility: visible; }}
td {{ padding: 8px; border: 1px solid #ddd; }}
tr:nth-child(even) {{ background: #f9f9f9; }}
.selected-row {{ background: #fff3cd !important; font-weight: bold; }}
.positive {{ color: green; }}
.negative {{ color: red; }}
.metric-box {{ 
    display: inline-block; 
    background: #4CAF50; 
    color: white; 
    padding: 10px 20px; 
    margin: 5px; 
    border-radius: 5px; 
    font-weight: bold;
    position: relative;
    cursor: help;
}}
.metric-box .tooltip {{ 
    visibility: hidden; 
    width: 250px; 
    background-color: #333; 
    color: #fff; 
    text-align: left; 
    border-radius: 6px; 
    padding: 8px; 
    position: absolute; 
    z-index: 1; 
    bottom: 125%; 
    left: 50%;
    transform: translateX(-50%);
    font-size: 11px;
    line-height: 1.3;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}}
.metric-box:hover .tooltip {{ visibility: visible; }}
.info-section {{ 
    background: #e3f2fd; 
    border-left: 4px solid #2196F3; 
    padding: 12px; 
    margin: 15px 0; 
    border-radius: 4px;
    font-size: 0.9em;
    line-height: 1.5;
}}
.chart-container {{
    margin: 20px 0;
    padding: 20px 0;
    border-top: 1px solid #ddd;
    border-bottom: 1px solid #ddd;
}}
.chart-container .plotly-graph-div {{
    margin: 20px 0;
    display: block;
    min-height: 400px;
}}
.return-button {{ display: inline-block; margin-bottom: 20px; padding: 10px 20px; background: #667eea; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; }}
.return-button:hover {{ background: #5568d3; }}
</style></head><body>
{progress_html}
<div class="container">
<a href="index.html" class="return-button">← Back to Main Dashboard</a>
<h1>GA Optimization Dashboard - v3.0</h1>
<p><strong>Generated:</strong> {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
<div class="metric-box">
    Pareto Solutions: {len(hof)}
    <span class="tooltip">Number of non-dominated solutions found. These represent the best trade-offs between Sortino Ratio, Max Drawdown, and Profit Factor. Higher is generally better, indicating more diverse optimal solutions.</span>
</div>
<div class="metric-box">
    Generations: {len(gens)}
    <span class="tooltip">Total number of generations completed. Each generation evaluates a population of candidate solutions and evolves them through selection, crossover, and mutation.</span>
</div>
{fitness_weights_html}
<h2>Selected Solution Performance<span class="tooltip-icon">?</span>
    <span class="tooltip">The best solution selected from the Pareto front based on highest Sortino Ratio. This represents the optimized strategy parameters that will be used for live trading.</span>
</h2>
<div class="info-section">
    <strong>Selection Criteria:</strong> The solution with the highest Sortino Ratio is selected as the "best" solution. This prioritizes risk-adjusted returns while still considering drawdown and profit factor through the Pareto front.
</div>
<h3>Actual Backtest Results (In-Sample)</h3>
<div class="metric-box">
    Sortino: {(is_res.get('sortino', 0) if isinstance(is_res, dict) else 0):.6f}
    <span class="tooltip">Sortino Ratio measures risk-adjusted returns, focusing only on downside volatility (negative returns). Higher is better. Values above 1.0 are considered good, above 2.0 are excellent. This is preferred over Sharpe Ratio for trading strategies as it doesn't penalize upside volatility.</span>
</div>
<div class="metric-box">
    Max DD: ${(is_res.get('max_drawdown', 0) if isinstance(is_res, dict) else 0):,.2f}
    <span class="tooltip">Maximum Drawdown is the largest peak-to-trough decline in equity during the backtest period. Lower is better. This represents the worst-case loss an investor would have experienced. Critical for risk management.</span>
</div>
<div class="metric-box">
    PF: {(is_res.get('profit_factor', 0) if isinstance(is_res, dict) else 0):.6f}
    <span class="tooltip">Profit Factor = Total Gross Profit / Total Gross Loss. Values above 1.0 indicate profitable strategy. Above 2.0 is excellent. This metric shows the ratio of winning to losing trades in dollar terms.</span>
</div>
<div class="metric-box">
    Avg Trades/Day: {(is_res.get('avg_trades_day', 0) if isinstance(is_res, dict) else 0):.3f}
    <span class="tooltip">Average number of trades executed per day. This helps assess strategy activity level. Too few trades may indicate over-filtering, too many may indicate overtrading. Target range is typically 1-5 trades/day.</span>
</div>
<div class="metric-box">
    Total Profit: ${(is_res.get('total_profit', 0) if isinstance(is_res, dict) else 0):,.2f}
    <span class="tooltip">Total Profit and Loss in dollars. Sum of all trade PNLs. This is the 5th optimization objective, directly optimizing for absolute profitability.</span>
</div>
<p><em>Note: GA fitness values (used for optimization) may differ from actual backtest results due to penalties for constraint violations. Total Profit shown here is from actual backtest, not normalized fitness value.</em></p>
<h2>Parameters<span class="tooltip-icon">?</span>
    <span class="tooltip">Optimized parameter values for the selected solution. These are the actual values that will be used in live trading. Compare these to your initial parameter ranges to see how the GA adjusted them.</span>
</h2>
{best_params_html}
<h2>Convergence<span class="tooltip-icon">?</span>
    <span class="tooltip">Convergence plots show how the optimization objectives improve over generations. Look for: (1) Steady upward trend in Sortino, Profit Factor, and Avg Trades/Day, (2) Steady downward trend in Drawdown, (3) Convergence where improvements plateau (indicates optimization is complete). If lines are still improving, consider running more generations.</span>
</h2>
<div class="info-section">
    <strong>⚠️ IMPORTANT: These charts show NORMALIZED FITNESS VALUES (0-1 range), not actual backtest results!</strong>
    <ul>
        <li><strong>Sortino/Drawdown/PF/Total Profit:</strong> Normalized to 0-1 range for optimization. Values of -1000 indicate hard constraint penalties (solution eliminated).</li>
        <li><strong>Avg Trades/Day:</strong> RAW value (actual trades/day) - this is NOT normalized.</li>
        <li><strong>To see actual backtest results:</strong> Check "Actual Backtest Results (In-Sample)" section below, which runs real backtests.</li>
    </ul>
    <strong>Interpreting Convergence:</strong> The "Best" line shows the best individual in each generation. The "Avg" line shows the population average. Convergence occurs when both lines plateau. If they're still improving, the GA may benefit from more generations. Divergence between Best and Avg indicates good diversity in the population. All five objectives (Sortino, Drawdown, Profit Factor, Avg Trades/Day, Total Profit) are optimized simultaneously.
</div>
{conv_div}
<h2>Pareto Front 3D<span class="tooltip-icon">?</span>
    <span class="tooltip">3D visualization of all Pareto-optimal solutions showing the trade-offs between Sortino Ratio (Y-axis), Max Drawdown (X-axis), and Profit Factor (Z-axis). Each point is a non-dominated solution. The red diamond is the selected solution. Color intensity represents Sortino Ratio (darker = higher). Rotate the chart to see trade-offs from different angles.</span>
</h2>
<div class="info-section">
    <strong>Understanding Pareto Optimality:</strong> A solution is Pareto-optimal if no other solution is better in ALL objectives simultaneously. For example, Solution A might have higher Sortino but higher Drawdown than Solution B - both are Pareto-optimal. The selected solution (red diamond) has the highest Sortino among all Pareto solutions.
</div>
{pareto3d_div}
<h2>Pareto Front 2D<span class="tooltip-icon">?</span>
    <span class="tooltip">2D projections of the Pareto front showing pairwise relationships between objectives. These help identify trade-offs: (1) Sortino vs DD: Higher Sortino often comes with higher drawdown risk, (2) Sortino vs PF: Both should ideally be high, (3) DD vs PF: Lower drawdown may reduce profit factor. The red diamond is the selected solution.</span>
</h2>
<div class="info-section">
    <strong>Trade-off Analysis:</strong> The 2D projections reveal relationships between objectives. A "knee" in the curve (where small improvement in one objective requires large sacrifice in another) often indicates a good compromise solution. Solutions in the upper-right regions (for maximization) or lower-left (for minimization) are generally preferred.
</div>
{pareto2d_div}
<h2>Pareto Size<span class="tooltip-icon">?</span>
    <span class="tooltip">Number of Pareto-optimal solutions found over generations. Generally increases over time as the GA explores the solution space. A large Pareto front (20+ solutions) indicates good diversity. A small front (1-5 solutions) may indicate premature convergence or limited solution space. Steady growth is healthy.</span>
</h2>
<div class="info-section">
    <strong>Pareto Size Interpretation:</strong> Early generations typically have few Pareto solutions. As optimization progresses, more non-dominated solutions are discovered. If the size plateaus early, the GA may have converged. If it keeps growing, the solution space is rich with trade-offs.
</div>
{paretosize_div}
<h2>Data Split Information<span class="tooltip-icon">?</span>
    <span class="tooltip">Shows the date ranges for all In-Sample (training) and Out-of-Sample (validation) periods. This helps understand which time periods were used for optimization vs validation.</span>
</h2>
<div class="info-section">
    <strong>Period Information:</strong> The data was split into multiple periods for training and validation. IS periods were used for optimization, OOS periods for validation.
</div>
"""
    
    # Add IS and OOS period dates
    if is_periods is not None and oos_periods is not None:
        periods_html = """<table class='periods-table'><thead><tr>
        <th>Period Type</th>
        <th>Period #</th>
        <th>Start Date</th>
        <th>End Date</th>
        <th>Rows</th>
    </tr></thead><tbody>"""
        
        for i, period in enumerate(is_periods, 1):
            periods_html += f"<tr><td>In-Sample</td><td>{i}</td><td>{period.index[0]}</td><td>{period.index[-1]}</td><td>{len(period):,}</td></tr>"
        
        for i, period in enumerate(oos_periods, 1):
            periods_html += f"<tr><td>Out-of-Sample</td><td>{i}</td><td>{period.index[0]}</td><td>{period.index[-1]}</td><td>{len(period):,}</td></tr>"
        
        periods_html += "</tbody></table>"
        html_content += periods_html
        
        # Add individual OOS period statistics if we have best_params
        if best_params and len(oos_periods) > 0:
            html_content += """
<h2>Individual OOS Period Statistics<span class="tooltip-icon">?</span>
    <span class="tooltip">Performance statistics for each individual Out-of-Sample period. This helps identify if the strategy performs consistently across different time periods or if it's overfitted to specific market conditions.</span>
</h2>
<div class="info-section">
    <strong>Period-by-Period Analysis:</strong> If performance varies significantly across OOS periods, the strategy may be overfitted to specific market conditions. Consistent performance across periods is a good sign of robustness.
</div>
"""
            
            oos_period_stats_html = """<table class='oos-periods-table'><thead><tr>
        <th>Period #</th>
        <th>Date Range</th>
        <th>Total PNL</th>
        <th>Trades</th>
        <th>Win Rate</th>
        <th>Profit Factor</th>
        <th>Sortino</th>
        <th>Max DD</th>
        <th>Avg Trades/Day</th>
    </tr></thead><tbody>"""
            
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
                        
                        oos_period_stats_html += f"""<tr>
        <td>{i}</td>
        <td>{oos_period.index[0].strftime('%Y-%m-%d')} to {oos_period.index[-1].strftime('%Y-%m-%d')}</td>
        <td class="{'positive' if total_pnl > 0 else 'negative'}">${total_pnl:,.2f}</td>
        <td>{num_trades}</td>
        <td>{win_rate:.1f}%</td>
        <td>{pf:.2f}</td>
        <td>{sortino:.2f}</td>
        <td>${max_dd:,.2f}</td>
        <td>{avg_trades_day:.2f}</td>
    </tr>"""
                    else:
                        oos_period_stats_html += f"""<tr>
        <td>{i}</td>
        <td>{oos_period.index[0].strftime('%Y-%m-%d')} to {oos_period.index[-1].strftime('%Y-%m-%d')}</td>
        <td colspan="7" style="text-align: center; color: #999;">No trades</td>
    </tr>"""
                except Exception as e:
                    oos_period_stats_html += f"""<tr>
        <td>{i}</td>
        <td>{oos_period.index[0].strftime('%Y-%m-%d')} to {oos_period.index[-1].strftime('%Y-%m-%d')}</td>
        <td colspan="7" style="text-align: center; color: #f00;">Error: {str(e)}</td>
    </tr>"""
            
            oos_period_stats_html += "</tbody></table>"
            html_content += oos_period_stats_html
    
    html_content += f"""
<h2>In-Sample vs OOS Comparison<span class="tooltip-icon">?</span>
    <span class="tooltip">Comparison of strategy performance between in-sample (training) and out-of-sample (validation) data. This is critical for detecting overfitting. Good generalization: IS and OOS metrics are similar. Overfitting: IS is much better than OOS. Green differences indicate OOS is better (good sign), red indicates OOS is worse (potential overfitting).</span>
</h2>
<div class="info-section">
    <strong>Overfitting Detection:</strong> If OOS performance is significantly worse than IS, the strategy may be overfitted to the training data. Look for: (1) Sortino dropping >50% in OOS, (2) Drawdown increasing >100% in OOS, (3) Trade frequency dropping dramatically. Small differences (<20%) are normal and acceptable.
</div>
{comparison_html}
{summary_html}
<h2>All Solutions<span class="tooltip-icon">?</span>
    <span class="tooltip">Complete list of all Pareto-optimal solutions ranked by Sortino Ratio. The selected solution is marked with ★. You can compare different solutions to see parameter variations. Higher-ranked solutions have better risk-adjusted returns, but may have different drawdown or profit factor characteristics.</span>
</h2>
<div class="info-section">
    <strong>⚠️ IMPORTANT: This table shows NORMALIZED FITNESS VALUES, not actual backtest results!</strong>
    <ul>
        <li><strong>Sortino/Drawdown/PF/Total Profit:</strong> Normalized fitness values (0-1 range) used for optimization. Values of -1000 indicate hard constraint penalties (solution eliminated due to negative Sortino, negative PNL, or win rate < 40%).</li>
        <li><strong>Avg Trades/Day:</strong> RAW value (actual trades/day) - this is NOT normalized and shows real trade frequency.</li>
        <li><strong>Why values differ from "Actual Backtest Results":</strong> Fitness values are normalized for optimization efficiency. The "Actual Backtest Results" section runs real backtests and shows actual metrics.</li>
        <li><strong>If all solutions show Sortino = -1000:</strong> All solutions hit hard constraints (likely negative Sortino, negative PNL, or win rate < 40%). The GA eliminated them from optimization, but they may still appear here with invalid fitness values.</li>
    </ul>
    <strong>Solution Selection:</strong> While the highest Sortino solution is automatically selected, you may want to manually review other solutions. For example, if Solution #2 has similar Sortino but much lower drawdown, it might be a better choice for risk-averse trading. All solutions in this table are Pareto-optimal.
</div>
{pareto_table_html}
</div>
<h2>Parameter Analysis<span class="tooltip-icon">?</span>
    <span class="tooltip">Analysis of how strategy parameters affect performance metrics. Use this to identify which parameters are most important and how they correlate with fitness objectives.</span>
</h2>
<div class="info-section">
    <strong>Understanding Parameter Analysis:</strong>
    <ul>
        <li><strong>Correlation Heatmap:</strong> Shows how each parameter correlates with each metric. Positive (blue) = parameter increases with metric, Negative (red) = parameter decreases with metric.</li>
        <li><strong>Parameter Importance:</strong> Combines correlation, top-bottom difference, range utilization, and variability to identify the most important parameters.</li>
        <li><strong>Parameter Distributions (Top vs Bottom):</strong> Compares parameter values in top 25% vs bottom 25% solutions. Shows which parameters distinguish good from bad solutions.</li>
        <li><strong>Parameter Interactions:</strong> 2D scatter plots showing how top parameters interact. Color = Sortino (darker = better). Helps identify parameter combinations that work together.</li>
        <li><strong>Parameter Distribution Histograms:</strong> Shows distribution of all parameter values with valid ranges marked. <strong style="color: red;">Red bars = values OUTSIDE valid range</strong>, Blue bars = values within range. Green/Red dashed lines = min/max boundaries. Use this to detect parameter clamping issues!</li>
        <li><strong>Focus on High-Importance Parameters:</strong> These are the parameters that most distinguish good solutions from bad ones.</li>
    </ul>
    <strong>Note:</strong> GA meta-parameters (POP_SIZE, NUM_GEN, etc.) are excluded from this analysis as they control the optimization algorithm, not the trading strategy.
</div>
<div class="chart-container">
{param_analysis_html}
</div>
{conv_script}
{pareto3d_script}
{pareto2d_script}
{paretosize_script}
{param_analysis_scripts}
</body></html>"""
    
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
    """
    Save GA state to checkpoint file.
    
    Args:
        pop: Current population
        hof: Hall of Fame
        logbook: Logbook with statistics
        gen: Current generation number
        config: Configuration dictionary (for verification)
    """
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
    print(f"Checkpoint saved: Generation {gen} → {CHECKPOINT_FILE}")

def load_checkpoint():
    """
    Load GA state from checkpoint file if it exists.
    
    Returns:
        tuple: (pop, hof, logbook, start_gen, config) or None if no checkpoint
    """
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
                elif fitness_len != 5:
                    print(f"\n=== CHECKPOINT INCOMPATIBLE ===")
                    print(f"Checkpoint contains individuals with {fitness_len} fitness values.")
                    print(f"v3 requires 5 fitness values (multi-objective: sortino, max_dd, pf, avg_trades_day, total_profit).")
                    print(f"This checkpoint appears to be from v2 (scalar fitness).")
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
    """
    Verify that saved checkpoint config matches current config.
    
    Returns:
        bool: True if compatible, False otherwise
    """
    critical_params = ['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'DATA_SPLITS', 'DATA_SIZE']
    for param in critical_params:
        if saved_config.get(param) != current_config.get(param):
            print(f"WARNING: Config mismatch for {param}")
            print(f"  Saved: {saved_config.get(param)}")
            print(f"  Current: {current_config.get(param)}")
            return False
    return True

# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
def main():
    global POP_SIZE, NUM_GEN, CX_PB, MUT_PB, MUT_MU, MUT_SIGMA
    
    # CRITICAL: Ensure FitnessMulti class has correct weights (5) before starting
    # This fixes issues where the class might have been created with old 4-weight definition
    if hasattr(creator, 'FitnessMulti'):
        if len(creator.FitnessMulti.weights) != 5:
            print(f"WARNING: FitnessMulti has {len(creator.FitnessMulti.weights)} weights, expected 5. Recreating...")
            del creator.FitnessMulti
            if hasattr(creator, "Individual"):
                del creator.Individual
            creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 5.0, 2.0))
            creator.create("Individual", list, fitness=creator.FitnessMulti)
            print(f"FitnessMulti recreated with weights: {creator.FitnessMulti.weights}")
    else:
        # Create if it doesn't exist
        creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 3.0, 1.0))
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
    
    # Print the exact parameter file that will be used (grouped)
    print("\n=== PARAMETER FILE USED (grouped by category) ===")
    
    def group_and_print_params(param_df_local):
        """Group and print parameters by category."""
        groups = {
            'Entry Criteria': ['Enable Long Trades', 'Enable Short Trades', 'Bollinger Band Length', 
                              'Bollinger Band StdDev', 'Long Entry on Wick Touch', 'Long Entry on Body in Zone',
                              'Long Trigger (% From Lower Band)', 'Short Entry on Wick Touch', 
                              'Short Entry on Body in Zone', 'Short Trigger (% From Upper Band)',
                              'Max ATR Filter (Points)', 'RTH Start (HH:MM)', 'RTH End (HH:MM)',
                              'Enable RTH Filter', 'Max Volume Multiplier', 'Timeframe (minutes)',
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
        param_df_filtered = param_df_local[~param_df_local['Name'].str.startswith('===')]
        
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
    NUM_GEN = param_dict.get('NUM_GEN', {'value': 10})['value']
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
                              'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT'])
    
    global PARAM_RANGES, param_keys
    PARAM_RANGES = {}
    for n, d in param_dict.items():
        if n.startswith('===') or n.startswith('__'):
            continue
        if n in ga_criteria_params:
            continue
        ptype = d.get('type', '')
        pmin = d.get('min')
        pmax = d.get('max')
        # Include int/float parameters with valid min/max
        if ptype in ('int', 'float') and pmin is not None and pmax is not None:
            # Exclude if min==max (effectively fixed)
            if pmin != pmax:
                PARAM_RANGES[n] = (pmin, pmax)
    
    param_keys = list(PARAM_RANGES.keys())
    
    print(f"Multi-core: Using {NUM_WORKERS} workers (CPU count: {multiprocessing.cpu_count()})")
    
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
    force_fresh = '--fresh' in sys.argv or '-f' in sys.argv
    if force_fresh:
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
            elif len(ind.fitness.values) != 5:
                invalid_individuals.append(i)
        
        if invalid_individuals:
            print(f"\n=== CHECKPOINT INCOMPATIBLE ===")
            print(f"Found {len(invalid_individuals)} individuals with invalid fitness format.")
            print(f"v3 requires 5 fitness values (multi-objective: sortino, max_dd, pf, avg_trades_day, total_profit).")
            print(f"This checkpoint appears to be from v2 (scalar fitness).")
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
        logbook.header = "gen", "evals", "avg_sortino", "avg_dd", "avg_pf", "pareto_size", "avg_trades_day", "max_trades_day", "avg_total_profit", "actual_dd_best", "actual_sortino_best", "actual_pf_best", "actual_pnl_best"
        start_gen = 0
        print("\nStarting fresh run...")
    
    # Statistics for multi-objective
    stats = tools.Statistics(lambda ind: ind.fitness.values)
    stats.register("avg_sortino", lambda x: np.mean([f[0] for f in x]))
    stats.register("avg_dd", lambda x: np.mean([f[1] for f in x]))  # Normalized drawdown (0-1, inverted)
    stats.register("avg_pf", lambda x: np.mean([f[2] for f in x]))
    stats.register("avg_trades_day", lambda x: np.mean([f[3] for f in x]))  # 4th objective
    stats.register("avg_total_profit", lambda x: np.mean([f[4] for f in x if len(f) > 4]))  # 5th objective
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
    
    # Main evolution loop with NSGA-II
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
                creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 5.0, 2.0))
            elif len(creator.FitnessMulti.weights) != 5:
                print(f"  WARNING: FitnessMulti class has {len(creator.FitnessMulti.weights)} weights, recreating with 5...")
                del creator.FitnessMulti
                creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 5.0, 2.0))
                # Also recreate Individual class to use new FitnessMulti
                if hasattr(creator, "Individual"):
                    del creator.Individual
                creator.create("Individual", list, fitness=creator.FitnessMulti)
                print(f"  FitnessMulti recreated with weights: {creator.FitnessMulti.weights}")
            
            for ind in offspring:
                if hasattr(ind, 'fitness') and hasattr(ind.fitness, 'weights'):
                    if len(ind.fitness.weights) != 5:
                        # Recreate fitness object with correct weights (class should now have 5)
                        ind.fitness = creator.FitnessMulti()
                        # Verify it worked
                        if len(ind.fitness.weights) != 5:
                            print(f"  ERROR: After recreation, fitness still has {len(ind.fitness.weights)} weights!")
                            print(f"  Class weights: {creator.FitnessMulti.weights if hasattr(creator, 'FitnessMulti') else 'N/A'}")
                elif not hasattr(ind, 'fitness'):
                    # No fitness object - create one
                    ind.fitness = creator.FitnessMulti()
            
            # Evaluate with parallel processing
            print(f"  Evaluating {len(offspring)} individuals in parallel ({NUM_WORKERS} workers)...")
            try:
                fits = parallel_evaluate(offspring, in_sample, param_dict, param_keys)
                
                # Validate all fitness tuples have correct length BEFORE assignment
                invalid_fits = []
                for idx, fit in enumerate(fits):
                    if len(fit) != 5:
                        invalid_fits.append((idx, fit, len(fit)))
                
                if invalid_fits:
                    print(f"  ⚠️  ERROR: Found {len(invalid_fits)} fitness tuples with wrong length:")
                    for idx, fit, length in invalid_fits[:5]:  # Show first 5
                        print(f"    Individual {idx}: length={length}, values={fit}")
                    # Fix them
                    for idx, fit, length in invalid_fits:
                        fits[idx] = (-1000.0, 100000.0, 0.0, 0.0, 0.0)
                    print(f"  Fixed {len(invalid_fits)} invalid fitness tuples.")
                
                # Diagnostic: Check if all solutions are getting penalized
                penalty_count = sum(1 for f in fits if f[0] < 0)  # Count negative Sortino (penalties)
                if penalty_count == len(fits) and gen % 5 == 0:  # Only print every 5 generations to avoid spam
                    print(f"  ⚠️  WARNING: All {len(fits)} solutions are getting penalized (likely failing MIN_TRADES_DAY={MIN_TRADES_DAY})")
                    # Sample a few to see what avg_trades_day values are
                    sample_indices = [0, len(fits)//4, len(fits)//2]
                    for idx in sample_indices:
                        sample_params = dict(zip(param_keys, offspring[idx]))
                        # Run a quick diagnostic
                        sample_metrics = run_backtest(sample_params, in_sample, param_dict, suppress_output=True)
                        trades_df = sample_metrics.get('trades_df', pd.DataFrame())
                        total_trades = len(trades_df)
                        days = (trades_df['exit_time'].max() - trades_df['entry_time'].min()).days if not trades_df.empty and len(trades_df) > 1 else 0
                        print(f"    Sample {idx}: avg_trades_day={sample_metrics['avg_trades_day']:.3f}, "
                              f"total_trades={total_trades}, days={days}")
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
                        fits.append((-1000.0, 100000.0, 0.0, 0.0, 0.0))  # Very poor fitness (5 objectives)
            
            # Assign fitness values
            for idx, (fit, ind) in enumerate(zip(fits, offspring)):
                # Safety check: ensure fitness has correct number of values
                if len(fit) != 5:
                    print(f"  ERROR: Individual {idx} has fitness tuple with {len(fit)} values, expected 5.")
                    print(f"  Fitness values: {fit}")
                    print(f"  Assigning poor fitness instead.")
                    fit = (-1000.0, 100000.0, 0.0, 0.0, 0.0)  # 5 objectives
                # Convert numpy types to Python floats (DEAP requires native Python types)
                fit = tuple(float(x) for x in fit)
                
                # Check if individual's fitness object has correct weights BEFORE assignment
                if hasattr(ind.fitness, 'weights') and len(ind.fitness.weights) != 5:
                    print(f"  WARNING: Individual {idx} has fitness with {len(ind.fitness.weights)} weights, expected 5.")
                    print(f"  Recreating fitness object with correct weights...")
                    # CRITICAL: First ensure the class itself has correct weights
                    if not hasattr(creator, 'FitnessMulti') or len(creator.FitnessMulti.weights) != 5:
                        print(f"    Class also has wrong weights ({len(creator.FitnessMulti.weights) if hasattr(creator, 'FitnessMulti') else 0}), recreating class...")
                        if hasattr(creator, "FitnessMulti"):
                            del creator.FitnessMulti
                        if hasattr(creator, "Individual"):
                            del creator.Individual
                        creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 5.0, 2.0))
                        creator.create("Individual", list, fitness=creator.FitnessMulti)
                        print(f"    Class recreated with weights: {creator.FitnessMulti.weights}")
                    # Now create new fitness object (should have 5 weights now)
                    ind.fitness = creator.FitnessMulti()
                    # Verify it worked
                    if len(ind.fitness.weights) != 5:
                        print(f"    FATAL: After class recreation, fitness still has {len(ind.fitness.weights)} weights!")
                        raise RuntimeError(f"Cannot fix fitness object - class has {len(creator.FitnessMulti.weights)} weights, expected 5")
                
                try:
                    ind.fitness.values = fit
                except AssertionError as e:
                    print(f"  FATAL ERROR assigning fitness to individual {idx}:")
                    print(f"    Fitness tuple: {fit}")
                    print(f"    Tuple length: {len(fit)}")
                    print(f"    Fitness weights: {ind.fitness.weights if hasattr(ind.fitness, 'weights') else 'N/A'}")
                    print(f"    Expected length: 5 (matching weights)")
                    print(f"    Error: {e}")
                    # Force recreate fitness object and try again
                    # CRITICAL: Ensure FitnessMulti class has correct weights first
                    if not hasattr(creator, 'FitnessMulti') or len(creator.FitnessMulti.weights) != 5:
                        print(f"    Recreating FitnessMulti class (has {len(creator.FitnessMulti.weights) if hasattr(creator, 'FitnessMulti') else 0} weights)...")
                        if hasattr(creator, "FitnessMulti"):
                            del creator.FitnessMulti
                        if hasattr(creator, "Individual"):
                            del creator.Individual
                        creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 5.0, 2.0))
                        creator.create("Individual", list, fitness=creator.FitnessMulti)
                        print(f"    Class recreated. New weights: {creator.FitnessMulti.weights}")
                    # Create new fitness object
                    ind.fitness = creator.FitnessMulti()
                    # Double-check it has correct weights
                    if len(ind.fitness.weights) != 5:
                        print(f"    FATAL: New fitness object still has {len(ind.fitness.weights)} weights!")
                        print(f"    This indicates a deeper issue with DEAP creator classes.")
                        raise RuntimeError(f"Cannot create fitness with 5 weights - class definition is corrupted")
                    ind.fitness.values = fit
                    print(f"  Fixed by recreating fitness object (now has {len(ind.fitness.weights)} weights).")
            
            # Validate all individuals have proper multi-objective fitness (4 values)
            all_individuals = offspring + pop
            for ind in all_individuals:
                if not ind.fitness.valid:
                    # Invalid fitness - assign poor fitness
                    ind.fitness.values = (-1000.0, 100000.0, 0.0, 0.0, 0.0)  # 5 objectives
                elif len(ind.fitness.values) != 5:
                    # Wrong fitness format - this shouldn't happen but handle it
                    print(f"WARNING: Individual has {len(ind.fitness.values)} fitness values, expected 5. Assigning poor fitness.")
                    ind.fitness.values = (-1000.0, 100000.0, 0.0, 0.0, 0.0)  # 5 objectives
            
            # Select next generation using NSGA-II
            pop = toolbox.select(all_individuals, POP_SIZE)
            
            # Update Pareto front
            hof.update(pop)
            
            # Record statistics
            record = stats.compile(pop)
            record['pareto_size'] = len(hof)
            
            # Calculate avg_trades_day for best individual (for tracking)
            best_ind = max(pop, key=lambda ind: ind.fitness.values[0]) if pop else None
            if best_ind:
                try:
                    best_params_temp = dict(zip(param_keys, best_ind))
                    # Clamp parameters
                    for n, v in best_params_temp.items():
                        mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
                        v = max(mn, min(v, mx))
                        if typ == 'int':
                            best_params_temp[n] = int(round(v))
                        else:
                            best_params_temp[n] = float(v)
                    best_metrics = run_backtest(best_params_temp, in_sample, param_dict, suppress_output=True)
                    record['avg_trades_day'] = best_metrics.get('avg_trades_day', 0.0)
                    record['max_trades_day'] = best_metrics.get('avg_trades_day', 0.0)  # For best individual, same as avg
                    # Store ACTUAL metrics (in real units) for the best individual
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
                print(f"  ⚠️  All solutions appear to be penalized (Sortino < 0)")
                print(f"     This suggests MIN_TRADES_DAY constraint ({MIN_TRADES_DAY}) may be too strict")
                print(f"     Consider reducing MIN_TRADES_DAY in the parameter CSV or relaxing filters")
            
            # Save checkpoint after each generation
            save_checkpoint(pop, hof, logbook, gen, current_config)
            
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
            else:
                # No solutions yet - use placeholder
                best_for_display = None
                best_params_display = {}
                best_fitness_display = (0.0, 0.0, 0.0, 0.0, 0.0)  # 5 objectives
            
            # For intermediate generations, run actual backtest to get real metrics (not normalized fitness)
            # This ensures HTML shows actual trades/day, not normalized values
            is_res_display = {'sortino': 0, 'max_drawdown': 0, 'profit_factor': 0, 'avg_trades_day': 0, 'total_profit': 0}
            trades_is_display = pd.DataFrame()
            
            if best_for_display is not None and len(in_sample) > 0:
                try:
                    # Run actual backtest to get real metrics
                    is_res_actual = run_backtest(best_params_display, in_sample, param_dict, suppress_output=True)
                    if isinstance(is_res_actual, dict):
                        is_res_display = {
                            'sortino': is_res_actual.get('sortino', 0),
                            'max_drawdown': is_res_actual.get('max_drawdown', 0),
                            'profit_factor': is_res_actual.get('profit_factor', 0),
                            'avg_trades_day': is_res_actual.get('avg_trades_day', 0),
                            'total_profit': is_res_actual.get('total_profit', 0)
                        }
                        trades_is_display = is_res_actual.get('trades_df', pd.DataFrame())
                except Exception as e:
                    print(f"  Warning: Could not run IS backtest for display: {e}")
                    # Fallback to fitness values (but these are normalized, so not ideal)
                    is_res_display = {'sortino': best_fitness_display[0], 'max_drawdown': best_fitness_display[1], 
                                     'profit_factor': best_fitness_display[2], 'avg_trades_day': best_fitness_display[3] if len(best_fitness_display) > 3 else 0, 'total_profit': best_fitness_display[4] if len(best_fitness_display) > 4 else 0}
            
            # Calculate OOS every 3 generations (or on first generation) to show progress without slowing down too much
            oos_res_display = {'sortino': 0, 'max_drawdown': 0, 'profit_factor': 0, 'avg_trades_day': 0, 'total_profit': 0}
            trades_oos_display = pd.DataFrame()
            
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
                    in_sample=in_sample
                )
                # Also copy to diagnostics directory for backup
                try:
                    import shutil
                    if os.path.exists(WEB_DASHBOARD):
                        shutil.copy2(WEB_DASHBOARD, HTML_DASHBOARD)
                except Exception as e:
                    pass  # Silent fail for backup copy
                
                if auto_launch_now:
                    print(f"  HTML Dashboard updated and opened → {WEB_DASHBOARD}")
                else:
                    print(f"  HTML Dashboard updated → {WEB_DASHBOARD}")
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
        return
    
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
        """Group parameters into logical categories."""
        groups = {
            'Entry Criteria': ['Enable Long Trades', 'Enable Short Trades', 'Bollinger Band Length', 
                              'Bollinger Band StdDev', 'Long Entry on Wick Touch', 'Long Entry on Body in Zone',
                              'Long Trigger (% From Lower Band)', 'Short Entry on Wick Touch', 
                              'Short Entry on Body in Zone', 'Short Trigger (% From Upper Band)',
                              'Max ATR Filter (Points)', 'RTH Start (HH:MM)', 'RTH End (HH:MM)',
                              'Enable RTH Filter', 'Max Volume Multiplier', 'Timeframe (minutes)',
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
        is_res = run_backtest(best_params, in_sample, param_dict, suppress_output=False, debug=True)
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
            oos_res = run_backtest(best_params, oos, param_dict, suppress_output=False)
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
    # DIAGNOSTIC PLOTS → ga_diagnostics/
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
    print(f"Plot → {DIAG_DIR}/convergence_multi_objective.png")
    
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
        print(f"Plot → {DIAG_DIR}/pareto_front.png")
    
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
    print(f"Plot → {DIAG_DIR}/pareto_size.png")
    
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
    print(f"Parameter plots → {DIAG_DIR}/param_evolution/")
    
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
        print(f"Plot → {DIAG_DIR}/oos_pnl_hist.png")
        
        plt.figure(figsize=(8, 4))
        plt.scatter(trades_oos.index, trades_oos['pnl'], c=np.where(trades_oos['pnl'] > 0, 'g', 'r'))
        plt.title('OOS Wins (Green) / Losses (Red)')
        plt.ylabel('PNL')
        plt.grid()
        plt.tight_layout()
        plt.savefig(f'{DIAG_DIR}/oos_win_loss.png')
        plt.close()
        print(f"Plot → {DIAG_DIR}/oos_win_loss.png")
        
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
        print(f"Plot → {DIAG_DIR}/oos_trade_duration.png")
        
        equity = 50000 + trades_oos.groupby(trades_oos['exit_time'].dt.date)['pnl'].sum().cumsum()
        plt.figure(figsize=(10, 4))
        equity.plot()
        plt.title('OOS Equity Curve')
        plt.ylabel('Equity')
        plt.grid()
        plt.tight_layout()
        plt.savefig(f'{DIAG_DIR}/oos_equity.png')
        plt.close()
        print(f"OOS equity → {DIAG_DIR}/oos_equity.png")
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
                            current_gen=NUM_GEN, total_gen=NUM_GEN, is_final=True, auto_launch=True)
    print(f"HTML Dashboard (FINAL) → {WEB_DASHBOARD}")
    
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
    print(f"Optimized CSV with {num_solutions} solutions → {OUTPUT_CSV}")
    print(f"  Solution_0_SELECTED = Best solution (highest Sortino)")
    print(f"  Solution_1, Solution_2, ... = Other Pareto-optimal solutions")
    print(f"  Statistics rows added at bottom showing metrics for each solution")
    
    # Optionally keep checkpoint file for later analysis (all solutions now saved in CSV)
    # Uncomment to delete checkpoint after successful completion:
    # if os.path.exists(CHECKPOINT_FILE):
    #     os.remove(CHECKPOINT_FILE)
    #     print(f"Checkpoint file removed: {CHECKPOINT_FILE}")
    if os.path.exists(CHECKPOINT_FILE):
        print(f"Checkpoint file kept: {CHECKPOINT_FILE} (all solutions also saved in CSV)")


if __name__ == "__main__":
    # Required for Windows multiprocessing
    multiprocessing.freeze_support()
    main()


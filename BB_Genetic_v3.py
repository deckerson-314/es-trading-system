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

# ----------------------------------------------------------------------
# CSV INPUT / OUTPUT
# ----------------------------------------------------------------------
PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'
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
param_keys = []

# ----------------------------------------------------------------------
# Back-tester using shared strategy module
# ----------------------------------------------------------------------
def run_backtest(params, df, param_dict_local, suppress_output=True):
    """
    Run backtest using shared strategy module.
    
    Args:
        params: Dictionary of optimizable parameters
        df: DataFrame with OHLCV data
        param_dict_local: Parameter dictionary (passed to avoid global access)
        suppress_output: If False, print progress
        
    Returns:
        dict with metrics: sortino, max_drawdown, avg_trades_day, profit_factor, trades_df
    """
    if len(df) == 0:
        return {'sortino': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0,
                'trades_df': pd.DataFrame()}
    
    # Create strategy instance
    strategy = BollingerBandStrategy(param_dict_local)
    
    # Update optimizable parameters
    strategy.update_optimizable_params(params)
    
    # Calculate indicators
    df = strategy.calculate_indicators(df)
    if len(df) == 0:
        return {'sortino': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0,
                'trades_df': pd.DataFrame()}
    
    # Apply filters
    df = strategy.apply_filters(df)
    if len(df) == 0:
        return {'sortino': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0,
                'trades_df': pd.DataFrame()}
    
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
            continue
        
        enter_long, enter_short = strategy.check_entry(row, df)
        
        if enter_long or enter_short:
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
    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        return {'sortino': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0,
                'trades_df': trades_df}
    
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
            # Cap Sortino at 100 to prevent extreme values (even best strategies rarely exceed 10-20)
            sortino = min(sortino, 100.0)
        else:
            downside_std = downside_rets.std()
            sortino = (rets.mean() / downside_std * np.sqrt(252)) if downside_std != 0 else 0.0
            # Cap Sortino at 100 to prevent extreme values
            sortino = min(sortino, 100.0)
    
    # Max drawdown
    peak = 50000
    dd = 0
    for p in equity:
        if p > peak:
            peak = p
        else:
            dd = max(dd, peak - p)
    
    days = (trades_df['exit_time'].max() - trades_df['entry_time'].min()).days or 1
    avg_trades_day = len(trades_df) / days
    
    # Profit factor
    avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean() if (trades_df['pnl'] > 0).any() else 0
    avg_loss = trades_df[trades_df['pnl'] < 0]['pnl'].mean() if (trades_df['pnl'] < 0).any() else 0
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    
    return {
        'sortino': sortino,
        'max_drawdown': dd,
        'avg_trades_day': avg_trades_day,
        'profit_factor': profit_factor,
        'trades_df': trades_df
    }

# ----------------------------------------------------------------------
# Multi-objective GA setup
# ----------------------------------------------------------------------
# Clear any existing creator classes to avoid conflicts
if hasattr(creator, "FitnessMulti"):
    del creator.FitnessMulti
if hasattr(creator, "Individual"):
    del creator.Individual

# Multi-objective fitness: (maximize Sortino, minimize Drawdown, maximize Profit Factor)
creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0))
creator.create("Individual", list, fitness=creator.FitnessMulti)

def create_individual():
    global PARAM_RANGES
    if PARAM_RANGES is None:
        raise RuntimeError("PARAM_RANGES not initialized. Call main() first.")
    return creator.Individual(random.uniform(lo, hi) for lo, hi in PARAM_RANGES.values())

def custom_mutate(ind):
    global PARAM_RANGES, MUT_MU, MUT_SIGMA
    if PARAM_RANGES is None:
        raise RuntimeError("PARAM_RANGES not initialized. Call main() first.")
    tools.mutGaussian(ind, mu=MUT_MU, sigma=MUT_SIGMA, indpb=0.2)
    for i, (lo, hi) in enumerate(PARAM_RANGES.values()):
        ind[i] = max(lo, min(ind[i], hi))
    return ind,

def evaluate_multi_objective(ind_and_df):
    """
    Evaluate individual with multi-objective fitness.
    
    Returns:
        tuple: (sortino, -max_drawdown, profit_factor)
        Note: Drawdown is negated because we want to minimize it (weights=-1.0)
    """
    global param_keys, param_dict
    ind, df = ind_and_df
    params = dict(zip(param_keys, ind))
    
    # Clamp & cast - ensure integer parameters are properly rounded
    for n, v in params.items():
        mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
        v = max(mn, min(v, mx))
        if typ == 'int':
            # Round to nearest integer for all int parameters
            params[n] = int(round(v))
        else:
            params[n] = float(v)
    
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
    
    # Check trade frequency constraints (use values from param_dict)
    target_trades = param_dict.get('TARGET_TRADES_DAY', {'value': 2})['value']
    min_trades = param_dict.get('MIN_TRADES_DAY', {'value': 1.0})['value']
    excess_pen = max(0.0, metrics['avg_trades_day'] - target_trades)
    low_pen = max(0.0, min_trades - metrics['avg_trades_day'])
    
    # Apply penalties to objectives if constraints violated
    sortino = metrics['sortino']
    max_dd = metrics['max_drawdown']
    pf = metrics['profit_factor']
    trades_df = metrics.get('trades_df', pd.DataFrame())
    
    # VALIDATION: Detect unrealistic results and heavily penalize them
    unrealistic = False
    
    # Check for unrealistic win rate (>95% is suspicious)
    if not trades_df.empty:
        win_rate = (trades_df['pnl'] > 0).sum() / len(trades_df)
        if win_rate > 0.95:
            unrealistic = True
    
    # Check for very short average trade duration (< 2 minutes is suspicious for 1-min bars)
    if not trades_df.empty and 'entry_time' in trades_df.columns and 'exit_time' in trades_df.columns:
        durations = (trades_df['exit_time'] - trades_df['entry_time']).dt.total_seconds() / 60
        avg_duration = durations.mean()
        if avg_duration < 2.0:  # Less than 2 minutes average
            unrealistic = True
    
    # Check for infinite profit factor (no losses)
    if pf == float('inf') or pf > 100:
        unrealistic = True
    
    # Check for zero drawdown (unrealistic)
    if max_dd == 0.0 and not trades_df.empty and len(trades_df) > 10:
        unrealistic = True
    
    # Heavy penalty for unrealistic results
    if unrealistic:
        sortino = -1000.0  # Very poor fitness
        max_dd = 1000000.0  # Very poor fitness
        pf = 0.0
    
    # Cap Sortino at 100 to prevent unrealistic values
    sortino = min(sortino, 100.0)
    
    # Heavy penalty for too few trades (violates minimum constraint)
    if low_pen > 0:
        sortino = -100.0  # Very poor fitness
        max_dd = 100000.0  # Very poor fitness
        pf = 0.0
    
    # Light penalty for too many trades (soft constraint)
    if excess_pen > 0:
        sortino *= (1.0 - excess_pen * 0.1)  # Reduce sortino slightly
        pf *= (1.0 - excess_pen * 0.1)  # Reduce profit factor slightly
    
    # Return multi-objective fitness: (maximize sortino, minimize drawdown, maximize profit_factor)
    return (sortino, max_dd, pf)

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
        Fitness tuple: (sortino, max_dd, pf)
    """
    ind, df_local, param_dict_local, param_keys_local = args
    
    # Use the passed parameters instead of globals
    params = dict(zip(param_keys_local, ind))
    
    # Clamp & cast - ensure integer parameters are properly rounded
    for n, v in params.items():
        mn, mx, typ = param_dict_local[n]['min'], param_dict_local[n]['max'], param_dict_local[n]['type']
        v = max(mn, min(v, mx))
        if typ == 'int':
            # Round to nearest integer for all int parameters
            params[n] = int(round(v))
        else:
            params[n] = float(v)
    
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
    
    # Check trade frequency constraints (use values from param_dict_local)
    target_trades = param_dict_local.get('TARGET_TRADES_DAY', {'value': 2})['value']
    min_trades = param_dict_local.get('MIN_TRADES_DAY', {'value': 1.0})['value']
    excess_pen = max(0.0, metrics['avg_trades_day'] - target_trades)
    low_pen = max(0.0, min_trades - metrics['avg_trades_day'])
    
    # Apply penalties to objectives if constraints violated
    sortino = metrics['sortino']
    max_dd = metrics['max_drawdown']
    pf = metrics['profit_factor']
    
    # Cap Sortino at 100 to prevent unrealistic values
    sortino = min(sortino, 100.0)
    
    # Heavy penalty for too few trades (violates minimum constraint)
    # BUT: Use a gradient penalty instead of hard cutoff to allow some diversity
    if low_pen > 0:
        # Gradient penalty: worse penalty for larger violations
        # This allows solutions with slightly fewer trades to still compete
        penalty_factor = min(1.0, low_pen / min_trades)  # 0 to 1 based on how far below min
        sortino = -100.0 * penalty_factor  # Scale penalty
        max_dd = 100000.0 * penalty_factor  # Scale penalty
        pf = 0.0 * (1.0 - penalty_factor)  # Scale penalty
    
    # Light penalty for too many trades (soft constraint)
    if excess_pen > 0:
        sortino *= (1.0 - excess_pen * 0.1)  # Reduce sortino slightly
        pf *= (1.0 - excess_pen * 0.1)  # Reduce profit factor slightly
    
    # Return multi-objective fitness: (maximize sortino, minimize drawdown, maximize profit_factor)
    return (sortino, max_dd, pf)

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
    pool = multiprocessing.Pool(processes=NUM_WORKERS)
    try:
        # Use map_async with timeout for better interrupt handling
        # Pass all necessary data to the worker function
        async_result = pool.map_async(_evaluate_worker, 
                                     [(ind, df, param_dict_local, param_keys_local) for ind in individuals])
        # Wait with timeout to allow interruption
        try:
            results = async_result.get(timeout=3600)  # 1 hour timeout (should never hit)
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
                            is_final=False, auto_launch=False, is_periods=None, oos_periods=None):
    """
    Generate comprehensive interactive HTML dashboard for GA results.
    
    Args:
        current_gen: Current generation number (for progress tracking)
        total_gen: Total number of generations
        is_final: Whether this is the final generation
        auto_launch: Whether to auto-launch the HTML file
    """
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
        pareto_data.append({
            'index': i,
            'sortino': fitness[0],
            'max_dd': fitness[1],
            'profit_factor': fitness[2],
            'params': clamped_params,  # Use clamped parameters
            'is_selected': (ind == best)
        })
    
    pareto_df = pd.DataFrame(pareto_data)
    
    # Sort by different criteria for top candidates
    top_sortino = pareto_df.nlargest(5, 'sortino')
    top_pf = pareto_df.nlargest(5, 'profit_factor')
    top_dd = pareto_df.nsmallest(5, 'max_dd')
    
    # Create convergence plots
    gens = logbook.select("gen")
    fig_convergence = make_subplots(rows=1, cols=3,
        subplot_titles=('Sortino Convergence', 'Drawdown Convergence', 'Profit Factor Convergence'))
    
    fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("avg_sortino"), name='Avg', line=dict(dash='dash')), row=1, col=1)
    fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("max_sortino"), name='Best', line=dict(width=2)), row=1, col=1)
    fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("avg_dd"), name='Avg', line=dict(dash='dash')), row=1, col=2)
    fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("min_dd"), name='Best', line=dict(width=2)), row=1, col=2)
    fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("avg_pf"), name='Avg', line=dict(dash='dash')), row=1, col=3)
    fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("max_pf"), name='Best', line=dict(width=2)), row=1, col=3)
    fig_convergence.update_layout(height=400, showlegend=True, title_text="Convergence Plots")
    fig_convergence.update_xaxes(title_text="Generation")
    fig_convergence.update_yaxes(title_text="Sortino", row=1, col=1)
    fig_convergence.update_yaxes(title_text="Drawdown", row=1, col=2)
    fig_convergence.update_yaxes(title_text="Profit Factor", row=1, col=3)
    
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
        hovertemplate="<b>%{{text}}</b><extra></extra>"
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
    pareto_table_html = """<table class='pareto-table'><thead><tr>
        <th>Rank<span class="tooltip-icon">?</span><span class="tooltip">Ranking by Sortino Ratio (highest to lowest). Lower rank = better risk-adjusted returns.</span></th>
        <th>Sortino<span class="tooltip-icon">?</span><span class="tooltip">Sortino Ratio - risk-adjusted return focusing on downside volatility. Higher is better.</span></th>
        <th>Max DD<span class="tooltip-icon">?</span><span class="tooltip">Maximum Drawdown in dollars. Lower is better for risk management.</span></th>
        <th>PF<span class="tooltip-icon">?</span><span class="tooltip">Profit Factor (Gross Profit / Gross Loss). Values >1.0 are profitable, >2.0 are excellent.</span></th>
        <th>Selected<span class="tooltip-icon">?</span><span class="tooltip">★ indicates the solution selected for use (highest Sortino Ratio).</span></th>
    </tr></thead><tbody>"""
    pareto_sorted = sorted(pareto_data, key=lambda x: x['sortino'], reverse=True)
    for rank, sol in enumerate(pareto_sorted, 1):
        mark = "★" if sol['is_selected'] else ""
        pareto_table_html += f"<tr class='{'selected-row' if sol['is_selected'] else ''}'><td>{rank}</td><td>{sol['sortino']:.4f}</td><td>{sol['max_dd']:.2f}</td><td>{sol['profit_factor']:.4f}</td><td>{mark}</td></tr>"
    pareto_table_html += "</tbody></table>"
    
    # Best params table - grouped by category
    def group_parameters(param_keys_local, param_dict_local):
        """Group parameters into logical categories."""
        groups = {
            'Entry Criteria': [],
            'Take Profit Criteria': [],
            'Stop Loss Criteria': [],
            'GA Criteria': []
        }
        
        # Define parameter groups
        entry_params = ['Enable Long Trades', 'Enable Short Trades', 'Bollinger Band Length', 
                        'Bollinger Band StdDev', 'Long Entry on Wick Touch', 'Long Entry on Body in Zone',
                        'Long Trigger (% From Lower Band)', 'Short Entry on Wick Touch', 
                        'Short Entry on Body in Zone', 'Short Trigger (% From Upper Band)',
                        'Min ATR Filter (Points)', 'RTH Start (HH:MM)', 'RTH End (HH:MM)',
                        'Enable RTH Filter', 'Min Volume Multiplier', 'Timeframe (minutes)',
                        'Max Open Trades']
        
        tp_params = ['Opposite Bollinger Band TP', 'Fixed ATR TP', 'Fixed BB at Entry TP',
                    'ATR Length for TP', 'ATR Multiplier for TP']
        
        sl_params = ['Initial Stop Loss (%)', 'Enable Trailing Stop', 
                     'ATR Length for Trailing Stop', 'ATR Multiplier for Trailing Stop',
                     'Trailing Delay (bars)']
        
        ga_params = ['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                     'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                     'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                     'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT']
        
        # Group parameters
        for pname in param_keys_local:
            if pname in entry_params:
                groups['Entry Criteria'].append(pname)
            elif pname in tp_params:
                groups['Take Profit Criteria'].append(pname)
            elif pname in sl_params:
                groups['Stop Loss Criteria'].append(pname)
            elif pname in ga_params:
                groups['GA Criteria'].append(pname)
            else:
                # Default to Entry Criteria if not found
                groups['Entry Criteria'].append(pname)
        
        return groups
    
    param_groups = group_parameters(param_keys, param_dict)
    
    best_params_html = ""
    for group_name, params_list in param_groups.items():
        if params_list:  # Only show group if it has parameters
            best_params_html += f"<h3 style='margin-top: 20px; color: #555; border-bottom: 2px solid #ddd; padding-bottom: 5px;'>{group_name}</h3>"
            best_params_html += "<table class='params-table'><thead><tr><th>Parameter</th><th>Value</th></tr></thead><tbody>"
            for pname in params_list:
                if pname in best_params:
                    val = best_params[pname]
                    typ = param_dict[pname].get('type', 'float')
                    formatted = int(round(val)) if typ == 'int' else f"{val:.4f}"
                    best_params_html += f"<tr><td>{pname}</td><td>{formatted}</td></tr>"
            best_params_html += "</tbody></table>"
    
    # Comparison table - match console output exactly
    comparison_html = """<table class='comparison-table'><thead><tr>
        <th>Metric<span class="tooltip-icon">?</span><span class="tooltip">Performance metric being compared between training (IS) and validation (OOS) data.</span></th>
        <th>In-Sample<span class="tooltip-icon">?</span><span class="tooltip">Performance on training data used for optimization. This is what the GA optimized for.</span></th>
        <th>OOS<span class="tooltip-icon">?</span><span class="tooltip">Out-of-Sample performance on validation data not seen during optimization. This tests generalization.</span></th>
        <th>Difference<span class="tooltip-icon">?</span><span class="tooltip">OOS - IS. Green = OOS better (good generalization), Red = OOS worse (potential overfitting).</span></th>
    </tr></thead><tbody>"""
    
    # Metrics to compare (matching console output)
    metrics_to_compare = [
        ('sortino', 'Sortino Ratio', False),  # (key, display_name, lower_is_better)
        ('max_drawdown', 'Max Drawdown', True),
        ('avg_trades_day', 'Avg Trades/Day', False),
        ('profit_factor', 'Profit Factor', False)
    ]
    
    for metric_key, metric_name, lower_is_better in metrics_to_compare:
        # Get values from backtest results (these should match console output)
        is_val = is_res.get(metric_key, 0) if isinstance(is_res, dict) else 0
        oos_val = oos_res.get(metric_key, 0) if isinstance(oos_res, dict) else 0
        
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
    
    # Extract div and script from each chart
    def extract_chart_html(html_snippet):
        div_start = html_snippet.find('<div')
        div_end = html_snippet.find('</div>') + 6
        script_start = html_snippet.find('<script')
        script_end = html_snippet.find('</script>') + 9
        div_part = html_snippet[div_start:div_end]
        script_part = html_snippet[script_start:script_end]
        return div_part, script_part
    
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
        
        progress_html = f"""
<div style="background: {status_color}; color: white; padding: 15px; border-radius: 5px; margin: 20px 0;">
    <h3 style="margin: 0 0 10px 0;">Optimization Status: {status}</h3>
    <div style="background: rgba(255,255,255,0.3); border-radius: 3px; height: 30px; position: relative; margin: 10px 0;">
        <div style="background: white; height: 100%; width: {progress_pct}%; border-radius: 3px; transition: width 0.3s;"></div>
        <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-weight: bold; color: {status_color};">
            Generation {current_gen} / {total_gen} ({progress_pct:.1f}%)
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
    
    # Generate full HTML with tooltips and auto-refresh
    # Auto-refresh every 30 seconds if not final
    refresh_meta = '<meta http-equiv="refresh" content="30">' if not is_final else ''
    
    html_content = f"""<!DOCTYPE html>
<html><head><title>GA Dashboard v3.0</title>
{refresh_meta}
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
<style>
body {{ font-family: Arial; margin: 20px; background: #f5f5f5; }}
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
.return-button {{ display: inline-block; margin-bottom: 20px; padding: 10px 20px; background: #667eea; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; }}
.return-button:hover {{ background: #5568d3; }}
</style></head><body>
<div class="container">
<a href="index.html" class="return-button">← Back to Main Dashboard</a>
<h1>GA Optimization Dashboard - v3.0</h1>
<p><strong>Generated:</strong> {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
{progress_html}
<div class="metric-box">
    Pareto Solutions: {len(hof)}
    <span class="tooltip">Number of non-dominated solutions found. These represent the best trade-offs between Sortino Ratio, Max Drawdown, and Profit Factor. Higher is generally better, indicating more diverse optimal solutions.</span>
</div>
<div class="metric-box">
    Generations: {len(gens)}
    <span class="tooltip">Total number of generations completed. Each generation evaluates a population of candidate solutions and evolves them through selection, crossover, and mutation.</span>
</div>
<h2>Selected Solution Performance<span class="tooltip-icon">?</span>
    <span class="tooltip">The best solution selected from the Pareto front based on highest Sortino Ratio. This represents the optimized strategy parameters that will be used for live trading.</span>
</h2>
<div class="info-section">
    <strong>Selection Criteria:</strong> The solution with the highest Sortino Ratio is selected as the "best" solution. This prioritizes risk-adjusted returns while still considering drawdown and profit factor through the Pareto front.
</div>
<h3>Actual Backtest Results (In-Sample)</h3>
<div class="metric-box">
    Sortino: {is_res.get('sortino', 0) if isinstance(is_res, dict) else 0:.6f}
    <span class="tooltip">Sortino Ratio measures risk-adjusted returns, focusing only on downside volatility (negative returns). Higher is better. Values above 1.0 are considered good, above 2.0 are excellent. This is preferred over Sharpe Ratio for trading strategies as it doesn't penalize upside volatility.</span>
</div>
<div class="metric-box">
    Max DD: ${is_res.get('max_drawdown', 0) if isinstance(is_res, dict) else 0:,.2f}
    <span class="tooltip">Maximum Drawdown is the largest peak-to-trough decline in equity during the backtest period. Lower is better. This represents the worst-case loss an investor would have experienced. Critical for risk management.</span>
</div>
<div class="metric-box">
    PF: {is_res.get('profit_factor', 0) if isinstance(is_res, dict) else 0:.6f}
    <span class="tooltip">Profit Factor = Total Gross Profit / Total Gross Loss. Values above 1.0 indicate profitable strategy. Above 2.0 is excellent. This metric shows the ratio of winning to losing trades in dollar terms.</span>
</div>
<div class="metric-box">
    Avg Trades/Day: {is_res.get('avg_trades_day', 0) if isinstance(is_res, dict) else 0:.6f}
    <span class="tooltip">Average number of trades executed per day. This helps assess strategy activity level. Too few trades may indicate over-filtering, too many may indicate overtrading. Target range is typically 1-5 trades/day.</span>
</div>
<p><em>Note: GA fitness values (used for optimization) may differ from actual backtest results due to penalties for constraint violations.</em></p>
<h2>Parameters<span class="tooltip-icon">?</span>
    <span class="tooltip">Optimized parameter values for the selected solution. These are the actual values that will be used in live trading. Compare these to your initial parameter ranges to see how the GA adjusted them.</span>
</h2>
{best_params_html}
<h2>Convergence<span class="tooltip-icon">?</span>
    <span class="tooltip">Convergence plots show how the optimization objectives improve over generations. Look for: (1) Steady upward trend in Sortino and Profit Factor, (2) Steady downward trend in Drawdown, (3) Convergence where improvements plateau (indicates optimization is complete). If lines are still improving, consider running more generations.</span>
</h2>
<div class="info-section">
    <strong>Interpreting Convergence:</strong> The "Best" line shows the best individual in each generation. The "Avg" line shows the population average. Convergence occurs when both lines plateau. If they're still improving, the GA may benefit from more generations. Divergence between Best and Avg indicates good diversity in the population.
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
                        days = (period_trades['exit_time'].max() - period_trades['entry_time'].min()).days or 1
                        avg_trades_day = num_trades / days
                        
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
    
    html_content += """
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
    <strong>Solution Selection:</strong> While the highest Sortino solution is automatically selected, you may want to manually review other solutions. For example, if Solution #2 has similar Sortino but much lower drawdown, it might be a better choice for risk-averse trading. All solutions in this table are Pareto-optimal.
</div>
{pareto_table_html}
</div>
{conv_script}
{pareto3d_script}
{pareto2d_script}
{paretosize_script}
</body></html>"""
    
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    # Auto-launch only if requested (first update or final update)
    if auto_launch:
        try:
            webbrowser.open(f'file://{os.path.abspath(html_path)}')
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
                if fitness_len != 3:
                    print(f"\n=== CHECKPOINT INCOMPATIBLE ===")
                    print(f"Checkpoint contains individuals with {fitness_len} fitness values.")
                    print(f"v3 requires 3 fitness values (multi-objective: sortino, max_dd, pf).")
                    print(f"This checkpoint appears to be from v2 (scalar fitness).")
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
    global TARGET_TRADES_DAY, TRADES_PENALTY_WEIGHT, DD_WEIGHT
    global DATA_SPLITS, DATA_SIZE, MIN_TRADES_DAY, MIN_TRADES_PEN_WEIGHT
    global PARAM_RANGES, param_keys, param_dict, param_df
    
    print("# Genetic Optimization for Bollinger Band Strategy - Version 3.0")
    print("# Multi-core parallelization | Multi-objective (NSGA-II) | Sortino Ratio")
    print("# Checkpoint/Resume enabled - saves after each generation")
    
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
                              'Min ATR Filter (Points)', 'RTH Start (HH:MM)', 'RTH End (HH:MM)',
                              'Enable RTH Filter', 'Min Volume Multiplier', 'Timeframe (minutes)',
                              'Max Open Trades'],
            'Take Profit Criteria': ['Opposite Bollinger Band TP', 'Fixed ATR TP', 'Fixed BB at Entry TP',
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
    PARAM_RANGES = {n: (d['min'], d['max']) for n, d in param_dict.items()
                    if d['type'] in ('int', 'float') and d['min'] is not None and d['max'] is not None}
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
        print(f"  Date range: {in_sample.index[0]} to {in_sample.index[-1]}")
        print(f"Combined OOS: {len(oos):,} rows ({len(oos)/len(df)*100:.1f}%)")
        if len(oos) > 0:
            print(f"  Date range: {oos.index[0]} to {oos.index[-1]}")
        print("=" * 50)
    else:
        # Simple chronological split (original approach)
        split = int(len(df) * DATA_SPLITS)
        in_sample, oos = df.iloc[:split], df.iloc[split:]
        print(f"\n=== Using Simple Chronological Split ===")
        print(f"IS: {len(in_sample)} rows ({len(in_sample)/len(df)*100:.1f}%)")
        print(f"OOS: {len(oos)} rows ({len(oos)/len(df)*100:.1f}%)")
        print("=" * 50)
    
    # Try to load checkpoint
    checkpoint_data = load_checkpoint()
    
    if checkpoint_data is not None:
        pop, hof, logbook, start_gen, saved_config = checkpoint_data
        
        # Validate all individuals in loaded population have correct fitness format
        invalid_individuals = []
        for i, ind in enumerate(pop):
            if not hasattr(ind, 'fitness') or not ind.fitness.valid:
                invalid_individuals.append(i)
            elif len(ind.fitness.values) != 3:
                invalid_individuals.append(i)
        
        if invalid_individuals:
            print(f"\n=== CHECKPOINT INCOMPATIBLE ===")
            print(f"Found {len(invalid_individuals)} individuals with invalid fitness format.")
            print(f"v3 requires 3 fitness values (multi-objective: sortino, max_dd, pf).")
            print(f"This checkpoint appears to be from v2 (scalar fitness).")
            print(f"Starting fresh run...")
            print("=" * 50)
            # Start fresh
            pop = toolbox.population(n=POP_SIZE)
            hof = tools.ParetoFront()  # Store Pareto-optimal solutions
            logbook = tools.Logbook()
            logbook.header = "gen", "evals", "avg_sortino", "avg_dd", "avg_pf", "pareto_size"
            start_gen = 0
        elif not verify_config_compatibility(saved_config, current_config):
            print("\nWARNING: Config mismatch detected!")
            print("Continuing with saved checkpoint despite config mismatch...")
            print("(Delete checkpoint file to start fresh if needed)")
    else:
        # Start fresh
        pop = toolbox.population(n=POP_SIZE)
        hof = tools.ParetoFront()  # Store Pareto-optimal solutions
        logbook = tools.Logbook()
        logbook.header = "gen", "evals", "avg_sortino", "avg_dd", "avg_pf", "pareto_size"
        start_gen = 0
        print("\nStarting fresh run...")
    
    # Statistics for multi-objective
    stats = tools.Statistics(lambda ind: ind.fitness.values)
    stats.register("avg_sortino", lambda x: np.mean([f[0] for f in x]))
    stats.register("avg_dd", lambda x: np.mean([f[1] for f in x]))
    stats.register("avg_pf", lambda x: np.mean([f[2] for f in x]))
    stats.register("min_dd", lambda x: np.min([f[1] for f in x]))
    stats.register("max_sortino", lambda x: np.max([f[0] for f in x]))
    stats.register("max_pf", lambda x: np.max([f[2] for f in x]))
    
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
            print(f"Generation {gen} starting...")
            print(f"  (Press Ctrl+C to interrupt - will save checkpoint after current generation)")
            
            # Create offspring using variation operators
            offspring = algorithms.varAnd(pop, toolbox, CX_PB, MUT_PB)
            
            # Evaluate with parallel processing
            print(f"  Evaluating {len(offspring)} individuals in parallel ({NUM_WORKERS} workers)...")
            try:
                fits = parallel_evaluate(offspring, in_sample, param_dict, param_keys)
                
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
                        fits.append((-1000.0, 100000.0, 0.0))  # Very poor fitness
            
            # Assign fitness values
            for fit, ind in zip(fits, offspring):
                ind.fitness.values = fit
            
            # Validate all individuals have proper multi-objective fitness (3 values)
            all_individuals = offspring + pop
            for ind in all_individuals:
                if not ind.fitness.valid:
                    # Invalid fitness - assign poor fitness
                    ind.fitness.values = (-1000.0, 100000.0, 0.0)
                elif len(ind.fitness.values) != 3:
                    # Wrong fitness format - this shouldn't happen but handle it
                    print(f"WARNING: Individual has {len(ind.fitness.values)} fitness values, expected 3. Assigning poor fitness.")
                    ind.fitness.values = (-1000.0, 100000.0, 0.0)
            
            # Select next generation using NSGA-II
            pop = toolbox.select(all_individuals, POP_SIZE)
            
            # Update Pareto front
            hof.update(pop)
            
            # Record statistics
            record = stats.compile(pop)
            record['pareto_size'] = len(hof)
            logbook.record(gen=gen, evals=len(pop), **record)
            
            print(f"{gen}\t{len(pop)}\t{round(record['avg_sortino'], 4)}\t{round(record['avg_dd'], 2)}\t{round(record['avg_pf'], 4)}\t{len(hof)}")
            print(f"  Best: Sortino={round(record['max_sortino'], 4)}, DD={round(record['min_dd'], 2)}, PF={round(record['max_pf'], 4)}")
            
            # Diagnostic: If all solutions are penalized, show more info
            if record['max_sortino'] < 0 and gen % 5 == 0:  # Only print every 5 generations
                print(f"  ⚠️  All solutions appear to be penalized (Sortino < 0)")
                print(f"     This suggests MIN_TRADES_DAY constraint ({MIN_TRADES_DAY}) may be too strict")
                print(f"     Consider reducing MIN_TRADES_DAY in the parameter CSV or relaxing filters")
            
            # Save checkpoint after each generation
            save_checkpoint(pop, hof, logbook, gen, current_config)
            
            # Update HTML dashboard after each generation (with progress info)
            # Select best solution for display (highest Sortino)
            if len(hof) > 0:
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
                best_fitness_display = (0.0, 0.0, 0.0)
            
            # For intermediate generations, use placeholder data (will be updated at end)
            is_res_display = {'sortino': best_fitness_display[0], 'max_drawdown': best_fitness_display[1], 
                             'profit_factor': best_fitness_display[2], 'avg_trades_day': 0}
            oos_res_display = {'sortino': 0, 'max_drawdown': 0, 'profit_factor': 0, 'avg_trades_day': 0}
            trades_is_display = pd.DataFrame()
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
                    oos_periods=oos_periods if 'oos_periods' in locals() else None
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
    print(f"Fitness: Sortino={best_fitness[0]:.4f}, MaxDD={best_fitness[1]:.2f}, PF={best_fitness[2]:.4f}")
    print(f"Parameters (grouped by category):")
    
    # Group parameters for display
    def group_params_for_display(params_dict_local):
        """Group parameters into logical categories."""
        groups = {
            'Entry Criteria': ['Enable Long Trades', 'Enable Short Trades', 'Bollinger Band Length', 
                              'Bollinger Band StdDev', 'Long Entry on Wick Touch', 'Long Entry on Body in Zone',
                              'Long Trigger (% From Lower Band)', 'Short Entry on Wick Touch', 
                              'Short Entry on Body in Zone', 'Short Trigger (% From Upper Band)',
                              'Min ATR Filter (Points)', 'RTH Start (HH:MM)', 'RTH End (HH:MM)',
                              'Enable RTH Filter', 'Min Volume Multiplier', 'Timeframe (minutes)',
                              'Max Open Trades'],
            'Take Profit Criteria': ['Opposite Bollinger Band TP', 'Fixed ATR TP', 'Fixed BB at Entry TP',
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
    is_res = run_backtest(best_params, in_sample, param_dict, suppress_output=False)
    trades_is = is_res.pop('trades_df')
    trades_is.to_csv(TRADES_IS_CSV, index=False)
    
    oos_res = run_backtest(best_params, oos, param_dict, suppress_output=False)
    trades_oos = oos_res.pop('trades_df')
    trades_oos.to_csv(TRADES_OOS_CSV, index=False)
    
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
    # Write optimized CSV (maintains grouping structure)
    # ------------------------------------------------------------------
    for name, val in best_params.items():
        # Find the parameter in the dataframe (skip section headers)
        matching_rows = param_df[param_df['Name'] == name]
        if not matching_rows.empty:
            idx = matching_rows.index[0]
            typ = param_dict[name]['type']
            param_df.at[idx, 'Value'] = int(val) if typ == 'int' else round(val, 4)
    param_df.to_csv(OUTPUT_CSV, index=False)
    print(f"Optimized CSV → {OUTPUT_CSV}")
    
    # Clean up checkpoint file on successful completion
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        print(f"Checkpoint file removed: {CHECKPOINT_FILE}")


if __name__ == "__main__":
    # Required for Windows multiprocessing
    multiprocessing.freeze_support()
    main()


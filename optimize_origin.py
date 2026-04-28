#!/usr/bin/env python3
"""
Genetic Optimization for Bollinger Band Strategy - Version 3.0
==============================================================
Uses shared bollinger_strategy module for unified strategy logic.

IMPROVEMENTS OVER V2:
  ΓÇó Multi-core parallelization (8-16x speedup)
  ΓÇó Multi-objective optimization (NSGA-II) - explores Pareto frontier
  ΓÇó Sortino Ratio instead of Sharpe Ratio (better for trading)

FINAL PRODUCTION SCRIPT
  ΓÇó Prints the exact CSV used
  ΓÇó All diagnostics ΓåÆ ga_diagnostics/
  ΓÇó Multi-objective: Maximize Sortino, Minimize Drawdown, Maximize Profit Factor
  ΓÇó Enforces TARGET_TRADES_DAY=4, MIN_TRADES_DAY=2
  ΓÇó Optimizable Trailing Delay (bars) to control quick wins via TP
  ΓÇó CHECKPOINT/RESUME: Saves state after each generation
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
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
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
os.makedirs(DIAG_DIR, exist_ok=True)
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
    print(f"Checkpoint saved: Generation {gen} ΓåÆ {CHECKPOINT_FILE}")

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
    
    # Print the exact parameter file that will be used
    print("\n=== PARAMETER FILE USED (exact copy) ===")
    print(param_df.to_string(index=False))
    print("========================================\n")
    
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
    split = int(len(df) * DATA_SPLITS)
    in_sample, oos = df.iloc[:split], df.iloc[split:]
    
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
                    logging.warning(f"Individual has {len(ind.fitness.values)} fitness values, expected 3. Assigning poor fitness.")
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
            
            # Save checkpoint after each generation
            save_checkpoint(pop, hof, logbook, gen, current_config)
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
    best_params = dict(zip(param_keys, best))
    best_fitness = best.fitness.values
    
    print("\n=== BEST SOLUTION FROM PARETO FRONT ===")
    print(f"Selected based on highest Sortino Ratio")
    print(f"Fitness: Sortino={best_fitness[0]:.4f}, MaxDD={best_fitness[1]:.2f}, PF={best_fitness[2]:.4f}")
    print(f"Parameters:")
    for k, v in best_params.items():
        print(f"  {k}: {round(v, 4) if isinstance(v, float) else v}")
    
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
    # DIAGNOSTIC PLOTS ΓåÆ ga_diagnostics/
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
    print(f"Plot ΓåÆ {DIAG_DIR}/convergence_multi_objective.png")
    
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
        print(f"Plot ΓåÆ {DIAG_DIR}/pareto_front.png")
    
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
    print(f"Plot ΓåÆ {DIAG_DIR}/pareto_size.png")
    
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
    print(f"Parameter plots ΓåÆ {DIAG_DIR}/param_evolution/")
    
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
        print(f"Plot ΓåÆ {DIAG_DIR}/oos_pnl_hist.png")
        
        plt.figure(figsize=(8, 4))
        plt.scatter(trades_oos.index, trades_oos['pnl'], c=np.where(trades_oos['pnl'] > 0, 'g', 'r'))
        plt.title('OOS Wins (Green) / Losses (Red)')
        plt.ylabel('PNL')
        plt.grid()
        plt.tight_layout()
        plt.savefig(f'{DIAG_DIR}/oos_win_loss.png')
        plt.close()
        print(f"Plot ΓåÆ {DIAG_DIR}/oos_win_loss.png")
        
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
        print(f"Plot ΓåÆ {DIAG_DIR}/oos_trade_duration.png")
        
        equity = 50000 + trades_oos.groupby(trades_oos['exit_time'].dt.date)['pnl'].sum().cumsum()
        plt.figure(figsize=(10, 4))
        equity.plot()
        plt.title('OOS Equity Curve')
        plt.ylabel('Equity')
        plt.grid()
        plt.tight_layout()
        plt.savefig(f'{DIAG_DIR}/oos_equity.png')
        plt.close()
        print(f"OOS equity ΓåÆ {DIAG_DIR}/oos_equity.png")
        if len(set(equity)) == 1:
            print("OOS equity is suspicious (straight line) - no trades or zero variation")
    
    # ------------------------------------------------------------------
    # Write optimized CSV
    # ------------------------------------------------------------------
    for name, val in best_params.items():
        idx = param_df[param_df['Name'] == name].index[0]
        typ = param_dict[name]['type']
        param_df.at[idx, 'Value'] = int(val) if typ == 'int' else round(val, 4)
    param_df.to_csv(OUTPUT_CSV, index=False)
    print(f"Optimized CSV ΓåÆ {OUTPUT_CSV}")
    
    # Clean up checkpoint file on successful completion
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        print(f"Checkpoint file removed: {CHECKPOINT_FILE}")


if __name__ == "__main__":
    # Required for Windows multiprocessing
    multiprocessing.freeze_support()
    main()


#!/usr/bin/env python3
"""
Genetic Optimization for Bollinger Band Strategy - Version 2.0
==============================================================
Uses shared bollinger_strategy module for unified strategy logic.
Converted from Jupyter notebook to standalone Python script.

FINAL PRODUCTION SCRIPT
  • Prints the exact CSV used
  • All diagnostics → ga_diagnostics/
  • Scalar fitness + IRONCLAD min-trades
  • Enforces TARGET_TRADES_DAY=4, MIN_TRADES_DAY=2
  • Optimizable Trailing Delay (bars) to control quick wins via TP
  • CHECKPOINT/RESUME: Saves state after each generation
    - Automatically resumes from interruption
    - Checkpoint file: ga_diagnostics/ga_checkpoint.pkl
    - Delete checkpoint file to start fresh
"""

import os
import warnings
import random
import pickle
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from deap import base, creator, tools, algorithms
from bollinger_strategy import BollingerBandStrategy, load_params

warnings.filterwarnings("ignore")

# ----------------------------------------------------------------------
# CSV INPUT / OUTPUT
# ----------------------------------------------------------------------
PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'
OUTPUT_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_optimized.csv'
TRADES_OOS_CSV = 'Bollinger/output/trades_oos.csv'
TRADES_IS_CSV = 'Bollinger/output/trades_is.csv'
DIAG_DIR = 'ga_diagnostics'
CHECKPOINT_FILE = os.path.join(DIAG_DIR, 'ga_checkpoint.pkl')
os.makedirs(DIAG_DIR, exist_ok=True)
os.makedirs(os.path.dirname(TRADES_IS_CSV), exist_ok=True)
os.makedirs(os.path.dirname(TRADES_OOS_CSV), exist_ok=True)

# ----------------------------------------------------------------------
# Load Parameters
# ----------------------------------------------------------------------
param_dict, param_df = load_params(PARAM_CSV, return_dataframe=True)

# Print the exact parameter file that will be used
print("\n=== PARAMETER FILE USED (exact copy) ===")
print(param_df.to_string(index=False))
print("========================================\n")

# ----------------------------------------------------------------------
# GA configuration
# ----------------------------------------------------------------------
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

# ----------------------------------------------------------------------
# Numeric ranges for the GA
# ----------------------------------------------------------------------
PARAM_RANGES = {n: (d['min'], d['max']) for n, d in param_dict.items()
                if d['type'] in ('int', 'float') and d['min'] is not None and d['max'] is not None}

# ----------------------------------------------------------------------
# Back-tester using shared strategy module
# ----------------------------------------------------------------------
def run_backtest(params, df, suppress_output=True):
    """
    Run backtest using shared strategy module.
    
    Args:
        params: Dictionary of optimizable parameters
        df: DataFrame with OHLCV data
        suppress_output: If False, print progress
        
    Returns:
        dict with metrics: sharpe, max_drawdown, avg_trades_day, profit_factor, trades_df
    """
    if len(df) == 0:
        return {'sharpe': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0,
                'trades_df': pd.DataFrame()}
    
    # Create strategy instance
    strategy = BollingerBandStrategy(param_dict)
    
    # Update optimizable parameters
    strategy.update_optimizable_params(params)
    
    # Calculate indicators
    df = strategy.calculate_indicators(df)
    if len(df) == 0:
        return {'sharpe': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0,
                'trades_df': pd.DataFrame()}
    
    # Apply filters
    df = strategy.apply_filters(df)
    if len(df) == 0:
        return {'sharpe': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0,
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
        return {'sharpe': 0, 'max_drawdown': 0, 'avg_trades_day': 0, 'profit_factor': 0,
                'trades_df': trades_df}
    
    # Daily equity (fill zero-PNL days)
    min_d = trades_df['exit_time'].min().date()
    max_d = trades_df['exit_time'].max().date()
    daily_pnl = trades_df.groupby(trades_df['exit_time'].dt.date)['pnl'].sum()\
                         .reindex(pd.date_range(min_d, max_d), fill_value=0)
    equity = 50000 + daily_pnl.cumsum()
    rets = equity.pct_change().dropna()
    sharpe = 0.0 if len(rets) < 2 else (rets.mean() / rets.std() * np.sqrt(252)) if rets.std() != 0 else 0.0
    
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
        'sharpe': sharpe,
        'max_drawdown': dd,
        'avg_trades_day': avg_trades_day,
        'profit_factor': profit_factor,
        'trades_df': trades_df
    }

# ----------------------------------------------------------------------
# GA plumbing
# ----------------------------------------------------------------------
creator.create("FitnessMax", base.Fitness, weights=(1.0,))
creator.create("Individual", list, fitness=creator.FitnessMax)

param_keys = list(PARAM_RANGES.keys())

def create_individual():
    return creator.Individual(random.uniform(lo, hi) for lo, hi in PARAM_RANGES.values())

def custom_mutate(ind):
    tools.mutGaussian(ind, mu=MUT_MU, sigma=MUT_SIGMA, indpb=0.2)
    for i, (lo, hi) in enumerate(PARAM_RANGES.values()):
        ind[i] = max(lo, min(ind[i], hi))
    return ind,

def evaluate_scalar(ind_and_df):
    ind, df = ind_and_df
    params = dict(zip(param_keys, ind))
    
    # Clamp & cast
    for n, v in params.items():
        mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
        v = max(mn, min(v, mx))
        params[n] = int(v) if typ == 'int' else float(v)
    
    # Clamp timeframe to >=1
    params['Timeframe (minutes)'] = max(1, int(params.get('Timeframe (minutes)',
                                                         param_dict['Timeframe (minutes)']['value'])))
    
    metrics = run_backtest(params, df, suppress_output=True)
    
    excess_pen = max(0.0, metrics['avg_trades_day'] - TARGET_TRADES_DAY)
    low_pen = max(0.0, MIN_TRADES_DAY - metrics['avg_trades_day'])
    
    fitness = (
        metrics['sharpe'] * 2.0
        - metrics['max_drawdown'] * 0.2
        - excess_pen * 0.2
        + metrics['profit_factor'] * 1.0
        - low_pen * 100.0  # ZERO TRADES = -100 → DEAD
    )
    return (fitness,)

toolbox = base.Toolbox()
toolbox.register("individual", create_individual)
toolbox.register("population", tools.initRepeat, list, toolbox.individual)
toolbox.register("evaluate", evaluate_scalar)
toolbox.register("mate", tools.cxBlend, alpha=0.5)
toolbox.register("mutate", custom_mutate)
toolbox.register("select", tools.selTournament, tournsize=3)

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
    print("# Genetic Optimization for Bollinger Band Strategy - Version 2.0")
    print("# Using shared bollinger_strategy module")
    print("# Checkpoint/Resume enabled - saves after each generation")
    toolbox.register("map", map)
    
    # Save current configuration
    current_config = {
        'POP_SIZE': POP_SIZE,
        'NUM_GEN': NUM_GEN,
        'CX_PB': CX_PB,
        'MUT_PB': MUT_PB,
        'DATA_SPLITS': DATA_SPLITS,
        'DATA_SIZE': DATA_SIZE,
        'PARAM_CSV': PARAM_CSV
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
        
        # Verify configuration compatibility
        if not verify_config_compatibility(saved_config, current_config):
            print("\nWARNING: Config mismatch detected!")
            print("Continuing with saved checkpoint despite config mismatch...")
            print("(Delete checkpoint file to start fresh if needed)")
    else:
        # Start fresh
        pop = toolbox.population(n=POP_SIZE)
        hof = tools.HallOfFame(1)
        logbook = tools.Logbook()
        logbook.header = "gen", "evals", "avg", "min", "max"
        start_gen = 0
        print("\nStarting fresh run...")
    
    stats = tools.Statistics(lambda i: i.fitness.values[0])
    stats.register("avg", np.mean)
    stats.register("min", np.min)
    stats.register("max", np.max)
    
    if start_gen == 0:
        print(logbook.header)
    
    print(f"\nConfiguration:")
    print(f"  NUM_GEN: {NUM_GEN}")
    print(f"  POP_SIZE: {POP_SIZE}")
    print(f"  Starting from generation: {start_gen}")
    print(f"  Will run generations: {list(range(start_gen, NUM_GEN))}")
    print()
    
    # Main evolution loop
    try:
        for gen in range(start_gen, NUM_GEN):
            print(f"Generation {gen} starting...")
            offspring = algorithms.varAnd(pop, toolbox, CX_PB, MUT_PB)
            
            # Evaluate with error handling
            print(f"  Evaluating {len(offspring)} individuals...")
            fits = []
            for i, (ind, df) in enumerate([(ind, in_sample) for ind in offspring]):
                try:
                    fit = toolbox.evaluate((ind, df))
                    fits.append(fit)
                except Exception as e:
                    print(f"  ERROR evaluating individual {i}: {e}")
                    # Assign a very poor fitness to failed evaluations
                    fits.append((-1000.0,))
            
            # Assign fitness values
            for fit, ind in zip(fits, offspring):
                ind.fitness.values = fit
            
            pop = toolbox.select(offspring, len(pop))
            hof.update(pop)
            record = stats.compile(pop)
            logbook.record(gen=gen, evals=len(pop), **record)
            print(f"{gen}\t{len(pop)}\t{round(record['avg'], 4)}\t{round(record['min'], 4)}\t{round(record['max'], 4)}")
            
            # Save checkpoint after each generation
            save_checkpoint(pop, hof, logbook, gen, current_config)
            print(f"Generation {gen} completed.\n")
            
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Checkpoint saved.")
        if 'gen' in locals():
            print(f"Completed {gen + 1} out of {NUM_GEN} generations.")
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
        print("\nERROR: No individuals in Hall of Fame. Cannot proceed.")
        print("This may indicate all evaluations failed.")
        return
    
    best = hof[0]
    best_params = dict(zip(param_keys, best))
    print("\n=== BEST INDIVIDUAL ===")
    print({k: round(v, 4) if isinstance(v, float) else v for k, v in best_params.items()})
    
    # ------------------------------------------------------------------
    # In-sample & OOS validation
    # ------------------------------------------------------------------
    is_res = run_backtest(best_params, in_sample, suppress_output=False)
    trades_is = is_res.pop('trades_df')
    trades_is.to_csv(TRADES_IS_CSV, index=False)
    
    oos_res = run_backtest(best_params, oos, suppress_output=False)
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
    plt.figure(figsize=(8, 4))
    plt.plot(logbook.select("gen"), logbook.select("avg"), label='Avg')
    plt.plot(logbook.select("gen"), logbook.select("max"), label='Best')
    plt.title('GA Convergence – Scalar Fitness')
    plt.xlabel('Generation')
    plt.ylabel('Fitness')
    plt.legend()
    plt.grid()
    plt.tight_layout()
    plt.savefig(f'{DIAG_DIR}/convergence_fitness.png')
    plt.close()
    print(f"Plot → {DIAG_DIR}/convergence_fitness.png")
    
    # Parameter evolution
    os.makedirs(f'{DIAG_DIR}/param_evolution', exist_ok=True)
    for i, pname in enumerate(param_keys):
        vals = [ind[i] for ind in hof]
        plt.figure(figsize=(6, 3))
        plt.plot(range(len(vals)), vals, marker='.')
        plt.title(f'Best {pname}')
        plt.xlabel('Generation')
        plt.ylabel(pname)
        plt.grid()
        plt.tight_layout()
        plt.savefig(f'{DIAG_DIR}/param_evolution/{pname.replace(" ", "_")}.png')
        plt.close()
    print(f"Parameter-evolution plots → {DIAG_DIR}/param_evolution/")
    
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
    # Write optimized CSV
    # ------------------------------------------------------------------
    for name, val in best_params.items():
        idx = param_df[param_df['Name'] == name].index[0]
        typ = param_dict[name]['type']
        param_df.at[idx, 'Value'] = int(val) if typ == 'int' else round(val, 4)
    param_df.to_csv(OUTPUT_CSV, index=False)
    print(f"Optimized CSV → {OUTPUT_CSV}")
    
    # Clean up checkpoint file on successful completion
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        print(f"Checkpoint file removed: {CHECKPOINT_FILE}")


if __name__ == "__main__":
    main()


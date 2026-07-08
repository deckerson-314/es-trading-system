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
import tempfile
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

  --seed N                Optional int. Fixes Python and NumPy RNG for reproducible GA runs (A/B).

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
from plotly.io._utils import plotly_cdn_url
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

# Extra logbook columns for population min/max/std (convergence bands). Old checkpoints: header extended on load.
GA_LOGBOOK_POP_STAT_KEYS = (
    'pop_min_sortino', 'pop_std_sortino', 'pop_max_dd_norm', 'pop_std_dd',
    'pop_min_pf', 'pop_std_pf', 'pop_min_trades_day', 'pop_std_trades_day',
    'pop_avg_trades_day', 'pop_max_total_profit', 'pop_min_total_profit', 'pop_std_total_profit',
    'pop_max_profit_per_trade', 'pop_min_profit_per_trade', 'pop_std_profit_per_trade',
    'pop_avg_profit_per_trade',
)
GA_LOGBOOK_BASE_KEYS = (
    'gen', 'evals', 'avg_sortino', 'avg_dd', 'avg_pf', 'pareto_size',
    'avg_trades_day', 'max_trades_day', 'avg_total_profit', 'avg_profit_per_trade',
    'actual_dd_best', 'actual_sortino_best', 'actual_pf_best', 'actual_pnl_best',
)
# Per-generation max of pre-cap ratio (metric / NORM_* divisor); can exceed 1.0; viz-only for logbook/dashboard.
GA_LOGBOOK_UC_KEYS = (
    'max_uc_sortino', 'max_uc_dd', 'max_uc_pf', 'max_uc_trades', 'max_uc_pnl', 'max_uc_ppt',
)
GA_LOGBOOK_HEADER_FULL = GA_LOGBOOK_BASE_KEYS + GA_LOGBOOK_UC_KEYS + GA_LOGBOOK_POP_STAT_KEYS


def extend_logbook_header_for_pop_stats(logbook):
    """Append population band columns; old log chapters return None for those keys in select()."""
    if logbook is None or not logbook.header:
        return
    h = tuple(logbook.header)
    extra = tuple(k for k in GA_LOGBOOK_UC_KEYS + GA_LOGBOOK_POP_STAT_KEYS if k not in h)
    if extra:
        logbook.header = h + extra


def _inject_max_uc_from_offspring(record, offspring):
    """Max pre-cap ratio per objective among individuals evaluated this generation (does not affect selection)."""
    names = (
        'max_uc_sortino', 'max_uc_dd', 'max_uc_pf', 'max_uc_trades', 'max_uc_pnl', 'max_uc_ppt',
    )
    for idx, key in enumerate(names):
        vals = []
        for ind in offspring or []:
            uc = getattr(ind, 'uncapped_ratios', None)
            if uc is None or len(uc) <= idx:
                continue
            try:
                v = float(uc[idx])
            except (TypeError, ValueError):
                continue
            if np.isfinite(v):
                vals.append(v)
        record[key] = float(np.max(vals)) if vals else None


def _parallel_eval_result_to_fit_unc(item):
    """Unpack (fit6, unc6) from parallel map; tolerate legacy 6-tuples."""
    if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], tuple) and len(item[0]) == 6:
        return item[0], item[1]
    if isinstance(item, (list, tuple)) and len(item) == 6:
        return tuple(float(x) for x in item), (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return (-1000.0, 100000.0, 0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


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
parser.add_argument(
    '--data-csv',
    type=str,
    default=None,
    help='Path to ES 1m OHLCV CSV (default: Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv)',
)
parser.add_argument(
    '--run-tag',
    type=str,
    default=None,
    help='Unique tag for this process: isolates checkpoint + genetic_results suffix so parallel GAs do not clobber each other',
)
parser.add_argument(
    '--seed',
    type=int,
    default=None,
    help='Random seed for deterministic GA runs (A/B reproducibility)',
)
args, _unknown_cli = parser.parse_known_args()


def _slug_run_tag(tag):
    """ASCII slug for filenames; None if tag missing."""
    import re
    if not tag or not str(tag).strip():
        return None
    s = re.sub(r'[^a-zA-Z0-9_.-]+', '_', str(tag).strip()).strip('._-')
    s = s[:96] if s else ''
    return s or 'run'

import glob

# Defines strategy-specific defaults
strategy_name_cap = args.strategy.capitalize()

if args.params == DEFAULT_PARAM_CSV:
    if args.strategy == 'trend':
        PARAM_CSV = os.path.join('strategies', 'trend', 'parameters', 'trend_strategy_params.csv')
    elif args.strategy == 'session':
        PARAM_CSV = os.path.join('strategies', 'session', 'parameters', 'session_strategy_params.csv')
    elif args.strategy == 'orb':
        PARAM_CSV = os.path.join('strategies', 'orb', 'parameters', 'orb_strategy_params.csv')
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

_run_slug = _slug_run_tag(getattr(args, 'run_tag', None))
if _run_slug is not None:
    suffix = f"{today_str}-{_run_slug}"
else:
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
    if _run_slug is not None:
        CHECKPOINT_FILE = os.path.join(CHECKPOINT_DIR, f'ga_checkpoint_v4_{_run_slug}.pkl')
    else:
        CHECKPOINT_FILE = os.path.join(CHECKPOINT_DIR, 'ga_checkpoint_v4.pkl')
START_TIME_FILE = os.path.join(DIAG_DIR, 'ga_start_time.txt')
HTML_DIR = os.path.join(DIAG_DIR, 'html')
HTML_DASHBOARD = os.path.join(HTML_DIR, 'ga_dashboard_v4.html')
WEB_DIR = os.path.join(os.getcwd(), 'web')  # Common web directory
if _run_slug is not None:
    WEB_DASHBOARD = os.path.join(WEB_DIR, f'ga_dashboard_v4_{_run_slug}.html')
else:
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

# New GA Weights and Limits
GA_START_DATE = None
GA_END_DATE = None
WEIGHT_SORTINO = None
WEIGHT_DRAWDOWN = None
WEIGHT_PF = None
WEIGHT_TRADES = None
WEIGHT_PNL = None
WEIGHT_PPT = None
MIN_TRADE_DURATION = None
MAX_WIN_RATE_CAP = None
LIMIT_MAX_LOSS = None
LIMIT_MIN_SORTINO = None

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
def _trade_duration_minutes_bar_aligned(trades_df, bar_minutes):
    """
    Per-trade holding span in minutes on the **bar grid** (inclusive), minimum one bar.

    The simulator stamps ``entry_time`` at bar open and often ``exit_time`` a few seconds
    into the same bar (end-of-bar convention). A raw datetime delta then looks like
    sub-minute / sub-bar holds even when the trade was exposed for a full candle — which
    misleads GA vs paper/live comparisons. We floor both timestamps to ``bar_minutes`` buckets,
    count inclusive bars, and multiply by ``bar_minutes``.
    """
    if trades_df is None or trades_df.empty:
        return pd.Series(dtype=float)
    if 'entry_time' not in trades_df.columns or 'exit_time' not in trades_df.columns:
        return pd.Series(dtype=float)
    M = max(float(bar_minutes), 1.0)
    try:
        st = pd.to_datetime(trades_df['entry_time'])
        et = pd.to_datetime(trades_df['exit_time'])
        rule = f'{int(M)}min'
        entry_bar = st.dt.floor(rule)
        exit_bar = et.dt.floor(rule)
        delta_min = (exit_bar - entry_bar).dt.total_seconds() / 60.0
        delta_min = delta_min.fillna(0.0)
        n_bars = (delta_min / M) + 1.0
        n_bars = n_bars.clip(lower=1.0)
        dur = n_bars * M
        return dur.astype(float)
    except Exception:
        return pd.Series(dtype=float)


def _mean_trade_duration_minutes(trades_df, bar_minutes=None):
    """Mean holding time in minutes; uses bar-aligned minutes when ``bar_minutes`` is set."""
    if trades_df is None or trades_df.empty:
        return 0.0
    if 'entry_time' not in trades_df.columns or 'exit_time' not in trades_df.columns:
        return 0.0
    try:
        if bar_minutes is not None and float(bar_minutes) > 0:
            s = _trade_duration_minutes_bar_aligned(trades_df, float(bar_minutes))
            if s is None or len(s) == 0:
                return 0.0
            v = float(s.mean())
        else:
            dur = (
                pd.to_datetime(trades_df['exit_time']) - pd.to_datetime(trades_df['entry_time'])
            ).dt.total_seconds() / 60.0
            v = float(dur.mean())
        if np.isnan(v) or np.isinf(v):
            return 0.0
        return max(0.0, v)
    except Exception:
        return 0.0


def _truthy_ga_flag(val) -> bool:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return int(val) != 0
    return str(val).strip().lower() in ("1", "true", "yes", "on")


from core.sim_fidelity import (
    apply_conservative_entry_slippage,
    ga_live_style_entry_enabled,
    simulate_bar_exit,
)


def _ga_live_style_entry_enabled(param_dict_local=None) -> bool:
    """GA fidelity: enter at signal-bar close (matches live market-at-close)."""
    from core.sim_fidelity import ga_live_style_entry_enabled
    return ga_live_style_entry_enabled(param_dict_local)


def _ga_conservative_stop_slippage_pts(param_dict_local=None) -> float:
    """GA fidelity: worsen stop fills by N points (0 = disabled)."""
    if param_dict_local and "GA_CONSERVATIVE_STOP_SLIPPAGE" in param_dict_local:
        v = param_dict_local["GA_CONSERVATIVE_STOP_SLIPPAGE"].get("value")
        if v is not None and not (isinstance(v, float) and pd.isna(v)) and str(v).strip() != "":
            try:
                return max(0.0, float(v))
            except (TypeError, ValueError):
                pass
    raw = os.environ.get("GA_CONSERVATIVE_STOP_SLIPPAGE", "").strip()
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 0.0


def _ga_apply_conservative_stop_fill(
    price: float, direction: int, reason: str, param_dict_local=None,
) -> float:
    """Worsen stop-loss exit price to reduce optimistic GA stop assumptions."""
    slip = _ga_conservative_stop_slippage_pts(param_dict_local)
    if slip <= 0 or not reason or "stop" not in str(reason).lower():
        return price
    # Long stop: exit lower; short stop: exit higher
    return price - slip * int(direction)


def run_backtest(params, df_in, param_dict_local, suppress_output=True, debug=False, mask=None):
    default_result = {
        'sortino': 0,
        'max_drawdown': 0,
        'avg_trades_day': 0,
        'profit_factor': 0,
        'total_profit': 0,
        'avg_profit_per_trade': 0.0,
        'avg_trade_duration_min': 0.0,
        'trades_df': pd.DataFrame(),
        'monthly_profit_stats': {'max_monthly_profit': 0, 'min_monthly_profit': 0, 'avg_monthly_profit': 0},
    }
    
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
    
    # Resample logic for multiple timeframes (live-parity rules; skip HTF-native input)
    from core.monitoring import prepare_strategy_ohlcv, resample_mask_to_htf

    tf = getattr(strategy, 'timeframe', 1)
    if tf > 1:
        df_in, htf_native = prepare_strategy_ohlcv(df_in, tf)
        if mask is not None and not htf_native:
            mask = resample_mask_to_htf(mask, tf, df_in.index)
        elif mask is not None:
            mask = mask.reindex(df_in.index).fillna(False).astype(bool)

    try:
        # Calculate indicators & signals (Vectorized)
        df = strategy.calculate_indicators(df_in)
        
        # If mask is provided, slice the dataframe AFTER indicators are calculated
        if mask is not None:
            df = df[mask]
            
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
    live_style_entry = _ga_live_style_entry_enabled(param_dict_local)
    
    # Pre-calculate signals (already in columns)
    # Using itertuples is efficient enough for Python loop
    
    # Get Transaction Cost
    transaction_cost = param_dict_local.get('Transaction Cost (Per Trade)', {'value': 15.0})['value']
    
    # Track time for jump detection (only if mask provided)
    last_time = None
    tf_delta = pd.Timedelta(minutes=strategy.timeframe * 5) # 5x timeframe buffer for gaps
    calendar_gap = pd.Timedelta(hours=4)

    for row in df.itertuples():
        # Initialize last_time on the first iteration
        if last_time is None:
            last_time = row.Index

        gap = row.Index - last_time
        gap_close = gap > max(tf_delta, calendar_gap)
        # Jump Detection: Close positions on interleaved-mask gaps or calendar/session gaps.
        if positions and gap_close:
            gap_reason = (
                "Gap: Period Transition"
                if mask is not None and gap > tf_delta
                else "Gap: Session Break"
            )
            for pos in positions[:]:
                pnl = (row.open - pos['entry_price']) * pos['direction'] * 50 - transaction_cost
                trades.append(pos | {
                    'exit_time': row.Index,
                    'exit_price': row.open,
                    'pnl': pnl,
                    'reason': gap_reason
                })
                positions.remove(pos)
            pending_entry = None

        last_time = row.Index
        # 1. Process Pending (Execute at Next Open)
        if pending_entry:
            dir_ = pending_entry['direction']
            entry_px = apply_conservative_entry_slippage(row.open, dir_, param_dict_local)
            pos = strategy.setup_position(entry_px, dir_, row, df)
            if 'stop' not in pos: pos['stop'] = 0.0 # Safety init
            positions.append(pos)
            pending_entry = None

        # 2. Check exits first
        for pos in positions[:]:
            should_exit, reason, price = simulate_bar_exit(strategy, pos, row, df, param_dict_local)
            if not should_exit:
                continue

            # Ensure transaction_cost is float
            try:
                t_cost = float(transaction_cost)
            except (ValueError, TypeError):
                t_cost = 0.0

            pnl = (price - pos['entry_price']) * pos['direction'] * 50 - t_cost
            # Use End of Bar for Exit Time to match BB_Strategy_v4.py logic
            exit_time = row.Index + pd.Timedelta(seconds=59)
            trades.append(pos | {
                'exit_time': exit_time,
                'exit_price': price,
                'pnl': pnl,
                'reason': reason
            })
            positions.remove(pos)
        
        # 3. Check entries (Vectorized lookup)
        if len(positions) < strategy.max_open_trades and pending_entry is None:
            if row.entry_long_signal:
                if live_style_entry:
                    entry_px = apply_conservative_entry_slippage(row.close, 1, param_dict_local)
                    pos = strategy.setup_position(entry_px, 1, row, df)
                    if 'stop' not in pos:
                        pos['stop'] = 0.0
                    positions.append(pos)
                    should_exit, reason, price = simulate_bar_exit(
                        strategy, pos, row, df, param_dict_local,
                    )
                    if should_exit:
                        try:
                            t_cost = float(transaction_cost)
                        except (ValueError, TypeError):
                            t_cost = 0.0
                        pnl = (price - pos['entry_price']) * pos['direction'] * 50 - t_cost
                        exit_time = row.Index + pd.Timedelta(seconds=59)
                        trades.append(pos | {
                            'exit_time': exit_time,
                            'exit_price': price,
                            'pnl': pnl,
                            'reason': reason,
                        })
                        positions.remove(pos)
                else:
                    pending_entry = {'direction': 1, 'entry_price': row.close, 'stop': 0.0}
            elif row.entry_short_signal:
                if live_style_entry:
                    entry_px = apply_conservative_entry_slippage(row.close, -1, param_dict_local)
                    pos = strategy.setup_position(entry_px, -1, row, df)
                    if 'stop' not in pos:
                        pos['stop'] = 0.0
                    positions.append(pos)
                    should_exit, reason, price = simulate_bar_exit(
                        strategy, pos, row, df, param_dict_local,
                    )
                    if should_exit:
                        try:
                            t_cost = float(transaction_cost)
                        except (ValueError, TypeError):
                            t_cost = 0.0
                        pnl = (price - pos['entry_price']) * pos['direction'] * 50 - t_cost
                        exit_time = row.Index + pd.Timedelta(seconds=59)
                        trades.append(pos | {
                            'exit_time': exit_time,
                            'exit_price': price,
                            'pnl': pnl,
                            'reason': reason,
                        })
                        positions.remove(pos)
                else:
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
    
    if mask is not None and not suppress_output:
        print(f"DEBUG_MASK: Trades={len(trades_df)}, TotalPNL={total_profit:.2f}")
    trades_df['cum_pnl'] = trades_df['pnl'].cumsum()
    trades_df['peak'] = trades_df['cum_pnl'].cummax()
    trades_df['drawdown'] = trades_df['peak'] - trades_df['cum_pnl']
    max_drawdown = trades_df['drawdown'].max()
    if pd.isna(max_drawdown): max_drawdown = 0
    
    # Sortino
    risk_free_rate = 0
    downside_returns = trades_df[trades_df['pnl'] < 0]['pnl']
    
    # Robust calculation: If we have 0 or 1 losses, std() is NA/0.
    # We use a floor to prevent Sortino from collapsing to 0 for highly profitable strategies.
    if len(downside_returns) > 1:
        downside_std = downside_returns.std()
    elif len(downside_returns) == 1:
        # Use absolute value of the single loss as a proxy for std
        downside_std = abs(downside_returns.iloc[0])
    else:
        # No losses! Use a tiny floor to represent "perfect" performance
        downside_std = 0.001
        
    avg_return = trades_df['pnl'].mean()
    if avg_return > 0:
        # Penalize if downside_std is still effectively 0
        sortino = (avg_return - risk_free_rate) / max(0.001, downside_std) * (252**0.5)
    else:
        # For negative returns, standard Sortino logic (negative/downside)
        sortino = (avg_return - risk_free_rate) / max(0.1, downside_std) * (252**0.5)
    
    # Cap insane values from the floor
    sortino = max(-500.0, min(sortino, 500.0))
        
    # Profit Factor
    gross_profit = trades_df[trades_df['pnl'] > 0]['pnl'].sum()
    gross_loss = abs(trades_df[trades_df['pnl'] < 0]['pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999.0
    
    # Trade Frequency
    if not df_in.empty:
         # Approximate total days from data
         # This assumes index is datetime
         try:
             # Use the potentially masked df to count actual traded days
             total_days = len(set(df.index.date)) or 1
         except:
             total_days = 1
    else:
         total_days = 1

    avg_trades_day = len(trades) / total_days
    tf_m = float(max(1, int(getattr(strategy, 'timeframe', 1) or 1)))
    avg_trade_duration_min = _mean_trade_duration_minutes(trades_df, bar_minutes=tf_m)
    
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
        'avg_profit_per_trade': total_profit / len(trades) if len(trades) > 0 else 0.0,
        'avg_trade_duration_min': avg_trade_duration_min,
        'trades_df': trades_df,
        'monthly_profit_stats': monthly_stats
    }

# ----------------------------------------------------------------------
# Multi-objective GA setup
# ----------------------------------------------------------------------

# --- DYNAMIC WEIGHT LOADING ---
import pandas as pd
_csv_weights = (1.0, -1.0, 1.0, 3.0, 2.0, 2.0)
try:
    _temp_df = pd.read_csv(PARAM_CSV, comment='#', skip_blank_lines=True)
    if 'Name' in _temp_df.columns and 'Value' in _temp_df.columns:
        _w_sortino = float(_temp_df[_temp_df['Name'] == 'WEIGHT_SORTINO']['Value'].iloc[0]) if not _temp_df[_temp_df['Name'] == 'WEIGHT_SORTINO'].empty else 1.0
        _w_dd = float(_temp_df[_temp_df['Name'] == 'WEIGHT_DRAWDOWN']['Value'].iloc[0]) if not _temp_df[_temp_df['Name'] == 'WEIGHT_DRAWDOWN'].empty else -1.0
        _w_pf = float(_temp_df[_temp_df['Name'] == 'WEIGHT_PF']['Value'].iloc[0]) if not _temp_df[_temp_df['Name'] == 'WEIGHT_PF'].empty else 1.0
        _w_trades = float(_temp_df[_temp_df['Name'] == 'WEIGHT_TRADES']['Value'].iloc[0]) if not _temp_df[_temp_df['Name'] == 'WEIGHT_TRADES'].empty else 3.0
        _w_pnl = float(_temp_df[_temp_df['Name'] == 'WEIGHT_PNL']['Value'].iloc[0]) if not _temp_df[_temp_df['Name'] == 'WEIGHT_PNL'].empty else 2.0
        _w_ppt = float(_temp_df[_temp_df['Name'] == 'WEIGHT_PPT']['Value'].iloc[0]) if not _temp_df[_temp_df['Name'] == 'WEIGHT_PPT'].empty else 2.0
        _csv_weights = (_w_sortino, _w_dd, _w_pf, _w_trades, _w_pnl, _w_ppt)
except Exception as e:
    pass

# Clear any existing creator classes to avoid conflicts
if hasattr(creator, "FitnessMulti"):
    del creator.FitnessMulti
if hasattr(creator, "Individual"):
    del creator.Individual

# Multi-objective fitness: (maximize Sortino, minimize Drawdown, maximize Profit Factor, maximize Avg Trades/Day, maximize Total Profit, maximize Avg Profit/Trade)
creator.create("FitnessMulti", base.Fitness, weights=_csv_weights)
creator.create("Individual", list, fitness=creator.FitnessMulti)

def create_fitness_with_correct_weights():
    # Check if FitnessMulti class has correct weights
    if hasattr(creator, 'FitnessMulti') and len(creator.FitnessMulti.weights) == 6:
        return creator.FitnessMulti()
    else:
        # Recreate the class if it has wrong weights
        if hasattr(creator, "FitnessMulti"):
            del creator.FitnessMulti
        creator.create("FitnessMulti", base.Fitness, weights=_csv_weights)
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


def _maybe_diversify_initial_population(pop, param_dict_local):
    """Optional stratified seeds (Trend exploration); controlled via param CSV."""
    try:
        raw = param_dict_local.get("GA_DIVERSE_SEED", {}).get("value", 0)
        enabled = str(raw).strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        enabled = False
    if not enabled:
        return 0
    try:
        frac = float(param_dict_local.get("GA_DIVERSE_SEED_FRACTION", {}).get("value", 0.6))
    except (TypeError, ValueError):
        frac = 0.6
    try:
        from strategies.trend.ga_exploration_seed import diversify_initial_population
    except ImportError:
        print("WARNING: GA_DIVERSE_SEED enabled but strategies.trend.ga_exploration_seed not found.")
        return 0
    n = diversify_initial_population(pop, param_keys, param_dict_local, clamp_individual, fraction=frac)
    if n:
        print(f"  Diverse seed: applied {n} stratified archetypes ({frac:.0%} of pop)")
    return n

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

def core_evaluate(ind, df_local, param_dict_local, param_keys_local, mask_local=None):
    """
    Core evaluation logic shared by single-process and multi-process evaluators.
    """
    params = dict(zip(param_keys_local, ind))
    
    # Clamp & cast - ensure integer parameters are properly rounded
    for n, v in params.items():
        if n not in param_dict_local:
            continue
        mn, mx, typ = param_dict_local[n]['min'], param_dict_local[n]['max'], param_dict_local[n]['type']
        v = max(mn, min(v, mx))
        if typ == 'int':
            params[n] = int(round(v))
        else:
            params[n] = float(v)
    
    # Convert boolean parameters
    for n in list(params.keys()):
        if n in param_dict_local:
            original_type = param_dict_local[n].get('type', '')
            if original_type == 'bool' and isinstance(params[n], (int, float)):
                params[n] = bool(int(round(params[n])))
    
    # Handle TP method selection
    if 'TP Method' in params:
        tp_method = int(round(params['TP Method']))
        params['Fixed BB at Entry TP'] = (tp_method == 0)
        params['Fixed ATR TP'] = (tp_method == 1)
        params['Opposite Bollinger Band TP'] = (tp_method == 2)
        params.pop('TP Method', None)
    
    # Ensure critical integer parameters
    for pk in ['Bollinger Band Length', 'ATR Length for Trailing Stop', 'ATR Length for TP', 'Max Open Trades', 'RSI Period']:
        if pk in params:
            params[pk] = max(1 if pk != 'Trailing Delay (bars)' else 0, int(round(params[pk])))
    
    if 'Trailing Delay (bars)' in params:
        params['Trailing Delay (bars)'] = max(0, int(round(params['Trailing Delay (bars)'])))
    if 'Trailing Delay (minutes)' in params:
        params['Trailing Delay (minutes)'] = max(0, int(round(params['Trailing Delay (minutes)'])))
        
    if 'Timeframe (minutes)' in params:
        params['Timeframe (minutes)'] = max(1, int(round(params['Timeframe (minutes)'])))
    elif 'Timeframe (minutes)' in param_dict_local:
        params['Timeframe (minutes)'] = max(1, int(round(param_dict_local['Timeframe (minutes)']['value'])))
    apply_trailing_param_context(params, param_dict_local)
    if trailing_stop_enabled(params, param_dict_local):
        sync_trailing_delay_params(
            params, param_dict_local, params.get('Timeframe (minutes)', 15))
    apply_rsi_param_context(params, param_dict_local)
    apply_adx_param_context(params, param_dict_local)
    apply_sma_param_context(params, param_dict_local)
    apply_volume_param_context(params, param_dict_local)
    apply_rth_param_context(params, param_dict_local)
    apply_maintenance_param_context(params, param_dict_local)
    apply_lookback_bars_from_minutes(params, param_dict_local)

    metrics = run_backtest(params, df_local, param_dict_local, suppress_output=True, mask=mask_local)
    
    # Get base metrics
    sortino_raw = metrics['sortino']
    sortino = metrics['sortino']
    max_dd = metrics['max_drawdown']
    pf = metrics['profit_factor']
    trades_df = metrics.get('trades_df', pd.DataFrame())
    total_pnl = trades_df['pnl'].sum() if not trades_df.empty else 0
    win_rate = (trades_df['pnl'] > 0).sum() / len(trades_df) if not trades_df.empty else 0.0
    avg_trades_day = metrics.get('avg_trades_day', 0.0)
    
    # GA Parameters from CSV
    min_trades = param_dict_local.get('MIN_TRADES_DAY', {'value': 1.0})['value']
    target_trades = param_dict_local.get('TARGET_TRADES_DAY', {'value': 2})['value']
    trades_penalty_weight = param_dict_local.get('TRADES_PENALTY_WEIGHT', {'value': 0.5})['value']
    min_win_rate = param_dict_local.get('MIN_WIN_RATE', {'value': 0.40})['value']
    limit_max_loss = param_dict_local.get('LIMIT_MAX_LOSS', {'value': 50000.0})['value']
    limit_min_sortino = param_dict_local.get('LIMIT_MIN_SORTINO', {'value': 1.0})['value']
    
    # 1. HARD PENALTY: Minimum trades per day
    low_trade_penalty = 0.0
    if avg_trades_day < min_trades:
        shortfall = min_trades - avg_trades_day
        low_trade_penalty = shortfall * 100.0
        
    # 2. GRADUATED PENALTIES
    constraint_penalty_factor = 1.0
    
    # Win Rate Constraint
    if not trades_df.empty and len(trades_df) >= 10:
        if win_rate < min_win_rate:
            violation_pct = (min_win_rate - win_rate) / min_win_rate
            penalty = violation_pct ** 1.5
            constraint_penalty_factor *= (1.0 - penalty * 0.9)
    
    # Profitability Constraint
    if total_pnl < 0:
        loss_magnitude = abs(total_pnl)
        if loss_magnitude > limit_max_loss:
            penalty = 0.95
        elif loss_magnitude > 10000:
            penalty = 0.80 + (loss_magnitude - 10000) / (limit_max_loss - 10000) * 0.15 if limit_max_loss > 10000 else 0.95
        elif loss_magnitude > 1000:
            penalty = 0.50 + (loss_magnitude - 1000) / 9000 * 0.30
        else:
            penalty = 0.20 + (loss_magnitude / 1000) * 0.30
        constraint_penalty_factor *= (1.0 - penalty)
    
    # Negative Sortino Constraint
    if sortino_raw < 0:
        sortino_magnitude = abs(sortino_raw)
        if sortino_magnitude > 5.0:
            penalty = 0.95
        elif sortino_magnitude > 2.0:
            penalty = 0.80 + (sortino_magnitude - 2.0) / 3.0 * 0.15
        elif sortino_magnitude > limit_min_sortino:
            penalty = 0.50 + (sortino_magnitude - limit_min_sortino) / (2.0 - limit_min_sortino) * 0.30 if limit_min_sortino < 2.0 else 0.80
        else:
            penalty = 0.30 + (sortino_magnitude / limit_min_sortino) * 0.20 if limit_min_sortino > 0 else 0.50
        constraint_penalty_factor *= (1.0 - penalty)
        sortino = max(0.01, sortino_raw * (1.0 - penalty * 0.5))
    
    sortino *= constraint_penalty_factor
    pf *= constraint_penalty_factor
    
    # 3. SOFT PENALTIES
    penalty_factor = 1.0
    
    # Trade frequency penalty
    if avg_trades_day < min_trades:
        penalty_factor_trades = 1.0 - (avg_trades_day / min_trades)
        penalty_factor *= (1.0 - penalty_factor_trades * 0.6)
    
    # Excess trades penalty
    if avg_trades_day > target_trades:
        excess_ratio = (avg_trades_day - target_trades) / target_trades
        if excess_ratio >= 3.0:
            penalty_factor *= 0.1
        elif excess_ratio >= 2.0:
            penalty_factor *= 0.25
        elif excess_ratio >= 1.0:
            penalty_factor *= 0.5
        else:
            penalty_factor *= (1.0 - excess_ratio * trades_penalty_weight)
            
    # High Win Rate Penalty
    max_win_rate_cap = param_dict_local.get('MAX_WIN_RATE_CAP', {'value': 0.95})['value']
    if not trades_df.empty and win_rate > max_win_rate_cap:
        excess_wr = (win_rate - max_win_rate_cap) / (1.0 - max_win_rate_cap) if max_win_rate_cap < 1.0 else 1.0
        penalty_factor *= (1.0 - excess_wr * 0.3)
    
    # Min Trade Duration Penalty (bar-aligned minutes, same definition as avg_trade_duration_min)
    min_trade_duration = param_dict_local.get('MIN_TRADE_DURATION', {'value': 2.0})['value']
    _tf_pen = float(max(1, int(round(params.get('Timeframe (minutes)', 1)))))
    if not trades_df.empty and 'entry_time' in trades_df.columns and 'exit_time' in trades_df.columns:
        durations = _trade_duration_minutes_bar_aligned(trades_df, _tf_pen)
        avg_duration = float(durations.mean()) if len(durations) else 0.0
        if avg_duration < min_trade_duration:
            penalty = (min_trade_duration - avg_duration) / min_trade_duration if min_trade_duration > 0 else 0
            penalty_factor *= (1.0 - penalty * 0.2)
            
    # No TP Penalty
    if not (params.get('Opposite Bollinger Band TP', False) or params.get('Fixed ATR TP', False) or params.get('Fixed BB at Entry TP', False)):
        penalty_factor *= 0.3

    # Interaction: many entry/session filters enabled but trades/day below rising floor
    fsp_raw = param_dict_local.get('ENABLE_FILTER_STACK_TRADE_PENALTY', {'value': 0})
    try:
        fsp_enabled = bool(int(round(float(fsp_raw.get('value', 0)))))
    except Exception:
        fsp_enabled = _param_truthy(fsp_raw.get('value', 0))
    if fsp_enabled:
        k_stack = count_enabled_stack_filters(params, param_dict_local)
        try:
            fsp_strength = float(param_dict_local.get('INTERACTION_PENALTY_STRENGTH', {'value': 0.4})['value'])
        except Exception:
            fsp_strength = 0.4
        try:
            fsp_base = float(param_dict_local.get('INTERACTION_LOW_TRADES_BASE', {'value': 0.2})['value'])
        except Exception:
            fsp_base = 0.2
        try:
            fsp_per = float(param_dict_local.get('INTERACTION_LOW_TRADES_PER_FILTER', {'value': 0.15})['value'])
        except Exception:
            fsp_per = 0.15
        try:
            fsp_min_k = int(round(float(param_dict_local.get('INTERACTION_MIN_FILTERS', {'value': 2})['value'])))
        except Exception:
            fsp_min_k = 2
        penalty_factor *= filter_stack_trade_penalty_multiplier(
            avg_trades_day=avg_trades_day,
            filter_count=k_stack,
            strength=fsp_strength,
            base=fsp_base,
            per_filter=fsp_per,
            min_filters=fsp_min_k,
        )

    sortino *= penalty_factor
    pf *= penalty_factor
    
    # 4. NORMALIZATION
    SORTINO_MAX = param_dict_local.get('NORM_SORTINO_MAX', {'value': 10.0})['value']
    DD_MAX = param_dict_local.get('NORM_DD_MAX', {'value': 100000.0})['value']
    PF_MAX = param_dict_local.get('NORM_PF_MAX', {'value': 5.0})['value']
    TRADES_MAX = param_dict_local.get('NORM_TRADES_MAX', {'value': 3.0})['value']
    PNL_MAX = param_dict_local.get('NORM_PNL_MAX', {'value': 200000.0})['value']
    NORM_PPT_MAX = param_dict_local.get('NORM_PROFIT_TRADE_MAX', {'value': 250.0})['value']
    
    avg_profit_per_trade = total_pnl / len(trades_df) if not trades_df.empty else 0.0

    # Pre-cap ratios (same numerators as fitness normalization; no min(...,1) — can exceed 1.0 for dashboard only)
    try:
        uc_sortino = float(sortino) / float(SORTINO_MAX) if SORTINO_MAX else 0.0
    except (TypeError, ZeroDivisionError, ValueError):
        uc_sortino = 0.0
    try:
        uc_dd = float(max_dd) / float(DD_MAX) if DD_MAX else 0.0
    except (TypeError, ZeroDivisionError, ValueError):
        uc_dd = 0.0
    try:
        uc_pf = float(pf) / float(PF_MAX) if PF_MAX else 0.0
    except (TypeError, ZeroDivisionError, ValueError):
        uc_pf = 0.0
    try:
        uc_trades = float(avg_trades_day) / float(TRADES_MAX) if TRADES_MAX else 0.0
    except (TypeError, ZeroDivisionError, ValueError):
        uc_trades = 0.0
    try:
        uc_pnl = float(total_pnl) / float(PNL_MAX) if PNL_MAX else 0.0
    except (TypeError, ZeroDivisionError, ValueError):
        uc_pnl = 0.0
    try:
        uc_ppt = float(avg_profit_per_trade) / float(NORM_PPT_MAX) if NORM_PPT_MAX else 0.0
    except (TypeError, ZeroDivisionError, ValueError):
        uc_ppt = 0.0
    uncapped_ratios = (uc_sortino, uc_dd, uc_pf, uc_trades, uc_pnl, uc_ppt)

    normalized_sortino = min(uc_sortino, 1.0)
    normalized_dd = max_dd / DD_MAX
    normalized_pf = min(uc_pf, 1.0)
    normalized_trades = min(uc_trades, 1.0)
    normalized_pnl = min(uc_pnl, 1.0)
    normalized_ppt = min(uc_ppt, 1.0)
    
    # Apply Low Trade Penalty (Subtractive)
    normalized_sortino -= low_trade_penalty
    normalized_pf -= low_trade_penalty
    normalized_trades -= low_trade_penalty
    normalized_pnl -= low_trade_penalty
    normalized_ppt -= low_trade_penalty
    normalized_dd += low_trade_penalty # DD is minimized (so addition is penalty)
    
    # Apply Constraint Penalty (Subtractive)
    if constraint_penalty_factor < 1.0:
        penalty_hit = (1.0 - constraint_penalty_factor)
        normalized_sortino -= penalty_hit
        normalized_pf -= penalty_hit
        normalized_trades -= penalty_hit
        normalized_pnl -= penalty_hit
        normalized_ppt -= penalty_hit
        normalized_dd += penalty_hit

    fit = (
        float(normalized_sortino),
        float(normalized_dd),
        float(normalized_pf),
        float(normalized_trades),
        float(normalized_pnl),
        float(normalized_ppt),
    )
    return fit, uncapped_ratios

def evaluate_multi_objective(ind_and_data):
    global param_keys, param_dict
    if len(ind_and_data) == 3:
        ind, df, mask = ind_and_data
    else:
        ind, df = ind_and_data
        mask = None
    out = core_evaluate(ind, df, param_dict, param_keys, mask)
    if isinstance(out, tuple) and len(out) == 2:
        fit, unc = out
    else:
        fit, unc = out, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    try:
        setattr(ind, 'uncapped_ratios', unc)
    except Exception:
        pass
    return fit

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
_worker_mask = None
_worker_param_dict = None
_worker_keys = None

def init_worker(df_shared, mask_shared, param_dict_shared, keys_shared):
    """
    Initialize worker process with shared data to avoid pickling overhead on every task.
    """
    global _worker_df, _worker_mask, _worker_param_dict, _worker_keys
    _worker_df = df_shared
    _worker_mask = mask_shared
    _worker_param_dict = param_dict_shared
    _worker_keys = keys_shared

# Module-level function for multiprocessing (must be at module level to be picklable)
def _evaluate_worker(ind):
    # Use shared memory globals initialized via init_worker
    df_local = _worker_df
    mask_local = _worker_mask
    param_dict_local = _worker_param_dict
    param_keys_local = _worker_keys
    
    # Check for legacy mode (WinError 1450 handled via proper init_worker now)
    if df_local is None:
        bad = (-1000.0, 100000.0, 0.0, 0.0, 0.0, 0.0)
        return bad, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    return core_evaluate(ind, df_local, param_dict_local, param_keys_local, mask_local)

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
    if 'Trailing Delay (minutes)' in clamped:
        clamped['Trailing Delay (minutes)'] = max(0, int(round(clamped['Trailing Delay (minutes)'])))
    if 'Timeframe (minutes)' in clamped:
        clamped['Timeframe (minutes)'] = max(1, int(round(clamped['Timeframe (minutes)'])))
    if 'Max Open Trades' in clamped:
        clamped['Max Open Trades'] = max(1, int(round(clamped['Max Open Trades'])))
    for pk in ('Channel Exit Sell Lookback (bars)', 'Channel Exit Buy Lookback (bars)'):
        if pk in clamped:
            clamped[pk] = max(1, int(round(clamped[pk])))
    if 'Channel Exit ATR Offset' in clamped:
        clamped['Channel Exit ATR Offset'] = max(0.0, float(clamped['Channel Exit ATR Offset']))
    return clamped

from strategies.trend.parameters import (
    resolve_trailing_delay_bars as _resolve_trailing_delay_bars_core,
    sync_trailing_delay_params,
    exclude_trailing_delay_from_param_ranges,
)


def resolve_trailing_delay_bars(params_local, param_dict_local=None, fallback_tf=15):
    """Resolve effective trailing delay bars (single active GA gene: minutes or bars)."""
    return _resolve_trailing_delay_bars_core(params_local, param_dict_local, fallback_tf)


_TRAILING_CONTEXT_KEYS = (
    'Trailing Delay (bars)',
    'Trailing Delay (minutes)',
    'ATR Multiplier for Trailing Stop',
    'ATR Length for Trailing Stop',
)


def trailing_stop_enabled(params_local, param_dict_local):
    """True if trailing is on for this evaluation (gene or template default)."""
    v = params_local.get('Enable Trailing Stop')
    if v is None and isinstance(param_dict_local, dict):
        meta = param_dict_local.get('Enable Trailing Stop', {})
        if isinstance(meta, dict):
            v = meta.get('value', 0)
        else:
            v = 0
    try:
        return bool(int(round(float(v))))
    except Exception:
        return bool(v)


def apply_trailing_param_context(params_local, param_dict_local):
    """
    When trailing is disabled, drop trailing-specific genes so they do not
    override template defaults in the strategy (dead dimensions during search).
    """
    if trailing_stop_enabled(params_local, param_dict_local):
        return params_local
    for k in _TRAILING_CONTEXT_KEYS:
        params_local.pop(k, None)
    return params_local


_RSI_CONTEXT_KEYS = (
    'RSI Period',
    'RSI Max Buy Threshold',
    'RSI Min Sell Threshold',
)


def rsi_filter_enabled(params_local, param_dict_local):
    """True if RSI filter is on for this evaluation (gene or template default)."""
    v = params_local.get('Enable RSI Filter')
    if v is None and isinstance(param_dict_local, dict):
        meta = param_dict_local.get('Enable RSI Filter', {})
        if isinstance(meta, dict):
            v = meta.get('value', 0)
        else:
            v = 0
    try:
        return bool(int(round(float(v))))
    except Exception:
        return bool(v)


def apply_rsi_param_context(params_local, param_dict_local):
    """
    When RSI filter is disabled, drop RSI tuning genes so they do not affect
    evaluation (dead dimensions); strategy restores thresholds from template.
    """
    if rsi_filter_enabled(params_local, param_dict_local):
        return params_local
    for k in _RSI_CONTEXT_KEYS:
        params_local.pop(k, None)
    return params_local


def _toggle_int_enabled(params_local, param_dict_local, enable_key):
    v = params_local.get(enable_key)
    if v is None and isinstance(param_dict_local, dict):
        meta = param_dict_local.get(enable_key, {})
        if isinstance(meta, dict):
            v = meta.get('value', 0)
        else:
            v = 0
    try:
        return bool(int(round(float(v))))
    except Exception:
        return bool(v)


_ADX_CONTEXT_KEYS = (
    'ADX Period',
    'Min ADX Threshold',
)


def adx_filter_enabled(params_local, param_dict_local):
    return _toggle_int_enabled(params_local, param_dict_local, 'Enable ADX Filter')


def apply_adx_param_context(params_local, param_dict_local):
    if adx_filter_enabled(params_local, param_dict_local):
        return params_local
    for k in _ADX_CONTEXT_KEYS:
        params_local.pop(k, None)
    return params_local


_SMA_CONTEXT_KEYS = ('SMA Period',)


def sma_filter_enabled(params_local, param_dict_local):
    return _toggle_int_enabled(params_local, param_dict_local, 'Enable SMA Filter')


def apply_sma_param_context(params_local, param_dict_local):
    if sma_filter_enabled(params_local, param_dict_local):
        return params_local
    for k in _SMA_CONTEXT_KEYS:
        params_local.pop(k, None)
    return params_local


_VOL_CONTEXT_KEYS = (
    'Volume MA Length',
    'Min Volume Multiplier',
)


def volume_filter_enabled(params_local, param_dict_local):
    return _toggle_int_enabled(params_local, param_dict_local, 'Enable Volume Filter')


def apply_volume_param_context(params_local, param_dict_local):
    if volume_filter_enabled(params_local, param_dict_local):
        return params_local
    for k in _VOL_CONTEXT_KEYS:
        params_local.pop(k, None)
    return params_local


_RTH_CONTEXT_KEYS = (
    'RTH Exit Buffer (minutes)',
)


def rth_filter_enabled(params_local, param_dict_local):
    return _toggle_int_enabled(params_local, param_dict_local, 'Enable RTH Filter')


def apply_rth_param_context(params_local, param_dict_local):
    if rth_filter_enabled(params_local, param_dict_local):
        return params_local
    for k in _RTH_CONTEXT_KEYS:
        params_local.pop(k, None)
    return params_local


_MAINT_CONTEXT_KEYS = (
    'Maintenance Buffer Minutes',
)


def maintenance_filter_enabled(params_local, param_dict_local):
    v = params_local.get('Enable Maintenance Filter')
    if v is None and isinstance(param_dict_local, dict):
        meta = param_dict_local.get('Enable Maintenance Filter', {})
        if isinstance(meta, dict):
            v = meta.get('value', False)
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ('1', 'true', 'yes')
    try:
        return bool(int(round(float(v))))
    except Exception:
        return bool(v)


def apply_maintenance_param_context(params_local, param_dict_local):
    if maintenance_filter_enabled(params_local, param_dict_local):
        return params_local
    for k in _MAINT_CONTEXT_KEYS:
        params_local.pop(k, None)
    return params_local


# Parent toggle -> child genes stripped at evaluation when parent is off.
# Genome slots may still mutate (dead dimensions); CSV export must preserve raw
# genome values for children — not template back-fill after stripping.
PARAM_CONTEXT_GROUPS = (
    ('Enable Trailing Stop', _TRAILING_CONTEXT_KEYS),
    ('Enable RSI Filter', _RSI_CONTEXT_KEYS),
    ('Enable ADX Filter', _ADX_CONTEXT_KEYS),
    ('Enable SMA Filter', _SMA_CONTEXT_KEYS),
    ('Enable Volume Filter', _VOL_CONTEXT_KEYS),
    ('Enable RTH Filter', _RTH_CONTEXT_KEYS),
    ('Enable Maintenance Filter', _MAINT_CONTEXT_KEYS),
)


def context_child_param_keys():
    """All parameter names that are inactive when their parent toggle is off."""
    keys = []
    for _, children in PARAM_CONTEXT_GROUPS:
        keys.extend(children)
    return tuple(keys)


_LOOKBACK_TEMPLATE_KEYS = (
    'Buy Lookback (minutes)',
    'Sell Lookback (minutes)',
    'Buy Lookback',
    'Sell Lookback',
    'Timeframe (minutes)',
)


def merge_eval_params_for_lookback(params_local, param_dict_local):
    """Fill missing lookback-related keys from CSV template (fixed genes / exports)."""
    out = dict(params_local)
    if not param_dict_local:
        return out
    for k in _LOOKBACK_TEMPLATE_KEYS:
        if k in out:
            continue
        meta = param_dict_local.get(k)
        if not isinstance(meta, dict):
            continue
        v = meta.get('value')
        if v is None or (isinstance(v, float) and (np.isnan(v) or pd.isna(v))):
            continue
        out[k] = v
    return out


def resolve_buy_lookback_bars(params_local, fallback_tf=15):
    """Prefer Buy Lookback (minutes) / Timeframe → bars; else raw Buy Lookback bars."""
    merge_tf = max(1, int(round(float(params_local.get('Timeframe (minutes)', fallback_tf)))))
    if 'Buy Lookback (minutes)' in params_local:
        try:
            mins = max(0.0, float(params_local['Buy Lookback (minutes)']))
            return max(1, int(round(mins / merge_tf)))
        except Exception:
            pass
    try:
        return max(1, int(round(float(params_local.get('Buy Lookback', 20)))))
    except Exception:
        return 1


def resolve_sell_lookback_bars(params_local, fallback_tf=15):
    """Prefer Sell Lookback (minutes) / Timeframe → bars; else raw Sell Lookback bars."""
    merge_tf = max(1, int(round(float(params_local.get('Timeframe (minutes)', fallback_tf)))))
    if 'Sell Lookback (minutes)' in params_local:
        try:
            mins = max(0.0, float(params_local['Sell Lookback (minutes)']))
            return max(1, int(round(mins / merge_tf)))
        except Exception:
            pass
    try:
        return max(1, int(round(float(params_local.get('Sell Lookback', 20)))))
    except Exception:
        return 1


def apply_lookback_bars_from_minutes(params_local, param_dict_local):
    """
    When CSV defines minute lookbacks, set Buy/Sell Lookback bar genes from wall-clock minutes.
    No-op if minute rows absent (backward compatible bars-only CSV).
    """
    if not param_dict_local:
        return params_local
    merged = merge_eval_params_for_lookback(params_local, param_dict_local)
    if 'Buy Lookback (minutes)' in param_dict_local:
        params_local['Buy Lookback'] = resolve_buy_lookback_bars(merged)
    if 'Sell Lookback (minutes)' in param_dict_local:
        params_local['Sell Lookback'] = resolve_sell_lookback_bars(merged)
    apply_channel_exit_lookbacks(params_local, param_dict_local)
    return params_local


def apply_channel_exit_lookbacks(params_local, param_dict_local):
    """Mirror entry lookbacks for channel exit when exit rows absent from CSV."""
    if not param_dict_local:
        return params_local
    merged = merge_eval_params_for_lookback(params_local, param_dict_local)
    if 'Channel Exit Sell Lookback (bars)' not in param_dict_local:
        params_local['Channel Exit Sell Lookback (bars)'] = resolve_sell_lookback_bars(merged)
    if 'Channel Exit Buy Lookback (bars)' not in param_dict_local:
        params_local['Channel Exit Buy Lookback (bars)'] = resolve_buy_lookback_bars(merged)
    return params_local


def _rsi_export_style(params_local, param_dict_local):
    """Detect param schema for dual-report RSI line (Trend vs Bollinger)."""
    pd_keys = set(param_dict_local.keys()) if param_dict_local else set()
    pl_keys = set(params_local.keys()) if params_local else set()
    if 'RSI Max Buy Threshold' in pd_keys or 'RSI Max Buy Threshold' in pl_keys:
        return 'trend'
    if 'RSI Overbought' in pd_keys or 'RSI Overbought' in pl_keys:
        return 'bollinger'
    return 'trend'


def describe_effective_rsi_band(params_local, param_dict_local=None):
    """
    One-line summary of RSI entry-filter semantics for genetic_results CSV (dual report).
    Uses merged solution params (template-filled when RSI genes were dropped).
    """
    param_dict_local = param_dict_local or {}
    if not rsi_filter_enabled(params_local, param_dict_local):
        return 'filter off (RSI not applied to entries)'

    def _coerce_float(key, fallback):
        v = params_local.get(key)
        if v is None:
            meta = param_dict_local.get(key)
            if isinstance(meta, dict):
                v = meta.get('value', fallback)
            else:
                v = fallback
        try:
            return float(v)
        except Exception:
            return float(fallback)

    def _coerce_int(key, fallback):
        v = params_local.get(key)
        if v is None:
            meta = param_dict_local.get(key)
            if isinstance(meta, dict):
                v = meta.get('value', fallback)
            else:
                v = fallback
        try:
            return int(round(float(v)))
        except Exception:
            return int(fallback)

    period = _coerce_int('RSI Period', 14)
    style = _rsi_export_style(params_local, param_dict_local)
    if style == 'bollinger':
        ob = _coerce_int('RSI Overbought', 70)
        os_ = _coerce_int('RSI Oversold', 30)
        return (
            f'on (mean reversion): period={period}, '
            f'long if RSI<{os_}, short if RSI>{ob}'
        )
    mx = _coerce_float('RSI Max Buy Threshold', 70.0)
    ms = _coerce_float('RSI Min Sell Threshold', 30.0)
    return f'on (Trend gates): period={period}, long if RSI<{mx:.1f}, short if RSI>{ms:.1f}'


_FILTER_STACK_COUNT_KEYS = (
    'Enable ADX Filter',
    'Enable SMA Filter',
    'Enable Trend Filter',
    'Enable Volume Filter',
    'Enable RSI Filter',
    'Enable VWAP Filter',
    'Enable RTH Filter',
    'Enable Maintenance Filter',
)


def _param_truthy(v) -> bool:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        try:
            return int(round(float(v))) != 0
        except Exception:
            return False
    if isinstance(v, str):
        return v.strip().lower() in ('1', 'true', 'yes')
    return bool(v)


def count_enabled_stack_filters(params_local, param_dict_local) -> int:
    """
    Count coarse entry/session gates for interaction penalty (keys must exist in param CSV).
    """
    if not param_dict_local:
        return 0
    n = 0
    for key in _FILTER_STACK_COUNT_KEYS:
        if key not in param_dict_local:
            continue
        v = params_local.get(key)
        if v is None:
            v = param_dict_local[key].get('value')
        if _param_truthy(v):
            n += 1
    return n


def filter_stack_trade_penalty_multiplier(
    *,
    avg_trades_day: float,
    filter_count: int,
    strength: float,
    base: float,
    per_filter: float,
    min_filters: int,
) -> float:
    """
    Extra soft penalty when many filters are on but realized trades/day stay below a
    rising floor (base + per_filter * count). Returns a multiplier in (0, 1] for penalty_factor.
    """
    try:
        min_filters = int(max(0, min_filters))
    except Exception:
        min_filters = 2
    if filter_count < min_filters:
        return 1.0
    try:
        expected = float(base) + float(per_filter) * float(filter_count)
    except Exception:
        return 1.0
    if expected <= 0:
        return 1.0
    try:
        atd = float(avg_trades_day)
    except Exception:
        atd = 0.0
    shortfall = max(0.0, expected - atd)
    if shortfall <= 0:
        return 1.0
    try:
        strength = float(strength)
    except Exception:
        strength = 0.0
    strength = max(0.0, min(1.0, strength))
    rel = min(1.0, shortfall / expected)
    return 1.0 - strength * rel


def finalize_ga_solution_params(raw_params, param_dict):
    """
    Clamp and cast one solution's parameters the same way as Hall-of-Fame export / evaluation.
    Accepts a dict mapping param name -> value (from a DEAP individual or a genetic_results CSV column).
    """
    clamped_params = {}
    for n, v in raw_params.items():
        if n not in param_dict:
            continue
        mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
        try:
            if isinstance(mn, (int, float)) and isinstance(mx, (int, float)) and isinstance(v, (int, float)):
                v = max(mn, min(v, mx))
        except Exception:
            pass
        if typ == 'int':
            clamped_params[n] = int(round(float(v)))
        elif typ == 'float':
            clamped_params[n] = float(v)
        else:
            clamped_params[n] = v

    for n in list(clamped_params.keys()):
        v = clamped_params[n]
        if isinstance(v, float) and (np.isnan(v) or pd.isna(v)):
            dv = param_dict.get(n, {}).get('value')
            if dv is not None and not (isinstance(dv, float) and (np.isnan(dv) or pd.isna(dv))):
                clamped_params[n] = dv
        v = clamped_params[n]
        if n in param_dict:
            original_type = param_dict[n].get('type', '')
            if original_type == 'bool' and isinstance(v, (int, float)) and not (isinstance(v, float) and (np.isnan(v) or pd.isna(v))):
                clamped_params[n] = bool(int(round(v)))

    if 'TP Method' in clamped_params:
        tp_method = int(round(clamped_params['TP Method']))
        clamped_params['Fixed BB at Entry TP'] = (tp_method == 0)
        clamped_params['Fixed ATR TP'] = (tp_method == 1)
        clamped_params['Opposite Bollinger Band TP'] = (tp_method == 2)
        clamped_params.pop('TP Method', None)

    if 'Bollinger Band Length' in clamped_params:
        clamped_params['Bollinger Band Length'] = max(1, int(round(clamped_params['Bollinger Band Length'])))
    if 'ATR Length for Trailing Stop' in clamped_params:
        clamped_params['ATR Length for Trailing Stop'] = max(1, int(round(clamped_params['ATR Length for Trailing Stop'])))
    if 'ATR Length for TP' in clamped_params:
        clamped_params['ATR Length for TP'] = max(1, int(round(clamped_params['ATR Length for TP'])))
    if 'Trailing Delay (bars)' in clamped_params:
        clamped_params['Trailing Delay (bars)'] = max(0, int(round(clamped_params['Trailing Delay (bars)'])))
    if 'Trailing Delay (minutes)' in clamped_params:
        clamped_params['Trailing Delay (minutes)'] = max(0, int(round(clamped_params['Trailing Delay (minutes)'])))
    clamped_params['Timeframe (minutes)'] = max(1, int(round(clamped_params.get('Timeframe (minutes)', 15))))
    apply_trailing_param_context(clamped_params, param_dict)
    if trailing_stop_enabled(clamped_params, param_dict):
        sync_trailing_delay_params(
            clamped_params, param_dict, clamped_params['Timeframe (minutes)'])
    apply_rsi_param_context(clamped_params, param_dict)
    apply_adx_param_context(clamped_params, param_dict)
    apply_sma_param_context(clamped_params, param_dict)
    apply_volume_param_context(clamped_params, param_dict)
    apply_rth_param_context(clamped_params, param_dict)
    apply_maintenance_param_context(clamped_params, param_dict)
    apply_lookback_bars_from_minutes(clamped_params, param_dict)
    if 'Max Open Trades' in clamped_params:
        clamped_params['Max Open Trades'] = max(1, int(round(clamped_params['Max Open Trades'])))
    for pk in ('Channel Exit Sell Lookback (bars)', 'Channel Exit Buy Lookback (bars)'):
        if pk in clamped_params:
            clamped_params[pk] = max(1, int(round(clamped_params[pk])))
    if 'Channel Exit ATR Offset' in clamped_params:
        clamped_params['Channel Exit ATR Offset'] = max(0.0, float(clamped_params['Channel Exit ATR Offset']))
    if 'Enable ADX Filter' in clamped_params:
        clamped_params['Enable ADX Filter'] = int(round(clamped_params['Enable ADX Filter']))
    if 'ADX Period' in clamped_params:
        clamped_params['ADX Period'] = max(1, int(round(clamped_params['ADX Period'])))
    if 'Enable Trend Filter' in clamped_params:
        clamped_params['Enable Trend Filter'] = int(round(clamped_params['Enable Trend Filter']))
    if 'Trend EMA Length' in clamped_params:
        clamped_params['Trend EMA Length'] = max(1, int(round(clamped_params['Trend EMA Length'])))
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

    return clamped_params


def merge_solution_params_with_template(clamped_params, param_dict, param_df):
    """
    Fill in parameters that the GA does not mutate (fixed / template-only rows).

    Hall-of-Fame CSV export previously left those cells empty, which made replays
    ambiguous unless loaders fell back to the template ``Value`` column. We merge
    ``param_dict`` / ``param_df`` defaults so every parameter row gets an explicit
    value in each Solution_* column.
    """
    merged = dict(clamped_params)
    for _, row in param_df.iterrows():
        name = row.get('Name')
        if pd.isna(name):
            continue
        name = str(name).strip()
        if not name or name.startswith('===') or name.startswith('---'):
            continue
        if '__' in name:
            continue
        if name not in param_dict:
            continue
        meta = param_dict[name]
        typ = meta.get('type', '')
        if typ in ('statistic', 'robustness', 'split_detail'):
            continue
        if name in merged:
            continue
        default_val = meta.get('value')
        if default_val is None and 'Value' in row.index:
            default_val = row['Value']
        merged[name] = default_val
    return merged


def build_solution_export_params(raw_params, param_dict, param_df, param_keys_local):
    """
    Build CSV export params: effective values for backtest parity plus raw genome
    slots for every optimizable gene.

    ``finalize_ga_solution_params`` strips context-dependent children when a parent
    toggle is off (so fitness matches evaluation). ``merge_solution_params_with_template``
    then back-filled template defaults into those holes — making every solution look
    like it shared the same trailing delay / ATR mult when trailing was off.

  Export overlays clamped genome values for all ``param_keys`` so inactive child
    genes show their actual (dormant) alleles, while derived statistic rows should
    use the returned ``effective_params``.
    """
    effective_params = finalize_ga_solution_params(dict(raw_params), param_dict)
    genome_clamped = clamp_params(dict(raw_params), param_dict)
    export_params = merge_solution_params_with_template(
        effective_params, param_dict, param_df)
    if param_keys_local:
        for key in param_keys_local:
            if key in genome_clamped:
                export_params[key] = genome_clamped[key]
    return export_params, effective_params


# Helper function to extract chart HTML (moved to global scope)
def extract_chart_html(html_snippet):
    if not html_snippet or len(html_snippet) == 0:
        return "", ""
    # Plotly full_html=False: <div>…<div id="…"></div>  <script>…</script>  </div>
    # The closing </div> must stay with the div block; otherwise the outer <div>
    # stays open and swallows following dashboard content (elite charts look blank).
    script_start = html_snippet.find("<script")
    if script_start == -1:
        return html_snippet.strip(), ""
    div_part = html_snippet[:script_start].strip()
    script_end = html_snippet.find("</script>", script_start)
    if script_end == -1:
        return div_part, ""
    script_part = html_snippet[script_start : script_end + 9]
    remainder = html_snippet[script_end + 9 :].strip()
    if remainder.startswith("</div>"):
        close_end = remainder.find(">") + 1
        div_part = (div_part + remainder[:close_end]).strip()
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
                        'Enable ADX Filter', 'ADX Period', 'Min ADX Threshold', 'Max ADX Threshold',
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
                     'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT', 'GA_START_DATE', 'GA_END_DATE',
                     'GA_LIVE_STYLE_ENTRY', 'GA_CONSERVATIVE_STOP_SLIPPAGE', 'GA_CONSERVATIVE_ENTRY_SLIPPAGE', 'GA_CONSERVATIVE_CHANNEL_SLIPPAGE', 'GA_PESSIMISTIC_STOPS',
                     'WEIGHT_SORTINO', 'WEIGHT_DRAWDOWN', 'WEIGHT_PF', 'WEIGHT_TRADES', 'WEIGHT_PNL', 'WEIGHT_PPT',
                     'MIN_TRADE_DURATION', 'MAX_WIN_RATE_CAP', 'LIMIT_MAX_LOSS', 'LIMIT_MIN_SORTINO',
                     'ENABLE_FILTER_STACK_TRADE_PENALTY', 'INTERACTION_PENALTY_STRENGTH',
                     'INTERACTION_LOW_TRADES_BASE', 'INTERACTION_LOW_TRADES_PER_FILTER',
                     'INTERACTION_MIN_FILTERS']

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


def get_robustness_metrics(is_res, oos_res, is_periods_res, oos_periods_res):
    """
    Calculate robustness evaluation metrics based on IS vs OOS performance.
    """
    is_sortino = is_res.get('sortino', 0)
    oos_sortino = oos_res.get('sortino', 0)
    
    # 1. Sortino IS-to-OOS Degradation
    degradation = (is_sortino - oos_sortino) / is_sortino if is_sortino > 0 else 0.0
    
    # 2. Positive OOS Splits
    positive_oos = sum(1 for res in oos_periods_res if res.get('sortino', 0) > 0)
    total_oos = len(oos_periods_res)
    
    # 3. Live-Ready Robustness Score (0-100)
    # Heuristic: Combination of low degradation, positive OOS splits, and absolute OOS Sortino
    oos_stability = positive_oos / total_oos if total_oos > 0 else 0.5
    deg_penalty = max(0, min(1, degradation)) if degradation > 0 else 0
    raw_score = (oos_stability * 40) + (max(0, min(oos_sortino / 5.0, 1.0)) * 40) + ((1.0 - deg_penalty) * 20)
    robustness_score = round(raw_score, 1)
    
    return {
        'degradation': degradation,
        'positive_oos_splits': positive_oos,
        'total_oos_splits': total_oos,
        'robustness_score': robustness_score
    }

def calculate_split_detail(params, is_periods, oos_periods, param_dict, df_full=None):
    """
    Calculates primary performance metrics for each IS and OOS split individually.
    If df_full is provided, it uses it for full history warm-up.
    """
    is_results = []
    oos_results = []
    
    # Process In-Sample periods
    for i, period_df in enumerate(is_periods):
        p_name = f"P{i*2+1}" if len(is_periods) > 1 else "IS"
        # If full history is available, use it for warm-up but restrict evaluation to the period's date range
        if df_full is not None:
            # Create a mask for just this period
            mask = pd.Series(False, index=df_full.index)
            mask.loc[period_df.index[0]:period_df.index[-1]] = True
            res = run_backtest(params, df_full, param_dict, mask=mask)
        else:
            res = run_backtest(params, period_df, param_dict)
            
        res['period_name'] = p_name
        is_results.append(res)
        
    # Process Out-of-Sample periods
    for i, period_df in enumerate(oos_periods):
        p_name = f"P{(i+1)*2}" if len(oos_periods) > 1 else "OOS"
        if df_full is not None:
            mask = pd.Series(False, index=df_full.index)
            mask.loc[period_df.index[0]:period_df.index[-1]] = True
            res = run_backtest(params, df_full, param_dict, mask=mask)
        else:
            res = run_backtest(params, period_df, param_dict)
            
        res['period_name'] = p_name
        oos_results.append(res)
        
    return is_results, oos_results


def _atomic_write_utf8(target_path: str, content: str) -> None:
    """
    Write UTF-8 text atomically (temp file in same folder, then os.replace).
    Normalizes the path; avoids Windows quirks with direct truncate-open on some setups.
    """
    target_path = os.path.abspath(os.path.normpath(target_path))
    parent = os.path.dirname(target_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        suffix='.tmp', prefix='ga_dashboard_', dir=parent or None
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as tf:
            tf.write(content)
        os.replace(tmp_path, target_path)
    except BaseException:
        try:
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def _clamp(v, lo, hi):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return None
    x = float(v)
    if lo is not None:
        x = max(lo, x)
    if hi is not None:
        x = min(hi, x)
    return x


def _mirror_missing_pop_bounds(avg, ymin, ymax, clamp_lo=None, clamp_hi=None):
    """When checkpoint rows lack pop_min/pop_max columns, mirror spread around avg (viz-only estimate)."""
    avg = list(avg)
    ymin = list(ymin)
    ymax = list(ymax)
    n = min(len(avg), len(ymin), len(ymax))
    has_lo = any(ymin[i] is not None for i in range(n))
    has_hi = any(ymax[i] is not None for i in range(n))
    if not has_lo and has_hi:
        for i in range(n):
            a, y = avg[i], ymax[i]
            if a is not None and y is not None:
                ymin[i] = _clamp(2.0 * float(a) - float(y), clamp_lo, clamp_hi)
    elif has_lo and not has_hi:
        for i in range(n):
            a, lo = avg[i], ymin[i]
            if a is not None and lo is not None:
                ymax[i] = _clamp(2.0 * float(a) - float(lo), clamp_lo, clamp_hi)
    return ymin, ymax


def _synth_std_from_band_width(avg, ymin, ymax):
    """Populate std when pop_std_* was never logged (checkpoint legacy rows)."""
    std = []
    for a, lo, hi in zip(avg, ymin, ymax):
        if a is None or lo is None or hi is None:
            std.append(None)
            continue
        w = max(abs(float(hi) - float(a)), abs(float(a) - float(lo)), 1e-12)
        std.append(min(w, 10.0))  # cap so inner band does not dominate
    return std


def _add_population_envelope_traces(fig, gens, logbook, row, col, avg_key, min_key, max_key, std_key,
                                    outer_rgba, inner_rgba, show_legend=False,
                                    legend_outer='Pop min–max', legend_inner='Pop avg±0.5σ',
                                    clamp_lo=None, clamp_hi=None, avg_fallback_key=None):
    """Fill between pop min/max (light) and avg ± 0.5*std (darker).

    Checkpoints saved before pop_* stats existed still have avg/max/min lines per generation;
    header may list pop_* keys after resume but row dicts omit them — we mirror-estimate bounds.
    """
    hdr = tuple(logbook.header) if logbook.header else ()
    if avg_key not in hdr or max_key not in hdr:
        return
    avg = list(logbook.select(avg_key))
    if avg_fallback_key and avg_fallback_key in hdr and not any(v is not None for v in avg):
        avg = list(logbook.select(avg_fallback_key))
    ymin = list(logbook.select(min_key)) if min_key in hdr else [None] * len(avg)
    ymax = list(logbook.select(max_key))
    std = list(logbook.select(std_key)) if std_key in hdr else [None] * len(avg)

    def _clean(seq, lo=None, hi=None):
        out = []
        for v in seq:
            if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
                out.append(None)
            elif isinstance(v, (int, float)):
                fv = float(v)
                if lo is not None and fv < lo:
                    out.append(None)
                elif hi is not None and fv > hi:
                    out.append(None)
                else:
                    out.append(fv)
            else:
                out.append(None)
        return out

    avg = _clean(avg)
    ymin = _clean(ymin)
    ymax = _clean(ymax)
    std = _clean(std, lo=0)
    # Pad / trim to common length
    m = min(len(gens), len(avg), len(ymin), len(ymax), len(std))
    if m == 0:
        return
    gens = gens[:m]
    avg, ymin, ymax, std = avg[:m], ymin[:m], ymax[:m], std[:m]

    ymin, ymax = _mirror_missing_pop_bounds(avg, ymin, ymax, clamp_lo=clamp_lo, clamp_hi=clamp_hi)
    if not any(std[i] is not None and std[i] > 1e-15 for i in range(m)):
        std = _synth_std_from_band_width(avg, ymin, ymax)

    if not any(x is not None for x in avg):
        return
    if not any(ymin[i] is not None and ymax[i] is not None for i in range(m)):
        return
    upper, lower = [], []
    for a, s in zip(avg, std):
        if a is None:
            upper.append(None)
            lower.append(None)
        else:
            half = (s or 0.0) * 0.5
            upper.append(a + half)
            lower.append(a - half)
    fig.add_trace(go.Scatter(
        x=gens, y=ymax, mode='lines', line=dict(width=0),
        name=legend_outer, legendgroup=f'env{row}{col}', showlegend=False, hoverinfo='skip'),
        row=row, col=col)
    fig.add_trace(go.Scatter(
        x=gens, y=ymin, mode='lines', line=dict(width=0), fill='tonexty',
        fillcolor=outer_rgba, name=legend_outer, legendgroup=f'env{row}{col}',
        showlegend=show_legend, hoverinfo='skip'),
        row=row, col=col)
    fig.add_trace(go.Scatter(
        x=gens, y=upper, mode='lines', line=dict(width=0),
        name=legend_inner, legendgroup=f'in{row}{col}', showlegend=False, hoverinfo='skip'),
        row=row, col=col)
    fig.add_trace(go.Scatter(
        x=gens, y=lower, mode='lines', line=dict(width=0), fill='tonexty',
        fillcolor=inner_rgba, name=legend_inner, legendgroup=f'in{row}{col}',
        showlegend=show_legend, hoverinfo='skip'),
        row=row, col=col)


def generate_elite_parameter_insight_html(hof, param_keys, param_dict, max_individuals=400):
    """
    Boundary diagnostics + histograms + Sortino scatter for Hall of Fame elites.
    Returns (info_html, hist_div, hist_script, scatter_div, scatter_script).
    """
    empty = ('', '', '', '', '')
    if hof is None or len(hof) == 0:
        return empty
    inds = [ind for ind in list(hof)[:max_individuals] if getattr(ind, 'fitness', None) and ind.fitness.valid]
    if not inds:
        return empty
    key_to_i = {k: i for i, k in enumerate(param_keys)}

    def _numeric_param_bounds(name):
        if name not in param_dict:
            return None
        meta = param_dict[name]
        try:
            mn = float(meta['min'])
            mx = float(meta['max'])
        except (TypeError, ValueError, KeyError):
            return None
        if mx <= mn:
            return None
        typ = str(meta.get('type', '')).lower()
        return mn, mx, typ

    table_rows = []
    boundary_scores = []
    # Per-parameter (x values, matching fitness Sortino for each x) — same length for scatter
    param_series = {}

    for pk in param_keys:
        spec = _numeric_param_bounds(pk)
        if spec is None:
            continue
        mn, mx, typ = spec
        eps = max(1e-9, 0.01 * (mx - mn))
        if typ == 'int':
            eps = max(eps, 0.51)
        vals = []
        fit0 = []
        ki = key_to_i.get(pk)
        if ki is None:
            continue
        for ind in inds:
            try:
                vals.append(float(ind[ki]))
                fit0.append(float(ind.fitness.values[0]))
            except (TypeError, ValueError, IndexError):
                continue
        if not vals:
            continue
        arr = np.array(vals, dtype=float)
        param_series[pk] = (arr, np.array(fit0, dtype=float))
        n = len(arr)
        near_lo = np.sum(arr <= mn + eps) / n * 100.0
        near_hi = np.sum(arr >= mx - eps) / n * 100.0
        med = float(np.median(arr))
        boundary_scores.append((pk, near_lo + near_hi, near_lo, near_hi, med, mn, mx, n))
        flag = ''
        if near_lo >= 35 or near_hi >= 35:
            flag = ' (!) wall'
        elif near_lo >= 20 or near_hi >= 20:
            flag = ' (?) near bound'
        table_rows.append((pk, mn, mx, med, near_lo, near_hi, flag))

    table_rows.sort(key=lambda t: t[4] + t[5], reverse=True)

    info_html = (
        "<div class='info-section'><strong>How to read this:</strong> "
        "<em>% near Min/Max</em> is the share of Hall of Fame solutions within 1% of the allowed range "
        "(or 0.51 units for ints). High values suggest the GA is pressing a constraint — "
        "expansion <em>might</em> help, or the bound may be economically correct. "
        "This is not automatic advice.</div>"
        "<table class='params-table'><thead><tr>"
        "<th>Parameter</th><th>Min</th><th>Max</th><th>Elite median</th>"
        "<th>% near Min</th><th>% near Max</th><th>Flag</th></tr></thead><tbody>"
        + ''.join(
            f'<tr><td>{pk}</td><td>{mn:g}</td><td>{mx:g}</td><td>{med:.5g}</td>'
            f'<td>{near_lo:.1f}%</td><td>{near_hi:.1f}%</td><td>{flag}</td></tr>'
            for pk, mn, mx, med, near_lo, near_hi, flag in table_rows
        ) + "</tbody></table>"
    )

    boundary_scores.sort(key=lambda t: t[1], reverse=True)
    top_params = [t[0] for t in boundary_scores[:18]]

    if not top_params:
        return info_html, '', '', '', ''

    n_chart = len(top_params)
    n_cols = 3
    n_rows = (n_chart + n_cols - 1) // n_cols
    _cells = n_rows * n_cols
    _hist_titles = list(top_params) + [''] * max(0, _cells - n_chart)
    fig_h = make_subplots(rows=n_rows, cols=n_cols, subplot_titles=_hist_titles[:_cells], vertical_spacing=0.08, horizontal_spacing=0.06)
    for i, pk in enumerate(top_params):
        r = i // n_cols + 1
        c = i % n_cols + 1
        series = param_series.get(pk)
        if series is None:
            continue
        arr, _fit0 = series
        if arr is None or len(arr) == 0:
            continue
        fig_h.add_trace(go.Histogram(x=arr, nbinsx=min(30, max(8, int(np.sqrt(len(arr))))), name=pk, showlegend=False), row=r, col=c)
    fig_h.update_layout(height=260 * n_rows, title_text='Elite parameter distributions (high boundary pressure)', showlegend=False)
    hist_html = fig_h.to_html(include_plotlyjs=False, full_html=False, div_id='elite_hist')
    hist_div, hist_script = extract_chart_html(hist_html)

    top_scatter = boundary_scores[:12]
    n_s = len(top_scatter)
    n_c2 = 3
    n_r2 = (n_s + n_c2 - 1) // n_c2 if n_s else 1
    _cells2 = n_r2 * n_c2
    _sc_titles = [t[0] for t in top_scatter] + [''] * max(0, _cells2 - n_s)
    fig_s = make_subplots(rows=n_r2, cols=n_c2, subplot_titles=_sc_titles[:_cells2], vertical_spacing=0.1, horizontal_spacing=0.06)
    for i, tup in enumerate(top_scatter):
        pk = tup[0]
        r = i // n_c2 + 1
        c = i % n_c2 + 1
        series = param_series.get(pk)
        if series is None:
            continue
        arr, y_sort = series
        if len(arr) == 0:
            continue
        fig_s.add_trace(
            go.Scatter(x=arr, y=y_sort, mode='markers', marker=dict(size=6, opacity=0.55), showlegend=False),
            row=r, col=c)
    fig_s.update_layout(height=280 * n_r2, title_text='Elite: parameter vs fitness Sortino (normalized)', showlegend=False)
    sc_html = fig_s.to_html(include_plotlyjs=False, full_html=False, div_id='elite_scatter')
    sc_div, sc_script = extract_chart_html(sc_html)

    return info_html, hist_div, hist_script, sc_div, sc_script


def generate_html_dashboard(hof, best, best_params, best_fitness, param_keys, param_dict,
                            logbook, is_res, oos_res, trades_is, trades_oos,
                            html_path, diag_dir, current_gen=None, total_gen=None, 
                            is_final=False, auto_launch=False, is_periods=None, oos_periods=None,
                            in_sample=None, best_gen_found=None, pop=None,
                            csv_export_index=None, csv_export_total=None):

    if os.environ.get('TRADING_GA_NO_BROWSER', '').strip().lower() in ('1', 'true', 'yes', 'on'):
        auto_launch = False

    if is_final:
        try:
            _csv_phase_fp = os.path.join(diag_dir, 'csv_export_phase_start.txt')
            if os.path.exists(_csv_phase_fp):
                os.remove(_csv_phase_fp)
        except OSError:
            pass

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
            avg_pt = fitness[5] if len(fitness) > 5 else 0.0
            
            pareto_data.append({
                'index': i,
                'sortino': fitness[0],  # Normalized
                'max_dd': fitness[1],  # Normalized
                'profit_factor': fitness[2],  # Normalized
                'avg_trades_day': avg_trades_day,  # Raw/Normalized (as provided)
                'total_profit': total_profit,  # Normalized
                'avg_profit_trade': avg_pt,  # Raw/Normalized (as provided)
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
    _band_outer = 'rgba(33, 150, 243, 0.14)'
    _band_inner = 'rgba(33, 150, 243, 0.32)'
    # Row 1: population bands first (behind lines). Legacy checkpoints: mirror-estimated bounds when pop_* rows missing.
    _add_population_envelope_traces(
        fig_convergence, gens, logbook, 1, 1, 'avg_sortino', 'pop_min_sortino', 'max_sortino', 'pop_std_sortino',
        _band_outer, _band_inner, show_legend=True,
        legend_outer='Sortino pop range', legend_inner='Sortino avg±0.5σ')
    _add_population_envelope_traces(
        fig_convergence, gens, logbook, 1, 2, 'avg_dd', 'min_dd', 'pop_max_dd_norm', 'pop_std_dd',
        _band_outer, _band_inner, show_legend=True,
        legend_outer='DD pop range', legend_inner='DD avg±0.5σ', clamp_lo=0.0, clamp_hi=1.0)
    # Rows 2–3 (normalized fitness space)
    _add_population_envelope_traces(
        fig_convergence, gens, logbook, 2, 1, 'avg_pf', 'pop_min_pf', 'max_pf', 'pop_std_pf',
        _band_outer, _band_inner, show_legend=True,
        legend_outer='PF pop range', legend_inner='PF avg±0.5σ',
        clamp_lo=0.0, clamp_hi=1.0)
    _add_population_envelope_traces(
        fig_convergence, gens, logbook, 2, 2, 'pop_avg_trades_day', 'pop_min_trades_day', 'max_trades_day', 'pop_std_trades_day',
        _band_outer, _band_inner, show_legend=True,
        legend_outer='Trades pop range', legend_inner='Trades avg±0.5σ',
        clamp_lo=0.0, clamp_hi=None, avg_fallback_key='avg_trades_day')
    if 'avg_total_profit' in logbook.header:
        _add_population_envelope_traces(
            fig_convergence, gens, logbook, 3, 1, 'avg_total_profit', 'pop_min_total_profit', 'pop_max_total_profit', 'pop_std_total_profit',
            _band_outer, _band_inner, show_legend=True,
            legend_outer='PnL pop range', legend_inner='PnL avg±0.5σ',
            clamp_lo=0.0, clamp_hi=1.0)
    if 'avg_profit_per_trade' in logbook.header:
        _add_population_envelope_traces(
            fig_convergence, gens, logbook, 3, 2, 'pop_avg_profit_per_trade', 'pop_min_profit_per_trade', 'pop_max_profit_per_trade', 'pop_std_profit_per_trade',
            _band_outer, _band_inner, show_legend=True,
            legend_outer='PPT pop range', legend_inner='PPT avg±0.5σ',
            clamp_lo=None, clamp_hi=None, avg_fallback_key='avg_profit_per_trade')
    
    # Sortino (row 1, col 1) — normalized only (same y-scale as population bands; no dual-scale overlay)
    avg_sortino = logbook.select("avg_sortino")
    max_sortino = logbook.select("max_sortino")
    avg_sortino = [v if isinstance(v, (int, float)) and v > -500 and not np.isinf(v) else None for v in avg_sortino]
    max_sortino = [v if isinstance(v, (int, float)) and v > -500 and not np.isinf(v) else None for v in max_sortino]
    fig_convergence.add_trace(
        go.Scatter(x=gens, y=avg_sortino, name='Sortino avg (normalized)', line=dict(dash='dash', color='gray'), showlegend=True),
        row=1, col=1)
    fig_convergence.add_trace(
        go.Scatter(x=gens, y=max_sortino, name='Sortino max in pop (normalized)', line=dict(width=2, color='blue'), showlegend=True),
        row=1, col=1)

    # Drawdown (row 1, col 2) — normalized only. Best-in-population is max(f[1]) = pop_max_dd_norm, not min_dd.
    avg_dd = logbook.select("avg_dd")
    avg_dd = [v if isinstance(v, (int, float)) and not np.isinf(v) and v >= 0 and v <= 1 else None for v in avg_dd]
    fig_convergence.add_trace(
        go.Scatter(x=gens, y=avg_dd, name='DD avg (normalized)', line=dict(dash='dash', color='gray'), showlegend=True),
        row=1, col=2)
    if 'pop_max_dd_norm' in logbook.header:
        dd_max_norm = logbook.select("pop_max_dd_norm")
        dd_max_norm = [v if isinstance(v, (int, float)) and not np.isinf(v) and v >= 0 and v <= 1 else None for v in dd_max_norm]
        if any(v is not None for v in dd_max_norm):
            fig_convergence.add_trace(
                go.Scatter(x=gens, y=dd_max_norm, name='DD max in pop (normalized)', line=dict(width=2, color='blue'), showlegend=True),
                row=1, col=2)
    
    # Profit Factor (row 2, col 1)
    fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("avg_pf"), name='PF avg', line=dict(dash='dash'), showlegend=True), row=2, col=1)
    fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("max_pf"), name='PF best', line=dict(width=2), showlegend=True), row=2, col=1)
    
    # Avg Trades/Day (row 2, col 2) — use pop_avg_trades_day: logbook avg_trades_day is overwritten with best-individual actual in record()
    if 'pop_avg_trades_day' in logbook.header:
        fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("pop_avg_trades_day"), name='Trades pop avg', line=dict(dash='dash'), showlegend=True), row=2, col=2)
    else:
        fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("avg_trades_day"), name='Trades avg (logbook)', line=dict(dash='dash'), showlegend=True), row=2, col=2)
    fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("max_trades_day"), name='Trades pop max', line=dict(width=2), showlegend=True), row=2, col=2)
    
    # Total Profit (row 3, col 1)
    if 'avg_total_profit' in logbook.header:
        fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("avg_total_profit"), name='PnL avg', line=dict(dash='dash'), showlegend=True), row=3, col=1)
        if 'pop_max_total_profit' in logbook.header:
            fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("pop_max_total_profit"), name='PnL pop max', line=dict(width=2), showlegend=True), row=3, col=1)
        else:
            fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("avg_total_profit"), name='PnL best (fallback)', line=dict(width=2), showlegend=True), row=3, col=1)
    else:
        # Fallback: use zeros if logbook doesn't have it yet
        fig_convergence.add_trace(go.Scatter(x=gens, y=[0]*len(gens), name='Avg', line=dict(dash='dash'), showlegend=False), row=3, col=1)
        fig_convergence.add_trace(go.Scatter(x=gens, y=[0]*len(gens), name='Best', line=dict(width=2), showlegend=False), row=3, col=1)

    # Avg Profit Per Trade (row 3, col 2) — lines use population stats when available (avg_trades_day overwrite makes raw avg_* misleading)
    if 'pop_avg_profit_per_trade' in logbook.header:
        fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("pop_avg_profit_per_trade"), name='PPT pop avg', line=dict(dash='dash'), showlegend=True), row=3, col=2)
        fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("pop_max_profit_per_trade"), name='PPT pop max', line=dict(width=2), showlegend=True), row=3, col=2)
    elif 'avg_profit_per_trade' in logbook.header:
        fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("avg_profit_per_trade"), name='PPT avg', line=dict(dash='dash'), showlegend=True), row=3, col=2)
        fig_convergence.add_trace(go.Scatter(x=gens, y=logbook.select("avg_profit_per_trade"), name='PPT best (fallback)', line=dict(width=2), showlegend=True), row=3, col=2)
    else:
         # Fallback
        fig_convergence.add_trace(go.Scatter(x=gens, y=[0]*len(gens), name='Avg', line=dict(dash='dash'), showlegend=False), row=3, col=2)
        fig_convergence.add_trace(go.Scatter(x=gens, y=[0]*len(gens), name='Best', line=dict(width=2), showlegend=False), row=3, col=2)

    def _max_uc_y_series(logbook, key):
        try:
            raw = list(logbook.select(key))
        except Exception:
            return None
        out = []
        for v in raw:
            if isinstance(v, (int, float)) and np.isfinite(v):
                out.append(float(v))
            else:
                out.append(None)
        return out if any(x is not None for x in out) else None

    _uc_style = dict(width=2, color='darkorange', dash='dot')
    _uc_pairs = [
        ('max_uc_sortino', 'Sortino pop max (pre-cap ratio)', 1, 1),
        ('max_uc_dd', 'DD pop max ($ / NORM_DD_MAX)', 1, 2),
        ('max_uc_pf', 'PF pop max (pre-cap ratio)', 2, 1),
        ('max_uc_trades', 'Trades pop max (pre-cap ratio)', 2, 2),
        ('max_uc_pnl', 'PnL pop max (pre-cap ratio)', 3, 1),
        ('max_uc_ppt', 'PPT pop max (pre-cap ratio)', 3, 2),
    ]
    for _uk, _un, _r, _c in _uc_pairs:
        _ys = _max_uc_y_series(logbook, _uk)
        if _ys:
            fig_convergence.add_trace(
                go.Scatter(x=gens, y=_ys, name=_un, line=_uc_style, showlegend=True),
                row=_r, col=_c,
            )

    fig_convergence.update_layout(height=900, showlegend=True, title_text="Convergence Plots")
    fig_convergence.update_xaxes(title_text="Generation", row=1, col=1)
    fig_convergence.update_xaxes(title_text="Generation", row=1, col=2)
    fig_convergence.update_xaxes(title_text="Generation", row=2, col=1)
    fig_convergence.update_xaxes(title_text="Generation", row=2, col=2)
    fig_convergence.update_xaxes(title_text="Generation", row=3, col=1)
    fig_convergence.update_xaxes(title_text="Generation", row=3, col=2)
    # Row 1: normalized bands + lines; y-axis autoranges so pre-cap ratio traces can exceed 1.0.
    fig_convergence.update_yaxes(title_text="Sortino (normalized + pre-cap max)", row=1, col=1, autorange=True)
    fig_convergence.update_yaxes(title_text="Drawdown (normalized + pre-cap max)", row=1, col=2, autorange=True)
    fig_convergence.update_yaxes(title_text="Profit Factor (normalized 0-1)", row=2, col=1)
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
            # Format fitness values (Frequency and Profit/Trade are already raw units in the 6-tuple)
            # Use raw format for Trades/Day and Profit/Trade even if others are normalized
            pareto_table_html += f"<tr class='{'selected-row' if sol['is_selected'] else ''}'><td>{rank}</td><td>{generation}</td><td>{sol['sortino']:.4f}</td><td>{sol['max_dd']:.2f}</td><td>{sol['profit_factor']:.4f}</td><td>{avg_trades:.3f}</td><td>{total_profit:.4f}</td><td>${ppt:,.2f}</td><td>{mark}</td></tr>"

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
            'Fitness Weights': [],
            'Hard Limits & Constraints': [],
            'Normalization Ranges': [],
            'Other': []
        }
        
        # Define parameter groups
        entry_params = ['Enable Long Trades', 'Enable Short Trades', 'Bollinger Band Length', 
                        'Bollinger Band StdDev', 'Long Entry on Wick Touch', 'Long Entry on Body in Zone',
                        'Long Trigger (% From Lower Band)', 'Short Entry on Wick Touch', 
                        'Short Entry on Body in Zone', 'Short Trigger (% From Upper Band)',
                        'ATR Length for Filter', 'Max ATR Filter (Points)', 'Min ATR Filter (Points)', 
                        'Enable Trend Filter', 'Trend EMA Length',
                        'Enable ADX Filter', 'ADX Period', 'Min ADX Threshold', 'Max ADX Threshold',
                        'RTH Start (HH:MM)', 'RTH End (HH:MM)',
                        'Enable RTH Filter', 'Volume MA Length', 'Max Volume Multiplier', 'Timeframe (minutes)',
                        'Max Open Trades', 'RTH Exit Buffer (minutes)', 'Enable Maintenance Filter',
                        'Daily Maintenance Start (HH:MM)', 'Daily Maintenance End (HH:MM)',
                        'Weekend Maintenance Start Day', 'Weekend Maintenance Start Time (HH:MM)',
                        'Weekend Maintenance End Day', 'Weekend Maintenance End Time (HH:MM)',
                        'Maintenance Buffer Minutes', 'Transaction Cost (Per Trade)',
                        'Enable RSI Filter', 'RSI Period', 'RSI Overbought', 'RSI Oversold',
                        'Enable VWAP Filter']
        
        tp_params = ['TP Method', 'Opposite Bollinger Band TP', 'Fixed ATR TP', 'Fixed BB at Entry TP',
                    'ATR Length for TP', 'ATR Multiplier for TP']
        
        sl_params = ['Initial Stop Loss (%)', 'Enable Trailing Stop', 
                     'ATR Length for Trailing Stop', 'ATR Multiplier for Trailing Stop',
                     'Trailing Delay (bars)']
        
        ga_params = ['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                     'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                     'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                     'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT', 'GA_START_DATE', 'GA_END_DATE',
                     'GA_LIVE_STYLE_ENTRY', 'GA_CONSERVATIVE_STOP_SLIPPAGE', 'GA_CONSERVATIVE_ENTRY_SLIPPAGE', 'GA_CONSERVATIVE_CHANNEL_SLIPPAGE', 'GA_PESSIMISTIC_STOPS',
                     'ENABLE_FILTER_STACK_TRADE_PENALTY', 'INTERACTION_PENALTY_STRENGTH',
                     'INTERACTION_LOW_TRADES_BASE', 'INTERACTION_LOW_TRADES_PER_FILTER',
                     'INTERACTION_MIN_FILTERS']
        
        fitness_weights = ['WEIGHT_SORTINO', 'WEIGHT_DRAWDOWN', 'WEIGHT_PF', 'WEIGHT_TRADES', 'WEIGHT_PNL', 'WEIGHT_PPT']
        
        limits_params = ['MIN_TRADE_DURATION', 'MAX_WIN_RATE_CAP', 'LIMIT_MAX_LOSS', 'LIMIT_MIN_SORTINO',
                         'MIN_WIN_RATE', 'SORTINO_CAP']
                         
        norm_params = ['NORM_SORTINO_MAX', 'NORM_DD_MAX', 'NORM_PF_MAX', 'NORM_TRADES_MAX', 
                       'NORM_PNL_MAX', 'NORM_PROFIT_TRADE_MAX']
        
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
            elif pname in fitness_weights:
                groups['Fitness Weights'].append(pname)
            elif pname in limits_params:
                groups['Hard Limits & Constraints'].append(pname)
            elif pname in norm_params:
                groups['Normalization Ranges'].append(pname)
            else:
                # Default to Other if not found
                groups['Other'].append(pname)
        
        return groups
    
    param_groups = group_parameters(param_keys, param_dict)
    
    # Determine which parameters are optimizable
    # Parameters in param_keys are optimizable (they were used to build PARAM_RANGES)
    # Also check for parameters that have min/max and are int/float, but exclude:
    # 1. GA Criteria parameters
    # 2. Parameters where min==max (effectively fixed)
    optimizable_params = set(param_keys)  # Start with known optimizable params
    for pname, pdata in param_dict.items():
        if pname.startswith('===') or pname.startswith('__'):
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
    _dash_tf = 15.0
    try:
        if isinstance(best_params, dict) and best_params.get('Timeframe (minutes)') is not None:
            _dash_tf = float(max(1, int(round(best_params['Timeframe (minutes)']))))
        elif param_dict and 'Timeframe (minutes)' in param_dict:
            _dash_tf = float(max(1, int(round(param_dict['Timeframe (minutes)']['value']))))
    except Exception:
        _dash_tf = 15.0

    required_keys = [
        'sortino',
        'max_drawdown',
        'avg_trades_day',
        'profit_factor',
        'total_profit',
        'avg_profit_per_trade',
        'avg_trade_duration_min',
    ]
    for key in required_keys:
        if key not in is_res:
             # Try to calculate if missing
             if key == 'avg_profit_per_trade':
                 tp = is_res.get('total_profit', 0)
                 count = len(trades_is) if 'trades_is' in locals() else 0
                 is_res[key] = tp / count if count > 0 else 0
             elif key == 'avg_trade_duration_min':
                 is_res[key] = _mean_trade_duration_minutes(trades_is, bar_minutes=_dash_tf)
             else:
                 is_res[key] = 0
        if key not in oos_res:
             if key == 'avg_profit_per_trade':
                 tp = oos_res.get('total_profit', 0)
                 count = len(trades_oos) if 'trades_oos' in locals() else 0
                 oos_res[key] = tp / count if count > 0 else 0
             elif key == 'avg_trade_duration_min':
                 oos_res[key] = _mean_trade_duration_minutes(trades_oos, bar_minutes=_dash_tf)
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
        ('avg_trade_duration_min', 'Avg Trade Duration (min, bar-span)', False),
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
        elif metric_key == 'avg_trade_duration_min':
            is_str = f"{is_val:.2f}"
            oos_str = f"{oos_val:.2f}"
            diff_str = f"{diff:+.2f} ({diff_pct:+.1f}%)"
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
    conv_html = fig_convergence.to_html(include_plotlyjs=False, full_html=False, div_id='conv_chart')
    pareto3d_html = fig_pareto_3d.to_html(include_plotlyjs=False, full_html=False, div_id='pareto3d_chart')
    pareto2d_html = fig_pareto_2d.to_html(include_plotlyjs=False, full_html=False, div_id='pareto2d_chart')
    paretosize_html = fig_pareto_size.to_html(include_plotlyjs=False, full_html=False, div_id='paretosize_chart')
    
    # Extract div and script from each chart (extract_chart_html is defined earlier)
    conv_div, conv_script = extract_chart_html(conv_html)
    pareto3d_div, pareto3d_script = extract_chart_html(pareto3d_html)
    pareto2d_div, pareto2d_script = extract_chart_html(pareto2d_html)
    paretosize_div, paretosize_script = extract_chart_html(paretosize_html)
    
    try:
        elite_info_html, elite_hist_div, elite_hist_script, elite_sc_div, elite_sc_script = generate_elite_parameter_insight_html(
            hof, param_keys, param_dict, max_individuals=400)
    except Exception as _elite_e:
        print(f"  Warning: elite parameter insight charts failed: {_elite_e}")
        traceback.print_exc()
        elite_info_html = ''
        elite_hist_div = elite_hist_script = elite_sc_div = elite_sc_script = ''
    
    # Progress information with time tracking (GA generations + optional CSV export phase)
    progress_html = ""
    show_ga = current_gen is not None and total_gen is not None and total_gen > 0
    show_csv = csv_export_total is not None and int(csv_export_total) > 0
    if show_ga or show_csv:
        ga_pct = min(100.0, (current_gen / total_gen * 100)) if show_ga else 0.0
        csv_idx = int(csv_export_index) if csv_export_index is not None else 0
        csv_tot = int(csv_export_total) if csv_export_total is not None else 0
        csv_pct = min(100.0, (csv_idx / csv_tot * 100)) if show_csv and csv_tot > 0 else 0.0

        if is_final:
            status = "COMPLETE"
            status_color = "#4CAF50"
        elif show_csv:
            status = "POST-GA EXPORT"
            status_color = "#FFB74D"
        else:
            status = "IN PROGRESS"
            status_color = "#FF9800"

        if show_ga and show_csv:
            combined_pct = (ga_pct + csv_pct) / 2.0
            headline = (
                f"{status} — GA {current_gen}/{total_gen} ({ga_pct:.1f}%) · "
                f"CSV rows {csv_idx}/{csv_tot} ({csv_pct:.1f}%) · "
                f"overall ~{combined_pct:.1f}%"
            )
        elif show_csv:
            combined_pct = csv_pct
            headline = f"{status} — building solution CSV rows {csv_idx}/{csv_tot} ({csv_pct:.1f}%)"
        else:
            combined_pct = ga_pct
            headline = f"{status} - Generation {current_gen}/{total_gen} ({ga_pct:.1f}%)"

        elapsed_time_str = "N/A"
        predicted_completion_str = "N/A"

        start_time = None
        START_TIME_FILE = os.path.join(diag_dir, 'ga_start_time.txt')
        if os.path.exists(START_TIME_FILE):
            try:
                with open(START_TIME_FILE, 'r') as f:
                    start_time = float(f.read().strip())
            except Exception:
                pass

        if start_time is not None:
            elapsed_seconds = time.time() - start_time
            elapsed_td = timedelta(seconds=int(elapsed_seconds))
            hours, remainder = divmod(elapsed_td.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            elapsed_time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            if elapsed_td.days > 0:
                elapsed_time_str = f"{elapsed_td.days}d {elapsed_time_str}"

            if not is_final:
                if show_csv and csv_tot > 0 and csv_idx > 0:
                    csv_phase_start = None
                    CSV_PHASE_START_FILE = os.path.join(diag_dir, 'csv_export_phase_start.txt')
                    if os.path.exists(CSV_PHASE_START_FILE):
                        try:
                            with open(CSV_PHASE_START_FILE, 'r') as f:
                                csv_phase_start = float(f.read().strip())
                        except Exception:
                            csv_phase_start = None
                    if csv_phase_start is not None:
                        elapsed_csv = max(0.0, time.time() - csv_phase_start)
                        rate = elapsed_csv / float(csv_idx)
                        remaining = rate * max(0, csv_tot - csv_idx)
                        predicted_completion = datetime.now() + timedelta(seconds=int(remaining))
                        predicted_completion_str = predicted_completion.strftime('%Y-%m-%d %H:%M:%S')
                elif show_ga and current_gen > 0 and (not show_csv or csv_idx == 0):
                    remaining_gens = total_gen - current_gen
                    if remaining_gens > 0:
                        avg_time_per_gen = elapsed_seconds / float(current_gen)
                        predicted_seconds = avg_time_per_gen * remaining_gens
                        predicted_completion = datetime.now() + timedelta(seconds=int(predicted_seconds))
                        predicted_completion_str = predicted_completion.strftime('%Y-%m-%d %H:%M:%S')

        ga_bar_color = "#4CAF50" if (show_csv and csv_idx >= csv_tot) else ("#81C784" if is_final else "#2196F3")
        csv_bar_color = "#FFB74D" if (show_csv and csv_idx < csv_tot) else "#4CAF50"

        ga_bar_block = ""
        if show_ga:
            ga_bar_block = f"""
            <div style="margin-top: 12px; text-align: left; font-size: 0.82em; color: #ccc;">GA (generations)</div>
            <div style="width: 100%; background-color: #555; height: 8px; border-radius: 4px; overflow: hidden;">
                <div style="width: {ga_pct:.4f}%; background-color: {ga_bar_color}; height: 100%;"></div>
            </div>"""

        csv_bar_block = ""
        if show_csv:
            csv_bar_block = f"""
            <div style="margin-top: 10px; text-align: left; font-size: 0.82em; color: #ccc;">CSV export (per-solution backtests / rows)</div>
            <div style="width: 100%; background-color: #555; height: 8px; border-radius: 4px; overflow: hidden;">
                <div style="width: {csv_pct:.4f}%; background-color: {csv_bar_color}; height: 100%;"></div>
            </div>"""

        footnote = ""
        if show_ga and show_csv:
            footnote = (
                "<div style=\"margin-top: 8px; font-size: 0.78em; color: #bbb;\">"
                "Overall % is the average of GA completion and CSV row completion. "
                "Refresh cadence: TRADING_GA_DASH_CSV_PROGRESS_EVERY (default 10).</div>"
            )

        progress_html = f"""
        <div style="background-color: #333; color: white; padding: 15px; text-align: center; margin-bottom: 20px; border-radius: 5px;">
            <h2 style="margin: 0; color: {status_color}; font-size: 1.15em;">{headline}</h2>
            <div style="margin-top: 10px; font-size: 0.9em;">
                <span>Elapsed (run): {elapsed_time_str}</span> |
                <span>Est. completion: {predicted_completion_str}</span>
            </div>
            {ga_bar_block}
            {csv_bar_block}
            {footnote}
        </div>
        """
    fitness_weights_html = (
        "<h2>Fitness Function Configuration</h2><div class='info-section'>"
        "<table class='params-table'><thead><tr><th>Objective</th>"
        "<th>MO weight<span class='tooltip-icon'>?</span><span class='tooltip'>"
        "DEAP multi-objective scalar weight (not the normalization divisor). "
        "The divisor used in <code>core_evaluate</code> is the next column.</span></th>"
        "<th>Direction</th>"
        "<th>Norm. divisor<br/><span style='font-weight:normal;font-size:0.85em;color:#666'>"
        "(CSV <code>Value</code> column)</span></th><th>Notes</th></tr></thead><tbody>"
    )
    
    # Get weights from creator.FitnessMulti
    from deap import creator
    if hasattr(creator, 'FitnessMulti'):
        weights = creator.FitnessMulti.weights
        weight_names = ['Sortino Ratio', 'Max Drawdown', 'Profit Factor', 'Avg Trades/Day', 'Total Profit', 'Avg Profit/Trade']
        directions = ['Maximize', 'Minimize', 'Maximize', 'Maximize', 'Maximize', 'Maximize']
        
        # Reload PARAM_CSV from disk so mid-run edits to NORM_* show in the dashboard.
        # (In-memory param_dict and worker processes still hold the snapshot from run start.)
        param_dict_norm = param_dict
        try:
            param_dict_norm, _ = load_params(PARAM_CSV, return_dataframe=True)
        except Exception:
            pass

        # Get normalization ranges from freshly loaded dict with safety check
        def get_p_val(key, default):
            item = param_dict_norm.get(key)
            if isinstance(item, dict):
                return item.get('value', default)
            return default

        norm_keys = [
            'NORM_SORTINO_MAX',
            'NORM_DD_MAX',
            'NORM_PF_MAX',
            'NORM_TRADES_MAX',
            'NORM_PNL_MAX',
            'NORM_PROFIT_TRADE_MAX',
        ]

        def format_norm_cell(norm_key: str, fallback):
            """Show active divisor (CSV Value column) used in core_evaluate."""
            v = get_p_val(norm_key, fallback)
            if isinstance(v, float):
                v_str = f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.4g}"
            else:
                v_str = str(v)
            return f"<strong>{v_str}</strong>"
        
        notes = [
            '<strong>Constraint:</strong> Maximize. Penalized if < LIMIT_MIN_SORTINO.',
            '<strong>Constraint:</strong> Minimize. Penalty: Geometric increase if DD > LIMIT_MAX_LOSS.',
            '<strong>Constraint:</strong> Maximize. Penalty: Small linear penalty if < 1.0.',
            '<strong>Graduated Soft Constraint:</strong> Substantial reduction if < MIN_TRADES_DAY. Soft Constraint: Penalty if trades > TARGET_TRADES_DAY.',
            '<strong>Goal:</strong> Maximize Profit ($). No Floor.',
            '<strong>Goal:</strong> Maximize Profit Per Trade. Penalized if WinRate < MAX_WIN_RATE_CAP or Duration < MIN_TRADE_DURATION.'
        ]
        
        default_norms = [10.0, 100000.0, 5.0, 3.0, 200000.0, 250.0]
        for i, (name, weight, direction, note, nk, fb) in enumerate(
            zip(weight_names, weights, directions, notes, norm_keys, default_norms)
        ):
            norm_range_str = format_norm_cell(nk, fb)
            
            weight_str = f"{weight:.1f}"
            if weight == 100.0:
                weight_str = f"<strong style='color: red; font-size: 1.1em;'>{weight:.1f} (!) DIAGNOSTIC</strong>"
            elif abs(weight) > 10:
                weight_str = f"<strong>{weight:.1f}</strong>"
            
            fitness_weights_html += f"<tr><td>{name}</td><td>{weight_str}</td><td>{direction}</td><td>{norm_range_str}</td><td>{note}</td></tr>"
    
    fitness_weights_html += (
        "</tbody></table>"
        "<p><em>Weights influence selection pressure.</em></p>"
        "<p><em>Trade scores are normalized.</em></p>"
        "<p style=\"font-size:0.88em;color:#666;margin-top:10px;\"><strong>Not hardcoded:</strong> each "
        "<code>NORM_*</code> row uses the <strong>Value</strong> column as the divisor in "
        "<code>core_evaluate</code>. Changing only <strong>Min</strong> or <strong>Max</strong> on that row "
        "does not change fitness or this table — update <strong>Value</strong>, save the same file passed as "
        "<code>--params</code> / default trend CSV, then start (or restart) the GA.</p>"
        "<p style=\"font-size:0.88em;color:#666;\">Dashboard numbers are re-read from <code>PARAM_CSV</code> when "
        "the HTML is rebuilt. If you edit the CSV <em>during</em> a run, refresh shows new Values, but worker "
        "processes still use the snapshot from pool start until you restart.</p>"
        "</div>"
    )
    
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
    # plotly-latest.min.js is frozen at plotly.js v1.x; Python plotly 3.x emits v2/v3 figure JSON — use versioned CDN.
    html_content += f"<script src='{plotly_cdn_url()}' charset='utf-8'></script>\n"
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
    html_content += (
        "<div class='info-section' style='font-size:0.88em'>"
        "<strong>Bands:</strong> light fill = population min–max per generation (normalized fitness); "
        "darker fill = mean ± 0.5×std. "
        "<strong>Sortino / Drawdown (row 1):</strong> solid/dashed lines and fills use the <strong>normalized fitness</strong> scale "
        "(solid = best in evaluated population that generation; dashed = population mean). "
        "<strong>Orange dotted</strong> traces (when present) show <code>max_uc_*</code>: the largest "
        "<em>pre-cap</em> ratio (raw metric ÷ CSV <code>NORM_*</code> divisor) among offspring that generation — "
        "values may exceed 1.0; they are <strong>not</strong> used by NSGA-II (selection still uses capped fitness). "
        "Actual Sortino and drawdown in dollars appear in Performance Metrics and elsewhere — not on this chart. "
        "<strong>Legacy checkpoints</strong> (no per-gen <code>pop_*</code> or <code>max_uc_*</code>) omit dotted lines until you run with a current build. "
        "Approximate bands still apply when <code>pop_*</code> is missing."
        "</div>\n")
    html_content += f"{conv_div}\n"
    if elite_info_html:
        html_content += "<h2>Elite parameter range pressure</h2>\n"
        html_content += elite_info_html
        if elite_hist_div:
            html_content += f"<h3>Histograms (highest boundary pressure)</h3>\n{elite_hist_div}\n"
        if elite_sc_div:
            html_content += f"<h3>Parameter vs fitness Sortino (top pressure params)</h3>\n{elite_sc_div}\n"
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
        
    # Add individual IS period statistics if we have best_params
    if best_params and is_periods and len(is_periods) > 0:
            html_content += ' <h2>Individual In-Sample Period Statistics<span class="tooltip-icon">?</span> <span class="tooltip">Average holding time in minutes, counting whole bars (inclusive): entry and exit in the same candle count as one bar times your Timeframe (minutes). Matches the GA backtest clock; avoids sub-minute artifacts from fill-at-open vs end-of-bar exit timestamps.</span> </h2> <div class="info-section"> <strong>Per-slice trade duration:</strong> Values are bar-aligned (minimum one bar of exposure per trade). Compare across IS periods; chronically low averages (near one bar) still mean very fast exits in signal space. </div> '
            is_period_stats_html = "<table class='oos-periods-table'><thead><tr> <th>Period #</th> <th>Date Range</th> <th>Total PNL</th> <th>Trades</th> <th>Win Rate</th> <th>Profit Factor</th> <th>Sortino</th> <th>Max DD</th> <th>Avg Trades/Day</th> <th>Avg Profit/Trade</th> <th>Avg Span (min)</th> </tr></thead><tbody>"
            for i, is_period in enumerate(is_periods, 1):
                try:
                    period_res = run_backtest(best_params, is_period, param_dict, suppress_output=True)
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
                        avg_trades_day = period_res.get('avg_trades_day', 0)
                        if avg_trades_day == 0 and num_trades > 0:
                            period_start = is_period.index.min()
                            period_end = is_period.index.max()
                            days = (period_end - period_start).days or 1
                            avg_trades_day = num_trades / days if days > 0 else 0
                        avg_profit_trade = total_pnl / num_trades if num_trades > 0 else 0
                        avg_dur = float(period_res.get('avg_trade_duration_min', 0.0))
                        is_period_stats_html += f"<tr> <td>{i}</td> <td>{is_period.index[0].strftime('%Y-%m-%d')} to {is_period.index[-1].strftime('%Y-%m-%d')}</td> <td class=\"{'positive' if total_pnl > 0 else 'negative'}\">${total_pnl:,.2f}</td> <td>{num_trades}</td> <td>{win_rate:.1f}%</td> <td>{pf:.2f}</td> <td>{sortino:.2f}</td> <td>${max_dd:,.2f}</td> <td>{avg_trades_day:.2f}</td> <td class=\"{'positive' if avg_profit_trade > 0 else 'negative'}\">${avg_profit_trade:,.2f}</td> <td>{avg_dur:.2f}</td> </tr>"
                    else:
                        is_period_stats_html += f"<tr> <td>{i}</td> <td>{is_period.index[0].strftime('%Y-%m-%d')} to {is_period.index[-1].strftime('%Y-%m-%d')}</td> <td colspan=\"9\" style=\"text-align: center; color: #999;\">No trades</td> </tr>"
                except Exception as e:
                    is_period_stats_html += f"<tr> <td>{i}</td> <td>{is_period.index[0].strftime('%Y-%m-%d')} to {is_period.index[-1].strftime('%Y-%m-%d')}</td> <td colspan=\"9\" style=\"text-align: center; color: #f00;\">Error: {str(e)}</td> </tr>"
            is_period_stats_html += "</tbody></table>"
            html_content += is_period_stats_html

    # Add individual OOS period statistics if we have best_params
    if best_params and oos_periods and len(oos_periods) > 0:
            html_content += ' <h2>Individual OOS Period Statistics<span class="tooltip-icon">?</span> <span class="tooltip">Performance statistics for each individual Out-of-Sample period. Avg Span (min) = average trade length in minutes on the bar grid (inclusive whole bars times Timeframe minutes), not raw seconds between timestamps; same convention as the GA CSV.</span> </h2> <div class="info-section"> <strong>Period-by-Period Analysis:</strong> If performance varies significantly across OOS periods, the strategy may be overfitted to the training data. Consistent performance across periods is a good sign of robustness. </div> '
            
            oos_period_stats_html = "<table class='oos-periods-table'><thead><tr> <th>Period #</th> <th>Date Range</th> <th>Total PNL</th> <th>Trades</th> <th>Win Rate</th> <th>Profit Factor</th> <th>Sortino</th> <th>Max DD</th> <th>Avg Trades/Day</th> <th>Avg Profit/Trade</th> <th>Avg Span (min)</th> </tr></thead><tbody>"
            
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
                        avg_dur = float(period_res.get('avg_trade_duration_min', 0.0))

                        oos_period_stats_html += f"<tr> <td>{i}</td> <td>{oos_period.index[0].strftime('%Y-%m-%d')} to {oos_period.index[-1].strftime('%Y-%m-%d')}</td> <td class=\"{'positive' if total_pnl > 0 else 'negative'}\">${total_pnl:,.2f}</td> <td>{num_trades}</td> <td>{win_rate:.1f}%</td> <td>{pf:.2f}</td> <td>{sortino:.2f}</td> <td>${max_dd:,.2f}</td> <td>{avg_trades_day:.2f}</td> <td class=\"{'positive' if avg_profit_trade > 0 else 'negative'}\">${avg_profit_trade:,.2f}</td> <td>{avg_dur:.2f}</td> </tr>"
                    else:
                        oos_period_stats_html += f"<tr> <td>{i}</td> <td>{oos_period.index[0].strftime('%Y-%m-%d')} to {oos_period.index[-1].strftime('%Y-%m-%d')}</td> <td colspan=\"9\" style=\"text-align: center; color: #999;\">No trades</td> </tr>"
                except Exception as e:
                    oos_period_stats_html += f"<tr> <td>{i}</td> <td>{oos_period.index[0].strftime('%Y-%m-%d')} to {oos_period.index[-1].strftime('%Y-%m-%d')}</td> <td colspan=\"9\" style=\"text-align: center; color: #f00;\">Error: {str(e)}</td> </tr>"
            
            oos_period_stats_html += "</tbody></table>"
            html_content += oos_period_stats_html
    
    html_content += ' <h2>In-Sample vs OOS Comparison<span class="tooltip-icon">?</span> <span class="tooltip">Comparison of strategy performance between in-sample (training) and out-of-sample (validation) data. This is critical for detecting overfitting. Good generalization: IS and OOS metrics are similar. Overfitting: IS is much better than OOS. Green differences indicate OOS is better (good sign), red indicates OOS is worse (potential overfitting).</span> </h2> <div class="info-section"> <strong>Overfitting Detection:</strong> If OOS performance is significantly worse than IS, the strategy may be overfitted to the training data. Look for: (1) Sortino dropping >50% in OOS, (2) Drawdown increasing >100% in OOS, (3) Trade frequency dropping dramatically. Small differences (<20%) are normal and acceptable. </div> '
    html_content += comparison_html
    html_content += summary_html
    
    html_content += ' </div> <h2>Parameter Analysis & Convergence<span class="tooltip-icon">?</span> <span class="tooltip">Analysis of how strategy parameters affect performance metrics. Includes both Convergence Stability (consensus) and Correlation Analysis (impact).</span> </h2> <div class="info-section"> <strong>Understanding Parameter Analysis:</strong> <ul> <li><strong>Convergence Analysis:</strong> Shows which parameters the GA has "agreed" on (Low Variance) vs. which are still debated (High Variance). Converged parameters are likely critical "Structural Edges".</li> <li><strong>Correlation Heatmap:</strong> Shows how each parameter correlates with each metric. Positive (blue) = parameter increases with metric, Negative (red) = parameter decreases with metric.</li> <li><strong>Parameter Importance:</strong> Combines correlation, top-bottom difference, range utilization, and variability to identify the most important parameters.</li> <li><strong>Parameter Distributions (Top vs Bottom):</strong> Compares parameter values in top 25% vs bottom 25% solutions. Shows which parameters distinguish good from bad solutions.</li> <li><strong>Parameter Interactions:</strong> 2D scatter plots showing how top parameters interact. Color = Sortino (darker = better). Helps identify parameter combinations that work together.</li> <li><strong>Parameter Distribution Histograms:</strong> Shows distribution of all parameter values with valid ranges marked. <strong style="color: red;">Red bars = values OUTSIDE valid range</strong>, Blue bars = values within range. Green/Red dashed lines = min/max boundaries. Use this to detect parameter clamping issues!</li> <li><strong>Focus on High-Importance Parameters:</strong> These are the parameters that most distinguish good solutions from bad ones.</li> </ul> <strong>Note:</strong> GA meta-parameters (POP_SIZE, NUM_GEN, etc.) are excluded from this analysis as they control the optimization algorithm, not the trading strategy. </div> <div class="chart-container"> '
    if param_conv_html:
        html_content += f"<h3>Convergence Analysis</h3>{param_conv_html}<hr>"
    html_content += "<h3>Correlation & Importance Analysis</h3>"
    html_content += param_analysis_html
    html_content += ' </div> '
    html_content += conv_script + ' ' + pareto3d_script + ' ' + pareto2d_script + ' ' + paretosize_script + ' '
    html_content += (elite_hist_script + ' ' + elite_sc_script + ' ').strip() + ' '
    html_content += param_analysis_scripts
    
    # All Solutions Table (Moved to bottom)
    html_content += ' <h2>All Solutions<span class="tooltip-icon">?</span> <span class="tooltip">Complete list of all Pareto-optimal solutions ranked by Sortino Ratio.</span> </h2> <div class="info-section"> '
    if showing_actual:
        html_content += '<strong> This table shows ACTUAL BACKTEST RESULTS from fresh backtests of each solution.</strong>'
    else:
        html_content += '<strong>(!) IMPORTANT: This table shows NORMALIZED FITNESS VALUES, not actual backtest results!</strong>'
    html_content += '</div>'
    html_content += pareto_table_html
    
    html_content += ' </body></html>'

    primary = os.path.abspath(os.path.normpath(html_path))
    written_path = primary
    try:
        _atomic_write_utf8(primary, html_content)
    except OSError as e:
        fb = os.path.abspath(os.path.join(diag_dir, 'html', 'ga_dashboard_v4.html'))
        try:
            _atomic_write_utf8(fb, html_content)
            written_path = fb
            print(f"  NOTE: GA dashboard written to {written_path} (web path failed: {e})")
        except OSError as e2:
            raise OSError(
                f"Failed to write dashboard to {primary!r} and fallback {fb!r}: {e!r}; {e2!r}"
            ) from e2

    # Auto-launch only if requested (first update or final update)
    if auto_launch:
        try:
            import urllib.request
            import urllib.error
            from pathlib import Path
            web_url = None
            try:
                urllib.request.urlopen('http://127.0.0.1:8000/', timeout=1)
                web_root = os.path.normcase(
                    os.path.abspath(os.path.normpath(os.path.join(os.getcwd(), 'web')))
                )
                if os.path.normcase(os.path.dirname(written_path)) == web_root:
                    web_url = f"http://127.0.0.1:8000/{os.path.basename(written_path)}"
            except (urllib.error.URLError, OSError, Exception):
                pass
            if not web_url:
                web_url = Path(written_path).resolve().as_uri()
            webbrowser.open(web_url)
        except Exception:
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

def build_ga_training_bundle(
    param_dict,
    *,
    ga_start_date,
    ga_end_date,
    data_splits,
    data_size,
    use_interleaved,
    num_periods,
    data_csv=None,
    verbose=True,
):
    """
    Load ES 1m data and build (in_sample, oos, is_mask, is_periods, oos_periods) exactly as the GA uses.
    Import this from tools (or notebooks) to replay `run_backtest(params, in_sample, ..., mask=is_mask)`.
    """
    if data_csv is None:
        data_csv = os.environ.get(
            'TRADING_DATA_CSV',
            'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv',
        )

    if verbose:
        print(f"Loading OHLC CSV: {data_csv}")
    if not os.path.isfile(data_csv):
        raise FileNotFoundError(
            f"GA data CSV not found: {data_csv!r}. "
            "Place the file under Bollinger/data, pass --data-csv, or set TRADING_DATA_CSV."
        )

    df = pd.read_csv(data_csv, header=None, names=['datetime', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['datetime'])
    if df['datetime'].dt.tz is None:
        df['datetime'] = df['datetime'].dt.tz_localize('UTC').dt.tz_convert('US/Eastern').dt.tz_localize(None)
    else:
        df['datetime'] = df['datetime'].dt.tz_convert('US/Eastern').dt.tz_localize(None)
    df.set_index('datetime', inplace=True)

    if verbose:
        print(f"\n=== Slicing Data Range: {ga_start_date} to {ga_end_date} ===")
    original_size = len(df)
    df = df.loc[ga_start_date:ga_end_date]
    if verbose:
        print(f"Data range sliced: {original_size} -> {len(df)} rows")

    if data_size > 0:
        df = df.tail(int(data_size))
        if verbose:
            print(f"Applied DATA_SIZE tail: {len(df)} rows")

    if use_interleaved and num_periods > 1:
        if verbose:
            print(f"\n=== Using Interleaved Data Split ===")
            print(f"Number of periods: {num_periods}")
        df = df.sort_index()
        period_size = len(df) // num_periods
        is_periods = []
        oos_periods = []
        is_mask = pd.Series(False, index=df.index)

        for i in range(num_periods):
            start_idx = i * period_size
            end_idx = (i + 1) * period_size if i < num_periods - 1 else len(df)
            if i % 2 == 0:
                is_mask.iloc[start_idx:end_idx] = True
                period = df.iloc[start_idx:end_idx]
                is_periods.append(period)
                if verbose:
                    print(f"  Period {i+1}: IS ({len(period):,} rows, {period.index[0]} to {period.index[-1]})")
            else:
                period = df.iloc[start_idx:end_idx]
                oos_periods.append(period)
                if verbose:
                    print(f"  Period {i+1}: OOS ({len(period):,} rows, {period.index[0]} to {period.index[-1]})")

        in_sample = df.copy()
        oos = df[~is_mask]
        if verbose:
            print(f"\nIS Mask coverage: {is_mask.sum():,} rows ({is_mask.sum()/len(df)*100:.1f}%)")
            print("=" * 50)
    else:
        split = int(len(df) * float(data_splits))
        is_mask = pd.Series(False, index=df.index)
        is_mask.iloc[:split] = True
        in_sample = df.copy()
        oos = df.iloc[split:]
        is_periods = [df.iloc[:split]] if split > 0 else []
        oos_periods = [df.iloc[split:]] if split < len(df) else []
        if verbose:
            print(f"\n=== Using Simple Chronological Split ===")
            print(f"IS: {is_mask.sum()} rows ({is_mask.sum()/len(df)*100:.1f}%)")
            print(f"OOS: {len(oos)} rows ({len(oos)/len(df)*100:.1f}%)")
            print("=" * 50)

    return in_sample, oos, is_mask, is_periods, oos_periods


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
    
    # Parameters will be loaded below, and FitnessMulti recreated if weights changed
    global TARGET_TRADES_DAY, TRADES_PENALTY_WEIGHT, DD_WEIGHT
    global DATA_SPLITS, DATA_SIZE, MIN_TRADES_DAY, MIN_TRADES_PEN_WEIGHT
    global GA_START_DATE, GA_END_DATE, WEIGHT_SORTINO, WEIGHT_DRAWDOWN, WEIGHT_PF, WEIGHT_TRADES, WEIGHT_PNL, WEIGHT_PPT
    global MIN_TRADE_DURATION, MAX_WIN_RATE_CAP, LIMIT_MAX_LOSS, LIMIT_MIN_SORTINO
    global PARAM_RANGES, param_keys, param_dict, param_df
    
    print("# Genetic Optimization for Bollinger Band Strategy - Version 3.0")
    print("# Multi-core parallelization | Multi-objective (NSGA-II) | Sortino Ratio")
    print("# Checkpoint/Resume enabled - saves after each generation")
    print("# Use --fresh or -f flag to force a fresh start (ignores checkpoint)")

    if args.seed is not None:
        random.seed(args.seed)
        np.random.seed(args.seed)
        print(f"Random seed fixed to {args.seed}")

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
                               'Enable ADX Filter', 'ADX Period', 'Min ADX Threshold', 'Max ADX Threshold',
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
                           'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT',
                           'GA_START_DATE', 'GA_END_DATE',
                           'GA_LIVE_STYLE_ENTRY', 'GA_CONSERVATIVE_STOP_SLIPPAGE', 'GA_CONSERVATIVE_ENTRY_SLIPPAGE', 'GA_CONSERVATIVE_CHANNEL_SLIPPAGE', 'GA_PESSIMISTIC_STOPS',
                           'ENABLE_FILTER_STACK_TRADE_PENALTY', 'INTERACTION_PENALTY_STRENGTH',
                           'INTERACTION_LOW_TRADES_BASE', 'INTERACTION_LOW_TRADES_PER_FILTER',
                           'INTERACTION_MIN_FILTERS'],
            'Fitness Weights': ['WEIGHT_SORTINO', 'WEIGHT_DRAWDOWN', 'WEIGHT_PF', 'WEIGHT_TRADES', 'WEIGHT_PNL', 'WEIGHT_PPT'],
            'Hard Limits & Constraints': ['MIN_TRADE_DURATION', 'MAX_WIN_RATE_CAP', 'LIMIT_MAX_LOSS', 'LIMIT_MIN_SORTINO',
                                         'MIN_WIN_RATE', 'SORTINO_CAP'],
            'Normalization Ranges': ['NORM_SORTINO_MAX', 'NORM_DD_MAX', 'NORM_PF_MAX', 'NORM_TRADES_MAX', 
                                    'NORM_PNL_MAX', 'NORM_PROFIT_TRADE_MAX']
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
    
    # Set GA configuration from parameters with robust fallback
    def get_config_val(name, default_val):
        d = param_dict.get(name, {})
        v = d.get('value')
        if pd.isna(v) or v is None:
            return default_val
        return v

    POP_SIZE = get_config_val('POP_SIZE', 20)
    if args.pop:
        POP_SIZE = args.pop
        print(f"Override: POP_SIZE set to {POP_SIZE}")

    NUM_GEN = get_config_val('NUM_GEN', 10)
    if args.gen:
        NUM_GEN = args.gen
        print(f"Override: NUM_GEN set to {NUM_GEN}")

    CX_PB = get_config_val('CX_PB', 0.7)
    MUT_PB = get_config_val('MUT_PB', 0.2)
    MUT_MU = get_config_val('MUT_MU', 0.0)
    MUT_SIGMA = get_config_val('MUT_SIGMA', 0.1)
    TARGET_TRADES_DAY = get_config_val('TARGET_TRADES_DAY', 2)
    TRADES_PENALTY_WEIGHT = get_config_val('TRADES_PENALTY_WEIGHT', 0.5)
    DD_WEIGHT = get_config_val('DD_WEIGHT', 0.3)
    DATA_SPLITS = get_config_val('DATA_SPLITS', 0.7)
    DATA_SIZE = get_config_val('DATA_SIZE', 100000)
    USE_INTERLEAVED = get_config_val('USE_INTERLEAVED_SPLIT', True)
    NUM_PERIODS = get_config_val('NUM_SPLIT_PERIODS', 5)
    MIN_TRADES_DAY = get_config_val('MIN_TRADES_DAY', 1.0)
    MIN_TRADES_PEN_WEIGHT = get_config_val('MIN_TRADES_PEN_WEIGHT', -100.0)

    
    # Load new GA parameters with safety checks for missing/NaN values
    def get_ga_val(name, default):
        d = param_dict.get(name, {})
        v = d.get('value')
        if pd.isna(v) or v == '' or v is None:
            return default
        return v

    GA_START_DATE = get_ga_val('GA_START_DATE', '2024-01-01')
    GA_END_DATE = get_ga_val('GA_END_DATE', '2024-12-31')
    WEIGHT_SORTINO = get_ga_val('WEIGHT_SORTINO', 1.0)
    WEIGHT_DRAWDOWN = get_ga_val('WEIGHT_DRAWDOWN', -1.0)
    WEIGHT_PF = get_ga_val('WEIGHT_PF', 1.0)
    WEIGHT_TRADES = get_ga_val('WEIGHT_TRADES', 3.0)
    WEIGHT_PNL = get_ga_val('WEIGHT_PNL', 2.0)
    WEIGHT_PPT = get_ga_val('WEIGHT_PPT', 2.0)
    MIN_TRADE_DURATION = get_ga_val('MIN_TRADE_DURATION', 2.0)
    MAX_WIN_RATE_CAP = get_ga_val('MAX_WIN_RATE_CAP', 0.95)
    LIMIT_MAX_LOSS = get_ga_val('LIMIT_MAX_LOSS', 50000.0)
    LIMIT_MIN_SORTINO = get_ga_val('LIMIT_MIN_SORTINO', 1.0)

    
    # CRITICAL: Ensure FitnessMulti class has correct weights from CSV
    target_weights = (WEIGHT_SORTINO, WEIGHT_DRAWDOWN, WEIGHT_PF, WEIGHT_TRADES, WEIGHT_PNL, WEIGHT_PPT)
    if hasattr(creator, 'FitnessMulti'):
        if creator.FitnessMulti.weights != target_weights:
            print(f"NOTICE: FitnessMulti weights changed from {creator.FitnessMulti.weights} to {target_weights}. Recreating...")
            del creator.FitnessMulti
            if hasattr(creator, "Individual"):
                del creator.Individual
            creator.create("FitnessMulti", base.Fitness, weights=target_weights)
            creator.create("Individual", list, fitness=creator.FitnessMulti)
            print(f"FitnessMulti recreated with weights: {creator.FitnessMulti.weights}")
    else:
        creator.create("FitnessMulti", base.Fitness, weights=target_weights)
        if not hasattr(creator, "Individual"):
            creator.create("Individual", list, fitness=creator.FitnessMulti)
    
    # Set numeric ranges for the GA
    # Include int/float parameters, but exclude:
    # 1. GA Criteria parameters (configuration, not optimization)
    # 2. Parameters where min==max (effectively fixed values)
    ga_criteria_params = set(['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                              'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                              'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                              'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT',
                              'GA_START_DATE', 'GA_END_DATE',
                              'GA_LIVE_STYLE_ENTRY', 'GA_CONSERVATIVE_STOP_SLIPPAGE', 'GA_CONSERVATIVE_ENTRY_SLIPPAGE', 'GA_CONSERVATIVE_CHANNEL_SLIPPAGE', 'GA_PESSIMISTIC_STOPS',
                              'WEIGHT_SORTINO', 'WEIGHT_DRAWDOWN', 'WEIGHT_PF', 'WEIGHT_TRADES', 'WEIGHT_PNL', 'WEIGHT_PPT',
                              'MIN_TRADE_DURATION', 'MAX_WIN_RATE_CAP', 'LIMIT_MAX_LOSS', 'LIMIT_MIN_SORTINO',
                              'NORM_SORTINO_MAX', 'NORM_DD_MAX', 'NORM_PF_MAX', 'NORM_TRADES_MAX', 
                              'NORM_PNL_MAX', 'NORM_PROFIT_TRADE_MAX', 'MIN_WIN_RATE', 'SORTINO_CAP',
                              'ENABLE_FILTER_STACK_TRADE_PENALTY', 'INTERACTION_PENALTY_STRENGTH',
                              'INTERACTION_LOW_TRADES_BASE', 'INTERACTION_LOW_TRADES_PER_FILTER',
                              'INTERACTION_MIN_FILTERS',
                              'GA_DIVERSE_SEED', 'GA_DIVERSE_SEED_FRACTION', 'MIN_PROFIT_PER_TRADE'])
    
    _skip_bars_lookback = set()
    if 'Buy Lookback (minutes)' in param_dict:
        _skip_bars_lookback.add('Buy Lookback')
    if 'Sell Lookback (minutes)' in param_dict:
        _skip_bars_lookback.add('Sell Lookback')

    global PARAM_RANGES, param_keys
    PARAM_RANGES = {}
    for n, d in param_dict.items():
        if not isinstance(d, dict):
            continue
        if n.startswith('===') or n.startswith('__'):
            continue
        if n in ga_criteria_params:
            continue
        if n in _skip_bars_lookback:
            continue
        if exclude_trailing_delay_from_param_ranges(n, param_dict):
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
        'NUM_WORKERS': NUM_WORKERS,
        'SEED': args.seed,
    }
    
    data_csv_arg = args.data_csv or os.environ.get('TRADING_DATA_CSV')
    in_sample, oos, is_mask, is_periods, oos_periods = build_ga_training_bundle(
        param_dict,
        ga_start_date=GA_START_DATE,
        ga_end_date=GA_END_DATE,
        data_splits=DATA_SPLITS,
        data_size=DATA_SIZE,
        use_interleaved=USE_INTERLEAVED,
        num_periods=NUM_PERIODS,
        data_csv=data_csv_arg,
        verbose=True,
    )
    
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
        logbook.header = GA_LOGBOOK_HEADER_FULL
        _s0, _dd0, _pf0, _td0, _pnl0, _ppt0 = (
            is_res['sortino'], is_res['max_drawdown'], is_res['profit_factor'],
            is_res['avg_trades_day'], is_res['total_profit'], is_res.get('avg_profit_per_trade', 0),
        )

        def _norm_div(k, default):
            meta = param_dict.get(k, {})
            if isinstance(meta, dict):
                return float(meta.get('value', default))
            return float(default)

        _sm = _norm_div('NORM_SORTINO_MAX', 10.0)
        _dm = _norm_div('NORM_DD_MAX', 100000.0)
        _pm = _norm_div('NORM_PF_MAX', 5.0)
        _tm = _norm_div('NORM_TRADES_MAX', 3.0)
        _nm = _norm_div('NORM_PNL_MAX', 200000.0)
        _xm = _norm_div('NORM_PROFIT_TRADE_MAX', 250.0)
        _uc_s = float(_s0) / _sm if _sm else 0.0
        _uc_d = float(_dd0) / _dm if _dm else 0.0
        _uc_p = float(_pf0) / _pm if _pm else 0.0
        _uc_t = float(_td0) / _tm if _tm else 0.0
        _uc_n = float(_pnl0) / _nm if _nm else 0.0
        _uc_x = float(_ppt0) / _xm if _xm else 0.0

        logbook.record(gen=0, evals=1, avg_sortino=_s0, avg_dd=_dd0, avg_pf=_pf0,
                       pareto_size=1, avg_trades_day=_td0, max_trades_day=_td0,
                       avg_total_profit=_pnl0, avg_profit_per_trade=_ppt0,
                       actual_dd_best=_dd0, actual_sortino_best=_s0,
                       actual_pf_best=_pf0, actual_pnl_best=_pnl0,
                       max_uc_sortino=_uc_s, max_uc_dd=_uc_d, max_uc_pf=_uc_p,
                       max_uc_trades=_uc_t, max_uc_pnl=_uc_n, max_uc_ppt=_uc_x,
                       pop_min_sortino=_s0, pop_std_sortino=0.0, pop_max_dd_norm=_dd0, pop_std_dd=0.0,
                       pop_min_pf=_pf0, pop_std_pf=0.0, pop_min_trades_day=_td0, pop_std_trades_day=0.0,
                       pop_avg_trades_day=_td0, pop_max_total_profit=_pnl0, pop_min_total_profit=_pnl0,
                       pop_std_total_profit=0.0, pop_max_profit_per_trade=_ppt0, pop_min_profit_per_trade=_ppt0,
                       pop_std_profit_per_trade=0.0, pop_avg_profit_per_trade=_ppt0)
        
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
        extend_logbook_header_for_pop_stats(logbook)
        
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
            _maybe_diversify_initial_population(pop, param_dict)
            hof = tools.ParetoFront()  # Store Pareto-optimal solutions
            logbook = tools.Logbook()
            logbook.header = GA_LOGBOOK_HEADER_FULL
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
        _maybe_diversify_initial_population(pop, param_dict)
        hof = tools.ParetoFront()  # Store Pareto-optimal solutions
        logbook = tools.Logbook()
        logbook.header = GA_LOGBOOK_HEADER_FULL
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
    stats.register("max_trades_day", lambda x: np.max([f[3] for f in x]))  # max normalized trades score in pop (0-1)
    # Population distribution stats for convergence bands (dashboard only; does not affect selection)
    stats.register("pop_min_sortino", lambda x: np.min([f[0] for f in x]))
    stats.register("pop_std_sortino", lambda x: np.std([f[0] for f in x], ddof=0))
    stats.register("pop_max_dd_norm", lambda x: np.max([f[1] for f in x]))
    stats.register("pop_std_dd", lambda x: np.std([f[1] for f in x], ddof=0))
    stats.register("pop_min_pf", lambda x: np.min([f[2] for f in x]))
    stats.register("pop_std_pf", lambda x: np.std([f[2] for f in x], ddof=0))
    stats.register("pop_min_trades_day", lambda x: np.min([f[3] for f in x]))
    stats.register("pop_std_trades_day", lambda x: np.std([f[3] for f in x], ddof=0))
    stats.register("pop_avg_trades_day", lambda x: np.mean([f[3] for f in x]))
    stats.register("pop_max_total_profit", lambda x: np.max([f[4] for f in x if len(f) > 4]))
    stats.register("pop_min_total_profit", lambda x: np.min([f[4] for f in x if len(f) > 4]))
    stats.register("pop_std_total_profit", lambda x: np.std([f[4] for f in x if len(f) > 4], ddof=0))
    stats.register("pop_max_profit_per_trade", lambda x: np.max([f[5] for f in x if len(f) > 5]))
    stats.register("pop_min_profit_per_trade", lambda x: np.min([f[5] for f in x if len(f) > 5]))
    stats.register("pop_std_profit_per_trade", lambda x: np.std([f[5] for f in x if len(f) > 5], ddof=0))
    stats.register("pop_avg_profit_per_trade", lambda x: np.mean([f[5] for f in x if len(f) > 5]))
    
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
                                          initargs=(in_sample, is_mask, param_dict, param_keys))
    
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
                for idx, item in enumerate(fits):
                    fit6, _unc = _parallel_eval_result_to_fit_unc(item)
                    if len(fit6) != 6:
                        invalid_fits.append((idx, item, len(fit6)))
                
                if invalid_fits:
                    print(f"  (!)  ERROR: Found {len(invalid_fits)} fitness tuples with wrong length:")
                    for idx, fit, length in invalid_fits[:5]:  # Show first 5
                        print(f"    Individual {idx}: length={length}, values={fit}")
                    # Fix them
                    _bad_fit = (-1000.0, 100000.0, 0.0, 0.0, 0.0, 0.0)
                    _bad_uc = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
                    for idx, fit, length in invalid_fits:
                        fits[idx] = (_bad_fit, _bad_uc)
                    print(f"  Fixed {len(invalid_fits)} invalid fitness tuples.")
                
                # Diagnostic: Check if all solutions are getting penalized
                penalty_count = sum(
                    1 for it in fits if _parallel_eval_result_to_fit_unc(it)[0][0] < 0)
                if penalty_count == len(fits) and gen % 5 == 0:  # Only print every 5 generations to avoid spam
                    print(f"  (!)  WARNING: All {len(fits)} solutions are getting penalized (likely failing MIN_TRADES_DAY={MIN_TRADES_DAY})")
                    # Sample a few to see what avg_trades_day values are
                    sample_indices = [0, len(fits)//4, len(fits)//2]
                    try:
                        for idx in sample_indices:
                            if idx >= len(offspring): continue
                            sample_params = dict(zip(param_keys, offspring[idx]))
                            # Run a quick diagnostic
                            sample_metrics = run_backtest(sample_params, in_sample, param_dict, suppress_output=True, mask=is_mask)
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
                for i, (ind, df_eval, mask_eval) in enumerate([(ind, in_sample, is_mask) for ind in offspring]):
                    try:
                        fit = toolbox.evaluate((ind, df_eval, mask_eval))
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
            for idx, (item, ind) in enumerate(zip(fits, offspring)):
                fit, unc = _parallel_eval_result_to_fit_unc(item)
                # Safety check: ensure fitness has correct number of values
                if len(fit) != 6:
                    print(f"  ERROR: Individual {idx} has fitness tuple with {len(fit)} values, expected 6.")
                    print(f"  Fitness values: {fit}")
                    print(f"  Assigning poor fitness instead.")
                    fit = (-1000.0, 100000.0, 0.0, 0.0, 0.0, 0.0)  # 6 objectives
                    unc = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
                # Convert numpy types to Python floats (DEAP requires native Python types)
                fit = tuple(float(x) for x in fit)
                try:
                    setattr(ind, 'uncapped_ratios', tuple(float(x) for x in unc))
                except Exception:
                    pass
                
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
            _inject_max_uc_from_offspring(record, offspring)
            
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
                    
                    # Store ACTUAL metrics (in real units) for the best individual from current generation
                    record['actual_trades_day_best'] = best_metrics.get('avg_trades_day', 0.0)
                    record['actual_sortino_best'] = best_metrics.get('sortino', 0.0)
                    record['actual_dd_best'] = best_metrics.get('max_drawdown', 0.0)
                    record['actual_pf_best'] = best_metrics.get('profit_factor', 0.0)
                    record['actual_pnl_best'] = best_metrics.get('total_profit', 0.0)
                    
                    # Calculate actual profit per trade
                    ppt_val = 0.0
                    trades_df = best_metrics.get('trades_df')
                    if isinstance(trades_df, pd.DataFrame) and not trades_df.empty:
                        ppt_val = best_metrics.get('total_profit', 0.0) / len(trades_df)
                    record['actual_ppt_best'] = ppt_val
                    
                    # Legacy mapping for backward compatibility with logbook header
                    record['avg_trades_day'] = record['actual_trades_day_best']
                    record['avg_profit_per_trade'] = record['actual_ppt_best']
                    
                except Exception as e:
                    record['actual_trades_day_best'] = 0.0
                    record['actual_sortino_best'] = 0.0
                    record['actual_dd_best'] = 0.0
                    record['actual_pf_best'] = 0.0
                    record['actual_pnl_best'] = 0.0
                    record['actual_ppt_best'] = 0.0
                    record['avg_trades_day'] = 0.0
                    record['avg_profit_per_trade'] = 0.0
            else:
                record['actual_trades_day_best'] = 0.0
                record['actual_sortino_best'] = 0.0
                record['actual_dd_best'] = 0.0
                record['actual_pf_best'] = 0.0
                record['actual_pnl_best'] = 0.0
                record['actual_ppt_best'] = 0.0
                record['avg_trades_day'] = 0.0
                record['avg_profit_per_trade'] = 0.0
            
            logbook.record(gen=gen, evals=len(pop), **record)
            
            print(f"{gen}\t{len(pop)}\t{round(record['avg_sortino'], 4)}\t{round(record['avg_dd'], 2)}\t{round(record['avg_pf'], 4)}\t{len(hof)}")
            actual_dd_str = f", Actual DD=${record.get('actual_dd_best', 0):,.0f}" if 'actual_dd_best' in record else ""
            _pdn = record.get('pop_max_dd_norm')
            _dd_mx_s = (
                f"{round(float(_pdn), 4)}" if isinstance(_pdn, (int, float)) and not (np.isnan(_pdn) or np.isinf(_pdn)) else "n/a"
            )
            print(f"  Best: Sortino={round(record['max_sortino'], 4)}, DD max in pop (norm)={_dd_mx_s}{actual_dd_str}, PF={round(record['max_pf'], 4)}")
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
    if 'Trailing Delay (minutes)' in best_params:
        best_params['Trailing Delay (minutes)'] = max(0, int(round(best_params['Trailing Delay (minutes)'])))
    if 'Timeframe (minutes)' in best_params:
        best_params['Timeframe (minutes)'] = max(1, int(round(best_params['Timeframe (minutes)'])))
    apply_trailing_param_context(best_params, param_dict)
    if trailing_stop_enabled(best_params, param_dict):
        sync_trailing_delay_params(
            best_params, param_dict, best_params.get('Timeframe (minutes)', 15))
    apply_rsi_param_context(best_params, param_dict)
    apply_adx_param_context(best_params, param_dict)
    apply_sma_param_context(best_params, param_dict)
    apply_volume_param_context(best_params, param_dict)
    apply_rth_param_context(best_params, param_dict)
    apply_maintenance_param_context(best_params, param_dict)
    apply_lookback_bars_from_minutes(best_params, param_dict)
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
    # Write genetic_results_*.csv early (before plots + dashboard)
    # Each solution runs split-level + aggregate backtests; large HoF can take a long time.
    # ------------------------------------------------------------------
    print("\n=== Writing optimized parameters CSV (genetic_results) ===")
    print(
        "  This step can take many minutes if HoF is large (split backtests per solution). "
        "By default, CSV export includes all HoF solutions; set TRADING_GA_CSV_MAX_SOLUTIONS to cap.",
        flush=True,
    )

    def _csv_dash_progress(done, total):
        """Refresh live dashboard during CSV row build (throttled inside save_optimized_results)."""
        os.makedirs(WEB_DIR, exist_ok=True)
        phase_fp = os.path.join(DIAG_DIR, 'csv_export_phase_start.txt')
        if done == 0:
            try:
                with open(phase_fp, 'w') as f:
                    f.write(str(time.time()))
            except OSError:
                pass
        try:
            generate_html_dashboard(
                hof,
                best,
                best_params,
                best_fitness,
                param_keys,
                param_dict,
                logbook,
                is_res,
                oos_res,
                trades_is,
                trades_oos,
                WEB_DASHBOARD,
                DIAG_DIR,
                current_gen=NUM_GEN,
                total_gen=NUM_GEN,
                is_final=False,
                auto_launch=False,
                is_periods=is_periods if 'is_periods' in locals() else None,
                oos_periods=oos_periods if 'oos_periods' in locals() else None,
                in_sample=in_sample if 'in_sample' in locals() else None,
                best_gen_found=best_gen_found if 'best_gen_found' in locals() else None,
                pop=pop if 'pop' in locals() else None,
                csv_export_index=done,
                csv_export_total=total,
            )
        except Exception as e:
            print(f"  WARNING: CSV-phase dashboard refresh failed: {e}", flush=True)
        try:
            import shutil
            if os.path.exists(WEB_DASHBOARD):
                shutil.copy2(WEB_DASHBOARD, HTML_DASHBOARD)
        except Exception:
            pass

    save_optimized_results(
        hof,
        best,
        param_df,
        param_dict,
        in_sample,
        oos,
        is_mask,
        is_periods,
        oos_periods,
        suffix,
        oos_mask=oos_mask if 'oos_mask' in locals() else None,
        csv_progress_callback=_csv_dash_progress,
    )
    
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
    n_pe = min(len(param_keys), len(best))
    if n_pe < len(param_keys):
        print(
            f"  WARNING: best genome length ({len(best)}) < param_keys ({len(param_keys)}); "
            f"param evolution plots only for first {n_pe} params (checkpoint/CSV mismatch)."
        )
    for i in range(n_pe):
        pname = param_keys[i]
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
        
        trades_oos = trades_oos.copy()
        _plot_tf = float(max(1, int(best_params.get('Timeframe (minutes)', 15) or 15)))
        trades_oos['duration'] = _trade_duration_minutes_bar_aligned(trades_oos, _plot_tf)
        plt.figure(figsize=(8, 4))
        trades_oos['duration'].hist(bins=20)
        plt.title('OOS trade span (bar-grid minutes)')
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

def _select_hof_for_csv_export(hof):
    """
    CSV export runs split-detail + aggregate backtests per solution and can dominate
    wall time when the Pareto front is large.

    Environment:
      TRADING_GA_CSV_MAX_SOLUTIONS  (default: uncapped when unset/blank)
        - Positive integer: export at most this many solutions (ranked by fitness Sortino).
        - 0 or negative: export all solutions in HoF (slow).

    Returns:
        (list of individuals to export, truncated: bool)
    """
    if not hof:
        return [], False

    raw = os.environ.get('TRADING_GA_CSV_MAX_SOLUTIONS', '').strip()
    if raw == '':
        max_n = 0
    else:
        try:
            max_n = int(raw)
        except ValueError:
            max_n = 0

    if max_n <= 0 or max_n >= len(hof):
        return list(hof), False

    ranked = sorted(hof, key=lambda ind: ind.fitness.values[0], reverse=True)
    return ranked[:max_n], True


def save_optimized_results(hof, best, param_df, param_dict, in_sample, oos, is_mask, is_periods, oos_periods, suffix, oos_mask=None,
                           csv_progress_callback=None):
    """
    Generate and save the optimized parameter CSV with robustness metrics and per-split details.
    """
    global param_keys, OUTPUT_CSV, CHECKPOINT_FILE, DIAG_DIR
    
    hof_export, truncated = _select_hof_for_csv_export(hof)
    if not hof_export:
        print("WARNING: No Hall-of-Fame solutions to export; skipping CSV.")
        return

    if truncated:
        print(
            f"  CSV export: using top {len(hof_export)} of {len(hof)} Pareto solutions "
            f"(by fitness Sortino). Set TRADING_GA_CSV_MAX_SOLUTIONS=0 to export all.",
            flush=True,
        )
    else:
        print(f"  CSV export: using all {len(hof_export)} Pareto solutions.", flush=True)

    n_export = len(hof_export)
    _ev_raw = os.environ.get('TRADING_GA_DASH_CSV_PROGRESS_EVERY', '').strip()
    try:
        _dash_every = int(_ev_raw) if _ev_raw else 10
    except ValueError:
        _dash_every = 10
    _dash_every = max(1, _dash_every)

    if csv_progress_callback and n_export > 0:
        try:
            csv_progress_callback(0, n_export)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Write optimized CSV with Pareto solutions as columns (possibly capped)
    # ------------------------------------------------------------------
    solutions_data = []
    for i, ind in enumerate(hof_export):
        if len(hof_export) <= 25 or i == 0 or (i + 1) % max(1, len(hof_export) // 10) == 0 or i == len(hof_export) - 1:
            print(
                f"    Building CSV rows: solution {i + 1}/{len(hof_export)} "
                f"(fitness Sortino={ind.fitness.values[0]:.4f})...",
                flush=True,
            )
        raw_params = dict(zip(param_keys, ind))
        export_params, effective_params = build_solution_export_params(
            raw_params, param_dict, param_df, param_keys)

        # Calculate Splits and Robustness for Top Solutions
        is_periods_res, oos_periods_res = calculate_split_detail(
            effective_params, is_periods, oos_periods, param_dict)

        # Get aggregate results for this solution
        sol_is_res = run_backtest(
            effective_params, in_sample, param_dict, suppress_output=True, mask=is_mask)
        sol_oos_res = run_backtest(
            effective_params, oos, param_dict, suppress_output=True, mask=oos_mask)
        
        # Calculate Robustness Evaluation
        robust = get_robustness_metrics(sol_is_res, sol_oos_res, is_periods_res, oos_periods_res)
        
        fitness = ind.fitness.values
        # Statistics must match aggregate run_backtest(IS) so manual replays can reproduce them.
        # (Previously we fell back to fitness[i], which are *normalized* objectives — not raw Sortino/PnL.)
        solutions_data.append({
            'params': export_params,
            'effective_params': effective_params,
            'sortino': float(sol_is_res.get('sortino', 0)),
            'max_dd': float(sol_is_res.get('max_drawdown', 0)),
            'profit_factor': float(sol_is_res.get('profit_factor', 0)),
            'avg_trades_day': float(sol_is_res.get('avg_trades_day', 0)),
            'total_profit': float(sol_is_res.get('total_profit', 0)),
            'avg_profit_per_trade': float(sol_is_res.get('avg_profit_per_trade', 0)),
            'avg_trade_duration_min': float(sol_is_res.get('avg_trade_duration_min', 0)),
            'fitness_vector': tuple(float(x) for x in fitness),
            'is_selected': (ind == best),
            'robustness': robust,
            'is_periods': is_periods_res,
            'oos_periods': oos_periods_res,
            'is_aggregate': sol_is_res,
            'oos_aggregate': sol_oos_res
        })

        if csv_progress_callback and n_export > 0:
            done = i + 1
            if done == 1 or done == n_export or (done % _dash_every) == 0:
                try:
                    csv_progress_callback(done, n_export)
                except Exception:
                    pass

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
        
        output_df[col_name] = ""
        
        # Fill in parameter values
        for name, val in sol_data['params'].items():
            matching_rows = output_df[output_df['Name'] == name]
            if not matching_rows.empty:
                idx = matching_rows.index[0]
                typ = param_dict[name]['type']
                if typ == 'bool':
                    output_df.at[idx, col_name] = str(val)
                elif typ == 'int':
                    output_df.at[idx, col_name] = int(val)
                elif typ == 'float':
                    output_df.at[idx, col_name] = round(val, 4)
                else:
                    output_df.at[idx, col_name] = val
    
    # Add statistics rows
    stats_rows = []
    stats_rows.append({'Name': '=== SOLUTION STATISTICS ===', 'Value': '', 'Description': ''})
    
    metrics = [
        ('Sortino Ratio (IS aggregate)', 'sortino', '{:.4f}'),
        ('Max Drawdown ($) (IS aggregate)', 'max_dd', '${:,.2f}'),
        ('Profit Factor (IS aggregate)', 'profit_factor', '{:.4f}'),
        ('Avg Trades/Day (IS aggregate)', 'avg_trades_day', '{:.3f}'),
        ('Total Profit ($) (IS aggregate)', 'total_profit', '${:,.2f}'),
        ('Avg Profit/Trade ($) (IS aggregate)', 'avg_profit_per_trade', '${:,.2f}'),
        ('Avg Trade Span (min, bar grid) (IS aggregate)', 'avg_trade_duration_min', '{:.2f}'),
    ]
    
    for metric_name, metric_key, format_str in metrics:
        row = {'Name': metric_name, 'Type': 'statistic', 'Description': f'{metric_name} for each solution'}
        for sol_idx, sol_data in enumerate(solutions_data):
            col_name = f"Solution_{sol_idx}"
            if sol_data['is_selected']: col_name += "_SELECTED"
            row[col_name] = format_str.format(sol_data[metric_key])
        stats_rows.append(row)

    oos_metrics = [
        ('Max Drawdown ($) (OOS aggregate)', 'max_drawdown', '${:,.2f}'),
        ('Profit Factor (OOS aggregate)', 'profit_factor', '{:.4f}'),
        ('Avg Trades/Day (OOS aggregate)', 'avg_trades_day', '{:.3f}'),
        ('Total Profit ($) (OOS aggregate)', 'total_profit', '${:,.2f}'),
        ('Avg Profit/Trade ($) (OOS aggregate)', 'avg_profit_per_trade', '${:,.2f}'),
        ('Avg Trade Span (min, bar grid) (OOS aggregate)', 'avg_trade_duration_min', '{:.2f}'),
    ]
    for metric_name, metric_key, format_str in oos_metrics:
        row = {'Name': metric_name, 'Type': 'statistic', 'Description': f'{metric_name} for each solution'}
        for sol_idx, sol_data in enumerate(solutions_data):
            col_name = f"Solution_{sol_idx}"
            if sol_data['is_selected']:
                col_name += "_SELECTED"
            oos = sol_data.get('oos_aggregate') or {}
            val = float(oos.get(metric_key, 0))
            row[col_name] = format_str.format(val)
        stats_rows.append(row)

    # Context-aware derived delay for easier cross-timeframe interpretation
    row_delay = {
        'Name': 'Derived Trailing Delay (bars from minutes/timeframe)',
        'Type': 'statistic',
        'Description': 'Effective trailing delay in bars using the active GA gene (minutes when optimizable, else bars).'
    }
    for sol_idx, sol_data in enumerate(solutions_data):
        col_name = f"Solution_{sol_idx}"
        if sol_data['is_selected']:
            col_name += "_SELECTED"
        params_local = sol_data.get('effective_params', sol_data.get('params', {}))
        row_delay[col_name] = resolve_trailing_delay_bars(
            params_local, param_dict, params_local.get('Timeframe (minutes)', 15))
    stats_rows.append(row_delay)

    row_rsi = {
        'Name': 'Derived RSI filter (effective entry gates)',
        'Type': 'statistic',
        'Description': (
            'Trend: long if RSI < Max Buy, short if RSI > Min Sell. '
            'Bollinger: mean-reversion long if RSI < Oversold, short if RSI > Overbought.'
        ),
    }
    for sol_idx, sol_data in enumerate(solutions_data):
        col_name = f"Solution_{sol_idx}"
        if sol_data['is_selected']:
            col_name += "_SELECTED"
        params_local = sol_data.get('effective_params', sol_data.get('params', {}))
        row_rsi[col_name] = describe_effective_rsi_band(params_local, param_dict)
    stats_rows.append(row_rsi)

    if param_dict and 'Buy Lookback (minutes)' in param_dict:
        row_lb = {
            'Name': 'Derived Buy Lookback (bars from minutes/timeframe)',
            'Type': 'statistic',
            'Description': 'Donchian long lookback in bars when Buy Lookback (minutes) is defined in CSV.',
        }
        for sol_idx, sol_data in enumerate(solutions_data):
            col_name = f"Solution_{sol_idx}"
            if sol_data['is_selected']:
                col_name += "_SELECTED"
            pl = merge_eval_params_for_lookback(
                sol_data.get('effective_params', sol_data.get('params', {})), param_dict)
            row_lb[col_name] = resolve_buy_lookback_bars(pl, pl.get('Timeframe (minutes)', 15))
        stats_rows.append(row_lb)
    if param_dict and 'Sell Lookback (minutes)' in param_dict:
        row_ls = {
            'Name': 'Derived Sell Lookback (bars from minutes/timeframe)',
            'Type': 'statistic',
            'Description': 'Donchian short lookback in bars when Sell Lookback (minutes) is defined in CSV.',
        }
        for sol_idx, sol_data in enumerate(solutions_data):
            col_name = f"Solution_{sol_idx}"
            if sol_data['is_selected']:
                col_name += "_SELECTED"
            pl = merge_eval_params_for_lookback(
                sol_data.get('effective_params', sol_data.get('params', {})), param_dict)
            row_ls[col_name] = resolve_sell_lookback_bars(pl, pl.get('Timeframe (minutes)', 15))
        stats_rows.append(row_ls)

    # Solution Rank
    rank_row = {'Name': 'Solution Rank', 'Type': 'statistic', 'Description': 'Rank by Sortino (0 = highest)'}
    for sol_idx in range(num_solutions):
        col_name = f"Solution_{sol_idx}"
        if solutions_data[sol_idx]['is_selected']: col_name += "_SELECTED"
        rank_row[col_name] = f"#{sol_idx}" + (" (SELECTED)" if solutions_data[sol_idx]['is_selected'] else "")
    stats_rows.append(rank_row)

    # Normalized NSGA-II objectives (for tuning / archive; not comparable to Sortino Ratio row above)
    stats_rows.append({'Name': '--- GA FITNESS VECTOR (normalized, per DEAP) ---', 'Type': ''})
    fitness_labels = [
        'Fitness[0] norm Sortino obj',
        'Fitness[1] norm DD obj',
        'Fitness[2] norm PF obj',
        'Fitness[3] norm Trades obj',
        'Fitness[4] norm PnL obj',
        'Fitness[5] norm PPT obj',
    ]
    for fi, flabel in enumerate(fitness_labels):
        row = {'Name': flabel, 'Type': 'statistic', 'Description': 'Normalized objective after penalties; see Sortino row for raw IS aggregate'}
        for sol_idx, sol_data in enumerate(solutions_data):
            col_name = f"Solution_{sol_idx}"
            if sol_data['is_selected']:
                col_name += "_SELECTED"
            fv = sol_data.get('fitness_vector', ())
            row[col_name] = f"{fv[fi]:.6f}" if fi < len(fv) else ""
        stats_rows.append(row)
    
    # Robustness Evaluation
    stats_rows.append({'Name': '--- ROBUSTNESS EVALUATION ---', 'Type': ''})
    metrics_robust = [
        ('Aggregate IS Sortino', 'is_aggregate', '{:.4f}'),
        ('Aggregate OOS Sortino', 'oos_aggregate', '{:.4f}'),
        ('Sortino IS-to-OOS Degradation', 'degradation', '{:.2%}'),
        ('Positive OOS Splits', 'positive_oos_splits', '{}/{}'),
        ('Live-Ready Robustness Score', 'robustness_score', '{:.1f}')
    ]
    for metric_name, key, format_str in metrics_robust:
        row = {'Name': metric_name, 'Type': 'robustness'}
        for sol_idx, sol_data in enumerate(solutions_data):
            col_name = f"Solution_{sol_idx}"
            if sol_data['is_selected']: col_name += "_SELECTED"
            
            if key in ['is_aggregate', 'oos_aggregate']:
                val = sol_data.get(key, {}).get('sortino', 0)
            else:
                val = sol_data['robustness'].get(key)
                
            if key == 'positive_oos_splits':
                row[col_name] = format_str.format(val, sol_data['robustness'].get('total_oos_splits'))
            else:
                row[col_name] = format_str.format(val)
        stats_rows.append(row)
        
    # Per-Split Detail (In-Sample)
    stats_rows.append({'Name': '--- PER-SPLIT DETAIL (In-Sample) ---', 'Type': ''})
    split_metrics = [
        'sortino',
        'avg_trades_day',
        'profit_factor',
        'max_drawdown',
        'total_profit',
        'avg_profit_per_trade',
        'avg_trade_duration_min',
    ]
    metric_labels = {
        'sortino': 'Sortino',
        'avg_trades_day': 'Trades/D',
        'profit_factor': 'Profit Fac',
        'max_drawdown': 'Max DD',
        'total_profit': 'Total PNL',
        'avg_profit_per_trade': 'Avg Profit/Tr',
        'avg_trade_duration_min': 'Span (min)',
    }
    
    all_is_periods = sorted(list(set(p['period_name'] for sol in solutions_data for p in sol['is_periods'])), key=lambda x: int(x[1:]))
    for p_name in all_is_periods:
        for m_key in split_metrics:
            label = f"  {metric_labels[m_key]} ({p_name})"
            row = {'Name': label, 'Type': 'split_detail'}
            for sol_idx, sol_data in enumerate(solutions_data):
                col_name = f"Solution_{sol_idx}"
                if sol_data['is_selected']: col_name += "_SELECTED"
                p_res = next((p for p in sol_data['is_periods'] if p['period_name'] == p_name), None)
                if p_res:
                    val = p_res.get(m_key, 0)
                    if m_key in ['max_drawdown', 'total_profit', 'avg_profit_per_trade']:
                        row[col_name] = f"${val:,.2f}"
                    elif m_key == 'avg_trade_duration_min':
                        row[col_name] = f"{float(val):.2f}"
                    else:
                        row[col_name] = f"{val:.4f}" if m_key != 'avg_trades_day' else f"{val:.3f}"
                else: row[col_name] = "N/A"
            stats_rows.append(row)

    # Per-Split Detail (Out-of-Sample)
    stats_rows.append({'Name': '--- PER-SPLIT DETAIL (Out-of-Sample) ---', 'Type': ''})
    all_oos_periods = sorted(list(set(p['period_name'] for sol in solutions_data for p in sol['oos_periods'])), key=lambda x: int(x[1:]))
    for p_name in all_oos_periods:
        for m_key in split_metrics:
            label = f"  {metric_labels[m_key]} ({p_name})"
            row = {'Name': label, 'Type': 'split_detail'}
            for sol_idx, sol_data in enumerate(solutions_data):
                col_name = f"Solution_{sol_idx}"
                if sol_data['is_selected']: col_name += "_SELECTED"
                p_res = next((p for p in sol_data['oos_periods'] if p['period_name'] == p_name), None)
                if p_res:
                    val = p_res.get(m_key, 0)
                    if m_key in ['max_drawdown', 'total_profit', 'avg_profit_per_trade']:
                        row[col_name] = f"${val:,.2f}"
                    elif m_key == 'avg_trade_duration_min':
                        row[col_name] = f"{float(val):.2f}"
                    else:
                        row[col_name] = f"{val:.4f}" if m_key != 'avg_trades_day' else f"{val:.3f}"
                else: row[col_name] = "N/A"
            stats_rows.append(row)
    
    # Save to CSV
    stats_df = pd.DataFrame(stats_rows)
    output_df = pd.concat([output_df, stats_df], ignore_index=True)
    output_df.to_csv(OUTPUT_CSV, index=False)
    print(f"Optimized CSV with {num_solutions} solutions  {OUTPUT_CSV}")
    
    # Archive checkpoint
    if os.path.exists(CHECKPOINT_FILE):
        archive_checkpoint = os.path.join(DIAG_DIR, f'ga_checkpoint_{suffix}.pkl')
        try:
            if os.path.exists(archive_checkpoint): os.remove(archive_checkpoint)
            os.rename(CHECKPOINT_FILE, archive_checkpoint)
            print(f"Run Complete: Checkpoint archived to {archive_checkpoint}")
            print("Next run will start fresh automatically.")
        except Exception as e: print(f"WARNING: Could not archive checkpoint: {e}")


if __name__ == "__main__":
    # Required for Windows multiprocessing
    multiprocessing.freeze_support()
    main()


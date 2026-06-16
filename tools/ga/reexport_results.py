import os
import sys
import pickle
import pandas as pd
import numpy as np

# Add parent directory to path to import optimize and strategy components
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import optimize
from strategies.factory import StrategyFactory

# Force Trend strategy context for this re-export
optimize.STRATEGY_NAME = "Trend"
# Strategy name capitalization for paths
strategy_name_cap = "Trend"
optimize.PATH = f"strategies/{strategy_name_cap.lower()}/parameters/"
optimize.PARAM_CSV = os.path.join(optimize.PATH, 'trend_strategy_params.csv')

def reexport_checkpoint(checkpoint_path, output_csv):
    print(f"Loading checkpoint: {checkpoint_path}")
    with open(checkpoint_path, 'rb') as f:
        checkpoint = pickle.load(f)
    
    # ------------------------------------------------------------------
    # Step 1: Initialize GA Environment
    # ------------------------------------------------------------------
    hof = checkpoint['hall_of_fame']
    # Limit to top 100 for performance and consistency with dashboard requirements
    hof = hof[:100]
    best = hof[0]
    population = checkpoint['population']
    gen = checkpoint['generation']
    suffix = "2026-04-24-1" # Match the requested run suffix

    print(f"Loaded population of size {len(population)} at generation {gen}")

    # Load parameters from the definitive Trend CSV
    print(f"Loading parameters from {optimize.PARAM_CSV}...")
    param_dict, param_df = optimize.load_params(optimize.PARAM_CSV, return_dataframe=True)

    # Identical to optimize.py initialization to ensure mapping matches 1:1
    ga_criteria_params = set(['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                              'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                              'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                              'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT',
                              'GA_START_DATE', 'GA_END_DATE',
                              'GA_LIVE_STYLE_ENTRY', 'GA_CONSERVATIVE_STOP_SLIPPAGE', 'GA_PESSIMISTIC_STOPS',
                              'WEIGHT_SORTINO', 'WEIGHT_DRAWDOWN', 'WEIGHT_PF', 'WEIGHT_TRADES', 'WEIGHT_PNL', 'WEIGHT_PPT',
                              'MIN_TRADE_DURATION', 'MAX_WIN_RATE_CAP', 'LIMIT_MAX_LOSS', 'LIMIT_MIN_SORTINO',
                              'NORM_SORTINO_MAX', 'NORM_DD_MAX', 'NORM_PF_MAX', 'NORM_TRADES_MAX', 
                              'NORM_PNL_MAX', 'NORM_PROFIT_TRADE_MAX', 'MIN_WIN_RATE', 'SORTINO_CAP'])

    param_ranges = {}
    for n, d in param_dict.items():
        if not isinstance(d, dict) or n.startswith('===') or n.startswith('__') or n in ga_criteria_params:
            continue
        ptype = d.get('type', '')
        pmin = d.get('min')
        pmax = d.get('max')
        if ptype in ('int', 'float') and pmin is not None and pmax is not None and pmin != pmax:
            param_ranges[n] = (pmin, pmax)

    param_keys = list(param_ranges.keys())
    print(f"Identified {len(param_keys)} optimizable parameters (Expected: 26)")
    
    # CRITICAL FIX: Set global variables in optimize module so save_optimized_results 
    # uses the correct mapping when it re-runs backtests for export.
    optimize.param_keys = param_keys
    optimize.param_dict = param_dict
    optimize.PARAM_RANGES = param_ranges
    optimize.PARAM_CSV = optimize.PARAM_CSV # Already set but for clarity
    optimize.STRATEGY_NAME = "Trend"

    print(f"Re-exporting to {output_csv}...")

    # ------------------------------------------------------------------
    # Step 2: Load Raw Data and Prepare Splits
    # ------------------------------------------------------------------
    DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'
    print(f"Loading raw data from {DATA_CSV}...")
    df_raw = pd.read_csv(DATA_CSV, header=None, names=['datetime', 'open', 'high', 'low', 'close', 'volume'])
    df_raw['datetime'] = pd.to_datetime(df_raw['datetime'])
    if df_raw['datetime'].dt.tz is None:
        df_raw['datetime'] = df_raw['datetime'].dt.tz_localize('UTC').dt.tz_convert('US/Eastern').dt.tz_localize(None)
    else:
        df_raw['datetime'] = df_raw['datetime'].dt.tz_convert('US/Eastern').dt.tz_localize(None)
    df_raw.set_index('datetime', inplace=True)

    GA_START_DATE = str(param_df[param_df['Name'] == 'GA_START_DATE']['Value'].iloc[0])
    GA_END_DATE = str(param_df[param_df['Name'] == 'GA_END_DATE']['Value'].iloc[0])
    DATA_SPLITS = float(param_df[param_df['Name'] == 'DATA_SPLITS']['Value'].iloc[0])
    USE_INTERLEAVED = str(param_df[param_df['Name'] == 'USE_INTERLEAVED_SPLIT']['Value'].iloc[0]).lower() == 'true'
    NUM_PERIODS = int(param_df[param_df['Name'] == 'NUM_SPLIT_PERIODS']['Value'].iloc[0])

    print(f"Defining evaluation range: {GA_START_DATE} to {GA_END_DATE}")
    df_eval = df_raw.loc[GA_START_DATE:GA_END_DATE]
    
    print("Regenerating IS/OOS splits...")
    is_mask = pd.Series(False, index=df_eval.index)
    oos_mask = pd.Series(True, index=df_eval.index) # Default OOS is everything not IS
    is_periods = []
    oos_periods = []
    
    if USE_INTERLEAVED and NUM_PERIODS > 1:
        period_size = len(df_eval) // NUM_PERIODS
        for i in range(NUM_PERIODS):
            start_idx = i * period_size
            end_idx = (i + 1) * period_size if i < NUM_PERIODS - 1 else len(df_eval)
            period = df_eval.iloc[start_idx:end_idx]
            if i % 2 == 0:
                is_mask.iloc[start_idx:end_idx] = True
                is_periods.append(period)
            else:
                oos_periods.append(period)
        
        # Ensure masks are exactly opposite
        oos_mask = ~is_mask
    else:
        split = int(len(df_eval) * DATA_SPLITS)
        is_mask.iloc[:split] = True
        is_periods.append(df_eval.iloc[:split])
        oos_periods.append(df_eval.iloc[split:])

    # ------------------------------------------------------------------
    # Step 3: Run High-Fidelity Recalculation Loop
    # ------------------------------------------------------------------
    print(f"\nRecalculating metrics for Hall of Fame individuals...")
    for i, ind in enumerate(hof):
        if i % 10 == 0:
            print(f"  Processing {i}/100...")
        
        # Prepare full parameters for individual (merging base + optimizable)
        backtest_full_params = {}
        for key, p_data in param_dict.items():
            backtest_full_params[key] = p_data.copy()
            
        # Overwrite optimizable parameters with the GA individual's values
        for key, val in zip(param_keys, ind):
            if key in backtest_full_params:
                backtest_full_params[key]['value'] = val
        
        # Overall Stats (Full Period)
        res_full = optimize.run_backtest(ind, df_eval, backtest_full_params, suppress_output=True)
        
        # Per-Split Detail (Continuous segments)
        is_periods_res, oos_periods_res = optimize.calculate_split_detail(
            ind, is_periods, oos_periods, backtest_full_params)
        
        # Store metrics in the individual object so save_optimized_results can see them
        ind.actual_metrics = {
            'sortino': res_full['sortino'],
            'max_drawdown': res_full['max_drawdown'],
            'profit_factor': res_full['profit_factor'],
            'avg_trades_day': res_full['avg_trades_day'],
            'total_profit': res_full['total_profit'],
            'avg_profit_per_trade': res_full['total_profit'] / len(res_full['trades_df']) if not res_full['trades_df'].empty else 0.0,
            'is_results': is_periods_res,
            'oos_results': oos_periods_res
        }

    # ------------------------------------------------------------------
    # Step 4: Export to CSV
    # ------------------------------------------------------------------
    print(f"Exporting results to {output_csv}...")
    strategy_name_lower = "trend" 
    # NOTE: save_optimized_results requires param_df (original CSV dataframe)
    param_df = pd.read_csv(f"strategies/{strategy_name_lower}/parameters/{strategy_name_lower}_strategy_params.csv")
    
    optimize.OUTPUT_CSV = output_csv
    optimize.save_optimized_results(
        hof, best, param_df, param_dict, 
        df_eval, df_eval,   # in_sample and oos dataframes (same for interleaved)
        is_mask, is_periods, oos_periods, 
        "reexport",
        oos_mask=oos_mask   # CRITICAL FIX: Pass the newly supported oos_mask
    )
    print("CSV Export Complete.")

if __name__ == "__main__":
    checkpoint = "Trend/diagnostics/ga_checkpoint_2026-04-24-1.pkl"
    output = "Trend/parameters/genetic_results_2026-04-24-1.csv"
    
    if not os.path.exists(checkpoint):
        checkpoint = "Trend/diagnostics/ga_checkpoint_v4.pkl"
        
    reexport_checkpoint(checkpoint, output)

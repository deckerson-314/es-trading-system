#!/usr/bin/env python3
"""
Diagnostic to understand why strategies are producing so few trades.
Runs actual backtests to see what's happening.
"""

import os
import pickle
import pandas as pd
import numpy as np
from bollinger_strategy import load_params
from BB_Genetic_v3 import run_backtest

CHECKPOINT_FILE = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'
PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'
DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'

def load_checkpoint():
    """Load GA checkpoint."""
    if not os.path.exists(CHECKPOINT_FILE):
        print(f"ERROR: Checkpoint file not found: {CHECKPOINT_FILE}")
        return None
    
    with open(CHECKPOINT_FILE, 'rb') as f:
        checkpoint = pickle.load(f)
    
    return checkpoint

def diagnose_why_no_trades():
    """Run actual backtests to see why trades aren't happening."""
    checkpoint = load_checkpoint()
    if checkpoint is None:
        return
    
    pop = checkpoint.get('population', [])
    gen = checkpoint.get('generation', 0)
    
    print("="*80)
    print("DIAGNOSTIC: WHY ARE THERE SO FEW TRADES?")
    print("="*80)
    print(f"Generation: {gen}")
    print()
    
    # Load parameters
    param_dict, _ = load_params(PARAM_CSV, return_dataframe=True)
    
    # Build PARAM_RANGES
    ga_criteria_params = set(['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                              'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                              'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                              'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT'])
    
    PARAM_RANGES = {}
    for n, d in param_dict.items():
        if n.startswith('===') or n.startswith('__'):
            continue
        if n in ga_criteria_params:
            continue
        ptype = d.get('type', '')
        pmin = d.get('min')
        pmax = d.get('max')
        if ptype in ('int', 'float') and pmin is not None and pmax is not None:
            if pmin != pmax:
                PARAM_RANGES[n] = (pmin, pmax)
    
    param_keys = list(PARAM_RANGES.keys())
    
    # Load data (just a sample for speed)
    print("Loading data sample...")
    df_full = pd.read_csv(DATA_CSV, header=None, nrows=50000)  # First 50K rows for speed
    df_full.columns = ['datetime', 'open', 'high', 'low', 'close', 'volume']
    df_full['datetime'] = pd.to_datetime(df_full['datetime'])
    df_full = df_full.set_index('datetime')
    
    print(f"Data loaded: {len(df_full)} rows")
    print(f"Date range: {df_full.index.min()} to {df_full.index.max()}")
    print()
    
    # Test top 5 solutions
    if pop and len(pop) > 0:
        # Get top solutions by trade frequency
        solutions = []
        for i, ind in enumerate(pop):
            if hasattr(ind, 'fitness') and ind.fitness.valid:
                fitness = ind.fitness.values
                if len(fitness) >= 5:
                    solutions.append((i, ind, fitness[3], fitness[0]))  # (idx, ind, trades, sortino)
        
        solutions.sort(key=lambda x: x[2], reverse=True)  # Sort by trade frequency
        
        print("="*80)
        print("TESTING TOP 5 SOLUTIONS BY TRADE FREQUENCY")
        print("="*80)
        
        for rank, (orig_idx, ind, trade_freq_norm, sortino) in enumerate(solutions[:5], 1):
            print(f"\n{'='*60}")
            print(f"Solution {rank} (Original index {orig_idx})")
            print(f"{'='*60}")
            print(f"Normalized Trade Frequency: {trade_freq_norm:.6f}")
            print(f"Normalized Sortino: {sortino:.6f}")
            
            # Extract parameters
            params = dict(zip(param_keys, ind))
            
            # Clamp parameters
            for n, v in params.items():
                if n not in param_dict:
                    continue
                mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
                v = max(mn, min(v, mx))
                if typ == 'int':
                    params[n] = int(round(v))
                else:
                    params[n] = float(v)
            
            # Convert boolean parameters
            for n in list(params.keys()):
                if n in param_dict:
                    original_type = param_dict[n].get('type', '')
                    if original_type == 'bool' and isinstance(params[n], (int, float)):
                        params[n] = bool(int(round(params[n])))
            
            # Handle TP method
            if 'TP Method' in params:
                tp_method = int(round(params['TP Method']))
                params['Fixed BB at Entry TP'] = (tp_method == 0)
                params['Fixed ATR TP'] = (tp_method == 1)
                params['Opposite Bollinger Band TP'] = (tp_method == 2)
                params.pop('TP Method', None)
            
            # Show key parameters
            print(f"\nKey Parameters:")
            key_params_to_show = [
                'Min ATR Filter (Points)',
                'Min Volume Multiplier',
                'Long Trigger (% From Lower Band)',
                'Short Trigger (% From Upper Band)',
                'Enable Long Trades',
                'Enable Short Trades',
                'Bollinger Band StdDev',
                'Enable RTH Filter'
            ]
            
            for key in key_params_to_show:
                if key in params:
                    val = params[key]
                    pdata = param_dict.get(key, {})
                    pmin = pdata.get('min')
                    pmax = pdata.get('max')
                    if pmin is not None and pmax is not None and pmin != pmax:
                        pct = ((val - pmin) / (pmax - pmin) * 100) if pmax != pmin else 0
                        conservative = " ⚠️ CONSERVATIVE" if pct > 70 else ""
                        print(f"  {key}: {val} ({pct:.1f}% of range){conservative}")
                    else:
                        print(f"  {key}: {val}")
            
            # Run backtest
            print(f"\nRunning backtest...")
            try:
                result = run_backtest(params, df_full, param_dict, suppress_output=True, debug=True)
                
                trades_df = result.get('trades_df', pd.DataFrame())
                num_trades = len(trades_df)
                avg_trades_day = result.get('avg_trades_day', 0.0)
                sortino = result.get('sortino', 0.0)
                pf = result.get('profit_factor', 0.0)
                total_pnl = trades_df['pnl'].sum() if not trades_df.empty else 0
                
                print(f"\nBacktest Results:")
                print(f"  Total Trades: {num_trades}")
                print(f"  Avg Trades/Day: {avg_trades_day:.6f}")
                print(f"  Sortino: {sortino:.6f}")
                print(f"  Profit Factor: {pf:.6f}")
                print(f"  Total PNL: ${total_pnl:,.2f}")
                
                if num_trades == 0:
                    print(f"\n🔴 NO TRADES EXECUTED!")
                    print(f"   This explains the low trade frequency!")
                    print(f"   Possible reasons:")
                    print(f"   1. Entry conditions too strict")
                    print(f"   2. Filters eliminating all opportunities")
                    print(f"   3. Parameters too conservative")
                    print(f"   4. Data period has no valid entry signals")
                elif num_trades < 5:
                    print(f"\n⚠️  VERY FEW TRADES ({num_trades})")
                    print(f"   This is why trade frequency is so low")
                else:
                    print(f"\n✓ Reasonable number of trades ({num_trades})")
                    
            except Exception as e:
                print(f"🔴 ERROR running backtest: {e}")
                import traceback
                traceback.print_exc()
    
    # Test with default/relaxed parameters
    print(f"\n{'='*80}")
    print("TESTING WITH RELAXED PARAMETERS (FOR COMPARISON)")
    print("="*80)
    
    relaxed_params = param_dict.copy()
    # Set relaxed values
    relaxed_params['Min ATR Filter (Points)'] = {'value': 2.0, 'min': 2.0, 'max': 4.0, 'type': 'float'}
    relaxed_params['Min Volume Multiplier'] = {'value': 0.5, 'min': 0.5, 'max': 1.8, 'type': 'float'}
    relaxed_params['Long Trigger (% From Lower Band)'] = {'value': 0.5, 'min': 0.5, 'max': 2.0, 'type': 'float'}
    relaxed_params['Short Trigger (% From Upper Band)'] = {'value': 0.5, 'min': 0.5, 'max': 2.0, 'type': 'float'}
    
    # Build params dict for backtest
    test_params = {}
    for key in param_dict.keys():
        if key.startswith('===') or key.startswith('__'):
            continue
        if key in ga_criteria_params:
            continue
        test_params[key] = param_dict[key].get('value')
    
    # Override with relaxed values
    test_params['Min ATR Filter (Points)'] = 2.0
    test_params['Min Volume Multiplier'] = 0.5
    test_params['Long Trigger (% From Lower Band)'] = 0.5
    test_params['Short Trigger (% From Upper Band)'] = 0.5
    
    print(f"\nRelaxed Parameters:")
    print(f"  Min ATR Filter: 2.0 (minimum)")
    print(f"  Min Volume Multiplier: 0.5 (minimum)")
    print(f"  Long Trigger: 0.5% (minimum)")
    print(f"  Short Trigger: 0.5% (minimum)")
    
    print(f"\nRunning backtest with relaxed parameters...")
    try:
        result = run_backtest(test_params, df_full, param_dict, suppress_output=True, debug=False)
        
        trades_df = result.get('trades_df', pd.DataFrame())
        num_trades = len(trades_df)
        avg_trades_day = result.get('avg_trades_day', 0.0)
        
        print(f"\nResults with Relaxed Parameters:")
        print(f"  Total Trades: {num_trades}")
        print(f"  Avg Trades/Day: {avg_trades_day:.6f}")
        
        if num_trades > 0:
            print(f"\n✓ Relaxed parameters DO produce trades")
            print(f"   This confirms the issue is parameter values being too conservative")
        else:
            print(f"\n🔴 Even relaxed parameters produce NO TRADES!")
            print(f"   This suggests a deeper issue:")
            print(f"   1. Entry logic may have a bug")
            print(f"   2. Data may not have valid signals")
            print(f"   3. Filters may be too restrictive by default")
            
    except Exception as e:
        print(f"🔴 ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n{'='*80}")
    print("DIAGNOSIS COMPLETE")
    print(f"{'='*80}")

if __name__ == '__main__':
    diagnose_why_no_trades()


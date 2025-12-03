"""
Analyze ongoing GA run to check entry parameters and identify issues.
"""

import pickle
import os
import sys
from bollinger_strategy.parameters import load_params

def analyze_ga_run():
    checkpoint_file = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'
    
    if not os.path.exists(checkpoint_file):
        print(f"ERROR: Checkpoint file not found: {checkpoint_file}")
        return
    
    # Load checkpoint
    with open(checkpoint_file, 'rb') as f:
        checkpoint = pickle.load(f)
    
    hof = checkpoint.get('hall_of_fame', [])
    gen = checkpoint.get('generation', 0)
    logbook = checkpoint.get('logbook', None)
    
    print("="*80)
    print("ONGOING GA RUN ANALYSIS")
    print("="*80)
    print(f"Current Generation: {gen}")
    print(f"Hall of Fame size: {len(hof)}")
    
    # Load parameter definitions
    param_dict, _ = load_params('Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv', return_dataframe=True)
    
    # Get optimizable parameter keys (same logic as GA)
    ga_criteria_params = set(['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                              'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                              'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                              'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT'])
    
    param_keys = []
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
                param_keys.append(n)
    
    print(f"\nTotal optimizable parameters: {len(param_keys)}")
    
    if len(hof) == 0:
        print("\nWARNING: Hall of Fame is empty!")
        return
    
    # Analyze top 5 solutions
    print("\n" + "="*80)
    print("TOP 5 SOLUTIONS ANALYSIS")
    print("="*80)
    
    entry_params = [
        'Long Entry on Body in Zone',
        'Long Entry on Wick Touch',
        'Short Entry on Body in Zone',
        'Short Entry on Wick Touch',
        'Enable Long Trades',
        'Enable Short Trades'
    ]
    
    for i, ind in enumerate(hof[:5]):
        fitness = ind.fitness.values
        best_params = dict(zip(param_keys, ind))
        
        # Clamp parameters
        for n, v in best_params.items():
            if n not in param_dict:
                continue
            mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
            v = max(mn, min(v, mx))
            if typ == 'int':
                best_params[n] = int(round(v))
            else:
                best_params[n] = float(v)
        
        print(f"\n--- Solution #{i+1} (Sortino={fitness[0]:.4f}, DD={fitness[1]:.4f}, PF={fitness[2]:.4f}, Trades/Day={fitness[3]:.4f}) ---")
        
        # Check entry parameters
        print("  Entry Parameters:")
        all_entry_disabled = True
        for p in entry_params:
            if p in best_params:
                val = best_params[p]
                # Convert to int for display (0 or 1)
                if isinstance(val, float):
                    val = int(round(val))
                status = "✓ ENABLED" if val else "✗ DISABLED"
                print(f"    {p}: {val} {status}")
                if val:
                    all_entry_disabled = False
            else:
                print(f"    {p}: NOT IN PARAM_KEYS")
        
        if all_entry_disabled:
            print("  ⚠️  WARNING: ALL ENTRY METHODS ARE DISABLED - NO TRADES POSSIBLE!")
        
        # Check ATR filter
        if 'Min ATR Filter (Points)' in best_params and 'Max ATR Filter (Points)' in best_params:
            min_atr = best_params['Min ATR Filter (Points)']
            max_atr = best_params['Max ATR Filter (Points)']
            if min_atr > max_atr:
                print(f"  ⚠️  WARNING: Invalid ATR Filter - Min ({min_atr:.4f}) > Max ({max_atr:.4f})")
            else:
                print(f"  ATR Filter: Min={min_atr:.4f}, Max={max_atr:.4f} ✓")
    
    # Analyze entry parameter trends
    print("\n" + "="*80)
    print("ENTRY PARAMETER TRENDS (All Hall of Fame Solutions)")
    print("="*80)
    
    entry_stats = {p: {'enabled': 0, 'disabled': 0, 'values': []} for p in entry_params}
    
    for ind in hof:
        best_params = dict(zip(param_keys, ind))
        for n, v in best_params.items():
            if n not in param_dict:
                continue
            mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
            v = max(mn, min(v, mx))
            if typ == 'int':
                v = int(round(v))
            best_params[n] = v
        
        for p in entry_params:
            if p in best_params:
                val = int(round(best_params[p])) if isinstance(best_params[p], float) else best_params[p]
                entry_stats[p]['values'].append(val)
                if val:
                    entry_stats[p]['enabled'] += 1
                else:
                    entry_stats[p]['disabled'] += 1
    
    for p in entry_params:
        stats = entry_stats[p]
        total = stats['enabled'] + stats['disabled']
        if total > 0:
            enabled_pct = (stats['enabled'] / total) * 100
            print(f"\n{p}:")
            print(f"  Enabled: {stats['enabled']}/{total} ({enabled_pct:.1f}%)")
            print(f"  Disabled: {stats['disabled']}/{total} ({100-enabled_pct:.1f}%)")
            if stats['values']:
                print(f"  Sample values: {stats['values'][:10]}")
    
    # Check if any solution has all entry methods disabled
    print("\n" + "="*80)
    print("SOLUTIONS WITH ALL ENTRY METHODS DISABLED")
    print("="*80)
    
    all_disabled_count = 0
    for i, ind in enumerate(hof):
        best_params = dict(zip(param_keys, ind))
        for n, v in best_params.items():
            if n not in param_dict:
                continue
            mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
            v = max(mn, min(v, mx))
            if typ == 'int':
                v = int(round(v))
            best_params[n] = v
        
        all_disabled = True
        for p in entry_params:
            if p in best_params:
                val = int(round(best_params[p])) if isinstance(best_params[p], float) else best_params[p]
                if val:
                    all_disabled = False
                    break
        
        if all_disabled:
            all_disabled_count += 1
            if all_disabled_count <= 5:  # Show first 5
                fitness = ind.fitness.values
                print(f"  Solution #{i+1}: Sortino={fitness[0]:.4f}, Trades/Day={fitness[3]:.4f}")
    
    if all_disabled_count > 0:
        print(f"\n⚠️  WARNING: {all_disabled_count} solutions have ALL entry methods disabled!")
        print("  These solutions should be eliminated by the GA (they can't generate trades).")
        print("  This suggests the fitness function is not properly penalizing zero-trade solutions.")
    else:
        print("  ✓ No solutions found with all entry methods disabled.")
    
    # Logbook analysis
    if logbook is not None:
        print("\n" + "="*80)
        print("CONVERGENCE ANALYSIS (Last 10 Generations)")
        print("="*80)
        
        if len(logbook) > 0:
            recent = logbook[-10:] if len(logbook) >= 10 else logbook
            print(f"\n{'Gen':<6} {'Avg Sortino':<12} {'Avg Trades/Day':<15} {'Max Trades/Day':<15} {'Pareto Size':<12}")
            print("-" * 70)
            for record in recent:
                gen = record.get('gen', 'N/A')
                avg_sortino = record.get('avg_sortino', 0)
                avg_trades = record.get('avg_trades_day', 0)
                max_trades = record.get('max_trades_day', 0)
                pareto = record.get('pareto_size', 0)
                print(f"{gen:<6} {avg_sortino:<12.4f} {avg_trades:<15.2f} {max_trades:<15.2f} {pareto:<12}")
    
    print("\n" + "="*80)
    print("RECOMMENDATIONS")
    print("="*80)
    
    # Check best solution
    if len(hof) > 0:
        best = hof[0]
        best_params = dict(zip(param_keys, best))
        for n, v in best_params.items():
            if n not in param_dict:
                continue
            mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
            v = max(mn, min(v, mx))
            if typ == 'int':
                best_params[n] = int(round(v))
            else:
                best_params[n] = float(v)
        
        all_disabled = True
        for p in entry_params:
            if p in best_params:
                val = int(round(best_params[p])) if isinstance(best_params[p], float) else best_params[p]
                if val:
                    all_disabled = False
                    break
        
        if all_disabled:
            print("\n⚠️  CRITICAL: Best solution has ALL entry methods disabled!")
            print("  This solution cannot generate any trades.")
            print("\n  RECOMMENDED FIXES:")
            print("  1. Add validation in evaluate_multi_objective() to eliminate solutions with all entry methods disabled")
            print("  2. Ensure at least one entry method is enabled for each direction (long/short)")
            print("  3. Check why the GA is converging to solutions with no entry methods")
        else:
            print("\n✓ Best solution has at least one entry method enabled.")
    
    print("\n" + "="*80)

if __name__ == '__main__':
    analyze_ga_run()


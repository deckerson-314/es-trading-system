#!/usr/bin/env python3
"""Regenerate the final HTML dashboard from checkpoint without running full GA."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from BB_Genetic_v3 import (
    load_checkpoint, generate_html_dashboard, load_data,
    WEB_DASHBOARD, DIAG_DIR, HTML_DASHBOARD
)
import pandas as pd

print("Loading checkpoint...")
result = load_checkpoint()
if result is None:
    print("ERROR: No checkpoint found!")
    exit(1)

pop, hof, logbook, start_gen, config = result
print(f"Loaded checkpoint from generation {start_gen - 1}")

# Find best solution
best = max(hof, key=lambda ind: ind.fitness.values[0])
best_params = dict(zip(config['param_keys'], best))
best_fitness = best.fitness.values

print(f"Best solution Sortino: {best_fitness[0]:.6f}")

# Load data
print("Loading data...")
in_sample, oos, is_periods, oos_periods = load_data()

# Run final backtests
print("Running final backtests...")
from BB_Genetic_v3 import run_backtest, param_dict, param_keys

# Convert parameters
test_params = best_params.copy()
if 'TP Method' in test_params:
    tp_method = int(round(test_params['TP Method']))
    test_params['Fixed BB at Entry TP'] = (tp_method == 0)
    test_params['Fixed ATR TP'] = (tp_method == 1)
    test_params['Opposite Bollinger Band TP'] = (tp_method == 2)
    test_params.pop('TP Method', None)

for n in list(test_params.keys()):
    if n in param_dict:
        original_type = param_dict[n].get('type', '')
        if original_type == 'bool' and isinstance(test_params[n], (int, float)):
            test_params[n] = bool(int(round(test_params[n])))

is_res = run_backtest(test_params, in_sample, param_dict, suppress_output=False)
oos_res = run_backtest(test_params, oos, param_dict, suppress_output=False)

trades_is = is_res.get('trades_df', pd.DataFrame())
trades_oos = oos_res.get('trades_df', pd.DataFrame())

print("\nGenerating HTML dashboard...")
os.makedirs(os.path.dirname(WEB_DASHBOARD), exist_ok=True)

generate_html_dashboard(
    hof, best, best_params, best_fitness, config['param_keys'], param_dict,
    logbook, is_res, oos_res, trades_is, trades_oos,
    WEB_DASHBOARD, DIAG_DIR,
    current_gen=start_gen, total_gen=start_gen, is_final=True, auto_launch=True,
    in_sample=in_sample, best_gen_found=start_gen - 1
)

print(f"\nDashboard generated: {WEB_DASHBOARD}")


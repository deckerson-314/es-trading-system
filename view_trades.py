import json
import pandas as pd
from backtest import run_backtest

with open('genetic_results_2026-03-10-1_solution_0_SELECTED.json') as f:
    params_dict = {k: {'value': v} for k, v in json.load(f).items()}

res = run_backtest('trend', 'recent_test.csv', params_dict, suppress_log=True)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)
print(res['trades_df'].to_string())

import pandas as pd
import json
from backtest import run_backtest
from compare_paper_backtest_trend import load_trend_params
import warnings
warnings.filterwarnings('ignore')

params = load_trend_params(r'c:\Trading\strategies\trend\parameters\trend_strategy_params.csv')
bt_results = run_backtest('trend', r'c:\Trading\temp_trend_bt_data.csv', params, suppress_log=True)
trades = bt_results['trades_df']
print(trades[['entry_time', 'direction', 'entry_price', 'exit_time', 'exit_price', 'pnl_currency', 'reason']].tail(10).to_string())

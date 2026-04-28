#!/usr/bin/env python3
import sys
import os
import pandas as pd
from datetime import datetime
import warnings

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from strategies.factory import StrategyFactory
from strategies.bollinger.parameters import load_params

warnings.filterwarnings("ignore")

def run_comparison():
    strategy_name = "trend"
    data_path = r"paper_logs\live_data.csv"
    params_path = r"c:\tmp\paper_bot_params.csv"
    output_dash = "paper_comparison_v5.html"

    print(f"Starting Paper Comparison Backtest")
    print(f"Data: {data_path}")
    print(f"Params: {params_path}")

    # 1. Load Data
    df = pd.read_csv(data_path, parse_dates=True, index_col=0)
    # Ensure DatetimeIndex - handle tz-aware strings correctly
    df.index = pd.to_datetime(df.index, utc=True)
    df.index = df.index.tz_convert('US/Eastern').tz_localize(None)
    
    # live_data.csv has specific columns from monitoring.py
    # We need to ensure it matches what strategy expects
    df.columns = [str(c).lower().strip() for c in df.columns]
    
    # 2. Load Params
    params_dict = load_params(params_path)
    params_dict['verbose'] = True # Force action log

    # 3. Init Strategy
    strategy = StrategyFactory.get_strategy(strategy_name, params_dict)
    
    # 4. Indicators & Signals
    # We SKIP resampling here because input is already 30m
    print(f"Directly calculating indicators on {len(df)} pre-resampled bars...")
    df = strategy.calculate_indicators(df)
    if hasattr(strategy, 'apply_filters'):
        df = strategy.apply_filters(df)
        
    signals = strategy.calculate_entry_signals(df, verbose=True)
    long_sigs, short_sigs, action_log = signals
    
    df['entry_long_signal'] = long_sigs
    df['entry_short_signal'] = short_sigs

    # 5. Simulation (Simplified for comparison)
    positions = []
    open_positions = []
    transaction_cost = 15.0
    
    for row in df.itertuples():
        # Check Exits
        for i, pos in enumerate(open_positions[:]):
            strategy.update_trailing_stop(pos, row, df)
            should_exit, reason, price = strategy.check_exit(pos, row, df)
            if should_exit:
                exit_time = row.Index
                pnl_points = (price - pos['entry_price']) * pos['direction']
                pnl_currency = pnl_points * 50 - transaction_cost
                positions.append({
                    'entry_time': pos['entry_time'], 'exit_time': exit_time,
                    'pnl_currency': pnl_currency, 'pnl_points': pnl_points,
                    'direction': pos['direction'], 'entry_price': pos['entry_price'],
                    'exit_price': price, 'reason': reason
                })
                open_positions.pop(i)
        
        # Check Entries (using same-bar entry for 30m comparison if signal matches)
        if not open_positions:
            if row.entry_long_signal:
                open_positions.append(strategy.setup_position(row.close, 1, row, df))
            elif row.entry_short_signal:
                open_positions.append(strategy.setup_position(row.close, -1, row, df))

    # 6. Reporting
    trades_df = pd.DataFrame(positions)
    equity_curve = trades_df.set_index('exit_time')['pnl_currency'].cumsum() if not trades_df.empty else pd.Series()
    
    print(f"Backtest complete. Trades: {len(trades_df)}")
    
    try:
        import importlib
        reporting_module = importlib.import_module(f"strategies.{strategy_name}.reporting")
        
        solutions_data = [{
             'name': "Paper Comparison (30m)",
             'stats': reporting_module.calculate_stats(trades_df, equity_curve),
             'params': params_dict,
             'trades_df': trades_df,
             'equity_curve': equity_curve,
             'df': df,
             'action_log': action_log
        }]
        
        reporting_module.generate_dashboard(
            solutions_data, output_dir="web", version='5.0', 
            filename=output_dash, open_browser=False
        )
        print(f"Dashboard saved to web/{output_dash}")
    except Exception as e:
        print(f"Reporting failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_comparison()

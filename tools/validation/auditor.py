"""
tools/validation/auditor.py
===========================
Auditing tool to compare live/paper executions recorded in `live_trades.csv` 
against a theoretical backtest generated over the identical `live_data.csv`.

Usage:
  python tools/validation/auditor.py --strategy bollinger --mode PAPER
"""

import pandas as pd
import sys
import os
import json
import argparse
from datetime import datetime, timedelta

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from strategies.factory import StrategyFactory
from backtest import run_backtest # Now that we have a modular backtest.py

def parse_live_trades_csv(csv_path):
    """
    Parse live_trades.csv into a unified trades dataframe matching the backtester output.
    Format: Time,Symbol,Action,Quantity,Price,Commission,RealizedPNL,Account,PermId,ExecutionId
    """
    if not os.path.exists(csv_path):
        print(f"File not found: {csv_path}")
        return pd.DataFrame()
        
    print(f"Parsing trades from {csv_path}...")
    try:
        df = pd.read_csv(csv_path)
        df['Time'] = pd.to_datetime(df['Time'])
        
        trades = []
        open_pos = None
        df = df.sort_values('Time')
        
        for _, row in df.iterrows():
            if open_pos is None:
                open_pos = row
            else:
                open_side = open_pos['Action'] # 'BOT' or 'SLD'
                close_side = row['Action']
                
                is_valid_close = (open_side == 'BOT' and close_side == 'SLD') or \
                                 (open_side == 'SLD' and close_side == 'BOT')
                                 
                if not is_valid_close:
                    open_pos = row
                    continue
                
                entry = open_pos
                exit = row
                
                if entry['Symbol'] != exit['Symbol']:
                    open_pos = row 
                    continue
                
                direction = 'LONG' if entry['Action'] == 'BOT' else 'SHORT'
                entry_price = float(entry['Price'])
                exit_price = float(exit['Price'])
                qty = float(entry['Quantity'])
                
                pnl = (exit_price - entry_price) * (1 if direction == 'LONG' else -1) * 50 * qty
                
                trades.append({
                    'live_entry_time': entry['Time'],
                    'live_exit_time': exit['Time'],
                    'live_direction': direction,
                    'live_entry_price': entry_price,
                    'live_exit_price': exit_price,
                    'live_pnl': pnl
                })
                open_pos = None
                
        return pd.DataFrame(trades)

    except Exception as e:
        print(f"Error parsing CSV: {e}")
        return pd.DataFrame()

def compare_live_vs_backtest(strategy_name, mode='PAPER', start_date=None, end_date=None, warmup=False):
    output_dir = f"{mode.lower()}_logs"
    live_data_path = os.path.join(output_dir, 'live_data.csv')
    live_trades_path = os.path.join(output_dir, 'live_trades.csv')
    
    # We shouldn't hardcode bollinger params here, let the factory/backtester handle it based on strategy
    
    if not os.path.exists(live_data_path):
        print(f"Error: {live_data_path} not found.")
        return

    # 1. Parse Live Trades
    live_trades = parse_live_trades_csv(live_trades_path)
    if not live_trades.empty:
        live_trades = live_trades.sort_values('live_entry_time')
        if start_date:
            s_ts = pd.Timestamp(start_date)
            live_trades = live_trades[live_trades['live_entry_time'] >= s_ts]
        if end_date:
            e_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1) 
            live_trades = live_trades[live_trades['live_entry_time'] <= e_ts]
        print(f"Found {len(live_trades)} completed trades in log (filtered).")
    else:
        print("No completed trades found in log.")

    # 2. Run Backtest Using Unified `run_backtest` pipeline
    print(f"\nRunning modular backtest on {live_data_path}.")
    
    try:
        # Load Strategy instance dynamically to verify it exists
        strategy = StrategyFactory.get_strategy(strategy_name)
    except ValueError as e:
        print(f"Strategy Error: {e}")
        return
        
    # Standard Timezone/Warmup normalization is now handled natively in the core backtest module (or should be).
    # For this audit script, we simply pass the live_data.csv to `run_backtest` 
    # Let's assume the backtest module handles continuous concatenation if required.
    
    # We call the external backtest pipeline
    backtest_result = run_backtest(
        data_path=live_data_path, 
        strategy_name=strategy_name,
        params_path=None # Assume default params for strategy for now, or add param arg
    )
    
    if not backtest_result:
        print("Backtest failed to return results.")
        return
        
    bt_trades = backtest_result['trades_df']
    
    if not bt_trades.empty:
        bt_trades['entry_time'] = pd.to_datetime(bt_trades['entry_time'])
        bt_trades['exit_time'] = pd.to_datetime(bt_trades['exit_time'])
        
        if bt_trades['entry_time'].dt.tz is not None:
             bt_trades['entry_time'] = bt_trades['entry_time'].dt.tz_localize(None)

        bt_trades = bt_trades.rename(columns={
            'entry_time': 'bt_entry_time',
            'exit_time': 'bt_exit_time',
            'entry_price': 'bt_entry_price',
            'exit_price': 'bt_exit_price',
            'pnl_currency': 'bt_pnl',
            'direction': 'bt_dir_val',
            'reason': 'bt_reason',
            'tp': 'bt_tp',
            'sl': 'bt_sl',
            'stop_history': 'bt_stop_history'
        })
        bt_trades['bt_direction'] = bt_trades['bt_dir_val'].map({1: 'LONG', -1: 'SHORT'})
        print(f"Backtest generated {len(bt_trades)} trades.")
    else:
        print("Backtest generated 0 trades.")

    # 3. Compare Side-by-Side Alignments
    print("\n" + "="*100)
    print("TRADE COMPARISON (Matched by Entry Time +/- 3 min)")
    print("="*100)
    
    if not live_trades.empty and not bt_trades.empty:
        matches = []
        tolerance = pd.Timedelta(minutes=3)

        live_trades_sorted = live_trades.sort_values('live_entry_time').reset_index(drop=True)
        bt_trades_sorted = bt_trades.sort_values('bt_entry_time').reset_index(drop=True)

        for i, live_trade in live_trades_sorted.iterrows():
            live_time = live_trade['live_entry_time']
            live_dir = live_trade['live_direction']
            live_pnl = live_trade['live_pnl']

            potential_matches = bt_trades_sorted[
                (bt_trades_sorted['bt_entry_time'] >= live_time - pd.Timedelta(seconds=180)) &
                (bt_trades_sorted['bt_entry_time'] <= live_time + pd.Timedelta(seconds=180))
            ]

            if not potential_matches.empty:
                lags = (live_time - potential_matches['bt_entry_time']).dt.total_seconds()
                best_idx = lags.abs().idxmin()
                closest_bt_trade = potential_matches.loc[best_idx]

                bt_time = closest_bt_trade['bt_entry_time']
                bt_dir = closest_bt_trade['bt_direction']
                bt_pnl = closest_bt_trade['bt_pnl']
                
                time_diff_seconds = (live_time - bt_time).total_seconds()
                status = "MATCHED"
                if live_dir != bt_dir:
                    status = "DIR MISMATCH"
                elif abs(time_diff_seconds) > tolerance.total_seconds():
                    status = "TIME MISMATCH"

                matches.append({
                    'Live Time': live_time,
                    'BT Time': bt_time,
                    'Diff (s)': time_diff_seconds,
                    'Status': status,
                    'Live Dir': live_dir,
                    'BT Dir': bt_dir,
                    'Live Price': live_trade['live_entry_price'],
                    'BT Price': closest_bt_trade['bt_entry_price'],
                    'Live PnL': live_pnl,
                    'BT PnL': bt_pnl,
                    'PnL Diff': live_pnl - bt_pnl,
                    'BT Reason': closest_bt_trade.get('bt_reason', 'N/A')
                })
            else:
                matches.append({
                    'Live Time': live_time,
                    'BT Time': None,
                    'Status': 'LIVE ONLY',
                    'Live Dir': live_dir,
                    'Live Price': live_trade['live_entry_price'],
                    'Live PnL': live_pnl
                })
        
        matches_df = pd.DataFrame(matches)
        
        # Select and Reorder columns
        cols = ['Live Time', 'BT Time', 'Diff (s)', 'Status', 'Live Dir', 'BT Dir', 'Live Price', 'BT Price', 'Live PnL', 'BT PnL', 'PnL Diff', 'BT Reason']
        cols = [c for c in cols if c in matches_df.columns]
        
        print(matches_df[cols].to_string())

        csv_output_path = os.path.join(output_dir, "validation_comparison.csv")
        matches_df[cols].to_csv(csv_output_path, index=False)
        print(f"\nComparison results saved to: {csv_output_path}")

    else:
        print("\nNO TRADES TO MATCH (One or both datasets are empty).")
        
        
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live vs Backtest Auditor")
    parser.add_argument('--strategy', type=str, required=True, help="Strategy to audit (e.g., bollinger, trend)")
    parser.add_argument('--mode', type=str, default='PAPER', choices=['PAPER', 'LIVE'], help="Log directory to pull from")
    args = parser.parse_args()
    
    compare_live_vs_backtest(strategy_name=args.strategy, mode=args.mode)

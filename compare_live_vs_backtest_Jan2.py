import pandas as pd
import sys
import os
from datetime import datetime
import numpy as np

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from backtest import run_backtest as run_backtest_v4
except ImportError:
    try:
        from BB_Strategy_v4 import run_backtest_v4
    except ImportError:
        print("Error: Could not import backtest module. Ensure backtest.py or BB_Strategy_v4.py is available.")
        sys.exit(1)

def parse_live_trades_csv(csv_path):
    """
    Parse live_trades.csv from Paper Logs.
    Format: Time,Symbol,Side,Price,Qty,Commission,RealizedPNL,PermID
    """
    if not os.path.exists(csv_path):
        print(f"File not found: {csv_path}")
        return pd.DataFrame()
        
    print(f"Parsing trades from {csv_path}...")
    try:
        df = pd.read_csv(csv_path)
        # Parse Time - handle potential varied formats if needed, but standard is usually consistent
        df['Time'] = pd.to_datetime(df['Time'])
        
        trades = []
        open_pos = None
        
        # Sort by Time
        df = df.sort_values('Time')
        
        for _, row in df.iterrows():
            if open_pos is None:
                # Open
                open_pos = row
            else:
                # Close
                entry = open_pos
                exit = row
                
                if entry['Symbol'] != exit['Symbol']:
                    open_pos = row # Mismatch, assume new open
                    continue
                
                direction = 'LONG' if entry['Side'] == 'BOT' else 'SHORT'
                entry_price = float(entry['Price'])
                exit_price = float(exit['Price'])
                qty = float(entry['Qty'])
                
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

def compare_live_vs_backtest_jan2():
    # PATHS
    data_path = r'c:\Trading\recent_warmup_data.csv'
    live_params_path = r'c:\Trading\Bollinger\parameters\live_params.csv'
    live_trades_path = r'c:\Trading\paper_logs\live_trades.csv'
    
    # Time Filter for Jan 2 (1pm to 5pm ET)
    # Adjust as needed. "Today" is Jan 2.
    analysis_start = pd.Timestamp("2026-01-02 09:00:00") # Start a bit earlier to see morning
    analysis_end = pd.Timestamp("2026-01-02 18:00:00")

    print(f"--- Running Comparison for Jan 2 (Analysis Window: {analysis_start} - {analysis_end}) ---")

    # 1. Parse Live Trades
    live_trades = parse_live_trades_csv(live_trades_path)
    if not live_trades.empty:
        # Filter for Jan 2
        live_trades = live_trades[
            (live_trades['live_entry_time'] >= analysis_start) & 
            (live_trades['live_entry_time'] <= analysis_end)
        ]
        live_trades = live_trades.sort_values('live_entry_time')
        print(f"Found {len(live_trades)} completed trades in log for Jan 2.")
    else:
        print("No completed trades found in log.")

    # 2. Run Backtest
    print(f"\nRunning backtest on {data_path}...")
    
    # Load and Normalize Data
    if os.path.exists(data_path):
        df = pd.read_csv(data_path, index_col=0, parse_dates=True)
        df.columns = [c.lower().strip() for c in df.columns]
        
        # Normalize Index to US/Eastern
        # source is likely UTC (ib_insync util.df puts UTC)
        if df.index.tz is None:
            # Assume UTC
            df.index = df.index.tz_localize('UTC').tz_convert('US/Eastern').tz_localize(None)
        else:
            df.index = df.index.tz_convert('US/Eastern').tz_localize(None)
            
        # Save to Temp File for Backtest (Strategy expects File Path)
        temp_data_path = r'c:\Trading\temp_jan2_et.csv'
        df.to_csv(temp_data_path)
            
        # Run Backtest
        # Pass the TEMP FILE PATH, Correct argument name 'data_path'
        # Returns a Dictionary, not a tuple
        bt_results_pack = run_backtest_v4(
            data_path=temp_data_path, 
            params_source=live_params_path,
            start_date="2026-01-02", 
            end_date="2026-01-02"
        )
        
        bt_trades = bt_results_pack.get('trades_df', pd.DataFrame())
        
        if not bt_trades.empty:
            bt_trades = bt_trades.rename(columns={
                'entry_time': 'bt_entry_time',
                'exit_time': 'bt_exit_time',
                'direction': 'bt_direction',
                'entry_price': 'bt_entry_price',
                'exit_price': 'bt_exit_price',
                'pnl': 'bt_pnl',
                'reason': 'bt_reason'
            })
        
        # --- MATCHING LOGIC (Copied from compare_live_vs_backtest.py) ---
        matches = []
        tolerance = pd.Timedelta(seconds=135)
        
        # Sort both dataframes
        live_trades_sorted = live_trades.sort_values('live_entry_time').reset_index(drop=True)
        bt_trades_sorted = bt_trades.sort_values('bt_entry_time').reset_index(drop=True) if not bt_trades.empty else pd.DataFrame(columns=['bt_entry_time', 'bt_direction'])

        # Iterate through live trades and find the closest backtest trade
        for i, live_trade in live_trades_sorted.iterrows():
            live_time = live_trade['live_entry_time']
            live_dir = live_trade['live_direction']
            live_pnl = live_trade['live_pnl']

            # Find backtest trades where Live is ~126s LATER than BT
            min_lag = 120 
            max_lag = 135
            
            if not bt_trades_sorted.empty:
                potential_matches = bt_trades_sorted[
                    (bt_trades_sorted['bt_entry_time'] >= live_time - pd.Timedelta(seconds=max_lag)) &
                    (bt_trades_sorted['bt_entry_time'] <= live_time - pd.Timedelta(seconds=min_lag))
                ]
            else:
                potential_matches = pd.DataFrame()

            if not potential_matches.empty:
                lags = (live_time - potential_matches['bt_entry_time']).dt.total_seconds()
                best_idx = (lags - 126.5).abs().idxmin()
                closest_bt_trade = potential_matches.loc[best_idx]

                bt_time = closest_bt_trade['bt_entry_time']
                bt_dir = closest_bt_trade['bt_direction']
                bt_pnl = closest_bt_trade['bt_pnl'] if 'bt_pnl' in closest_bt_trade else 0
                
                time_diff_seconds = (live_time - bt_time).total_seconds()
                status = "MATCHED"
                if live_dir != bt_dir:
                    status = "DIR MISMATCH"
                elif abs(time_diff_seconds) > tolerance.total_seconds():
                    status = "TIME MISMATCH"

                live_dur = live_trade['live_exit_time'] - live_trade['live_entry_time']
                bt_dur = closest_bt_trade['bt_exit_time'] - closest_bt_trade['bt_entry_time']

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
                    'BT Reason': closest_bt_trade.get('bt_reason', 'N/A'),
                    'Live Dur': live_dur,
                    'BT Dur': bt_dur
                })
            else:
                live_dur = live_trade['live_exit_time'] - live_trade['live_entry_time']
                matches.append({
                    'Live Time': live_time,
                    'BT Time': None,
                    'Diff (s)': None,
                    'Status': 'LIVE ONLY',
                    'Live Dir': live_dir,
                    'BT Dir': None,
                    'Live Price': live_trade['live_entry_price'],
                    'BT Price': None,
                    'Live PnL': live_pnl,
                    'BT PnL': None,
                    'PnL Diff': None,
                    'BT Reason': None,
                    'Live Dur': live_dur,
                    'BT Dur': None
                })
        
        # Also check for BT trades that didn't get a live match
        matched_bt_times = {m['BT Time'] for m in matches if m['BT Time'] is not None}
        if not bt_trades_sorted.empty:
            for i, bt_trade in bt_trades_sorted.iterrows():
                if bt_trade['bt_entry_time'] not in matched_bt_times:
                    bt_dur = bt_trade['bt_exit_time'] - bt_trade['bt_entry_time']
                    status = "BT ONLY"
                    matches.append({
                        'Live Time': None,
                        'BT Time': bt_trade['bt_entry_time'],
                        'Diff (s)': None,
                        'Status': status,
                        'Live Dir': None,
                        'BT Dir': bt_trade['bt_direction'],
                        'Live Price': None,
                        'BT Price': bt_trade['bt_entry_price'],
                        'Live PnL': None,
                        'BT PnL': bt_trade.get('bt_pnl', 0),
                        'PnL Diff': None,
                        'BT Reason': bt_trade.get('bt_reason', 'N/A'),
                        'Live Dur': None,
                        'BT Dur': bt_dur
                    })

        matches_df = pd.DataFrame(matches)
        
        # Sort by Unified Time
        if not matches_df.empty:
            matches_df['SortTime'] = matches_df['Live Time'].combine_first(matches_df['BT Time'])
            matches_df = matches_df.sort_values('SortTime').reset_index(drop=True)
            
            # Select Columns
            cols = ['Live Time', 'BT Time', 'Diff (s)', 'Status', 
                    'Live Dir', 'BT Dir', 
                    'Live Price', 'BT Price', 
                    'Live PnL', 'BT PnL', 'PnL Diff',
                    'Live Dur', 'BT Dur',
                    'BT Reason']
            cols = [c for c in cols if c in matches_df.columns]
            
            print("\n" + "="*80)
            print("MATCHED COMPARISON (Jan 2)")
            print("="*80)
            print(matches_df[cols].to_string())
            
            # SAVE CSV
            csv_path = r'c:\Trading\jan2_comparison_metrics.csv'
            matches_df[cols].to_csv(csv_path, index=False)
            print(f"\nSaved Matched Comparison to: {csv_path}")
        else:
            print("No matches generated.")

    else:
        print(f"Data file not found: {data_path}")

if __name__ == "__main__":
    compare_live_vs_backtest_jan2()

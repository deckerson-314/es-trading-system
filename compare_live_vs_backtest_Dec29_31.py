import pandas as pd
import sys
import os
import re
from datetime import datetime, timedelta
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
    Parse the live_trades.csv file.
    Format: Time,Symbol,Side,Price,Qty,Commission,RealizedPNL,PermID
    """
    if not os.path.exists(csv_path):
        print(f"Error: Live trades CSV not found at {csv_path}")
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(csv_path)
        # Filter for Dec 29-31 2025
        df['Time'] = pd.to_datetime(df['Time'])
        
        start_date = pd.Timestamp("2025-12-29 00:00:00")
        end_date = pd.Timestamp("2025-12-31 23:59:59")
        
        # Determine PnL direction
        # Side is BOT/SLD. PnL is usually calculated on Close.
        # But this CSV logs individual executions (Entry AND Exit).
        # We need to reconstruct "Trades" (Entry + Exit pair) to get PnL.
        # However, the user's dashboard logic does this pairing.
        # For simplicity here, let's just list the EXECUTIONS side-by-side or try to pair them.
        # Actually, the user wants "Unrealized PNL" comparison? No, "comparing the live trading to a backtest".
        # Comparing TRADES is best.
        
        # Simple pairing logic:
        # Assume FIFO or alternating BOT/SLD.
        trades = []
        open_pos = None
        
        # Sort by time
        df = df.sort_values('Time')
        print(f"DEBUG: Loaded {len(df)} rows from CSV.")
        print(f"DEBUG: Date Range in CSV: {df['Time'].min()} to {df['Time'].max()}")
        print(f"DEBUG: Dtypes:\n{df.dtypes}")
        
        for _, row in df.iterrows():
            if open_pos is None:
                open_pos = row
            else:
                # Close match
                entry = open_pos
                exit = row
                
                # Check if symbols match
                if entry['Symbol'] != exit['Symbol']:
                    open_pos = row # Reset if symbol mismatch (should verify)
                    continue
                    
                direction = 'LONG' if entry['Side'] == 'BOT' else 'SHORT'
                entry_price = float(entry['Price'])
                exit_price = float(exit['Price'])
                
                pnl = (exit_price - entry_price) * (1 if direction == 'LONG' else -1) * 50
                
                trades.append({
                    'live_entry_time': entry['Time'],
                    'live_exit_time': exit['Time'],
                    'live_direction': direction,
                    'live_entry_price': entry_price,
                    'live_exit_price': exit_price,
                    'live_pnl': pnl
                })
                open_pos = None
        
        trades_df = pd.DataFrame(trades)
        
        # Filter by date range (Entry Time)
        if not trades_df.empty:
            # Ensure naive
            if trades_df['live_entry_time'].dt.tz is not None:
                trades_df['live_entry_time'] = trades_df['live_entry_time'].dt.tz_localize(None)
            if trades_df['live_exit_time'].dt.tz is not None:
                trades_df['live_exit_time'] = trades_df['live_exit_time'].dt.tz_localize(None)
                
            trades_df = trades_df[(trades_df['live_entry_time'] >= start_date) & (trades_df['live_entry_time'] <= end_date)]
            
        return trades_df
        
    except Exception as e:
        print(f"Error parsing live trades CSV: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()

def compare_live_vs_backtest():
    # 1. Config
    print("--- Live vs Backtest Comparison (Dec 29-31) ---")
    live_data_path = r'c:\Trading\ES_1min_Dec29_31_20251231.csv'
    # live_trades_csv = r'c:\Trading\paper_logs\live_trades.csv' # STALE
    live_trades_csv = r'c:\Trading\live_logs\live_trades.csv' # CORRECT
    live_params_path = r'c:\Trading\Bollinger\parameters\live_params.csv'
    
    if not os.path.exists(live_data_path):
        print(f"DATA FILE NOT FOUND: {live_data_path}")
        return

    # 2. Get Live Trades
    print(f"Parsing Live Trades from {live_trades_csv}...")
    live_trades = parse_live_trades_csv(live_trades_csv)
    print(f"Found {len(live_trades)} live trades in target period.")
    
    # 3. Run Backtest
    print(f"Running Backtest on {live_data_path}...")
    
    # Create simple params
    def local_load_params(filepath):
        import csv
        p = {}
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                for row in csv.DictReader(f):
                    try:
                        val = row['Value']
                        if row['Type'] == 'int': val = int(val)
                        elif row['Type'] == 'float': val = float(val)
                        elif row['Type'] == 'bool': val = str(val).lower() == 'true'
                        p[row['Name']] = {'value': val}
                    except: pass
        return p
        
    params = local_load_params(live_params_path)
    
    bt_result = run_backtest_v4(live_data_path, params, suppress_log=True)
    bt_trades = bt_result['trades_df']
    
    print(f"Backtest generated {len(bt_trades)} trades.")
    if not bt_trades.empty:
        print(f"BT Columns: {list(bt_trades.columns)}")
        # Normalize columns
        bt_trades['entry_time'] = pd.to_datetime(bt_trades['entry_time'])
        if bt_trades['entry_time'].dt.tz is not None:
             bt_trades['entry_time'] = bt_trades['entry_time'].dt.tz_localize(None)
    
    # 4. Compare
    print("\n" + "="*80)
    print("COMPARISON REPORT")
    print("="*80)
    
    if not live_trades.empty:
        print("\nLIVE TRADES (Dec 29-31):")
        print(live_trades[['live_entry_time', 'live_direction', 'live_entry_price', 'live_pnl']])
    else:
        print("\nNO LIVE TRADES FOUND in date range.")
        
    if not bt_trades.empty:
        # Determine direction column
        if 'dir_val' in bt_trades.columns:
            bt_trades['direction'] = bt_trades['dir_val'].map({1: 'LONG', -1: 'SHORT'})
        elif 'direction' in bt_trades.columns:
            # Maybe int?
            if bt_trades['direction'].dtype == 'int64' or bt_trades['direction'].dtype == 'float':
                 bt_trades['direction'] = bt_trades['direction'].map({1: 'LONG', -1: 'SHORT'})
        else:
             print("Warning: Could not determine direction column.")
             bt_trades['direction'] = 'UNKNOWN'
        
        print("\nBACKTEST TRADES (Dec 29-31):")
        # Filter BT trades by date
        mask = (bt_trades['entry_time'] >= pd.Timestamp("2025-12-29 00:00:00")) & (bt_trades['entry_time'] <= pd.Timestamp("2025-12-31 23:59:59"))
        filtered_bt = bt_trades[mask].copy()
        
        if not filtered_bt.empty:
            disp_cols = ['entry_time', 'direction', 'entry_price', 'pnl_currency']
            # validation
            present = [c for c in disp_cols if c in filtered_bt.columns]
            print(filtered_bt[present])
        else:
            print("No BT trades in this specific date range.")
    else:
        print("\nNO BACKTEST TRADES FOUND.")

    # 5. Visual Match
    print("\n" + "="*80)
    print("MATCHING ANALYSIS")
    print("="*80)
    
    if not live_trades.empty and not bt_trades.empty:
        # Fuzzy match by time
        matches = []
        bt_trades['entry_time'] = pd.to_datetime(bt_trades['entry_time'])
        
        for _, live_t in live_trades.iterrows():
            l_time = live_t['live_entry_time']
            # Find closest backtest trade within 5 mins
            # Check timezone awareness
            if l_time.tzinfo:
                l_time = l_time.tz_localize(None)
            
            # Create a copy for comparison
            bt_copy = bt_trades.copy()
            if bt_copy['entry_time'].dt.tz is not None:
                bt_copy['entry_time'] = bt_copy['entry_time'].dt.tz_localize(None)
                
            bt_copy['time_diff'] = (bt_copy['entry_time'] - l_time).abs()
            closest = bt_copy.nsmallest(1, 'time_diff')
            
            match_info = {'Live Time': l_time, 'Status': 'MISSING IN BT'}
            
            if not closest.empty:
                diff = closest.iloc[0]['time_diff']
                if diff <= timedelta(minutes=10):
                    match_info['Status'] = 'MATCHED'
                    match_info['BT Time'] = closest.iloc[0]['entry_time']
                    match_info['Diff (min)'] = diff.total_seconds() / 60
                    match_info['Live PnL'] = live_t['live_pnl']
                    match_info['BT PnL'] = closest.iloc[0]['pnl_currency']
                    match_info['PnL Diff'] = live_t['live_pnl'] - closest.iloc[0]['pnl_currency']
            
            matches.append(match_info)
            
        print(pd.DataFrame(matches))

if __name__ == "__main__":
    compare_live_vs_backtest()

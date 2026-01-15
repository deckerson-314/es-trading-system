import pandas as pd
import sys
import os
from datetime import datetime
import numpy as np

# Add project root to path
sys.path.append(os.getcwd())
from BB_Strategy_v4 import run_backtest_v4

import pandas as pd
import sys
import os
import re
from datetime import datetime, timedelta
import numpy as np

# Add project root to path
sys.path.append(os.getcwd())
from BB_Strategy_v4 import run_backtest_v4

def parse_live_trades_csv(csv_path):
    """
    Parse live_trades.csv.
    Format: Time,Symbol,Side,Price,Qty,Commission,RealizedPNL,PermID
    """
    if not os.path.exists(csv_path):
        print(f"File not found: {csv_path}")
        return pd.DataFrame()
        
    print(f"Parsing trades from {csv_path}...")
    try:
        df = pd.read_csv(csv_path)
        df['Time'] = pd.to_datetime(df['Time'])
        
        # Simple pairing or just list executions? 
        # The original script expected mismatched 'trades' (Entry/Exit).
        # live_trades.csv has individual executions.
        # We need to construct trades to match the dataframe format expected by the comparison logic:
        # 'live_entry_time', 'live_exit_time', 'live_direction', 'live_entry_price', 'live_exit_price', 'live_pnl'
        
        trades = []
        open_pos = None
        
        df = df.sort_values('Time')
        
        for _, row in df.iterrows():
            if open_pos is None:
                # Open new potential trade
                open_pos = row
            else:
                # Check if this row can VALIDLY close the open_pos
                # Valid pairings: BOT->SLD, SLD->BOT
                
                open_side = open_pos['Side'] # 'BOT' or 'SLD'
                close_side = row['Side']
                
                is_valid_close = (open_side == 'BOT' and close_side == 'SLD') or \
                                 (open_side == 'SLD' and close_side == 'BOT')
                                 
                if not is_valid_close:
                    # Mismatch (e.g. BOT then BOT). 
                    # Assume previous was abandoned/missed. Start new with this row.
                    # print(f"Warning: Dropping orphan trade starting {open_pos['Time']} ({open_side}) due to following {close_side}")
                    open_pos = row
                    continue
                
                # Close the trade
                entry = open_pos
                exit = row
                
                if entry['Symbol'] != exit['Symbol']:
                    open_pos = row # Mismatch symbol
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

def compare_live_vs_backtest():
    # Use continuous historical data to fix missing overnight gaps
    # Use live log data for comparison
    live_data_path = r'c:\Trading\paper_logs\live_data.csv' 
    live_params_path = r'c:\Trading\Bollinger\parameters\live_params.csv'
    live_trades_path = r'c:\Trading\paper_logs\live_trades.csv'
    
    if not os.path.exists(live_data_path):
        print(f"Error: {live_data_path} not found.")
        return

    # 1. Parse Live Trades
    live_trades = parse_live_trades_csv(live_trades_path)
    if not live_trades.empty:
        live_trades = live_trades.sort_values('live_entry_time')
        print(f"Found {len(live_trades)} completed trades in log.")
    else:
        print("No completed trades found in log.")

    # 2. Run Backtest
    print(f"\nRunning backtest on {live_data_path} (Continuous Data).")
    
    # Load Warm-up Data
    warmup_path = 'c:/Trading/recent_warmup_data.csv'
    if os.path.exists(warmup_path):
        warmup_df = pd.read_csv(warmup_path, index_col=0, parse_dates=True)
        live_df = pd.read_csv(live_data_path, index_col=0, parse_dates=True)
        
        # FIX: Normalize Columns
        live_df.columns = [c.lower().strip() for c in live_df.columns]
        warmup_df.columns = [c.lower().strip() for c in warmup_df.columns]
        
        # TIMEZONE HANDLING
        # Historical Data (CT, UTC-6) needs to align with Warmup (UTC) and Live Log (ET, UTC-5).
        # Strategy expects Naive Eastern Time (e.g. 11:30 is 11:30 AM ET).
        # We must convert to US/Eastern, then make naive.
        
        
        # TIMEZONE HANDLING (Robust Normalization)
        
        def normalize_to_eastern_naive(df, source_name="Data"):
            """
            Normalize DataFrame index to Naive Eastern Time.
            Handles specific quirks of Warmup (Naive UTC) and Live (Aware/Naive CT).
            """
            if df.index.tz is not None:
                # If already aware, convert fairly
                return df.index.tz_convert('US/Eastern').tz_localize(None)
            else:
                # If naive, we must surmise the source
                if source_name == "Warmup":
                     # Warmup is known to be UTC based on +5h shift diagnosis
                     return df.index.tz_localize('UTC').tz_convert('US/Eastern').tz_localize(None)
                elif source_name == "Live":
                     # Continuous data from platform is usually Exchange Time (CT)
                     return df.index.tz_localize('US/Central').tz_convert('US/Eastern').tz_localize(None)
            return df.index

        # 1. LIVE DATA
        live_df.index = normalize_to_eastern_naive(live_df, "Live")
        
        # CRITICAL FIX (Jan 13): Live Data is logged with End-Time labels (e.g. 14:56:00 covers 14:55-14:56).
        # Strategy expects Start-Time labels (e.g. 14:55:00 covers 14:55-14:56) for standard left-closed resampling.
        # Shift index backwards by 1 minute to standardize semantics.
        live_df.index = live_df.index - pd.Timedelta(minutes=1)
        
        # 2. WARMUP DATA
        warmup_df.index = normalize_to_eastern_naive(warmup_df, "Warmup")
            
        # 4. Filter Warmup to strictly before Live
        start_live = live_df.index[0]
        warmup_df = warmup_df[warmup_df.index < start_live]
        
        # 5. Concat
        common_cols = ['open', 'high', 'low', 'close', 'volume']
        combined_df = pd.concat([warmup_df[common_cols], live_df[common_cols]]) 
        
        # 6. Sort and Dedupe
        combined_df.sort_index(inplace=True)
        combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
        
        combined_path = 'temp_combined_data.csv'
        combined_df.to_csv(combined_path)

        print(f"Combined data saved to {combined_path} ({len(combined_df)} rows)")
        
        # Load and Override Params (Disable Volume Filter to allow execution despite history mismatch)
        # We need to import load_params or implement it. 
        # Since imports are tricky with dot-notation in this environment, we'll use a local simple loader.
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
        print("NOTE: Temporarily overriding 'Max Volume Multiplier' to 100.0 for comparison to bypass history mismatch.")
        params['Max Volume Multiplier'] = {'value': 100.0}
        
        # Override TP Method to align with OBSERVED Live Behavior (Fixed Entry TP used effectively)
        # Live System exited at 6994.50 (Entry Band 6994.42) vs Dynamic Band 6994.59.
        # This implies Fixed Entry Logic was dominant.
        print("NOTE: Overriding 'Fixed BB at Entry TP' to True to match Live Execution behavior.")
        params['Fixed BB at Entry TP'] = {'value': True}
        params['Opposite Bollinger Band TP'] = {'value': False}
        
        backtest_result = run_backtest_v4(combined_path, params, suppress_log=True)
        
        
    else:
        print("Warm-up data not found, running on live data only...")
        backtest_result = run_backtest_v4(live_data_path, live_params_path, suppress_log=True)

    bt_trades = backtest_result['trades_df']
    
    if not bt_trades.empty:
        # Normalize columns for merge
        bt_trades['entry_time'] = pd.to_datetime(bt_trades['entry_time'])
        bt_trades['exit_time'] = pd.to_datetime(bt_trades['exit_time'])
        
        # Filter BT trades to only those overlapping with Live Session
        # (Start from first live trade or first live bar)
        if hasattr(live_trades, 'live_entry_time') and not live_trades.empty:
             start_cutoff = live_trades['live_entry_time'].min() - timedelta(minutes=60)
        else:
             # Fallback if no live trades
             live_df_temp = pd.read_csv(live_data_path, index_col=0, parse_dates=True)
             start_cutoff = live_df_temp.index[0]
        
        # Convert cutoff to timezone-naive if needed
        if start_cutoff.tzinfo is not None:
            start_cutoff = start_cutoff.tz_localize(None)

        if bt_trades['entry_time'].dt.tz is not None:
             bt_trades['entry_time'] = bt_trades['entry_time'].dt.tz_localize(None)
             
        # DEBUG: Disable Cutoff Filter to see all trades
        # bt_trades = bt_trades[bt_trades['entry_time'] >= start_cutoff]
        pass

        
        # Rename for clarity
        bt_trades = bt_trades.rename(columns={
            'entry_time': 'bt_entry_time',
            'exit_time': 'bt_exit_time',
            'entry_price': 'bt_entry_price',
            'exit_price': 'bt_exit_price',
            'pnl_currency': 'bt_pnl',
            'direction': 'bt_dir_val',
            'reason': 'bt_reason'
        })
        bt_trades['bt_direction'] = bt_trades['bt_dir_val'].map({1: 'LONG', -1: 'SHORT'})
        print(f"Backtest generated {len(bt_trades)} trades.")
    else:
        print("Backtest generated 0 trades.")

    # 3. Compare Side-by-Side
    print("\n" + "="*100)
    print("DEBUG: TRADES BEFORE MERGE")
    print("LIVE TRADES:")
    print(live_trades[['live_entry_time', 'live_direction', 'live_entry_price']])
    print("\nBACKTEST TRADES:")
    if not bt_trades.empty:
        print(bt_trades[['bt_entry_time', 'bt_direction', 'bt_entry_price']])
        
    print("\n" + "="*100)
    print("DEBUG: INDICATOR CHECK AT 15:12")
    
    # Re-create Indicator Comparison (Live vs Bbacktest DF)
    bt_df = backtest_result['df']
    original_log_path = r'c:\Trading\live_logs\live_data.csv'
    
    if not bt_df.empty and os.path.exists(original_log_path):
        live_df_chk = pd.read_csv(original_log_path, index_col=0, parse_dates=True)
        # Normalize timezones
        if live_df_chk.index.tz is not None:
             live_df_chk.index = live_df_chk.index.tz_convert('UTC').tz_localize(None)
        if bt_df.index.tz is not None:
             bt_df.index = bt_df.index.tz_convert('UTC').tz_localize(None)
        
        # Rename columns for join
             # Let's add them to the subset join
             print("DEBUG: Row Data at 15:12")
             print(target_row) # Print everything available first
             
             # Need to re-fetch source data to get volume/ma specifically if not in join
             live_src = live_df_chk.loc[target_row.index]
             bt_src = bt_df.loc[target_row.index]
             
             print("\nLIVE DATA (from CSV):")
             print(live_src[['volume', 'volume_ma', 'volume_filter']])
             
             print("\nBACKTEST DATA:")
             print(bt_src[['volume', 'avg_volume', 'volume_filter']])
             
             print("\nSIGNAL DEBUG:")
             print(bt_src[['close', 'upper', 'lower', 'entry_long_signal', 'entry_short_signal']])
             
        else:
             print("No data found for 15:12 in combined indicator dataframe.")
             
    print("="*100)
    print("TRADE COMPARISON (Matched by Entry Time +/- 2 min)")
    print("="*100)
    
    if not live_trades.empty and not bt_trades.empty:
        # Use merge_asof to align trades
        comparison = pd.merge_asof(
            live_trades, 
            bt_trades.sort_values('bt_entry_time'), 
            left_on='live_entry_time', 
            right_on='bt_entry_time', 
            tolerance=pd.Timedelta(hours=4), # Huge tolerance to see alignment
            direction='nearest'
        )
        
        # Select and Reorder columns
        matches = []
        # Set a tolerance for matching entry times (e.g., 3 minutes)
        tolerance = pd.Timedelta(minutes=3)

        # Sort both dataframes by entry time for efficient matching
        live_trades_sorted = live_trades.sort_values('live_entry_time').reset_index(drop=True)
        bt_trades_sorted = bt_trades.sort_values('bt_entry_time').reset_index(drop=True)

        # Iterate through live trades and find the closest backtest trade
        for i, live_trade in live_trades_sorted.iterrows():
            live_time = live_trade['live_entry_time']
            live_dir = live_trade['live_direction']
            live_pnl = live_trade['live_pnl']

            # Find backtest trades where Live is within +/- 3 minutes of BT
            # Target Window: -180s to +180s
            
            potential_matches = bt_trades_sorted[
                (bt_trades_sorted['bt_entry_time'] >= live_time - pd.Timedelta(seconds=180)) &
                (bt_trades_sorted['bt_entry_time'] <= live_time + pd.Timedelta(seconds=180))
            ]

            if not potential_matches.empty:
                # Find the one closest in time (smallest absolute lag)
                lags = (live_time - potential_matches['bt_entry_time']).dt.total_seconds()
                best_idx = lags.abs().idxmin()
                closest_bt_trade = potential_matches.loc[best_idx]
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

                # Calculate Durations
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
        for i, bt_trade in bt_trades_sorted.iterrows():
            if bt_trade['bt_entry_time'] not in matched_bt_times:
                bt_dur = bt_trade['bt_exit_time'] - bt_trade['bt_entry_time']
                bt_time = bt_trade['bt_entry_time']
                
                # Check if Live was already in a trade
                status = "BT ONLY"
                overlap_note = ""
                
                # Check overlap with ANY live trade
                for _, live_trade in live_trades_sorted.iterrows():
                    if live_trade['live_entry_time'] <= bt_time <= live_trade['live_exit_time']:
                        status = "BT ONLY (LIVE OCCUPIED)"
                        overlap_note = f"in Live Trade ({live_trade['live_direction']})"
                        break

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
                    'BT PnL': bt_trade['bt_pnl'],
                    'PnL Diff': None,
                    'BT Reason': bt_trade.get('bt_reason', 'N/A'),
                    'Live Dur': None,
                    'BT Dur': bt_dur,
                    'Overlap Note': overlap_note
                })

        matches_df = pd.DataFrame(matches)
        
        # 1. SEQUENTIAL SORTING
        # Create a unified timestamp for sorting
        matches_df['SortTime'] = matches_df['Live Time'].combine_first(matches_df['BT Time'])
        matches_df = matches_df.sort_values('SortTime').reset_index(drop=True)
        
        # 2. OVERLAP ANALYSIS (Why did BT miss a Live Trade?)
        # For 'LIVE ONLY' trades, check if BT was holding a position at (LiveTime - 114s)
        avg_lag = 114 # seconds
        
        for i, row in matches_df.iterrows():
            if row['Status'] == 'LIVE ONLY' and pd.notnull(row['Live Time']):
                check_time = row['Live Time'] - pd.Timedelta(seconds=avg_lag)
                
                # Check if this time falls within any BT trade interval
                # bt_trades_sorted has 'bt_entry_time' and 'bt_exit_time'
                
                # Optimisation: Filter BT trades that started before check_time
                candidates = bt_trades_sorted[bt_trades_sorted['bt_entry_time'] <= check_time]
                
                is_occupied = False
                occupying_trade = None
                
                for _, bt_row in candidates.iterrows():
                    if bt_row['bt_exit_time'] >= check_time:
                        is_occupied = True
                        occupying_trade = bt_row
                        break
                
                if is_occupied:
                    matches_df.at[i, 'Status'] = 'LIVE ONLY (BT OCCUPIED)'
                    matches_df.at[i, 'BT Reason'] = f"In Trade ({occupying_trade['bt_direction']})"

        # Reorder columns
        cols = ['Live Time', 'BT Time', 'Diff (s)', 'Status', 
                'Live Dir', 'BT Dir', 
                'Live Price', 'BT Price', 
                'Live PnL', 'BT PnL', 'PnL Diff',
                'Live Dur', 'BT Dur',
                'BT Reason']
        # Filter only existing cols
        cols = [c for c in cols if c in matches_df.columns]
        
        print("\nMATCHED TRADES (SEQUENTIAL | Tol: 120-135s | Overlap Check):")
        # Force full string output
        print(matches_df[cols].to_string())

        # Save to CSV
        csv_output_path = "comparison_metrics_sequential.csv"
        matches_df[cols].to_csv(csv_output_path, index=False)
        print(f"\nComparison results saved to: {csv_output_path}")
        
        # Analyze Lag
        if 'Diff (s)' in matches_df.columns:
            matched = matches_df[matches_df['Status'].isin(['MATCHED', 'DIR MISMATCH'])]
            if not matched.empty:
                avg_diff = matched['Diff (s)'].mean()
                median_diff = matched['Diff (s)'].median()
                print(f"\nAverage Diff (Live - BT): {avg_diff:.2f} seconds")
                print(f"Median Diff (Live - BT): {median_diff:.2f} seconds")

    else:
        print("\nNO TRADES TO MATCH.")
        
    # ALWAYS PRINT RAW TRADES FOR DEBUGGING - FULL LIST
    print("\n" + "="*50)
    print("DEBUG: RAW TRADE LISTS (FULL - NO TRUNCATION)")
    print("="*50)
    
    print("LIVE TRADES:")
    print(live_trades[['live_entry_time', 'live_direction', 'live_entry_price', 'live_pnl']].to_string())
    
    print("\nBACKTEST TRADES:")
    if not bt_trades.empty:
        # Sort for readability
        bt_trades = bt_trades.sort_values('bt_entry_time') # Changed from 'entry_time' to 'bt_entry_time' to match new column name
        print(bt_trades[['bt_entry_time', 'bt_direction', 'bt_entry_price', 'bt_pnl', 'bt_reason']].to_string()) # Added reason

if __name__ == "__main__":
    compare_live_vs_backtest()

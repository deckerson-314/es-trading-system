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

def parse_live_trades_from_log(log_path):
    """
    Parse ib_deployment.log for TRADE CLOSE lines.
    Format: ... TRADE CLOSE - SHORT | ... | Entry Price: $... | Exit Price: $... | ... | Entry Time: ... | Exit Time: ...
    """
    trades = []
    if not os.path.exists(log_path):
        print(f"Log file not found: {log_path}")
        return pd.DataFrame()
        
    print(f"Parsing trades from {log_path}...")
    
    # Regex pattern
    # Look for: TRADE CLOSE - (DIR) ... Entry Price: $X ... Exit Price: $Y ... Entry Time: T1 ... Exit Time: T2
    pattern = re.compile(r"TRADE CLOSE - (LONG|SHORT).*?Entry Price: \$([\d\.]+).*?Exit Price: \$([\d\.]+).*?Entry Time: ([\d\- :]+).*?Exit Time: ([\d\- :]+)")
    
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if "TRADE CLOSE" in line:
                    match = pattern.search(line)
                    if match:
                        direction = match.group(1)
                        entry_price = float(match.group(2))
                        exit_price = float(match.group(3))
                        entry_time_str = match.group(4)
                        exit_time_str = match.group(5)
                        
                        try:
                            entry_time = pd.to_datetime(entry_time_str)
                            exit_time = pd.to_datetime(exit_time_str)
                            
                            # Determine PnL direction
                            dir_val = 1 if direction == 'LONG' else -1
                            pnl = (exit_price - entry_price) * dir_val * 50 # ES multiplier
                            
                            trades.append({
                                'live_entry_time': entry_time,
                                'live_exit_time': exit_time,
                                'live_direction': direction,
                                'live_entry_price': entry_price,
                                'live_exit_price': exit_price,
                                'live_pnl': pnl
                            })
                        except Exception as e:
                            print(f"Error parsing date in line: {entry_time_str} / {exit_time_str} - {e}")
                            
    except Exception as e:
        print(f"Error reading log file: {e}")
        
    return pd.DataFrame(trades)

def compare_live_vs_backtest():
    live_data_path = 'live_data.csv'
    live_params_path = 'Bollinger/parameters/live_params.csv'
    log_path = 'ib_deployment.log'
    
    if not os.path.exists(live_data_path):
        print(f"Error: {live_data_path} not found.")
        return

    # 1. Parse Live Trades
    live_trades = parse_live_trades_from_log(log_path)
    if not live_trades.empty:
        live_trades = live_trades.sort_values('live_entry_time')
        print(f"Found {len(live_trades)} completed trades in log.")
    else:
        print("No completed trades found in log.")

    # 2. Run Backtest
    print(f"\nRunning backtest on {live_data_path} (with 5-day warm-up)...")
    
    # Load Warm-up Data
    warmup_path = 'c:/Trading/recent_warmup_data.csv'
    if os.path.exists(warmup_path):
        warmup_df = pd.read_csv(warmup_path, index_col=0, parse_dates=True)
        live_df = pd.read_csv(live_data_path, index_col=0, parse_dates=True)
        
        # FIX: Normalize Columns and Timezones
        
        # 1. Ensure Index Names match (for clarity)
        warmup_df.index.name = 'datetime'
        live_df.index.name = 'datetime'
        
        # 2. Select only common OHLCV columns for Warmup
        common_cols = ['open', 'high', 'low', 'close', 'volume']
        warmup_df = warmup_df[common_cols]
        
        # 3. Normalize Timezones (Convert to Eastern to match Live typically, or UTC)
        # Assuming Live is ET (UTC-5). Warmup is UTC-6 (CST?) or varying.
        # Safest: Convert both to UTC, then remove tz info (to be naive but aligned)
        if warmup_df.index.tz is not None:
            warmup_df.index = warmup_df.index.tz_convert('UTC').tz_localize(None)
        if live_df.index.tz is not None:
            live_df.index = live_df.index.tz_convert('UTC').tz_localize(None) # Align to UTC then drop
            
        # 4. Filter Warmup to strictly before Live
        start_live = live_df.index[0]
        warmup_df = warmup_df[warmup_df.index < start_live]
        
        # 5. Concat
        combined_df = pd.concat([warmup_df, live_df[common_cols]]) # Use only common cols for backtest source
        
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
             
        # FIX: Backtest runs in UTC (due to Warmup concat), Live Log is ET.
        # Shift Backtest Times by -5 hours to match Live Log
        print("Adjusting Backtest Timestamps from UTC to ET (-5 hours)...")
        bt_trades['entry_time'] = bt_trades['entry_time'] - pd.Timedelta(hours=5)
        bt_trades['exit_time'] = bt_trades['exit_time'] - pd.Timedelta(hours=5)

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
    if not bt_df.empty:
        live_df_chk = pd.read_csv(live_data_path, index_col=0, parse_dates=True)
        # Normalize timezones
        if live_df_chk.index.tz is not None:
             live_df_chk.index = live_df_chk.index.tz_convert('UTC').tz_localize(None)
        if bt_df.index.tz is not None:
             bt_df.index = bt_df.index.tz_convert('UTC').tz_localize(None)
        
        # Rename columns for join
        live_subset = live_df_chk[['close', 'atr_filter', 'volume_filter', 'in_rth']].copy()
        live_subset.columns = [f"LIVE_{c}" for c in live_subset.columns]
        
        bt_subset = bt_df[['close', 'atr_filter', 'volume_filter', 'in_rth', 'entry_long_signal', 'entry_short_signal']].copy()
        bt_subset.columns = [f"BT_{c}" for c in bt_subset.columns]
        
        # Join
        ind_comparison = live_subset.join(bt_subset, how='inner')
        
        # Check specific time
        target_row = ind_comparison[ind_comparison.index.astype(str).str.contains("15:12")]
        if not target_row.empty:
             pd.set_option('display.max_columns', None)
             pd.set_option('display.width', 1000)
             # Add Volume and Avg Volume columns to print
             # LIVE_volume might be 5-sec based or resampled? 
             # live_data.csv has 'volume' and 'volume_ma' columns (I put them in save_live_data_row)
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
        cols = [
            'live_entry_time', 'bt_entry_time', 
            'live_direction', 'bt_direction',
            'live_entry_price', 'bt_entry_price',
            'live_exit_price', 'bt_exit_price',
            'live_pnl', 'bt_pnl',
            'bt_reason'
        ]
        
        final_view = comparison[cols].copy()
        
        # Calculate diffs
        final_view['diff_entry'] = final_view['live_entry_price'] - final_view['bt_entry_price']
        final_view['diff_pnl'] = final_view['live_pnl'] - final_view['bt_pnl']
        
        # Formatting
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)
        pd.set_option('display.float_format', lambda x: '%.2f' % x)
        
        print(final_view)
        
    elif not live_trades.empty:
        print("Live trades exist but no backtest trades to match.")
        print(live_trades)
    elif not bt_trades.empty:
        print("Backtest trades exist but no live trades to match.")
        print(bt_trades[['bt_entry_time', 'bt_direction', 'bt_entry_price', 'bt_pnl']])
    else:
        print("No trades in either live log or backtest.")
        
    # ALWAYS PRINT RAW TRADES FOR DEBUGGING
    print("\n" + "="*50)
    print("DEBUG: RAW TRADE LISTS")
    print("="*50)
    print("LIVE TRADES:")
    print(live_trades[['live_entry_time', 'live_direction', 'live_entry_price', 'live_pnl']])
    print("\nBACKTEST TRADES:")
    if not bt_trades.empty:
        print(bt_trades[['bt_entry_time', 'bt_direction', 'bt_entry_price', 'bt_pnl']])

if __name__ == "__main__":
    compare_live_vs_backtest()

import pandas as pd
import sys
import os
from datetime import datetime
import numpy as np

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest import run_backtest
from strategies.trend.strategy import TrendStrategy
from plot_comparison import generate_comparison_charts

def parse_live_trades_csv(csv_path, analysis_start=None, analysis_end=None):
    if not os.path.exists(csv_path):
        print(f"File not found: {csv_path}")
        return pd.DataFrame()
        
    print(f"Parsing trades from {csv_path}...")
    try:
        df = pd.read_csv(csv_path, header=None)
        # Handle cases where header might or might not exist
        if 'Price' not in df.iloc[0].values and 'Price' not in df.columns:
            df.columns = ['Time', 'Symbol', 'Side', 'Price', 'Qty', 'Commission', 'RealizedPNL', 'PermID']
        elif 'Price' in df.iloc[0].values:
            df.columns = df.iloc[0]
            df = df[1:]
            
        df['Time'] = pd.to_datetime(df['Time'])
        df['Price'] = df['Price'].astype(float)
        df['Qty'] = df['Qty'].astype(float)
        
        # Filter to analysis window BEFORE position tracking to avoid historical imbalances
        if analysis_start is not None:
             # Add a 30m buffer for warmup if needed, though Trend is usually fine
             df = df[df['Time'] >= (analysis_start - pd.Timedelta(minutes=30))]
        if analysis_end is not None:
             df = df[df['Time'] <= analysis_end]

        if df.empty:
            return pd.DataFrame()

        # Sort by time, then by PermID. IBKR assigns higher PermIDs to the child 
        # (exit) orders in a bracket fill compared to the parent (entry).
        df = df.sort_values(['Time', 'PermID'], ascending=[True, True])
        
        trades = []
        # Group by Symbol to handle multiple contracts or rollovers correctly
        for symbol, symbol_df in df.groupby('Symbol'):
            net_pos = 0
            entry_fill = None
            
            for _, row in symbol_df.iterrows():
                side_sign = 1 if row['Side'] == 'BOT' else -1
                qty = row['Qty']
                prev_pos = net_pos
                net_pos += side_sign * qty
                
                # Check for entry: transition from flat
                if prev_pos == 0 and net_pos != 0:
                    entry_fill = row
                
                # Check for exit: transition from non-zero to zero
                elif prev_pos != 0 and net_pos == 0:
                    if entry_fill is not None:
                        direction = 1 if entry_fill['Side'] == 'BOT' else -1
                        trades.append({
                            'live_entry_time': entry_fill['Time'],
                            'live_exit_time': row['Time'],
                            'live_direction': direction,
                            'live_entry_price': float(entry_fill['Price']),
                            'live_exit_price': float(row['Price']),
                            'live_pnl': (float(row['Price']) - float(entry_fill['Price'])) * direction * 50 * float(entry_fill['Qty']),
                            'symbol': symbol
                        })
                    entry_fill = None
                
                # Handling doubled positions (bug scenario)
                # If we are at pos 2, and go to 1, it's a partial exit but we stay in 'trade mode'
                # The next fill that hits 0 will close the sequence from the FIRST entry_fill.
                
        return pd.DataFrame(trades)

    except Exception as e:
        print(f"Error parsing CSV: {e}")
        return pd.DataFrame()

def load_trend_params(params_path):
    if not os.path.exists(params_path):
        print(f"WARNING: Params file not found at {params_path}, using defaults")
        return {}
        
    df = pd.read_csv(params_path)
    params = {}
    
    # Check if this is GA Format (Solution_0) or flat format
    if 'Solution_0' in df.columns:
        col_name = 'Solution_0'
        if 'Solution_0_SELECTED' in df.columns:
            col_name = 'Solution_0_SELECTED'
            
        for _, row in df.iterrows():
            name = row.get('Name')
            if pd.isna(name) or str(name).startswith('==='): continue
            row_type = row.get('Type', '')
            val = row.get(col_name)
            if pd.isna(val) or val == '': continue
            
            if row_type == 'int':
                try: val = int(float(val))
                except: pass
            elif row_type == 'float':
                try: val = float(val)
                except: pass
            elif row_type == 'bool':
                if str(val).lower() == 'true': val = True
                elif str(val).lower() == 'false': val = False
            
            params[name] = {'value': val, 'type': row_type}
    else:
        # Standard flat format Name,Value,Type
        for _, row in df.iterrows():
            name = row.get('Name')
            val = row.get('Value')
            if pd.isna(name): continue
            
            row_type = row.get('Type', 'float')
            if pd.isna(val) or val == '': continue
            
            if row_type == 'int':
                try: val = int(float(val))
                except: pass
            elif row_type == 'float':
                try: val = float(val)
                except: pass
            elif row_type == 'bool':
                if str(val).lower() in ['true', '1']: val = True
                else: val = False
            
            params[name] = {'value': val, 'type': row_type}
            
    return params

def main():
    data_path = r'c:\Trading\paper_logs\live_data.csv'
    live_trades_path = r'c:\Trading\paper_logs\live_trades.csv'
    params_path = r'c:\Trading\strategies\trend\parameters\trend_strategy_params_testing_ultra_high.csv'
    
    analysis_start = pd.Timestamp("2026-03-27 09:30:00")
    analysis_end = pd.Timestamp("2026-03-27 13:15:00")

    print(f"--- Running Comparison for Trend Strategy (Analysis Window: {analysis_start.date()} to {analysis_end.date()}) ---")

    # 1. Parse Live Trades
    live_trades = parse_live_trades_csv(live_trades_path, analysis_start=analysis_start, analysis_end=analysis_end)
    if not live_trades.empty:
        live_trades = live_trades[
            (live_trades['live_entry_time'] >= analysis_start) & 
            (live_trades['live_entry_time'] <= analysis_end)
        ]
        live_trades = live_trades.sort_values('live_entry_time')
        print(f"Found {len(live_trades)} completed trades in live_trades.csv for Trend Strategy.")
    else:
        print("No completed trades found in log.")
        return

    print(f"\nFormatting and extracting Backtest Data from {data_path}...")
    if not os.path.exists(data_path):
        print(f"Data file not found: {data_path}")
        return
        
    df_data = pd.read_csv(data_path, index_col=0, parse_dates=True)
    df_data.columns = [c.lower().strip() for c in df_data.columns]
    
    # CRITICAL: Strip to OHLCV only. The live_data.csv contains extra indicator
    # columns (mid, upper, lower, adx, volume_ma, etc.) from other strategies.
    # These columns have NaN values that cause TrendStrategy.calculate_indicators()
    # dropna() to wipe ALL rows, producing zero signals and zero matches.
    ohlcv_cols = ['open', 'high', 'low', 'close', 'volume']
    extra_cols = [c for c in df_data.columns if c not in ohlcv_cols]
    if extra_cols:
        print(f"  Stripping {len(extra_cols)} non-OHLCV columns: {extra_cols}")
        df_data = df_data[ohlcv_cols]
    
    # Drop duplicate timestamps (live_data.csv appends duplicates from two bot instances)
    df_data = df_data[~df_data.index.duplicated(keep='last')]
    
    df_data.index = pd.to_datetime(df_data.index, utc=True)
    if getattr(df_data.index, 'tz', None) is not None and str(df_data.index.tz) != 'US/Eastern':
        df_data.index = df_data.index.tz_convert('US/Eastern').tz_localize(None)
    else:
        df_data.index = df_data.index.tz_localize(None)
    
    # Drop any rows with NaN in OHLCV
    df_data = df_data.dropna(subset=ohlcv_cols)
        
    temp_data_path = r'c:\Trading\temp_trend_bt_data.csv'
    df_data.to_csv(temp_data_path)
    print(f"Saved {len(df_data)} rows to {temp_data_path} (OHLCV only, full history for warmup)")

    # 3. Load Parameters
    params_dict = load_trend_params(params_path)
    print(f"Loaded {len(params_dict)} parameters for Trend strategy.")

    # 4. Run Backtest using unified backtest.py
    print(f"Running backtest...")
    bt_results = run_backtest(
        strategy_name='trend', 
        data_path=temp_data_path, 
        params_dict=params_dict, 
        suppress_log=True
    )
    
    bt_trades = bt_results.get('trades_df', pd.DataFrame())
    
    if not bt_trades.empty:
        bt_trades = bt_trades.rename(columns={
            'entry_time': 'bt_entry_time',
            'exit_time': 'bt_exit_time',
            'direction': 'bt_direction',
            'entry_price': 'bt_entry_price',
            'exit_price': 'bt_exit_price',
            'pnl_currency': 'bt_pnl',
            'reason': 'bt_reason'
        })
        print(f"Backtest completed with {len(bt_trades)} trades in window.")
    else:
        print("Backtest produced 0 trades.")

    # 5. Matching Logic
    matches = []
    
    # Sort both dataframes
    live_trades_sorted = live_trades.sort_values('live_entry_time').reset_index(drop=True)
    bt_trades_sorted = bt_trades.sort_values('bt_entry_time').reset_index(drop=True) if not bt_trades.empty else pd.DataFrame(columns=['bt_entry_time', 'bt_direction'])

    for i, live_trade in live_trades_sorted.iterrows():
        live_time = live_trade['live_entry_time']
        live_dir = live_trade['live_direction']
        live_pnl = live_trade['live_pnl']

        if not bt_trades_sorted.empty:
            # Look for trades within +/- 15 minutes to be safe, since paper trades might have lag or timing issues
            potential_matches = bt_trades_sorted[
                (bt_trades_sorted['bt_entry_time'] >= live_time - pd.Timedelta(minutes=17)) &
                (bt_trades_sorted['bt_entry_time'] <= live_time + pd.Timedelta(minutes=17))
            ]
        else:
            potential_matches = pd.DataFrame()

        live_dur = live_trade['live_exit_time'] - live_trade['live_entry_time']

        if not potential_matches.empty:
            lags = (live_time - potential_matches['bt_entry_time']).dt.total_seconds()
            best_idx = lags.abs().idxmin()
            closest_bt_trade = potential_matches.loc[best_idx]

            bt_time = closest_bt_trade['bt_entry_time']
            bt_dir = closest_bt_trade['bt_direction']
            bt_pnl = closest_bt_trade['bt_pnl'] if 'bt_pnl' in closest_bt_trade else 0
            
            time_diff_seconds = (live_time - bt_time).total_seconds()
            status = "MATCHED"
            if live_dir != bt_dir:
                status = "DIR MISMATCH"

            bt_dur = closest_bt_trade['bt_exit_time'] - closest_bt_trade['bt_entry_time']

            matches.append({
                'Live Time': live_time,
                'BT Time': bt_time,
                'Diff (s)': time_diff_seconds,
                'Status': status,
                'Live Dir': live_dir,
                'BT Dir': bt_dir,
                'Live Exit Time': live_trade['live_exit_time'],
                'BT Exit Time': closest_bt_trade['bt_exit_time'],
                'Live Price': live_trade['live_entry_price'],
                'BT Price': closest_bt_trade['bt_entry_price'],
                'Live Exit Price': live_trade['live_exit_price'],
                'BT Exit Price': closest_bt_trade['bt_exit_price'],
                'Live PnL': live_pnl,
                'BT PnL': bt_pnl,
                'PnL Diff': live_pnl - bt_pnl if bt_pnl else live_pnl,
                'BT Reason': closest_bt_trade.get('bt_reason', 'N/A'),
                'Live Dur': live_dur,
                'BT Dur': bt_dur,
                'SortTime': live_time
            })
        else:
            matches.append({
                'Live Time': live_time,
                'BT Time': None,
                'Diff (s)': None,
                'Status': 'LIVE ONLY',
                'Live Dir': live_dir,
                'BT Dir': None,
                'Live Price': live_trade['live_entry_price'],
                'BT Price': None,
                'Live Exit Time': live_trade['live_exit_time'],
                'BT Exit Time': None,
                'Live Exit Price': live_trade['live_exit_price'],
                'BT Exit Price': None,
                'Live PnL': live_pnl,
                'BT PnL': None,
                'PnL Diff': None,
                'BT Reason': None,
                'Live Dur': live_dur,
                'BT Dur': None,
                'SortTime': live_time
            })
    
    # BT Only trades
    matched_bt_times = {m['BT Time'] for m in matches if m['BT Time'] is not None}
    if not bt_trades_sorted.empty:
        for i, row in bt_trades_sorted.iterrows():
            if row['bt_entry_time'] not in matched_bt_times:
                matches.append({
                'Live Time': None,
                'BT Time': row['bt_entry_time'],
                'Diff (s)': None,
                'Status': 'BT ONLY',
                'Live Dir': None,
                'BT Dir': row['bt_direction'],
                'Live Price': None,
                'BT Price': row['bt_entry_price'],
                'Live Exit Time': None,
                'BT Exit Time': row['bt_exit_time'],
                'Live Exit Price': None,
                'BT Exit Price': row['bt_exit_price'],
                'Live PnL': None,
                'BT PnL': row.get('bt_pnl', 0),
                'PnL Diff': None,
                'BT Reason': row.get('bt_reason', 'N/A'),
                'Live Dur': None,
                'BT Dur': row['bt_exit_time'] - row['bt_entry_time'],
                'SortTime': row['bt_entry_time']
            })

    matches_df = pd.DataFrame(matches)
    
    if not matches_df.empty:
        matches_df = matches_df.sort_values('SortTime').reset_index(drop=True)
        
        cols = [
            'Live Time', 'BT Time', 'Diff (s)', 'Status', 
            'Live Dir', 'BT Dir', 
            'Live Price', 'BT Price', 
            'Live Exit Price', 'BT Exit Price',
            'Live PnL', 'BT PnL',
            'BT Reason'
        ]
        
        print("\n" + "="*95)
        print("MATCHED COMPARISON (TREND STRATEGY - MARCH 2026)")
        print("="*95)
        print(matches_df[cols].to_string())
        
        summary = matches_df['Status'].value_counts()
        matches_df.to_csv('final_comparison_results.csv', index=False)
        print("\nSummary:")
        print(summary)
        
        # 6. Generate interactive dashboard
        try:
            print("\nGenerating interactive comparison dashboard overlays...")
            generate_comparison_charts("final_comparison_results.csv", "web/comparison_charts")
        except Exception as e:
            print(f"Failed to generate dashboard: {e}")
    else:
        print("No matches generated.")

if __name__ == "__main__":
    main()

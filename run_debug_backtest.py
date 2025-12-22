import pandas as pd
import sys
import os

# Add path to find modules
sys.path.append('c:\\Trading')

from BB_Strategy_v4 import run_backtest_v4
# from ib_deployment_v4 import load_params # REMOVED to avoid dotenv error

def load_params(filepath):
    """Simple param loader to avoid imports."""
    params = {}
    import csv
    if not os.path.exists(filepath):
        return params
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            val = row['Value']
            name = row['Name']
            if val and name:
                try:
                    if row['Type'] == 'int':
                        val = int(val)
                    elif row['Type'] == 'float':
                        val = float(val)
                    elif row['Type'] == 'bool':
                        val = str(val).lower() == 'true'
                except:
                    pass
                params[name] = {'value': val}
    return params

def run_debug():
    # UPDATED: Use the Main Master Data File that USER just updated
    # main_data_path = r"c:\Trading\Backtrader\data\ES_full_1min_continuous_ratio_adjusted.csv"
    # Actually, let's use the one in Bollinger/data since merge_gap_data writes to c:\Trading\Backtrader\data...
    # Wait, merge_gap_data updated c:\Trading\Backtrader\data\ES_full_1min_continuous_ratio_adjusted.csv
    # So we use that one.
    live_data_path = r"c:\Trading\Backtrader\data\ES_full_1min_continuous_ratio_adjusted.csv"
    live_params_path = 'c:\\Trading\\Bollinger\\parameters\\live_params.csv'
    
    if os.path.exists(live_data_path):
        print(f"Loading Master Data: {live_data_path}")
        # Read full file (no header for this file? Step 10404 says NO HEADER)
        # Wait, Step 10404 says "Main Data (No Header)".
        # And updated file should also have NO header if merge_gap_data respected that.
        # Let's check.
        try:
            # Try reading with header inference first line
            # If datetime column missing, reload.
            # But merge_gap_data Step 116: df_combined.to_csv(main_file, header=False)
            # So it HAS NO HEADER.
            
            df = pd.read_csv(live_data_path, header=None, names=['datetime', 'open', 'high', 'low', 'close', 'volume'], index_col='datetime', parse_dates=True)
        except Exception as e:
            print(f"Error reading master file: {e}")
            return

        print(f"Total rows: {len(df)}")
        
        # Slice Last 5 Days for Valid Warmup
        last_date = df.index[-1]
        start_slice = last_date - pd.Timedelta(days=5)
        df_slice = df[df.index >= start_slice]
        
        sliced_path = 'temp_master_slice.csv'
        df_slice.to_csv(sliced_path) # pandas writes header by default
        print(f"Sliced last 5 days to {sliced_path} ({len(df_slice)} rows)")
        
        # Load Parameters
        params = load_params(live_params_path)
        
        print("Using Standard Parameters (Volume Filter Enabled).")
        print("Running Backtest on Sliced Master Data...")
        
        # Pass Sliced Path (which now HAS header "datetime,open..." from to_csv default)
        result = run_backtest_v4(sliced_path, params, suppress_log=True)
        
        trades = result['trades_df']
        if not trades.empty:
            if trades['entry_time'].dt.tz is not None:
                trades['entry_time'] = trades['entry_time'].dt.tz_localize(None)
            
            # Shift UTC to ET
            trades['entry_time'] = trades['entry_time'] - pd.Timedelta(hours=5)
            
            print("Trades columns found:", trades.columns.tolist())
            
            # Select columns carefully
            cols_to_show = ['entry_time', 'direction', 'entry_price']
            if 'pnl' in trades.columns:
                cols_to_show.append('pnl')
            elif 'PnL' in trades.columns:
                cols_to_show.append('PnL')
            elif 'realized_pnl' in trades.columns:
                cols_to_show.append('realized_pnl')
                
            print("\nGenerated Trades (Dec 16 only):")
            dec16_trades = trades[trades['entry_time'] >= '2025-12-16 00:00:00']
            if not dec16_trades.empty:
                print(dec16_trades[cols_to_show])
            else:
                print("No trades found for Dec 16 even with Volume Filter disabled.")
                print("Last 5 trades:")
                print(trades[cols_to_show].tail())
        else:
            print("No trades generated.")
            
    else:
        print("Data files missing.")

if __name__ == "__main__":
    run_debug()

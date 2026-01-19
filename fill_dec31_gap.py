
import pandas as pd
import os

def fill_gap():
    main_path = r'c:\Trading\ES_1min_Dec29_31_20251231.csv'
    live_log_path = r'c:\Trading\live_logs\live_data.csv'
    output_path = r'c:\Trading\ES_1min_Dec29_31_EXTENDED.csv'
    
    print(f"Reading Main: {main_path}")
    df_main = pd.read_csv(main_path, index_col=0, parse_dates=True)
    print(f"Main End: {df_main.index[-1]}")
    
    print(f"Reading Live Log: {live_log_path}")
    df_live = pd.read_csv(live_log_path, index_col=0, parse_dates=True)
    print(f"Live Log End: {df_live.index[-1]}")
    
    # 1. Normalize Columns
    # Main has Title Case: Open, High, Low, Close, Volume
    # Live likely has lowercase: open, high, low, close, volume (based on file checks)
    # Let's inspect columns
    print(f"Main Cols: {df_main.columns}")
    print(f"Live Cols: {df_live.columns}")
    
    # Rename Live to Title Case
    df_live.rename(columns={
        'open': 'Open', 
        'high': 'High', 
        'low': 'Low', 
        'close': 'Close', 
        'volume': 'Volume'
    }, inplace=True)
    
    # Select only OHLCV
    wanted_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    # Check if they exist
    for c in wanted_cols:
        if c not in df_live.columns:
            print(f"Warning: Col {c} missing in live log. Available: {df_live.columns}")
    
    df_live_clean = df_live[wanted_cols].copy()
    
    # 2. Normalize Timezones
    # Main is likely Central (UTC-6)
    # Live is likely Eastern (UTC-5)
    
    target_tz = df_main.index.tz
    print(f"Target TZ (Main): {target_tz}")
    
    if df_live_clean.index.tz is not None:
        print("Converting Live Log to Target TZ...")
        df_live_clean.index = df_live_clean.index.tz_convert(target_tz)
    else:
        print("Live Log is Naive? Assuming ET and converting...")
        df_live_clean.index = df_live_clean.index.tz_localize('US/Eastern').tz_convert(target_tz)
        
    # 3. Merge
    print("Concatenating...")
    df_combined = pd.concat([df_main, df_live_clean])
    
    # 4. Sort and Dedupe
    df_combined.sort_index(inplace=True)
    df_combined = df_combined[~df_combined.index.duplicated(keep='last')]
    
    print(f"New Extended End: {df_combined.index[-1]}")
    
    df_combined.to_csv(output_path)
    print(f"Saved to {output_path}")

if __name__ == "__main__":
    fill_gap()

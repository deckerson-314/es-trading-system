import pandas as pd
import os
import pytz

def clean_data():
    input_path = r'c:\Trading\paper_logs\live_data.csv'
    output_path = r'c:\Trading\data\Q1_ES_1min_cleaned.csv'
    
    print(f"Reading {input_path}...")
    # Skip potential duplicate headers within the file if the bot crashed/restarted
    df = pd.read_csv(input_path, on_bad_lines='skip')
    
    # Filter rows that look like headers (containing "datetime")
    df = df[df['datetime'] != 'datetime']
    
    # Select columns
    target_cols = ['datetime', 'open', 'high', 'low', 'close', 'volume']
    if not all(col in df.columns for col in target_cols):
        print(f"ERROR: Missing columns. Found: {df.columns}")
        return
        
    df = df[target_cols].copy()
    
    # Parse datetime with utc=True to avoid mixed timezone issues
    print("Parsing datetimes...")
    df['datetime'] = pd.to_datetime(df['datetime'], utc=True, errors='coerce')
    df.dropna(subset=['datetime'], inplace=True)
    
    # Define Q1 bounds in UTC
    # 2026-01-01 00:00:00 EST is 2026-01-01 05:00:00 UTC
    # For simplicity, we'll just use UTC direct.
    start_dt = pd.Timestamp('2026-01-01', tz='UTC')
    end_dt = pd.Timestamp('2026-04-01', tz='UTC')
    
    print(f"Filtering between {start_dt} and {end_dt} (UTC)...")
    
    mask = (df['datetime'] >= start_dt) & (df['datetime'] < end_dt)
    df_q1 = df.loc[mask].copy()
    
    # Sort and remove duplicates
    df_q1.sort_values('datetime', inplace=True)
    df_q1.drop_duplicates(subset=['datetime'], inplace=True)
    
    # Convert back to New York time and STRIP timezone for backtester compatibility
    print("Converting to naive NY Time...")
    df_q1['datetime'] = df_q1['datetime'].dt.tz_convert('US/Eastern').dt.tz_localize(None)
    
    print(f"Extraction complete. Found {len(df_q1)} bars.")
    
    if not df_q1.empty:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        df_q1.to_csv(output_path, index=False)
        print(f"Saved to {output_path}")
    else:
        print("WARNING: No data found in Q1 2026!")

if __name__ == "__main__":
    clean_data()

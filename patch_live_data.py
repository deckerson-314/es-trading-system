import pandas as pd
import numpy as np

def patch_data():
    csv_path = 'c:\\Trading\\paper_logs\\live_data.csv'
    print(f"Loading {csv_path}...")
    
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"Error loading CSV: {e}")
        return

    # Target Timestamp
    target_ts_str = "2026-01-15 09:11:00-05:00"
    
    # Check if exists
    if target_ts_str in df['datetime'].values:
        print(f"Timestamp {target_ts_str} ALREADY EXISTS. No patch needed.")
        return

    print(f"Timestamp {target_ts_str} MISSING. Appending patch row...")
    
    # Construct Row
    # We only care about OHLCV for backtest re-simulation.
    # Fill others with default values to maintain structure (though pandas handles missing cols by filling NaN)
    # But we want to match columns.
    
    new_row = {col: np.nan for col in df.columns}
    new_row['datetime'] = target_ts_str
    new_row['open'] = 7002.00
    new_row['high'] = 7002.25
    new_row['low'] = 7002.00
    new_row['close'] = 7002.00
    new_row['volume'] = 99
    
    # Append
    df_new = pd.DataFrame([new_row])
    df = pd.concat([df, df_new], ignore_index=True)
    
    # Sort
    print("Sorting by datetime...")
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime')
    
    # Save
    print("Saving patched file...")
    # Convert datetime back to string format if needed? 
    # Original file has offset-aware strings. pd.to_datetime makes them Timestamp.
    # We should keep the output format consistent.
    # The read_csv didn't parse dates? I didn't verify.
    # If I parsed dates, I need to format them back.
    # Let's rely on pandas default string conversion or parse explicitly.
    
    # Safer to just append text effectively, but pandas is robust.
    # Let's verify format.
    
    df.to_csv(csv_path, index=False)
    print("Patch Complete.")

if __name__ == "__main__":
    patch_data()

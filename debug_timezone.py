
import pandas as pd
import os

def debug_tz():
    print("--- Debugging Timezone Logic ---")
    
    # 1. Load Live File
    live_path = r'c:\Trading\ES_1min_Dec29_31_20251231.csv'
    if os.path.exists(live_path):
        df_live = pd.read_csv(live_path, index_col=0, parse_dates=True)
        print(f"Live File Loaded. Rows: {len(df_live)}")
        print(f"Live Index TZ: {df_live.index.tz}")
        print(f"Sample Index: {df_live.index[0]}")
        
        # Apply Conversion Logic
        target_tz = 'US/Eastern'
        if df_live.index.tz is not None:
            print(f"Converting to {target_tz}...")
            df_live.index = df_live.index.tz_convert(target_tz).tz_localize(None)
            print(f"Sample Converted: {df_live.index[0]}")
            
            # Check 11:28 case
            # Find a row that was originally 11:28 ET (i.e. 16:28 UTC -> 10:28 CT)
            # 2025-12-30 10:28:00-06:00
            # Let's search for string match in original if possible, but here we have transformed df
            
            check = df_live[df_live.index.astype(str).str.contains("11:28")]
            if not check.empty:
                print(f"Found 11:28 row after conversion:\n{check.head(1)}")
            else:
                print("No 11:28 row found after conversion.")
        else:
            print("Live Index is NAIVE. Conversion skipped.")
            
    else:
        print("Live file missing.")

    # 2. Check Warmup
    warm_path = r'c:\Trading\recent_warmup_data.csv'
    if os.path.exists(warm_path):
        df_warm = pd.read_csv(warm_path, index_col=0, parse_dates=True)
        print(f"\nWarmup File Loaded. Rows: {len(df_warm)}")
        print(f"Warmup Index TZ: {df_warm.index.tz}")
        print(f"Sample Warmup: {df_warm.index[0]}")
    else:
        print("Warmup file missing.")

if __name__ == "__main__":
    debug_tz()

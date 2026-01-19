
import pandas as pd
import os

def normalize_to_eastern_naive(df, source_name="Data"):
    print(f"\nProcessing {source_name}...")
    print(f"Original TZ: {df.index.tz}")
    print(f"Original Sample: {df.index[0]}")
    
    if df.index.tz is not None:
        # If aware, simply convert
        res = df.index.tz_convert('US/Eastern').tz_localize(None)
        print(f"Aware Conversion Result: {res[0]}")
        return res
    else:
        # If naive, we must guess based on source
        if source_name == "Warmup":
             # Warmup is known to be UTC based on diagnosis
             res = df.index.tz_localize('UTC').tz_convert('US/Eastern').tz_localize(None)
             print(f"Naive Warmup (UTC->ET) Result: {res[0]}")
             return res
        elif source_name == "Live":
             # Continuous data naive?
             res = df.index.tz_localize('US/Central').tz_convert('US/Eastern').tz_localize(None)
             print(f"Naive Live (CT->ET) Result: {res[0]}")
             return res
    return df.index

def debug_alignment():
    print("--- Debugging Alignment Logic ---")
    
    # 1. Load Live File (Continuous)
    live_path = r'c:\Trading\ES_1min_Dec29_31_20251231.csv'
    if os.path.exists(live_path):
        df_live = pd.read_csv(live_path, index_col=0, parse_dates=True)
        # Force the same index processing as the script might implicitely do? 
        # Actually proper read_csv handles ISO8601 with offsets automatically.
        
        # Test Normalization
        norm_index = normalize_to_eastern_naive(df_live, "Live")
        
        # Check specific known time
        # 11:30 AM ET on Dec 30 should exist.
        target_str = "2025-12-30 11:30:00"
        if pd.Timestamp(target_str) in norm_index:
            print(f"SUCCESS: Found {target_str} in Normalized Live Data.")
        else:
            print(f"FAILED: Could not find {target_str} in Normalized Live Data.")
            # Print near matches
            print(f"Head of Normalized: {norm_index[:5]}")
            
    # 2. Load Warmup
    warm_path = r'c:\Trading\recent_warmup_data.csv'
    if os.path.exists(warm_path):
        df_warm = pd.read_csv(warm_path, index_col=0, parse_dates=True)
        norm_index_w = normalize_to_eastern_naive(df_warm, "Warmup")
        print(f"Head of Normalized Warmup: {norm_index_w[:5]}")

if __name__ == "__main__":
    debug_alignment()

import pandas as pd
import numpy as np

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

try:
    df = pd.read_csv('live_data.csv')
    df['datetime'] = pd.to_datetime(df['datetime'])
    
    print(f"Total Rows: {len(df)}")
    
    # Check Active Filters
    # From live_params: RTH=0, Trend=0, ADX=1, Vol=1, ATR=1, Maint=1
    
    print("\n--- Filter Pass Rates ---")
    if 'in_rth' in df.columns:
        print(f"In RTH: {df['in_rth'].sum()} / {len(df)} ({df['in_rth'].mean():.1%})")
    
    if 'in_maintenance' in df.columns:
        print(f"Not Maintenance: {(~df['in_maintenance']).sum()} / {len(df)}")
    
    if 'volume_filter' in df.columns:
        print(f"Volume Filter Pass: {df['volume_filter'].sum()} / {len(df)} ({df['volume_filter'].mean():.1%})")
        
    if 'atr_filter' in df.columns:
        print(f"ATR Filter Pass: {df['atr_filter'].sum()} / {len(df)} ({df['atr_filter'].mean():.1%})")

    # ADX Filter Check
    # live_data.csv might have 'adx' value, need to check if < threshold (21)
    if 'adx' in df.columns:
        adx_threshold = 21  # Hardcoded from live_params
        df['adx_pass'] = df['adx'] < adx_threshold
        print(f"ADX Filter Pass (< {adx_threshold}): {df['adx_pass'].sum()} / {len(df)} ({df['adx_pass'].mean():.1%})")
    else:
        df['adx_pass'] = True # Assume true if missing for now
        print("ADX column missing")

    # Combined Filter Status (Assuming RTH=0 (disabled) logic if param says 0, but script logs 'in_rth' anyway. 
    # Let's trust the columns if they exist. Main blockers are Vol, ATR, ADX.
    # Note: enable_rth_filter is 0 in params, so 'in_rth' column might be irrelevant or always True in logic? 
    # Actually logic usually applies it if enabled. If disabled, logic returns True. 
    # Let's assume the CSV columns represent the FINAL logical state used by the strategy.)
    
    df['all_filters_pass'] = (
        df['volume_filter'] & 
        df['atr_filter'] & 
        (~df['in_maintenance']) &
        df['adx_pass']
    )
    
    print(f"\nAll Filters Pass: {df['all_filters_pass'].sum()} / {len(df)}")

    # Check for Triggers ONLY when Filters Pass
    eligible_df = df[df['all_filters_pass']]
    
    if len(eligible_df) > 0:
        print(f"\nScanning {len(eligible_df)} eligible bars for triggers...")
        
        # Long Trigger: Low <= Lower (Wick Touch=1)
        long_triggers = eligible_df[eligible_df['low'] <= eligible_df['lower']]
        
        # Short Trigger: High >= Upper (Wick Touch=1) 
        short_triggers = eligible_df[eligible_df['high'] >= eligible_df['upper']]
        
        if len(long_triggers) > 0:
            print(f"\n!!! FOUND {len(long_triggers)} VALID LONG TRIGGERS !!!")
            print(long_triggers[['datetime', 'low', 'lower', 'close', 'adx']])
            
        if len(short_triggers) > 0:
            print(f"\n!!! FOUND {len(short_triggers)} VALID SHORT TRIGGERS !!!")
            print(short_triggers[['datetime', 'high', 'upper', 'close', 'adx']])
            
        if len(long_triggers) == 0 and len(short_triggers) == 0:
            print("\nNo entries triggered during eligible periods.")
            # Show closest approach
            eligible_df['dist_lower'] = eligible_df['low'] - eligible_df['lower']
            eligible_df['dist_upper'] = eligible_df['high'] - eligible_df['upper']
            print("\nClosest Calls:")
            print(eligible_df.nsmallest(5, 'dist_lower')[['datetime', 'low', 'lower', 'dist_lower']])
            print(eligible_df.nlargest(5, 'dist_upper')[['datetime', 'high', 'upper', 'dist_upper']])
            
    else:
        print("\nNo bars passed all filters.")

except Exception as e:
    print(f"Error: {e}")

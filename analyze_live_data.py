import pandas as pd
import numpy as np

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

try:
    df = pd.read_csv('live_data.csv')
    df['datetime'] = pd.to_datetime(df['datetime'])
    
    print(f"Total Rows: {len(df)}")
    print(f"Time Range: {df['datetime'].min()} to {df['datetime'].max()}")
    
    # Check Filters
    print("\n--- Filter Pass Rates ---")
    if 'in_rth' in df.columns:
        print(f"In RTH: {df['in_rth'].sum()} / {len(df)} ({df['in_rth'].mean():.1%})")
    if 'in_maintenance' in df.columns:
        print(f"Not Maintenace: {(~df['in_maintenance']).sum()} / {len(df)}")
    if 'volume_filter' in df.columns:
        print(f"Volume Filter Pass: {df['volume_filter'].sum()} / {len(df)} ({df['volume_filter'].mean():.1%})")
    if 'atr_filter' in df.columns:
        print(f"ATR Filter Pass: {df['atr_filter'].sum()} / {len(df)} ({df['atr_filter'].mean():.1%})")
        
    # Check Combined Entry Conditions (approximate)
    # We don't have the exact entry signal column, but we can infer
    
    # Check Proximity to Bands
    df['dist_lower'] = df['low'] - df['lower']
    df['dist_upper'] = df['high'] - df['upper']
    
    print("\n--- Band Proximity (Last 10 bars) ---")
    print(df[['datetime', 'close', 'lower', 'upper', 'dist_lower', 'dist_upper']].tail(10))
    
    print("\n--- Filter Status (Last 10 bars) ---")
    filter_cols = [c for c in ['in_rth', 'volume_filter', 'atr_filter'] if c in df.columns]
    print(df[['datetime'] + filter_cols].tail(10))

    # Check for potential missed entries
    # Touch Lower (Long)
    touches_lower = df[df['low'] <= df['lower']]
    print(f"\nPotential Long Triggers (Low <= Lower): {len(touches_lower)}")
    if len(touches_lower) > 0:
        print(touches_lower[['datetime', 'close', 'lower', 'volume_filter', 'atr_filter']])

    # Touch Upper (Short)
    touches_upper = df[df['high'] >= df['upper']]
    print(f"\nPotential Short Triggers (High >= Upper): {len(touches_upper)}")
    if len(touches_upper) > 0:
        print(touches_upper[['datetime', 'close', 'upper', 'volume_filter', 'atr_filter']])

except Exception as e:
    print(f"Error analyzing CSV: {e}")

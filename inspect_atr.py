import pandas as pd
import numpy as np

pd.set_option('display.max_columns', None)
try:
    df = pd.read_csv('live_data.csv')
    
    # We recorded 'atr_ts' (Trailing Stop ATR). 
    # The filter usually uses a different ATR length, but this gives us a proxy.
    
    # Check simple stats of ATR
    if 'atr_ts' in df.columns:
        print("\n--- ATR Statistics ---")
        print(df['atr_ts'].describe())
        print("\n--- Last 10 ATR Values ---")
        print(df[['datetime', 'atr_ts', 'atr_filter']].tail(10))
        
    if 'atr_filter' in df.columns:
         print("\n--- ATR Filter Status ---")
         # 'atr_filter' is a boolean result (True/False)
         pass_count = df['atr_filter'].sum()
         print(f"Pass Count: {pass_count} / {len(df)}")

except Exception as e:
    print(e)

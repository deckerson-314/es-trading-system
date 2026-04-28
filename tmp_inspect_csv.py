import pandas as pd
import os

DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'
if os.path.exists(DATA_CSV):
    print("Loading large CSV (subset)...")
    # Read just around 2024
    df = pd.read_csv(DATA_CSV, header=None, names=['datetime', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['datetime'])
    
    mask_2024 = (df['datetime'] >= '2024-01-01') & (df['datetime'] <= '2024-01-02')
    df_2024 = df[mask_2024]
    
    print("\nData for start of 2024:")
    print(df_2024.head().to_string())
    print("\nRows in 2024 window:", len(df_2024))
    
    # Check for US/Eastern conversion matching optimize.py
    # df['datetime'] = df['datetime'].dt.tz_localize('UTC').dt.tz_convert('US/Eastern').dt.tz_localize(None)
    # Let's see what optimize.py would see after its normalization
    dt_sample = df_2024['datetime'].iloc[0]
    print("\nOriginal Sample DT:", dt_sample)
    localized = pd.Timestamp(dt_sample).tz_localize('UTC').tz_convert('US/Eastern').tz_localize(None)
    print("After optimize.py normalization:", localized)

else:
    print("File definitely does not exist in the CWD.")

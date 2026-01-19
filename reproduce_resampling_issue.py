
import pandas as pd
import numpy as np

# Simulation: Data feed provides 1-min bars.
# 12:58:00 (Completed)
# 12:59:00 (Completed)
# 13:00:00 (Partial / Just Started)

data = [
    # datetime, open, high, low, close, volume (Hist Values)
    ('2026-01-05 12:58:00', 6952.75, 6953.25, 6952.50, 6953.25, 324),
    ('2026-01-05 12:59:00', 6953.25, 6955.25, 6953.25, 6954.50, 390),
    # 13:00 Partial Bar (Snapshot at 5s)
    # Assume price opened at 6955.00 and hasn't moved much yet.
    ('2026-01-05 13:00:00', 6955.00, 6955.25, 6955.00, 6955.00, 100) 
]

df = pd.DataFrame(data, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
df['datetime'] = pd.to_datetime(df['datetime'])
df.set_index('datetime', inplace=True)

print("--- Input Data (Last row is Partial) ---")
print(df)

# Logic from strategy_v4.py
timeframe = 2
df_resampled = df.resample(f'{timeframe}T', label='right', closed='left').agg({
    'open': 'first',
    'high': 'max',
    'low': 'min',
    'close': 'last',
    'volume': 'sum'
})

print("\n--- Resampled Data (2-min, Right/Right) ---")
print(df_resampled)

# Check 13:00 bucket
if pd.Timestamp('2026-01-05 13:00:00') in df_resampled.index:
    row = df_resampled.loc['2026-01-05 13:00:00']
    print("\n--- 13:00 Aggregated Bucket Analysis ---")
    print(f"Close: {row['close']}")
    print(f"Volume: {row['volume']}")
    
    if row['close'] == 6955.00:
        print("\n[VERDICT] CORRUPTION CONFIRMED!")
        print("The 13:00 Bucket closed with the 13:00 Partial Bar price (6955.00)")
        print("Instead of the 12:59 Bar Close (6954.50) or 13:00 Bar Close (Hist value 6953.75)")
    else:
        print("\n[VERDICT] No corruption? Close is", row['close'])
else:
    print("13:00 Bucket not created?")


import pandas as pd
import numpy as np

# Load 1-min Historical Data
csv_path = r'c:\Trading\recent_warmup_data.csv'
df = pd.read_csv(csv_path, index_col=0, parse_dates=True)

# Filter for Jan 5
df = df.loc['2026-01-05'].copy()

# Convert timezones (Central to Eastern to match Log)
if df.index.tz is not None:
    df.index = df.index.tz_convert('US/Eastern').tz_localize(None)

# Resample to 2-min using Backtest Defaults (Left/Left)
resampled = df.resample('2T', label='left', closed='left').agg({
    'open': 'first',
    'high': 'max',
    'low': 'min',
    'close': 'last',
    'volume': 'sum'
})

print("\n--- Aggregated Historical Data (2-min, Left/Left) ---")
print(resampled.loc['2026-01-05 12:56':'2026-01-05 13:04'])

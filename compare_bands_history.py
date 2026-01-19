
import pandas as pd
import numpy as np

# Load Live Data
print("Loading Live Data...")
live_path = r"c:\Trading\live_logs\live_data.csv"
try:
    # Use on_bad_lines to skip malformed rows if any
    df_live = pd.read_csv(live_path, on_bad_lines='skip')
except Exception as e:
    print(f"Error loading live data: {e}")
    exit()

# Parse datetime (assuming ISO format with potential timezone)
df_live['datetime'] = pd.to_datetime(df_live['datetime'], utc=True).dt.tz_convert('US/Eastern').dt.tz_localize(None)

# Load Hist Data (Backtest)
print("Loading Hist Data...")
hist_path = r"c:\Trading\ES_1min_Dec29_31_EXTENDED.csv"
df_hist = pd.read_csv(hist_path)
df_hist.columns = [c.lower() for c in df_hist.columns]
# Hist is CT. Convert to ET (CT+1)
df_hist['datetime'] = pd.to_datetime(df_hist['datetime']).dt.tz_localize(None) + pd.Timedelta(hours=1)

# Target Window: 12:36 ET to 13:16 ET (40 mins)
start_dt = pd.Timestamp("2025-12-30 12:36:00")
end_dt = pd.Timestamp("2025-12-30 13:16:00")

print(f"\nComparing Window: {start_dt} to {end_dt}")

# Filter
live_segment = df_live[(df_live['datetime'] >= start_dt) & (df_live['datetime'] <= end_dt)].copy()
hist_segment = df_hist[(df_hist['datetime'] >= start_dt) & (df_hist['datetime'] <= end_dt)].copy()

# Set index
live_segment.set_index('datetime', inplace=True)
hist_segment.set_index('datetime', inplace=True)

# Resample Live to 1min (ensure distinct)
# Live logs might be duplicates or irregular.
live_1min = live_segment[~live_segment.index.duplicated(keep='last')].resample('1min').last()

print(f"Live Rows: {len(live_1min)}")
print(f"Hist Rows: {len(hist_segment)}")

# Merge
comparison = pd.merge(live_1min[['close']], hist_segment[['close']], left_index=True, right_index=True, suffixes=('_live', '_hist'), how='outer')

print(f"Merged Rows: {len(comparison)}")
print(comparison.head())
print(comparison.tail())

# Calculate diff
comparison['diff'] = comparison['close_live'] - comparison['close_hist']

# Show discrepancies > 0.25 (1 tick)
divergence = comparison[comparison['diff'].abs() > 0.01]

print("\n--- Price Comparison (Close) ---")
print(comparison)

print("\n--- Significant Divergences ---")
print(divergence)

if len(divergence) > 0:
    print("\nCONCLUSION: Input data differed in the rolling window.")
else:
    print("\nCONCLUSION: Input prices MATCH. Calculation difference must be logic/resampling.")

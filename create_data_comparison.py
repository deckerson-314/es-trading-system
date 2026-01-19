
import pandas as pd
import re
import os

# 1. Parse Log File
log_path = r'c:\Trading\paper_logs\ib_execution.log'
log_data = []

print("Parsing Log File...")
# Regex to capture: Time, O, H, L, C, Vol
# Pattern: [2-min bar] 13:00:00 | O: 6953.25 H: 6955.25 L: 6953.00 C: 6955.00 | Vol: 1356
pattern = re.compile(r'(\d{2}:\d{2}:\d{2})\s+\|\s+O:\s+([\d\.]+)\s+H:\s+([\d\.]+)\s+L:\s+([\d\.]+)\s+C:\s+([\d\.]+)\s+\|\s+Vol:\s+([\d,]+)')

# Date for context (Jan 5)
target_date_str = "2026-01-05"

with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        if target_date_str in line and "bar]" in line:
             match = pattern.search(line)
             if match:
                 time_str = match.group(1)
                 o = float(match.group(2))
                 h = float(match.group(3))
                 l = float(match.group(4))
                 c = float(match.group(5))
                 v = int(match.group(6).replace(',', ''))
                 
                 dt_str = f"{target_date_str} {time_str}"
                 log_data.append({
                     'datetime': pd.to_datetime(dt_str),
                     'Live_Open': o,
                     'Live_High': h,
                     'Live_Low': l,
                     'Live_Close': c,
                     'Live_Vol': v
                 })

live_df = pd.DataFrame(log_data)
if not live_df.empty:
    live_df.set_index('datetime', inplace=True)
    print(f"Loaded {len(live_df)} bars from Log.")
else:
    print("No bars found in Log.")

# 2. Parse CSV File (Backtest Data)
csv_path = r'c:\Trading\recent_warmup_data.csv'
print("Parsing CSV File...")
csv_df = pd.read_csv(csv_path, index_col=0, parse_dates=True)

# Filter for Jan 5
csv_df = csv_df.loc['2026-01-05']

# CSV is likely Central (-06:00). Logs are Eastern (-05:00).
# Convert CSV to Eastern-Naive for matching
if csv_df.index.tz is not None:
    # Convert to Eastern then drop tz
    csv_df = csv_df.tz_convert('US/Eastern').tz_localize(None)

print(f"Loaded {len(csv_df)} bars from CSV (Jan 5).")

# 3. Merge
# Note: Log might be 2-min bars? User said "parameters set for 2-minute bars".
# But CSV is 1-minute bars.
# We should resample CSV to 2-min to match Log?
# Or check if Log contains 1-min bars too?
# Step 18413 showed "[2-min bar]".
# Step 18339 showed "[1-min bar]".
# It seems mixed? Or depends on config.
# We will match exact timestamps first.

merged = pd.merge(live_df, csv_df, left_index=True, right_index=True, how='outer', suffixes=('_Live', '_Hist'))

# Calculate Diffs
merged['Diff_Close'] = merged['Live_Close'] - merged['close']
merged['Diff_Vol'] = merged['Live_Vol'] - merged['volume']

# Select Output Columns
out_cols = [
    'Live_Open', 'open', 
    'Live_High', 'high', 
    'Live_Low', 'low', 
    'Live_Close', 'close', 'Diff_Close',
    'Live_Vol', 'volume', 'Diff_Vol'
]

output_path = r'c:\Trading\data_comparison_Jan5.csv'
merged[out_cols].to_csv(output_path)
print(f"Saved side-by-side comparison to {output_path}")

# Print sample around 13:00
print("\nSample Data (12:55 - 13:05):")
print(merged.loc['2026-01-05 12:55':'2026-01-05 13:05'][['Live_Close', 'close', 'Diff_Close']].to_string())

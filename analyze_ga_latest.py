import pandas as pd
import glob
import os

# Find latest results file
search_path = r"c:\Trading\Bollinger\parameters\genetic_results_*.csv"
files = glob.glob(search_path)
files.sort(key=os.path.getmtime, reverse=True)

if not files:
    print("No result files found.")
    exit()

latest_file = files[0]
print(f"Analyzing: {latest_file}")

try:
    df = pd.read_csv(latest_file)
except Exception as e:
    print(f"Error reading CSV: {e}")
    exit()

# Print columns to verify names
# print("Columns:", df.columns.tolist())

# Sort by Sortino Ratio or Total PnL
# Assuming columns exist. If not, print columns and exit.
sort_col = 'Sortino Ratio' if 'Sortino Ratio' in df.columns else 'Total PnL'
if sort_col not in df.columns:
    print(f"Sort column {sort_col} not found. Available: {df.columns.tolist()}")
    exit()

df_sorted = df.sort_values(by=sort_col, ascending=False)
top_20 = df_sorted.head(20)

print(f"\n--- Top 20 Solutions (Sorted by {sort_col}) ---")
print(top_20[[sort_col, 'Total PnL', 'Win Rate', 'Avg Trades/Day']].to_string())

# Analyze Filters
filters = [
    'Enable Trailing Stop', 
    'Enable Trend Filter', 
    'Enable ADX Filter', 
    'Enable RTH Filter',
    'Enable RSI Filter',
    'Enable VWAP Filter'
]

print("\n--- Filter Usage in Top 20 ---")
for f in filters:
    if f in top_20.columns:
        counts = top_20[f].value_counts()
        print(f"\n{f}:")
        print(counts)
    else:
        print(f"\n{f}: Not found in columns")

# Check correlation between Filters and Trades/Day
print("\n--- Trades/Day Stats vs Filters ---")
print(f"Mean Trades/Day (Top 20): {top_20['Avg Trades/Day'].mean()}")
print(f"Min Trades/Day  (Top 20): {top_20['Avg Trades/Day'].min()}")

if 'Enable Trailing Stop' in top_20.columns:
    print("\nAvg PnL with Trailing Stop ON vs OFF (Top 20):")
    print(top_20.groupby('Enable Trailing Stop')['Total PnL'].mean())

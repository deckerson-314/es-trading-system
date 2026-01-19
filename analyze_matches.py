import pandas as pd
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

df = pd.read_csv('c:/Trading/comparison_metrics_sequential.csv')
# Filter for 1/7 and 1/8
df['Live Time'] = pd.to_datetime(df['Live Time'])
df = df[df['Live Time'].dt.strftime('%Y-%m-%d').isin(['2026-01-07', '2026-01-08'])]

matches = df[df['Status'] == 'MATCHED'].copy()
print("=== MATCHED TRADES ANALYSIS (1/7 & 1/8) ===")
print(f"Total Matches: {len(matches)}")
if not matches.empty:
    matches['Price Diff'] = matches['Live Price'] - matches['BT Price']
    matches['PnL Diff'] = matches['Live PnL'] - matches['BT PnL']
    
    print("\nDetailed Match Data:")
    print(matches[['Live Time', 'BT Time', 'Live Price', 'BT Price', 'Price Diff', 'Live PnL', 'BT PnL']].to_string())
    
    print("\nStatistics:")
    print(f"Avg Price Diff: {matches['Price Diff'].abs().mean():.2f}")
    print(f"Max Price Diff: {matches['Price Diff'].abs().max():.2f}")

unmatched = df[df['Status'] != 'MATCHED']
print("\n=== UNMATCHED TRADES ===")
print(unmatched[['Live Time', 'Status', 'Live PnL']].to_string())

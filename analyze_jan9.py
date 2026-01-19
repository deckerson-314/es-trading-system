import pandas as pd
import numpy as np

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)
pd.set_option('display.max_colwidth', 50)

df = pd.read_csv('c:/Trading/comparison_metrics_sequential.csv')
df['Live Time'] = pd.to_datetime(df['Live Time'])

# Filter for 1/9
mask = (df['Status'] == 'MATCHED') & (df['Live Time'].dt.strftime('%Y-%m-%d') == '2026-01-09')
matches = df[mask].copy()

matches['PnL Diff'] = matches['Live PnL'] - matches['BT PnL']
matches['Dur Diff'] = pd.to_timedelta(matches['Live Dur']) - pd.to_timedelta(matches['BT Dur'])
matches['Dur Diff Mins'] = matches['Dur Diff'].dt.total_seconds() / 60

# Sort by Time
matches = matches.sort_values('Live Time').reset_index(drop=True)

print("=== MATCHED TRADES ANALYSIS (1/9) ===")
print(f"Total Matches: {len(matches)}")

# Write to file to ensure full output
with open('c:/Trading/jan9_analysis.txt', 'w') as f:
    f.write("=== MATCHED TRADES ANALYSIS (1/9) ===\n")
    f.write(f"Total Matches: {len(matches)}\n\n")
    f.write("Details:\n")
    f.write(f"{'Index':<5} {'Live Time':<20} {'BT Time':<20} {'Live PnL':>10} {'BT PnL':>10} {'PnL Diff':>10} {'Diff(M)':>10} {'BT Reason':<20}\n")
    for idx, row in matches.iterrows():
        f.write(f"{idx:<5} {str(row['Live Time']):<20} {str(row['BT Time']):<20} {row['Live PnL']:>10.2f} {row['BT PnL']:>10.2f} {row['PnL Diff']:>10.2f} {row['Dur Diff Mins']:>10.1f} {row['BT Reason']:<20}\n")

    f.write("\nStats:\n")
    if not matches.empty:
        f.write(f"Avg PnL Diff: {matches['PnL Diff'].mean():.2f}\n")
        f.write(f"Avg Duration Diff (Mins): {matches['Dur Diff Mins'].mean():.2f}\n")
        
        # Analyze TP Opp BB specifically
        tp_matches = matches[matches['BT Reason'] == 'TP Opp BB']
        if not tp_matches.empty:
            f.write(f"\nTP Opp BB Stats ({len(tp_matches)} trades):\n")
            f.write(f"Avg PnL Diff: {tp_matches['PnL Diff'].mean():.2f}\n")
            f.write(f"Avg Duration Diff: {tp_matches['Dur Diff Mins'].mean():.2f} mins\n")
    
print("Saved to c:/Trading/jan9_analysis.txt")

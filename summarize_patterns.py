import pandas as pd
import numpy as np

df = pd.read_csv('c:/Trading/comparison_metrics_sequential.csv')
df['Live Time'] = pd.to_datetime(df['Live Time'])

mask = (df['Status'] == 'MATCHED') & (df['Live Time'].dt.strftime('%Y-%m-%d').isin(['2026-01-07', '2026-01-08']))
matches = df[mask].copy()

matches['PnL Diff'] = matches['Live PnL'] - matches['BT PnL']
matches['Dur Diff'] = pd.to_timedelta(matches['Live Dur']) - pd.to_timedelta(matches['BT Dur'])
matches['Dur Diff Mins'] = matches['Dur Diff'].dt.total_seconds() / 60

# Filter for "TP Opp BB"
tp_matches = matches[matches['BT Reason'] == 'TP Opp BB'].copy()

print(f"Total TP Opp BB Matches: {len(tp_matches)}")

if not tp_matches.empty:
    avg_pnl_diff = tp_matches['PnL Diff'].mean()
    avg_dur_diff = tp_matches['Dur Diff Mins'].mean()
    
    better_pnl = len(tp_matches[tp_matches['PnL Diff'] > 0])
    worse_pnl = len(tp_matches[tp_matches['PnL Diff'] < 0])
    
    early_exit = len(tp_matches[tp_matches['Dur Diff Mins'] < -1])
    late_exit = len(tp_matches[tp_matches['Dur Diff Mins'] > 1])
    
    print(f"Avg PnL Diff: {avg_pnl_diff:.2f}")
    print(f"Avg Duration Diff (Mins): {avg_dur_diff:.2f}")
    print(f"Live PnL Better: {better_pnl}, Worse: {worse_pnl}")
    print(f"Live Exited Early: {early_exit}, Late: {late_exit}")
    
    print("\nIndividual Trades (TP Opp BB):")
    for idx, row in tp_matches.iterrows():
        print(f"Live: {row['Live Dur']}, BT: {row['BT Dur']}, DurDiff: {row['Dur Diff Mins']:.1f}m, PnL Diff: {row['PnL Diff']:.2f}")

matches.to_csv('c:/Trading/temp_matches_dump.csv')
print("Dumped matches to temp_matches_dump.csv")

import pandas as pd

df = pd.read_csv('c:/Trading/comparison_metrics_sequential.csv')
df['Live Time'] = pd.to_datetime(df['Live Time'])

mask = (df['Status'] == 'MATCHED') & (df['Live Time'].dt.strftime('%Y-%m-%d') == '2026-01-09')
matches = df[mask].copy()

matches.to_csv('c:/Trading/jan9_matches.csv', index=False)
print("Saved c:/Trading/jan9_matches.csv")

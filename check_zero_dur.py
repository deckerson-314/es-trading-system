import pandas as pd

df = pd.read_csv('c:/Trading/comparison_metrics_sequential.csv')
# 'BT Dur' format usually '0 days 00:02:00'
zero_dur = df[df['BT Dur'].str.contains('00:00:00', na=False)]

print(f"Total 0-Second Trades: {len(zero_dur)}")
if not zero_dur.empty:
    print(zero_dur[['BT Time', 'BT Dur', 'BT Reason', 'BT PnL']].head(10))

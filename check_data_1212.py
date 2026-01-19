import pandas as pd
df = pd.read_csv('c:\\Trading\\temp_combined_data.csv', index_col=0, parse_dates=True)
print(df.loc['2026-01-15 12:12:00'])

import pandas as pd
import os

def debug_parse(csv_path):
    df = pd.read_csv(csv_path)
    df['Time'] = pd.to_datetime(df['Time'])
    print(f"Time type: {type(df['Time'].iloc[0])}")
    print(f"Time tz: {df['Time'].dt.tz}")
    
    analysis_start = pd.Timestamp("2026-03-27 09:30:00")
    print(f"Analysis start type: {type(analysis_start)}")
    print(f"Analysis start tz: {analysis_start.tz}")
    
    # Check if there are any trades in the window before parsing
    window_df = df[
        (df['Time'] >= analysis_start) & 
        (df['Time'] <= pd.Timestamp("2026-03-27 11:00:00"))
    ]
    print(f"Fills in window: {len(window_df)}")
    
    # ... previous debug logic ...
    df_window = window_df.sort_values(['Time', 'Side'], ascending=[True, True])
    net_pos = 0
    trades_count = 0
    for _, row in df_window.iterrows():
        side_sign = 1 if row['Side'] == 'BOT' else -1
        qty = row['Qty']
        prev_pos = net_pos
        net_pos += side_sign * qty
        if prev_pos != 0 and net_pos == 0:
            trades_count += 1
    
    print(f"Completed trades detected in window: {trades_count}")

if __name__ == "__main__":
    debug_parse(r'c:\Trading\paper_logs\live_trades.csv')

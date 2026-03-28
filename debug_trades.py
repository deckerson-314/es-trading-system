import pandas as pd
import os

def debug_parse(csv_path):
    df = pd.read_csv(csv_path)
    df['Time'] = pd.to_datetime(df['Time'])
    df = df[df['Time'].dt.date == pd.Timestamp('2026-03-27').date()]
    df['Price'] = df['Price'].astype(float)
    df['Qty'] = df['Qty'].astype(float)
    df = df.sort_values(['Time', 'Side'], ascending=[True, True])
    
    net_pos = 0
    print(f"{'Time':20} {'Side':5} {'Qty':5} {'Price':10} {'NetPos':8}")
    print("-" * 55)
    
    for _, row in df.iterrows():
        side_sign = 1 if row['Side'] == 'BOT' else -1
        qty = row['Qty']
        net_pos += side_sign * qty
        print(f"{str(row['Time']):20} {row['Side']:5} {qty:5} {row['Price']:10.2f} {net_pos:8.1f}")

if __name__ == "__main__":
    debug_parse(r'c:\Trading\paper_logs\live_trades.csv')

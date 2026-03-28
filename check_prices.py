import pandas as pd
import sys
sys.path.insert(0, '.')
from compare_paper_backtest_trend import parse_live_trades_csv

trades = parse_live_trades_csv(r'paper_logs\live_trades.csv')
trades['live_entry_time'] = pd.to_datetime(trades['live_entry_time'])
today = trades[trades['live_entry_time'].dt.date == pd.Timestamp('2026-03-27').date()]
print(f"Total today: {len(today)}")

# Also show the raw fills for comparison
raw = pd.read_csv(r'paper_logs\live_trades.csv')
raw['Time'] = pd.to_datetime(raw['Time'])
raw_today = raw[raw['Time'].dt.date == pd.Timestamp('2026-03-27').date()].head(10)

print("\nRaw fills (first 10 today):")
for _, r in raw_today.iterrows():
    print(f"  {r['Time'].strftime('%H:%M:%S')} {r['Side']:3s} @ {float(r['Price']):.2f} PnL={float(r['RealizedPNL']):.2f}")

print("\nParsed trades (first 14):")
for i, row in today.head(14).iterrows():
    print(f"  #{i}: {row['live_entry_time'].strftime('%H:%M:%S')} dir={int(row['live_direction']):+d} entry={row['live_entry_price']:.2f} exit={row['live_exit_price']:.2f} pnl={row['live_pnl']:.1f}")

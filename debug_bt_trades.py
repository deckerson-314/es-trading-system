"""
debug_bt_trades.py - Check what backtest actually produces for today
"""
import pandas as pd, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_paper_backtest_trend import load_trend_params
from backtest import run_backtest

# Prepare data (OHLCV only, correct TZ)
df = pd.read_csv(r'c:\Trading\paper_logs\live_data.csv', index_col=0, parse_dates=True)
df.columns = [c.lower().strip() for c in df.columns]
df = df[['open', 'high', 'low', 'close', 'volume']]
df = df[~df.index.duplicated(keep='last')]
df.index = pd.to_datetime(df.index, utc=True)
df.index = df.index.tz_convert('US/Eastern').tz_localize(None)
df = df.dropna()
df.to_csv(r'c:\Trading\temp_tz_debug.csv')

params = load_trend_params(r'c:\Trading\strategies\trend\parameters\trend_strategy_params_testing_ultra_high.csv')
results = run_backtest('trend', r'c:\Trading\temp_tz_debug.csv', params, suppress_log=True)
bt_trades = results.get('trades_df', pd.DataFrame())

# Filter to today
today_bt = bt_trades[bt_trades['entry_time'].dt.date == pd.Timestamp('2026-03-27').date()]
today_bt = today_bt.sort_values('entry_time')

# Also load paper trades
paper = pd.read_csv(r'c:\Trading\paper_logs\live_trades.csv')
paper['Time'] = pd.to_datetime(paper['Time'])
today_paper = paper[paper['Time'].dt.date == pd.Timestamp('2026-03-27').date()]

print(f"BT trades today: {len(today_bt)}")
print(f"Paper fills today: {len(today_paper)}")

# Print all BT trades today with entry prices
print(f"\n{'='*100}")
print(f"BACKTEST TRADES (today only, first 30):")
print(f"{'='*100}")
for i, (_, t) in enumerate(today_bt.head(30).iterrows()):
    d = 'LONG' if t['direction'] == 1 else 'SHORT'
    print(f"  {i+1:3d}. {t['entry_time']} | {d:5s} | Entry={t['entry_price']:8.2f} | Exit={t['exit_price']:8.2f} | {t.get('reason','')}")

# Print all paper fills today
print(f"\n{'='*100}")
print(f"PAPER FILLS (today only, first 30):")
print(f"{'='*100}")
for i, (_, t) in enumerate(today_paper.head(30).iterrows()):
    print(f"  {i+1:3d}. {t['Time']} | {t['Side']:3s} | Price={t['Price']:8.2f} | PnL={t['RealizedPNL']}")

# Now do price-based matching: for each paper fill, find the closest BT trade by price
print(f"\n{'='*100}")
print(f"PRICE-BASED MATCHING (paper fill -> nearest BT trade by entry price):")
print(f"{'='*100}")

if len(today_bt) > 0 and len(today_paper) > 0:
    for i, (_, p) in enumerate(today_paper.head(20).iterrows()):
        if float(p['RealizedPNL']) != 0:
            continue  # skip exits
        p_price = float(p['Price'])
        p_time = p['Time']
        p_side = p['Side']
        
        # Find BT trades with entry price within 1 point
        near = today_bt[abs(today_bt['entry_price'] - p_price) <= 1.0]
        if len(near) > 0:
            best = near.iloc[(near['entry_price'] - p_price).abs().argsort().iloc[0]]
            time_diff = (p_time - best['entry_time']).total_seconds()
            dir_match = (p_side == 'BOT' and best['direction'] == 1) or (p_side == 'SLD' and best['direction'] == -1)
            bt_dir = 'LONG' if best['direction'] == 1 else 'SHORT'
            print(f"  Paper {p_time.strftime('%H:%M:%S')} {p_side} @ {p_price:.2f} "
                  f"<-> BT {best['entry_time'].strftime('%H:%M:%S')} {bt_dir} @ {best['entry_price']:.2f} "
                  f"| dt={time_diff:+.0f}s | dir={'OK' if dir_match else 'MISMATCH'}")
        else:
            print(f"  Paper {p_time.strftime('%H:%M:%S')} {p_side} @ {p_price:.2f} "
                  f"<-> NO BT TRADE within 1pt")

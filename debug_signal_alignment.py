"""
debug_signal_alignment.py - Check if backtest produces signals at the SAME times
"""
import pandas as pd, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_paper_backtest_trend import load_trend_params
from strategies.trend.strategy import TrendStrategy

# Load and prepare data EXACTLY as backtest.py does
df = pd.read_csv(r'c:\Trading\paper_logs\live_data.csv', index_col=0, parse_dates=True)
df.columns = [c.lower().strip() for c in df.columns]
df = df[['open', 'high', 'low', 'close', 'volume']]
df = df[~df.index.duplicated(keep='last')]
df.index = pd.to_datetime(df.index, utc=True)
df.index = df.index.tz_convert('US/Eastern').tz_localize(None)
df = df.dropna()

params = load_trend_params(r'c:\Trading\strategies\trend\parameters\trend_strategy_params_testing_ultra_high.csv')
strategy = TrendStrategy(params)

# Calculate indicators on today's data (with warmup from previous days)
today = pd.Timestamp('2026-03-27')
# Use a window that gives enough warmup
warmup_start = today - pd.Timedelta(days=2)
window = df[df.index >= warmup_start]

print(f"Data window: {window.index[0]} to {window.index[-1]} ({len(window)} bars)")
print(f"Strategy lookback: buy={strategy.lookback_buy}, sell={strategy.lookback_sell}")

df_ind = strategy.calculate_indicators(window.copy())
print(f"After calculate_indicators: {len(df_ind)} rows")

long_sigs, short_sigs = strategy.calculate_entry_signals(df_ind)

# Get today's signals only
today_mask = df_ind.index.date == today.date()
today_ind = df_ind[today_mask]
today_long = long_sigs[today_mask]
today_short = short_sigs[today_mask]

print(f"\nToday's signals: {today_long.sum()} LONG, {today_short.sum()} SHORT")

# Load paper trades
paper = pd.read_csv(r'c:\Trading\paper_logs\live_trades.csv')
paper['Time'] = pd.to_datetime(paper['Time'])
today_paper = paper[paper['Time'].dt.date == today.date()]

# For each paper entry, check if there's a signal at that exact time
print(f"\n{'='*110}")
print(f"SIGNAL CHECK AT PAPER TRADE TIMES:")
print(f"{'='*110}")

entry_fills = today_paper[today_paper['RealizedPNL'] == 0].head(20)
for _, fill in entry_fills.iterrows():
    fill_time = fill['Time']
    fill_price = float(fill['Price'])
    fill_side = fill['Side']
    
    # Find the bar at or just before the fill time (the "completed bar" the bot would check)
    bar_before = today_ind[today_ind.index <= fill_time]
    
    if len(bar_before) >= 2:
        # The live bot uses index[-2] (completed bar)
        completed_bar = bar_before.iloc[-2]
        completed_time = bar_before.index[-2]
        
        # Get signal at that bar
        long_sig = today_long.loc[completed_time] if completed_time in today_long.index else False
        short_sig = today_short.loc[completed_time] if completed_time in today_short.index else False
        
        dc_h = completed_bar.get('donchian_high', 0)
        dc_l = completed_bar.get('donchian_low', 0)
        
        signal = 'LONG' if long_sig else ('SHORT' if short_sig else 'NONE')
        expected = 'SHORT' if fill_side == 'SLD' else 'LONG'
        match = signal == expected
        
        print(f"  Fill {fill_time.strftime('%H:%M:%S')} {fill_side} @ {fill_price:.2f} | "
              f"Completed bar: {completed_time.strftime('%H:%M:%S')} | "
              f"DC: H={dc_h:.2f} L={dc_l:.2f} | "
              f"Signal: {signal} | Expected: {expected} | {'OK' if match else 'MISMATCH'}")
    else:
        print(f"  Fill {fill_time.strftime('%H:%M:%S')} {fill_side} @ {fill_price:.2f} | "
              f"Not enough bars before this time")

# Show ALL signals in the 9:30-10:00 window
print(f"\n{'='*110}")
print(f"ALL SIGNALS 09:30-10:30 ET:")
print(f"{'='*110}")
morning = today_ind[(today_ind.index.hour >= 9) & (today_ind.index.hour <= 10)]
for ts in morning.index:
    row = morning.loc[ts]
    l = today_long.loc[ts] if ts in today_long.index else False
    s = today_short.loc[ts] if ts in today_short.index else False
    if l or s:
        sig = 'LONG' if l else 'SHORT'
        dc_h = row.get('donchian_high', 0)
        dc_l = row.get('donchian_low', 0)
        print(f"  {ts.strftime('%H:%M')} | {sig:5s} | "
              f"H={row['high']:.2f} L={row['low']:.2f} C={row['close']:.2f} | "
              f"DC_H={dc_h:.2f} DC_L={dc_l:.2f}")

# Now check: does the LIVE bot use index[-2] (monitoring.py line 238)?
print(f"\n{'='*110}")
print(f"CRITICAL: Live bot signal bar offset check")
print(f"{'='*110}")
print(f"  monitoring.py line 238: completed_idx = data_ind.index[-2]")
print(f"  This means the live bot triggers on the COMPLETED bar (bar before current)")
print(f"  backtest.py line 221-225: checks entry signals on CURRENT bar, executes on NEXT bar")
print(f"  This is a 1-bar offset between live and backtest!")

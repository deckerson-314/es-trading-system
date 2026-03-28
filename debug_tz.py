"""
debug_tz.py — Timezone forensics for paper vs backtest comparison
"""
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 90)
print("PART 1: RAW TIMESTAMPS from live_data.csv")
print("=" * 90)

raw = pd.read_csv(r'c:\Trading\paper_logs\live_data.csv')
col0 = raw.columns[0]
print(f"  Column 0: '{col0}'")
print(f"  First 3 raw strings:  '{raw.iloc[0][col0]}', '{raw.iloc[1][col0]}', '{raw.iloc[2][col0]}'")
print(f"  Last 3 raw strings:   '{raw.iloc[-3][col0]}', '{raw.iloc[-2][col0]}', '{raw.iloc[-1][col0]}'")

# Check for mixed timezone offsets
offsets = raw[col0].str.extract(r'([-+]\d{2}:\d{2})$')
unique_offsets = offsets[0].dropna().unique()
print(f"  Unique TZ offsets in data: {unique_offsets}")

# Parse with utc=True (the only safe way with mixed offsets)
raw['_ts'] = pd.to_datetime(raw[col0], utc=True)
today = raw[raw['_ts'].dt.date == pd.Timestamp('2026-03-27').date()]
print(f"\n  Today's rows: {len(today)}")

# Show bars around 9:30-9:40 — both raw string AND parsed
today_930 = today[(today['_ts'].dt.hour >= 13) & (today['_ts'].dt.hour <= 14)]  # 13-14 UTC = 9-10 ET
print(f"\n  Bars around 9:30 ET (showing raw string vs UTC-parsed):")
for i in range(min(12, len(today_930))):
    row = today_930.iloc[i]
    ts_utc = row['_ts']
    ts_et = ts_utc.tz_convert('US/Eastern')
    print(f"    RAW: '{row[col0]}' -> UTC: {ts_utc} -> ET: {ts_et} | C={row['close']:.2f}")

print("\n" + "=" * 90)
print("PART 2: RAW TIMESTAMPS from live_trades.csv")
print("=" * 90)

trades = pd.read_csv(r'c:\Trading\paper_logs\live_trades.csv')
print(f"  Columns: {list(trades.columns)}")

# Check trade timestamps for TZ info
print(f"  First 5 raw trade timestamps:")
for i in range(min(5, len(trades))):
    print(f"    '{trades.iloc[i]['Time']}'")

# Are there timezone offsets in trade timestamps?
trade_offsets = trades['Time'].str.extract(r'([-+]\d{2}:\d{2})$')
trade_tz_unique = trade_offsets[0].dropna().unique()
print(f"  TZ offsets in trade timestamps: {trade_tz_unique if len(trade_tz_unique) > 0 else 'NONE (naive)'}")

trades['_ts'] = pd.to_datetime(trades['Time'])
today_tr = trades[trades['_ts'].dt.date == pd.Timestamp('2026-03-27').date()]
print(f"\n  Today's trades: {len(today_tr)}")
print(f"  First 10 today:")
for i in range(min(10, len(today_tr))):
    row = today_tr.iloc[i]
    print(f"    '{row['Time']}' | {row['Side']} @ {row['Price']} | PnL={row['RealizedPNL']}")

print("\n" + "=" * 90)
print("PART 3: THE CONVERSION PIPELINE (what backtest.py does)")
print("=" * 90)

df = pd.read_csv(r'c:\Trading\paper_logs\live_data.csv', index_col=0, parse_dates=True)
df.columns = [c.lower().strip() for c in df.columns]
df = df[['open', 'high', 'low', 'close', 'volume']]

print(f"  Step 1 — read_csv(parse_dates=True):")
print(f"    Index dtype: {df.index.dtype}")
print(f"    Index tz: {getattr(df.index, 'tz', 'NONE')}")
print(f"    Index[0]: {df.index[0]}")

# The critical question: what does pandas do with mixed-offset timestamps in the index?
# Answer: it stores them as object dtype (strings) or as a DatetimeIndex with UTC conversion
print(f"    Type of Index[0]: {type(df.index[0])}")

# Step 2: pd.to_datetime(utc=True)
df.index = pd.to_datetime(df.index, utc=True)
print(f"\n  Step 2 — pd.to_datetime(utc=True):")
print(f"    Index tz: {getattr(df.index, 'tz', 'NONE')}")
print(f"    Index[0]: {df.index[0]}")

# Step 3: tz_convert to Eastern, then strip
df.index = df.index.tz_convert('US/Eastern').tz_localize(None)
print(f"\n  Step 3 — tz_convert('US/Eastern').tz_localize(None):")
print(f"    Index[0]: {df.index[0]}")
print(f"    Index[-1]: {df.index[-1]}")

# Now show the SAME bars around 9:30-9:40 ET after pipeline
today_bt = df[df.index.date == pd.Timestamp('2026-03-27').date()]
bt_930 = today_bt[(today_bt.index.hour == 9) & (today_bt.index.minute >= 30) & (today_bt.index.minute <= 42)]
print(f"\n  BT bars at 9:30-9:42 ET after pipeline:")
for ts in bt_930.index:
    row = bt_930.loc[ts]
    print(f"    {ts} | O={row['open']:.2f} H={row['high']:.2f} L={row['low']:.2f} C={row['close']:.2f}")

print("\n" + "=" * 90)
print("PART 4: PRICE-BASED CROSS-REFERENCE (find the trade in the data)")
print("=" * 90)

# First paper trade: SLD @ 6471.00 at "2026-03-27 09:35:08"
trade_price = 6471.00
trade_time_str = '2026-03-27 09:35:08'
trade_time = pd.Timestamp(trade_time_str)

print(f"  First paper trade: {trade_time_str} SLD @ {trade_price}")
print(f"  Trade timestamp has TZ: {trade_time.tzinfo}")

# Find ALL bars today where the price range includes 6471
today_bt = df[df.index.date == pd.Timestamp('2026-03-27').date()]
price_match = today_bt[(today_bt['low'] <= trade_price) & (today_bt['high'] >= trade_price)]
print(f"\n  Bars today where H/L range includes {trade_price}:")
for ts in price_match.index[:15]:
    row = price_match.loc[ts]
    delta = (trade_time - ts).total_seconds()
    print(f"    {ts} | H={row['high']:.2f} L={row['low']:.2f} C={row['close']:.2f} | Δ from trade: {delta:+.0f}s ({delta/3600:+.1f}h)")

# If there's a systematic offset, we should see it here
if len(price_match) > 0:
    deltas = [(trade_time - ts).total_seconds() for ts in price_match.index]
    print(f"\n  Systematic offset check:")
    print(f"    Min delta: {min(deltas):+.0f}s ({min(deltas)/3600:+.1f}h)")
    print(f"    Max delta: {max(deltas):+.0f}s ({max(deltas)/3600:+.1f}h)")
    
    # Check for 4h or 5h offset (UTC vs ET)
    for offset_h in [0, 1, -1, 4, 5, -4, -5]:
        adjusted = trade_time - pd.Timedelta(hours=offset_h)
        exact = today_bt[(today_bt.index >= adjusted - pd.Timedelta(minutes=1)) & 
                         (today_bt.index <= adjusted + pd.Timedelta(minutes=1))]
        if len(exact) > 0:
            row = exact.iloc[0]
            price_ok = row['low'] <= trade_price <= row['high']
            print(f"    Offset {offset_h:+d}h → {adjusted} : "
                  f"{'✓ MATCH' if price_ok else '✗ no price match'} "
                  f"(H={row['high']:.2f} L={row['low']:.2f})")

print("\n" + "=" * 90)
print("PART 5: NOW CHECK what the raw data string says at trade time")
print("=" * 90)

# The key: what does the raw CSV string say for the bar at 9:35 ET?
raw_today = raw[pd.to_datetime(raw[col0], utc=True).dt.date == pd.Timestamp('2026-03-27').date()]
# Find the raw row closest to 9:35 ET
for i in range(len(raw_today)):
    row = raw_today.iloc[i]
    ts_str = row[col0]
    if '09:35' in ts_str:
        print(f"  Raw row containing '09:35': '{ts_str}' | C={row['close']:.2f}")
        break
    elif '13:35' in ts_str:
        print(f"  Raw row containing '13:35' (UTC?): '{ts_str}' | C={row['close']:.2f}")
        break

# Show 5 rows around the first trade time, searching by close price
for i in range(len(raw_today)):
    row = raw_today.iloc[i]
    if abs(float(row['close']) - trade_price) <= 2:
        print(f"  Raw row with close~{trade_price}: '{row[col0]}' | C={row['close']:.2f}")
        # Show context
        start = max(0, i-2)
        end = min(len(raw_today), i+3)
        for j in range(start, end):
            r = raw_today.iloc[j]
            marker = " <<<" if j == i else ""
            print(f"    '{r[col0]}' | O={r['open']:.2f} H={r['high']:.2f} L={r['low']:.2f} C={r['close']:.2f}{marker}")
        break

print("\n" + "=" * 90)
print("DONE")
print("=" * 90)

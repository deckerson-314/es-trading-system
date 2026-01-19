
import pandas as pd

# Historical Data per Minute (from c:\Trading\verify_aggregation_Jan5.py output)
# 12:56: 322 ? (Guessing similar)
# 12:57: ?
# 12:58: 324
# 12:59: 390
# 13:00: 380 (Full Minute Hist)
# 13:01: ...

# Live Log at 13:00:05 reported Vol: 1356.

# Let's see what combination sums to ~1356.
v58 = 324
v59 = 390
v00 = 380 # Full Hist
v00_partial = 100 # Hypothetical

print(f"12:58 + 12:59 = {v58 + v59} (Target Correct Volume)")
print(f"12:59 + 13:00(Full) = {v59 + v00}")
print(f"12:58 + 12:59 + 13:00(Full) = {v58 + v59 + v00}")

# If Live Log saw 1356.
# Maybe 12:56 + 12:57 + 12:58 + 12:59? (4 minutes?)
# Maybe Volume is Cumulative for the day? No, it varies up/down.
# Maybe Volume is "Count" (Ticks) vs "Size" (Contracts)?
# IB "TRADES" gives Volume (Contracts).
# "Count" is tick count.
# I will check 'barCount' in recent_warmup_data.csv.

print("\nChecking recent_warmup_data.csv for tick counts vs volume...")
try:
    df = pd.read_csv(r'c:\Trading\recent_warmup_data.csv', index_col=0, parse_dates=True)
    df = df.loc['2026-01-05 12:55':'2026-01-05 13:05']
    print(df[['volume', 'barCount']])
    
    print("\nSums:")
    print(f"Sum Vol 58-59: {df.loc['2026-01-05 12:58:00':'2026-01-05 12:59:00', 'volume'].sum()}")
    print(f"Sum Count 58-59: {df.loc['2026-01-05 12:58:00':'2026-01-05 12:59:00', 'barCount'].sum()}")
    
    # Check if 1356 matches sum of Counts?
    # Or Sum of Volumes for different range.
except Exception as e:
    print(e)

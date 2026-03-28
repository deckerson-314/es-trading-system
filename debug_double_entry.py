"""
debug_double_entry.py - Check if the bot is opening 2 positions at once
"""
import pandas as pd

paper = pd.read_csv(r'c:\Trading\paper_logs\live_trades.csv')
paper['Time'] = pd.to_datetime(paper['Time'])
today = paper[paper['Time'].dt.date == pd.Timestamp('2026-03-27').date()].copy()
today = today.sort_values(['Time', 'PermID']).reset_index(drop=True)

print(f"Total fills today: {len(today)}")
print(f"Unique PermIDs: {today['PermID'].nunique()}")

# Track the net position over time
position = 0
print(f"\n{'='*120}")
print(f"POSITION TRACKING (running net position after each fill):")
print(f"{'='*120}")

for i, (_, row) in enumerate(today.iterrows()):
    side = row['Side']
    qty = int(row['Qty'])
    if side == 'BOT':
        position += qty
    elif side == 'SLD':
        position -= qty
    
    marker = " <<<< DOUBLE!" if abs(position) > 1 else ""
    print(f"  {i+1:3d}. {row['Time']} | {side:3s} @ {row['Price']:8.2f} | PermID={row['PermID']} | NetPos={position:+d}{marker}")

print(f"\n{'='*120}")
print(f"SUMMARY:")
print(f"{'='*120}")
print(f"  Max position (abs): {today.apply(lambda r: int(r['Qty']), axis=1).sum() // 2}")

# Timeline of events - group by timestamp rounding to nearest second
print(f"\n{'='*120}")
print(f"FILLS GROUPED BY SECOND:")
print(f"{'='*120}")
today['second'] = today['Time'].dt.floor('s')
for sec, group in today.groupby('second'):
    if len(group) > 1:
        fills = []
        for _, r in group.iterrows():
            fills.append(f"{r['Side']}@{r['Price']:.2f}(Perm={r['PermID']})")
        print(f"  {sec} | {len(group)} fills: {', '.join(fills)}")

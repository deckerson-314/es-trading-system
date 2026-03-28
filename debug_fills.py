"""
debug_fills.py - Deep analysis of paper trade fills and duplicate detection
"""
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

paper = pd.read_csv(r'c:\Trading\paper_logs\live_trades.csv')
paper['Time'] = pd.to_datetime(paper['Time'])
today = paper[paper['Time'].dt.date == pd.Timestamp('2026-03-27').date()].copy()

print(f"Total fills today: {len(today)}")
print(f"Unique PermIDs today: {today['PermID'].nunique()}")

# Show ALL fills with PermID
print(f"\n{'='*120}")
print(f"ALL FILLS TODAY (with PermID for grouping):")
print(f"{'='*120}")
for i, (_, row) in enumerate(today.iterrows()):
    pnl = float(row['RealizedPNL'])
    pnl_str = f"PnL={pnl:+.2f}" if pnl != 0 else "PnL=0.00"
    print(f"  {i+1:3d}. {row['Time']} | {row['Side']:3s} @ {row['Price']:8.2f} | "
          f"Qty={row['Qty']} | {pnl_str:>14s} | PermID={row['PermID']}")

# Check for duplicate PermIDs
print(f"\n{'='*120}")
print(f"DUPLICATE PERMID CHECK:")
print(f"{'='*120}")
perm_counts = today['PermID'].value_counts()
dupes = perm_counts[perm_counts > 1]
if len(dupes) > 0:
    print(f"  {len(dupes)} PermIDs appear more than once:")
    for permid, count in dupes.items():
        rows = today[today['PermID'] == permid]
        print(f"\n  PermID {permid} (appears {count}x):")
        for _, r in rows.iterrows():
            print(f"    {r['Time']} | {r['Side']:3s} @ {r['Price']:8.2f} | PnL={float(r['RealizedPNL'])}")
else:
    print("  No duplicate PermIDs found")

# Check for near-duplicate timestamps (same second)
print(f"\n{'='*120}")
print(f"NEAR-DUPLICATE TIMESTAMP CHECK (fills within 1 second of each other):")
print(f"{'='*120}")
today_sorted = today.sort_values('Time').reset_index(drop=True)
for i in range(1, len(today_sorted)):
    prev = today_sorted.iloc[i-1]
    curr = today_sorted.iloc[i]
    delta = (curr['Time'] - prev['Time']).total_seconds()
    if delta < 1.0:
        price_diff = abs(float(curr['Price']) - float(prev['Price']))
        same_side = curr['Side'] == prev['Side']
        same_perm = curr['PermID'] == prev['PermID']
        print(f"  [{i-1}] {prev['Time']} {prev['Side']} @ {prev['Price']:.2f} | PermID={prev['PermID']}")
        print(f"  [{i}]   {curr['Time']} {curr['Side']} @ {curr['Price']:.2f} | PermID={curr['PermID']}")
        print(f"       dt={delta:.1f}s | dp={price_diff:.2f} | same_side={same_side} | same_perm={same_perm}")
        print()

# Group fills into trades properly using PermID
# Each bracket order creates: entry (PermID_A), stop (PermID_B), tp (PermID_C)
# Entry fill has its own PermID, exit fill has its own PermID
print(f"\n{'='*120}")
print(f"TRADE RECONSTRUCTION (sequential fill pairing):")
print(f"{'='*120}")

# The fills alternate: entry fill, then exit fill
# But with bracket orders, entry is a market order, exit is stop or limit
# Let's look at the pattern
position = None
trades = []
for i, (_, row) in enumerate(today_sorted.iterrows()):
    side = row['Side']
    price = float(row['Price'])
    pnl = float(row['RealizedPNL'])
    
    if position is None:
        # This should be an entry
        position = {'entry_time': row['Time'], 'entry_side': side, 'entry_price': price, 
                     'entry_permid': row['PermID']}
    else:
        # This should be the exit
        # But check: is it the OPPOSITE side?
        if (position['entry_side'] == 'BOT' and side == 'SLD') or \
           (position['entry_side'] == 'SLD' and side == 'BOT'):
            # Proper exit
            dir_str = 'LONG' if position['entry_side'] == 'BOT' else 'SHORT'
            calc_pnl = (price - position['entry_price']) * (1 if dir_str == 'LONG' else -1) * 50
            trades.append({
                'entry_time': position['entry_time'],
                'exit_time': row['Time'],
                'direction': dir_str,
                'entry_price': position['entry_price'],
                'exit_price': price,
                'calc_pnl': calc_pnl,
                'reported_pnl': pnl,
                'entry_permid': position['entry_permid'],
                'exit_permid': row['PermID']
            })
            position = None
        else:
            # Same side — could be a duplicate fill or second position
            print(f"  WARNING: Same-side fill sequence at {row['Time']}:")
            print(f"    Position: {position['entry_side']} @ {position['entry_price']:.2f}")
            print(f"    New fill: {side} @ {price:.2f}")
            # Treat the new fill as a fresh entry, abandon the old
            position = {'entry_time': row['Time'], 'entry_side': side, 'entry_price': price,
                         'entry_permid': row['PermID']}

print(f"\n  Reconstructed {len(trades)} round-trip trades:")
for i, t in enumerate(trades):
    dur = (t['exit_time'] - t['entry_time']).total_seconds()
    print(f"  {i+1:3d}. {t['entry_time'].strftime('%H:%M:%S')} -> {t['exit_time'].strftime('%H:%M:%S')} | "
          f"{t['direction']:5s} | Entry={t['entry_price']:.2f} Exit={t['exit_price']:.2f} | "
          f"CalcPnL={t['calc_pnl']:+.0f} | Duration={dur:.0f}s | "
          f"EntryPerm={t['entry_permid']} ExitPerm={t['exit_permid']}")

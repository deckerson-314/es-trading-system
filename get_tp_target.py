import pandas as pd
try:
    df = pd.read_csv('c:\\Trading\\debug_processed_df.csv', index_col=0, parse_dates=True)
    
    # Target Row (Entry Signal Generation Bar for 12:12 execution is 12:10)
    # TP derived from 12:10 Upper Band (Fixed BB Entry)
    
    ts_entry = pd.Timestamp('2026-01-15 12:12:00')
    ts_prev = pd.Timestamp('2026-01-15 12:10:00')
    
    u_prev = df.loc[ts_prev, 'upper']
    u_entry = df.loc[ts_entry, 'upper']
    
    print(f"TP ANALYSIS:")
    print(f"12:10 Upper (Expected TP): {u_prev}")
    print(f"12:12 Upper (Current Band): {u_entry}")
    
    # Check Price Action
    mask = (df.index >= ts_entry) & (df.index <= ts_entry + pd.Timedelta(hours=4))
    highs = df.loc[mask, 'high']
    
    print(f"Max High in Trade: {highs.max()}")
    
    hit_prev = (highs >= u_prev).any()
    hit_entry = (highs >= u_entry).any()
    
    print(f"Did Price hit 12:10 Upper? {hit_prev}")
    print(f"Did Price hit 12:12 Upper? {hit_entry}")
    
    if hit_prev:
        first_hit = highs[highs >= u_prev].index[0]
        print(f"First Hit (TP Time): {first_hit}")

except Exception as e:
    print(e)

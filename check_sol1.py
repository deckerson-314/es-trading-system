import pandas as pd

file_path = "Bollinger/parameters/genetic_results_2025-12-06-3.csv"
try:
    df = pd.read_csv(file_path, index_col='Name')
    
    # Scan all solution columns
    sol_cols = [c for c in df.columns if 'Solution_' in c]
    trades_per_day = []
    
    print(f"\nScanning {len(sol_cols)} solutions...")
    for col in sol_cols:
        try:
            val = df.loc['Avg Trades/Day', col]
            # Clean string
            if isinstance(val, str):
                val = val.replace('$', '').replace(',', '')
            val = float(val)
            trades_per_day.append(val)
        except:
            pass
            
    if trades_per_day:
        s = pd.Series(trades_per_day)
        print("\n=== Population Trades/Day Stats ===")
        print(f"Count: {len(s)}")
        print(f"Min: {s.min():.4f}")
        print(f"Max: {s.max():.4f}")
        print(f"Mean: {s.mean():.4f}")
        print(f"Median: {s.median():.4f}")
        print(f"Top 5 High Freq: {s.nlargest(5).tolist()}")
    else:
        print("No trade data found in any solution.")

except Exception as e:
    print(f"Error: {e}")

import pandas as pd
import glob
import os

# Find latest results file
files = glob.glob('c:/Trading/Bollinger/parameters/genetic_results_*.csv')
if not files:
    print("No results files found.")
    exit(1)

# Hardcode relevant file
latest_file = 'c:/Trading/Bollinger/parameters/genetic_results_2025-12-07-1.csv'
print(f"Analyzing file: {latest_file}")

try:
    df = pd.read_csv(latest_file)
    print(f"Columns: {list(df.columns)}")
    print(f"Total Rows: {len(df)}")
    
    # Handle transposed CSV format if needed (index is params)
    if 'Sortino' not in df.columns and 'sortino' not in df.columns and 'Sortino Ratio' not in df.columns:
         # Check if it's the transposed format where rows are params
         pass

    # Normalize column names
    df.columns = [c.strip() for c in df.columns]
    
    sortino_col = 'Sortino' if 'Sortino' in df.columns else 'Sortino Ratio'
    if sortino_col not in df.columns:
        sortino_col = 'sortino'
    
    # Filter for valid solutions (Sortino > -900)
    if sortino_col in df.columns:
        valid_df = df[df[sortino_col] > -100]
    
    if valid_df.empty:
        print("No valid solutions found yet.")
        exit()

    print(f"Valid Solutions: {len(valid_df)}")
    
    # Analyze Bollinger Band Length
    if 'Bollinger Band Length' in valid_df.columns:
        bb_len = valid_df['Bollinger Band Length']
        print(f"\n--- Bollinger Band Length Stats ---")
        print(f"Mean: {bb_len.mean():.2f}")
        print(f"Median: {bb_len.median():.2f}")
        print(f"Min: {bb_len.min()}")
        print(f"Max: {bb_len.max()}")
        print(f"Mode: {bb_len.mode().values[0]}")
        
        # Check specific buckets
        print("\nDistribution:")
        print(bb_len.value_counts().sort_index().head(10))
        
        # Correlation with Sortino
        corr = valid_df['Bollinger Band Length'].corr(valid_df['Sortino Ratio'])
        print(f"\nCorrelation with Sortino: {corr:.4f}")
        
    else:
        print("Column 'Bollinger Band Length' not found.")
        
    # Check top 10 solutions
    print("\n--- Top 5 Solutions (by Sortino) ---")
    top_5 = valid_df.sort_values('Sortino Ratio', ascending=False).head(5)
    cols = ['gen', 'Sortino Ratio', 'Avg Trades/Day', 'Bollinger Band Length', 'Bollinger Band StdDev']
    print(top_5[cols].to_string(index=False))

except Exception as e:
    print(f"Error: {e}")

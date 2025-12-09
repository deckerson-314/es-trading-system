import pandas as pd
import numpy as np
import os
import sys

# Load the latest results file
RESULTS_FILE = r"c:\Trading\Bollinger\parameters\genetic_results_2025-12-06-4.csv"

def analyze_run():
    if not os.path.exists(RESULTS_FILE):
        print(f"File not found: {RESULTS_FILE}")
        return

    print(f"Analyzing GA Results: {os.path.basename(RESULTS_FILE)}")
    
    try:
        # Read the CSV - The first column 'Name' should be the index
        df_raw = pd.read_csv(RESULTS_FILE)
        
        # Set 'Name' as index to facilitate transposition
        if 'Name' in df_raw.columns:
            df_raw.set_index('Name', inplace=True)
        else:
            print("Error: 'Name' column not found.")
            return

        # Transpose: Now Index = Solution_X, Columns = Parameters + Metrics
        df_t = df_raw.T
        
        # Filter: We only want rows that look like solutions (ignore 'Value', 'Min', 'Max', 'Type', 'Description')
        # Actually in this file format, the columns starting from 6th (index 5) are solutions.
        # But after transpose, these are the ROW indexes.
        
        # Identify rows that start with 'Solution_'
        solution_rows = [idx for idx in df_t.index if str(idx).startswith('Solution_')]
        df = df_t.loc[solution_rows].copy()
        
        print(f"Total Solutions Found: {len(df)}")
        
        # Convert columns to numeric where possible
        cols_to_convert = ['sortino', 'total_profit', 'avg_trades_day', 'max_drawdown', 'profit_factor', 
                           'Bollinger Band Length', 'Bollinger Band StdDev']
        
        for col in cols_to_convert:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        required_cols = ['sortino', 'total_profit', 'avg_trades_day', 'max_drawdown', 'profit_factor']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            print(f"MISSING METRICS IN DATA: {missing}")
            # Try to map if names are different?
            # List available columns just in case
            # print(f"Available columns: {list(df.columns)}")
            return

        # 1. General Stats
        print("\n=== General Statistics ===")
        print(df[required_cols].describe())

        # 2. Top 5 by Sortino
        print("\n=== Top 5 by Sortino Ratio ===")
        top_sortino = df.sort_values('sortino', ascending=False).head(5)
        print(top_sortino[required_cols].round(4).to_string())

        # 3. Top 5 by Total Profit
        print("\n=== Top 5 by Total Profit ===")
        top_profit = df.sort_values('total_profit', ascending=False).head(5)
        print(top_profit[required_cols].round(4).to_string())
        
        # 4. Analyze Trade Frequency Bias
        print("\n=== Trade Frequency Analysis ===")
        print(f"Avg Trades/Day (All): {df['avg_trades_day'].mean():.4f}")
        print(f"Avg Trades/Day (Top 10 Sortino): {top_sortino['avg_trades_day'].mean():.4f}")
        
        # Correlation
        corr_sortino_trades = df['sortino'].corr(df['avg_trades_day'])
        print(f"Correlation (Sortino vs Trades/Day): {corr_sortino_trades:.4f}")
        
        # Check for Scalpers (High frequency)
        scalpers = df[df['avg_trades_day'] > 5.0]
        print(f"Number of 'Scalper' solutions (>5 trades/day): {len(scalpers)}")
        if len(scalpers) > 0:
            print("Top Scalper by Sortino:")
            print(scalpers.sort_values('sortino', ascending=False).head(1)[required_cols].to_string())

        # Check for Parameter Convergence (Bollinger Band Length)
        if 'Bollinger Band Length' in df.columns:
             print("\n=== Parameter Convergence: BB Length ===")
             print(f"Mean: {df['Bollinger Band Length'].mean():.2f}")
             print(f"Std Dev: {df['Bollinger Band Length'].std():.2f}")
             
             # Std Dev of Bands vs Performance
             if 'Bollinger Band StdDev' in df.columns:
                 print("\n=== Parameter Convergence: BB StdDev ===")
                 print(f"Mean: {df['Bollinger Band StdDev'].mean():.2f}")
                 print(f"Std Dev: {df['Bollinger Band StdDev'].std():.2f}")
                 
                 print("\n--- Relationship: Band Tightness vs Performance ---")
                 print(top_sortino[['sortino', 'Bollinger Band Length', 'Bollinger Band StdDev']].to_string())

    except Exception as e:
        print(f"Error analyzing file: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    analyze_run()

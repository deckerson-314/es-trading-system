import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import os

# Paths
INPUT_CSV = "Bollinger/parameters/genetic_results_2025-12-06-3.csv"
OUTPUT_DIR = "results"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def analyze_ga_results():
    print(f"Loading {INPUT_CSV}...")
    
    # 1. Load Transposed Data
    # The file has params in rows, solutions in columns.
    # We need to read it, find the 'Name' column, and transpose.
    
    try:
        df_raw = pd.read_csv(INPUT_CSV, index_col='Name')
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    # Columns are Solution_0, Solution_1... plus meta cols
    sol_cols = [c for c in df_raw.columns if 'Solution_' in c]
    
    # Transpose to get Solutions as Rows
    df = df_raw[sol_cols].astype(str).transpose()
    
    # Clean Data
    # Remove '$', ',', '%'
    for col in df.columns:
        df[col] = df[col].str.replace('$', '').str.replace(',', '').str.replace('%', '')
        df[col] = pd.to_numeric(df[col], errors='coerce')
        
    # Filter for valid solutions (Total Profit > 0)
    if 'Total Profit (norm)' in df.columns:
        df['PnL'] = df['Total Profit (norm)']
    elif 'Total PnL' in df.columns: # fallback
        df['PnL'] = df['Total PnL']
        
    df_valid = df[df['PnL'] > 0].copy()
    print(f"Found {len(df_valid)} profitable solutions out of {len(df)}")
    
    # 2. Analyze Band Tightness & Profitability
    # print(f"Available Columns: {df_valid.columns.tolist()}") # Commented out to reduce noise
    
    # Try to find Raw Profit
    raw_pnl_col = next((c for c in df_valid.columns if 'Total Profit' in c and 'norm' not in c), None)
    if raw_pnl_col:
        df_valid['PnL'] = df_valid[raw_pnl_col]
    
    # Use Avg Trades/Day as proxy if Trades missing
    if 'Avg Trades/Day' in df_valid.columns:
        df_valid['Trades'] = df_valid['Avg Trades/Day'] * 1300 # Approx 5 years
    elif 'Trades' not in df_valid.columns:
         print("Error: Missing Trades info.")
         return

    # Calculate Per-Trade Metrics
    df_valid['Avg_Trade_Profit'] = df_valid['PnL'] / df_valid['Trades']
    
    # Stats for Top 10% vs Bottom 50%
    n_top = max(1, int(len(df_valid) * 0.1))
    df_sorted = df_valid.sort_values('PnL', ascending=False)
    
    top_10 = df_sorted.head(n_top)
    bottom_50 = df_sorted.tail(int(len(df_valid) * 0.5))
    
    print("\n=== Band Parameter Analysis ===")
    print(f"Top {n_top} Solutions (Mean PnL: ${top_10['PnL'].mean():,.0f})")
    print(f"  Avg Length: {top_10['Bollinger Band Length'].mean():.1f}")
    print(f"  Avg StdDev: {top_10['Bollinger Band StdDev'].mean():.2f}")
    print(f"  Avg Trades: {top_10['Trades'].mean():.0f}")
    print(f"  Avg Profit/Trade: ${top_10['Avg_Trade_Profit'].mean():.2f}")
    
    print(f"\nBottom 50% Solutions (Mean PnL: ${bottom_50['PnL'].mean():,.0f})")
    print(f"  Avg Length: {bottom_50['Bollinger Band Length'].mean():.1f}")
    print(f"  Avg StdDev: {bottom_50['Bollinger Band StdDev'].mean():.2f}")
    print(f"  Avg Trades: {bottom_50['Trades'].mean():.0f}")
    print(f"  Avg Profit/Trade: ${bottom_50['Avg_Trade_Profit'].mean():.2f}")
    
    # Correlation
    corr_std = df_valid['PnL'].corr(df_valid['Bollinger Band StdDev'])
    corr_len = df_valid['PnL'].corr(df_valid['Bollinger Band Length'])
    corr_trades = df_valid['PnL'].corr(df_valid['Trades'])
    
    print(f"\nCorrelation with PnL:")
    print(f"  StdDev: {corr_std:.3f}")
    print(f"  Length: {corr_len:.3f}")
    print(f"  Trades: {corr_trades:.3f}")
    
    # 3. Visualization
    # Scatter: Avg Trade Profit vs PnL, colored by StdDev
    fig = px.scatter(
        df_valid, 
        x='Avg_Trade_Profit', 
        y='PnL', 
        color='Bollinger Band StdDev',
        title='GA Analysis: Avg Trade Profit vs Total PnL (Color=StdDev)',
        labels={'PnL': 'Total Profit ($)', 'Avg_Trade_Profit': 'Avg Profit per Trade ($)'},
        hover_data=['Bollinger Band Length', 'Trades'],
        # trendline="ols"  <-- Removed
    )
    
    plot_path = os.path.join(OUTPUT_DIR, "ga_profit_analysis.html")
    fig.write_html(plot_path)
    print(f"\nPlot saved to: {plot_path}")
    
    # Also save summary text
    with open(os.path.join(OUTPUT_DIR, "ga_band_analysis.txt"), "w") as f:
        f.write(f"Top 10% Avg Profit/Trade: ${top_10['Avg_Trade_Profit'].mean():.2f}\n")
        f.write(f"Correlation Trades vs PnL: {corr_trades:.3f}\n")


if __name__ == "__main__":
    analyze_ga_results()

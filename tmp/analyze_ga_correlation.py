import pandas as pd
import numpy as np

def analyze_ga_correlation(file_path):
    print(f"\n--- Analyzing {file_path} ---")
    try:
        # Read without header to avoid column mismatch issues
        df = pd.read_csv(file_path, header=None)
        
        # Helper to find row index by name
        def get_row_index(name):
            matches = df[df[0] == name].index
            return matches[0] if len(matches) > 0 else None

        adx_idx = get_row_index('Enable ADX Filter')
        sortino_idx = get_row_index('Sortino Ratio (IS)')
        timeframe_idx = get_row_index('Timeframe (minutes)') # Note: check if it's 'minutes' or '(min)'
        rsi_idx = get_row_index('Enable RSI Filter')
        
        if adx_idx is None or sortino_idx is None:
            # Try alternative names or check what's there
            print(f"DEBUG: Found names in Col 0: {df[0].dropna().unique()[:20]}")
            return

        # Starting from Solution_0 at column index 6
        sol_data = df.iloc[:, 6:]
        
        # Convert to float, handling possible strings
        def clear_and_float(row_idx):
            vals = sol_data.iloc[row_idx].values
            # Clean up comma in strings like "$136,765.70"
            clean_vals = [str(x).replace('$', '').replace(',', '') for x in vals]
            return pd.to_numeric(clean_vals, errors='coerce')

        adx_vals = clear_and_float(adx_idx)
        sortino_vals = clear_and_float(sortino_idx)
        timeframe_vals = clear_and_float(timeframe_idx) if timeframe_idx is not None else None
        rsi_vals = clear_and_float(rsi_idx) if rsi_idx is not None else None
        
        results_df = pd.DataFrame({
            'ADX': adx_vals,
            'Sortino': sortino_vals
        })
        if timeframe_vals is not None: results_df['Timeframe'] = timeframe_vals
        if rsi_vals is not None: results_df['RSI'] = rsi_vals
        
        # Drop rows with NaN
        results_df = results_df.dropna()
        
        print("\nSummary Stats by ADX Filter:")
        print(results_df.groupby('ADX').mean())
        
        print("\nCorrelation Matrix (IS Performance):")
        print(results_df.corr())
        
        # Check distribution
        adx_counts = results_df['ADX'].value_counts()
        print("\nADX Filter Distribution:")
        print(adx_counts)

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

analyze_ga_correlation(r"c:\Trading\Trend\parameters\genetic_results_2026-04-03-1.csv")
analyze_ga_correlation(r"c:\Trading\Trend\parameters\genetic_results_2026-04-01-1.csv")

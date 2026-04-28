import pandas as pd
import numpy as np
import os

def analyze(csv_path, name):
    print(f"\n--- Analyzing {name} ({csv_path}) ---")
    df = pd.read_csv(csv_path)
    
    # Transpose so solutions are rows
    df = df.set_index('Name')
    sol_cols = [c for c in df.columns if c.startswith('Solution_')]
    df_sols = df[sol_cols].T
    
    # Identify splits
    metrics = [str(m) for m in df_sols.columns if isinstance(m, str) or not pd.isna(m)]
    
    # In 04-04-3, they are prefixed with '  '
    is_sortino_cols = [m for m in metrics if 'Sortino' in m and any(p in m for p in ['P1','P3','P5','P7','P9','P11'])]
    oos_sortino_cols = [m for m in metrics if 'Sortino' in m and any(p in m for p in ['P2','P4','P6','P8','P10'])]
    
    # Additional metrics for 04-04-3
    is_pf_cols = [m for m in metrics if 'Profit Fac' in m and any(p in m for p in ['P1','P3','P5','P7','P9','P11'])]
    oos_pf_cols = [m for m in metrics if 'Profit Fac' in m and any(p in m for p in ['P2','P4','P6','P8','P10'])]
    
    def clean_val(val):
        if isinstance(val, str):
            val = val.replace('$', '').replace(',', '')
        return float(val)

    # Convert to float
    for c in is_sortino_cols + oos_sortino_cols + is_pf_cols + oos_pf_cols:
        df_sols[c] = df_sols[c].apply(clean_val)

    # Calculate consistency
    df_sols['IS_Sortino_Mean'] = df_sols[is_sortino_cols].mean(axis=1)
    df_sols['IS_Sortino_Std'] = df_sols[is_sortino_cols].std(axis=1)
    df_sols['OOS_Sortino_Mean'] = df_sols[oos_sortino_cols].mean(axis=1)
    df_sols['OOS_Sortino_Std'] = df_sols[oos_sortino_cols].std(axis=1)
    df_sols['OOS_Sortino_Min'] = df_sols[oos_sortino_cols].min(axis=1)
    df_sols['OOS_Neg_Splits'] = (df_sols[oos_sortino_cols] < 0).sum(axis=1)
    
    if is_pf_cols:
        df_sols['OOS_PF_Mean'] = df_sols[oos_pf_cols].mean(axis=1)
        df_sols['OOS_PF_Min'] = df_sols[oos_pf_cols].min(axis=1)

    # Get top 5 by OOS Consistency (High Min Sortino, then High Mean)
    consistent = df_sols.sort_values(['OOS_Neg_Splits', 'OOS_Sortino_Min', 'OOS_Sortino_Mean'], ascending=[True, False, False])
    
    print("\nTop 5 Most Consistent Solutions (by OOS metrics):")
    cols_to_show = ['OOS_Sortino_Mean', 'OOS_Sortino_Std', 'OOS_Sortino_Min', 'OOS_Neg_Splits']
    if 'OOS_PF_Mean' in df_sols.columns:
        cols_to_show += ['OOS_PF_Mean', 'OOS_PF_Min']
    
    # Add some parameters for context
    param_cols = ['Timeframe (minutes)', 'Buy Lookback', 'Sell Lookback', 'Min ADX Threshold', 'Initial Stop Loss (%)', 'Enable Trailing Stop']
    cols_to_show = param_cols + cols_to_show
    
    print(consistent[cols_to_show].head(10))
    
    # Specific analysis of Solution_0
    if 'Solution_0' in df_sols.index:
         print("\nSolution_0 (Top by GA Sortino) Metrics:")
         print(df_sols.loc['Solution_0', cols_to_show])
         
    return df_sols

# Run analysis
res_04_04 = analyze(r'c:\Trading\Trend\parameters\genetic_results_2026-04-04-3.csv', 'April 4th (11 Splits)')
res_04_01 = analyze(r'c:\Trading\Trend\parameters\genetic_results_2026-04-01-1.csv', 'April 1st (Baseline)')

print("\n--- COMPARISON SUMMARY ---")

def get_best(df):
    for idx in df.index:
        if idx.startswith('Solution_0'):
            return df.loc[idx]
    return None

s0_new = get_best(res_04_04)
s0_old = get_best(res_04_01)
print(f"Old S0 (Baseline) IS Sortino: {s0_old['Sortino Ratio (IS)']}")
print(f"New S0 (GA Best) IS Sortino: {s0_new['Sortino Ratio (IS)']}")
print(f"Difference: {float(s0_new['Sortino Ratio (IS)']) - float(s0_old['Sortino Ratio (IS)'])}")

print("\nADX Fixed Check:")
print(f"Old S0 ADX: {s0_old['Min ADX Threshold']}")
print(f"New S0 ADX: {s0_new['Min ADX Threshold']}")

print("\nLookbacks Check:")
print(f"Old S0 Lookbacks: Buy={s0_old['Buy Lookback']} Sell={s0_old['Sell Lookback']}")
print(f"New S0 Lookbacks: Buy={s0_new['Buy Lookback']} Sell={s0_new['Sell Lookback']}")

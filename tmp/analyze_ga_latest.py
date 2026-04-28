
import pandas as pd
import numpy as np

file_path = r'c:\Trading\Trend\parameters\genetic_results_2026-04-14-13.csv'
df = pd.read_csv(file_path)

# Extract statistics
# The statistics rows are at the bottom, identified by Type='statistic'
stats_df = df[df['Type'] == 'statistic'].copy()

# Map metrics we care about
metrics_map = {
    'Sortino Ratio (IS)': 'sortino_is',
    'Profit Factor (IS)': 'pf_is',
    'Avg Trades/Day (IS)': 'trades_is',
    'Sortino Ratio (OOS)': 'sortino_oos',
    'Sortino IS-to-OOS Degradation': 'degradation',
    'Positive OOS Splits': 'pos_oos',
    'Live-Ready Robustness Score': 'robustness'
}

results = []
solution_cols = [c for c in df.columns if c.startswith('Solution_')]

for col in solution_cols:
    sol_data = {'id': col}
    for label, key in metrics_map.items():
        row = stats_df[stats_df['Name'] == label]
        if not row.empty:
            val = row[col].values[0]
            # Strip symbols
            if isinstance(val, str):
                val = val.replace('$', '').replace('%', '').replace(',', '')
            try:
                sol_data[key] = float(val)
            except:
                sol_data[key] = val
    results.append(sol_data)

res_df = pd.DataFrame(results)

# Filter for reasonable solutions (e.g. positive robustness)
best_robust = res_df.sort_values('robustness', ascending=False).head(15)

print("\n=== TOP SOLUTIONS BY ROBUSTNESS SCORE ===")
print(best_robust.to_string(index=False))

# Also look at high Sortino solutions
best_sortino = res_df.sort_values('sortino_is', ascending=False).head(5)
print("\n=== TOP SOLUTIONS BY SORTINO (IS) ===")
print(best_sortino.to_string(index=False))

# Check the one the user might be thinking of (PF around 1.32) if it exists in this run
pf_match = res_df[(res_df['pf_is'] >= 1.30) & (res_df['pf_is'] <= 1.35)]
if not pf_match.empty:
    print("\n=== SOLUTIONS WITH PF ~1.32 IN THIS RUN ===")
    print(pf_match.to_string(index=False))
else:
    print("\nNo solutions with PF ~1.32 found in this run.")

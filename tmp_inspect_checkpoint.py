import pickle
import pandas as pd

checkpoint_path = r'c:\Trading\Trend\diagnostics\ga_checkpoint_2026-04-24-1.pkl'
with open(checkpoint_path, 'rb') as f:
    cp = pickle.load(f)

hof = cp['hall_of_fame']
print(f"HoF Size: {len(hof)}")

for i in range(5):
    ind = hof[i]
    metrics = getattr(ind, 'actual_metrics', {})
    print(f"Solution {i}: Sortino={metrics.get('sortino')}, PnL={metrics.get('total_profit')}")

if 'hall_of_fame' in cp:
    ind0 = cp['hall_of_fame'][0]
    print("\nSolution 0 Parameters:")
    print(list(ind0))

import pandas as pd
import glob
import os
import numpy as np

files = [
    'c:\\Trading\\Trend\\parameters\\genetic_results_2026-04-13-2.csv',
    'c:\\Trading\\Trend\\parameters\\genetic_results_2026-04-13-1.csv',
    'c:\\Trading\\Trend\\parameters\\genetic_results_2026-04-12-2.csv',
    'c:\\Trading\\Trend\\parameters\\genetic_results_2026-04-12-1.csv'
]

results = []
all_solutions = []

def parse_val(v):
    if pd.isna(v) or v == '' or v == '---': return np.nan
    if isinstance(v, str):
        v = v.replace('$', '').replace(',', '')
    try:
        return float(v)
    except:
        return np.nan

for file in files:
    if not os.path.exists(file):
        continue
    
    df = pd.read_csv(file)
    
    # Find all Solution columns
    sol_cols = [c for c in df.columns if c.startswith('Solution_')]
    
    run_name = os.path.basename(file)
    
    run_stats = {
        'Run': run_name,
        'Total_Solutions': len(sol_cols),
        'Positive_OOS_Sortino_Count': 0,
        'Positive_OOS_PNL_Count': 0,
        'Total_OOS_PNL': 0.0,
        'Avg_OOS_PPT': 0.0,
        'Avg_Trades_Day': 0.0,
        'OOS_Split_Consistency_Avg': 0.0
    }
    
    run_solutions = []
    
    for col in sol_cols:
        def get_val(name):
            row = df[df['Name'] == name]
            if not row.empty:
                return parse_val(row.iloc[0][col])
            return np.nan
            
        timeframe = get_val('Timeframe (minutes)')
        is_sortino = get_val('Sortino Ratio (IS)')
        oos_sortino = get_val('Sortino Ratio (OOS)')
        is_trades = get_val('Avg Trades/Day (IS)')
        oos_pnl = get_val('Total Profit (OOS) ($)')
        oos_ppt = get_val('Avg Profit/Trade (OOS) ($)')
        
        # Analyze OOS Splits
        oos_splits_pnl = []
        for p in ['P1', 'P2', 'P3', 'P4', 'P5']:
            val = get_val(f'  Total PNL ({p})')
            # The CSV might list "Total PNL (P1)" under "OOS Split detail" visually, 
            # but we need to ensure we grab the right one. The Name column might just be '  Total PNL (P1)'
            # Let's check both IS and OOS to see if they both exist. 
            # In the CSV, they both might be named '  Total PNL (P1)'. 
            # We can find all matches and assume the second one is OOS, or just check '  Sortino (P1)'
            pass
            
        # A more robust way to get OOS splits:
        # Since pandas read_csv will make duplicate names unique, e.g., '  Total PNL (P1).1' for the second occurrence.
        # Let's count positive splits based on whatever OOS metrics we can find.
        # For simplicity, let's just grab the OOS PNL directly by exact name if it distinguishes.
        # Wait, get_val returns the first match. To get OOS slices, we know they appear after '--- PER-SPLIT DETAIL (Out-of-Sample) ---'
        oos_start_idx = df[df['Name'] == '--- PER-SPLIT DETAIL (Out-of-Sample) ---'].index
        is_start_idx = df[df['Name'] == '--- PER-SPLIT DETAIL (In-Sample) ---'].index
        
        positive_oos_splits = 0
        total_oos_splits = 0
        if not oos_start_idx.empty:
            start_i = oos_start_idx[0]
            # search from start_i onwards for 'Total PNL' or 'Sortino'
            for idx in range(start_i+1, len(df)):
                name = str(df.iloc[idx]['Name'])
                if 'Sortino (' in name and not 'Ratio' in name:
                    val = parse_val(df.iloc[idx][col])
                    if not np.isnan(val):
                        total_oos_splits += 1
                        if val > 0:
                            positive_oos_splits += 1
        
        fraction_positive_oos = positive_oos_splits / total_oos_splits if total_oos_splits > 0 else 0
        
        # Accumulate run stats
        if not np.isnan(oos_sortino) and oos_sortino > 0:
            run_stats['Positive_OOS_Sortino_Count'] += 1
        if not np.isnan(oos_pnl) and oos_pnl > 0:
            run_stats['Positive_OOS_PNL_Count'] += 1
            
        if not np.isnan(oos_pnl): run_stats['Total_OOS_PNL'] += oos_pnl
        if not np.isnan(oos_ppt): run_stats['Avg_OOS_PPT'] += oos_ppt
        if not np.isnan(is_trades): run_stats['Avg_Trades_Day'] += is_trades
        run_stats['OOS_Split_Consistency_Avg'] += fraction_positive_oos
        
        sol_data = {
            'Run': run_name,
            'Solution': col,
            'Timeframe': timeframe,
            'IS_Sortino': is_sortino,
            'OOS_Sortino': oos_sortino,
            'IS_Trades': is_trades,
            'OOS_PNL': oos_pnl,
            'OOS_PPT': oos_ppt,
            'Pos_OOS_Splits': f"{positive_oos_splits}/{total_oos_splits}"
        }
        all_solutions.append(sol_data)
        run_solutions.append(sol_data)
        
    num = len(sol_cols)
    if num > 0:
        run_stats['Total_OOS_PNL'] /= num
        run_stats['Avg_OOS_PPT'] /= num
        run_stats['Avg_Trades_Day'] /= num
        run_stats['OOS_Split_Consistency_Avg'] /= num
        
    results.append(run_stats)

print("="*100)
print("AGGREGATE RUN PERFORMANCE (ALL SOLUTIONS)")
print("="*100)
for r in results:
    print(f"RUN: {r['Run']}")
    print(f"  Total Solutions : {r['Total_Solutions']}")
    val1 = r['Positive_OOS_Sortino_Count']
    val2 = r['Positive_OOS_PNL_Count']
    num = r['Total_Solutions']
    print(f"  % Pos OOS Sortio: {val1/num*100:.1f}% ({val1}/{num})")
    print(f"  % Pos OOS PNL   : {val2/num*100:.1f}% ({val2}/{num})")
    print(f"  Avg OOS PNL     : ${r['Total_OOS_PNL']:,.2f}")
    print(f"  Avg OOS PPT     : ${r['Avg_OOS_PPT']:,.2f}")
    print(f"  Avg Trades/Day  : {r['Avg_Trades_Day']:.3f} (IS)")
    print(f"  Avg OOS Split % : {r['OOS_Split_Consistency_Avg']*100:.1f}% positive OOS splits per solution")
    print("-" * 60)

# Find absolute best OOS solutions across all runs
df_all = pd.DataFrame(all_solutions)
try:
    df_all = df_all.sort_values(by='OOS_Sortino', ascending=False)
except:
    pass

print("\n" + "="*100)
print("TOP 10 BEST OOS SOLUTIONS ACCROSS ALL RUNS")
print("="*100)
# format nicely
columns = ['Run', 'Solution', 'Timeframe', 'IS_Trades', 'IS_Sortino', 'OOS_Sortino', 'OOS_PNL', 'Pos_OOS_Splits']
if not df_all.empty:
    print(df_all[columns].head(10).to_string(index=False))

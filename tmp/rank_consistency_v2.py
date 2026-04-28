import pandas as pd
import numpy as np

def analyze_consistency(csv_path):
    df = pd.read_csv(csv_path)
    
    # Identify Solution columns
    solution_cols = [c for c in df.columns if c.startswith('Solution_')]
    
    results = []
    
    # OOS Splits are P2, P4, P6, P8, P10
    oos_pnl_keys = [f'Total PNL ({p})' for p in ['P2', 'P4', 'P6', 'P8', 'P10']]
    oos_sortino_keys = [f'Sortino ({p})' for p in ['P2', 'P4', 'P6', 'P8', 'P10']]
    
    for col in solution_cols:
        # Get overall metrics
        try:
            # Use exact matching helper
            def get_val(name):
                series = df[df['Name'] == name][col]
                if series.empty:
                    # Try with slightly different name (just in case of spaces)
                    series = df[df['Name'].str.strip() == name.strip()][col]
                if series.empty:
                    raise KeyError(f"Name '{name}' not found for column '{col}'")
                val = series.values[0]
                if isinstance(val, str):
                    # Clean currency/formatting
                    val = val.replace('$', '').replace(',', '').replace('(', '-').replace(')', '').strip()
                    if val == '---' or val == '': return 0.0
                    return float(val)
                return float(val)

            oos_sortino = get_val('Sortino Ratio (OOS)')
            oos_profit = get_val('Total Profit (OOS) ($)')
            is_sortino = get_val('Sortino Ratio (IS)')
            is_profit = get_val('Total Profit (IS) ($)')
            is_dd = get_val('Max Drawdown (IS) ($)')
                
            # Per-split profitable count
            profitable_oos_splits = 0
            for pnl_key in oos_pnl_keys:
                val = get_val(pnl_key)
                if val > 0:
                    profitable_oos_splits += 1
            
            # Mean OOS Sortino
            oos_split_sortinos = []
            for s_key in oos_sortino_keys:
                val = get_val(s_key)
                oos_split_sortinos.append(val)
            mean_oos_sortino = np.mean(oos_split_sortinos)
            
            # Param check (Timeframe, Lookbacks are ints usually)
            tf = int(get_val('Timeframe (minutes)'))
            buy_lookback = int(get_val('Buy Lookback'))
            sell_lookback = int(get_val('Sell Lookback'))
            
            results.append({
                'Solution': col,
                'IS_Sortino': is_sortino,
                'IS_Profit': is_profit,
                'IS_DD': is_dd,
                'OOS_Sortino_Total': oos_sortino,
                'OOS_Profit_Total': oos_profit,
                'OOS_Profitable_Splits': profitable_oos_splits,
                'Mean_OOS_Sortino': mean_oos_sortino,
                'TF': tf,
                'Buy_LB': buy_lookback,
                'Sell_LB': sell_lookback
            })
        except Exception as e:
            print(f"Error processing {col}: {e}")
            continue

    res_df = pd.DataFrame(results)
    
    # Filter for "Consistent" solutions (Profitable in at least 3/5 OOS splits)
    consistent = res_df[res_df['OOS_Profitable_Splits'] >= 3].sort_values('Mean_OOS_Sortino', ascending=False)
    
    print("\n--- TOP CONSISTENT SOLUTIONS (Min 3/5 profitable OOS splits) ---")
    print(consistent[['Solution', 'OOS_Profitable_Splits', 'Mean_OOS_Sortino', 'OOS_Profit_Total', 'IS_DD', 'TF', 'Buy_LB']].head(15).to_string(index=False))
    
    # Look for Solution_9 specifically
    print("\n--- SOLUTION_9 STATS ---")
    print(res_df[res_df['Solution'] == 'Solution_9_SELECTED'][['Solution', 'OOS_Profitable_Splits', 'Mean_OOS_Sortino', 'OOS_Profit_Total', 'IS_DD', 'TF', 'Buy_LB']].to_string(index=False))

if __name__ == "__main__":
    analyze_consistency(r'c:\Trading\Trend\parameters\genetic_results_2026-04-06-1.csv')

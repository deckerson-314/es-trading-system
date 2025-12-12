import pandas as pd

CSV_PATH = r"c:\Trading\Bollinger\parameters\genetic_results_2025-12-11-5.csv"

def find_high_freq():
    try:
        df = pd.read_csv(CSV_PATH)
    except Exception as e:
        print(f"Error: {e}")
        return

    # Find Metric Rows
    df['Name_Clean'] = df['Name'].astype(str).str.strip()
    
    row_trades_day = df[df['Name_Clean'] == 'Avg Trades/Day'].index[0]
    row_profit_norm = df[df['Name_Clean'] == 'Total Profit (norm)'].index[0]
    row_sortino = df[df['Name_Clean'] == 'Sortino Ratio'].index[0]

    sol_cols = [c for c in df.columns if c.startswith('Solution_')]
    
    high_freq_sols = []
    
    for col in sol_cols:
        try:
            t_day = float(df.loc[row_trades_day, col])
            if t_day >= 2.5: # Look for anything close to 3
                p_norm = float(df.loc[row_profit_norm, col])
                sortino = float(df.loc[row_sortino, col])
                
                # Calc Profit ($)
                profit_dollar = p_norm * 465000.0
                
                # Calc Profit/Trade
                # Est total trades
                total_trades = t_day * 4400
                p_trade = 0
                if total_trades > 0:
                    p_trade = profit_dollar / total_trades
                
                high_freq_sols.append({
                    'Solution': col,
                    'Trades/Day': t_day,
                    'Profit ($)': profit_dollar,
                    'Sortino': sortino,
                    'Profit/Trade': p_trade
                })
        except:
            continue
            
    # Sort by Frequency
    results = pd.DataFrame(high_freq_sols)
    if not results.empty:
        print(f"Found {len(results)} solutions with > 2.5 trades/day.")
        print(results.sort_values(by='Trades/Day', ascending=False).head(10).to_string())
        
        print("\n--- Best Profit High-Freq ---")
        print(results.sort_values(by='Profit ($)', ascending=False).head(5).to_string())
    else:
        print("No solutions found with > 2.5 trades/day.")

if __name__ == "__main__":
    find_high_freq()

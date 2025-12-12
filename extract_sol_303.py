import pandas as pd
import json

CSV_PATH = r"c:\Trading\Bollinger\parameters\genetic_results_2025-12-11-5.csv"
TARGET_SOL = 'Solution_303'

def extract_specific():
    try:
        df = pd.read_csv(CSV_PATH)
    except Exception as e:
        print(f"Error: {e}")
        return

    if TARGET_SOL not in df.columns:
        print(f"{TARGET_SOL} not found in CSV.")
        return

    print(f"--- Statistics for {TARGET_SOL} ---")
    
    # 1. Get Params
    params = {}
    for idx, row in df.iterrows():
        if row['Type'] in ['int', 'float', 'bool']:
            val = row[TARGET_SOL]
            if pd.isna(val) or str(val).strip() == '':
                val = row['Value']
            
            # Format nicely
            try:
                if row['Type'] == 'int': val = int(float(val))
                elif row['Type'] == 'float': val = float(val)
                elif row['Type'] == 'bool': val = (str(val).lower() == 'true')
            except: pass
            
            params[row['Name']] = val

    # 2. Get Metrics
    metrics_to_find = {
        'Total Profit': 'Profit',
        'Total Profit (norm)': 'Profit (Norm)', 
        'Sortino Ratio': 'Sortino',
        'Max Drawdown': 'Max DD',
        'Max Drawdown ($)': 'Max DD ($)',
        'Total Trades': 'Trades',
        'Avg Trades/Day': 'Trades/Day',
        'Win Rate': 'Win Rate'
    }
    
    metrics = {}
    df['Name_Clean'] = df['Name'].astype(str).str.strip()
    
    for key, label in metrics_to_find.items():
        # Fuzzy match row
        match = df[df['Name_Clean'].str.contains(key, case=False, regex=False)]
        if not match.empty:
            val = match.iloc[0][TARGET_SOL]
            try:
                metrics[label] = float(val)
            except:
                metrics[label] = val
                
    # Calc Profit/Trade
    profit_norm = metrics.get('Profit (Norm)', 0.0)
    profit = metrics.get('Profit', profit_norm * 465000.0)
    trades = metrics.get('Trades', 0.0)
    
    if trades == 0 and metrics.get('Trades/Day', 0) > 0:
        trades = metrics['Trades/Day'] * 4400 # Est
        metrics['Trades (Est)'] = trades
        
    avg_pnl = 0.0
    if trades > 0:
        avg_pnl = profit / trades
    
    metrics['Avg Profit/Trade'] = avg_pnl
    
    # Print Metrics
    for k, v in metrics.items():
        print(f"{k}: {v}")
        
    print("\n--- Key Parameters ---")
    keys = ['Bollinger Band Length', 'Bollinger Band StdDev', 'RSI Length', 'RSI Overbought', 'RSI Oversold', 'ADX Period', 'Max ADX Threshold', 'Take Profit (ATR)', 'Stop Loss (ATR)']
    for k in keys:
        if k in params:
            print(f"{k}: {params[k]}")

if __name__ == "__main__":
    extract_specific()

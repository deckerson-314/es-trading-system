import pandas as pd
import sys

def report():
    try:
        df = pd.read_csv(r'Bollinger\parameters\genetic_results_2025-12-13-2.csv')
        # Use Sol 0
        col = 'Solution_0_SELECTED'
        
        # Key Parameters to highlight
        key_params = [
            'Bollinger Band Length', 
            'Bollinger Band StdDev', 
            'Max Volume Multiplier',
            'Max ATR Filter (Points)', 
            'Min ATR Filter (Points)',
            'ADX Threshold', 
            'Take Profit (ATR Multiplier)', 
            'Stop Loss (ATR Multiplier)',
            'Trailing Stop (ATR Multiplier)',
            'Close on Opposite Band',
            'Timeframe (minutes)'
        ]
        
        print("=== WINNING PARAMETERS (GEN 99) ===")
        for index, row in df.iterrows():
            name = row['Name']
            if pd.isna(name): continue
            
            # Print if it's in our key list OR if not starting with metadata chars
            if name in key_params or (not str(name).startswith('=') and not str(name).startswith('__')):
                 print(f"{name}: {row[col]}")
                 
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    report()

import sys
import os
sys.path.append(r'c:\Trading')
from bollinger_strategy.parameters import load_params

csv_path = r'c:\Trading\Bollinger\parameters\backtest_params.csv'

def check_params():
    try:
        params, df = load_params(csv_path, return_dataframe=True)
        print(f"Loaded {len(params)} parameters.")
        
        norm_keys = [k for k in params.keys() if 'NORM_' in k]
        print(f"Found {len(norm_keys)} NORM_ keys.")
        
        if 'NORM_SORTINO_MAX' in params:
            print(f"NORM_SORTINO_MAX: {params['NORM_SORTINO_MAX']}")
        else:
            print("NORM_SORTINO_MAX NOT FOUND!")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_params()

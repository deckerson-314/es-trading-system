
import pandas as pd
import sys
import os

# Add path to bollinger_strategy
sys.path.append(os.getcwd())

from bollinger_strategy.strategy_v4 import BollingerBandStrategyV4

def main():
    print("Loading recent_warmup_data.csv...")
    try:
        df = pd.read_csv('c:/Trading/recent_warmup_data.csv', parse_dates=['datetime'])
        df.set_index('datetime', inplace=True)
        # Convert to US/Eastern to match live script behavior (if needed, but Strategy manages timezone agnostic)
        # df.index = df.index.tz_convert('US/Eastern') 
        # Actually warmup data is usually UTC or Exchange Time. Strategy likely expects naive or consistent.
        # Let's assume input is fine.
    except Exception as e:
        print(f"Failed to load data: {e}")
        return

    print(f"Input Data Length: {len(df)}")
    print(df.tail())

    # Initialize Strategy
    strategy = BollingerBandStrategyV4({
        'timeframe': 2,
        'bb_length': 20,
        'bb_std_dev': 2.0,
        'enable_volume_filter': True,
        'volume_ma_length': 50,
        'max_volume_multiplier': 3.0,
        'enable_atr_filter': True,
        'min_atr_points': 0.5,
        'max_atr_points': 5.0
    })

    print("\n--- 1. Calculate Indicators ---")
    df_ind = strategy.calculate_indicators(df.copy())
    print(f"Indicators DF Length: {len(df_ind)}")
    print(df_ind.tail())

    print("\n--- 2. Apply Filters ---")
    df_filt = strategy.apply_filters(df_ind.copy())
    print(f"Filters DF Length: {len(df_filt)}")
    print(df_filt.tail())
    
    # Check for missing rows
    missing = len(df_ind) - len(df_filt)
    print(f"\nMissing Rows: {missing}")
    
    if len(df_filt) > 0:
        last_ind = df_ind.index[-1]
        last_filt = df_filt.index[-1]
        print(f"\nLatest Ind Time: {last_ind}")
        print(f"Latest Filt Time: {last_filt}")
        
        if last_ind != last_filt:
            print("MISMATCH! Filter dropped the latest row.")
            # Check why
            last_row = df_ind.iloc[-1]
            print("\nLast Row of Indicators (Dropped?):")
            print(last_row)
            # Check for NaNs
            print("\nNaN check on Last Row:")
            print(last_row.isna())

if __name__ == "__main__":
    main()

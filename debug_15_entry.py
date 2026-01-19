import pandas as pd
import numpy as np
import sys
import os

# Add path to strategy
sys.path.append(r'c:\Trading')
from bollinger_strategy.strategy_v4 import BollingerBandStrategyV4

def debug_entry():
    # 1. Load Data
    csv_path = r'c:\Trading\paper_logs\live_data.csv'
    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    
    # SHIFT FIX (Standardization)
    df.index = df.index - pd.Timedelta(minutes=2)
    
    # FORCE ALIGNMENT FIX: Insert dummy row at aligned start time
    # start_align = df.index[0].floor('2T')
    # if start_align not in df.index:
    #     df.loc[start_align] = np.nan
    #     df.sort_index(inplace=True)
    
    # 2. Params
    params = {
        'Bollinger Band Length': {'value': 5},
        'Bollinger Band StdDev': {'value': 2.265},
        'Short Entry on Wick Touch': {'value': True},
        'Short Trigger (% From Upper Band)': {'value': 0.0},
        'Timeframe (minutes)': {'value': 2},
        # Filters
        'Enable RTH Filter': {'value': False},  # Matches Live
        'RTH Start (HH:MM)': {'value': '09:30'},
        'Enable Maintenance Filter': {'value': False},
        'Max Open Trades': {'value': 1}
    }
    
    # 3. Init Strategy
    strat = BollingerBandStrategyV4(params)
    
    # 4. Calc
    print("Calculating Indicators...")
    df_calc = strat.calculate_indicators(df)
    print("Applying Filters...")
    df_calc = strat.apply_filters(df_calc)
    
    print("\n--- RESAMPLED DATA HEAD ---")
    print(df_calc[['open', 'high', 'low', 'close', 'volume']].head(20))
    
    # Target: 09:12 Live -> Shift 2m -> 09:10
    t_target = pd.Timestamp("2026-01-15 09:10:00-05:00")
    
    # Check if target is in index (string comparison fallback)
    row = None
    if t_target in df_calc.index:
        row = df_calc.loc[t_target]
    else:
        print("Direct match failed. Checking string match...")
        matches = [i for i in df_calc.index if str(i).startswith('2026-01-15 09:12')]
        if matches:
            print(f"Found fuzzy match: {matches[0]}")
            row = df_calc.loc[matches[0]]
        else:
            print(f"Target {t_target} NOT FOUND in Resampled Data")
            return

    print(f"\n--- CHECKING ENTRY AT {row.name} ---")
    print(f"High: {row['high']}")
    print(f"Upper: {row['upper']}")
    print(f"Trigger Pct: {strat.short_trigger_pct}")
    
    trigger = row['upper'] * (1 + strat.short_trigger_pct/100)
    print(f"Trigger Price: {trigger}")
    
    if row['high'] >= trigger:
        print(">> CONDITION MET (High >= Trigger)")
    else:
        print(f">> CONDITION FAILED ({row['high']} < {trigger})")
        
    # Check Strategy Check_Entry
    enter_long, enter_short = strat.check_entry(row, df_calc)
    print(f"Strategy Check Result: Long={enter_long}, Short={enter_short}")

if __name__ == "__main__":
    debug_entry()

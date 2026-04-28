import pandas as pd
import numpy as np
import os
import pickle
import sys

# Add current dir to path to import optimize
sys.path.append(os.getcwd())
import optimize

# Mock dependencies
optimize.PARAM_RANGES = {} 

def audit_mask():
    checkpoint = r'Trend\diagnostics\ga_checkpoint_2026-04-24-1.pkl'
    param_csv = r'strategies\bollinger\parameters\backtest_params.csv'
    
    param_df = pd.read_csv(param_csv)
    GA_START_DATE = str(param_df[param_df['Name'] == 'GA_START_DATE']['Value'].iloc[0])
    GA_END_DATE = str(param_df[param_df['Name'] == 'GA_END_DATE']['Value'].iloc[0])
    
    DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'
    df_raw = pd.read_csv(DATA_CSV, header=None, names=['datetime', 'open', 'high', 'low', 'close', 'volume'])
    df_raw['datetime'] = pd.to_datetime(df_raw['datetime'])
    df_raw['datetime'] = df_raw['datetime'].dt.tz_localize('UTC').dt.tz_convert('US/Eastern').dt.tz_localize(None)
    df_raw.set_index('datetime', inplace=True)
    
    df_eval = df_raw.loc[GA_START_DATE:GA_END_DATE]
    
    is_mask = pd.Series(False, index=df_raw.index)
    
    # Simple split reproduction
    split_ratio = float(param_df[param_df['Name'] == 'DATA_SPLITS']['Value'].iloc[0])
    split_idx = int(len(df_eval) * split_ratio)
    
    if len(df_eval) > 0:
        split_time = df_eval.index[split_idx-1]
        start_time = df_eval.index[0]
        is_mask.loc[start_time:split_time] = True
        
    print(f"df_eval size: {len(df_eval)}")
    print(f"is_mask True count: {is_mask.sum()}")
    print(f"First True index: {is_mask[is_mask].index[0] if is_mask.any() else 'N/A'}")
    print(f"Last True index: {is_mask[is_mask].index[-1] if is_mask.any() else 'N/A'}")

audit_mask()

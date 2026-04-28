import pandas as pd

param_csv = r'strategies\bollinger\parameters\backtest_params.csv'
param_df = pd.read_csv(param_csv)

ga_criteria_params = set(['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                          'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                          'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                          'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT',
                          'GA_START_DATE', 'GA_END_DATE', 
                          'WEIGHT_SORTINO', 'WEIGHT_DRAWDOWN', 'WEIGHT_PF', 'WEIGHT_TRADES', 'WEIGHT_PNL', 'WEIGHT_PPT',
                          'MIN_TRADE_DURATION', 'MAX_WIN_RATE_CAP', 'LIMIT_MAX_LOSS', 'LIMIT_MIN_SORTINO',
                          'NORM_SORTINO_MAX', 'NORM_DD_MAX', 'NORM_PF_MAX', 'NORM_TRADES_MAX', 
                          'NORM_PNL_MAX', 'NORM_PROFIT_TRADE_MAX', 'MIN_WIN_RATE', 'SORTINO_CAP',
                          'MIN_PROFIT_PER_TRADE',
                          'Enable Long Trades', 'Enable Short Trades', # Likely fixed
                          'Max Open Trades',
                          'Enable Trailing Stop',
                          'Enable RSI Filter', 'Enable VWAP Filter' # V5 additions often fixed
                          ])

keys = []
for _, row in param_df.iterrows():
    n = row['Name']
    if pd.isna(n) or n.startswith('===') or n.startswith('__'): continue
    if n in ga_criteria_params: continue
    
    ptype = str(row['Type']).lower()
    pmin = row['Min']
    pmax = row['Max']
    
    if ptype in ('int', 'float', 'bool') and pmin is not None and pmax is not None:
        if str(pmin).lower() != str(pmax).lower():
            keys.append(n)

print(f"Total keys found: {len(keys)}")
for i, k in enumerate(keys):
    print(f"{i+1}: {k}")

import pandas as pd
import collections

def load_params(csv_path):
    df = pd.read_csv(csv_path)
    # Filter out section headers
    df = df[~df['Name'].str.startswith('===').fillna(False)]
    
    p_dict = collections.OrderedDict()
    for _, row in df.iterrows():
        name = row['Name']
        if pd.isna(name): continue
        p_dict[name] = {
            'value': row['Value'],
            'min': row['Min'],
            'max': row['Max'],
            'type': str(row['Type']).lower() if pd.notna(row['Type']) else None
        }
    return p_dict

p_dict = load_params(r'strategies\bollinger\parameters\backtest_params.csv')

ga_set = {'POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA', 'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT', 'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS', 'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT', 'GA_START_DATE', 'GA_END_DATE', 'WEIGHT_SORTINO', 'WEIGHT_DRAWDOWN', 'WEIGHT_PF', 'WEIGHT_TRADES', 'WEIGHT_PNL', 'WEIGHT_PPT', 'MIN_TRADE_DURATION', 'MAX_WIN_RATE_CAP', 'LIMIT_MAX_LOSS', 'LIMIT_MIN_SORTINO', 'NORM_SORTINO_MAX', 'NORM_DD_MAX', 'NORM_PF_MAX', 'NORM_TRADES_MAX', 'NORM_PNL_MAX', 'NORM_PROFIT_TRADE_MAX', 'MIN_WIN_RATE', 'SORTINO_CAP', 'MIN_PROFIT_PER_TRADE'}

keys = []
for n, d in p_dict.items():
    if n.startswith('===') or n.startswith('__'): continue
    if n in ga_set: continue
    
    ptype = d.get('type')
    pmin = d.get('min')
    pmax = d.get('max')
    
    if ptype in ('int', 'float') and pd.notna(pmin) and pd.notna(pmax):
        if pmin != pmax:
            keys.append(n)

print(f"Total keys: {len(keys)}")
for i, k in enumerate(keys):
    print(f"{i+1}: {k}")

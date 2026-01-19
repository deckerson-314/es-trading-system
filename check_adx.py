import pandas as pd
import numpy as np
import os

def check_adx():
    data_path = 'c:\\Trading\\temp_combined_data.csv'
    print(f"Loading {data_path}...")
    df = pd.read_csv(data_path, index_col=0, parse_dates=True)
    df.columns = ['open', 'high', 'low', 'close', 'volume']
    
    # Resample 2T
    df_resampled = df.resample('2T', label='right', closed='left').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    })
    df_resampled.dropna(how='any', inplace=True)
    
    df_resampled.dropna(how='any', inplace=True)
    
    # HYPOTHESIS TEST: START AT 07:30
    df_jan15 = df_resampled[df_resampled.index >= '2026-01-15 07:30']
    print(f"Jan 15 Data Length (from 07:30): {len(df_jan15)}")
    
    # ADX Calc
    length = 20
    # Use df_jan15
    df_calc = df_jan15.copy()
    
    high = df_calc['high']
    low = df_calc['low']
    close = df_calc['close']
    
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    up = high - high.shift(1)
    down = low.shift(1) - low
    
    # Print Morning Data
    print("Morning Data (08:50-09:00):")
    print(df_calc[['high','low','close']].head(10))
    
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    print("Morning TR:")
    print(tr.head(10))
    
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    plus_dm = pd.Series(plus_dm, index=df_calc.index)
    minus_dm = pd.Series(minus_dm, index=df_calc.index)
    
    atr = tr.ewm(alpha=1/length, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/length, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/length, adjust=False).mean() / atr)
    
    sum_di = plus_di + minus_di
    dx = 100 * (abs(plus_di - minus_di) / sum_di)
    dx = dx.fillna(0)
    
    adx = dx.ewm(alpha=1/length, adjust=False).mean()
    
    # Check 09:12
    ts = pd.Timestamp("2026-01-15 09:12:00")
    if ts in adx.index:
        print(f"ADX at 09:12: {adx[ts]}")
    else:
        print("09:12 NOT FOUND")

if __name__ == "__main__":
    check_adx()

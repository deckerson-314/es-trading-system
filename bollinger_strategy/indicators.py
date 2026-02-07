"""
Indicator Calculations
======================
Bollinger Bands and ATR calculations.
All implementations use identical logic.
"""

import pandas as pd
import numpy as np


def calculate_bollinger_bands(df, bb_length, bb_stddev):
    """
    Calculate Bollinger Bands.
    
    Args:
        df: DataFrame with 'close' column
        bb_length: Rolling window length for moving average
        bb_stddev: Standard deviation multiplier
        
    Returns:
        DataFrame with added columns: 'mid', 'std', 'upper', 'lower'
    """
    df = df.copy()
    df['mid'] = df['close'].rolling(bb_length).mean()
    df['std'] = df['close'].rolling(bb_length).std()
    df['upper'] = df['mid'] + df['std'] * bb_stddev
    df['lower'] = df['mid'] - df['std'] * bb_stddev
    return df


def calculate_atr(df, atr_length):
    """
    Calculate Average True Range (ATR).
    
    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        atr_length: Rolling window length for ATR
        
    Returns:
        Series: ATR values
    """
    tr = np.maximum.reduce([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift()).abs(),
        (df['low'] - df['close'].shift()).abs()
    ])
    atr = pd.Series(tr, index=df.index).rolling(atr_length).mean()
    return atr


def calculate_ema(df, length):
    """
    Calculate Exponential Moving Average (EMA).
    
    Args:
        df: DataFrame with 'close' column
        length: Window length
        
    Returns:
        Series: EMA values
    """
    return df['close'].ewm(span=length, adjust=False).mean()


def calculate_adx(df, length):
    """
    Calculate Average Directional Index (ADX).
     Uses Wilder's smoothing (alpha=1/length).
    
    Args:
        df: DataFrame with 'high', 'low', 'close'
        length: Window length (standard 14)
        
    Returns:
        Series: ADX values
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    # 1. Calculate True Range and Directional Movement
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    up = high - high.shift(1)
    down = low.shift(1) - low
    
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)
    
    # 2. Smooth (Wilder's Smoothing)
    # alpha = 1 / length
    atr = tr.ewm(alpha=1/length, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/length, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/length, adjust=False).mean() / atr)
    
    # 3. Calculate DX and ADX
    # Avoid division by zero
    sum_di = plus_di + minus_di
    dx = 100 * (abs(plus_di - minus_di) / sum_di)
    dx = dx.fillna(0) # Handle initial NaNs
    
    # ADX is smoothed DX
    adx = dx.ewm(alpha=1/length, adjust=False).mean()
    
    return adx


def calculate_rsi(df, period=14):
    """
    Calculate Relative Strength Index (RSI).
    Uses Wilder's smoothing.
    
    Args:
        df: DataFrame with 'close' column
        period: RSI period (standard 14)
        
    Returns:
        Series: RSI values (0-100)
    """
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    
    # Wilder's Smoothing
    ma_up = up.ewm(alpha=1/period, adjust=False).mean()
    ma_down = down.ewm(alpha=1/period, adjust=False).mean()
    
    # Avoid division by zero
    rs = ma_up / ma_down
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)  # Neutral filling


def calculate_vwap(df):
    """
    Calculate Volume Weighted Average Price (VWAP).
    Resets at the start of each day (based on index date).
    
    Args:
        df: DataFrame with 'close', 'high', 'low', 'volume' columns and DatetimeIndex.
        
    Returns:
        Series: VWAP values
    """
    df = df.copy()
    
    # Typical Price
    df['tp'] = (df['high'] + df['low'] + df['close']) / 3
    df['vol_price'] = df['tp'] * df['volume']
    
    # Group by Date for Daily Reset
    # Note: efficient vectorized groupby cumsum
    grouper = df.index.date
    
    # Calculate cumulative sums per day
    daily_cum_vol = df.groupby(grouper)['volume'].cumsum()
    daily_cum_vol_price = df.groupby(grouper)['vol_price'].cumsum()
    
    # Calculate VWAP
    vwap = daily_cum_vol_price / daily_cum_vol
    
    # Fill NaNs (start of day or zero volume) with Typical Price
    vwap = vwap.fillna(df['tp'])
    
    return vwap

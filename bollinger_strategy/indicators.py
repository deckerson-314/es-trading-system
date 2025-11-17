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


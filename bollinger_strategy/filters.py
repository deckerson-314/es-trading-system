"""
Filter Logic
============
RTH (Regular Trading Hours), Volume, and ATR filters.
All implementations use identical logic.
"""

import pandas as pd
from datetime import time


def apply_rth_filter(df, enable_rth_filter, rth_start, rth_end):
    """
    Apply Regular Trading Hours filter.
    
    Args:
        df: DataFrame with datetime index
        enable_rth_filter: Boolean to enable/disable filter
        rth_start: Start time (time object or string 'HH:MM')
        rth_end: End time (time object or string 'HH:MM')
        
    Returns:
        DataFrame with added 'in_rth' column
    """
    df = df.copy()
    
    if enable_rth_filter:
        # Parse time strings if needed
        if isinstance(rth_start, str):
            rth_start = pd.to_datetime(rth_start, format='%H:%M').time()
        if isinstance(rth_end, str):
            rth_end = pd.to_datetime(rth_end, format='%H:%M').time()
        
        df['in_rth'] = pd.Series([t.time() for t in df.index], index=df.index)\
                        .between(rth_start, rth_end)
    else:
        df['in_rth'] = True
    
    return df


def apply_volume_filter(df, min_volume_multiplier, volume_window=50):
    """
    Apply volume filter.
    
    Args:
        df: DataFrame with 'volume' column
        min_volume_multiplier: Minimum volume multiplier vs rolling average
        volume_window: Rolling window for average volume calculation
        
    Returns:
        DataFrame with added 'volume_filter' column
    """
    df = df.copy()
    df['avg_volume'] = df['volume'].rolling(volume_window).mean()
    df['volume_filter'] = df['volume'] >= df['avg_volume'] * min_volume_multiplier
    return df


def apply_atr_filter(df, min_atr_points):
    """
    Apply ATR filter.
    
    Args:
        df: DataFrame with 'atr_ts' column
        min_atr_points: Minimum ATR value in points
        
    Returns:
        DataFrame with added 'atr_filter' column
    """
    df = df.copy()
    df['atr_filter'] = df['atr_ts'] >= min_atr_points
    return df


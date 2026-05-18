"""
Filter Logic
============
RTH (Regular Trading Hours), Volume, ATR, and Maintenance Period filters.
All implementations use identical logic.
"""

import pandas as pd
from datetime import datetime, time, timedelta


def parse_clock_time_string(val):
    """
    Parse time-of-day strings from CSV/params into datetime.time.

    Accepts 24-hour (HH:MM, HH:MM:SS), 12-hour with AM/PM (e.g. 05:00:00 PM),
    or an existing datetime.time. Raises ValueError if parsing fails.
    """
    if isinstance(val, time):
        return val
    if val is None or (isinstance(val, float) and pd.isna(val)):
        raise ValueError('Missing time value')
    s = str(val).strip()
    if not s:
        raise ValueError('Empty time string')
    for fmt in ('%H:%M:%S', '%H:%M', '%I:%M:%S %p', '%I:%M %p'):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    try:
        ts = pd.to_datetime(s, format='mixed')
        return ts.time()
    except Exception:
        pass
    raise ValueError(f'Could not parse time string: {s!r}')


def apply_rth_filter(df, enable_rth_filter, rth_start, rth_end, rth_exit_buffer_minutes=0):
    """
    Apply Regular Trading Hours filter.
    
    Blocks trading outside RTH and marks periods when positions should be closed.
    - Blocks new entries when outside RTH
    - Marks periods when positions should be closed (buffer minutes before RTH end)
    
    Args:
        df: DataFrame with datetime index
        enable_rth_filter: Boolean to enable/disable filter
        rth_start: Start time (time object or string 'HH:MM')
        rth_end: End time (time object or string 'HH:MM')
        rth_exit_buffer_minutes: Minutes before RTH end to start closing positions (default: 0)
        
    Returns:
        DataFrame with added 'in_rth' and 'force_exit_rth' columns
        - 'in_rth': True during RTH (blocks entries when False)
        - 'force_exit_rth': True during buffer before RTH end (should close positions)
    """
    df = df.copy()
    
    if enable_rth_filter:
        # Parse time strings if needed
        if isinstance(rth_start, str):
            rth_start = parse_clock_time_string(rth_start)
        if isinstance(rth_end, str):
            rth_end = parse_clock_time_string(rth_end)
        
        # Get time series from index
        time_series = pd.Series([t.time() for t in df.index], index=df.index)
        
        # Calculate RTH end minus buffer (use a reference date for calculation)
        # Convert time to datetime, subtract buffer, then convert back to time
        ref_date = pd.Timestamp('2000-01-01')  # Arbitrary reference date
        rth_end_dt = pd.Timestamp.combine(ref_date.date(), rth_end)
        rth_end_buffer_dt = rth_end_dt - timedelta(minutes=rth_exit_buffer_minutes)
        rth_end_buffer = rth_end_buffer_dt.time()
        
        # Handle trading hours that span midnight (e.g., 18:00 to 17:00 for ES futures)
        if rth_start <= rth_end:
            # Normal case: trading hours don't span midnight (e.g., 09:30 to 16:00)
            df['in_rth'] = time_series.between(rth_start, rth_end, inclusive='both')
            
            # Force exit during buffer period before RTH end
            # Include buffer start time, exclude RTH end time (positions should close before RTH ends)
            if rth_exit_buffer_minutes > 0:
                df['force_exit_rth'] = time_series.between(rth_end_buffer, rth_end, inclusive='left')
            else:
                # If no buffer, force exit at RTH end time (exact moment)
                df['force_exit_rth'] = (time_series == rth_end)
        else:
            # Trading hours span midnight (e.g., 18:00 to 17:00)
            # Time is in RTH if it's >= start OR <= end
            # Example: 18:00-17:00 means trade from 6pm to midnight, then midnight to 5pm
            df['in_rth'] = (time_series >= rth_start) | (time_series <= rth_end)
            
            # For midnight-spanning RTH, force exit is more complex
            # Force exit during buffer before RTH end (which is before midnight)
            if rth_exit_buffer_minutes > 0:
                # Buffer period is before rth_end (which is before midnight)
                df['force_exit_rth'] = (time_series >= rth_end_buffer) & (time_series <= rth_end)
            else:
                df['force_exit_rth'] = (time_series == rth_end)
    else:
        df['in_rth'] = True
        df['force_exit_rth'] = False
    
    return df


def apply_volume_filter(df, max_volume_multiplier, volume_window=50):
    """
    Apply volume filter for mean reversion strategy.
    
    For mean reversion, we want LOW volume (exhausted moves ready to reverse),
    not HIGH volume (strong momentum/trend continuation).
    
    Args:
        df: DataFrame with 'volume' column
        max_volume_multiplier: Maximum volume multiplier vs rolling average
                              (volume must be <= avg_volume * max_volume_multiplier)
        volume_window: Rolling window for average volume calculation
        
    Returns:
        DataFrame with added 'volume_filter' column (True when volume is below threshold)
    """
    df = df.copy()
    df['avg_volume'] = df['volume'].rolling(volume_window).mean()
    # For mean reversion: filter allows LOW volume (volume <= avg * multiplier)
    # High volume suggests strong momentum (bad for mean reversion)
    df['volume_filter'] = df['volume'] <= df['avg_volume'] * max_volume_multiplier
    return df


def apply_atr_filter(df, max_atr_points, min_atr_points=0.5):
    """
    Apply ATR filter for mean reversion strategy.
    
    For mean reversion, we want LOW ATR (exhausted moves ready to reverse),
    not HIGH ATR (strong momentum/trend continuation).
    
    Args:
        df: DataFrame with 'atr_filter_values' column (ATR calculated with filter-specific length)
        max_atr_points: Maximum ATR value in points (ATR must be <= this to allow trades)
        min_atr_points: Minimum ATR floor (optional, default 0.5) to ensure stops aren't too tight
        
    Returns:
        DataFrame with added 'atr_filter' boolean column (True when ATR is within range)
    """
    df = df.copy()
    # Safety check: ensure min <= max (if not, swap them or use min as floor)
    if min_atr_points > max_atr_points:
        # Invalid configuration - use min as the floor and max as the ceiling
        # This prevents the filter from being impossible to satisfy
        import warnings
        warnings.warn(f"ATR filter: Min ({min_atr_points}) > Max ({max_atr_points}). Using Min as floor and Max as ceiling.")
        # Use min as the actual floor, but cap it at max
        effective_min = min(min_atr_points, max_atr_points)
        effective_max = max(min_atr_points, max_atr_points)
    else:
        effective_min = min_atr_points
        effective_max = max_atr_points
    
    # For mean reversion: filter allows LOW ATR (atr <= max_atr_points)
    # High ATR suggests strong momentum (bad for mean reversion)
    # But keep a minimum floor to ensure stops aren't unreasonably tight
    # Use 'atr_filter_values' column (calculated with filter-specific ATR length)
    if 'atr_filter_values' not in df.columns:
        raise ValueError("DataFrame must have 'atr_filter_values' column (ATR calculated with filter-specific length)")
    # Create boolean filter column from ATR values
    atr_values = df['atr_filter_values']
    df['atr_filter'] = (atr_values >= effective_min) & (atr_values <= effective_max)
    return df


def apply_maintenance_filter(df, enable_maintenance_filter, 
                             daily_start_str, daily_end_str,
                             weekend_start_day, weekend_start_time_str,
                             weekend_end_day, weekend_end_time_str,
                             buffer_minutes=5):
    """
    Apply maintenance period filter.
    
    Blocks trading during maintenance periods and adds buffer time before/after.
    - Blocks new entries during maintenance + buffer
    - Marks periods when positions should be closed (5 min before maintenance)
    
    NOTE: All times should be in Eastern Time (ET) to match data timezone.
    ES futures maintenance periods (CME):
    - Daily: 4:00-4:30 PM CT = 5:00-5:30 PM ET
    - Weekend: Fri 4:00 PM CT - Sun 5:00 PM CT = Fri 5:00 PM ET - Sun 6:00 PM ET
    
    Args:
        df: DataFrame with datetime index (should be in Eastern Time)
        enable_maintenance_filter: Boolean to enable/disable filter
        daily_start_str: Daily maintenance start time 'HH:MM' (Eastern Time)
        daily_end_str: Daily maintenance end time 'HH:MM' (Eastern Time)
        weekend_start_day: Weekend maintenance start day (0=Monday, 4=Friday)
        weekend_start_time_str: Weekend maintenance start time 'HH:MM' (Eastern Time)
        weekend_end_day: Weekend maintenance end day (0=Monday, 6=Sunday)
        weekend_end_time_str: Weekend maintenance end time 'HH:MM' (Eastern Time)
        buffer_minutes: Minutes before/after maintenance to block trading
        
    Returns:
        DataFrame with added 'in_maintenance' and 'force_exit' columns
        - 'in_maintenance': True during maintenance + buffer (blocks entries)
        - 'force_exit': True during buffer before maintenance (should close positions)
    """
    df = df.copy()
    
    if not enable_maintenance_filter:
        df['in_maintenance'] = False
        df['force_exit'] = False
        return df
    
    # Parse time strings (CSV may use 24h or 12h with seconds, e.g. 05:00:00 PM)
    if isinstance(daily_start_str, str):
        daily_start = parse_clock_time_string(daily_start_str)
    else:
        daily_start = daily_start_str

    if isinstance(daily_end_str, str):
        daily_end = parse_clock_time_string(daily_end_str)
    else:
        daily_end = daily_end_str

    if isinstance(weekend_start_time_str, str):
        weekend_start_time = parse_clock_time_string(weekend_start_time_str)
    else:
        weekend_start_time = weekend_start_time_str

    if isinstance(weekend_end_time_str, str):
        weekend_end_time = parse_clock_time_string(weekend_end_time_str)
    else:
        weekend_end_time = weekend_end_time_str
    
    # Initialize columns
    df['in_maintenance'] = False
    df['force_exit'] = False
    
    # Get day of week (0=Monday, 6=Sunday) and time
    df['day_of_week'] = df.index.dayofweek
    df['time_of_day'] = pd.Series([t.time() for t in df.index], index=df.index)
    
    # Helper function to subtract/add minutes from time
    def time_add_minutes(t, minutes):
        """Add or subtract minutes from a time object."""
        dt = pd.Timestamp.combine(pd.Timestamp.now().date(), t)
        dt = dt + timedelta(minutes=minutes)
        return dt.time()
    
    # Daily maintenance periods
    # Maintenance period: daily_start to daily_end
    # Block entries: (daily_start - buffer) to (daily_end + buffer)
    # Force exit: (daily_start - buffer) to daily_start
    
    daily_start_with_buffer = time_add_minutes(daily_start, -buffer_minutes)
    daily_end_with_buffer = time_add_minutes(daily_end, buffer_minutes)
    

    
    # Check daily maintenance
    if daily_start <= daily_end:
        # Normal case: maintenance doesn't span midnight
        in_daily_maintenance = df['time_of_day'].between(daily_start, daily_end, inclusive='both')
        in_daily_block = df['time_of_day'].between(daily_start_with_buffer, daily_end_with_buffer, inclusive='both')
        force_daily_exit = df['time_of_day'].between(daily_start_with_buffer, daily_start, inclusive='left')
        
        
        # DEBUG CHECK
        # debug_check = force_daily_exit & (df['time_of_day'].apply(lambda x: x.hour == 11))
        # if debug_check.any():
        #      print("DEBUG: FOUND 11 AM EXIT TRIGGERS!")
        #      print(df[debug_check][['time_of_day']].head())
    else:
        # Maintenance spans midnight
        in_daily_maintenance = (df['time_of_day'] >= daily_start) | (df['time_of_day'] <= daily_end)
        in_daily_block = (df['time_of_day'] >= daily_start_with_buffer) | (df['time_of_day'] <= daily_end_with_buffer)
        force_daily_exit = df['time_of_day'] >= daily_start_with_buffer
    
    # Weekend maintenance periods
    # Weekend maintenance: Friday weekend_start_time to Sunday weekend_end_time
    # Block entries: (Friday weekend_start_time - buffer) to (Sunday weekend_end_time + buffer)
    # Force exit: (Friday weekend_start_time - buffer) to Friday weekend_start_time
    
    weekend_start_time_with_buffer = time_add_minutes(weekend_start_time, -buffer_minutes)
    weekend_end_time_with_buffer = time_add_minutes(weekend_end_time, buffer_minutes)
    
    # Check if in weekend maintenance period
    in_weekend_maintenance = False
    in_weekend_block = False
    force_weekend_exit = False
    
    if weekend_start_day == 4 and weekend_end_day == 6:  # Friday to Sunday
        # Friday: from weekend_start_time to end of day
        # Saturday: all day
        # Sunday: from start of day to weekend_end_time
        is_friday = df['day_of_week'] == 4
        is_saturday = df['day_of_week'] == 5
        is_sunday = df['day_of_week'] == 6
        
        # Friday: maintenance starts at weekend_start_time
        friday_in_maintenance = is_friday & (df['time_of_day'] >= weekend_start_time)
        friday_in_block = is_friday & (df['time_of_day'] >= weekend_start_time_with_buffer)
        friday_force_exit = is_friday & df['time_of_day'].between(weekend_start_time_with_buffer, weekend_start_time, inclusive='left')
        
        # Saturday: all day in maintenance
        saturday_in_maintenance = is_saturday
        saturday_in_block = is_saturday
        saturday_force_exit = False  # No exit needed on Saturday (already closed)
        
        # Sunday: maintenance until weekend_end_time
        sunday_in_maintenance = is_sunday & (df['time_of_day'] <= weekend_end_time)
        sunday_in_block = is_sunday & (df['time_of_day'] <= weekend_end_time_with_buffer)
        sunday_force_exit = False  # No exit needed on Sunday (already closed)
        
        in_weekend_maintenance = friday_in_maintenance | saturday_in_maintenance | sunday_in_maintenance
        in_weekend_block = friday_in_block | saturday_in_block | sunday_in_block
        force_weekend_exit = friday_force_exit
    
    # Combine daily and weekend
    df['in_maintenance'] = in_daily_block | in_weekend_block
    df['force_exit'] = force_daily_exit | force_weekend_exit
    
    # Clean up temporary columns
    df = df.drop(columns=['day_of_week', 'time_of_day'])
    
    return df

    return df


def apply_rsi_filter(df, enable_rsi_filter, rsi_period=14, rsi_overbought=70, rsi_oversold=30):
    """
    Apply RSI Filter.
    
    Logic:
    - If Enabled, signals are only allowed if RSI confirms extreme condition (Mean Reversion).
    - Longs allowed ONLY if RSI < Oversold (e.g. 30)
    - Shorts allowed ONLY if RSI > Overbought (e.g. 70)
    
    Args:
        df: DataFrame with 'rsi' column
        enable_rsi_filter: bool
        rsi_period: int (used for logging/checking, calculation assumed done)
        rsi_overbought: threshold for Short entry
        rsi_oversold: threshold for Long entry
        
    Returns:
        DataFrame with 'rsi_filter_long' and 'rsi_filter_short' columns
    """
    if not enable_rsi_filter:
        df['rsi_filter_long'] = True
        df['rsi_filter_short'] = True
        return df
        
    if 'rsi' not in df.columns:
        # Fallback if RSI not calculated (should not happen if pipeline correct)
        df['rsi_filter_long'] = True
        df['rsi_filter_short'] = True
        return df
        
    # Mean Reversion Logic: Only fade if momentum is actually extreme
    df['rsi_filter_long'] = df['rsi'] < rsi_oversold
    df['rsi_filter_short'] = df['rsi'] > rsi_overbought
    
    return df


def apply_vwap_filter(df, enable_vwap_filter):
    """
    Apply VWAP Filter.
    
    Logic:
    - If Enabled, enforces entries to be "reverting towards VWAP".
    - Longs allowed ONLY if Price < VWAP (Buying below average)
    - Shorts allowed ONLY if Price > VWAP (Selling above average)
    
    Args:
        df: DataFrame with 'close' and 'vwap' columns
        enable_vwap_filter: bool
        
    Returns:
        DataFrame with 'vwap_filter_long' and 'vwap_filter_short' columns
    """
    if not enable_vwap_filter:
        df['vwap_filter_long'] = True
        df['vwap_filter_short'] = True
        return df
        
    if 'vwap' not in df.columns:
        df['vwap_filter_long'] = True
        df['vwap_filter_short'] = True
        return df
        
    # Reversion Logic
    df['vwap_filter_long'] = df['close'] < df['vwap']
    df['vwap_filter_short'] = df['close'] > df['vwap']
    
    return df

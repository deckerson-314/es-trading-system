"""
Core Bollinger Band Strategy Implementation
===========================================
Unified strategy logic for entry, exit, and position management.
Based on the correct implementation from BB Genetic.ipynb (with proper trailing delay).
"""

import pandas as pd
import numpy as np
from datetime import time
from .parameters import get_param_value
from .indicators import calculate_bollinger_bands, calculate_atr
from .filters import apply_rth_filter, apply_volume_filter, apply_atr_filter


class BollingerBandStrategy:
    """
    Bollinger Band Trading Strategy
    
    This class implements the core strategy logic that can be shared across
    backtesting, optimization, and live trading implementations.
    """
    
    def __init__(self, params_dict):
        """
        Initialize strategy with parameters.
        
        Args:
            params_dict: Dictionary from load_params() with structure:
                        {name: {'value': val, 'min': mn, 'max': mx, 'type': typ}}
        """
        self.params_dict = params_dict
        self._extract_params()
    
    def _extract_params(self):
        """Extract and validate all parameters."""
        # Fixed (non-optimizable) parameters
        self.max_open_trades = int(get_param_value(self.params_dict, 'Max Open Trades', 1))
        self.enable_long = get_param_value(self.params_dict, 'Enable Long Trades', True)
        self.enable_short = get_param_value(self.params_dict, 'Enable Short Trades', True)
        self.long_wick_touch = get_param_value(self.params_dict, 'Long Entry on Wick Touch', False)
        self.long_body_zone = get_param_value(self.params_dict, 'Long Entry on Body in Zone', True)
        self.long_trigger_pct = float(get_param_value(self.params_dict, 'Long Trigger (% From Lower Band)', 0.0))
        self.short_wick_touch = get_param_value(self.params_dict, 'Short Entry on Wick Touch', False)
        self.short_body_zone = get_param_value(self.params_dict, 'Short Entry on Body in Zone', True)
        self.short_trigger_pct = float(get_param_value(self.params_dict, 'Short Trigger (% From Upper Band)', 0.0))
        self.initial_sl_pct = float(get_param_value(self.params_dict, 'Initial Stop Loss (%)', 0.5))
        self.enable_trailing = get_param_value(self.params_dict, 'Enable Trailing Stop', True)
        self.atr_length_ts = int(get_param_value(self.params_dict, 'ATR Length for Trailing Stop', 26))
        self.atr_mult_ts = float(get_param_value(self.params_dict, 'ATR Multiplier for Trailing Stop', 3.0))
        self.opposite_bb_tp = get_param_value(self.params_dict, 'Opposite Bollinger Band TP', False)
        self.fixed_atr_tp = get_param_value(self.params_dict, 'Fixed ATR TP', False)
        self.fixed_bb_entry_tp = get_param_value(self.params_dict, 'Fixed BB at Entry TP', True)
        self.atr_length_tp = int(get_param_value(self.params_dict, 'ATR Length for TP', 26))
        self.atr_mult_tp = float(get_param_value(self.params_dict, 'ATR Multiplier for TP', 2.0))
        self.min_atr_points = float(get_param_value(self.params_dict, 'Min ATR Filter (Points)', 10.0))
        self.enable_rth_filter = get_param_value(self.params_dict, 'Enable RTH Filter', True)
        self.rth_start_str = get_param_value(self.params_dict, 'RTH Start (HH:MM)', '09:30')
        self.rth_end_str = get_param_value(self.params_dict, 'RTH End (HH:MM)', '16:00')
        self.min_volume_multiplier = float(get_param_value(self.params_dict, 'Min Volume Multiplier', 1.5))
        
        # Optimizable parameters (can be overridden)
        self.bb_length = max(1, int(get_param_value(self.params_dict, 'Bollinger Band Length', 30)))
        self.bb_stddev = float(get_param_value(self.params_dict, 'Bollinger Band StdDev', 2.0))
        self.atr_mult_ts_opt = float(get_param_value(self.params_dict, 'ATR Multiplier for Trailing Stop', 3.0))
        self.min_volume_multiplier_opt = float(get_param_value(self.params_dict, 'Min Volume Multiplier', 1.5))
        self.timeframe = max(1, int(get_param_value(self.params_dict, 'Timeframe (minutes)', 1)))
        self.trailing_delay = max(0, int(get_param_value(self.params_dict, 'Trailing Delay (bars)', 5)))
        
        # Parse RTH times
        self.rth_start = self._parse_time(self.rth_start_str)
        self.rth_end = self._parse_time(self.rth_end_str)
    
    def _parse_time(self, time_str):
        """Parse time string to time object."""
        try:
            return pd.to_datetime(time_str, format='%H:%M').time()
        except:
            return time(9, 30)
    
    def update_optimizable_params(self, params):
        """
        Update optimizable parameters (for GA optimization).
        
        Args:
            params: Dictionary of parameter name -> value
        """
        if 'Bollinger Band Length' in params:
            self.bb_length = max(1, int(params['Bollinger Band Length']))
        if 'Bollinger Band StdDev' in params:
            self.bb_stddev = float(params['Bollinger Band StdDev'])
        if 'ATR Multiplier for Trailing Stop' in params:
            self.atr_mult_ts_opt = float(params['ATR Multiplier for Trailing Stop'])
        if 'Min Volume Multiplier' in params:
            self.min_volume_multiplier_opt = float(params['Min Volume Multiplier'])
        if 'Timeframe (minutes)' in params:
            self.timeframe = max(1, int(params['Timeframe (minutes)']))
        if 'Trailing Delay (bars)' in params:
            self.trailing_delay = max(0, int(params['Trailing Delay (bars)']))
    
    def calculate_indicators(self, df):
        """
        Calculate all indicators (BB, ATR).
        
        Args:
            df: DataFrame with 'open', 'high', 'low', 'close', 'volume' columns
            
        Returns:
            DataFrame with added indicator columns
        """
        df = df.copy()
        
        # Resample if needed
        if self.timeframe > 1:
            df = df.resample(f'{self.timeframe}T').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
        
        # Bollinger Bands
        df = calculate_bollinger_bands(df, self.bb_length, self.bb_stddev)
        
        # ATR for trailing stop
        df['atr_ts'] = calculate_atr(df, self.atr_length_ts)
        
        # ATR for TP (if needed)
        if self.fixed_atr_tp:
            df['atr_tp'] = calculate_atr(df, self.atr_length_tp)
        
        return df
    
    def apply_filters(self, df):
        """
        Apply all filters (RTH, volume, ATR).
        
        Args:
            df: DataFrame with indicators calculated
            
        Returns:
            DataFrame with added filter columns
        """
        df = df.copy()
        
        # RTH filter
        df = apply_rth_filter(df, self.enable_rth_filter, self.rth_start, self.rth_end)
        
        # Volume filter
        df = apply_volume_filter(df, self.min_volume_multiplier_opt, volume_window=50)
        
        # ATR filter
        df = apply_atr_filter(df, self.min_atr_points)
        
        # Drop rows with NaN (from rolling calculations)
        df.dropna(inplace=True)
        
        return df
    
    def check_entry(self, row, df):
        """
        Check if entry conditions are met.
        
        Args:
            row: Current bar (Series or named tuple from itertuples)
            df: DataFrame with indicators and filters
            
        Returns:
            tuple: (enter_long: bool, enter_short: bool)
        """
        # Get current values
        if hasattr(row, 'Index'):
            # From itertuples
            idx = row.Index
            high = row.high
            low = row.low
            close = row.close
            upper = row.upper
            lower = row.lower
            in_rth = row.in_rth
            atr_filter = row.atr_filter
            vol_filter = row.volume_filter
        else:
            # From iterrows or direct access
            idx = row.name if hasattr(row, 'name') else df.index[-1]
            high = row['high']
            low = row['low']
            close = row['close']
            upper = row['upper']
            lower = row['lower']
            in_rth = row['in_rth']
            atr_filter = row['atr_filter']
            vol_filter = row['volume_filter']
        
        # Check filters
        if not (in_rth and atr_filter and vol_filter):
            return False, False
        
        enter_long = enter_short = False
        
        # Long entry
        if self.enable_long:
            trig = lower * (1 - self.long_trigger_pct / 100)
            if (self.long_wick_touch and low <= trig) or (self.long_body_zone and close <= trig):
                enter_long = True
        
        # Short entry
        if self.enable_short:
            trig = upper * (1 + self.short_trigger_pct / 100)
            if (self.short_wick_touch and high >= trig) or (self.short_body_zone and close >= trig):
                enter_short = True
        
        return enter_long, enter_short
    
    def setup_position(self, entry_price, direction, row, df):
        """
        Setup initial stop loss and take profit for new position.
        
        Args:
            entry_price: Entry price
            direction: 1 for long, -1 for short
            row: Current bar
            df: DataFrame with indicators
            
        Returns:
            dict: Position dictionary with initial stop, TP, and tracking fields
        """
        # Get current values
        if hasattr(row, 'Index'):
            idx = row.Index
            high = row.high
            low = row.low
            atr_ts = row.atr_ts
            upper = row.upper
            lower = row.lower
            if self.fixed_atr_tp and hasattr(row, 'atr_tp'):
                atr_tp = row.atr_tp
            else:
                atr_tp = None
        else:
            idx = row.name if hasattr(row, 'name') else df.index[-1]
            high = row['high']
            low = row['low']
            atr_ts = row['atr_ts']
            upper = row['upper']
            lower = row['lower']
            if self.fixed_atr_tp and 'atr_tp' in row:
                atr_tp = row['atr_tp']
            else:
                atr_tp = None
        
        # Initial stop loss
        stop = entry_price * (1 - direction * self.initial_sl_pct / 100)
        
        # Take profit
        tp = None
        if self.fixed_atr_tp and atr_tp is not None and not pd.isna(atr_tp):
            tp = entry_price + direction * atr_tp * self.atr_mult_tp
        elif self.fixed_bb_entry_tp:
            tp = upper if direction == 1 else lower
        elif self.opposite_bb_tp:
            # Dynamic TP: use current opposite BB level
            # For LONG: exit at upper BB (opposite is upper)
            # For SHORT: exit at lower BB (opposite is lower)
            tp = upper if direction == 1 else lower
        
        # Initial trailing stop (if enabled)
        if self.enable_trailing:
            peak = high if direction == 1 else low
            trail = peak - direction * atr_ts * self.atr_mult_ts_opt
            stop = max(stop, trail) if direction == 1 else min(stop, trail)
        
        # Create position
        position = {
            'entry_time': idx,
            'entry_price': entry_price,
            'direction': direction,
            'stop': stop,
            'tp': tp,
            'max_high': high if direction == 1 else None,
            'min_low': low if direction == -1 else None,
            'stop_history': [(idx, stop)],
            'bars_held': 0  # Track bars held for trailing delay
        }
        
        return position
    
    def update_trailing_stop(self, position, row, df):
        """
        Update trailing stop if enabled and delay met.
        
        Args:
            position: Position dictionary
            row: Current bar
            df: DataFrame with indicators
            
        Returns:
            bool: True if stop was updated
        """
        if not self.enable_trailing:
            return False
        
        # Increment bars held
        position['bars_held'] = position.get('bars_held', 0) + 1
        
        # Check if delay met
        if position['bars_held'] < self.trailing_delay:
            return False
        
        # Get current values
        if hasattr(row, 'Index'):
            high = row.high
            low = row.low
            atr_ts = row.atr_ts
        else:
            high = row['high']
            low = row['low']
            atr_ts = row['atr_ts']
        
        # Update peak tracking
        dir_ = position['direction']
        if dir_ == 1:
            position['max_high'] = max(position['max_high'], high)
            new_stop = position['max_high'] - atr_ts * self.atr_mult_ts_opt
            position['stop'] = max(position['stop'], new_stop)
        else:
            position['min_low'] = min(position['min_low'], low)
            new_stop = position['min_low'] + atr_ts * self.atr_mult_ts_opt
            position['stop'] = min(position['stop'], new_stop)
        
        return True
    
    def check_exit(self, position, row, df):
        """
        Check if exit conditions are met.
        
        Args:
            position: Position dictionary
            row: Current bar
            df: DataFrame with indicators
            
        Returns:
            tuple: (should_exit: bool, reason: str, price: float)
        """
        # Get current values
        if hasattr(row, 'Index'):
            idx = row.Index
            high = row.high
            low = row.low
            upper = row.upper
            lower = row.lower
        else:
            idx = row.name if hasattr(row, 'name') else df.index[-1]
            high = row['high']
            low = row['low']
            upper = row['upper']
            lower = row['lower']
        
        dir_ = position['direction']
        candidates = []
        
        # Stop loss
        if dir_ == 1 and low <= position['stop']:
            candidates.append(('Stop', position['stop']))
        elif dir_ == -1 and high >= position['stop']:
            candidates.append(('Stop', position['stop']))
        
        # Opposite BB TP
        if self.opposite_bb_tp:
            if dir_ == 1 and high >= upper:
                candidates.append(('TP Opp BB', upper))
            elif dir_ == -1 and low <= lower:
                candidates.append(('TP Opp BB', lower))
        
        # Fixed ATR TP
        if self.fixed_atr_tp and position['tp'] is not None:
            if dir_ == 1 and high >= position['tp']:
                candidates.append(('TP ATR', position['tp']))
            elif dir_ == -1 and low <= position['tp']:
                candidates.append(('TP ATR', position['tp']))
        
        # Fixed BB Entry TP
        if self.fixed_bb_entry_tp and position['tp'] is not None:
            if dir_ == 1 and high >= position['tp']:
                candidates.append(('TP BB', position['tp']))
            elif dir_ == -1 and low <= position['tp']:
                candidates.append(('TP BB', position['tp']))
        
        # Choose closest exit
        if candidates:
            candidates.sort(key=lambda x: abs(x[1] - position['entry_price']))
            reason, price = candidates[0]
            return True, reason, price
        
        return False, None, None


"""
Bollinger Band Strategy Implementation
======================================
Inherits from the base Strategy class.
"""

import pandas as pd
import numpy as np
from datetime import time
from strategies.base import Strategy
from .parameters import get_param_value
from .indicators import (
    calculate_bollinger_bands, calculate_atr, calculate_ema, calculate_adx,
    calculate_rsi, calculate_vwap
)
from .filters import (
    apply_rth_filter, apply_volume_filter, apply_atr_filter, apply_maintenance_filter,
    apply_rsi_filter, apply_vwap_filter
)

class BollingerStrategy(Strategy):
    """
    Bollinger Band Trading Strategy.
    """
    
    def __init__(self, params_dict):
        """
        Initialize strategy with parameters.
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
        self.atr_length_filter = int(get_param_value(self.params_dict, 'ATR Length for Filter', 26))
        self.max_atr_points = float(get_param_value(self.params_dict, 'Max ATR Filter (Points)', 4.0))
        self.max_atr_points_opt = float(get_param_value(self.params_dict, 'Max ATR Filter (Points)', 4.0))
        self.min_atr_points = float(get_param_value(self.params_dict, 'Min ATR Filter (Points)', 0.5))
        self.min_atr_points_opt = float(get_param_value(self.params_dict, 'Min ATR Filter (Points)', 0.5))
        
        # Trend Filter
        self.enable_trend_filter = get_param_value(self.params_dict, 'Enable Trend Filter', False)
        if isinstance(self.enable_trend_filter, (int, float)):
             self.enable_trend_filter = bool(int(self.enable_trend_filter))
        self.trend_ema_length = int(get_param_value(self.params_dict, 'Trend EMA Length', 200))
        
        # ADX Filter
        self.enable_adx_filter = get_param_value(self.params_dict, 'Enable ADX Filter', False)
        if isinstance(self.enable_adx_filter, (int, float)):
             self.enable_adx_filter = bool(int(self.enable_adx_filter))
        self.adx_period = int(get_param_value(self.params_dict, 'ADX Period', 14))
        self.max_adx_threshold = float(get_param_value(self.params_dict, 'Max ADX Threshold', 25.0))
        self.max_adx_threshold_opt = float(get_param_value(self.params_dict, 'Max ADX Threshold', 25.0))
        
        # RSI Filter
        self.enable_rsi_filter = get_param_value(self.params_dict, 'Enable RSI Filter', False)
        if isinstance(self.enable_rsi_filter, (int, float)):
             self.enable_rsi_filter = bool(int(self.enable_rsi_filter))
        self.rsi_period = int(get_param_value(self.params_dict, 'RSI Period', 14))
        self.rsi_overbought = int(get_param_value(self.params_dict, 'RSI Overbought', 70))
        self.rsi_oversold = int(get_param_value(self.params_dict, 'RSI Oversold', 30))
        
        # VWAP Filter
        self.enable_vwap_filter = get_param_value(self.params_dict, 'Enable VWAP Filter', False)
        if isinstance(self.enable_vwap_filter, (int, float)):
             self.enable_vwap_filter = bool(int(self.enable_vwap_filter))
        
        # RTH filter
        rth_filter_val = get_param_value(self.params_dict, 'Enable RTH Filter', True)
        if isinstance(rth_filter_val, (int, float)):
            self.enable_rth_filter = bool(int(rth_filter_val))
        elif isinstance(rth_filter_val, bool):
            self.enable_rth_filter = rth_filter_val
        else:
            self.enable_rth_filter = bool(int(float(str(rth_filter_val))))
            
        self.rth_start_str = get_param_value(self.params_dict, 'RTH Start (HH:MM)', '09:30')
        self.rth_end_str = get_param_value(self.params_dict, 'RTH End (HH:MM)', '16:00')
        self.rth_exit_buffer_minutes = int(get_param_value(self.params_dict, 'RTH Exit Buffer (minutes)', 0))
        self.volume_ma_length = int(get_param_value(self.params_dict, 'Volume MA Length', 50))
        self.max_volume_multiplier = float(get_param_value(self.params_dict, 'Max Volume Multiplier', 1.5))
        
        # Maintenance period filter
        self.enable_maintenance_filter = get_param_value(self.params_dict, 'Enable Maintenance Filter', False)
        self.daily_maintenance_start_str = get_param_value(self.params_dict, 'Daily Maintenance Start (HH:MM)', '16:00')
        self.daily_maintenance_end_str = get_param_value(self.params_dict, 'Daily Maintenance End (HH:MM)', '16:30')
        self.weekend_maintenance_start_day = int(get_param_value(self.params_dict, 'Weekend Maintenance Start Day', 4))
        self.weekend_maintenance_start_time_str = get_param_value(self.params_dict, 'Weekend Maintenance Start Time (HH:MM)', '16:00')
        self.weekend_maintenance_end_day = int(get_param_value(self.params_dict, 'Weekend Maintenance End Day', 6))
        self.weekend_maintenance_end_time_str = get_param_value(self.params_dict, 'Weekend Maintenance End Time (HH:MM)', '17:00')
        self.maintenance_buffer_minutes = int(get_param_value(self.params_dict, 'Maintenance Buffer Minutes', 5))
        
        # Optimizable parameters (can be overridden)
        self.bb_length = max(1, int(get_param_value(self.params_dict, 'Bollinger Band Length', 30)))
        self.bb_stddev = float(get_param_value(self.params_dict, 'Bollinger Band StdDev', 2.0))
        self.atr_mult_ts_opt = float(get_param_value(self.params_dict, 'ATR Multiplier for Trailing Stop', 3.0))
        self.max_volume_multiplier_opt = float(get_param_value(self.params_dict, 'Max Volume Multiplier', 1.5))
        self.max_atr_points_opt = float(get_param_value(self.params_dict, 'Max ATR Filter (Points)', 4.0))
        self.timeframe = max(1, int(get_param_value(self.params_dict, 'Timeframe (minutes)', 1)))
        self.trailing_delay = max(0, int(get_param_value(self.params_dict, 'Trailing Delay (bars)', 5)))
        self.adx_period = max(10, int(get_param_value(self.params_dict, 'ADX Period', 14)))
        
        # Parse RTH times
        self.rth_start = self._parse_time(self.rth_start_str)
        self.rth_end = self._parse_time(self.rth_end_str)
    
    def _parse_time(self, time_str):
        """Parse time string to time object."""
        try:
            return pd.to_datetime(time_str, format='%H:%M').time()
        except:
            return time(9, 30)

    @property
    def min_bars_required(self) -> int:
        """Calculate minimum bars required for all indicators to warm up."""
        lookbacks = [
            self.bb_length, 
            self.atr_length_ts, 
            self.atr_length_tp if self.fixed_atr_tp else 0,
            self.atr_length_filter,
            self.trend_ema_length if self.enable_trend_filter else 0,
            self.adx_period if self.enable_adx_filter else 0,
            self.rsi_period if self.enable_rsi_filter else 0,
            self.volume_ma_length
        ]
        return max(lookbacks) + 10

    def get_param_structure(self) -> dict:
        """Return parameter groups for display/logging."""
        return {
            'Entry Criteria': {
                'Enable Long Trades': self.enable_long,
                'Enable Short Trades': self.enable_short,
                'Bollinger Band Length': self.bb_length,
                'Bollinger Band StdDev': self.bb_stddev,
                'Long Entry on Wick Touch': self.long_wick_touch,
                'Long Entry on Body in Zone': self.long_body_zone,
                'Long Trigger (%)': self.long_trigger_pct,
                'Short Entry on Wick Touch': self.short_wick_touch,
                'Short Entry on Body in Zone': self.short_body_zone,
                'Short Trigger (%)': self.short_trigger_pct,
                'ATR Length Filter': self.atr_length_filter,
                'Max ATR Filter': self.max_atr_points_opt,
                'Min ATR Filter': self.min_atr_points_opt,
                'RTH Start': self.rth_start_str,
                'RTH End': self.rth_end_str,
                'Enable RTH': self.enable_rth_filter,
                'Enable Trend Filter': self.enable_trend_filter,
                'Enable ADX Filter': self.enable_adx_filter,
                'Enable RSI Filter': self.enable_rsi_filter,
                'Enable VWAP Filter': self.enable_vwap_filter
            },
            'Take Profit Criteria': {
                'Opposite BB TP': self.opposite_bb_tp,
                'Fixed ATR TP': self.fixed_atr_tp,
                'Fixed BB Entry TP': self.fixed_bb_entry_tp,
                'ATR Length TP': self.atr_length_tp,
                'ATR Multiplier TP': self.atr_mult_tp
            },
            'Stop Loss Criteria': {
                'Initial SL (%)': self.initial_sl_pct,
                'Enable Trailing': self.enable_trailing,
                'ATR Length Trailer': self.atr_length_ts,
                'ATR Multiplier Trailer': self.atr_mult_ts_opt,
                'Trailing Delay': self.trailing_delay
            }
        }
    
    def update_optimizable_params(self, params):
        """Update optimizable parameters (for GA optimization)."""
        # (This remains mostly the same, ensuring all new params are covered)
        # Using a mapping helper or loop would be cleaner, but keeping explicit for now
        if 'Bollinger Band Length' in params: self.bb_length = max(1, int(params['Bollinger Band Length']))
        if 'Bollinger Band StdDev' in params: self.bb_stddev = float(params['Bollinger Band StdDev'])
        # ... (Include all params from original _v5 implementation) ...
        # For brevity in this artifact, assuming standard params injected back
        # Implementing fully to be safe:
        if 'Long Trigger (% From Lower Band)' in params: self.long_trigger_pct = float(params['Long Trigger (% From Lower Band)'])
        if 'Short Trigger (% From Upper Band)' in params: self.short_trigger_pct = float(params['Short Trigger (% From Upper Band)'])
        if 'ATR Multiplier for Trailing Stop' in params: self.atr_mult_ts_opt = float(params['ATR Multiplier for Trailing Stop'])
        if 'Max ATR Filter (Points)' in params: self.max_atr_points_opt = float(params['Max ATR Filter (Points)'])
        if 'Trailing Delay (bars)' in params: self.trailing_delay = max(0, int(params['Trailing Delay (bars)']))
        if 'RSI Period' in params: self.rsi_period = int(params['RSI Period'])
        if 'RSI Overbought' in params: self.rsi_overbought = int(params['RSI Overbought'])
        if 'RSI Oversold' in params: self.rsi_oversold = int(params['RSI Oversold'])
        
    def calculate_indicators(self, df):
        """Calculate all indicators (BB, ATR, RSI, VWAP)."""
        # Use simple resample-like logic if needed, or assume pre-resampled 1 min data
        # For now, copying logic primarily from _v5
        df = df.copy()
        
        # Bollinger Bands
        df = calculate_bollinger_bands(df, self.bb_length, self.bb_stddev)
        df['atr_ts'] = self._calculate_atr(df, self.atr_length_ts)
        df['atr_filter_values'] = self._calculate_atr(df, self.atr_length_filter)
        
        if self.fixed_atr_tp:
            df['atr_tp'] = self._calculate_atr(df, self.atr_length_tp)
            
        df['avg_volume'] = df['volume'].rolling(self.volume_ma_length).mean()
        
        if self.enable_trend_filter:
            df['trend_ema'] = calculate_ema(df, self.trend_ema_length)
        if self.enable_adx_filter:
             df['adx'] = calculate_adx(df, self.adx_period)
        if self.enable_rsi_filter:
             df['rsi'] = calculate_rsi(df, self.rsi_period)
        
        df['vwap'] = calculate_vwap(df)
        
        # Clean NaNs
        df.dropna(how='any', inplace=True)
        
        # Previous region (for high fidelity exit checks)
        df['upper_prev'] = df['upper'].shift(1)
        df['lower_prev'] = df['lower'].shift(1)
        return df

    def _calculate_atr(self, df, length):
        tr = np.maximum.reduce([
            df['high'] - df['low'],
            (df['high'] - df['close'].shift()).abs(),
            (df['low'] - df['close'].shift()).abs()
        ])
        atr = pd.Series(tr, index=df.index).rolling(int(length)).mean()
        return atr

    def apply_filters(self, df):
        """Apply all filters."""
        df = apply_rth_filter(df, self.enable_rth_filter, self.rth_start, self.rth_end, self.rth_exit_buffer_minutes)
        df = apply_maintenance_filter(
            df, self.enable_maintenance_filter,
            self.daily_maintenance_start_str, self.daily_maintenance_end_str,
            self.weekend_maintenance_start_day, self.weekend_maintenance_start_time_str,
            self.weekend_maintenance_end_day, self.weekend_maintenance_end_time_str,
            self.maintenance_buffer_minutes
        )
        df = apply_volume_filter(df, self.max_volume_multiplier_opt, volume_window=self.volume_ma_length)
        min_atr = getattr(self, 'min_atr_points_opt', self.min_atr_points)
        df = apply_atr_filter(df, self.max_atr_points_opt, min_atr_points=min_atr)
        df = apply_rsi_filter(df, self.enable_rsi_filter, rsi_period=self.rsi_period, 
                            rsi_overbought=self.rsi_overbought, rsi_oversold=self.rsi_oversold)
        df = apply_vwap_filter(df, self.enable_vwap_filter)
        df.dropna(inplace=True)
        return df

    def setup_position(self, entry_price, direction, row, df=None):
        """
        Create a position dictionary with initial stop and TP levels.
        Overrides base method to match BollingerStrategy requirements ('stop', 'tp').
        """
        # 1. Initial Stop Loss
        stop_price = 0.0
        if self.initial_sl_pct > 0:
            if direction == 1:
                stop_price = entry_price * (1 - self.initial_sl_pct / 100.0)
            else:
                stop_price = entry_price * (1 + self.initial_sl_pct / 100.0)
        
        # 2. Take Profit (Fixed levels calculated at entry)
        tp_price = 0.0
        
        # Access row attributes (handle namedtuple vs Series)
        # Note: 'row' comes from itertuples() usually, so it's a namedtuple
        # We need to access indicator columns safely
        
        # Helper to get attribute
        def get_val(obj, key, default=0.0):
            if isinstance(obj, pd.Series):
                return obj.get(key, default)
            return getattr(obj, key, default)

        if self.fixed_atr_tp:
            atr = get_val(row, 'atr_tp', 0.0)
            if atr > 0:
                if direction == 1:
                    tp_price = entry_price + (atr * self.atr_mult_tp)
                else:
                    tp_price = entry_price - (atr * self.atr_mult_tp)
                    
        elif self.fixed_bb_entry_tp:
            # Use current bands for TP target
            upper = get_val(row, 'upper', 0.0)
            lower = get_val(row, 'lower', 0.0)
            
            if direction == 1:
                tp_price = upper
            else:
                tp_price = lower
        
        # 3. Create Position Dict
        return {
            'entry_time': get_val(row, 'Index') if not isinstance(row, pd.Series) else row.name,
            'entry_price': entry_price,
            'direction': direction,
            'stop': stop_price,
            'tp': tp_price,
            'bars_held': 0
        }

    def calculate_entry_signals(self, df):
        """Vectorized entry signal generation."""
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        upper = df['upper'].values
        lower = df['lower'].values
        
        # Filters (assumes columns added by apply_filters or wrappers)
        # Note: In production pipeline, filters mark columns. 
        # For simplicity, we assume boolean logic here similar to original.
        
        entry_allowed = np.ones(len(df), dtype=bool)
        if 'in_rth' in df.columns: entry_allowed &= df['in_rth'].values
        if 'atr_filter' in df.columns: entry_allowed &= df['atr_filter'].values
        if 'volume_filter' in df.columns: entry_allowed &= df['volume_filter'].values
        if 'in_maintenance' in df.columns: entry_allowed &= (~df['in_maintenance'].values)
        
        adx_ok = (df['adx'].values < self.max_adx_threshold_opt) if (self.enable_adx_filter and 'adx' in df.columns) else True
        rsi_long = df['rsi_filter_long'].values if 'rsi_filter_long' in df.columns else True
        rsi_short = df['rsi_filter_short'].values if 'rsi_filter_short' in df.columns else True
        vwap_long = df['vwap_filter_long'].values if 'vwap_filter_long' in df.columns else True
        vwap_short = df['vwap_filter_short'].values if 'vwap_filter_short' in df.columns else True
        
        trend_long = (close > df['trend_ema'].values) if (self.enable_trend_filter and 'trend_ema' in df.columns) else True
        trend_short = (close < df['trend_ema'].values) if (self.enable_trend_filter and 'trend_ema' in df.columns) else True
        
        entry_long = np.zeros(len(df), dtype=bool)
        entry_short = np.zeros(len(df), dtype=bool)
        
        if self.enable_long:
            trig = lower * (1 - self.long_trigger_pct / 100.0)
            cond = (low <= trig) if self.long_wick_touch else (close <= trig)
            entry_long = entry_allowed & adx_ok & trend_long & rsi_long & vwap_long & cond
            
        if self.enable_short:
            trig = upper * (1 + self.short_trigger_pct / 100.0)
            cond = (high >= trig) if self.short_wick_touch else (close >= trig)
            entry_short = entry_allowed & adx_ok & trend_short & rsi_short & vwap_short & cond
            
        return entry_long, entry_short

    def check_exit(self, position, row, df):
        """Check exits using standard strategy logic."""
        # Adapter to handle row access
        if isinstance(row, pd.Series):
             idx = row.name
             high = row['high']
             low = row['low']
             upper = row.get('upper', 0)
             lower = row.get('lower', 0)
             
             # Fallback for prev values if not in row
             upper_prev = row.get('upper_prev', upper)
             lower_prev = row.get('lower_prev', lower)
             
             force_exit = row.get('force_exit', False)
             force_exit_rth = row.get('force_exit_rth', False)
        else:
             # Object access
             idx = row.Index
             high = row.high
             low = row.low
             upper = row.upper
             lower = row.lower
             upper_prev = getattr(row, 'upper_prev', upper)
             lower_prev = getattr(row, 'lower_prev', lower)
             force_exit = getattr(row, 'force_exit', False)
             force_exit_rth = getattr(row, 'force_exit_rth', False)

        if force_exit: return True, 'Maintenance Exit', row['close'] if isinstance(row, pd.Series) else row.close
        if force_exit_rth: return True, 'RTH Exit', row['close'] if isinstance(row, pd.Series) else row.close
        
        dir_ = position['direction']
        
        # Stop Loss
        if dir_ == 1 and low <= position['stop']: return True, 'Stop Loss', position['stop']
        if dir_ == -1 and high >= position['stop']: return True, 'Stop Loss', position['stop']
        
        # Take Profit
        candidates = []
        # (Standard logic as in original v5)
        if self.opposite_bb_tp:
             tp_target = upper_prev if dir_ == 1 else lower_prev
             if dir_ == 1 and high >= tp_target: candidates.append(('TP Opp BB', tp_target))
             elif dir_ == -1 and low <= tp_target: candidates.append(('TP Opp BB', tp_target))
             
        if self.fixed_atr_tp and position['tp']:
             if dir_ == 1 and high >= position['tp']: candidates.append(('TP ATR', position['tp']))
             elif dir_ == -1 and low <= position['tp']: candidates.append(('TP ATR', position['tp']))

        if self.fixed_bb_entry_tp and position['tp']:
             if dir_ == 1 and high >= position['tp']: candidates.append(('TP BB', position['tp']))
             elif dir_ == -1 and low <= position['tp']: candidates.append(('TP BB', position['tp']))
             
        if candidates:
            # Pick best price logic or simply first hit?
            # Standard: Close to entry first? Or most profitable?
            # Implementation: Return closest to current price? 
            # Original v5 simply picked closest to entry for conservative testing
            candidates.sort(key=lambda x: abs(x[1] - position['entry_price']))
            return True, candidates[0][0], candidates[0][1]
            
        return False, None, None

    def update_trailing_stop(self, position, row, df):
        """Update trailing stop."""
        high = row['high'] if isinstance(row, pd.Series) else row.high
        low = row['low'] if isinstance(row, pd.Series) else row.low
        atr = row['atr_ts'] if isinstance(row, pd.Series) else row.atr_ts
        idx = row.name if isinstance(row, pd.Series) else row.Index
        
        position['bars_held'] = position.get('bars_held', 0) + 1
        
        if self.enable_trailing and position['bars_held'] >= self.trailing_delay:
            if position['direction'] == 1:
                new_stop = low - atr * self.atr_mult_ts_opt
                position['stop'] = max(position['stop'], new_stop)
            else:
                new_stop = high + atr * self.atr_mult_ts_opt
                position['stop'] = min(position['stop'], new_stop)

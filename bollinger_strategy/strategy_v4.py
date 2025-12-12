"""
Core Bollinger Band Strategy Implementation - Version 4.0
=========================================================
Vectorized signal generation, conservative exit logic, and dual-mode support.
"""

import pandas as pd
import numpy as np
from datetime import time
from .parameters import get_param_value
from .indicators import calculate_bollinger_bands, calculate_atr, calculate_ema, calculate_adx
from .filters import apply_rth_filter, apply_volume_filter, apply_atr_filter, apply_maintenance_filter


class BollingerBandStrategyV4:
    """
    Bollinger Band Trading Strategy v4
    
    Features:
    - Vectorized entry signal generation
    - Conservative intra-bar exit logic (Stop Loss > Take Profit)
    - Optimized state management
    """
    
    def __init__(self, params_dict):
        """
        Initialize strategy with parameters.
        
        Args:
            params_dict: Dictionary from load_params()
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
    
    def update_optimizable_params(self, params):
        """
        Update optimizable parameters (for GA optimization).
        """
        if 'Bollinger Band Length' in params:
            self.bb_length = max(1, int(params['Bollinger Band Length']))
        if 'Bollinger Band StdDev' in params:
            self.bb_stddev = float(params['Bollinger Band StdDev'])
        if 'Long Trigger (% From Lower Band)' in params:
            self.long_trigger_pct = float(params['Long Trigger (% From Lower Band)'])
        if 'Short Trigger (% From Upper Band)' in params:
            self.short_trigger_pct = float(params['Short Trigger (% From Upper Band)'])
        if 'Long Entry on Body in Zone' in params:
            self.long_body_zone = bool(int(round(params['Long Entry on Body in Zone'])))
        if 'Long Entry on Wick Touch' in params:
            self.long_wick_touch = bool(int(round(params['Long Entry on Wick Touch'])))
        if 'Short Entry on Body in Zone' in params:
            self.short_body_zone = bool(int(round(params['Short Entry on Body in Zone'])))
        if 'Short Entry on Wick Touch' in params:
            self.short_wick_touch = bool(int(round(params['Short Entry on Wick Touch'])))
        if 'ATR Multiplier for Trailing Stop' in params:
            self.atr_mult_ts_opt = float(params['ATR Multiplier for Trailing Stop'])
        if 'Volume MA Length' in params:
            self.volume_ma_length = max(1, int(params['Volume MA Length']))
        if 'Max Volume Multiplier' in params:
            self.max_volume_multiplier_opt = float(params['Max Volume Multiplier'])
        if 'Max ATR Filter (Points)' in params:
            self.max_atr_points_opt = float(params['Max ATR Filter (Points)'])
        if 'Min ATR Filter (Points)' in params:
            self.min_atr_points_opt = float(params['Min ATR Filter (Points)'])
        if 'Timeframe (minutes)' in params:
            self.timeframe = max(1, int(params['Timeframe (minutes)']))
        if 'Trailing Delay (bars)' in params:
            self.trailing_delay = max(0, int(params['Trailing Delay (bars)']))
        if 'ATR Length for Trailing Stop' in params:
            self.atr_length_ts = max(1, int(params['ATR Length for Trailing Stop']))
        if 'ATR Length for TP' in params:
            self.atr_length_tp = max(1, int(params['ATR Length for TP']))
        if 'ATR Length for Filter' in params:
            self.atr_length_filter = max(1, int(params['ATR Length for Filter']))
        if 'ATR Multiplier for TP' in params:
            self.atr_mult_tp = float(params['ATR Multiplier for TP'])
        if 'Initial Stop Loss (%)' in params:
            self.initial_sl_pct = float(params['Initial Stop Loss (%)'])
        if 'Fixed BB at Entry TP' in params:
            self.fixed_bb_entry_tp = bool(int(round(params['Fixed BB at Entry TP'])))
        if 'Fixed ATR TP' in params:
            self.fixed_atr_tp = bool(int(round(params['Fixed ATR TP'])))
        if 'Opposite Bollinger Band TP' in params:
            self.opposite_bb_tp = bool(int(round(params['Opposite Bollinger Band TP'])))
        if 'Enable Trailing Stop' in params:
            self.enable_trailing = bool(int(round(params['Enable Trailing Stop'])))
        if 'Enable RTH Filter' in params:
            self.enable_rth_filter = bool(int(round(params['Enable RTH Filter'])))
        if 'RTH Exit Buffer (minutes)' in params:
            self.rth_exit_buffer_minutes = int(params['RTH Exit Buffer (minutes)'])
        if 'Maintenance Buffer Minutes' in params:
            self.maintenance_buffer_minutes = int(params['Maintenance Buffer Minutes'])
        if 'Enable Trend Filter' in params:
            self.enable_trend_filter = bool(int(round(params['Enable Trend Filter'])))
        if 'Trend EMA Length' in params:
             self.trend_ema_length = max(10, int(params['Trend EMA Length']))
        if 'Enable ADX Filter' in params:
            self.enable_adx_filter = bool(int(round(params['Enable ADX Filter'])))
        if 'ADX Period' in params:
             self.adx_period = max(10, int(params['ADX Period']))
        if 'Max ADX Threshold' in params:
             self.max_adx_threshold_opt = float(params['Max ADX Threshold'])

    def calculate_indicators(self, df):
        """Calculate all indicators (BB, ATR)."""
        df = df.copy()
        
        # Resampling logic (preserving v3 logic for now)
        if len(df) >= 2:
            time_diff = (df.index[1] - df.index[0]).total_seconds()
            incoming_bar_seconds = int(time_diff)
            target_bar_seconds = self.timeframe * 60
            
            if incoming_bar_seconds < target_bar_seconds:
                df_resampled = df.resample(f'{self.timeframe}T', label='right', closed='right').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                })
                # Drop only empty rows
                df_resampled = df_resampled.dropna(subset=['open', 'high', 'low', 'close', 'volume'], how='all')
                df = df_resampled
        
        # Bollinger Bands
        df = calculate_bollinger_bands(df, self.bb_length, self.bb_stddev)
        
        # ATR for trailing stop
        df['atr_ts'] = calculate_atr(df, self.atr_length_ts)
        
        # ATR for filter
        df['atr_filter_values'] = calculate_atr(df, self.atr_length_filter)
        
        # ATR for TP
        # ATR for TP
        if self.fixed_atr_tp:
            df['atr_tp'] = calculate_atr(df, self.atr_length_tp)
            
        # Trend EMA
        df['trend_ema'] = calculate_ema(df, self.trend_ema_length)
        
        # ADX
        df['adx'] = calculate_adx(df, self.adx_period)
        
        return df

    def apply_filters(self, df):
        """Apply all filters (RTH, volume, ATR, maintenance)."""
        df = df.copy()
        
        # RTH filter
        df = apply_rth_filter(df, self.enable_rth_filter, self.rth_start, self.rth_end, self.rth_exit_buffer_minutes)
        
        # Maintenance period filter
        df = apply_maintenance_filter(
            df, self.enable_maintenance_filter,
            self.daily_maintenance_start_str, self.daily_maintenance_end_str,
            self.weekend_maintenance_start_day, self.weekend_maintenance_start_time_str,
            self.weekend_maintenance_end_day, self.weekend_maintenance_end_time_str,
            self.maintenance_buffer_minutes
        )
        
        # Volume filter
        df = apply_volume_filter(df, self.max_volume_multiplier_opt, volume_window=self.volume_ma_length)
        
        # ATR filter
        min_atr_to_use = getattr(self, 'min_atr_points_opt', self.min_atr_points)
        df = apply_atr_filter(df, self.max_atr_points_opt, min_atr_points=min_atr_to_use)
        
        # Drop rows with NaN
        df.dropna(inplace=True)
        
        return df

    def calculate_entry_signals(self, df):
        """
        Vectorized calculation of entry signals.
        Returns entries series.
        """
        # Ensure we work with arrays for speed
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        upper = df['upper'].values
        lower = df['lower'].values
        
        # Filters (boolean arrays)
        # Handle cases where column might be missing if filters disabled
        in_rth = df['in_rth'].values if 'in_rth' in df.columns else np.ones(len(df), dtype=bool)
        atr_filter = df['atr_filter'].values if 'atr_filter' in df.columns else np.ones(len(df), dtype=bool)
        vol_filter = df['volume_filter'].values if 'volume_filter' in df.columns else np.ones(len(df), dtype=bool)
        
        # Handle maintenance columns (might need safe access)
        in_main_col = 'in_maintenance'
        if in_main_col not in df.columns and 'in_maintenance_' in df.columns:
            in_main_col = 'in_maintenance_'
        in_maintenance = df[in_main_col].values if in_main_col in df.columns else np.zeros(len(df), dtype=bool)

        # Combined Entry Filter: Must be in RTH, pass ATR/Vol filters, not in maintenance
        # Combined Entry Filter: Must be in RTH, pass ATR/Vol filters, not in maintenance
        entry_allowed = in_rth & atr_filter & vol_filter & (~in_maintenance)
        
        # ADX Filter Logic
        if self.enable_adx_filter and 'adx' in df.columns:
             adx_vals = df['adx'].values
             # We want Ranging Market: ADX < Threshold
             adx_aligned = (adx_vals < self.max_adx_threshold_opt)
        else:
             adx_aligned = np.ones(len(df), dtype=bool)
        
        # Trend Filter Logic
        trend_long = np.ones(len(df), dtype=bool)
        trend_short = np.ones(len(df), dtype=bool)
        
        if self.enable_trend_filter and 'trend_ema' in df.columns:
            ema_vals = df['trend_ema'].values
            # Long: Close > EMA
            trend_long = (close > ema_vals)
            # Short: Close < EMA
            trend_short = (close < ema_vals)
            
        entry_long = np.zeros(len(df), dtype=bool)
        entry_short = np.zeros(len(df), dtype=bool)
        
        if self.enable_long:
            trig_long = lower * (1 - self.long_trigger_pct / 100.0)
            # Vectorized conditions
            cond_wick = (low <= trig_long) if self.long_wick_touch else np.zeros(len(df), dtype=bool)
            cond_body = (close <= trig_long) if self.long_body_zone else np.zeros(len(df), dtype=bool)
            entry_long = entry_allowed & adx_aligned & trend_long & (cond_wick | cond_body)

        if self.enable_short:
            trig_short = upper * (1 + self.short_trigger_pct / 100.0)
            # Vectorized conditions
            cond_wick = (high >= trig_short) if self.short_wick_touch else np.zeros(len(df), dtype=bool)
            cond_body = (close >= trig_short) if self.short_body_zone else np.zeros(len(df), dtype=bool)
            entry_short = entry_allowed & adx_aligned & trend_short & (cond_wick | cond_body)
            
        return entry_long, entry_short

    def check_entry(self, row, df):
        """
        Check entry for a single row (legacy/live support).
        """
        # Just reuse the logic, but for a single row it's often faster to just do scalar checks
        # as implemented in v3. Use v3 logic here for safety in live loop.
        
        in_maintenance = False
        if hasattr(row, 'Index'):
            idx = row.Index
            high = row.high
            low = row.low
            close = row.close
            upper = row.upper
            lower = row.lower
            in_rth = row.in_rth
            atr_filter = row.atr_filter
            vol_filter = row.volume_filter
            in_maintenance = getattr(row, 'in_maintenance', False)
            if not in_maintenance and hasattr(row, 'in_maintenance_'):
                in_maintenance = getattr(row, 'in_maintenance_', False)
        else:
            idx = row.name if hasattr(row, 'name') else df.index[-1]
            high = row['high']
            low = row['low']
            close = row['close']
            upper = row['upper']
            lower = row['lower']
            in_rth = row['in_rth']
            atr_filter = row['atr_filter']
            vol_filter = row['volume_filter']
            in_maintenance = row.get('in_maintenance', False) if hasattr(row, 'get') else (row['in_maintenance'] if 'in_maintenance' in row else False)

        if not (in_rth and atr_filter and vol_filter and not in_maintenance):
            return False, False

        enter_long = enter_short = False
        if self.enable_long:
            trig = lower * (1 - self.long_trigger_pct / 100)
            if (self.long_wick_touch and low <= trig) or (self.long_body_zone and close <= trig):
                enter_long = True
        
        if self.enable_short:
            trig = upper * (1 + self.short_trigger_pct / 100)
            if (self.short_wick_touch and high >= trig) or (self.short_body_zone and close >= trig):
                enter_short = True
                
        return enter_long, enter_short

    def setup_position(self, entry_price, direction, row, df):
        """Setup initial position details."""
        # Same as v3
        if hasattr(row, 'Index'):
            idx = row.Index
            high = row.high
            low = row.low
            upper = row.upper
            lower = row.lower
            atr_tp = getattr(row, 'atr_tp', None) if self.fixed_atr_tp else None
        else:
            idx = row.name if hasattr(row, 'name') else df.index[-1]
            high = row['high']
            low = row['low']
            upper = row['upper']
            lower = row['lower']
            atr_tp = row.get('atr_tp', None) if self.fixed_atr_tp else None
            
        # Initial Stop
        stop = entry_price * (1 - direction * self.initial_sl_pct / 100)
        
        # Take Profit
        tp = None
        if self.fixed_atr_tp and atr_tp is not None and not pd.isna(atr_tp):
            tp = entry_price + direction * atr_tp * self.atr_mult_tp
        elif self.fixed_bb_entry_tp:
            tp = upper if direction == 1 else lower
        elif self.opposite_bb_tp:
            tp = upper if direction == 1 else lower
            
        # Min stop distance
        min_stop_distance = entry_price * 0.001
        if direction == 1:
            stop = min(stop, entry_price - min_stop_distance)
        else:
            stop = max(stop, entry_price + min_stop_distance)
            
        position = {
            'entry_time': idx,
            'entry_price': entry_price,
            'direction': direction,
            'stop': stop,
            'tp': tp,
            'max_high': high if direction == 1 else None,
            'min_low': low if direction == -1 else None,
            'stop_history': [(idx, stop)],
            'bars_held': 0
        }
        return position

    def update_trailing_stop(self, position, row, df):
        """Update trailing stop if enabled."""
        if hasattr(row, 'Index'):
            idx = row.Index
            high = row.high
            low = row.low
            atr_ts = row.atr_ts
        else:
            idx = row.name if hasattr(row, 'name') else df.index[-1]
            high = row['high']
            low = row['low']
            atr_ts = row['atr_ts']
            
        if 'stop_history' not in position:
            position['stop_history'] = []
            
        position['bars_held'] = position.get('bars_held', 0) + 1
        
        stop_updated = False
        dir_ = position['direction']
        
        if self.enable_trailing and position['bars_held'] >= self.trailing_delay:
            if dir_ == 1:
                new_stop = low - atr_ts * self.atr_mult_ts_opt
                position['stop'] = max(position['stop'], new_stop)
            else:
                new_stop = high + atr_ts * self.atr_mult_ts_opt
                position['stop'] = min(position['stop'], new_stop)
            stop_updated = True
            
        position['stop_history'].append((idx, position['stop']))
        return stop_updated

    def check_exit(self, position, row, df):
        """
        Check exits with CONSERVATIVE logic.
        Stop Loss is checked BEFORE Take Profit if both are hit in the same bar.
        """
        if hasattr(row, 'Index'):
            high = row.high
            low = row.low
            close = row.close
            upper = row.upper
            lower = row.lower
            force_exit = getattr(row, 'force_exit', False)
            force_exit_rth = getattr(row, 'force_exit_rth', False)
        else:
            high = row['high']
            low = row['low']
            close = row['close']
            upper = row['upper']
            lower = row['lower']
            force_exit = row.get('force_exit', False)
            force_exit_rth = row.get('force_exit_rth', False)
            
        # Priority 0: Force Exits (Maintenance/RTH)
        if force_exit:
            return True, 'Maintenance Exit', close
        if force_exit_rth:
            return True, 'RTH Exit', close
            
        dir_ = position['direction']
        
        # Priority 1: Stop Loss
        # We check this FIRST and return immediately if hit.
        # This is the "Conservative" change from v3.
        stop_hit = False
        if dir_ == 1 and low <= position['stop']:
            stop_hit = True
        elif dir_ == -1 and high >= position['stop']:
            stop_hit = True
            
        if stop_hit:
            return True, 'Stop', position['stop']
            
        # Priority 2: Take Profits
        candidates = []
        
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
        
        if candidates:
            # If multiple TPs hit (unlikely but possible), take closest or best?
            # v3 took closest. Let's stick to closest to be consistent with "hitting the first one"
            candidates.sort(key=lambda x: abs(x[1] - position['entry_price']))
            reason, price = candidates[0]
            return True, reason, price
            
        return False, None, None

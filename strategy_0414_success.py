"""
Trend Following Strategy (Dual Thrust / Donchian)
================================================
Inherits from the base Strategy class.
"""

import pandas as pd
import numpy as np
import math
from datetime import time
from strategies.base import Strategy
from .parameters import get_param_value
from strategies.bollinger.filters import apply_rth_filter, apply_maintenance_filter

class TrendStrategy(Strategy):
    """
    Trend Following Strategy using Donchian Channels / Dual Thrust logic.
    """
    
    def __init__(self, params_dict):
        self.params_dict = params_dict
        self._extract_params()
        
    def _extract_params(self):
        """Extract and validate all parameters."""
        # Fixed / Config
        self.max_open_trades = int(get_param_value(self.params_dict, 'Max Open Trades', 1))
        self.enable_long = get_param_value(self.params_dict, 'Enable Long Trades', True)
        self.enable_short = get_param_value(self.params_dict, 'Enable Short Trades', True)
        self.initial_sl_pct = float(get_param_value(self.params_dict, 'Initial Stop Loss (%)', 1.0))
        self.timeframe = int(get_param_value(self.params_dict, 'Timeframe (minutes)', 15))
        
        # Trailing Stop
        trailing_val = get_param_value(self.params_dict, 'Enable Trailing Stop', True)
        if isinstance(trailing_val, (int, float)): self.enable_trailing = bool(int(trailing_val))
        else: self.enable_trailing = trailing_val
        self.atr_length_ts = int(get_param_value(self.params_dict, 'ATR Length for Trailing Stop', 14))
        self.atr_mult_ts = float(get_param_value(self.params_dict, 'ATR Multiplier for Trailing Stop', 3.0))
        self.trailing_delay = int(get_param_value(self.params_dict, 'Trailing Delay (bars)', 5))
        
        # Take Profit
        self.tp_mult_atr = float(get_param_value(self.params_dict, 'Take Profit ATR Multiplier', 0.0)) # 0 = disabled
        
        # Entry Logic (Donchian / Dual Thrust)
        self.lookback_buy = int(get_param_value(self.params_dict, 'Buy Lookback', 20))
        self.lookback_sell = int(get_param_value(self.params_dict, 'Sell Lookback', 20))
        
        # Filter Logic
        adx_filter_val = get_param_value(self.params_dict, 'Enable ADX Filter', False)
        if isinstance(adx_filter_val, (int, float)): self.enable_adx_filter = bool(int(adx_filter_val))
        else: self.enable_adx_filter = adx_filter_val
        self.adx_period = int(get_param_value(self.params_dict, 'ADX Period', 14))
        self.min_adx = float(get_param_value(self.params_dict, 'Min ADX Threshold', 20.0))
        
        self.atr_filter_period = int(get_param_value(self.params_dict, 'ATR Filter Period', 14))

        self.min_atr_points = float(get_param_value(self.params_dict, 'Min ATR (Points)', 0.5))

        # RSI Filter
        rsi_filter_val = get_param_value(self.params_dict, 'Enable RSI Filter', False)
        if isinstance(rsi_filter_val, (int, float)): self.enable_rsi_filter = bool(int(rsi_filter_val))
        else: self.enable_rsi_filter = rsi_filter_val
        self.rsi_period = int(get_param_value(self.params_dict, 'RSI Period', 14))
        self.rsi_max_buy = float(get_param_value(self.params_dict, 'RSI Max Buy Threshold', 70.0))
        self.rsi_min_sell = float(get_param_value(self.params_dict, 'RSI Min Sell Threshold', 30.0))

        # VWAP Filter
        vwap_filter_val = get_param_value(self.params_dict, 'Enable VWAP Filter', False)
        if isinstance(vwap_filter_val, (int, float)): self.enable_vwap_filter = bool(int(vwap_filter_val))
        else: self.enable_vwap_filter = vwap_filter_val

        # Regime Filter (SMA)
        self.enable_sma_filter = get_param_value(self.params_dict, 'Enable SMA Filter', False)
        self.sma_period = int(get_param_value(self.params_dict, 'SMA Period', 200))

        # Volume Filter
        self.enable_vol_filter = get_param_value(self.params_dict, 'Enable Volume Filter', False)
        self.vol_ma_length = int(get_param_value(self.params_dict, 'Volume MA Length', 20))
        self.min_vol_mult = float(get_param_value(self.params_dict, 'Min Volume Multiplier', 1.5))

        # Time Filters (RTH & Maintenance)
        rth_filter_val = get_param_value(self.params_dict, 'Enable RTH Filter', True)
        if isinstance(rth_filter_val, (int, float)): self.enable_rth_filter = bool(int(rth_filter_val))
        elif isinstance(rth_filter_val, bool): self.enable_rth_filter = rth_filter_val
        else: self.enable_rth_filter = bool(int(float(str(rth_filter_val))))
        
        self.rth_start_str = get_param_value(self.params_dict, 'RTH Start (HH:MM)', '09:30')
        self.rth_end_str = get_param_value(self.params_dict, 'RTH End (HH:MM)', '16:00')
        self.rth_exit_buffer_minutes = int(get_param_value(self.params_dict, 'RTH Exit Buffer (minutes)', 0))
        
        self.enable_maintenance_filter = get_param_value(self.params_dict, 'Enable Maintenance Filter', False)
        self.daily_maintenance_start_str = get_param_value(self.params_dict, 'Daily Maintenance Start (HH:MM)', '16:00')
        self.daily_maintenance_end_str = get_param_value(self.params_dict, 'Daily Maintenance End (HH:MM)', '16:30')
        self.weekend_maintenance_start_day = int(get_param_value(self.params_dict, 'Weekend Maintenance Start Day', 4))
        self.weekend_maintenance_start_time_str = get_param_value(self.params_dict, 'Weekend Maintenance Start Time (HH:MM)', '16:00')
        self.weekend_maintenance_end_day = int(get_param_value(self.params_dict, 'Weekend Maintenance End Day', 6))
        self.weekend_maintenance_end_time_str = get_param_value(self.params_dict, 'Weekend Maintenance End Time (HH:MM)', '17:00')
        self.maintenance_buffer_minutes = int(get_param_value(self.params_dict, 'Maintenance Buffer Minutes', 5))

        self.rth_start = self._parse_time(self.rth_start_str)
        self.rth_end = self._parse_time(self.rth_end_str)
        
    def _parse_time(self, time_str):
        try:
            return pd.to_datetime(time_str, format='%H:%M').time()
        except:
            return time(9, 30)
        
    @property
    def min_bars_required(self) -> int:
        """Calculate minimum bars required for all indicators to warm up."""
        lookbacks = [
            self.lookback_buy,
            self.lookback_sell,
            self.atr_length_ts,
            self.adx_period if self.enable_adx_filter else 0,
            self.atr_filter_period,
            self.sma_period if self.enable_sma_filter else 0,
            self.vol_ma_length if getattr(self, 'enable_vol_filter', False) else 0,
            self.rsi_period if getattr(self, 'enable_rsi_filter', False) else 0
        ]
        return max(lookbacks) + 10

    def get_param_structure(self) -> dict:
        return {
            'Entry Criteria': {
                'Enable Long': self.enable_long,
                'Enable Short': self.enable_short,
                'Buy Lookback': self.lookback_buy,
                'Sell Lookback': self.lookback_sell,
                'Enable ADX Filter': self.enable_adx_filter,
                'Min ADX': self.min_adx,
                'Min ATR': self.min_atr_points,
                'Enable RSI': getattr(self, 'enable_rsi_filter', False),
                'Enable VWAP': getattr(self, 'enable_vwap_filter', False),
                'Enable RTH': self.enable_rth_filter,
                'RTH Start': self.rth_start_str,
                'RTH End': self.rth_end_str
            },
            'Exit Criteria': {
                'Initial SL (%)': self.initial_sl_pct,
                'Trailing Stop': self.enable_trailing,
                'Trail ATR Mult': self.atr_mult_ts,
                'TP ATR Mult': self.tp_mult_atr
            }
        }
        
    def update_optimizable_params(self, params):
        """Update params from GA individual."""
        if 'Buy Lookback' in params: self.lookback_buy = int(params['Buy Lookback'])
        if 'Sell Lookback' in params: self.lookback_sell = int(params['Sell Lookback'])
        if 'ATR Multiplier for Trailing Stop' in params: self.atr_mult_ts = float(params['ATR Multiplier for Trailing Stop'])
        if 'Initial Stop Loss (%)' in params: self.initial_sl_pct = float(params['Initial Stop Loss (%)'])
        if 'Min ADX Threshold' in params: self.min_adx = float(params['Min ADX Threshold'])
        if 'ADX Period' in params: self.adx_period = int(params['ADX Period'])
        # Min ATR (Points)
        if 'Min ATR (Points)' in params: self.min_atr_points = float(params['Min ATR (Points)'])
        # ATR Filter Period
        if 'ATR Filter Period' in params: self.atr_filter_period = int(params['ATR Filter Period'])
        # Trailing Delay
        if 'Trailing Delay (bars)' in params: self.trailing_delay = int(params['Trailing Delay (bars)'])
        # Take Profit
        if 'Take Profit ATR Multiplier' in params: self.tp_mult_atr = float(params['Take Profit ATR Multiplier'])
        # ATR Length for TS
        if 'ATR Length for Trailing Stop' in params: self.atr_length_ts = int(params['ATR Length for Trailing Stop'])
        
        # Boolean Filters (Optimized as 0/1 int)
        if 'Enable ADX Filter' in params: self.enable_adx_filter = bool(int(params['Enable ADX Filter']))
        if 'Enable Trailing Stop' in params: self.enable_trailing = bool(int(params['Enable Trailing Stop']))
        
        # New Filters
        if 'SMA Period' in params: self.sma_period = int(params['SMA Period'])
        if 'Volume MA Length' in params: self.vol_ma_length = int(params['Volume MA Length'])
        if 'Min Volume Multiplier' in params: self.min_vol_mult = float(params['Min Volume Multiplier'])
        
        # Boolean Filters (Optimized as 0/1 int)
        if 'Enable SMA Filter' in params: self.enable_sma_filter = bool(int(params['Enable SMA Filter']))
        if 'Enable Volume Filter' in params: self.enable_vol_filter = bool(int(params['Enable Volume Filter']))
        if 'Enable RSI Filter' in params: self.enable_rsi_filter = bool(int(params['Enable RSI Filter']))
        if 'Enable VWAP Filter' in params: self.enable_vwap_filter = bool(int(params['Enable VWAP Filter']))

        # Filter Parameters
        if 'RSI Period' in params: self.rsi_period = int(params['RSI Period'])
        if 'RSI Max Buy Threshold' in params: self.rsi_max_buy = float(params['RSI Max Buy Threshold'])
        if 'RSI Min Sell Threshold' in params: self.rsi_min_sell = float(params['RSI Min Sell Threshold'])

    def calculate_indicators(self, df):
        """Calculate Donchian Channels, ATR, ADX."""
        df = df.copy()
        
        # 1. Donchian Channels (High of last N, Low of last N)
        # Shift NOT needed for backtest usually if we use "Close > High[1:]", but typically logic is:
        # Breakout of the High of the PREVIOUS N bars.
        # So we calculate rolling max of N, then SHIFT by 1 to represent "Yesterday's" high.
        
        df['donchian_high'] = df['high'].rolling(self.lookback_buy).max().shift(1)
        df['donchian_low'] = df['low'].rolling(self.lookback_sell).min().shift(1)
        
        # 2. ATR (for stops and filters)
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        
        df['atr'] = tr.rolling(self.atr_length_ts).mean()
        df['atr_filter'] = tr.rolling(self.atr_filter_period).mean()
        
        # 3. ADX (Wilder's implementation approximation)
        if self.enable_adx_filter:
            up = df['high'] - df['high'].shift(1)
            down = df['low'].shift(1) - df['low']
            pos_dm = np.where((up > down) & (up > 0), up, 0.0)
            neg_dm = np.where((down > up) & (down > 0), down, 0.0)
            
            tr_s = tr.rolling(self.adx_period).sum()
            pos_dm_s = pd.Series(pos_dm, index=df.index).rolling(self.adx_period).sum()
            neg_dm_s = pd.Series(neg_dm, index=df.index).rolling(self.adx_period).sum()
            
            # Avoid div by zero
            pos_di = 100 * (pos_dm_s / tr_s.replace(0, 1))
            neg_di = 100 * (neg_dm_s / tr_s.replace(0, 1))
            dx = 100 * np.abs(pos_di - neg_di) / (pos_di + neg_di).replace(0, 1)
            df['adx'] = dx.rolling(self.adx_period).mean()
            
        # 4. Regime Filter (SMA)
        if self.enable_sma_filter:
            df['sma_regime'] = df['close'].rolling(self.sma_period).mean()
            
        # 5. Volume Filter
        if getattr(self, 'enable_vol_filter', False):
            df['vol_ma'] = df['volume'].rolling(self.vol_ma_length).mean()
        
        # 6. RSI Filter
        if getattr(self, 'enable_rsi_filter', False):
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
            rs = gain / loss.replace(0, 1e-9)
            df['rsi'] = 100 - (100 / (1 + rs))

        # 7. VWAP Filter
        if getattr(self, 'enable_vwap_filter', False):
            # Typical Price * Volume
            tp = (df['high'] + df['low'] + df['close']) / 3
            pv = tp * df['volume']
            # Rolling window for intra-day VWAP or full history?
            # Standard VWAP is cumulative since session start.
            # For backtest simplicity and consistency with Bollinger, we can use a rolling version 
            # or cumulative if we have session logic.
            # Let's use cumulative since session start (9:30 ET) if possible, 
            # or a very long rolling window if not.
            # Bollinger used cumulative sum for the day.
            
            # Group by date to reset VWAP each day
            df['date'] = df.index.date
            df['cum_pv'] = df.groupby('date')['volume'].transform(lambda x: (tp.loc[x.index] * x).cumsum())
            df['cum_vol'] = df.groupby('date')['volume'].transform(lambda x: x.cumsum())
            df['vwap'] = df['cum_pv'] / df['cum_vol'].replace(0, 1)
            df.drop(columns=['date', 'cum_pv', 'cum_vol'], inplace=True)
            
        df.dropna(inplace=True)
        return df

    def apply_filters(self, df):
        """
        Apply time filters to dataframe.
        """
        df = apply_rth_filter(df, self.enable_rth_filter, self.rth_start, self.rth_end, self.rth_exit_buffer_minutes)
        df = apply_maintenance_filter(
            df, self.enable_maintenance_filter,
            self.daily_maintenance_start_str, self.daily_maintenance_end_str,
            self.weekend_maintenance_start_day, self.weekend_maintenance_start_time_str,
            self.weekend_maintenance_end_day, self.weekend_maintenance_end_time_str,
            self.maintenance_buffer_minutes
        )
        return df

    def calculate_entry_signals(self, df, verbose=False):
        """
        Long if High > Donchian High.
        Short if Low < Donchian Low.
        """
        # --- 1. Core Breakout Signals (Candidates) ---
        # Trigger on the BAR that first breaks the level
        long_breakout = (df['high'] > df['donchian_high']) & (df['high'].shift(1) <= df['donchian_high'].shift(1))
        short_breakout = (df['low'] < df['donchian_low']) & (df['low'].shift(1) >= df['donchian_low'].shift(1))
        
        # --- 2. Individual Filter Masks ---
        masks = {}
        
        # ADX Filter
        masks['ADX'] = (df['adx'] > self.min_adx).values if self.enable_adx_filter else np.ones(len(df), dtype=bool)
        
        # ATR Filter
        masks['ATR'] = (df['atr_filter'] > self.min_atr_points).values
        
        # SMA Filter (Regime)
        if self.enable_sma_filter:
            masks['SMA_Long'] = (df['close'] > df['sma_regime']).values
            masks['SMA_Short'] = (df['close'] < df['sma_regime']).values
        else:
            masks['SMA_Long'] = masks['SMA_Short'] = np.ones(len(df), dtype=bool)
            
        # Volume Filter
        if getattr(self, 'enable_vol_filter', False):
            masks['VOL'] = (df['volume'] > (df['vol_ma'] * self.min_vol_mult)).values
        else:
            masks['VOL'] = np.ones(len(df), dtype=bool)

        # RSI Filter
        if getattr(self, 'enable_rsi_filter', False):
            masks['RSI_Long'] = (df['rsi'] < self.rsi_max_buy).values
            masks['RSI_Short'] = (df['rsi'] > self.rsi_min_sell).values
        else:
            masks['RSI_Long'] = masks['RSI_Short'] = np.ones(len(df), dtype=bool)

        # VWAP Filter
        if getattr(self, 'enable_vwap_filter', False):
            masks['VWAP_Long'] = (df['close'] > df['vwap']).values
            masks['VWAP_Short'] = (df['close'] < df['vwap']).values
        else:
            masks['VWAP_Long'] = masks['VWAP_Short'] = np.ones(len(df), dtype=bool)
        
        # Time Filters
        masks['RTH'] = df['in_rth'].values if 'in_rth' in df.columns else np.ones(len(df), dtype=bool)
        masks['MAINT'] = (~df['in_maintenance'].values) if 'in_maintenance' in df.columns else np.ones(len(df), dtype=bool)
        
        # Side Enables
        masks['ENABLE_L'] = np.full(len(df), self.enable_long)
        masks['ENABLE_S'] = np.full(len(df), self.enable_short)

        # --- 3. Final Signal Calculation ---
        long_sig = (long_breakout & 
                    masks['ADX'] & masks['ATR'] & masks['SMA_Long'] & 
                    masks['VOL'] & masks['RSI_Long'] & masks['VWAP_Long'] & 
                    masks['RTH'] & masks['MAINT'] & masks['ENABLE_L'])
        
        short_sig = (short_breakout & 
                     masks['ADX'] & masks['ATR'] & masks['SMA_Short'] & 
                     masks['VOL'] & masks['RSI_Short'] & masks['VWAP_Short'] & 
                     masks['RTH'] & masks['MAINT'] & masks['ENABLE_S'])
        
        # --- 4. Action Log (Diagnostics) ---
        if verbose:
            try:
                action_log = []
                # Check rejections for LONG candidates
                long_cands_idx = np.where(long_breakout)[0]
                for loc in long_cands_idx:
                    row = df.iloc[loc]
                    idx = row.name
                    reasons = []
                    if not masks['ENABLE_L'][loc]: reasons.append("Long Disabled")
                    if not masks['RTH'][loc]: reasons.append("RTH Filter")
                    if not masks['MAINT'][loc]: reasons.append("Maintenance Filter")
                    if not masks['ADX'][loc]: 
                        if 'adx' in row: reasons.append(f"ADX ({row['adx']:.1f} < {self.min_adx})")
                    if not masks['ATR'][loc]: 
                        if 'atr_filter' in row: reasons.append(f"ATR ({row['atr_filter']:.2f} < {self.min_atr_points})")
                    if not masks['SMA_Long'][loc]: reasons.append("SMA Filter")
                    if not masks['VOL'][loc]: reasons.append("Volume Filter")
                    if not masks['RSI_Long'][loc]: 
                        if 'rsi' in row: reasons.append(f"RSI ({row['rsi']:.1f} > {self.rsi_max_buy})")
                    if not masks['VWAP_Long'][loc]: reasons.append("VWAP Filter")
                    
                    if reasons:
                        action_log.append({
                            'timestamp': idx,
                            'direction': 'LONG',
                            'type': 'Breakout Rejected',
                            'reasons': reasons
                        })
                    else:
                        action_log.append({
                            'timestamp': idx,
                            'direction': 'LONG',
                            'type': 'Signal Triggered',
                            'reasons': []
                        })

                # Check rejections for SHORT candidates
                short_cands_idx = np.where(short_breakout)[0]
                for loc in short_cands_idx:
                    row = df.iloc[loc]
                    idx = row.name
                    reasons = []
                    if not masks['ENABLE_S'][loc]: reasons.append("Short Disabled")
                    if not masks['RTH'][loc]: reasons.append("RTH Filter")
                    if not masks['MAINT'][loc]: reasons.append("Maintenance Filter")
                    if not masks['ADX'][loc]: 
                        if 'adx' in row: reasons.append(f"ADX ({row['adx']:.1f} < {self.min_adx})")
                    if not masks['ATR'][loc]: 
                        if 'atr_filter' in row: reasons.append(f"ATR ({row['atr_filter']:.2f} < {self.min_atr_points})")
                    if not masks['SMA_Short'][loc]: reasons.append("SMA Filter")
                    if not masks['VOL'][loc]: reasons.append("Volume Filter")
                    if not masks['RSI_Short'][loc]: 
                        if 'rsi' in row: reasons.append(f"RSI ({row['rsi']:.1f} < {self.rsi_min_sell})")
                    if not masks['VWAP_Short'][loc]: reasons.append("VWAP Filter")
                    
                    if reasons:
                        action_log.append({
                            'timestamp': idx,
                            'direction': 'SHORT',
                            'type': 'Breakout Rejected',
                            'reasons': reasons
                        })
                    else:
                        action_log.append({
                            'timestamp': idx,
                            'direction': 'SHORT',
                            'type': 'Signal Triggered',
                            'reasons': []
                        })

                return long_sig, short_sig, action_log
            except Exception as e:
                import logging
                logging.error(f"Action Log generation failed: {e}")
                raise e
            
        return long_sig, short_sig

    def setup_position(self, entry_price, direction, row, df=None):
        """Create position with initial stop logic."""
        
        # For trend strategy, entry price is often the breakout level (stop order)
        # In this simplified backtest, we often use 'close' or 'breakout level'
        # To be robust, if High > Donchian, we theoretically entered at Donchian Level + Tick
        # But for now, using the passed entry_price which comes from Backtester (customizable)
        
        stop_price = 0.0
        if self.initial_sl_pct > 0:
            if direction == 1:
                stop_price = entry_price * (1 - self.initial_sl_pct / 100.0)
            else:
                stop_price = entry_price * (1 + self.initial_sl_pct / 100.0)
        
        tp_price = None
        if self.tp_mult_atr > 0:
            atr = row.atr if hasattr(row, 'atr') else row['atr']
            if not pd.isna(atr) and atr > 0:
                if direction == 1:
                    tp_price = entry_price + (atr * self.tp_mult_atr)
                else:
                    tp_price = entry_price - (atr * self.tp_mult_atr)

        return {
            'entry_time': row.Index if not isinstance(row, pd.Series) else row.name,
            'entry_price': entry_price,
            'direction': direction,
            'stop': stop_price,
            'tp': tp_price,
            'bars_held': 0,
            'highest_high': entry_price if direction == 1 else -1,
            'lowest_low': entry_price if direction == -1 else 999999
        }

    def check_exit(self, position, row, df):
        """
        Check stops (Initial, Trailing) and TP.
        Also check for 'Reverse' signal (Donchian lower band for Longs).
        """
        idx = row.Index if not isinstance(row, pd.Series) else row.name
        high = row.high if not isinstance(row, pd.Series) else row['high']
        low = row.low if not isinstance(row, pd.Series) else row['low']
        close = row.close if not isinstance(row, pd.Series) else row['close']
        donchian_low = row.donchian_low if hasattr(row, 'donchian_low') else row['donchian_low']
        donchian_high = row.donchian_high if hasattr(row, 'donchian_high') else row['donchian_high']
        
        dir_ = position['direction']
        
        stop_price = position.get('stop', 0)
        tp_price = position.get('tp')
        
        # 1. Stop Loss
        if dir_ == 1 and low <= stop_price: return True, 'Stop Loss', stop_price
        if dir_ == -1 and high >= stop_price: return True, 'Stop Loss', stop_price
        
        # 2. Take Profit
        if tp_price is not None and tp_price > 0:
            if dir_ == 1 and high >= tp_price: return True, 'Take Profit', tp_price
            if dir_ == -1 and low <= tp_price: return True, 'Take Profit', tp_price
            
        # 3. Channel Exit (Reversal)
        # If Long, and Price drops below Donchian Low (Support broken) -> Exit
        if dir_ == 1 and low < donchian_low:
             return True, 'Channel Exit', donchian_low
        if dir_ == -1 and high > donchian_high:
             return True, 'Channel Exit', donchian_high
             
        return False, None, None

    def update_trailing_stop(self, position, row, df):
        """Update trailing stop based on ATR."""
        if not self.enable_trailing: return
        
        high = row.high if not isinstance(row, pd.Series) else row['high']
        low = row.low if not isinstance(row, pd.Series) else row['low']
        atr = row.atr if not isinstance(row, pd.Series) else row['atr']
        
        position['bars_held'] += 1
        if position['bars_held'] < self.trailing_delay: return
        
        if position['direction'] == 1:
            # Ratchet logic
            new_stop = high - (atr * self.atr_mult_ts) # Standard Chandelier Exit uses High
            # Or use close? High is safer for profit locking.
            if new_stop > position['stop']:
                position['stop'] = new_stop
        else:
             new_stop = low + (atr * self.atr_mult_ts)
             if new_stop < position['stop']:
                 position['stop'] = new_stop

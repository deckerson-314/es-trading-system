
import pytest
import pandas as pd
import numpy as np
import itertools
from datetime import datetime
from tests.helpers.synthetic_data import make_strategy, make_breakout_scenario, make_gap_scenario, make_flash_crash_scenario

class TestCombinatorialFilters:
    """
    Pillar A Phase 2: Combinatorial Grid Testing.
    Verifies every combination of the 6 entry filters (2^6 = 64 combinations).
    """
    
    # List of filter toggle names and their related setting names
    # Note: ATR has no toggle, it is always on. We toggle it by setting 'Min ATR (Points)' to 0 vs 99.
    FILTERS = [
        ('Enable ADX Filter', 1, 0, 'Min ADX Threshold', 20.0, 999.0),
        ('Min ATR (Points)', 0.0, 999.0, None, None, None), 
        ('Enable RSI Filter', 1, 0, 'RSI Max Buy Threshold', 70.0, 0.0), # 0.0 is impossible RSI for Long
        ('Enable SMA Filter', True, False, 'SMA Position', 'above', 'below'), # custom logic in loop
        ('Enable Volume Filter', True, False, 'Min Volume Multiplier', 1.0, 999.0),
        ('Enable VWAP Filter', 1, 0, 'VWAP Position', 'above', 'below') # custom logic in loop
    ]

    @pytest.mark.parametrize("comb", list(itertools.product([True, False], repeat=6)))
    def test_filter_grid_64_combinations(self, comb):
        """
        Test all 64 combinations of filters.
        A signal should ONLY fire if ALL enabled filters are passing.
        """
        # 1. Setup Data for a PASSING breakout
        # We need indicator values that generally 'pass' common thresholds
        # ADX=30, RSI=50, Price > SMA, Price > VWAP, Vol=5000 (MA=1000)
        df, breakout_idx = make_breakout_scenario(
            lookback=5, warmup_extra=40, breakout_magnitude=10.0, base_price=100.0, volume=5000
        )
        
        # Inject indicator context into the breakout bar to ensure PASSING values
        row = df.iloc[breakout_idx]
        price = row['close']
        
        # Manually force indicator values in the DF for the breakout bar
        # (This is more reliable than relying on the random sine wave for high-precision thresholds)
        df.loc[df.index[breakout_idx], 'adx'] = 30.0
        df.loc[df.index[breakout_idx], 'rsi'] = 50.0
        df.loc[df.index[breakout_idx], 'atr_filter'] = 5.0
        df.loc[df.index[breakout_idx], 'sma_regime'] = price - 10.0 # Price > SMA
        df.loc[df.index[breakout_idx], 'vwap'] = price - 5.0 # Price > VWAP
        df.loc[df.index[breakout_idx], 'vol_ma'] = 1000.0 # Vol (5k) > VolMA(1k) * 1.5
        
        # 2. Setup Parameters based on the combination
        # If comb[i] is True, we want that filter to be ENABLED and BLOCKED.
        # If comb[i] is False, we want that filter to be DISABLED (Pass-through).
        
        params = {}
        should_pass = True
        
        # ADX (comb[0])
        if comb[0]: # Enable and BLOCK
            params['Enable ADX Filter'] = 1
            params['Min ADX Threshold'] = 99.0
            should_pass = False
        else: # Disable
            params['Enable ADX Filter'] = 0
            
        # ATR (comb[1]) - Always on, so we block by setting threshold high
        if comb[1]: # BLOCK
            params['Min ATR (Points)'] = 99.0
            should_pass = False
        else: # PASS
            params['Min ATR (Points)'] = 0.0
            
        # RSI (comb[2])
        if comb[2]: # Enable and BLOCK
            params['Enable RSI Filter'] = 1
            params['RSI Max Buy Threshold'] = 10.0 # RSI(50) > 10
            should_pass = False
        else:
            params['Enable RSI Filter'] = 0
            
        # SMA (comb[3])
        if comb[3]: # Enable and BLOCK
            params['Enable SMA Filter'] = True
            df.loc[df.index[breakout_idx], 'sma_regime'] = price + 10.0 # Price < SMA (Blocked for Long)
            should_pass = False
        else:
            params['Enable SMA Filter'] = False
            
        # Volume (comb[4])
        if comb[4]: # Enable and BLOCK
            params['Enable Volume Filter'] = True
            params['Min Volume Multiplier'] = 10.0 # Vol(5k) < VolMA(1k) * 10
            should_pass = False
        else:
            params['Enable Volume Filter'] = False
            
        # VWAP (comb[5])
        if comb[5]: # Enable and BLOCK
            params['Enable VWAP Filter'] = 1
            should_pass = False
        else:
            params['Enable VWAP Filter'] = 0
            
        # 1. Setup Data for a PASSING breakout
        df, breakout_idx = make_breakout_scenario(
            lookback=5, warmup_extra=40, breakout_magnitude=10.0, base_price=100.0, volume=5000
        )
        
        # Save the timestamp of the breakout bar
        breakout_ts = df.index[breakout_idx]
        
        # 3. Execution
        strategy = make_strategy(**params)
        
        # Calculate base indicators (Donchian, ATR, etc.)
        df = strategy.calculate_indicators(df)
        df = strategy.apply_filters(df)
        
        # MANUALLY OVERRIDE specific indicators for the breakout bar to control the test
        # We use the timestamp since dropna() might have shifted positional indices
        price = df.loc[breakout_ts, 'close']
        df.loc[breakout_ts, 'adx'] = 30.0
        df.loc[breakout_ts, 'rsi'] = 50.0
        df.loc[breakout_ts, 'atr_filter'] = 5.0
        df.loc[breakout_ts, 'sma_regime'] = price - 10.0 # Price > SMA
        df.loc[breakout_ts, 'vwap'] = price - 5.0 # Price > VWAP
        df.loc[breakout_ts, 'volume'] = 5000.0
        df.loc[breakout_ts, 'vol_ma'] = 1000.0 # Vol(5k) > VolMA(1k) * 1.5 (default multiplier)

        # APPLY KILLER OVERRIDES if comb[i] is True
        if comb[3]: # SMA Block
            df.loc[breakout_ts, 'sma_regime'] = price + 10.0
        if comb[5]: # VWAP Block
            df.loc[breakout_ts, 'vwap'] = price + 5.0

        res = strategy.calculate_entry_signals(df, verbose=True)
        long_sig, short_sig, action_log = res if len(res) == 3 else (res[0], res[1], [])
        
        # 4. Verification
        try:
            actual_signal = bool(long_sig.loc[breakout_ts])
        except KeyError:
            # Handle if breakout_ts was dropped for some reason (shouldn't happen with 40 warmup)
            pytest.fail(f"Breakout timestamp {breakout_ts} dropped from DataFrame. Runway insufficient.")

        if actual_signal != should_pass:
            # Diagnostic for failure
            res = strategy.calculate_entry_signals(df, verbose=True)
            long_sig, short_sig, action_log = res if len(res) == 3 else (res[0], res[1], [])
            rejection = next((a for a in action_log if a['timestamp'] == breakout_ts), None)
            reasons = rejection['reasons'] if rejection else "No rejection logged (Triggered?)"
            
            # Recalculate masks for the fail message
            m = {}
            m['LB'] = bool((df['high'] > df['donchian_high']).loc[breakout_ts])
            m['WS'] = bool((df['high'].shift(1) <= df['donchian_high'].shift(1)).loc[breakout_ts])
            m['ADX'] = bool((df['adx'] > strategy.min_adx).loc[breakout_ts]) if strategy.enable_adx_filter else True
            m['ATR'] = bool((df['atr_filter'] > strategy.min_atr_points).loc[breakout_ts])
            m['SMA'] = bool((df['close'] > df['sma_regime']).loc[breakout_ts]) if strategy.enable_sma_filter else True
            m['VOL'] = bool((df['volume'] > (df['vol_ma'] * strategy.min_vol_mult)).loc[breakout_ts]) if getattr(strategy, 'enable_vol_filter', False) else True
            m['RSI'] = bool((df['rsi'] < strategy.rsi_max_buy).loc[breakout_ts]) if getattr(strategy, 'enable_rsi_filter', False) else True
            m['VWAP'] = bool((df['close'] > df['vwap']).loc[breakout_ts]) if getattr(strategy, 'enable_vwap_filter', False) else True
            m['RTH'] = bool(df.loc[breakout_ts, 'in_rth']) if 'in_rth' in df.columns else True
            m['MAI'] = bool(~df.loc[breakout_ts, 'in_maintenance']) if 'in_maintenance' in df.columns else True
            m['ENL'] = bool(strategy.enable_long)

            msg = (f"Comb {comb} FAILED. Expected {should_pass}, Actual {actual_signal}.\n"
                   f"Masks: {m}\n"
                   f"Reasons: {reasons}")
            pytest.fail(msg)
            
        assert actual_signal == should_pass, f"Comb {comb} failed. Expected {should_pass}, got {actual_signal}"

class TestMarketAnomalies:
    """
    Stress tests for extreme market behavior.
    """
    
    def test_price_gap_breakout(self):
        """Verify that a massive gap still triggers a signal."""
        df, breakout_idx = make_gap_scenario(gap_magnitude=50.0)
        breakout_ts = df.index[breakout_idx]
        strategy = make_strategy() # All filters off
        df = strategy.calculate_indicators(df)
        df = strategy.apply_filters(df)
        res = strategy.calculate_entry_signals(df, verbose=True)
        long_sig, _, action_log = res if len(res) == 3 else (res[0], res[1], [])
        
        if not bool(long_sig.loc[breakout_ts]):
            rejection = next((a for a in action_log if a['timestamp'] == breakout_ts), None)
            reasons = rejection['reasons'] if rejection else "No rejection logged (Triggered?)"
            pytest.fail(f"Price Gap Fail. TS: {breakout_ts}. Rejection: {reasons}")

        assert long_sig.loc[breakout_ts] == True
        
    def test_flash_crash_priority_sl_over_tp(self):
        """Verify that if both SL and TP hit, SL wins (Safety Priority)."""
        df, crash_idx = make_flash_crash_scenario(tp_dist=10.0, sl_dist=5.0)
        crash_ts = df.index[crash_idx]
        strategy = make_strategy()
        df = strategy.calculate_indicators(df)
        df = strategy.apply_filters(df)
        
        # Setup a dummy position that is ALREADY OPEN at the crash bar
        pos = {
            'direction': 1,
            'entry_price': 100.0,
            'stop': 95.0,     # Hit by Low
            'tp_price': 110.0, # Hit by High
            'bars_held': 10
        }
        
        # Ensure crash_ts exists after dropna
        if crash_ts not in df.index:
            pytest.fail(f"Crash timestamp {crash_ts} dropped. Need more warmup.")
            
        row = df.loc[crash_ts]
        should_exit, reason, price = strategy.check_exit(pos, row, df)
        
        assert should_exit == True
        assert reason == 'Stop Loss'
        assert price == 95.0

    def test_exact_rth_boundary(self):
        """Signal fires exactly at 09:30:00."""
        # 2025-06-03 is a Tuesday (avoid weekend maintenance)
        start_date = datetime(2025, 6, 3, 10, 0)
        df, breakout_idx = make_breakout_scenario(warmup_extra=100, start=start_date)
        
        # Set the breakout bar timestamp to exactly 09:30:00
        new_index = df.index.tolist()
        new_index[breakout_idx] = df.index[breakout_idx].replace(hour=9, minute=30, second=0)
        df.index = pd.DatetimeIndex(new_index)
        breakout_ts = df.index[breakout_idx]
        
        # Enable RTH Filter, ensure others pass
        strategy = make_strategy(**{
            'Enable RTH Filter': 1,
            'Min ADX Threshold': 0.0,
            'Min ATR (Points)': 0.0,
            'Enable SMA Filter': False,
            'Enable Volume Filter': False
        })
        df = strategy.calculate_indicators(df)
        df = strategy.apply_filters(df)
        res = strategy.calculate_entry_signals(df, verbose=True)
        long_sig, _, action_log = res if len(res) == 3 else (res[0], res[1], [])
        
        if not bool(long_sig.loc[breakout_ts]):
            rejection = next((a for a in action_log if a['timestamp'] == breakout_ts), None)
            reasons = rejection['reasons'] if rejection else "No rejection logged"
            pytest.fail(f"RTH Boundary Fail at 09:30. In_RTH: {df.loc[breakout_ts, 'in_rth']}. Rejection: {reasons}")

        assert long_sig.loc[breakout_ts] == True

    def test_exact_maintenance_boundary(self):
        """Signal fires at 16:59:00 (1 min before maintenance)."""
        # 2025-06-03 is a Tuesday
        start_date = datetime(2025, 6, 3, 10, 0)
        df, breakout_idx = make_breakout_scenario(warmup_extra=100, start=start_date)
        new_index = df.index.tolist()
        new_index[breakout_idx] = df.index[breakout_idx].replace(hour=16, minute=59, second=0)
        df.index = pd.DatetimeIndex(new_index)
        breakout_ts = df.index[breakout_idx]
        
        # Set Buffer to 0 to test exact boundary, ensure others pass
        strategy = make_strategy(**{
            'Enable Maintenance Filter': True, 
            'Maintenance Buffer Minutes': 0,
            'Min ADX Threshold': 0.0,
            'Min ATR (Points)': 0.0
        })
        df = strategy.calculate_indicators(df)
        df = strategy.apply_filters(df)
        res = strategy.calculate_entry_signals(df, verbose=True)
        long_sig, _, action_log = res if len(res) == 3 else (res[0], res[1], [])
        
        if not bool(long_sig.loc[breakout_ts]):
            rejection = next((a for a in action_log if a['timestamp'] == breakout_ts), None)
            reasons = rejection['reasons'] if rejection else "No rejection logged"
            
            # Deep forensic dump
            h = df.loc[breakout_ts, 'high']
            dh = df.loc[breakout_ts, 'donchian_high']
            prev_h = df.shift(1).loc[breakout_ts, 'high']
            prev_dh = df.shift(1).loc[breakout_ts, 'donchian_high']
            lb = (h > dh) and (prev_h <= prev_dh)
            
            m = {}
            for k in ['ADX', 'ATR', 'SMA_Long', 'VOL', 'RSI_Long', 'VWAP_Long', 'RTH', 'MAINT', 'ENABLE_L']:
                if k in locals(): # in case I forgot some
                    pass 
            
            # Re-verify the logic from strategy.py:350
            msg = (f"MAINT Boundary Fail. LB: {lb} (H:{h:.2f} > DH:{dh:.2f} & PrevH:{prev_h:.2f} <= PrevDH:{prev_dh:.2f}).\n"
                   f"In_Maint: {df.loc[breakout_ts, 'in_maintenance']}\n"
                   f"Rejection: {reasons}")
            pytest.fail(msg)

        assert long_sig.loc[breakout_ts] == True
        
        # Move to 17:00:00
        df, breakout_idx = make_breakout_scenario(warmup_extra=100, start=start_date)
        new_index = df.index.tolist()
        new_index[breakout_idx] = df.index[breakout_idx].replace(hour=17, minute=0, second=0)
        df.index = pd.DatetimeIndex(new_index)
        breakout_ts = df.index[breakout_idx]
        
        df = strategy.calculate_indicators(df)
        df = strategy.apply_filters(df)
        res = strategy.calculate_entry_signals(df, verbose=True)
        long_sig = res[0] # Signal is the first element
        
        # Should FAIL
        assert long_sig.loc[breakout_ts] == False

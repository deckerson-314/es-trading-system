import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from strategies.bollinger.indicators import calculate_rsi, calculate_vwap
from strategies.bollinger.filters import apply_rsi_filter, apply_vwap_filter

def test_rsi_calculation():
    """Test that RSI calculates smoothly over 100 random bars"""
    dates = [datetime(2025, 1, 1) + timedelta(minutes=i) for i in range(100)]
    
    # Create simple upward trend to test overbought
    df = pd.DataFrame({
        'close': np.linspace(100, 150, 100) # Constant gain
    }, index=dates)
    
    rsi = calculate_rsi(df, period=14)
    assert rsi.iloc[-1] > 70  # Should be heavily overbought

    # Create simple downward trend to test oversold
    df = pd.DataFrame({
        'close': np.linspace(150, 100, 100) # Constant loss
    }, index=dates)
    
    rsi = calculate_rsi(df, period=14)
    assert rsi.iloc[-1] < 30  # Should be heavily oversold
    
def test_rsi_filter():
    df = pd.DataFrame({
        'rsi': [20, 50, 80]
    })
    
    df_filtered = apply_rsi_filter(df, enable_rsi_filter=True, rsi_overbought=70, rsi_oversold=30)
    
    # RSI = 20 (oversold) -> Long allowed, Short not overbought
    assert df_filtered.iloc[0]['rsi_filter_long'] == True
    assert df_filtered.iloc[0]['rsi_filter_short'] == False
    
    # RSI = 50 (neutral) -> Neither allowed (in strict mean reversion)
    assert df_filtered.iloc[1]['rsi_filter_long'] == False
    assert df_filtered.iloc[1]['rsi_filter_short'] == False
    
    # RSI = 80 (overbought) -> Short allowed, Long not oversold
    assert df_filtered.iloc[2]['rsi_filter_long'] == False
    assert df_filtered.iloc[2]['rsi_filter_short'] == True

def test_vwap_calculation():
    """Test intraday VWAP calculation"""
    dates = [
        datetime(2025, 1, 1, 9, 30),
        datetime(2025, 1, 1, 9, 31),
        datetime(2025, 1, 2, 9, 30) # Next day!
    ]
    
    df = pd.DataFrame({
        'high': [102, 112, 52],
        'low': [98, 108, 48],
        'close': [100, 110, 50],
        'volume': [100, 200, 50]
    }, index=pd.DatetimeIndex(dates))
    
    vwap = calculate_vwap(df)
    
    # Bar 1: TP = 100, Vol = 100 -> VWAP = 100
    assert vwap.iloc[0] == 100.0
    
    # Bar 2: TP = 110, Vol = 200. Total TP*V = 10000 + 22000 = 32000. Total Vol = 300. VWAP = 106.66
    assert abs(vwap.iloc[1] - 106.666) < 0.01
    
    # Bar 3: NEW DAY. TP = 50, Vol = 50 -> VWAP = 50
    assert vwap.iloc[2] == 50.0

def test_vwap_filter():
    """Test VWAP mean reversion filter logic"""
    df = pd.DataFrame({
        'close': [90, 100, 110],
        'vwap': [100, 100, 100]
    })
    
    df_filtered = apply_vwap_filter(df, enable_vwap_filter=True)
    
    # Close 90 < VWAP 100 -> Long allowed (buying below average)
    assert df_filtered.iloc[0]['vwap_filter_long'] == True
    assert df_filtered.iloc[0]['vwap_filter_short'] == False
    
    # Close 110 > VWAP 100 -> Short allowed (selling above average)
    assert df_filtered.iloc[2]['vwap_filter_long'] == False
    assert df_filtered.iloc[2]['vwap_filter_short'] == True

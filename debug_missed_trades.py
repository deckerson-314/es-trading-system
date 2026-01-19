
import pandas as pd
import sys
import os
import numpy as np
from datetime import datetime

# Add project root to path
sys.path.append(os.getcwd())
from bollinger_strategy.strategy_v4 import BollingerBandStrategyV4

# Helper to wrap params
def wrap_params(p):
    return {k: {'value': v} for k, v in p.items()}

# Mock parameters matching live_params.csv (wrapped)
raw_params = {
    'Bollinger Band Length': 5,
    'Bollinger Band StdDev': 2.265,
    'Timeframe (minutes)': 2,
    'Long Entry on Body in Zone': 0,
    'Long Entry on Wick Touch': 1,
    'Short Entry on Body in Zone': 0,
    'Short Entry on Wick Touch': 1,
    'Enable Long Trades': 1,
    'Enable Short Trades': 1,
    'Initial Stop Loss (%)': 0.5,
    'Enable Trailing Stop': 0,
    'ATR Length for Trailing Stop': 1,
    'ATR Multiplier for Trailing Stop': 0.5114,
    'Trailing Delay (bars)': 0,
    'Opposite Bollinger Band TP': 0,
    'Fixed ATR TP': 0,
    'Fixed BB at Entry TP': 0,
    'ATR Length for TP': 1,
    'ATR Multiplier for TP': 2.3233,
    'ATR Length for Filter': 1,
    'Max ATR Filter (Points)': 4.0189,
    'Min ATR Filter (Points)': 1.4812,
    'Enable Trend Filter': 0,
    'Trend EMA Length': 1,
    'Enable ADX Filter': 1,
    'ADX Period': 1,
    'Max ADX Threshold': 21,
    'RTH Start (HH:MM)': '09:30',
    'RTH End (HH:MM)': '16:00',
    'Enable RTH Filter': 0,
    'RTH Exit Buffer (minutes)': 20,
    'Volume MA Length': 1,
    'Max Volume Multiplier': 2.8447,
    'Enable Maintenance Filter': 1,
    'Daily Maintenance Start (HH:MM)': '17:00', 
    'Daily Maintenance End (HH:MM)': '17:30',
    'Weekend Maintenance Start Day': 4,
    'Weekend Maintenance Start Time (HH:MM)': '17:00',
    'Weekend Maintenance End Day': 6,
    'Weekend Maintenance End Time (HH:MM)': '18:00',
    'Maintenance Buffer Minutes': 24,
    'Max Open Trades': 1,
    'Transaction Cost (Per Trade)': 20
}

params = wrap_params(raw_params)

# Values from debug dump (Dec 30 12:10 - 12:30 range approx)
data_rows = [
    # Time, Open, High, Low, Close, Volume
    ('2025-12-30 12:10:00', 6951.75, 6953.0, 6951.75, 6952.0, 2684.0),
    ('2025-12-30 12:11:00', 6952.0, 6952.75, 6951.5, 6951.5, 1324.0),
    ('2025-12-30 12:12:00', 6951.5, 6952.0, 6951.0, 6951.25, 483.0),
    ('2025-12-30 12:13:00', 6951.5, 6951.75, 6950.5, 6950.5, 1279.0),
    ('2025-12-30 12:14:00', 6950.5, 6950.75, 6949.0, 6949.25, 2351.0),
    ('2025-12-30 12:15:00', 6949.25, 6949.25, 6947.5, 6947.5, 2195.0),
    # 12:14+15 -> 12:16 Bar (2-min). Signal here?
    
    ('2025-12-30 12:16:00', 6947.5, 6947.75, 6946.0, 6946.5, 3352.0),
    ('2025-12-30 12:17:00', 6946.75, 6947.0, 6945.75, 6946.25, 1070.0),
    # 12:16+17 -> 12:18 Bar (2-min).
    
    ('2025-12-30 12:18:00', 6946.25, 6947.0, 6945.5, 6946.5, 1162.0),
    ('2025-12-30 12:19:00', 6946.25, 6947.25, 6945.75, 6946.5, 856.0),
    
    ('2025-12-30 12:20:00', 6946.5, 6947.5, 6946.25, 6947.0, 936.0),
    ('2025-12-30 12:21:00', 6947.0, 6949.0, 6946.75, 6948.75, 1695.0),
]

# Create local DF
df = pd.DataFrame(data_rows, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
df['datetime'] = pd.to_datetime(df['datetime']).dt.tz_localize(None)
df.set_index('datetime', inplace=True)

# NEED TO CORRECTLY RESAMPLE MANUALLY for this test to match strategy_v4 logic
# Strategy v4 resamples internally if len(df) >= 2.
# We are passing a small 1-min df, so it should resample to 2-min.

strategy = BollingerBandStrategyV4(params)

print("\n--- CALCULATING INDICATORS (Internal Resampling) ---")
# This returns the RESAMPLED dataframe (2-min bars)
df_resampled = strategy.calculate_indicators(df)

# We need to manually add 'atr_filter' and others because they are done in apply_filters
# But apply_filters drops rows, so let's call it but keep the original
df_filtered = strategy.apply_filters(df_resampled.copy())

# Logic from calculate_entry_signals uses Arrays.
# Let's inspect the indicators on the 2-min bars
cols_to_show = ['open', 'high', 'low', 'close', 'volume', 'lower', 'upper', 'atr_filter_values', 'adx']
print(df_filtered[cols_to_show].to_string())

# Manually check signal logic for the bar ending at 12:16 (Timestamp 12:16 in 'right' label)
# or 12:18.
# Live Trade was 12:18:07 (executed 12:18 signal? or 12:16 signal delayed?)
# If delayed by 2m, it executed 12:16 signal.
# 12:16 Bar covers 12:14:00 to 12:16:00.
# 12:18 Bar covers 12:16:00 to 12:18:00.

print("\n--- SIGNAL CHECK (Focused) ---")
entry_long, entry_short = strategy.calculate_entry_signals(df_filtered)
df_filtered['long_signal'] = entry_long
df_filtered['short_signal'] = entry_short

target_cols = ['close', 'lower', 'long_signal', 'short_signal', 'adx']
print(df_filtered[target_cols].tail(10))

# Explicit check
print("\nExplicit Check 12:16 vs 12:18:")
if '2025-12-30 12:16:00' in df_filtered.index:
    print("12:16 ROW:", df_filtered.loc['2025-12-30 12:16:00'][target_cols])
if '2025-12-30 12:18:00' in df_filtered.index:
    print("12:18 ROW:", df_filtered.loc['2025-12-30 12:18:00'][target_cols])


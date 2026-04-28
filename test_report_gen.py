
import os
import pandas as pd
from datetime import datetime, timedelta
from strategies.bollinger.strategy import BollingerStrategy
from types import SimpleNamespace

def test_report():
    # Mock data
    data = pd.DataFrame({
        'open': [100, 101, 102, 101],
        'high': [105, 106, 107, 106],
        'low': [95, 96, 97, 96],
        'close': [102, 103, 104, 103],
        'volume': [1000, 1100, 1200, 1100],
        'upper': [110, 111, 112, 111],
        'lower': [90, 91, 92, 91],
        'mid': [100, 101, 102, 101],
        'rsi': [50, 55, 60, 55],
        'vwap': [100, 101, 102, 101]
    }, index=pd.date_range(datetime.now() - timedelta(minutes=60), periods=4, freq='15min'))

    # Mock parameters dictionary as expected by get_param_value
    params = {
        'Bollinger Band Length': {'value': 20},
        'Enable Long Trades': {'value': True},
        'Enable Short Trades': {'value': True},
        'Long Entry on Wick Touch': {'value': False},
        'Long Entry on Body in Zone': {'value': True},
        'Long Trigger (% From Lower Band)': {'value': 0.0},
        'Short Entry on Wick Touch': {'value': False},
        'Short Entry on Body in Zone': {'value': True},
        'Short Trigger (% From Upper Band)': {'value': 0.0},
        'Initial Stop Loss (%)': {'value': 0.5},
        'Enable Trailing Stop': {'value': True},
        'ATR Length for Trailing Stop': {'value': 26},
        'ATR Multiplier for Trailing Stop': {'value': 3.0},
        'Opposite Bollinger Band TP': {'value': False},
        'Fixed ATR TP': {'value': False},
        'Fixed BB at Entry TP': {'value': True},
        'ATR Length for TP': {'value': 26},
        'ATR Multiplier for TP': {'value': 2.0},
        'ATR Length for Filter': {'value': 26},
        'Max ATR Filter (Points)': {'value': 4.0},
        'Min ATR Filter (Points)': {'value': 0.5},
        'Enable Trend Filter': {'value': False},
        'Trend EMA Length': {'value': 200},
        'Enable ADX Filter': {'value': False},
        'ADX Period': {'value': 14},
        'Max ADX Threshold': {'value': 25.0},
        'Enable RSI Filter': {'value': False},
        'RSI Period': {'value': 14},
        'RSI Overbought': {'value': 70},
        'RSI Oversold': {'value': 30},
        'Enable VWAP Filter': {'value': False},
        'Enable RTH Filter': {'value': True},
        'RTH Start (HH:MM)': {'value': '09:30'},
        'RTH End (HH:MM)': {'value': '16:00'},
        'RTH Exit Buffer (minutes)': {'value': 0},
        'Volume MA Length': {'value': 50},
        'Max Volume Multiplier': {'value': 1.5},
        'Enable Maintenance Filter': {'value': False},
        'Daily Maintenance Start (HH:MM)': {'value': '16:00'},
        'Daily Maintenance End (HH:MM)': {'value': '16:30'},
        'Weekend Maintenance Start Day': {'value': 4},
        'Weekend Maintenance Start Time (HH:MM)': {'value': '16:00'},
        'Weekend Maintenance End Day': {'value': 6},
        'Weekend Maintenance End Time (HH:MM)': {'value': '17:00'},
        'Maintenance Buffer Minutes': {'value': 5},
        'Timeframe (minutes)': {'value': 1},
        'Trailing Delay (bars)': {'value': 5}
    }

    strategy = BollingerStrategy(params)
    
    trade = {
        'entry_time': data.index[1],
        'exit_time': data.index[3],
        'direction': 1,
        'entry_price': 101.0,
        'exit_price': 105.0,
        'pnl': 200.0,
        'qty': 1,
        'reason': 'Take Profit'
    }

    output_dir = os.path.join(os.getcwd(), 'web', 'trades')
    os.makedirs(output_dir, exist_ok=True)
    
    filename = strategy.generate_trade_report(trade, data, output_dir)
    print(f"Report filename: {filename}")
    
    full_path = os.path.join(output_dir, filename) if filename else None
    if full_path and os.path.exists(full_path):
        print(f"Verification SUCCESS: Report file exists at {full_path}")
    else:
        print("Verification FAILED: Report file missing.")

if __name__ == "__main__":
    test_report()

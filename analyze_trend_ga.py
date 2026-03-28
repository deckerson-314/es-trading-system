
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import sys

# === CONFIGURATION ===
run_id = '2026-03-15-1'
is_file = fr'c:\Trading\Trend\output\genetic_trades_is_{run_id}.csv'
oos_file = fr'c:\Trading\Trend\output\genetic_trades_oos_{run_id}.csv'
results_file = fr'c:\Trading\Trend\parameters\genetic_results_{run_id}.csv'
report_file = 'analysis_report.txt'

class Logger(object):
    def __init__(self):
        self.terminal = sys.stdout
        self.log = open(report_file, "w", encoding='utf-8')

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        pass    

sys.stdout = Logger()

print(f"Analyzing GA Run: {run_id}")

# === 1. TRADE ANALYSIS ===
def analyze_trades(file_path, label):
    print(f"\n{'='*20} {label} Analysis {'='*20}")
    try:
        trades = pd.read_csv(file_path, parse_dates=['entry_time', 'exit_time'])
    except FileNotFoundError:
        print(f"File not found: {file_path}")
        return None

    if len(trades) == 0:
        print("No trades found.")
        return None

    trades = trades.sort_values('entry_time')
    
    # Metrics
    win_rate = len(trades[trades['pnl'] > 0]) / len(trades)
    avg_pnl = trades['pnl'].mean()
    total_pnl = trades['pnl'].sum()
    gross_profit = trades[trades['pnl'] > 0]['pnl'].sum()
    gross_loss = abs(trades[trades['pnl'] < 0]['pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
    max_drawdown = trades['drawdown'].max() if 'drawdown' in trades.columns else 0
    
    # Duration
    trades['duration_minutes'] = (trades['exit_time'] - trades['entry_time']).dt.total_seconds() / 60
    
    print(f"Total Trades: {len(trades)}")
    print(f"Win Rate:     {win_rate:.2%}")
    print(f"Avg PnL:      ${avg_pnl:.2f}")
    print(f"Total PnL:    ${total_pnl:.2f}")
    print(f"Profit Factor: {profit_factor:.2f}")
    print(f"Max Drawdown: ${max_drawdown:.2f}")
    print(f"Avg Duration: {trades['duration_minutes'].mean():.0f} min")
    
    print("\nExit Reasons:")
    print(trades['reason'].value_counts())

    return {
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'avg_pnl': avg_pnl,
        'total_pnl': total_pnl
    }

is_metrics = analyze_trades(is_file, "IN-SAMPLE (IS)")
oos_metrics = analyze_trades(oos_file, "OUT-OF-SAMPLE (OOS)")

# Comparison
if is_metrics and oos_metrics:
    print(f"\n{'='*20} IS vs OOS Robustness Check {'='*20}")
    print(f"{'Metric':<15} {'IS':<10} {'OOS':<10} {'Diff %'}")
    
    for k in is_metrics:
        is_val = is_metrics[k]
        oos_val = oos_metrics[k]
        
        # Calculate percent drop/gain
        if is_val != 0:
            diff = (oos_val - is_val) / abs(is_val) * 100
        else:
            diff = 0
            
        print(f"{k:<15} {is_val:<10.2f} {oos_val:<10.2f} {diff:+.1f}%")

# === 2. PARAMETER CONVERGENCE ANALYSIS ===
print(f"\n{'='*20} Parameter Convergence {'='*20}")
try:
    results = pd.read_csv(results_file)
    
    # Check for new filter usage
    if 'Enable SMA Filter' in results.columns:
        sma_usage = results['Enable SMA Filter'].mean()
        print(f"SMA Filter Usage: {sma_usage:.2%}")
    
    if 'Enable Volume Filter' in results.columns:
        vol_usage = results['Enable Volume Filter'].mean()
        print(f"Volume Filter Usage: {vol_usage:.2%}")
        
    print("\nTop 5 Parameter Sets (by Rank/row order):")
    # Usually results are saved generation by generation. The last rows might be the final population.
    # We will just look at the last 10 rows
    last_gen = results.tail(10)
    
    key_params = ['Enable SMA Filter', 'SMA Period', 'Enable Volume Filter', 'Volume MA Length', 'Min Volume Multiplier']
    for col in key_params:
        if col in results.columns:
            try:
                mean_val = last_gen[col].mean()
                std_val = last_gen[col].std()
                print(f"{col:<30}: Mean={mean_val:.2f} (Std={std_val:.2f})")
            except:
                print(f"{col:<30}: {last_gen[col].mode()[0]}")

except FileNotFoundError:
    print(f"Results file not found: {results_file}")

print("\nDeep Analysis Complete.")

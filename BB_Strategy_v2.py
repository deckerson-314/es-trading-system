#!/usr/bin/env python3
"""
Bollinger Band Trading Strategy Backtester - Version 2.0
========================================================
Uses shared bollinger_strategy module for unified strategy logic.
Converted from Jupyter notebook to standalone Python script.

Version History:
- 2.0 - Refactored to use shared bollinger_strategy module
- 1.23 - Added Trailing Delay (bars) with min changes (aligned with GA)
- 1.22 - Added Timeframe (minutes) param for resampling
- 1.21 - Added Min Volume Multiplier param
"""

import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from bollinger_strategy import BollingerBandStrategy, load_params

# === Paths ===
NOTEBOOK_DIR = os.getcwd()
DRIVE_PATH = os.path.join(NOTEBOOK_DIR, 'Bollinger')
PARAMS_CSV = os.path.join(DRIVE_PATH, 'parameters', 'BB_Strategy_Parameters_optimized.csv')
DATA_CSV = os.path.join(DRIVE_PATH, 'data', 'ES_full_1min_continuous_ratio_adjusted.csv')
LOG_DIR = os.path.join(DRIVE_PATH, 'logs')
PLOTS_DIR = os.path.join(DRIVE_PATH, 'plots')
SUMMARY_PLOT_DIR = os.path.join(PLOTS_DIR, 'summary')

os.makedirs(os.path.dirname(PARAMS_CSV), exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(PLOTS_DIR, exist_ok=True)
os.makedirs(SUMMARY_PLOT_DIR, exist_ok=True)

# === Config ===
VERSION = '2.0'
FROM_DATE = '2024-07-01'
TO_DATE = '2025-10-01'
multiplier = 50
initial_capital = 50000
candles_before_after = 50
max_individual_plots = 20  # Limit individual trade plots to last N
volume_window = 50  # Rolling window for avg volume

# === Logging ===
log_file = os.path.join(LOG_DIR, f'backtest_log_v{VERSION}.txt')

def log(message):
    """Log message to both console and file."""
    print(message)
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(message + '\n')

log(f"Starting backtest version {VERSION} from {FROM_DATE} to {TO_DATE}")

# === Load Parameters ===
try:
    params_dict = load_params(PARAMS_CSV, return_dataframe=True)[0]
    log(f"Parameters loaded from: {PARAMS_CSV}")
except FileNotFoundError:
    log(f"ERROR: Parameter file not found: {PARAMS_CSV}")
    sys.exit(1)

# Initialize strategy
strategy = BollingerBandStrategy(params_dict)

log("\n" + "="*70)
log("STRATEGY PARAMETERS")
log("="*70)
for name in sorted(params_dict.keys()):
    if not name.startswith('__'):
        value = params_dict[name]['value']
        log(f"{name:45} = {value}")
log("="*70 + "\n")

# === Load Data ===
log(f"Loading data from: {DATA_CSV}")
df = pd.read_csv(DATA_CSV, header=None, 
                 names=['datetime', 'open', 'high', 'low', 'close', 'volume'],
                 parse_dates=['datetime'], index_col='datetime')
df = df.loc[FROM_DATE:TO_DATE]
log(f"Loaded {len(df)} bars from {FROM_DATE} to {TO_DATE}")

# === Calculate Indicators ===
log("Calculating indicators...")
df = strategy.calculate_indicators(df)
log(f"After resampling: {len(df)} bars")

# === Apply Filters ===
log("Applying filters...")
df = strategy.apply_filters(df)
log(f"After filters: {len(df)} bars")

if len(df) == 0:
    log("ERROR: No data after filtering!")
    sys.exit(1)

# === Simulation ===
log("Running simulation...")
positions = []
trades = []

for row in df.itertuples():
    # Check exits first
    for pos in positions[:]:
        # Update trailing stop
        strategy.update_trailing_stop(pos, row, df)
        
        # Check exit
        should_exit, reason, price = strategy.check_exit(pos, row, df)
        
        if should_exit:
            pnl = (price - pos['entry_price']) * pos['direction'] * multiplier
            trade = pos.copy()
            trade.update({
                'exit_time': row.Index,
                'exit_price': price,
                'pnl': pnl,
                'reason': reason
            })
            trades.append(trade)
            positions.remove(pos)
            log(f"EXIT: {row.Index} | {reason} | Price: {price:.2f} | PNL: {pnl:,.2f}")
    
    # Check entries
    if len(positions) >= strategy.max_open_trades:
        continue
    
    enter_long, enter_short = strategy.check_entry(row, df)
    
    if enter_long or enter_short:
        direction = 1 if enter_long else -1
        entry_price = row.close
        position = strategy.setup_position(entry_price, direction, row, df)
        positions.append(position)
        
        tp_display = f"{position['tp']:.2f}" if position['tp'] is not None else "Dynamic"
        log(f"ENTRY: {row.Index} | {'Long' if direction==1 else 'Short'} | "
            f"Price: {entry_price:.2f} | TP: {tp_display}")

# === Final Close ===
for pos in positions:
    exit_price = df.iloc[-1]['close']
    pnl = (exit_price - pos['entry_price']) * pos['direction'] * multiplier
    trade = pos.copy()
    trade.update({
        'exit_time': df.index[-1],
        'exit_price': exit_price,
        'pnl': pnl,
        'reason': 'End of Data'
    })
    trades.append(trade)
    log(f"FINAL CLOSE: PNL {pnl:,.2f} (End)")

# === Convert trades to DataFrame for analysis ===
trades_df = pd.DataFrame(trades)

if not trades_df.empty:
    trades_df['entry_date'] = trades_df['entry_time'].dt.date
    trades_df['exit_date'] = trades_df['exit_time'].dt.date
    trades_df['duration'] = (trades_df['exit_time'] - trades_df['entry_time']).dt.total_seconds() / 60  # minutes
    trades_df['direction_str'] = trades_df['direction'].map({1: 'Long', -1: 'Short'})
    trades_df['result'] = np.where(trades_df['pnl'] > 0, 'Win', 'Loss')
    
    # === Detailed Metrics ===
    total_pnl = trades_df['pnl'].sum()
    num_trades = len(trades_df)
    win_rate = (trades_df['pnl'] > 0).mean() * 100
    avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean() if (trades_df['pnl'] > 0).any() else 0
    avg_loss = trades_df[trades_df['pnl'] < 0]['pnl'].mean() if (trades_df['pnl'] < 0).any() else 0
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
    
    # Long vs Short
    long_trades = trades_df[trades_df['direction'] == 1]
    short_trades = trades_df[trades_df['direction'] == -1]
    long_pnl = long_trades['pnl'].sum()
    short_pnl = short_trades['pnl'].sum()
    long_count = len(long_trades)
    short_count = len(short_trades)
    long_win_rate = (long_trades['pnl'] > 0).mean() * 100 if long_count > 0 else 0
    short_win_rate = (short_trades['pnl'] > 0).mean() * 100 if short_count > 0 else 0
    long_avg_win = long_trades[long_trades['pnl'] > 0]['pnl'].mean() if (long_trades['pnl'] > 0).any() else 0
    long_avg_loss = long_trades[long_trades['pnl'] < 0]['pnl'].mean() if (long_trades['pnl'] < 0).any() else 0
    short_avg_win = short_trades[short_trades['pnl'] > 0]['pnl'].mean() if (short_trades['pnl'] > 0).any() else 0
    short_avg_loss = short_trades[short_trades['pnl'] < 0]['pnl'].mean() if (short_trades['pnl'] < 0).any() else 0
    long_pf = abs(long_avg_win / long_avg_loss) if long_avg_loss != 0 else float('inf')
    short_pf = abs(short_avg_win / short_avg_loss) if short_avg_loss != 0 else float('inf')
    
    # Duration stats
    avg_duration = trades_df['duration'].mean()
    max_duration = trades_df['duration'].max()
    min_duration = trades_df['duration'].min()
    
    # Equity curve, drawdown, run-up
    trades_df = trades_df.sort_values('exit_time')
    equity = initial_capital
    equity_curve = []
    peak = initial_capital
    max_drawdown = 0
    max_runup = 0
    
    for _, trade in trades_df.iterrows():
        equity += trade['pnl']
        equity_curve.append((trade['exit_time'], equity))
        
        if equity > peak:
            peak = equity
        else:
            current_drawdown = peak - equity
            if current_drawdown > max_drawdown:
                max_drawdown = current_drawdown
    
    equity_df = pd.DataFrame(equity_curve, columns=['time', 'equity']).set_index('time')
    
    # Daily returns for Sharpe/Sortino
    daily_pnl = trades_df.groupby(trades_df['exit_time'].dt.date)['pnl'].sum()
    daily_equity = initial_capital + daily_pnl.cumsum().fillna(initial_capital)
    daily_returns = daily_equity.pct_change().dropna()
    sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(252) if daily_returns.std() != 0 else 0
    downside = daily_returns[daily_returns < 0]
    sortino = daily_returns.mean() / downside.std() * np.sqrt(252) if len(downside) > 0 and downside.std() != 0 else 0
    
    # === Log Detailed Results ===
    log("\n" + "="*80)
    log("DETAILED BACKTEST RESULTS")
    log("="*80)
    log(f"Period: {FROM_DATE} to {TO_DATE}")
    log(f"Total Trades: {num_trades}")
    log(f"Total PNL: ${total_pnl:,.2f}")
    log(f"Win Rate: {win_rate:.1f}%")
    log(f"Profit Factor: {profit_factor:.2f}")
    log(f"Avg Win: ${avg_win:,.2f} | Avg Loss: ${avg_loss:,.2f}")
    log(f"Sharpe Ratio: {sharpe:.2f}")
    log(f"Sortino Ratio: {sortino:.2f}")
    log(f"Max Drawdown: ${max_drawdown:,.2f}")
    log(f"Max Run-up: ${max_runup:,.2f}")
    log(f"Avg Trade Duration: {avg_duration:.1f} min | Max: {max_duration:.0f} min | Min: {min_duration:.0f} min")
    log("\nLONG vs SHORT PERFORMANCE")
    log("-" * 50)
    log(f"Long Trades: {long_count} | PNL: ${long_pnl:,.2f} | Win Rate: {long_win_rate:.1f}% | PF: {long_pf:.2f}")
    log(f"Short Trades: {short_count} | PNL: ${short_pnl:,.2f} | Win Rate: {short_win_rate:.1f}% | PF: {short_pf:.2f}")
    log("="*80)
    
    # === Combined Summary Plot ===
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(16, 15), sharex=True, 
                                         gridspec_kw={'height_ratios': [3, 1, 2]})
    
    # Price, BB, Trades (ax1)
    ax1.plot(df.index, df['close'], label='Close', color='black', linewidth=0.8, alpha=0.7)
    ax1.plot(df.index, df['upper'], label='Upper BB', color='blue', linestyle='--', alpha=0.7)
    ax1.plot(df.index, df['mid'], label='Mid BB', color='gray', linestyle='--', alpha=0.7)
    ax1.plot(df.index, df['lower'], label='Lower BB', color='blue', linestyle='--', alpha=0.7)
    
    # Trade markers
    for _, trade in trades_df.iterrows():
        entry_color = 'green' if trade['direction'] == 1 else 'red'
        exit_color = 'lime' if trade['pnl'] > 0 else 'darkred'
        marker_size = 80
        ax1.scatter(trade['entry_time'], trade['entry_price'],
                    color=entry_color, marker='^', s=marker_size, edgecolors='black', zorder=5)
        ax1.scatter(trade['exit_time'], trade['exit_price'],
                    color=exit_color, marker='v', s=marker_size, edgecolors='black', zorder=5)
    
    ax1.set_title(f"Combined Summary: Trades, Market, Performance (v{VERSION})")
    ax1.set_ylabel('Price')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Volume (ax2)
    ax2.bar(df.index, df['volume'], width=0.0008, color='gray', alpha=0.6)
    ax2.set_ylabel('Volume')
    
    # Equity Curve (ax3)
    ax3.plot(equity_df.index, equity_df['equity'], label='Equity Curve', color='blue', linewidth=2)
    ax3.fill_between(equity_df.index, initial_capital, equity_df['equity'],
                     where=equity_df['equity'] >= initial_capital, color='green', alpha=0.3, label='Run-up')
    ax3.fill_between(equity_df.index, initial_capital, equity_df['equity'],
                     where=equity_df['equity'] < initial_capital, color='red', alpha=0.3, label='Drawdown')
    ax3.set_ylabel('Equity ($)')
    ax3.set_xlabel('Date')
    ax3.legend()
    ax3.grid(True, alpha=0.3)
    
    plt.tight_layout(pad=3.0)
    combined_plot_path = os.path.join(SUMMARY_PLOT_DIR, f"combined_summary_v{VERSION}.png")
    plt.savefig(combined_plot_path, dpi=150)
    plt.close()
    log(f"Combined summary plot saved: {combined_plot_path}")
    
    # === Individual Trade Plots (Last N only) ===
    trades_to_plot = trades_df.tail(max_individual_plots)
    for i, trade in enumerate(trades_to_plot.itertuples(), 1):
        entry_loc = df.index.get_loc(trade.entry_time)
        exit_loc = df.index.get_loc(trade.exit_time)
        start_loc = max(0, entry_loc - candles_before_after)
        end_loc = min(len(df) - 1, exit_loc + candles_before_after)
        segment = df.iloc[start_loc:end_loc + 1]
        
        fig, ax = plt.subplots(figsize=(14, 7))
        times = segment.index
        
        for j in range(len(segment)):
            t = times[j]
            o, h, l, c = segment.iloc[j][['open', 'high', 'low', 'close']]
            color = 'green' if c >= o else 'red'
            ax.vlines(t, l, h, color='black', linewidth=0.8)
            ax.vlines(t, o, c, color=color, linewidth=2.5)
        
        ax.plot(times, segment['upper'], label='Upper BB', color='blue', linestyle='--', alpha=0.7)
        ax.plot(times, segment['mid'], label='Mid BB', color='gray', linestyle='--', alpha=0.7)
        ax.plot(times, segment['lower'], label='Lower BB', color='blue', linestyle='--', alpha=0.7)
        
        entry_marker = '^' if trade.direction == 1 else 'v'
        entry_color = 'green' if trade.direction == 1 else 'red'
        exit_color = 'lime' if trade.pnl > 0 else 'red'
        
        ax.scatter(trade.entry_time, trade.entry_price, marker=entry_marker, color=entry_color, 
                   s=120, zorder=5, label='Entry')
        ax.scatter(trade.exit_time, trade.exit_price, marker='v', color=exit_color, 
                   s=120, zorder=5, label='Exit')
        
        if hasattr(trade, 'stop_history') and trade.stop_history:
            stop_times, stop_prices = zip(*trade.stop_history)
            ax.plot(stop_times, stop_prices, label='Trailing Stop', color='orange', linewidth=2)
        
        if trade.tp is not None:
            ax.hlines(trade.tp, trade.entry_time, trade.exit_time, color='purple', 
                     linestyle=':', linewidth=1.5, label='Fixed TP')
        
        ax.set_title(f"Trade {i} (Last {max_individual_plots}) | {trade.direction_str} | "
                    f"PNL: ${trade.pnl:,.0f} | {trade.reason}")
        ax.set_xlabel('Time (ET)')
        ax.set_ylabel('Price')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        trade_type = trade.direction_str
        result = 'Win' if trade.pnl > 0 else 'Loss'
        pnl_str = f"{'+$' if trade.pnl > 0 else '-$'}{abs(trade.pnl):,.0f}"
        filename = f"trade_last_{i:03d}_{trade_type}_{result}_{pnl_str}_v{VERSION}.png"
        plot_path = os.path.join(PLOTS_DIR, filename)
        plt.savefig(plot_path, dpi=150)
        plt.close()
        log(f"Individual plot saved: {filename}")
else:
    log("No trades executed.")
    total_pnl = 0
    num_trades = 0

log(f"Backtest v{VERSION} completed. Logs: {log_file} | Summary: {SUMMARY_PLOT_DIR} | "
    f"Individual (last {max_individual_plots}): {PLOTS_DIR}")


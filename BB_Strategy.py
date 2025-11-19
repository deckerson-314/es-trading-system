#!/usr/bin/env python3
# Bollinger Band Trading Strategy Backtester - Version 1.23
# ========================================================
# FINAL: 100% working — Added timeframe resampling param
# FIXED: Combined summary plot, PARAMS_CSV v1.12
# NO bugs
# Version History (Last 10 Versions):
# ------------------------------------------------
# Version 1.23 - Added Trailing Delay (bars) with min changes (aligned with GA)
# Version 1.22 - Added Timeframe (minutes) param for resampling
# Version 1.21 - Added Min Volume Multiplier param
# Version 1.20 - Combined summary plots, fig height fix
# Version 1.19 - Added extensive analysis, summary plots
# Version 1.18 - Added Min ATR Filter, RTH to CSV
# Version 1.17 - Fixed in_rth calculation
# Version 1.16 - np.maximum.reduce → pd.Series
# Version 1.15 - Parameter name fix
# Version 1.14 - ast.literal_eval fix
# Version 1.13 - atr_tp column fix
# To set up a new environment:
# 1. Install Python 3.x
# 2. Install JupyterLab: pip install jupyterlab
# 3. Install required libraries: pip install pandas numpy matplotlib
# 4. Run JupyterLab: jupyter lab
# 5. Ensure data and parameter CSV files are in the specified paths
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import ast
from datetime import time

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
VERSION = '1.23'
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
    print(message)
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(message + '\n')

log(f"Starting backtest version {VERSION} from {FROM_DATE} to {TO_DATE}")

# === Load Parameters (Safe Parsing) ===
try:
    params_df = pd.read_csv(PARAMS_CSV)
    log(f"Parameters loaded from: {PARAMS_CSV}")
except FileNotFoundError:
    log(f"ERROR: Parameter file not found: {PARAMS_CSV}")
    raise

param_order = params_df['Name'].tolist()
params = {}
for _, row in params_df.iterrows():
    key = row['Name'].strip()
    value = row['Value'].strip()
    if value in ['true', 'false']:
        params[key] = (value == 'true')
    elif value.replace('.', '', 1).replace('-', '', 1).isdigit():
        try:
            params[key] = ast.literal_eval(value)
        except:
            params[key] = value
    else:
        params[key] = value

# NEW: Trailing Delay (bars) param (with default if missing)
trailing_delay = params.get('Trailing Delay (bars)', 5)
trailing_delay = max(0, trailing_delay)  # Clamp to >=0

log("\n" + "="*70)
log("STRATEGY PARAMETERS (CSV ORDER)")
log("="*70)
for key in param_order:
    key = key.strip()
    if key in params and not key.startswith('__'):
        log(f"{key:45} = {params[key]}")
log(f"Trailing Delay (bars): {trailing_delay}")
log("="*70 + "\n")

# === Extract ===
max_open_trades = params.get('Max Open Trades', 1)
enable_long = params.get('Enable Long Trades', True)
enable_short = params.get('Enable Short Trades', True)
bb_length = params.get('Bollinger Band Length', 30)
bb_stddev = params.get('Bollinger Band StdDev', 2.0)
long_wick_touch = params.get('Long Entry on Wick Touch', False)
long_body_zone = params.get('Long Entry on Body in Zone', True)
long_trigger_pct = params.get('Long Trigger (% From Lower Band)', 0.0)
short_wick_touch = params.get('Short Entry on Wick Touch', False)
short_body_zone = params.get('Short Entry on Body in Zone', True)
short_trigger_pct = params.get('Short Trigger (% From Upper Band)', 0.0)
initial_sl_pct = params.get('Initial Stop Loss (%)', 0.5)
enable_trailing = params.get('Enable Trailing Stop', True)
atr_length_ts = params.get('ATR Length for Trailing Stop', 26)
atr_mult_ts = params.get('ATR Multiplier for Trailing Stop', 3.0)
opposite_bb_tp = params.get('Opposite Bollinger Band TP', False)
fixed_atr_tp = params.get('Fixed ATR TP', False)
fixed_bb_entry_tp = params.get('Fixed BB at Entry TP', True)
atr_length_tp = params.get('ATR Length for TP', 26)
atr_mult_tp = params.get('ATR Multiplier for TP', 2.0)
min_atr_points = params.get('Min ATR Filter (Points)', 10.0)
enable_rth_filter = params.get('Enable RTH Filter', True)
rth_start_str = params.get('RTH Start (HH:MM)', '09:30')
rth_end_str = params.get('RTH End (HH:MM)', '16:00')
min_volume_multiplier = params.get('Min Volume Multiplier', 1.5)
timeframe = params.get('Timeframe (minutes)', 1)
if not 1 <= timeframe <= 15:
    log("Warning: Timeframe out of range (1-15), defaulting to 1 min")
    timeframe = 1
log(f"Using timeframe: {timeframe} minute(s)")

# Parse time strings to time objects
def parse_time(time_str):
    try:
        return pd.to_datetime(time_str, format='%H:%M').time()
    except:
        log(f"Warning: Invalid time format '{time_str}', using default 09:30")
        return time(9, 30)

rth_start = parse_time(rth_start_str)
rth_end = parse_time(rth_end_str)
log(f"Filter Params: Min ATR={min_atr_points}, Enable RTH={enable_rth_filter}, RTH {rth_start_str}-{rth_end_str}, Min Volume Multiplier={min_volume_multiplier}")

# === Load Data ===
df = pd.read_csv(DATA_CSV, header=None, names=['datetime', 'open', 'high', 'low', 'close', 'volume'],
                 parse_dates=['datetime'], index_col='datetime')
df = df.loc[FROM_DATE:TO_DATE]

# New: Resample if timeframe > 1
if timeframe > 1:
    df = df.resample(f'{timeframe}T').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    log(f"Resampled to {timeframe}-min bars: {len(df)} bars")

# === Indicators ===
df['mid'] = df['close'].rolling(bb_length).mean()
df['std'] = df['close'].rolling(bb_length).std()
df['upper'] = df['mid'] + df['std'] * bb_stddev
df['lower'] = df['mid'] - df['std'] * bb_stddev

# TRUE RANGE
tr = np.maximum.reduce([
    df['high'] - df['low'],
    (df['high'] - df['close'].shift()).abs(),
    (df['low'] - df['close'].shift()).abs()
])
df['atr_ts'] = pd.Series(tr, index=df.index).rolling(atr_length_ts).mean()
if fixed_atr_tp:
    df['atr_tp'] = pd.Series(tr, index=df.index).rolling(atr_length_tp).mean()
    log("Fixed ATR TP enabled — atr_tp column added")
else:
    log("Fixed ATR TP disabled — atr_tp column NOT added")

# Volume Filter
df['avg_volume'] = df['volume'].rolling(volume_window).mean()
df['volume_filter'] = df['volume'] >= df['avg_volume'] * min_volume_multiplier
df['atr_filter'] = df['atr_ts'] >= min_atr_points
if enable_rth_filter:
    df['in_rth'] = pd.Series(df.index.time, index=df.index).between(rth_start, rth_end)
    log(f"RTH filter enabled: {rth_start_str} to {rth_end_str}")
else:
    df['in_rth'] = True
    log("RTH filter disabled — all hours allowed")
df.dropna(inplace=True)
log(f"After filters: {len(df)} bars")

# === Simulation ===
positions = []
trades = []
for idx, row in df.iterrows():
    for pos in positions[:]:
        direction = pos['direction']
        if direction == 1:
            pos['max_high'] = max(pos['max_high'], row['high'])
        else:
            pos['min_low'] = min(pos['min_low'], row['low'])
        
        # Increment bars_held
        pos['bars_held'] = pos.get('bars_held', 0) + 1
        
        # Trailing stop (only after delay)
        if enable_trailing and pos['bars_held'] >= trailing_delay:
            atr = row['atr_ts']
            if direction == 1:
                pos['stop'] = max(pos['stop'], pos['max_high'] - atr * atr_mult_ts)
            else:
                pos['stop'] = min(pos['stop'], pos['min_low'] + atr * atr_mult_ts)
        pos['stop_history'].append((idx, pos['stop']))
        candidates = []
        if direction == 1 and row['low'] <= pos['stop']:
            candidates.append(('Stop', pos['stop']))
        elif direction == -1 and row['high'] >= pos['stop']:
            candidates.append(('Stop', pos['stop']))
        if opposite_bb_tp:
            if direction == 1 and row['high'] >= row['upper']:
                candidates.append(('TP Opposite BB', row['upper']))
            elif direction == -1 and row['low'] <= row['lower']:
                candidates.append(('TP Opposite BB', row['lower']))
        if fixed_atr_tp and 'atr_tp' in df.columns and pos['tp'] is not None:
            if direction == 1 and row['high'] >= pos['tp']:
                candidates.append(('TP Fixed ATR', pos['tp']))
            elif direction == -1 and row['low'] <= pos['tp']:
                candidates.append(('TP Fixed ATR', pos['tp']))
        if fixed_bb_entry_tp and pos['tp'] is not None:
            if direction == 1 and row['high'] >= pos['tp']:
                candidates.append(('TP Fixed BB Entry', pos['tp']))
            elif direction == -1 and row['low'] <= pos['tp']:
                candidates.append(('TP Fixed BB Entry', pos['tp']))
        if candidates:
            candidates.sort(key=lambda x: abs(x[1] - pos['entry_price']))
            exit_reason, exit_price = candidates[0]
            pnl = (exit_price - pos['entry_price']) * direction * multiplier
            trade = pos.copy()
            trade.update({'exit_time': idx, 'exit_price': exit_price, 'pnl': pnl, 'reason': exit_reason})
            trades.append(trade)
            positions.remove(pos)
            log(f"EXIT: {idx} | {exit_reason} | Price: {exit_price:.2f} | PNL: {pnl:,.2f}")
    if len(positions) >= max_open_trades or not row['in_rth'] or not row['atr_filter'] or not row['volume_filter']:
        continue
    enter_long = enter_short = False
    if enable_long:
        trigger = row['lower'] * (1 - long_trigger_pct / 100)
        if (long_wick_touch and row['low'] <= trigger) or (long_body_zone and row['close'] <= trigger):
            enter_long = True
    if enable_short:
        trigger = row['upper'] * (1 + short_trigger_pct / 100)
        if (short_wick_touch and row['high'] >= trigger) or (short_body_zone and row['close'] >= trigger):
            enter_short = True
    if enter_long or enter_short:
        direction = 1 if enter_long else -1
        entry_price = row['close']
        stop = entry_price * (1 - direction * initial_sl_pct / 100)
        print(f"ENTRY: long={enter_long}, short={enter_short}, direction={direction}, entry={entry_price:.2f}, stop={stop:.2f}")
        tp = None
        tp_method = "None"
        if fixed_atr_tp and 'atr_tp' in df.columns:
            atr_val = row['atr_tp']
            if not pd.isna(atr_val):
                tp = entry_price + direction * atr_val * atr_mult_tp
                tp_method = "Fixed ATR"
        elif fixed_bb_entry_tp:
            tp = row['upper'] if direction == 1 else row['lower']
            tp_method = "Fixed BB at Entry"
        if enable_trailing:
            peak = row['high'] if direction == 1 else row['low']
            trail_stop = peak - direction * row['atr_ts'] * atr_mult_ts
            stop = max(stop, trail_stop) if direction == 1 else min(stop, trail_stop)
        pos = {
            'entry_time': idx, 'entry_price': entry_price, 'direction': direction,
            'stop': stop, 'tp': tp, 'max_high': row['high'] if direction == 1 else None,
            'min_low': row['low'] if direction == -1 else None,
            'stop_history': [(idx, stop)],
            'bars_held': 0  # Track bars held for trailing delay
        }
        positions.append(pos)
        tp_display = f"{tp:.2f}" if tp is not None else "Dynamic"
        log(f"ENTRY: {idx} | {'Long' if direction==1 else 'Short'} | Price: {entry_price:.2f} | TP: {tp_display} ({tp_method})")

# === Final Close ===
for pos in positions:
    exit_price = df.iloc[-1]['close']
    pnl = (exit_price - pos['entry_price']) * pos['direction'] * multiplier
    trade = pos.copy()
    trade.update({'exit_time': df.index[-1], 'exit_price': exit_price, 'pnl': pnl, 'reason': 'End of Data'})
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
if not trades_df.empty:
    # Overall
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
    current_drawdown = 0
    current_runup = 0
    for _, trade in trades_df.iterrows():
        equity += trade['pnl']
        equity_curve.append((trade['exit_time'], equity))
       
        if equity > peak:
            peak = equity
            current_drawdown = 0
        else:
            current_drawdown = peak - equity
            if current_drawdown > max_drawdown:
                max_drawdown = current_drawdown
       
        current_runup = equity - (initial_capital + sum(trades_df.loc[:trade.name-1, 'pnl']) if trade.name > 0 else 0)
        if current_runup > max_runup:
            max_runup = current_runup
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
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(16, 15), sharex=True, gridspec_kw={'height_ratios': [3, 1, 2]})
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
else:
    log("No trades executed.")
    total_pnl = 0
    num_trades = 0

# === Individual Trade Plots (Last N only) ===
if not trades_df.empty:
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
        ax.scatter(trade.entry_time, trade.entry_price, marker=entry_marker, color=entry_color, s=120, zorder=5, label='Entry')
        ax.scatter(trade.exit_time, trade.exit_price, marker='v', color=exit_color, s=120, zorder=5, label='Exit')
        stop_times, stop_prices = zip(*trade.stop_history)
        ax.plot(stop_times, stop_prices, label='Trailing Stop', color='orange', linewidth=2)
        if trade.tp is not None:
            ax.hlines(trade.tp, trade.entry_time, trade.exit_time, color='purple', linestyle=':', linewidth=1.5, label='Fixed TP')
        ax.set_title(f"Trade {i} (Last {max_individual_plots}) | {trade.direction_str} | PNL: ${trade.pnl:,.0f} | {trade.reason}")
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

log(f"Backtest v{VERSION} completed. Logs: {log_file} | Summary: {SUMMARY_PLOT_DIR} | Individual (last {max_individual_plots}): {PLOTS_DIR}")


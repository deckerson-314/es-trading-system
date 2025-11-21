#!/usr/bin/env python3
"""
Bollinger Band Trading Strategy Backtester - Version 3.0
========================================================
Uses shared bollinger_strategy module for unified strategy logic.
Enhanced with Plotly interactive visualizations and comprehensive analysis.

Version History:
- 3.0 - Plotly interactive charts, enhanced analysis features
- 2.0 - Refactored to use shared bollinger_strategy module
- 1.23 - Added Trailing Delay (bars) with min changes (aligned with GA)
"""

import os
import sys
import re
import json
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.offline as pyo
import webbrowser
from bollinger_strategy import BollingerBandStrategy, load_params

# === Paths ===
NOTEBOOK_DIR = os.getcwd()
DRIVE_PATH = os.path.join(NOTEBOOK_DIR, 'Bollinger')
PARAMS_CSV = os.path.join(DRIVE_PATH, 'parameters', 'BB_Strategy_Parameters_optimized.csv')
DATA_CSV = os.path.join(DRIVE_PATH, 'data', 'ES_full_1min_continuous_ratio_adjusted.csv')
LOG_DIR = os.path.join(DRIVE_PATH, 'logs')
PLOTS_DIR = os.path.join(DRIVE_PATH, 'plots')
SUMMARY_PLOT_DIR = os.path.join(PLOTS_DIR, 'summary')
HTML_DIR = os.path.join(PLOTS_DIR, 'html_v3')

os.makedirs(os.path.dirname(PARAMS_CSV), exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(PLOTS_DIR, exist_ok=True)
os.makedirs(SUMMARY_PLOT_DIR, exist_ok=True)
os.makedirs(HTML_DIR, exist_ok=True)

# === Config ===
VERSION = '3.0'
FROM_DATE = '2025-04-01'
TO_DATE = '2025-08-01'
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
log("STRATEGY PARAMETERS (grouped by category)")
log("="*70)

# Group parameters for display
def group_params_for_display(params_dict_local):
    """Group parameters into logical categories."""
    groups = {
        'Entry Criteria': ['Enable Long Trades', 'Enable Short Trades', 'Bollinger Band Length', 
                          'Bollinger Band StdDev', 'Long Entry on Wick Touch', 'Long Entry on Body in Zone',
                          'Long Trigger (% From Lower Band)', 'Short Entry on Wick Touch', 
                          'Short Entry on Body in Zone', 'Short Trigger (% From Upper Band)',
                          'Min ATR Filter (Points)', 'RTH Start (HH:MM)', 'RTH End (HH:MM)',
                          'Enable RTH Filter', 'Min Volume Multiplier', 'Timeframe (minutes)',
                          'Max Open Trades'],
        'Take Profit Criteria': ['Opposite Bollinger Band TP', 'Fixed ATR TP', 'Fixed BB at Entry TP',
                                'ATR Length for TP', 'ATR Multiplier for TP'],
        'Stop Loss Criteria': ['Initial Stop Loss (%)', 'Enable Trailing Stop', 
                              'ATR Length for Trailing Stop', 'ATR Multiplier for Trailing Stop',
                              'Trailing Delay (bars)'],
        'GA Criteria': ['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                       'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                       'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                       'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT']
    }
    
    grouped = {}
    for group_name, param_list in groups.items():
        grouped[group_name] = {k: v for k, v in params_dict_local.items() if k in param_list}
    
    return grouped

grouped_params = group_params_for_display(params_dict)
for group_name, params in grouped_params.items():
    if params:
        log(f"\n--- {group_name} ---")
        for name in sorted(params.keys()):
            value = params[name]['value']
            log(f"  {name:45} = {value}")

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
    trades_df['entry_hour'] = trades_df['entry_time'].dt.hour
    trades_df['entry_month'] = trades_df['entry_time'].dt.month
    trades_df['entry_day_of_week'] = trades_df['entry_time'].dt.dayofweek  # 0=Monday
    
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
    
    # Duration stats by direction
    long_avg_duration = long_trades['duration'].mean() if len(long_trades) > 0 else 0
    long_max_duration = long_trades['duration'].max() if len(long_trades) > 0 else 0
    long_min_duration = long_trades['duration'].min() if len(long_trades) > 0 else 0
    
    short_avg_duration = short_trades['duration'].mean() if len(short_trades) > 0 else 0
    short_max_duration = short_trades['duration'].max() if len(short_trades) > 0 else 0
    short_min_duration = short_trades['duration'].min() if len(short_trades) > 0 else 0
    
    # Equity curve, drawdown, run-up
    trades_df = trades_df.sort_values('exit_time')
    equity = initial_capital
    equity_curve = []
    peak = initial_capital
    max_drawdown = 0
    max_runup = 0
    drawdown_curve = []
    
    for _, trade in trades_df.iterrows():
        equity += trade['pnl']
        equity_curve.append((trade['exit_time'], equity))
        
        if equity > peak:
            peak = equity
            current_drawdown = 0
            current_runup = equity - initial_capital
            if current_runup > max_runup:
                max_runup = current_runup
        else:
            current_drawdown = peak - equity
            if current_drawdown > max_drawdown:
                max_drawdown = current_drawdown
        
        drawdown_curve.append((trade['exit_time'], current_drawdown))
    
    equity_df = pd.DataFrame(equity_curve, columns=['time', 'equity']).set_index('time')
    drawdown_df = pd.DataFrame(drawdown_curve, columns=['time', 'drawdown']).set_index('time')
    
    # Daily returns for Sharpe/Sortino
    daily_pnl = trades_df.groupby(trades_df['exit_time'].dt.date)['pnl'].sum()
    daily_equity = initial_capital + daily_pnl.cumsum().fillna(initial_capital)
    daily_returns = daily_equity.pct_change().dropna()
    sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(252) if daily_returns.std() != 0 else 0
    downside = daily_returns[daily_returns < 0]
    sortino = daily_returns.mean() / downside.std() * np.sqrt(252) if len(downside) > 0 and downside.std() != 0 else 0
    
    # Additional metrics
    largest_win = trades_df['pnl'].max()
    largest_loss = trades_df['pnl'].min()
    consecutive_wins = 0
    consecutive_losses = 0
    max_consecutive_wins = 0
    max_consecutive_losses = 0
    current_streak = 0
    current_streak_type = None
    
    for _, trade in trades_df.iterrows():
        is_win = trade['pnl'] > 0
        if is_win:
            if current_streak_type == 'win':
                current_streak += 1
            else:
                if current_streak > max_consecutive_losses:
                    max_consecutive_losses = current_streak
                current_streak = 1
                current_streak_type = 'win'
        else:
            if current_streak_type == 'loss':
                current_streak += 1
            else:
                if current_streak > max_consecutive_wins:
                    max_consecutive_wins = current_streak
                current_streak = 1
                current_streak_type = 'loss'
    
    if current_streak_type == 'win' and current_streak > max_consecutive_wins:
        max_consecutive_wins = current_streak
    elif current_streak_type == 'loss' and current_streak > max_consecutive_losses:
        max_consecutive_losses = current_streak
    
    # Monthly performance
    monthly_pnl = trades_df.groupby(trades_df['exit_time'].dt.to_period('M')).agg({
        'pnl': ['sum', 'count'],
        'result': lambda x: (x == 'Win').sum()
    })
    monthly_pnl.columns = ['Total_PNL', 'Trade_Count', 'Win_Count']
    monthly_pnl['Win_Rate'] = (monthly_pnl['Win_Count'] / monthly_pnl['Trade_Count'] * 100).round(1)
    
    # Debug: Log monthly PNL data
    log(f"\nMonthly PNL data:\n{monthly_pnl}")
    
    # Exit reason breakdown
    exit_reasons = trades_df['reason'].value_counts()
    log(f"\nExit reasons:\n{exit_reasons}")
    
    # Performance by hour
    hourly_perf = trades_df.groupby('entry_hour').agg({
        'pnl': ['sum', 'mean', 'count'],
        'result': lambda x: (x == 'Win').sum()
    })
    hourly_perf.columns = ['Total_PNL', 'Avg_PNL', 'Trade_Count', 'Win_Count']
    hourly_perf['Win_Rate'] = (hourly_perf['Win_Count'] / hourly_perf['Trade_Count'] * 100).round(1)
    log(f"\nHourly performance:\n{hourly_perf}")
    
    # Performance by day of week
    dow_perf = trades_df.groupby('entry_day_of_week').agg({
        'pnl': ['sum', 'mean', 'count'],
        'result': lambda x: (x == 'Win').sum()
    })
    dow_perf.columns = ['Total_PNL', 'Avg_PNL', 'Trade_Count', 'Win_Count']
    dow_perf['Win_Rate'] = (dow_perf['Win_Count'] / dow_perf['Trade_Count'] * 100).round(1)
    # Map day numbers to names (only for days that have trades)
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    dow_perf.index = [day_names[i] for i in dow_perf.index]
    log(f"\nDay of week performance:\n{dow_perf}")
    
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
    log(f"Largest Win: ${largest_win:,.2f} | Largest Loss: ${largest_loss:,.2f}")
    log(f"Sharpe Ratio: {sharpe:.2f}")
    log(f"Sortino Ratio: {sortino:.2f}")
    log(f"Max Drawdown: ${max_drawdown:,.2f}")
    log(f"Max Run-up: ${max_runup:,.2f}")
    log(f"Max Consecutive Wins: {max_consecutive_wins} | Max Consecutive Losses: {max_consecutive_losses}")
    log(f"Avg Trade Duration: {avg_duration:.1f} min | Max: {max_duration:.0f} min | Min: {min_duration:.0f} min")
    log("\nLONG vs SHORT PERFORMANCE")
    log("-" * 50)
    log(f"Long Trades: {long_count} | PNL: ${long_pnl:,.2f} | Win Rate: {long_win_rate:.1f}% | PF: {long_pf:.2f}")
    log(f"Short Trades: {short_count} | PNL: ${short_pnl:,.2f} | Win Rate: {short_win_rate:.1f}% | PF: {short_pf:.2f}")
    log("="*80)
    
    # === Create Interactive Plotly Dashboard ===
    log("\nCreating interactive Plotly visualizations...")
    
    # 1. MAIN OVERVIEW CHART (Price, BB, Trades, Volume, Equity)
    fig_main = make_subplots(
        rows=4, cols=1,
        subplot_titles=('Price & Bollinger Bands with Trades', 'Volume', 'Equity Curve', 'Drawdown'),
        vertical_spacing=0.06,
        row_heights=[0.4, 0.15, 0.25, 0.2],
        shared_xaxes=True
    )
    
    # Convert index to list for better serialization
    df_index_list = df.index.tolist()
    
    # Candlestick chart
    fig_main.add_trace(go.Candlestick(
        x=df_index_list,
        open=df['open'].tolist(),
        high=df['high'].tolist(),
        low=df['low'].tolist(),
        close=df['close'].tolist(),
        name='Price',
        increasing_line_color='green',
        decreasing_line_color='red'
    ), row=1, col=1)
    
    # BB Bands
    fig_main.add_trace(go.Scatter(x=df_index_list, y=df['upper'].tolist(), name='Upper BB', 
                                  line=dict(color='blue', width=1, dash='dash'), 
                                  opacity=0.7), row=1, col=1)
    fig_main.add_trace(go.Scatter(x=df_index_list, y=df['mid'].tolist(), name='Mid BB', 
                                  line=dict(color='gray', width=1, dash='dash'), 
                                  opacity=0.7), row=1, col=1)
    fig_main.add_trace(go.Scatter(x=df_index_list, y=df['lower'].tolist(), name='Lower BB', 
                                  line=dict(color='blue', width=1, dash='dash'), 
                                  opacity=0.7), row=1, col=1)
    
    # Trade markers, TP lines, and trailing stops
    for _, trade in trades_df.iterrows():
        entry_color = 'green' if trade['direction'] == 1 else 'red'
        exit_color = 'lime' if trade['pnl'] > 0 else 'darkred'
        
        # Entry marker
        fig_main.add_trace(go.Scatter(
            x=[trade['entry_time']], y=[trade['entry_price']],
            mode='markers', marker=dict(symbol='triangle-up', size=12, color=entry_color,
                                       line=dict(color='black', width=1)),
            name='Entry', showlegend=False,
            hovertemplate=f"<b>ENTRY</b><br>" +
                         f"Time: {trade['entry_time']}<br>" +
                         f"Price: ${trade['entry_price']:.2f}<br>" +
                         f"Direction: {trade['direction_str']}<extra></extra>"
        ), row=1, col=1)
        
        # Exit marker
        fig_main.add_trace(go.Scatter(
            x=[trade['exit_time']], y=[trade['exit_price']],
            mode='markers', marker=dict(symbol='triangle-down', size=12, color=exit_color,
                                       line=dict(color='black', width=1)),
            name='Exit', showlegend=False,
            hovertemplate=f"<b>EXIT</b><br>" +
                         f"Time: {trade['exit_time']}<br>" +
                         f"Price: ${trade['exit_price']:.2f}<br>" +
                         f"PNL: ${trade['pnl']:,.2f}<br>" +
                         f"Reason: {trade['reason']}<extra></extra>"
        ), row=1, col=1)
        
        # Take Profit line (if fixed TP exists)
        if 'tp' in trade and trade['tp'] is not None and not pd.isna(trade['tp']):
            fig_main.add_trace(go.Scatter(
                x=[trade['entry_time'], trade['exit_time']],
                y=[trade['tp'], trade['tp']],
                mode='lines',
                name='Take Profit',
                line=dict(color='purple', dash='dot', width=2),
                showlegend=False,
                hovertemplate=f"<b>Take Profit</b><br>" +
                             f"Price: ${trade['tp']:.2f}<extra></extra>"
            ), row=1, col=1)
        
        # Trailing Stop line (if stop_history exists) - make it very visible
        if 'stop_history' in trade and trade['stop_history'] and len(trade['stop_history']) > 0:
            stop_times, stop_prices = zip(*trade['stop_history'])
            fig_main.add_trace(go.Scatter(
                x=list(stop_times),
                y=list(stop_prices),
                mode='lines',
                name='Trailing Stop',
                line=dict(color='red', width=4, dash='solid'),
                opacity=0.9,
                showlegend=False,
                hovertemplate="<b>Trailing Stop</b><br>" +
                             "Time: %{x}<br>" +
                             "Stop: $%{y:.2f}<extra></extra>"
            ), row=1, col=1)
    
    # Volume
    fig_main.add_trace(go.Bar(x=df_index_list, y=df['volume'].tolist(), name='Volume',
                             marker_color='gray', opacity=0.6), row=2, col=1)
    
    # Equity Curve
    equity_index_list = equity_df.index.tolist()
    equity_values_list = equity_df['equity'].tolist()
    fig_main.add_trace(go.Scatter(x=equity_index_list, y=equity_values_list, 
                                  name='Equity', line=dict(color='blue', width=2),
                                  fill='tozeroy', fillcolor='rgba(0,100,255,0.1)'), row=3, col=1)
    fig_main.add_hline(y=initial_capital, line_dash="dash", line_color="gray", 
                      annotation_text="Initial Capital", row=3, col=1)
    
    # Drawdown
    drawdown_index_list = drawdown_df.index.tolist()
    drawdown_values_list = drawdown_df['drawdown'].tolist()
    fig_main.add_trace(go.Scatter(x=drawdown_index_list, y=drawdown_values_list,
                                 name='Drawdown', line=dict(color='red', width=2),
                                 fill='tozeroy', fillcolor='rgba(255,0,0,0.2)'), row=4, col=1)
    
    fig_main.update_layout(
        title=f'BB Strategy Backtest Overview - v{VERSION} | Period: {FROM_DATE} to {TO_DATE}',
        height=1200,
        hovermode='x unified',
        showlegend=True
    )
    
    fig_main.update_xaxes(title_text="Date", row=4, col=1)
    
    # Configure y-axes with auto-scaling when x-axis is zoomed
    fig_main.update_yaxes(
        title_text="Price ($)", 
        row=1, col=1,
        autorange=True,  # Auto-scale based on visible data
        fixedrange=False  # Allow manual y-axis zoom
    )
    fig_main.update_yaxes(
        title_text="Volume", 
        row=2, col=1,
        autorange=True,
        fixedrange=False
    )
    fig_main.update_yaxes(
        title_text="Equity ($)", 
        row=3, col=1,
        autorange=True,
        fixedrange=False
    )
    fig_main.update_yaxes(
        title_text="Drawdown ($)", 
        row=4, col=1,
        autorange=True,
        fixedrange=False
    )
    
    # 2. PERFORMANCE METRICS DASHBOARD
    fig_metrics = make_subplots(
        rows=2, cols=3,
        subplot_titles=('Monthly PNL', 'Monthly Win Rate', 'PNL Distribution',
                       'Performance by Hour', 'Performance by Day of Week', 'Exit Reasons'),
        specs=[[{"type": "bar"}, {"type": "bar"}, {"type": "histogram"}],
               [{"type": "bar"}, {"type": "bar"}, {"type": "pie"}]]
    )
    
    # Monthly PNL - ensure we're using actual data
    monthly_pnl_x = monthly_pnl.index.astype(str).tolist()
    monthly_pnl_y = monthly_pnl['Total_PNL'].tolist()
    log(f"Adding Monthly PNL chart: {len(monthly_pnl_x)} months, first value: {monthly_pnl_y[0] if monthly_pnl_y else 'N/A'}")
    fig_metrics.add_trace(go.Bar(x=monthly_pnl_x, y=monthly_pnl_y,
                                 name='Monthly PNL', marker_color='blue',
                                 hovertemplate='Month: %{x}<br>PNL: $%{y:,.2f}<extra></extra>'),
                         row=1, col=1)
    
    # Monthly Win Rate
    monthly_winrate_y = monthly_pnl['Win_Rate'].tolist()
    fig_metrics.add_trace(go.Bar(x=monthly_pnl_x, y=monthly_winrate_y,
                                 name='Win Rate %', marker_color='green',
                                 hovertemplate='Month: %{x}<br>Win Rate: %{y:.1f}%<extra></extra>'),
                         row=1, col=2)
    
    # PNL Distribution - use actual trades_df['pnl'] values
    pnl_values = trades_df['pnl'].tolist()
    log(f"Adding PNL Distribution: {len(pnl_values)} trades, range: ${min(pnl_values):,.2f} to ${max(pnl_values):,.2f}")
    fig_metrics.add_trace(go.Histogram(x=pnl_values, nbinsx=50, name='PNL Distribution',
                                       marker_color='purple', opacity=0.7,
                                       hovertemplate='PNL Range: $%{x}<br>Count: %{y}<extra></extra>'),
                         row=1, col=3)
    fig_metrics.add_vline(x=0, line_dash="dash", line_color="red", row=1, col=3)
    
    # Performance by Hour - ensure we're using actual data
    hourly_x = hourly_perf.index.tolist()
    hourly_y = hourly_perf['Total_PNL'].tolist()
    hourly_custom = hourly_perf['Trade_Count'].tolist()
    log(f"Adding Hourly Performance: {len(hourly_x)} hours")
    fig_metrics.add_trace(go.Bar(x=hourly_x, y=hourly_y,
                                 name='Hourly PNL', marker_color='orange',
                                 hovertemplate='Hour: %{x}:00<br>PNL: $%{y:,.2f}<br>Trades: %{customdata}<extra></extra>',
                                 customdata=hourly_custom),
                         row=2, col=1)
    
    # Performance by Day of Week - ensure we're using actual data
    dow_x = dow_perf.index.tolist()
    dow_y = dow_perf['Total_PNL'].tolist()
    dow_custom = dow_perf['Win_Rate'].tolist()
    log(f"Adding Day of Week Performance: {len(dow_x)} days")
    fig_metrics.add_trace(go.Bar(x=dow_x, y=dow_y,
                                 name='DOW PNL', marker_color='teal',
                                 hovertemplate='Day: %{x}<br>PNL: $%{y:,.2f}<br>Win Rate: %{customdata:.1f}%<extra></extra>',
                                 customdata=dow_custom),
                         row=2, col=2)
    
    # Exit Reasons - ensure we're using actual data
    exit_labels = exit_reasons.index.tolist()
    exit_values = exit_reasons.values.tolist()
    log(f"Adding Exit Reasons: {len(exit_labels)} reasons")
    fig_metrics.add_trace(go.Pie(labels=exit_labels, values=exit_values,
                                name='Exit Reasons', hole=0.4,
                                hovertemplate='Reason: %{label}<br>Count: %{value}<br>%{percent}<extra></extra>'),
                         row=2, col=3)
    
    fig_metrics.update_layout(
        title=f'Performance Analysis Dashboard - v{VERSION}',
        height=800,
        showlegend=False
    )
    
    # Calculate additional stats for HTML table
    long_largest_win = long_trades['pnl'].max() if len(long_trades) > 0 else 0
    long_largest_loss = long_trades['pnl'].min() if len(long_trades) > 0 else 0
    short_largest_win = short_trades['pnl'].max() if len(short_trades) > 0 else 0
    short_largest_loss = short_trades['pnl'].min() if len(short_trades) > 0 else 0
    
    # Generate individual trade HTML files first (needed for thumbnails)
    trades_to_plot = trades_df.tail(max_individual_plots)
    trade_files = []
    
    for i, trade in enumerate(trades_to_plot.itertuples(), 1):
        entry_loc = df.index.get_loc(trade.entry_time)
        exit_loc = df.index.get_loc(trade.exit_time)
        start_loc = max(0, entry_loc - candles_before_after)
        end_loc = min(len(df) - 1, exit_loc + candles_before_after)
        segment = df.iloc[start_loc:end_loc + 1]
        
        fig_trade = go.Figure()
        
        # Candlestick chart
        fig_trade.add_trace(go.Candlestick(
            x=segment.index,
            open=segment['open'],
            high=segment['high'],
            low=segment['low'],
            close=segment['close'],
            name='Price'
        ))
        
        # BB Bands
        fig_trade.add_trace(go.Scatter(x=segment.index, y=segment['upper'],
                                      name='Upper BB', line=dict(color='blue', dash='dash', width=1),
                                      opacity=0.7))
        fig_trade.add_trace(go.Scatter(x=segment.index, y=segment['mid'],
                                      name='Mid BB', line=dict(color='gray', dash='dash', width=1),
                                      opacity=0.7))
        fig_trade.add_trace(go.Scatter(x=segment.index, y=segment['lower'],
                                      name='Lower BB', line=dict(color='blue', dash='dash', width=1),
                                      opacity=0.7))
        
        # Entry marker
        entry_color = 'green' if trade.direction == 1 else 'red'
        fig_trade.add_trace(go.Scatter(
            x=[trade.entry_time], y=[trade.entry_price],
            mode='markers+text', marker=dict(symbol='triangle-up', size=15, color=entry_color,
                                            line=dict(color='black', width=2)),
            text=['ENTRY'], textposition='top center',
            name='Entry', showlegend=True
        ))
        
        # Exit marker
        exit_color = 'lime' if trade.pnl > 0 else 'darkred'
        fig_trade.add_trace(go.Scatter(
            x=[trade.exit_time], y=[trade.exit_price],
            mode='markers+text', marker=dict(symbol='triangle-down', size=15, color=exit_color,
                                            line=dict(color='black', width=2)),
            text=['EXIT'], textposition='bottom center',
            name='Exit', showlegend=True
        ))
        
        # Trailing stop (if available) - make it very visible
        if hasattr(trade, 'stop_history') and trade.stop_history:
            stop_times, stop_prices = zip(*trade.stop_history)
            fig_trade.add_trace(go.Scatter(
                x=list(stop_times), 
                y=list(stop_prices),
                name='Trailing Stop', 
                line=dict(color='red', width=4, dash='solid'),
                opacity=0.9,
                hovertemplate="<b>Trailing Stop</b><br>" +
                             "Time: %{x}<br>" +
                             "Stop: $%{y:.2f}<extra></extra>"
            ))
        
        # Take Profit line (if fixed)
        if trade.tp is not None:
            fig_trade.add_trace(go.Scatter(
                x=[trade.entry_time, trade.exit_time],
                y=[trade.tp, trade.tp],
                mode='lines', name='Take Profit',
                line=dict(color='purple', dash='dot', width=2)
            ))
        
        trade_type = trade.direction_str
        result = 'Win' if trade.pnl > 0 else 'Loss'
        pnl_str = f"{'+$' if trade.pnl > 0 else '-$'}{abs(trade.pnl):,.0f}"
        
        fig_trade.update_layout(
            title=f"Trade {i} | {trade_type} | {result} | PNL: {pnl_str} | {trade.reason}",
            xaxis_title="Time",
            yaxis_title="Price ($)",
            height=600,
            hovermode='x unified',
            yaxis=dict(
                autorange=True,  # Auto-scale based on visible data
                fixedrange=False  # Allow manual y-axis zoom
            )
        )
        
        filename = f"trade_last_{i:03d}_{trade_type}_{result}_{pnl_str.replace('$', '').replace(',', '')}_v{VERSION}.html"
        trade_html = os.path.join(HTML_DIR, filename)
        fig_trade.write_html(trade_html, include_plotlyjs='cdn')
        log(f"Individual trade plot saved: {filename}")
        
        trade_files.append({
            'filename': filename,
            'index': i,
            'type': trade_type,
            'result': result,
            'pnl': trade.pnl,
            'pnl_str': pnl_str,
            'reason': trade.reason,
            'entry_time': trade.entry_time,
            'exit_time': trade.exit_time
        })
    
    # Create comprehensive dashboard HTML (combines all elements)
    dashboard_html = os.path.join(HTML_DIR, f'comprehensive_dashboard_v{VERSION}.html')
    with open(dashboard_html, 'w', encoding='utf-8') as f:
        f.write(f"""
<!DOCTYPE html>
<html>
<head>
    <title>Trade Statistics - BB Strategy v{VERSION}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1400px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #555; border-bottom: 2px solid #ddd; padding-bottom: 10px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #4CAF50; color: white; font-weight: bold; }}
        tr:hover {{ background-color: #f5f5f5; }}
        .positive {{ color: green; font-weight: bold; }}
        .negative {{ color: red; font-weight: bold; }}
        .metric-box {{ display: inline-block; margin: 10px; padding: 15px; background: #f0f0f0; border-radius: 5px; min-width: 200px; }}
        .metric-label {{ font-size: 12px; color: #666; }}
        .metric-value {{ font-size: 24px; font-weight: bold; color: #333; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>BB Strategy Backtest Statistics - v{VERSION}</h1>
        <p><strong>Period:</strong> {FROM_DATE} to {TO_DATE}</p>
        
        <h2>Overall Performance</h2>
        <div class="metric-box">
            <div class="metric-label">Total PNL</div>
            <div class="metric-value {'positive' if total_pnl > 0 else 'negative'}">${total_pnl:,.2f}</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Total Trades</div>
            <div class="metric-value">{num_trades}</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Win Rate</div>
            <div class="metric-value">{win_rate:.1f}%</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Profit Factor</div>
            <div class="metric-value">{profit_factor:.2f}</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Sharpe Ratio</div>
            <div class="metric-value">{sharpe:.2f}</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Sortino Ratio</div>
            <div class="metric-value">{sortino:.2f}</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Max Drawdown</div>
            <div class="metric-value negative">${max_drawdown:,.2f}</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Max Run-up</div>
            <div class="metric-value positive">${max_runup:,.2f}</div>
        </div>
        
        <h2>Trade Statistics</h2>
        <table>
            <tr>
                <th>Metric</th>
                <th>Overall</th>
                <th>Long</th>
                <th>Short</th>
            </tr>
            <tr>
                <td>Total Trades</td>
                <td>{num_trades}</td>
                <td>{long_count}</td>
                <td>{short_count}</td>
            </tr>
            <tr>
                <td>Total PNL</td>
                <td class="{'positive' if total_pnl > 0 else 'negative'}">${total_pnl:,.2f}</td>
                <td class="{'positive' if long_pnl > 0 else 'negative'}">${long_pnl:,.2f}</td>
                <td class="{'positive' if short_pnl > 0 else 'negative'}">${short_pnl:,.2f}</td>
            </tr>
            <tr>
                <td>Win Rate</td>
                <td>{win_rate:.1f}%</td>
                <td>{long_win_rate:.1f}%</td>
                <td>{short_win_rate:.1f}%</td>
            </tr>
            <tr>
                <td>Profit Factor</td>
                <td>{profit_factor:.2f}</td>
                <td>{long_pf:.2f}</td>
                <td>{short_pf:.2f}</td>
            </tr>
            <tr>
                <td>Avg Win</td>
                <td class="positive">${avg_win:,.2f}</td>
                <td class="positive">${long_avg_win:,.2f}</td>
                <td class="positive">${short_avg_win:,.2f}</td>
            </tr>
            <tr>
                <td>Avg Loss</td>
                <td class="negative">${avg_loss:,.2f}</td>
                <td class="negative">${long_avg_loss:,.2f}</td>
                <td class="negative">${short_avg_loss:,.2f}</td>
            </tr>
            <tr>
                <td>Largest Win</td>
                <td class="positive">${largest_win:,.2f}</td>
                <td class="positive">${long_largest_win:,.2f}</td>
                <td class="positive">${short_largest_win:,.2f}</td>
            </tr>
            <tr>
                <td>Largest Loss</td>
                <td class="negative">${largest_loss:,.2f}</td>
                <td class="negative">${long_largest_loss:,.2f}</td>
                <td class="negative">${short_largest_loss:,.2f}</td>
            </tr>
            <tr>
                <td>Avg Duration (min)</td>
                <td>{avg_duration:.1f}</td>
                <td>{long_avg_duration:.1f}</td>
                <td>{short_avg_duration:.1f}</td>
            </tr>
            <tr>
                <td>Max Duration (min)</td>
                <td>{max_duration:.0f}</td>
                <td>{long_max_duration:.0f}</td>
                <td>{short_max_duration:.0f}</td>
            </tr>
            <tr>
                <td>Min Duration (min)</td>
                <td>{min_duration:.0f}</td>
                <td>{long_min_duration:.0f}</td>
                <td>{short_min_duration:.0f}</td>
            </tr>
        </table>
        
        <h2>Monthly Performance</h2>
        <table>
            <tr>
                <th>Month</th>
                <th>Total PNL</th>
                <th>Trade Count</th>
                <th>Win Rate</th>
            </tr>
""")
        for month, row in monthly_pnl.iterrows():
            pnl_class = 'positive' if row['Total_PNL'] > 0 else 'negative'
            f.write(f"""
            <tr>
                <td>{month}</td>
                <td class="{pnl_class}">${row['Total_PNL']:,.2f}</td>
                <td>{int(row['Trade_Count'])}</td>
                <td>{row['Win_Rate']:.1f}%</td>
            </tr>
""")
        f.write("""
        </table>
        
        <h2>Exit Reasons</h2>
        <table>
            <tr>
                <th>Reason</th>
                <th>Count</th>
                <th>Percentage</th>
            </tr>
""")
        for reason, count in exit_reasons.items():
            pct = (count / num_trades * 100)
            f.write(f"""
            <tr>
                <td>{reason}</td>
                <td>{count}</td>
                <td>{pct:.1f}%</td>
            </tr>
""")
        f.write("""
        </table>
        
        <h2>Performance Metrics Dashboard</h2>
        <div id="performance_metrics_chart"></div>
        
        <h2>Input Parameters</h2>
""")
        # Add parameters to table (grouped)
        grouped_params_html = group_params_for_display(params_dict)
        for group_name, params in grouped_params_html.items():
            if params:
                f.write(f"""
        <h3 style='margin-top: 20px; color: #555; border-bottom: 2px solid #ddd; padding-bottom: 5px;'>{group_name}</h3>
        <table>
            <tr>
                <th>Parameter Name</th>
                <th>Value</th>
                <th>Type</th>
                <th>Min</th>
                <th>Max</th>
            </tr>
""")
                for name in sorted(params.keys()):
                    param_info = params[name]
                    value = param_info.get('value', 'N/A')
                    param_type = param_info.get('type', 'N/A')
                    min_val = param_info.get('min', 'N/A')
                    max_val = param_info.get('max', 'N/A')
                    
                    # Format value based on type
                    if param_type == 'bool':
                        value_str = 'True' if value else 'False'
                    elif param_type == 'float':
                        value_str = f"{value:.4f}" if isinstance(value, (int, float)) else str(value)
                    elif param_type == 'int':
                        value_str = str(int(value)) if isinstance(value, (int, float)) else str(value)
                    else:
                        value_str = str(value)
                    
                    # Format min/max
                    min_str = f"{min_val:.4f}" if isinstance(min_val, float) else (str(int(min_val)) if isinstance(min_val, int) else str(min_val)) if min_val is not None else 'N/A'
                    max_str = f"{max_val:.4f}" if isinstance(max_val, float) else (str(int(max_val)) if isinstance(max_val, int) else str(max_val)) if max_val is not None else 'N/A'
                    
                    f.write(f"""
            <tr>
                <td><strong>{name}</strong></td>
                <td>{value_str}</td>
                <td>{param_type if param_type else 'N/A'}</td>
                <td>{min_str}</td>
                <td>{max_str}</td>
            </tr>
""")
                f.write("        </table>\n")
        
        f.write("""
        <h2>Main Overview Chart</h2>
        <div id="main_overview_chart"></div>
        
        <h2>Individual Trade Charts</h2>
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; margin: 20px 0;">
""")
        # Add thumbnail links for each trade
        for trade_info in trade_files:
            result_class = 'positive' if trade_info['pnl'] > 0 else 'negative'
            f.write(f"""
            <div style="border: 2px solid #ddd; border-radius: 8px; padding: 15px; text-align: center; background: #f9f9f9;">
                <h3 style="margin: 5px 0;">Trade #{trade_info['index']}</h3>
                <p style="margin: 5px 0;"><strong>{trade_info['type']}</strong> | <span class="{result_class}">{trade_info['result']}</span></p>
                <p style="margin: 5px 0; font-size: 18px; font-weight: bold;" class="{result_class}">{trade_info['pnl_str']}</p>
                <p style="margin: 5px 0; color: #666; font-size: 12px;">{trade_info['reason']}</p>
                <p style="margin: 5px 0; color: #666; font-size: 11px;">Entry: {trade_info['entry_time'].strftime('%Y-%m-%d %H:%M')}</p>
                <a href="{trade_info['filename']}" target="_blank" style="display: inline-block; margin-top: 10px; padding: 8px 16px; background: #4CAF50; color: white; text-decoration: none; border-radius: 4px;">View Chart</a>
            </div>
""")
        f.write("""
        </div>
    </div>
    
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
""")
        # Embed the performance metrics chart - extract from to_html
        metrics_html_str = fig_metrics.to_html(include_plotlyjs=False, div_id='performance_metrics_chart')
        # Extract the div and script from the HTML string
        # Find the div tag
        div_start = metrics_html_str.find('<div id="performance_metrics_chart"')
        if div_start != -1:
            div_end = metrics_html_str.find('</div>', div_start) + 6
            metrics_div = metrics_html_str[div_start:div_end]
            f.write(metrics_div)
        
        # Find the script tag
        script_start = metrics_html_str.find('<script')
        if script_start != -1:
            script_end = metrics_html_str.find('</script>', script_start) + 9
            metrics_script = metrics_html_str[script_start:script_end]
            f.write(metrics_script)
        
        # Embed the main overview chart - extract from to_html
        main_html_str = fig_main.to_html(include_plotlyjs=False, div_id='main_overview_chart')
        # Extract the div and script from the HTML string
        # Use regex to find the complete div (handles nested divs)
        import re
        div_pattern = r'<div id="main_overview_chart"[^>]*>.*?</div>'
        div_match = re.search(div_pattern, main_html_str, re.DOTALL)
        if div_match:
            main_div = div_match.group(0)
            f.write(main_div)
        else:
            # Fallback: simple extraction
            div_start = main_html_str.find('<div id="main_overview_chart"')
            if div_start != -1:
                # Find the matching closing div by counting nested divs
                pos = div_start
                depth = 0
                while pos < len(main_html_str):
                    if main_html_str[pos:pos+4] == '<div':
                        depth += 1
                    elif main_html_str[pos:pos+6] == '</div>':
                        depth -= 1
                        if depth == 0:
                            div_end = pos + 6
                            main_div = main_html_str[div_start:div_end]
                            f.write(main_div)
                            break
                    pos += 1
        
        # Find the script tag - there may be multiple, get the one with the chart data
        script_pattern = r'<script type="text/javascript">(.*?)</script>'
        script_matches = re.findall(script_pattern, main_html_str, re.DOTALL)
        if script_matches:
            # Use the last script tag (usually contains the Plotly.newPlot call)
            for script_content in script_matches:
                if 'Plotly.newPlot' in script_content or 'main_overview_chart' in script_content:
                    f.write(f'<script type="text/javascript">{script_content}</script>')
                    break
        else:
            # Fallback: simple extraction
            script_start = main_html_str.find('<script')
            if script_start != -1:
                script_end = main_html_str.find('</script>', script_start) + 9
                main_script = main_html_str[script_start:script_end]
                f.write(main_script)
        f.write("""
    </script>
</body>
</html>
""")
    log(f"Comprehensive dashboard saved: {dashboard_html}")
    
    # Open comprehensive dashboard in browser
    try:
        webbrowser.open(f'file://{os.path.abspath(dashboard_html)}')
        log(f"Opened comprehensive dashboard in browser")
    except:
        log(f"Could not auto-open browser. Please open manually: {dashboard_html}")
    
    log(f"\n{'='*80}")
    log(f"Backtest v{VERSION} completed successfully!")
    log(f"{'='*80}")
    log(f"HTML Output Directory: {HTML_DIR}")
    log(f"  - Comprehensive Dashboard: comprehensive_dashboard_v{VERSION}.html")
    log(f"  - Individual Trades: {len(trade_files)} files")
    log(f"{'='*80}")
    
else:
    log("No trades executed.")
    total_pnl = 0
    num_trades = 0
    log(f"Backtest v{VERSION} completed with no trades.")


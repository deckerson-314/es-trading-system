"""
Reporting and Dashboard Generation for Trend Strategy
=====================================================
Handles generation of HTML dashboards, trade plots, and performance metrics.
Adapted from strategies/bollinger/reporting.py.
"""

import os
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import webbrowser
from .parameters import load_params

def group_params_for_display(params_dict_local):
    """Group parameters into logical categories."""
    groups = {
        'Entry Criteria': ['Enable Long Trades', 'Enable Short Trades', 'Buy Lookback', 'Sell Lookback'],
        'Exit Criteria': ['Initial Stop Loss (%)', 'Take Profit ATR Multiplier', 
                         'Enable Trailing Stop', 'ATR Multiplier for Trailing Stop', 
                         'ATR Length for Trailing Stop', 'Trailing Delay (bars)'],
        'Risk Management': ['Initial Capital', 'Position Sizing (% of Equity)', 'Max Open Trades', 
                           'Max Daily Drawdown (%)', 'Strategy Max Drawdown (%)'],
        'Filters': ['Enable ADX Filter', 'ADX Period', 'Min ADX Threshold',
                   'Enable ATR Filter', 'Min ATR (Points)', 'ATR Filter Period',
                   'Enable SMA Filter', 'SMA Period',
                   'Enable Volume Filter', 'Volume MA Length', 'Min Volume Multiplier',
                   'Enable RSI Filter', 'RSI Period', 'RSI Max Buy Threshold', 'RSI Min Sell Threshold',
                   'Enable VWAP Filter', 'Enable RTH Filter', 'Enable Maintenance Filter'],
        'GA Criteria': ['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                       'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                       'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                       'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT']
    }
    
    grouped = {}
    for group_name, param_list in groups.items():
        grouped[group_name] = {k: v for k, v in params_dict_local.items() if k in param_list}
    
    # Add 'Other' group for unclassified params
    all_grouped_keys = [k for group in grouped.values() for k in group.keys()]
    others = {k: v for k, v in params_dict_local.items() if k not in all_grouped_keys and not str(v).startswith('===')}
    if others:
        grouped['Other Parameters'] = others
        
    return grouped

def calculate_stats(trades_df, equity_series=None):
    """Calculate standard performance metrics."""
    if trades_df.empty:
        return {'Total PnL': 0, 'Win Rate': 0, 'Profit Factor': 0, 'Sharpe': 0, 
                'Sortino': 0, 'Max Drawdown': 0, 'Trades': 0, 'Avg Trades/Day': 0,
                'Avg Duration (min)': 0, 'Max Duration (min)': 0}
        
    pnl = trades_df['pnl_currency'].sum()
    wr = (trades_df['pnl_points'] > 0).mean() * 100
    
    gross_win = trades_df[trades_df['pnl_currency'] > 0]['pnl_currency'].sum()
    gross_loss = abs(trades_df[trades_df['pnl_currency'] < 0]['pnl_currency'].sum())
    pf = gross_win / gross_loss if gross_loss > 0 else float('inf')
    
    # DD
    dd = 0
    if equity_series is not None and not equity_series.empty:
        peak = equity_series.cummax()
        dd = (peak - equity_series).max()
        
    # Sortino/Sharpe
    sharpe = 0; sortino = 0
    try:
        daily = trades_df.set_index('exit_time')['pnl_currency'].resample('D').sum().fillna(0)
        if len(daily) > 1:
            std = daily.std()
            sharpe = (daily.mean() / std * np.sqrt(252)) if std > 0 else 0
            down_std = daily[daily < 0].std()
            sortino = (daily.mean() / down_std * np.sqrt(252)) if down_std > 0 else 0
    except: pass
        
    # Trades/Day
    tpd = 0
    try:
        days = (trades_df['exit_time'].max() - trades_df['entry_time'].min()).days
        tpd = len(trades_df) / max(1, days)
    except: pass
    
    # Duration
    avg_dur = 0
    max_dur = 0
    try:
        if not pd.api.types.is_datetime64_any_dtype(trades_df['entry_time']):
             trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
        if not pd.api.types.is_datetime64_any_dtype(trades_df['exit_time']):
             trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'])
             
        # Duration in minutes
        durations = (trades_df['exit_time'] - trades_df['entry_time']).dt.total_seconds() / 60
        if not durations.empty:
            avg_dur = durations.mean()
            max_dur = durations.max()
    except: pass

    return {
        'Total PnL': pnl, 'Win Rate': wr, 'Profit Factor': pf, 'Sharpe': sharpe,
        'Sortino': sortino, 'Max Drawdown': dd, 'Trades': len(trades_df), 'Avg Trades/Day': tpd,
        'Avg Duration (min)': avg_dur, 'Max Duration (min)': max_dur,
        'Ret/DD': pnl / dd if dd > 0 else 0
    }

def generate_trade_plot(trade, df, output_dir, version, sol_name=None, parent_filename=None):
    """Generate detailed HTML plot for a single trade."""
    try:
        # Generate filename
        exit_dt = pd.to_datetime(trade.exit_time)
        timestamp = exit_dt.strftime("%Y%m%d_%H%M%S")
        filename = f"trade_report_{timestamp}.html"
        filepath = os.path.join(output_dir, filename)
        
        # Get data segment
        entry_time = pd.to_datetime(trade.entry_time)
        exit_time = pd.to_datetime(trade.exit_time)
        
        # Ensure DF index is datetime
        if not pd.api.types.is_datetime64_any_dtype(df.index):
            df.index = pd.to_datetime(df.index)
            
        candles_before_after = 50
        
        try:
             entry_idx = df.index.get_indexer([entry_time], method='nearest')[0]
             exit_idx = df.index.get_indexer([exit_time], method='nearest')[0]
        except:
             return None
             
        start_loc = max(0, entry_idx - candles_before_after)
        end_loc = min(len(df) - 1, exit_idx + candles_before_after)
        segment = df.iloc[start_loc:end_loc + 1]
        
        # Create subplots
        fig_trade = make_subplots(
            rows=4, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.5, 0.15, 0.15, 0.2],
            subplot_titles=('Price & Donchian Channels', 'ADX / Trend', 'RSI', 'Volume')
        )
        
        # Price
        fig_trade.add_trace(go.Candlestick(
            x=segment.index, open=segment['open'], high=segment['high'],
            low=segment['low'], close=segment['close'], name='Price'
        ), row=1, col=1)
        
        # Donchian Channels
        if 'donchian_high' in segment.columns:
            fig_trade.add_trace(go.Scatter(x=segment.index, y=segment['donchian_high'], line=dict(color='blue', dash='dash', width=1), name='Donchian High'), row=1, col=1)
            fig_trade.add_trace(go.Scatter(x=segment.index, y=segment['donchian_low'], line=dict(color='blue', dash='dash', width=1), name='Donchian Low'), row=1, col=1)
        
        # SMA Regime
        if 'sma_regime' in segment.columns:
            fig_trade.add_trace(go.Scatter(x=segment.index, y=segment['sma_regime'], line=dict(color='gray', width=1), name='SMA Regime'), row=1, col=1)

        # VWAP
        if 'vwap' in segment.columns:
            fig_trade.add_trace(go.Scatter(x=segment.index, y=segment['vwap'], line=dict(color='orange', width=1.5), name='VWAP'), row=1, col=1)
            
        # Markers
        entry_color = 'green' if trade.direction == 1 else 'red'
        exit_color = 'lime' if trade.pnl_currency > 0 else 'darkred'
        
        fig_trade.add_trace(go.Scatter(
            x=[entry_time], y=[trade.entry_price],
            mode='markers+text', marker=dict(symbol='triangle-up', size=15, color=entry_color, line=dict(color='black', width=2)),
            text=['ENTRY'], textposition='top center', name='Entry'
        ), row=1, col=1)
        
        fig_trade.add_trace(go.Scatter(
            x=[exit_time], y=[trade.exit_price],
            mode='markers+text', marker=dict(symbol='triangle-down', size=15, color=exit_color, line=dict(color='black', width=2)),
            text=['EXIT'], textposition='bottom center', name='Exit'
        ), row=1, col=1)
        
        # Trailing stop
        if hasattr(trade, 'stop_history') and isinstance(trade.stop_history, list) and len(trade.stop_history) > 0:
            stop_times, stop_prices = zip(*trade.stop_history)
            stop_times_dt = pd.to_datetime(stop_times)
            fig_trade.add_trace(go.Scatter(x=stop_times_dt, y=list(stop_prices), name='Trailing Stop', line=dict(color='red', width=2, dash='solid'), opacity=0.8), row=1, col=1)
        
        # Take Profit line
        if hasattr(trade, 'tp') and trade.tp is not None and not pd.isna(trade.tp):
            fig_trade.add_trace(go.Scatter(x=[entry_time, exit_time], y=[trade.tp, trade.tp], mode='lines', name='Take Profit', line=dict(color='purple', dash='dot', width=2)), row=1, col=1)
        
        # ADX / Trend Subplot
        if 'adx' in segment.columns:
            fig_trade.add_trace(go.Scatter(x=segment.index, y=segment['adx'], line=dict(color='steelblue', width=1.5), name='ADX'), row=2, col=1)
            fig_trade.add_hline(y=25, line_dash="dash", line_color="rgba(0,0,0,0.2)", row=2, col=1)

        # RSI Subplot
        if 'rsi' in segment.columns:
            fig_trade.add_trace(go.Scatter(x=segment.index, y=segment['rsi'], line=dict(color='purple', width=1.5), name='RSI'), row=3, col=1)
            fig_trade.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
            fig_trade.add_hline(y=30, line_dash="dot", line_color="green", row=3, col=1)
        
        # Volume Subplot
        colors = ['green' if c >= o else 'red' for c, o in zip(segment['close'], segment['open'])]
        fig_trade.add_trace(go.Bar(x=segment.index, y=segment['volume'], name='Volume', marker_color=colors), row=4, col=1)
        
        # Layout
        res_str = "WIN" if trade.pnl_currency > 0 else "LOSS"
        sol_prefix = f"[{sol_name}] " if sol_name else ""
        title = f"{sol_prefix}Trade {trade.Index if hasattr(trade, 'Index') else ''} | {res_str} ${abs(trade.pnl_currency):,.0f} | {trade.reason}"
        fig_trade.update_layout(title=title, height=1000, hovermode='x unified', template='plotly_white')
        
        plotly_div = fig_trade.to_html(full_html=False, include_plotlyjs='cdn')
        back_link = parent_filename if parent_filename else "../dashboard_paper.html"
        back_label = "Back to Dashboard"
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{title}</title>
            <style>
                body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; margin: 0; background: #f8fafc; padding: 20px; }}
                .container {{ max-width: 1400px; margin: 0 auto; background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
                .back-home {{ 
                    display: inline-block; 
                    margin-bottom: 20px; 
                    padding: 8px 16px; 
                    background: #34495e; 
                    color: white; 
                    text-decoration: none; 
                    border-radius: 6px; 
                    font-size: 14px;
                    transition: background 0.2s;
                }}
                .back-home:hover {{ background: #2c3e50; }}
            </style>
        </head>
        <body>
            <div class="container">
                <a href="{back_link}" class="back-home">&larr; {back_label}</a>
                {plotly_div}
            </div>
        </body>
        </html>
        """
        with open(filepath, "w", encoding='utf-8') as f:
            f.write(html)
        return filename
        
    except Exception as e:
        print(f"Error generating plot for trade: {e}")
        return None

def generate_near_miss_plot(near_miss_idx, df, output_dir, version, sol_name=None, parent_filename=None):
    """
    Generate a plot for a rejected breakout (Near-Miss).
    """
    try:
        if df is None or df.empty: return None
        
        # Ensure timestamp
        target_time = pd.to_datetime(near_miss_idx)
        time_slug = target_time.strftime('%Y%m%d_%H%M%S')
        filename = f"near_miss_{time_slug}_{sol_name.replace(' ', '_')}.html"
        filepath = os.path.join(output_dir, filename)
        
        if os.path.exists(filepath): return filename
            
        # Ensure DF index is datetime
        if not pd.api.types.is_datetime64_any_dtype(df.index):
            df.index = pd.to_datetime(df.index)
            
        # Slice data
        try:
            loc = df.index.get_indexer([target_time], method='nearest')[0]
            start_idx = max(0, loc - 30)
            end_idx = min(len(df), loc + 30)
            segment = df.iloc[start_idx:end_idx].copy()
        except:
            return None
            
        # Create plot
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, 
                             vertical_spacing=0.05, row_heights=[0.6, 0.2, 0.2],
                             subplot_titles=('Price & Channels', 'RSI', 'ADX'))
        
        # Candlestick
        fig.add_trace(go.Candlestick(
            x=segment.index, open=segment['open'], high=segment['high'], 
            low=segment['low'], close=segment['close'], name='Price'
        ), row=1, col=1)
        
        # Technicals
        if 'donchian_high' in segment.columns:
            fig.add_trace(go.Scatter(x=segment.index, y=segment['donchian_high'], line=dict(color='blue', dash='dash', width=1), name='D-High'), row=1, col=1)
            fig.add_trace(go.Scatter(x=segment.index, y=segment['donchian_low'], line=dict(color='blue', dash='dash', width=1), name='D-Low'), row=1, col=1)
        
        if 'sma_regime' in segment.columns:
            fig.add_trace(go.Scatter(x=segment.index, y=segment['sma_regime'], line=dict(color='gray', width=1), name='SMA'), row=1, col=1)
            
        # Rejection Line
        fig.add_vline(x=target_time, line_dash="dash", line_color="red")
        
        # Indicators
        if 'rsi' in segment.columns:
            fig.add_trace(go.Scatter(x=segment.index, y=segment['rsi'], name='RSI', line=dict(color='purple', width=1.5)), row=2, col=1)
            fig.add_hline(y=70, line_dash="dot", line_color="red", row=2, col=1)
            fig.add_hline(y=30, line_dash="dot", line_color="green", row=2, col=1)
            
        if 'adx' in segment.columns:
            fig.add_trace(go.Scatter(x=segment.index, y=segment['adx'], name='ADX', line=dict(color='brown', width=1.5)), row=3, col=1)
            
        # Layout
        title = f"Near-Miss Audit: {target_time} | Sol: {sol_name}"
        fig.update_layout(title=title, height=800, template='plotly_white', hovermode='x unified', showlegend=False)
        
        plotly_div = fig.to_html(full_html=False, include_plotlyjs='cdn')
        back_link = parent_filename if parent_filename else "trend_dashboard_v4.1.html"
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{title}</title>
            <style>
                body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; margin:0; background:#f8fafc; padding:20px; }}
                .container {{ max-width: 1400px; margin: 0 auto; background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
                .back-home {{ display: inline-block; margin-bottom: 20px; padding: 8px 16px; background: #34495e; color: white; text-decoration: none; border-radius: 6px; font-size:14px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <a href="{back_link}" class="back-home">&larr; Back to Dashboard</a>
                {plotly_div}
            </div>
        </body>
        </html>
        """
        with open(filepath, "w", encoding='utf-8') as f:
            f.write(html)
        return filename
    except Exception as e:
        print(f"Error generating near-miss plot: {e}")
        return None

def generate_dashboard(solutions_data, output_dir=None, version='5.0', open_browser=True, filename=None):
    """
    Generate Unified HTML Dashboard for Trend Strategy (v5.0 Unified).
    """
    if output_dir is None:
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        output_dir = os.path.join(BASE_DIR, 'web')
    
    os.makedirs(output_dir, exist_ok=True)
    is_multi = len(solutions_data) > 1
    
    # helper colors
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

    for sol in solutions_data:
        if 'stats' not in sol or not sol['stats']:
            sol['stats'] = calculate_stats(sol['trades_df'], sol['equity_curve'])

    # 1. HTML Header
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Trend Strategy V{version} Dashboard</title>
        <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>📊</text></svg>">
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin:0; background:#f4f4f9; color:#333; }}
            .container {{ max-width: 1400px; margin: 20px auto; background:white; padding:30px; border-radius:12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }}
            h1 {{ color: #2c3e50; border-bottom: 2px solid #eee; padding-bottom:10px; }}
            h2 {{ color: #34495e; margin-top: 35px; border-bottom: 1px solid #eee; padding-bottom: 5px; }}
            .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:15px; margin-bottom: 25px; }}
            .metric-box {{ background: #f8f9fa; padding:15px; border-radius:8px; text-align:center; border: 1px solid #e9ecef; transition: transform 0.2s; }}
            .metric-box:hover {{ transform: translateY(-3px); box-shadow: 0 4px 8px rgba(0,0,0,0.1); }}
            .metric-val {{ font-size: 24px; font-weight:bold; color:#2c3e50; }}
            .metric-label {{ font-size: 12px; color:#6c757d; text-transform: uppercase; letter-spacing: 1px; }}
            .metric-sub {{ font-size: 11px; color:#999; margin-top: 5px; }}
            table {{ width:100%; border-collapse:collapse; margin-top:15px; background: white; }}
            th, td {{ padding:12px; text-align:left; border-bottom:1px solid #eee; }}
            th {{ background:#f8f9fa; font-size:12px; font-weight: 600; text-transform: uppercase; }}
            tr:hover {{ background-color: #f8f9fa; }}
            .positive {{ color: #27ae60; }}
            .negative {{ color: #c0392b; }}
            .best {{ color: #27ae60; font-weight: bold; }}
            .chart-container {{ margin: 25px 0; border: 1px solid #eee; border-radius:8px; background: white; padding: 10px; }}
            .action-log-container {{ margin-top: 30px; background: #fff5f5; padding: 20px; border-radius: 8px; border: 1px solid #feb2b2; }}
            .reason-tag {{ display: inline-block; background: #fed7d7; color: #9b2c2c; padding: 2px 6px; border-radius: 4px; margin: 2px; font-size: 11px; }}
            .sol-tag {{ font-size: 10px; background: #eee; padding: 2px 6px; border-radius: 4px; color: #555; font-weight: bold; }}
            .back-home {{ display: inline-block; margin-bottom: 20px; padding: 10px 20px; background: #34495e; color: white; text-decoration: none; border-radius: 6px; font-weight: 600; transition: background 0.2s; }}
            .back-home:hover {{ background: #2c3e50; }}
            .trade-list {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 15px; margin-top: 15px; }}
            .trade-card {{ border: 1px solid #e9ecef; padding: 15px; border-radius: 8px; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
            .btn {{ display: inline-block; padding: 6px 12px; background: #3498db; color: white; text-decoration: none; border-radius: 4px; font-size: 11px; margin-top: 10px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <a href="index.html" class="back-home">&larr; Back to Home</a>
            <h1>Trend Strategy V{version} Dashboard</h1>
    """

    # 2. Key Summary Metrics (Multi-Solution Ready)
    html_content += '<div class="metrics-grid">'
    summary_metrics = [
        ('Total PnL', 'Total PnL', True),
        ('Win Rate', 'Win Rate', True),
        ('Profit Factor', 'Profit Factor', True),
        ('Max Drawdown', 'Max Drawdown', False)
    ]
    
    for label, key, higher_better in summary_metrics:
        values = [(s['stats'][key], s['name']) for s in solutions_data]
        if higher_better: best_val, best_name = max(values, key=lambda x: x[0])
        else: best_val, best_name = min(values, key=lambda x: x[0])
        
        fmt = f"${best_val:,.0f}" if 'PnL' in key or 'Drawdown' in key else f"{best_val:.1f}%" if 'Win' in key else f"{best_val:.2f}"
        cls = 'positive' if (higher_better and best_val > 0) or (not higher_better and key != 'Max Drawdown') else 'negative'
        if key == 'Max Drawdown': cls = 'negative'
        
        sub_text = best_name if is_multi else ""
        html_content += f"""
            <div class="metric-box">
                <div class="metric-label">{label}</div>
                <div class="metric-val {cls}">{fmt}</div>
                <div class="metric-sub">{sub_text}</div>
            </div>
        """
    html_content += '</div>'

    # 3. Performance Comparison Table
    html_content += "<h2>Performance Comparison</h2>"
    metrics_list = ['Total PnL', 'Win Rate', 'Profit Factor', 'Max Drawdown', 'Ret/DD', 'Sortino', 'Trades', 'Avg Trades/Day']
    html_content += "<table><tr><th>Metric</th>" + "".join(f"<th>{s['name']}</th>" for s in solutions_data) + "</tr>"
    for m in metrics_list:
        html_content += f"<tr><td>{m}</td>"
        vals = [s['stats'].get(m, 0) for s in solutions_data]
        best_val = min(vals) if m == 'Max Drawdown' else max(vals)
        for s in solutions_data:
            val = s['stats'].get(m, 0)
            style = 'class="best"' if val == best_val and is_multi else ""
            fmt = f"${val:,.0f}" if 'PnL' in m or 'Drawdown' in m else f"{val:.1f}%" if 'Win' in m else f"{val:.2f}"
            html_content += f"<td {style}>{fmt}</td>"
        html_content += "</tr>"
    html_content += "</table>"

    # 4. Equity Curve Comparison
    fig_eq = go.Figure()
    for idx, sol in enumerate(solutions_data):
        eq = sol['equity_curve']
        if not eq.empty:
            if len(eq) > 5000: eq = eq.iloc[::len(eq)//5000]
            fig_eq.add_trace(go.Scatter(x=eq.index, y=eq.values, name=sol['name'], line=dict(color=colors[idx % len(colors)])))
    fig_eq.update_layout(title="Equity Curve Comparison", height=500, template='plotly_white', legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    html_content += f'<div class="chart-container">{fig_eq.to_html(full_html=False, include_plotlyjs="cdn")}</div>'

    # 5. Advanced Analysis Plots (Risk Radar & Monthly)
    html_content += "<h2>Advanced Analytics</h2>"
    fig_adv = make_subplots(
        rows=2, cols=2,
        subplot_titles=('Strategy Profile (Radar)', 'Monthly PnL', 'Day of Week Performance', 'Underwater Plot'),
        specs=[[{'type': 'polar'}, {'type': 'xy'}], [{'type': 'xy'}, {'type': 'xy'}]],
        vertical_spacing=0.15
    )
    
    radar_metrics = ['Win Rate', 'Profit Factor', 'Sortino', 'Ret/DD']
    norm_ranges = {m: (min([s['stats'].get(m,0) for s in solutions_data]), max([s['stats'].get(m,0) for s in solutions_data])) for m in radar_metrics}
    
    for idx, sol in enumerate(solutions_data):
        color = colors[idx % len(colors)]
        # Radar
        r_vals = []
        for m in radar_metrics:
            vmin, vmax = norm_ranges[m]
            div = (vmax - vmin) if (vmax - vmin) != 0 else 1
            r_vals.append((sol['stats'].get(m,0) - vmin) / div)
        fig_adv.add_trace(go.Scatterpolar(r=r_vals, theta=radar_metrics, name=sol['name'], fill='toself', line_color=color, opacity=0.4), row=1, col=1)
        
        # Monthly PnL
        tdf = sol['trades_df']
        if not tdf.empty:
            if not pd.api.types.is_datetime64_any_dtype(tdf['exit_time']): tdf['exit_time'] = pd.to_datetime(tdf['exit_time'])
            m_stats = tdf.groupby(tdf['exit_time'].dt.to_period('M'))['pnl_currency'].sum()
            fig_adv.add_trace(go.Bar(x=m_stats.index.astype(str), y=m_stats.values, name=sol['name'], marker_color=color, showlegend=False), row=1, col=2)
            
            # DoW
            if not pd.api.types.is_datetime64_any_dtype(tdf['entry_time']): tdf['entry_time'] = pd.to_datetime(tdf['entry_time'])
            tdf['dow'] = tdf['entry_time'].dt.day_name()
            dow_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
            dow_stats = tdf.groupby('dow')['pnl_currency'].sum().reindex(dow_order)
            fig_adv.add_trace(go.Bar(x=dow_stats.index, y=dow_stats.values, name=sol['name'], marker_color=color, showlegend=False), row=2, col=1)
            
            # Underwater
            eq = sol['equity_curve']
            peak = eq.cummax()
            dd = eq - peak
            if len(dd) > 2000: dd = dd.iloc[::len(dd)//2000]
            fig_adv.add_trace(go.Scatter(x=dd.index, y=dd.values, name=sol['name'], fill='tozeroy', line_color=color, showlegend=False), row=2, col=2)

    fig_adv.update_layout(height=900, template='plotly_white', barmode='group')
    html_content += f'<div class="chart-container">{fig_adv.to_html(full_html=False, include_plotlyjs="cdn")}</div>'

    # 6. Action Log (Near-Miss Rejections)
    if any(sol.get('action_log') for sol in solutions_data):
        html_content += '<div class="action-log-container"><h2>Action Log (Rejection Audit)</h2>'
        for sol in solutions_data:
            log = sol.get('action_log', [])
            if log:
                html_content += f"<h3>{sol['name']} Recent Activity</h3>"
                html_content += "<table><tr><th>Timestamp</th><th>Direction</th><th>Rejection Reasons</th><th>Audit</th></tr>"
                for entry in log[-15:]:
                    reasons_html = "".join(f'<span class="reason-tag">{r}</span>' for r in entry['reasons'])
                    audit_link = ""
                    if entry.get('type') == 'Breakout Rejected':
                        plot_file = generate_near_miss_plot(entry['timestamp'], sol.get('df'), output_dir, version, sol_name=sol['name'], parent_filename=filename)
                        if plot_file: audit_link = f'<a href="{plot_file}" target="_blank">View Chart</a>'
                    html_content += f"<tr><td>{entry['timestamp']}</td><td>{entry['direction']}</td><td>{reasons_html}</td><td>{audit_link}</td></tr>"
                html_content += "</table>"
        html_content += '</div>'

    # 7. Recent Trades (Labeled by Solution)
    html_content += "<h2>Recent Executed Trades</h2><table><tr><th>Solution</th><th>Time</th><th>Side</th><th>PnL</th><th>Reason</th><th>Chart</th></tr>"
    all_trades_list = []
    for sol in solutions_data:
        tdf = sol['trades_df'].tail(20).copy()
        tdf['sol_label'] = sol['name']
        tdf['raw_df'] = [sol.get('df')] * len(tdf)
        all_trades_list.append(tdf)
    if all_trades_list:
        combined_trades = pd.concat(all_trades_list).sort_values('exit_time', ascending=False).head(40)
        for t in combined_trades.itertuples():
            plot_file = generate_trade_plot(t, t.raw_df, output_dir, version, sol_name=t.sol_label, parent_filename=filename)
            chart_btn = f'<a href="{plot_file}" target="_blank">View</a>' if plot_file else "-"
            pnl_cls = 'positive' if t.pnl_currency > 0 else 'negative'
            html_content += f"""
                <tr>
                    <td><span class="sol-tag">{t.sol_label}</span></td>
                    <td>{t.exit_time}</td>
                    <td>{'LONG' if t.direction==1 else 'SHORT'}</td>
                    <td class="{pnl_cls}">${t.pnl_currency:,.0f}</td>
                    <td>{t.reason}</td>
                    <td>{chart_btn}</td>
                </tr>
            """
    html_content += "</table></div></body></html>"

    if filename is None: filename = f'trend_dashboard_v{version}.html'
    path = os.path.join(output_dir, filename)
    with open(path, 'w', encoding='utf-8') as f: f.write(html_content)
    print(f"Dashboard saved to {path}")
    if open_browser:
        try: webbrowser.open(f'file://{os.path.abspath(path)}')
        except: pass
    return path

    if filename is None:
        filename = f'trend_dashboard_v{version}.html'
    path = os.path.join(output_dir, filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"Dashboard saved to {path}")
    if open_browser:
        try: webbrowser.open(f'file://{os.path.abspath(path)}')
        except: pass
    return path

"""
Reporting and Dashboard Generation
==================================
Handles generation of HTML dashboards, trade plots, and performance metrics.
Ported from BB_Strategy_v3.py for modularity in v4.
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
        'Entry Criteria': ['Enable Long Trades', 'Enable Short Trades', 'Bollinger Band Length', 
                          'Bollinger Band StdDev', 'Long Entry on Wick Touch', 'Long Entry on Body in Zone',
                          'Long Trigger (% From Lower Band)', 'Short Entry on Wick Touch', 
                          'Short Entry on Body in Zone', 'Short Trigger (% From Upper Band)'],
        'Exit Criteria': ['Profit Target (Multiplier)', 'TP Method', 'Stop Loss (Multiplier)', 
                         'Use Trailing Stop', 'Trailing Stop Activation (Multiplier)', 'Trailing Stop Distance (Multiplier)',
                         'Use Time-Based Exit', 'Max Trade Duration (Bars)', 'Exit on Band Touch', 'Band Touch Exit StdDev'],
        'Risk Management': ['Initial Capital', 'Position Sizing (% of Equity)', 'Max Open Trades', 
                           'Max Daily Drawdown (%)', 'Strategy Max Drawdown (%)'],
        'Filters': ['Use RTH Only', 'RTH Start Hour', 'RTH End Hour', 
                   'Use Volume Filter', 'Min Volume (Percentile)', 'Volume MAPeriod',
                   'Use ATR Filter', 'Min Volatility (ATR)', 'ATR Period',
                   'Use Trend Filter', 'Trend EMA Period', 'Trend Filter Type'],
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
                'Sortino': 0, 'Max Drawdown': 0, 'Trades': 0, 'Avg Trades/Day': 0}
        
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
        'Avg Duration (min)': avg_dur, 'Max Duration (min)': max_dur
    }

def generate_dashboard(solutions_data, output_dir=None, version='4.0', open_browser=True):
    """
    Generate Unified HTML Dashboard.
    """
    if output_dir is None:
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(BASE_DIR, 'web')
    
    os.makedirs(output_dir, exist_ok=True)
    
    is_multi = len(solutions_data) > 1
    
    # Ensure stats are calculated
    for sol in solutions_data:
        if 'stats' not in sol or not sol['stats']:
            sol['stats'] = calculate_stats(sol['trades_df'], sol['equity_curve'])

    # === 1. HTML Header ===
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>BB Strategy V{version} Dashboard</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; background: #f4f4f9; color: #333; }}
            .container {{ max-width: 1400px; margin: 20px auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }}
            h1 {{ color: #2c3e50; font-size: 28px; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
            h2 {{ color: #34495e; margin-top: 30px; font-size: 22px; }}
            h3 {{ color: #7f8c8d; font-size: 18px; }}
            
            /* Metric Boxes */
            .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 25px; }}
            .metric-box {{ background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center; border: 1px solid #e9ecef; transition: transform 0.2s; }}
            .metric-box:hover {{ transform: translateY(-3px); box-shadow: 0 4px 8px rgba(0,0,0,0.1); }}
            .metric-val {{ font-size: 24px; font-weight: bold; color: #2c3e50; margin: 5px 0; }}
            .metric-label {{ font-size: 13px; color: #6c757d; text-transform: uppercase; letter-spacing: 1px; }}
            .metric-sub {{ font-size: 12px; color: #999; margin-top: 5px; }}
            
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; background: white; }}
            th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #eee; }}
            th {{ background-color: #f8f9fa; color: #495057; font-weight: 600; text-transform: uppercase; font-size: 12px; }}
            tr:hover {{ background-color: #f8f9fa; }}
            
            .positive {{ color: #27ae60; }}
            .negative {{ color: #c0392b; }}
            .highlight {{ background-color: #fff3cd; font-weight: bold; }} /* Diff Highlight */
            .best {{ color: #27ae60; font-weight: bold; }}
            
            .trade-list {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px; max-height: 800px; overflow-y: auto; }}
            .trade-card {{ border: 1px solid #e9ecef; padding: 15px; border-radius: 8px; background: white; position: relative; }}
            .trade-card:hover {{ border-color: #ced4da; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }}
            .btn {{ display: inline-block; padding: 6px 12px; background: #3498db; color: white; text-decoration: none; border-radius: 4px; font-size: 12px; margin-top: 10px; }}
            .btn:hover {{ background: #2980b9; }}
            .sol-tag {{ position: absolute; top: 10px; right: 10px; font-size: 10px; background: #eee; padding: 2px 6px; border-radius: 4px; color: #555; }}
            
            .chart-container {{ margin: 20px 0; border: 1px solid #eee; border-radius: 8px; overflow: hidden; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>BB Strategy V{version} Report</h1>
    """

    # === 2. Top-Level Metric Boxes (Summary) ===
    # If Multi: Show BEST values across solutions
    # If Single: Show that solution's values
    
    html_content += '<div class="metrics-grid">'
    
    summary_metrics = [
        ('Total PnL', 'Total PnL', True), # Name, Key, HigherBetter
        ('Win Rate', 'Win Rate', True),
        ('Profit Factor', 'Profit Factor', True),
        ('Sortino', 'Sortino', True),
        ('Max Drawdown', 'Max Drawdown', False)
    ]
    
    for label, key, higher_better in summary_metrics:
        # Collect values
        values = [(s['stats'][key], s['name']) for s in solutions_data]
        
        if higher_better:
            best_val, best_name = max(values, key=lambda x: x[0])
        else:
            best_val, best_name = min(values, key=lambda x: x[0])
            
        # Format
        if 'PnL' in key or 'Drawdown' in key: fmt = f"${best_val:,.2f}"
        elif 'Rate' in key: fmt = f"{best_val:.1f}%"
        else: fmt = f"{best_val:.2f}"
        
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

    # === 3. Detailed Performance Table ===
    html_content += "<h2>Performance Comparison</h2>"
    metrics_list = ['Total PnL', 'Win Rate', 'Profit Factor', 'Sharpe', 'Sortino', 'Max Drawdown', 'Trades', 'Avg Trades/Day', 'Avg Duration (min)', 'Max Duration (min)']
    
    html_content += "<table><tr><th>Metric</th>" + "".join(f"<th>{s['name']}</th>" for s in solutions_data) + "</tr>"
    
    for m in metrics_list:
        html_content += f"<tr><td>{m}</td>"
        values = [s['stats'][m] for s in solutions_data]
        if not values: continue
        
        best_val = min(values) if m == 'Max Drawdown' else max(values)
        
        for s in solutions_data:
            val = s['stats'][m]
            style = 'class="best"' if val == best_val and len(values) > 1 else ""
            
            if 'PnL' in m or 'Drawdown' in m: fmt = f"${val:,.2f}"
            elif 'Rate' in m: fmt = f"{val:.1f}%"
            elif 'Duration' in m: fmt = f"{val:.0f}m"
            elif 'Trades' in m and 'Day' not in m: fmt = f"{val}"
            else: fmt = f"{val:.2f}"
                
            html_content += f"<td {style}>{fmt}</td>"
        html_content += "</tr>"
    html_content += "</table>"
    
    # === 4. Exit Reason Analysis (Restored) ===
    html_content += "<h2>Exit Analysis</h2>"
    
    # Gather reasons
    reasons = set()
    for s in solutions_data:
        if not s['trades_df'].empty and 'reason' in s['trades_df'].columns:
            reasons.update(s['trades_df']['reason'].unique())
            
    if reasons:
        sorted_reasons = sorted(list(reasons))
        html_content += "<table><tr><th>Exit Reason</th>" + "".join(f"<th>{s['name']}</th>" for s in solutions_data) + "</tr>"
        
        for reason in sorted_reasons:
             html_content += f"<tr><td>{reason}</td>"
             for s in solutions_data:
                 tdf = s['trades_df']
                 count = 0
                 if not tdf.empty and 'reason' in tdf.columns:
                     count = len(tdf[tdf['reason'] == reason])
                 html_content += f"<td>{count}</td>"
             html_content += "</tr>"
        html_content += "</table>"
    else:
        html_content += "<p>No exit reason data available.</p>"

    # === 5. Monthly Statistics (Combined) ===
    html_content += "<h2>Monthly Performance</h2>"
    
    all_months = set()
    monthly_data = {} 
    
    for i, sol in enumerate(solutions_data):
        tdf = sol['trades_df']
        if not tdf.empty:
            try:
                # Ensure datetime
                if not pd.api.types.is_datetime64_any_dtype(tdf['exit_time']):
                    tdf['exit_time'] = pd.to_datetime(tdf['exit_time'])
                    
                m_stats = tdf.groupby(tdf['exit_time'].dt.to_period('M')).agg({
                    'pnl_currency': 'sum',
                    'exit_time': 'count'
                })
                m_stats.index = m_stats.index.astype(str)
                
                for month, row in m_stats.iterrows():
                    all_months.add(month)
                    if month not in monthly_data: monthly_data[month] = {}
                    monthly_data[month][i] = {
                        'pnl': row['pnl_currency'],
                        'count': row['exit_time']
                    }
            except Exception as e:
                print(f"Error calc monthly for {sol['name']}: {e}")

    if all_months:
        sorted_months = sorted(list(all_months), reverse=True)
        html_content += "<table><tr><th>Month</th>"
        for s in solutions_data:
            html_content += f"<th>{s['name']} PnL</th><th>Trades</th>"
        html_content += "</tr>"
        
        for month in sorted_months:
            html_content += f"<tr><td>{month}</td>"
            for i, sol in enumerate(solutions_data):
                data = monthly_data.get(month, {}).get(i, {'pnl': 0, 'count': 0})
                pnl = data['pnl']
                count = data['count']
                
                cls = 'positive' if pnl > 0 else 'negative'
                fmt_pnl = f"${pnl:,.0f}" if pnl != 0 else "-"
                
                html_content += f"<td class='{cls}'>{fmt_pnl}</td><td>{count}</td>"
            html_content += "</tr>"
        html_content += "</table>"
    else:
        html_content += "<p>No monthly data available.</p>"

    # === 4. Analysis Charts (Restored from v3) ===
    html_content += "<h2>Detailed Analysis</h2>"
    
    # Prepare Subplots
    fig_analysis = make_subplots(
        rows=3, cols=2,
        subplot_titles=('Monthly PnL', 'Monthly Win Rate', 'Hourly Performance', 
                       'Day of Week Performance', 'PnL Distribution', 'Exit Reasons'),
        vertical_spacing=0.12,
        horizontal_spacing=0.1
    )
    
    # helper colors
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']
    
    # 1. Monthly PnL & 2. Win Rate
    # Reuse `monthly_data` computed above? No, computed earlier was for table string.
    # Let's re-compute properly for plotting
    
    for idx, sol in enumerate(solutions_data):
        color = colors[idx % len(colors)]
        tdf = sol['trades_df']
        if tdf.empty: continue
        
        # Ensure DateTime
        if not pd.api.types.is_datetime64_any_dtype(tdf['exit_time']):
             tdf['exit_time'] = pd.to_datetime(tdf['exit_time'])
        if not pd.api.types.is_datetime64_any_dtype(tdf['entry_time']):
             tdf['entry_time'] = pd.to_datetime(tdf['entry_time'])
             
        # Monthly Stats
        m_stats = tdf.groupby(tdf['exit_time'].dt.to_period('M')).agg({
            'pnl_currency': 'sum',
            'exit_time': 'count'
        })
        m_stats['wins'] = tdf[tdf['pnl_currency'] > 0].groupby(tdf['exit_time'].dt.to_period('M'))['exit_time'].count()
        m_stats['win_rate'] = (m_stats['wins'].fillna(0) / m_stats['exit_time']) * 100
        
        x_str = m_stats.index.astype(str).tolist()
        
        # Trace 1: Monthly PnL
        fig_analysis.add_trace(go.Bar(
            x=x_str, y=m_stats['pnl_currency'], name=f"{sol['name']} PnL",
            marker_color=color, showlegend=True, legendgroup=sol['name']
        ), row=1, col=1)
        
        # Trace 2: Win Rate
        fig_analysis.add_trace(go.Bar(
            x=x_str, y=m_stats['win_rate'], name=f"{sol['name']} WR%",
            marker_color=color, showlegend=False, legendgroup=sol['name'],
            opacity=0.6
        ), row=1, col=2)
        
        # 3. Hourly Performance
        tdf['hour'] = tdf['entry_time'].dt.hour
        h_stats = tdf.groupby('hour')['pnl_currency'].sum()
        fig_analysis.add_trace(go.Bar(
            x=h_stats.index, y=h_stats.values, name=f"{sol['name']} Hourly",
            marker_color=color, showlegend=False, legendgroup=sol['name']
        ), row=2, col=1)

        # 4. Day of Week
        tdf['dow'] = tdf['entry_time'].dt.day_name()
        # Order: Mon-Fri
        dow_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
        dow_stats = tdf.groupby('dow')['pnl_currency'].sum().reindex(dow_order)
        fig_analysis.add_trace(go.Bar(
            x=dow_stats.index, y=dow_stats.values, name=f"{sol['name']} DoW",
            marker_color=color, showlegend=False, legendgroup=sol['name']
        ), row=2, col=2)
        
        # 5. PnL Distribution (Histogram / Box)
        # Using Box for comparison cleanliness
        fig_analysis.add_trace(go.Box(
            y=tdf['pnl_currency'], name=sol['name'],
            marker_color=color, showlegend=False, legendgroup=sol['name']
        ), row=3, col=1)
        
        # 6. Exit Reasons
        if 'reason' in tdf.columns:
            reasons = tdf['reason'].value_counts()
            fig_analysis.add_trace(go.Bar(
                x=reasons.index, y=reasons.values, name=f"{sol['name']} Exits",
                marker_color=color, showlegend=False, legendgroup=sol['name']
            ), row=3, col=2)

    fig_analysis.update_layout(height=1000, template='plotly_white', barmode='group', title_text="Analysis Charts")
    analysis_html = fig_analysis.to_html(include_plotlyjs='cdn', full_html=False)
    html_content += f'<div class="chart-container">{analysis_html}</div>'

    analysis_html = fig_analysis.to_html(include_plotlyjs='cdn', full_html=False)
    html_content += f'<div class="chart-container">{analysis_html}</div>'

    # === 5. Advanced Risk Analysis (New) ===
    html_content += "<h2>Advanced Risk Analysis</h2>"
    
    # Grid for Risk Charts
    fig_risk = make_subplots(
        rows=2, cols=2,
        subplot_titles=('Strategy Profile (Radar)', 'Rolling 30-Day Sharpe', 
                       'PnL Correlation', 'Underwater Plot (Drawdown)'),
        specs=[[{'type': 'polar'}, {'type': 'xy'}], 
               [{'type': 'xy'}, {'type': 'xy'}]],
        vertical_spacing=0.15,
        horizontal_spacing=0.1
    )
    
    # 1. Radar Chart
    # Normalize metrics: PnL, Win Rate, Profit Factor, Sortino, Return/DD
    radar_metrics = ['Total PnL', 'Win Rate', 'Profit Factor', 'Sortino']
    # Add Return/DD manually
    for sol in solutions_data:
        pnl = sol['stats']['Total PnL']
        dd = abs(sol['stats']['Max Drawdown'])
        sol['stats']['Ret/DD'] = pnl / dd if dd > 0 else 0
    radar_metrics.append('Ret/DD')
    
    # Find min/max for normalization
    norm_ranges = {}
    for m in radar_metrics:
        vals = [s['stats'].get(m, 0) for s in solutions_data]
        norm_ranges[m] = (min(vals), max(vals))
        
    for idx, sol in enumerate(solutions_data):
        color = colors[idx % len(colors)]
        # Calc normalized scores
        r_vals = []
        for m in radar_metrics:
            vmin, vmax = norm_ranges[m]
            val = sol['stats'].get(m, 0)
            if vmax - vmin == 0: score = 1
            else: score = (val - vmin) / (vmax - vmin)
            r_vals.append(score)
            
        # Close the loop
        r_vals_closed = r_vals + [r_vals[0]]
        theta_closed = radar_metrics + [radar_metrics[0]]
        
        fig_risk.add_trace(go.Scatterpolar(
            r=r_vals, theta=radar_metrics, name=sol['name'],
            fill='toself', line_color=color, opacity=0.6,
            hovertext=[f"{m}: {sol['stats'][m]:.2f}" for m in radar_metrics]
        ), row=1, col=1)

    # 2. Rolling Sharpe
    for idx, sol in enumerate(solutions_data):
        color = colors[idx % len(colors)]
        tdf = sol['trades_df']
        if tdf.empty: continue
        
        daily = tdf.set_index('exit_time')['pnl_currency'].resample('D').sum().fillna(0)
        # Apply 30-day rolling
        rolling_mean = daily.rolling(window=30).mean()
        rolling_std = daily.rolling(window=30).std()
        rolling_sharpe = (rolling_mean / rolling_std * np.sqrt(252)).fillna(0)
        
        fig_risk.add_trace(go.Scatter(
            x=rolling_sharpe.index, y=rolling_sharpe.values, name=f"{sol['name']} Sharpe",
            line=dict(color=color), showlegend=False
        ), row=1, col=2)
        
    # 3. Correlation Matrix
    if len(solutions_data) > 1:
        # Build common daily PnL frame
        corr_data = {}
        for sol in solutions_data:
            tdf = sol['trades_df']
            if tdf.empty: continue
            corr_data[sol['name']] = tdf.set_index('exit_time')['pnl_currency'].resample('D').sum()
            
        corr_df = pd.DataFrame(corr_data).fillna(0)
        if not corr_df.empty:
            corr_matrix = corr_df.corr()
            
            fig_risk.add_trace(go.Heatmap(
                z=corr_matrix.values,
                x=corr_matrix.columns,
                y=corr_matrix.index,
                colorscale='Viridis',
                zmin=-1, zmax=1,
                text=np.around(corr_matrix.values, 2),
                texttemplate="%{text}",
                showscale=True
            ), row=2, col=1)
    else:
        # Dummy annotation for single solution
        fig_risk.add_annotation(
            text="Correlation N/A (Single Solution)",
            xref="x3", yref="y3",
            x=0.5, y=0.5, showarrow=False,
            row=2, col=1
        )

    # 4. Underwater Plot
    for idx, sol in enumerate(solutions_data):
        color = colors[idx % len(colors)]
        eq = sol['equity_curve']
        if eq.empty: continue
        
        peak = eq.cummax()
        dd = eq - peak # Dollar Drawdown
        
        if len(dd) > 5000: dd = dd.iloc[::len(dd)//5000]
        
        fig_risk.add_trace(go.Scatter(
            x=dd.index, y=dd.values, name=f"{sol['name']} DD",
            fill='tozeroy', line=dict(color=color, width=0),
            showlegend=False
        ), row=2, col=2)

    fig_risk.update_layout(height=1000, template='plotly_white', title_text="Advanced Risk Analysis")
    risk_html = fig_risk.to_html(include_plotlyjs='cdn', full_html=False)
    html_content += f'<div class="chart-container">{risk_html}</div>'

    # === 6. Charts (Unified) ===
    html_content += "<h2>Equity Curve & Analysis</h2>"
    
    fig = go.Figure()
    for sol in solutions_data:
        eq = sol['equity_curve']
        if not eq.empty:
            if len(eq) > 5000: eq = eq.iloc[::len(eq)//5000]
            fig.add_trace(go.Scatter(x=eq.index, y=eq.values, name=sol['name'], mode='lines'))
    fig.update_layout(height=600, title='Equity Curve Comparison', template='plotly_white')
    chart_html = fig.to_html(include_plotlyjs='cdn', full_html=False)
    html_content += f'<div class="chart-container">{chart_html}</div>'

    if not is_multi:
        sol = solutions_data[0]
        df = sol.get('df')
        if df is not None:
             html_content += "<h3>Detailed Analysis</h3>"
             if len(df) > 3000: df = df.iloc[::len(df)//3000]
             
             fig_det = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.5, 0.25, 0.25], 
                                subplot_titles=('Price & Strategies', 'Equity', 'Drawdown'))
             
             fig_det.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'), row=1, col=1)
             if 'upper' in df.columns:
                 fig_det.add_trace(go.Scatter(x=df.index, y=df['upper'], line=dict(color='blue', dash='dash', width=1), name='Upper BB'), row=1, col=1)
                 fig_det.add_trace(go.Scatter(x=df.index, y=df['lower'], line=dict(color='blue', dash='dash', width=1), name='Lower BB'), row=1, col=1)
             
             eq = sol['equity_curve']
             if not eq.empty:
                 if len(eq) > 3000: eq = eq.iloc[::len(eq)//3000]
                 fig_det.add_trace(go.Scatter(x=eq.index, y=eq.values, name='Equity', line=dict(color='green')), row=2, col=1)
                 peak = eq.cummax()
                 dd = peak - eq
                 fig_det.add_trace(go.Scatter(x=eq.index, y=dd.values, name='Drawdown', line=dict(color='red'), fill='tozeroy'), row=3, col=1)
                 
             fig_det.update_layout(height=1000, template='plotly_white', showlegend=True)
             chart_det_html = fig_det.to_html(include_plotlyjs='cdn', full_html=False)
             html_content += f'<div class="chart-container">{chart_det_html}</div>'

    # === 7. Recent Trades ===
    html_content += "<h2>Recent Trades</h2><div class='trade-list'>"
    
    all_trades = []
    for sol in solutions_data:
        t_df = sol['trades_df']
        if not t_df.empty:
            tail = t_df.tail(20).copy() 
            tail['sol_name'] = sol['name']
            all_trades.append(tail)
            
    if all_trades:
        combined_df = pd.concat(all_trades).sort_values('exit_time', ascending=False)
        display_df = combined_df.head(50) 
        
        for i, trade in enumerate(display_df.itertuples()):
            pnl = trade.pnl_currency
            cls = 'positive' if pnl > 0 else 'negative'
            res = 'Win' if pnl > 0 else 'Loss'
            
            # Duration str
            dur_str = ""
            try:
                entry = pd.to_datetime(trade.entry_time)
                exit_t = pd.to_datetime(trade.exit_time)
                diff = exit_t - entry
                mins = int(diff.total_seconds() / 60)
                if mins >= 60:
                     hrs = mins // 60
                     mns = mins % 60
                     dur_str = f"{hrs}h {mns}m"
                else:
                     dur_str = f"{mins}m"
            except: pass

            html_content += f"""
            <div class="trade-card" style="border-left: 5px solid {'#27ae60' if pnl>0 else '#c0392b'}">
                <span class="sol-tag">{trade.sol_name}</span>
                <h3>{res} <span class="{cls}">${abs(pnl):,.0f}</span></h3>
                <p style="margin: 5px 0 0; color: #666; font-size: 13px;">{trade.exit_time}</p>
                <p style="margin: 5px 0 0; font-size: 14px;"><strong>{trade.direction}</strong> | {trade.reason} | ⏱️ {dur_str}</p>
            </div>
            """
    else:
        html_content += "<p>No trades found.</p>"
    html_content += "</div>"

    # === 8. Parameters (Show ALL, Highlight Diffs) ===
    html_content += "<h2>Parameters</h2>"
    
    all_keys = set()
    for sol in solutions_data: all_keys.update(sol['params'].keys())
    
    sorted_keys = sorted(list(all_keys))
    
    if sorted_keys:
        html_content += "<table><tr><th>Parameter</th>" + "".join(f"<th>{s['name']}</th>" for s in solutions_data) + "</tr>"
        
        for k in sorted_keys:
            # Skip internal keys
            if str(k).startswith('__') or str(k).startswith('==='): continue
            
            vals = [s['params'].get(k, {}).get('value') if isinstance(s['params'].get(k), dict) else s['params'].get(k) for s in solutions_data]
            
            # Check for difference
            unique_vals = set(str(v) for v in vals)
            row_cls = 'highlight' if len(unique_vals) > 1 and is_multi else ''
            
            html_content += f"<tr class='{row_cls}'><td>{k}</td>"
            for s in solutions_data:
                val = s['params'].get(k, {}).get('value') if isinstance(s['params'].get(k), dict) else s['params'].get(k)
                html_content += f"<td>{val}</td>"
            html_content += "</tr>"
        html_content += "</table>"
    else:
        html_content += "<p>No parameters found.</p>"

    html_content += "</div></body></html>"
    
    # Save
    filename = f'comprehensive_dashboard_v{version}.html'
    path = os.path.join(output_dir, filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html_content)
        
    print(f"Dashboard saved to: {path}")
    if open_browser:
        try: webbrowser.open(f'file://{os.path.abspath(path)}')
        except: pass

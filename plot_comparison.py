import json
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
import glob
from datetime import timedelta


# Define paths
LIVE_DATA_PATH = "c:/Trading/paper_logs/live_data.csv"

def load_ohlc_data(csv_path):
    """Load OHLC data for context plotting."""
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path, on_bad_lines='skip')
        df.rename(columns={
            'datetime': 'Time', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close',
            'upper': 'Upper', 'lower': 'Lower'
        }, inplace=True)
        df['Time'] = pd.to_datetime(df['Time'], utc=True).dt.tz_convert('US/Eastern').dt.tz_localize(None)
        df.set_index('Time', inplace=True)
        return df
    except Exception as e:
        print(f"Error loading OHLC {csv_path}: {e}")
        return None

def generate_aggregate_plots(df):
    """Generate Aggregate performance comparison plots."""
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=('Cumulative PnL (Live vs BT)', 'PnL Difference Distribution', 
                       'Time Lag (Live - BT)', 'PnL Comparison Scatter'),
        vertical_spacing=0.15
    )
    
    # Sort by time
    df = df.sort_values('SortTime')
    
    # 1. Cumulative PnL
    live_pnl = df['Live PnL'].fillna(0).cumsum()
    bt_pnl = df['BT PnL'].fillna(0).cumsum()
    
    fig.add_trace(go.Scatter(x=df['SortTime'], y=live_pnl, name='Live Cum PnL', line=dict(color='green')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['SortTime'], y=bt_pnl, name='BT Cum PnL', line=dict(color='blue', dash='dash')), row=1, col=1)
    
    # 2. PnL Diff Hist
    pnl_diff = df['PnL Diff'].dropna()
    fig.add_trace(go.Histogram(x=pnl_diff, name='PnL Diff', marker_color='orange'), row=1, col=2)
    
    # 3. Lag Scatter
    fig.add_trace(go.Scatter(
        x=df['SortTime'], y=df['Diff (s)'], 
        mode='markers', name='Time Lag (s)', marker=dict(color='purple', size=6)
    ), row=2, col=1)
    
    # 4. PnL Scatter (Correlation)
    fig.add_trace(go.Scatter(
        x=df['BT PnL'], y=df['Live PnL'],
        mode='markers', name='PnL Correlation', 
        marker=dict(color='teal', size=8),
        text=df['SortTime']
    ), row=2, col=2)
    # Add 1:1 line
    min_val = min(df['BT PnL'].min(), df['Live PnL'].min())
    max_val = max(df['BT PnL'].max(), df['Live PnL'].max())
    fig.add_trace(go.Scatter(
        x=[min_val, max_val], y=[min_val, max_val],
        mode='lines', name='Perfect Match', line=dict(color='gray', dash='dot')
    ), row=2, col=2)

    fig.update_layout(height=800, template='plotly_white', title_text="Aggregate Comparison Metrics")
    
    # Enable Range Slider and Selector on the X-Axis of the 1st subplot (Cum PnL)
    # And link the X-axis of the 3rd subplot (Lag) to it.
    
    # Note: 'x' is R1C1, 'x3' is R2C1.
    fig.update_xaxes(matches='x') # Link all x-axes? No, R1C2 and R2C2 are not time. 
    # Actually, simpler to just set rangeslider on the layout's xaxis, and ensure x3 matches x.
    
    fig.update_xaxes(matches='x', row=2, col=1) # Make Lag plot match Cum PnL plot
    
    fig.update_layout(
        xaxis=dict(
            rangeselector=dict(
                buttons=list([
                    dict(count=1, label="1h", step="hour", stepmode="backward"),
                    dict(count=4, label="4h", step="hour", stepmode="backward"),
                    dict(count=1, label="1d", step="day", stepmode="backward"),
                    dict(count=7, label="1w", step="day", stepmode="backward"),
                    dict(step="all")
                ])
            ),
            rangeslider=dict(visible=True),
            type="date"
        )
    )
    return fig

def generate_overlay_chart(trade_row, ohlc_df, output_dir):
    """Generate individual trade chart with overlay."""
    try:
        if ohlc_df is None: return None
        
        # Center time
        center_time = trade_row['Live Time'] if pd.notna(trade_row['Live Time']) else trade_row['BT Time']
        if pd.isna(center_time): return None
        
        start_t = center_time - timedelta(minutes=45)
        end_t = center_time + timedelta(minutes=45)
        
        mask = (ohlc_df.index >= start_t) & (ohlc_df.index <= end_t)
        sub_df = ohlc_df.loc[mask]
        
        if sub_df.empty: return None
        
        fig = go.Figure()
        
        # Candles
        fig.add_trace(go.Candlestick(
            x=sub_df.index,
            open=sub_df['Open'], high=sub_df['High'],
            low=sub_df['Low'], close=sub_df['Close'],
            name='Price'
        ))
        
        # Bollinger Bands
        if 'Upper' in sub_df.columns and 'Lower' in sub_df.columns:
            fig.add_trace(go.Scatter(
                x=sub_df.index, y=sub_df['Upper'], 
                line=dict(color='blue', dash='dash', width=1), 
                name='Upper BB', opacity=0.5
            ))
            fig.add_trace(go.Scatter(
                x=sub_df.index, y=sub_df['Lower'], 
                line=dict(color='blue', dash='dash', width=1), 
                name='Lower BB', opacity=0.5
            ))
            
        # Parse Backtest Stops/TP (Model Reference)
        bt_tp = trade_row.get('BT TP')
        if pd.notna(bt_tp):
             fig.add_trace(go.Scatter(
                x=[sub_df.index[0], sub_df.index[-1]], 
                y=[bt_tp, bt_tp],
                mode='lines',
                line=dict(color='purple', dash='dot', width=1),
                name='Model TP'
            ))
            
        bt_stop_hist_str = trade_row.get('BT Stop Hist')
        if isinstance(bt_stop_hist_str, str) and bt_stop_hist_str:
            try:
                stop_hist = json.loads(bt_stop_hist_str)
                if stop_hist:
                    # Extract times and prices
                    st_times = [pd.to_datetime(x[0]) for x in stop_hist]
                    st_prices = [x[1] for x in stop_hist]
                    
                    # Flatten step line
                    # For accurate visual, we might want to extend the stop line to the exit
                    
                    fig.add_trace(go.Scatter(
                        x=st_times, y=st_prices,
                        mode='lines',
                        line=dict(color='red', width=1.5),
                        name='Model Stop (Dyn)'
                    ))
            except:
                pass


        # Live Trade
        if pd.notna(trade_row['Live Time']):
            live_is_long = trade_row.get('Live Dir') in [1, 'LONG', 'Long', 'long']
            color = 'green' if live_is_long else 'red'
            # Entry
            fig.add_trace(go.Scatter(
                x=[trade_row['Live Time']], y=[trade_row['Live Price']],
                mode='markers',
                marker=dict(symbol='triangle-up' if live_is_long else 'triangle-down', size=15, color=color, line=dict(width=2, color='black')),
                name='LIVE Entry'
            ))
            # Exit
            if 'Live Exit Time' in trade_row and pd.notna(trade_row['Live Exit Time']):
                 fig.add_trace(go.Scatter(
                    x=[trade_row['Live Exit Time']], y=[trade_row['Live Exit Price']],
                    mode='markers',
                    marker=dict(symbol='x', size=12, color=color, line=dict(width=2, color='black')),
                    name='LIVE Exit'
                ))
                # Duration Line
                 fig.add_trace(go.Scatter(
                    x=[trade_row['Live Time'], trade_row['Live Exit Time']], 
                    y=[trade_row['Live Price'], trade_row['Live Exit Price']],
                    mode='lines',
                    line=dict(color=color, width=2),
                    name='LIVE Duration'
                ))

        # BT Trade
        if pd.notna(trade_row['BT Time']):
            bt_is_long = trade_row.get('BT Dir') in [1, 'LONG', 'Long', 'long']
            color = 'lime' if bt_is_long else 'magenta'
            # Entry
            fig.add_trace(go.Scatter(
                x=[trade_row['BT Time']], y=[trade_row['BT Price']],
                mode='markers',
                marker=dict(symbol='circle-open', size=15, color=color, line=dict(width=3)),
                name='BT Entry'
            ))
            # Exit
            if 'BT Exit Time' in trade_row and pd.notna(trade_row['BT Exit Time']):
                 fig.add_trace(go.Scatter(
                    x=[trade_row['BT Exit Time']], y=[trade_row['BT Exit Price']],
                    mode='markers',
                    marker=dict(symbol='circle-x-open', size=12, color=color, line=dict(width=3)),
                    name='BT Exit'
                ))
                # Duration Line
                 fig.add_trace(go.Scatter(
                    x=[trade_row['BT Time'], trade_row['BT Exit Time']], 
                    y=[trade_row['BT Price'], trade_row['BT Exit Price']],
                    mode='lines',
                    line=dict(color=color, width=2, dash='dot'),
                    name='BT Duration'
                ))
            
        title = f"Trade Comparison | Status: {trade_row['Status']} | Diff: {trade_row.get('Diff (s)', 'N/A')}s"
        fig.update_layout(
            title=title, 
            height=500, 
            template='plotly_white',
            yaxis=dict(fixedrange=False, autorange=True),
            xaxis=dict(rangeslider=dict(visible=False))
        )
        
        filename = f"overlay_{center_time.strftime('%Y%m%d_%H%M%S')}.html"
        filepath = os.path.join(output_dir, filename)
        
        # Stats Preparation
        def get_dir_str(d):
            if pd.isna(d) or d == "": return "-"
            if isinstance(d, str):
                return d.upper()
            return "LONG" if d == 1 else "SHORT"
            
        def get_dir_class(d):
            if pd.isna(d) or d == "": return ""
            d_str = str(d).upper()
            if d_str == "LONG" or d == 1: return "long"
            if d_str == "SHORT" or d == -1: return "short"
            return ""

        stats_html = f"""
        <div class="stats-box">
            <h3>Trade Comparison Details</h3>
            <table>
                <tr>
                    <th>Metric</th>
                    <th>Live / Paper</th>
                    <th>Backtest (Model)</th>
                </tr>
                <tr>
                    <td><b>Direction</b></td>
                    <td class="{get_dir_class(trade_row.get('Live Dir'))}">{get_dir_str(trade_row.get('Live Dir'))}</td>
                    <td class="{get_dir_class(trade_row.get('BT Dir'))}">{get_dir_str(trade_row.get('BT Dir'))}</td>
                </tr>
                <tr>
                    <td><b>Entry Time</b></td>
                    <td>{trade_row['Live Time'].strftime('%H:%M:%S') if pd.notna(trade_row.get('Live Time')) else '-'}</td>
                    <td>{trade_row['BT Time'].strftime('%H:%M:%S') if pd.notna(trade_row.get('BT Time')) else '-'}</td>
                </tr>
                <tr>
                    <td><b>Entry Price</b></td>
                    <td>{f"{trade_row.get('Live Price', 0):.2f}" if pd.notna(trade_row.get('Live Price')) else '-'}</td>
                    <td>{f"{trade_row.get('BT Price', 0):.2f}" if pd.notna(trade_row.get('BT Price')) else '-'}</td>
                </tr>
                <tr>
                    <td><b>Exit Price</b></td>
                    <td>{f"{trade_row.get('Live Exit Price', 0):.2f}" if pd.notna(trade_row.get('Live Exit Price')) else '-'}</td>
                    <td>{f"{trade_row.get('BT Exit Price', 0):.2f}" if pd.notna(trade_row.get('BT Exit Price')) else '-'}</td>
                </tr>
                <tr>
                    <td><b>PnL</b></td>
                    <td class="{'pnl-pos' if trade_row.get('Live PnL', 0) > 0 else 'pnl-neg' if trade_row.get('Live PnL', 0) < 0 else ''}">${f"{trade_row.get('Live PnL', 0):.2f}" if pd.notna(trade_row.get('Live PnL')) else '-'}</td>
                    <td class="{'pnl-pos' if trade_row.get('BT PnL', 0) > 0 else 'pnl-neg' if trade_row.get('BT PnL', 0) < 0 else ''}">${f"{trade_row.get('BT PnL', 0):.2f}" if pd.notna(trade_row.get('BT PnL')) else '-'}</td>
                </tr>
                <tr>
                    <td><b>Duration</b></td>
                    <td>{str(trade_row.get('Live Dur', '-')).split('.')[0]}</td>
                    <td>{str(trade_row.get('BT Dur', '-')).split('.')[0]}</td>
                </tr>
                <tr>
                    <td><b>Sync Lag</b></td>
                    <td colspan="2" style="text-align:center; background:#f8f9fa;">{f"{trade_row.get('Diff (s)', 0):.1f}s" if pd.notna(trade_row.get('Diff (s)')) else 'N/A'}</td>
                </tr>
            </table>
        </div>
        """

        # Wrapped in template for "Back to Gallery" button and Stats
        plotly_div = fig.to_html(full_html=False, include_plotlyjs='cdn', config={'scrollZoom': True})
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
                .stats-box {{ margin-bottom: 20px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; background: #fff; }}
                .stats-box h3 {{ margin-top: 0; color: #1e293b; font-size: 1.1rem; border-bottom: 2px solid #f1f5f9; padding-bottom: 10px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
                th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #f1f5f9; }}
                th {{ color: #64748b; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; }}
                .long {{ color: #059669; font-weight: bold; }}
                .short {{ color: #dc2626; font-weight: bold; }}
                .pnl-pos {{ color: #059669; }}
                .pnl-neg {{ color: #dc2626; }}
            </style>
        </head>
        <body>
            <div class="container">
                <a href="index.html" class="back-home">&larr; Back to Gallery</a>
                {stats_html}
                {plotly_div}
            </div>
        </body>
        </html>
        """
        with open(filepath, "w", encoding='utf-8') as f:
            f.write(html)
        return filename
        
    except Exception as e:
        print(f"Error plotting overlay: {e}")
        return None

def generate_comparison_charts(csv_path="comparison_metrics_sequential.csv", output_dir="web/comparison_charts", data_path=LIVE_DATA_PATH):
    """
    Reads comparison metrics and generates overlay charts for unmatched/matched trades.
    """
    if not os.path.exists(csv_path):
         print(f"Metrics file not found: {csv_path}")
         return
         
    os.makedirs(output_dir, exist_ok=True)
    df = pd.read_csv(csv_path)
    
    # Parse Timestamps
    df['SortTime'] = pd.to_datetime(df['SortTime'])
    if 'Live Time' in df.columns: df['Live Time'] = pd.to_datetime(df['Live Time'])
    if 'BT Time' in df.columns: df['BT Time'] = pd.to_datetime(df['BT Time'])
    
    # Load OHLC
    ohlc_df = load_ohlc_data(data_path)
    
    # Generate Aggregate Plots
    agg_fig = generate_aggregate_plots(df)
    agg_filename = "aggregate_metrics.html"
    agg_fig.write_html(os.path.join(output_dir, agg_filename), include_plotlyjs='cdn')

    # Helpers for table rendering
    def get_dir_str(d):
        if pd.isna(d) or d == "": return "-"
        if isinstance(d, str): return d.upper()
        return "LONG" if d == 1 else "SHORT"
        
    def get_dir_class(d):
        if pd.isna(d) or d == "": return ""
        d_str = str(d).upper()
        if d_str == "LONG" or d == 1: return "long"
        if d_str == "SHORT" or d == -1: return "short"
        return ""

    # HTML Header
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Trade Comparison Gallery</title>
        <style>
            body { font-family: 'Segoe UI', sans-serif; padding: 20px; background: #f0f2f5; max-width: 1600px; margin: 0 auto; }
            h1, h2 { color: #333; }
            .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(400px, 1fr)); gap: 20px; }
            .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); border: 1px solid #ddd; }
            .match { border-top: 5px solid #2ecc71; }
            .mismatch { border-top: 5px solid #e74c3c; }
            .only { border-top: 5px solid #f39c12; }
            table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.9rem; }
            th, td { padding: 8px; border-bottom: 1px solid #eee; text-align: left; }
            th { background: #f8f9fa; color: #666; }
            .btn { display: inline-block; padding: 5px 10px; background: #3498db; color: white; text-decoration: none; border-radius: 4px; margin-top: 10px; font-size: 0.8rem;}
            .btn:hover { background: #2980b9; }
            iframe { width: 100%; height: 600px; border: none; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); background: white; }
            .back-home { 
                display: inline-block; 
                margin-bottom: 20px; 
                padding: 8px 16px; 
                background: #34495e; 
                color: white; 
                text-decoration: none; 
                border-radius: 6px; 
                font-size: 14px;
                transition: background 0.2s;
            }
            .back-home:hover { background: #2c3e50; }
            .long { color: #059669; font-weight: bold; }
            .short { color: #dc2626; font-weight: bold; }
        </style>
    </head>
    <body>
        <a href="../index.html" class="back-home">&larr; Back to Home</a>
        <h1>Live vs Backtest Comparison Analysis</h1>
        <p>Generated: """ + pd.Timestamp.now().strftime('%Y-%m-%d %H:%M') + """</p>
        
        <h2>Global Metrics</h2>
        <iframe src="aggregate_metrics.html"></iframe>
        
        <h2>Trade Detail Gallery (Last 100 Trades)</h2>
        <div class="grid">
    """
    
    # Sort descending time
    df_rev = df.sort_values('SortTime', ascending=False).head(100)
    
    for _, row in df_rev.iterrows():
        status = row['Status']
        cls = 'match' if status == 'MATCHED' else 'mismatch' if 'MISMATCH' in status else 'only'
        
        # Generate Overlay Plot
        plot_link = ""
        overlay_file = generate_overlay_chart(row, ohlc_df, output_dir)
        if overlay_file:
            plot_link = f'<a href="{overlay_file}" class="btn">View Chart Overlay</a>'

        live_t_str = row['Live Time'].strftime('%H:%M:%S') if pd.notna(row['Live Time']) else '-'
        bt_t_str = row['BT Time'].strftime('%H:%M:%S') if pd.notna(row['BT Time']) else '-'
        diff_str = f"{row.get('Diff (s)', 0):.1f}s" if pd.notna(row.get('Diff (s)')) else '-'
        
        # Determine overall direction for the row (favor Live, fallback to BT)
        dir_val = row.get('Live Dir') if pd.notna(row.get('Live Dir')) else row.get('BT Dir')
        dir_label = get_dir_str(dir_val)
        dir_class = get_dir_class(dir_val)
        
        html_content += f"""
        <div class="card {cls}">
            <h3>{status} <span style="float:right; font-size:0.8em; color:#888">{row['SortTime'].strftime('%Y-%m-%d')}</span></h3>
            <table>
                <tr>
                    <th>Metric</th><th>Live</th><th>Backtest</th>
                </tr>
                <tr>
                    <td>Direction</td><td class="{dir_class}">{dir_label}</td><td class="{get_dir_class(row.get('BT Dir'))}">{get_dir_str(row.get('BT Dir'))}</td>
                </tr>
                <tr>
                    <td>Time</td><td>{live_t_str}</td><td>{bt_t_str}</td>
                </tr>
                <tr>
                    <td>Lag</td><td colspan="2" style="text-align:center">{diff_str}</td>
                </tr>
                <tr>
                    <td>Price</td><td>{row.get('Live Price', '-')}</td><td>{row.get('BT Price', '-')}</td>
                </tr>
                <tr>
                    <td>PnL</td><td>{row.get('Live PnL', '-')}</td><td>{row.get('BT PnL', '-')}</td>
                </tr>
                <tr>
                    <td>Duration</td><td>{str(row.get('Live Dur', '-')).split('.')[0]}</td><td>{str(row.get('BT Dur', '-')).split('.')[0]}</td>
                </tr>
            </table>
            {plot_link}
        </div>
        """
        
    html_content += "</div></body></html>"
    
    with open(os.path.join(output_dir, "index.html"), "w", encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"Comparison gallery generated at {output_dir}/index.html")

if __name__ == "__main__":
    generate_comparison_charts()

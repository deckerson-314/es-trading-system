
import os
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import pytz
from typing import List, Dict, Any, Optional

EASTERN = pytz.timezone('US/Eastern')

# Constants
WEB_DIR = "web"
WEB_DASHBOARD = os.path.join(WEB_DIR, "dashboard.html")

@dataclass
class DashboardState:
    """Holds the complete state required to render the dashboard."""
    mode: str = "PAPER"
    port: int = 7497
    contract_symbol: str = "N/A"
    
    connection_start_time: Optional[datetime] = None
    total_uptime_seconds: float = 0.0
    is_connected: bool = False
    
    # Account & Market Data
    account_info: Dict[str, Any] = field(default_factory=dict)
    positions: List[Dict[str, Any]] = field(default_factory=list)
    active_orders: List[Dict[str, Any]] = field(default_factory=list)
    completed_trades: List[Dict[str, Any]] = field(default_factory=list)
    
    current_price: float = 0.0
    last_data_receipt_time: Optional[datetime] = None
    
    # Statistics
    dashboard_stats: Dict[str, Any] = field(default_factory=lambda: {
        'reconnections': 0, 
        'trades_opened': 0, 
        'trades_closed': 0,
        'orders_placed': 0, 
        'orders_filled': 0, 
        'orders_cancelled': 0,
        'last_update': None
    })
    
    # Logs
    error_log: List[Dict[str, Any]] = field(default_factory=list)
    live_tracker: List[Dict[str, Any]] = field(default_factory=list)
    bar_log: List[Dict[str, Any]] = field(default_factory=list)
    
    # Parameters
    params: Dict[str, Any] = field(default_factory=dict)

def format_duration(seconds):
    """Format seconds into HH:MM:SS string."""
    if not seconds:
        return "00:00:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def group_params_for_display(params_dict):
    """
    Group parameters into logical categories for the dashboard.
    Falls back to 'Other' for unrecognized parameters.
    """
    groups = {
        'Strategy Config': ['Strategy Name', 'Timeframe', 'Symbol', 'Exchange', 'Currency'],
        'Entry Criteria': ['Enable Long Trades', 'Enable Short Trades', 
                           'Bollinger Band Length', 'Bollinger Band StdDev',
                           'RSI Period', 'RSI Overbought', 'RSI Oversold',
                           'Use RSI Filter', 'Use VWAP Filter',
                           'Trend Filter Method', 'Trend EMA Length',
                           'ADX Period', 'ADX Threshold', 'Use ADX Filter'],
        'Exit Criteria': ['Take Profit Method', 'Stop Loss Method',
                          'Target Profit (%)', 'Stop Loss (%)',
                          'Trailing Stop (%)', 'Breakeven Trigger (%)',
                          'Time Exit (Bars)', 'EOD Exit Time'],
        'Risk Management': ['Position Size (Contracts)', 'Max Drawdown (%)', 
                            'Max Daily Loss ($)', 'Max Daily Profit ($)',
                            'Max Open Positions'],
        'Session Times': ['RTH Start', 'RTH End', 'Liquid Hours Start', 'Liquid Hours End']
    }
    
    grouped = {}
    used_keys = set()
    
    for group_name, keys in groups.items():
        grouped[group_name] = {}
        for key in keys:
            # Flexible matching (case-insensitive and partial match)
            for param_name, param_data in params_dict.items():
                if param_name not in used_keys:
                    # Exact match
                    if key.lower() == param_name.lower():
                        grouped[group_name][param_name] = param_data
                        used_keys.add(param_name)
                    # Or key is contained in param_name (e.g. "RSI" in "RSI Period")
                    # but be careful not to grab everything
    
    # Add 'Other' category for remaining
    other_params = {k: v for k, v in params_dict.items() if k not in used_keys}
    if other_params:
        grouped['Other'] = other_params
        
    return grouped

def generate_dashboard_html(state: DashboardState) -> str:
    """Generate the live trading dashboard HTML from state."""
    
    # Calculate uptime
    current_uptime = 0
    now_eastern = datetime.now(EASTERN)
    if state.connection_start_time and state.is_connected:
        # Convert state.connection_start_time to offset-aware if it's naive
        start_time = state.connection_start_time
        if start_time.tzinfo is None:
            start_time = EASTERN.localize(start_time)
        current_uptime = (now_eastern - start_time).total_seconds()
    total_uptime = state.total_uptime_seconds + current_uptime
    
    # Status
    # Ensure last_data_receipt_time is offset-aware for comparison
    last_receipt = state.last_data_receipt_time
    if last_receipt and last_receipt.tzinfo is None:
        last_receipt = EASTERN.localize(last_receipt)
        
    time_since_data = (now_eastern - last_receipt).total_seconds() if last_receipt else 0
    is_stale = time_since_data > 60
    
    status_class = "disconnected" if not state.is_connected else "stale" if is_stale else "online"
    status_text = "CONNECTION: OFFLINE" if not state.is_connected else "DATA: STALE (60s+)" if is_stale else "CONNECTION: ONLINE"
    
    # Choose icon based on mode
    icon_emoji = "📈" if state.mode.upper() == "LIVE" else "🧪"
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>IB {state.mode.capitalize()} Dashboard</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>{icon_emoji}</text></svg>">
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="5">
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 20px; background: #eaeff2; color: #333; }}
        .container {{ max-width: 1600px; margin: 0 auto; background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
        h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 15px; margin-top: 0; font-weight: 600; }}
        h2 {{ color: #34495e; margin-top: 35px; border-bottom: 2px solid #ecf0f1; padding-bottom: 8px; font-weight: 500; }}
        h3 {{ color: #7f8c8d; margin-top: 20px; font-size: 1.1em; }}
        
        /* Status Bar */
        .status-bar {{ color: white; padding: 15px 20px; border-radius: 8px; margin: 20px 0; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .status-bar.online {{ background: #2ecc71 !important; box-shadow: 0 2px 4px rgba(46, 204, 113, 0.2) !important; }}
        .status-bar.disconnected {{ background: #e74c3c !important; box-shadow: 0 2px 4px rgba(231, 76, 60, 0.2) !important; }}
        .status-bar.stale {{ background: #f39c12 !important; box-shadow: 0 2px 4px rgba(243, 156, 18, 0.4) !important; }}
        
        /* Metrics */
        .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; margin: 25px 0; }}
        .metric-box {{ background: #f8f9fa; border-left: 5px solid #3498db; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); transition: transform 0.2s; }}
        .metric-box:hover {{ transform: translateY(-2px); }}
        .metric-box .label {{ font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.5px; color: #7f8c8d; margin-bottom: 8px; font-weight: 600; }}
        .metric-box .value {{ font-size: 1.8em; font-weight: 700; color: #2c3e50; }}
        
        /* Tables */
        table {{ width: 100%; border-collapse: separate; border-spacing: 0; margin: 20px 0; width: 100%; border: 1px solid #e1e8ed; border-radius: 8px; overflow: hidden; }}
        th {{ background: #f8f9fa; color: #555; padding: 12px 15px; text-align: left; font-weight: 600; border-bottom: 2px solid #e1e8ed; text-transform: uppercase; font-size: 0.85em; letter-spacing: 0.5px; }}
        td {{ padding: 12px 15px; border-bottom: 1px solid #eee; color: #444; }}
        tr:last-child td {{ border-bottom: none; }}
        tr:hover {{ background-color: #f8f9fa; }}
        
        /* Colors */
        .positive {{ color: #27ae60; font-weight: 600; }}
        .negative {{ color: #c0392b; font-weight: 600; }}
        .neutral {{ color: #7f8c8d; }}
        
        /* Logs */
        .log-container {{ max-height: 400px; overflow-y: auto; background: #fff; padding: 0; border-radius: 8px; border: 1px solid #e1e8ed; font-family: 'Consolas', monospace; font-size: 0.9em; }}
        .log-entry {{ padding: 8px 15px; border-bottom: 1px solid #f0f0f0; display: flex; align-items: flex-start; }}
        .log-entry:last-child {{ border-bottom: none; }}
        .log-timestamp {{ color: #95a5a6; margin-right: 15px; white-space: nowrap; }}
        .log-type {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 0.85em; margin-right: 10px; font-weight: bold; width: 60px; text-align: center; }}
        
        .log-type.INFO {{ background: #e3f2fd; color: #1976d2; }}
        .log-type.WARNING {{ background: #fff3e0; color: #f57c00; }}
        .log-type.ERROR {{ background: #ffebee; color: #c62828; }}
        .log-type.TRADE {{ background: #e8f5e9; color: #2e7d32; }}
        
        .report-link {{
            text-decoration: none;
            background: #3498db;
            color: white;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.85em;
            font-weight: 600;
            display: inline-block;
            transition: background 0.2s;
        }}
        .report-link:hover {{
            background: #2980b9;
            color: white;
        }}
        
        /* Parameters */
        .params-section {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 20px; }}
        .params-group {{ background: white; border: 1px solid #e1e8ed; border-radius: 8px; padding: 0; overflow: hidden; }}
        .params-group h3 {{ background: #f8f9fa; margin: 0; padding: 10px 15px; border-bottom: 1px solid #e1e8ed; font-size: 1em; color: #333; }}
        .params-table {{ margin: 0; border: none; }}
        .params-table td {{ padding: 8px 15px; border-bottom: 1px solid #f0f0f0; }}
        .params-table td:first-child {{ color: #666; font-weight: 500; width: 60%; }}
        .params-table td:last-child {{ font-family: 'Consolas', monospace; color: #333; }}
        
        .return-button {{ display: inline-block; margin-bottom: 20px; padding: 8px 16px; background: #fff; color: #3498db; border: 1px solid #3498db; text-decoration: none; border-radius: 20px; font-weight: 600; font-size: 0.9em; transition: all 0.2s; }}
        .return-button:hover {{ background: #3498db; color: white; }}
        
        /* Stale Warning */
        .stale-warning {{ display: none; background: #f1c40f; color: #000; text-align: center; padding: 10px; font-weight: bold; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .stale-data .stale-warning {{ display: block; }}
        .stale-data .status-bar {{ background: #95a5a6 !important; opacity: 0.8; }}
    </style>
</head>
<body>
    <div class="container">
        <a href="index.html" class="return-button">← Back to Index</a>
        
        <div class="stale-warning">⚠️ WARNING: THIS DASHBOARD IS SHOWING STALE DATA (BOT MAY BE OFFLINE)</div>

        <div class="status-bar {status_class}">
            <div>
                <strong style="font-size: 1.2em;">{status_text}</strong>
                <span style="opacity: 0.8; margin-left: 10px;">[{state.mode.upper()}]</span>
                {f'<span style="margin-left: 20px; opacity: 0.9;">Last Data: {state.last_data_receipt_time.strftime("%H:%M:%S")} ({int(time_since_data)}s ago)</span>' if state.last_data_receipt_time else ""}
            </div>
            <div style="text-align: right; font-size: 0.9em;">
                <div>Uptime: {format_duration(total_uptime)}</div>
                <div id="last-update" data-timestamp="{now_eastern.isoformat()}" style="display:none"></div>
                <div id="last-data-receipt" data-timestamp="{last_receipt.isoformat() if last_receipt else ''}" style="display:none"></div>
                <div>Last Update: {now_eastern.strftime('%Y-%m-%d %H:%M:%S')}</div>
            </div>
        </div>

        <h1>{state.contract_symbol} Trading Dashboard</h1>

        <div class="metric-grid">
            <div class="metric-box">
                <div class="label">Net Liquidation</div>
                <div class="value">${state.account_info.get('NetLiquidation', 0) or 0:,.2f}</div>
            </div>
            <div class="metric-box">
                <div class="label">Unrealized PNL</div>
                <div class="value {'positive' if (state.account_info.get('UnrealizedPNL') or 0) >= 0 else 'negative'}">
                    ${state.account_info.get('UnrealizedPNL') or 0:,.2f}
                </div>
            </div>
            <div class="metric-box">
                <div class="label">Realized PNL</div>
                <div class="value {'positive' if (state.account_info.get('RealizedPNL') or 0) >= 0 else 'negative'}">
                    ${state.account_info.get('RealizedPNL') or 0:,.2f}
                </div>
            </div>
            <div class="metric-box">
                <div class="label">Current Price</div>
                <div class="value">${state.current_price:,.2f}</div>
            </div>
        </div>
        
        <h2>Active Positions</h2>
"""
    if state.positions:
        html += """        <table>
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Pos</th>
                    <th>Avg Price</th>
                    <th>Mkt Price</th>
                    <th>Mkt Value</th>
                    <th>Unrealized PnL</th>
                    <th>Realized PnL</th>
                </tr>
            </thead>
            <tbody>
"""
        for pos in state.positions:
            unrealized = pos.get('unrealizedPNL', 0)
            realized = pos.get('realizedPNL', 0)
            pnl_class = 'positive' if unrealized >= 0 else 'negative'
            
            html += f"""                <tr>
                    <td>{pos.get('symbol', 'N/A')}</td>
                    <td>{pos.get('position', 0)}</td>
                    <td>${pos.get('avgCost', 0):,.2f}</td>
                    <td>${state.current_price:,.2f}</td>
                    <td>${pos.get('marketValue', 0):,.2f}</td>
                    <td class="{pnl_class}">${unrealized:,.2f}</td>
                    <td>${realized:,.2f}</td>
                </tr>
"""
        html += """            </tbody>
        </table>
"""
    else:
        html += """        <div style="padding: 20px; text-align: center; color: #7f8c8d; background: #f8f9fa; border-radius: 8px;">No active positions</div>"""

    html += """
        <h2>Active Orders</h2>
"""
    if state.active_orders:
        html += """        <table>
            <thead>
                <tr>
                    <th>Check</th>
                    <th>Order ID</th>
                    <th>Type</th>
                    <th>Action</th>
                    <th>Size</th>
                    <th>Lmt Price</th>
                    <th>Aux Price</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
"""
        for order in state.active_orders:
            html += f"""                <tr>
                    <td><input type="checkbox" disabled></td>
                    <td>{order.get('orderId')}</td>
                    <td>{order.get('orderType')}</td>
                    <td>{order.get('action')}</td>
                    <td>{order.get('totalQuantity')}</td>
                    <td>{f"${order.get('lmtPrice'):.2f}" if order.get('lmtPrice') else '-'}</td>
                    <td>{f"${order.get('auxPrice'):.2f}" if order.get('auxPrice') else '-'}</td>
                    <td><span class="log-type INFO" style="width: auto; padding: 2px 8px;">{order.get('status')}</span></td>
                </tr>
"""
        html += """            </tbody>
        </table>
"""
    else:
        html += """        <div style="padding: 20px; text-align: center; color: #7f8c8d; background: #f8f9fa; border-radius: 8px;">No active orders</div>"""

    # === BAR LOG SECTION ===
    html += """
        <h2>Bar Log (Last 20 Aggregated Bars)</h2>
"""
    if state.bar_log:
        html += """        <div class="log-container" style="max-height: 300px;">
"""
        for bar in reversed(state.bar_log[-20:]):
            criteria = bar.get('entry_criteria', '')
            bar_info = bar.get('bar_info', '')
            html += f"""            <div class="log-entry" style="flex-direction: column;">
                <div style="font-weight: 600; color: #2c3e50;">{bar.get('timestamp', '')} - {bar_info}</div>
                <div style="color: #555; font-size: 0.85em; margin-top: 4px;">{criteria}</div>
            </div>
"""
        html += """        </div>
"""
    else:
        html += """        <div style="padding: 20px; text-align: center; color: #7f8c8d; background: #f8f9fa; border-radius: 8px;">No bar data yet</div>"""

    # === COMPLETED TRADES SECTION ===
    html += """
        <h2>Completed Trades</h2>
"""
    if state.completed_trades:
        html += """        <table>
            <thead>
                <tr>
                    <th>Exit Time</th>
                    <th>Direction</th>
                    <th>Entry</th>
                    <th>Exit</th>
                    <th>PnL</th>
                    <th>R-Multiple</th>
                    <th>Duration</th>
                    <th>Reason</th>
                    <th>Report</th>
                </tr>
            </thead>
            <tbody>
"""
        for trade in reversed(state.completed_trades[-20:]):
            pnl = trade.get('pnl', 0)
            r_mult = trade.get('r_multiple', 0)
            pnl_class = 'positive' if pnl > 0 else 'negative' if pnl < 0 else ''
            r_class = 'positive' if r_mult > 0 else 'negative' if r_mult < 0 else ''
            
            exit_time = trade.get('exit_time', '')
            if hasattr(exit_time, 'strftime'):
                exit_time = exit_time.strftime('%Y-%m-%d %H:%M:%S')
            
            direction = trade.get('direction', 'N/A')
            dir_emoji = '🟢' if direction == 'LONG' else '🔴' if direction == 'SHORT' else ''
            
            html += f"""                <tr>
                    <td>{exit_time}</td>
                    <td>{dir_emoji} {direction}</td>
                    <td>${trade.get('entry_price', 0):,.2f}</td>
                    <td>${trade.get('exit_price', 0):,.2f}</td>
                    <td class="{pnl_class}">${pnl:,.2f}</td>
                    <td class="{r_class}" title="Risk: ${trade.get('initial_risk', 0):,.2f}">{r_mult:+.2f}R</td>
                    <td>{trade.get('duration', 'N/A')}</td>
                    <td><span class="log-type {'TRADE' if trade.get('reason') == 'TP' else 'WARNING' if trade.get('reason') == 'Stop' else 'INFO'}" style="width: auto; padding: 2px 8px;">{trade.get('reason', 'N/A')}</span></td>
                    <td>
                        {f'<a href="{trade.get("report_url")}" target="_blank" class="report-link">📊 View</a>' if trade.get('report_url') else '<span style="color:#bdc3c7">N/A</span>'}
                    </td>
                </tr>
"""
        html += """            </tbody>
        </table>
"""
    else:
        html += """        <div style="padding: 20px; text-align: center; color: #7f8c8d; background: #f8f9fa; border-radius: 8px;">No completed trades</div>"""

    html += """
        <h2>System Logs</h2>
        <div class="log-container">
"""
    # Combine live tracker and error log, sort by timestamp
    all_logs = []
    
    for entry in state.live_tracker:
        all_logs.append({
            'timestamp': entry.get('timestamp', ''),
            'type': entry.get('type', 'INFO').upper(),
            'message': entry.get('message', '')
        })
        
    for entry in state.error_log:
        all_logs.append({
            'timestamp': entry.get('timestamp', ''),
            'type': 'ERROR',
            'message': entry.get('error', str(entry))
        })
        
    # Sort by timestamp descending (newest first)
    all_logs.sort(key=lambda x: x['timestamp'], reverse=True)
    
    for log in all_logs[:100]: # Show last 100
        html += f"""            <div class="log-entry">
                <span class="log-timestamp">{log['timestamp']}</span>
                <span class="log-type {log['type']}">{log['type']}</span>
                <span class="log-message">{log['message']}</span>
            </div>
"""
            
    html += """        </div>

        <h2>Strategy Parameters</h2>
        <div class="params-section">
"""
    
    grouped_params = group_params_for_display(state.params)
    for group_name, params in grouped_params.items():
        if not params: continue
        
        html += f"""            <div class="params-group">
                <h3>{group_name}</h3>
                <table class="params-table">
"""
        for name, data in params.items():
            val = data if not isinstance(data, dict) else data.get('value', data)
            # Basic formatting
            if isinstance(val, bool):
                val_str = "True" if val else "False"
            elif isinstance(val, float):
                val_str = f"{val:.4f}"
            else:
                val_str = str(val)
                
            html += f"""                    <tr>
                        <td>{name}</td>
                        <td>{val_str}</td>
                    </tr>
"""
        html += """                </table>
            </div>
"""

    html += """        </div>
    </div>
    
    <script>
        function checkStaleData() {
            const lastUpdateElem = document.getElementById('last-update');
            const lastDataElem = document.getElementById('last-data-receipt');
            const warningElem = document.querySelector('.stale-warning');
            if (!lastUpdateElem || !lastDataElem || !warningElem) return;
            
            const now = new Date();
            const fileUpdateTs = new Date(lastUpdateElem.dataset.timestamp);
            const fileDiff = (now - fileUpdateTs) / 1000;
            
            const dataTs = lastDataElem.dataset.timestamp ? new Date(lastDataElem.dataset.timestamp) : null;
            const dataDiff = dataTs ? (now - dataTs) / 1000 : 0;
            
            if (fileDiff > 30) {
                document.body.classList.add('stale-data');
                warningElem.innerText = '⚠️ CRITICAL: BOT OFFLINE (No dashboard updates for ' + Math.round(fileDiff) + 's)';
            } else if (dataDiff > 45) {
                document.body.classList.add('stale-data');
                warningElem.innerText = '⚠️ WARNING: DATA STALLED (No market bars for ' + Math.round(dataDiff) + 's)';
            } else {
                document.body.classList.remove('stale-data');
                warningElem.innerText = ''; // Clear text
            }
        }
        
        // Check immediately and then every 2 seconds
        checkStaleData();
        setInterval(checkStaleData, 2000);
    </script>
</body>
</html>
"""
    return html

def update_dashboard(state: DashboardState, html_path: str = WEB_DASHBOARD, json_path: str = None) -> None:
    """
    Main entry point to update dashboard files.
    """
    try:
        # Create directories if needed
        os.makedirs(os.path.dirname(html_path), exist_ok=True)
        if json_path:
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            
        # 1. Generate & Write HTML
        html_content = generate_dashboard_html(state)
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
            
        # 2. Write JSONP Status (if path provided)
        if json_path:
            prefix = "live" if state.mode.lower() == "live" else "paper"
            total_pos = sum(p.get('position', 0) for p in state.positions) if state.positions else 0.0
            
            pnl = 0.0
            if state.account_info:
                pnl = float(state.account_info.get('RealizedPNL', 0) or 0) + float(state.account_info.get('UnrealizedPNL', 0) or 0)
                
            status_data = {
                'mode': state.mode.upper(),
                'port': state.port,
                'connected': state.is_connected,
                'net_liquidation': float(state.account_info.get('NetLiquidation', 0)) if state.account_info else 0.0,
                'pnl': pnl,
                'position': total_pos,
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            js_content = f"window.updateStatus('{prefix}', {json.dumps(status_data)});"
            with open(json_path, 'w', encoding='utf-8') as f:
                f.write(js_content)
                
    except Exception as e:
        logging.error(f"Failed to update dashboard: {e}")


import os
import json
import logging
import math
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import pytz
from typing import List, Dict, Any, Optional

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore

EASTERN = pytz.timezone('US/Eastern')

# Constants
WEB_DIR = "web"
WEB_DASHBOARD = os.path.join(WEB_DIR, "dashboard.html")


def _write_text_file_robust(path: str, content: str, encoding: str = 'utf-8', attempts: int = 6) -> None:
    """
    Write dashboard files on Windows-friendly paths.

    In-place truncate usually works while a browser has the HTML open for viewing.
    os.replace(tmp, path) often fails with WinError 5 when the destination is locked.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    last_err: Optional[OSError] = None
    for i in range(attempts):
        try:
            with open(path, 'w', encoding=encoding, newline='\n') as handle:
                handle.write(content)
            return
        except OSError as e:
            last_err = e
            time.sleep(0.04 * (i + 1))

    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix='._dash_', suffix='.tmp', dir=directory)
        with os.fdopen(fd, 'w', encoding=encoding, newline='\n') as handle:
            handle.write(content)
        os.replace(tmp_path, path)
        tmp_path = None
        return
    except OSError:
        if tmp_path and os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        if last_err is not None:
            raise last_err
        raise


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

    # Live chart (OHLC + Donchian + optional SL/TP overlay); built in main / update_ui
    chart_payload: Optional[Dict[str, Any]] = None
    trade_overlay: Optional[Dict[str, Any]] = None

def format_duration(seconds):
    """Format seconds into HH:MM:SS string."""
    if not seconds:
        return "00:00:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_dashboard_datetime(ts: Any) -> str:
    """Format trade timestamps for HTML (US/Eastern when aware UTC)."""
    if ts is None or ts == '':
        return ''
    if isinstance(ts, str):
        return ts
    try:
        if hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
            return ts.astimezone(EASTERN).strftime('%Y-%m-%d %H:%M:%S %Z')
    except Exception:
        pass
    if hasattr(ts, 'strftime'):
        return ts.strftime('%Y-%m-%d %H:%M:%S')
    return str(ts)


# Indicator columns: last value in each HTF bucket (matches live aggregation).
_CHART_INDICATOR_COLS = (
    'donchian_high', 'donchian_low', 'upper', 'lower', 'mid', 'atr',
    'atr_filter', 'adx', 'rsi', 'sma_regime',
)


def _extract_chart_thresholds(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract indicator/filter thresholds from strategy params for chart guide lines."""
    if not params:
        return {}

    def _get(keys):
        for key in keys:
            if key not in params:
                continue
            entry = params[key]
            v = entry.get('value', entry) if isinstance(entry, dict) else entry
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return None

    out: Dict[str, Any] = {}
    out['min_atr'] = _get(['Min ATR (Points)', 'Min ATR Filter (Points)', 'min_atr_points'])
    out['min_adx'] = _get(['Min ADX Threshold', 'ADX Threshold', 'min_adx'])
    out['rsi_max_buy'] = _get(['RSI Max Buy Threshold', 'RSI Overbought', 'rsi_max_buy'])
    out['rsi_min_sell'] = _get(['RSI Min Sell Threshold', 'RSI Oversold', 'rsi_min_sell'])
    return {k: v for k, v in out.items() if v is not None}


def dashboard_timeframe_minutes(params: Optional[Dict[str, Any]]) -> int:
    """Bar size in minutes from strategy params (CSV-style dict with 'value' entries)."""
    if not params:
        return 1
    for key in ('Timeframe (minutes)', 'timeframe', 'Timeframe'):
        if key not in params:
            continue
        entry = params[key]
        v = entry.get('value', entry) if isinstance(entry, dict) else entry
        try:
            return max(1, int(round(float(v))))
        except (TypeError, ValueError):
            continue
    return 1


def build_chart_payload_from_df(
    df: Any,
    max_bars: int = 480,
    timeframe_mins: int = 1,
    completed_trades: Optional[List[Dict[str, Any]]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Serialize OHLC for Plotly; resample 1m history to the strategy timeframe when >1."""
    if pd is None or df is None or getattr(df, 'empty', True):
        return None
    tf = max(1, int(timeframe_mins or 1))
    try:
        need_1m = min(len(df), max(2000, max_bars * tf * 4 + 120))
        d1 = df.tail(int(need_1m)).copy()
        if len(d1) < 2:
            return None
        if not isinstance(d1.index, pd.DatetimeIndex):
            d1.index = pd.to_datetime(d1.index)
    except Exception:
        return None

    base = ['open', 'high', 'low', 'close']
    for c in base:
        if c not in d1.columns:
            return None
    if 'volume' not in d1.columns:
        d1['volume'] = 0.0

    try:
        if tf > 1:
            from core.monitoring import resample_data

            d = resample_data(d1[base + ['volume']], tf)
            rule = f'{tf}min'
            for col in _CHART_INDICATOR_COLS:
                if col in d1.columns:
                    agg = d1[col].resample(rule, closed='right', label='right').last()
                    d[col] = agg.reindex(d.index).ffill()
        else:
            d = d1[base + ['volume']].copy()
            for col in _CHART_INDICATOR_COLS:
                if col in d1.columns:
                    d[col] = d1[col]
        d = d.dropna(how='any', subset=base)
        d = d.tail(int(max_bars))
        if len(d) < 2:
            return None
    except Exception:
        logging.debug('build_chart_payload_from_df failed', exc_info=True)
        return None

    def jfloat(x: Any) -> Any:
        try:
            if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
                return None
            v = float(x)
            if math.isnan(v) or math.isinf(v):
                return None
            return v
        except (TypeError, ValueError):
            return None

    times: List[str] = []
    for t in d.index:
        if hasattr(t, 'isoformat'):
            times.append(t.isoformat())
        else:
            times.append(str(t))

    o = [jfloat(v) for v in d['open'].tolist()]
    h = [jfloat(v) for v in d['high'].tolist()]
    lo = [jfloat(v) for v in d['low'].tolist()]
    c = [jfloat(v) for v in d['close'].tolist()]

    payload: Dict[str, Any] = {
        'times': times,
        'o': o,
        'h': h,
        'l': lo,
        'c': c,
        'v': [jfloat(v) for v in d['volume'].tolist()],
        'timeframe_mins': tf,
    }
    if 'donchian_high' in d.columns:
        s = d['donchian_high'].ffill()
        payload['donchian_high'] = [jfloat(v) for v in s.tolist()]
    if 'donchian_low' in d.columns:
        s = d['donchian_low'].ffill()
        payload['donchian_low'] = [jfloat(v) for v in s.tolist()]
    for col in ('atr', 'atr_filter', 'adx', 'rsi', 'sma_regime'):
        if col in d.columns:
            payload[col] = [jfloat(v) for v in d[col].ffill().tolist()]
    thresholds = _extract_chart_thresholds(params)
    if thresholds:
        payload['thresholds'] = thresholds
    if completed_trades:
        markers = []
        for tr in completed_trades[-300:]:
            et = tr.get('entry_time')
            xt = tr.get('exit_time')
            ep = jfloat(tr.get('entry_price'))
            xp = jfloat(tr.get('exit_price'))
            if xt is None or xp is None:
                continue
            markers.append({
                'entry_time': et.isoformat() if hasattr(et, 'isoformat') else (str(et) if et else None),
                'entry_price': ep,
                'exit_time': xt.isoformat() if hasattr(xt, 'isoformat') else str(xt),
                'exit_price': xp,
                'direction': tr.get('direction', 'N/A'),
                'reason': tr.get('reason', ''),
                'pnl': jfloat(tr.get('pnl')),
                'stop_at_close': jfloat(tr.get('stop_at_close')),
                'tp_at_close': jfloat(tr.get('tp_at_close')),
            })
        if markers:
            payload['trade_markers'] = markers
    return payload


def _chart_json_for_page(state: DashboardState) -> str:
    """JSON for embedded chart (safe inside HTML)."""
    merged = None
    if state.chart_payload:
        merged = dict(state.chart_payload)
        if state.trade_overlay:
            merged['overlay'] = state.trade_overlay
    raw = json.dumps(merged) if merged else 'null'
    return raw.replace('</', '<\\/')

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
    chart_tf = dashboard_timeframe_minutes(state.params)
    
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
        #live-chart {{ width: 100%; height: 520px; min-height: 360px; }}
        .sub-metric {{ font-size: 0.75em; color: #7f8c8d; margin-top: 6px; }}
    </style>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js" charset="utf-8"></script>
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
                <div class="label">Realized PNL (account)</div>
                <div class="value {'positive' if (state.account_info.get('RealizedPNL') or 0) >= 0 else 'negative'}">
                    ${state.account_info.get('RealizedPNL') or 0:,.2f}
                </div>
                {f'<div class="sub-metric">ES line realized (ref): ${state.account_info.get("ContractRealizedPNL") or 0:,.2f}</div>' if state.account_info.get('ContractRealizedPNL') is not None else ''}
            </div>
            <div class="metric-box">
                <div class="label">Current Price</div>
                <div class="value">${state.current_price:,.2f}</div>
            </div>
        </div>
        
        <h2>Price chart ({chart_tf}-minute bars)</h2>
        <div id="live-chart"></div>
        <script type="application/json" id="chart-payload">{_chart_json_for_page(state)}</script>
        
        <h2>Active Positions</h2>
"""
    if state.positions:
        html += """        <table>
            <thead>
                <tr>
                    <th>Contract</th>
                    <th>Pos</th>
                    <th>Avg (pts)</th>
                    <th>Mkt (pts)</th>
                    <th>Mkt Value</th>
                    <th>Unrealized</th>
                    <th>Realized (line)</th>
                </tr>
            </thead>
            <tbody>
"""
        for pos in state.positions:
            unrealized = float(pos.get('unrealizedPNL', 0) or 0)
            realized = float(pos.get('realizedPNL', 0) or 0)
            pnl_class = 'positive' if unrealized >= 0 else 'negative'
            sym = pos.get('localSymbol') or pos.get('symbol', 'N/A')
            avg_pts = float(pos.get('avgPrice', 0) or pos.get('avgCost', 0) or 0)
            mkt_pts = float(pos.get('marketPrice', 0) or 0)
            if mkt_pts <= 0:
                mkt_pts = float(state.current_price or 0)
            
            html += f"""                <tr>
                    <td>{sym}</td>
                    <td>{pos.get('position', 0)}</td>
                    <td>${avg_pts:,.2f}</td>
                    <td>${mkt_pts:,.2f}</td>
                    <td>${float(pos.get('marketValue', 0) or 0):,.2f}</td>
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
        for trade in reversed(state.completed_trades[-200:]):
            pnl = float(trade.get('pnl', 0) or 0)
            r_mult = float(trade.get('r_multiple', 0) or 0)
            pnl_class = 'positive' if pnl > 0 else 'negative' if pnl < 0 else ''
            r_class = 'positive' if r_mult > 0 else 'negative' if r_mult < 0 else ''
            
            exit_time = format_dashboard_datetime(trade.get('exit_time'))
            reason = str(trade.get('reason', 'N/A') or '')
            reason_lower = reason.lower()
            if 'take profit' in reason_lower or reason_lower == 'tp':
                reason_cls = 'TRADE'
            elif 'stop' in reason_lower:
                reason_cls = 'WARNING'
            else:
                reason_cls = 'INFO'
            
            direction = trade.get('direction', 'N/A')
            dir_emoji = '🟢' if direction == 'LONG' else '🔴' if direction == 'SHORT' else ''
            
            html += f"""                <tr>
                    <td>{exit_time}</td>
                    <td>{dir_emoji} {direction}</td>
                    <td>${float(trade.get('entry_price', 0) or 0):,.2f}</td>
                    <td>${float(trade.get('exit_price', 0) or 0):,.2f}</td>
                    <td class="{pnl_class}">${pnl:,.2f}</td>
                    <td class="{r_class}" title="Risk: ${trade.get('initial_risk', 0):,.2f}">{r_mult:+.2f}R</td>
                    <td>{trade.get('duration', 'N/A')}</td>
                    <td><span class="log-type {reason_cls}" style="width: auto; padding: 2px 8px;">{reason}</span></td>
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

        function renderLiveChart() {
            var el = document.getElementById('live-chart');
            var raw = document.getElementById('chart-payload');
            if (!el) return;
            if (typeof Plotly === 'undefined') return;
            if (!raw) {
                el.innerHTML = '<p style="padding:12px;color:#7f8c8d">Chart waiting…</p>';
                return;
            }
            var p;
            try { p = JSON.parse(raw.textContent); } catch (e) {
                el.innerHTML = '<p style="padding:12px;color:#c0392b">Chart JSON error</p>';
                return;
            }
            if (!p || !p.times || p.times.length < 2) {
                el.innerHTML = '<p style="padding:12px;color:#7f8c8d">No OHLC yet (history warming up)…</p>';
                return;
            }
            var tfm = p.timeframe_mins || 1;
            var zoomKey = 'dashboard_live_chart_zoom_v1';
            var savedZoom = null;
            try {
                var saved = localStorage.getItem(zoomKey);
                if (saved) savedZoom = JSON.parse(saved);
            } catch (_) {}
            var traces = [{
                type: 'candlestick', x: p.times, open: p.o, high: p.h, low: p.l, close: p.c,
                name: 'ES', increasing: {line: {color: '#26a69a'}}, decreasing: {line: {color: '#ef5350'}},
                xaxis: 'x', yaxis: 'y'
            }];
            function anyNonNull(arr) {
                if (!arr) return false;
                for (var i = 0; i < arr.length; i++) if (arr[i] != null) return true;
                return false;
            }
            if (anyNonNull(p.donchian_high))
                traces.push({ type: 'scatter', x: p.times, y: p.donchian_high, name: 'Donchian high',
                    line: { color: '#1565c0', width: 1.2 }, mode: 'lines', xaxis: 'x', yaxis: 'y' });
            if (anyNonNull(p.donchian_low))
                traces.push({ type: 'scatter', x: p.times, y: p.donchian_low, name: 'Donchian low',
                    line: { color: '#c62828', width: 1.2 }, mode: 'lines', xaxis: 'x', yaxis: 'y' });
            if (anyNonNull(p.sma_regime))
                traces.push({ type: 'scatter', x: p.times, y: p.sma_regime, name: 'SMA',
                    line: { color: '#6b7280', width: 1.2 }, mode: 'lines', xaxis: 'x', yaxis: 'y' });
            if (anyNonNull(p.v))
                traces.push({ type: 'bar', x: p.times, y: p.v, name: 'Volume',
                    marker: {color: '#94a3b8'}, opacity: 0.6, xaxis: 'x2', yaxis: 'y2' });
            if (anyNonNull(p.atr))
                traces.push({ type: 'scatter', x: p.times, y: p.atr, name: 'ATR',
                    line: { color: '#8b5cf6', width: 1.5 }, mode: 'lines', xaxis: 'x3', yaxis: 'y3' });
            if (anyNonNull(p.atr_filter))
                traces.push({ type: 'scatter', x: p.times, y: p.atr_filter, name: 'ATR Filter',
                    line: { color: '#a78bfa', width: 1, dash: 'dot' }, mode: 'lines', xaxis: 'x3', yaxis: 'y3' });
            if (anyNonNull(p.adx))
                traces.push({ type: 'scatter', x: p.times, y: p.adx, name: 'ADX',
                    line: { color: '#0891b2', width: 1.5 }, mode: 'lines', xaxis: 'x3', yaxis: 'y3' });
            if (anyNonNull(p.rsi))
                traces.push({ type: 'scatter', x: p.times, y: p.rsi, name: 'RSI',
                    line: { color: '#7c3aed', width: 1.5 }, mode: 'lines', xaxis: 'x4', yaxis: 'y4' });
            if (p.trade_markers && p.trade_markers.length) {
                var entX = [], entY = [], entTxt = [];
                var exX = [], exY = [], exTxt = [];
                for (var k = 0; k < p.trade_markers.length; k++) {
                    var m = p.trade_markers[k];
                    if (m.entry_time && m.entry_price != null) {
                        entX.push(m.entry_time);
                        entY.push(m.entry_price);
                        entTxt.push('ENTRY ' + (m.direction || '') + '<br>' + (m.reason || '') + '<br>PnL: ' + (m.pnl != null ? m.pnl.toFixed(2) : 'n/a'));
                    }
                    if (m.exit_time && m.exit_price != null) {
                        exX.push(m.exit_time);
                        exY.push(m.exit_price);
                        var extra = [];
                        if (m.stop_at_close != null) extra.push('SL@close: ' + m.stop_at_close.toFixed(2));
                        if (m.tp_at_close != null) extra.push('TP@close: ' + m.tp_at_close.toFixed(2));
                        exTxt.push('EXIT ' + (m.direction || '') + '<br>' + (m.reason || '') + '<br>PnL: ' + (m.pnl != null ? m.pnl.toFixed(2) : 'n/a') +
                            (extra.length ? ('<br>' + extra.join('<br>')) : ''));
                    }
                }
                if (entX.length) traces.push({
                    type: 'scatter', mode: 'markers', x: entX, y: entY, name: 'Entries',
                    marker: { symbol: 'triangle-up', size: 8, color: '#6a1b9a' },
                    text: entTxt, hovertemplate: '%{text}<extra></extra>', xaxis: 'x', yaxis: 'y'
                });
                if (exX.length) traces.push({
                    type: 'scatter', mode: 'markers', x: exX, y: exY, name: 'Exits',
                    marker: { symbol: 'x', size: 8, color: '#2f3640' },
                    text: exTxt, hovertemplate: '%{text}<extra></extra>', xaxis: 'x', yaxis: 'y'
                });
            }
            var shapes = [];
            var ann = [];
            var x0 = p.times[0], x1 = p.times[p.times.length - 1];
            if (p.overlay) {
                if (p.overlay.stop != null) {
                    shapes.push({ type: 'line', xref: 'x', yref: 'y', x0: x0, x1: x1, y0: p.overlay.stop, y1: p.overlay.stop,
                        line: { color: '#c62828', width: 2, dash: 'dash' } });
                    ann.push({ x: x1, y: p.overlay.stop, text: ' SL', showarrow: false, xanchor: 'left', font: { color: '#c62828', size: 11 } });
                }
                if (p.overlay.take_profit != null) {
                    shapes.push({ type: 'line', xref: 'x', yref: 'y', x0: x0, x1: x1, y0: p.overlay.take_profit, y1: p.overlay.take_profit,
                        line: { color: '#2e7d32', width: 2, dash: 'dot' } });
                    ann.push({ x: x1, y: p.overlay.take_profit, text: ' TP', showarrow: false, xanchor: 'left', font: { color: '#2e7d32', size: 11 } });
                }
                if (p.overlay.entry_price != null) {
                    shapes.push({ type: 'line', xref: 'x', yref: 'y', x0: x0, x1: x1, y0: p.overlay.entry_price, y1: p.overlay.entry_price,
                        line: { color: '#6a1b9a', width: 1, dash: 'solid' } });
                }
            }
            if (p.thresholds) {
                if (p.thresholds.min_atr != null) {
                    shapes.push({ type: 'line', xref: 'x3', yref: 'y3', x0: x0, x1: x1, y0: p.thresholds.min_atr, y1: p.thresholds.min_atr,
                        line: { color: '#8b5cf6', width: 1, dash: 'dash' } });
                }
                if (p.thresholds.min_adx != null) {
                    shapes.push({ type: 'line', xref: 'x3', yref: 'y3', x0: x0, x1: x1, y0: p.thresholds.min_adx, y1: p.thresholds.min_adx,
                        line: { color: '#0891b2', width: 1, dash: 'dot' } });
                }
                if (p.thresholds.rsi_max_buy != null) {
                    shapes.push({ type: 'line', xref: 'x4', yref: 'y4', x0: x0, x1: x1, y0: p.thresholds.rsi_max_buy, y1: p.thresholds.rsi_max_buy,
                        line: { color: '#7c3aed', width: 1, dash: 'dot' } });
                }
                if (p.thresholds.rsi_min_sell != null) {
                    shapes.push({ type: 'line', xref: 'x4', yref: 'y4', x0: x0, x1: x1, y0: p.thresholds.rsi_min_sell, y1: p.thresholds.rsi_min_sell,
                        line: { color: '#7c3aed', width: 1, dash: 'dot' } });
                }
            }
            var layout = {
                title: 'Last ' + p.times.length + ' × ' + tfm + '-minute bars',
                dragmode: 'zoom', showlegend: true, legend: { orientation: 'h', y: 1.1 },
                xaxis: { domain:[0,1], anchor:'y', rangeslider: { visible: false }, type: 'date', showticklabels:false },
                yaxis: { title: 'Price', domain:[0.46,1.0], autorange: true },
                xaxis2: { domain:[0,1], anchor:'y2', type:'date', showticklabels:false, matches:'x' },
                yaxis2: { title: 'Vol', domain:[0.31,0.44], autorange:true },
                xaxis3: { domain:[0,1], anchor:'y3', type:'date', showticklabels:false, matches:'x' },
                yaxis3: { title: 'ATR/ADX', domain:[0.16,0.29], autorange:true },
                xaxis4: { domain:[0,1], anchor:'y4', type:'date', matches:'x' },
                yaxis4: { title: 'RSI', domain:[0.0,0.14], range:[0,100] },
                shapes: shapes, annotations: ann, margin: { t: 40, r: 20, b: 36, l: 56 }
            };
            if (savedZoom) {
                if (savedZoom.x0 && savedZoom.x1) {
                    layout.xaxis.range = [savedZoom.x0, savedZoom.x1];
                    layout.xaxis.autorange = false;
                }
                if (savedZoom.y0 != null && savedZoom.y1 != null) {
                    layout.yaxis.range = [savedZoom.y0, savedZoom.y1];
                    layout.yaxis.autorange = false;
                }
                if (savedZoom.y20 != null && savedZoom.y21 != null) {
                    layout.yaxis2.range = [savedZoom.y20, savedZoom.y21];
                    layout.yaxis2.autorange = false;
                }
                if (savedZoom.y30 != null && savedZoom.y31 != null) {
                    layout.yaxis3.range = [savedZoom.y30, savedZoom.y31];
                    layout.yaxis3.autorange = false;
                }
                if (savedZoom.y40 != null && savedZoom.y41 != null) {
                    layout.yaxis4.range = [savedZoom.y40, savedZoom.y41];
                    layout.yaxis4.autorange = false;
                }
            }
            Plotly.react(el, traces, layout, { displayModeBar: true, responsive: true });
            if (!el.__zoomHookAttached) {
                el.on('plotly_relayout', function(ev) {
                    if (!ev) return;
                    var x0 = ev['xaxis.range[0]'];
                    var x1 = ev['xaxis.range[1]'];
                    var y0 = ev['yaxis.range[0]'];
                    var y1 = ev['yaxis.range[1]'];
                    var y20 = ev['yaxis2.range[0]'];
                    var y21 = ev['yaxis2.range[1]'];
                    var y30 = ev['yaxis3.range[0]'];
                    var y31 = ev['yaxis3.range[1]'];
                    var y40 = ev['yaxis4.range[0]'];
                    var y41 = ev['yaxis4.range[1]'];
                    if (ev['xaxis.autorange'] || ev['yaxis.autorange'] || ev['yaxis2.autorange'] || ev['yaxis3.autorange'] || ev['yaxis4.autorange']) {
                        try { localStorage.removeItem(zoomKey); } catch (_) {}
                        return;
                    }
                    if (x0 || x1 || y0 != null || y1 != null || y20 != null || y21 != null || y30 != null || y31 != null || y40 != null || y41 != null) {
                        try {
                            localStorage.setItem(zoomKey, JSON.stringify({
                                x0: x0 || (savedZoom && savedZoom.x0) || null,
                                x1: x1 || (savedZoom && savedZoom.x1) || null,
                                y0: (y0 != null) ? y0 : ((savedZoom && savedZoom.y0) || null),
                                y1: (y1 != null) ? y1 : ((savedZoom && savedZoom.y1) || null),
                                y20: (y20 != null) ? y20 : ((savedZoom && savedZoom.y20) || null),
                                y21: (y21 != null) ? y21 : ((savedZoom && savedZoom.y21) || null),
                                y30: (y30 != null) ? y30 : ((savedZoom && savedZoom.y30) || null),
                                y31: (y31 != null) ? y31 : ((savedZoom && savedZoom.y31) || null),
                                y40: (y40 != null) ? y40 : ((savedZoom && savedZoom.y40) || null),
                                y41: (y41 != null) ? y41 : ((savedZoom && savedZoom.y41) || null)
                            }));
                        } catch (_) {}
                    }
                });
                el.__zoomHookAttached = true;
            }
        }
        function scheduleLiveChart(attemptsLeft) {
            var el = document.getElementById('live-chart');
            if (!el) return;
            if (typeof Plotly !== 'undefined') {
                renderLiveChart();
                return;
            }
            if (attemptsLeft <= 0) {
                el.innerHTML = '<div style="padding:16px;color:#c0392b;line-height:1.55;max-width:52em"><strong>Chart library did not load.</strong> Browsers often block scripts when you open the dashboard as <code>file://</code>. From your project root run <code>python -m http.server 8765</code> then open <code>http://localhost:8765/web/dashboard_paper.html</code>. Also check network / ad blockers.</div>';
                return;
            }
            el.innerHTML = '<p style="padding:12px;color:#7f8c8d">Loading chart library…</p>';
            setTimeout(function() { scheduleLiveChart(attemptsLeft - 1); }, 300);
        }
        scheduleLiveChart(40);
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
        # 1. Generate & Write HTML (in-place write avoids WinError 5 when file is open in browser)
        html_content = generate_dashboard_html(state)
        _write_text_file_robust(html_path, html_content, encoding='utf-8')

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
            _write_text_file_robust(json_path, js_content, encoding='utf-8')

    except Exception as e:
        logging.error(f"Failed to update dashboard: {e}")

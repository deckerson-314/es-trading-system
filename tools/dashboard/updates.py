import html as html_lib

import os
import json
import logging
import math
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
import pytz
from typing import List, Dict, Any, Optional, TYPE_CHECKING

from tools.dashboard.debug import (
    append_perf_record,
    client_debug_script_block,
    dashboard_debug_enabled,
    health_sidecar_path,
    log_dashboard_write,
    next_write_seq,
    timed_section,
)

if TYPE_CHECKING:
    from tools.safety.guards import SecurityGuard

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore

EASTERN = pytz.timezone('US/Eastern')

# Constants
WEB_DIR = "web"
WEB_DASHBOARD = os.path.join(WEB_DIR, "dashboard.html")

# Stale thresholds: 1m bar streams can go ~60s between receipts; background browser
# tabs throttle meta-refresh, which falsely inflates "snapshot age" in client JS.
DASHBOARD_DATA_STALE_SERVER_SEC = 120
DASHBOARD_FILE_STALE_CLIENT_SEC = 180
DASHBOARD_DATA_STALL_CLIENT_SEC = 150


def _format_dashboard_order_price(val) -> str:
    """Format a single IB price field for the orders table (handles unset / NaN)."""
    if val is None:
        return "-"
    try:
        x = float(val)
        if not math.isfinite(x) or abs(x) > 1e12:
            return "-"
        return f"${x:,.2f}"
    except (TypeError, ValueError):
        return "-"


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
    open_brackets: List[Dict[str, Any]] = field(default_factory=list)
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

    # Set True after trade open/close so the next UI cycle forces a full HTML refresh.
    request_full_refresh: bool = False
    
    # Parameters
    params: Dict[str, Any] = field(default_factory=dict)

    # Populated after startup: blocks `check_entries` when daily emergency flatten latched.
    security_guard: Optional["SecurityGuard"] = None

    # Single clientId policy (core.client_id_guard)
    client_id_trading_halted: bool = False
    client_id_expected: int = 0
    client_id_active_on_account: List[int] = field(default_factory=list)
    client_id_violation_detail: str = ""

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


def build_chart_payload_with_indicators(
    df: Any,
    strategy: Any,
    max_bars: int = 480,
    timeframe_mins: int = 1,
    completed_trades: Optional[List[Dict[str, Any]]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Refresh strategy indicators on a bar snapshot, then serialize for Plotly."""
    if pd is None or df is None or getattr(df, 'empty', True):
        return None
    work = df
    if strategy is not None:
        try:
            work = df.copy()
            from core.monitoring import update_indicators

            update_indicators(strategy, work)
        except Exception:
            logging.debug(
                'build_chart_payload_with_indicators: indicator refresh failed',
                exc_info=True,
            )
            work = df
    return build_chart_payload_from_df(
        work, max_bars, timeframe_mins, completed_trades, params
    )


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
                'live_exit_type': tr.get('live_exit_type', ''),
                'exit_path': tr.get('exit_path', ''),
                'broker_stop_at_exit': jfloat(tr.get('broker_stop_at_exit')),
                'model_stop_at_exit': jfloat(tr.get('model_stop_at_exit')),
                'pnl': jfloat(tr.get('pnl')),
                'stop_at_open': jfloat(tr.get('stop_at_open')),
                'tp_at_open': jfloat(tr.get('tp_at_open')),
                'stop_at_close': jfloat(tr.get('stop_at_close')),
                'tp_at_close': jfloat(tr.get('tp_at_close')),
            })
        if markers:
            payload['trade_markers'] = markers
    return payload


def _sanitize_json_for_browser(obj: Any) -> Any:
    """
    Ensure values are JSON-serializable per RFC 7159 so browsers' JSON.parse works.
    Python's json.dumps(allow_nan=True) emits NaN/Infinity which JSON.parse rejects.
    """
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, str):
        return obj
    if isinstance(obj, int) and not isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): _sanitize_json_for_browser(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json_for_browser(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        try:
            return obj.isoformat()
        except Exception:
            return None
    if pd is not None:
        try:
            if isinstance(obj, pd.Timestamp):
                return pd.Timestamp(obj).isoformat()
        except Exception:
            pass
    try:
        import numpy as np

        if isinstance(obj, np.ndarray):
            return _sanitize_json_for_browser(obj.tolist())
        if isinstance(obj, np.generic):
            return _sanitize_json_for_browser(obj.item())
    except ImportError:
        pass
    try:
        x = float(obj)
        if math.isfinite(x):
            return x
    except (TypeError, ValueError):
        pass
    return str(obj)


def chart_payload_json_path(html_path: str) -> str:
    """Sidecar JSON for live chart polling (no full HTML regen)."""
    base, _ = os.path.splitext(html_path)
    return f'{base}_chart.json'


def export_chart_payload(state: DashboardState) -> Optional[Dict[str, Any]]:
    """Chart dict for browser / sidecar JSON."""
    if not state.chart_payload:
        return None
    merged = dict(state.chart_payload)
    if state.trade_overlay:
        merged['overlay'] = state.trade_overlay
    return merged


def write_chart_payload_json(
    state: DashboardState,
    json_path: str,
    write_label: str = '',
) -> int:
    """Write chart-only JSON sidecar (~100KB). Fast path for 30s chart updates."""
    import time as _time

    t0 = _time.perf_counter()
    merged = export_chart_payload(state)
    if not merged:
        logging.info('Dashboard chart JSON skipped [%s]: no payload', write_label or '?')
        return 0
    try:
        safe = _sanitize_json_for_browser(merged)
        chart_points = len(safe.get('times') or [])
        seq = next_write_seq()
        wrapper = {
            'write_seq': seq,
            'write_label': write_label,
            'wall_ts': datetime.now(EASTERN).isoformat(),
            'chart_points': chart_points,
            'chart': safe,
        }
        content = json.dumps(wrapper, allow_nan=False)
        _write_text_file_robust(json_path, content, encoding='utf-8')
        ms = round((_time.perf_counter() - t0) * 1000, 1)
        logging.info(
            'Dashboard chart JSON #%s [%s] pts=%s bytes=%s write=%.0fms',
            seq,
            write_label or '?',
            chart_points,
            len(content),
            ms,
        )
        append_perf_record({
            'event': 'dashboard_chart_json',
            'write_seq': seq,
            'write_label': write_label,
            'json_path': json_path,
            'chart_points': chart_points,
            'json_bytes': len(content),
            'write_ms': ms,
        })
        return seq
    except Exception as e:
        logging.error('Dashboard chart JSON write failed [%s]: %s', write_label or '?', e, exc_info=True)
        raise


def _chart_json_for_page(state: DashboardState) -> str:
    """JSON for embedded chart (safe inside HTML)."""
    merged = export_chart_payload(state)
    if not merged:
        return "null"
    try:
        safe = _sanitize_json_for_browser(merged)
        raw = json.dumps(safe, allow_nan=False)
        return raw.replace("</", "<\\/")
    except (TypeError, ValueError) as e:
        logging.warning("chart JSON encode failed: %s", e)
        return "null"


def tables_payload_json_path(html_path: str) -> str:
    """Sidecar JSON for live table polling (positions, orders, trades, logs)."""
    base, _ = os.path.splitext(html_path)
    return f'{base}_tables.json'


def render_positions_panel(state: DashboardState) -> str:
    """HTML fragment for positions + open-bracket tables."""
    html = ''
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

    if state.open_brackets:
        html += """
        <h3>Bot-tracked bracket</h3>
        <table>
            <thead>
                <tr>
                    <th>Contract</th>
                    <th>Dir</th>
                    <th>Qty</th>
                    <th>Entry Time</th>
                    <th>Duration</th>
                    <th>Entry</th>
                    <th>Stop</th>
                    <th>TP</th>
                    <th>Mkt</th>
                </tr>
            </thead>
            <tbody>
"""
        for row in state.open_brackets:
            html += f"""                <tr>
                    <td>{row.get('localSymbol', 'N/A')}</td>
                    <td>{row.get('direction', 'N/A')}</td>
                    <td>{row.get('qty', '')}</td>
                    <td>{row.get('entry_time', 'N/A')}</td>
                    <td>{row.get('duration', 'N/A')}</td>
                    <td>${float(row.get('entry_price') or 0):,.2f}</td>
                    <td>${float(row.get('stop') or 0):,.2f}</td>
                    <td>{'$' + format(float(row.get('take_profit') or 0), ',.2f') if row.get('take_profit') is not None else 'N/A'}</td>
                    <td>${float(row.get('market_price') or 0):,.2f}</td>
                </tr>
"""
        html += """            </tbody>
        </table>
"""
    return html


def render_orders_panel(state: DashboardState) -> str:
    if not state.active_orders:
        return """        <div style="padding: 20px; text-align: center; color: #7f8c8d; background: #f8f9fa; border-radius: 8px;">No active orders</div>"""
    html = """        <div style="overflow-x:auto;">
        <table>
            <thead>
                <tr>
                    <th>Contract</th>
                    <th>PermID</th>
                    <th>Parent</th>
                    <th>Order ID</th>
                    <th>Type</th>
                    <th>Action</th>
                    <th>Size</th>
                    <th>Lmt</th>
                    <th>Stop</th>
                    <th>Aux</th>
                    <th>Trig*</th>
                    <th>TIF</th>
                    <th>Status</th>
                    <th>Why held</th>
                </tr>
            </thead>
            <tbody>
"""
    for order in state.active_orders:
        sym = html_lib.escape(str(order.get("localSymbol") or order.get("symbol") or "-"))
        why = html_lib.escape(str(order.get("whyHeld") or ""))
        html += f"""                <tr>
                    <td>{sym}</td>
                    <td>{order.get('permId') or '-'}</td>
                    <td>{order.get('parentId') or '-'}</td>
                    <td>{order.get('orderId') or '-'}</td>
                    <td>{html_lib.escape(str(order.get('orderType') or ''))}</td>
                    <td>{html_lib.escape(str(order.get('action') or ''))}</td>
                    <td>{order.get('totalQuantity')}</td>
                    <td>{_format_dashboard_order_price(order.get('lmtPrice'))}</td>
                    <td>{_format_dashboard_order_price(order.get('stopPrice'))}</td>
                    <td>{_format_dashboard_order_price(order.get('auxPrice'))}</td>
                    <td>{_format_dashboard_order_price(order.get('triggerPrice'))}</td>
                    <td>{html_lib.escape(str(order.get('tif') or ''))}</td>
                    <td><span class="log-type INFO" style="width: auto; padding: 2px 8px;">{html_lib.escape(str(order.get('status') or ''))}</span></td>
                    <td style="max-width:220px;font-size:0.85em">{why}</td>
                </tr>
"""
    html += """            </tbody>
        </table>
        </div>
        <p style="font-size:0.85em;color:#64748b;margin-top:6px">*Trig = first of Stop / Aux / Lmt (IB populates different fields per order type).</p>
"""
    return html


def render_bar_log_panel(state: DashboardState) -> str:
    if not state.bar_log:
        return """        <div style="padding: 20px; text-align: center; color: #7f8c8d; background: #f8f9fa; border-radius: 8px;">No bar data yet</div>"""
    html = """        <div class="log-container" style="max-height: 300px;">
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
    return html


def render_completed_trades_panel(state: DashboardState) -> str:
    if not state.completed_trades:
        return """        <div style="padding: 20px; text-align: center; color: #7f8c8d; background: #f8f9fa; border-radius: 8px;">No completed trades</div>"""
    html = """        <table>
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
                    <th>Exit Type</th>
                    <th>Slip (pts)</th>
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
        live_exit = str(trade.get('live_exit_type', '') or '')
        slip_pts = trade.get('slippage_pts')
        slip_disp = f"{float(slip_pts):+.2f}" if slip_pts is not None else "—"
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
                    <td>{live_exit or '—'}</td>
                    <td>{slip_disp}</td>
                    <td>
                        {f'<a href="{trade.get("report_url")}" target="_blank" class="report-link">📊 View</a>' if trade.get('report_url') else '<span style="color:#bdc3c7">N/A</span>'}
                    </td>
                </tr>
"""
    html += """            </tbody>
        </table>
"""
    return html


def render_system_logs_panel(state: DashboardState) -> str:
    all_logs = []
    for entry in state.live_tracker:
        all_logs.append({
            'timestamp': entry.get('timestamp', ''),
            'type': entry.get('type', 'INFO').upper(),
            'message': entry.get('message', ''),
        })
    for entry in state.error_log:
        all_logs.append({
            'timestamp': entry.get('timestamp', ''),
            'type': 'ERROR',
            'message': entry.get('error', str(entry)),
        })
    all_logs.sort(key=lambda x: x['timestamp'], reverse=True)
    html = ''
    for log in all_logs[:100]:
        html += f"""            <div class="log-entry">
                <span class="log-timestamp">{log['timestamp']}</span>
                <span class="log-type {log['type']}">{log['type']}</span>
                <span class="log-message">{log['message']}</span>
            </div>
"""
    if not html:
        html = """            <div class="log-entry"><span class="log-message">No log entries yet</span></div>
"""
    return html


def build_tables_sections(state: DashboardState) -> Dict[str, str]:
    return {
        'positions': render_positions_panel(state),
        'orders': render_orders_panel(state),
        'bar_log': render_bar_log_panel(state),
        'completed_trades': render_completed_trades_panel(state),
        'system_logs': render_system_logs_panel(state),
    }


def write_tables_payload_json(
    state: DashboardState,
    json_path: str,
    write_label: str = '',
) -> int:
    """Write table HTML fragments for browser polling (~50–200KB)."""
    import time as _time

    t0 = _time.perf_counter()
    try:
        sections = build_tables_sections(state)
        seq = next_write_seq()
        wrapper = {
            'write_seq': seq,
            'write_label': write_label,
            'wall_ts': datetime.now(EASTERN).isoformat(),
            'completed_trade_count': len(state.completed_trades or []),
            'active_order_count': len(state.active_orders or []),
            'position_count': len(state.positions or []),
            'sections': sections,
        }
        content = json.dumps(_sanitize_json_for_browser(wrapper), allow_nan=False)
        _write_text_file_robust(json_path, content, encoding='utf-8')
        ms = round((_time.perf_counter() - t0) * 1000, 1)
        logging.info(
            'Dashboard tables JSON #%s [%s] trades=%s orders=%s pos=%s bytes=%s write=%.0fms',
            seq,
            write_label or '?',
            wrapper['completed_trade_count'],
            wrapper['active_order_count'],
            wrapper['position_count'],
            len(content),
            ms,
        )
        append_perf_record({
            'event': 'dashboard_tables_json',
            'write_seq': seq,
            'write_label': write_label,
            'json_path': json_path,
            'json_bytes': len(content),
            'write_ms': ms,
        })
        return seq
    except Exception as e:
        logging.error('Dashboard tables JSON write failed [%s]: %s', write_label or '?', e, exc_info=True)
        raise


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

def generate_dashboard_html(
    state: DashboardState,
    write_label: str = "",
    write_seq: Optional[int] = None,
    health_basename: Optional[str] = None,
) -> str:
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
    is_stale = time_since_data > DASHBOARD_DATA_STALE_SERVER_SEC

    status_class = "disconnected" if not state.is_connected else "stale" if is_stale else "online"
    stale_lbl = f"DATA: STALE ({DASHBOARD_DATA_STALE_SERVER_SEC}s+)"
    status_text = "CONNECTION: OFFLINE" if not state.is_connected else stale_lbl if is_stale else "CONNECTION: ONLINE"
    
    # Choose icon based on mode
    icon_emoji = "📈" if state.mode.upper() == "LIVE" else "🧪"
    chart_tf = dashboard_timeframe_minutes(state.params)
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>IB {state.mode.capitalize()} Dashboard</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>{icon_emoji}</text></svg>">
    <meta charset="UTF-8">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
    <meta http-equiv="refresh" content="30">
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
        #live-chart {{ width: 100%; height: 620px; min-height: 420px; }}
        .sub-metric {{ font-size: 0.75em; color: #7f8c8d; margin-top: 6px; }}
    </style>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js" charset="utf-8"></script>
</head>
<body>
    <div class="container">
        <a href="index.html" class="return-button">← Back to Index</a>
        
        <div class="stale-warning">⚠️ WARNING: THIS DASHBOARD MAY BE OUT OF DATE</div>

        <div class="status-bar {status_class}" id="dash-status-bar">
            <div>
                <strong id="dash-status-text" style="font-size: 1.2em;">{status_text}</strong>
                <span style="opacity: 0.8; margin-left: 10px;">[{state.mode.upper()}]</span>
                <span id="dash-last-data-line" style="margin-left: 20px; opacity: 0.9;">{f'Last Data: {state.last_data_receipt_time.strftime("%H:%M:%S")} ({int(time_since_data)}s ago)' if state.last_data_receipt_time else ''}</span>
            </div>
            <div style="text-align: right; font-size: 0.9em;">
                <div>Uptime: {format_duration(total_uptime)}</div>
                <div id="last-update" data-timestamp="{now_eastern.isoformat()}" style="display:none"></div>
                <div id="last-data-receipt" data-timestamp="{last_receipt.isoformat() if last_receipt else ''}" style="display:none"></div>
                <div id="dash-last-update-line">Last Update: {now_eastern.strftime('%Y-%m-%d %H:%M:%S')}</div>
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
        <div id="dash-positions-panel">
{render_positions_panel(state)}
        </div>

        <h2>Active Orders (all symbols, non-terminal)</h2>
        <div id="dash-orders-panel">
{render_orders_panel(state)}
        </div>

        <h2>Bar Log (Last 20 {chart_tf}-minute bars)</h2>
        <p style="font-size:0.85em;color:#64748b;margin:-8px 0 12px 0">Updates when a completed strategy bar closes (not every 1-minute chart tick). Newest entry at top.</p>
        <div id="dash-bar-log-panel">
{render_bar_log_panel(state)}
        </div>

        <h2>Completed Trades</h2>
        <div id="dash-completed-trades-panel">
{render_completed_trades_panel(state)}
        </div>

        <h2>System Logs</h2>
        <div id="dash-system-logs-panel" class="log-container">
{render_system_logs_panel(state)}
        </div>

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
"""
    if dashboard_debug_enabled() and health_basename:
        lbl = html_lib.escape(write_label or '', quote=True)
        html += f"    <!-- dashboard write_seq={write_seq} label={lbl} -->\n"
        html += client_debug_script_block(health_basename)
    status_js_name = f"{state.mode.lower()}_status.js"
    chart_json_name = os.path.basename(chart_payload_json_path(f'dashboard_{state.mode.lower()}.html'))
    tables_json_name = os.path.basename(tables_payload_json_path(f'dashboard_{state.mode.lower()}.html'))
    html += f"        const DASH_FILE_STALE_SEC = {DASHBOARD_FILE_STALE_CLIENT_SEC};\n"
    html += f"        const DASH_DATA_STALL_SEC = {DASHBOARD_DATA_STALL_CLIENT_SEC};\n"
    html += f"        const DASH_STATUS_JS = '{status_js_name}';\n"
    html += f"        const CHART_JSON_URL = '{chart_json_name}';\n"
    html += f"        const TABLES_JSON_URL = '{tables_json_name}';\n"
    html += f"        var lastChartJsonSeq = 0;\n"
    html += f"        var lastTablesJsonSeq = 0;\n"
    html += f"        var lastStatusPollTs = Date.now();\n"
    html += f"        var lastChartJsonPollTs = 0;\n"
    html += f"        var lastTablesJsonPollTs = 0;\n"
    html += """
        function parseStatusPayload(text) {
            var m = text.match(/updateStatus\\s*\\(\\s*['"][^'"]+['"]\\s*,\\s*(\\{[\\s\\S]*\\})\\s*\\)/);
            if (!m) return null;
            try { return JSON.parse(m[1]); } catch (e) { return null; }
        }

        function applyStatusPayload(st) {
            if (!st) return;
            lastStatusPollTs = Date.now();
            var lastUpdateElem = document.getElementById('last-update');
            var lastDataElem = document.getElementById('last-data-receipt');
            if (st.last_update_iso && lastUpdateElem) {
                lastUpdateElem.dataset.timestamp = st.last_update_iso;
            }
            if (st.last_data_receipt_iso && lastDataElem) {
                lastDataElem.dataset.timestamp = st.last_data_receipt_iso;
            }
            var statusText = document.getElementById('dash-status-text');
            var statusBar = document.getElementById('dash-status-bar');
            var lastDataLine = document.getElementById('dash-last-data-line');
            var lastUpdateLine = document.getElementById('dash-last-update-line');
            if (statusText && statusBar) {
                if (!st.connected) {
                    statusText.textContent = 'CONNECTION: OFFLINE';
                    statusBar.className = 'status-bar disconnected';
                } else if (st.data_stale) {
                    statusText.textContent = 'DATA: STALE (live stream)';
                    statusBar.className = 'status-bar stale';
                } else {
                    statusText.textContent = 'CONNECTION: ONLINE';
                    statusBar.className = 'status-bar online';
                }
            }
            if (lastUpdateLine && st.last_update) {
                lastUpdateLine.textContent = 'Last Update: ' + st.last_update;
            }
            if (lastDataLine && st.last_data_receipt_iso) {
                var d = new Date(st.last_data_receipt_iso);
                if (!isNaN(d.getTime())) {
                    var sec = Math.max(0, Math.round((Date.now() - d) / 1000));
                    var hh = ('0' + d.getHours()).slice(-2);
                    var mm = ('0' + d.getMinutes()).slice(-2);
                    var ss = ('0' + d.getSeconds()).slice(-2);
                    lastDataLine.textContent = 'Last Data: ' + hh + ':' + mm + ':' + ss + ' (' + sec + 's ago)';
                }
            }
        }

        function checkStaleData() {
            const lastUpdateElem = document.getElementById('last-update');
            const lastDataElem = document.getElementById('last-data-receipt');
            const warningElem = document.querySelector('.stale-warning');
            if (!lastUpdateElem || !lastDataElem || !warningElem) return;
            if (document.visibilityState !== 'visible') return;

            const now = new Date();
            const fileUpdateTs = new Date(lastUpdateElem.dataset.timestamp);
            const fileDiff = isNaN(fileUpdateTs) ? 999999 : (now - fileUpdateTs) / 1000;

            const dataTs = lastDataElem.dataset.timestamp ? new Date(lastDataElem.dataset.timestamp) : null;
            const dataDiff = dataTs && !isNaN(dataTs) ? (now - dataTs) / 1000 : 0;

            if (fileDiff > DASH_FILE_STALE_SEC) {
                var statusFresh = (Date.now() - lastStatusPollTs) / 1000 < 20;
                var chartFresh = lastChartJsonPollTs > 0
                    && (Date.now() - lastChartJsonPollTs) / 1000 < 90;
                if (statusFresh || chartFresh) {
                    document.body.classList.remove('stale-data');
                    warningElem.innerText = '';
                    return;
                }
                document.body.classList.add('stale-data');
                warningElem.innerText = '⚠️ Dashboard snapshot not updating (' + Math.round(fileDiff)
                    + 's). Bot may be running but HTML writes stopped — check paper_logs; hard-refresh (Ctrl+F5). Status: ' + DASH_STATUS_JS;
            } else if (dataDiff > DASH_DATA_STALL_SEC) {
                document.body.classList.add('stale-data');
                warningElem.innerText = '⚠️ No recent market bars in snapshot (' + Math.round(dataDiff)
                    + 's) — data stall or quiet session';
            } else {
                document.body.classList.remove('stale-data');
                warningElem.innerText = '';
            }
        }

        function pollStatusJs() {
            fetch(DASH_STATUS_JS + '?_=' + Date.now(), { cache: 'no-store' })
                .then(function(r) { return r.text(); })
                .then(function(text) {
                    applyStatusPayload(parseStatusPayload(text));
                    checkStaleData();
                })
                .catch(function() { checkStaleData(); });
        }

        checkStaleData();
        setInterval(checkStaleData, 2000);
        pollStatusJs();
        setInterval(pollStatusJs, 8000);

        function renderLiveChartFromPayload(p) {
            var el = document.getElementById('live-chart');
            if (!el) return;
            if (typeof Plotly === 'undefined') return;
            if (!p || !p.times || p.times.length < 2) {
                el.innerHTML = '<p style="padding:12px;color:#7f8c8d">No OHLC yet (history warming up)…</p>';
                return;
            }
            var tfm = p.timeframe_mins || 1;
            var zoomKey = 'dashboard_live_chart_zoom_v2';
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
            function priceYRangeForWindow(p, i0, i1) {
                var lo = Infinity, hi = -Infinity;
                function eat(v) {
                    if (v != null && isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
                }
                for (var i = i0; i <= i1; i++) {
                    if (p.h) eat(p.h[i]);
                    if (p.l) eat(p.l[i]);
                    if (p.o) eat(p.o[i]);
                    if (p.c) eat(p.c[i]);
                }
                if (p.trade_markers) {
                    for (var k = 0; k < p.trade_markers.length; k++) {
                        var m = p.trade_markers[k];
                        eat(m.entry_price); eat(m.exit_price);
                        eat(m.stop_at_open); eat(m.stop_at_close);
                        eat(m.tp_at_open); eat(m.tp_at_close);
                    }
                }
                if (p.closed_trade_lines) {
                    for (var ci = 0; ci < p.closed_trade_lines.length; ci++) {
                        var st = p.closed_trade_lines[ci].stop;
                        if (st) for (var s = 0; s < st.length; s++) eat(st[s]);
                    }
                }
                if (!isFinite(lo)) return null;
                var pad = Math.max(2, (hi - lo) * 0.08);
                return [lo - pad, hi + pad];
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
                    line: { color: '#0891b2', width: 1.5 }, mode: 'lines', xaxis: 'x4', yaxis: 'y4' });
            if (anyNonNull(p.rsi))
                traces.push({ type: 'scatter', x: p.times, y: p.rsi, name: 'RSI',
                    line: { color: '#7c3aed', width: 1.5 }, mode: 'lines', xaxis: 'x5', yaxis: 'y5' });
            if (p.trade_markers && p.trade_markers.length) {
                var entX = [], entY = [], entTxt = [];
                var exX = [], exY = [], exTxt = [];
                for (var k = 0; k < p.trade_markers.length; k++) {
                    var m = p.trade_markers[k];
                    if (m.entry_time && m.entry_price != null) {
                        entX.push(m.entry_time);
                        entY.push(m.entry_price);
                        var entExtra = ['ENTRY ' + (m.direction || ''), '@ ' + m.entry_price.toFixed(2), m.entry_time];
                        if (m.stop_at_open != null) entExtra.push('SL@open: ' + m.stop_at_open.toFixed(2));
                        if (m.tp_at_open != null) entExtra.push('TP@open: ' + m.tp_at_open.toFixed(2));
                        entTxt.push(entExtra.join('<br>'));
                    }
                    if (m.exit_time && m.exit_price != null) {
                        exX.push(m.exit_time);
                        exY.push(m.exit_price);
                        var extra = ['EXIT ' + (m.direction || ''), '@ ' + m.exit_price.toFixed(2), m.exit_time];
                        if (m.live_exit_type) extra.push(m.live_exit_type);
                        else if (m.reason) extra.push(m.reason);
                        if (m.stop_at_close != null) extra.push('SL@close: ' + m.stop_at_close.toFixed(2));
                        if (m.tp_at_close != null) extra.push('TP@close: ' + m.tp_at_close.toFixed(2));
                        if (m.pnl != null) extra.push('PnL: $' + m.pnl.toFixed(2));
                        exTxt.push(extra.join('<br>'));
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
                    shapes.push({ type: 'line', xref: 'x4', yref: 'y4', x0: x0, x1: x1, y0: p.thresholds.min_adx, y1: p.thresholds.min_adx,
                        line: { color: '#0891b2', width: 1, dash: 'dot' } });
                }
                if (p.thresholds.rsi_max_buy != null) {
                    shapes.push({ type: 'line', xref: 'x5', yref: 'y5', x0: x0, x1: x1, y0: p.thresholds.rsi_max_buy, y1: p.thresholds.rsi_max_buy,
                        line: { color: '#7c3aed', width: 1, dash: 'dot' } });
                }
                if (p.thresholds.rsi_min_sell != null) {
                    shapes.push({ type: 'line', xref: 'x5', yref: 'y5', x0: x0, x1: x1, y0: p.thresholds.rsi_min_sell, y1: p.thresholds.rsi_min_sell,
                        line: { color: '#7c3aed', width: 1, dash: 'dot' } });
                }
            }
            var layout = {
                title: 'Last ' + p.times.length + ' × ' + tfm + '-minute bars',
                dragmode: 'zoom', showlegend: true, legend: { orientation: 'h', y: 1.1 },
                xaxis: { domain:[0,1], anchor:'y', rangeslider: { visible: false }, type: 'date', showticklabels:false },
                yaxis: { title: 'Price', domain:[0.46,1.0], autorange: true },
                xaxis2: { domain:[0,1], anchor:'y2', type:'date', showticklabels:false, matches:'x' },
                yaxis2: { title: 'Vol', domain:[0.34,0.44], autorange: true },
                xaxis3: { domain:[0,1], anchor:'y3', type:'date', showticklabels:false, matches:'x' },
                yaxis3: { title: 'ATR', domain:[0.23,0.33], autorange: true },
                xaxis4: { domain:[0,1], anchor:'y4', type:'date', showticklabels:false, matches:'x' },
                yaxis4: { title: 'ADX', domain:[0.12,0.22], autorange: true },
                xaxis5: { domain:[0,1], anchor:'y5', type:'date', matches:'x' },
                yaxis5: { title: 'RSI', domain:[0.0,0.11], autorange: true },
                shapes: shapes, annotations: ann, margin: { t: 40, r: 20, b: 36, l: 56 }
            };
            if (p.active_trade_lines && p.active_trade_lines.times && p.active_trade_lines.times.length) {
                if (anyNonNull(p.active_trade_lines.stop))
                    traces.push({ type: 'scatter', x: p.active_trade_lines.times, y: p.active_trade_lines.stop, name: 'Active SL (per bar)',
                        line: { color: '#b71c1c', width: 1.6, shape: 'hv' }, mode: 'lines', xaxis: 'x', yaxis: 'y' });
                if (anyNonNull(p.active_trade_lines.tp))
                    traces.push({ type: 'scatter', x: p.active_trade_lines.times, y: p.active_trade_lines.tp, name: 'Active TP (per bar)',
                        line: { color: '#1b5e20', width: 1.6, shape: 'hv' }, mode: 'lines', xaxis: 'x', yaxis: 'y' });
            }
            if (p.closed_trade_lines && p.closed_trade_lines.length) {
                var closedColors = ['#e65100', '#6a1b9a'];
                for (var ci = 0; ci < p.closed_trade_lines.length; ci++) {
                    var cl = p.closed_trade_lines[ci];
                    var cc = closedColors[ci % closedColors.length];
                    if (cl.times && anyNonNull(cl.stop))
                        traces.push({ type: 'scatter', x: cl.times, y: cl.stop, name: (cl.label || 'Closed SL'),
                            line: { color: cc, width: 2.2, shape: 'hv' }, mode: 'lines', xaxis: 'x', yaxis: 'y' });
                    if (cl.times && anyNonNull(cl.tp))
                        traces.push({ type: 'scatter', x: cl.times, y: cl.tp, name: (cl.label || 'Closed TP') + ' TP',
                            line: { color: cc, width: 1, shape: 'hv', dash: 'dashdot' }, mode: 'lines', xaxis: 'x', yaxis: 'y' });
                }
            }
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
                if (savedZoom.y50 != null && savedZoom.y51 != null) {
                    layout.yaxis5.range = [savedZoom.y50, savedZoom.y51];
                    layout.yaxis5.autorange = false;
                }
            } else {
                var nBars = p.times.length;
                var startIdx = Math.max(0, nBars - 21);
                layout.xaxis.range = [p.times[startIdx], p.times[nBars - 1]];
                layout.xaxis.autorange = false;
                var yWin = priceYRangeForWindow(p, startIdx, nBars - 1);
                if (yWin) {
                    layout.yaxis.range = yWin;
                    layout.yaxis.autorange = false;
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
                    var y50 = ev['yaxis5.range[0]'];
                    var y51 = ev['yaxis5.range[1]'];
                    if (ev['xaxis.autorange'] || ev['yaxis.autorange'] || ev['yaxis2.autorange'] || ev['yaxis3.autorange'] || ev['yaxis4.autorange'] || ev['yaxis5.autorange']) {
                        try { localStorage.removeItem(zoomKey); } catch (_) {}
                        return;
                    }
                    if (x0 || x1 || y0 != null || y1 != null || y20 != null || y21 != null || y30 != null || y31 != null || y40 != null || y41 != null || y50 != null || y51 != null) {
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
                                y41: (y41 != null) ? y41 : ((savedZoom && savedZoom.y41) || null),
                                y50: (y50 != null) ? y50 : ((savedZoom && savedZoom.y50) || null),
                                y51: (y51 != null) ? y51 : ((savedZoom && savedZoom.y51) || null)
                            }));
                        } catch (_) {}
                    }
                });
                el.__zoomHookAttached = true;
            }
        }
        function renderLiveChart() {
            var raw = document.getElementById('chart-payload');
            if (!raw) {
                var el0 = document.getElementById('live-chart');
                if (el0) el0.innerHTML = '<p style="padding:12px;color:#7f8c8d">Chart waiting…</p>';
                return;
            }
            var p;
            try { p = JSON.parse(raw.textContent); } catch (e) {
                var el1 = document.getElementById('live-chart');
                if (el1) el1.innerHTML = '<p style="padding:12px;color:#c0392b">Chart JSON error</p>';
                return;
            }
            renderLiveChartFromPayload(p);
        }
        function pollChartJson() {
            if (typeof Plotly === 'undefined' || !CHART_JSON_URL) return;
            fetch(CHART_JSON_URL + '?_=' + Date.now(), { cache: 'no-store' })
                .then(function(r) { return r.json(); })
                .then(function(w) {
                    if (!w || !w.chart) return;
                    lastChartJsonPollTs = Date.now();
                    if (w.write_seq && w.write_seq <= lastChartJsonSeq) return;
                    lastChartJsonSeq = w.write_seq || 0;
                    renderLiveChartFromPayload(w.chart);
                })
                .catch(function(e) { console.warn('[dashboard] chart JSON poll failed:', e); });
        }
        setInterval(pollChartJson, 30000);
        setTimeout(pollChartJson, 3000);
        function pollTablesJson() {
            if (!TABLES_JSON_URL) return;
            fetch(TABLES_JSON_URL + '?_=' + Date.now(), { cache: 'no-store' })
                .then(function(r) { return r.json(); })
                .then(function(w) {
                    if (!w || !w.sections) return;
                    lastTablesJsonPollTs = Date.now();
                    if (w.write_seq && w.write_seq <= lastTablesJsonSeq) return;
                    lastTablesJsonSeq = w.write_seq || 0;
                    var s = w.sections;
                    var el;
                    if (s.positions && (el = document.getElementById('dash-positions-panel'))) el.innerHTML = s.positions;
                    if (s.orders && (el = document.getElementById('dash-orders-panel'))) el.innerHTML = s.orders;
                    if (s.bar_log && (el = document.getElementById('dash-bar-log-panel'))) el.innerHTML = s.bar_log;
                    if (s.completed_trades && (el = document.getElementById('dash-completed-trades-panel'))) el.innerHTML = s.completed_trades;
                    if (s.system_logs && (el = document.getElementById('dash-system-logs-panel'))) el.innerHTML = s.system_logs;
                })
                .catch(function(e) { console.warn('[dashboard] tables JSON poll failed:', e); });
        }
        setInterval(pollTablesJson, 15000);
        setTimeout(pollTablesJson, 2500);
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

def build_status_payload(state: DashboardState) -> Dict[str, Any]:
    """Small JSON blob for paper_status.js / live_status.js (browser freshness poll)."""
    total_pos = sum(p.get('position', 0) for p in state.positions) if state.positions else 0.0
    pnl = 0.0
    if state.account_info:
        pnl = float(state.account_info.get('RealizedPNL', 0) or 0) + float(
            state.account_info.get('UnrealizedPNL', 0) or 0
        )
    now_et = datetime.now(EASTERN)
    lr = state.last_data_receipt_time
    if lr and lr.tzinfo is None:
        lr = EASTERN.localize(lr)
    data_age = (now_et - lr).total_seconds() if lr else 0
    return {
        'mode': state.mode.upper(),
        'port': state.port,
        'connected': state.is_connected,
        'net_liquidation': float(state.account_info.get('NetLiquidation', 0))
        if state.account_info
        else 0.0,
        'pnl': pnl,
        'position': total_pos,
        'current_price': float(state.current_price or 0),
        'last_update': now_et.strftime('%Y-%m-%d %H:%M:%S'),
        'last_update_iso': now_et.isoformat(),
        'last_data_receipt_iso': lr.isoformat() if lr else None,
        'data_stale': data_age > DASHBOARD_DATA_STALE_SERVER_SEC,
        'client_id_halted': bool(getattr(state, 'client_id_trading_halted', False)),
        'client_id_expected': int(getattr(state, 'client_id_expected', 0) or 0),
        'client_id_active': list(getattr(state, 'client_id_active_on_account', []) or []),
        'client_id_violation': str(getattr(state, 'client_id_violation_detail', '') or ''),
    }


def write_dashboard_status_only(state: DashboardState, json_path: str) -> None:
    """Fast heartbeat: status.js only (no HTML / Plotly payload)."""
    prefix = "live" if state.mode.lower() == "live" else "paper"
    status_data = build_status_payload(state)
    js_content = (
        f"window.updateStatus('{prefix}', "
        f"{json.dumps(_sanitize_json_for_browser(status_data), allow_nan=False)});"
    )
    _write_text_file_robust(json_path, js_content, encoding='utf-8')


def update_dashboard(
    state: DashboardState,
    html_path: str = WEB_DASHBOARD,
    json_path: str = None,
    write_label: str = "",
) -> None:
    """
    Main entry point to update dashboard files.
    """
    import time as _time

    t0 = _time.perf_counter()
    timings: Dict[str, float] = {}
    chart_points = 0
    if state.chart_payload and state.chart_payload.get('times'):
        chart_points = len(state.chart_payload['times'])
    health_bn = os.path.basename(health_sidecar_path(html_path))
    err: Optional[str] = None
    html_bytes = 0
    write_seq = next_write_seq()

    try:
        if json_path:
            with timed_section(timings, 'write_status_js_ms'):
                write_dashboard_status_only(state, json_path)

        with timed_section(timings, 'generate_html_ms'):
            html_content = generate_dashboard_html(
                state,
                write_label=write_label,
                write_seq=write_seq,
                health_basename=health_bn if dashboard_debug_enabled() else None,
            )
        html_bytes = len(html_content.encode('utf-8'))

        with timed_section(timings, 'write_html_ms'):
            _write_text_file_robust(html_path, html_content, encoding='utf-8')

        with timed_section(timings, 'write_tables_json_ms'):
            write_tables_payload_json(state, tables_payload_json_path(html_path), write_label)

        if state.chart_payload:
            with timed_section(timings, 'write_chart_json_ms'):
                write_chart_payload_json(state, chart_payload_json_path(html_path), write_label)

    except Exception as e:
        err = str(e)
        logging.error(f"Failed to update dashboard: {e}", exc_info=True)
        raise
    finally:
        timings['total_ms'] = round((_time.perf_counter() - t0) * 1000, 1)
        log_dashboard_write(
            write_label=write_label,
            html_path=html_path,
            connected=state.is_connected,
            timings_ms=timings,
            html_bytes=html_bytes,
            chart_points=chart_points,
            last_data_receipt=state.last_data_receipt_time,
            error=err,
            write_seq=write_seq,
        )

#!/usr/bin/env python3
"""
main.py - Unified Live/Paper Trading Entry Point
================================================
Uses StrategyFactory for strategy logic and core/ modules for:
  - Connection management (core/connection.py)
  - Trade execution & exits (core/execution.py)
  - Position protection (core/protection.py)
  - Bar processing & monitoring (core/monitoring.py)
  - Account utilities (core/account.py)

Ported from ib_deployment_v4.py to preserve all production features
while maintaining the new modular architecture.
"""

import os
import sys
import signal

# Force UTF-8 encoding for console output (fixes Windows emoji issues)
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

import argparse
import pandas as pd
import numpy as np
import logging
import json
import re
import shutil
import uuid
from datetime import datetime, time
from ib_insync import IB, Future, util, MarketOrder, StopOrder, LimitOrder
from dotenv import load_dotenv
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
import warnings
import pytz
import time as time_module
import webbrowser

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from strategies.factory import StrategyFactory
from strategies.bollinger.parameters import load_params
from strategies.bollinger.filters import is_strategy_in_maintenance_window
from tools.dashboard.updates import (
    DashboardState,
    update_dashboard,
    write_dashboard_status_only,
    build_chart_payload_with_indicators,
    write_chart_payload_json,
    chart_payload_json_path,
    write_tables_payload_json,
    tables_payload_json_path,
    dashboard_timeframe_minutes,
    format_dashboard_datetime,
)
from tools.dashboard.debug import append_perf_record, dashboard_debug_enabled
from tools.safety.guards import SecurityGuard
from tools.notifications.email_service import send_email

# Core modules (ported from ib_deployment_v4.py)
from core.connection import (
    get_front_es_contract,
    connect_with_retry,
    request_historical_data_with_retry,
    disconnect_ib_quiet,
)
from core.client_id_guard import (
    assert_session_client_id,
    run_client_id_integrity_check,
)
from core.account import get_account_summary, format_duration, add_to_live_tracker, add_error
from core.execution import (
    check_entries,
    check_exits,
    _close_all_positions,
    send_composite_status_notification,
    prune_dead_brackets,
    _entry_trade_for_bracket,
    register_completed_trade_persist_hook,
    _live_exit_type,
)
from core.completed_trades import dedupe_completed_trades_near_fills
from core.protection import (cancel_all_pending, cleanup_orphaned_orders, close_orphaned_positions,
                              protect_existing_positions, check_and_recreate_tp_orders,
                              periodic_protection_check, run_reconnection_safety_sequence,
                              reconcile_positions, restore_tracked_brackets_from_ib,
                              ensure_all_bracket_stops_armed, enforce_stop_invariant,
                              consolidate_duplicate_protective_orders)
from core.shutdown import register_shutdown_checker, ShutdownRequested, is_shutdown_requested
from core.monitoring import (
    on_bar_update_handler,
    seed_data_ref_from_bars,
    configure_bar_pipeline,
    bar_pipeline_consumer,
    update_indicators,
)

EASTERN = pytz.timezone('US/Eastern')

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=pd.errors.SettingWithCopyWarning)

load_dotenv()

EMAIL_FROM = os.getenv('EMAIL_FROM')
EMAIL_TO = os.getenv('EMAIL_TO')
EMAIL_PWD = os.getenv('EMAIL_PASSWORD')

if not all([EMAIL_FROM, EMAIL_TO, EMAIL_PWD]):
    logging.warning("Missing Gmail credentials in .env. Email alerts disabled.")

# =============================================================================
# Parse Command Line Arguments
# =============================================================================
parser = argparse.ArgumentParser(
    description='Trading System Entry Point (Main)',
    formatter_class=argparse.RawTextHelpFormatter,
    epilog="""
EXAMPLES:
  Paper Trading (Bollinger):
    python main.py --strategy bollinger --port 7497 --mode PAPER --output_dir paper_logs

  Live Trading:
    python main.py --strategy bollinger --port 7496 --mode LIVE --output_dir live_logs
"""
)

parser.add_argument('--strategy', type=str, default='bollinger', help='Strategy to run (default: bollinger)')
parser.add_argument('--port', type=int, required=True, help='IB TWS/Gateway Port (e.g., 7497 for Paper, 7496 for Live)')
parser.add_argument('--mode', type=str, choices=['PAPER', 'LIVE'], default='PAPER', help='Trading Mode label')
parser.add_argument('--params', type=str, help='Path to parameter CSV file')
parser.add_argument('--output_dir', type=str, default='paper_logs', help='Directory for logs')
parser.add_argument('--dashboard', type=str, default=None, help='Filename for HTML dashboard (default: dashboard_{mode}.html)')
parser.add_argument('--client_id', type=int, default=100, help='Base Client ID for IB Connection')

args = parser.parse_args()

# Default dashboard name based on mode
if not args.dashboard:
    args.dashboard = f'dashboard_{args.mode.lower()}.html'

# Default params path (fallback)
if not args.params:
    if args.strategy.lower() == 'bollinger':
        if args.mode == 'LIVE':
            args.params = r'strategies\bollinger\parameters\live_params.csv'
        else:
            args.params = r'strategies\bollinger\parameters\paper_params.csv'
    elif args.strategy.lower() == 'trend':
        args.params = r'strategies\trend\parameters\trend_strategy_params.csv'

# Validate Output Directory
if not os.path.exists(args.output_dir):
    try:
        os.makedirs(args.output_dir)
        print(f"Created output directory: {args.output_dir}")
    except OSError as e:
        print(f"Error creating output directory: {e}")
        exit(1)

# Trade reports (unified_trade_report) resolve open_trade_timeline.jsonl from this path
os.environ["IB_BOT_OUTPUT_DIR"] = os.path.abspath(args.output_dir)

# =============================================================================
# Setup Logging
# =============================================================================
log_file = os.path.join(args.output_dir, f'{args.strategy}_{args.mode.lower()}_execution.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logging.info("=" * 60)
logging.info(f"STARTING TRADING SYSTEM - Strategy: {args.strategy.upper()}")
logging.info(f"MODE: {args.mode} | PORT: {args.port}")
logging.info("=" * 60)

# Load Parameters
try:
    if os.path.exists(args.params):
        params_dict = load_params(args.params)
        logging.info(f"Loaded parameters from {args.params}")
    else:
        logging.warning(f"Parameter file not found: {args.params}. Using empty dict.")
        params_dict = {}
except Exception as e:
    logging.error(f"Error loading parameters: {e}")
    params_dict = {}

# Initialize Strategy via Factory
try:
    strategy = StrategyFactory.get_strategy(args.strategy, params_dict)
    logging.info(f"Strategy '{args.strategy}' initialized successfully.")
except Exception as e:
    logging.critical(f"Failed to initialize strategy: {e}")
    sys.exit(1)

# Dump params for logging
param_groups = strategy.get_param_structure()
if param_groups:
    for group_name, params in param_groups.items():
        logging.info(f"\n--- {group_name} ---")
        if isinstance(params, dict):
            for name, val in params.items():
                if isinstance(val, dict) and 'value' in val:
                    logging.info(f"  {name:45} = {val['value']}")
                else:
                    logging.info(f"  {name:45} = {val}")

# =============================================================================
# IBKR CONNECTION & EXECUTION ENGINE
# =============================================================================
ib = IB()

# Global State
positions = []
data_ref = {'data': pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])}
contract = None
dashboard_state = None
guard = None
bars_obj = None
live_tracker = []
error_log = []
bar_log = []
completed_trades = []
portfolio_realized_pnl = None
last_data_receipt = {'time': datetime.now()}

# Dashboard tracking
connection_start_time = None
total_uptime_seconds = 0
dashboard_stats = {
    'trades_opened': 0, 'trades_closed': 0, 'orders_placed': 0,
    'orders_filled': 0, 'orders_cancelled': 0, 'reconnections': 0
}
seen_perm_ids = set() # Track unique executions to avoid duplicates

# Disconnect tracking
disconnect_start_time = None
disconnect_email_sent = False
DISCONNECT_ALERT_THRESHOLD = 30

# Throttle expensive per-trade HTML report sweeps — they must not block dashboard file writes.
_last_trade_report_sweep_mono = 0.0
TRADE_REPORT_SWEEP_INTERVAL_SEC = 30.0
_trade_report_sweep_task = None  # asyncio.Task while background sweep runs

# reqOpenOrders() every second can eventually stall IB Gateway; refresh at most this often.
_OPEN_ORDERS_REQ_MIN_SEC = 5.0
_last_req_open_orders_mono = 0.0
# Dashboard periodic refresh: ib.trades() is usually enough; remote open-order sync is expensive.
_DASHBOARD_OPEN_ORDERS_REMOTE_MIN_SEC = 60.0
_last_dashboard_open_orders_remote_mono = 0.0
_dashboard_refresh_lock = None  # asyncio.Lock, created in main()

# Throttle SecurityGuard in the UI loop so orphan scans do not run every second.
_LAST_GUARD_UI_MONO = 0.0
_GUARD_UI_MIN_SEC = 5.0

# Full HTML regen is expensive (~400KB); status.js heartbeat runs on its own task/executor.
_LAST_FULL_DASHBOARD_MONO = 0.0
_FULL_DASHBOARD_MIN_SEC = 30.0
_FULL_DASHBOARD_MIN_SEC_FLAT = 120.0
_CHART_REFRESH_MIN_SEC = 30.0
_LAST_CHART_REFRESH_MONO = 0.0
_status_js_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dash-status")
_dashboard_write_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dash-html")
_chart_build_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dash-chart")
_dashboard_refresh_task = None
_chart_refresh_task = None
_bot_lock_file = None
_status_heartbeat_task = None
_chart_refresh_loop_task = None
_full_dashboard_refresh_loop_task = None
_IB_SNAPSHOT_TIMEOUT_SEC = 12.0
_ui_task = None
_bar_task = None
_protection_task = None
_active_ib_client_id = None
_shutdown_watchdog_thread = None
_SHUTDOWN_GATHER_TIMEOUT_SEC = 3.0

# During CME maintenance, live bars stop; avoid hammering IB with resubscribes every ~60s.
MAINTENANCE_DATA_STALL_LOG_INTERVAL_SEC = 300
MAINTENANCE_DATA_STALL_RECONNECT_INTERVAL_SEC = 300
_last_maint_stall_log_mono = 0.0
_last_maint_stall_reconnect_mono = 0.0
_market_data_subscribed_mono = 0.0
_STARTUP_STALL_GRACE_SEC = 180.0

# Web directory
WEB_DIR = os.path.join(os.getcwd(), 'web')
if not os.path.exists(WEB_DIR):
    try: os.makedirs(WEB_DIR)
    except: pass

COMPLETED_TRADES_PATH = os.path.join(args.output_dir, "completed_trades.json")
_completed_trades_persist_sig = None


def _ib_finite_price(x):
    try:
        v = float(x)
        if not np.isfinite(v) or abs(v) > 1e12:
            return None
        return v
    except (TypeError, ValueError):
        return None


def _has_open_market_exposure(ib, contract, brackets) -> bool:
    """True when bot or IB still has a non-flat ES position / working bracket."""
    if brackets:
        for b in brackets:
            if int(b.get("direction") or 0) == 0:
                continue
            trade = _entry_trade_for_bracket(ib, contract, b)
            if trade and trade.filled():
                return True
    if contract:
        try:
            for p in ib.positions():
                if p.contract.conId == contract.conId and abs(float(p.position or 0)) >= 1:
                    return True
        except Exception:
            pass
    return False


def collect_all_ib_open_orders(ib, refresh_remote: bool = True):
    """
    All working (non-terminal) orders visible to this IB session, every symbol.
    Includes stopPrice/auxPrice so STP legs are visible on the dashboard.
    When flat, skip reqOpenOrders() — it often blocks >5s and is unnecessary.
    """
    global _last_req_open_orders_mono
    out = []
    now = time_module.monotonic()
    if refresh_remote:
        try:
            if now - _last_req_open_orders_mono >= _OPEN_ORDERS_REQ_MIN_SEC:
                ib.reqOpenOrders()
                _last_req_open_orders_mono = now
        except Exception:
            pass
    try:
        for t in ib.trades():
            if t.isDone():
                continue
            o = t.order
            c = t.contract
            lmt = _ib_finite_price(getattr(o, "lmtPrice", float("nan")))
            aux = _ib_finite_price(getattr(o, "auxPrice", float("nan")))
            stp = _ib_finite_price(getattr(o, "stopPrice", float("nan")))
            trig = stp or aux or lmt
            ost = t.orderStatus
            status = getattr(ost, "status", "") or ""
            why = (getattr(ost, "whyHeld", "") or "")[:120]
            out.append(
                {
                    "conId": getattr(c, "conId", 0),
                    "localSymbol": getattr(c, "localSymbol", None) or getattr(c, "symbol", ""),
                    "permId": getattr(o, "permId", 0) or 0,
                    "orderId": getattr(o, "orderId", 0) or 0,
                    "parentId": getattr(o, "parentId", 0) or 0,
                    "orderType": getattr(o, "orderType", ""),
                    "action": getattr(o, "action", ""),
                    "totalQuantity": getattr(o, "totalQuantity", 0),
                    "tif": getattr(o, "tif", ""),
                    "lmtPrice": lmt,
                    "auxPrice": aux,
                    "stopPrice": stp,
                    "triggerPrice": trig,
                    "status": status,
                    "whyHeld": why,
                }
            )
    except Exception as e:
        logging.debug(f"collect_all_ib_open_orders: {e}")
    out.sort(key=lambda r: (str(r.get("localSymbol") or ""), int(r.get("orderId") or 0)))
    return out


def _trade_overlay_from_open_brackets(open_brackets):
    """Entry / SL / TP in index points for the live Plotly overlay (first open bracket)."""
    if not open_brackets:
        return None
    b = open_brackets[0]
    out = {}
    ep = b.get('entry_price')
    if ep:
        try:
            out['entry_price'] = float(ep)
        except (TypeError, ValueError):
            pass
    sl = b.get('stopLoss')
    if sl is not None:
        sp = getattr(sl, 'auxPrice', None) or getattr(sl, 'stopPrice', None)
        if sp:
            try:
                out['stop'] = float(sp)
            except (TypeError, ValueError):
                pass
    tp_o = b.get('takeProfit')
    if tp_o is not None:
        lp = getattr(tp_o, 'lmtPrice', None)
        if lp:
            try:
                out['take_profit'] = float(lp)
            except (TypeError, ValueError):
                pass
    return out or None


def _active_trade_stop_tp_series(open_brackets, output_dir: str, max_points: int = 1200):
    """
    Load per-bar stop/TP history for the first active bracket from open_trade_timeline.jsonl.
    """
    if not open_brackets or not output_dir:
        return None
    b = open_brackets[0]
    entry_time = b.get("entry_time")
    direction = b.get("direction", 0)
    if entry_time is None:
        return None

    timeline_path = os.path.join(output_dir, "open_trade_timeline.jsonl")
    if not os.path.exists(timeline_path):
        return None

    target_dir = "LONG" if direction == 1 else "SHORT" if direction == -1 else None
    target_entry = entry_time.isoformat() if hasattr(entry_time, "isoformat") else str(entry_time)

    rows = []
    try:
        with open(timeline_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                rec_entry = rec.get("entry_time")
                if not rec_entry or str(rec_entry) != target_entry:
                    continue
                if target_dir and str(rec.get("direction", "")).upper() != target_dir:
                    continue
                rows.append(rec)
    except Exception:
        return None

    if not rows:
        return None

    rows = rows[-max_points:]
    times, stop_vals, tp_vals = [], [], []
    for rec in rows:
        ts = rec.get("ts")
        if not ts:
            continue
        times.append(str(ts))
        try:
            stop_vals.append(float(rec.get("stop")) if rec.get("stop") is not None else None)
        except (TypeError, ValueError):
            stop_vals.append(None)
        try:
            tp_vals.append(float(rec.get("tp")) if rec.get("tp") is not None else None)
        except (TypeError, ValueError):
            tp_vals.append(None)

    if not times:
        return None
    return {"times": times, "stop": stop_vals, "tp": tp_vals}


def _closed_trade_timelines_for_chart(output_dir: str, completed_trades: list, max_trades: int = 2):
    """Per-bar SL/TP paths for recent closed trades (from open_trade_timeline.jsonl)."""
    if not output_dir or not completed_trades:
        return []
    timeline_path = os.path.join(output_dir, "open_trade_timeline.jsonl")
    if not os.path.isfile(timeline_path):
        return []
    out = []
    for tr in list(reversed(completed_trades))[:max_trades]:
        entry_time = tr.get("entry_time")
        if entry_time is None:
            continue
        direction = tr.get("direction", "LONG")
        dir_int = 1 if str(direction).upper() == "LONG" else -1
        series = _active_trade_stop_tp_series(
            [{"entry_time": entry_time, "direction": dir_int}],
            output_dir,
        )
        if series:
            series["label"] = f"{direction} {tr.get('reason', '')}"
            out.append(series)
    return out


def _open_bracket_rows_for_dashboard(ib, contract, brackets, current_price: float):
    """Serializable open-bracket rows for the dashboard (entry time, duration, SL/TP)."""
    rows = []
    if not contract or not brackets:
        return rows
    now = datetime.now(EASTERN)
    sym = getattr(contract, "localSymbol", None) or getattr(contract, "symbol", "ES")
    for b in brackets:
        trade = _entry_trade_for_bracket(ib, contract, b)
        if not trade or not trade.filled():
            continue
        direction = int(b.get("direction") or 0)
        if direction == 0:
            continue
        entry_time = b.get("entry_time")
        ep = float(b.get("entry_price") or 0)
        if trade.fills:
            try:
                ep = float(trade.fills[0].execution.price)
            except Exception:
                pass
        sl = b.get("entry_stop_price")
        if sl is None and b.get("stopLoss") is not None:
            sl = getattr(b["stopLoss"], "auxPrice", None) or getattr(b["stopLoss"], "stopPrice", None)
        tp = b.get("entry_tp_price")
        if tp is None and b.get("takeProfit") is not None:
            tp = getattr(b["takeProfit"], "lmtPrice", None)
        dur = "N/A"
        if entry_time is not None:
            et = entry_time
            if getattr(et, "tzinfo", None) is not None:
                et_cmp = et.astimezone(EASTERN).replace(tzinfo=None)
            else:
                et_cmp = et
            dur = format_duration((now.replace(tzinfo=None) - et_cmp).total_seconds())
        rows.append({
            "localSymbol": sym,
            "direction": "LONG" if direction == 1 else "SHORT",
            "qty": abs(float(getattr(b.get("entry"), "totalQuantity", 1) or 1)),
            "entry_time": format_dashboard_datetime(entry_time),
            "duration": dur,
            "entry_price": ep,
            "stop": float(sl) if sl is not None else None,
            "take_profit": float(tp) if tp is not None else None,
            "market_price": float(current_price or 0),
        })
    return rows


def _bracket_position_rows_for_dashboard(ib, contract, brackets, current_price: float, multiplier: float = 50.0):
    """Filled bot brackets when IB portfolio() is empty or lagging."""
    rows = []
    if not contract or not brackets:
        return rows
    cp = float(current_price or 0)
    local_sym = getattr(contract, 'localSymbol', None) or getattr(contract, 'symbol', 'ES')
    sym = getattr(contract, 'symbol', 'ES')
    for bracket in brackets:
        trade = _entry_trade_for_bracket(ib, contract, bracket)
        if not trade or not trade.filled():
            continue
        direction = int(bracket.get('direction') or 0)
        if direction == 0:
            continue
        entry = bracket.get('entry')
        qty = abs(float(getattr(entry, 'totalQuantity', 0) or 0))
        if qty <= 0:
            qty = 1.0
        ep = float(bracket.get('entry_price') or 0)
        if trade.fills:
            try:
                ep = float(trade.fills[0].execution.price)
            except (TypeError, ValueError, IndexError, AttributeError):
                pass
        if ep <= 0:
            continue
        mkt = cp if cp > 0 else ep
        unreal = (mkt - ep) * direction * multiplier * qty
        rows.append({
            'symbol': sym,
            'localSymbol': local_sym,
            'position': direction * qty,
            'avgCost': ep,
            'avgPrice': ep,
            'marketPrice': mkt,
            'marketValue': mkt * multiplier * qty * direction,
            'realizedPNL': 0.0,
            'unrealizedPNL': unreal,
            'source': 'bot',
        })
    return rows


def _merge_positions_for_dashboard(ib, contract, brackets, portfolio_rows, current_price: float):
    """IB portfolio rows plus bot-tracked fills missing from portfolio()."""
    merged = list(portfolio_rows)
    ib_by_sym = {}
    for row in portfolio_rows:
        if abs(float(row.get('position') or 0)) > 0:
            key = row.get('localSymbol') or row.get('symbol') or ''
            ib_by_sym[key] = float(row['position'])
    for row in _bracket_position_rows_for_dashboard(ib, contract, brackets, current_price):
        key = row.get('localSymbol') or row.get('symbol') or ''
        if key in ib_by_sym and abs(ib_by_sym[key]) >= 1:
            continue
        merged.append(row)
    return merged


def _portfolio_row_for_dashboard(p, current_price: float, multiplier: float = 50.0) -> dict:
    """Normalize IB PortfolioItem for the dashboard (futures avg cost → price in points)."""
    sym = getattr(p.contract, 'symbol', '') or ''
    local_sym = getattr(p.contract, 'localSymbol', sym)
    pos_qty = float(p.position or 0)
    ac = float(p.averageCost or 0)
    avg_pts = ac
    if ac > 20000 and pos_qty != 0:
        avg_pts = ac / (multiplier * abs(pos_qty))
    mkt = float(getattr(p, 'marketPrice', 0) or 0)
    if mkt <= 0 and current_price > 0:
        mkt = float(current_price)
    return {
        'symbol': sym,
        'localSymbol': local_sym,
        'position': pos_qty,
        'avgCost': ac,
        'avgPrice': avg_pts,
        'marketPrice': mkt,
        'marketValue': p.marketValue,
        'realizedPNL': getattr(p, 'realizedPNL', getattr(p, 'realizedPnl', 0)) or 0,
        'unrealizedPNL': getattr(p, 'unrealizedPNL', getattr(p, 'unrealizedPnl', 0)) or 0,
    }


def _serialize_trade_record(trade: dict) -> dict:
    out = dict(trade)
    for k in ("entry_time", "exit_time"):
        v = out.get(k)
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
    return out


def _deserialize_trade_record(trade: dict) -> dict:
    out = dict(trade)
    for k in ("entry_time", "exit_time"):
        v = out.get(k)
        if isinstance(v, str):
            try:
                out[k] = datetime.fromisoformat(v)
            except ValueError:
                pass
    return out


def load_persisted_completed_trades(path: str, max_keep: int = 1000) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            return []
        parsed = [_deserialize_trade_record(x) for x in raw if isinstance(x, dict)]
        return parsed[-max_keep:]
    except Exception as e:
        logging.warning(f"Failed to load persisted completed trades: {e}")
        return []


def backfill_completed_trades_from_log(log_path: str, max_keep: int = 1000) -> list:
    """
    One-time bootstrap for historical debug visibility.
    Parses TRADE CLOSE lines from existing execution log into completed_trades format.
    """
    if not os.path.exists(log_path):
        return []
    recs = []
    pat = re.compile(
        r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\w+\s+TRADE CLOSE:\s+"
        r"(?P<reason>.*?)\s+@\s+\$(?P<exit>[0-9\.\-]+),\s+PNL:\s+\$(?P<pnl>[0-9,\.\-]+)"
    )
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = pat.match(line.strip())
                if not m:
                    continue
                try:
                    ts = datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S")
                    exit_px = float(m.group("exit"))
                    pnl = float(m.group("pnl").replace(",", ""))
                    reason = m.group("reason").strip()
                    recs.append({
                        "exit_time": ts,
                        "entry_time": None,
                        "direction": "N/A",
                        "qty": 1,
                        "entry_price": 0.0,
                        "exit_price": exit_px,
                        "pnl": pnl,
                        "r_multiple": 0.0,
                        "reason": reason,
                        "live_exit_type": _live_exit_type(reason),
                        "duration": "Backfilled",
                        "report_url": "",
                        "stop_at_close": None,
                        "tp_at_close": None,
                    })
                except Exception:
                    continue
    except Exception as e:
        logging.warning(f"Failed to backfill completed trades from log: {e}")
        return []
    return recs[-max_keep:]


def backfill_completed_trades_from_live_csv(csv_path: str, max_keep: int = 1000, multiplier: float = 50.0) -> list:
    """
    Fallback bootstrap from execution audit CSV when TRADE CLOSE lines are missing.
    Reconstructs round-trips via FIFO matching of BOT/SLD fills.
    """
    if not os.path.exists(csv_path):
        return []

    def _parse_row(line: str):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 8:
            return None
        try:
            return {
                "ts": datetime.strptime(parts[0], "%Y-%m-%d %H:%M:%S"),
                "symbol": parts[1],
                "side": parts[2].upper(),
                "price": float(parts[3]),
                "qty": float(parts[4]),
            }
        except Exception:
            return None

    rows = []
    try:
        with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("Time,Symbol,Side,"):
                    continue
                rec = _parse_row(line)
                if rec and rec["qty"] > 0:
                    rows.append(rec)
    except Exception as e:
        logging.warning(f"Failed to parse execution CSV for trade backfill: {e}")
        return []

    long_entries = []
    short_entries = []
    current_day = None
    trades = []

    for r in rows:
        d = r["ts"].date()
        if current_day is None:
            current_day = d
        elif d != current_day:
            # Avoid stale carry-over across sessions/days for reconstructed matches.
            long_entries.clear()
            short_entries.clear()
            current_day = d

        side = r["side"]
        if side == "BOT":
            if short_entries:
                entry = short_entries.pop()  # Prefer nearest open (LIFO) for cleaner pairing.
                qty = min(entry["qty"], r["qty"])
                pnl = (entry["price"] - r["price"]) * multiplier * qty
                trades.append({
                    "exit_time": r["ts"],
                    "entry_time": entry["ts"],
                    "direction": "SHORT",
                    "qty": qty,
                    "entry_price": entry["price"],
                    "exit_price": r["price"],
                    "pnl": float(pnl),
                    "r_multiple": 0.0,
                    "reason": "Backfilled (CSV Match)",
                    "duration": "Backfilled",
                    "report_url": "",
                    "stop_at_close": None,
                    "tp_at_close": None,
                })
                rem = entry["qty"] - qty
                if rem > 0:
                    short_entries.append({**entry, "qty": rem})
                rem_close = r["qty"] - qty
                if rem_close > 0:
                    long_entries.append({**r, "qty": rem_close})
            else:
                long_entries.append(r)
        elif side == "SLD":
            if long_entries:
                entry = long_entries.pop()  # Prefer nearest open (LIFO) for cleaner pairing.
                qty = min(entry["qty"], r["qty"])
                pnl = (r["price"] - entry["price"]) * multiplier * qty
                trades.append({
                    "exit_time": r["ts"],
                    "entry_time": entry["ts"],
                    "direction": "LONG",
                    "qty": qty,
                    "entry_price": entry["price"],
                    "exit_price": r["price"],
                    "pnl": float(pnl),
                    "r_multiple": 0.0,
                    "reason": "Backfilled (CSV Match)",
                    "duration": "Backfilled",
                    "report_url": "",
                    "stop_at_close": None,
                    "tp_at_close": None,
                })
                rem = entry["qty"] - qty
                if rem > 0:
                    long_entries.append({**entry, "qty": rem})
                rem_close = r["qty"] - qty
                if rem_close > 0:
                    short_entries.append({**r, "qty": rem_close})
            else:
                short_entries.append(r)

    return trades[-max_keep:]


def merge_completed_trade_lists(primary: list, secondary: list, max_keep: int = 1000) -> list:
    """Deduplicate and merge two completed trade lists, unioning richer fields per fill."""
    combined = list(primary or []) + list(secondary or [])
    return dedupe_completed_trades_near_fills(combined, window_sec=120, max_keep=max_keep)


def bootstrap_completed_trades(log_path: str, csv_path: str, max_keep: int = 1000) -> list:
    """Merge log-derived closes with execution-csv reconstructed closes."""
    log_trades = backfill_completed_trades_from_log(log_path, max_keep=max_keep * 2)
    csv_trades = backfill_completed_trades_from_live_csv(csv_path, max_keep=max_keep * 2)
    if not log_trades and not csv_trades:
        return []

    merged = []
    seen = set()
    for t in (log_trades + csv_trades):
        et = t.get("exit_time")
        ep = t.get("exit_price")
        pnl = t.get("pnl")
        key = (
            et.isoformat() if hasattr(et, "isoformat") else str(et),
            round(float(ep), 6) if ep is not None else None,
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(t)

    merged.sort(key=lambda x: x.get("exit_time") or datetime.min)
    merged = dedupe_completed_trades_near_fills(merged, window_sec=120, max_keep=max_keep)
    return merged


def persist_completed_trades(path: str, trades: list, max_keep: int = 1000) -> None:
    """
    Write completed trades atomically when possible. On Windows, antivirus or another
    handle on the destination can make os.replace fail with WinError 5; we retry and
    fall back to shutil.copyfile so the bot does not crash on shutdown persist.
    """
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    payload = [_serialize_trade_record(t) for t in trades[-max_keep:]]
    basename = os.path.basename(path)
    tmp = os.path.join(d, f".{basename}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        last_err = None
        for attempt in range(25):
            try:
                os.replace(tmp, path)
                return
            except (PermissionError, OSError) as e:
                win = getattr(e, "winerror", None)
                if isinstance(e, PermissionError) or win in (5, 32) or getattr(e, "errno", None) in (13, 16):
                    last_err = e
                    time_module.sleep(min(0.03 * (attempt + 1), 0.35))
                    continue
                raise
        try:
            shutil.copyfile(tmp, path)
        except Exception:
            if last_err:
                raise last_err from None
            raise
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def maybe_persist_completed_trades(path: str, trades: list) -> None:
    global _completed_trades_persist_sig
    n = len(trades)
    last_exit = ""
    report_count = 0
    last_report_url = ""
    if n:
        v = trades[-1].get("exit_time")
        last_exit = v.isoformat() if hasattr(v, "isoformat") else str(v)
        last_report_url = str(trades[-1].get("report_url") or "")
        report_count = sum(1 for t in trades if t.get("report_url"))
    sig = (n, last_exit, report_count, last_report_url)
    if sig == _completed_trades_persist_sig:
        return
    persist_completed_trades(path, trades)
    _completed_trades_persist_sig = sig


def ensure_completed_trade_reports(trades: list, strategy_obj, data_df: pd.DataFrame = None) -> int:
    """
    Generate missing HTML reports for completed trades.
    Returns number of report links newly populated.
    """
    if not trades or strategy_obj is None or not hasattr(strategy_obj, "generate_trade_report"):
        return 0
    trades_dir = os.path.join(WEB_DIR, "trades")
    os.makedirs(trades_dir, exist_ok=True)
    generated = 0
    for tr in trades:
        reason = str(tr.get("reason") or "")
        needs_report = not tr.get("report_url") or "Backfilled" in reason
        if not needs_report:
            continue
        try:
            rep = strategy_obj.generate_trade_report(dict(tr), data_df, trades_dir)
            if rep:
                tr["report_url"] = f"trades/{os.path.basename(rep)}"
                generated += 1
        except Exception:
            continue
    return generated


def error_handler(reqId, errorCode, errorString, contract_obj=None):
    """Handle IB Errors."""
    if errorCode in [2104, 2106, 2158]:
        return
    logging.error(f"IB Error {reqId} {errorCode}: {errorString}")
    add_error(error_log, f"IB Error {errorCode}: {errorString}")
    if dashboard_state:
        dashboard_state.error_log.append({
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'error': f"IB Error {errorCode}: {errorString}"
        })

ib.errorEvent += error_handler


def log_execution(trade, fill):
    """Log executions to live_trades.csv with FIFO trade pairing."""
    global open_fills_log, completed_trades
    try:
        csv_path = os.path.join(args.output_dir, 'live_trades.csv')
        file_exists = os.path.isfile(csv_path)

        et_tz = pytz.timezone('US/Eastern')
        if fill.time:
            ft = fill.time if fill.time.tzinfo else pytz.utc.localize(fill.time)
            fill_time = ft.astimezone(et_tz).strftime('%Y-%m-%d %H:%M:%S')
            fill_dt = ft.astimezone(et_tz)
        else:
            fill_dt = datetime.now(et_tz)
            fill_time = fill_dt.strftime('%Y-%m-%d %H:%M:%S')

        symbol = fill.contract.localSymbol if fill.contract else 'ES'
        side = fill.execution.side if hasattr(fill, 'execution') else 'UNKNOWN'
        price = fill.execution.price if hasattr(fill, 'execution') else 0.0
        shares = abs(fill.execution.shares) if hasattr(fill, 'execution') else 0
        comm = fill.commissionReport.commission if fill.commissionReport else 0.0
        realized = fill.commissionReport.realizedPNL if fill.commissionReport else 0.0
        perm_id = fill.execution.permId if hasattr(fill, 'execution') else 0

        # Deduplication Check
        global seen_perm_ids
        if perm_id and perm_id in seen_perm_ids:
            logging.debug(f"Skipping duplicate execution log for PermID: {perm_id}")
            return
        if perm_id:
            seen_perm_ids.add(perm_id)
            if len(seen_perm_ids) > 1000: pass # basic cleanup if needed

        # 3. Log execution to CSV (always, for audit trail)
        with open(csv_path, 'a', newline='') as f:
            if not file_exists:
                f.write("Time,Symbol,Side,Price,Qty,Commission,RealizedPNL,PermID\n")
            f.write(f"{fill_time},{symbol},{side},{price},{shares},{comm},{realized},{perm_id}\n")
            f.flush()

        logging.info(f"💾 Execution Logged: {side} {shares} @ {price} (Comm: {comm})")

    except Exception as e:
        logging.error(f"Failed to log execution: {e}")

ib.execDetailsEvent += log_execution


def check_disconnect_status():
    """Check disconnect status and send email alerts."""
    global disconnect_start_time, disconnect_email_sent

    if not ib.isConnected():
        if disconnect_start_time is None:
            disconnect_start_time = datetime.now()
            disconnect_email_sent = False
            logging.warning("API disconnected - tracking time")

        if not disconnect_email_sent:
            dur = (datetime.now() - disconnect_start_time).total_seconds()
            if dur >= DISCONNECT_ALERT_THRESHOLD:
                dur_str = format_duration(dur)
                pos_info = f"{len(positions)} tracked position(s)" if positions else "No tracked positions"
                msg = (f"API DISCONNECT ALERT\n{'='*50}\n\nDisconnected for: {dur_str}\n"
                       f"Open Positions: {pos_info}\n\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                custom_send_email("API DISCONNECTED ⚠️", msg)
                disconnect_email_sent = True
                add_to_live_tracker(live_tracker, 'warning', f"Disconnect alert ({dur_str})")

    elif disconnect_start_time is not None:
        dur = (datetime.now() - disconnect_start_time).total_seconds()
        dur_str = format_duration(dur)
        msg = (f"API RECONNECTION\n{'='*50}\n\nRestored after: {dur_str}\n"
               f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        custom_send_email("API RECONNECTED", msg)
        logging.info(f"Reconnection email sent (was disconnected {dur_str})")
        disconnect_start_time = None
        disconnect_email_sent = False


        disconnect_start_time = None
        disconnect_email_sent = False


def _log_ib_client_session(connected_client_id: int) -> None:
    """Record active API clientId; must match --client_id (no rotation)."""
    global _active_ib_client_id
    _active_ib_client_id = connected_client_id
    if connected_client_id != args.client_id:
        logging.critical(
            "Connected clientId %s != configured %s — aborting (single clientId policy).",
            connected_client_id,
            args.client_id,
        )
        sys.exit(1)
    logging.info("IB session clientId=%s (exclusive)", connected_client_id)


def _sync_dashboard_heartbeat_fields() -> None:
    """Copy fast-moving fields into dashboard_state for status.js (no IB calls)."""
    if not dashboard_state:
        return
    dashboard_state.is_connected = ib.isConnected()
    dashboard_state.bar_log = bar_log[-20:]
    dashboard_state.last_data_receipt_time = last_data_receipt['time']
    if data_ref['data'] is not None and not data_ref['data'].empty:
        dashboard_state.current_price = float(data_ref['data']['close'].iloc[-1])


async def _write_status_js_async(state, status_path: str, timeout: float = 5.0) -> None:
    """Fast heartbeat for browser stale-banner poll (dedicated executor, no HTML)."""
    if state is None or not status_path or _shutdown_requested:
        return
    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(_status_js_executor, write_dashboard_status_only, state, status_path),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logging.warning("status.js heartbeat timed out (%.0fs)", timeout)
    except Exception as e:
        logging.warning("status.js heartbeat failed: %s", e)


async def _write_dashboard_files_async(state, html_path, status_path, label: str, timeout: float = 45.0):
    """
    Run HTML generation and disk writes on a dedicated worker thread so status.js heartbeat
    never shares the default asyncio thread pool with heavy chart/HTML work.
    """
    if state is None or _shutdown_requested:
        return
    loop = asyncio.get_running_loop()
    t0 = time_module.perf_counter()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(
                _dashboard_write_executor,
                update_dashboard,
                state,
                html_path,
                status_path,
                label,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logging.error("Dashboard write timed out (%.0fs): %s", timeout, label)
        if dashboard_debug_enabled():
            append_perf_record({
                'event': 'dashboard_write_timeout',
                'write_label': label,
                'timeout_sec': timeout,
                'async_wait_ms': round((time_module.perf_counter() - t0) * 1000, 1),
            })
    except Exception as e:
        logging.error("Dashboard write failed (%s): %s", label, e, exc_info=True)
    else:
        if dashboard_debug_enabled():
            append_perf_record({
                'event': 'dashboard_async_complete',
                'write_label': label,
                'async_wait_ms': round((time_module.perf_counter() - t0) * 1000, 1),
            })


async def _refresh_dashboard_chart_payload(state) -> bool:
    """Rebuild Plotly payload from in-memory bars only (no IB). Keeps last good chart on failure."""
    if state is None or data_ref['data'] is None or data_ref['data'].empty:
        return False
    prior = state.chart_payload
    _chart_tf = dashboard_timeframe_minutes(state.params)
    loop = asyncio.get_running_loop()
    try:
        payload = await asyncio.wait_for(
            loop.run_in_executor(
                _chart_build_executor,
                build_chart_payload_with_indicators,
                data_ref['data'],
                strategy,
                480,
                _chart_tf,
                completed_trades,
                state.params,
            ),
            timeout=45.0,
        )
    except asyncio.TimeoutError:
        logging.warning("Chart payload build timed out (45s); keeping last chart snapshot")
        return prior is not None
    except Exception as e:
        logging.warning("Chart payload build skipped (%s): %s", type(e).__name__, e)
        return prior is not None
    if not payload:
        return prior is not None
    tp_sl_series = _active_trade_stop_tp_series(positions, args.output_dir)
    if tp_sl_series:
        payload['active_trade_lines'] = tp_sl_series
    closed_lines = _closed_trade_timelines_for_chart(
        args.output_dir, completed_trades, max_trades=2,
    )
    if closed_lines:
        payload['closed_trade_lines'] = closed_lines
    state.chart_payload = payload
    state.trade_overlay = _trade_overlay_from_open_brackets(positions)
    return True


def _sync_dashboard_table_fields_blocking() -> None:
    """Refresh table panel fields from in-memory bot state + fast IB cache (no reqOpenOrders)."""
    if not dashboard_state:
        return
    dashboard_state.live_tracker = live_tracker[-200:]
    dashboard_state.bar_log = bar_log[-20:]
    dashboard_state.completed_trades = list(completed_trades[-1000:])
    cp = float(dashboard_state.current_price or 0)
    dashboard_state.open_brackets = _open_bracket_rows_for_dashboard(
        ib, contract, positions, cp,
    )
    if ib.isConnected():
        try:
            dashboard_state.active_orders = collect_all_ib_open_orders(
                ib, refresh_remote=False,
            )
        except Exception as e:
            logging.debug("Dashboard orders sync skipped: %s", e)
    if positions:
        pass  # detailed rows refreshed on full IB snapshot; keep last good rows
    elif ib.isConnected() and contract:
        try:
            ib_rows = []
            for p in ib.positions():
                if p.contract.conId != contract.conId:
                    continue
                if abs(float(p.position or 0)) < 1:
                    continue
                ib_rows.append(_portfolio_row_for_dashboard(p, cp))
            if ib_rows:
                dashboard_state.positions = ib_rows
            else:
                dashboard_state.positions = []
        except Exception as e:
            logging.debug("Dashboard IB positions sync skipped: %s", e)
            dashboard_state.positions = []
    else:
        dashboard_state.positions = []


async def _write_chart_json_async(state, html_path: str, label: str, timeout: float = 15.0) -> bool:
    """Fast chart-only sidecar write (~100KB JSON, no HTML regen)."""
    if state is None or _shutdown_requested:
        return False
    loop = asyncio.get_running_loop()
    chart_path = chart_payload_json_path(html_path)
    try:
        await asyncio.wait_for(
            loop.run_in_executor(
                _chart_build_executor,
                write_chart_payload_json,
                state,
                chart_path,
                label,
            ),
            timeout=timeout,
        )
        return True
    except asyncio.TimeoutError:
        logging.error("Dashboard chart JSON timed out (%.0fs): %s", timeout, label)
        return False
    except Exception as e:
        logging.error("Dashboard chart JSON failed (%s): %s", label, e, exc_info=True)
        return False


async def _write_tables_json_async(state, html_path: str, label: str, timeout: float = 15.0) -> bool:
    """Fast tables sidecar write (positions, orders, trades, logs)."""
    if state is None or _shutdown_requested:
        return False
    loop = asyncio.get_running_loop()
    tables_path = tables_payload_json_path(html_path)
    try:
        await asyncio.wait_for(
            loop.run_in_executor(
                _chart_build_executor,
                write_tables_payload_json,
                state,
                tables_path,
                label,
            ),
            timeout=timeout,
        )
        return True
    except asyncio.TimeoutError:
        logging.error("Dashboard tables JSON timed out (%.0fs): %s", timeout, label)
        return False
    except Exception as e:
        logging.error("Dashboard tables JSON failed (%s): %s", label, e, exc_info=True)
        return False


async def _run_chart_dashboard_refresh(dash_path: str, status_path: str):
    """Lightweight chart refresh — writes chart JSON only (no 370KB HTML regen)."""
    global _LAST_CHART_REFRESH_MONO
    if not dashboard_state or _shutdown_requested:
        return
    t0 = time_module.monotonic()
    try:
        _sync_dashboard_heartbeat_fields()
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(_chart_build_executor, _sync_dashboard_table_fields_blocking),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logging.debug("Dashboard table field sync timed out (5s)")
        except Exception as e:
            logging.debug("Dashboard table field sync skipped: %s", e)
        if data_ref['data'] is not None and not data_ref['data'].empty:
            dashboard_state.current_price = float(data_ref['data']['close'].iloc[-1])
        built = await _refresh_dashboard_chart_payload(dashboard_state)
        if not built and not dashboard_state.chart_payload:
            logging.info("Dashboard chart refresh skipped: no bar data yet")
        else:
            await _write_chart_json_async(dashboard_state, dash_path, "chart refresh")
        await _write_tables_json_async(dashboard_state, dash_path, "tables refresh")
        _LAST_CHART_REFRESH_MONO = time_module.monotonic()
        logging.info(
            "Dashboard chart refresh OK in %.1fs",
            time_module.monotonic() - t0,
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logging.warning("Chart dashboard refresh failed: %s", e, exc_info=True)


async def _run_chart_dashboard_refresh_loop():
    """Dedicated 30s chart JSON refresh — independent of full HTML / IB snapshot scheduling."""
    dash_path = os.path.join(WEB_DIR, args.dashboard)
    status_path = os.path.join(WEB_DIR, f"{args.mode.lower()}_status.js")
    while not _shutdown_requested:
        try:
            if dashboard_state and ib.isConnected():
                await _run_chart_dashboard_refresh(dash_path, status_path)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.warning("Chart refresh loop error: %s", e, exc_info=True)
        try:
            await _interruptible_sleep(_CHART_REFRESH_MIN_SEC)
        except asyncio.CancelledError:
            raise


def _apply_dashboard_ib_snapshot(force_refresh: bool) -> None:
    """Blocking IB snapshot for dashboard — must run in a worker thread, not on the asyncio loop."""
    global _last_dashboard_open_orders_remote_mono
    if not dashboard_state or not ib.isConnected():
        return
    has_exposure = _has_open_market_exposure(ib, contract, positions)
    refresh_remote_orders = force_refresh
    if not has_exposure:
        refresh_remote_orders = False
    else:
        now_remote = time_module.monotonic()
        if (
            not refresh_remote_orders
            and (now_remote - _last_dashboard_open_orders_remote_mono)
            >= _DASHBOARD_OPEN_ORDERS_REMOTE_MIN_SEC
        ):
            refresh_remote_orders = True
            _last_dashboard_open_orders_remote_mono = now_remote
    if data_ref['data'] is not None and not data_ref['data'].empty:
        dashboard_state.current_price = float(data_ref['data']['close'].iloc[-1])
    else:
        dashboard_state.current_price = 0.0
    try:
        dashboard_state.account_info = get_account_summary(
            ib,
            data_ref['data'],
            contract,
            portfolio_realized_pnl,
        )
    except Exception as e:
        logging.warning("get_account_summary failed: %s", e)
    if guard and contract:
        try:
            flattened = guard.check_daily_pnl(
                ib,
                contract,
                dashboard_state.account_info,
                positions,
            )
            if flattened:
                add_to_live_tracker(
                    live_tracker, 'ERROR',
                    "EMERGENCY FLATTEN - Limits Breached",
                )
        except Exception as e:
            logging.error("check_daily_pnl failed: %s", e, exc_info=True)
    cp = dashboard_state.current_price
    if contract and positions and has_exposure:
        try:
            prune_dead_brackets(
                ib, contract, positions, live_tracker,
            )
        except Exception as e:
            logging.warning("Dashboard prune_dead_brackets skipped: %s", e, exc_info=True)
    pos_data = []
    if has_exposure:
        try:
            for p in ib.portfolio():
                if not contract or p.contract.symbol == contract.symbol:
                    pos_data.append(_portfolio_row_for_dashboard(p, cp))
        except Exception as e:
            logging.warning("ib.portfolio() snapshot failed for dashboard: %s", e)
    try:
        dashboard_state.positions = (
            _merge_positions_for_dashboard(ib, contract, positions, pos_data, cp)
            if has_exposure
            else []
        )
    except Exception as e:
        logging.warning("merge dashboard positions failed: %s", e)
        dashboard_state.positions = pos_data
    if has_exposure:
        try:
            dashboard_state.active_orders = collect_all_ib_open_orders(
                ib,
                refresh_remote_orders,
            )
        except Exception as e:
            logging.warning("collect_all_ib_open_orders failed: %s", e)
    else:
        dashboard_state.active_orders = []
    dashboard_state.open_brackets = _open_bracket_rows_for_dashboard(
        ib, contract, positions, dashboard_state.current_price,
    )


async def _run_light_dashboard_refresh(
    dash_path: str,
    status_path: str,
    label: str = "light refresh",
) -> None:
    """Refresh dashboard HTML from in-memory state only — no blocking IB calls."""
    global _LAST_FULL_DASHBOARD_MONO
    if not dashboard_state or _shutdown_requested:
        return
    _sync_dashboard_heartbeat_fields()
    dashboard_state.live_tracker = live_tracker[-200:]
    dashboard_state.bar_log = bar_log[-20:]
    dashboard_state.completed_trades = list(completed_trades[-1000:])
    dashboard_state.is_connected = ib.isConnected()
    dashboard_state.total_uptime_seconds = total_uptime_seconds
    dashboard_state.connection_start_time = connection_start_time
    dashboard_state.trade_overlay = _trade_overlay_from_open_brackets(positions)
    if ib.isConnected():
        try:
            acct = await asyncio.wait_for(
                asyncio.to_thread(
                    get_account_summary,
                    ib,
                    data_ref['data'],
                    contract,
                    portfolio_realized_pnl,
                ),
                timeout=8.0,
            )
            if acct:
                dashboard_state.account_info = acct
        except asyncio.TimeoutError:
            logging.debug("Light refresh account snapshot timed out (8s); keeping cached values")
        except Exception as e:
            logging.debug("Light refresh account snapshot skipped: %s", e)
    _sync_dashboard_table_fields_blocking()
    if not positions:
        dashboard_state.positions = []
    await _write_dashboard_files_async(
        dashboard_state, dash_path, status_path, label,
    )
    _LAST_FULL_DASHBOARD_MONO = time_module.monotonic()


async def _run_full_dashboard_refresh_loop():
    """Dedicated periodic HTML refresh — flat book uses light refresh (no IB blocking)."""
    dash_path = os.path.join(WEB_DIR, args.dashboard)
    status_path = os.path.join(WEB_DIR, f"{args.mode.lower()}_status.js")
    while not _shutdown_requested:
        try:
            if dashboard_state and ib.isConnected():
                likely_flat = not positions
                force = bool(getattr(dashboard_state, 'request_full_refresh', False))
                if likely_flat and not force:
                    await _run_light_dashboard_refresh(dash_path, status_path)
                else:
                    await _run_full_dashboard_refresh(dash_path, status_path)
            elif dashboard_state and not _shutdown_requested:
                _sync_dashboard_heartbeat_fields()
                await _write_dashboard_files_async(
                    dashboard_state, dash_path, status_path, "disconnected snapshot",
                )
                _LAST_FULL_DASHBOARD_MONO = time_module.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.warning("Full dashboard refresh loop error: %s", e, exc_info=True)
        likely_flat = not positions
        interval = _FULL_DASHBOARD_MIN_SEC_FLAT if likely_flat else _FULL_DASHBOARD_MIN_SEC
        try:
            await _interruptible_sleep(interval)
        except asyncio.CancelledError:
            raise


async def _run_dashboard_status_heartbeat():
    """Write paper_status.js every second on a dedicated thread — never blocked by full HTML refresh."""
    status_path = os.path.join(WEB_DIR, f"{args.mode.lower()}_status.js")
    while not _shutdown_requested:
        try:
            if dashboard_state:
                _sync_dashboard_heartbeat_fields()
                await _write_status_js_async(dashboard_state, status_path)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.warning("Dashboard status heartbeat loop error: %s", e)
        try:
            await asyncio.sleep(1 if ib.isConnected() else 5)
        except asyncio.CancelledError:
            raise


async def _run_full_dashboard_refresh(dash_path: str, status_path: str):
    """Background full refresh: IB snapshot (threaded) + HTML write."""
    global _LAST_FULL_DASHBOARD_MONO, _last_trade_report_sweep_mono, _trade_report_sweep_task
    if _dashboard_refresh_lock is None:
        return
    if _dashboard_refresh_lock.locked():
        logging.debug("Dashboard full refresh skipped (previous still in flight)")
        return
    async with _dashboard_refresh_lock:
        if not dashboard_state or not ib.isConnected() or _shutdown_requested:
            return
        force_refresh = bool(getattr(dashboard_state, 'request_full_refresh', False))
        likely_flat = not positions
        if likely_flat and not force_refresh:
            await _run_light_dashboard_refresh(dash_path, status_path)
            return
        try:
            await asyncio.wait_for(
                asyncio.to_thread(_apply_dashboard_ib_snapshot, force_refresh),
                timeout=_IB_SNAPSHOT_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            logging.warning(
                "Dashboard IB snapshot timed out (%.0fs); falling back to light refresh",
                _IB_SNAPSHOT_TIMEOUT_SEC,
            )
            await _run_light_dashboard_refresh(dash_path, status_path, "light refresh (IB timeout)")
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.error("Dashboard IB snapshot failed: %s", e, exc_info=True)
            await _run_light_dashboard_refresh(dash_path, status_path, "light refresh (IB error)")
            return
        try:
            dashboard_state.is_connected = ib.isConnected()
            dashboard_state.total_uptime_seconds = total_uptime_seconds
            dashboard_state.connection_start_time = connection_start_time
            dashboard_state.last_data_receipt_time = last_data_receipt['time']
            dashboard_state.live_tracker = live_tracker[-200:]
            dashboard_state.bar_log = bar_log[-20:]
            dashboard_state.completed_trades = list(completed_trades[-1000:])
            dashboard_state.trade_overlay = _trade_overlay_from_open_brackets(positions)

            if _shutdown_requested:
                return
            dashboard_state.request_full_refresh = False
            await _write_dashboard_files_async(
                dashboard_state, dash_path, status_path, "post-IB refresh"
            )
            _LAST_FULL_DASHBOARD_MONO = time_module.monotonic()

            try:
                maybe_persist_completed_trades(COMPLETED_TRADES_PATH, completed_trades)
            except Exception as e:
                logging.error("completed_trades persist failed: %s", e, exc_info=True)

            now_mono = time_module.monotonic()
            if now_mono - _last_trade_report_sweep_mono >= TRADE_REPORT_SWEEP_INTERVAL_SEC:
                _last_trade_report_sweep_mono = now_mono
                if _trade_report_sweep_task is None or _trade_report_sweep_task.done():

                    def _sweep_trade_reports_blocking():
                        try:
                            ensure_completed_trade_reports(
                                completed_trades, strategy, data_ref['data']
                            )
                            maybe_persist_completed_trades(
                                COMPLETED_TRADES_PATH, completed_trades
                            )
                        except Exception as ex:
                            logging.error("Trade report sweep failed: %s", ex, exc_info=True)

                    _trade_report_sweep_task = asyncio.create_task(
                        asyncio.to_thread(_sweep_trade_reports_blocking)
                    )
                else:
                    logging.debug(
                        "Trade-report sweep skipped (previous background sweep still running)"
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.error(
                "Dashboard full refresh failed (status heartbeat continues): %s",
                e,
                exc_info=True,
            )


async def update_ui_periodically():
    """Run throttled SecurityGuard checks (dashboard refresh has its own dedicated loop)."""
    global _LAST_GUARD_UI_MONO
    if _dashboard_refresh_lock is None:
        _dashboard_refresh_lock = asyncio.Lock()
    while not _shutdown_requested:
        connected = ib.isConnected()
        try:
            now_g = time_module.monotonic()
            if guard and connected and (now_g - _LAST_GUARD_UI_MONO >= _GUARD_UI_MIN_SEC):
                _LAST_GUARD_UI_MONO = now_g
                try:
                    guard.check_connection(ib, positions)
                    if contract:
                        guard.check_orphaned_orders(ib, contract, positions)
                except Exception as e:
                    logging.error("Security guard UI check failed: %s", e, exc_info=True)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.error("UI update / Guard check failed: %s", e, exc_info=True)
        finally:
            if _shutdown_requested:
                break
            try:
                await asyncio.sleep(1 if ib.isConnected() else 5)
            except asyncio.CancelledError:
                raise


def ensure_connected_and_subscribed():
    """Re-subscribe to market data after reconnection.
    
    CRITICAL: Must clear old event handlers before creating new subscription.
    If cancelHistoricalData fails (common during reconnection), the old bars_obj
    event handler survives and both old+new fire on each bar, causing double entries.
    """
    global bars_obj, contract
    if not ib.isConnected() or is_shutdown_requested():
        return

    try:
        if bars_obj is not None:
            # CRITICAL: Clear event handlers FIRST, before cancelling the subscription.
            # This prevents the old handler from firing even if cancel fails.
            try:
                bars_obj.updateEvent.clear()
                logging.info("Cleared old bar event handlers")
            except Exception as e:
                logging.warning(f"Failed to clear old event handlers: {e}")

            try:
                logging.info("Cancelling previous market data subscription...")
                ib.cancelHistoricalData(bars_obj)
            except Exception as e:
                logging.warning(f"Failed to cancel old bars (handlers already cleared): {e}")

        if is_shutdown_requested():
            raise ShutdownRequested()
        bars_obj = request_historical_data_with_retry(ib, contract)
        if is_shutdown_requested():
            raise ShutdownRequested()
        bars_obj.updateEvent += lambda bars, hasNewBar: on_bar_update_handler(
            bars, hasNewBar, strategy=strategy, ib=ib, contract=contract,
            data_ref=data_ref, positions=positions, completed_trades=completed_trades,
            live_tracker=live_tracker, bar_log=bar_log, dashboard_state=dashboard_state,
            send_email_fn=custom_send_email, output_dir=args.output_dir,
            last_data_receipt=last_data_receipt
        )
        logging.info(f"Subscribed to market data ({len(bars_obj)} bars)")
        seed_data_ref_from_bars(bars_obj, data_ref)
        last_data_receipt['time'] = datetime.now()
        global _market_data_subscribed_mono
        _market_data_subscribed_mono = time_module.monotonic()
    except ShutdownRequested:
        logging.info("Market data subscribe aborted (shutdown requested)")
        raise
    except Exception as e:
        logging.error(f"Failed to subscribe to data: {e}")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_lock_pid(lock_path: str):
    try:
        with open(lock_path, 'r', encoding='utf-8') as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _acquire_single_instance_lock() -> None:
    """Refuse to start if another bot is already running for this mode/port."""
    global _bot_lock_file
    lock_path = os.path.join(args.output_dir, f"bot_{args.mode.lower()}_{args.port}.lock")
    os.makedirs(args.output_dir, exist_ok=True)

    stale = _read_lock_pid(lock_path)
    if stale and not _pid_alive(stale):
        logging.warning("Removing stale bot lock (pid %s no longer running)", stale)
        try:
            os.remove(lock_path)
        except OSError:
            pass

    handle = open(lock_path, 'a+', encoding='utf-8')
    try:
        if sys.platform == 'win32':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, PermissionError) as e:
        handle.close()
        other = _read_lock_pid(lock_path)
        if other and _pid_alive(other):
            logging.critical(
                "Another bot instance is already running for %s on port %s (pid %s). Exiting.",
                args.mode,
                args.port,
                other,
            )
            sys.exit(1)
        logging.critical(
            "Could not acquire bot lock (%s). Close other bots or delete %s",
            e,
            lock_path,
        )
        sys.exit(1)
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    _bot_lock_file = handle
    logging.info("Bot instance lock acquired: %s (pid %s)", lock_path, os.getpid())


# =============================================================================
# Cooperative shutdown (Ctrl+C must not call ib.disconnect in the signal handler)
# =============================================================================
_shutdown_requested = False
_run_loop = None
_main_task = None
_previous_sigint_handler = None
_previous_sigterm_handler = None


def _disconnect_ib_sync():
    """Disconnect IB in a worker thread (used from asyncio finally)."""
    try:
        if ib.isConnected():
            logging.info("Disconnecting from TWS...")
            ib.disconnect()
    except Exception as e:
        logging.warning("IB disconnect during shutdown: %s", e)


async def _interruptible_sleep(seconds: float, step: float = 0.25) -> None:
    """Sleep in short slices so _shutdown_requested / task cancel is picked up quickly."""
    if seconds <= 0:
        return
    end = time_module.monotonic() + seconds
    while not _shutdown_requested:
        remaining = end - time_module.monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(step, remaining))


def _shutdown_watchdog_thread_fn():
    """Thread watchdog: cancel main even when sync IB work blocks the asyncio loop."""
    while not _shutdown_requested:
        time_module.sleep(0.25)
    _cancel_all_background_tasks()
    task = _main_task
    loop = _run_loop
    if loop is not None and loop.is_running() and task is not None and not task.done():
        try:
            loop.call_soon_threadsafe(task.cancel)
        except Exception:
            pass
    if loop is None or not loop.is_running():
        return
    for pending in asyncio.all_tasks(loop):
        if not pending.done():
            try:
                loop.call_soon_threadsafe(pending.cancel)
            except Exception:
                pass


def _start_shutdown_watchdog():
    global _shutdown_watchdog_thread
    if _shutdown_watchdog_thread is not None and _shutdown_watchdog_thread.is_alive():
        return
    _shutdown_watchdog_thread = threading.Thread(
        target=_shutdown_watchdog_thread_fn,
        name="shutdown-watchdog",
        daemon=True,
    )
    _shutdown_watchdog_thread.start()


def _cancel_all_background_tasks():
    """Cancel asyncio worker tasks so Ctrl+C does not wait on dashboard/IB work."""
    for task in (
        _ui_task,
        _bar_task,
        _protection_task,
        _status_heartbeat_task,
        _dashboard_refresh_task,
        _chart_refresh_loop_task,
        _full_dashboard_refresh_loop_task,
        _trade_report_sweep_task,
    ):
        if task is not None and not task.done():
            task.cancel()


def _handle_shutdown_signal(signum=None, frame=None):
    """First Ctrl+C: set flag + cancel tasks. Second: force exit. Never log here (deadlock risk)."""
    global _shutdown_requested
    if _shutdown_requested:
        try:
            sys.stderr.write("\nForced exit\n")
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(130)
    _shutdown_requested = True
    try:
        sys.stderr.write("\nShutdown requested (Ctrl+C again to force quit)...\n")
        sys.stderr.flush()
    except Exception:
        pass
    _cancel_all_background_tasks()
    loop = _run_loop
    task = _main_task
    if loop is not None and loop.is_running() and task is not None and not task.done():
        try:
            loop.call_soon_threadsafe(task.cancel)
        except Exception:
            pass


def _install_shutdown_handlers():
    global _previous_sigint_handler, _previous_sigterm_handler
    if hasattr(signal, 'SIGINT'):
        _previous_sigint_handler = signal.signal(signal.SIGINT, _handle_shutdown_signal)
    if hasattr(signal, 'SIGTERM'):
        _previous_sigterm_handler = signal.signal(signal.SIGTERM, _handle_shutdown_signal)


# =============================================================================
def make_custom_email_fn():
    strat_tag = "BB" if 'boll' in args.strategy.casefold() else ("TR" if 'trend' in args.strategy.casefold() else "BOT")
    mode_tag = "L" if args.mode.casefold() == 'live' else "P"
    prefix = f"[{strat_tag}-{mode_tag}]"
    
    def custom_send_email(subj, body, attachment_path=None, attachment_paths=None):
        cleaned_subj = subj.replace("[BB] ", "").replace("[TR] ", "").replace("BB Strategy - ", "")
        final_subj = f"{prefix} {cleaned_subj}"
        return send_email(final_subj, body, attachment_path, attachment_paths)
    return custom_send_email

custom_send_email = make_custom_email_fn()

# =============================================================================
# MAIN LOOP
# =============================================================================
async def main():
    global contract, dashboard_state, guard, bars_obj
    global connection_start_time, total_uptime_seconds, portfolio_realized_pnl
    global last_unrealized_alert_tier, last_heartbeat_time
    global _last_maint_stall_log_mono, _last_maint_stall_reconnect_mono
    global _shutdown_requested
    last_unrealized_alert_tier = 0
    last_heartbeat_time = datetime.now()

    protection_task = None
    ui_task = None
    bar_task = None
    global _status_heartbeat_task, _dashboard_refresh_task, _ui_task, _bar_task, _protection_task
    global _shutdown_watchdog_thread, _chart_refresh_loop_task, _full_dashboard_refresh_loop_task

    try:
        _acquire_single_instance_lock()
        _start_shutdown_watchdog()
        # Connect (waits until Gateway is up — normal if bot starts before nightly reboot finishes)
        connected_client_id = await connect_with_retry(
            ib, '127.0.0.1', args.port, base_client_id=args.client_id, mode=args.mode,
        )
        _log_ib_client_session(connected_client_id)
        assert_session_client_id(ib, args.client_id)
        connection_start_time = datetime.now()
        add_to_live_tracker(live_tracker, 'info', 'Connected to Interactive Brokers API')

        def _persist_completed_trades_immediate():
            global _completed_trades_persist_sig
            persist_completed_trades(COMPLETED_TRADES_PATH, completed_trades)
            n = len(completed_trades)
            last_exit = ""
            report_count = 0
            last_report_url = ""
            if n:
                v = completed_trades[-1].get("exit_time")
                last_exit = v.isoformat() if hasattr(v, "isoformat") else str(v)
                last_report_url = str(completed_trades[-1].get("report_url") or "")
                report_count = sum(1 for t in completed_trades if t.get("report_url"))
            _completed_trades_persist_sig = (n, last_exit, report_count, last_report_url)

        register_completed_trade_persist_hook(_persist_completed_trades_immediate)

        def _restore_completed_trades_at_startup():
            live_csv = os.path.join(args.output_dir, "live_trades.csv")
            restored = load_persisted_completed_trades(COMPLETED_TRADES_PATH, max_keep=1000)
            bootstrap = bootstrap_completed_trades(log_file, live_csv, max_keep=1000)
            if restored:
                merged = merge_completed_trade_lists(restored, bootstrap, max_keep=1000)
                maybe_persist_completed_trades(COMPLETED_TRADES_PATH, merged)
                return merged, (
                    f"Restored {len(restored)} persisted completed trades (merged -> {len(merged)})"
                )
            backfilled = bootstrap
            if backfilled:
                persist_completed_trades(COMPLETED_TRADES_PATH, backfilled, max_keep=1000)
                return backfilled, f"Backfilled {len(backfilled)} completed trades from execution log + CSV"
            return None, None

        # Restore completed trades off the event loop so Ctrl+C is not blocked for ~8s.
        restored_trades, restore_msg = await asyncio.to_thread(_restore_completed_trades_at_startup)
        if _shutdown_requested:
            return
        if restored_trades is not None:
            completed_trades[:] = restored_trades
        if restore_msg:
            logging.info(restore_msg)
        logging.info("Resolving front ES contract...")
        if _shutdown_requested:
            return
        # Auto-resolve front-month ES contract (must run on IB event-loop thread — not thread-safe)
        try:
            contract = get_front_es_contract(ib)
        except ShutdownRequested:
            return
        logging.info("Resolved front ES contract: %s exp %s", contract.localSymbol, contract.lastTradeDateOrContractMonth)
        cancel_all_pending(ib, contract, live_tracker)
        try:
            reconcile_positions(
                ib, contract, positions, live_tracker,
                completed_trades=completed_trades, send_email_fn=custom_send_email,
                data=data_ref['data'],
            )
        except Exception as e:
            logging.error(f"Startup reconciliation failed: {e}")

        # --- SELF-HEALING STARTUP ---

        # Initialize Dashboard
        dashboard_state = DashboardState(
            mode=args.mode, port=args.port,
            contract_symbol=contract.localSymbol,
            connection_start_time=datetime.now(),
            is_connected=True, params=params_dict,
            last_data_receipt_time=last_data_receipt['time']
        )

        # Initialize Security Guard
        guard = SecurityGuard(params_dict)
        dashboard_state.security_guard = guard

        bar_pipeline_q = asyncio.Queue(maxsize=512)
        configure_bar_pipeline(
            bar_pipeline_q,
            {
                "strategy": strategy,
                "ib": ib,
                "contract": contract,
                "data_ref": data_ref,
                "positions": positions,
                "completed_trades": completed_trades,
                "live_tracker": live_tracker,
                "bar_log": bar_log,
                "dashboard_state": dashboard_state,
                "send_email_fn": custom_send_email,
                "output_dir": args.output_dir,
            },
        )
        bar_task = asyncio.create_task(bar_pipeline_consumer())
        _bar_task = bar_task

        # Subscribe to account updates
        ib.reqAccountSummary()

        def on_account_summary(val):
            if dashboard_state:
                try:
                    v = val.value
                    # Do NOT merge RealizedPNL / UnrealizedPNL here: accountSummaryEvent fires **per tag**,
                    # so mixing one fresh tag with stale others makes total_pnl nonsense and false flatten.
                    # Those fields come from `get_account_summary()` in `update_ui_periodically` instead.
                    if val.tag in ['NetLiquidation', 'TotalCashValue', 'BuyingPower',
                                   'EquityWithLoanValue']:
                        try:
                            v = float(v)
                        except Exception:
                            pass
                        dashboard_state.account_info[val.tag] = v
                except Exception:
                    pass

        ib.accountSummaryEvent += on_account_summary

        # Portfolio PnL callback (most accurate source)
        def on_portfolio_update(item):
            global portfolio_realized_pnl, last_unrealized_alert_tier
            if item.contract.symbol == 'ES' and item.contract.conId == contract.conId:
                portfolio_realized_pnl = (getattr(item, 'realizedPNL', None) or
                                          getattr(item, 'realizedPnl', None))
                unrealized = getattr(item, 'unrealizedPNL', getattr(item, 'unrealizedPnl', None))
                if unrealized is not None:
                    if unrealized < 0:
                        tier = int(-unrealized // 100) * 100
                        if tier >= 500 and tier > last_unrealized_alert_tier:
                            last_unrealized_alert_tier = tier
                            custom_send_email(f"🚨W: -${tier}", f"Unrealized PNL target crossed: -${tier}\nDetails:\n{item}")
                    elif unrealized > -100:
                        last_unrealized_alert_tier = 0  # Reset when largely recovered

        ib.updatePortfolioEvent += on_portfolio_update

        # Subscribe to market data with retry (IB calls — event-loop thread only)
        try:
            ensure_connected_and_subscribed()
        except ShutdownRequested:
            return
        if _shutdown_requested:
            return

        await _interruptible_sleep(2)
        if _shutdown_requested:
            return

        # Startup protection checks (indicators first — setup_position needs atr)
        logging.info("Running startup protection checks...")
        if _shutdown_requested:
            return
        run_client_id_integrity_check(
            ib,
            args.client_id,
            contract,
            send_email_fn=custom_send_email,
            live_tracker=live_tracker,
            dashboard_state=dashboard_state,
            label="startup",
        )
        update_indicators(strategy, data_ref['data'])
        restored_brackets = restore_tracked_brackets_from_ib(
            ib, contract, positions, strategy, data_ref['data'], live_tracker,
        )
        if _shutdown_requested:
            return
        if restored_brackets:
            logging.info("Restored %s open bracket(s) from IB after restart", restored_brackets)
        from core.protection import adopt_ib_protection_for_position
        try:
            for pos in [p for p in ib.positions() if p.contract.symbol == "ES" and p.position != 0]:
                adopt_ib_protection_for_position(
                    ib, positions, pos, strategy=strategy, data=data_ref['data'], live_tracker=live_tracker,
                )
        except Exception as e:
            logging.error("Startup adopt pass failed: %s", e)
        armed = ensure_all_bracket_stops_armed(ib, contract, positions, live_tracker)
        if armed:
            logging.info("Startup: verified/armed stop on %s tracked bracket(s)", armed)
        n_consolidated = consolidate_duplicate_protective_orders(ib, contract, positions, live_tracker)
        if n_consolidated:
            logging.info("Startup: cancelled %s duplicate protective order(s)", n_consolidated)
        protect_existing_positions(
            ib, contract, positions, strategy, data_ref['data'], live_tracker,
        )
        if _shutdown_requested:
            return
        close_orphaned_positions(ib, contract, positions, live_tracker)
        if _shutdown_requested:
            return
        check_and_recreate_tp_orders(
            ib, contract, positions, strategy, data_ref['data'], live_tracker,
        )
        enforce_stop_invariant(ib, positions, strategy, data_ref['data'], live_tracker, contract=contract)
        if _shutdown_requested:
            return

        # Generate initial dashboard
        dash_path = os.path.join(WEB_DIR, args.dashboard)
        status_path = os.path.join(WEB_DIR, f"{args.mode.lower()}_status.js")
        if dashboard_state and not _shutdown_requested:
            if data_ref['data'] is not None and not data_ref['data'].empty:
                dashboard_state.current_price = float(data_ref['data']['close'].iloc[-1])
            await _refresh_dashboard_chart_payload(dashboard_state)
            await _write_dashboard_files_async(
                dashboard_state, dash_path, status_path, "startup"
            )
            _LAST_CHART_REFRESH_MONO = time_module.monotonic()
        add_to_live_tracker(live_tracker, 'info', 'Dashboard initialized')

        # Open dashboard in browser (HTTP — file:// breaks status/chart JSON polling)
        try:
            dash_name = os.path.basename(dash_path)
            webbrowser.open(f'http://127.0.0.1:8000/{dash_name}')
        except Exception:
            pass

        # Start async tasks
        _status_heartbeat_task = asyncio.create_task(_run_dashboard_status_heartbeat())
        _chart_refresh_loop_task = asyncio.create_task(_run_chart_dashboard_refresh_loop())
        _full_dashboard_refresh_loop_task = asyncio.create_task(_run_full_dashboard_refresh_loop())
        ui_task = asyncio.create_task(update_ui_periodically())
        _ui_task = ui_task
        protection_task = asyncio.create_task(
            periodic_protection_check(
                ib, contract, positions, strategy, data_ref['data'], live_tracker,
                send_email_fn=custom_send_email, close_all_fn=_close_all_positions,
                completed_trades=completed_trades, expected_client_id=args.client_id,
                dashboard_state=dashboard_state,
            )
        )
        _protection_task = protection_task

        def _deferred_completed_trade_reports():
            try:
                n = ensure_completed_trade_reports(completed_trades, strategy, data_ref['data'])
                if n:
                    persist_completed_trades(COMPLETED_TRADES_PATH, completed_trades, max_keep=1000)
                    logging.info(f"Background: generated {n} missing completed-trade reports")
            except Exception as ex:
                logging.error("Deferred completed-trade report sweep failed: %s", ex, exc_info=True)

        asyncio.create_task(asyncio.to_thread(_deferred_completed_trade_reports))

        custom_send_email("START", f"Bot started in {args.mode} mode on port {args.port}\n"
                   f"Contract: {contract.localSymbol}\nStrategy: {args.strategy}")

        # Main loop
        while not _shutdown_requested:
            try:
                if _shutdown_requested:
                    break
                check_disconnect_status()

                if not ib.isConnected():
                    # Track disconnect
                    if connection_start_time:
                        now_eastern = datetime.now(EASTERN)
                        # Ensure connection_start_time is offset-aware
                        if connection_start_time.tzinfo is None:
                            connection_start_time = EASTERN.localize(connection_start_time)
                        total_uptime_seconds += (now_eastern - connection_start_time).total_seconds()
                        connection_start_time = None
                    add_to_live_tracker(live_tracker, 'warning', 'Connection lost - reconnecting')
                    dashboard_stats['reconnections'] += 1

                    logging.warning(
                        "Connection lost (expected during nightly IB Gateway reboot) — reconnecting "
                        "on clientId %s...",
                        args.client_id,
                    )
                    if _shutdown_requested:
                        break
                    await disconnect_ib_quiet(ib)
                    connected_client_id = await connect_with_retry(
                        ib, '127.0.0.1', args.port, base_client_id=args.client_id, mode=args.mode,
                    )
                    _log_ib_client_session(connected_client_id)
                    assert_session_client_id(ib, args.client_id)

                    connection_start_time = datetime.now(EASTERN)
                    add_to_live_tracker(live_tracker, 'info', 'Reconnected')

                    ensure_connected_and_subscribed()

                    # Post-reconnection safety
                    await _interruptible_sleep(2)
                    if _shutdown_requested:
                        break
                    run_reconnection_safety_sequence(
                        ib, contract, positions, strategy,
                        data_ref['data'], live_tracker, completed_trades,
                        expected_client_id=args.client_id,
                        send_email_fn=custom_send_email,
                        dashboard_state=dashboard_state,
                    )

                    # Force an immediate dashboard update after reconnection
                    if dashboard_state and not _shutdown_requested:
                        dashboard_state.is_connected = True
                        dashboard_state.connection_start_time = connection_start_time
                        dash_path = os.path.join(WEB_DIR, args.dashboard)
                        dashboard_state.last_data_receipt_time = last_data_receipt['time']
                        dash_path = os.path.join(WEB_DIR, args.dashboard)
                        status_path = os.path.join(WEB_DIR, f"{args.mode.lower()}_status.js")
                        await _write_dashboard_files_async(
                            dashboard_state, dash_path, status_path, "post-reconnect"
                        )
                        add_to_live_tracker(live_tracker, 'info', 'Dashboard refreshed after reconnection')

                # 15-Min Heartbeat Status (Enhanced with Charts)
                now = datetime.now()
                if (now - last_heartbeat_time).total_seconds() >= 900:
                    last_heartbeat_time = now
                    if positions and not _shutdown_requested:
                        send_composite_status_notification(
                            ib, positions, data_ref['data'],
                            dashboard_state.account_info if dashboard_state else {},
                            custom_send_email,
                        )
                    # (Removed 'else' block to skip flat status emails)


                # Data liveness check
                time_since = (now - last_data_receipt['time']).total_seconds()
                subscribed_ago = (
                    time_module.monotonic() - _market_data_subscribed_mono
                    if _market_data_subscribed_mono
                    else _STARTUP_STALL_GRACE_SEC + 1
                )
                if time_since > 60 and subscribed_ago >= _STARTUP_STALL_GRACE_SEC:
                    now_eastern = datetime.now(EASTERN)
                    in_maint = is_strategy_in_maintenance_window(strategy, now_eastern)
                    if in_maint and not positions:
                        mono = time_module.monotonic()
                        if mono - _last_maint_stall_log_mono >= MAINTENANCE_DATA_STALL_LOG_INTERVAL_SEC:
                            logging.info(
                                "No live bars for %.1fs during maintenance window; "
                                "deferring aggressive data resubscribe (next log/reconnect in %ds)",
                                time_since,
                                MAINTENANCE_DATA_STALL_RECONNECT_INTERVAL_SEC,
                            )
                            add_to_live_tracker(
                                live_tracker,
                                'info',
                                f'Maintenance data pause ({time_since:.0f}s, flat)',
                            )
                            _last_maint_stall_log_mono = mono
                        if mono - _last_maint_stall_reconnect_mono >= MAINTENANCE_DATA_STALL_RECONNECT_INTERVAL_SEC:
                            logging.info(
                                "Maintenance window: periodic data resubscribe (%.1fs without live bars)",
                                time_since,
                            )
                            ensure_connected_and_subscribed()
                            _last_maint_stall_reconnect_mono = mono
                    else:
                        if in_maint and positions:
                            logging.warning(
                                "⚠️ DATA STALLED during maintenance with open position(s)! "
                                "No bars for %.1fs. Restarting data...",
                                time_since,
                            )
                            add_to_live_tracker(
                                live_tracker,
                                'warning',
                                'Data stalled during maintenance (position open)',
                            )
                        else:
                            logging.warning(
                                f"⚠️ DATA STALLED! No bars for {time_since:.1f}s. Restarting data..."
                            )
                            add_to_live_tracker(live_tracker, 'warning', 'Data Stalled - Forcing Restart')
                        ensure_connected_and_subscribed()
                        if time_since > 180 and positions:
                            msg = (
                                f"No tick data received for {time_since:.1f}s!\n"
                                f"Open brackets: {len(positions)}\n"
                                f"Time: {now.strftime('%H:%M:%S')}"
                            )
                            custom_send_email("🚨 STALL: POS OPEN!", msg)
                        last_data_receipt['time'] = now

                await _interruptible_sleep(10)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                error_msg = f"Error in main loop: {e}"
                logging.error(error_msg)
                add_error(error_log, error_msg)
                add_to_live_tracker(live_tracker, 'error', error_msg)
                await _interruptible_sleep(5)

    except asyncio.CancelledError:
        logging.info("Main task cancelled, shutting down...")
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        add_to_live_tracker(live_tracker, 'error', f"Fatal: {e}")
        import traceback
        traceback.print_exc()
    finally:
        _shutdown_requested = True
        logging.info("Cleaning up...")
        _cancel_all_background_tasks()
        pending = [
            t
            for t in (
                ui_task,
                bar_task,
                protection_task,
                _status_heartbeat_task,
                _dashboard_refresh_task,
                _chart_refresh_loop_task,
                _full_dashboard_refresh_loop_task,
                _trade_report_sweep_task,
            )
            if t is not None and not t.done()
        ]
        if pending:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=_SHUTDOWN_GATHER_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                logging.warning(
                    "Background task shutdown timed out (%.0fs); forcing disconnect",
                    _SHUTDOWN_GATHER_TIMEOUT_SEC,
                )
        for ex in (_status_js_executor, _dashboard_write_executor, _chart_build_executor):
            try:
                ex.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                ex.shutdown(wait=False)
        try:
            await asyncio.wait_for(asyncio.to_thread(_disconnect_ib_sync), timeout=8.0)
        except asyncio.TimeoutError:
            logging.warning("IB disconnect timed out (8s) during shutdown")
        except Exception as e:
            logging.warning("IB disconnect failed during shutdown: %s", e)
        try:
            custom_send_email("STOP", f"Bot stopped in {args.mode} mode")
        except Exception as e:
            logging.warning("STOP email failed during shutdown: %s", e)
        logging.info("Shutdown complete.")


if __name__ == '__main__':
    util.patchAsyncio()
    _install_shutdown_handlers()
    register_shutdown_checker(lambda: _shutdown_requested)
    _start_shutdown_watchdog()

    async def _run_main():
        global _run_loop, _main_task
        _run_loop = asyncio.get_running_loop()
        _main_task = asyncio.current_task()
        await main()

    try:
        asyncio.run(_run_main())
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
        print("Program interrupted by user.")

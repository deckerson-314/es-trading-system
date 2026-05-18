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
import atexit

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
import warnings
import pytz
import time as time_module
import webbrowser

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from strategies.factory import StrategyFactory
from strategies.bollinger.parameters import load_params
from tools.dashboard.updates import (
    DashboardState,
    update_dashboard,
    build_chart_payload_from_df,
    dashboard_timeframe_minutes,
)
from tools.safety.guards import SecurityGuard
from tools.notifications.email_service import send_email

# Core modules (ported from ib_deployment_v4.py)
from core.connection import get_front_es_contract, connect_with_retry, request_historical_data_with_retry
from core.account import get_account_summary, format_duration, add_to_live_tracker, add_error
from core.execution import (
    check_entries,
    check_exits,
    _close_all_positions,
    send_composite_status_notification,
    prune_dead_brackets,
    _entry_trade_for_bracket,
)
from core.protection import (cancel_all_pending, cleanup_orphaned_orders, close_orphaned_positions,
                              protect_existing_positions, check_and_recreate_tp_orders,
                              periodic_protection_check, run_reconnection_safety_sequence,
                              reconcile_positions)
from core.monitoring import (
    update_indicators,
    on_bar_update_handler,
    configure_bar_pipeline,
    bar_pipeline_consumer,
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

# Throttle SecurityGuard in the UI loop so orphan scans do not run every second.
_LAST_GUARD_UI_MONO = 0.0
_GUARD_UI_MIN_SEC = 5.0

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


def collect_all_ib_open_orders(ib):
    """
    All working (non-terminal) orders visible to this IB session, every symbol.
    Includes stopPrice/auxPrice so STP legs are visible on the dashboard.
    """
    global _last_req_open_orders_mono
    out = []
    now = time_module.monotonic()
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
                    recs.append({
                        "exit_time": ts,
                        "entry_time": None,
                        "direction": "N/A",
                        "qty": 1,
                        "entry_price": 0.0,
                        "exit_price": exit_px,
                        "pnl": pnl,
                        "r_multiple": 0.0,
                        "reason": m.group("reason"),
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


def _completed_trade_quality_score(tr: dict) -> int:
    """Prefer real execution records over log/CSV backfills when collapsing duplicates."""
    score = 0
    if tr.get("entry_time") is not None:
        score += 4
    if tr.get("entry_price") not in (None, 0, 0.0):
        score += 3
    if tr.get("report_url"):
        score += 2
    if tr.get("stop_at_close") is not None:
        score += 1
    if tr.get("tp_at_close") is not None:
        score += 1
    if tr.get("params_snapshot"):
        score += 3
    reason = str(tr.get("reason") or "")
    if "Backfilled" in reason:
        score -= 3
    return score


def _normalize_trade_ts(val):
    if val is None:
        return None
    try:
        ts = pd.Timestamp(val)
        if ts.tzinfo is not None:
            ts = ts.tz_convert("US/Eastern").tz_localize(None)
        return ts.to_pydatetime()
    except Exception:
        return None


def _direction_compatible(a: str, b: str) -> bool:
    da = str(a or "").strip().upper()
    db = str(b or "").strip().upper()
    if not da or da == "N/A" or not db or db == "N/A":
        return True
    return da == db


def _same_fill_event(a: dict, b: dict, window_sec: float = 120.0) -> bool:
    """
    True when two completed_trade rows likely describe the same broker fill.
    Log lines use second resolution; CSV and live paths use different timestamps
    a few seconds apart for the same exit.
    """
    ea = _normalize_trade_ts(a.get("exit_time"))
    eb = _normalize_trade_ts(b.get("exit_time"))
    if ea is None or eb is None:
        return False
    if abs((ea - eb).total_seconds()) > window_sec:
        return False
    try:
        pa = round(float(a.get("exit_price")), 2)
        pb = round(float(b.get("exit_price")), 2)
    except (TypeError, ValueError):
        return False
    if pa != pb:
        return False
    if not _direction_compatible(a.get("direction"), b.get("direction")):
        return False
    eta = _normalize_trade_ts(a.get("entry_time"))
    etb = _normalize_trade_ts(b.get("entry_time"))
    if eta is not None and etb is not None:
        if abs((eta - etb).total_seconds()) > 1800:
            return False
    return True


def dedupe_completed_trades_near_fills(trades: list, window_sec: float = 120.0, max_keep: int = 1000) -> list:
    """Collapse near-duplicate rows from CSV + log backfill + live close for the same exit."""
    if not trades:
        return []
    items = list(trades)
    n = len(items)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        for j in range(i + 1, n):
            if _same_fill_event(items[i], items[j], window_sec):
                union(i, j)

    groups: dict = {}
    for i in range(n):
        r = find(i)
        groups.setdefault(r, []).append(items[i])

    out = [max(grp, key=_completed_trade_quality_score) for grp in groups.values()]
    out.sort(key=lambda x: _normalize_trade_ts(x.get("exit_time")) or datetime.min)
    return out[-max_keep:]


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


def merge_completed_trade_lists(primary: list, secondary: list, max_keep: int = 1000) -> list:
    """Deduplicate and merge two completed trade lists, preferring richer records."""

    by_key = {}
    for t in (primary or []) + (secondary or []):
        et = t.get("exit_time")
        ep = t.get("exit_price")
        pnl = t.get("pnl")
        key = (
            et.isoformat() if hasattr(et, "isoformat") else str(et),
            round(float(ep), 6) if ep is not None else None,
        )
        existing = by_key.get(key)
        if existing is None or _completed_trade_quality_score(t) > _completed_trade_quality_score(existing):
            by_key[key] = t
    merged = list(by_key.values())
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
        if tr.get("report_url"):
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


async def _write_dashboard_files_async(state, html_path, status_path, label: str, timeout: float = 90.0):
    """
    Run HTML/JS generation and disk writes on a worker thread. The UI coroutine awaits this, but
    the event loop can still run IB socket I/O and on_bar_update_handler while the thread works,
    which prevents the dashboard from appearing frozen when chart/HTML work is slow.
    """
    if state is None:
        return
    try:
        await asyncio.wait_for(
            asyncio.to_thread(update_dashboard, state, html_path, status_path),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logging.error("Dashboard write timed out (%.0fs): %s", timeout, label)
    except Exception as e:
        logging.error("Dashboard write failed (%s): %s", label, e, exc_info=True)


async def update_ui_periodically():
    """Periodically update the dashboard files."""
    global _last_trade_report_sweep_mono, _trade_report_sweep_task, _LAST_GUARD_UI_MONO
    while True:
        connected = ib.isConnected()
        try:
            if dashboard_state:
                dash_path = os.path.join(WEB_DIR, args.dashboard)
                status_path = os.path.join(WEB_DIR, f"{args.mode.lower()}_status.js")
                # Refresh HTML + status.js first so embedded `last-update` advances even if IB
                # calls below stall; avoids a silent disk freeze when the gateway wedges.
                dashboard_state.is_connected = connected
                dashboard_state.bar_log = bar_log[-20:]
                await _write_dashboard_files_async(
                    dashboard_state, dash_path, status_path, "pre-IB heartbeat"
                )

                if connected:
                    # IB is often flaky for a few seconds right after reconnect; any exception
                    # here used to skip the second update_dashboard with fresh fields.
                    try:
                        # Latest print for PnL + chart (before account summary uses data_ref)
                        if data_ref['data'] is not None and not data_ref['data'].empty:
                            dashboard_state.current_price = float(data_ref['data']['close'].iloc[-1])
                        else:
                            dashboard_state.current_price = 0.0

                        dashboard_state.account_info = get_account_summary(
                            ib, data=data_ref['data'], contract=contract,
                            portfolio_realized_pnl=portfolio_realized_pnl
                        )

                        if guard and contract:
                            try:
                                flattened = guard.check_daily_pnl(
                                    ib, contract, dashboard_state.account_info, positions
                                )
                                if flattened:
                                    add_to_live_tracker(
                                        live_tracker, 'ERROR',
                                        "EMERGENCY FLATTEN - Limits Breached",
                                    )
                            except Exception as e:
                                logging.error("check_daily_pnl failed: %s", e, exc_info=True)

                        cp = dashboard_state.current_price
                        # Isolate risky bits so one failure does not skip chart / completed-trades refresh.
                        if contract and positions:
                            try:
                                prune_dead_brackets(ib, contract, positions, live_tracker)
                            except Exception as e:
                                logging.warning(
                                    "Dashboard prune_dead_brackets skipped: %s", e, exc_info=True
                                )

                        pos_data = []
                        try:
                            for p in ib.portfolio():
                                if not contract or p.contract.symbol == contract.symbol:
                                    pos_data.append(_portfolio_row_for_dashboard(p, cp))
                        except Exception as e:
                            logging.warning("ib.portfolio() snapshot failed for dashboard: %s", e)

                        try:
                            dashboard_state.positions = _merge_positions_for_dashboard(
                                ib, contract, positions, pos_data, cp,
                            )
                        except Exception as e:
                            logging.warning("merge dashboard positions failed: %s", e)
                            dashboard_state.positions = pos_data

                        try:
                            dashboard_state.active_orders = collect_all_ib_open_orders(ib)
                        except Exception as e:
                            logging.warning("collect_all_ib_open_orders failed: %s", e)
                        await asyncio.sleep(0.06)

                        # Update state common fields
                        dashboard_state.is_connected = ib.isConnected()
                        dashboard_state.total_uptime_seconds = total_uptime_seconds
                        dashboard_state.connection_start_time = connection_start_time
                        dashboard_state.last_data_receipt_time = last_data_receipt['time']

                        # Always update live tracker and completed trades on dashboard
                        dashboard_state.live_tracker = live_tracker[-200:]
                        dashboard_state.bar_log = bar_log[-20:]
                        dashboard_state.completed_trades = list(completed_trades[-1000:])

                        _chart_tf = dashboard_timeframe_minutes(dashboard_state.params)
                        try:
                            dashboard_state.chart_payload = await asyncio.wait_for(
                                asyncio.to_thread(
                                    build_chart_payload_from_df,
                                    data_ref['data'],
                                    480,
                                    _chart_tf,
                                    completed_trades,
                                    dashboard_state.params,
                                ),
                                timeout=45.0,
                            )
                        except (asyncio.TimeoutError, Exception) as e:
                            logging.warning(
                                "Chart payload build skipped (%s): %s",
                                type(e).__name__,
                                e,
                            )
                            dashboard_state.chart_payload = None
                        if dashboard_state.chart_payload:
                            tp_sl_series = _active_trade_stop_tp_series(positions, args.output_dir)
                            if tp_sl_series:
                                dashboard_state.chart_payload['active_trade_lines'] = tp_sl_series
                        dashboard_state.trade_overlay = _trade_overlay_from_open_brackets(positions)
                    except Exception as e:
                        logging.error(
                            "Dashboard state refresh failed after connect/reconnect (writing last-good snapshot): %s",
                            e,
                            exc_info=True,
                        )

                    await _write_dashboard_files_async(
                        dashboard_state, dash_path, status_path, "post-IB refresh"
                    )

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
                                    logging.error(
                                        "Trade report sweep failed: %s", ex, exc_info=True
                                    )

                            _trade_report_sweep_task = asyncio.create_task(
                                asyncio.to_thread(_sweep_trade_reports_blocking)
                            )
                        else:
                            logging.debug(
                                "Trade-report sweep skipped (previous background sweep still running)"
                            )

            now_g = time_module.monotonic()
            if guard and connected and (now_g - _LAST_GUARD_UI_MONO >= _GUARD_UI_MIN_SEC):
                _LAST_GUARD_UI_MONO = now_g
                try:
                    guard.check_connection(ib, positions)
                    if contract:
                        guard.check_orphaned_orders(ib, contract, positions)
                except Exception as e:
                    logging.error("Security guard UI check failed: %s", e, exc_info=True)

        except Exception as e:
            logging.error("UI update / Guard check failed: %s", e, exc_info=True)
        finally:
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
    if not ib.isConnected():
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

        bars_obj = request_historical_data_with_retry(ib, contract)
        bars_obj.updateEvent += lambda bars, hasNewBar: on_bar_update_handler(
            bars, hasNewBar, strategy=strategy, ib=ib, contract=contract,
            data_ref=data_ref, positions=positions, completed_trades=completed_trades,
            live_tracker=live_tracker, bar_log=bar_log, dashboard_state=dashboard_state,
            send_email_fn=custom_send_email, output_dir=args.output_dir,
            last_data_receipt=last_data_receipt
        )
        logging.info(f"Subscribed to market data ({len(bars_obj)} bars)")
    except Exception as e:
        logging.error(f"Failed to subscribe to data: {e}")


# =============================================================================
# Clean Exit
# =============================================================================
def clean_exit(signum=None, frame=None):
    """Clean shutdown handler."""
    logging.info("Shutdown signal received, cleaning up...")
    try:
        if ib.isConnected():
            logging.info("Disconnecting from TWS...")
            ib.disconnect()
    except: pass
    logging.info("Shutdown complete.")
    exit(0)

if hasattr(signal, 'SIGINT'):
    signal.signal(signal.SIGINT, clean_exit)
if hasattr(signal, 'SIGTERM'):
    signal.signal(signal.SIGTERM, clean_exit)
if os.name == 'nt':
    atexit.register(clean_exit)


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
    last_unrealized_alert_tier = 0
    last_heartbeat_time = datetime.now()

    protection_task = None

    try:
        # Connect with retry
        await connect_with_retry(ib, '127.0.0.1', args.port, base_client_id=args.client_id)
        connection_start_time = datetime.now()
        add_to_live_tracker(live_tracker, 'info', 'Connected to Interactive Brokers API')
        # Restore completed trades so dashboard/debug survives restarts.
        live_csv = os.path.join(args.output_dir, "live_trades.csv")
        restored = load_persisted_completed_trades(COMPLETED_TRADES_PATH, max_keep=1000)
        bootstrap = bootstrap_completed_trades(log_file, live_csv, max_keep=1000)
        if restored:
            merged = merge_completed_trade_lists(restored, bootstrap, max_keep=1000)
            completed_trades[:] = merged
            maybe_persist_completed_trades(COMPLETED_TRADES_PATH, completed_trades)
            logging.info(
                f"Restored {len(restored)} persisted completed trades (merged -> {len(merged)})"
            )
        else:
            backfilled = bootstrap
            if backfilled:
                completed_trades[:] = backfilled
                persist_completed_trades(COMPLETED_TRADES_PATH, completed_trades, max_keep=1000)
                logging.info(
                    f"Backfilled {len(backfilled)} completed trades from execution log + CSV"
                )
        generated_reports = ensure_completed_trade_reports(completed_trades, strategy, data_ref['data'])
        if generated_reports:
            persist_completed_trades(COMPLETED_TRADES_PATH, completed_trades, max_keep=1000)
            logging.info(f"Generated {generated_reports} missing completed-trade reports")

        # Auto-resolve front-month ES contract
        contract = get_front_es_contract(ib)
        cancel_all_pending(ib, contract, live_tracker)

        # --- SELF-HEALING STARTUP ---
        # Sync internal state with reality immediately after connection
        try:
            reconcile_positions(ib, contract, positions, live_tracker, 
                              completed_trades=completed_trades, send_email_fn=custom_send_email,
                              data=data_ref['data'])
        except Exception as e:
            logging.error(f"Startup reconciliation failed: {e}")

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
        asyncio.create_task(bar_pipeline_consumer())

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

        # Subscribe to market data with retry
        ensure_connected_and_subscribed()

        await asyncio.sleep(2)

        # Startup protection checks
        logging.info("Running startup protection checks...")
        # Protect FIRST so they are added to 'positions' tracking
        protect_existing_positions(ib, contract, positions, strategy, data_ref['data'], live_tracker)
        close_orphaned_positions(ib, contract, positions, live_tracker)
        check_and_recreate_tp_orders(ib, contract, positions, strategy, data_ref['data'], live_tracker)

        # Generate initial dashboard
        dash_path = os.path.join(WEB_DIR, args.dashboard)
        status_path = os.path.join(WEB_DIR, f"{args.mode.lower()}_status.js")
        if dashboard_state:
            await _write_dashboard_files_async(
                dashboard_state, dash_path, status_path, "startup"
            )
        add_to_live_tracker(live_tracker, 'info', 'Dashboard initialized')

        # Open dashboard in browser
        try:
            dashboard_abs = os.path.abspath(dash_path)
            webbrowser.open(f'file://{dashboard_abs}')
        except: pass

        # Start async tasks
        asyncio.create_task(update_ui_periodically())
        protection_task = asyncio.create_task(
            periodic_protection_check(ib, contract, positions, strategy, data_ref['data'], live_tracker,
                                     send_email_fn=custom_send_email, close_all_fn=_close_all_positions,
                                     completed_trades=completed_trades)
        )

        custom_send_email("START", f"Bot started in {args.mode} mode on port {args.port}\n"
                   f"Contract: {contract.localSymbol}\nStrategy: {args.strategy}")

        # Main loop
        while True:
            try:
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

                    logging.warning("Connection lost, reconnecting...")
                    await connect_with_retry(ib, '127.0.0.1', args.port, base_client_id=args.client_id)

                    connection_start_time = datetime.now(EASTERN)
                    add_to_live_tracker(live_tracker, 'info', 'Reconnected')

                    ensure_connected_and_subscribed()

                    # Post-reconnection safety
                    await asyncio.sleep(2)
                    run_reconnection_safety_sequence(ib, contract, positions, strategy,
                                                     data_ref['data'], live_tracker, completed_trades)

                    # Force an immediate dashboard update after reconnection
                    if dashboard_state:
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
                    if positions:
                        # Use the new detailed status reporting with charts
                        send_composite_status_notification(
                            ib, positions, data_ref['data'], 
                            dashboard_state.account_info if dashboard_state else {}, 
                            custom_send_email
                        )
                    # (Removed 'else' block to skip flat status emails)


                # Data liveness check
                time_since = (now - last_data_receipt['time']).total_seconds()
                if time_since > 60:
                    logging.warning(f"⚠️ DATA STALLED! No bars for {time_since:.1f}s. Restarting data...")
                    add_to_live_tracker(live_tracker, 'warning', 'Data Stalled - Forcing Restart')
                    ensure_connected_and_subscribed()
                    if time_since > 180:
                        subj = "🚨 STALL: POS OPEN!" if positions else "⚠️ STALL: FLAT"
                        msg = f"No tick data received for {time_since:.1f}s!\nPositions: {len(positions)}\nTime: {now.strftime('%H:%M:%S')}"
                        custom_send_email(subj, msg)
                    last_data_receipt['time'] = now

                await asyncio.sleep(10)

            except KeyboardInterrupt:
                break
            except Exception as e:
                error_msg = f"Error in main loop: {e}"
                logging.error(error_msg)
                add_error(error_log, error_msg)
                add_to_live_tracker(live_tracker, 'error', error_msg)
                await asyncio.sleep(5)

    except KeyboardInterrupt:
        logging.info("Keyboard interrupt, shutting down...")
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        add_to_live_tracker(live_tracker, 'error', f"Fatal: {e}")
        import traceback
        traceback.print_exc()
    finally:
        logging.info("Cleaning up...")
        if protection_task:
            try:
                protection_task.cancel()
                await protection_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            if ib.isConnected():
                ib.disconnect()
        except: pass
        custom_send_email("STOP", f"Bot stopped in {args.mode} mode")
        logging.info("Shutdown complete.")


if __name__ == '__main__':
    util.patchAsyncio()
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Program interrupted by user.")

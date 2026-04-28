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
from tools.dashboard.updates import DashboardState, update_dashboard
from tools.safety.guards import SecurityGuard
from tools.notifications.email_service import send_email

# Core modules (ported from ib_deployment_v4.py)
from core.connection import get_front_es_contract, connect_with_retry, request_historical_data_with_retry
from core.account import get_account_summary, format_duration, add_to_live_tracker, add_error
from core.execution import check_entries, check_exits, _close_all_positions, send_composite_status_notification
from core.protection import (cancel_all_pending, cleanup_orphaned_orders, close_orphaned_positions,
                              protect_existing_positions, check_and_recreate_tp_orders,
                              periodic_protection_check, run_reconnection_safety_sequence,
                              reconcile_positions)
from core.monitoring import update_indicators, on_bar_update_handler

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

# Web directory
WEB_DIR = os.path.join(os.getcwd(), 'web')
if not os.path.exists(WEB_DIR):
    try: os.makedirs(WEB_DIR)
    except: pass


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


async def update_ui_periodically():
    """Periodically update the dashboard files."""
    while True:
        if not ib.isConnected():
            await asyncio.sleep(5)
            continue
        try:
            if dashboard_state:
                # Update account summary using robust utility
                dashboard_state.account_info = get_account_summary(
                    ib, data=data_ref['data'], contract=contract, 
                    portfolio_realized_pnl=portfolio_realized_pnl
                )

                # Update positions
                pos_data = []
                for p in ib.portfolio():
                    if not contract or p.contract.symbol == contract.symbol:
                        pos_data.append({
                            'symbol': p.contract.symbol, 'position': p.position,
                            'avgCost': p.averageCost,
                            'marketValue': p.marketValue,
                            'realizedPNL': getattr(p, 'realizedPNL', getattr(p, 'realizedPnl', 0)) or 0,
                            'unrealizedPNL': getattr(p, 'unrealizedPNL', getattr(p, 'unrealizedPnl', 0)) or 0
                        })
                dashboard_state.positions = pos_data

                # Update orders
                orders_data = []
                for t in ib.trades():
                    if not t.isDone():
                        orders_data.append({
                            'orderId': t.order.orderId, 'orderType': t.order.orderType,
                            'action': t.order.action, 'totalQuantity': t.order.totalQuantity,
                            'lmtPrice': t.order.lmtPrice, 'auxPrice': t.order.auxPrice,
                            'status': t.orderStatus.status
                        })
                dashboard_state.active_orders = orders_data

                # Update state common fields
                dashboard_state.is_connected = ib.isConnected()
                dashboard_state.total_uptime_seconds = total_uptime_seconds
                dashboard_state.connection_start_time = connection_start_time
                dashboard_state.last_data_receipt_time = last_data_receipt['time']

                # Always update live tracker and completed trades on dashboard
                dashboard_state.live_tracker = live_tracker[-200:]
                dashboard_state.bar_log = bar_log[-20:]
                dashboard_state.completed_trades = completed_trades[-50:]
                
                # Update current price in state for dashboard metrics
                if data_ref['data'] is not None and not data_ref['data'].empty:
                    dashboard_state.current_price = data_ref['data']['close'].iloc[-1]

                dash_path = os.path.join(WEB_DIR, args.dashboard)
                status_path = os.path.join(WEB_DIR, f"{args.mode.lower()}_status.js")
                update_dashboard(dashboard_state, dash_path, status_path)

            # Security guard checks (only if connected)
            if guard and ib.isConnected():
                guard.check_connection(ib, positions)
                if contract:
                    guard.check_orphaned_orders(ib, contract, positions)

        except Exception as e:
            logging.error(f"UI update / Guard check failed: {e}")

        await asyncio.sleep(5)


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

        # Subscribe to account updates
        ib.reqAccountSummary()

        def on_account_summary(val):
            if dashboard_state:
                try:
                    v = val.value
                    if val.tag in ['NetLiquidation', 'TotalCashValue', 'BuyingPower',
                                   'EquityWithLoanValue', 'RealizedPNL', 'UnrealizedPNL']:
                        try: v = float(v)
                        except: pass
                    dashboard_state.account_info[val.tag] = v

                    if guard and contract and ib.isConnected():
                        flattened = guard.check_daily_pnl(ib, contract, dashboard_state.account_info, positions)
                        if flattened:
                            add_to_live_tracker(live_tracker, 'ERROR', "EMERGENCY FLATTEN - Limits Breached")
                except: pass

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
            update_dashboard(dashboard_state, dash_path, status_path)
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
                        update_dashboard(dashboard_state, dash_path, status_path)
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

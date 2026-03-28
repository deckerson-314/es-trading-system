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
from core.execution import check_entries, check_exits
from core.protection import (cancel_all_pending, cleanup_orphaned_orders, close_orphaned_positions,
                              protect_existing_positions, check_and_recreate_tp_orders,
                              periodic_protection_check, run_reconnection_safety_sequence)
from core.monitoring import update_indicators, on_bar_update_handler

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
open_fills_log = []
portfolio_realized_pnl = None
last_data_receipt = {'time': datetime.now()}

# Dashboard tracking
connection_start_time = None
total_uptime_seconds = 0
dashboard_stats = {
    'trades_opened': 0, 'trades_closed': 0, 'orders_placed': 0,
    'orders_filled': 0, 'orders_cancelled': 0, 'reconnections': 0
}

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

        with open(csv_path, 'a', newline='') as f:
            if not file_exists:
                f.write("Time,Symbol,Side,Price,Qty,Commission,RealizedPNL,PermID\n")
            f.write(f"{fill_time},{symbol},{side},{price},{shares},{comm},{realized},{perm_id}\n")
            f.flush()

        logging.info(f"💾 Execution Logged: {side} {shares} @ {price} (Comm: {comm})")

        # FIFO trade pairing
        matched = None
        if side == 'BOT':
            for i, f in enumerate(open_fills_log):
                if f['side'] == 'SLD': matched = open_fills_log.pop(i); break
        elif side == 'SLD':
            for i, f in enumerate(open_fills_log):
                if f['side'] == 'BOT': matched = open_fills_log.pop(i); break

        if matched:
            entry_price = matched['price']
            exit_price = price
            multiplier = 50
            if side == 'SLD':
                pnl = (exit_price - entry_price) * shares * multiplier
                direction = 'LONG'
            else:
                pnl = (entry_price - exit_price) * shares * multiplier
                direction = 'SHORT'
            duration = fill_dt - matched['dt']
            duration_str = str(duration).split('.')[0]

            reason = 'Live Fill'
            for bracket in positions:
                if bracket.get('stopLoss') and bracket['stopLoss'].permId == perm_id:
                    reason = 'Stop Loss'; break
                if bracket.get('takeProfit') and bracket['takeProfit'].permId == perm_id:
                    reason = 'Take Profit'; break

            completed_trades.append({
                'exit_time': fill_dt, 'direction': direction, 'qty': shares,
                'entry_price': entry_price, 'exit_price': exit_price,
                'pnl': pnl - comm - matched['comm'], 'r_multiple': 0,
                'duration': duration_str, 'reason': reason
            })
            add_to_live_tracker(live_tracker, 'trade', f"CLOSE ({reason}): {direction} PnL=${pnl:.2f}")

            try:
                msg = (f"TRADE CLOSE - {direction} ({reason})\n{'='*30}\n"
                       f"Entry: ${entry_price:.2f}\nExit: ${exit_price:.2f}\n"
                       f"PnL: ${pnl:.2f}\nDuration: {duration_str}")
                send_email("BB Strategy - Trade CLOSE", msg)
            except: pass
        else:
            open_fills_log.append({
                'time': fill_time, 'dt': fill_dt, 'side': side,
                'qty': shares, 'price': price, 'comm': comm
            })
            logging.info(f"🆕 New Position Opened: {side} @ {price}")

    except Exception as e:
        logging.error(f"Failed to log execution to CSV: {e}")

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
                send_email("BB Strategy - API DISCONNECTED ⚠️", msg)
                disconnect_email_sent = True
                add_to_live_tracker(live_tracker, 'warning', f"Disconnect alert ({dur_str})")

    elif disconnect_start_time is not None:
        dur = (datetime.now() - disconnect_start_time).total_seconds()
        dur_str = format_duration(dur)
        msg = (f"API RECONNECTION\n{'='*50}\n\nRestored after: {dur_str}\n"
               f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        send_email("BB Strategy - API RECONNECTED", msg)
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
                dashboard_state.is_connected = ib.isConnected()
                if connection_start_time:
                    dashboard_state.total_uptime_seconds = (datetime.now() - connection_start_time).total_seconds()

                # Update positions
                pos_data = []
                for p in ib.portfolio():
                    if not contract or p.contract.symbol == contract.symbol:
                        pos_data.append({
                            'symbol': p.contract.symbol, 'position': p.position,
                            'avgCost': p.averageCost,
                            'marketValue': p.marketValue,
                            'realizedPNL': p.realizedPNL,
                            'unrealizedPNL': p.unrealizedPNL
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

                # Update live tracker and completed trades on dashboard
                dashboard_state.live_tracker = live_tracker[-200:]
                dashboard_state.bar_log = bar_log[-20:]
                dashboard_state.completed_trades = completed_trades[-50:]

                dash_path = os.path.join(WEB_DIR, args.dashboard)
                status_path = os.path.join(WEB_DIR, f"{args.mode.lower()}_status.js")
                update_dashboard(dashboard_state, dash_path, status_path)

            # Security guard checks
            if guard:
                guard.check_connection(ib, positions)
                if ib.isConnected() and contract:
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
            send_email_fn=send_email, output_dir=args.output_dir,
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
# MAIN LOOP
# =============================================================================
async def main():
    global contract, dashboard_state, guard, bars_obj
    global connection_start_time, total_uptime_seconds, portfolio_realized_pnl

    protection_task = None

    try:
        # Connect with retry
        await connect_with_retry(ib, '127.0.0.1', args.port, base_client_id=args.client_id)
        connection_start_time = datetime.now()
        add_to_live_tracker(live_tracker, 'info', 'Connected to Interactive Brokers API')

        # Auto-resolve front-month ES contract
        contract = get_front_es_contract(ib)
        cancel_all_pending(ib, contract, live_tracker)

        # Initialize Dashboard
        dashboard_state = DashboardState(
            mode=args.mode, port=args.port,
            contract_symbol=contract.localSymbol,
            connection_start_time=datetime.now(),
            is_connected=True, params=params_dict
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
            global portfolio_realized_pnl
            if item.contract.symbol == 'ES' and item.contract.conId == contract.conId:
                portfolio_realized_pnl = (getattr(item, 'realizedPNL', None) or
                                          getattr(item, 'realizedPnl', None))

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
            periodic_protection_check(ib, contract, positions, strategy, data_ref['data'], live_tracker)
        )

        send_email("Trading Bot Started", f"Bot started in {args.mode} mode on port {args.port}\n"
                   f"Contract: {contract.localSymbol}\nStrategy: {args.strategy}")

        # Main loop
        while True:
            try:
                check_disconnect_status()

                if not ib.isConnected():
                    # Track disconnect
                    if connection_start_time:
                        total_uptime_seconds += (datetime.now() - connection_start_time).total_seconds()
                        connection_start_time = None
                    add_to_live_tracker(live_tracker, 'warning', 'Connection lost - reconnecting')
                    dashboard_stats['reconnections'] += 1

                    logging.warning("Connection lost, reconnecting...")
                    await connect_with_retry(ib, '127.0.0.1', args.port, base_client_id=args.client_id)

                    connection_start_time = datetime.now()
                    add_to_live_tracker(live_tracker, 'info', 'Reconnected')

                    ensure_connected_and_subscribed()

                    # Post-reconnection safety
                    await asyncio.sleep(2)
                    run_reconnection_safety_sequence(ib, contract, positions, strategy,
                                                     data_ref['data'], live_tracker)

                    # Force an immediate dashboard update after reconnection
                    if dashboard_state:
                        dashboard_state.is_connected = True
                        dashboard_state.connection_start_time = connection_start_time
                        dash_path = os.path.join(WEB_DIR, args.dashboard)
                        status_path = os.path.join(WEB_DIR, f"{args.mode.lower()}_status.js")
                        update_dashboard(dashboard_state, dash_path, status_path)
                        add_to_live_tracker(live_tracker, 'info', 'Dashboard refreshed after reconnection')

                # Data liveness check
                time_since = (datetime.now() - last_data_receipt['time']).total_seconds()
                if time_since > 60:
                    logging.warning(f"⚠️ DATA STALLED! No bars for {time_since:.1f}s. Restarting data...")
                    add_to_live_tracker(live_tracker, 'warning', 'Data Stalled - Forcing Restart')
                    ensure_connected_and_subscribed()
                    last_data_receipt['time'] = datetime.now()

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
        send_email("Trading Bot Stopped", f"Bot stopped in {args.mode} mode")
        logging.info("Shutdown complete.")


if __name__ == '__main__':
    util.patchAsyncio()
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Program interrupted by user.")

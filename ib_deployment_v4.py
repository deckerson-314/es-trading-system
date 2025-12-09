#!/usr/bin/env python3
"""
ib_deployment_v2.py - Bollinger Band Live Trading with IB (Version 2.0)
========================================================================
Uses shared bollinger_strategy module for unified strategy logic.
REAL ORDERS + REAL PNL

Revision History:
- 2.0 - Refactored to use shared bollinger_strategy module
- 2.13 - Fixed NameError in on_bar_update by using new_row in check_exits call
- 2.12 - Fixed bracketOrder by adding limitPrice=0.0 for market entry
"""

import os
import argparse
import pandas as pd
import numpy as np
import logging
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, time
from threading import Timer
from ib_insync import IB, Future, util, MarketOrder, StopOrder, LimitOrder, Order
from dotenv import load_dotenv
import asyncio
import warnings
import pytz
import signal
import time as time_module
from bollinger_strategy import BollingerBandStrategyV4 as BollingerBandStrategy, load_params

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=pd.errors.SettingWithCopyWarning)

load_dotenv()

EMAIL_FROM = os.getenv('EMAIL_FROM')
EMAIL_TO = os.getenv('EMAIL_TO')
EMAIL_PWD = os.getenv('EMAIL_PASSWORD')

if not all([EMAIL_FROM, EMAIL_TO, EMAIL_PWD]):
    raise RuntimeError("Missing Gmail credentials in .env")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('ib_deployment.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

REVISION = "4.0"
logging.info(f"Starting ib_deployment_v2.py - REVISION {REVISION}")

# =============================================================================
# Load Parameters
# =============================================================================
# =============================================================================
# Load Parameters
# =============================================================================
# Default path (can be overridden by CLI args)
DEFAULT_PARAM_CSV = r'Bollinger\parameters\live_params.csv'

# Parse Command Line Arguments
parser = argparse.ArgumentParser(description='IB Live Trading Deployment')
parser.add_argument('--params', type=str, default=DEFAULT_PARAM_CSV, help='Path to parameter CSV file')
args = parser.parse_args()

PARAM_CSV = args.params

params_dict = load_params(PARAM_CSV)
logging.info(f"Loaded {len(params_dict)} parameters from {PARAM_CSV}")

# Initialize strategy
strategy = BollingerBandStrategy(params_dict)

logging.info("\n=== LOADED PARAMETERS (grouped by category) ===")

# Group parameters for display
def group_params_for_display(params_dict_local):
    """Group parameters into logical categories."""
    groups = {
        'Entry Criteria': ['Enable Long Trades', 'Enable Short Trades', 'Bollinger Band Length', 
                          'Bollinger Band StdDev', 'Long Entry on Wick Touch', 'Long Entry on Body in Zone',
                          'Long Trigger (% From Lower Band)', 'Short Entry on Wick Touch', 
                          'Short Entry on Body in Zone', 'Short Trigger (% From Upper Band)',
                          'ATR Length for Filter', 'Max ATR Filter (Points)', 'Min ATR Filter (Points)', 'RTH Start (HH:MM)', 'RTH End (HH:MM)',
                          'Enable RTH Filter', 'Volume MA Length', 'Max Volume Multiplier', 'Timeframe (minutes)',
                          'Max Open Trades'],
        'Take Profit Criteria': ['Opposite Bollinger Band TP', 'Fixed ATR TP', 'Fixed BB at Entry TP',
                                'ATR Length for TP', 'ATR Multiplier for TP'],
        'Stop Loss Criteria': ['Initial Stop Loss (%)', 'Enable Trailing Stop', 
                              'ATR Length for Trailing Stop', 'ATR Multiplier for Trailing Stop',
                              'Trailing Delay (bars)'],
        'GA Criteria': ['POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
                       'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
                       'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
                       'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT']
    }
    
    grouped = {}
    for group_name, param_list in groups.items():
        grouped[group_name] = {k: v for k, v in params_dict_local.items() if k in param_list}
    
    return grouped

grouped_params = group_params_for_display(params_dict)
for group_name, params in grouped_params.items():
    if params:
        logging.info(f"\n--- {group_name} ---")
        for name in sorted(params.keys()):
            value_dict = params[name]
            logging.info(f"  {name:45} = {value_dict['value']}")

# 15-min Status Timer
class StatusTimer:
    def __init__(self):
        self.timer = None
    
    def _report(self):
        positions_list = ib.positions()
        es_positions = [p for p in positions_list if p.contract.symbol == 'ES']
        
        # Check for active orders
        active_orders_count = 0
        try:
            for trade in ib.trades():
                if trade.contract.conId == contract.conId if contract else False:
                    if trade.isActive() or (trade.orderStatus and 
                        trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                        active_orders_count += 1
        except:
            pass
        
        # Skip email if no positions and no active orders
        if len(es_positions) == 0 and len(positions) == 0 and active_orders_count == 0:
            logging.debug("Skipping status email - no positions, no tracked positions, and no active orders")
            self.start()  # Restart timer for next check
            return
        
        # Get account summary
        account = get_account_summary()
        
        # Get current market price
        current_price = 0
        if len(data) > 0:
            current_price = data['close'].iloc[-1]
        
        # Build position details
        position_details = []
        for bracket in positions:
            entry_order = bracket.get('entry')
            stop_order = bracket.get('stopLoss')
            tp_order = bracket.get('takeProfit')
            direction = bracket.get('direction', 0)
            entry_price = bracket.get('entry_price', 0)
            entry_time = bracket.get('entry_time')
            
            # Get current stop and TP prices
            current_stop = getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', 0)) if stop_order else 0
            tp_price = getattr(tp_order, 'lmtPrice', None) if tp_order else None
            
            # Calculate duration
            duration_str = "N/A"
            if entry_time:
                duration_seconds = (datetime.now() - entry_time).total_seconds()
                duration_str = format_duration(duration_seconds)
            
            # Get unrealized PNL for this position
            pos_unrealized = 0
            for pos in es_positions:
                if pos.contract.conId == contract.conId:
                    # Try to get unrealized PNL with fallbacks
                    pos_unrealized = getattr(pos, 'unrealizedPNL', None)
                    if pos_unrealized is None:
                        pos_unrealized = getattr(pos, 'unrealizedPnl', None)
                    if pos_unrealized is None:
                        pos_unrealized = getattr(pos, 'unrealized_pnl', None)
                    if pos_unrealized is None:
                        pos_unrealized = 0  # Default to 0 if not available
                    break
            
            # Calculate price change
            price_change = current_price - entry_price if entry_price > 0 and current_price > 0 else 0
            price_change_pct = (price_change / entry_price * 100) if entry_price > 0 else 0
            
            # Get quantity from stop order or entry order
            qty = 1  # Default
            if stop_order and hasattr(stop_order, 'totalQuantity'):
                qty = abs(stop_order.totalQuantity)
            elif entry_order and hasattr(entry_order, 'totalQuantity'):
                qty = abs(entry_order.totalQuantity)
            
            # Calculate risk and reward for this position
            contract_multiplier = 50  # ES contract multiplier
            risk_dollars = abs(entry_price - current_stop) * contract_multiplier * qty if entry_price > 0 and current_stop > 0 else 0
            reward_dollars = abs(entry_price - tp_price) * contract_multiplier * qty if (tp_price and entry_price > 0) else None
            risk_reward_ratio = reward_dollars / risk_dollars if (reward_dollars and risk_dollars > 0) else None
            
            pos_info = [
                f"  Position {len(position_details) + 1}: {'LONG' if direction == 1 else 'SHORT'}",
                f"    Entry: ${entry_price:.2f} @ {entry_time.strftime('%H:%M:%S')}" if entry_time else f"    Entry: ${entry_price:.2f}",
                f"    Current: ${current_price:.2f} ({price_change_pct:+.2f}%)",
                f"    Stop: ${current_stop:.2f} (Risk: ${risk_dollars:,.2f})",
                f"    TP: ${tp_price:.2f} (Reward: ${reward_dollars:,.2f})" if tp_price else "    TP: None",
                f"    Risk/Reward: {risk_reward_ratio:.2f}:1" if risk_reward_ratio else "    Risk/Reward: N/A",
                f"    Unrealized PNL: ${pos_unrealized:,.2f}",
                f"    Duration: {duration_str}"
            ]
            position_details.extend(pos_info)
        
        # Build comprehensive status email
        msg_lines = [
            f"STATUS UPDATE - 15 Minute Report",
            f"{'='*50}",
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"",
            f"Positions:",
            f"  Open ES Positions: {len(es_positions)}",
            f"  Total Unrealized PNL: ${account.get('UnrealizedPNL', 0):,.2f}",
            f""
        ]
        
        if position_details:
            msg_lines.extend(position_details)
            msg_lines.append("")
        else:
            msg_lines.append("  No open positions")
            msg_lines.append("")
        
        msg_lines.append(f"Account Summary:")
        
        # Add account values (show 0.00 if available, N/A only if truly missing)
        net_liq = account.get('NetLiquidation')
        if net_liq is not None:
            msg_lines.append(f"  Net Liquidation: ${net_liq:,.2f}")
        else:
            msg_lines.append("  Net Liquidation: N/A")
        
        total_cash = account.get('TotalCashValue')
        if total_cash is not None:
            msg_lines.append(f"  Total Cash: ${total_cash:,.2f}")
        else:
            msg_lines.append("  Total Cash: N/A")
        
        buying_power = account.get('BuyingPower')
        if buying_power is not None:
            msg_lines.append(f"  Buying Power: ${buying_power:,.2f}")
        else:
            msg_lines.append("  Buying Power: N/A")
        
        msg_lines.extend([
            f"  Total Unrealized PNL: ${account.get('UnrealizedPNL', 0):,.2f}",
            f"  Total Realized PNL: ${account.get('RealizedPNL', 0):,.2f}",
        ])
        
        gross_pos = account.get('GrossPositionValue')
        if gross_pos is not None:
            msg_lines.append(f"  Gross Position Value: ${gross_pos:,.2f}")
        else:
            msg_lines.append("  Gross Position Value: N/A")
        
        msg = "\n".join(msg_lines)
        logging.info(msg.replace('\n', ' | '))
        send_email("BB Strategy - 15-min Status", msg)
        self.start()
    
    def start(self):
        if self.timer:
            self.timer.cancel()
        self.timer = Timer(900, self._report)
        self.timer.start()
    
    def stop(self):
        if self.timer:
            self.timer.cancel()

status_timer = StatusTimer()

# Global State
ib = IB()
positions = []  # List of BracketOrder objects for open positions
data = pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])
bar_count = 0
bars = None
contract = None

# Disconnect tracking for email alerts
disconnect_start_time = None  # Timestamp when disconnect was first detected
disconnect_email_sent = False  # Flag to prevent spam - only send one email per disconnect
DISCONNECT_ALERT_THRESHOLD = 30  # Send email if disconnected for more than 30 seconds

# Dashboard tracking variables
connection_start_time = None  # When connection was established
total_uptime_seconds = 0  # Cumulative uptime
last_disconnect_time = None  # Last disconnect timestamp
error_log = []  # List of recent errors (max 100)
dashboard_stats = {
    'trades_opened': 0,
    'trades_closed': 0,
    'orders_placed': 0,
    'orders_filled': 0,
    'orders_cancelled': 0,
    'reconnections': 0,
    'last_update': None
}
live_tracker = []  # List of recent events (max 200)
bar_log = []  # List of aggregated bar logs with entry criteria (max 20)
HTML_DASHBOARD = 'ib_deployment_dashboard.html'
WEB_DIR = os.path.join(os.getcwd(), 'web')  # Common web directory
WEB_DASHBOARD = os.path.join(WEB_DIR, 'ib_deployment_dashboard.html')

# Track realized PNL from portfolio updates (more accurate than positions)
portfolio_realized_pnl = None  # Will be updated from updatePortfolio callback

# Define helper functions
def send_email(subject, body):
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL_FROM, EMAIL_PWD)
            server.send_message(msg)
        logging.info(f"Email sent: {subject}")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")

def check_disconnect_status():
    """
    Check if API is disconnected and send email alert if disconnected for too long.
    Called periodically from main loop.
    """
    global disconnect_start_time, disconnect_email_sent
    
    if not ib.isConnected():
        # Disconnected - track when it started
        if disconnect_start_time is None:
            disconnect_start_time = datetime.now()
            disconnect_email_sent = False
            logging.warning("API disconnected - tracking disconnect time")
        
        # Check if we've been disconnected long enough to send alert
        if not disconnect_email_sent:
            disconnect_duration = (datetime.now() - disconnect_start_time).total_seconds()
            
            if disconnect_duration >= DISCONNECT_ALERT_THRESHOLD:
                # Send disconnect alert email
                duration_str = format_duration(disconnect_duration)
                
                # Get current position info if available (from tracked brackets, since we can't query IB while disconnected)
                position_info = []
                try:
                    # Use tracked positions since we can't query IB while disconnected
                    for bracket in positions:
                        direction = bracket.get('direction', 0)
                        if direction != 0:
                            stop_order = bracket.get('stopLoss')
                            if stop_order and hasattr(stop_order, 'totalQuantity'):
                                qty = abs(stop_order.totalQuantity)
                                direction_str = 'LONG' if direction == 1 else 'SHORT'
                                position_info.append(f"  {qty} contract(s) {direction_str}")
                except:
                    pass
                
                position_summary = "\n".join(position_info) if position_info else "  No tracked positions (may have closed while disconnected)"
                
                msg_lines = [
                    f"API DISCONNECTION ALERT",
                    f"{'='*50}",
                    f"",
                    f"The Interactive Brokers API connection has been lost.",
                    f"",
                    f"Disconnect Duration: {duration_str}",
                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"",
                    f"Current Open Positions:",
                    position_summary,
                    f"",
                    f"WARNING: While disconnected:",
                    f"  - Orders may fill without notification",
                    f"  - Positions may close without protection updates",
                    f"  - Orphaned orders may remain active",
                    f"",
                    f"The script will attempt to reconnect automatically.",
                    f"After reconnection, all positions will be checked and protected."
                ]
                
                msg = "\n".join(msg_lines)
                send_email("BB Strategy - API DISCONNECTION ALERT", msg)
                disconnect_email_sent = True
                logging.warning(f"Disconnect alert email sent (disconnected for {duration_str})")
    else:
        # Connected - check if we just reconnected
        if disconnect_start_time is not None:
            # We were disconnected but are now connected
            disconnect_duration = (datetime.now() - disconnect_start_time).total_seconds()
            duration_str = format_duration(disconnect_duration)
            
            # Send reconnection email
            msg_lines = [
                f"API RECONNECTION NOTIFICATION",
                f"{'='*50}",
                f"",
                f"The Interactive Brokers API connection has been restored.",
                f"",
                f"Disconnect Duration: {duration_str}",
                f"Reconnection Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"",
                f"The script will now:",
                f"  1. Check for orphaned orders and cancel them",
                f"  2. Verify all positions are protected",
                f"  3. Recreate any missing TP orders",
                f"  4. Resume normal operation"
            ]
            
            msg = "\n".join(msg_lines)
            send_email("BB Strategy - API RECONNECTED", msg)
            logging.info(f"Reconnection email sent (was disconnected for {duration_str})")
            
            # Reset disconnect tracking
            disconnect_start_time = None
            disconnect_email_sent = False

def get_account_summary():
    """Get account summary information."""
    try:
        account_values = ib.accountValues()
        summary = {}
        
        # Debug: Log first few account values to understand structure
        if len(account_values) > 0:
            logging.debug(f"Sample account value structure: {type(account_values[0])}, dir: {[x for x in dir(account_values[0]) if not x.startswith('_')]}")
            if len(account_values) <= 5:
                for av in account_values:
                    logging.debug(f"  Account value: {av}")
        
        # Account values can have different formats - try both tag and key access
        for av in account_values:
            # Try different ways to access tag and value
            tag = None
            value = None
            
            if hasattr(av, 'tag'):
                tag = av.tag
            elif hasattr(av, 'key'):
                tag = av.key
            elif hasattr(av, 'account'):
                # Sometimes it's an AccountValue object with account, tag, value
                tag = getattr(av, 'tag', None)
            
            if hasattr(av, 'value'):
                value = av.value
            elif hasattr(av, 'val'):
                value = av.val
            
            if tag and value is not None:
                # Check for relevant tags (case-insensitive)
                tag_upper = tag.upper() if tag else ''
                if any(keyword in tag_upper for keyword in ['NETLIQUIDATION', 'CASH', 'BUYINGPOWER', 'GROSSPOSITION', 'AVAILABLEFUNDS']):
                    try:
                        val = float(value) if value else 0.0
                        # Store with original tag
                        summary[tag] = val
                        
                        # Map to standard names for easier access
                        if 'NETLIQUIDATION' in tag_upper and 'CURRENCY' not in tag_upper:
                            summary['NetLiquidation'] = val
                        elif 'NETLIQUIDATION' in tag_upper:
                            summary['NetLiquidation'] = val  # Use currency-specific if that's all we have
                        if 'CASH' in tag_upper and 'TOTAL' in tag_upper:
                            summary['TotalCashValue'] = val
                        elif 'CASH' in tag_upper and 'BALANCE' in tag_upper:
                            summary['TotalCashValue'] = val
                        if 'BUYINGPOWER' in tag_upper:
                            summary['BuyingPower'] = val
                        if 'GROSSPOSITION' in tag_upper:
                            summary['GrossPositionValue'] = val
                    except (ValueError, TypeError) as e:
                        logging.debug(f"Could not convert account value {tag}={value}: {e}")
        
        # Get positions for PNL calculation
        positions_list = ib.positions()
        es_positions = [p for p in positions_list if p.contract.symbol == 'ES']
        # Calculate PNL with fallbacks for different attribute names
        total_unrealized_pnl = 0
        total_realized_pnl = 0
        for p in es_positions:
            unrealized = getattr(p, 'unrealizedPNL', None)
            if unrealized is None:
                unrealized = getattr(p, 'unrealizedPnl', None)
            if unrealized is None:
                unrealized = getattr(p, 'unrealized_pnl', None)
            if unrealized is None:
                unrealized = 0
            total_unrealized_pnl += unrealized
            
            realized = getattr(p, 'realizedPNL', None)
            if realized is None:
                realized = getattr(p, 'realizedPnl', None)
            if realized is None:
                realized = getattr(p, 'realized_pnl', None)
            if realized is None:
                realized = 0
            total_realized_pnl += realized
        
        # Use portfolio_realized_pnl if available (from updatePortfolio callback - more accurate)
        # This is especially important when there are no open positions
        global portfolio_realized_pnl
        if portfolio_realized_pnl is not None:
            summary['RealizedPNL'] = portfolio_realized_pnl
        else:
            summary['RealizedPNL'] = total_realized_pnl
        
        summary['UnrealizedPNL'] = total_unrealized_pnl
        summary['ES_Positions'] = len(es_positions)
        
        return summary
    except Exception as e:
        logging.debug(f"Error getting account summary: {e}")
        import traceback
        logging.debug(f"Traceback: {traceback.format_exc()}")
        return {}

def format_duration(seconds):
    """Format duration in seconds to human-readable string."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"

def add_to_live_tracker(event_type, message):
    """Add an event to the live tracker."""
    global live_tracker
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    live_tracker.append({
        'timestamp': timestamp,
        'type': event_type,  # 'info', 'warning', 'error', 'trade', 'order'
        'message': message
    })
    # Keep only last 200 entries
    if len(live_tracker) > 200:
        live_tracker = live_tracker[-200:]

def add_error(error_msg):
    """Add an error to the error log."""
    global error_log
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    error_log.append({
        'timestamp': timestamp,
        'error': error_msg
    })
    # Keep only last 100 errors
    if len(error_log) > 100:
        error_log = error_log[-100:]

def generate_dashboard_html():
    """Generate the live trading dashboard HTML."""
    global connection_start_time, total_uptime_seconds, dashboard_stats, error_log, live_tracker, params_dict, ib, contract, data, bar_log
    
    # Calculate connection uptime
    current_uptime = 0
    is_connected = False
    try:
        is_connected = ib.isConnected()
    except:
        pass
    
    if connection_start_time and is_connected:
        current_uptime = (datetime.now() - connection_start_time).total_seconds()
    total_uptime = total_uptime_seconds + current_uptime
    
    # Get current account info
    account = {}
    try:
        account = get_account_summary()
    except Exception as e:
        logging.debug(f"Error getting account summary: {e}")
    
    # Get current positions
    es_positions = []
    try:
        if is_connected:
            positions_list = ib.positions()
            es_positions = [p for p in positions_list if p.contract.conId == contract.conId] if contract else []
    except Exception as e:
        logging.debug(f"Error getting positions: {e}")
    
    # Get active orders
    active_orders = []
    try:
        if is_connected:
            for trade in ib.trades():
                if contract and trade.contract.conId == contract.conId:
                    if trade.isActive() or (trade.orderStatus and 
                        trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                        order = trade.order
                        order_type = type(order).__name__
                        if 'Market' in order_type:
                            order_type = "MKT"
                        elif 'Stop' in order_type:
                            order_type = "STP"
                        elif 'Limit' in order_type:
                            order_type = "LMT"
                        active_orders.append({
                            'orderId': order.orderId,
                            'permId': order.permId,
                            'type': order_type,
                            'action': order.action,
                            'qty': order.totalQuantity,
                            'limit': getattr(order, 'lmtPrice', None),
                            'stop': getattr(order, 'auxPrice', getattr(order, 'stopPrice', None)),
                            'status': trade.orderStatus.status if trade.orderStatus else "Unknown"
                        })
    except Exception as e:
        logging.debug(f"Error getting orders: {e}")
    
    # Get current market data
    current_price = 0
    try:
        if len(data) > 0:
            current_price = data['close'].iloc[-1]
    except:
        pass
    
    # Generate HTML
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>IB Deployment Live Dashboard</title>
    <meta http-equiv="refresh" content="5">
    <style>
        body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1600px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; border-bottom: 2px solid #ddd; padding-bottom: 5px; }}
        h3 {{ color: #666; margin-top: 20px; }}
        .status-bar {{ background: {'#4CAF50' if ib.isConnected() else '#f44336'}; color: white; padding: 15px; border-radius: 5px; margin: 20px 0; }}
        .status-bar.disconnected {{ background: #f44336; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
        .metric-box {{ background: #e3f2fd; border-left: 4px solid #2196F3; padding: 15px; border-radius: 4px; }}
        .metric-box .label {{ font-size: 0.9em; color: #666; }}
        .metric-box .value {{ font-size: 1.5em; font-weight: bold; color: #2196F3; margin-top: 5px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th {{ background: #4CAF50; color: white; padding: 10px; text-align: left; }}
        td {{ padding: 8px; border: 1px solid #ddd; }}
        tr:nth-child(even) {{ background: #f9f9f9; }}
        .positive {{ color: green; font-weight: bold; }}
        .negative {{ color: red; font-weight: bold; }}
        .live-tracker {{ max-height: 400px; overflow-y: auto; background: #f9f9f9; padding: 10px; border-radius: 4px; font-family: monospace; font-size: 0.9em; }}
        .live-tracker .entry {{ padding: 5px; margin: 2px 0; border-left: 3px solid #ddd; }}
        .live-tracker .entry.info {{ border-left-color: #2196F3; }}
        .live-tracker .entry.warning {{ border-left-color: #FF9800; }}
        .live-tracker .entry.error {{ border-left-color: #f44336; }}
        .live-tracker .entry.trade {{ border-left-color: #4CAF50; }}
        .live-tracker .entry.order {{ border-left-color: #9C27B0; }}
        .error-log {{ max-height: 300px; overflow-y: auto; background: #ffebee; padding: 10px; border-radius: 4px; font-family: monospace; font-size: 0.85em; }}
        .error-entry {{ padding: 5px; margin: 2px 0; color: #c62828; }}
        .bar-log-container {{ margin: 20px 0; }}
        .bar-log-scroll {{ max-height: 500px; overflow-y: auto; background: #f5f5f5; padding: 10px; border-radius: 4px; border: 1px solid #ddd; font-family: monospace; font-size: 0.85em; }}
        .bar-log-entry {{ padding: 8px; margin: 5px 0; background: white; border-left: 3px solid #2196F3; border-radius: 3px; }}
        .bar-log-timestamp {{ font-weight: bold; color: #2196F3; margin-bottom: 3px; }}
        .bar-log-info {{ color: #333; margin-bottom: 3px; }}
        .bar-log-criteria {{ color: #666; font-size: 0.9em; padding-left: 10px; }}
        .params-section {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }}
        .params-group {{ background: #f9f9f9; padding: 15px; border-radius: 4px; }}
        .params-group h3 {{ margin-top: 0; color: #555; border-bottom: 1px solid #ddd; padding-bottom: 5px; }}
        .params-table {{ width: 100%; font-size: 0.9em; }}
        .params-table td {{ padding: 5px; }}
        .return-button {{ display: inline-block; margin-bottom: 20px; padding: 10px 20px; background: #667eea; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; }}
        .return-button:hover {{ background: #5568d3; }}
    </style>
</head>
<body>
    <div class="container">
        <a href="index.html" class="return-button">← Back to Main Dashboard</a>
        <h1>IB Deployment Live Trading Dashboard</h1>
        <p><strong>Last Updated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <div class="status-bar {'disconnected' if not is_connected else ''}">
            <h2 style="margin: 0; color: white;">Connection Status: {'CONNECTED' if is_connected else 'DISCONNECTED'}</h2>
            <p style="margin: 5px 0 0 0;">
                <strong>Total Uptime:</strong> {format_duration(total_uptime)} | 
                <strong>Current Session:</strong> {format_duration(current_uptime) if connection_start_time and ib.isConnected() else 'N/A'} |
                <strong>Reconnections:</strong> {dashboard_stats['reconnections']}
            </p>
        </div>
        
        <h2>Account Summary</h2>
        <div class="metric-grid">
            <div class="metric-box">
                <div class="label">Net Liquidation</div>
                <div class="value">${account.get('NetLiquidation', 0):,.2f}</div>
            </div>
            <div class="metric-box">
                <div class="label">Total Cash</div>
                <div class="value">${account.get('TotalCashValue', 0):,.2f}</div>
            </div>
            <div class="metric-box">
                <div class="label">Buying Power</div>
                <div class="value">${account.get('BuyingPower', 0):,.2f}</div>
            </div>
            <div class="metric-box">
                <div class="label">Unrealized PNL</div>
                <div class="value {'positive' if account.get('UnrealizedPNL', 0) >= 0 else 'negative'}">
                    ${account.get('UnrealizedPNL', 0):,.2f}
                </div>
            </div>
            <div class="metric-box">
                <div class="label">Realized PNL</div>
                <div class="value {'positive' if account.get('RealizedPNL', 0) >= 0 else 'negative'}">
                    ${account.get('RealizedPNL', 0):,.2f}
                </div>
            </div>
            <div class="metric-box">
                <div class="label">Open ES Positions</div>
                <div class="value">{len(es_positions)}</div>
            </div>
            <div class="metric-box">
                <div class="label">Current Price</div>
                <div class="value">${current_price:.2f}</div>
            </div>
        </div>
        
        <h2>Active Positions</h2>
"""
    
    if es_positions:
        html += """        <table>
            <thead>
                <tr>
                    <th>Direction</th>
                    <th>Size</th>
                    <th>Avg Price</th>
                    <th>Current Price</th>
                    <th>Stop Loss</th>
                    <th>Take Profit</th>
                    <th>Risk ($)</th>
                    <th>Reward ($)</th>
                    <th>R:R Ratio</th>
                    <th>Unrealized PNL</th>
                    <th>Realized PNL</th>
                </tr>
            </thead>
            <tbody>
"""
        for pos in es_positions:
            direction = 'LONG' if pos.position > 0 else 'SHORT'
            pos_direction = 1 if pos.position > 0 else -1
            # Try to get average cost - Position object may have different attribute names
            avg_price = 0
            try:
                # Try common attribute names
                avg_price = getattr(pos, 'averageCost', None)
                if avg_price is None:
                    avg_price = getattr(pos, 'avgCost', None)
                if avg_price is None:
                    avg_price = getattr(pos, 'averagePrice', None)
                if avg_price is None:
                    # Calculate from market value if available
                    if hasattr(pos, 'marketValue') and hasattr(pos, 'position') and pos.position != 0:
                        avg_price = abs(pos.marketValue / pos.position)
                if avg_price is None or avg_price == 0:
                    avg_price = current_price  # Fallback to current price
            except:
                avg_price = current_price  # Fallback to current price
            
            # Get PNL values with fallbacks
            unrealized_pnl = getattr(pos, 'unrealizedPNL', None)
            if unrealized_pnl is None:
                unrealized_pnl = getattr(pos, 'unrealizedPnl', None)
            if unrealized_pnl is None:
                unrealized_pnl = getattr(pos, 'unrealized_pnl', None)
            if unrealized_pnl is None:
                unrealized_pnl = 0
            
            realized_pnl = getattr(pos, 'realizedPNL', None)
            if realized_pnl is None:
                realized_pnl = getattr(pos, 'realizedPnl', None)
            if realized_pnl is None:
                realized_pnl = getattr(pos, 'realized_pnl', None)
            if realized_pnl is None:
                realized_pnl = 0
            
            # Find matching tracked position to get SL and TP
            # First, try to get from active orders (most up-to-date, especially for trailing stops)
            stop_price = None
            tp_price = None
            risk_dollars = None
            reward_dollars = None
            risk_reward_ratio = None
            
            qty = abs(pos.position)
            contract_multiplier = 50  # ES contract multiplier
            
            try:
                # Look for active stop and TP orders matching this position
                for trade in ib.trades():
                    if trade.contract.conId != contract.conId:
                        continue
                    
                    if not trade.isActive():
                        continue
                    
                    order = trade.order
                    order_qty = abs(order.totalQuantity) if hasattr(order, 'totalQuantity') else 0
                    
                    # Check if this order matches our position size
                    if order_qty != qty:
                        continue
                    
                    # Check if it's a stop order
                    is_stop = (isinstance(order, StopOrder) or 
                              (hasattr(order, 'auxPrice') and getattr(order, 'auxPrice', 0) > 0 and 
                               hasattr(order, 'lmtPrice') and getattr(order, 'lmtPrice', 0) == 0))
                    
                    if is_stop:
                        # Check direction matches
                        order_action = order.action
                        if (pos_direction == 1 and order_action == 'SELL') or (pos_direction == -1 and order_action == 'BUY'):
                            stop_price = getattr(order, 'auxPrice', None)
                            if stop_price is None:
                                stop_price = getattr(order, 'stopPrice', None)
                    
                    # Check if it's a limit order (likely TP)
                    is_limit = (isinstance(order, LimitOrder) or 
                               (hasattr(order, 'lmtPrice') and getattr(order, 'lmtPrice', 0) > 0))
                    
                    if is_limit and not is_stop:
                        # Check direction matches
                        order_action = order.action
                        if (pos_direction == 1 and order_action == 'SELL') or (pos_direction == -1 and order_action == 'BUY'):
                            tp_price = getattr(order, 'lmtPrice', None)
            except Exception as e:
                logging.debug(f"Error getting SL/TP from active orders: {e}")
            
            # If we didn't find from active orders, try bracket dictionary as fallback
            if stop_price is None or tp_price is None:
                for bracket in positions:
                    bracket_direction = bracket.get('direction', 0)
                    if bracket_direction == pos_direction:
                        # Get stop loss price from bracket
                        if stop_price is None:
                            stop_order = bracket.get('stopLoss')
                            if stop_order:
                                stop_price = getattr(stop_order, 'auxPrice', None)
                                if stop_price is None:
                                    stop_price = getattr(stop_order, 'stopPrice', None)
                        
                        # Get take profit price from bracket
                        if tp_price is None:
                            tp_order = bracket.get('takeProfit')
                            if tp_order:
                                tp_price = getattr(tp_order, 'lmtPrice', None)
                        
                        break
            
            # Calculate risk and reward
            if stop_price and current_price > 0:
                if pos_direction == 1:  # LONG
                    risk_dollars = abs(current_price - stop_price) * contract_multiplier * qty
                    if tp_price:
                        reward_dollars = abs(tp_price - current_price) * contract_multiplier * qty
                else:  # SHORT
                    risk_dollars = abs(stop_price - current_price) * contract_multiplier * qty
                    if tp_price:
                        reward_dollars = abs(current_price - tp_price) * contract_multiplier * qty
                
                # Calculate risk/reward ratio
                if risk_dollars and risk_dollars > 0 and reward_dollars:
                    risk_reward_ratio = reward_dollars / risk_dollars
            
            # Format display values
            stop_str = f"${stop_price:.2f}" if stop_price else "N/A"
            tp_str = f"${tp_price:.2f}" if tp_price else "N/A"
            risk_str = f"${risk_dollars:,.2f}" if risk_dollars is not None else "N/A"
            reward_str = f"${reward_dollars:,.2f}" if reward_dollars is not None else "N/A"
            rr_str = f"{risk_reward_ratio:.2f}:1" if risk_reward_ratio else "N/A"
            
            html += f"""                <tr>
                    <td>{direction}</td>
                    <td>{abs(pos.position)}</td>
                    <td>${avg_price:.2f}</td>
                    <td>${current_price:.2f}</td>
                    <td>{stop_str}</td>
                    <td>{tp_str}</td>
                    <td class="negative">{risk_str}</td>
                    <td class="positive">{reward_str}</td>
                    <td>{rr_str}</td>
                    <td class="{'positive' if unrealized_pnl >= 0 else 'negative'}">${unrealized_pnl:,.2f}</td>
                    <td class="{'positive' if realized_pnl >= 0 else 'negative'}">${realized_pnl:,.2f}</td>
                </tr>
"""
        html += """            </tbody>
        </table>
"""
    else:
        html += """        <p><em>No open positions</em></p>
"""
    
    html += f"""
        <h2>Active Orders</h2>
"""
    if active_orders:
        html += """        <table>
            <thead>
                <tr>
                    <th>Order ID</th>
                    <th>Type</th>
                    <th>Action</th>
                    <th>Quantity</th>
                    <th>Limit Price</th>
                    <th>Stop Price</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
"""
        for order in active_orders:
            limit_str = f"${order['limit']:.2f}" if order['limit'] else "N/A"
            stop_str = f"${order['stop']:.2f}" if order['stop'] else "N/A"
            html += f"""                <tr>
                    <td>{order['orderId']}</td>
                    <td>{order['type']}</td>
                    <td>{order['action']}</td>
                    <td>{order['qty']}</td>
                    <td>{limit_str}</td>
                    <td>{stop_str}</td>
                    <td>{order['status']}</td>
                </tr>
"""
        html += """            </tbody>
        </table>
"""
    else:
        html += """        <p><em>No active orders</em></p>
"""
    
    html += f"""
        <h2>Statistics</h2>
        <div class="metric-grid">
            <div class="metric-box">
                <div class="label">Trades Opened</div>
                <div class="value">{dashboard_stats['trades_opened']}</div>
            </div>
            <div class="metric-box">
                <div class="label">Trades Closed</div>
                <div class="value">{dashboard_stats['trades_closed']}</div>
            </div>
            <div class="metric-box">
                <div class="label">Orders Placed</div>
                <div class="value">{dashboard_stats['orders_placed']}</div>
            </div>
            <div class="metric-box">
                <div class="label">Orders Filled</div>
                <div class="value">{dashboard_stats['orders_filled']}</div>
            </div>
            <div class="metric-box">
                <div class="label">Orders Cancelled</div>
                <div class="value">{dashboard_stats['orders_cancelled']}</div>
            </div>
        </div>
        
        <h2>Recent Errors</h2>
"""
    if error_log:
        html += """        <div class="error-log">
"""
        for error in error_log[-20:]:  # Show last 20 errors
            html += f"""            <div class="error-entry">
                <strong>{error['timestamp']}</strong>: {error['error']}
            </div>
"""
        html += """        </div>
"""
    else:
        html += """        <p><em>No errors recorded</em></p>
"""
    
    html += f"""
        <h2>Bar Log & Entry Criteria</h2>
        <div class="bar-log-container">
            <div class="bar-log-scroll">
"""
    
    # Show last 20 bar logs (most recent at top)
    global bar_log
    if bar_log:
        for entry in reversed(bar_log):
            html += f"""                <div class="bar-log-entry">
                    <div class="bar-log-timestamp">{entry['timestamp']}</div>
                    <div class="bar-log-info">{entry['bar_info']}</div>
"""
            if entry['entry_criteria']:
                html += f"""                    <div class="bar-log-criteria">{entry['entry_criteria']}</div>
"""
            html += """                </div>
"""
    else:
        html += """                <div class="bar-log-entry">
                    <em>No aggregated bars logged yet</em>
                </div>
"""
    
    html += """            </div>
        </div>
        
        <h2>Strategy Parameters</h2>
        <div class="params-section">
"""
    
    # Group parameters for display
    grouped_params = group_params_for_display(params_dict)
    for group_name, params in grouped_params.items():
        if params:
            html += f"""            <div class="params-group">
                <h3>{group_name}</h3>
                <table class="params-table">
"""
            for name in sorted(params.keys()):
                value_dict = params[name]
                value = value_dict['value']
                # Format value based on type
                if value_dict.get('type') == 'bool':
                    value_str = 'True' if value else 'False'
                elif value_dict.get('type') == 'float':
                    value_str = f"{value:.4f}" if isinstance(value, (int, float)) else str(value)
                elif value_dict.get('type') == 'int':
                    value_str = str(int(value)) if isinstance(value, (int, float)) else str(value)
                else:
                    value_str = str(value)
                
                html += f"""                    <tr>
                        <td><strong>{name}</strong></td>
                        <td>{value_str}</td>
                    </tr>
"""
            html += """                </table>
            </div>
"""
    
    html += """        </div>
        
        <h2>Live Event Tracker</h2>
        <div class="live-tracker">
"""
    
    # Show last 100 events
    for event in live_tracker[-100:]:
        html += f"""            <div class="entry {event['type']}">
                <strong>{event['timestamp']}</strong> [{event['type'].upper()}] {event['message']}
            </div>
"""
    
    html += """        </div>
    </div>
</body>
</html>
"""
    
    return html

def update_dashboard():
    """Update the dashboard HTML file."""
    try:
        html = generate_dashboard_html()
        # Write directly to web directory as primary location
        os.makedirs(WEB_DIR, exist_ok=True)
        with open(WEB_DASHBOARD, 'w', encoding='utf-8') as f:
            f.write(html)
        # Only log dashboard saves every 60 seconds to reduce log noise
        last_log_time = getattr(update_dashboard, '_last_log_time', None)
        if last_log_time is None or (datetime.now() - last_log_time).total_seconds() >= 60:
            logging.debug(f"Dashboard updated: {WEB_DASHBOARD}")
            update_dashboard._last_log_time = datetime.now()
        
        dashboard_stats['last_update'] = datetime.now()
    except Exception as e:
        logging.error(f"Failed to update dashboard: {e}")

def get_front_es_contract():
    for attempt in range(3):
        try:
            temp_contract = Future('ES', '', 'CME', currency='USD')
            cds = ib.reqContractDetails(temp_contract)
            if not cds:
                raise ValueError("No ES contracts found")
            today = datetime.now().date()
            future_cds = [cd for cd in cds 
                         if datetime.strptime(cd.contract.lastTradeDateOrContractMonth, '%Y%m%d').date() > today]
            if not future_cds:
                raise ValueError("No future ES contract found")
            front = min(future_cds, 
                       key=lambda cd: datetime.strptime(cd.contract.lastTradeDateOrContractMonth, '%Y%m%d'))
            ib.qualifyContracts(front.contract)
            logging.info(f"Resolved front ES contract: {front.contract.conId} exp {front.contract.lastTradeDateOrContractMonth}")
            return front.contract
        except Exception as e:
            logging.error(f"Failed to resolve contract on attempt {attempt+1}: {e}")
            time_module.sleep(5)
    raise ValueError("Failed to resolve ES contract after retries")

def cancel_all_pending():
    """
    Cancel all pending orders, but preserve protective orders (stop loss, take profit) 
    for existing positions to avoid leaving positions unprotected on restart.
    """
    try:
        # First, check if there are any open positions
        es_positions = []
        if contract:
            try:
                positions_list = ib.positions()
                es_positions = [p for p in positions_list if p.contract.conId == contract.conId] if contract else []
            except:
                pass
        
        has_open_position = any(abs(p.position) > 0 for p in es_positions)
        
        if has_open_position:
            # We have an open position - only cancel non-protective orders
            # Protective orders are stop loss and take profit orders
            logging.info("Open position detected - preserving protective orders (SL/TP)")
            
            # Get all active orders
            orders_to_cancel = []
            protective_orders = []
            
            try:
                for trade in ib.trades():
                    if contract and trade.contract.conId == contract.conId:
                        if trade.isActive() or (trade.orderStatus and 
                            trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                            order = trade.order
                            
                            # Check if this is a protective order (stop loss or take profit)
                            is_stop = (isinstance(order, StopOrder) or 
                                      (hasattr(order, 'auxPrice') and getattr(order, 'auxPrice', 0) > 0 and 
                                       hasattr(order, 'lmtPrice') and getattr(order, 'lmtPrice', 0) == 0))
                            is_limit = (isinstance(order, LimitOrder) or 
                                       (hasattr(order, 'lmtPrice') and getattr(order, 'lmtPrice', 0) > 0))
                            
                            if is_stop or (is_limit and not is_stop):
                                # This is a protective order - preserve it
                                protective_orders.append(trade)
                            else:
                                # This is not a protective order (e.g., entry order) - cancel it
                                orders_to_cancel.append(trade)
            except Exception as e:
                logging.debug(f"Error checking orders: {e}")
                # Fallback to global cancel if we can't check orders
                ib.reqGlobalCancel()
                logging.info("Cancelled all pending orders (fallback)")
                return
            
            # Cancel only non-protective orders
            for trade in orders_to_cancel:
                try:
                    ib.cancelOrder(trade.order)
                except Exception as e:
                    logging.debug(f"Error cancelling order {trade.order.orderId}: {e}")
            
            if orders_to_cancel:
                logging.info(f"Cancelled {len(orders_to_cancel)} non-protective order(s), preserved {len(protective_orders)} protective order(s)")
            else:
                logging.info(f"No non-protective orders to cancel, preserved {len(protective_orders)} protective order(s)")
        else:
            # No open positions - safe to cancel all orders
            ib.reqGlobalCancel()
            logging.info("Cancelled all pending orders (no open positions)")
    except Exception as e:
        logging.warning(f"Error in cancel_all_pending: {e}, falling back to global cancel")
        ib.reqGlobalCancel()
        logging.info("Cancelled all pending orders (fallback)")

def log_all_open_orders(context=""):
    """
    Log all ACTIVE open orders with their details for debugging.
    Only shows orders that are currently active (not filled/cancelled).
    
    Args:
        context: Optional context string to include in log (e.g., "After trailing stop update")
    """
    if contract is None:
        return
    
    try:
        # Get active orders from trades (trades have both order and contract info)
        active_orders = []
        for trade in ib.trades():
            if trade.contract.conId != contract.conId:
                continue
                
            order = trade.order
            order_status = trade.orderStatus
            status = order_status.status if order_status else "Unknown"
            
            # Only include ACTIVE orders (exclude filled/cancelled)
            active_statuses = ['PreSubmitted', 'Submitted', 'PendingSubmit', 
                             'PendingCancel', 'ApiPending', 'ApiCancelled']
            if not (trade.isActive() or status in active_statuses):
                continue
            
            # Skip if already in active_orders
            if any(o['permId'] == order.permId for o in active_orders):
                continue
            
            # Get order type
            order_type = type(order).__name__
            if 'Market' in order_type or isinstance(order, MarketOrder):
                order_type = "MKT"
            elif 'Stop' in order_type or isinstance(order, StopOrder):
                order_type = "STP"
            elif 'Limit' in order_type or isinstance(order, LimitOrder):
                order_type = "LMT"
            else:
                order_type = order_type.replace('Order', '')
            
            order_info = {
                'orderId': order.orderId,
                'permId': order.permId,
                'type': order_type,
                'action': order.action,
                'qty': order.totalQuantity,
                'status': status,
                'transmit': order.transmit if hasattr(order, 'transmit') else "N/A",
                'parentId': order.parentId if hasattr(order, 'parentId') else None,
            }
            
            # Add price info
            if isinstance(order, StopOrder) or 'Stop' in type(order).__name__:
                order_info['stopPrice'] = getattr(order, 'auxPrice', getattr(order, 'stopPrice', 0))
            elif isinstance(order, LimitOrder) or 'Limit' in type(order).__name__:
                order_info['limitPrice'] = getattr(order, 'lmtPrice', 0)
            
            active_orders.append(order_info)
        
        if active_orders:
            logging.info(f"=== ACTIVE ORDERS FOR ES {context} ===")
            for o in active_orders:
                price_info = ""
                if 'stopPrice' in o:
                    price_info = f" | Stop: {o['stopPrice']:.2f}"
                elif 'limitPrice' in o:
                    price_info = f" | Limit: {o['limitPrice']:.2f}"
                
                parent_info = f" | Parent: {o['parentId']}" if o['parentId'] else ""
                transmit_info = f" | Transmit: {o['transmit']}"
                
                logging.info(f"  OrderID: {o['orderId']} | PermID: {o['permId']} | "
                           f"Type: {o['type']} | Action: {o['action']} | Qty: {o['qty']}"
                           f"{price_info}{parent_info}{transmit_info} | Status: {o['status']}")
            logging.info(f"=== TOTAL: {len(active_orders)} ACTIVE ES ORDER(S) ===")
        else:
            logging.info(f"No active ES orders {context}")
            
    except Exception as e:
        logging.error(f"Error logging open orders: {e}")
        import traceback
        logging.error(traceback.format_exc())

# Real-Time Bar Handler
def on_bar_update(bars, hasNewBar):
    global data, bar_count
    try:
        if not hasNewBar:
            return
    
        bar = bars[-1]
    
        # Diagnostic: Check bar attributes to understand volume reporting
        bar_time = bar.date.astimezone(pytz.timezone('US/Eastern'))
        bar_seconds = bar_time.second
        bar_minute = bar_time.minute
    
        new_row = pd.Series({
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': bar.volume
        }, name=bar_time)
    
        data = data._append(new_row)
        bar_count += 1
    
        # Log incoming bar (currently 5-second bars for volume investigation)
        # NOTE: IB API volume may be filtered (excludes combo trades, block trades, etc.)
        # TWS shows unfiltered volume, which can be 10x-20x higher
        # bar.volume is per-bar volume for the bar period (not cumulative across bars)
        # Check if data is live or delayed by comparing bar time to current time
        current_time = datetime.now(pytz.timezone('US/Eastern'))
        time_delay_seconds = (current_time - bar_time).total_seconds()
        delay_indicator = ""
        if time_delay_seconds < 10:
            delay_indicator = " [LIVE]"
        elif time_delay_seconds > 900:  # 15 minutes
            delay_indicator = " [DELAYED]"
    
        logging.info(f"[5-sec bar] {bar_time.strftime('%H:%M:%S')}{delay_indicator} | "
                    f"O: {bar.open:.2f} H: {bar.high:.2f} L: {bar.low:.2f} C: {bar.close:.2f} | "
                    f"Vol: {bar.volume:,.0f}")
    
        # Check if this bar completes a resampled period (for logging resampled bar)
        # Since we're receiving 5-second bars, we need to resample to target timeframe
        # IMPORTANT: With label='right', the resampled bar timestamp is the END of the period
        # So a 7-min bar at 12:08:00 includes data from 12:01:00 (exclusive) to 12:08:00 (inclusive)
        # We should log it when we receive the LAST 5-sec bar that completes the period
        # For 1-min bars: log when we receive a bar at :00 (the bar that completes the minute)
        # For 7-min bars: log when we receive a bar at :08, :15, :22, :29, :36, :43, :50, :57
        should_log_resampled = False
        if strategy.timeframe == 1:
            # For 1-minute bars, log when second == 0 (the bar that completes the minute)
            if bar_time.second == 0:
                should_log_resampled = True
        elif strategy.timeframe > 1:
            # For multi-minute bars, log when minute % timeframe == 0 and second == 0
            # This is when we receive the last 5-sec bar that completes the resampled period
            if bar_time.minute % strategy.timeframe == 0 and bar_time.second == 0:
                should_log_resampled = True
    
        update_indicators()
    
        # Log resampled bar if timeframe > 1 and this bar completed a resampled period
        # IMPORTANT: Only log if we actually have data up to (or very close to) the resampled bar timestamp
        # This prevents logging incomplete resampled bars
        if should_log_resampled and len(data) >= strategy.bb_length:
            # Check if we have data up to the expected resampled bar timestamp
            # For a 7-min bar, if current bar is at 12:08:00, we should have data up to 12:08:00
            expected_resampled_time = bar_time.replace(second=0, microsecond=0)
            # Allow up to 5 seconds of tolerance (one bar) - this handles the case where
            # we receive the bar at 12:08:00 but the resampled bar timestamp is also 12:08:00
            has_sufficient_data = len(data) > 0 and (data.index[-1] >= expected_resampled_time - pd.Timedelta(seconds=5))
        
            if has_sufficient_data:
                # Get the resampled data (calculate_indicators is called in update_indicators, but we need it here for logging)
                data_with_indicators = strategy.calculate_indicators(data.copy())
                # Apply filters for entry criteria logging
                data_with_filters = strategy.apply_filters(data_with_indicators)
        
                if len(data_with_indicators) > 0:
                    latest_resampled_idx = data_with_indicators.index[-1]
                    latest_resampled_row = data_with_indicators.iloc[-1]
                    
                    # Get the corresponding row from data_with_filters (for filter status)
                    if len(data_with_filters) > 0 and latest_resampled_idx in data_with_filters.index:
                        resampled_row_with_filters = data_with_filters.loc[latest_resampled_idx]
                    else:
                        # Fallback to data_with_indicators if filters not available
                        resampled_row_with_filters = latest_resampled_row
                
                    # Only log if we have data up to (or very close to) the resampled bar timestamp
                    # This prevents logging incomplete resampled bars
                    time_gap_to_resampled = (latest_resampled_idx - data.index[-1]).total_seconds()
                    if time_gap_to_resampled > 60:  # More than 1 minute gap
                        # Don't log - we don't have enough data for this resampled bar yet
                        logging.debug(f"  Skipping resampled bar at {latest_resampled_idx} - only have data up to {data.index[-1]} (gap: {time_gap_to_resampled:.0f}s)")
                        return
            
                # Calculate how many 5-sec bars were included in this resampled bar
                # For a 7-minute bar, we need 7 minutes of 5-sec bars = 420 seconds / 5 = 84 bars
                # The resampled bar at latest_resampled_idx represents data from (latest_resampled_idx - timeframe) to latest_resampled_idx
                # With label='right' and closed='right', the bar at 11:54:00 includes data from 11:47:00 (exclusive) to 11:54:00 (inclusive)
                # So we need bars from (11:47:00 + 5 seconds) to 11:54:00 (inclusive) = 84 bars
                # Example: 11:47:05, 11:47:10, ..., 11:53:55, 11:54:00 = 84 bars
                resample_start = latest_resampled_idx - pd.Timedelta(minutes=strategy.timeframe)
                # With closed='right', the start time is exclusive, so we need bars AFTER resample_start
                # The first bar included is resample_start + 5 seconds (the first 5-sec bar after the start)
                resample_start_exclusive = resample_start + pd.Timedelta(seconds=5)
            
                # IMPORTANT: With label='right', the resampled bar timestamp (latest_resampled_idx) is the END of the period
                # But we might not have data up to that exact timestamp yet. We need to find the actual
                # last 5-second bar that was included in the resampling.
                # The resampled bar at 12:08:00 should include bars from 12:01:00 (exclusive) to 12:08:00 (inclusive)
                # But if the last 5-sec bar is only at 12:07:00, we only have 6 minutes of data
            
                # Find all bars that are <= latest_resampled_idx (the resampled bar end time)
                available_bars_up_to_resampled = data[data.index <= latest_resampled_idx]
            
                if len(available_bars_up_to_resampled) == 0:
                    # No bars available - shouldn't happen, but handle gracefully
                    period_bars = pd.DataFrame()
                else:
                    # Use the actual last 5-second bar timestamp as the end point
                    actual_end_time = available_bars_up_to_resampled.index[-1]
                
                    # Check if we have enough data to reach the resampled bar timestamp
                    time_gap_seconds = (latest_resampled_idx - actual_end_time).total_seconds()
                    if time_gap_seconds > 10:  # More than 10 seconds gap
                        # We're logging a resampled bar before we have all the data for it
                        # This happens because we check at the start of the period, not the end
                        logging.debug(f"  Note: Resampled bar timestamp ({latest_resampled_idx}) is {time_gap_seconds:.0f} seconds ahead of last 5-sec bar ({actual_end_time})")
                
                    # Get all bars in the resampled period (from resample_start_exclusive to actual_end_time)
                    if resample_start_exclusive >= data.index[0]:
                        # Get all bars in the range, including both endpoints
                        period_bars = data.loc[resample_start_exclusive:actual_end_time]
                    else:
                        # If resample_start is before our data starts, use what we have
                        period_bars = data.loc[:actual_end_time]
            
                num_bars = len(period_bars)
            
                # Expected number of bars: timeframe minutes * 60 seconds / 5 seconds per bar
                expected_bars = (strategy.timeframe * 60) // 5
            
                # If we don't have enough history, the count will be less than expected
                # This is normal during startup - the resampling still works correctly
                if num_bars < expected_bars:
                    # Calculate actual time span and log detailed debug info
                    actual_start = period_bars.index[0] if len(period_bars) > 0 else None
                    actual_end = period_bars.index[-1] if len(period_bars) > 0 else None
                    if actual_start and actual_end:
                        actual_span_minutes = (actual_end - actual_start).total_seconds() / 60
                        logging.warning(f"  ⚠️ {strategy.timeframe}-min bar has {num_bars} bars (expected {expected_bars})")
                        logging.warning(f"     Resampled bar time: {latest_resampled_idx}")
                        logging.warning(f"     Calculated start: {resample_start}, exclusive start: {resample_start_exclusive}")
                        logging.warning(f"     Actual period: {actual_start} to {actual_end} (span: {actual_span_minutes:.1f} min)")
                        logging.warning(f"     Data range: {data.index[0]} to {data.index[-1]} (total: {len(data)} bars)")
                        logging.warning(f"     Bars up to resampled time: {len(available_bars_up_to_resampled)}")
            
                # Always log the actual count (even if less than expected during startup)
                if num_bars == expected_bars:
                    bar_count_msg = f"sum of {num_bars} 5-sec bars"
                else:
                    bar_count_msg = f"sum of {num_bars} 5-sec bars (expected {expected_bars}, limited by available data)"
                    # Log a debug message if the count doesn't match expected
                    if num_bars == expected_bars + 1:
                        # Common case: we're including the start boundary when we shouldn't
                        logging.debug(f"  Note: Found {num_bars} bars (expected {expected_bars}) - likely including start boundary. Period: {resample_start} to {latest_resampled_idx}")
                    else:
                        logging.debug(f"  Note: Found {num_bars} bars, expected {expected_bars} for {strategy.timeframe}-min period (from {resample_start_exclusive} to {latest_resampled_idx})")
            
                bar_info = f"[{strategy.timeframe}-min bar] {latest_resampled_idx.strftime('%H:%M:%S')} | " \
                           f"O: {latest_resampled_row.get('open', 0):.2f} H: {latest_resampled_row.get('high', 0):.2f} " \
                           f"L: {latest_resampled_row.get('low', 0):.2f} C: {latest_resampled_row.get('close', 0):.2f} | " \
                           f"Vol: {latest_resampled_row.get('volume', 0):,.0f} ({bar_count_msg})"
                logging.info(bar_info)
                
                # Log entry criteria status for this aggregated bar
                entry_criteria = ""
                if len(data) >= strategy.bb_length and 'upper' in data.columns:
                    entry_criteria = log_entry_criteria_status(resampled_row_with_filters, data_with_filters)
                
                # Store in bar_log for dashboard
                global bar_log
                timestamp = latest_resampled_idx.strftime('%H:%M:%S')
                bar_log.append({
                    'timestamp': timestamp,
                    'bar_info': bar_info,
                    'entry_criteria': entry_criteria
                })
                # Keep only last 20 entries
                if len(bar_log) > 20:
                    bar_log = bar_log[-20:]
    
        # Only check entries/exits if we have enough data and indicators are calculated
        if len(data) >= strategy.bb_length and 'upper' in data.columns:
            latest_row = data.iloc[-1]
            check_entries(data.index[-1], latest_row)
            check_exits(data.index[-1], latest_row)

    except Exception as e:
        # Log exception concisely without printing all bar data
        bar_time_str = "unknown"
        if bars and len(bars) > 0:
            try:
                bar_time_str = bars[-1].date.strftime('%H:%M:%S') if hasattr(bars[-1], 'date') else "unknown"
            except:
                pass
        logging.error(f"Error in on_bar_update at {bar_time_str}: {type(e).__name__}: {str(e)}", exc_info=True)

# Indicators & Filters
def update_indicators():
    """Update indicators using shared strategy module."""
    if len(data) < strategy.bb_length:
        return
    
    # Calculate indicators using strategy module
    # We need to work with the full dataframe
    data_with_indicators = strategy.calculate_indicators(data.copy())
    
    # Copy indicator columns back to global data
    for col in ['mid', 'std', 'upper', 'lower', 'atr_ts']:
        if col in data_with_indicators.columns:
            data[col] = data_with_indicators[col]
    
    if strategy.fixed_atr_tp and 'atr_tp' in data_with_indicators.columns:
        data['atr_tp'] = data_with_indicators['atr_tp']
    
    # Apply filters
    data_with_filters = strategy.apply_filters(data_with_indicators)
    
    # Copy filter columns back (including maintenance and RTH filters)
    # CRITICAL FIX: Handle resampling correctly and prevent stale force_exit values
    # When resampling occurs (timeframe > 1), data_with_filters has fewer rows than data
    # We need to map filter values from resampled bars back to 1-minute bars
    
    # For force_exit and force_exit_rth: NEVER forward-fill - these must be recalculated for each bar
    # Forward-filling would cause stale True values to persist across day boundaries
    for col in ['force_exit', 'force_exit_rth']:
        if col in data_with_filters.columns:
            # Reset to False first (prevents stale values)
            data[col] = False
            # Only copy values where indices match exactly (from resampled bars)
            matching_indices = data.index.intersection(data_with_filters.index)
            if len(matching_indices) > 0:
                data.loc[matching_indices, col] = data_with_filters.loc[matching_indices, col]
            # For latest row: if it doesn't have a match, use the most recent resampled bar's value
            if len(data) > 0 and data.index[-1] not in matching_indices:
                # Find the most recent resampled bar before or at the latest bar time
                latest_time = data.index[-1]
                earlier_resampled = data_with_filters[data_with_filters.index <= latest_time]
                if len(earlier_resampled) > 0:
                    data.loc[data.index[-1], col] = earlier_resampled[col].iloc[-1]
    
    # For other filter columns: forward-fill is OK (they're less time-sensitive)
    for col in ['volume_filter', 'atr_filter', 'in_rth', 'in_maintenance']:
        if col in data_with_filters.columns:
            reindexed = data_with_filters[col].reindex(data.index, method='ffill')
            data[col] = reindexed.fillna(False)

# Entry Criteria Status Logging
def log_entry_criteria_status(resampled_row, data_with_filters):
    """Log the status of all entry criteria for an aggregated bar."""
    try:
        # Get current values
        current_price = resampled_row.get('close', 0)
        upper_bb = resampled_row.get('upper', 0)
        lower_bb = resampled_row.get('lower', 0)
        atr_value = resampled_row.get('atr_ts', 0)
        volume = resampled_row.get('volume', 0)
        
        # Check max open trades
        max_trades_check = len(positions) < strategy.max_open_trades
        max_trades_status = "✅" if max_trades_check else f"❌ ({len(positions)}/{strategy.max_open_trades})"
        
        # Check filters
        in_rth = resampled_row.get('in_rth', True)
        atr_filter = resampled_row.get('atr_filter', False)
        volume_filter = resampled_row.get('volume_filter', False)
        in_maintenance = resampled_row.get('in_maintenance', False)
        
        # Calculate volume filter threshold
        volume_ma = resampled_row.get('volume_ma', 0)
        volume_threshold = volume_ma * strategy.max_volume_multiplier if volume_ma > 0 else 0
        
        # Check entry signals (only if filters pass)
        enter_long = False
        enter_short = False
        long_reason = ""
        short_reason = ""
        
        if max_trades_check and in_rth and atr_filter and volume_filter and not in_maintenance:
            # All filters pass - check entry signals
            enter_long, enter_short = strategy.check_entry(resampled_row, data_with_filters)
            
            # Determine why entry signals are/aren't triggered
            if strategy.enable_long:
                long_trigger = lower_bb * (1 - strategy.long_trigger_pct / 100)
                low_price = resampled_row.get('low', current_price)
                close_price = resampled_row.get('close', current_price)
                
                wick_touch = strategy.long_wick_touch and low_price <= long_trigger
                body_zone = strategy.long_body_zone and close_price <= long_trigger
                
                if enter_long:
                    if wick_touch:
                        long_reason = f"Wick touch (low={low_price:.2f} <= trigger={long_trigger:.2f})"
                    elif body_zone:
                        long_reason = f"Body in zone (close={close_price:.2f} <= trigger={long_trigger:.2f})"
                    else:
                        long_reason = "Signal triggered"
                else:
                    reasons = []
                    if not wick_touch and strategy.long_wick_touch:
                        reasons.append(f"Wick not touched (low={low_price:.2f} > trigger={long_trigger:.2f})")
                    if not body_zone and strategy.long_body_zone:
                        reasons.append(f"Body not in zone (close={close_price:.2f} > trigger={long_trigger:.2f})")
                    long_reason = " | ".join(reasons) if reasons else "No entry signal"
            else:
                long_reason = "Long trades disabled"
            
            if strategy.enable_short:
                short_trigger = upper_bb * (1 + strategy.short_trigger_pct / 100)
                high_price = resampled_row.get('high', current_price)
                close_price = resampled_row.get('close', current_price)
                
                wick_touch = strategy.short_wick_touch and high_price >= short_trigger
                body_zone = strategy.short_body_zone and close_price >= short_trigger
                
                if enter_short:
                    if wick_touch:
                        short_reason = f"Wick touch (high={high_price:.2f} >= trigger={short_trigger:.2f})"
                    elif body_zone:
                        short_reason = f"Body in zone (close={close_price:.2f} >= trigger={short_trigger:.2f})"
                    else:
                        short_reason = "Signal triggered"
                else:
                    reasons = []
                    if not wick_touch and strategy.short_wick_touch:
                        reasons.append(f"Wick not touched (high={high_price:.2f} < trigger={short_trigger:.2f})")
                    if not body_zone and strategy.short_body_zone:
                        reasons.append(f"Body not in zone (close={close_price:.2f} < trigger={short_trigger:.2f})")
                    short_reason = " | ".join(reasons) if reasons else "No entry signal"
            else:
                short_reason = "Short trades disabled"
        else:
            # Filters don't pass - entry signals not checked
            if not max_trades_check:
                long_reason = f"Max trades limit ({len(positions)}/{strategy.max_open_trades})"
                short_reason = f"Max trades limit ({len(positions)}/{strategy.max_open_trades})"
            elif not in_rth:
                long_reason = "Outside RTH"
                short_reason = "Outside RTH"
            elif not atr_filter:
                long_reason = f"ATR filter failed (ATR={atr_value:.2f})"
                short_reason = f"ATR filter failed (ATR={atr_value:.2f})"
            elif not volume_filter:
                long_reason = f"Volume filter failed (vol={volume:,.0f} < threshold={volume_threshold:,.0f})"
                short_reason = f"Volume filter failed (vol={volume:,.0f} < threshold={volume_threshold:,.0f})"
            elif in_maintenance:
                long_reason = "Maintenance period"
                short_reason = "Maintenance period"
        
        # Build status line
        status_parts = []
        status_parts.append(f"Max Trades: {max_trades_status}")
        status_parts.append(f"RTH: {'✅' if in_rth else '❌'}")
        status_parts.append(f"ATR Filter: {'✅' if atr_filter else f'❌ ({atr_value:.2f})'}")
        status_parts.append(f"Vol Filter: {'✅' if volume_filter else f'❌ ({volume:,.0f} < {volume_threshold:,.0f})'}")
        status_parts.append(f"Maintenance: {'❌' if in_maintenance else '✅'}")
        status_parts.append(f"Long: {'✅' if enter_long else '❌'} ({long_reason})")
        status_parts.append(f"Short: {'✅' if enter_short else '❌'} ({short_reason})")
        
        # Add BB position info
        if upper_bb > 0 and lower_bb > 0:
            pct_from_lower = ((current_price - lower_bb) / lower_bb * 100) if lower_bb > 0 else 0
            pct_from_upper = ((upper_bb - current_price) / upper_bb * 100) if upper_bb > 0 else 0
            status_parts.append(f"BB: Lower={lower_bb:.2f} | Price={current_price:.2f} | Upper={upper_bb:.2f} | {pct_from_lower:+.2f}% from lower, {pct_from_upper:+.2f}% from upper")
        
        criteria_str = ' | '.join(status_parts)
        logging.info(f"  Entry Criteria: {criteria_str}")
        return criteria_str
        
    except Exception as e:
        logging.debug(f"Error logging entry criteria status: {e}")
        return ""

# Entry Logic
def check_entries(idx, latest_row):
    if len(positions) >= strategy.max_open_trades:
        return
    
    if len(data) < 2:
        return
    
    # Check filters (including maintenance - blocks entries during maintenance + buffer)
    in_maintenance = latest_row.get('in_maintenance', False)
    if not (latest_row.get('in_rth', True) and latest_row.get('atr_filter', False) and 
            latest_row.get('volume_filter', False) and not in_maintenance):
        return
    
    # Use strategy module to check entry (latest_row should have all indicators)
    enter_long, enter_short = strategy.check_entry(latest_row, data)
    
    if not (enter_long or enter_short):
        return
    
    direction = 1 if enter_long else -1
    action = 'BUY' if direction == 1 else 'SELL'
    qty = 1
    
    # Setup position using strategy module
    entry_price = latest_row['close']
    position_dict = strategy.setup_position(entry_price, direction, latest_row, data)
    
    stop_price = position_dict['stop']
    tp = position_dict.get('tp')
    
    # Round prices to ES tick size (0.25)
    entry_price = round(entry_price * 4) / 4
    stop_price = round(stop_price * 4) / 4
    if tp is not None:
        tp = round(tp * 4) / 4
    
    # Create bracket order manually with proper parent-child relationships
    # Entry order (market order for immediate execution)
    entry_order = MarketOrder(
        action=action,
        totalQuantity=qty,
        transmit=False  # Don't transmit until children are attached
    )
    
    # Place entry order first to get orderId
    trade = ib.placeOrder(contract, entry_order)
    
    # Wait for order to be submitted and get the orderId
    ib.sleep(1)  # Give IB time to process the order
    
    # Get orderId from the order or trade
    entry_order_id = entry_order.orderId
    if entry_order_id == 0:
        # If orderId not set, try to get it from the trade
        if trade and trade.order:
            entry_order_id = trade.order.orderId
        if entry_order_id == 0:
            logging.error("Failed to get entry orderId, cannot create bracket")
            return
    
    # Stop loss order (constructor accepts stopPrice, but stores as auxPrice)
    # Use GTC (Good Till Canceled) for ES futures to allow after-hours execution
    stop_action = 'SELL' if direction == 1 else 'BUY'
    stop_order = StopOrder(
        action=stop_action,
        totalQuantity=qty,
        stopPrice=stop_price,  # Constructor parameter
        parentId=entry_order_id,
        tif='GTC',  # Good Till Canceled - allows after-hours execution for ES futures
        transmit=False if tp is not None else True  # Transmit if no TP
    )
    
    # Take profit order (if specified)
    tp_order = None
    if tp is not None:
        tp_action = 'SELL' if direction == 1 else 'BUY'
        tp_order = LimitOrder(
            action=tp_action,
            totalQuantity=qty,
            lmtPrice=tp,
            parentId=entry_order_id,
            tif='GTC',  # Good Till Canceled - allows after-hours execution for ES futures
            transmit=True  # Transmit the bracket (last order)
        )
        ib.placeOrder(contract, stop_order)
        ib.placeOrder(contract, tp_order)
    else:
        # No TP, just transmit the stop
        ib.placeOrder(contract, stop_order)
    
    # Wait a moment for orders to be processed
    ib.sleep(0.5)
    
    # Log orders after placement
    log_all_open_orders("After placing new trade")
    
    # Store bracket as dict for easier access
    # Include position_dict fields needed for trailing stop tracking
    entry_time = datetime.now()
    bracket = {
        'entry': entry_order,
        'stopLoss': stop_order,
        'takeProfit': tp_order,
        'direction': direction,
        'position_dict': position_dict,  # Store full position dict for strategy module
        'entry_time': entry_time,  # Track entry time for duration calculation
        'entry_price': entry_price  # Store entry price for close email
    }
    positions.append(bracket)
    
    # Get account summary
    account = get_account_summary()
    current_price = latest_row['close']
    
    # Calculate risk and reward in dollars
    # ES contract multiplier is 50
    contract_multiplier = 50
    risk_dollars = abs(entry_price - stop_price) * contract_multiplier * qty
    reward_dollars = abs(entry_price - tp) * contract_multiplier * qty if tp is not None else None
    risk_reward_ratio = reward_dollars / risk_dollars if (tp is not None and risk_dollars > 0) else None
    
    # Build comprehensive email
    msg_lines = [
        f"TRADE OPEN - {'LONG' if direction==1 else 'SHORT'}",
        f"{'='*50}",
        f"Entry Price: ${entry_price:.2f}",
        f"Current Price: ${current_price:.2f}",
        f"Stop Loss: ${stop_price:.2f} (Risk: ${risk_dollars:,.2f})",
        f"Take Profit: ${tp:.2f} (Reward: ${reward_dollars:,.2f})" if tp is not None else "Take Profit: None",
        f"Risk/Reward Ratio: {risk_reward_ratio:.2f}:1" if risk_reward_ratio else "Risk/Reward Ratio: N/A",
        f"Position Size: {qty} contract(s)",
        f"Entry Order ID: {entry_order.permId}",
        f"",
        f"Account Information:",
    ]
    
    # Add account values (show 0.00 if available, N/A only if truly missing)
    net_liq = account.get('NetLiquidation')
    if net_liq is not None:
        msg_lines.append(f"  Net Liquidation: ${net_liq:,.2f}")
    else:
        msg_lines.append("  Net Liquidation: N/A")
    
    total_cash = account.get('TotalCashValue')
    if total_cash is not None:
        msg_lines.append(f"  Total Cash: ${total_cash:,.2f}")
    else:
        msg_lines.append("  Total Cash: N/A")
    
    buying_power = account.get('BuyingPower')
    if buying_power is not None:
        msg_lines.append(f"  Buying Power: ${buying_power:,.2f}")
    else:
        msg_lines.append("  Buying Power: N/A")
    
    msg_lines.extend([
        f"  Total Unrealized PNL: ${account.get('UnrealizedPNL', 0):,.2f}",
        f"  Total Realized PNL: ${account.get('RealizedPNL', 0):,.2f}",
        f"  Open ES Positions: {account.get('ES_Positions', 0)}",
        f"",
        f"Time: {entry_time.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    ])
    
    msg = "\n".join(msg_lines)
    send_email("BB Strategy - Trade OPEN", msg)
    logging.info(msg.replace('\n', ' | '))
    dashboard_stats['trades_opened'] += 1
    dashboard_stats['orders_placed'] += 3 if tp is not None else 2  # Entry + SL + TP (if exists)
    add_to_live_tracker('trade', f"TRADE OPEN: {'LONG' if direction==1 else 'SHORT'} {qty} @ ${entry_price:.2f}, SL: ${stop_price:.2f}, TP: ${tp:.2f}" if tp else f"TRADE OPEN: {'LONG' if direction==1 else 'SHORT'} {qty} @ ${entry_price:.2f}, SL: ${stop_price:.2f}")
    
    if len(positions) == 1:
        status_timer.start()

# Exit Logic (for manual closes or trailing updates)
def check_exits(idx, latest_row):
    # Check for RTH force exit (close all positions before RTH ends)
    if strategy.enable_rth_filter and strategy.rth_exit_buffer_minutes > 0:
        force_exit_rth = latest_row.get('force_exit_rth', False) if isinstance(latest_row, dict) else getattr(latest_row, 'force_exit_rth', False)
        if force_exit_rth:
            # Only log warning if we have positions to close
            es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
            has_open_position = any(abs(p.position) > 0 for p in es_positions)
            
            if has_open_position or len(positions) > 0:
                # Only log warning once per RTH period to avoid spam
                if not hasattr(check_exits, '_rth_warning_logged'):
                    logging.warning(f"⚠️ RTH ENDING - Closing all positions ({strategy.rth_exit_buffer_minutes} min buffer)")
                    add_to_live_tracker('warning', f'RTH: Closing all positions {strategy.rth_exit_buffer_minutes} minutes before RTH end')
                    check_exits._rth_warning_logged = True
            else:
                # No positions to close - reset warning flag
                if hasattr(check_exits, '_rth_warning_logged'):
                    delattr(check_exits, '_rth_warning_logged')
                return  # Exit early if no positions
            
            # Close all open positions
            for bracket in positions[:]:
                try:
                    entry_order = bracket['entry']
                    entry_trade = None
                    for trade in ib.trades():
                        if trade.order.permId == entry_order.permId:
                            entry_trade = trade
                            break
                    
                    if not entry_trade or entry_trade.isActive():
                        continue
                    
                    # Get actual position from IB
                    es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
                    if not es_positions or es_positions[0].position == 0:
                        positions.remove(bracket)
                        continue
                    
                    actual_position = es_positions[0].position
                    actual_qty = abs(actual_position)
                    close_action = 'SELL' if actual_position > 0 else 'BUY'
                    
                    logging.info(f"Closing position for RTH end: {close_action} {actual_qty} @ market")
                    
                    # Cancel all orders first
                    stop_order = bracket.get('stopLoss')
                    tp_order = bracket.get('takeProfit')
                    
                    for order in [stop_order, tp_order]:
                        if order:
                            try:
                                ib.cancelOrder(order)
                            except:
                                pass
                    
                    # Close position with market order
                    close_order = MarketOrder(action=close_action, totalQuantity=actual_qty, transmit=True)
                    close_trade = ib.placeOrder(contract, close_order)
                    ib.sleep(2)  # Wait for execution
                    
                    # Get exit price and PNL
                    if close_trade.orderStatus and close_trade.orderStatus.filled > 0:
                        exit_price = close_trade.orderStatus.avgFillPrice
                        direction = bracket.get('direction', 0)
                        entry_price = bracket.get('entry_price', 0)
                        pnl = (exit_price - entry_price) * direction * 50  # ES multiplier
                        
                        logging.info(f"Position closed for RTH: Exit @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")
                        add_to_live_tracker('trade', f"RTH EXIT: {'LONG' if direction==1 else 'SHORT'} @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")
                    
                    # Remove from tracking
                    positions.remove(bracket)
                    
                except Exception as e:
                    logging.error(f"Error closing position for RTH end: {e}")
                    import traceback
                    logging.error(traceback.format_exc())
            
            # Send email notification
            try:
                account = get_account_summary()
                msg_lines = [
                    f"RTH END - All Positions Closed",
                    f"{'='*50}",
                    f"All open positions have been closed {strategy.rth_exit_buffer_minutes} minutes before RTH end.",
                    f"RTH End Time: {strategy.rth_end_str} ET",
                    f"",
                    f"Account Information:",
                    f"  Net Liquidation: ${account.get('NetLiquidation', 0):,.2f}",
                    f"  Total Cash: ${account.get('TotalCashValue', 0):,.2f}",
                    f"  Total Realized PNL: ${account.get('RealizedPNL', 0):,.2f}",
                    f"",
                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}"
                ]
                msg = "\n".join(msg_lines)
                send_email("BB Strategy - RTH End - Positions Closed", msg)
            except Exception as e:
                logging.error(f"Error sending RTH exit email: {e}")
            
            return  # Exit early after closing all positions
    
    # Check for maintenance force exit (close all positions 5 min before maintenance)
    if strategy.enable_maintenance_filter:
        force_exit = latest_row.get('force_exit', False) if isinstance(latest_row, dict) else getattr(latest_row, 'force_exit', False)
        if force_exit:
            # Only log warning and close positions if we actually have positions
            es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
            has_open_position = any(abs(p.position) > 0 for p in es_positions)
            
            if has_open_position or len(positions) > 0:
                # Get current time to show when maintenance actually is
                current_time = datetime.now(pytz.timezone('America/New_York')).time()
                # Only log warning once per maintenance period to avoid spam
                if not hasattr(check_exits, '_maintenance_warning_logged'):
                    logging.warning(f"⚠️ MAINTENANCE PERIOD APPROACHING - Closing all positions (Current: {current_time.strftime('%H:%M:%S')} ET)")
                    add_to_live_tracker('warning', f'MAINTENANCE: Closing all positions 5 minutes before maintenance period ({current_time.strftime("%H:%M")} ET)')
                    check_exits._maintenance_warning_logged = True
            else:
                # No positions to close, but force_exit is True - this is normal during buffer period
                # Don't log warning if there are no positions
                # Reset warning flag when force_exit becomes False again
                if hasattr(check_exits, '_maintenance_warning_logged'):
                    delattr(check_exits, '_maintenance_warning_logged')
                return
            
            # Close all open positions
            for bracket in positions[:]:
                try:
                    entry_order = bracket['entry']
                    entry_trade = None
                    for trade in ib.trades():
                        if trade.order.permId == entry_order.permId:
                            entry_trade = trade
                            break
                    
                    if not entry_trade or entry_trade.isActive():
                        continue
                    
                    # Get actual position from IB
                    es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
                    if not es_positions or es_positions[0].position == 0:
                        positions.remove(bracket)
                        continue
                    
                    actual_position = es_positions[0].position
                    actual_qty = abs(actual_position)
                    close_action = 'SELL' if actual_position > 0 else 'BUY'
                    
                    logging.info(f"Closing position for maintenance: {close_action} {actual_qty} @ market")
                    
                    # Cancel all orders first
                    stop_order = bracket.get('stopLoss')
                    tp_order = bracket.get('takeProfit')
                    
                    for order in [stop_order, tp_order]:
                        if order:
                            try:
                                ib.cancelOrder(order)
                            except:
                                pass
                    
                    # Close position with market order
                    close_order = MarketOrder(action=close_action, totalQuantity=actual_qty, transmit=True)
                    close_trade = ib.placeOrder(contract, close_order)
                    ib.sleep(2)  # Wait for execution
                    
                    # Get exit price and PNL
                    if close_trade.fills:
                        exit_price = close_trade.fills[0].execution.price
                        fill = entry_trade.fills[0].execution if entry_trade.fills else None
                        if fill:
                            entry_price = fill.price
                            dir_ = 1 if fill.side == 'BOT' else -1
                            qty = fill.shares
                            pnl = (exit_price - entry_price) * dir_ * qty * multiplier
                            
                            add_to_live_tracker('trade', 
                                f"TRADE CLOSE (Maintenance): {'LONG' if dir_==1 else 'SHORT'} {qty} @ ${exit_price:.2f}, "
                                f"PNL: ${pnl:,.2f}")
                            
                            msg = (f"TRADE CLOSE (Maintenance) - {'LONG' if dir_==1 else 'SHORT'}\n"
                                   f"Entry: {entry_price:.2f}\n"
                                   f"Exit: {exit_price:.2f}\n"
                                   f"PNL: {pnl:,.2f}")
                            send_email("BB Strategy - Trade CLOSE (Maintenance)", msg)
                    
                    positions.remove(bracket)
                except Exception as e:
                    logging.error(f"Error closing position for maintenance: {e}")
                    # Remove bracket anyway to prevent retry loops
                    if bracket in positions:
                        positions.remove(bracket)
            
            if not positions:
                status_timer.stop()
            return  # Exit early after closing all positions
    
    for bracket in positions[:]:
        entry_order = bracket['entry']
        stop_order = bracket['stopLoss']
        tp_order = bracket['takeProfit']
        dir_ = bracket['direction']
        
        # Find the trade for the entry order
        entry_trade = None
        for trade in ib.trades():
            if trade.order.permId == entry_order.permId:
                entry_trade = trade
                break
        
        if not entry_trade or entry_trade.isActive():
            continue
        
        # Get direction from entry (verify with fill)
        fill = entry_trade.fills[0].execution if entry_trade.fills else None
        if not fill:
            continue
        
        # Find stop and TP trades
        stop_trade = None
        tp_trade = None
        for trade in ib.trades():
            if trade.order.permId == stop_order.permId:
                stop_trade = trade
            if tp_order and trade.order.permId == tp_order.permId:
                tp_trade = trade
        
        # Check if stop should trigger (price has hit stop level)
        current_price = latest_row['close']
        # StopOrder stores price in auxPrice (even though constructor uses stopPrice)
        stop_price = getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', 0))
        
        # For long positions: stop triggers when price falls below stop
        # For short positions: stop triggers when price rises above stop
        stop_should_trigger = False
        if dir_ == 1:  # Long position
            stop_should_trigger = current_price <= stop_price
        else:  # Short position
            stop_should_trigger = current_price >= stop_price
        
        # If stop should trigger, handle it
        if stop_should_trigger:
            # Check stop order status
            stop_order_status = None
            stop_order_why_held = ''
            if stop_trade and stop_trade.orderStatus:
                stop_order_status = stop_trade.orderStatus.status
                stop_order_why_held = getattr(stop_trade.orderStatus, 'whyHeld', '')
            
            # If stop order is in PreSubmitted with 'trigger' (waiting for market open),
            # and price has moved through stop level, we need to manually close the position
            if stop_order_status == 'PreSubmitted' and 'trigger' in stop_order_why_held.lower():
                logging.warning(f"CRITICAL: Stop should trigger at {stop_price:.2f}, current price {current_price:.2f}")
                logging.warning(f"Stop order is in PreSubmitted (waiting for market open). Manually closing position to protect against further loss.")
                
                # Cancel TP order if active
                if tp_order and tp_trade and tp_trade.isActive():
                    try:
                        ib.cancelOrder(tp_order)
                        logging.info("Cancelled TP order before manual stop execution")
                    except Exception as e:
                        logging.warning(f"Error cancelling TP order: {e}")
                
                # Cancel the stop order (it won't execute anyway during after-hours)
                try:
                    ib.cancelOrder(stop_order)
                    logging.info("Cancelled stop order (was waiting for market open)")
                except Exception as e:
                    logging.warning(f"Error cancelling stop order: {e}")
                
                # Manually close the position with a market order
                # CRITICAL: Get actual position from IB to ensure correct direction and quantity
                try:
                    es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
                    if not es_positions or es_positions[0].position == 0:
                        logging.warning("No position found in IB. Position may have already closed.")
                        # Remove bracket anyway
                        positions.remove(bracket)
                        continue
                    
                    actual_position = es_positions[0].position
                    actual_qty = abs(actual_position)
                    actual_direction = 1 if actual_position > 0 else -1
                    
                    # Close action is opposite of position direction
                    # LONG position (positive) -> SELL to close
                    # SHORT position (negative) -> BUY to close
                    close_action = 'SELL' if actual_position > 0 else 'BUY'
                    
                    logging.warning(f"Actual position from IB: {actual_position} contracts ({'LONG' if actual_position > 0 else 'SHORT'})")
                    logging.warning(f"Placing {close_action} {actual_qty} @ market to close position")
                    
                    close_order = MarketOrder(action=close_action, totalQuantity=actual_qty, transmit=True)
                    close_trade = ib.placeOrder(contract, close_order)
                    
                    # Wait for execution
                    ib.sleep(3)
                    
                    # Check if position was closed
                    es_positions_after = [p for p in ib.positions() if p.contract.conId == contract.conId]
                    position_closed = not es_positions_after or es_positions_after[0].position == 0
                    
                    if position_closed:
                        logging.info("Position successfully closed via manual market order")
                        # Remove bracket and exit this iteration
                        positions.remove(bracket)
                        # Send close email
                        try:
                            entry_price = bracket.get('entry_price', 0)
                            if not entry_price and entry_trade and entry_trade.fills:
                                entry_price = entry_trade.fills[0].execution.price
                            
                            exit_price = close_trade.fills[0].execution.price if close_trade.fills else current_price
                            pnl = (exit_price - entry_price) * actual_direction * contract.multiplier * actual_qty if entry_price > 0 else 0
                            
                            # Try to get PNL from commission report
                            if close_trade.fills:
                                for fill in close_trade.fills:
                                    if fill.commissionReport and hasattr(fill.commissionReport, 'realizedPNL'):
                                        pnl = fill.commissionReport.realizedPNL
                                        break
                            
                            # Send close email (simplified version)
                            msg_lines = [
                                f"TRADE CLOSE - {'LONG' if actual_direction==1 else 'SHORT'} (Manual Close)",
                                f"{'='*50}",
                                f"Entry Price: ${entry_price:.2f}",
                                f"Exit Price: ${exit_price:.2f}",
                                f"Position Size: {actual_qty} contract(s)",
                                f"Reason: Manual Close (Stop triggered, order in PreSubmitted)",
                                f"PNL: ${pnl:,.2f}",
                                f"",
                                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            ]
                            msg = "\n".join(msg_lines)
                            send_email("BB Strategy - Trade CLOSE", msg)
                            logging.info(msg.replace('\n', ' | '))
                            dashboard_stats['trades_closed'] += 1
                            dashboard_stats['orders_filled'] += 1
                            add_to_live_tracker('trade', f"TRADE CLOSE (Manual): {'LONG' if actual_direction==1 else 'SHORT'} {actual_qty} @ ${exit_price:.2f}, PNL: ${pnl:,.2f}")
                        except Exception as e:
                            logging.warning(f"Error sending close email: {e}")
                        
                        if not positions:
                            status_timer.stop()
                        continue  # Skip trailing stop update for this bracket
                    else:
                        remaining_position = es_positions_after[0].position if es_positions_after else 0
                        logging.error(f"WARNING: Position still open after manual close attempt! Remaining: {remaining_position}")
                        # Don't remove bracket - position is still open
                        
                except Exception as e:
                    logging.error(f"CRITICAL ERROR: Failed to manually close position: {e}")
                    import traceback
                    logging.error(f"Traceback: {traceback.format_exc()}")
            
            # If stop order is active (not waiting for market open), just cancel TP
            elif stop_trade and stop_trade.isActive():
                if tp_order and tp_trade and tp_trade.isActive():
                    logging.warning(f"Stop should trigger at {stop_price:.2f}, current price {current_price:.2f}. Cancelling TP order.")
                    log_all_open_orders("Before cancelling TP (stop should trigger)")
                    ib.cancelOrder(tp_order)
                    ib.sleep(0.5)
                    log_all_open_orders("After cancelling TP")
        
        # Check if position still exists before updating trailing stop
        # (Position may have closed via TP or stop)
        position_still_open = any(t.contract.conId == contract.conId for t in ib.positions())
        
        # Trailing stop update if enabled and position is still open
        if position_still_open:
            # Use strategy module's update_trailing_stop which handles bars_held and delay
            position_dict = bracket.get('position_dict', {})
            if not position_dict:
                # Fallback: create minimal position dict if missing (for existing positions)
                current_stop = getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', 0))
                position_dict = {
                    'direction': dir_,
                    'bars_held': 0,  # Will start counting from now
                    'stop': current_stop,
                    'max_high': latest_row['high'] if dir_ == 1 else None,
                    'min_low': latest_row['low'] if dir_ == -1 else None
                }
                bracket['position_dict'] = position_dict
                logging.warning(f"Created position_dict for existing position (bars_held reset to 0)")
            
            # Update trailing stop using strategy module (handles delay check)
            bars_held = position_dict.get('bars_held', 0)
            stop_updated = strategy.update_trailing_stop(position_dict, latest_row, data)
            new_bars_held = position_dict.get('bars_held', 0)
            
            # Log trailing stop status
            if strategy.enable_trailing:
                if new_bars_held < strategy.trailing_delay:
                    logging.debug(f"Trailing stop delay: {new_bars_held}/{strategy.trailing_delay} bars held")
                elif stop_updated:
                    logging.info(f"Trailing stop updated: bars_held={new_bars_held}, new_stop={position_dict['stop']:.2f}")
            
            # Check if stop order is active (including PreSubmitted with trigger)
            stop_order_active = False
            if stop_trade:
                stop_order_active = stop_trade.isActive()
                # Also check if status is PreSubmitted (waiting to trigger)
                if not stop_order_active and stop_trade.orderStatus:
                    status = stop_trade.orderStatus.status
                    if status in ['PreSubmitted', 'Submitted', 'PendingSubmit']:
                        stop_order_active = True
            
            if stop_updated and stop_order_active:
                # Strategy module updated the stop, now update IB order
                new_stop = position_dict['stop']
                new_stop = round(new_stop * 4) / 4  # Round to tick size
                current_stop = getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', 0))
                
                # Only update if stop actually changed
                if (dir_ == 1 and new_stop > current_stop) or (dir_ == -1 and new_stop < current_stop):
                    # SAFER APPROACH: Place new stop first, verify it's active, then cancel old one
                    # This ensures position is always protected (minimal gap risk)
                    stop_action = 'SELL' if dir_ == 1 else 'BUY'
                    qty = abs(stop_order.totalQuantity)
                    
                    # Log orders before update
                    log_all_open_orders("Before trailing stop update")
                    
                    # Create and place new stop order first
                    new_stop_order = StopOrder(
                        action=stop_action,
                        totalQuantity=qty,
                        stopPrice=new_stop,
                        tif='GTC',  # Good Till Canceled - allows after-hours execution for ES futures
                        transmit=True  # Ensure it's transmitted immediately
                    )
                    
                    try:
                        # Place new stop order
                        new_trade = ib.placeOrder(contract, new_stop_order)
                        logging.info(f"Placed new stop order at {new_stop:.2f} (old stop: {current_stop:.2f})")
                        
                        # Wait for new order to be submitted and check status
                        ib.sleep(1.5)  # Give IB time to process
                        
                        # Verify new order is active before canceling old one
                        # Try multiple methods to find the new order:
                        # 1. Use the trade object returned by placeOrder
                        # 2. Find by orderId if available
                        # 3. Find by permId if available
                        # 4. Find by matching characteristics (stop price, action, type)
                        new_order_active = False
                        new_trade_obj = None
                        
                        # Method 1: Use the trade object returned by placeOrder
                        if new_trade and new_trade.order:
                            new_trade_obj = new_trade
                            # Check if it's active or in a valid pending state
                            if new_trade.isActive() or (new_trade.orderStatus and 
                                new_trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                                new_order_active = True
                                # Update permId if available
                                if hasattr(new_trade.order, 'permId') and new_trade.order.permId != 0:
                                    new_stop_order.permId = new_trade.order.permId
                                if hasattr(new_trade.order, 'orderId') and new_trade.order.orderId != 0:
                                    new_stop_order.orderId = new_trade.order.orderId
                        
                        # Method 2: Find by orderId if not found yet
                        if not new_order_active and hasattr(new_stop_order, 'orderId') and new_stop_order.orderId != 0:
                            for trade in ib.trades():
                                if (trade.contract.conId == contract.conId and 
                                    trade.order.orderId == new_stop_order.orderId):
                                    new_trade_obj = trade
                                    if trade.isActive() or (trade.orderStatus and 
                                        trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                                        new_order_active = True
                                        if hasattr(trade.order, 'permId') and trade.order.permId != 0:
                                            new_stop_order.permId = trade.order.permId
                                    break
                        
                        # Method 3: Find by permId if available
                        if not new_order_active and hasattr(new_stop_order, 'permId') and new_stop_order.permId != 0:
                            for trade in ib.trades():
                                if (trade.contract.conId == contract.conId and 
                                    trade.order.permId == new_stop_order.permId):
                                    new_trade_obj = trade
                                    if trade.isActive() or (trade.orderStatus and 
                                        trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                                        new_order_active = True
                                    break
                        
                        # Method 4: Find by matching characteristics (stop price, action, type)
                        if not new_order_active:
                            for trade in ib.trades():
                                if (trade.contract.conId == contract.conId and 
                                    isinstance(trade.order, StopOrder) and
                                    trade.order.action == stop_action):
                                    trade_stop = getattr(trade.order, 'auxPrice', getattr(trade.order, 'stopPrice', 0))
                                    if abs(trade_stop - new_stop) < 0.01:  # Match within 1 cent
                                        new_trade_obj = trade
                                        if trade.isActive() or (trade.orderStatus and 
                                            trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                                            new_order_active = True
                                            if hasattr(trade.order, 'permId') and trade.order.permId != 0:
                                                new_stop_order.permId = trade.order.permId
                                            if hasattr(trade.order, 'orderId') and trade.order.orderId != 0:
                                                new_stop_order.orderId = trade.order.orderId
                                        break
                        
                        if new_order_active:
                            # New order is active, safe to cancel old one
                            # Note: Brief period where both might be active, but only one can trigger
                            log_all_open_orders("Before cancelling old stop (new one is active)")
                            try:
                                ib.cancelOrder(stop_order)
                                ib.sleep(0.5)
                                logging.info(f"Cancelled old stop order at {current_stop:.2f}")
                                dashboard_stats['orders_cancelled'] += 1
                                add_to_live_tracker('order', f"Trailing stop updated: cancelled old stop @ ${current_stop:.2f}, placed new stop @ ${new_stop:.2f}")
                            except Exception as e:
                                logging.warning(f"Error cancelling old stop order (new one is active): {e}")
                                # Check if old order was auto-cancelled by IB
                                old_still_active = False
                                for trade in ib.trades():
                                    if (trade.order.permId == stop_order.permId and 
                                        trade.isActive() and 
                                        trade.contract.conId == contract.conId):
                                        old_still_active = True
                                        break
                                if not old_still_active:
                                    logging.info("Old stop order was automatically cancelled by IB")
                            
                            # Update the bracket with the new stop order
                            bracket['stopLoss'] = new_stop_order
                            logging.info(f"Successfully updated trailing stop to {new_stop:.2f}")
                            
                            # Verify TP order is still active after trailing stop update
                            if tp_order:
                                tp_still_active = False
                                for trade in ib.trades():
                                    if (trade.order.permId == tp_order.permId and 
                                        trade.contract.conId == contract.conId):
                                        if trade.isActive() or (trade.orderStatus and 
                                            trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit']):
                                            tp_still_active = True
                                        break
                                
                                if not tp_still_active:
                                    logging.warning(f"WARNING: TP order (PermID: {tp_order.permId}) is no longer active after trailing stop update!")
                                    logging.warning("TP may have been cancelled by IB when bracket was modified. Attempting to recreate...")
                                    
                                    # Recreate TP order
                                    try:
                                        tp_price = getattr(tp_order, 'lmtPrice', 0)
                                        if tp_price > 0:
                                            tp_action = 'SELL' if dir_ == 1 else 'BUY'
                                            new_tp_order = LimitOrder(
                                                action=tp_action,
                                                totalQuantity=qty,
                                                lmtPrice=tp_price,
                                                tif='GTC',  # Good Till Canceled - allows after-hours execution for ES futures
                                                transmit=True
                                            )
                                            tp_trade = ib.placeOrder(contract, new_tp_order)
                                            ib.sleep(0.5)
                                            
                                            # Verify new TP order is active
                                            # Use the trade object returned by placeOrder, or find by matching characteristics
                                            new_tp_active = False
                                            if tp_trade and tp_trade.order:
                                                if tp_trade.isActive() or (tp_trade.orderStatus and 
                                                    tp_trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit']):
                                                    new_tp_active = True
                                                    # Update the order object with permId if assigned
                                                    if hasattr(tp_trade.order, 'permId') and tp_trade.order.permId != 0:
                                                        new_tp_order.permId = tp_trade.order.permId
                                            else:
                                                # Fallback: find by matching LimitOrder with same price and action
                                                for trade in ib.trades():
                                                    if (trade.contract.conId == contract.conId and 
                                                        isinstance(trade.order, LimitOrder) and
                                                        trade.order.action == tp_action and
                                                        abs(getattr(trade.order, 'lmtPrice', 0) - tp_price) < 0.01):
                                                        if trade.isActive() or (trade.orderStatus and 
                                                            trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit']):
                                                            new_tp_active = True
                                                            if hasattr(trade.order, 'permId') and trade.order.permId != 0:
                                                                new_tp_order.permId = trade.order.permId
                                                            break
                                            
                                            if new_tp_active:
                                                bracket['takeProfit'] = new_tp_order
                                                logging.info(f"Successfully recreated TP order at {tp_price:.2f}")
                                            else:
                                                logging.error(f"Failed to recreate TP order - new order is not active")
                                        else:
                                            logging.error(f"Cannot recreate TP order - original TP price not found")
                                    except Exception as e:
                                        logging.error(f"Error recreating TP order: {e}")
                                else:
                                    logging.debug(f"TP order (PermID: {tp_order.permId}) is still active after trailing stop update")
                            
                            # Log orders after trailing stop update
                            ib.sleep(0.5)  # Brief wait for cleanup
                            log_all_open_orders("After trailing stop update")
                        else:
                            # New order didn't activate - could be rejected or pending
                            if new_trade_obj:
                                status = new_trade_obj.orderStatus.status if new_trade_obj.orderStatus else "Unknown"
                                why_held = getattr(new_trade_obj.orderStatus, 'whyHeld', '') if new_trade_obj.orderStatus else ''
                                logging.warning(f"New stop order status: {status} (whyHeld: {why_held}). Keeping old stop active.")
                                
                                # Log order details for debugging
                                if hasattr(new_trade_obj.order, 'orderId'):
                                    logging.warning(f"  OrderID: {new_trade_obj.order.orderId}")
                                if hasattr(new_trade_obj.order, 'permId'):
                                    logging.warning(f"  PermID: {new_trade_obj.order.permId}")
                                
                                # If order is in PreSubmitted with trigger, it's waiting for market open - that's OK
                                if status == 'PreSubmitted' and 'trigger' in why_held.lower():
                                    logging.info("Order is waiting for market open (PreSubmitted with trigger). Will activate when market opens.")
                                    # Don't cancel - let it activate when market opens
                                    # Update bracket with new order anyway so we track it
                                    bracket['stopLoss'] = new_stop_order
                                    if hasattr(new_trade_obj.order, 'permId') and new_trade_obj.order.permId != 0:
                                        new_stop_order.permId = new_trade_obj.order.permId
                            else:
                                logging.warning(f"New stop order not found in trades. Keeping old stop active.")
                                logging.warning(f"  Attempted to place stop at {new_stop:.2f}, but order not found after placement.")
                                # Log all active orders to help debug
                                log_all_open_orders("After failed order placement")
                            
                            # Cancel the new order if it exists but isn't active (unless it's waiting for market open)
                            try:
                                if new_trade_obj and new_trade_obj.orderStatus:
                                    status = new_trade_obj.orderStatus.status
                                    why_held = getattr(new_trade_obj.orderStatus, 'whyHeld', '')
                                    if not (status == 'PreSubmitted' and 'trigger' in why_held.lower()):
                                        ib.cancelOrder(new_stop_order)
                                        logging.info("Cancelled new stop order that failed to activate")
                            except Exception as cancel_err:
                                logging.debug(f"Error cancelling new order: {cancel_err}")
                            # Old stop order remains active as protection
                            
                    except Exception as e:
                        logging.error(f"Failed to place new stop order: {e}")
                        import traceback
                        logging.error(f"Traceback: {traceback.format_exc()}")
                        # Old stop order remains active as fallback protection
            
            # Update dynamic TP (Opposite BB TP) if enabled and position is still open
            if position_still_open and strategy.opposite_bb_tp and tp_order:
                # Calculate new TP from current opposite BB level
                if 'upper' in data.columns and 'lower' in data.columns and len(data) > 0:
                    new_tp_raw = data['upper'].iloc[-1] if dir_ == 1 else data['lower'].iloc[-1]
                    
                    # Check if new_tp is NaN (can happen if not enough data for BB calculation)
                    if pd.isna(new_tp_raw) or np.isnan(new_tp_raw):
                        logging.debug(f"Opposite BB TP: Skipping update - BB value is NaN (not enough data)")
                        # Skip TP update - keep current TP active
                    else:
                        new_tp = float(new_tp_raw)
                        new_tp = round(new_tp * 4) / 4  # Round to tick size
                        
                        # Get current TP price
                        current_tp = getattr(tp_order, 'lmtPrice', 0)
                        
                        # Debug logging - always log when checking
                        logging.info(f"Opposite BB TP check: current_tp={current_tp:.2f}, new_tp={new_tp:.2f}, dir={'LONG' if dir_==1 else 'SHORT'}")
                        
                        # For Opposite BB TP, the TP should track the opposite BB level in BOTH directions
                        # Only update if the new TP is different from current (within tick size tolerance)
                        tp_should_update = abs(new_tp - current_tp) >= 0.25  # ES tick size is 0.25
                        
                        if tp_should_update:
                            logging.info(f"Opposite BB TP update: old={current_tp:.2f}, new={new_tp:.2f}")
                            
                            # Find tp_trade from ib.trades() if not already available
                            tp_trade = None
                            if hasattr(tp_order, 'permId') and tp_order.permId != 0:
                                for trade in ib.trades():
                                    if (trade.contract.conId == contract.conId and 
                                        trade.order.permId == tp_order.permId):
                                        tp_trade = trade
                                        break
                            
                            # If still not found, try to find by matching characteristics
                            if tp_trade is None:
                                tp_action = 'SELL' if dir_ == 1 else 'BUY'
                                for trade in ib.trades():
                                    if (trade.contract.conId == contract.conId and 
                                        isinstance(trade.order, LimitOrder) and
                                        trade.order.action == tp_action and
                                        abs(getattr(trade.order, 'lmtPrice', 0) - current_tp) < 0.01):
                                        tp_trade = trade
                                        # Update permId if found
                                        if hasattr(trade.order, 'permId') and trade.order.permId != 0:
                                            tp_order.permId = trade.order.permId
                                        break
                            
                            # Check if TP order is active
                            tp_order_active = False
                            if tp_trade:
                                tp_order_active = tp_trade.isActive()
                                if not tp_order_active and tp_trade.orderStatus:
                                    status = tp_trade.orderStatus.status
                                    if status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']:
                                        tp_order_active = True
                            else:
                                logging.warning(f"Could not find tp_trade for TP order. Checking if order exists in ib.trades()...")
                                # Last resort: check if any active TP order exists
                                tp_action = 'SELL' if dir_ == 1 else 'BUY'
                                for trade in ib.trades():
                                    if (trade.contract.conId == contract.conId and 
                                        isinstance(trade.order, LimitOrder) and
                                        trade.order.action == tp_action):
                                        if trade.isActive() or (trade.orderStatus and 
                                            trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                                            tp_trade = trade
                                            tp_order_active = True
                                            # Update the order object with permId
                                            if hasattr(trade.order, 'permId') and trade.order.permId != 0:
                                                tp_order.permId = trade.order.permId
                                                tp_order.lmtPrice = trade.order.lmtPrice
                                            break
                            
                            if not tp_order_active:
                                logging.warning(f"TP order is not active. Status: {tp_trade.orderStatus.status if tp_trade and tp_trade.orderStatus else 'Unknown'}")
                            
                            if tp_order_active:
                                # SAFER APPROACH: Place new TP first, verify it's active, then cancel old one
                                tp_action = 'SELL' if dir_ == 1 else 'BUY'
                                qty = abs(tp_order.totalQuantity) if hasattr(tp_order, 'totalQuantity') else 1
                                
                                # Create and place new TP order first
                                new_tp_order = LimitOrder(
                                    action=tp_action,
                                    totalQuantity=qty,
                                    lmtPrice=new_tp,
                                    tif='GTC',  # Good Till Canceled - allows after-hours execution for ES futures
                                    transmit=True
                                )
                                
                                try:
                                    # Place new TP order
                                    new_tp_trade = ib.placeOrder(contract, new_tp_order)
                                    logging.info(f"Placed new TP order at {new_tp:.2f} (old TP: {current_tp:.2f})")
                                    
                                    # Wait for new order to be submitted and check status
                                    ib.sleep(1.5)  # Give IB time to process
                                    
                                    # Verify new TP order is active
                                    new_tp_active = False
                                    new_tp_trade_obj = None
                                    
                                    # Method 1: Use the trade object returned by placeOrder
                                    if new_tp_trade and new_tp_trade.order:
                                        new_tp_trade_obj = new_tp_trade
                                        if new_tp_trade.isActive() or (new_tp_trade.orderStatus and 
                                            new_tp_trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                                            new_tp_active = True
                                            if hasattr(new_tp_trade.order, 'permId') and new_tp_trade.order.permId != 0:
                                                new_tp_order.permId = new_tp_trade.order.permId
                                            if hasattr(new_tp_trade.order, 'orderId') and new_tp_trade.order.orderId != 0:
                                                new_tp_order.orderId = new_tp_trade.order.orderId
                                    
                                    # Method 2: Find by permId if available
                                    if not new_tp_active and hasattr(new_tp_order, 'permId') and new_tp_order.permId != 0:
                                        for trade in ib.trades():
                                            if (trade.contract.conId == contract.conId and 
                                                trade.order.permId == new_tp_order.permId):
                                                new_tp_trade_obj = trade
                                                if trade.isActive() or (trade.orderStatus and 
                                                    trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                                                    new_tp_active = True
                                                break
                                    
                                    # Method 3: Find by matching characteristics
                                    if not new_tp_active:
                                        for trade in ib.trades():
                                            if (trade.contract.conId == contract.conId and 
                                                isinstance(trade.order, LimitOrder) and
                                                trade.order.action == tp_action and
                                                abs(getattr(trade.order, 'lmtPrice', 0) - new_tp) < 0.01):
                                                new_tp_trade_obj = trade
                                                if trade.isActive() or (trade.orderStatus and 
                                                    trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                                                    new_tp_active = True
                                                    if hasattr(trade.order, 'permId') and trade.order.permId != 0:
                                                        new_tp_order.permId = trade.order.permId
                                                    if hasattr(trade.order, 'orderId') and trade.order.orderId != 0:
                                                        new_tp_order.orderId = trade.order.orderId
                                                break
                                    
                                    if new_tp_active:
                                        # CRITICAL: Before cancelling old TP, check if it has a parentId
                                        # If it does, cancelling it will also cancel the stop loss (they're in a bracket)
                                        # We need to recreate the stop loss as standalone first
                                        old_tp_has_parent = hasattr(tp_order, 'parentId') and tp_order.parentId != 0
                                        
                                        if old_tp_has_parent:
                                            # Old TP is part of a bracket - cancelling it will cancel the stop loss too
                                            # Recreate stop loss as standalone order first
                                            stop_order = bracket.get('stopLoss')
                                            if stop_order:
                                                stop_price = getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', 0))
                                                if stop_price > 0:
                                                    logging.info(f"Old TP has parentId - recreating stop loss as standalone before cancelling TP")
                                                    stop_action = 'SELL' if dir_ == 1 else 'BUY'
                                                    stop_qty = abs(stop_order.totalQuantity) if hasattr(stop_order, 'totalQuantity') else qty
                                                    
                                                    # Create new standalone stop order
                                                    new_stop_order = StopOrder(
                                                        action=stop_action,
                                                        totalQuantity=stop_qty,
                                                        stopPrice=stop_price,
                                                        tif='GTC',
                                                        transmit=True  # Standalone, no parent
                                                    )
                                                    
                                                    try:
                                                        new_stop_trade = ib.placeOrder(contract, new_stop_order)
                                                        ib.sleep(1.0)  # Wait for submission
                                                        
                                                        # Verify new stop is active
                                                        new_stop_active = False
                                                        if new_stop_trade and new_stop_trade.order:
                                                            if new_stop_trade.isActive() or (new_stop_trade.orderStatus and 
                                                                new_stop_trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                                                                new_stop_active = True
                                                                if hasattr(new_stop_trade.order, 'permId') and new_stop_trade.order.permId != 0:
                                                                    new_stop_order.permId = new_stop_trade.order.permId
                                                        
                                                        if new_stop_active:
                                                            # Update bracket with new standalone stop
                                                            bracket['stopLoss'] = new_stop_order
                                                            logging.info(f"Recreated stop loss as standalone order at {stop_price:.2f}")
                                                            # Stop loss recreation succeeded, proceed with TP cancellation
                                                            # Now safe to cancel old TP (stop loss is protected)
                                                            try:
                                                                ib.cancelOrder(tp_order)
                                                                ib.sleep(0.5)
                                                                logging.info(f"Cancelled old TP order at {current_tp:.2f}")
                                                            except Exception as e:
                                                                logging.warning(f"Error cancelling old TP order (new one is active): {e}")
                                                                # Check if old order was auto-cancelled by IB
                                                                old_tp_still_active = False
                                                                for trade in ib.trades():
                                                                    if (trade.order.permId == tp_order.permId and 
                                                                        trade.isActive() and 
                                                                        trade.contract.conId == contract.conId):
                                                                        old_tp_still_active = True
                                                                        break
                                                                if not old_tp_still_active:
                                                                    logging.info("Old TP order was automatically cancelled by IB")
                                                            
                                                            # Update the bracket with the new TP order
                                                            bracket['takeProfit'] = new_tp_order
                                                            logging.info(f"Successfully updated opposite BB TP to {new_tp:.2f}")
                                                        else:
                                                            logging.warning(f"Failed to recreate stop loss - new order not active. Aborting TP update.")
                                                            # Abort TP update - cancel new TP order
                                                            try:
                                                                if new_tp_trade_obj:
                                                                    ib.cancelOrder(new_tp_order)
                                                            except:
                                                                pass
                                                    except Exception as stop_err:
                                                        logging.error(f"Error recreating stop loss: {stop_err}")
                                                        # Don't cancel old TP if we can't protect the stop
                                                        logging.warning(f"Aborting TP update - cannot protect stop loss")
                                                        try:
                                                            if new_tp_trade_obj:
                                                                ib.cancelOrder(new_tp_order)
                                                        except:
                                                            pass
                                                        # Skip TP update - don't cancel old TP
                                                else:
                                                    logging.warning(f"Cannot recreate stop loss - stop price not found")
                                                    # Abort TP update
                                                    try:
                                                        if new_tp_trade_obj:
                                                            ib.cancelOrder(new_tp_order)
                                                    except:
                                                        pass
                                            else:
                                                logging.warning(f"Cannot recreate stop loss - stop order not found in bracket")
                                                # Abort TP update
                                                try:
                                                    if new_tp_trade_obj:
                                                        ib.cancelOrder(new_tp_order)
                                                except:
                                                    pass
                                        else:
                                            # Old TP doesn't have parentId - safe to cancel directly
                                            try:
                                                ib.cancelOrder(tp_order)
                                                ib.sleep(0.5)
                                                logging.info(f"Cancelled old TP order at {current_tp:.2f}")
                                            except Exception as e:
                                                logging.warning(f"Error cancelling old TP order (new one is active): {e}")
                                                # Check if old order was auto-cancelled by IB
                                                old_tp_still_active = False
                                                for trade in ib.trades():
                                                    if (trade.order.permId == tp_order.permId and 
                                                        trade.isActive() and 
                                                        trade.contract.conId == contract.conId):
                                                        old_tp_still_active = True
                                                        break
                                                if not old_tp_still_active:
                                                    logging.info("Old TP order was automatically cancelled by IB")
                                            
                                            # Update the bracket with the new TP order
                                            bracket['takeProfit'] = new_tp_order
                                            logging.info(f"Successfully updated opposite BB TP to {new_tp:.2f}")
                                    else:
                                        if new_tp_trade_obj:
                                            status = new_tp_trade_obj.orderStatus.status if new_tp_trade_obj.orderStatus else "Unknown"
                                            logging.warning(f"New TP order status: {status}. Keeping old TP active.")
                                        else:
                                            logging.warning(f"New TP order not found in trades. Keeping old TP active.")
                                        
                                        try:
                                            if new_tp_trade_obj:
                                                ib.cancelOrder(new_tp_order)
                                        except:
                                            pass
                                        # Old TP order remains active as fallback
                                        
                                except Exception as e:
                                    logging.error(f"Failed to update opposite BB TP: {e}")
                                    import traceback
                                    logging.error(f"Traceback: {traceback.format_exc()}")
                                    # Old TP order remains active as fallback
                            else:
                                logging.warning(f"TP order not active, skipping opposite BB TP update")
                        else:
                            # TP should not update (new TP is same as current, within tick size)
                            logging.debug(f"Opposite BB TP: new_tp={new_tp:.2f} is same as current_tp={current_tp:.2f} (within tick size), no update needed")
                else:
                    logging.warning(f"Opposite BB TP: Cannot calculate - missing BB columns in data")
            else:
                # Log why the check is skipped (only at debug level to avoid spam)
                if not position_still_open:
                    logging.debug(f"Opposite BB TP check skipped: position not open")
                elif not strategy.opposite_bb_tp:
                    logging.debug(f"Opposite BB TP check skipped: strategy.opposite_bb_tp={strategy.opposite_bb_tp}")
                elif not tp_order:
                    logging.debug(f"Opposite BB TP check skipped: no tp_order")
        
        # Check if position closed
        if not any(t.contract.conId == contract.conId for t in ib.positions()):
            # Find exit trade
            exit_trade = None
            for trade in ib.trades():
                if tp_order and trade.order.permId == tp_order.permId and trade.filled():
                    exit_trade = trade
                    reason = 'TP'
                    break
                elif trade.order.permId == stop_order.permId and trade.filled():
                    exit_trade = trade
                    reason = 'Stop'
                    break
            
            # Get entry information from bracket or entry_trade
            entry_price = bracket.get('entry_price', 0)
            entry_time = bracket.get('entry_time')
            if not entry_price and entry_trade and entry_trade.fills:
                entry_price = entry_trade.fills[0].execution.price
            
            # Get current stop and TP prices
            current_stop = getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', 0))
            tp_price = getattr(tp_order, 'lmtPrice', None) if tp_order else None
            
            # Get position size
            qty = abs(stop_order.totalQuantity) if stop_order and hasattr(stop_order, 'totalQuantity') else 1
            
            if exit_trade:
                exit_price = exit_trade.fills[0].execution.price if exit_trade.fills else 0
                # Get PNL from commission report if available
                pnl = 0
                if exit_trade.fills:
                    for fill in exit_trade.fills:
                        if fill.commissionReport and hasattr(fill.commissionReport, 'realizedPNL'):
                            pnl = fill.commissionReport.realizedPNL
                            break
                # If no commission report, calculate manually
                if pnl == 0 and entry_price > 0:
                    pnl = (exit_price - entry_price) * dir_ * contract.multiplier
            else:
                reason = 'Unknown'
                exit_price = latest_row['close']
                pnl = 0
                if entry_price > 0:
                    pnl = (exit_price - entry_price) * dir_ * contract.multiplier
            
            # Calculate duration
            exit_time = datetime.now()
            duration_seconds = 0
            duration_str = "N/A"
            if entry_time:
                duration_seconds = (exit_time - entry_time).total_seconds()
                duration_str = format_duration(duration_seconds)
            
            # Get account summary
            account = get_account_summary()
            
            # Calculate price change
            price_change = exit_price - entry_price if entry_price > 0 else 0
            price_change_pct = (price_change / entry_price * 100) if entry_price > 0 else 0
            
            # Calculate risk and reward in dollars (based on original entry)
            contract_multiplier = 50  # ES contract multiplier
            risk_dollars = abs(entry_price - current_stop) * contract_multiplier * qty
            reward_dollars = abs(entry_price - tp_price) * contract_multiplier * qty if tp_price else None
            risk_reward_ratio = reward_dollars / risk_dollars if (tp_price and risk_dollars > 0) else None
            
            # Calculate actual PNL vs expected risk/reward
            expected_risk = -risk_dollars if reason == 'Stop' else None
            expected_reward = reward_dollars if reason == 'TP' else None
            
            # Build comprehensive email
            msg_lines = [
                f"TRADE CLOSE - {'LONG' if dir_==1 else 'SHORT'}",
                f"{'='*50}",
                f"Entry Price: ${entry_price:.2f}",
                f"Exit Price: ${exit_price:.2f}",
                f"Price Change: ${price_change:.2f} ({price_change_pct:+.2f}%)",
                f"Position Size: {qty} contract(s)",
                f"",
                f"Exit Details:",
                f"  Reason: {reason}",
                f"  Stop Loss: ${current_stop:.2f} (Risk: ${risk_dollars:,.2f})",
                f"  Take Profit: ${tp_price:.2f} (Reward: ${reward_dollars:,.2f})" if tp_price else "  Take Profit: None",
                f"  Risk/Reward Ratio: {risk_reward_ratio:.2f}:1" if risk_reward_ratio else "  Risk/Reward Ratio: N/A",
                f"",
                f"Performance:",
                f"  PNL: ${pnl:,.2f}",
                f"  Expected Risk: ${expected_risk:,.2f}" if expected_risk else f"  Expected Reward: ${expected_reward:,.2f}" if expected_reward else "",
                f"  Duration: {duration_str}",
                f"  Entry Time: {entry_time.strftime('%Y-%m-%d %H:%M:%S')}" if entry_time else "  Entry Time: N/A",
                f"  Exit Time: {exit_time.strftime('%Y-%m-%d %H:%M:%S')}",
                f"",
                f"Account Information:",
            ]
            
            # Add account values (show 0.00 if available, N/A only if truly missing)
            net_liq = account.get('NetLiquidation')
            if net_liq is not None:
                msg_lines.append(f"  Net Liquidation: ${net_liq:,.2f}")
            else:
                msg_lines.append("  Net Liquidation: N/A")
            
            total_cash = account.get('TotalCashValue')
            if total_cash is not None:
                msg_lines.append(f"  Total Cash: ${total_cash:,.2f}")
            else:
                msg_lines.append("  Total Cash: N/A")
            
            msg_lines.extend([
                f"  Total Unrealized PNL: ${account.get('UnrealizedPNL', 0):,.2f}",
                f"  Total Realized PNL: ${account.get('RealizedPNL', 0):,.2f}",
                f"  Open ES Positions: {account.get('ES_Positions', 0)}"
            ])
            
            msg = "\n".join(msg_lines)
            send_email("BB Strategy - Trade CLOSE", msg)
            logging.info(msg.replace('\n', ' | '))
            dashboard_stats['trades_closed'] += 1
            dashboard_stats['orders_filled'] += 1  # Exit order filled
            add_to_live_tracker('trade', f"TRADE CLOSE: {'LONG' if dir_==1 else 'SHORT'} {qty} @ ${exit_price:.2f}, PNL: ${pnl:,.2f}, Reason: {reason}")
            
            # Cancel any orphaned orders from this bracket (e.g., standalone stop orders from trailing updates)
            try:
                # Cancel the stop order if it's still active
                if stop_order:
                    for trade in ib.trades():
                        if (trade.order.permId == stop_order.permId and 
                            trade.contract.conId == contract.conId and 
                            trade.isActive()):
                            try:
                                ib.cancelOrder(stop_order)
                                logging.info(f"Cancelled orphaned stop order (PermID: {stop_order.permId}) after position close")
                            except Exception as e:
                                logging.warning(f"Error cancelling orphaned stop order: {e}")
                            break
                
                # Cancel the TP order if it's still active (shouldn't be, but just in case)
                if tp_order:
                    for trade in ib.trades():
                        if (trade.order.permId == tp_order.permId and 
                            trade.contract.conId == contract.conId and 
                            trade.isActive()):
                            try:
                                ib.cancelOrder(tp_order)
                                logging.info(f"Cancelled orphaned TP order (PermID: {tp_order.permId}) after position close")
                            except Exception as e:
                                logging.warning(f"Error cancelling orphaned TP order: {e}")
                            break
            except Exception as e:
                logging.warning(f"Error cleaning up orphaned orders: {e}")
            
            positions.remove(bracket)
            
            # Clean up any remaining orphaned orders
            cleanup_orphaned_orders()
            
            if not positions:
                status_timer.stop()

# Clean up orphaned orders (orders that don't belong to any active position)
def cleanup_orphaned_orders():
    """
    Cancel any active ES orders that don't belong to any tracked position.
    This handles cases where orders remain active after positions close.
    CRITICAL: This is especially important after reconnection, as orders may have
    filled while disconnected, leaving orphaned opposite orders active.
    """
    global positions, contract
    
    if contract is None:
        return
    
    # First, verify actual positions match tracked brackets
    es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
    has_open_position = any(abs(p.position) > 0 for p in es_positions)
    
    # If no open position, all protective orders (stop loss/take profit) should be cancelled
    # These orders remain active after a position closes and need to be cleaned up
    if not has_open_position:
        active_orders = [t for t in ib.trades() if t.contract.conId == contract.conId and t.isActive()]
        if active_orders:
            logging.info(f"No open ES position detected. Cleaning up {len(active_orders)} protective order(s) (stop loss/take profit) left from closed position.")
            for trade in active_orders:
                try:
                    order_type = type(trade.order).__name__
                    ib.cancelOrder(trade.order)
                    logging.debug(f"Cancelled {order_type} order (PermID: {trade.order.permId})")
                except Exception as e:
                    logging.warning(f"Error cancelling {order_type} order {trade.order.permId}: {e}")
        # Clear all tracked brackets since position is closed
        positions.clear()
        return
    
    # Get all tracked order IDs from active positions
    tracked_order_ids = set()
    for bracket in positions:
        if bracket.get('stopLoss'):
            stop_order = bracket['stopLoss']
            if hasattr(stop_order, 'permId') and stop_order.permId:
                tracked_order_ids.add(stop_order.permId)
        if bracket.get('takeProfit'):
            tp_order = bracket['takeProfit']
            if hasattr(tp_order, 'permId') and tp_order.permId:
                tracked_order_ids.add(tp_order.permId)
        if bracket.get('entry'):
            entry_order = bracket['entry']
            if hasattr(entry_order, 'permId') and entry_order.permId:
                tracked_order_ids.add(entry_order.permId)
    
    # If we reach here, there's an open position, so only cancel untracked standalone orders
    # (standalone orders from trailing stop updates that got orphaned)
    for trade in ib.trades():
        order = trade.order
        if (trade.contract.conId == contract.conId and 
            trade.isActive() and
            hasattr(order, 'permId') and
            order.permId not in tracked_order_ids):
            # Only cancel standalone orders (no parentId) - these are likely orphaned from trailing updates
            # OR orders with parentId pointing to filled entry orders (orphaned from position close while disconnected)
            should_cancel = False
            if not hasattr(order, 'parentId') or order.parentId == 0:
                # Standalone order - likely orphaned from trailing update
                should_cancel = True
            else:
                # Check if parent order is filled (position closed, but this protective order remains)
                parent_filled = False
                for parent_trade in ib.trades():
                    if (hasattr(order, 'parentId') and 
                        parent_trade.order.permId == order.parentId and
                        parent_trade.filled()):
                        parent_filled = True
                        break
                if parent_filled:
                    # Parent is filled but this protective order is still active - orphaned!
                    should_cancel = True
                    logging.warning(f"Found orphaned protective order (PermID: {order.permId}) with filled parent. Cancelling.")
            
            if should_cancel:
                try:
                    ib.cancelOrder(order)
                    logging.info(f"Cancelled orphaned order: {type(order).__name__} (PermID: {order.permId})")
                except Exception as e:
                    logging.warning(f"Error cancelling orphaned order {order.permId}: {e}")

# Check and handle orphaned positions
def close_orphaned_positions():
    """
    Handle positions that don't match any tracked brackets.
    
    Strategy:
    1. If position is UNPROTECTED (no stop loss), protect it first (safer than closing)
    2. If position is protected but doesn't match tracked brackets, it might be from:
       - Orphaned order fill (should be protected, not closed)
       - Manual trade (should be protected, not closed)
       - Error in tracking (should be protected, not closed)
    
    We now PROTECT orphaned positions instead of closing them, as closing might cause
    unnecessary losses if the position is profitable. The strategy will manage it normally.
    """
    global positions, contract, strategy
    
    if contract is None:
        return
    
    es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
    
    if not es_positions:
        return
    
    # Check each position
    for pos in es_positions:
        position_size = pos.position
        if position_size == 0:
            continue
        
        # Check if this position matches any tracked bracket
        position_matched = False
        for bracket in positions:
            bracket_dir = bracket.get('direction', 0)
            # Check if direction matches
            pos_dir = 1 if position_size > 0 else -1
            if bracket_dir == pos_dir:
                # Check if quantity matches (approximately)
                stop_order = bracket.get('stopLoss')
                bracket_qty = abs(stop_order.totalQuantity) if stop_order and hasattr(stop_order, 'totalQuantity') else 1
                if abs(abs(position_size) - bracket_qty) <= 1:  # Allow 1 contract difference
                    position_matched = True
                    break
        
        # If position doesn't match any bracket, check if it's protected
        if not position_matched:
            qty = abs(position_size)
            direction = 1 if position_size > 0 else -1
            
            # Check if position has protection
            has_protection = False
            for trade in ib.trades():
                order = trade.order
                # Check if it's a stop order for this contract
                is_stop_order = (isinstance(order, StopOrder) or 
                                (hasattr(order, 'auxPrice') and order.auxPrice > 0 and 
                                 hasattr(order, 'lmtPrice') and order.lmtPrice == 0))
                
                if (trade.contract.conId == contract.conId and 
                    trade.isActive() and 
                    is_stop_order and
                    abs(order.totalQuantity) == qty):
                    # Check if it's the right direction
                    order_dir = 1 if order.action == 'SELL' else -1
                    if order_dir == direction:
                        has_protection = True
                        break
            
            if not has_protection:
                # UNPROTECTED orphaned position - protect it instead of closing
                logging.warning(f"UNPROTECTED ORPHANED POSITION DETECTED: {qty} contracts ({'LONG' if direction==1 else 'SHORT'})")
                logging.warning("This position doesn't match any tracked bracket and has no protection.")
                logging.warning("Protecting it with stop loss instead of closing (safer approach).")
                
                # protect_existing_positions() will handle this, but we log it here for clarity
                # The protect_existing_positions() function will be called after this
            else:
                # Protected orphaned position - log it but don't close
                logging.info(f"ORPHANED POSITION DETECTED (but protected): {qty} contracts ({'LONG' if direction==1 else 'SHORT'})")
                logging.info("Position doesn't match tracked brackets but has protection. Leaving it active.")

def protect_existing_positions():
    """
    Check for existing positions and ensure they have stop loss orders.
    This handles cases where positions exist but stop orders are missing.
    """
    global positions, contract, data
    
    if contract is None:
        return
    
    # Check for ES positions
    es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
    
    if not es_positions:
        return
    
    logging.info(f"Found {len(es_positions)} existing ES position(s). Checking protection...")
    
    for pos in es_positions:
        position_size = pos.position
        if position_size == 0:
            continue
        
        direction = 1 if position_size > 0 else -1
        qty = abs(position_size)
        
        # Check if there's an active stop order for this position
        has_protection = False
        
        # First check our tracked brackets
        for bracket in positions:
            stop_order = bracket.get('stopLoss')
            if stop_order:
                for trade in ib.trades():
                    if trade.order.permId == stop_order.permId and trade.isActive():
                        # Verify it's for the right contract and quantity
                        if trade.contract.conId == contract.conId:
                            has_protection = True
                            break
            if has_protection:
                break
        
        # Also check all active orders directly (in case bracket tracking is out of sync)
        if not has_protection:
            for trade in ib.trades():
                order = trade.order
                # Check if it's a stop order for this contract
                # StopOrder has auxPrice set, LimitOrder/MarketOrder don't (or it's 0)
                is_stop_order = (isinstance(order, StopOrder) or 
                                (hasattr(order, 'auxPrice') and order.auxPrice > 0 and 
                                 hasattr(order, 'lmtPrice') and order.lmtPrice == 0))
                
                if (trade.contract.conId == contract.conId and 
                    trade.isActive() and 
                    is_stop_order and
                    abs(order.totalQuantity) == qty):
                    # Check if it's the right direction
                    order_dir = 1 if order.action == 'SELL' else -1
                    if order_dir == direction:
                        has_protection = True
                        stop_price = getattr(order, 'auxPrice', getattr(order, 'stopPrice', 0))
                        logging.info(f"Found active stop order for position: {stop_price:.2f}")
                        break
        
        if not has_protection:
            logging.warning(f"UNPROTECTED POSITION DETECTED: {qty} contracts, direction {direction}")
            
            # Get current price
            if len(data) == 0:
                logging.error("No price data available. Cannot create stop loss.")
                continue
            
            current_price = data['close'].iloc[-1]
            
            # Calculate stop loss using strategy
            if len(data) >= strategy.bb_length:
                latest_row = data.iloc[-1]
                position_dict = strategy.setup_position(current_price, direction, latest_row, data)
                stop_price = position_dict['stop']
                stop_price = round(stop_price * 4) / 4  # Round to ES tick size
                
                # Create stop loss order
                stop_action = 'SELL' if direction == 1 else 'BUY'
                stop_order = StopOrder(
                    action=stop_action,
                    totalQuantity=qty,
                    stopPrice=stop_price,
                    tif='GTC',  # Good Till Canceled - allows after-hours execution for ES futures
                    transmit=True
                )
                
                try:
                    ib.placeOrder(contract, stop_order)
                    logging.info(f"Created stop loss order for unprotected position: {stop_price:.2f}")
                    
                    # Create a dummy bracket entry for tracking
                    # We don't have the original entry order, so create a placeholder
                    dummy_entry = MarketOrder(action='BUY' if direction == 1 else 'SELL', totalQuantity=qty)
                    dummy_entry.orderId = 0  # Mark as placeholder
                    dummy_entry.permId = 0
                    
                    bracket = {
                        'entry': dummy_entry,
                        'stopLoss': stop_order,
                        'takeProfit': None,
                        'direction': direction
                    }
                    positions.append(bracket)
                    
                except Exception as e:
                    logging.error(f"Failed to create stop loss for unprotected position: {e}")
            else:
                logging.warning("Not enough data to calculate stop loss. Position remains unprotected!")

# Check and recreate missing TP orders
def check_and_recreate_tp_orders():
    """
    Check all tracked positions and ensure they have TP orders if they should.
    This handles cases where TP orders were cancelled or lost.
    """
    global positions, contract, strategy, data
    
    if contract is None:
        return
    
    # Note: We allow checking even if positions list is empty, because we might need
    # to create a bracket for an existing position that wasn't tracked
    
    # First, check if we have an actual open position
    es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
    has_open_position = any(abs(p.position) > 0 for p in es_positions)
    
    if not has_open_position:
        # No open position, clear all tracked brackets
        logging.info("No open ES position found. Clearing tracked positions.")
        positions.clear()
        return
    
    # Note: We don't check max_open_trades here because we're just adding TP orders
    # to existing positions, not opening new ones. The max_open_trades limit only
    # applies to opening new positions, not to adding protective orders.
    
    # If we have an open position but no tracked brackets, we need to create a bracket
    # This handles cases where the position exists but wasn't tracked (e.g., from a previous run)
    if has_open_position and len(positions) == 0:
        logging.warning("Open position found but no tracked brackets. Creating bracket for existing position...")
        # Get the position details
        for pos in es_positions:
            if abs(pos.position) > 0:
                direction = 1 if pos.position > 0 else -1
                qty = abs(pos.position)
                
                # Try to get entry price
                entry_price = getattr(pos, 'averageCost', None)
                if entry_price is None:
                    entry_price = getattr(pos, 'avgCost', None)
                if entry_price is None:
                    entry_price = getattr(pos, 'averagePrice', None)
                if entry_price is None or entry_price == 0:
                    if len(data) > 0:
                        entry_price = data['close'].iloc[-1]
                    else:
                        logging.error("Cannot create bracket - no entry price available")
                        continue
                
                # Create a dummy bracket for tracking
                dummy_entry = MarketOrder(action='BUY' if direction == 1 else 'SELL', totalQuantity=qty)
                dummy_entry.orderId = 0
                dummy_entry.permId = 0
                
                # Find the stop order if it exists
                stop_order = None
                for trade in ib.trades():
                    if (trade.contract.conId == contract.conId and trade.isActive()):
                        order = trade.order
                        is_stop = (isinstance(order, StopOrder) or 
                                  (hasattr(order, 'auxPrice') and order.auxPrice > 0 and 
                                   hasattr(order, 'lmtPrice') and order.lmtPrice == 0))
                        if is_stop and abs(order.totalQuantity) == qty:
                            order_dir = 1 if order.action == 'SELL' else -1
                            if order_dir == direction:
                                stop_order = order
                                break
                
                bracket = {
                    'entry': dummy_entry,
                    'stopLoss': stop_order,
                    'takeProfit': None,  # Will be created below
                    'direction': direction,
                    'entry_price': entry_price,
                    'entry_time': datetime.now()  # Approximate
                }
                positions.append(bracket)
                logging.info(f"Created tracking bracket for existing position: {direction} {qty} @ ${entry_price:.2f}")
                break
    
    for bracket in positions[:]:  # Use slice to allow safe removal
        tp_order = bracket.get('takeProfit')
        direction = bracket.get('direction', 0)
        
        if direction == 0:
            continue
        
        # Verify the position still exists
        position_size = 0
        for pos in es_positions:
            if abs(pos.position) > 0:
                # Check if direction matches
                pos_direction = 1 if pos.position > 0 else -1
                if pos_direction == direction:
                    position_size = abs(pos.position)
                    break
        
        if position_size == 0:
            # Position no longer exists, remove this bracket
            logging.info(f"Position for bracket (direction={direction}) no longer exists. Removing bracket.")
            positions.remove(bracket)
            continue
        
        # Check if TP should exist (based on strategy - if TP is enabled)
        # TP is enabled if fixed_atr_tp, fixed_bb_entry_tp, or opposite_bb_tp is True
        if not (strategy.fixed_atr_tp or strategy.fixed_bb_entry_tp or strategy.opposite_bb_tp):
            continue  # Strategy doesn't use TP
        
        # Check if TP order exists and is active
        tp_active = False
        if tp_order:
            for trade in ib.trades():
                if (trade.contract.conId == contract.conId and 
                    hasattr(tp_order, 'permId') and 
                    trade.order.permId == tp_order.permId):
                    if trade.isActive() or (trade.orderStatus and 
                        trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                        tp_active = True
                        logging.debug(f"TP order found active: PermID={tp_order.permId}, Status={trade.orderStatus.status if trade.orderStatus else 'Unknown'}")
                    break
        
        if not tp_active:
            # TP is missing - need to recreate it
            logging.warning(f"TP order missing for {'LONG' if direction == 1 else 'SHORT'} position (size={position_size}). Attempting to recreate...")
            logging.info(f"TP enabled check: fixed_atr_tp={strategy.fixed_atr_tp}, fixed_bb_entry_tp={strategy.fixed_bb_entry_tp}, opposite_bb_tp={strategy.opposite_bb_tp}")
            
            # Get entry price from position or bracket
            entry_order = bracket.get('entry')
            entry_price = None
            
            # Try to get entry price from filled entry order
            if entry_order and hasattr(entry_order, 'permId') and entry_order.permId != 0:
                for trade in ib.trades():
                    if (trade.contract.conId == contract.conId and 
                        trade.order.permId == entry_order.permId):
                        if trade.fills:
                            entry_price = trade.fills[0].execution.price
                            break
            
                        # Fallback: get from position average cost
                        if entry_price is None:
                            es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
                            if es_positions:
                                pos = es_positions[0]
                                # Try to get average cost with fallbacks
                                entry_price = getattr(pos, 'averageCost', None)
                                if entry_price is None:
                                    entry_price = getattr(pos, 'avgCost', None)
                                if entry_price is None:
                                    entry_price = getattr(pos, 'averagePrice', None)
                                if entry_price is None or entry_price == 0:
                                    # Use current market price as last resort
                                    if len(data) > 0:
                                        entry_price = data['close'].iloc[-1]
            
            # Fallback: use current market price (less ideal)
            if entry_price is None or entry_price == 0:
                if len(data) > 0:
                    entry_price = data['close'].iloc[-1]
                else:
                    logging.error("Cannot recreate TP - no entry price available")
                    continue
            
            # Calculate TP price using strategy
            try:
                # Use the strategy's take profit calculation
                # Check which TP method is enabled
                if strategy.fixed_atr_tp:
                    # Use ATR-based TP
                    atr_tp = data['atr_tp'].iloc[-1] if 'atr_tp' in data.columns and len(data) > 0 else None
                    if atr_tp is None or pd.isna(atr_tp):
                        # Fallback to atr_ts if atr_tp not available
                        atr_tp = data['atr_ts'].iloc[-1] if 'atr_ts' in data.columns and len(data) > 0 else 0
                    if atr_tp > 0:
                        tp = entry_price + direction * atr_tp * strategy.atr_mult_tp
                    else:
                        logging.error("Cannot recreate TP - ATR not available")
                        continue
                elif strategy.fixed_bb_entry_tp:
                    # Use BB-based TP (fixed at entry)
                    if 'upper' in data.columns and 'lower' in data.columns and len(data) > 0:
                        tp = data['upper'].iloc[-1] if direction == 1 else data['lower'].iloc[-1]
                    else:
                        logging.error("Cannot recreate TP - BB bands not available")
                        continue
                elif strategy.opposite_bb_tp:
                    # Use dynamic opposite BB TP (current opposite BB level)
                    if 'upper' in data.columns and 'lower' in data.columns and len(data) > 0:
                        tp_raw = data['upper'].iloc[-1] if direction == 1 else data['lower'].iloc[-1]
                        
                        # Check if TP value is NaN (can happen if not enough data for BB calculation)
                        if pd.isna(tp_raw) or np.isnan(tp_raw):
                            logging.warning("Cannot recreate TP - BB value is NaN (not enough data). Will retry when data is available.")
                            continue
                        
                        tp = float(tp_raw)
                    else:
                        logging.error("Cannot recreate TP - BB bands not available")
                        continue
                else:
                    logging.error("Cannot recreate TP - TP method not enabled")
                    continue
                
                # Check if tp is NaN before rounding
                if pd.isna(tp) or np.isnan(tp):
                    logging.warning("Cannot recreate TP - calculated TP value is NaN. Will retry when data is available.")
                    continue
                
                tp = round(tp * 4) / 4  # Round to tick size
                
                # Get current price to verify TP won't immediately fill
                current_price = data['close'].iloc[-1] if len(data) > 0 else 0
                
                # Verify TP price is appropriate (won't immediately fill)
                # For LONG: TP should be above current price
                # For SHORT: TP should be below current price
                if direction == 1:  # LONG position
                    if tp <= current_price:
                        logging.warning(f"TP price {tp:.2f} is not above current price {current_price:.2f} for LONG position. Skipping TP recreation.")
                        continue
                else:  # SHORT position
                    if tp >= current_price:
                        logging.warning(f"TP price {tp:.2f} is not below current price {current_price:.2f} for SHORT position. Skipping TP recreation.")
                        continue
                
                # Get quantity from stop order or position
                qty = position_size  # Use the verified position size
                stop_order = bracket.get('stopLoss')
                if stop_order and hasattr(stop_order, 'totalQuantity'):
                    qty = abs(stop_order.totalQuantity)
                
                            # Note: We're just adding a TP order to an existing position,
                            # not opening a new position, so max_open_trades doesn't apply here
                
                tp_action = 'SELL' if direction == 1 else 'BUY'
                new_tp_order = LimitOrder(
                    action=tp_action,
                    totalQuantity=qty,
                    lmtPrice=tp,
                    tif='GTC',  # Good Till Canceled - allows after-hours execution for ES futures
                    transmit=True
                )
                
                logging.info(f"Recreating TP order: {tp_action} {qty} @ {tp:.2f} (current price: {current_price:.2f})")
                tp_trade = ib.placeOrder(contract, new_tp_order)
                ib.sleep(0.5)
                
                # Verify new TP order is active
                new_tp_active = False
                if tp_trade and tp_trade.order:
                    if tp_trade.isActive() or (tp_trade.orderStatus and 
                        tp_trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                        new_tp_active = True
                        if hasattr(tp_trade.order, 'permId') and tp_trade.order.permId != 0:
                            new_tp_order.permId = tp_trade.order.permId
                
                if new_tp_active:
                    bracket['takeProfit'] = new_tp_order
                    logging.info(f"Successfully recreated TP order at {tp:.2f}")
                else:
                    logging.error(f"Failed to recreate TP order - new order is not active")
            except Exception as e:
                logging.error(f"Error recreating TP order: {e}")
                import traceback
                logging.error(f"Traceback: {traceback.format_exc()}")

# Periodic position protection check
async def periodic_protection_check():
    """Periodically check that all positions are protected."""
    while True:
        await asyncio.sleep(60)  # Check every minute
        if ib.isConnected() and contract is not None:
            try:
                cleanup_orphaned_orders()  # Clean up any orphaned orders first
                close_orphaned_positions()  # Close any orphaned positions
                protect_existing_positions()
                check_and_recreate_tp_orders()  # Check and recreate missing TP orders
                # Log orders periodically to monitor for excessive orders
                log_all_open_orders("Periodic check")
            except Exception as e:
                logging.error(f"Error in periodic protection check: {e}")

# Ensure connected and subscribed
def ensure_connected_and_subscribed():
    global contract, bars, data, bar_count
    if not ib.isConnected():
        logging.warning("RECONNECTING TO TWS...")
        ib.connect('127.0.0.1', 7497, clientId=100)
        ib.sleep(3)
    
    # Explicitly request live market data (type 1)
    # Default behavior: IB uses live data if subscribed, delayed otherwise
    # Explicitly setting ensures we get live data if available
    # Note: ib_insync doesn't expose marketDataTypeEvent callback, so we verify via timestamp check in on_bar_update
    try:
        ib.reqMarketDataType(1)  # Request live data (requires market data subscription)
        logging.info("Requested LIVE market data (type 1) - will verify via timestamp check")
    except Exception as e:
        logging.warning(f"Could not set market data type: {e}")
    
    if contract is None:
        contract = get_front_es_contract()
    
    if bars:
        bars.updateEvent -= on_bar_update
        ib.cancelHistoricalData(bars)
        bars = None
        ib.sleep(1)
    
    bars = ib.reqHistoricalData(
        contract,
        endDateTime='',
        durationStr='5400 S',
        barSizeSetting='5 secs',  # Using 5-second bars for accurate volume (matches TWS within ~2%)
        whatToShow='TRADES',
        useRTH=False,
        formatDate=1,
        keepUpToDate=True
    )
    
    hist_df = util.df(bars)
    if hist_df is not None and not hist_df.empty:
        hist_df.rename(columns={'date': 'datetime'}, inplace=True)
        hist_df['datetime'] = pd.to_datetime(hist_df['datetime']).dt.tz_convert('US/Eastern')
        hist_df.set_index('datetime', inplace=True)
        data = hist_df[['open', 'high', 'low', 'close', 'volume']].copy()
        bar_count = len(data)
        latest_bar_time = data.index[-1]
        current_time = datetime.now(pytz.timezone('US/Eastern'))
        time_delay_seconds = (current_time - latest_bar_time).total_seconds()
        time_delay_minutes = time_delay_seconds / 60
        
        logging.info(f"PRE-FILLED WITH {bar_count} HISTORICAL 5-SEC BARS. LATEST: {latest_bar_time}")
        if time_delay_seconds < 10:
            logging.info(f"✅ Data appears LIVE (delay: {time_delay_seconds:.1f} seconds)")
        elif time_delay_minutes > 10:
            logging.warning(f"⚠️ Data appears DELAYED (delay: {time_delay_minutes:.1f} minutes - expected ~15 min for delayed data)")
        else:
            logging.info(f"Data delay: {time_delay_seconds:.1f} seconds ({time_delay_minutes:.1f} minutes)")
        
        update_indicators()
    else:
        logging.warning("NO INITIAL HISTORICAL DATA.")
    
    bars.updateEvent += on_bar_update
    logging.info("REAL-TIME 5-SEC BARS SUBSCRIBED VIA KEEPUPTODATE")

# Clean exit handler
def clean_exit(signum=None, frame=None):
    """Clean shutdown handler."""
    logging.info("Shutdown signal received, cleaning up...")
    try:
        status_timer.stop()
    except:
        pass
    
    try:
        if ib.isConnected():
            logging.info("Disconnecting from TWS...")
            ib.disconnect()
    except Exception as e:
        logging.error(f"Error during disconnect: {e}")
    
    logging.info("Shutdown complete.")
    exit(0)

# Register signal handlers (Windows-compatible)
if hasattr(signal, 'SIGINT'):
    signal.signal(signal.SIGINT, clean_exit)
if hasattr(signal, 'SIGTERM'):
    signal.signal(signal.SIGTERM, clean_exit)

# Windows-specific: handle Ctrl+C in console
if os.name == 'nt':
    import atexit
    atexit.register(clean_exit)

# Connection helper with retry and client ID management
async def connect_with_retry(host='127.0.0.1', port=7497, base_client_id=100, max_retries=5):
    """
    Connect to TWS with automatic client ID management.
    If base_client_id is in use, tries alternative IDs.
    """
    for attempt in range(max_retries):
        client_id = base_client_id + attempt
        try:
            logging.info(f"Attempting to connect with clientId {client_id}...")
            await ib.connectAsync(host, port, clientId=client_id, timeout=10)
            logging.info(f"Successfully connected with clientId {client_id}")
            return True
        except Exception as e:
            error_msg = str(e)
            if "client id is already in use" in error_msg.lower() or "326" in error_msg:
                if attempt < max_retries - 1:
                    logging.warning(f"Client ID {client_id} in use, trying {client_id + 1}...")
                    continue
                else:
                    logging.error(f"All client IDs from {base_client_id} to {client_id} are in use.")
                    logging.error("Please close other TWS connections or wait for them to timeout.")
                    raise
            else:
                logging.error(f"Connection error: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                else:
                    raise
    return False

# MAIN LOOP
async def main():
    global contract
    protection_task = None
    
    global connection_start_time, total_uptime_seconds, dashboard_stats
    
    try:
        # Connect with retry logic
        await connect_with_retry('127.0.0.1', 7497, base_client_id=100)
        
        # Track connection start
        connection_start_time = datetime.now()
        add_to_live_tracker('info', 'Connected to Interactive Brokers API')
        
        contract = get_front_es_contract()
        cancel_all_pending()
        ensure_connected_and_subscribed()
        
        # Register portfolio update callback to track realized PNL
        def on_portfolio_update(item):
            """Handle portfolio updates to track realized PNL."""
            global portfolio_realized_pnl
            if item.contract.symbol == 'ES' and item.contract.conId == contract.conId:
                # Update realized PNL from portfolio item (most accurate source)
                portfolio_realized_pnl = getattr(item, 'realizedPNL', None)
                if portfolio_realized_pnl is None:
                    portfolio_realized_pnl = getattr(item, 'realizedPnl', None)
                if portfolio_realized_pnl is None:
                    portfolio_realized_pnl = getattr(item, 'realized_pnl', None)
        
        ib.updatePortfolioEvent += on_portfolio_update
        
        # Wait a moment for data to load
        await asyncio.sleep(2)
        
        # Check and protect existing positions on startup
        logging.info("Checking for orphaned positions and closing them...")
        close_orphaned_positions()
        logging.info("Checking for existing positions and ensuring protection...")
        log_all_open_orders("On startup (before protection check)")
        protect_existing_positions()
        check_and_recreate_tp_orders()  # Check and recreate missing TP orders
        log_all_open_orders("On startup (after protection check)")
        
        # Generate initial dashboard
        update_dashboard()
        add_to_live_tracker('info', 'Dashboard initialized')
        
        # Try to open dashboard in browser (only once on startup)
        try:
            import webbrowser
            import os
            dashboard_path = os.path.abspath(WEB_DASHBOARD)
            webbrowser.open(f'file://{dashboard_path}')
            add_to_live_tracker('info', f'Dashboard opened in browser: {WEB_DASHBOARD}')
        except Exception as e:
            logging.warning(f"Could not open dashboard in browser: {e}")
        
        # Start periodic protection check
        protection_task = asyncio.create_task(periodic_protection_check())
        
        # Main loop
        loop_count = 0
        while True:
            try:
                # Check disconnect status and send email alerts if needed
                check_disconnect_status()
                
                if not ib.isConnected():
                    # Track disconnect
                    if connection_start_time:
                        session_uptime = (datetime.now() - connection_start_time).total_seconds()
                        total_uptime_seconds += session_uptime
                        connection_start_time = None
                    add_to_live_tracker('warning', 'Connection lost - attempting reconnection')
                    dashboard_stats['reconnections'] += 1
                    
                    logging.warning("Connection lost, reconnecting...")
                    await connect_with_retry('127.0.0.1', 7497, base_client_id=100)
                    
                    # Track reconnection
                    connection_start_time = datetime.now()
                    add_to_live_tracker('info', 'Reconnected to Interactive Brokers API')
                    
                    ensure_connected_and_subscribed()
                    # CRITICAL: After reconnection, immediately check for orphaned orders
                    # This handles cases where TP/SL filled while disconnected, leaving
                    # the opposite order active and potentially fillable
                    await asyncio.sleep(2)
                    logging.info("Checking for orphaned orders after reconnection...")
                    cleanup_orphaned_orders()  # Cancel any orphaned orders first
                    close_orphaned_positions()  # Close any positions that don't match tracked brackets
                    protect_existing_positions()  # Ensure remaining positions are protected
                    check_and_recreate_tp_orders()  # Check and recreate missing TP orders
                    log_all_open_orders("After reconnection cleanup")
                    # Note: check_disconnect_status() will send reconnection email on next iteration
                
                # Update dashboard every 5 seconds (every other loop iteration)
                loop_count += 1
                if loop_count % 1 == 0:  # Update every 10 seconds (every iteration)
                    update_dashboard()
                
                await asyncio.sleep(10)
            except KeyboardInterrupt:
                logging.info("Keyboard interrupt received...")
                break
            except Exception as e:
                error_msg = f"Error in main loop: {e}"
                logging.error(error_msg)
                add_error(error_msg)
                add_to_live_tracker('error', error_msg)
                await asyncio.sleep(5)
                
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received, shutting down...")
    except Exception as e:
        error_msg = f"Fatal error: {e}"
        logging.error(error_msg)
        add_error(error_msg)
        add_to_live_tracker('error', error_msg)
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        logging.info("Cleaning up...")
        
        # Cancel protection task
        if protection_task:
            try:
                protection_task.cancel()
                await protection_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logging.error(f"Error cancelling protection task: {e}")
        
        # Stop status timer
        try:
            status_timer.stop()
        except:
            pass
        
        # Disconnect from IB
        try:
            if ib.isConnected():
                logging.info("Disconnecting from TWS...")
                ib.disconnect()
        except Exception as e:
            logging.error(f"Error during disconnect: {e}")
        
        logging.info("Shutdown complete.")

if __name__ == '__main__':
    util.patchAsyncio()
    asyncio.run(main())


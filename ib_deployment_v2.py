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
from bollinger_strategy import BollingerBandStrategy, load_params

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

REVISION = "2.0"
logging.info(f"Starting ib_deployment_v2.py - REVISION {REVISION}")

# =============================================================================
# Load Parameters
# =============================================================================
PARAM_CSV = r'Bollinger\parameters\BB_Strategy_Parameters_optimized_TWS.csv'

params_dict = load_params(PARAM_CSV)
logging.info(f"Loaded {len(params_dict)} parameters from {PARAM_CSV}")

# Initialize strategy
strategy = BollingerBandStrategy(params_dict)

logging.info("\n=== LOADED PARAMETERS ===")
for name, value_dict in sorted(params_dict.items()):
    if not name.startswith('__'):
        logging.info(f"{name:45} = {value_dict['value']}")

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
                    pos_unrealized = pos.unrealizedPNL
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
        total_unrealized_pnl = sum(p.unrealizedPNL for p in es_positions)
        total_realized_pnl = sum(p.realizedPNL for p in es_positions)
        
        summary['UnrealizedPNL'] = total_unrealized_pnl
        summary['RealizedPNL'] = total_realized_pnl
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
    ib.reqGlobalCancel()
    logging.info("Cancelled all pending orders")

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
    if not hasNewBar:
        return
    
    bar = bars[-1]
    new_row = pd.Series({
        'open': bar.open,
        'high': bar.high,
        'low': bar.low,
        'close': bar.close,
        'volume': bar.volume
    }, name=bar.date.astimezone(pytz.timezone('US/Eastern')))
    
    data = data._append(new_row)
    bar_count += 1
    
    logging.info(f"Bar received: {bar.date.strftime('%H:%M:%S')} | "
                f"O: {bar.open:.2f} H: {bar.high:.2f} L: {bar.low:.2f} C: {bar.close:.2f} | Vol: {bar.volume}")
    
    update_indicators()
    
    # Only check entries/exits if we have enough data and indicators are calculated
    if len(data) >= strategy.bb_length and 'upper' in data.columns:
        latest_row = data.iloc[-1]
        check_entries(data.index[-1], latest_row)
        check_exits(data.index[-1], latest_row)

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
    
    # Copy filter columns back
    for col in ['volume_filter', 'atr_filter', 'in_rth']:
        if col in data_with_filters.columns:
            data[col] = data_with_filters[col]

# Entry Logic
def check_entries(idx, latest_row):
    if len(positions) >= strategy.max_open_trades:
        return
    
    if len(data) < 2:
        return
    
    # Check filters
    if not (latest_row.get('in_rth', True) and latest_row.get('atr_filter', False) and latest_row.get('volume_filter', False)):
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
    
    if len(positions) == 1:
        status_timer.start()

# Exit Logic (for manual closes or trailing updates)
def check_exits(idx, latest_row):
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
                    new_tp = float(data['upper'].iloc[-1]) if dir_ == 1 else float(data['lower'].iloc[-1])
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
                                    # New TP order is active, safe to cancel old one
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
    """
    global positions, contract
    
    if contract is None:
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
    
    # Check if there are any active ES positions
    es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
    has_position = any(abs(p.position) > 0 for p in es_positions)
    
    # If no position, cancel all active ES orders
    if not has_position:
        for trade in ib.trades():
            if (trade.contract.conId == contract.conId and 
                trade.isActive() and
                hasattr(trade.order, 'permId') and
                trade.order.permId not in tracked_order_ids):
                try:
                    ib.cancelOrder(trade.order)
                    logging.info(f"Cancelled orphaned order: {type(trade.order).__name__} (PermID: {trade.order.permId})")
                except Exception as e:
                    logging.warning(f"Error cancelling orphaned order {trade.order.permId}: {e}")
    else:
        # If there is a position, only cancel orders that aren't tracked and don't have a parentId
        # (standalone orders from trailing stop updates that got orphaned)
        for trade in ib.trades():
            order = trade.order
            if (trade.contract.conId == contract.conId and 
                trade.isActive() and
                hasattr(order, 'permId') and
                order.permId not in tracked_order_ids):
                # Only cancel standalone orders (no parentId) - these are likely orphaned from trailing updates
                if not hasattr(order, 'parentId') or order.parentId == 0:
                    try:
                        ib.cancelOrder(order)
                        logging.info(f"Cancelled orphaned standalone order: {type(order).__name__} (PermID: {order.permId})")
                    except Exception as e:
                        logging.warning(f"Error cancelling orphaned order {order.permId}: {e}")

# Check and protect existing positions
def close_orphaned_positions():
    """
    Close any positions that don't match any tracked brackets.
    This handles cases where positions exist but aren't tracked (e.g., from manual close errors).
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
        
        # If position doesn't match any bracket, close it
        if not position_matched:
            logging.warning(f"ORPHANED POSITION DETECTED: {position_size} contracts ({'LONG' if position_size > 0 else 'SHORT'})")
            logging.warning("This position doesn't match any tracked bracket. Closing it...")
            
            try:
                close_action = 'SELL' if position_size > 0 else 'BUY'
                close_qty = abs(position_size)
                
                close_order = MarketOrder(action=close_action, totalQuantity=close_qty, transmit=True)
                close_trade = ib.placeOrder(contract, close_order)
                logging.warning(f"Placed market order to close orphaned position: {close_action} {close_qty} @ market")
                
                # Wait for execution
                ib.sleep(3)
                
                # Verify position closed
                es_positions_after = [p for p in ib.positions() if p.contract.conId == contract.conId]
                position_closed = not es_positions_after or es_positions_after[0].position == 0
                
                if position_closed:
                    logging.info("Orphaned position successfully closed")
                else:
                    remaining = es_positions_after[0].position if es_positions_after else 0
                    logging.error(f"WARNING: Orphaned position still open! Remaining: {remaining}")
                    
            except Exception as e:
                logging.error(f"CRITICAL ERROR: Failed to close orphaned position: {e}")
                import traceback
                logging.error(f"Traceback: {traceback.format_exc()}")

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
    
    if contract is None or not positions:
        return
    
    # First, check if we have an actual open position
    es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
    has_open_position = any(abs(p.position) > 0 for p in es_positions)
    
    if not has_open_position:
        # No open position, clear all tracked brackets
        logging.info("No open ES position found. Clearing tracked positions.")
        positions.clear()
        return
    
    # Check if we're at max positions
    if len(positions) >= strategy.max_open_trades:
        logging.warning(f"Already at max positions ({strategy.max_open_trades}). Skipping TP recreation.")
        return
    
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
        # TP is enabled if fixed_atr_tp or fixed_bb_entry_tp is True
        if not (strategy.fixed_atr_tp or strategy.fixed_bb_entry_tp):
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
                    break
        
        if not tp_active:
            # TP is missing - need to recreate it
            logging.warning(f"TP order missing for {'LONG' if direction == 1 else 'SHORT'} position. Attempting to recreate...")
            
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
                    entry_price = es_positions[0].averageCost
            
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
                        tp = data['upper'].iloc[-1] if direction == 1 else data['lower'].iloc[-1]
                    else:
                        logging.error("Cannot recreate TP - BB bands not available")
                        continue
                else:
                    logging.error("Cannot recreate TP - TP method not enabled")
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
                
                # Double-check we're not exceeding max positions
                if len(positions) >= strategy.max_open_trades:
                    logging.warning(f"At max positions ({strategy.max_open_trades}). Skipping TP recreation.")
                    continue
                
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
        barSizeSetting='1 min',
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
        logging.info(f"PRE-FILLED WITH {bar_count} HISTORICAL 1-MIN BARS. LATEST: {data.index[-1]}")
        update_indicators()
    else:
        logging.warning("NO INITIAL HISTORICAL DATA.")
    
    bars.updateEvent += on_bar_update
    logging.info("REAL-TIME 1-MIN BARS SUBSCRIBED VIA KEEPUPTODATE")

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
    
    try:
        # Connect with retry logic
        await connect_with_retry('127.0.0.1', 7497, base_client_id=100)
        
        contract = get_front_es_contract()
        cancel_all_pending()
        ensure_connected_and_subscribed()
        
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
        
        # Start periodic protection check
        protection_task = asyncio.create_task(periodic_protection_check())
        
        # Main loop
        while True:
            try:
                if not ib.isConnected():
                    logging.warning("Connection lost, reconnecting...")
                    await connect_with_retry('127.0.0.1', 7497, base_client_id=100)
                    ensure_connected_and_subscribed()
                    # Re-check protection after reconnection
                    await asyncio.sleep(2)
                    close_orphaned_positions()
                    protect_existing_positions()
                    check_and_recreate_tp_orders()  # Check and recreate missing TP orders
                await asyncio.sleep(10)
            except KeyboardInterrupt:
                logging.info("Keyboard interrupt received...")
                break
            except Exception as e:
                logging.error(f"Error in main loop: {e}")
                await asyncio.sleep(5)
                
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received, shutting down...")
    except Exception as e:
        logging.error(f"Fatal error: {e}")
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


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
        pnl = sum(pos.unrealizedPNL for pos in positions_list if pos.contract.symbol == 'ES')
        msg = f"Status: {len(positions_list)} open position(s)\nUnrealized PNL: ${pnl:,.2f}"
        logging.info(msg)
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
    stop_action = 'SELL' if direction == 1 else 'BUY'
    stop_order = StopOrder(
        action=stop_action,
        totalQuantity=qty,
        stopPrice=stop_price,  # Constructor parameter
        parentId=entry_order_id,
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
    bracket = {
        'entry': entry_order,
        'stopLoss': stop_order,
        'takeProfit': tp_order,
        'direction': direction,
        'position_dict': position_dict  # Store full position dict for strategy module
    }
    positions.append(bracket)
    
    tp_str = f"{tp:.2f}" if tp is not None else "None"
    msg = (f"TRADE OPEN - {'LONG' if direction==1 else 'SHORT'}\n"
           f"Entry Order ID: {entry_order.permId}\nStop: {stop_price:.2f}\nTP: {tp_str}")
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
        
        # If stop should trigger but hasn't, and TP is still active, cancel TP
        if stop_should_trigger and stop_trade and stop_trade.isActive():
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
                        transmit=True  # Ensure it's transmitted immediately
                    )
                    
                    try:
                        # Place new stop order
                        new_trade = ib.placeOrder(contract, new_stop_order)
                        logging.info(f"Placed new stop order at {new_stop:.2f} (old stop: {current_stop:.2f})")
                        
                        # Wait for new order to be submitted and check status
                        ib.sleep(1.5)  # Give IB time to process
                        
                        # Verify new order is active before canceling old one
                        new_order_active = False
                        new_trade_obj = None
                        for trade in ib.trades():
                            if (hasattr(new_stop_order, 'permId') and 
                                trade.order.permId == new_stop_order.permId and 
                                trade.contract.conId == contract.conId):
                                new_trade_obj = trade
                                if trade.isActive():
                                    new_order_active = True
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
                                logging.warning(f"New stop order status: {status}. Keeping old stop active.")
                            else:
                                logging.warning(f"New stop order not found in trades. Keeping old stop active.")
                            
                            # Cancel the new order if it exists but isn't active
                            try:
                                if new_trade_obj:
                                    ib.cancelOrder(new_stop_order)
                            except:
                                pass
                            # Old stop order remains active as protection
                            
                    except Exception as e:
                        logging.error(f"Failed to place new stop order: {e}")
                        # Old stop order remains active as fallback protection
        
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
                if pnl == 0 and entry_trade.fills:
                    entry_price = entry_trade.fills[0].execution.price if entry_trade.fills else 0
                    pnl = (exit_price - entry_price) * dir_ * contract.multiplier if entry_price > 0 else 0
            else:
                reason = 'Unknown'
                exit_price = latest_row['close']
                pnl = 0
            
            msg = (f"TRADE CLOSE - {'LONG' if dir_==1 else 'SHORT'}\n"
                   f"Exit: {exit_price:.2f}\nReason: {reason}\nPNL: {pnl:,.2f}")
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

# Periodic position protection check
async def periodic_protection_check():
    """Periodically check that all positions are protected."""
    while True:
        await asyncio.sleep(60)  # Check every minute
        if ib.isConnected() and contract is not None:
            try:
                cleanup_orphaned_orders()  # Clean up any orphaned orders first
                protect_existing_positions()
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
        logging.info("Checking for existing positions and ensuring protection...")
        log_all_open_orders("On startup (before protection check)")
        protect_existing_positions()
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
                    protect_existing_positions()
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


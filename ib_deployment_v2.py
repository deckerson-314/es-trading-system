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
from ib_insync import IB, Future, util, BracketOrder
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
    check_entries(data.index[-1], new_row)
    check_exits(data.index[-1], new_row)

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
def check_entries(idx, new_row):
    if len(positions) >= strategy.max_open_trades:
        return
    
    if len(data) < 2:
        return
    
    latest = data.iloc[-1]
    
    # Check filters
    if not (latest.get('in_rth', True) and latest.get('atr_filter', False) and latest.get('volume_filter', False)):
        return
    
    # Use strategy module to check entry
    enter_long, enter_short = strategy.check_entry(new_row, data)
    
    if not (enter_long or enter_short):
        return
    
    direction = 1 if enter_long else -1
    action = 'BUY' if direction == 1 else 'SELL'
    qty = 1
    
    # Setup position using strategy module
    entry_price = new_row['close']
    position_dict = strategy.setup_position(entry_price, direction, new_row, data)
    
    stop_price = position_dict['stop']
    tp = position_dict.get('tp')
    
    # Create bracket order
    bracket = ib.bracketOrder(action, qty, limitPrice=0.0, stopLossPrice=stop_price, takeProfitPrice=tp)
    for o in bracket:
        ib.placeOrder(contract, o)
    
    positions.append(bracket)
    
    tp_str = f"{tp:.2f}" if tp is not None else "None"
    msg = (f"TRADE OPEN - {'LONG' if direction==1 else 'SHORT'}\n"
           f"Entry Order ID: {bracket.entry.permId}\nStop: {stop_price:.2f}\nTP: {tp_str}")
    send_email("BB Strategy - Trade OPEN", msg)
    logging.info(msg.replace('\n', ' | '))
    
    if len(positions) == 1:
        status_timer.start()

# Exit Logic (for manual closes or trailing updates)
def check_exits(idx, new_row):
    for bracket in positions[:]:
        entry_trade = ib.trades()[bracket.entry.permId] if bracket.entry.permId in [t.order.permId for t in ib.trades()] else None
        if not entry_trade or entry_trade.isActive():
            continue
        
        # Get direction from entry
        fill = entry_trade.fills[0].execution if entry_trade.fills else None
        if not fill:
            continue
        
        dir_ = 1 if fill.side == 'BOT' else -1
        
        # Create position dict for strategy module
        # We need to track this per position - for now use a simplified approach
        # In a real implementation, you'd maintain position state
        
        # Trailing stop update if enabled
        # Note: IB handles trailing stops via bracket orders, but we can still update them
        if strategy.enable_trailing:
            stop_order = bracket.stopLoss
            if stop_order.isActive():
                atr = data['atr_ts'].iloc[-1] if 'atr_ts' in data.columns else 0
                peak = new_row['high'] if dir_ == 1 else new_row['low']
                new_stop = peak - dir_ * atr * strategy.atr_mult_ts_opt
                current_stop = stop_order.auxPrice
                
                if (dir_ == 1 and new_stop > current_stop) or (dir_ == -1 and new_stop < current_stop):
                    stop_order.auxPrice = new_stop
                    ib.placeOrder(contract, stop_order)
                    logging.info(f"Updated trailing stop for trade {bracket.entry.permId} to {new_stop:.2f}")
        
        # Check if position closed
        if not any(t.contract.conId == contract.conId for t in ib.positions()):
            pnl = sum(f.realizedPNL for f in entry_trade.fills)
            reason = 'TP' if bracket.takeProfit.filled() else 'Stop' if bracket.stopLoss.filled() else 'Unknown'
            exit_price = bracket.takeProfit.avgFillPrice if bracket.takeProfit.filled() else bracket.stopLoss.avgFillPrice
            
            msg = (f"TRADE CLOSE - {'LONG' if dir_==1 else 'SHORT'}\n"
                   f"Exit: {exit_price:.2f}\nReason: {reason}\nPNL: {pnl:,.2f}")
            send_email("BB Strategy - Trade CLOSE", msg)
            logging.info(msg.replace('\n', ' | '))
            positions.remove(bracket)
            
            if not positions:
                status_timer.stop()

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
def clean_exit(signum, frame):
    logging.info("Interrupt received, shutting down...")
    status_timer.stop()
    if ib.isConnected():
        ib.disconnect()
    exit(0)

signal.signal(signal.SIGINT, clean_exit)
signal.signal(signal.SIGTERM, clean_exit)

# MAIN LOOP
async def main():
    global contract
    await ib.connectAsync('127.0.0.1', 7497, clientId=100)
    contract = get_front_es_contract()
    cancel_all_pending()
    ensure_connected_and_subscribed()
    
    while True:
        if not ib.isConnected():
            ensure_connected_and_subscribed()
        await asyncio.sleep(10)

if __name__ == '__main__':
    util.patchAsyncio()
    asyncio.run(main())


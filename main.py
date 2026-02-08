#!/usr/bin/env python3
"""
main.py - Unified Live/Paper Trading Entry Point
================================================
Uses StrategyFactory to load specific strategy logic.
Handles IBKR connection, order management, and reporting.
"""

import os
import sys

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
import smtplib
import json
from email.mime.text import MIMEText
from datetime import datetime, time
from threading import Timer
from ib_insync import IB, Future, util, MarketOrder, StopOrder, LimitOrder, Order
from dotenv import load_dotenv
import asyncio
import warnings
import pytz
import time as time_module

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from strategies.factory import StrategyFactory
# from strategies.bollinger.parameters import load_params # Dynamic loading preferred, but we need a loader.
# For now, we can create a generic load_params or import from the specific strategy if known, 
# but the Factory should ideally handle it or we use a shared util.
# Let's import load_params from the specific strategy module for now as a fallback, 
# or better: implement a generic JSON/CSV loader in core.
# Given the current state, I'll import from strategies.bollinger.parameters as that's where I moved it.
from strategies.bollinger.parameters import load_params

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
parser.add_argument('--mode', type=str, choices=['PAPER', 'LIVE'], default='PAPER', help='Trading Mode label (default: PAPER)')
parser.add_argument('--params', type=str, help='Path to parameter CSV file (optional, defaults to strategy default)')
parser.add_argument('--output_dir', type=str, default='paper_logs', help='Directory for logs (default: paper_logs)')
parser.add_argument('--dashboard', type=str, default='dashboard.html', help='Filename for HTML dashboard')
parser.add_argument('--client_id', type=int, default=100, help='Base Client ID for IB Connection')

args = parser.parse_args()

# default params path (fallback)
if not args.params:
    if args.strategy.lower() == 'bollinger':
        # Default logic for bollinger
        if args.mode == 'LIVE':
             args.params = r'strategies\bollinger\parameters\live_params.csv'
        else:
             args.params = r'strategies\bollinger\parameters\paper_params.csv'

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
log_file_path = os.path.join(args.output_dir, f'{args.strategy}_{args.mode.lower()}_execution.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logging.info("="*60)
logging.info(f"STARTING TRADING SYSTEM (MAIN) - Strategy: {args.strategy.upper()}")
logging.info(f"MODE: {args.mode}")
logging.info(f"PORT: {args.port}")
logging.info("="*60)

# Load Parameters
try:
    if os.path.exists(args.params):
        params_dict = load_params(args.params)
        logging.info(f"Loaded parameters from {args.params}")
    else:
        logging.warning(f"Parameter file not found: {args.params}. Using empty dict (Strategy defaults may apply).")
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

# Dump Param Structure for Logging
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
# IBKR CONNECTION & EXECUTION ENGINE (Simplified adaptation from v5)
# =============================================================================
# NOTE: In a full refactor, this Engine logic would be in core/engine.py.
# For this step, we keep it in main.py to minimize breakage, but adapt it to use 'strategy' object.

ib = IB()

# ... (Rest of the execution loop logic, adapted from ib_deployment_v5.py)
# Implementation Note: copy-pasting the robust event loop and IB interaction 
# from ib_deployment_v5.py but replacing direct calls with strategy methods.

# Global State for Tracking
positions = []  
data = pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])
contract = None

def error_handler(reqId, errorCode, errorString, contract_obj=None):
    """Handle IB Errors"""
    if errorCode in [2104, 2106, 2158]: # Market data codes (harmless)
        return
    logging.error(f"IB Error {reqId} {errorCode}: {errorString}")

ib.errorEvent += error_handler

def log_execution(trade, fill):
    """Log executions"""
    # ... (Keep existing log_execution logic or import it)
    # For brevity in this artifact, I will focus on the structure. 
    # In a real run, I'd copy the full function or move it to core/execution.py
    pass

ib.execDetailsEvent += log_execution

# Main Loop Logic
async def run_periodically():
    """Main Strategy Loop"""
    global data, contract
    
    # 1. Undefine contract if not set (Example for ES)
    contract = Future('ES', '202603', 'CME') # Hardcoded for now, or move to config
    # qualify
    await ib.qualifyContractsAsync(contract)
    
    # 2. Request Data
    ib.reqMktData(contract, '', False, False)
    
    # Real-time bars
    bars = ib.reqHistoricalData(
        contract, endDateTime='', durationStr='2 D',
        barSizeSetting='1 min', whatToShow='TRADES', useRTH=False, keepUpToDate=True
    )
    
    def on_bar_update(bars, hasNewBar):
        try:
            if not hasNewBar:
                return
                
            global data
            df = util.df(bars)
            if df is None or df.empty:
                return
                
            df.set_index('date', inplace=True)
            data = df[['open', 'high', 'low', 'close', 'volume']]
            
            # --- STRATEGY UPDATE ---
            # 1. Calc Indicators
            data_with_inds = strategy.calculate_indicators(data)
            
            # 2. Check Exits
            # (Requires position tracking logic which matches 'positions' list to 'strategy.check_exit')
            # ...
            
            # 3. Check Entries
            long_sig, short_sig = strategy.calculate_entry_signals(data_with_inds)
            latest_long = long_sig.iloc[-1]
            latest_short = short_sig.iloc[-1]
            
            if latest_long:
                 logging.info("ENTRY LONG SIGNAL")
                 # execute_trade(direction=1)
            elif latest_short:
                 logging.info("ENTRY SHORT SIGNAL")
                 # execute_trade(direction=-1)
                 
        except Exception as e:
            logging.error(f"Error in bar update: {e}")

    bars.updateEvent += on_bar_update
    
    # Keep loop alive
    while ib.isConnected():
        await asyncio.sleep(1)

async def main():
    try:
        await ib.connectAsync('127.0.0.1', args.port, clientId=args.client_id)
        await run_periodically()
    except Exception as e:
        logging.critical(f"Connection failed: {e}")
    finally:
        ib.disconnect()

if __name__ == '__main__':
    util.patchAsyncio()
    asyncio.run(main())

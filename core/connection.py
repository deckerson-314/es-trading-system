"""
core/connection.py - IBKR Connection & Contract Management
Ported from ib_deployment_v4.py lines 1553-1573, 3882-3911
"""
import logging
import asyncio
import time as time_module
from datetime import datetime, timedelta
from ib_insync import Future


def get_front_es_contract(ib):
    """Auto-resolve front-month ES contract. Retries 3 times with 5s delay."""
    for attempt in range(3):
        try:
            temp_contract = Future('ES', '', 'CME', currency='USD')
            cds = ib.reqContractDetails(temp_contract)
            if not cds:
                raise ValueError("No ES contracts found")
            today = datetime.now().date()
            # Customary ES roll happens 8 days before expiration (3rd Friday)
            roll_cutoff = today + timedelta(days=8)
            future_cds = [cd for cd in cds
                         if datetime.strptime(cd.contract.lastTradeDateOrContractMonth, '%Y%m%d').date() > roll_cutoff]
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


async def connect_with_retry(ib, host='127.0.0.1', port=7497, base_client_id=100, max_retries=5):
    """Connect to TWS with automatic client ID rotation on conflict."""
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
                    raise
            else:
                logging.error(f"Connection error: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                else:
                    raise
    return False


def request_historical_data_with_retry(ib, contract, max_retries=5):
    """Request historical data with exponential backoff. Returns bars object."""
    for attempt in range(max_retries):
        try:
            logging.info(f"Requesting historical data (attempt {attempt+1}/{max_retries})...")
            ib.reqMarketDataType(1)  # Live data
            bars = ib.reqHistoricalData(
                contract, endDateTime='', durationStr='4 D',
                barSizeSetting='1 min', whatToShow='TRADES',
                useRTH=False, keepUpToDate=True
            )
            if bars and len(bars) > 0:
                logging.info(f"Received {len(bars)} historical bars")
                return bars
            else:
                raise ValueError("Empty bars returned")
        except Exception as e:
            delay = min(2 ** attempt, 32)
            logging.error(f"Historical data request failed (attempt {attempt+1}): {e}. Retrying in {delay}s...")
            if attempt < max_retries - 1:
                time_module.sleep(delay)
            else:
                raise
    return None

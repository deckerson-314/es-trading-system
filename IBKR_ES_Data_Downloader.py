# ==============================================================================
#  IBKR Futures Data Downloader
# ==============================================================================
#
#  Purpose:
#  This script connects to an Interactive Brokers TWS or Gateway instance via
#  an ngrok tunnel and downloads 90 days of 1-minute historical data for a
#  specified futures contract (default is ES). It downloads the data in
#  chunks to avoid API timeouts.
#
# ==============================================================================
#  REVISION HISTORY
# ==============================================================================
#  Last Updated: 2025-09-22 16:02 EDT
#  --
#  - 2025-09-22 16:02 EDT: **CRITICAL FIX:** Re-implemented the chunking logic to
#    reliably download large datasets (like 90 days of 1-min data) by breaking
#    the request into smaller, 10-day increments to avoid API timeouts.
#  - 2025-09-22 15:46 EDT: Modified to download ES futures data.
#  - 2025-09-22 15:05 EDT: Reverted to manual ngrok connection for stability.
# ==============================================================================

import pandas as pd
import datetime
from ib_insync import *
import os

def download_futures_data_chunked(host, port, symbol='ES', exchange='CME', currency='USD', total_days=90, chunk_days=10, bar_size='1 min'):
    """
    Connects to IBKR and downloads historical data for a futures contract in chunks.
    """
    ib = IB()
    all_bars_df = None
    try:
        print(f"Attempting to connect to TWS/Gateway via manual ngrok tunnel at {host}:{port}...")
        ib.connect(host, port, clientId=1, timeout=20)
        print("Connection successful.")

        generic_contract = Future(symbol=symbol, exchange=exchange, currency=currency)
        contracts = ib.reqContractDetails(generic_contract)
        if not contracts:
            print(f"Error: Could not find any contracts for symbol {symbol} on {exchange}.")
            return

        front_month_contract = sorted(contracts, key=lambda c: c.contract.lastTradeDateOrContractMonth)[0].contract
        print(f"Found front-month contract: {front_month_contract.localSymbol}")

        print(f"Starting download of {total_days} days of {bar_size} data for {symbol} in {chunk_days}-day chunks...")
        
        all_bars_list = []
        end_date_time = '' # Start with the current time

        for i in range(0, total_days, chunk_days):
            days_to_get = min(chunk_days, total_days - i)
            duration_str = f'{days_to_get} D'
            
            print(f"  - Requesting chunk {i//chunk_days + 1}: {duration_str} ending at {end_date_time or 'now'}...")
            
            bars = ib.reqHistoricalData(
                front_month_contract,
                endDateTime=end_date_time,
                durationStr=duration_str,
                barSizeSetting=bar_size,
                whatToShow='TRADES',
                useRTH=False,
                formatDate=1
            )

            if not bars:
                print("  - No more data returned for this period. Stopping download.")
                break

            print(f"  - Received {len(bars)} bars.")
            all_bars_list.extend(bars)
            
            # The new end time for the next chunk is the start time of the current chunk
            end_date_time = bars[0].date
            
            ib.sleep(2) # Pause between requests to be kind to the API

        if not all_bars_list:
            print("No data was downloaded in total.")
            return

        print("\nCombining all data chunks...")
        all_bars_df = util.df(all_bars_list)
        
        # Clean up the final DataFrame
        all_bars_df.drop_duplicates(inplace=True)
        all_bars_df.sort_values(by='date', inplace=True)
        
        print(f"Total unique bars received: {len(all_bars_df)}")
        
        all_bars_df.rename(columns={'date': 'datetime', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
        all_bars_df.set_index('datetime', inplace=True)

        base_dir = "/content/drive/MyDrive/TradingStrategyOptimization"
        data_dir = os.path.join(base_dir, "data")
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
            
        timestamp = datetime.datetime.now().strftime("%Y%m%d")
        filename = f"{symbol}_1min_90D_{timestamp}.csv"
        filepath = os.path.join(data_dir, filename)
        
        all_bars_df.to_csv(filepath)
        print(f"Data successfully saved to {filepath}")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if ib.isConnected():
            print("Disconnecting from TWS/Gateway.")
            ib.disconnect()

def download_overlap_check(host, port, symbol='ES', exchange='CME', currency='USD'):
    """
    Downloads a 1-hour chunk of data overlapping with the known end date (2025-10-10 16:55:00)
    to verify data consistency.
    Target: 1 Hour ending 2025-10-10 17:00:00 (should cover the 16:55 bar).
    """
    ib = IB()
    try:
        print(f"Connecting to IBKR for OVERLAP CHECK at {host}:{port}...")
        ib.connect(host, port, clientId=2, timeout=20)
        
        contract = Future(symbol=symbol, exchange=exchange, currency=currency)
        contracts = ib.reqContractDetails(contract)
        if not contracts:
            print("Error: Contract not found.")
            return

        # Find contract matching the date? Or just use front month and hope continuous?
        # Actually, if we ask for historical data for Oct 2025, we might need the specific contract for that time 
        # OR just mapping the continuous.
        # Let's use the explicit request logic with 'TRADES'.
        
        # NOTE: 2025-10-10 is likely the contract expiration related? 
        # Check active contract for that date?
        # We will try the first returned contract (front month) but specifing endDateTime far in past might require 'CONTFUT'?
        # Or let's assume 'ES' continuous mapping works if we request it.
        # But `reqHistoricalData` on a specific contract object usually requires that contract to be valid for that date.
        
        # Let's try using the 'Continuous Future' if possible, or just the front month and request old date.
        # The original script does: front_month_contract = sorted(...)[0].contract
        
        target_contract = sorted(contracts, key=lambda c: c.contract.lastTradeDateOrContractMonth)[0].contract
        print(f"Using contract: {target_contract.localSymbol}")

        end_time_str = "20251010 17:00:00" 
        print(f"Requesting 1 Hour of data ending {end_time_str}...")
        
        bars = ib.reqHistoricalData(
            target_contract,
            endDateTime=end_time_str,
            durationStr="3600 S", # 1 Hour
            barSizeSetting="1 min",
            whatToShow="TRADES",
            useRTH=False,
            formatDate=1
        )
        
        if not bars:
            print("Error: No data returned from IBKR for this period.")
            return

        print(f"Received {len(bars)} bars.")
        df = util.df(bars)
        if df is not None:
            df.rename(columns={'date': 'datetime', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
            df.set_index('datetime', inplace=True)
            
            # Save to temp file
            out_file = "c:\\Trading\\overlap_test_ibkr.csv"
            df.to_csv(out_file)
            print(f"Overlap data saved to: {out_file}")
            print("Please inspect this file and compare with your main data.")
            print(df.tail())
            
    except Exception as e:
        print(f"Overlap Check Error: {e}")
    finally:
        if ib.isConnected():
            ib.disconnect()

if __name__ == '__main__':
    util.patchAsyncio()
    
    print("Please provide the ngrok connection details from your terminal.")
    # ngrok_host = input("Enter ngrok host (e.g., 0.tcp.ngrok.io): ")
    # ngrok_port = int(input("Enter ngrok port (e.g., 12345): "))
    
    # download_futures_data_chunked(ngrok_host, ngrok_port)
    
    # Hardcoded local for testing if needed, or prompt
    print("--- MODE SELECTION ---")
    print("1. Standard Download")
    print("2. Overlap Check (1 Hour)")
    mode = input("Select Mode (1/2): ")
    
    host = input("Enter Host (default 127.0.0.1): ") or "127.0.0.1"
    port = input("Enter Port (default 7496 for TWS, 4001 for Gateway): ") or "7496"
    port = int(port)
        
    if mode == '2':
        download_overlap_check(host, port)
    else:
        # Calculate days from 2025-10-10 to NOW
        start_date = datetime.datetime(2025, 10, 10)
        now = datetime.datetime.now()
        days_diff = (now - start_date).days + 5 # +buffer
        print(f"Calculated Gap: {days_diff} days (from {start_date.date()} to Now)")
        
        chunk = 5 # Safety for chunks
        download_futures_data_chunked(host, port, total_days=days_diff, chunk_days=chunk)


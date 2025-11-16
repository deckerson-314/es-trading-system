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

if __name__ == '__main__':
    util.patchAsyncio()
    
    print("Please provide the ngrok connection details from your terminal.")
    ngrok_host = input("Enter ngrok host (e.g., 0.tcp.ngrok.io): ")
    ngrok_port = int(input("Enter ngrok port (e.g., 12345): "))
    
    download_futures_data_chunked(ngrok_host, ngrok_port)


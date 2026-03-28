"""
tools/data/downloader.py
========================
Utility for downloading recent high-fidelity minute data from Interactive Brokers.
Used primarily to fetch recent market data to audit live trade executions against a backtest.
"""

from ib_insync import IB, Future, util
import pandas as pd
import datetime
import os
import argparse

def download_recent_data(symbol='ES', exchange='CME', days=5, chunk_days=5, bar_size='1 min', output_path='recent_warmup_data.csv', port=None):
    """
    Connects to IBKR and downloads recent historical data.
    """
    ib = IB()
    ports = [port] if port else [7497, 7496, 4002, 4001]
    connected = False
    
    try:
        for p in ports:
            try:
                print(f"Attempting connection on port {p} (Client ID 101)...")
                ib.connect('127.0.0.1', p, clientId=101, timeout=10)
                print(f"Connected on port {p}.")
                connected = True
                break
            except Exception:
                continue
                
        if not connected:
            print("Could not connect to any standard IBKR port.")
            return False

        contract = Future(symbol=symbol, exchange=exchange, currency='USD')
        details = ib.reqContractDetails(contract)
        if not details:
            print(f"No contract found for {symbol}.")
            return False

        # Get front month contract using 8-day roll buffer (CME standard)
        today = datetime.date.today()
        roll_cutoff = today + datetime.timedelta(days=8)
        
        valid_contracts = [
            d for d in details 
            if datetime.datetime.strptime(d.contract.lastTradeDateOrContractMonth, '%Y%m%d').date() > roll_cutoff
        ]
        
        if not valid_contracts:
            # Fallback to absolute front if no future contracts meeting criteria (unlikely for ES)
            front_contract = sorted(details, key=lambda c: c.contract.lastTradeDateOrContractMonth)[0].contract
        else:
            front_contract = sorted(valid_contracts, key=lambda c: c.contract.lastTradeDateOrContractMonth)[0].contract
        print(f"Starting chunked download of {days} days for {front_contract.localSymbol} in {chunk_days}-day increments...")
        all_bars = []
        end_date_time = ''
        
        for i in range(0, days, chunk_days):
            current_chunk = min(chunk_days, days - i)
            chunk_duration = f"{current_chunk} D"
            
            print(f"  - Requesting chunk {i//chunk_days + 1}: {chunk_duration} ending at {end_date_time or 'now'}...")
            
            chunk_bars = ib.reqHistoricalData(
                front_contract,
                endDateTime=end_date_time,
                durationStr=chunk_duration,
                barSizeSetting=bar_size,
                whatToShow='TRADES',
                useRTH=False,
                formatDate=1
            )
            
            if not chunk_bars:
                print("  - No more data returned for this period. Stopping.")
                break
                
            print(f"  - Received {len(chunk_bars)} bars.")
            all_bars.extend(chunk_bars)
            
            # Step back in time
            end_date_time = chunk_bars[0].date
            
            if i + chunk_days < days:
                ib.sleep(2) # Respect IBKR pacing rules
        
        if all_bars:
            df = util.df(all_bars)
            df.drop_duplicates(subset=['date'], inplace=True)
            df.sort_values('date', inplace=True)
            
            df.rename(columns={'date': 'datetime'}, inplace=True)
            df.set_index('datetime', inplace=True)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            
            df.to_csv(output_path)
            print(f"Saved {len(df)} unique bars to {output_path}")
            return True
        else:
            print("No data received.")
            return False
            
    except Exception as e:
        print(f"Error downloading data: {e}")
        return False
    finally:
        if ib.isConnected():
            ib.disconnect()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download recent IBKR data")
    parser.add_argument('--symbol', type=str, default='ES')
    parser.add_argument('--days', type=int, default=5, help="Total number of days to download")
    parser.add_argument('--chunk_days', type=int, default=5, help="Number of days per API request (pacing)")
    parser.add_argument('--output', type=str, default='recent_warmup_data.csv')
    parser.add_argument('--port', type=int, default=None, help="Force specific IBKR port")
    
    args = parser.parse_args()
    
    download_recent_data(
        symbol=args.symbol, 
        days=args.days, 
        chunk_days=args.chunk_days, 
        output_path=args.output, 
        port=args.port
    )

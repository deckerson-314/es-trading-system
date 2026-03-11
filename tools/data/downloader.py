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

def download_recent_data(symbol='ES', exchange='CME', duration_str='5 D', bar_size='1 min', output_path='recent_warmup_data.csv', port=None):
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

        # Get front month contract
        front_contract = sorted(details, key=lambda c: c.contract.lastTradeDateOrContractMonth)[0].contract
        print(f"Downloading data for: {front_contract.localSymbol}")
        
        bars = ib.reqHistoricalData(
            front_contract,
            endDateTime='',
            durationStr=duration_str,
            barSizeSetting=bar_size,
            whatToShow='TRADES',
            useRTH=False,
            formatDate=1
        )
        
        if bars:
            df = util.df(bars)
            df.rename(columns={'date': 'datetime'}, inplace=True)
            df.set_index('datetime', inplace=True)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            
            df.to_csv(output_path)
            print(f"Saved {len(df)} bars to {output_path}")
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
    parser.add_argument('--days', type=int, default=5)
    parser.add_argument('--output', type=str, default='recent_warmup_data.csv')
    parser.add_argument('--port', type=int, default=None, help="Force specific IBKR port")
    
    args = parser.parse_args()
    duration = f"{args.days} D"
    
    download_recent_data(symbol=args.symbol, duration_str=duration, output_path=args.output, port=args.port)

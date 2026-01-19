from ib_insync import *
import pandas as pd
import datetime
import os

def download_recent_data():
    ib = IB()
    ports = [7497, 7496, 4002, 4001]
    connected = False
    
    try:
        for port in ports:
            try:
                print(f"Attempting connection on port {port} (Client ID 101)...")
                ib.connect('127.0.0.1', port, clientId=101, timeout=10)
                print(f"Connected on port {port}.")
                connected = True
                break
            except Exception:
                continue
                
        if not connected:
            print("Could not connect to any standard IBKR port.")
            return

        contract = Future(symbol='ES', exchange='CME', currency='USD')
        details = ib.reqContractDetails(contract)
        if not details:
            print("No contract found.")
            return

        front_contract = sorted(details, key=lambda c: c.contract.lastTradeDateOrContractMonth)[0].contract
        print(f"Downloading data for: {front_contract.localSymbol}")
        
        # Download 5 days of 1-minute data
        bars = ib.reqHistoricalData(
            front_contract,
            endDateTime='',
            durationStr='5 D',
            barSizeSetting='1 min',
            whatToShow='TRADES',
            useRTH=False,
            formatDate=1
        )
        
        if bars:
            df = util.df(bars)
            df.rename(columns={'date': 'datetime', 'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'volume'}, inplace=True)
            df.set_index('datetime', inplace=True)
            
            output_path = 'c:/Trading/recent_warmup_data.csv'
            df.to_csv(output_path)
            print(f"Saved {len(df)} bars to {output_path}")
        else:
            print("No data received.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ib.disconnect()

if __name__ == "__main__":
    download_recent_data()

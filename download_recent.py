import os
import sys
import pandas as pd
from datetime import datetime, timedelta
import asyncio

# Fix IB-insync nested asyncio
import nest_asyncio
nest_asyncio.apply()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ib_insync import IB, ContFuture, util

async def download_recent():
    ib = IB()
    try:
        await ib.connectAsync('127.0.0.1', 7497, clientId=999)
        print("Connected to IBKR")
        
        from ib_insync import Future
        contract = Future('ES', '20260618', 'CME')
        await ib.qualifyContractsAsync(contract)
        
        print(f"Requesting 30 D of 1 min data for {contract.localSymbol}...")
        bars = await ib.reqHistoricalDataAsync(
            contract,
            endDateTime='',
            durationStr='30 D',
            barSizeSetting='1 min',
            whatToShow='TRADES',
            useRTH=False,
            formatDate=2
        )
        
        df = util.df(bars)
        if df is not None and not df.empty:
            df.set_index('date', inplace=True)
            out_path = r'c:\Trading\paper_logs\recent_1min.csv'
            df.to_csv(out_path)
            print(f"Saved {len(df)} bars to {out_path}")
        else:
            print("No data received.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ib.disconnect()

if __name__ == '__main__':
    asyncio.run(download_recent())

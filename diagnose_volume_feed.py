
from ib_insync import *
import asyncio
import pandas as pd

async def main():
    ib = IB()
    ports = [7497, 7496, 4002, 4001]
    connected = False
    
    # 1. Connect
    for port in ports:
        try:
             print(f"Connecting to port {port}...")
             await ib.connectAsync('127.0.0.1', port, clientId=111)
             connected = True
             break
        except:
             continue
    
    if not connected:
        print("Could not connect.")
        return

    try:
        # Get Contract
        contract = Future('ES', '202603', 'CME')
        await ib.qualifyContractsAsync(contract)
        print(f"Contract: {contract}")
        
        # 1. Download last 20 mins of Historical Data
        print("\n--- 1. Historical Data (Last 20 1-min bars) ---")
        bars = await ib.reqHistoricalDataAsync(
            contract, endDateTime='', durationStr='1200 S',
            barSizeSetting='1 min', whatToShow='TRADES', useRTH=False, formatDate=1
        )
        df = util.df(bars)
        if df is not None:
             print(df[['date', 'close', 'volume']].tail(10))
             last_hist_vol = df['volume'].iloc[-1]
             print(f"Latest Hist Volume: {last_hist_vol}")
        
        # 2. Subscribe to Live Updates
        print("\n--- 2. Live Updates (KeepUpToDate) ---")
        print("Listening for 30 seconds...")
        
        live_bars = ib.reqHistoricalData(
            contract, endDateTime='', durationStr='60 S',
            barSizeSetting='1 min', whatToShow='TRADES', useRTH=False, formatDate=1,
            keepUpToDate=True
        )
        
        start_time = pd.Timestamp.now()
        
        def on_bar_update(bars, hasNewBar):
             if hasNewBar:
                 print(f"[NEW BAR] {bars[-1].date} | Vol: {bars[-1].volume}")
             else:
                 print(f"[UPDATE] {bars[-1].date} | Vol: {bars[-1].volume}")
                 
        live_bars.updateEvent += on_bar_update
        
        while (pd.Timestamp.now() - start_time).total_seconds() < 30:
            await asyncio.sleep(1)
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ib.disconnect()

if __name__ == '__main__':
    util.patchAsyncio()
    asyncio.run(main())


from ib_insync import IB, Future, util
import datetime

def test_long_history():
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7497, clientId=157)
        # ESH6 (March 2026) - Still available
        contract = Future(conId=649180695) # Using the conId we found
        ib.qualifyContracts(contract)
        
        print(f"Requesting 6 months of history for {contract.localSymbol}...")
        
        # Request data ending today
        bars = ib.reqHistoricalData(
            contract,
            endDateTime='',
            durationStr='180 D',
            barSizeSetting='1 hour', # Using hourly for speed of test
            whatToShow='TRADES',
            useRTH=False,
            formatDate=1
        )
        
        if bars:
            print(f"Success! Received {len(bars)} bars.")
            print(f"First bar date: {bars[0].date}")
        else:
            print("Failed to retrieve long history.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ib.disconnect()

if __name__ == "__main__":
    test_long_history()

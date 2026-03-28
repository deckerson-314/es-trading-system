
from ib_insync import IB, Future, util
import datetime

def test_direct_request():
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7497, clientId=154)
        # ES Dec 2025 (Expired) - No qualification
        contract = Future(symbol='ES', lastTradeDateOrContractMonth='202512', exchange='CME', currency='USD')
        
        # Test a date range from Oct 2025
        end_date = datetime.datetime(2025, 10, 15, 16, 0)
        
        bars = ib.reqHistoricalData(
            contract,
            endDateTime=end_date,
            durationStr='1 D',
            barSizeSetting='1 min',
            whatToShow='TRADES',
            useRTH=False,
            formatDate=1
        )
        
        if bars:
            print(f"Success! Received {len(bars)} bars via direct request.")
        else:
            print("Failed.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ib.disconnect()

if __name__ == "__main__":
    test_direct_request()

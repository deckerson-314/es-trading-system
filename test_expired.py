
from ib_insync import IB, Future, util
import datetime

def test_expired_contract():
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7497, clientId=151)
        # ES Dec 2025 (Expired)
        contract = Future('ES', '202512', 'CME')
        ib.qualifyContracts(contract)
        print(f"Contract qualified: {contract}")
        
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
            print(f"Success! Received {len(bars)} bars for expired contract.")
            print(f"First bar: {bars[0].date}")
        else:
            print("Failed to retrieve bars for expired contract.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ib.disconnect()

if __name__ == "__main__":
    test_expired_contract()

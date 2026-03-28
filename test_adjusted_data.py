
from ib_insync import IB, ContFuture, util
import datetime

def test_adjusted_data():
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7497, clientId=150)
        # ES Continuous Future
        contract = ContFuture('ES', 'CME')
        ib.qualifyContracts(contract)
        
        print(f"Requesting adjusted data for {contract.symbol}...")
        
        # Request 1 day of data ending in Dec 2025 (to cross a roll)
        # Roll is around Dec 11
        end_date = datetime.datetime(2025, 12, 15)
        
        bars = ib.reqHistoricalData(
            contract,
            endDateTime=end_date,
            durationStr='10 D',
            barSizeSetting='1 hour',
            whatToShow='ADJUSTED_LAST',
            useRTH=False,
            formatDate=1
        )
        
        if bars:
            df = util.df(bars)
            print(df.head())
            print(f"Total bars: {len(df)}")
            print("Successfully retrieved adjusted data.")
        else:
            print("Failed to retrieve adjusted data.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ib.disconnect()

if __name__ == "__main__":
    test_adjusted_data()

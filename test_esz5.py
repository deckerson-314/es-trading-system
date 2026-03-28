
from ib_insync import IB, Future

def test_esz5():
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7497, clientId=156)
        # ESZ25 (Dec 2025)
        contract = Future(localSymbol='ESZ5', exchange='CME')
        ib.qualifyContracts(contract)
        print(f"Success! {contract}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ib.disconnect()

if __name__ == "__main__":
    test_esz5()

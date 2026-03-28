
from ib_insync import IB, Future

def test_local_symbol():
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7497, clientId=155)
        # ESH26 (March 2026 - Very recently expired or expiring)
        contract = Future(localSymbol='ESH6', exchange='CME')
        ib.qualifyContracts(contract)
        print(f"Success qualifying: {contract}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ib.disconnect()

if __name__ == "__main__":
    test_local_symbol()

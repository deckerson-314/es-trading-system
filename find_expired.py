
from ib_insync import IB, Future

def find_expired():
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7497, clientId=153)
        # Guessed expiry for Dec 2025
        contract = Future('ES', '20251219', 'CME')
        details = ib.reqContractDetails(contract)
        if details:
             print(f"Found it! {details[0].contract}")
        else:
             print("Still not found.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ib.disconnect()

if __name__ == "__main__":
    find_expired()

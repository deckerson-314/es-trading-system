
from ib_insync import IB, Future

def list_es_contracts():
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7497, clientId=152)
        contract = Future('ES', '', 'CME')
        details = ib.reqContractDetails(contract)
        for d in details:
            print(f"Contract: {d.contract.localSymbol}, Expiry: {d.contract.lastTradeDateOrContractMonth}, ConId: {d.contract.conId}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ib.disconnect()

if __name__ == "__main__":
    list_es_contracts()

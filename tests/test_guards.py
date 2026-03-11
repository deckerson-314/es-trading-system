class MockIB:
    def __init__(self):
        self.connected = True
    def isConnected(self):
        return self.connected
    def trades(self): return []
    def positions(self): return []
    def cancelOrder(self, order): print(f"Cancelled order: {order}")
    def placeOrder(self, contract, order): print(f"Placed order: {order}")

class MockContract:
    conId = 12345

def test_guard():
    import sys
    import os
    # Add project root to path (C:\Trading)
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root_dir)
    from tools.safety.guards import SecurityGuard

    params = {
        'Max Daily Loss ($)': {'value': 500},
        'Daily Target ($)': {'value': 1000}
    }
    
    guard = SecurityGuard(params)
    ib = MockIB()
    contract = MockContract()
    
    # 1. Test limits NOT breached
    account = {'RealizedPNL': -100, 'UnrealizedPNL': 50} # -50 total
    res = guard.check_daily_pnl(ib, contract, account, [])
    print(f"Test 1 (Safe): {'PASS' if not res else 'FAIL'}")
    
    # 2. Test Loss Limit breached
    guard.last_pnl_check = guard.last_pnl_check.replace(year=2000) # reset throttle
    account = {'RealizedPNL': -600, 'UnrealizedPNL': 50} # -550 total
    res = guard.check_daily_pnl(ib, contract, account, [])
    print(f"Test 2 (Loss Breached): {'PASS' if res and guard.flattened_today else 'FAIL'}")
    
    # 3. Test Profit Limit breached
    guard = SecurityGuard(params) # New instance
    guard.last_pnl_check = guard.last_pnl_check.replace(year=2000)
    account = {'RealizedPNL': 500, 'UnrealizedPNL': 600} # +1100 total
    res = guard.check_daily_pnl(ib, contract, account, [])
    print(f"Test 3 (Profit Breached): {'PASS' if res and guard.flattened_today else 'FAIL'}")

if __name__ == '__main__':
    test_guard()

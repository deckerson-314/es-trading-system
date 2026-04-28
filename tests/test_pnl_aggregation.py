import sys
import os
import pandas as pd
from dataclasses import dataclass
from typing import List

# Add project root to path
sys.path.append(os.path.abspath('.'))

# Mock ib_insync classes
@dataclass
class MockContract:
    symbol: str
    conId: int = 0

@dataclass
class MockPosition:
    contract: MockContract
    position: float
    averageCost: float
    marketValue: float = 0.0
    realizedPNL: float = 0.0
    unrealizedPNL: float = 0.0

@dataclass
class MockAccountValue:
    tag: str
    value: str
    currency: str = 'USD'
    account: str = 'U12345'

class MockIB:
    def __init__(self, positions: List[MockPosition], account_values: List[MockAccountValue]):
        self._positions = positions
        self._account_values = account_values

    def positions(self):
        return self._positions

    def accountValues(self):
        return self._account_values

# Import the actual function to test
from core.account import get_account_summary

def test_pnl_aggregation():
    # 1. Test basic PNL aggregation from positions
    pos1 = MockPosition(MockContract('ES'), position=1, averageCost=5000.0, realizedPNL=100.0, unrealizedPNL=500.0)
    pos2 = MockPosition(MockContract('MES'), position=0, averageCost=0, realizedPNL=50.0, unrealizedPNL=0)
    
    ib = MockIB([pos1, pos2], [])
    
    # Portfolio realized PNL passed explicitly (like in main.py)
    portfolio_pnl = 150.0
    
    summary = get_account_summary(ib, portfolio_realized_pnl=portfolio_pnl)
    
    print("--- Test 1: Realized PNL from portfolio ---")
    print(f"Expected RealizedPNL: 150.0, Actual: {summary.get('RealizedPNL')}")
    print(f"Expected UnrealizedPNL: 500.0, Actual: {summary.get('UnrealizedPNL')}")
    
    # 2. Test fallback to total_realized_pnl if portfolio_realized_pnl is None
    ib = MockIB([pos1, pos2], [])
    summary = get_account_summary(ib, portfolio_realized_pnl=None)
    
    print("\n--- Test 2: Realized PNL from totals ---")
    print(f"Expected RealizedPNL: 150.0, Actual: {summary.get('RealizedPNL')}")
    
    # 3. Test case naming variations from AccountValues
    av1 = MockAccountValue('UnrealizedPnL', '1000.0')
    av2 = MockAccountValue('RealizedPnL', '200.0')
    av3 = MockAccountValue('NetLiquidation', '100000.0')
    
    ib = MockIB([], [av1, av2, av3])
    summary = get_account_summary(ib)
    
    print("\n--- Test 3: AccountValues mapping ---")
    print(f"Actual UnrealizedPnL: {summary.get('UnrealizedPnL')}")
    print(f"Actual RealizedPnL: {summary.get('RealizedPnL')}")
    print(f"Actual UnrealizedPNL (normalized): {summary.get('UnrealizedPNL')}")
    print(f"Actual RealizedPNL (normalized): {summary.get('RealizedPNL')}")

if __name__ == "__main__":
    try:
        test_pnl_aggregation()
    except Exception as e:
        print(f"Error in test: {e}")
        import traceback
        traceback.print_exc()

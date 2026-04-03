import os
import sys
from ib_insync import IB, util
import pandas as pd
from datetime import datetime
import pytz

# Add project root to path
sys.path.append(os.getcwd())

from core.connection import connect_with_retry, get_front_es_contract
from core.account import get_account_summary

async def diagnose_current_state():
    ib = IB()
    try:
        print("Connecting to TWS on port 7497 (Paper)...")
        await ib.connectAsync('127.0.0.1', 7497, clientId=999)
        
        print("\n--- ACCOUNT SUMMARY ---")
        acct_summary = ib.accountSummary()
        for item in acct_summary:
            if item.tag in ['NetLiquidation', 'RealizedPNL', 'UnrealizedPNL', 'TotalCashValue']:
                print(f"{item.tag}: {item.value}")
        
        print("\n--- POSITIONS (ib.positions()) ---")
        positions = ib.positions()
        if not positions:
            print("No positions found in ib.positions().")
        for p in positions:
            print(f"Contract: {p.contract.localSymbol} ({p.contract.conId}), Pos: {p.position}, AvgCost: {p.avgCost}")
            
        print("\n--- PORTFOLIO (ib.portfolio()) ---")
        portfolio = ib.portfolio()
        if not portfolio:
            print("No items in ib.portfolio().")
        for item in portfolio:
            print(f"Contract: {item.contract.localSymbol}, Pos: {item.position}, MktPrice: {item.marketPrice}, UnrealizedPNL: {item.unrealizedPNL}")

        print("\n--- ACTIVE ORDERS (ib.trades()) ---")
        trades = [t for t in ib.trades() if t.isActive()]
        if not trades:
            print("No active orders found.")
        for t in trades:
            print(f"Order: {t.order.action} {t.order.totalQuantity} {t.contract.localSymbol}, Type: {t.order.orderType}, Status: {t.orderStatus.status}")

        # Check if we are currently in maintenance according to the Trend strategy
        from strategies.trend.strategy import TrendStrategy
        from strategies.factory import StrategyFactory
        from strategies.bollinger.parameters import load_params
        
        params_path = r'strategies\trend\parameters\trend_strategy_params.csv'
        if os.path.exists(params_path):
            params = load_params(params_path)
            strategy = TrendStrategy(params)
            
            # Create a dummy row for the current time
            et_tz = pytz.timezone('US/Eastern')
            now_et = datetime.now(et_tz)
            dummy_df = pd.DataFrame(index=[now_et])
            dummy_df['open'] = 0; dummy_df['high'] = 0; dummy_df['low'] = 0; dummy_df['close'] = 0; dummy_df['volume'] = 0
            
            filtered_df = strategy.apply_filters(dummy_df)
            in_maint = filtered_df['in_maintenance'].iloc[0]
            force_exit = filtered_df['force_exit'].iloc[0]
            
            print(f"\n--- MAINTENANCE STATUS (Trend Strategy) ---")
            print(f"Current Time (ET): {now_et.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"In Maintenance: {in_maint}")
            print(f"Force Exit Triggered: {force_exit}")
            
            # Check the specific weekend settings
            print(f"Weekend Start Day: {strategy.weekend_maintenance_start_day} (Time: {strategy.weekend_maintenance_start_time_str})")
            print(f"Weekend End Day: {strategy.weekend_maintenance_end_day} (Time: {strategy.weekend_maintenance_end_time_str})")
            print(f"Current Day of Week: {now_et.weekday()} (0=Mon, 4=Fri, 5=Sat)")
        
    except Exception as e:
        print(f"Error during diagnosis: {e}")
    finally:
        ib.disconnect()

if __name__ == '__main__':
    import asyncio
    util.patchAsyncio()
    asyncio.run(diagnose_current_state())

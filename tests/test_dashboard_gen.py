
import unittest
import os
import json
import sys
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.dashboard.updates import DashboardState, update_dashboard

class TestDashboardGeneration(unittest.TestCase):
    def setUp(self):
        self.test_dir = "tests/test_output"
        if not os.path.exists(self.test_dir):
            os.makedirs(self.test_dir)
            
        self.html_path = os.path.join(self.test_dir, "dashboard.html")
        self.json_path = os.path.join(self.test_dir, "status.json")
        
    def test_dashboard_creation(self):
        # 1. Create State
        state = DashboardState(
            mode="PAPER",
            port=7497,
            contract_symbol="ES",
            connection_start_time=datetime.now(),
            is_connected=True,
            current_price=4500.50
        )
        
        # Add some mock data
        state.account_info = {
            'NetLiquidation': 100000.0,
            'UnrealizedPNL': 500.0,
            'RealizedPNL': -50.0
        }
        
        state.positions.append({
            'symbol': 'ES',
            'position': 1,
            'avgCost': 4490.0,
            'marketValue': 4500.50 * 50,
            'unrealizedPNL': (4500.50 - 4490.0) * 50,
            'realizedPNL': 0.0
        })
        
        state.live_tracker.append({
            'timestamp': '10:00:00',
            'type': 'INFO',
            'message': 'Test log message'
        })
        
        state.params = {
            'Strategy Name': 'TestStrategy',
            'Timeframe': 1,
            'RSI Period': 14
        }
        
        # 2. Generate Dashboard
        update_dashboard(state, self.html_path, self.json_path)
        
        # 3. Verify Files Exist
        self.assertTrue(os.path.exists(self.html_path), "Dashboard HTML not created")
        self.assertTrue(os.path.exists(self.json_path), "Status JSON not created")
        
        # 4. Verify Content
        with open(self.html_path, 'r', encoding='utf-8') as f:
            html = f.read()
            self.assertIn("ES Trading Dashboard", html)
            self.assertIn("$100,000.00", html) # Net Liq
            self.assertIn("Test log message", html)
            self.assertIn("RSI Period", html)
            
        with open(self.json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(data['net_liquidation'], 100000.0)
            self.assertTrue(data['connected'])

if __name__ == '__main__':
    unittest.main()

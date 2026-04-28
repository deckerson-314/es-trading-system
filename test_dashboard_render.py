
import os
from datetime import datetime
from tools.dashboard.updates import DashboardState, update_dashboard

def test_dashboard_link():
    state = DashboardState(
        mode='PAPER',
        port=7497,
        contract_symbol='ES',
        connection_start_time=datetime.now(),
        is_connected=True
    )
    
    # Mock a completed trade with report_url
    state.completed_trades = [{
        'exit_time': datetime.now(),
        'direction': 'LONG',
        'entry_price': 5000.0,
        'exit_price': 5010.0,
        'pnl': 500.0,
        'r_multiple': 2.0,
        'duration': '00:15:00',
        'reason': 'TP',
        'report_url': 'trades/trade_report_test.html'
    }]
    
    web_dir = os.path.join(os.getcwd(), 'web')
    os.makedirs(web_dir, exist_ok=True)
    html_path = os.path.join(web_dir, 'test_dashboard.html')
    
    update_dashboard(state, html_path=html_path)
    print(f"Dashboard generated: {html_path}")
    
    if os.path.exists(html_path):
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if 'report-link' in content and 'trades/trade_report_test.html' in content:
                print("Verification SUCCESS: Dashboard contains report link and styling.")
            else:
                print("Verification FAILED: Dashboard missing report link or styling.")
    else:
        print("Verification FAILED: Dashboard file missing.")

if __name__ == "__main__":
    test_dashboard_link()

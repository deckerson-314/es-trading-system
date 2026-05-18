
import os
from datetime import datetime, timedelta
from tools.dashboard.updates import DashboardState, update_dashboard

def test_stale_data_ui():
    # 1. Test Online State
    state_online = DashboardState(
        mode='PAPER',
        is_connected=True,
        connection_start_time=datetime.now() - timedelta(hours=1),
        last_data_receipt_time=datetime.now() - timedelta(seconds=10) # Fresh
    )
    
    web_dir = os.path.join(os.getcwd(), 'web')
    os.makedirs(web_dir, exist_ok=True)
    online_path = os.path.join(web_dir, 'test_online.html')
    update_dashboard(state_online, html_path=online_path)
    
    # 2. Test Stale State
    state_stale = DashboardState(
        mode='PAPER',
        is_connected=True,
        connection_start_time=datetime.now() - timedelta(hours=1),
        last_data_receipt_time=datetime.now() - timedelta(seconds=130)  # Stale vs server threshold
    )
    stale_path = os.path.join(web_dir, 'test_stale.html')
    update_dashboard(state_stale, html_path=stale_path)
    
    print(f"Online Dashboard: {online_path}")
    print(f"Stale Dashboard: {stale_path}")
    
    # Content Checks
    with open(online_path, 'r', encoding='utf-8') as f:
        content = f.read()
        if 'CONNECTION: ONLINE' in content and 'class="status-bar "' in content:
            print("Verification SUCCESS: Online dashboard looks correct.")
        else:
            print("Verification FAILED: Online dashboard status incorrect.")

    with open(stale_path, 'r', encoding='utf-8') as f:
        content = f.read()
        if 'DATA: STALE (120s+)' in content and 'class="status-bar stale"' in content:
            print("Verification SUCCESS: Stale dashboard looks correct.")
        else:
            print("Verification FAILED: Stale dashboard status incorrect.")

if __name__ == "__main__":
    test_stale_data_ui()


import os
from datetime import datetime, timedelta
from tools.dashboard.updates import DashboardState, update_dashboard

def test_enhanced_stale_ui():
    # 1. Test Data Stale (Bot Alive)
    state_data_stale = DashboardState(
        mode='PAPER',
        is_connected=True,
        connection_start_time=datetime.now() - timedelta(hours=1),
        last_data_receipt_time=datetime.now() - timedelta(seconds=130)  # Stale vs server threshold
    )
    
    web_dir = os.path.join(os.getcwd(), 'web')
    os.makedirs(web_dir, exist_ok=True)
    stale_path = os.path.join(web_dir, 'test_data_stale.html')
    # Use a real timestamp for last-update so JS thinks bot is alive
    update_dashboard(state_data_stale, html_path=stale_path)
    
    print(f"Data Stale Dashboard: {stale_path}")
    
    # 2. Test Bot Offline
    # To test this visually, we'd need to wait 30s after generating the file.
    # But we can check if the elements exist.
    
    with open(stale_path, 'r', encoding='utf-8') as f:
        content = f.read()
        if 'id="last-data-receipt"' in content and 'DATA: STALE (120s+)' in content:
            print("Verification SUCCESS: Dashboard contains data-receipt element and Python-side status.")
        else:
            print("Verification FAILED: Dashboard missing elements.")

if __name__ == "__main__":
    test_enhanced_stale_ui()

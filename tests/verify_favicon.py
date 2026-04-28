
import sys
import os
sys.path.append(os.getcwd())

from tools.dashboard.updates import DashboardState, update_dashboard
import os

def test_favicon():
    state = DashboardState(mode="PAPER", contract_symbol="ES")
    html_path = "web/test_favicon_paper.html"
    update_dashboard(state, html_path=html_path)
    
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()
        if '<link rel="icon"' in content:
            print(f"PASS: Favicon link found in {html_path}")
            if '🧪' in content:
                print("PASS: Correct PAPER emoji (🧪) found.")
            else:
                print("FAIL: Incorrect emoji for PAPER.")
        else:
            print(f"FAIL: No favicon link in {html_path}")

    state_live = DashboardState(mode="LIVE", contract_symbol="ES")
    html_path_live = "web/test_favicon_live.html"
    update_dashboard(state_live, html_path=html_path_live)
    
    with open(html_path_live, 'r', encoding='utf-8') as f:
        content = f.read()
        if '📈' in content:
            print("PASS: Correct LIVE emoji (📈) found.")
        else:
            print("FAIL: Incorrect emoji for LIVE.")

if __name__ == "__main__":
    if not os.path.exists("web"):
        os.makedirs("web")
    test_favicon()

#!/usr/bin/env python3
"""
Copy existing HTML dashboard files to web/ directory
Run this once to migrate existing files
"""

import os
import shutil
from pathlib import Path

WEB_DIR = Path('web')
WEB_DIR.mkdir(exist_ok=True)

print("="*60)
print("Setting up web directory for dashboards")
print("="*60)

# Files to copy
files_to_copy = [
    # Live Trading Dashboard
    ('ib_deployment_dashboard.html', 'ib_deployment_dashboard.html'),
    
    # GA Dashboard
    ('ga_diagnostics_v3/html/ga_dashboard_v3.html', 'ga_dashboard_v3.html'),
    
    # Backtest Dashboard (may have version number)
    ('Bollinger/plots/html_v3/comprehensive_dashboard_v3.0.html', 'comprehensive_dashboard_v3.0.html'),
]

copied = 0
missing = 0

for source, dest in files_to_copy:
    source_path = Path(source)
    dest_path = WEB_DIR / dest
    
    if source_path.exists():
        try:
            shutil.copy2(source_path, dest_path)
            print(f"[OK] Copied: {source} -> web/{dest}")
            copied += 1
        except Exception as e:
            print(f"[ERROR] Error copying {source}: {e}")
            missing += 1
    else:
        print(f"[WARN] Not found: {source}")
        missing += 1

print("\n" + "="*60)
print(f"Summary: {copied} files copied, {missing} files not found")
print("="*60)
print("\nNext steps:")
print("   1. Run: python start_web_server.py")
print("   2. Access at: http://127.0.0.1:8000")
print("   3. For remote access, ngrok will start automatically if installed")
print("="*60)


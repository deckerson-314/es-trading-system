
import re

log_path = r'c:\Trading\paper_logs\ib_execution.log'
target_time = "2026-01-05 13:"

print(f"Scanning {log_path} for events around {target_time}...")

with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        if "2026-01-05 13:00" in line or "2026-01-05 13:01" in line or "2026-01-05 13:02" in line:
             print(line.strip())

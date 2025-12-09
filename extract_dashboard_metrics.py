import re
import os

html_path = 'c:\\Trading\\ga_diagnostics_v4\\html\\ga_dashboard_v4.html'

if not os.path.exists(html_path):
    print("Dashboard file not found.")
    exit(1)

with open(html_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Regex to find the metrics
# Pattern: <div class='metric-box'>Avg Trades/Day: 2.463</div>
trades_pattern = re.search(r"<div class='metric-box'>Avg Trades/Day: ([\d\.]+)</div>", content)
sortino_pattern = re.search(r"<div class='metric-box'>Sortino: ([\d\.-]+)</div>", content)
dd_pattern = re.search(r"<div class='metric-box'>Max DD: \$([\d\.,]+)</div>", content)
pf_pattern = re.search(r"<div class='metric-box'>PF: ([\d\.]+)</div>", content)

print("--- DASHBOARD METRICS ---")
if trades_pattern:
    print(f"Avg Trades/Day: {trades_pattern.group(1)}")
else:
    print("Avg Trades/Day: Not found")

if sortino_pattern:
    print(f"Sortino: {sortino_pattern.group(1)}")
else:
    print("Sortino: Not found")

if dd_pattern:
    print(f"Max DD: ${dd_pattern.group(1)}")
else:
    print("Max DD: Not found")
    
if pf_pattern:
    print(f"PF: {pf_pattern.group(1)}")
else:
    print("PF: Not found")

# Check for error text
if "Error:" in content:
    print("(!) WARNING: 'Error:' string found in HTML")
if "Exception" in content:
    print("(!) WARNING: 'Exception' string found in HTML")


import re
import pandas as pd
from datetime import datetime

def check_scan():
    log_path = r'c:\Trading\debug_alignment_output.txt'
    # Flexible regex to catch the table lines
    # Format roughly:
    # 24 2025-12-30 12:30:06  LONG 6948.50  2025-12-30 12:30:00  Matched ...
    
    # We'll just look for lines containing "MATCHED"
    # match_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+.*\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+MATCHED")
    # This might be brittle due to column spacing.
    
    # Let's iterate lines.
    count = 0
    max_diff = 0
    with open(log_path, 'r') as f:
        for line in f:
            if "MATCHED" in line:
                # Extract dates. Assume they are the first two YYYY-MM-DD HH:MM:SS patterns in the line?
                # Actually Live Date is usually col 2, BT Date is col ~5?
                # "24 2025-12-30 12:30:06  LONG ..."
                dates = re.findall(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", line)
                if len(dates) >= 2:
                    live_t = pd.to_datetime(dates[0])
                    bt_t = pd.to_datetime(dates[1])
                    diff = abs((live_t - bt_t).total_seconds())
                    
                    if diff > 180: # 3 mins
                        print(f"LARGE MISMATCH: Live={live_t}, BT={bt_t}, Diff={diff}s")
                    
                    if diff > max_diff:
                        max_diff = diff
                    count += 1
                    
    print(f"Scanned {count} MATCHED trades.")
    print(f"Max Time Difference: {max_diff} seconds")

if __name__ == "__main__":
    check_scan()

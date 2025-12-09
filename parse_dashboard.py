
import re
import sys

try:
    with open(r'C:\Trading\web\ga_dashboard_v4.html', 'r', encoding='utf-8') as f:
        html = f.read()
    
    # 1. Find Generation Info (look for "Generation:" pattern)
    # <div class='header-info'>... <strong>Generation:</strong> Generation 90</div>
    gen_match = re.search(r'Generation:\s*</strong>\s*([^<]+)', html)
    if gen_match:
        print(f"GENERATION FOUND: {gen_match.group(1).strip()}")
    else:
        print("GENERATION NOT FOUND in Header.")

    # 2. Extract Table Rows for "Net Profit" and "Sortino"
    # Looking for a row like: <tr><td>Net Profit ($)</td><td>255,015.00</td><td>-1,200.00</td>...</tr>
    print("\n--- METRICS EXTRACTION ---")
    
    # Regex to find table rows with columns
    # We look for <tr>...</tr> blocks
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    
    for row in rows:
        # Remove tags to see text content
        # Simplistic barrier: just replace </td><td> with | and strip tags
        clean_row = re.sub(r'<[^>]+>', '|', row)
        clean_row = re.sub(r'\|+', '|', clean_row).strip('|')
        
        if "Net Profit" in clean_row or "Sortino" in clean_row or "Trades" in clean_row:
            print(f"ROW: {clean_row}")

except Exception as e:
    print(f"Error: {e}")

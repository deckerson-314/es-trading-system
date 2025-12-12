
import re

try:
    with open(r"C:\Trading\ga_diagnostics_v4\html\ga_dashboard_v4.html", "r", encoding='utf-8') as f:
        html = f.read()

    # Regex to find Comparison Table
    # Look for table with class 'comparison-table'
    comp_table_match = re.search(r"<table class='comparison-table'>(.*?)</table>", html, re.DOTALL)
    if comp_table_match:
        print("\n--- PERFORMANCE SUMMARY ---")
        table_content = comp_table_match.group(1)
        rows = re.findall(r"<tr>(.*?)</tr>", table_content, re.DOTALL)
        for r in rows:
            # Extract cell content
            cells = re.findall(r"<t[hd]>(.*?)</t[hd]>", r)
            clean_cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            print(" | ".join(clean_cells))
    
    # Extract Params
    print("\n--- OPTIMIZED PARAMETERS ---")
    # Finding optimized values is harder with regex across whole file, 
    # but we can look for specific td patterns if we know the structure.
    # Pattern: <tr><td>Name</td><td>Range</td><td><strong>Value</strong></td></tr>
    
    params_to_find = ['Bollinger Band StdDev', 'Enable ADX Filter', 'Max ADX Threshold', 'ADX Period', 'Bollinger Band Length']
    for p in params_to_find:
        # Regex: <td>PName</td>...<td><strong>Value</strong></td>
        pattern = r"<td>" + re.escape(p) + r"</td>.*?<td><strong>(.*?)</strong></td>"
        match = re.search(pattern, html, re.DOTALL)
        if match:
            print(f"{p}: {match.group(1)}")

except Exception as e:
    print(f"Error: {e}")


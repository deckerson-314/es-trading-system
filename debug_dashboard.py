
import os
import sys

# Help Support
if len(sys.argv) > 1 and sys.argv[1] in ['?', '-?', '/?', '--help', '-h']:
    print(f"""
================================================================================
             DASHBOARD DEBUGGER
================================================================================

DESCRIPTION:
  Scans the generated 'ga_dashboard_v4.html' for common rendering issues:
  1. Duplicate HTML IDs (e.g., 'param_analysis_plot' appearing twice).
  2. Missing Script Tags (Plotly JSON data not injected correctly).
  3. Truncated Content (Unexpected file end).

USAGE:
  python debug_dashboard.py [ARGUMENTS]

ARGUMENTS:
  ? / -h            Show this help manual.

EXAMPLES:
  Run Check:        python debug_dashboard.py

================================================================================
""")
    sys.exit(0)

try:
    with open('ga_diagnostics_v4/html/ga_dashboard_v4.html', 'r', encoding='utf-8') as f:
        content = f.read()

    print(f"Total Length: {len(content)}")
    
    # Check for Duplicate IDs
    count_id = content.count('id="param_analysis_plot"')
    print(f"Occurrences of id='param_analysis_plot': {count_id}")

    # Check for Script Injection
    # Plotly scripts usually start after the div
    pos = content.find('id="param_analysis_plot"')
    if pos != -1:
        print("Found div at position:", pos)
        snippet = content[pos:pos+500]
        print("Snippet after div start:")
        print(snippet)
        
        # Look for the script close to this
        script_pos = content.find('<script type="text/javascript">', pos)
        if script_pos != -1:
             print(f"Found script tag after div at distance: {script_pos - pos}")
        else:
             print("WARNING: No script tag found after div!")
    else:
        print("ERROR: Div not found!")

except Exception as e:
    print(f"Error reading file: {e}")

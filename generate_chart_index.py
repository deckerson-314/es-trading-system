import os
import glob
from datetime import datetime

CHARTS_DIR = r"c:\Trading\comparison_charts"
INDEX_FILE = os.path.join(CHARTS_DIR, "index.html")

def generate_index():
    # Get list of HTML files
    files = glob.glob(os.path.join(CHARTS_DIR, "trade_compare_*.html"))
    files.sort(reverse=True) # Newest first based on naming convention
    
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trade Comparison Charts</title>
    <style>
        body { font-family: 'Segoe UI', system-ui, sans-serif; padding: 2rem; background: #f8fafc; color: #334155; }
        .container { max-width: 800px; margin: 0 auto; background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
        h1 { color: #1e293b; border-bottom: 2px solid #3b82f6; padding-bottom: 0.5rem; }
        .chart-list { list-style: none; padding: 0; }
        .chart-item { padding: 1rem; border-bottom: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: center; transition: background 0.2s; }
        .chart-item:hover { background: #f1f5f9; }
        .chart-link { text-decoration: none; color: #2563eb; font-weight: 500; font-size: 1.1rem; }
        .chart-link:hover { text-decoration: underline; }
        .chart-time { font-size: 0.9rem; color: #64748b; }
        .back-link { display: inline-block; margin-bottom: 1rem; color: #64748b; text-decoration: none; }
        .back-link:hover { color: #334155; }
    </style>
</head>
<body>
    <div class="container">
        <a href="../web/index.html" class="back-link">← Back to Main Dashboard</a>
        <h1>Comparison Charts Archive</h1>
        <ul class="chart-list">
"""

    if not files:
        html += "<p>No comparison charts found.</p>"
    
    for f in files:
        filename = os.path.basename(f)
        # Parse timestamp from filename: trade_compare_YYYYMMDD_HHMMSS.html
        try:
            ts_str = filename.replace('trade_compare_', '').replace('.html', '')
            dt = datetime.strptime(ts_str, '%Y%m%d_%H%M%S')
            display_time = dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            display_time = filename
            
        html += f"""            <li class="chart-item">
                <a href="{filename}" class="chart-link">{display_time}</a>
                <span class="chart-time">{filename}</span>
            </li>
"""

    html += """        </ul>
    </div>
</body>
</html>
"""

    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"Generated index.html with {len(files)} charts.")

if __name__ == "__main__":
    generate_index()

#!/usr/bin/env python3
"""
Simple HTTP server for Trading Strategy Dashboards
Serves the web/ directory on localhost and optionally via ngrok
"""

import os
import sys
import http.server
import socketserver
import webbrowser
import threading
import time
from pathlib import Path

# Configuration
PORT = 8000
# Startup from /tools/dashboard/server.py -> Root is up 2 levels
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WEB_DIR = PROJECT_ROOT / 'web'

class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Custom handler to serve from web directory and add CORS headers"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)
    
    def end_headers(self):
        # Explicitly set charset for HTML and JSON to ensure Unicode displays correctly
        # This fixes the issue with missing emojis (âœ… vs âŒ) in the dashboard
        path = self.path.lower()
        if path.endswith('.html') or path.endswith('.htm'):
            self.send_header('Content-Type', 'text/html; charset=utf-8')
        elif path.endswith('.json'):
            self.send_header('Content-Type', 'application/json; charset=utf-8')
        elif path.endswith('.js'):
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
        elif path.endswith('.css'):
            self.send_header('Content-Type', 'text/css; charset=utf-8')
            
        # Add CORS headers for cross-origin requests
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        super().end_headers()
    
    def log_message(self, format, *args):
        """Custom log format"""
        print(f"[{self.log_date_time_string()}] {format % args}")

def start_ngrok(port):
    """Start ngrok tunnel if available"""
    try:
        import subprocess
        # Check if ngrok is available
        result = subprocess.run(['ngrok', 'version'], 
                              capture_output=True, 
                              text=True, 
                              timeout=2)
        if result.returncode == 0:
            print("\n" + "="*60)
            print("Starting ngrok tunnel...")
            print("⚠️  NOTE: ngrok free tier has bandwidth limits")
            print("   Consider using Cloudflare Tunnel instead (unlimited, free)")
            print("   Run: python start_web_server_cloudflare.py")
            print("="*60)
            # Start ngrok in background
            ngrok_process = subprocess.Popen(
                ['ngrok', 'http', str(port)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            time.sleep(3)  # Wait for ngrok to start
            
            # Try to get the public URL from ngrok API
            try:
                import urllib.request
                import json
                response = urllib.request.urlopen('http://127.0.0.1:4040/api/tunnels', timeout=2)
                data = json.loads(response.read())
                if data.get('tunnels'):
                    public_url = data['tunnels'][0]['public_url']
                    print(f"\n✅ ngrok tunnel active!")
                    print(f"🌐 Public URL: {public_url}")
                    print(f"📱 Access from anywhere: {public_url}")
                    print("="*60 + "\n")
                    return ngrok_process, public_url
            except:
                print("⚠️  ngrok started but couldn't retrieve public URL")
                print("   Check http://127.0.0.1:4040 for ngrok web interface")
                return ngrok_process, None
    except FileNotFoundError:
        print("\n⚠️  ngrok not found. Install from: https://ngrok.com/download")
        print("   💡 Better option: Use Cloudflare Tunnel (unlimited, free)")
        print("   Run: python start_web_server_cloudflare.py")
        print("   Or use localhost only (http://127.0.0.1:8000)\n")
        return None, None
    except Exception as e:
        print(f"\n⚠️  Error starting ngrok: {e}")
        print("   💡 Consider Cloudflare Tunnel instead (unlimited, free)")
        print("   Continuing with localhost only...\n")
        return None, None

def main():
    """Start the web server"""
    # Ensure web directory exists
    WEB_DIR.mkdir(exist_ok=True)
    
    # Check if index.html exists
    if not (WEB_DIR / 'index.html').exists():
        print("⚠️  Warning: index.html not found in web/ directory")
        print("   Creating a basic index.html...")
        (WEB_DIR / 'index.html').write_text("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading System Dashboard Hub</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; margin: 0; padding: 20px; color: #333; }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 { text-align: center; color: #2c3e50; margin-bottom: 30px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .card { background: white; border-radius: 10px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); transition: transform 0.2s, box-shadow 0.2s; display: flex; flex-direction: column; text-decoration: none; color: inherit; border-left: 5px solid #ccc; position: relative; }
        .card:hover { transform: translateY(-5px); box-shadow: 0 8px 12px rgba(0,0,0,0.15); }
        .card h2 { margin-top: 0; color: #34495e; font-size: 1.2rem; display: flex; justify-content: space-between; align-items: center; }
        .card .status-indicator { font-size: 0.8rem; padding: 2px 8px; border-radius: 10px; background: #eee; color: #666; font-weight: normal; }
        .card p { color: #7f8c8d; font-size: 0.9rem; flex-grow: 1; margin-bottom: 15px; }
        .card .metrics { background: #f9f9f9; padding: 10px; border-radius: 5px; font-size: 0.85rem; }
        .card .metrics div { display: flex; justify-content: space-between; margin-bottom: 5px; }
        .card .metrics div:last-child { margin-bottom: 0; }
        .card .metrics span.label { color: #7f8c8d; }
        .card .metrics span.value { font-weight: bold; color: #2c3e50; }
        .card .footer { margin-top: auto; font-size: 0.8rem; color: #bdc3c7; text-align: right; }
        
        .border-blue { border-left-color: #3498db; }
        .border-green { border-left-color: #27ae60; }
        .border-purple { border-left-color: #9b59b6; }
        
        .loading-pulse { animation: pulse 1.5s infinite; opacity: 0.6; }
        @keyframes pulse { 0% { opacity: 0.6; } 50% { opacity: 1; } 100% { opacity: 0.6; } }
        
        .val-positive { color: #27ae60 !important; }
        .val-negative { color: #e74c3c !important; }
        .status-connected { background-color: #d4edda !important; color: #155724 !important; }
        .status-disconnected { background-color: #f8d7da !important; color: #721c24 !important; }
        
        #last-update-all { text-align: center; color: #95a5a6; font-size: 0.8rem; margin-top: 30px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Trading System Dashboards (v4.0)</h1>
        
        <div class="grid">
            <!-- LIVE TRADING -->
            <a href="ib_deployment_dashboard.html" class="card border-green" id="card-live">
                <h2>Live Trading <span class="status-indicator loading-pulse" id="live-status">Checking...</span></h2>
                <p>Deploy strategies to Interactive Brokers live/paper account.</p>
                <div class="metrics" id="live-metrics">
                    <div style="text-align:center; color:#999;">Loading metrics...</div>
                </div>
                <div class="footer" id="live-updated">Last Check: Never</div>
            </a>

            <!-- GENETIC ALGORITHM -->
            <a href="ga_dashboard_v4.html" class="card border-purple" id="card-ga">
                <h2>Genetic Optimizer <span class="status-indicator" id="ga-status">v4.0</span></h2>
                <p>Monitor multi-objective evolution progress and Pareto front analysis.</p>
                <div class="metrics" id="ga-metrics">
                    <div style="text-align:center; color:#999;">Loading metrics...</div>
                </div>
                <div class="footer" id="ga-updated">Last Check: Never</div>
            </a>

            <!-- BACKTESTING -->
            <a href="comprehensive_dashboard_v4.0.html" class="card border-blue" id="card-bt">
                <h2>Backtest Analysis <span class="status-indicator">v4.0</span></h2>
                <p>Deep dive into strategy performance, trades, and equity curves.</p>
                <div class="metrics" id="bt-metrics">
                    <div style="text-align:center; color:#999;">Loading metrics...</div>
                </div>
                <div class="footer" id="bt-updated">Last Check: Never</div>
            </a>
        </div>
        
        <div id="last-update-all">Auto-refreshing summaries every 30s</div>
    </div>

    <script>
        const parser = new DOMParser();

        async function fetchAndParse(url) {
            try {
                const response = await fetch(url, { cache: "no-store" });
                if (!response.ok) throw new Error('Failed to load');
                const text = await response.text();
                return parser.parseFromString(text, 'text/html');
            } catch (e) {
                console.error(`Error fetching ${url}:`, e);
                return null;
            }
        }

        // --- SCRAPERS ---
        
        async function updateLiveCard() {
            const doc = await fetchAndParse('ib_deployment_dashboard.html');
            const metricsDiv = document.getElementById('live-metrics');
            const statusSpan = document.getElementById('live-status');
            const footer = document.getElementById('live-updated');
            
            if (!doc) {
                statusSpan.textContent = 'Offline';
                statusSpan.className = 'status-indicator status-disconnected';
                metricsDiv.innerHTML = '<div style="color:#e74c3c">Dashboard not found</div>';
                return;
            }

            // Status
            const connHeader = Array.from(doc.querySelectorAll('h2')).find(h => h.textContent.includes('Connection Status'));
            const isConnected = connHeader && connHeader.textContent.includes('CONNECTED');
            statusSpan.textContent = isConnected ? 'Connected' : 'Disconnected';
            statusSpan.className = `status-indicator ${isConnected ? 'status-connected' : 'status-disconnected'}`;
            
            // Metrics (Semantic Search)
            const labels = Array.from(doc.querySelectorAll('.label'));
            const getValue = (name) => {
                const labelEl = labels.find(l => l.textContent.includes(name));
                return labelEl ? labelEl.nextElementSibling.textContent.trim() : 'N/A';
            };
            
            const netLiq = getValue('Net Liquidation');
            const unrealized = getValue('Unrealized PNL');
            const openPos = getValue('Open ES Positions');
            
            // Clean content of newlines/spaces
            const clean = (s) => s.replace(/[\\n\\r]+/g, '').replace(/\\s+/g, ' ').trim();

            metricsDiv.innerHTML = `
                <div><span class="label">Net Liq:</span> <span class="value">${clean(netLiq)}</span></div>
                <div><span class="label">Unrealized:</span> <span class="value ${clean(unrealized).includes('-') ? 'val-negative' : 'val-positive'}">${clean(unrealized)}</span></div>
                <div><span class="label">Open Pos:</span> <span class="value">${clean(openPos)}</span></div>
            `;
            
            // Updated Time
            const timeP = Array.from(doc.querySelectorAll('p')).find(p => p.textContent.includes('Last Updated'));
            if(timeP) footer.textContent = timeP.textContent;
            else footer.textContent = 'Updated: Just now';
        }

        async function updateGACard() {
            const doc = await fetchAndParse('ga_dashboard_v4.html');
            const metricsDiv = document.getElementById('ga-metrics');
            const footer = document.getElementById('ga-updated');
            
            if (!doc) {
                metricsDiv.innerHTML = '<div style="color:#ccc">Not started yet</div>';
                return;
            }

            // Generation Progress (Look for text "Generation X of Y")
            // Or look for any h2/h3 that mentions Generation
            let genText = "Unknown Generaton";
            const bodyText = doc.body.textContent;
            const genMatch = bodyText.match(/Generation\\s+(\\d+)\\s+of\\s+(\\d+)/i) || bodyText.match(/Generation\\s+(\\d+)/i);
            if(genMatch) genText = genMatch[0];

            // Metrics from a table or boxes
            // Look for "Best Sortino" label
            const findMetric = (term) => {
                // Try .metric-label style first
                let els = Array.from(doc.querySelectorAll('.metric-label, th, .label'));
                let found = els.find(e => e.textContent.toLowerCase().includes(term.toLowerCase()));
                if(found) {
                    // Try next sibling or cell
                    if (found.tagName === 'TH') {
                        // Table logic: find index, get corresponding TD
                        const tr = found.parentElement;
                        const ths = Array.from(tr.querySelectorAll('th'));
                        const idx = ths.indexOf(found);
                        const nextTr = tr.nextElementSibling;
                        if(nextTr) {
                             const tds = nextTr.querySelectorAll('td');
                             if(tds[idx]) return tds[idx].textContent.trim();
                        }
                        return null; 
                    }
                    return found.nextElementSibling ? found.nextElementSibling.textContent.trim() : null;
                }
                return null;
            };

            const getTableVal = (key) => {
                // Heuristic for GA table
                const tds = Array.from(doc.querySelectorAll('td'));
                const idx = tds.findIndex(td => td.textContent.includes(key));
                if(idx !== -1 && idx + 1 < tds.length) return tds[idx+1].textContent.trim();
                return 'N/A';
            };

            // Try different accessors based on potential HTML structures
            const sortino = getTableVal('Sortino') || 'N/A';
            const pf = getTableVal('Profit Factor') || 'N/A';
            
            metricsDiv.innerHTML = `
                <div style="margin-bottom:8px; border-bottom:1px solid #eee; padding-bottom:4px"><strong>${genText}</strong></div>
                <div><span class="label">Best Sortino:</span> <span class="value">${sortino}</span></div>
                <div><span class="label">Profit Factor:</span> <span class="value">${pf}</span></div>
            `;
            footer.textContent = 'Fetched: ' + new Date().toLocaleTimeString();
        }

        async function updateBacktestCard() {
            const doc = await fetchAndParse('comprehensive_dashboard_v4.0.html');
            const metricsDiv = document.getElementById('bt-metrics');
            const footer = document.getElementById('bt-updated');
            
            if (!doc) {
                metricsDiv.innerHTML = '<div style="color:#ccc">No backtest report</div>';
                return;
            }

            // Reporting.py uses .metric-box .metric-label .metric-val
            const getMetric = (name) => {
                const labels = Array.from(doc.querySelectorAll('.metric-label'));
                const matched = labels.find(l => l.textContent.trim() === name);
                if(matched && matched.nextElementSibling) return matched.nextElementSibling.textContent.trim();
                return 'N/A';
            };
            
            const pnl = getMetric('Total PnL');
            const winRate = getMetric('Win Rate');
            const pf = getMetric('Profit Factor');
            const trades = getMetric('Trades');

            metricsDiv.innerHTML = `
                <div><span class="label">Total PnL:</span> <span class="value ${pnl.includes('-')?'val-negative':'val-positive'}">${pnl}</span></div>
                <div><span class="label">Win Rate:</span> <span class="value">${winRate}</span></div>
                <div><span class="label">Profit Factor:</span> <span class="value">${pf}</span></div>
                <div><span class="label">Trades:</span> <span class="value">${trades}</span></div>
            `;
             footer.textContent = 'Fetched: ' + new Date().toLocaleTimeString();
        }

        // --- ORCHESTRATION ---
        async function refreshAll() {
            await Promise.all([updateLiveCard(), updateGACard(), updateBacktestCard()]);
            document.getElementById('last-update-all').textContent = 'Last auto-refresh: ' + new Date().toLocaleTimeString();
        }

        // Init
        refreshAll();
        // Loop
        setInterval(refreshAll, 30000); 

    </script>
</body>
</html>""")
    
    # Start HTTP server
    with socketserver.TCPServer(("", PORT), CustomHTTPRequestHandler) as httpd:
        print("="*60)
        print("Trading Strategy Web Server")
        print("="*60)
        print(f"Serving directory: {WEB_DIR.absolute()}")
        print(f"Local URL: http://127.0.0.1:{PORT}")
        print(f"Network URL: http://{get_local_ip()}:{PORT}")
        print("="*60)
        print("\nTips:")
        print("   - Access from this computer: http://127.0.0.1:8000")
        print("   - Access from network: http://<your-ip>:8000")
        print("   - Press Ctrl+C to stop the server")
        print("\n⚠️  ngrok bandwidth limit hit?")
        print("   💡 Use Cloudflare Tunnel instead (FREE, unlimited):")
        print("      python start_web_server_cloudflare.py")
        print("\n" + "="*60 + "\n")
        
        # Try to start ngrok
        ngrok_process, public_url = start_ngrok(PORT)
        
        # Open browser
        try:
            if public_url:
                webbrowser.open(public_url)
            else:
                webbrowser.open(f'http://127.0.0.1:{PORT}')
        except:
            pass
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n🛑 Shutting down server...")
            if ngrok_process:
                ngrok_process.terminate()
            print("✅ Server stopped")
            sys.exit(0)

def get_local_ip():
    """Get local IP address"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"

if __name__ == '__main__':
    main()


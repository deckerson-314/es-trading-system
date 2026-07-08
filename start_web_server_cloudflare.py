#!/usr/bin/env python3
"""
HTTP server for Trading Strategy Dashboards with Cloudflare Tunnel support
Cloudflare Tunnel is a free alternative to ngrok with no bandwidth limits
"""

import logging
import os
import re
import socket
import sys
import http.server
import socketserver
import webbrowser
import threading
import time
import subprocess
from datetime import datetime
from pathlib import Path

# Configuration
PORT = 8000
WEB_DIR = Path(__file__).parent / 'web'
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

from tools.notifications.email_service import send_email

_TUNNEL_URL_RE = re.compile(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com')
_TUNNEL_REGISTERED_RE = re.compile(r'Registered tunnel connection', re.I)
_TUNNEL_FAILED_RE = re.compile(
    r'(?:Register tunnel error|initial tunnel connection failed|'
    r'failed to request quick Tunnel|Cloudflared reached the Cloudflare edge)',
    re.I,
)

class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Custom handler to serve from web directory and add CORS headers"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)
    
    def end_headers(self):
        # Add CORS headers for cross-origin requests
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        super().end_headers()
    
    def log_message(self, format, *args):
        """Custom log format"""
        print(f"[{self.log_date_time_string()}] {format % args}")

def start_cloudflare_tunnel(port):
    """Start Cloudflare Tunnel if available; return (process, public_url or None)."""
    try:
        result = subprocess.run(
            ['cloudflared', '--version'],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return None, None
    except FileNotFoundError:
        print("\nWarning: cloudflared not found.")
        print("   Install from: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/")
        print("   Or use localhost only (http://127.0.0.1:8000)\n")
        return None, None
    except Exception as e:
        print(f"\nWarning: Error checking cloudflared: {e}")
        print("   Continuing with localhost only...\n")
        return None, None

    print("\n" + "=" * 60)
    print("Starting Cloudflare Tunnel...")
    print("=" * 60)
    print("Cloudflare Tunnel provides:")
    print("  - FREE unlimited bandwidth")
    print("  - No account required for basic use")
    print("  - Permanent subdomain option (with account)")
    print("=" * 60)

    tunnel_state = {"url": None, "registered": False, "failed": False, "error": None}

    def _launch_cloudflared(extra_args=None):
        cmd = ['cloudflared', 'tunnel', '--url', f'http://127.0.0.1:{port}']
        if extra_args:
            cmd.extend(extra_args)
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    def _start_output_reader(process):
        def _read_tunnel_output():
            for line in process.stdout:
                print(line, end='')
                if tunnel_state["url"] is None:
                    match = _TUNNEL_URL_RE.search(line)
                    if match:
                        tunnel_state["url"] = match.group(0)
                if _TUNNEL_REGISTERED_RE.search(line):
                    tunnel_state["registered"] = True
                if _TUNNEL_FAILED_RE.search(line):
                    tunnel_state["failed"] = True
                    tunnel_state["error"] = line.strip()

        reader = threading.Thread(target=_read_tunnel_output, daemon=True)
        reader.start()

    def _wait_for_registration(process, timeout_sec=25):
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if tunnel_state["registered"]:
                return True
            if tunnel_state["failed"] or process.poll() is not None:
                return False
            time.sleep(0.25)
        return tunnel_state["registered"]

    try:
        # Default protocol is QUIC; forcing http2 often fails on quick tunnels.
        cloudflared_process = _launch_cloudflared()
        _start_output_reader(cloudflared_process)
        registered = _wait_for_registration(cloudflared_process)
        if not registered:
            if cloudflared_process.poll() is None:
                cloudflared_process.terminate()
                try:
                    cloudflared_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    cloudflared_process.kill()
            print("\nWarning: Cloudflare quick tunnel failed to register.")
            if tunnel_state["error"]:
                print(f"   Last error: {tunnel_state['error']}")
            print("   Local dashboard still works at http://127.0.0.1:{0}".format(port))
            print("   Retry tunnel later or run: cloudflared tunnel --url http://127.0.0.1:{0}".format(port))
            print("=" * 60 + "\n")
            return None, None

        public_url = tunnel_state["url"]
        if public_url:
            print("\nCloudflare Tunnel active!")
            print(f"Public URL: {public_url}")
            print(f"Access from anywhere: {public_url}")
        else:
            print("\nCloudflare Tunnel registered (public URL not detected in output).")
            print("   Check output above for https://....trycloudflare.com")
        print("=" * 60 + "\n")
        return cloudflared_process, public_url
    except Exception as e:
        print(f"\nWarning: Error starting Cloudflare Tunnel: {e}")
        print("   Continuing with localhost only...\n")
        return None, None


def send_startup_email(port: int, local_ip: str, public_url: str | None = None) -> bool:
    """Notify via email (same service as paper bot) with dashboard links."""
    local_url = f"http://127.0.0.1:{port}"
    lan_url = f"http://{local_ip}:{port}" if local_ip else None
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hostname = socket.gethostname()

    lines = [
        "Trading dashboard web server started.",
        "",
        f"Time:   {now}",
        f"Host:   {hostname}",
        f"Port:   {port}",
        "",
        f"Local:  {local_url}",
    ]
    if lan_url and local_ip not in ("localhost", "127.0.0.1"):
        lines.append(f"LAN:    {lan_url}")
    elif lan_url:
        lines.append(f"LAN:    (unavailable — using {local_ip})")

    if public_url:
        lines.extend([
            f"Public: {public_url}",
            "",
            "Quick links (public):",
            f"  Hub:   {public_url}/index.html",
            f"  Paper: {public_url}/dashboard_paper.html",
        ])
    else:
        lines.extend([
            "Public: (none — Cloudflare tunnel unavailable or URL pending)",
        ])

    lines.extend([
        "",
        "Quick links (local):",
        f"  Hub:   {local_url}/index.html",
        f"  Paper: {local_url}/dashboard_paper.html",
    ])
    if lan_url and local_ip not in ("localhost", "127.0.0.1"):
        lines.extend([
            "",
            "Quick links (LAN):",
            f"  Hub:   {lan_url}/index.html",
            f"  Paper: {lan_url}/dashboard_paper.html",
        ])

    subject = f"[WEB] START: Dashboard server (port {port})"
    return send_email(subject, "\n".join(lines))

def main():
    """Start the web server"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Fix Windows console encoding issues for Unicode (emojis)
    try:
        if sys.platform == 'win32':
            sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass

    # Ensure web directory exists
    WEB_DIR.mkdir(exist_ok=True)
    
    # Check if index.html exists
    if not (WEB_DIR / 'index.html').exists():
        print("Warning: index.html not found in web/ directory")
        print("Creating a basic index.html...")
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
        print("STARTING: Trading Strategy Web Server")
        print("="*60)
        print(f"Serving directory: {WEB_DIR.absolute()}")
        print(f"Local URL: http://127.0.0.1:{PORT}")
        print(f"Network URL: http://{get_local_ip()}:{PORT}")
        print("="*60)
        print("\nRemote Access Options:")
        print("   1. Cloudflare Tunnel (FREE, unlimited bandwidth)")
        print("   2. Port Forwarding (permanent, requires router access)")
        print("   3. VPN (most secure)")
        print("\n   Press Ctrl+C to stop the server")
        print("="*60 + "\n")
        
        # Try to start Cloudflare Tunnel
        cloudflared_process, public_url = start_cloudflare_tunnel(PORT)

        local_ip = get_local_ip()
        if send_startup_email(PORT, local_ip, public_url):
            print("Startup notification email sent.")
        else:
            print("Startup notification email not sent (check .env EMAIL_* credentials).")
        
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
            print("\n\nShutting down server...")
            if cloudflared_process:
                cloudflared_process.terminate()
            print("Server stopped")
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


#!/usr/bin/env python3
"""
HTTP server for Trading Strategy Dashboards with Cloudflare Tunnel support
Cloudflare Tunnel is a free alternative to ngrok with no bandwidth limits
"""

import os
import sys
import http.server
import socketserver
import webbrowser
import threading
import time
import subprocess
from pathlib import Path

# Configuration
PORT = 8000
WEB_DIR = Path(__file__).parent / 'web'

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
    """Start Cloudflare Tunnel if available"""
    try:
        # Check if cloudflared is available
        result = subprocess.run(['cloudflared', '--version'], 
                              capture_output=True, 
                              text=True, 
                              timeout=2)
        if result.returncode == 0:
            print("\n" + "="*60)
            print("Starting Cloudflare Tunnel...")
            print("="*60)
            print("Cloudflare Tunnel provides:")
            print("  - FREE unlimited bandwidth")
            print("  - No account required for basic use")
            print("  - Permanent subdomain option (with account)")
            print("="*60)
            
            # Start cloudflared in background
            cloudflared_process = subprocess.Popen(
                ['cloudflared', 'tunnel', '--url', f'http://127.0.0.1:{port}'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait a moment for tunnel to establish
            time.sleep(4)
            
            # Try to extract URL from output (cloudflared prints it to stderr)
            try:
                # Give it a moment to output the URL
                time.sleep(1)
                # The URL is typically printed to stderr
                # For now, we'll just indicate it's running
                print(f"\n✅ Cloudflare Tunnel active!")
                print(f"🌐 Check the output above for your public URL")
                print(f"   (Usually starts with: https://xxxx-xxxx.trycloudflare.com)")
                print(f"📱 Access from anywhere using that URL")
                print("="*60 + "\n")
                return cloudflared_process, None
            except:
                print("⚠️  Cloudflare Tunnel started but couldn't extract URL")
                print("   Check the output above for the public URL")
                return cloudflared_process, None
    except FileNotFoundError:
        print("\n⚠️  cloudflared not found.")
        print("   Install from: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/")
        print("   Or use localhost only (http://127.0.0.1:8000)\n")
        return None, None
    except Exception as e:
        print(f"\n⚠️  Error starting Cloudflare Tunnel: {e}")
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
        (WEB_DIR / 'index.html').write_text("""
<!DOCTYPE html>
<html>
<head><title>Trading Dashboards</title></head>
<body>
    <h1>Trading Strategy Dashboards</h1>
    <ul>
        <li><a href="ib_deployment_dashboard.html">Live Trading Dashboard</a></li>
        <li><a href="ga_dashboard_v3.html">Genetic Algorithm Dashboard</a></li>
        <li><a href="comprehensive_dashboard_v3.0.html">Backtest Dashboard</a></li>
    </ul>
</body>
</html>
        """)
    
    # Start HTTP server
    with socketserver.TCPServer(("", PORT), CustomHTTPRequestHandler) as httpd:
        print("="*60)
        print("🚀 Trading Strategy Web Server")
        print("="*60)
        print(f"📁 Serving directory: {WEB_DIR.absolute()}")
        print(f"🌐 Local URL: http://127.0.0.1:{PORT}")
        print(f"🌐 Network URL: http://{get_local_ip()}:{PORT}")
        print("="*60)
        print("\n💡 Remote Access Options:")
        print("   1. Cloudflare Tunnel (FREE, unlimited bandwidth)")
        print("   2. Port Forwarding (permanent, requires router access)")
        print("   3. VPN (most secure)")
        print("\n   Press Ctrl+C to stop the server")
        print("="*60 + "\n")
        
        # Try to start Cloudflare Tunnel
        cloudflared_process, public_url = start_cloudflare_tunnel(PORT)
        
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
            if cloudflared_process:
                cloudflared_process.terminate()
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


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
        print("\n💡 Tips:")
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


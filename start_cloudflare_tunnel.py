#!/usr/bin/env python3
"""
Simple script to start Cloudflare Tunnel to existing web server
Use this if you already have a web server running on port 8000
"""

import subprocess
import sys
import time

PORT = 8000

def main():
    """Start Cloudflare Tunnel to local server"""
    print("="*60)
    print("🌐 Starting Cloudflare Tunnel")
    print("="*60)
    print(f"Tunneling to: http://127.0.0.1:{PORT}")
    print("\n💡 Make sure your web server is running on port 8000")
    print("   Press Ctrl+C to stop the tunnel")
    print("="*60 + "\n")
    
    try:
        import re
        
        # Start cloudflared tunnel
        # Note: cloudflared outputs URL to stderr
        process = subprocess.Popen(
            ['cloudflared', 'tunnel', '--url', f'http://127.0.0.1:{PORT}'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        print("Cloudflare Tunnel starting...\n")
        print("Looking for public URL (usually appears within 5-10 seconds)...\n")
        
        url_found = False
        public_url = None
        
        for line in process.stdout:
            print(line, end='')
            # Look for the URL (cloudflared outputs it to stderr, which we merged)
            if not url_found and ('trycloudflare.com' in line or 'https://' in line):
                # Extract URL using regex
                url_match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
                if url_match:
                    public_url = url_match.group(0)
                    url_found = True
                    print("\n" + "="*60)
                    print("✅ TUNNEL ACTIVE!")
                    print("="*60)
                    print(f"🌐 Public URL: {public_url}")
                    print(f"📱 Access from anywhere: {public_url}")
                    print("="*60 + "\n")
        
        # Wait for process
        process.wait()
        
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping tunnel...")
        if 'process' in locals():
            process.terminate()
        print("✅ Tunnel stopped")
        sys.exit(0)
    except FileNotFoundError:
        print("❌ Error: cloudflared not found!")
        print("   Please install cloudflared first:")
        print("   winget install --id Cloudflare.cloudflared")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()


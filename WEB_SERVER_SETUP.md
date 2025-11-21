# Web Server Setup Guide

## Overview

A centralized web server has been set up to access all trading strategy dashboards remotely. All HTML files are now stored in the `web/` directory for easy access.

## Files Created

1. **web/index.html** - Landing page showing summaries of all three dashboards
2. **start_web_server.py** - Python HTTP server with ngrok support
3. **setup_web_files.py** - Script to copy existing files to web directory
4. **web/README.md** - Documentation for the web directory

## Dashboard Locations

All dashboards are automatically copied to `web/` when generated:

- **Live Trading**: `web/ib_deployment_dashboard.html`
- **Genetic Algorithm**: `web/ga_dashboard_v3.html`
- **Backtest Analysis**: `web/comprehensive_dashboard_v3.0.html`

## Starting the Server

### Option 1: Simple Start (Localhost Only)
```bash
python start_web_server.py
```

### Option 2: With ngrok (Remote Access)
If ngrok is installed, it will automatically start:
```bash
python start_web_server.py
# ngrok will start automatically and show public URL
```

### Option 3: Manual ngrok
If you prefer to run ngrok separately:
```bash
# Terminal 1: Start web server
python start_web_server.py

# Terminal 2: Start ngrok
ngrok http 8000
```

## Access URLs

After starting the server, you'll see:

- **Local**: http://127.0.0.1:8000
- **Network**: http://<your-local-ip>:8000
- **Public (ngrok)**: https://xxxx-xx-xx-xx-xx.ngrok.io (if ngrok auto-started)

## Landing Page Features

The landing page (`index.html`) shows:
- Status indicators for each dashboard
- Summary statistics from each dashboard
- Links to full dashboards
- Auto-refresh every 30 seconds
- Preview iframes (if cross-origin allows)

## Remote Access Options

### 1. ngrok (Recommended - Already Integrated)
- **Pros**: Easy, secure, works behind firewalls
- **Cons**: Free tier has session limits, URLs change
- **Setup**: Already integrated in `start_web_server.py`

### 2. Port Forwarding (Router)
- **Pros**: Permanent URL, no third-party
- **Cons**: Requires router access, security considerations
- **Setup**: Forward port 8000 to your computer's IP

### 3. VPN (Most Secure)
- **Pros**: Very secure, full network access
- **Cons**: Requires VPN server setup
- **Options**: Tailscale, ZeroTier, WireGuard

### 4. Cloudflare Tunnel (Alternative to ngrok)
- **Pros**: Free, permanent subdomain, no port forwarding
- **Cons**: Requires Cloudflare account
- **Setup**: Install `cloudflared` and run: `cloudflared tunnel --url http://127.0.0.1:8000`

## Security Considerations

⚠️ **Important**: The current setup has no authentication. Anyone with the URL can access your dashboards.

### Recommended Security Measures:

1. **Use ngrok with authentication**:
   ```bash
   ngrok http 8000 --basic-auth="username:password"
   ```

2. **Add authentication to the web server** (future enhancement)

3. **Use VPN** for the most secure remote access

4. **Firewall rules**: Only allow access from trusted IPs

## Troubleshooting

### Port Already in Use
If port 8000 is busy, edit `start_web_server.py` and change `PORT = 8000` to another port.

### ngrok Not Starting
- Check if ngrok is installed: `ngrok version`
- Install from: https://ngrok.com/download
- Or use localhost only (remove ngrok code)

### Files Not Updating
- Check that scripts are copying files to `web/` directory
- Verify file permissions
- Check console output for copy errors

### Cross-Origin Issues
- The server includes CORS headers
- If iframes don't load, it's likely a browser security restriction
- Use direct links instead of iframes

## Maintenance

### Updating Existing Files
Run once to copy existing files:
```bash
python setup_web_files.py
```

### Automatic Updates
All three scripts now automatically copy HTML files to `web/` when generated:
- `BB_Strategy_v3.py` - Copies backtest dashboard
- `BB_Genetic_v3.py` - Copies GA dashboard  
- `ib_deployment_v2.py` - Copies live trading dashboard

## Next Steps

1. ✅ Run `python setup_web_files.py` to copy existing files
2. ✅ Start server: `python start_web_server.py`
3. ✅ Access landing page at http://127.0.0.1:8000
4. ✅ For remote access, use ngrok URL shown in console
5. 🔒 Consider adding authentication for production use


# Cloudflare Tunnel - Quick Start Guide

## ✅ Installation Complete!

`cloudflared` has been successfully installed on your system.

## 🚀 Two Ways to Use Cloudflare Tunnel

### Option 1: Tunnel to Existing Server (Recommended)

If you already have a web server running on port 8000:

```powershell
python start_cloudflare_tunnel.py
```

This will:
- Connect to your existing server on port 8000
- Create a public Cloudflare URL
- Display the URL in the console

**Keep this window open** - the tunnel stays active while the script runs.

---

### Option 2: Start New Server with Cloudflare

If you want to start a fresh server with Cloudflare built-in:

```powershell
python start_web_server_cloudflare.py
```

This will:
- Start a new web server on port 8000
- Automatically create a Cloudflare tunnel
- Open your browser to the public URL

**Note:** Make sure to stop any existing server on port 8000 first!

---

## 📱 Accessing Your Dashboards

Once the tunnel is active, you'll see a URL like:
```
https://xxxx-xxxx.trycloudflare.com
```

**Use this URL from anywhere:**
- Your phone
- Another computer
- Any device with internet access

The URL is **temporary** and changes each time you restart the tunnel.

---

## 🔒 Security Note

⚠️ **Important:** Your dashboards have NO password protection. Anyone with the URL can access them.

**For better security:**
1. Use a VPN (like Tailscale) instead
2. Or add authentication to your web server
3. Or set up a permanent Cloudflare tunnel with authentication

---

## 🛑 Stopping the Tunnel

Press `Ctrl+C` in the terminal where the tunnel is running.

---

## ❓ Troubleshooting

**"cloudflared not found"**
- Restart your terminal/PowerShell
- Or add cloudflared to PATH manually

**"Port 8000 already in use"**
- Stop the existing server first
- Or use Option 1 (tunnel to existing server)

**"Connection failed"**
- Make sure your web server is running
- Check that port 8000 is accessible locally: `http://127.0.0.1:8000`

---

## 📚 More Information

- Cloudflare Tunnel docs: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/
- For permanent URLs: Create a free Cloudflare account and set up a named tunnel


# Installing Cloudflare Tunnel (cloudflared) on Windows

## Quick Install Options

### Option 1: Using winget (Recommended)
```powershell
winget install --id Cloudflare.cloudflared
```

### Option 2: Using Chocolatey
```powershell
choco install cloudflared
```

### Option 3: Manual Download
1. Go to: https://github.com/cloudflare/cloudflared/releases/latest
2. Download: `cloudflared-windows-amd64.exe` (or `cloudflared-windows-386.exe` for 32-bit)
3. Rename to `cloudflared.exe`
4. Add to PATH or place in a folder in your PATH

### Option 4: Using Scoop
```powershell
scoop install cloudflared
```

## Verify Installation

After installing, verify it works:
```powershell
cloudflared --version
```

You should see something like:
```
cloudflared version 2024.x.x (built YYYY-MM-DD)
```

## Using with Trading Dashboards

Once installed, simply run:
```powershell
python start_web_server_cloudflare.py
```

The script will automatically detect cloudflared and start the tunnel!


# Web dashboard + Cloudflare tunnel (long-running).
. (Join-Path $PSScriptRoot "trading_common.ps1")
$Host.UI.RawUI.WindowTitle = "Trading - Web"
Enter-TradingRepo
Write-Host "Starting web server..." -ForegroundColor Green
Start-TradingWeb

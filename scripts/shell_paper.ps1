# Trend paper bot (long-running).
. (Join-Path $PSScriptRoot "trading_common.ps1")
$Host.UI.RawUI.WindowTitle = "Trading - Paper"
Enter-TradingRepo
Write-Host "Starting paper bot on port $TradingPaperPort..." -ForegroundColor Green
Start-TradingPaper

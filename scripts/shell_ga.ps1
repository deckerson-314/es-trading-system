# GA optimize shell — venv ready; type 'ga -Fresh' or customize.
. (Join-Path $PSScriptRoot "trading_common.ps1")
$Host.UI.RawUI.WindowTitle = "Trading - GA"
Enter-TradingRepo
Show-TradingHelp
Write-Host "Example: ga -Fresh" -ForegroundColor Yellow
Write-Host "  -> trend, $TradingGaCores cores" -ForegroundColor DarkGray

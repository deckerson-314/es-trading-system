# Backtest shell — venv ready; type 'backtest' or run with custom args.
. (Join-Path $PSScriptRoot "trading_common.ps1")
$Host.UI.RawUI.WindowTitle = "Trading - Backtest"
Enter-TradingRepo
Show-TradingHelp
Write-Host "Example: backtest" -ForegroundColor Yellow
Write-Host "  -> $TradingBacktestStart .. $TradingBacktestEnd" -ForegroundColor DarkGray

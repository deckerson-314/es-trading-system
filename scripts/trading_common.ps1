# Shared setup for Trading workstation shells (venv, paths, command helpers).
# Dot-source from scripts/shell_*.ps1 — do not run directly.

$script:TradingRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$script:TradingVenvActivate = Join-Path $TradingRoot "venv\Scripts\Activate.ps1"
$script:TradingPython = Join-Path $TradingRoot "venv\Scripts\python.exe"

$script:TradingDataCsv = Join-Path $TradingRoot "Bollinger\data\ES_full_1min_continuous_ratio_adjusted.csv"
$script:TradingProdParams = Join-Path $TradingRoot "strategies\trend\parameters\trend_strategy_params.csv"

$script:TradingBacktestStart = "2020-01-02"
$script:TradingBacktestEnd = "2025-07-14"
$script:TradingPaperPort = 4002
$script:TradingGaCores = 6

function Enter-TradingRepo {
    Set-Location $TradingRoot
    if (-not (Test-Path $TradingVenvActivate)) {
        throw "Virtual environment not found: $TradingVenvActivate"
    }
    . $TradingVenvActivate
}

function Start-TradingWeb {
    Set-Location $TradingRoot
    & $TradingPython (Join-Path $TradingRoot "start_web_server_cloudflare.py") @args
}

function Start-TradingPaper {
    Set-Location $TradingRoot
    & $TradingPython (Join-Path $TradingRoot "main.py") `
        --mode PAPER --strategy trend --port $TradingPaperPort @args
}

function Invoke-TradingBacktest {
    param(
        [string] $Start = $TradingBacktestStart,
        [string] $End = $TradingBacktestEnd,
        [string] $Data = $TradingDataCsv,
        [string] $Params = $TradingProdParams,
        [string] $Strategy = "trend"
    )
    Set-Location $TradingRoot
    & $TradingPython (Join-Path $TradingRoot "backtest.py") `
        --strategy $Strategy `
        --data $Data `
        --params $Params `
        --start $Start `
        --end $End @args
}

function Invoke-TradingGA {
    param(
        [int] $Cores = $TradingGaCores,
        [string] $Strategy = "trend",
        [switch] $Fresh
    )
    Set-Location $TradingRoot
    $gaArgs = @(
        (Join-Path $TradingRoot "optimize.py"),
        "--strategy", $Strategy,
        "--cores", "$Cores"
    )
    if ($Fresh) { $gaArgs += "--fresh" }
    & $TradingPython @gaArgs @args
}

# Short aliases for interactive shells
Set-Alias -Name backtest -Value Invoke-TradingBacktest -Scope Global -Force
Set-Alias -Name ga -Value Invoke-TradingGA -Scope Global -Force

function Show-TradingHelp {
    Write-Host ""
    Write-Host "Trading shortcuts (venv active, cwd=$TradingRoot):" -ForegroundColor Cyan
    Write-Host "  Start-TradingWeb              Web dashboard + Cloudflare tunnel"
    Write-Host "  Start-TradingPaper            Paper bot (port $TradingPaperPort)"
    Write-Host "  backtest                      Default trend backtest ($TradingBacktestStart .. $TradingBacktestEnd)"
    Write-Host "  ga -Fresh                     GA optimize (trend, $TradingGaCores cores)"
    Write-Host ""
    Write-Host "Edit defaults in scripts\trading_common.ps1" -ForegroundColor DarkGray
    Write-Host ""
}

# Open four Trading workstation PowerShell windows (Web, Paper, Backtest, GA).
#
# Usage (double-click or from any shell):
#   powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Trading\scripts\launch_trading.ps1"
#
# Optional: -WebOnly, -PaperOnly, -BacktestOnly, -GaOnly to open a subset.

param(
    [switch] $WebOnly,
    [switch] $PaperOnly,
    [switch] $BacktestOnly,
    [switch] $GaOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$all = @(
    @{ Name = "Web";      Script = "shell_web.ps1" },
    @{ Name = "Paper";    Script = "shell_paper.ps1" },
    @{ Name = "Backtest"; Script = "shell_backtest.ps1" },
    @{ Name = "GA";       Script = "shell_ga.ps1" }
)

$onlyFlags = @($WebOnly, $PaperOnly, $BacktestOnly, $GaOnly) | Where-Object { $_ }
if ($onlyFlags.Count -gt 1) {
    throw "Use at most one of -WebOnly, -PaperOnly, -BacktestOnly, -GaOnly"
}

if ($onlyFlags.Count -eq 1) {
    if ($WebOnly)      { $all = $all | Where-Object Name -eq "Web" }
    if ($PaperOnly)    { $all = $all | Where-Object Name -eq "Paper" }
    if ($BacktestOnly) { $all = $all | Where-Object Name -eq "Backtest" }
    if ($GaOnly)       { $all = $all | Where-Object Name -eq "GA" }
}

$psExe = if (Get-Command pwsh -ErrorAction SilentlyContinue) { "pwsh" } else { "powershell" }

foreach ($shell in $all) {
    $scriptPath = Join-Path $PSScriptRoot $shell.Script
    if (-not (Test-Path $scriptPath)) {
        throw "Missing shell script: $scriptPath"
    }
    Start-Process $psExe -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $scriptPath
    ) -WorkingDirectory $RepoRoot
    Start-Sleep -Milliseconds 300
}

Write-Host "Opened $($all.Count) Trading shell(s) from $RepoRoot" -ForegroundColor Green

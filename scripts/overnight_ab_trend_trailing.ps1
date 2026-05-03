# Overnight A/B: Trend GA baseline (no Trailing Delay minutes row) vs context (full prod CSV copy).
# Starts BOTH runs in parallel (two processes). Total CPU ~ 2 x Cores - leave headroom on the machine.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Trading\scripts\overnight_ab_trend_trailing.ps1"
#
# Optional: -RepoRoot "C:\Trading"  -Pop 100 -Gen 100 -Cores 6
#
# Environment: TRADING_GA_NO_BROWSER set in-script; optional TRADING_DATA_CSV for --data-csv.
# After both runs: copies genetic_results to results folder and runs _make_ab_summary.py.

param(
    [string] $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [int] $Pop = 100,
    [int] $Gen = 100,
    [int] $Cores = 6,
    [int] $Seed = 1337
)

$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$RunDir = Join-Path $RepoRoot "results\overnight_ab_trailing_$stamp"
New-Item -ItemType Directory -Path $RunDir -Force | Out-Null

$prod = Join-Path $RepoRoot "strategies\trend\parameters\trend_strategy_params.csv"
if (-not (Test-Path $prod)) { throw "Missing production params: $prod" }

$baselineCsv = Join-Path $RunDir "baseline_params.csv"
$contextCsv = Join-Path $RunDir "context_params.csv"
Copy-Item $prod $contextCsv -Force
(Get-Content $prod) | Where-Object { $_ -notmatch '^Trailing Delay \(minutes\),' } | Set-Content $baselineCsv -Encoding utf8

$tagBase = "ab_$stamp"
$tagBaseline = "${tagBase}_baseline"
$tagContext = "${tagBase}_context"

@"
overnight_ab_trailing
started_utc: $(Get-Date -Format 'o')
repo: $RepoRoot
parallel: two python processes
pop: $Pop  gen: $Gen  cores_each: $Cores  (approx_total_cores: $($Cores * 2))
seed_each: $Seed
baseline_params: $baselineCsv
context_params: $contextCsv
--run-tag baseline: $tagBaseline
--run-tag context: $tagContext
expected_genetic_results_glob_baseline: Trend\parameters\genetic_results_*-${tagBaseline}.csv
expected_genetic_results_glob_context: Trend\parameters\genetic_results_*-${tagContext}.csv
TRADING_GA_NO_BROWSER: 1 (no dashboard browser launches)
"@ | Set-Content (Join-Path $RunDir "RUN_META.txt") -Encoding utf8

$py = Join-Path $RepoRoot "venv\Scripts\python.exe"
$opt = Join-Path $RepoRoot "optimize.py"
if (-not (Test-Path $py)) { throw "Missing venv python: $py" }

$commonArgs = @(
    $opt,
    "--strategy", "trend",
    "--fresh",
    "--cores", "$Cores",
    "--gen", "$Gen",
    "--pop", "$Pop",
    "--seed", "$Seed"
)
if ($env:TRADING_DATA_CSV) {
    $commonArgs += @("--data-csv", $env:TRADING_DATA_CSV)
}

$env:TRADING_GA_NO_BROWSER = "1"

$baselineArgs = $commonArgs + @(
    "--params", $baselineCsv,
    "--run-tag", $tagBaseline
)
$contextArgs = $commonArgs + @(
    "--params", $contextCsv,
    "--run-tag", $tagContext
)

$logB = Join-Path $RunDir "baseline_stdout.log"
$logC = Join-Path $RunDir "context_stdout.log"
$errB = Join-Path $RunDir "baseline_stderr.log"
$errC = Join-Path $RunDir "context_stderr.log"

Write-Host "Starting baseline + context in parallel..."
Write-Host "  RunDir: $RunDir"
$p1 = Start-Process -FilePath $py -ArgumentList $baselineArgs -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $logB -RedirectStandardError $errB -PassThru
$p2 = Start-Process -FilePath $py -ArgumentList $contextArgs -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $logC -RedirectStandardError $errC -PassThru

Wait-Process -Id @($p1.Id, $p2.Id)
Write-Host "Both runs finished. Exit codes: baseline=$($p1.ExitCode) context=$($p2.ExitCode)"

$tp = Join-Path $RepoRoot "Trend\parameters"
$genB = Get-ChildItem -Path (Join-Path $tp "genetic_results_*-$tagBaseline.csv") | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$genC = Get-ChildItem -Path (Join-Path $tp "genetic_results_*-$tagContext.csv") | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $genB) { throw "Missing baseline genetic_results matching *-$tagBaseline.csv under $tp" }
if (-not $genC) { throw "Missing context genetic_results matching *-$tagContext.csv under $tp" }
$genB = $genB.FullName
$genC = $genC.FullName

Copy-Item $genB (Join-Path $RunDir "baseline_genetic_results.csv") -Force
Copy-Item $genC (Join-Path $RunDir "context_genetic_results.csv") -Force

$summarySrc = Join-Path $RepoRoot "results\ab_trailing_context_v3\_make_ab_summary.py"
if (Test-Path $summarySrc) {
    Copy-Item $summarySrc (Join-Path $RunDir "_make_ab_summary.py") -Force
    & $py (Join-Path $RunDir "_make_ab_summary.py")
} else {
    Write-Warning "Could not find _make_ab_summary.py template at $summarySrc - copy ab_summary manually."
}

Write-Host "Done. Artifacts under: $RunDir"

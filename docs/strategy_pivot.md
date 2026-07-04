# Strategy Pivot: Trend → Session VWAP

**Date:** 2026-07-04  
**Status:** Trend/Donchian **deprecated** for optimization and deploy. **Session VWAP mean reversion** is the active intraday research target.

## Why we abandoned Trend

Attribution and entry-edge analysis on Jul-03 OOS showed:

- Strategy **SS - RS ~ -$36k** — entry selection is anti-predictive vs random OOS entries.
- Direction beats opposite only **~38%** at the same timestamps.
- **70%** of exits via stop loss; maintenance/TP paths are profitable but rare.
- Donchian breakout at bar close **chases** extensions; industry trend systems enter at the **level**, not the spike close.

The Trend module remains in the repo for historical GA artifacts and parity replay. Do **not** deploy or run fresh GA on Trend without explicit experiment need.

## Research summary (2025–2026 intraday ES)

| Theme | Rationale |
|-------|-----------|
| **VWAP mean reversion** | Institutional anchor; fade extensions on range days |
| **Opening range regime** | Skip trend explosions (wide OR) and dead opens (tight OR) |
| **ADX cap** | Mean reversion when ADX low; avoid trend days |
| **Session time windows** | Trade after OR; flat before close |
| **Attribution gate** | `tools/analysis/strategy_attribution.py` before GA sign-off |

ORB-with-confirmation and order-flow filters are documented as future enhancements.

## New strategy: `session`

**Class:** `SessionVwapStrategy`  
**CLI / GA:** `--strategy session`  
**Params:** `strategies/session/parameters/session_strategy_params.csv`

### Logic (v1)

1. Compute **session VWAP** (RTH bars only, daily reset).
2. After **opening range** (default 30 min), fade extensions below/above VWAP when price **reverts** toward VWAP.
3. Regime: ADX ≤ cap, OR width in band, ATR in band.
4. Exit: stop (ATR), target VWAP, max hold, RTH/maintenance flat.

### Commands

```powershell
# GA (fresh)
$env:STRATEGY = 'session'
python optimize.py --strategy session --fresh

# Attribution (after OOS export)
python tools/analysis/strategy_attribution.py `
  --trades Session/output/genetic_trades_oos_YYYY-MM-DD-N.csv `
  --param-csv strategies/session/parameters/session_strategy_params.csv
```

## Preserved infrastructure

- GA engine, sim fidelity, paper/backtest parity, attribution, live IB execution — unchanged.
- Bollinger strategy — unchanged (separate product line).

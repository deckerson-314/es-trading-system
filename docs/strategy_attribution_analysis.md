# Strategy Attribution Analysis

Formal framework for diagnosing whether a strategy adds value beyond friction and random trading. Implements a **four-quadrant entry/exit decomposition** with **MFE/MAE excursion diagnostics**, aligned with common buy-side and vendor practice (performance attribution, trade-level MAE/MFE analysis).

## Purpose

Use this **before** trusting GA OOS rankings or deploying a parameter set. It answers:

1. Is net PnL worse than paying friction on every round-trip?
2. Is the strategy worse than a **random trading null** at the same frequency?
3. Does edge come from **entry selection**, **exit management**, or neither?
4. Are losses driven by **bad direction**, **bad timing**, or **stops cutting winners**?

## Industry alignment

| Concept | Our implementation | Common reference |
|--------|-------------------|------------------|
| Selection vs timing | SS/SR/RS/RR quadrants | Brinson-style attribution; entry/exit decomposition |
| MAE / MFE | Per-trade excursion on 1-min path | TradeVis, RustyBT `trade_analysis`, stop/TP optimization literature |
| Random benchmark | RR Monte Carlo null | Permutation / bootstrap null for skill vs luck |
| Capture ratio | Realized PnL / MFE | Measures exit efficiency |
| MAE-before-MFE | Adverse move before favorable | Flags entries that go wrong immediately |

**Not included (future):** factor regression (alpha/beta vs SPX), full exit-engine replay on random entries (path-dependent stops/TP), live vs backtest slippage attribution.

## Four quadrants

Entry and exit are varied in a 2×2 factorial:

```
                    │ Strategy Exit          │ Random Exit
────────────────────┼────────────────────────┼──────────────────────────
Strategy Entry (SS) │ Actual exported trades │ SR: same entry/direction;
                    │                        │     random hold → close
────────────────────┼────────────────────────┼──────────────────────────
Random Entry (RS)   │ RS*: random OOS entry  │ RR: MC random entry,
                    │     + hold-matched     │     direction, hold
                    │     exit @ close       │
```

| Code | Name | Entry | Exit |
|------|------|-------|------|
| **SS** | Strategy / Strategy | Exported `entry_time`, `direction`, `entry_price` | Exported `exit_time`, `exit_price` (stops, TP, maintenance) |
| **SR** | Strategy / Random | Same as SS | Hold sampled from empirical SS distribution; exit at 1-min **close** |
| **RS** | Random / Hold-matched | Random non-overlapping OOS bars; coin-flip direction | Hold = paired SS trade duration; exit at **close** |
| **RR** | Random / Random | Random OOS entries; coin-flip direction | Random hold (Gaussian around SS median); exit at **close** |

\* **RS** isolates **entry selection** (timing + direction jointly) while holding exit policy constant (time-only). True **Random Entry + Strategy Exit Rules** (stops/trails on random entries) requires running the exit engine forward from each random entry; that is documented as future work (`--replay-exits`).

### How to read the quadrants

| Comparison | Meaning |
|------------|---------|
| **SS − RR** | Total structural edge vs random trading null |
| **SS − SR** | Exit path effect (positive ⇒ strategy exits help vs time-only random hold) |
| **SS − RS** | Entry selection effect (positive ⇒ strategy entries beat random OOS entries) |
| **SR − RR** | Entry vs random, with both using time-only exits |
| **Direction diagnostics** | At SS timestamps: strategy vs **opposite** direction (pure direction signal) |

## Diagnostic statistics

Reported per quadrant (except RR, which is MC-aggregated):

| Statistic | Description |
|-----------|-------------|
| Net / gross PnL | USD after `transaction_cost` per leg |
| Win rate, profit factor, expectancy | Standard trade stats |
| **MFE** (pts) | Max favorable excursion from entry during hold |
| **MAE** (pts) | Max adverse excursion during hold |
| MFE/MAE ratio | >1 ⇒ favorable movement dominated (does not imply profit) |
| **Capture ratio** | Realized pts / MFE; low ⇒ exits leave money on table |
| **MAE-before-MFE %** | Adverse move touched before favorable (bad entries) |
| **MFE>5 & loss %** | Had room to win but closed red (exit problem) |
| Time to MFE / MAE | Minutes from entry to peak excursion |
| Friction floor | `−cost × n_trades` |
| MC band (SR, RR) | Median, 5th/95th pct, % positive runs |

**Fixed-horizon edges** (SS only): median close PnL at 30/60/120/240/480 minutes for strategy vs opposite direction — separates short-term mean reversion from longer drift.

## Usage

### CLI

```powershell
$env:STRATEGY = 'trend'
python tools/analysis/strategy_attribution.py `
  --trades Trend/output/genetic_trades_oos_2026-07-03-1.csv `
  --output results/attribution_jul03.md `
  --json results/attribution_jul03.json `
  --mc-runs 200
```

### Python API

```python
from core.trade_attribution import AttributionConfig, load_trades_csv, run_attribution
from tools.analysis.strategy_attribution import load_ga_context

ohlcv, oos_mask = load_ga_context("strategies/trend/parameters/trend_strategy_params.csv")
trades = load_trades_csv("Trend/output/genetic_trades_oos_2026-07-03-1.csv")
report = run_attribution(trades, ohlcv, oos_mask, cfg=AttributionConfig(mc_runs=200))
```

### Legacy scripts (wrappers)

| Script | Status |
|--------|--------|
| `tools/random_trades_baseline.py` | Wraps RR quadrant + friction floor |
| `tools/entry_edge_study.py` | Wraps direction diagnostics + horizon edges |

Prefer `tools/analysis/strategy_attribution.py` for full reports.

## Interpretation guide (Trend Jul-03 example)

Typical pattern when Donchian breakout + tight stops fail:

- **SS** deeply negative; **RR** near zero ⇒ strategy destroys value vs null.
- **Direction diagnostics**: strategy beats opposite <40% ⇒ **anti-predictive direction**.
- **SS − SR** large negative ⇒ **exit path** (stops) amplifies losses.
- **Fixed horizons**: negative edge at 30–120 min, slightly positive at 240+ min ⇒ short-term fade after breakout.
- **High MAE-before-MFE** on stop exits ⇒ entries go adverse immediately.

## Files

| Path | Role |
|------|------|
| `core/trade_attribution.py` | Library: quadrants, MFE/MAE, report builders |
| `tools/analysis/strategy_attribution.py` | CLI |
| `docs/strategy_attribution_analysis.md` | This document |
| `tests/test_trade_attribution.py` | Unit tests |

## Integration

See `web/system_architecture.md` — **Strategy Attribution** under the Verification / Diagnostics layer. Run attribution on every OOS trade export before paper deploy or GA sign-off.

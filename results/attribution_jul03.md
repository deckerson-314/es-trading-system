# Strategy Attribution Report

**Source:** `Trend\output\genetic_trades_oos_2026-07-03-1.csv`  
**Trades:** 639  
**MC runs:** 200

## Four-Quadrant Summary

| Quadrant | Label | Trades | Net PnL | Win% | PF | MFE med | MAE med | Capture |
|----------|-------|--------|---------|------|-----|---------|---------|---------|
| SS | Strategy Entry / Strategy Exit | 639 | $-36,757 | 37.9% | 0.88 | 12.7 | 13.2 | -0.39 |
| SR | Strategy Entry / Random Exit | 639 | $-13,988 | 49.9% | 0.96 | 12.4 | 12.4 | 0.11 |
| RS | Random Entry / Hold-Matched Exit | 5 | $-839 | 40.0% | 0.52 | 16.6 | 19.1 | -0.42 |
| RR | Random Entry / Random Exit | 639 | $-71 (MC med) | 48.5%+ | n/a | n/a | n/a | n/a |

## Full Report

```text
========================================================================
STRATEGY ATTRIBUTION REPORT (Four-Quadrant Entry/Exit Decomposition)
========================================================================
Source: Trend\output\genetic_trades_oos_2026-07-03-1.csv
Trades: 639
MC runs: 200  |  Cost/trade: $15

| Quadrant | Label | Trades | Net PnL | Win% | PF | MFE med | MAE med | Capture |
|----------|-------|--------|---------|------|-----|---------|---------|---------|
| SS | Strategy Entry / Strategy Exit | 639 | $-36,757 | 37.9% | 0.88 | 12.7 | 13.2 | -0.39 |
| SR | Strategy Entry / Random Exit | 639 | $-13,988 | 49.9% | 0.96 | 12.4 | 12.4 | 0.11 |
| RS | Random Entry / Hold-Matched Exit | 5 | $-839 | 40.0% | 0.52 | 16.6 | 19.1 | -0.42 |
| RR | Random Entry / Random Exit | 639 | $-71 (MC med) | 48.5%+ | n/a | n/a | n/a | n/a |

--- Quadrant detail ---

[SS] Strategy Entry / Strategy Exit
  Net PnL:        $-36,757
  Friction floor: $-9,585
  Win rate: 37.9%  PF: 0.88  Expectancy: $-58/trade
  MFE/MAE med: 12.73 / 13.21 pts  ratio 0.96
  Capture med: -0.39  MAE-before-MFE: 95.3%  MFE>5 & loss: 36.8%
  Time to MFE/MAE med: 89 / 68 min

[SR] Strategy Entry / Random Exit
  Net PnL:        $-13,988
  Friction floor: $-9,585
  MC median:      $-43,620  (p5 $-109,815, p95 $17,291, 10.0% positive)
  Win rate: 49.9%  PF: 0.96  Expectancy: $-22/trade
  MFE/MAE med: 12.35 / 12.45 pts  ratio 0.99
  Capture med: 0.11  MAE-before-MFE: 96.1%  MFE>5 & loss: 26.4%
  Time to MFE/MAE med: 83 / 75 min

[RS] Random Entry / Hold-Matched Exit
  Net PnL:        $-839
  Friction floor: $-75
  Win rate: 40.0%  PF: 0.52  Expectancy: $-168/trade
  MFE/MAE med: 16.64 / 19.08 pts  ratio 0.87
  Capture med: -0.42  MAE-before-MFE: 80.0%  MFE>5 & loss: 40.0%
  Time to MFE/MAE med: 26 / 45 min

[RR] Random Entry / Random Exit
  Net PnL:        $-71
  Friction floor: $-9,585
  MC median:      $-71  (p5 $-11,598, p95 $8,969, 48.5% positive)

--- Entry direction diagnostics (SS windows) ---
  Strategy beats opposite: 38.0%
  Median edge vs opposite: -11.02 pts/trade
  Opposite-direction net:  $17,587
  Coin-flip MC median:     $-4,936 (41.0% positive)

--- Fixed-horizon edge (strategy vs opposite, no exits) ---
   30 min: strat -1.00 pts  opp +1.00 pts  edge -2.00 pts
   60 min: strat -0.19 pts  opp +0.19 pts  edge -0.38 pts
  120 min: strat -0.72 pts  opp +0.72 pts  edge -1.44 pts
  240 min: strat +0.96 pts  opp -0.96 pts  edge +1.92 pts
  480 min: strat +0.78 pts  opp -0.78 pts  edge +1.56 pts

--- Interpretation ---
- SS loses more than friction-only: negative edge beyond costs.
- SS underperforms RR null: strategy logic destroys value vs random trading.
- Exit path effect (SS - SR): $-22,769  (positive => strategy exits help vs time-only random hold)
- Entry selection effect (SS - RS): $-35,917  (positive => strategy entries beat random OOS entries)
- Direction is anti-predictive vs opposite at same entry/exit times.

--- Notes ---
- SS = actual strategy entry and exit (exported trades).
- SR = strategy entry with random hold from empirical distribution; exit at bar close.
- RS = random OOS entry/direction with hold matched to paired strategy trade; exit at bar close.
- RR = Monte Carlo random entry, direction, and hold (matched count and hold distribution).
- Path-dependent strategy exits on random entries require exit-engine replay (future work).
```

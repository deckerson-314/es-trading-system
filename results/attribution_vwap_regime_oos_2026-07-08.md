# Strategy Attribution Report

**Source:** `Vwap_regime\output\genetic_trades_oos_2026-07-08-1.csv`  
**Trades:** 220  
**MC runs:** 200

## Four-Quadrant Summary

| Quadrant | Label | Trades | Net PnL | Win% | PF | MFE med | MAE med | Capture |
|----------|-------|--------|---------|------|-----|---------|---------|---------|
| SS | Strategy Entry / Strategy Exit | 220 | $-12,732 | 41.4% | 0.73 | 4.1 | 6.3 | 0.03 |
| SR | Strategy Entry / Random Exit | 220 | $-18,540 (MC med) | 41.4% | 0.69 | 4.9 | 7.4 | 0.00 |
| RS | Random Entry / Hold-Matched Exit | 220 | $-1,936 (MC med) | 49.1% | 1.20 | 4.7 | 4.1 | 0.09 |
| RR | Random Entry / Random Exit | 220 | $278 (MC med) | 53.0%+ | n/a | n/a | n/a | n/a |

## Full Report

```text
========================================================================
STRATEGY ATTRIBUTION REPORT (Four-Quadrant Entry/Exit Decomposition)
========================================================================
Source: Vwap_regime\output\genetic_trades_oos_2026-07-08-1.csv
Trades: 220
MC runs: 200  |  Cost/trade: $15

| Quadrant | Label | Trades | Net PnL | Win% | PF | MFE med | MAE med | Capture |
|----------|-------|--------|---------|------|-----|---------|---------|---------|
| SS | Strategy Entry / Strategy Exit | 220 | $-12,732 | 41.4% | 0.73 | 4.1 | 6.3 | 0.03 |
| SR | Strategy Entry / Random Exit | 220 | $-18,540 (MC med) | 41.4% | 0.69 | 4.9 | 7.4 | 0.00 |
| RS | Random Entry / Hold-Matched Exit | 220 | $-1,936 (MC med) | 49.1% | 1.20 | 4.7 | 4.1 | 0.09 |
| RR | Random Entry / Random Exit | 220 | $278 (MC med) | 53.0%+ | n/a | n/a | n/a | n/a |

--- Quadrant detail ---

[SS] Strategy Entry / Strategy Exit
  Net PnL:        $-12,732
  Friction floor: $-3,300
  Win rate: 41.4%  PF: 0.73  Expectancy: $-58/trade
  MFE/MAE med: 4.07 / 6.33 pts  ratio 0.64
  Capture med: 0.03  MAE-before-MFE: 88.2%  MFE>5 & loss: 10.0%
  Time to MFE/MAE med: 21 / 18 min

[SR] Strategy Entry / Random Exit
  Net PnL:        $-18,540
  Friction floor: $-3,300
  MC median:      $-18,540  (p5 $-54,066, p95 $12,126, 16.5% positive)
  Win rate: 41.4%  PF: 0.69  Expectancy: $-84/trade
  MFE/MAE med: 4.90 / 7.44 pts  ratio 0.66
  Capture med: 0.00  MAE-before-MFE: 87.3%  MFE>5 & loss: 14.5%
  Time to MFE/MAE med: 26 / 29 min

[RS] Random Entry / Hold-Matched Exit
  Net PnL:        $-1,936
  Friction floor: $-3,300
  MC median:      $-1,936  (p5 $-33,580, p95 $27,997, 41.0% positive)
  Win rate: 49.1%  PF: 1.20  Expectancy: $-9/trade
  MFE/MAE med: 4.74 / 4.05 pts  ratio 1.17
  Capture med: 0.09  MAE-before-MFE: 79.1%  MFE>5 & loss: 13.6%
  Time to MFE/MAE med: 30 / 21 min

[RR] Random Entry / Random Exit
  Net PnL:        $278
  Friction floor: $-3,300
  MC median:      $278  (p5 $-6,162, p95 $5,413, 53.0% positive)

--- Entry direction diagnostics (SS windows) ---
  Strategy beats opposite: 45.0%
  Median edge vs opposite: -2.16 pts/trade
  Opposite-direction net:  $6,132
  Coin-flip MC median:     $-3,972 (30.0% positive)

--- Fixed-horizon edge (strategy vs opposite, no exits) ---
   30 min: strat -0.72 pts  opp +0.72 pts  edge -1.44 pts
   60 min: strat -0.72 pts  opp +0.72 pts  edge -1.44 pts
  120 min: strat -0.73 pts  opp +0.73 pts  edge -1.46 pts
  240 min: strat -0.73 pts  opp +0.73 pts  edge -1.46 pts
  480 min: strat -1.25 pts  opp +1.25 pts  edge -2.50 pts

--- Interpretation ---
- SS loses more than friction-only: negative edge beyond costs.
- SS underperforms RR null: strategy logic destroys value vs random trading.
- Exit path effect (SS - SR): $5,808  (positive => strategy exits help vs time-only random hold)
- Entry selection effect (SS - RS): $-10,796  (positive => strategy entries beat random OOS entries)

--- Notes ---
- SS = actual strategy entry and exit (exported trades).
- SR = strategy entry with random hold from empirical distribution; exit at bar close.
- RS = random OOS entry/direction with hold matched to paired strategy trade; exit at bar close.
- RR = Monte Carlo random entry, direction, and hold (matched count and hold distribution).
- Path-dependent strategy exits on random entries require exit-engine replay (future work).
```

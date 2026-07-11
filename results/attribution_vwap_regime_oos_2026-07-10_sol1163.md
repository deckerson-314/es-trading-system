# Strategy Attribution Report

**Source:** `C:\Trading\Vwap_regime\output\genetic_trades_oos_2026-07-10-1_sol1163.csv`  
**Trades:** 15  
**MC runs:** 200

## Four-Quadrant Summary

| Quadrant | Label | Trades | Net PnL | Win% | PF | MFE med | MAE med | Capture |
|----------|-------|--------|---------|------|-----|---------|---------|---------|
| SS | Strategy Entry / Strategy Exit | 15 | $-992 | 33.3% | 0.41 | 1.3 | 3.8 | 0.33 |
| SR | Strategy Entry / Random Exit | 15 | $-597 (MC med) | 20.0% | 0.22 | 1.3 | 3.2 | -0.06 |
| RS | Random Entry / Hold-Matched Exit | 15 | $-356 (MC med) | 66.7% | 0.68 | 4.2 | 1.1 | 0.33 |
| RR | Random Entry / Random Exit | 15 | $-174 (MC med) | 46.0%+ | n/a | n/a | n/a | n/a |

## Full Report

```text
========================================================================
STRATEGY ATTRIBUTION REPORT (Four-Quadrant Entry/Exit Decomposition)
========================================================================
Source: C:\Trading\Vwap_regime\output\genetic_trades_oos_2026-07-10-1_sol1163.csv
Trades: 15
MC runs: 200  |  Cost/trade: $15

| Quadrant | Label | Trades | Net PnL | Win% | PF | MFE med | MAE med | Capture |
|----------|-------|--------|---------|------|-----|---------|---------|---------|
| SS | Strategy Entry / Strategy Exit | 15 | $-992 | 33.3% | 0.41 | 1.3 | 3.8 | 0.33 |
| SR | Strategy Entry / Random Exit | 15 | $-597 (MC med) | 20.0% | 0.22 | 1.3 | 3.2 | -0.06 |
| RS | Random Entry / Hold-Matched Exit | 15 | $-356 (MC med) | 66.7% | 0.68 | 4.2 | 1.1 | 0.33 |
| RR | Random Entry / Random Exit | 15 | $-174 (MC med) | 46.0%+ | n/a | n/a | n/a | n/a |

--- Quadrant detail ---

[SS] Strategy Entry / Strategy Exit
  Net PnL:        $-992
  Friction floor: $-225
  Win rate: 33.3%  PF: 0.41  Expectancy: $-66/trade
  MFE/MAE med: 1.29 / 3.80 pts  ratio 0.34
  Capture med: 0.33  MAE-before-MFE: 66.7%  MFE>5 & loss: 0.0%
  Time to MFE/MAE med: 11 / 9 min

[SR] Strategy Entry / Random Exit
  Net PnL:        $-597
  Friction floor: $-225
  MC median:      $-597  (p5 $-1,786, p95 $511, 15.5% positive)
  Win rate: 20.0%  PF: 0.22  Expectancy: $-40/trade
  MFE/MAE med: 1.29 / 3.25 pts  ratio 0.40
  Capture med: -0.06  MAE-before-MFE: 73.3%  MFE>5 & loss: 0.0%
  Time to MFE/MAE med: 15 / 9 min

[RS] Random Entry / Hold-Matched Exit
  Net PnL:        $-356
  Friction floor: $-225
  MC median:      $-356  (p5 $-2,417, p95 $1,584, 38.0% positive)
  Win rate: 66.7%  PF: 0.68  Expectancy: $-24/trade
  MFE/MAE med: 4.21 / 1.11 pts  ratio 3.79
  Capture med: 0.33  MAE-before-MFE: 93.3%  MFE>5 & loss: 6.7%
  Time to MFE/MAE med: 14 / 3 min

[RR] Random Entry / Random Exit
  Net PnL:        $-174
  Friction floor: $-225
  MC median:      $-174  (p5 $-3,314, p95 $2,710, 46.0% positive)

--- Entry direction diagnostics (SS windows) ---
  Strategy beats opposite: 53.3%
  Median edge vs opposite: +0.24 pts/trade
  Opposite-direction net:  $542
  Coin-flip MC median:     $-199 (35.0% positive)

--- Fixed-horizon edge (strategy vs opposite, no exits) ---
   30 min: strat +0.02 pts  opp -0.02 pts  edge +0.04 pts
   60 min: strat -0.72 pts  opp +0.72 pts  edge -1.44 pts
  120 min: strat -0.75 pts  opp +0.75 pts  edge -1.50 pts
  240 min: strat -6.61 pts  opp +6.61 pts  edge -13.22 pts
  480 min: strat -3.50 pts  opp +3.50 pts  edge -7.00 pts

--- Interpretation ---
- SS loses more than friction-only: negative edge beyond costs.
- SS underperforms RR null: strategy logic destroys value vs random trading.
- Exit path effect (SS - SR): $-395  (positive => strategy exits help vs time-only random hold)
- Entry selection effect (SS - RS): $-636  (positive => strategy entries beat random OOS entries)

--- Notes ---
- SS = actual strategy entry and exit (exported trades).
- SR = strategy entry with random hold from empirical distribution; exit at bar close.
- RS = random OOS entry/direction with hold matched to paired strategy trade; exit at bar close.
- RR = Monte Carlo random entry, direction, and hold (matched count and hold distribution).
- Path-dependent strategy exits on random entries require exit-engine replay (future work).
```

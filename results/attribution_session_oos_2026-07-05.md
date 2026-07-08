# Strategy Attribution Report

**Source:** `c:\Trading\Session\output\genetic_trades_oos_2026-07-05-1.csv`  
**Trades:** 225  
**MC runs:** 200

## Four-Quadrant Summary

| Quadrant | Label | Trades | Net PnL | Win% | PF | MFE med | MAE med | Capture |
|----------|-------|--------|---------|------|-----|---------|---------|---------|
| SS | Strategy Entry / Strategy Exit | 225 | $-18,453 | 54.2% | 0.35 | 2.1 | 3.8 | 0.50 |
| SR | Strategy Entry / Random Exit | 225 | $-15,628 (MC med) | 32.4% | 0.47 | 1.2 | 3.5 | 0.08 |
| RS | Random Entry / Hold-Matched Exit | 225 | $-4,847 (MC med) | 46.2% | 1.29 | 2.8 | 2.2 | 0.08 |
| RR | Random Entry / Random Exit | 225 | $21 (MC med) | 50.5%+ | n/a | n/a | n/a | n/a |

## Full Report

```text
========================================================================
STRATEGY ATTRIBUTION REPORT (Four-Quadrant Entry/Exit Decomposition)
========================================================================
Source: c:\Trading\Session\output\genetic_trades_oos_2026-07-05-1.csv
Trades: 225
MC runs: 200  |  Cost/trade: $15

| Quadrant | Label | Trades | Net PnL | Win% | PF | MFE med | MAE med | Capture |
|----------|-------|--------|---------|------|-----|---------|---------|---------|
| SS | Strategy Entry / Strategy Exit | 225 | $-18,453 | 54.2% | 0.35 | 2.1 | 3.8 | 0.50 |
| SR | Strategy Entry / Random Exit | 225 | $-15,628 (MC med) | 32.4% | 0.47 | 1.2 | 3.5 | 0.08 |
| RS | Random Entry / Hold-Matched Exit | 225 | $-4,847 (MC med) | 46.2% | 1.29 | 2.8 | 2.2 | 0.08 |
| RR | Random Entry / Random Exit | 225 | $21 (MC med) | 50.5%+ | n/a | n/a | n/a | n/a |

--- Quadrant detail ---

[SS] Strategy Entry / Strategy Exit
  Net PnL:        $-18,453
  Friction floor: $-3,375
  Win rate: 54.2%  PF: 0.35  Expectancy: $-82/trade
  MFE/MAE med: 2.06 / 3.77 pts  ratio 0.55
  Capture med: 0.50  MAE-before-MFE: 79.1%  MFE>5 & loss: 0.0%
  Time to MFE/MAE med: 10 / 8 min

[SR] Strategy Entry / Random Exit
  Net PnL:        $-15,628
  Friction floor: $-3,375
  MC median:      $-15,628  (p5 $-30,470, p95 $2,408, 9.0% positive)
  Win rate: 32.4%  PF: 0.47  Expectancy: $-69/trade
  MFE/MAE med: 1.24 / 3.52 pts  ratio 0.35
  Capture med: 0.08  MAE-before-MFE: 72.0%  MFE>5 & loss: 4.0%
  Time to MFE/MAE med: 7 / 8 min

[RS] Random Entry / Hold-Matched Exit
  Net PnL:        $-4,847
  Friction floor: $-3,375
  MC median:      $-4,847  (p5 $-21,345, p95 $16,300, 35.5% positive)
  Win rate: 46.2%  PF: 1.29  Expectancy: $-22/trade
  MFE/MAE med: 2.79 / 2.16 pts  ratio 1.29
  Capture med: 0.08  MAE-before-MFE: 79.6%  MFE>5 & loss: 4.4%
  Time to MFE/MAE med: 8 / 8 min

[RR] Random Entry / Random Exit
  Net PnL:        $21
  Friction floor: $-3,375
  MC median:      $21  (p5 $-2,826, p95 $3,398, 50.5% positive)

--- Entry direction diagnostics (SS windows) ---
  Strategy beats opposite: 54.7%
  Median edge vs opposite: +4.00 pts/trade
  Opposite-direction net:  $11,703
  Coin-flip MC median:     $-3,257 (20.0% positive)

--- Fixed-horizon edge (strategy vs opposite, no exits) ---
   30 min: strat -1.00 pts  opp +1.00 pts  edge -2.00 pts
   60 min: strat -0.72 pts  opp +0.72 pts  edge -1.44 pts
  120 min: strat -0.19 pts  opp +0.19 pts  edge -0.38 pts
  240 min: strat -0.45 pts  opp +0.45 pts  edge -0.90 pts
  480 min: strat +0.35 pts  opp -0.35 pts  edge +0.70 pts

--- Interpretation ---
- SS loses more than friction-only: negative edge beyond costs.
- SS underperforms RR null: strategy logic destroys value vs random trading.
- Exit path effect (SS - SR): $-2,825  (positive => strategy exits help vs time-only random hold)
- Entry selection effect (SS - RS): $-13,606  (positive => strategy entries beat random OOS entries)

--- Notes ---
- SS = actual strategy entry and exit (exported trades).
- SR = strategy entry with random hold from empirical distribution; exit at bar close.
- RS = random OOS entry/direction with hold matched to paired strategy trade; exit at bar close.
- RR = Monte Carlo random entry, direction, and hold (matched count and hold distribution).
- Path-dependent strategy exits on random entries require exit-engine replay (future work).
```

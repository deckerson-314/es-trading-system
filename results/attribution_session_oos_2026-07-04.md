# Strategy Attribution Report

**Source:** `c:\Trading\Session\output\genetic_trades_oos_2026-07-04-1.csv`  
**Trades:** 135  
**MC runs:** 200

## Four-Quadrant Summary

| Quadrant | Label | Trades | Net PnL | Win% | PF | MFE med | MAE med | Capture |
|----------|-------|--------|---------|------|-----|---------|---------|---------|
| SS | Strategy Entry / Strategy Exit | 135 | $-10,151 | 54.8% | 0.61 | 4.8 | 5.8 | 0.46 |
| SR | Strategy Entry / Random Exit | 135 | $292 (MC med) | 44.4% | 0.79 | 4.0 | 6.0 | 0.10 |
| RS | Random Entry / Hold-Matched Exit | 135 | $-1,678 (MC med) | 45.2% | 1.45 | 3.1 | 2.5 | 0.10 |
| RR | Random Entry / Random Exit | 135 | $21 (MC med) | 50.5%+ | n/a | n/a | n/a | n/a |

## Full Report

```text
========================================================================
STRATEGY ATTRIBUTION REPORT (Four-Quadrant Entry/Exit Decomposition)
========================================================================
Source: c:\Trading\Session\output\genetic_trades_oos_2026-07-04-1.csv
Trades: 135
MC runs: 200  |  Cost/trade: $15

| Quadrant | Label | Trades | Net PnL | Win% | PF | MFE med | MAE med | Capture |
|----------|-------|--------|---------|------|-----|---------|---------|---------|
| SS | Strategy Entry / Strategy Exit | 135 | $-10,151 | 54.8% | 0.61 | 4.8 | 5.8 | 0.46 |
| SR | Strategy Entry / Random Exit | 135 | $292 (MC med) | 44.4% | 0.79 | 4.0 | 6.0 | 0.10 |
| RS | Random Entry / Hold-Matched Exit | 135 | $-1,678 (MC med) | 45.2% | 1.45 | 3.1 | 2.5 | 0.10 |
| RR | Random Entry / Random Exit | 135 | $21 (MC med) | 50.5%+ | n/a | n/a | n/a | n/a |

--- Quadrant detail ---

[SS] Strategy Entry / Strategy Exit
  Net PnL:        $-10,151
  Friction floor: $-2,025
  Win rate: 54.8%  PF: 0.61  Expectancy: $-75/trade
  MFE/MAE med: 4.84 / 5.76 pts  ratio 0.84
  Capture med: 0.46  MAE-before-MFE: 88.9%  MFE>5 & loss: 0.0%
  Time to MFE/MAE med: 9 / 10 min

[SR] Strategy Entry / Random Exit
  Net PnL:        $292
  Friction floor: $-2,025
  MC median:      $292  (p5 $-21,440, p95 $24,615, 51.5% positive)
  Win rate: 44.4%  PF: 0.79  Expectancy: $2/trade
  MFE/MAE med: 4.05 / 6.04 pts  ratio 0.67
  Capture med: 0.10  MAE-before-MFE: 86.7%  MFE>5 & loss: 11.9%
  Time to MFE/MAE med: 7 / 8 min

[RS] Random Entry / Hold-Matched Exit
  Net PnL:        $-1,678
  Friction floor: $-2,025
  MC median:      $-1,678  (p5 $-20,070, p95 $17,313, 43.0% positive)
  Win rate: 45.2%  PF: 1.45  Expectancy: $-12/trade
  MFE/MAE med: 3.08 / 2.49 pts  ratio 1.24
  Capture med: 0.10  MAE-before-MFE: 80.7%  MFE>5 & loss: 6.7%
  Time to MFE/MAE med: 9 / 8 min

[RR] Random Entry / Random Exit
  Net PnL:        $21
  Friction floor: $-2,025
  MC median:      $21  (p5 $-2,826, p95 $3,398, 50.5% positive)

--- Entry direction diagnostics (SS windows) ---
  Strategy beats opposite: 56.3%
  Median edge vs opposite: +6.08 pts/trade
  Opposite-direction net:  $6,101
  Coin-flip MC median:     $-1,815 (33.5% positive)

--- Fixed-horizon edge (strategy vs opposite, no exits) ---
   30 min: strat -0.34 pts  opp +0.34 pts  edge -0.69 pts
   60 min: strat -0.74 pts  opp +0.74 pts  edge -1.49 pts
  120 min: strat +0.82 pts  opp -0.82 pts  edge +1.64 pts
  240 min: strat +0.79 pts  opp -0.79 pts  edge +1.57 pts
  480 min: strat -1.79 pts  opp +1.79 pts  edge -3.57 pts

--- Interpretation ---
- SS loses more than friction-only: negative edge beyond costs.
- SS underperforms RR null: strategy logic destroys value vs random trading.
- Exit path effect (SS - SR): $-10,443  (positive => strategy exits help vs time-only random hold)
- Entry selection effect (SS - RS): $-8,473  (positive => strategy entries beat random OOS entries)

--- Notes ---
- SS = actual strategy entry and exit (exported trades).
- SR = strategy entry with random hold from empirical distribution; exit at bar close.
- RS = random OOS entry/direction with hold matched to paired strategy trade; exit at bar close.
- RR = Monte Carlo random entry, direction, and hold (matched count and hold distribution).
- Path-dependent strategy exits on random entries require exit-engine replay (future work).
```

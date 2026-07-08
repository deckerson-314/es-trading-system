# Strategy Attribution Report

**Source:** `c:\Trading\Orb\output\genetic_trades_oos_2026-07-06-1.csv`  
**Trades:** 34  
**MC runs:** 200

## Four-Quadrant Summary

| Quadrant | Label | Trades | Net PnL | Win% | PF | MFE med | MAE med | Capture |
|----------|-------|--------|---------|------|-----|---------|---------|---------|
| SS | Strategy Entry / Strategy Exit | 34 | $-2,861 | 32.4% | 0.68 | 7.5 | 7.5 | -0.45 |
| SR | Strategy Entry / Random Exit | 34 | $-3,735 (MC med) | 47.1% | 0.29 | 6.8 | 7.4 | -0.05 |
| RS | Random Entry / Hold-Matched Exit | 34 | $442 (MC med) | 41.2% | 0.43 | 4.6 | 5.0 | -0.08 |
| RR | Random Entry / Random Exit | 34 | $-199 (MC med) | 45.5%+ | n/a | n/a | n/a | n/a |

## Full Report

```text
========================================================================
STRATEGY ATTRIBUTION REPORT (Four-Quadrant Entry/Exit Decomposition)
========================================================================
Source: c:\Trading\Orb\output\genetic_trades_oos_2026-07-06-1.csv
Trades: 34
MC runs: 200  |  Cost/trade: $15

| Quadrant | Label | Trades | Net PnL | Win% | PF | MFE med | MAE med | Capture |
|----------|-------|--------|---------|------|-----|---------|---------|---------|
| SS | Strategy Entry / Strategy Exit | 34 | $-2,861 | 32.4% | 0.68 | 7.5 | 7.5 | -0.45 |
| SR | Strategy Entry / Random Exit | 34 | $-3,735 (MC med) | 47.1% | 0.29 | 6.8 | 7.4 | -0.05 |
| RS | Random Entry / Hold-Matched Exit | 34 | $442 (MC med) | 41.2% | 0.43 | 4.6 | 5.0 | -0.08 |
| RR | Random Entry / Random Exit | 34 | $-199 (MC med) | 45.5%+ | n/a | n/a | n/a | n/a |

--- Quadrant detail ---

[SS] Strategy Entry / Strategy Exit
  Net PnL:        $-2,861
  Friction floor: $-510
  Win rate: 32.4%  PF: 0.68  Expectancy: $-84/trade
  MFE/MAE med: 7.49 / 7.55 pts  ratio 0.99
  Capture med: -0.45  MAE-before-MFE: 91.2%  MFE>5 & loss: 38.2%
  Time to MFE/MAE med: 15 / 20 min

[SR] Strategy Entry / Random Exit
  Net PnL:        $-3,735
  Friction floor: $-510
  MC median:      $-3,735  (p5 $-27,412, p95 $7,754, 26.0% positive)
  Win rate: 47.1%  PF: 0.29  Expectancy: $-110/trade
  MFE/MAE med: 6.81 / 7.45 pts  ratio 0.92
  Capture med: -0.05  MAE-before-MFE: 94.1%  MFE>5 & loss: 29.4%
  Time to MFE/MAE med: 19 / 24 min

[RS] Random Entry / Hold-Matched Exit
  Net PnL:        $442
  Friction floor: $-510
  MC median:      $442  (p5 $-11,752, p95 $10,906, 52.5% positive)
  Win rate: 41.2%  PF: 0.43  Expectancy: $13/trade
  MFE/MAE med: 4.65 / 5.02 pts  ratio 0.93
  Capture med: -0.08  MAE-before-MFE: 79.4%  MFE>5 & loss: 20.6%
  Time to MFE/MAE med: 17 / 14 min

[RR] Random Entry / Random Exit
  Net PnL:        $-199
  Friction floor: $-510
  MC median:      $-199  (p5 $-7,420, p95 $5,279, 45.5% positive)

--- Entry direction diagnostics (SS windows) ---
  Strategy beats opposite: 32.4%
  Median edge vs opposite: -7.12 pts/trade
  Opposite-direction net:  $1,841
  Coin-flip MC median:     $-247 (46.5% positive)

--- Fixed-horizon edge (strategy vs opposite, no exits) ---
   30 min: strat +1.51 pts  opp -1.51 pts  edge +3.02 pts
   60 min: strat -0.05 pts  opp +0.05 pts  edge -0.10 pts
  120 min: strat -2.25 pts  opp +2.25 pts  edge -4.50 pts
  240 min: strat -3.61 pts  opp +3.61 pts  edge -7.22 pts
  480 min: strat -5.52 pts  opp +5.52 pts  edge -11.04 pts

--- Interpretation ---
- SS loses more than friction-only: negative edge beyond costs.
- SS underperforms RR null: strategy logic destroys value vs random trading.
- Exit path effect (SS - SR): $874  (positive => strategy exits help vs time-only random hold)
- Entry selection effect (SS - RS): $-3,303  (positive => strategy entries beat random OOS entries)
- Direction is anti-predictive vs opposite at same entry/exit times.

--- Notes ---
- SS = actual strategy entry and exit (exported trades).
- SR = strategy entry with random hold from empirical distribution; exit at bar close.
- RS = random OOS entry/direction with hold matched to paired strategy trade; exit at bar close.
- RR = Monte Carlo random entry, direction, and hold (matched count and hold distribution).
- Path-dependent strategy exits on random entries require exit-engine replay (future work).
```

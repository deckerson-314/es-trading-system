# Strategy Attribution Report

**Source:** `C:\Trading\Vwap_regime\output\genetic_trades_oos_2026-07-10-1_sol0.csv`  
**Trades:** 60  
**MC runs:** 200

## Four-Quadrant Summary

| Quadrant | Label | Trades | Net PnL | Win% | PF | MFE med | MAE med | Capture |
|----------|-------|--------|---------|------|-----|---------|---------|---------|
| SS | Strategy Entry / Strategy Exit | 60 | $-3,349 | 46.7% | 0.71 | 3.9 | 4.5 | 0.23 |
| SR | Strategy Entry / Random Exit | 60 | $405 (MC med) | 40.0% | 1.12 | 5.5 | 5.4 | 0.01 |
| RS | Random Entry / Hold-Matched Exit | 60 | $-648 (MC med) | 50.0% | 1.57 | 3.6 | 2.7 | 0.17 |
| RR | Random Entry / Random Exit | 60 | $-163 (MC med) | 47.0%+ | n/a | n/a | n/a | n/a |

## Full Report

```text
========================================================================
STRATEGY ATTRIBUTION REPORT (Four-Quadrant Entry/Exit Decomposition)
========================================================================
Source: C:\Trading\Vwap_regime\output\genetic_trades_oos_2026-07-10-1_sol0.csv
Trades: 60
MC runs: 200  |  Cost/trade: $15

| Quadrant | Label | Trades | Net PnL | Win% | PF | MFE med | MAE med | Capture |
|----------|-------|--------|---------|------|-----|---------|---------|---------|
| SS | Strategy Entry / Strategy Exit | 60 | $-3,349 | 46.7% | 0.71 | 3.9 | 4.5 | 0.23 |
| SR | Strategy Entry / Random Exit | 60 | $405 (MC med) | 40.0% | 1.12 | 5.5 | 5.4 | 0.01 |
| RS | Random Entry / Hold-Matched Exit | 60 | $-648 (MC med) | 50.0% | 1.57 | 3.6 | 2.7 | 0.17 |
| RR | Random Entry / Random Exit | 60 | $-163 (MC med) | 47.0%+ | n/a | n/a | n/a | n/a |

--- Quadrant detail ---

[SS] Strategy Entry / Strategy Exit
  Net PnL:        $-3,349
  Friction floor: $-900
  Win rate: 46.7%  PF: 0.71  Expectancy: $-56/trade
  MFE/MAE med: 3.88 / 4.46 pts  ratio 0.87
  Capture med: 0.23  MAE-before-MFE: 81.7%  MFE>5 & loss: 6.7%
  Time to MFE/MAE med: 14 / 14 min

[SR] Strategy Entry / Random Exit
  Net PnL:        $405
  Friction floor: $-900
  MC median:      $405  (p5 $-8,927, p95 $13,931, 54.0% positive)
  Win rate: 40.0%  PF: 1.12  Expectancy: $7/trade
  MFE/MAE med: 5.55 / 5.40 pts  ratio 1.03
  Capture med: 0.01  MAE-before-MFE: 83.3%  MFE>5 & loss: 18.3%
  Time to MFE/MAE med: 14 / 16 min

[RS] Random Entry / Hold-Matched Exit
  Net PnL:        $-648
  Friction floor: $-900
  MC median:      $-648  (p5 $-11,541, p95 $10,763, 46.0% positive)
  Win rate: 50.0%  PF: 1.57  Expectancy: $-11/trade
  MFE/MAE med: 3.63 / 2.73 pts  ratio 1.33
  Capture med: 0.17  MAE-before-MFE: 71.7%  MFE>5 & loss: 11.7%
  Time to MFE/MAE med: 14 / 10 min

[RR] Random Entry / Random Exit
  Net PnL:        $-163
  Friction floor: $-900
  MC median:      $-163  (p5 $-3,043, p95 $2,703, 47.0% positive)

--- Entry direction diagnostics (SS windows) ---
  Strategy beats opposite: 50.0%
  Median edge vs opposite: -0.14 pts/trade
  Opposite-direction net:  $1,549
  Coin-flip MC median:     $-877 (37.0% positive)

--- Fixed-horizon edge (strategy vs opposite, no exits) ---
   30 min: strat -0.44 pts  opp +0.44 pts  edge -0.88 pts
   60 min: strat -0.30 pts  opp +0.30 pts  edge -0.60 pts
  120 min: strat -0.02 pts  opp +0.02 pts  edge -0.04 pts
  240 min: strat +0.52 pts  opp -0.52 pts  edge +1.04 pts
  480 min: strat -2.60 pts  opp +2.60 pts  edge -5.19 pts

--- Interpretation ---
- SS loses more than friction-only: negative edge beyond costs.
- SS underperforms RR null: strategy logic destroys value vs random trading.
- Exit path effect (SS - SR): $-3,754  (positive => strategy exits help vs time-only random hold)
- Entry selection effect (SS - RS): $-2,701  (positive => strategy entries beat random OOS entries)

--- Notes ---
- SS = actual strategy entry and exit (exported trades).
- SR = strategy entry with random hold from empirical distribution; exit at bar close.
- RS = random OOS entry/direction with hold matched to paired strategy trade; exit at bar close.
- RR = Monte Carlo random entry, direction, and hold (matched count and hold distribution).
- Path-dependent strategy exits on random entries require exit-engine replay (future work).
```

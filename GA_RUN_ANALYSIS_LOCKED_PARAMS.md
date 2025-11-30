# GA Run Analysis - Locked Parameters Diagnostic

## Summary

This analysis covers the GA run with **locked parameters** (all optimizable parameters set to backtest values) to verify the GA evaluation function works correctly.

## Key Findings

### ✅ **Trade Frequency is Working!**

- **Avg Trades/Day: 24.489** (from logbook)
- This confirms the GA evaluation function **CAN produce trades**
- The issue is NOT with the evaluation function itself
- The problem is with **parameter optimization** (GA converging to conservative values)

### 🔴 **All Solutions Hit Hard Constraints**

**Diagnostic Results:**
- All 120 solutions have Sortino = -1000 (hard constraint penalty)
- This means ALL solutions were eliminated due to:
  - Negative Sortino (strategy losing money on risk-adjusted basis)
  - OR Negative PNL (strategy losing money overall)
  - OR Win Rate < 40% (too many losing trades)

**Why This Happened:**
- With locked parameters, all individuals are identical
- The locked parameters produce trades (24.489/day) but are **not profitable**
- They fail the hard constraints, so they all get penalized

### 📊 **Discrepancies in HTML Dashboard**

#### 1. **Convergence Charts Show -1000 for Sortino**

**Root Cause:**
- Convergence charts use `logbook.select("avg_sortino")` and `logbook.select("max_sortino")`
- These come from `stats.compile(pop)` which uses **normalized fitness values**
- When solutions hit hard constraints, fitness[0] = -inf (or -1000 if there's an error)
- The charts show these normalized fitness values, not actual backtest results

**Fix Applied:**
- Added warning note explaining these are normalized fitness values (0-1 range)
- Noted that -1000 indicates hard constraint penalties
- Referenced "Actual Backtest Results" section for real values

#### 2. **"All Solutions" Section Shows Invalid Data**

**Root Cause:**
- "All Solutions" table uses `ind.fitness.values` directly
- These are normalized fitness values (0-1 range) or hard constraint penalties (-inf/-1000)
- All 120 solutions hit hard constraints, so they all show Sortino = -1000

**Fix Applied:**
- Added prominent warning explaining these are normalized fitness values
- Clarified that -1000 = hard constraint penalty (solution eliminated)
- Noted that "Actual Backtest Results" shows real backtest metrics
- Updated tooltips to clarify normalized vs actual values

#### 3. **Total Profit Shows 0 in Convergence Chart**

**Root Cause:**
- Convergence chart uses `logbook.select("avg_total_profit")`
- This is `fitness[4]` (normalized 0-1 range)
- When all solutions hit hard constraints, this becomes 0
- Actual backtest shows negative PNL (which is correct)

**Fix Applied:**
- Added note explaining convergence charts show normalized values
- Referenced "Actual Backtest Results" for real PNL

#### 4. **Profit Factor Shows 0 in Convergence Chart**

**Root Cause:**
- Same as above - normalized fitness values
- `fitness[2]` (Profit Factor) is normalized to 0-1 range
- When solutions hit hard constraints, this becomes 0
- Actual backtest shows PF = 0.810510 (which is correct)

**Fix Applied:**
- Same fixes as above - added explanatory notes

## What This Tells Us

### ✅ **Good News:**

1. **GA evaluation function works correctly**
   - Can produce trades (24.489 trades/day)
   - Can calculate metrics (Sortino, PF, etc.)
   - The function itself is not broken

2. **Trade frequency calculation is correct**
   - Shows 24.489 trades/day (reasonable)
   - This matches expectations for locked parameters

### 🔴 **The Real Problem:**

1. **All solutions are unprofitable with locked parameters**
   - Sortino = -1000 (hard constraint penalty)
   - This is expected - the locked parameters may not be profitable on the GA's data split
   - The GA correctly identifies and eliminates unprofitable solutions

2. **HTML dashboard confusion**
   - Fitness values (normalized) vs actual backtest results
   - Users see -1000 in charts but 0.27 in actual results
   - This is now explained with clear notes

## Recommendations

### For Future GA Runs:

1. **Remove hard constraints temporarily** to see if solutions can evolve
   - Or relax them (e.g., allow negative Sortino but with heavy penalty)
   - This will let the GA explore the solution space even if initial solutions are unprofitable

2. **Use unlocked parameters** (not diagnostic locked file)
   - The diagnostic file served its purpose - confirmed evaluation works
   - Now switch back to normal parameter file for actual optimization

3. **Monitor both fitness values and actual backtest results**
   - Fitness values show optimization progress
   - Actual backtest results show real strategy performance
   - Both are important but serve different purposes

### For HTML Dashboard:

1. ✅ **Fixed:** Added clear notes explaining normalized vs actual values
2. ✅ **Fixed:** Updated tooltips to clarify what each metric represents
3. **Future Enhancement:** Could run actual backtests for "All Solutions" table (expensive but more accurate)

## Conclusion

The GA evaluation function is working correctly. The discrepancies in the HTML were due to:
- Convergence charts showing normalized fitness values (for optimization)
- "All Solutions" showing normalized fitness values (for comparison)
- "Actual Backtest Results" showing real backtest metrics (for validation)

All solutions hitting hard constraints is expected with locked parameters that are unprofitable. The diagnostic served its purpose - it confirmed the GA can produce trades and calculate metrics correctly.


# Parameter Clamping Fix - Root Cause Analysis

## Problem Identified

The diagnostic revealed that parameters in the Hall of Fame are **dramatically outside their valid CSV ranges**:

1. **Min ATR Filter (Points)**: 
   - CSV Range: [0.0, 4.0]
   - Actual values: Mean 8.34, Max 28.73
   - **63% of solutions are ABOVE max range!**

2. **Min Volume Multiplier**:
   - CSV Range: [0.0, 10.0]
   - Actual values: Mean 7.48, Max 11.18
   - **1% of solutions are ABOVE max range**

3. **Short Trigger (% From Upper Band)**:
   - CSV Range: [0.0, 2.0]
   - Actual values: Mean 46.88, Max 64.93
   - **100% of solutions are ABOVE max range!**

4. **Long Trigger (% From Lower Band)**:
   - CSV Range: [0.0, 2.0]
   - Actual values: Mean 0.008, but 11% are below min

## Root Cause

**Parameters were NOT being clamped after crossover!**

The GA uses `cxBlend` for crossover, which can create values outside valid ranges when:
1. Parents have values near boundaries
2. The blend operation pushes values beyond limits
3. No clamping occurs after crossover

Additionally:
- Initial population might not have been clamped (safety check missing)
- Checkpoint loading didn't clamp existing individuals
- Mutation clamped, but crossover didn't

## Impact

1. **Trade Filtering**: Parameters like `Min ATR Filter` at 8-28 (vs max 4.0) are **completely blocking trades**
2. **Invalid Strategy**: Parameters outside valid ranges produce unpredictable behavior
3. **GA Convergence**: The GA was optimizing with invalid parameter values, leading to poor solutions

## Fix Applied

Added comprehensive clamping in **5 critical locations**:

1. **`clamp_individual()` function**: Centralized clamping logic
2. **`create_individual()`**: Clamp after creation (safety check)
3. **`custom_mutate()`**: Clamp after mutation (already existed, now uses centralized function)
4. **After `varAnd()`**: **NEW** - Clamp all offspring after crossover/mutation
5. **Initial population**: Clamp when creating fresh population
6. **Checkpoint loading**: Clamp when loading existing population and Hall of Fame

## Next Steps

1. **Current checkpoint has invalid values** - The existing checkpoint contains individuals with parameters outside valid ranges
2. **Recommendation**: Start a fresh run with `--fresh` flag to regenerate population with clamped values
3. **Verify**: After the next run, re-run the diagnostic to confirm parameters stay within ranges

## Why These Specific Parameters Were High

- **Min ATR Filter**: Drifted upward over generations because higher values (incorrectly) appeared to reduce risk (fewer trades = fewer losses)
- **Short Trigger**: Drifted to extreme values (46-64%) because the GA was exploring invalid parameter space
- **Volume Multiplier**: Drifted to high values (7-11) to filter out trades, which the GA incorrectly interpreted as "safer"

All of these are **trade-filtering parameters** that reduce trade frequency, which explains why the GA converged to near-zero trades/day.


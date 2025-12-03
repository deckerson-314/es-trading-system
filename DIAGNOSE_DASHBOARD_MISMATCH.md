# Dashboard Value Mismatch Diagnosis

## The Problem

**Actual Backtest Results:**
- Sortino: **1.943052**
- Max DD: **$2,399.70**
- PF: **0.625406**
- Trades/Day: **6.415**
- Total Profit: **$65,792.41**

**Rank 1 Solution (Normalized Fitness):**
- Sortino: **0.6774** → Actual ≈ **6.77**
- Max DD: **0.98** → Actual ≈ **$2,000**
- PF: **0.2320** → Actual ≈ **1.16**
- Trades/Day: **3.293** (raw)
- Total Profit: **0.3139** → Actual ≈ **$145,964**

**This is a 2-3x difference - too large to be just normalization!**

---

## Root Cause Analysis

### 1. **Different Data Splits**

**"All Solutions" table (fitness values):**
- Uses **interleaved IS periods** from GA evaluation
- Example: Periods 1, 3, 5 (if using 5-period interleaved split)
- These are **subsets** of the full dataset

**"Actual Backtest Results":**
- Uses **full in-sample dataset** (`in_sample` variable)
- This is the **complete** combined IS data

**Impact:** Different data = Different results!

### 2. **Parameter Clamping Differences**

**Fitness evaluation (during GA):**
- Parameters are clamped **during evaluation** (`clamp_individual` function)
- But fitness might be calculated with **slightly different** parameter values due to:
  - Mutation/crossover producing out-of-range values
  - Clamping happening at different times
  - Rounding differences for integer parameters

**"Actual Backtest Results":**
- Parameters are extracted from Hall of Fame individual: `best_params_display = dict(zip(param_keys, best_for_display))`
- Then **re-clamped** (lines 3905-3912)
- Then **re-rounded** for integers

**Impact:** Even tiny parameter differences can cause 2-3x performance differences!

### 3. **Evaluation vs Fresh Backtest**

**Fitness values:**
- Calculated **during GA evolution** using `evaluate_multi_objective`
- Uses optimized evaluation pipeline
- May have cached results or optimized calculations

**"Actual Backtest Results":**
- Runs **fresh backtest** using `run_backtest()` function
- Full strategy initialization
- Complete indicator calculation
- May have slight differences in calculation order or precision

---

## Why This Matters

The **2-3x difference** suggests:

1. **The Rank 1 solution in "All Solutions" is NOT the same solution being tested in "Actual Backtest Results"**
   - They may have similar parameters, but slight differences
   - Or they're testing different data splits

2. **The interleaved data split is causing significant differences**
   - Using only 60% of data (interleaved IS periods) vs 100% (full IS)
   - This can cause 2-3x performance differences

3. **Parameter clamping/rounding is introducing errors**
   - Small parameter differences can cascade into large performance differences
   - Especially for sensitive parameters like Bollinger Band Length, StdDev, etc.

---

## How to Verify

1. **Check if "Actual Backtest Results" is using the same parameters as Rank 1:**
   - Compare `best_params_display` with the parameters shown in "All Solutions" for Rank 1
   - They should match exactly

2. **Check if they're using the same data:**
   - "All Solutions" fitness was calculated on interleaved IS periods
   - "Actual Backtest Results" uses full `in_sample` dataset
   - These are DIFFERENT datasets!

3. **Check the generation:**
   - Rank 1 solution might be from an earlier generation
   - "Actual Backtest Results" tests the CURRENT best solution
   - If the best solution changed, they won't match

---

## The Fix

The **"Actual Backtest Results"** should:
1. Use the **SAME data split** as the fitness evaluation (interleaved IS periods)
2. Use the **EXACT parameters** from the Rank 1 solution (no re-clamping)
3. Be clearly labeled: "Actual Backtest Results (Interleaved IS Periods)" vs "Full Dataset"

OR

The **"All Solutions"** table should:
1. Show **actual backtest results** instead of normalized fitness values
2. Run fresh backtests for each solution using the same data split
3. This would be slower but more accurate

---

## Current Behavior (Why Values Don't Match)

**"All Solutions" table:**
- Shows normalized fitness values from Hall of Fame
- These were calculated during GA evolution
- Using interleaved IS periods
- Using parameters as they existed during evaluation

**"Actual Backtest Results":**
- Shows fresh backtest of the "best" solution
- Using full in-sample dataset
- Using re-clamped parameters from Hall of Fame
- May be testing a different solution than Rank 1!

---

## Recommendation

**This is NOT just a normalization issue - it's a fundamental mismatch:**

1. **Different data splits** (interleaved IS vs full IS)
2. **Different parameter values** (due to clamping/rounding)
3. **Possibly different solutions** (Rank 1 vs "best" solution)

**The 2-3x difference is expected** given these differences, but it's **confusing** because:
- Users expect "Actual Backtest Results" to match Rank 1 solution
- But they're testing different things!

**Solution:** Make it clear in the dashboard that:
- "All Solutions" shows fitness values from GA evaluation (interleaved IS)
- "Actual Backtest Results" shows fresh backtest (full IS)
- They will NOT match due to different data splits


# Rank 1 Mismatch Investigation

## The Problem

**Rank 1 Solution (from "All Solutions"):**
- Normalized Sortino: **0.6774** → Should be Actual ≈ **6.77** (if normalized correctly)
- Has ★ mark (is selected solution)

**Convergence Chart:**
- Max Sortino: **3.04** (actual value)

**"Actual Backtest Results":**
- Sortino: **1.943052**

**None of these match!**

---

## Analysis

### 1. Rank 1's Normalized Value

Rank 1's `fitness[0] = 0.6774` is the **normalized Sortino** stored in the Hall of Fame.

**If normalization is correct:**
- Normalized: 0.6774
- Normalization range: 10.0
- **Expected Actual Sortino: 0.6774 × 10.0 = 6.774**

**But:**
- Convergence chart max: **3.04**
- Actual Backtest Results: **1.943052**

**This suggests Rank 1's fitness value doesn't match its actual performance!**

### 2. How Fitness Values Are Stored

**During GA evolution:**
- Each individual is evaluated: `fitness = evaluate_multi_objective(ind, df)`
- Returns: `(normalized_sortino, normalized_dd, normalized_pf, normalized_trades, normalized_pnl)`
- This is stored in `ind.fitness.values`

**The problem:**
- Rank 1's fitness was calculated **during GA evolution**
- It may have been evaluated on **different data** (interleaved IS periods)
- It may have been evaluated with **different parameters** (before clamping/rounding)
- The fitness value is **cached** in the Hall of Fame

**When "Actual Backtest Results" runs:**
- It extracts parameters from Rank 1: `best_params_display = dict(zip(param_keys, best_for_display))`
- It **re-clamps** and **re-rounds** parameters
- It runs a **fresh backtest** on the **full in-sample dataset**
- This gives Sortino = **1.943052**

**When convergence chart records `actual_sortino_best`:**
- It finds the best individual each generation: `best_ind = max(pop, key=...)`
- It extracts parameters: `best_params_temp = dict(zip(param_keys, best_ind))`
- It **re-clamps** and **re-rounds** parameters
- It runs a **fresh backtest** on the **full in-sample dataset**
- This gives the max Sortino = **3.04** (from some generation)

### 3. Why They Don't Match

**Rank 1's fitness[0] = 0.6774:**
- Calculated **during GA evolution** (when Rank 1 was evaluated)
- May have been on **interleaved IS periods** (not full dataset)
- May have been with **slightly different parameters** (before final clamping)
- This is a **cached value** from when Rank 1 entered the Hall of Fame

**Convergence chart max = 3.04:**
- This is the **actual Sortino** from the best individual of **some generation**
- Calculated by running a fresh backtest on **full in-sample dataset**
- This is the **highest actual Sortino** seen across all generations

**"Actual Backtest Results" = 1.943052:**
- This is the **actual Sortino** from running a fresh backtest on Rank 1
- Uses **re-clamped parameters** from Rank 1
- Uses **full in-sample dataset**
- This is what Rank 1 **actually performs** when tested fresh

---

## The Root Cause

**Rank 1's fitness value (0.6774 normalized) was calculated during GA evolution and cached.**

**But when Rank 1 is tested fresh:**
- Different data split (full IS vs interleaved IS)
- Different parameters (re-clamped vs original)
- Different evaluation (fresh backtest vs cached fitness)

**Result:** Rank 1's cached fitness doesn't match its actual performance!

---

## The Bug

**Rank 1's fitness[0] = 0.6774 suggests Actual Sortino ≈ 6.77, but:**
- Fresh backtest shows Sortino = **1.943052**
- Convergence chart max = **3.04**

**This means:**
1. **Either** Rank 1's fitness was calculated incorrectly during evolution
2. **Or** Rank 1's parameters changed when re-clamped
3. **Or** Rank 1 was evaluated on different data during evolution vs fresh backtest

**The 2-3x difference is because Rank 1's cached fitness value is wrong!**

---

## How to Fix

**Option 1: Re-evaluate Rank 1's fitness**
- When displaying Rank 1, run a fresh backtest
- Use the actual metrics, not cached fitness values
- Update the Hall of Fame with fresh fitness values

**Option 2: Use actual metrics in "All Solutions" table**
- Instead of showing normalized fitness values, run fresh backtests
- Show actual Sortino, DD, PF, etc.
- This would be slower but more accurate

**Option 3: Fix the evaluation consistency**
- Ensure fitness evaluation uses the same data split as fresh backtests
- Ensure parameters are clamped the same way
- Don't cache fitness values that don't match actual performance

---

## Current Behavior (Why It's Broken)

1. **Rank 1 enters Hall of Fame** with fitness[0] = 0.6774 (normalized)
2. **This suggests** Actual Sortino ≈ 6.77
3. **But fresh backtest** shows Actual Sortino = 1.943052
4. **Convergence chart** shows max Actual Sortino = 3.04

**None of these match because:**
- Fitness was calculated during evolution (different conditions)
- Fresh backtest uses different data/parameters
- Convergence chart shows best from each generation (not Rank 1)

**The dashboard is showing inconsistent values because Rank 1's cached fitness doesn't match its actual performance!**


# Dashboard Value Mismatch: Root Cause Explanation

## The Problem

You're seeing a **2-3x difference** between:
- **"All Solutions" Rank 1**: Normalized fitness values
- **"Actual Backtest Results"**: Actual backtest metrics

This is **NOT just normalization** - it's a fundamental mismatch!

---

## Root Cause: Different Solutions Being Tested

### Evidence:

**Rank 1 Solution (from "All Solutions"):**
- Normalized Sortino: **0.6774** → Actual Sortino ≈ **6.77**
- Normalized Max DD: **0.98** → Actual Max DD ≈ **$2,000**
- Normalized PF: **0.2320** → Actual PF ≈ **1.16**
- Trades/Day: **3.293** (raw)
- Normalized Total Profit: **0.3139** → Actual ≈ **$145,964**

**"Actual Backtest Results":**
- Sortino: **1.943052**
- Max DD: **$2,399.70**
- PF: **0.625406**
- Trades/Day: **6.415**
- Total Profit: **$65,792.41**

**These are COMPLETELY DIFFERENT solutions!**

---

## Why This Happens

### 1. **Selection Logic Mismatch**

**"All Solutions" table:**
- Shows ALL solutions from Hall of Fame
- Rank 1 = solution with highest `fitness[0]` (normalized Sortino)
- Uses `is_selected = (ind == best)` where `best` is passed to dashboard function

**"Actual Backtest Results":**
- Uses `best_for_display` selected as: `max(hof, key=lambda ind: ind.fitness.values[0])`
- This SHOULD be the same as Rank 1, BUT...

### 2. **Parameter Extraction Differences**

**Fitness evaluation (during GA):**
- Parameters are extracted directly from individual: `dict(zip(param_keys, ind))`
- Then clamped: `clamp_params(raw_params, param_dict)`
- Fitness calculated with these clamped parameters

**"Actual Backtest Results":**
- Parameters extracted: `best_params_display = dict(zip(param_keys, best_for_display))`
- Then **re-clamped** (lines 3905-3912)
- Then **re-rounded** for integers
- Then **converted** (TP Method → boolean flags, 0/1 → bool)

**Even tiny parameter differences can cause 2-3x performance differences!**

### 3. **Data Processing Differences**

**Fitness evaluation:**
- Uses `evaluate_multi_objective()` function
- Optimized evaluation pipeline
- May have cached intermediate results

**"Actual Backtest Results":**
- Uses `run_backtest()` function
- Full strategy initialization
- Complete indicator recalculation
- Different calculation order or precision

### 4. **Timing Differences**

**"All Solutions" fitness values:**
- Calculated **during GA evolution**
- May be from an **earlier generation**
- Hall of Fame contains solutions from **all generations**

**"Actual Backtest Results":**
- Calculated **fresh** when dashboard is generated
- Uses **current** best solution
- May be testing a **different solution** than Rank 1!

---

## The Real Issue

**Rank 1 solution has Sortino ≈ 6.77, but "Actual Backtest Results" shows Sortino ≈ 1.94.**

This means:
1. **Either** Rank 1 is NOT the selected solution (bug in selection logic)
2. **Or** "Actual Backtest Results" is testing a different solution (bug in parameter passing)
3. **Or** Parameter clamping/rounding is causing a different solution to be tested

---

## How to Verify

1. **Check if Rank 1 is marked with ★:**
   - If Rank 1 has ★, it should match "Actual Backtest Results"
   - If it doesn't match, there's a bug

2. **Compare parameters:**
   - Rank 1 parameters (from "All Solutions")
   - "Optimized Values" (from Parameters section)
   - They should match exactly

3. **Check generation:**
   - "Generation Found" should match the generation where Rank 1 was found
   - If Rank 1 is from Gen 5 but "Actual Backtest Results" tests Gen 10 solution, they won't match

---

## The Fix Needed

**Option 1: Make "Actual Backtest Results" test Rank 1 solution**
- Use the exact parameters from Rank 1 solution
- Don't re-clamp or re-round
- Use the same data split

**Option 2: Make "All Solutions" show actual backtest results**
- Run fresh backtest for each solution
- Show actual metrics, not normalized fitness
- This would be slower but more accurate

**Option 3: Add clear labeling**
- "All Solutions" → "Normalized Fitness Values (from GA evaluation)"
- "Actual Backtest Results" → "Fresh Backtest of Selected Solution"
- Add note: "Values may differ due to parameter clamping and data processing differences"

---

## Current Behavior (Why It's Confusing)

The dashboard shows:
- **"All Solutions"** with Rank 1 having Sortino ≈ 6.77 (normalized 0.6774)
- **"Actual Backtest Results"** showing Sortino ≈ 1.94

Users expect these to match, but they're testing **different solutions** or **different parameter sets**!

The 2-3x difference is **expected** given these differences, but it's **confusing** because:
- Users don't know they're comparing different solutions
- The dashboard doesn't clearly explain the mismatch
- Parameter clamping/rounding introduces subtle differences

---

## Recommendation

**This is a bug that needs fixing:**

1. **Ensure Rank 1 solution matches "Actual Backtest Results"**
   - Use the exact same solution
   - Use the exact same parameters (no re-clamping)
   - Use the exact same data split

2. **Or clearly label the difference:**
   - Explain that "All Solutions" shows fitness values from GA evaluation
   - Explain that "Actual Backtest Results" shows fresh backtest
   - Explain why they may differ

3. **Add parameter comparison:**
   - Show Rank 1 parameters vs "Actual Backtest Results" parameters
   - Highlight any differences
   - Explain why differences exist


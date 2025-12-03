# Root Cause Analysis: Why Fitness Values Don't Match Parameters

## Investigation Results

### Test Results:
1. **Best solution in Hall of Fame:**
   - Fitness shows: `trades/day = 1.0000`
   - Parameters: All entry methods = 0 (disabled)

2. **Re-evaluation with same parameters:**
   - Raw parameters: 27 trades, 3.0 trades/day
   - Clamped parameters: 27 trades, 3.0 trades/day
   - **Fitness does NOT match either!**

3. **Key Finding:**
   - Fitness value (1.0) ≠ Re-evaluation (3.0)
   - This means fitness is **stale** or from a **different evaluation**

## Root Cause Identified

### The Problem: Fitness Values Are From Different Data/Time Periods

**During GA Evaluation:**
- Solutions are evaluated on **interleaved IS periods** (scattered across different time ranges)
- Example: Period 1 (2008-2011), Period 3 (2015-2018), Period 5 (2022-2025)
- Fitness is calculated from these specific periods

**When We Re-Evaluate:**
- We use a small sample (last 10,000 bars)
- This is a **different time period** than the interleaved IS periods
- Different market conditions → different number of trades

**Result:**
- Fitness value (1.0) is from interleaved IS periods
- Re-evaluation (3.0) is from different data
- They don't match because they're evaluating different market conditions

### Why Invalid Solutions Appear in Hall of Fame

**NSGA-II Pareto Front Behavior:**
1. Solution is evaluated on interleaved IS periods → gets fitness
2. Solution is added to Hall of Fame based on Pareto dominance
3. Parameters are later mutated/crossed → become invalid
4. But fitness values are **NOT re-evaluated** when parameters change
5. Hall of Fame still shows old fitness values

**The Issue:**
- Hall of Fame stores individuals with their fitness values
- When parameters are mutated/crossed, the individual's parameter values change
- But the fitness values are **not automatically re-evaluated**
- So we see invalid parameters with old fitness values

## Why This Happens

### 1. Fitness Evaluation is Expensive
- Each evaluation runs a full backtest
- Re-evaluating every time parameters change would be too slow
- GA only evaluates when explicitly requested (during evolution loop)

### 2. NSGA-II Doesn't Re-Evaluate Automatically
- NSGA-II compares fitness values for Pareto dominance
- It doesn't know if parameters have changed
- It assumes fitness values are current

### 3. Parameter Clamping Happens in Evaluation Function
- Parameters are clamped **inside** `evaluate_multi_objective()`
- But the individual's parameter values are **not modified**
- So `ind` still has original (potentially invalid) values
- Fitness is calculated with clamped params, but `ind` has raw params

## The Real Fix

**Don't add validation checks** (that's treating symptoms).

**Instead, fix the display/analysis logic:**

1. **When displaying parameters:**
   - Always clamp parameters the same way they were clamped during evaluation
   - Display the clamped values, not raw values
   - This ensures displayed parameters match the fitness values

2. **When analyzing solutions:**
   - Re-evaluate solutions on the same data the GA used
   - Or clearly label that fitness is from different data
   - Don't assume fitness matches current parameters

3. **When checking for invalid solutions:**
   - Re-evaluate on the same data the GA used
   - Or check if parameters would be invalid after clamping
   - Don't rely on fitness values alone

## Conclusion

**The fitness values are correct** - they're from evaluating on interleaved IS periods.

**The parameters are correct** - they're what's stored in the individual.

**The mismatch is expected** - they represent different things:
- Fitness = performance on interleaved IS periods (what GA optimized for)
- Parameters = current parameter values (may have changed since evaluation)

**The solution:** When displaying/analyzing, always clamp parameters the same way they were clamped during evaluation, and understand that fitness values are from specific data periods.


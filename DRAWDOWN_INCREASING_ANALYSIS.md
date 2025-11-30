# Significance of Drawdown Increasing Through Initial Generations

## What You're Observing

If **drawdown is steadily increasing** (getting worse) through the initial generations, this means:
- The **best solution's drawdown** (`min_dd`) is increasing
- Or the **average population drawdown** (`avg_dd`) is increasing
- Or both

**Remember**: Lower drawdown is better, so "increasing" means worse performance.

---

## Why This Happens: Multi-Objective Trade-offs

Your GA uses **4 objectives** with different weights:
1. **Sortino Ratio**: maximize (weight = 1.0)
2. **Max Drawdown**: minimize (weight = -1.0)
3. **Profit Factor**: maximize (weight = 1.0)
4. **Avg Trades/Day**: maximize (weight = 3.0) ⚠️ **HIGHEST WEIGHT**

### The Trade-off Problem

When drawdown increases, it's usually because the GA is **sacrificing risk control for other objectives**:

#### Scenario 1: Prioritizing Trade Frequency (Most Likely)
- **Weight 3.0 for avg_trades_day** is the highest
- The GA is finding solutions with **more trades** (good for objective 4)
- But more trades often means **more risk exposure**
- Solutions with:
  - Wider stops (allowing more trades to develop)
  - More aggressive entries (more opportunities)
  - Less conservative filters (more trade signals)
- **Result**: Higher drawdown, but more trades/day

#### Scenario 2: Prioritizing Sortino/Profit Factor
- Solutions with **higher Sortino or PF** might have:
  - Wider stops (fewer stop-outs, better win rate)
  - More aggressive position sizing
  - Riskier entry conditions
- **Result**: Better Sortino/PF, but higher drawdown

#### Scenario 3: Exploration Phase
- Early generations explore **diverse parameter combinations**
- Some combinations are inherently riskier
- The GA hasn't learned to balance objectives yet
- **Result**: Temporary increase in drawdown as it explores

---

## Is This Good or Bad?

### ✅ **NORMAL (Early Generations 1-15)**
If drawdown increases in the **first 10-15 generations**, this is likely **normal exploration**:
- The GA is trying different parameter combinations
- Some early solutions are riskier
- The GA will learn to balance objectives as it evolves
- **Action**: Monitor - should stabilize or decrease later

### ⚠️ **CONCERNING (Mid Generations 15-30)**
If drawdown continues increasing through **generations 15-30**, this suggests:
- The fitness function is **over-prioritizing other objectives**
- The GA is systematically choosing riskier solutions
- The weight balance may be wrong
- **Action**: Review fitness weights, add drawdown penalty

### 🔴 **PROBLEMATIC (Late Generations 30+)**
If drawdown is still increasing in **generations 30+**, this is a **serious issue**:
- The GA has converged to high-risk solutions
- The fitness function doesn't penalize drawdown enough
- Solutions may be overfitted or unrealistic
- **Action**: Fix fitness function, add drawdown constraints

---

## Current Fitness Function Analysis

Looking at your code:

```python
# Fitness weights: (1.0, -1.0, 1.0, 3.0)
# - Sortino: 1.0
# - Drawdown: -1.0 (minimize)
# - Profit Factor: 1.0
# - Avg Trades/Day: 3.0 (maximize) ⚠️
```

### The Problem

**Drawdown has equal weight to Sortino and PF (1.0), but trades/day has 3x the weight.**

This means:
- A solution with **3x more trades** can offset **3x worse drawdown**
- The GA will favor solutions with more trades, even if drawdown increases
- **This is by design** (you wanted to prevent convergence to zero trades)

### Drawdown Penalties

**Current penalties that affect drawdown:**
1. ✅ **Zero drawdown penalty** (line 505-507): Adds artificial $100 drawdown if zero
2. ❌ **No direct drawdown penalty** for high drawdown
3. ❌ **No maximum drawdown constraint**

**What's missing:**
- No penalty for drawdown > threshold (e.g., > $50K)
- No constraint on maximum acceptable drawdown
- Drawdown only has weight -1.0, which may be insufficient

---

## What This Means for Your Strategy

### If Drawdown is Increasing:

1. **The GA is finding more active strategies** (more trades)
   - This is good for the trades/day objective
   - But may increase risk exposure

2. **The GA is exploring riskier parameter combinations**
   - Wider stops
   - More aggressive entries
   - Less conservative filters

3. **The fitness function may be unbalanced**
   - Trades/day (weight 3.0) is dominating
   - Drawdown (weight -1.0) is being sacrificed

---

## Recommendations

### 1. **Monitor the Pattern** 📊
- **If drawdown increases then decreases**: ✅ Normal exploration
- **If drawdown increases then plateaus**: ⚠️ GA found a risk level
- **If drawdown keeps increasing**: 🔴 Problem - fix fitness function

### 2. **Add Drawdown Penalty** 🔧
Add a penalty for excessive drawdown:

```python
# In evaluate_multi_objective function, after line 535:
# Penalty for excessive drawdown
if max_dd > 50000:  # $50K threshold
    penalty = (max_dd - 50000) / 50000  # 0 to 1 scale
    sortino *= (1.0 - penalty * 0.5)  # Reduce by up to 50%
    pf *= (1.0 - penalty * 0.5)
```

### 3. **Increase Drawdown Weight** 🔧
Consider increasing drawdown weight from -1.0 to -2.0 or -3.0:

```python
# In main function, line ~1954:
creator.create("FitnessMulti", base.Fitness, 
               weights=(1.0, -2.0, 1.0, 3.0))  # Increased drawdown weight
```

**Trade-off**: This will reduce the emphasis on trades/day, but improve risk control.

### 4. **Add Maximum Drawdown Constraint** 🔧
Add a hard constraint on maximum acceptable drawdown:

```python
# In evaluate_multi_objective function:
MAX_ACCEPTABLE_DD = 100000  # $100K maximum

if max_dd > MAX_ACCEPTABLE_DD:
    # Heavy penalty - make solution non-viable
    sortino *= 0.1  # Reduce by 90%
    pf *= 0.1
```

### 5. **Review Parameter Ranges** 🎯
Check if parameter ranges allow excessive risk:
- **Initial Stop Loss**: Is max too wide? (allows large losses)
- **Trailing Stop**: Is max too wide? (allows large drawdowns)
- **Position Sizing**: Is max too large? (amplifies risk)

---

## Expected Behavior

### Healthy Pattern ✅
```
Generation 1-10:  Drawdown increases (exploration)
Generation 11-20: Drawdown stabilizes (learning)
Generation 21-30: Drawdown decreases (optimization)
Generation 31+:   Drawdown low and stable (converged)
```

### Concerning Pattern ⚠️
```
Generation 1-60:  Drawdown steadily increases
```
**Problem**: GA is systematically choosing riskier solutions
**Solution**: Add drawdown penalty or increase weight

### Ideal Pattern ✅
```
Generation 1-5:   Drawdown increases slightly (exploration)
Generation 6-60:  Drawdown decreases and stabilizes (optimization)
```
**This is what you want**: Initial exploration, then risk reduction

---

## Specific to Your Current Run

Based on your latest analysis:
- **IS Drawdown**: $52K
- **OOS Drawdown**: $112K (115% worse - overfitting)
- **Strategy is losing money**: -$28K IS, -$105K OOS

**If drawdown is increasing in your current run:**
1. This is **consistent with losing money** - higher drawdown = more losses
2. The GA may be finding solutions that:
   - Have more trades (good for objective)
   - But lose money on most trades (bad for PNL)
   - Result: Higher drawdown, more trades, negative PNL

**This suggests:**
- The fitness function needs a **PNL penalty** (not just Sortino/PF)
- Drawdown weight may need to be increased
- Parameter ranges may need to be tightened

---

## Action Items

1. **Check your convergence charts**:
   - Is drawdown increasing throughout all generations?
   - Or does it increase then decrease?
   - What generation does it peak at?

2. **Compare with other objectives**:
   - Is Sortino increasing while drawdown increases? (trade-off)
   - Is trades/day increasing while drawdown increases? (expected)
   - Is PF increasing while drawdown increases? (trade-off)

3. **Review fitness weights**:
   - Current: (1.0, -1.0, 1.0, 3.0)
   - Consider: (1.0, -2.0, 1.0, 3.0) or (1.0, -1.0, 1.0, 2.0)

4. **Add drawdown penalty** if it keeps increasing beyond generation 20

---

## Summary

**Drawdown increasing in early generations is NORMAL** if:
- It happens in generations 1-15
- It's part of exploration
- It stabilizes or decreases later

**Drawdown increasing is CONCERNING if:**
- It continues beyond generation 20
- It's steadily increasing throughout
- It's accompanied by negative PNL

**Root cause**: The high weight on trades/day (3.0) may be causing the GA to sacrifice drawdown for more trades. This is a **multi-objective trade-off** that needs to be balanced.

**Solution**: Monitor the pattern, and if it persists, add drawdown penalties or increase drawdown weight in the fitness function.


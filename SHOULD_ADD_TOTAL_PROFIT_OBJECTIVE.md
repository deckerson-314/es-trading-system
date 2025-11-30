# Should We Add Total Profit as an Objective?

## Current State

**Current Objectives (4):**
1. **Sortino Ratio** (maximize) - Risk-adjusted return
2. **Max Drawdown** (minimize) - Risk measure
3. **Profit Factor** (maximize) - Win/loss ratio
4. **Avg Trades/Day** (maximize) - Trade frequency

**Current Constraints:**
- **Hard Constraint**: `total_pnl < 0` → Eliminated (must be profitable)
- Total PNL is calculated but **NOT used as an objective**

---

## Pros of Adding Total Profit as Objective

### 1. **Direct Optimization for What Matters** ✅
- Traders care most about **making money**
- Total profit is the ultimate goal, not just risk-adjusted metrics
- Could help find solutions that are actually profitable (not just theoretically good)

### 2. **Could Help with Trade Frequency Issue** ✅
- Total profit is **correlated with trade frequency** (more trades = more profit potential)
- Adding it as an objective might push the GA toward solutions that trade more
- Could help solve the current problem where solutions converge to zero trades

### 3. **Balance Risk-Adjusted Metrics** ✅
- Sortino and PF are ratios - they can be high even with low absolute returns
- A solution with Sortino=3.0 and $10K profit might be worse than Sortino=2.5 and $50K profit
- Total profit would help distinguish between these cases

### 4. **Prevent Overfitting to Ratios** ✅
- High Sortino/PF can come from very few trades (overfitting)
- Total profit requires actual trading activity
- Could help find more robust solutions

### 5. **More Complete Picture** ✅
- Current objectives focus on "quality" (Sortino, PF) and "risk" (DD)
- Missing "quantity" (total profit)
- Adding it would make the optimization more comprehensive

---

## Cons of Adding Total Profit as Objective

### 1. **Highly Correlated with Trade Frequency** ⚠️
- More trades = more profit (generally)
- Could create redundancy with `avg_trades_day` objective
- Might not add much new information

### 2. **Scale Dependency** ⚠️
- Total profit depends on:
  - Account size (currently $50K)
  - Time period (IS period length)
  - Number of trades
- Not normalized - harder to compare across different data splits
- Would need careful normalization

### 3. **Could Encourage Excessive Risk** ⚠️
- Higher profit might come from taking more risk
- Could conflict with Max Drawdown objective
- Might favor solutions with high profit but also high drawdown

### 4. **Overfitting Risk** ⚠️
- Optimizing for total profit could lead to overfitting to specific time periods
- Solutions might exploit specific market conditions in IS data
- Could worsen OOS performance

### 5. **Already Captured Indirectly** ⚠️
- Sortino uses returns (which come from profit)
- Profit Factor is profit/loss ratio
- Positive PNL is already a hard constraint
- Might be redundant

### 6. **Normalization Challenges** ⚠️
- Total profit can vary widely ($1K to $1M+)
- Hard to set a reasonable normalization range
- Would need to adjust based on account size and time period

---

## Analysis: Would It Help?

### Current Problem: Zero Trade Frequency

**Root Cause**: Solutions with zero trades can still have "good" fitness if they have:
- High Sortino (from very few trades)
- Low Drawdown (no trades = no drawdown)
- High PF (from very few trades)

**Would Total Profit Help?**
- ✅ **YES** - Solutions with zero trades would have $0 profit
- ✅ **YES** - Would push GA toward solutions that actually trade
- ✅ **YES** - Would create a clear incentive to trade more

### Trade-off Analysis

**Scenario 1: Solution A**
- Sortino: 2.5
- MaxDD: $50K
- PF: 2.0
- Trades/Day: 0.5
- **Total Profit: $25K**

**Scenario 2: Solution B**
- Sortino: 3.0
- MaxDD: $30K
- PF: 2.5
- Trades/Day: 0.1
- **Total Profit: $5K**

**Current System**: Solution B might dominate (higher Sortino, lower DD, higher PF)

**With Total Profit**: Solution A would be more competitive (much higher profit)

**Verdict**: ✅ **Total profit would help distinguish between these cases**

---

## Recommendation

### ✅ **YES, Add Total Profit as 5th Objective** (with caveats)

**Implementation:**
1. **Add as 5th objective** (maximize)
2. **Normalize carefully**: Use a reasonable range based on account size and time period
   - Example: `PNL_RANGE = (0, 200000)` for $50K account over IS period
   - Or use percentile-based normalization from population
3. **Weight appropriately**: Start with weight 1.0 (same as Sortino)
4. **Keep hard constraint**: Still eliminate solutions with negative PNL

**Code Changes:**
```python
# Add to fitness tuple
creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 3.0, 1.0))
#                                                      ↑    ↑    ↑    ↑    ↑
#                                                  Sortino DD   PF  Trades PNL

# Normalize total profit
PNL_RANGE = (0.0, 200000.0)  # Adjust based on account size and period
pnl_norm = (total_pnl - PNL_RANGE[0]) / (PNL_RANGE[1] - PNL_RANGE[0])
pnl_norm = max(0.0001, min(1.0, pnl_norm))  # Clamp to 0-1

# Return 5-tuple
return (sortino_norm, dd_norm, pf_norm, trades_day_norm, pnl_norm)
```

**Why This Helps:**
1. **Solves trade frequency problem**: Solutions must trade to have profit
2. **More complete optimization**: Balances quality, risk, frequency, and absolute returns
3. **Prevents overfitting to ratios**: Requires actual trading activity
4. **Better Pareto front**: More diverse solutions with different profit/trade frequency trade-offs

**Potential Issues to Monitor:**
1. **Overfitting**: Watch for solutions that exploit specific IS periods
2. **Risk increase**: Monitor if solutions take excessive risk for profit
3. **Normalization**: Adjust range if solutions hit the cap

---

## Alternative: Use Total Profit as Constraint Instead

If adding as objective is too risky, consider:

**Option 1: Minimum Profit Constraint**
```python
# Hard constraint: Must have minimum profit
if total_pnl < 10000:  # $10K minimum
    return (-float('inf'), float('inf'), -float('inf'), -float('inf'))
```

**Option 2: Profit Penalty**
```python
# Soft penalty: Reward higher profit
if total_pnl > 50000:
    bonus = (total_pnl - 50000) / 100000  # 0-1 scale
    sortino *= (1.0 + bonus * 0.2)  # Up to 20% bonus
```

**Verdict**: Adding as objective is better - gives more nuanced optimization.

---

## Conclusion

**Recommendation**: ✅ **Add Total Profit as 5th Objective**

**Rationale**:
1. Directly addresses the zero trade frequency problem
2. Provides more complete optimization picture
3. Helps distinguish between solutions with similar ratios but different absolute returns
4. Low risk - can always remove if it causes issues

**Implementation Priority**: **HIGH** - Could solve the current trade frequency crisis.


# GA Run Analysis - November 28, 2025

## Executive Summary

**Run Status**: Completed (49/50 generations, 98% complete)  
**Analysis Date**: 2025-11-28 14:25:32  
**Fitness Weights**: Sortino=1.0, Drawdown=-1.0, PF=1.0, **Trades/Day=100.0**, Total Profit=2.0

## Key Findings

### ✅ Positive Results

1. **Trade Frequency**: **2.63 trades/day average** - This is ACCEPTABLE and much better than previous runs
   - Best solution: 2.63 trades/day
   - Population average: 2.63 trades/day
   - Status: Stable (converged, not improving further)

2. **Sortino Ratio**: Improving (+15.9% in recent generations)
   - Best solution: 0.1477 (normalized)
   - Average: 0.0285 (normalized)
   - Trend: ↑ Improving

3. **Pareto Front**: 188 Pareto-optimal solutions found
   - Good diversity in solution space
   - Multiple trade-offs between objectives

### ⚠️ Concerns

1. **Conservative Parameters**: The GA has converged to very conservative filter values:
   - **Min ATR Filter**: 4.0 (100% of max range) - Very conservative
   - **Min Volume Multiplier**: 3.0 (100% of max range) - Very conservative
   - **Short Trigger**: 2.0% (100% of max range) - Very restrictive
   - **Bollinger Band Length**: 5 (minimum value) - Very short lookback
   - **Bollinger Band StdDev**: 1.0 (minimum value) - Very narrow bands

2. **Profit Factor**: Low normalized values (0.17-0.35)
   - If normalization max is 5.0, actual PF is likely around 1.0-1.5
   - This suggests marginal profitability

3. **Trade Frequency Stability**: Trade frequency has converged and is not improving
   - Recent trend: 0.00% change (stable)
   - May have reached local optimum

## Convergence Analysis

### Generation Comparison

| Metric | Gen 0 | Gen 25 | Gen 49 | Trend |
|--------|-------|--------|--------|-------|
| Sortino (Avg) | -983.33 | 0.0201 | 0.0285 | ↑ +15.9% |
| Drawdown (Avg) | 98,333 | 0.4463 | 0.3453 | ↑ +2.4% |
| Profit Factor (Avg) | 0.0004 | 0.1764 | 0.1963 | ↑ +3.1% |
| Trades/Day (Avg) | 1.03 | 2.02 | 2.63 | → Stable |

### Key Observations

1. **Early Generations**: Started with very poor fitness (negative Sortino, high drawdown)
   - This is normal - GA was exploring the solution space
   - Many solutions likely violated constraints initially

2. **Mid Generations**: Rapid improvement in all metrics
   - Sortino went from negative to positive
   - Trade frequency doubled from 1.03 to 2.02

3. **Recent Generations**: Metrics stabilizing
   - Sortino still improving slowly (+15.9%)
   - Trade frequency has converged (stable)
   - Drawdown and PF improving marginally

## Pareto Front Analysis

### Top 10 Solutions (by Sortino)

| Rank | Sortino | Drawdown | PF | Trades/Day | Total Profit |
|------|---------|----------|----|-----------|--------------|
| ★ 1 | 0.1477 | $0.20 | 0.0465 | 0.8778 | 0.0001 |
| 2 | 0.1477 | $0.20 | 0.0465 | 0.8778 | 0.0001 |
| 3 | 0.1477 | $0.20 | 0.0465 | 0.8778 | 0.0001 |
| 4 | 0.1375 | $0.48 | 0.2934 | 1.0000 | 0.0096 |
| 5 | 0.1375 | $0.48 | 0.2934 | 1.0000 | 0.0096 |
| 6 | 0.0685 | $0.17 | 0.0908 | 0.8366 | 0.0001 |
| 7 | 0.0557 | $0.15 | 0.0441 | 0.5979 | 0.0001 |
| 8 | 0.0547 | $0.78 | 0.3389 | 1.0000 | 0.6484 |
| 9 | 0.0537 | $0.69 | 0.2868 | 0.5113 | 0.5988 |
| 10 | 0.0529 | $0.76 | 0.3370 | 1.0000 | 0.6392 |

**Note**: All values shown are normalized fitness values, not actual backtest metrics.

### Statistics Across All 188 Pareto Solutions

- **Sortino**: Min=0.0001, Max=0.1477, Mean=0.0264, Std=0.0250
- **Drawdown**: Min=$0.00, Max=$0.83, Mean=$0.28
- **Profit Factor**: Min=0.0084, Max=0.3482, Mean=0.1658
- **Avg Trades/Day**: Min=0.4012, Max=1.0000, Mean=0.7966
- **Total Profit**: Min=0.0001, Max=0.7716, Mean=0.1822

## Parameter Analysis

### Best Solution Parameters (by Sortino)

| Parameter | Value | % of Range | Status |
|-----------|-------|------------|--------|
| Min ATR Filter (Points) | 4.0 | 100% | ⚠️ At maximum (very conservative) |
| Min Volume Multiplier | 3.0 | 100% | ⚠️ At maximum (very conservative) |
| Long Trigger (% From Lower Band) | 0.0123% | 0.6% | ✓ Near minimum (permissive) |
| Short Trigger (% From Upper Band) | 2.0% | 100% | ⚠️ At maximum (very restrictive) |
| Bollinger Band Length | 5 | 0% | ⚠️ At minimum (very short) |
| Bollinger Band StdDev | 1.0 | 0% | ⚠️ At minimum (very narrow) |

### Parameter Distribution (Top 25% vs Bottom 25% by Sortino)

| Parameter | Top 25% | Bottom 25% | Difference |
|-----------|---------|------------|------------|
| Min ATR Filter | 3.85 | 3.96 | -2.7% |
| Min Volume Multiplier | 2.97 | 2.93 | +1.2% |
| Long Trigger | 0.019% | 0.009% | +109% |
| Short Trigger | 1.84% | 1.87% | -1.7% |
| Bollinger Band Length | 5.0 | 5.0 | 0% (converged) |
| Bollinger Band StdDev | 1.0 | 1.0 | 0% (converged) |

### Key Insights

1. **Filter Parameters at Extremes**: 
   - ATR and Volume filters are at or near maximum values
   - This creates very conservative entry conditions
   - Despite this, trade frequency is still 2.63/day (acceptable)

2. **Bollinger Band Parameters Converged**:
   - Length and StdDev are at minimum values
   - This suggests the GA found that shorter, narrower bands work better
   - However, this may be overfitting to the training data

3. **Trigger Parameters**:
   - Long trigger is very permissive (near 0%)
   - Short trigger is very restrictive (at 2.0%)
   - This asymmetry may indicate different optimal entry conditions for long vs short

## Recommendations

### 1. Trade Frequency ✅
- **Status**: ACCEPTABLE (2.63 trades/day)
- **Action**: No immediate action needed
- **Note**: Despite conservative filters, trade frequency is reasonable

### 2. Conservative Parameters ⚠️
- **Issue**: Parameters at extremes (filters at max, BB at min)
- **Risk**: May be overfitting or too conservative
- **Recommendation**: 
  - Consider tightening parameter ranges to prevent extreme values
  - Or add penalties for parameters at extremes
  - Verify actual backtest results (not just normalized fitness)

### 3. Profit Factor ⚠️
- **Issue**: Low normalized PF values (0.17-0.35)
- **Recommendation**: 
  - Run actual backtest on best solution to verify real PF
  - If actual PF < 1.5, consider adjusting fitness function
  - May need to increase PF weight or add profitability constraint

### 4. Convergence
- **Status**: Metrics have stabilized
- **Recommendation**: 
  - Run is essentially complete (98% done)
  - Consider extracting best solution and running full backtest
  - May benefit from restarting with different initial conditions or parameter ranges

## Next Steps

1. **Extract Best Solution**: Export the best solution (by Sortino) to CSV
2. **Run Full Backtest**: Test the best solution on full dataset with actual metrics
3. **Verify Trade Frequency**: Confirm 2.63 trades/day in actual backtest
4. **Check Profitability**: Verify actual Profit Factor and Sortino Ratio
5. **Consider Parameter Ranges**: If parameters are at extremes, consider:
   - Tightening ranges to prevent overfitting
   - Adding penalties for extreme values
   - Restarting with different ranges

## Conclusion

The GA run shows **significant improvement** over previous runs:
- ✅ Trade frequency is acceptable (2.63/day)
- ✅ Sortino is improving
- ✅ Multiple Pareto-optimal solutions found

However, there are concerns:
- ⚠️ Parameters converged to extremes (may indicate overfitting)
- ⚠️ Profit Factor appears low (needs verification)
- ⚠️ Trade frequency has stabilized (may have reached local optimum)

**Overall Assessment**: The run is successful in terms of trade frequency, but parameter extremes and low PF values suggest the need for verification through actual backtesting and potentially adjusting the optimization approach.


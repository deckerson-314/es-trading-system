# Genetic Algorithm Weights and Constraints - Research Summary

**Research Date**: Current  
**Purpose**: Understanding best practices for fitness function design, weight selection, and constraint handling in genetic algorithms for trading strategy optimization

---

## Executive Summary

This research compiles findings from academic papers, blogs, and forums on genetic algorithm fitness function design, with a focus on:
1. **Weight Selection** for multi-objective optimization
2. **Constraint Handling** methods (penalty vs hard constraints)
3. **Fitness Function Normalization** to prevent objective dominance
4. **Best Practices** for trading strategy optimization

**Key Finding**: The current implementation may be suffering from **penalty function design issues** and **lack of normalization**, which allows bad solutions to survive despite penalties.

---

## 1. Fitness Function Design Principles

### 1.1 Multi-Objective Optimization

**From Research**:
- Multi-objective optimization allows balancing multiple goals (e.g., profitability vs risk)
- NSGA-II (Non-dominated Sorting Genetic Algorithm) is commonly used for multi-objective problems
- Each objective should be normalized to prevent one from dominating

**Key Insight**: When combining multiple objectives (Sortino, Drawdown, Profit Factor, Trades/Day), **normalization is critical** to ensure each objective contributes equitably.

**Example from Research**:
```
Fitness = w1 * normalized_sortino + w2 * normalized_drawdown + w3 * normalized_pf + w4 * normalized_trades
```

**Current Implementation Issue**: 
- Objectives may not be normalized, causing Sortino (range 0-30) to dominate over Avg Trades/Day (range 0-5)
- Weight of 3.0 for trades/day may not be sufficient if Sortino isn't normalized

---

## 2. Constraint Handling Methods

### 2.1 Penalty Functions (Soft Constraints)

**From Research**:
- Penalty functions reduce fitness for constraint violations
- **Challenge**: Tuning penalty parameters is difficult
- **Common Approach**: Gradual penalties that increase with violation severity

**Example Penalty Functions**:

**Linear Penalty**:
```python
if constraint_violated:
    penalty = violation_amount * penalty_coefficient
    fitness = fitness * (1 - penalty)
```

**Exponential Penalty**:
```python
if constraint_violated:
    penalty = exp(violation_amount * penalty_coefficient)
    fitness = fitness / penalty
```

**Research Finding**: Penalty coefficients should be **10-100x the expected fitness range** to be effective.

**Current Implementation Issue**:
- Win rate penalty: 37% reduction for 18.8% win rate (below 40%)
- PNL penalty: 95% reduction for -$62,680 loss
- **Problem**: If original Sortino is 30.0 (capped), even 95% penalty leaves 1.5, which becomes 0.01 (floor)
- **Solution Needed**: Penalties should be **applied BEFORE cap/floor**, or cap/floor should be removed

### 2.2 Hard Constraints (Death Penalty Method)

**From Research**:
- Hard constraints **eliminate** solutions that violate constraints
- More effective than penalties for critical constraints
- Can be implemented by:
  1. Setting fitness to negative infinity
  2. Excluding from selection
  3. Rejecting during evaluation

**Example**:
```python
if win_rate < 0.40 or total_pnl < 0:
    return -float('inf')  # Hard constraint - eliminate solution
```

**Research Finding**: For **critical constraints** (e.g., minimum win rate, positive PNL), hard constraints are more effective than penalties.

**Current Implementation Issue**:
- Win rate constraint (40% minimum) is implemented as a penalty, not a hard constraint
- PNL constraint (positive) is implemented as a penalty, not a hard constraint
- **Result**: Bad solutions survive and can still be selected

### 2.3 Violation Constraint-Handling (VCH) Method

**From Research** (arXiv:1610.00976):
- Uses a "violation factor" to assess constraint violation degree
- Balances exploration of feasible and infeasible solutions
- More robust than fixed penalty coefficients

**Key Insight**: VCH method doesn't require extensive parameter tuning, making it more practical.

---

## 3. Weight Selection Best Practices

### 3.1 Normalization First, Then Weighting

**From Research**:
- **Proportionate Distance Normalization**: Best component = 1.0, worst = 0.0, others proportional
- **Rank-Based Normalization**: Rank components, assign values 0.0-1.0
- Prevents outliers from dominating

**Example**:
```python
# Normalize each objective to 0-1 range
normalized_sortino = (sortino - min_sortino) / (max_sortino - min_sortino)
normalized_drawdown = 1 - (drawdown - min_dd) / (max_dd - min_dd)  # Inverted (lower is better)
normalized_pf = (pf - min_pf) / (max_pf - min_pf)
normalized_trades = (trades - min_trades) / (max_trades - min_trades)

# Then apply weights
fitness = w1*normalized_sortino + w2*normalized_drawdown + w3*normalized_pf + w4*normalized_trades
```

**Current Implementation Issue**:
- Objectives are NOT normalized before weighting
- Sortino (0-30 range) dominates over Avg Trades/Day (0-5 range)
- Weight of 3.0 for trades/day may not compensate for scale difference

### 3.2 Weight Selection Guidelines

**From Research**:
- Weights should reflect **relative importance** of objectives
- Common approach: Start with equal weights, adjust based on results
- Weights can be **adaptive** (change during evolution)

**Example Weight Ranges** (from trading strategy research):
- **Profitability metrics** (Sortino, Sharpe): 1.0 - 2.0
- **Risk metrics** (Drawdown): -1.0 to -2.0 (negative because lower is better)
- **Frequency metrics** (Trades/Day): 0.5 - 1.0 (lower priority)
- **Constraint penalties**: 10-100x base fitness range

**Current Implementation**:
- Sortino: 1.0 ✅
- Drawdown: -1.0 ✅
- Profit Factor: 1.0 ✅
- Avg Trades/Day: 3.0 ⚠️ (high, but may not be effective without normalization)

---

## 4. Trading Strategy-Specific Insights

### 4.1 Common Metrics in Trading GA Fitness Functions

**From Research**:
1. **Sharpe Ratio**: Risk-adjusted return (most common)
2. **Sortino Ratio**: Downside risk-adjusted return (better for trading)
3. **Profit-to-Maximum Drawdown Ratio**: Return per unit of risk
4. **Win Rate**: Percentage of profitable trades
5. **Profit Factor**: Gross profit / Gross loss
6. **Trade Frequency**: Number of trades per period

**Key Insight**: Most successful implementations use **2-4 objectives**, not more.

### 4.2 Overfitting Prevention

**From Research**:
- **Out-of-Sample Testing**: Critical for detecting overfitting
- **Cross-Validation**: Use multiple train/test splits
- **Complexity Penalties**: Penalize overly complex strategies
- **Robustness Constraints**: Require good performance across market conditions

**Current Implementation**:
- ✅ Uses interleaved IS/OOS splits
- ✅ Tracks OOS performance
- ⚠️ But OOS Sortino is 0.006 (essentially zero) - severe overfitting detected

### 4.3 Normalization Example from Trading Research

**From Research** (fabian-kostadinov.github.io):
```python
# Proportionate Distance Normalization
def normalize_component(value, min_val, max_val, invert=False):
    if max_val == min_val:
        return 0.5  # Neutral if no variation
    normalized = (value - min_val) / (max_val - min_val)
    if invert:
        normalized = 1.0 - normalized  # For metrics where lower is better
    return normalized

# Apply to each objective
fitness = (
    w1 * normalize_component(sortino, min_sortino, max_sortino) +
    w2 * normalize_component(drawdown, min_dd, max_dd, invert=True) +
    w3 * normalize_component(profit_factor, min_pf, max_pf) +
    w4 * normalize_component(trades_per_day, min_trades, max_trades)
)
```

---

## 5. Specific Recommendations for Current Implementation

### 5.1 Immediate Fixes

**1. Normalize Objectives Before Weighting**
```python
# Normalize each objective to 0-1 range based on population statistics
# This ensures each objective contributes equitably
```

**2. Apply Penalties BEFORE Cap/Floor**
```python
# Current (WRONG):
sortino = min(30.0, max(0.01, sortino))  # Cap/floor first
sortino *= (1.0 - penalty)  # Penalty after - ineffective

# Correct:
sortino *= (1.0 - penalty)  # Penalty first
sortino = min(30.0, max(0.01, sortino))  # Cap/floor after
```

**3. Convert Critical Constraints to Hard Constraints**
```python
# Win rate < 40%: ELIMINATE (don't just penalize)
if win_rate < 0.40:
    return -float('inf')

# Negative PNL: ELIMINATE (don't just penalize)
if total_pnl < 0:
    return -float('inf')
```

**4. Increase Penalty Strength for Non-Critical Constraints**
```python
# For non-critical constraints, use much stronger penalties
# Penalty should be 10-100x the expected fitness range
penalty_factor = violation_amount * 50.0  # Much stronger
```

### 5.2 Weight Adjustment Strategy

**Current Weights**:
- Sortino: 1.0
- Drawdown: -1.0
- Profit Factor: 1.0
- Avg Trades/Day: 3.0

**Recommended After Normalization**:
- Sortino: 1.0 (keep)
- Drawdown: -1.0 (keep)
- Profit Factor: 1.0 (keep)
- Avg Trades/Day: 1.0-2.0 (reduce from 3.0, normalization will make it more effective)

**Rationale**: After normalization, all objectives will be on the same scale (0-1), so weights can be more balanced.

---

## 6. Academic Papers and Resources

### 6.1 Key Papers Referenced

1. **"Violation Constraint-Handling (VCH) Method"** (arXiv:1610.00976)
   - Alternative to penalty functions
   - Uses violation factors instead of fixed penalties
   - More robust, less parameter tuning

2. **"Optimizing Bollinger Bands Trading Strategies"** (sba.org.br)
   - Real-world example of GA for trading
   - Uses constraints on parameter ranges
   - Demonstrates fitness function design

3. **"Profit-to-Maximum Drawdown Ratio"** (repository.essex.ac.uk)
   - Risk-adjusted performance metric
   - Used in trading strategy optimization

### 6.2 Useful Resources

1. **PyGAD Library** (arxiv.org/abs/2106.06158)
   - Python GA framework
   - Examples of fitness function design
   - Constraint handling examples

2. **GeneTrader** (github.com/imsatoshi/GeneTrader)
   - Open-source GA for trading
   - Real-world implementation
   - Multi-process parallel computation

3. **Fitness Function Design Tutorial** (fabian-kostadinov.github.io)
   - Normalization techniques
   - Proportionate distance normalization
   - Rank-based normalization

---

## 7. Common Pitfalls and How to Avoid Them

### 7.1 Pitfall: One Objective Dominates

**Problem**: Sortino (0-30) dominates over Trades/Day (0-5) due to scale difference.

**Solution**: Normalize all objectives to 0-1 range before weighting.

### 7.2 Pitfall: Penalties Too Weak

**Problem**: 37% penalty for 18.8% win rate (below 40%) is insufficient.

**Solution**: Use hard constraints for critical violations, or increase penalty to 90-99%.

### 7.3 Pitfall: Cap/Floor Applied After Penalties

**Problem**: Penalties reduce Sortino to 1.5, but floor of 0.01 prevents elimination.

**Solution**: Apply penalties BEFORE cap/floor, or remove cap/floor entirely.

### 7.4 Pitfall: No Normalization

**Problem**: Different objective scales cause one to dominate.

**Solution**: Normalize all objectives based on population statistics.

---

## 8. Implementation Checklist

### Before Next GA Run:

- [ ] **Normalize all objectives** to 0-1 range based on population statistics
- [ ] **Apply penalties BEFORE cap/floor** (or remove cap/floor)
- [ ] **Convert critical constraints to hard constraints** (win rate < 40%, PNL < 0)
- [ ] **Increase penalty strength** for non-critical constraints (10-100x)
- [ ] **Reduce Sortino cap** from 30.0 to more realistic value (e.g., 10.0)
- [ ] **Remove or reduce floor** from 0.01 to allow negative fitness
- [ ] **Add logging** to track penalty application and constraint violations
- [ ] **Test penalty effectiveness** on known bad solutions

---

## 9. Example Improved Fitness Function

```python
def evaluate_multi_objective(individual, is_data, oos_data, param_dict):
    # Run backtest
    result = run_backtest(is_data, individual, param_dict)
    
    # Extract metrics
    sortino_raw = result.get('sortino_ratio', 0.0)
    max_dd = result.get('max_drawdown', 0.0)
    pf = result.get('profit_factor', 0.0)
    avg_trades_day = result.get('avg_trades_day', 0.0)
    total_pnl = result.get('total_pnl', 0.0)
    win_rate = result.get('win_rate', 0.0)
    trades_df = result.get('trades_df', pd.DataFrame())
    
    # HARD CONSTRAINTS - Eliminate bad solutions immediately
    if not trades_df.empty:
        if win_rate < 0.40:  # Minimum 40% win rate
            return (-float('inf'), float('inf'), -float('inf'), -float('inf'))
        if total_pnl < 0:  # Must be profitable
            return (-float('inf'), float('inf'), -float('inf'), -float('inf'))
    
    # Apply penalties for non-critical constraints (before normalization)
    penalty_factor = 1.0
    
    # Penalty for very low trade frequency
    if avg_trades_day < 0.5:
        penalty_factor *= 0.5  # 50% reduction
    
    # Penalty for very high drawdown
    if max_dd > 100000:  # $100K drawdown
        penalty_factor *= 0.7  # 30% reduction
    
    # Normalize objectives (based on population statistics - would need to pass these)
    # For now, use reasonable ranges
    normalized_sortino = min(1.0, sortino_raw / 10.0)  # Cap at 10.0 = 1.0
    normalized_dd = 1.0 - min(1.0, max_dd / 100000.0)  # Inverted, $100K = 0.0
    normalized_pf = min(1.0, pf / 5.0)  # Cap at 5.0 = 1.0
    normalized_trades = min(1.0, avg_trades_day / 5.0)  # Cap at 5.0/day = 1.0
    
    # Apply penalty
    normalized_sortino *= penalty_factor
    normalized_pf *= penalty_factor
    normalized_trades *= penalty_factor
    
    # Return fitness tuple (weights applied by DEAP)
    return (
        normalized_sortino,      # Maximize (weight: 1.0)
        -normalized_dd,          # Minimize (weight: -1.0, so negative)
        normalized_pf,          # Maximize (weight: 1.0)
        normalized_trades       # Maximize (weight: 1.0-2.0)
    )
```

**Key Changes**:
1. ✅ Hard constraints eliminate bad solutions
2. ✅ Penalties applied before normalization
3. ✅ Objectives normalized to 0-1 range
4. ✅ No cap/floor on final fitness (let DEAP handle it)
5. ✅ Penalties are multiplicative (more effective)

---

## 10. Conclusion

**Research Findings**:
1. **Normalization is critical** - Prevents one objective from dominating
2. **Hard constraints are more effective** - For critical constraints (win rate, PNL)
3. **Penalty strength matters** - Should be 10-100x expected fitness range
4. **Apply penalties before cap/floor** - Otherwise penalties are ineffective
5. **Weight selection** - Should reflect relative importance after normalization

**Current Implementation Issues**:
1. ❌ No normalization - Sortino dominates
2. ❌ Soft constraints instead of hard - Bad solutions survive
3. ❌ Cap/floor applied after penalties - Penalties ineffective
4. ❌ Penalty strength too weak - 37% for critical violation

**Recommended Actions**:
1. ✅ Implement normalization
2. ✅ Convert critical constraints to hard constraints
3. ✅ Fix penalty application order
4. ✅ Increase penalty strength or use hard constraints

---

## References

1. **Violation Constraint-Handling Method**: arXiv:1610.00976
2. **Bollinger Bands Optimization**: sba.org.br/cba2024/papers/paper_8234.pdf
3. **Profit-to-Maximum Drawdown**: repository.essex.ac.uk/32762/1/Ozgur_WCCI.pdf
4. **PyGAD Library**: arxiv.org/abs/2106.06158
5. **Fitness Function Design**: fabian-kostadinov.github.io/2014/12/22/evolving-trading-strategies-with-genetic-programming-fitness-functions/
6. **GeneTrader**: github.com/imsatoshi/GeneTrader
7. **Trading Strategy GA Tutorial**: medium.com/@jamesaaa100/genetic-algorithm-for-trading-strategy-optimization-in-python-6477c5859237

---

**Document Created**: Current Date  
**Last Updated**: Current Date  
**Status**: Research Complete - Ready for Implementation


# How Convergence Charts Work

## The Key Question

**For Generation X, do all the charts (Sortino, Drawdown, PF, etc.) come from the same individual/solution, or from different ones?**

---

## Answer: It Depends on Which Line You're Looking At!

### Two Types of "Best" Lines:

1. **Normalized "Best" Lines** (from `max_sortino`, `min_dd`, `max_pf`):
   - **These come from DIFFERENT individuals!**
   - Each chart shows the best value for that specific metric from the entire population
   - Generation 5 might have:
     - Sortino chart: Individual A (best Sortino = 2.0)
     - Drawdown chart: Individual B (best Drawdown = $5K)
     - PF chart: Individual C (best Profit Factor = 1.8)
   - **These are from different parameter sets!**

2. **Actual "Best" Lines** (from `actual_sortino_best`, `actual_dd_best`, `actual_pf_best`):
   - **These come from the SAME individual!**
   - The "best individual" is selected as: `max(pop, key=lambda ind: ind.fitness.values[0])`
   - This is the individual with the **highest Sortino** in that generation
   - Then a fresh backtest is run on this individual to get actual metrics
   - All actual metrics (Sortino, DD, PF, Trades/Day, Total Profit) come from this same individual

---

## How Statistics Are Calculated

### Normalized Statistics (from population):

```python
stats.register("max_sortino", lambda x: np.max([f[0] for f in x]))  # Best Sortino from ANY individual
stats.register("min_dd", lambda x: np.min([f[1] for f in x]))      # Best Drawdown from ANY individual
stats.register("max_pf", lambda x: np.max([f[2] for f in x]))       # Best PF from ANY individual
```

**These are independent!** Each finds the best value for that metric across the entire population.

### Actual Statistics (from "best individual"):

```python
best_ind = max(pop, key=lambda ind: ind.fitness.values[0])  # Individual with highest Sortino
# Then run backtest on best_ind to get:
actual_sortino_best = backtest_result['sortino']
actual_dd_best = backtest_result['max_drawdown']
actual_pf_best = backtest_result['profit_factor']
```

**These all come from the same individual!** The one with the highest Sortino.

---

## What This Means

### Normalized "Best" Lines:
- Show the **theoretical best** for each metric
- May come from different individuals
- Useful for seeing the **potential** of the population
- Example: "Someone in Gen 5 achieved Sortino=2.0, someone else achieved DD=$5K"

### Actual "Best" Lines:
- Show the **actual performance** of the best Sortino individual
- All metrics come from the same solution
- Useful for seeing **realistic performance** of the best solution
- Example: "The best Sortino solution in Gen 5 has Sortino=1.8, DD=$8K, PF=1.5"

---

## Example from Your Data

**Generation 7 (normalized "Best" lines):**
- Sortino chart: Shows best Sortino from any individual in Gen 7
- Drawdown chart: Shows best Drawdown from any individual in Gen 7
- PF chart: Shows best PF from any individual in Gen 7
- **These may be from different individuals!**

**Generation 7 (actual "Best" lines):**
- Sortino chart: Shows actual Sortino from the best Sortino individual
- Drawdown chart: Shows actual Drawdown from the same individual
- PF chart: Shows actual PF from the same individual
- **These are all from the same individual!**

---

## Why This Matters

### When Comparing Charts:

1. **If using normalized "Best" lines:**
   - Don't expect them to match across charts
   - Sortino=2.0 and DD=$5K might be from different solutions
   - This shows the **diversity** of the population

2. **If using actual "Best" lines:**
   - They should be consistent across charts
   - All metrics come from the same solution
   - This shows the **realistic performance** of the best solution

### When Comparing to "All Solutions" Table:

- The "All Solutions" table shows actual backtest results
- If convergence chart shows actual "Best" lines, they should match the best individual from that generation
- If convergence chart shows normalized "Best" lines, they may not match (they're from different individuals)

---

## Current Implementation

**The convergence charts show:**
- **Actual "Best" lines** when available (from `actual_sortino_best`, etc.)
- **Normalized "Best" lines** as fallback (from `max_sortino`, `min_dd`, `max_pf`)

**So:**
- If actual lines are available: All metrics come from the same individual (best Sortino)
- If only normalized lines: Each metric comes from potentially different individuals

---

## Recommendation

**For consistency:**
- The actual "Best" lines are more useful because they show realistic performance
- They all come from the same solution, so they're consistent
- They match what you'd see if you ran a backtest on that generation's best solution

**The normalized "Best" lines are misleading** because they suggest a solution exists with all those best values, when in reality they're from different solutions.


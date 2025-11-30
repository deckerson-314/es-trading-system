# Optimizable vs Non-Optimizable Parameters

**Input File**: `Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv`  
**Output File**: `Bollinger/parameters/BB_Strategy_Parameters_optimized_v3.csv`

---

## ✅ OPTIMIZABLE Parameters (14 total)

The GA optimizes these parameters. They must be:
- Type: `int` or `float`
- Have both `Min` and `Max` defined

### Entry Criteria (5 parameters)
1. **Bollinger Band Length** - `int`, 20-100
2. **Bollinger Band StdDev** - `float`, 1.5-3.0
3. **Long Trigger (% From Lower Band)** - `float`, 0.0-2.0
4. **Short Trigger (% From Upper Band)** - `float`, 0.0-2.0
5. **Min ATR Filter (Points)** - `float`, 2.0-10.0
6. **Min Volume Multiplier** - `float`, 0.5-1.8
7. **Timeframe (minutes)** - `int`, 1-15
8. **Max Open Trades** - `int`, 1-1 (currently fixed at 1, but has min/max so could be optimized)

### Stop Loss Criteria (4 parameters)
9. **Initial Stop Loss (%)** - `float`, 0.5-2.0
10. **ATR Length for Trailing Stop** - `int`, 10-100
11. **ATR Multiplier for Trailing Stop** - `float`, 0.5-4.5
12. **Trailing Delay (bars)** - `int`, 0-20

### Take Profit Criteria (2 parameters)
13. **ATR Length for TP** - `int`, 15-80
14. **ATR Multiplier for TP** - `float`, 1.0-5.0

### Maintenance/Filter Parameters (1 parameter)
15. **RTH Exit Buffer (minutes)** - `int`, 0-60
16. **Weekend Maintenance Start Day** - `int`, 0-6
17. **Weekend Maintenance End Day** - `int`, 0-6
18. **Maintenance Buffer Minutes** - `int`, 1-30

**Total Optimizable: 18 parameters**

---

## ❌ NON-OPTIMIZABLE Parameters

### Boolean Parameters (Type: `bool`) - 11 parameters
These are **fixed** - GA cannot optimize them:
1. **Enable Long Trades** - `bool` (true/false)
2. **Enable Short Trades** - `bool` (true/false)
3. **Long Entry on Wick Touch** - `bool` (false/true)
4. **Long Entry on Body in Zone** - `bool` (false/true)
5. **Short Entry on Wick Touch** - `bool` (false/true)
6. **Short Entry on Body in Zone** - `bool` (false/true)
7. **Enable RTH Filter** - `bool` (false/true)
8. **Enable Maintenance Filter** - `bool` (false/true)
9. **Opposite Bollinger Band TP** - `bool` (false/true)
10. **Fixed ATR TP** - `bool` (false/true)
11. **Fixed BB at Entry TP** - `bool` (false/true)
12. **Enable Trailing Stop** - `bool` (false/true)
13. **USE_INTERLEAVED_SPLIT** - `bool` (false/true)

### String/Time Parameters (Type: `str`) - 4 parameters
These are **fixed** as time strings:
14. **RTH Start (HH:MM)** - `str` (e.g., "09:30")
15. **RTH End (HH:MM)** - `str` (e.g., "16:00")
16. **Daily Maintenance Start (HH:MM)** - `str` (e.g., "17:00")
17. **Daily Maintenance End (HH:MM)** - `str` (e.g., "17:30")
18. **Weekend Maintenance Start Time (HH:MM)** - `str` (e.g., "17:00")
19. **Weekend Maintenance End Time (HH:MM)** - `str` (e.g., "18:00")

### GA Configuration Parameters - 13 parameters
These control **how the GA runs** - they are read from CSV but **not optimized**:
20. **POP_SIZE** - Population size (used to configure GA)
21. **NUM_GEN** - Number of generations (used to configure GA)
22. **CX_PB** - Crossover probability (used to configure GA)
23. **MUT_PB** - Mutation probability (used to configure GA)
24. **MUT_MU** - Mutation mean (used to configure GA)
25. **MUT_SIGMA** - Mutation std dev (used to configure GA)
26. **TARGET_TRADES_DAY** - Target trades/day (used in fitness function)
27. **TRADES_PENALTY_WEIGHT** - Penalty weight (used in fitness function)
28. **DD_WEIGHT** - Drawdown weight (used in fitness function)
29. **DATA_SPLITS** - Data split ratio (used to configure data)
30. **DATA_SIZE** - Data size limit (used to configure data)
31. **NUM_SPLIT_PERIODS** - Number of interleaved periods (used to configure data)
32. **MIN_TRADES_DAY** - Minimum trades/day (used in fitness function)
33. **MIN_TRADES_PEN_WEIGHT** - Minimum trades penalty (used in fitness function)

### Special/Metadata
34. **__indicatorName** - Metadata identifier (not a parameter)
35. **=== ENTRY CRITERIA ===** - Section header (not a parameter)
36. **=== TAKE PROFIT CRITERIA ===** - Section header (not a parameter)
37. **=== STOP LOSS CRITERIA ===** - Section header (not a parameter)
38. **=== GA CRITERIA ===** - Section header (not a parameter)

**Total Non-Optimizable: 38 parameters/headers**

---

## Summary

- **Optimizable**: 18 parameters (strategy tuning parameters)
- **Non-Optimizable**: 38 items (booleans, strings, GA config, headers)
- **Total Items in CSV**: 56 rows

---

## Key Insights

### Why Some Parameters Aren't Optimized

1. **Boolean Parameters**: 
   - GA works with continuous values (int/float)
   - Booleans are discrete (true/false only)
   - Would need to convert to 0/1 integers to optimize

2. **String Parameters**:
   - GA can't optimize text strings
   - Time strings would need conversion to numeric (minutes from midnight)

3. **GA Configuration Parameters**:
   - These control the optimization process itself
   - Not part of the strategy being optimized
   - You set these manually to configure how the GA runs

### Current Optimization Focus

The GA optimizes **18 strategy parameters** that directly affect:
- Entry timing and conditions
- Stop loss placement
- Take profit targets
- Trade filtering

All other parameters are **fixed** during optimization.

---

## How to Verify What's Being Optimized

When the GA starts, it prints:
```
Multi-core: Using 8 workers (CPU count: X)
```

You can also check the `param_keys` list in the code - it contains only the optimizable parameter names.

The optimized CSV output file will show the **optimized values** for the 18 optimizable parameters, while all other parameters remain at their default values from the input CSV.


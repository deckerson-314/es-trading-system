# Parameter Optimization Status

## How GA Determines Optimizable Parameters

The GA only optimizes parameters that meet **ALL** of these criteria:
1. **Type is 'int' or 'float'** (not 'bool' or 'str')
2. **Has both Min and Max defined** (not None/empty)
3. **Is not a GA configuration parameter** (POP_SIZE, NUM_GEN, etc. are used but not optimized)

**Code Reference** (line 1668-1669):
```python
PARAM_RANGES = {n: (d['min'], d['max']) for n, d in param_dict.items()
                if d['type'] in ('int', 'float') and d['min'] is not None and d['max'] is not None}
```

---

## ✅ OPTIMIZABLE Parameters (Strategy Parameters)

These are optimized by the GA:

### Entry Criteria
1. **Bollinger Band Length** (int, 10-100)
2. **Bollinger Band StdDev** (float, 1.0-3.0)
3. **Long Trigger (% From Lower Band)** (float, 0.0-2.0)
4. **Short Trigger (% From Upper Band)** (float, 0.0-2.0)
5. **Min ATR Filter (Points)** (float, 0-10)
6. **Min Volume Multiplier** (float, 1.0-1.5)
7. **Timeframe (minutes)** (int, 1-8)
8. **Max Open Trades** (int, 1-5)

### Stop Loss Criteria
9. **Initial Stop Loss (%)** (float, 0.1-2.0)
10. **ATR Length for Trailing Stop** (int, 10-100)
11. **ATR Multiplier for Trailing Stop** (float, 1.0-5.0)
12. **Trailing Delay (bars)** (int, 0-20)

### Take Profit Criteria
13. **ATR Length for TP** (int, 10-80)
14. **ATR Multiplier for TP** (float, 1.0-6.0)

**Total: 14 optimizable strategy parameters**

---

## ❌ NON-OPTIMIZABLE Parameters

These are **NOT** optimized by the GA (used as fixed values):

### Boolean Flags (Type: bool)
1. **Enable Long Trades** - Fixed at `true` or `false`
2. **Enable Short Trades** - Fixed at `true` or `false`
3. **Long Entry on Wick Touch** - Fixed at `false` or `true`
4. **Long Entry on Body in Zone** - Fixed at `true` or `false`
5. **Short Entry on Wick Touch** - Fixed at `false` or `true`
6. **Short Entry on Body in Zone** - Fixed at `true` or `false`
7. **Enable Trailing Stop** - Fixed at `true` or `false`
8. **Opposite Bollinger Band TP** - Fixed at `false` or `true`
9. **Fixed ATR TP** - Fixed at `false` or `true`
10. **Fixed BB at Entry TP** - Fixed at `true` or `false`
11. **Enable RTH Filter** - Fixed at `true` or `false`

### String/Time Parameters (Type: str)
12. **RTH Start (HH:MM)** - Fixed time string (e.g., "09:30")
13. **RTH End (HH:MM)** - Fixed time string (e.g., "16:00")

### GA Configuration Parameters (Used by GA, not optimized)
14. **POP_SIZE** - Population size (used to configure GA)
15. **NUM_GEN** - Number of generations (used to configure GA)
16. **CX_PB** - Crossover probability (used to configure GA)
17. **MUT_PB** - Mutation probability (used to configure GA)
18. **MUT_MU** - Mutation mean (used to configure GA)
19. **MUT_SIGMA** - Mutation std dev (used to configure GA)
20. **TARGET_TRADES_DAY** - Target trades/day (used in fitness function)
21. **TRADES_PENALTY_WEIGHT** - Penalty weight (used in fitness function)
22. **DD_WEIGHT** - Drawdown weight (used in fitness function)
23. **DATA_SPLITS** - Data split ratio (used to configure data)
24. **DATA_SIZE** - Data size limit (used to configure data)
25. **MIN_TRADES_DAY** - Minimum trades/day (used in fitness function)
26. **MIN_TRADES_PEN_WEIGHT** - Minimum trades penalty (used in fitness function)

### Special/Metadata
27. **__indicatorName** - Metadata identifier (not a parameter)

**Total: 27 non-optimizable parameters**

---

## Summary

- **Optimizable**: 14 parameters (all strategy tuning parameters)
- **Non-Optimizable**: 27 parameters (booleans, strings, GA config, metadata)
- **Total Parameters**: 41 parameters in CSV

---

## Important Notes

### Boolean Parameters
- Boolean parameters are **fixed** - the GA cannot optimize them
- If you want to test different boolean combinations, you need to:
  1. Manually change the Value in CSV
  2. Run separate GA runs with different boolean settings
  3. Or modify the code to treat booleans as optimizable (0/1 integers)

### GA Configuration Parameters
- These control **how the GA runs**, not the strategy
- They are read from CSV and used to configure the GA
- They are **not optimized** - you set them manually

### String Parameters (RTH Times)
- Currently fixed as strings
- Could be made optimizable by converting to numeric (minutes from midnight)
- Currently not optimized

---

## How to Make More Parameters Optimizable

If you want to optimize boolean parameters, you could:
1. Change them to int type (0 = false, 1 = true)
2. Set Min=0, Max=1
3. Update the strategy code to convert 0/1 to bool

Example:
```csv
Enable Long Trades,1,0,1,int,Allow long entries (0=false, 1=true)
```

Then in strategy code:
```python
self.enable_long = bool(get_param_value(self.params_dict, 'Enable Long Trades', 1))
```


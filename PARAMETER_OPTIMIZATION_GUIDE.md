# Parameter Optimization Guide

## Overview

The GA now supports:
1. **Boolean parameters as optimizable** (convert to 0/1 int in CSV)
2. **Fixed values** (set min=max in CSV)
3. **Mutually exclusive TP methods** (use single integer parameter)

---

## 1. Optimizing Boolean Parameters

To make a boolean parameter optimizable, change it from `bool` to `int` with `Min=0, Max=1`:

### Before (Fixed):
```csv
Long Entry on Wick Touch,false,false,true,bool,Enter if low touches lower band
```

### After (Optimizable):
```csv
Long Entry on Wick Touch,0,0,1,int,Enter if low touches lower band (0=false, 1=true)
```

The code will automatically convert 0/1 back to False/True when running the strategy.

**Parameters you might want to optimize:**
- `Long Entry on Wick Touch` → `0,0,1,int`
- `Short Entry on Wick Touch` → `0,0,1,int`
- `Enable RTH Filter` → `0,0,1,int`
- `Enable Trailing Stop` → `0,0,1,int`
- `Enable Maintenance Filter` → `0,0,1,int`

---

## 2. Fixed Values (min==max)

To fix a parameter at a specific value, set `Min` and `Max` to the same value:

### Example: Fix Max Open Trades at 1
```csv
Max Open Trades,1,1,1,int,Maximum concurrent positions (fixed at 1)
```

The GA will **not optimize** parameters where min==max - they remain fixed at that value.

---

## 3. Mutually Exclusive TP Methods

The three TP methods are mutually exclusive:
- `Fixed BB at Entry TP` (current default)
- `Fixed ATR TP`
- `Opposite Bollinger Band TP`

### Solution: Use a Single Integer Parameter

**Add this new parameter to your CSV:**
```csv
TP Method,0,0,2,int,Take profit method (0=Fixed BB at Entry, 1=Fixed ATR, 2=Opposite BB)
```

**Then set the three boolean TP parameters to fixed (min=max):**
```csv
Fixed BB at Entry TP,true,true,true,bool,FIXED: Upper BB at entry (long) - controlled by TP Method
Fixed ATR TP,false,false,false,bool,FIXED: Entry ± (ATR × Multiplier) - controlled by TP Method
Opposite Bollinger Band TP,false,false,false,bool,DYNAMIC: Exit at current opposite BB - controlled by TP Method
```

The code will automatically:
- Read the `TP Method` value (0, 1, or 2)
- Set the corresponding boolean to `True` and others to `False`
- Pass the correct boolean values to the strategy

---

## Example CSV Updates

### Entry Criteria Section
```csv
Long Entry on Wick Touch,0,0,1,int,Enter if low touches lower band (0=false, 1=true) - OPTIMIZABLE
Short Entry on Wick Touch,0,0,1,int,Enter if high touches upper band (0=false, 1=true) - OPTIMIZABLE
Enable RTH Filter,1,0,1,int,Restrict entries to RTH only (0=false, 1=true) - OPTIMIZABLE
```

### Take Profit Criteria Section
```csv
TP Method,0,0,2,int,Take profit method (0=Fixed BB at Entry, 1=Fixed ATR, 2=Opposite BB) - OPTIMIZABLE
Fixed BB at Entry TP,true,true,true,bool,FIXED: Controlled by TP Method
Fixed ATR TP,false,false,false,bool,FIXED: Controlled by TP Method
Opposite Bollinger Band TP,false,false,false,bool,FIXED: Controlled by TP Method
```

### Stop Loss Criteria Section
```csv
Enable Trailing Stop,1,0,1,int,Use ATR trailing stop (0=false, 1=true) - OPTIMIZABLE
```

---

## How It Works

1. **Boolean Optimization**: When a parameter is `int` type with `Min=0, Max=1`, the GA optimizes it as 0 or 1, then the code converts it to `False` or `True` before passing to the strategy.

2. **Fixed Values**: Parameters with `min==max` are excluded from `PARAM_RANGES`, so they're never optimized and always use the fixed value.

3. **TP Method**: The `TP Method` integer (0-2) is optimized by the GA, then converted to the three boolean flags before running the strategy.

---

## Notes

- **Backward Compatibility**: Existing boolean parameters that remain `bool` type will continue to work as fixed values.
- **Strategy Code**: No changes needed to strategy code - the conversion happens in `BB_Genetic_v3.py` before calling `run_backtest()`.
- **Dashboard Display**: The HTML dashboard will show:
  - Optimizable booleans: Range "0 - 1", Optimized Value "0" or "1"
  - Fixed parameters: Range "*Fixed*", Value shows the fixed value
  - TP Method: Range "0 - 2", Optimized Value shows which method was selected


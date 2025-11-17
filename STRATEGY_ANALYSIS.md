# Bollinger Band Strategy Analysis & Refactoring Plan

## Executive Summary

This document analyzes three implementations of the Bollinger Band trading strategy:
1. **BB Genetic.ipynb** - Genetic algorithm optimizer with backtesting
2. **BB Strategy.ipynb** - Standalone backtester with visualization
3. **ib_deployment.py** - Live trading implementation for Interactive Brokers

**Key Finding**: The core strategy logic has **drifted significantly** between implementations, with critical differences in trailing stop logic, entry/exit conditions, and parameter handling.

---

## 1. Core Strategy Components Comparison

### 1.1 Indicator Calculations

#### Bollinger Bands
**All three implementations are IDENTICAL:**
```python
df['mid'] = df['close'].rolling(bb_length).mean()
df['std'] = df['close'].rolling(bb_length).std()
df['upper'] = df['mid'] + df['std'] * bb_stddev
df['lower'] = df['mid'] - df['std'] * bb_stddev
```

#### ATR Calculation
**All three implementations are IDENTICAL:**
```python
tr = np.maximum.reduce([
    df['high'] - df['low'],
    (df['high'] - df['close'].shift()).abs(),
    (df['low'] - df['close'].shift()).abs()
])
df['atr_ts'] = pd.Series(tr, index=df.index).rolling(atr_length_ts).mean()
```

**✅ GOOD**: Indicator calculations are consistent across all implementations.

---

### 1.2 Entry Logic

#### Entry Conditions
**All three are IDENTICAL:**
```python
# Long entry
if enable_long:
    trig = lower * (1 - long_trigger_pct / 100)
    if (long_wick_touch and low <= trig) or (long_body_zone and close <= trig):
        enter_long = True

# Short entry
if enable_short:
    trig = upper * (1 + short_trigger_pct / 100)
    if (short_wick_touch and high >= trig) or (short_body_zone and close >= trig):
        enter_short = True
```

**✅ GOOD**: Entry logic is consistent.

#### Initial Stop Loss & Take Profit Setup
**All three are IDENTICAL:**
```python
entry = close
stop = entry * (1 - direction * initial_sl_pct / 100)

# TP calculation
if fixed_atr_tp:
    tp = entry + direction * atr_val * atr_mult_tp
elif fixed_bb_entry_tp:
    tp = upper if direction==1 else lower
```

**✅ GOOD**: Initial stop/TP setup is consistent.

---

### 1.3 Trailing Stop Logic - ⚠️ CRITICAL DIFFERENCES

#### BB Genetic.ipynb (CORRECT - per-bar tracking)
```python
# In exit loop, per position:
pos['bars_held'] = pos.get('bars_held', 0) + 1  # Track bars held

# Trailing stop (only after delay)
if enable_trailing and pos['bars_held'] >= trailing_delay:
    atr = atr_ts
    if dir_ == 1:
        new_stop = pos['max_high'] - atr * atr_mult_ts
        pos['stop'] = max(pos['stop'], new_stop)
    else:
        new_stop = pos['min_low'] + atr * atr_mult_ts
        pos['stop'] = min(pos['stop'], new_stop)
```

**✅ CORRECT**: Tracks `bars_held` per position, only trails after delay.

#### BB Strategy.ipynb (MISSING trailing delay check)
```python
# In exit loop:
if enable_trailing:
    atr = row['atr_ts']
    if direction == 1:
        pos['stop'] = max(pos['stop'], pos['max_high'] - atr * atr_mult_ts)
    else:
        pos['stop'] = min(pos['stop'], pos['min_low'] + atr * atr_mult_ts)
```

**❌ BUG**: Missing `bars_held` tracking and `trailing_delay` check! Trailing starts immediately.

#### ib_deployment.py (USES GLOBAL bar_count - WRONG)
```python
# In check_exits:
if enable_trailing and bar_count >= trailing_delay:  # ❌ WRONG: uses global bar_count
    atr = data['atr_ts'].iloc[-1]
    peak = new_row['high'] if dir_ == 1 else new_row['low']
    new_stop = peak - dir_ * atr * atr_mult_ts
    # Updates bracket order stop
```

**❌ BUG**: Uses global `bar_count` instead of per-position `bars_held`. All positions share the same delay counter.

#### ib_deployment-v1.45.py (CORRECT - per-position tracking)
```python
# In check_exits:
pos['bars_held'] += 1  # ✅ Correct: per-position tracking

if enable_trailing and pos['bars_held'] >= trailing_delay:
    atr = data['atr_ts'].iloc[-1]
    if dir_ == 1:
        new_stop = pos['max_high'] - atr * atr_mult_ts
        pos['stop'] = max(pos['stop'], new_stop)
    # ... similar for short
```

**✅ CORRECT**: Tracks `bars_held` per position.

**🔴 CRITICAL ISSUE**: 
- `BB Strategy.ipynb` ignores trailing delay completely
- `ib_deployment.py` uses wrong delay mechanism (global vs per-position)
- Only `BB Genetic.ipynb` and `ib_deployment-v1.45.py` implement it correctly

---

### 1.4 Exit Logic

#### Exit Condition Checking
**All three are IDENTICAL:**
```python
candidates = []
# Stop loss
if direction == 1 and low <= pos['stop']:
    candidates.append(('Stop', pos['stop']))
elif direction == -1 and high >= pos['stop']:
    candidates.append(('Stop', pos['stop']))

# Opposite BB TP
if opposite_bb_tp:
    if direction == 1 and high >= upper:
        candidates.append(('TP Opp BB', upper))
    elif direction == -1 and low <= lower:
        candidates.append(('TP Opp BB', lower))

# Fixed ATR TP
if fixed_atr_tp and pos['tp'] is not None:
    if direction == 1 and high >= pos['tp']:
        candidates.append(('TP ATR', pos['tp']))
    # ... similar for short

# Fixed BB Entry TP
if fixed_bb_entry_tp and pos['tp'] is not None:
    if direction == 1 and high >= pos['tp']:
        candidates.append(('TP BB', pos['tp']))
    # ... similar for short

# Choose closest exit
if candidates:
    candidates.sort(key=lambda x: abs(x[1] - pos['entry_price']))
    reason, price = candidates[0]
```

**✅ GOOD**: Exit logic is consistent.

---

### 1.5 Filter Logic

#### RTH Filter
**All three are IDENTICAL:**
```python
if enable_rth_filter:
    df['in_rth'] = pd.Series([t.time() for t in df.index], index=df.index)\
                    .between(rth_start, rth_end)
else:
    df['in_rth'] = True
```

**✅ GOOD**: RTH filter is consistent.

#### Volume Filter
**All three are IDENTICAL:**
```python
df['avg_volume'] = df['volume'].rolling(50).mean()
df['volume_filter'] = df['volume'] >= df['avg_volume'] * min_volume_multiplier
```

**✅ GOOD**: Volume filter is consistent.

#### ATR Filter
**All three are IDENTICAL:**
```python
df['atr_filter'] = df['atr_ts'] >= min_atr_points
```

**✅ GOOD**: ATR filter is consistent.

---

### 1.6 Parameter Loading

#### BB Genetic.ipynb
```python
def load_params(csv_path):
    df = pd.read_csv(csv_path)
    d = {}
    for _, r in df.iterrows():
        name, val, mn, mx, typ = r['Name'], r['Value'], r['Min'], r['Max'], r['Type']
        if pd.notna(typ):
            if typ == 'int':
                val = int(val); mn = int(mn) if pd.notna(mn) else None
            elif typ == 'float':
                val = float(val); mn = float(mn) if pd.notna(mn) else None
            elif typ == 'bool':
                val = ast.literal_eval(val.capitalize())
        d[name] = {'value': val, 'min': mn, 'max': mx, 'type': typ}
    return d, df
```

**✅ COMPREHENSIVE**: Handles types, min/max, returns dict + DataFrame.

#### BB Strategy.ipynb
```python
for _, row in params_df.iterrows():
    key = row['Name'].strip()
    value = row['Value'].strip()
    if value in ['true', 'false']:
        params[key] = (value == 'true')
    elif value.replace('.', '', 1).replace('-', '', 1).isdigit():
        try:
            params[key] = ast.literal_eval(value)
        except:
            params[key] = value
    else:
        params[key] = value
```

**⚠️ SIMPLER**: Basic type inference, no min/max handling.

#### ib_deployment.py
```python
def load_params(csv_path):
    df = pd.read_csv(csv_path)
    d = {}
    for _, r in df.iterrows():
        name, val = r['Name'].strip(), r['Value']
        if isinstance(val, str):
            val = val.strip()
        if val in ('true', 'false'):
            d[name] = (val == 'true')
        elif str(val).lstrip('-').replace('.', '', 1).isdigit():
            d[name] = float(val)
        else:
            d[name] = val
    return d
```

**⚠️ SIMPLER**: Similar to BB Strategy, converts all numbers to float.

**⚠️ ISSUE**: Parameter loading differs - could cause type mismatches.

---

## 2. Critical Differences Summary

| Component | BB Genetic | BB Strategy | ib_deployment | ib_deployment-v1.45 |
|-----------|------------|-------------|---------------|---------------------|
| **Trailing Delay** | ✅ Per-position `bars_held` | ❌ Missing | ❌ Global `bar_count` | ✅ Per-position `bars_held` |
| **Entry Logic** | ✅ Correct | ✅ Correct | ✅ Correct | ✅ Correct |
| **Exit Logic** | ✅ Correct | ✅ Correct | ✅ Correct | ✅ Correct |
| **Indicators** | ✅ Correct | ✅ Correct | ✅ Correct | ✅ Correct |
| **Filters** | ✅ Correct | ✅ Correct | ✅ Correct | ✅ Correct |
| **Param Loading** | ✅ Comprehensive | ⚠️ Basic | ⚠️ Basic | ⚠️ Basic |

---

## 3. Parameter File Differences

### Files Used:
- **BB Genetic**: `BB_Strategy_Parameters_v1.12.csv`
- **BB Strategy**: `BB_Strategy_Parameters_optimized.csv`
- **ib_deployment.py**: `BB_Strategy_Parameters_optimized_TWS.csv`
- **ib_deployment-v1.45.py**: `BB_Strategy_Parameters_optimized.csv`

**⚠️ ISSUE**: Different parameter files could lead to different strategy behavior.

### Parameter Name Mismatch:
- **ib_deployment.py line 85**: `'Short Entry on Body in Zone'` → Should be `'Short Entry on Body in Zone'` but code uses `'Short Entry on Zone'` (line 85)
  - **❌ BUG**: Parameter name mismatch could cause default value to be used

---

## 4. Refactoring Plan

### Phase 1: Create Shared Strategy Module

Create `bollinger_strategy.py` with:

```python
class BollingerBandStrategy:
    """
    Shared Bollinger Band trading strategy implementation.
    Used by backtesting, optimization, and live trading.
    """
    
    def __init__(self, params):
        """Initialize strategy with parameters dict."""
        self.params = params
        self._extract_params()
    
    def _extract_params(self):
        """Extract and validate all parameters."""
        # ... parameter extraction logic
    
    def calculate_indicators(self, df):
        """Calculate BB and ATR indicators."""
        # ... indicator calculation
    
    def apply_filters(self, df):
        """Apply RTH, volume, and ATR filters."""
        # ... filter logic
    
    def check_entry(self, row, df):
        """Check if entry conditions are met. Returns (enter_long, enter_short)."""
        # ... entry logic
    
    def setup_position(self, entry_price, direction, row, df):
        """Setup initial stop and TP for new position."""
        # ... position setup
    
    def update_trailing_stop(self, position, row, df):
        """Update trailing stop if enabled and delay met."""
        # ... trailing stop logic (CORRECT implementation)
    
    def check_exit(self, position, row, df):
        """Check if exit conditions are met. Returns (should_exit, reason, price)."""
        # ... exit logic
```

### Phase 2: Refactor Each Implementation

1. **BB Genetic.ipynb**: Replace `run_backtest()` with strategy class
2. **BB Strategy.ipynb**: Replace inline logic with strategy class
3. **ib_deployment.py**: Replace inline logic with strategy class

### Phase 3: Standardize Parameter Loading

Create `parameter_loader.py`:
```python
def load_params(csv_path, return_dataframe=False):
    """
    Unified parameter loading with proper type handling.
    """
    # ... comprehensive loading logic from BB Genetic
```

### Phase 4: Testing & Validation

1. Run all three implementations with identical parameters
2. Verify identical trade signals
3. Verify identical PNL calculations
4. Document any remaining differences

---

## 5. Immediate Action Items

### High Priority (Fix Bugs):
1. ✅ **Fix BB Strategy.ipynb**: Add `bars_held` tracking and trailing delay check
2. ✅ **Fix ib_deployment.py**: Replace global `bar_count` with per-position `bars_held`
3. ✅ **Fix ib_deployment.py line 85**: Correct parameter name `'Short Entry on Body in Zone'`

### Medium Priority (Refactoring):
4. Create shared strategy module
5. Standardize parameter loading
6. Update all three implementations to use shared module

### Low Priority (Enhancement):
7. Add unit tests for strategy logic
8. Add integration tests comparing outputs
9. Create strategy documentation

---

## 6. Recommended Next Steps

1. **Immediate**: Fix the trailing delay bugs in `BB Strategy.ipynb` and `ib_deployment.py`
2. **Short-term**: Create the shared strategy module (`bollinger_strategy.py`)
3. **Medium-term**: Refactor all three implementations to use the shared module
4. **Long-term**: Add comprehensive testing and documentation

---

## 7. Code Structure Proposal

```
Trading/
├── bollinger_strategy/
│   ├── __init__.py
│   ├── strategy.py          # Core strategy logic
│   ├── indicators.py        # BB, ATR calculations
│   ├── filters.py           # RTH, volume, ATR filters
│   └── parameters.py        # Parameter loading/validation
├── backtesting/
│   ├── genetic_optimizer.py # Uses bollinger_strategy
│   └── standalone.py        # Uses bollinger_strategy
├── live_trading/
│   └── ib_deployment.py     # Uses bollinger_strategy
└── tests/
    ├── test_strategy.py
    └── test_integration.py
```

---

## Conclusion

The strategy logic has **drifted significantly**, with critical bugs in trailing stop implementation. The refactoring plan will:
- ✅ Eliminate code duplication
- ✅ Fix existing bugs
- ✅ Ensure consistency across all implementations
- ✅ Make future updates easier (change once, works everywhere)

**Estimated Effort**: 2-3 days for full refactoring + testing.


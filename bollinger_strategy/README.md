# Bollinger Band Strategy - Shared Module

This module provides a unified implementation of the Bollinger Band trading strategy that can be shared across:
- Backtesting (`BB Strategy.ipynb`)
- Genetic Algorithm Optimization (`BB Genetic.ipynb`)
- Live Trading (`ib_deployment.py`)

## Features

✅ **Unified Logic**: Single source of truth for strategy logic
✅ **Correct Implementation**: Based on BB Genetic.ipynb with proper trailing delay
✅ **Type Safety**: Comprehensive parameter loading with type validation
✅ **Modular Design**: Separate modules for indicators, filters, and strategy logic

## Installation

The module is already in your project. Just import it:

```python
from bollinger_strategy import BollingerBandStrategy, load_params
```

## Quick Start

### 1. Load Parameters

```python
from bollinger_strategy import load_params

# Load parameters from CSV
params_dict = load_params('Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv')
```

### 2. Initialize Strategy

```python
from bollinger_strategy import BollingerBandStrategy

strategy = BollingerBandStrategy(params_dict)
```

### 3. Calculate Indicators

```python
import pandas as pd

# Load your data
df = pd.read_csv('Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv',
                 header=None, names=['datetime','open','high','low','close','volume'],
                 parse_dates=['datetime'], index_col='datetime')

# Calculate indicators
df = strategy.calculate_indicators(df)
```

### 4. Apply Filters

```python
# Apply RTH, volume, and ATR filters
df = strategy.apply_filters(df)
```

### 5. Check Entries

```python
# In your simulation loop
for idx, row in df.iterrows():
    enter_long, enter_short = strategy.check_entry(row, df)
    
    if enter_long or enter_short:
        direction = 1 if enter_long else -1
        entry_price = row['close']
        position = strategy.setup_position(entry_price, direction, row, df)
        positions.append(position)
```

### 6. Update Positions and Check Exits

```python
# In your simulation loop
for position in positions[:]:
    # Update trailing stop
    strategy.update_trailing_stop(position, row, df)
    
    # Check exit
    should_exit, reason, price = strategy.check_exit(position, row, df)
    
    if should_exit:
        # Close position
        pnl = (price - position['entry_price']) * position['direction'] * 50
        positions.remove(position)
```

## Updating Optimizable Parameters

For genetic algorithm optimization, you can update optimizable parameters:

```python
# Update parameters (e.g., from GA)
optimized_params = {
    'Bollinger Band Length': 79,
    'Bollinger Band StdDev': 2.6358,
    'ATR Multiplier for Trailing Stop': 1.0257,
    'Trailing Delay (bars)': 19,
    # ... etc
}

strategy.update_optimizable_params(optimized_params)

# Recalculate indicators with new parameters
df = strategy.calculate_indicators(df)
df = strategy.apply_filters(df)
```

## Module Structure

```
bollinger_strategy/
├── __init__.py          # Package initialization
├── parameters.py        # Parameter loading and validation
├── indicators.py        # BB and ATR calculations
├── filters.py           # RTH, volume, ATR filters
├── strategy.py          # Core strategy logic
└── README.md            # This file
```

## Key Differences from Original Implementations

### ✅ Fixed Issues

1. **Trailing Delay**: Now correctly implemented with per-position `bars_held` tracking
2. **Parameter Loading**: Unified, type-safe parameter loading
3. **Consistency**: All three implementations will use identical logic

### 🔧 Migration Path

1. **Phase 1** (Current): Shared module created, existing files untouched
2. **Phase 2** (Optional): Create new versions using shared module
3. **Phase 3** (When Ready): Test and validate new versions
4. **Phase 4** (Final): Switch to new versions when confident

## Example: Complete Backtest Loop

```python
from bollinger_strategy import BollingerBandStrategy, load_params
import pandas as pd

# Load parameters
params = load_params('Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv')
strategy = BollingerBandStrategy(params)

# Load and prepare data
df = pd.read_csv('data.csv', ...)
df = strategy.calculate_indicators(df)
df = strategy.apply_filters(df)

# Simulation
positions = []
trades = []

for row in df.itertuples():
    # Check exits first
    for pos in positions[:]:
        strategy.update_trailing_stop(pos, row, df)
        should_exit, reason, price = strategy.check_exit(pos, row, df)
        
        if should_exit:
            pnl = (price - pos['entry_price']) * pos['direction'] * 50
            trades.append({
                **pos,
                'exit_time': row.Index,
                'exit_price': price,
                'pnl': pnl,
                'reason': reason
            })
            positions.remove(pos)
    
    # Check entries
    if len(positions) < strategy.max_open_trades:
        enter_long, enter_short = strategy.check_entry(row, df)
        
        if enter_long or enter_short:
            direction = 1 if enter_long else -1
            entry_price = row.close
            position = strategy.setup_position(entry_price, direction, row, df)
            positions.append(position)

# Close remaining positions
for pos in positions:
    price = df.iloc[-1]['close']
    pnl = (price - pos['entry_price']) * pos['direction'] * 50
    trades.append({
        **pos,
        'exit_time': df.index[-1],
        'exit_price': price,
        'pnl': pnl,
        'reason': 'EOD'
    })
```

## Notes

- All existing files remain untouched
- Your running genetic algorithm continues to work
- You can migrate when ready
- The shared module is ready to use immediately


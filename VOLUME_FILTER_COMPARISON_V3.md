# Volume Filter Logic Comparison Across Scripts (Using BB_Strategy_v3.py)

## Summary

All three scripts (GA, Backtester v3, Live Trading) use **identical logic** through the shared `bollinger_strategy` module: they resample 5-second bars to the target timeframe, then apply the volume filter using the **resampled bar volume** (not the 5-second bar volume).

---

## 1. BB_Strategy_v3.py (Standalone Backtester v3.0)

### Data Flow:
1. **Load Data**: Reads 5-second bars from CSV (line 123-127)
   ```python
   df = pd.read_csv(DATA_CSV, header=None, 
                    names=['datetime', 'open', 'high', 'low', 'close', 'volume'],
                    parse_dates=['datetime'], index_col='datetime')
   ```

2. **Calculate Indicators** (line 131):
   ```python
   df = strategy.calculate_indicators(df)
   ```
   - Inside `calculate_indicators()` (from `bollinger_strategy/strategy.py`):
     - Detects incoming bar frequency (5-second bars)
     - If target timeframe > 1 minute, resamples:
       ```python
       df_resampled = df.resample(f'{self.timeframe}T', label='right', closed='right').agg({
           'open': 'first',
           'high': 'max',
           'low': 'min',
           'close': 'last',
           'volume': 'sum'  # ← Sums volumes from 5-sec bars
       })
       ```

3. **Apply Filters** (line 137):
   ```python
   df = strategy.apply_filters(df)
   ```
   - Calls `apply_volume_filter()` from `bollinger_strategy/filters.py`:
     ```python
     df['avg_volume'] = df['volume'].rolling(volume_window).mean()
     df['volume_filter'] = df['volume'] <= df['avg_volume'] * max_volume_multiplier
     ```
   - Uses `df['volume']` which is the **resampled bar volume**

4. **Entry Checking** (line 242):
   ```python
   enter_long, enter_short = strategy.check_entry(row, df)
   ```
   - `row` is from the resampled DataFrame (via `df.itertuples()`)
   - Uses resampled bar volume for filter evaluation

### Key Point:
✅ Uses **resampled bar volume** (e.g., 1,504 for a 7-min bar) for filtering

---

## 2. BB_Genetic_v3.py (GA Backtester)

### Data Flow:
1. **Load Data**: Reads 5-second bars from CSV
2. **Calculate Indicators**:
   ```python
   df = strategy.calculate_indicators(df)
   ```
   - Same resampling logic as BB_Strategy_v3.py
   - Resamples 5-second bars to target timeframe with `volume: 'sum'`

3. **Apply Filters**:
   ```python
   df = strategy.apply_filters(df)
   ```
   - Uses `apply_volume_filter()` from shared module
   - Compares **resampled bar volume** vs `avg_volume * max_volume_multiplier`

4. **Entry Checking**:
   ```python
   enter_long, enter_short = strategy.check_entry(row, df)
   ```
   - Uses resampled bar row

### Key Point:
✅ Uses **resampled bar volume** (e.g., 1,504 for a 7-min bar) for filtering

---

## 3. ib_deployment_v2.py (Live Trading)

### Data Flow:
1. **Receive Data**: Gets 5-second bars from IB API
   ```python
   data = data._append(new_row)  # 5-second bars stored here
   ```

2. **Calculate Indicators**:
   ```python
   data_with_indicators = strategy.calculate_indicators(data.copy())
   ```
   - Same resampling logic as other scripts
   - Resamples 5-second bars to target timeframe with `volume: 'sum'`

3. **Apply Filters**:
   ```python
   data_with_filters = strategy.apply_filters(data_with_indicators)
   ```
   - Uses `apply_volume_filter()` from shared module
   - Compares **resampled bar volume** vs `avg_volume * max_volume_multiplier`

4. **Entry Check** (FIXED):
   ```python
   # Get resampled bar row (has resampled volume)
   resampled_row = data_with_filters.iloc[-1]
   # Ensure volume is from resampled bar
   resampled_row['volume'] = resampled_row_indicators['volume']  # Resampled volume
   
   check_entries(..., resampled_row, ...)
   ```
   - In `check_entries()`:
     ```python
     resampled_bar_volume = latest_row.get('volume', 0)  # ← Resampled bar volume
     vol_threshold = avg_volume * strategy.max_volume_multiplier_opt
     volume_filter = resampled_bar_volume <= vol_threshold
     ```

### Key Point:
✅ **NOW** uses **resampled bar volume** (e.g., 1,504 for a 7-min bar) for filtering
- **Before fix**: Was using 5-second bar volume (e.g., 13) ❌
- **After fix**: Uses resampled bar volume (e.g., 1,504) ✅

---

## Volume Filter Logic (All Scripts - Shared Module)

The volume filter is implemented in `bollinger_strategy/filters.py`:

```python
def apply_volume_filter(df, max_volume_multiplier, volume_window=50):
    df['avg_volume'] = df['volume'].rolling(volume_window).mean()
    # For mean reversion: filter allows LOW volume
    df['volume_filter'] = df['volume'] <= df['avg_volume'] * max_volume_multiplier
    return df
```

**Important**: The `df['volume']` here is the **resampled bar volume** (after `calculate_indicators()` resamples the data).

**Filter Logic**: 
- Allows LOW volume (volume <= avg * multiplier) - good for mean reversion
- Blocks HIGH volume (volume > avg * multiplier) - indicates strong momentum

---

## Consistency Check

| Script | Input Data | Resampling | Volume Filter Uses | Filter Direction |
|--------|-----------|------------|-------------------|------------------|
| **BB_Strategy_v3.py** | 5-sec CSV | ✅ Resamples to target timeframe | ✅ Resampled bar volume | ✅ LOW volume (<=) |
| **BB_Genetic_v3.py** | 5-sec CSV | ✅ Resamples to target timeframe | ✅ Resampled bar volume | ✅ LOW volume (<=) |
| **ib_deployment_v2.py** | 5-sec IB API | ✅ Resamples to target timeframe | ✅ Resampled bar volume (after fix) | ✅ LOW volume (<=) |

---

## Data Flow Diagram

```
5-Second Bars (CSV or IB API)
    ↓
strategy.calculate_indicators()
    ↓
Resample to Target Timeframe (e.g., 7 minutes)
    ↓
volume = sum(5-sec bar volumes)  ← Aggregated volume
    ↓
strategy.apply_filters()
    ↓
apply_volume_filter()
    ↓
avg_volume = rolling_mean(volume, window=50)  ← From resampled bars
volume_filter = (volume <= avg_volume * multiplier)  ← Uses resampled volume
    ↓
strategy.check_entry()
    ↓
Uses resampled bar row with resampled volume
```

---

## Conclusion

All three scripts now use **identical logic** through the shared `bollinger_strategy` module:

1. ✅ Start with 5-second bars
2. ✅ Resample to target timeframe (summing volumes: `volume: 'sum'`)
3. ✅ Calculate `avg_volume` from resampled bars
4. ✅ Compare **resampled bar volume** vs `avg_volume * multiplier`
5. ✅ Filter direction: Allows LOW volume (mean reversion strategy)

The fix in `ib_deployment_v2.py` ensures that entry checks use the resampled bar volume (1,504) instead of the 5-second bar volume (13), making it **fully consistent** with the GA and backtester.

---

## Key Differences from Old BB_Strategy.py

**Note**: The old `BB_Strategy.py` (not v3) had a different volume filter:
- Old: `df['volume_filter'] = df['volume'] >= df['avg_volume'] * min_volume_multiplier` (allows HIGH volume)
- New (v3): Uses shared module with `<=` (allows LOW volume)

**BB_Strategy_v3.py** uses the shared module, so it's consistent with GA and live trading.


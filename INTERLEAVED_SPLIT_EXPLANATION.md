# Interleaved In-Sample / Out-of-Sample Split

## Overview
Implemented interleaved data splitting to improve generalization and reduce overfitting. Instead of a single contiguous split, the data is now divided into multiple alternating periods.

---

## How It Works

### Simple Split (Original - Still Available)
```
[========== IS ==========][===== OOS =====]
    65% of data             35% of data
```

### Interleaved Split (New - Default)
```
[== IS ==][== OOS ==][== IS ==][== OOS ==][== IS ==]
Period 1  Period 2   Period 3  Period 4   Period 5
```

**With 5 periods:**
- Periods 1, 3, 5 → Combined into IS dataset
- Periods 2, 4 → Combined into OOS dataset
- Final IS: ~60% of data (3 out of 5 periods)
- Final OOS: ~40% of data (2 out of 5 periods)

---

## Benefits

1. **Better Generalization**
   - Strategy tested across multiple time periods
   - Reduces overfitting to specific market conditions
   - More robust validation

2. **Market Condition Diversity**
   - IS and OOS periods span different market regimes
   - Tests strategy across bull/bear/sideways markets
   - Reduces temporal bias

3. **More Realistic Performance**
   - If strategy only works in one period, it will fail in others
   - Forces optimization to find generalizable parameters
   - Better predictor of live trading performance

---

## Configuration

### Parameters Added to CSV

**USE_INTERLEAVED_SPLIT** (bool, default: true)
- Enable/disable interleaved splitting
- Set to `false` to use simple chronological split

**NUM_SPLIT_PERIODS** (int, default: 5, range: 3-7)
- Number of alternating periods
- **Odd numbers recommended** (ensures more IS than OOS)
- Examples:
  - 3 periods: IS-OOS-IS (2 IS, 1 OOS)
  - 5 periods: IS-OOS-IS-OOS-IS (3 IS, 2 OOS) ← **Recommended**
  - 7 periods: IS-OOS-IS-OOS-IS-OOS-IS (4 IS, 3 OOS)

---

## Example Output

When running with interleaved split, you'll see:

```
=== Using Interleaved Data Split ===
Number of periods: 5
Pattern: Alternating IS-OOS-IS-OOS...
  Period 1: IS (200,000 rows, 2020-01-01 to 2020-06-30)
  Period 2: OOS (200,000 rows, 2020-07-01 to 2020-12-31)
  Period 3: IS (200,000 rows, 2021-01-01 to 2021-06-30)
  Period 4: OOS (200,000 rows, 2021-07-01 to 2021-12-31)
  Period 5: IS (200,000 rows, 2022-01-01 to 2022-06-30)

Combined IS: 600,000 rows (60.0%)
  Date range: 2020-01-01 to 2022-06-30
Combined OOS: 400,000 rows (40.0%)
  Date range: 2020-07-01 to 2021-12-31
==================================================
```

---

## Implementation Details

1. **Data is sorted chronologically** before splitting
2. **Equal-sized periods** (last period may be slightly larger)
3. **Even-indexed periods (0, 2, 4...)** → IS
4. **Odd-indexed periods (1, 3, 5...)** → OOS
5. **Periods are concatenated** maintaining chronological order
6. **Final datasets are sorted** to ensure proper time sequence

---

## Comparison: Simple vs Interleaved

| Feature | Simple Split | Interleaved Split |
|---------|-------------|-------------------|
| **IS Periods** | 1 contiguous | Multiple (alternating) |
| **OOS Periods** | 1 contiguous | Multiple (alternating) |
| **Temporal Bias** | High (recent data in OOS) | Low (distributed) |
| **Market Diversity** | Limited | High |
| **Overfitting Risk** | Higher | Lower |
| **Generalization** | Moderate | Better |

---

## When to Use Each

### Use Interleaved Split (Recommended)
- ✅ New optimization runs
- ✅ When overfitting is a concern
- ✅ When you want robust validation
- ✅ When data spans multiple market regimes

### Use Simple Split
- ✅ When you specifically want to test on recent data
- ✅ When you want to simulate "train on past, test on future"
- ✅ When data is limited (interleaved needs more data)

---

## Notes

- **DATA_SPLITS parameter** is still used but interpreted differently:
  - In simple split: Direct IS fraction (e.g., 0.65 = 65% IS)
  - In interleaved: Not directly used (periods are equal-sized)
  
- **Odd NUM_PERIODS recommended** to ensure IS > OOS

- **More periods = better generalization** but requires more data

---

## Files Modified

1. `BB_Genetic_v3.py` - Added interleaved split logic
2. `Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv` - Added new parameters

---

## Next Steps

1. Run GA with interleaved split enabled (default)
2. Monitor IS/OOS consistency - should be much better
3. Compare results to previous simple split run
4. Adjust NUM_PERIODS if needed (3, 5, or 7)


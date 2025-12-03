# GA Dashboard Normalization Conversion Guide

## Understanding the "All Solutions" Table vs "Actual Backtest Results"

The **"All Solutions"** table shows **NORMALIZED FITNESS VALUES** (0-1 range) used by the GA for optimization.
The **"Actual Backtest Results"** section shows **REAL BACKTEST METRICS** from running the strategy.

These values will **NOT match** because they serve different purposes:
- **Normalized values**: Used for multi-objective optimization (NSGA-II)
- **Actual values**: Real performance metrics from backtesting

---

## Normalization Formulas

### Current Normalization Ranges (from CSV):
- `NORM_SORTINO_MAX` = **10.0**
- `NORM_DD_MAX` = **100,000.0** (dollars)
- `NORM_PF_MAX` = **5.0**
- `NORM_TRADES_MAX` = **3.0** (but trades/day is NOT normalized - uses raw value)
- `NORM_PNL_MAX` = **465,000.0** (dollars)

---

## Conversion Formulas

### 1. Sortino Ratio
**Formula:** `normalized_sortino = min(1.0, max(0.0, actual_sortino / 10.0))`

**Example:**
- Actual Sortino: **1.943052**
- Normalized: `1.943052 / 10.0 = 0.1943`
- **Note:** If normalized value is **0.6774**, the actual Sortino would be: `0.6774 × 10.0 = 6.774`

**Reverse:** `actual_sortino = normalized_sortino × 10.0`

---

### 2. Max Drawdown (INVERTED!)
**Formula:** `normalized_dd = 1.0 - min(1.0, max(0.0, actual_dd / 100000.0))`

**Why inverted?** Lower drawdown is better, so we invert: $0 DD = 1.0, $100K DD = 0.0

**Example:**
- Actual Max DD: **$2,399.70**
- Normalized: `1.0 - (2399.70 / 100000.0) = 1.0 - 0.024 = 0.976`
- **Note:** If normalized value is **0.98**, the actual DD would be: `(1.0 - 0.98) × 100000.0 = $2,000`

**Reverse:** `actual_dd = (1.0 - normalized_dd) × 100000.0`

---

### 3. Profit Factor
**Formula:** `normalized_pf = min(1.0, max(0.0, actual_pf / 5.0))`

**Example:**
- Actual PF: **0.625406**
- Normalized: `0.625406 / 5.0 = 0.1251`
- **Note:** If normalized value is **0.2320**, the actual PF would be: `0.2320 × 5.0 = 1.16`

**Reverse:** `actual_pf = normalized_pf × 5.0`

---

### 4. Avg Trades/Day (NOT NORMALIZED!)
**Formula:** `normalized_trades = actual_trades_day` (raw value, no normalization)

**Example:**
- Actual Trades/Day: **6.415**
- Displayed value: **6.415** (should match exactly)
- **Note:** If displayed value is **3.293**, that's the actual trades/day (not normalized)

**Why not normalized?** The GA uses raw trades/day values directly to make the weight=5.0 more effective.

---

### 5. Total Profit
**Formula:** `normalized_pnl = min(1.0, max(0.0, actual_pnl / 465000.0))`

**Example:**
- Actual Total Profit: **$65,792.41**
- Normalized: `65792.41 / 465000.0 = 0.1415`
- **Note:** If normalized value is **0.3139**, the actual profit would be: `0.3139 × 465000.0 = $145,963.50`

**Reverse:** `actual_pnl = normalized_pnl × 465000.0`

---

## Why Values Don't Match

### Example from Your Dashboard:

**Actual Backtest Results:**
- Sortino: **1.943052**
- Max DD: **$2,399.70**
- PF: **0.625406**
- Avg Trades/Day: **6.415**
- Total Profit: **$65,792.41**

**Rank 1 Solution (Normalized Fitness Values):**
- Sortino: **0.6774** → Actual would be: `0.6774 × 10.0 = 6.774`
- Max DD: **0.98** → Actual would be: `(1.0 - 0.98) × 100000.0 = $2,000`
- PF: **0.2320** → Actual would be: `0.2320 × 5.0 = 1.16`
- Avg Trades/Day: **3.293** → This IS the actual value (not normalized)
- Total Profit: **0.3139** → Actual would be: `0.3139 × 465000.0 = $145,963.50`

### Why the Difference?

The **"All Solutions"** table shows fitness values from the **Hall of Fame** (best solutions across all generations).
The **"Actual Backtest Results"** shows a **fresh backtest** of the selected solution.

**Possible reasons for mismatch:**
1. **Different data splits**: Fitness uses interleaved IS periods, actual backtest may use full dataset
2. **Different evaluation**: Fitness uses normalized/penalized values, actual backtest uses raw metrics
3. **Parameter conversion**: Fitness may use slightly different parameter values due to clamping/rounding
4. **Time period**: Fitness values may be from an earlier generation, actual backtest uses current parameters

---

## Quick Reference Table

| Metric | Normalization Range | Formula | Reverse Formula |
|--------|-------------------|---------|----------------|
| **Sortino** | 10.0 | `actual / 10.0` | `normalized × 10.0` |
| **Max DD** | 100,000.0 | `1.0 - (actual / 100000.0)` | `(1.0 - normalized) × 100000.0` |
| **Profit Factor** | 5.0 | `actual / 5.0` | `normalized × 5.0` |
| **Trades/Day** | N/A (raw) | `actual` (no change) | `normalized` (same) |
| **Total Profit** | 465,000.0 | `actual / 465000.0` | `normalized × 465000.0` |

---

## Important Notes

1. **Drawdown is INVERTED**: Higher normalized value = Lower actual drawdown (better)
2. **Trades/Day is NOT normalized**: The displayed value IS the actual trades/day
3. **Values are clamped**: All normalized values are clamped to [0.0001, 1.0] range
4. **Penalty values**: If you see **-1000** in normalized values, the solution hit a hard constraint (negative Sortino, negative PNL, or win rate < 40%)

---

## How to Verify

To verify the conversion, check the **"Selected Solution Performance"** section - it should show actual backtest results that match the conversion formulas above.

If values still don't match after conversion, it likely means:
- The solution in "All Solutions" is from a different generation
- Different data splits were used
- Parameters were clamped/rounded differently


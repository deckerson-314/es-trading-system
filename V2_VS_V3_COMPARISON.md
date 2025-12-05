# Functional Comparison: ib_deployment_v2.py vs ib_deployment_v3.py

## Overview

**V2 (ib_deployment_v2.py)**: Base version from git (December 3, 2025)  
**V3 (ib_deployment_v3.py)**: Enhanced version with critical bug fixes

---

## Key Functional Differences

### 1. Exception Handling in `on_bar_update()`

#### V2 (No Exception Handling)
```python
def on_bar_update(bars, hasNewBar):
    global data, bar_count
    if not hasNewBar:
        return
    
    bar = bars[-1]
    # ... rest of function ...
```

**Problem**: If an exception occurs during bar processing, `ib_insync` logs the entire `bars` object (thousands of lines), flooding the log file and making debugging impossible.

#### V3 (Exception Handling Added)
```python
def on_bar_update(bars, hasNewBar):
    global data, bar_count
    try:
        if not hasNewBar:
            return
        
        if not bars or len(bars) == 0:
            logging.warning("on_bar_update: bars list is empty")
            return
        
        bar = bars[-1]
        # ... rest of function ...
    except Exception as e:
        # Log exception concisely without printing all bar data
        bar_time_str = "unknown"
        if bars and len(bars) > 0:
            try:
                bar_time_str = bars[-1].date.strftime('%H:%M:%S') if hasattr(bars[-1], 'date') else "unknown"
            except:
                pass
        logging.error(f"Error in on_bar_update at {bar_time_str}: {type(e).__name__}: {str(e)}", exc_info=True)
```

**Benefits**:
- ✅ Prevents log flooding with massive `BarData` objects
- ✅ Provides concise error messages with traceback
- ✅ Allows script to continue running after errors
- ✅ Makes debugging much easier

---

### 2. NaN Handling in Opposite BB TP Calculation

#### V2 (No NaN Check)
```python
# Update dynamic TP (Opposite BB TP)
if position_still_open and strategy.opposite_bb_tp and tp_order:
    if 'upper' in data.columns and 'lower' in data.columns and len(data) > 0:
        new_tp = float(data['upper'].iloc[-1]) if dir_ == 1 else float(data['lower'].iloc[-1])
        new_tp = round(new_tp * 4) / 4  # Round to tick size
        # ... continues with TP update ...
```

**Problem**: If Bollinger Bands haven't calculated yet (not enough data), `new_tp` becomes `NaN`, causing:
```
ValueError: cannot convert float NaN to integer
```
This crashes the script on every bar update until enough data accumulates.

#### V3 (NaN Check Added)
```python
# Update dynamic TP (Opposite BB TP)
if position_still_open and strategy.opposite_bb_tp and tp_order:
    if 'upper' in data.columns and 'lower' in data.columns and len(data) > 0:
        new_tp_raw = data['upper'].iloc[-1] if dir_ == 1 else data['lower'].iloc[-1]
        
        # Check if new_tp is NaN (can happen if not enough data for BB calculation)
        if pd.isna(new_tp_raw) or np.isnan(new_tp_raw):
            logging.debug(f"Opposite BB TP: Skipping update - BB value is NaN (not enough data)")
            # Skip TP update - keep current TP active
        else:
            new_tp = float(new_tp_raw)
            new_tp = round(new_tp * 4) / 4  # Round to tick size
            # ... continues with TP update ...
```

**Benefits**:
- ✅ Prevents crashes when BB values are NaN
- ✅ Gracefully skips TP update until data is ready
- ✅ Keeps existing TP order active (position remains protected)
- ✅ Script continues running normally

---

### 3. Stop Loss Protection During TP Updates

#### V2 (Stop Loss Lost During TP Update)
```python
# When updating opposite BB TP:
if new_tp_active:
    # New TP order is active, safe to cancel old one
    try:
        ib.cancelOrder(tp_order)  # ❌ This also cancels stop loss!
        ib.sleep(0.5)
        logging.info(f"Cancelled old TP order at {current_tp:.2f}")
    except Exception as e:
        # ...
    
    bracket['takeProfit'] = new_tp_order
    logging.info(f"Successfully updated opposite BB TP to {new_tp:.2f}")
```

**Problem**: When the old TP order has a `parentId` (part of a bracket), cancelling it causes IB to also cancel the stop loss order (they share the same parent). This leaves the position unprotected!

**Evidence from logs**:
```
2025-12-05 15:09:06,855 INFO orderStatus: StopOrder(... status='Cancelled' ...)
2025-12-05 15:09:06,857 INFO orderStatus: LimitOrder(... status='Cancelled' ...)  # TP
```

#### V3 (Stop Loss Protected During TP Update)
```python
# When updating opposite BB TP:
if new_tp_active:
    # CRITICAL: Before cancelling old TP, check if it has a parentId
    # If it does, cancelling it will also cancel the stop loss (they're in a bracket)
    # We need to recreate the stop loss as standalone first
    old_tp_has_parent = hasattr(tp_order, 'parentId') and tp_order.parentId != 0
    
    if old_tp_has_parent:
        # Old TP is part of a bracket - cancelling it will cancel the stop loss too
        # Recreate stop loss as standalone order first
        stop_order = bracket.get('stopLoss')
        if stop_order:
            stop_price = getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', 0))
            if stop_price > 0:
                logging.info(f"Old TP has parentId - recreating stop loss as standalone before cancelling TP")
                stop_action = 'SELL' if dir_ == 1 else 'BUY'
                stop_qty = abs(stop_order.totalQuantity) if hasattr(stop_order, 'totalQuantity') else qty
                
                # Create new standalone stop order
                new_stop_order = StopOrder(
                    action=stop_action,
                    totalQuantity=stop_qty,
                    stopPrice=stop_price,
                    tif='GTC',
                    transmit=True  # Standalone, no parent
                )
                
                try:
                    new_stop_trade = ib.placeOrder(contract, new_stop_order)
                    ib.sleep(1.0)  # Wait for submission
                    
                    # Verify new stop is active
                    new_stop_active = False
                    if new_stop_trade and new_stop_trade.order:
                        if new_stop_trade.isActive() or (new_stop_trade.orderStatus and 
                            new_stop_trade.orderStatus.status in ['PreSubmitted', 'Submitted', 'PendingSubmit', 'ApiPending']):
                            new_stop_active = True
                            if hasattr(new_stop_trade.order, 'permId') and new_stop_trade.order.permId != 0:
                                new_stop_order.permId = new_stop_trade.order.permId
                    
                    if new_stop_active:
                        # Update bracket with new standalone stop
                        bracket['stopLoss'] = new_stop_order
                        logging.info(f"Recreated stop loss as standalone order at {stop_price:.2f}")
                        # Now safe to cancel old TP
                        ib.cancelOrder(tp_order)
                        # ...
                    else:
                        logging.warning(f"Failed to recreate stop loss - aborting TP update")
                        # Cancel new TP order, keep old TP
                        ib.cancelOrder(new_tp_order)
                except Exception as stop_err:
                    logging.error(f"Error recreating stop loss: {stop_err}")
                    logging.warning(f"Aborting TP update - cannot protect stop loss")
                    # Cancel new TP order, keep old TP
                    ib.cancelOrder(new_tp_order)
    else:
        # Old TP doesn't have parentId - safe to cancel directly
        ib.cancelOrder(tp_order)
        # ...
```

**Benefits**:
- ✅ Stop loss is **never lost** during TP updates
- ✅ Position remains protected at all times
- ✅ If stop loss recreation fails, TP update is aborted (safer)
- ✅ Both orders become standalone after first TP update (no more bracket issues)

---

## Summary Table

| Feature | V2 | V3 | Impact |
|---------|----|----|--------|
| **Exception Handling** | ❌ None | ✅ Try-except in `on_bar_update` | Prevents log flooding, allows graceful error handling |
| **NaN Handling** | ❌ Crashes on NaN | ✅ Checks and skips NaN | Prevents crashes during startup/data gaps |
| **Stop Loss Protection** | ❌ Lost during TP update | ✅ Recreated before TP cancellation | **Critical**: Position always protected |
| **Error Recovery** | ❌ Script crashes | ✅ Continues running | Better uptime and reliability |
| **Log Readability** | ❌ Flooded with BarData | ✅ Concise error messages | Much easier debugging |

---

## Critical Issues Fixed in V3

### 1. **Stop Loss Disappearing** (CRITICAL)
- **V2**: Stop loss cancelled when TP is updated (bracket relationship)
- **V3**: Stop loss recreated as standalone before TP cancellation
- **Impact**: Position protection maintained at all times

### 2. **Script Crashes on NaN** (HIGH)
- **V2**: Crashes with `ValueError: cannot convert float NaN to integer`
- **V3**: Gracefully skips TP update when BB values are NaN
- **Impact**: Script runs continuously without crashes

### 3. **Log Flooding** (MEDIUM)
- **V2**: Exceptions print entire `bars` object (thousands of lines)
- **V3**: Concise error messages with traceback
- **Impact**: Logs remain readable and useful

---

## Code Statistics

| Metric | V2 | V3 | Change |
|--------|----|----|--------|
| **Total Lines** | ~3,286 | ~3,400 | +114 lines |
| **Exception Handlers** | 0 | 1 (in `on_bar_update`) | +1 |
| **NaN Checks** | 0 | 1 (in TP update) | +1 |
| **Stop Loss Protection Logic** | 0 | ~70 lines | +70 lines |

---

## Recommendation

**Use V3 for production trading** - It includes critical fixes that prevent:
1. Unprotected positions (stop loss disappearing)
2. Script crashes (NaN handling)
3. Unusable logs (exception handling)

V2 should only be used as a reference or if you need to understand the original implementation.

---

## Migration Notes

V3 is **backward compatible** with V2:
- Same parameter file format
- Same strategy logic
- Same entry/exit conditions
- Same order placement approach

The changes are **additive** (bug fixes and error handling), not architectural changes.


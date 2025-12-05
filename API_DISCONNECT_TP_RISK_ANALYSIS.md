# Critical Risk: TP Fill During API Disconnect

## The Problem

**Scenario:**
1. LONG position with:
   - Entry: Filled (+1 position)
   - Stop Loss: SELL @ $6874.50 (active, Submitted)
   - Take Profit: SELL @ $6883.75 (active, Submitted)

2. **API Disconnects**

3. **During Disconnect:**
   - TP fills at $6883.75
   - Position closes (goes to 0)
   - **BUT: Stop Loss order remains active on IB server!**

4. **After Reconnection:**
   - We detect position = 0
   - We call `cleanup_orphaned_orders()` to cancel stop
   - **BUT: There's a timing window!**

5. **The Risk:**
   - If price moves to $6874.50 BEFORE cleanup runs
   - Stop executes: SELL @ $6874.50
   - **This creates a SHORT position (-1)!**
   - We now have an unintended position

## Why This Happens

- **No OCA (One-Cancels-All)**: Without bracket orders or OCA groups, orders are independent
- **IB Behavior**: When TP fills, IB doesn't automatically cancel the stop
- **Timing Window**: Between reconnection and cleanup, stop can execute

## Current Protection

The code has `cleanup_orphaned_orders()` that:
- Checks if position = 0
- Cancels all active orders
- **BUT**: Only runs on reconnection and periodic checks

## The Gap

1. **On Every Bar Update**: We should check if position = 0 but stop is active
2. **Immediate Cancellation**: When TP fills, we should cancel stop immediately
3. **Reconnection Priority**: First thing after reconnect should be order cleanup

## Solution

### 1. Check on Every Exit Check
In `check_exits()`, verify position matches orders:
```python
# After checking if position closed
es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
has_open_position = any(abs(p.position) > 0 for p in es_positions)

if not has_open_position:
    # Position closed - cancel all protective orders immediately
    if stop_trade and stop_trade.isActive():
        ib.cancelOrder(stop_order)
    if tp_trade and tp_trade.isActive():
        ib.cancelOrder(tp_order)
```

### 2. Enhanced Cleanup on Reconnection
Make cleanup the FIRST thing after reconnect:
```python
# Immediately after reconnect
await asyncio.sleep(1)  # Minimal wait
cleanup_orphaned_orders()  # FIRST - cancel orphaned orders
# Then check positions, etc.
```

### 3. Periodic Verification
Check every bar update:
```python
# In check_exits() or on_bar_update()
es_positions = [p for p in ib.positions() if p.contract.conId == contract.conId]
has_open_position = any(abs(p.position) > 0 for p in es_positions)

if not has_open_position:
    # No position but orders active - cancel immediately
    cleanup_orphaned_orders()
```

### 4. Order Direction Validation
When checking orders, verify they match position direction:
```python
# If position is 0, any active stop/TP should be cancelled
# If position is LONG (+1), stop should be SELL
# If position is SHORT (-1), stop should be BUY
```

## Implementation Priority

1. **CRITICAL**: Check position on every bar update
2. **CRITICAL**: Cancel orders immediately when position = 0
3. **HIGH**: Enhanced cleanup on reconnection
4. **MEDIUM**: Order direction validation


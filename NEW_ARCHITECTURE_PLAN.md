# New Architecture Plan: Dynamic TP/SL with Reliable Order Management

## Problem Statement

We need:
- ✅ Dynamic TP updates (opposite BB TP)
- ✅ Dynamic SL updates (trailing stops)
- ✅ Reliable order management
- ✅ No duplicate orders
- ✅ No missing stops
- ✅ Simple state management

Current approach fails because:
- Manual order management is too complex
- State gets out of sync
- Error recovery creates more bugs
- `bracketOrder()` doesn't support dynamic updates

---

## Solution: Hybrid Architecture with State Machine

### Core Principle: **Entry with Bracket, Convert to Standalone for Updates**

1. **Entry Phase**: Use `ib.bracketOrder()` for reliable initial entry
2. **Conversion Phase**: After entry fills, convert to standalone orders
3. **Update Phase**: Update standalone orders independently
4. **State Machine**: Single source of truth with clear state transitions

---

## Architecture Design

### Phase 1: Entry (Use `bracketOrder()`)

```python
# Entry - Simple, reliable
bracket = ib.bracketOrder(action, qty, limitPrice=0.0, stopLossPrice=stop_price, takeProfitPrice=tp)
for o in bracket:
    ib.placeOrder(contract, o)

# Track as bracket initially
position_state = {
    'type': 'BRACKET',  # BRACKET or STANDALONE
    'bracket': bracket,  # IB bracket object
    'entry': bracket.entry,
    'stop': bracket.stopLoss,
    'tp': bracket.takeProfit,
    'direction': direction,
    'entry_price': entry_price,
    'position_dict': position_dict
}
positions.append(position_state)
```

**Benefits:**
- IB manages order relationships
- No PreSubmitted issues
- No duplicate orders
- Simple, reliable

### Phase 2: Conversion to Standalone (After Entry Fills)

```python
def convert_bracket_to_standalone(position_state):
    """
    Convert bracket orders to standalone orders after entry fills.
    This allows independent updates of stop and TP.
    """
    bracket = position_state['bracket']
    entry_trade = get_trade_by_permId(bracket.entry.permId)
    
    if not entry_trade or entry_trade.isActive():
        return False  # Entry not filled yet
    
    # Cancel bracket stop and TP (they're children of entry)
    # Place new standalone orders
    stop_order = StopOrder(
        action=bracket.stopLoss.action,
        totalQuantity=bracket.stopLoss.totalQuantity,
        stopPrice=bracket.stopLoss.auxPrice,
        tif='GTC',
        transmit=True  # Standalone, transmit immediately
    )
    
    tp_order = None
    if bracket.takeProfit:
        tp_order = LimitOrder(
            action=bracket.takeProfit.action,
            totalQuantity=bracket.takeProfit.totalQuantity,
            lmtPrice=bracket.takeProfit.lmtPrice,
            tif='GTC',
            transmit=True  # Standalone, transmit immediately
        )
    
    # Cancel old bracket orders
    ib.cancelOrder(bracket.stopLoss)
    if bracket.takeProfit:
        ib.cancelOrder(bracket.takeProfit)
    
    # Place new standalone orders
    ib.placeOrder(contract, stop_order)
    if tp_order:
        ib.placeOrder(contract, tp_order)
    
    # Update state
    position_state['type'] = 'STANDALONE'
    position_state['stop'] = stop_order
    position_state['tp'] = tp_order
    position_state['bracket'] = None  # No longer a bracket
    
    return True
```

**Benefits:**
- Clean conversion after entry
- Standalone orders can be updated independently
- No parent-child relationship issues

### Phase 3: Updates (Standalone Orders)

```python
def update_trailing_stop(position_state, new_stop_price):
    """
    Update trailing stop - simple because it's standalone.
    """
    if position_state['type'] != 'STANDALONE':
        return False
    
    old_stop = position_state['stop']
    
    # Place new stop first (ensure protection)
    new_stop = StopOrder(
        action=old_stop.action,
        totalQuantity=old_stop.totalQuantity,
        stopPrice=new_stop_price,
        tif='GTC',
        transmit=True
    )
    
    new_trade = ib.placeOrder(contract, new_stop)
    ib.sleep(0.5)  # Wait for submission
    
    # Verify new stop is Submitted
    if new_trade.orderStatus.status == 'Submitted':
        # Cancel old stop
        ib.cancelOrder(old_stop)
        position_state['stop'] = new_stop
        return True
    else:
        # New stop failed, keep old one
        ib.cancelOrder(new_stop)
        return False

def update_tp(position_state, new_tp_price):
    """
    Update TP - simple because it's standalone.
    """
    if position_state['type'] != 'STANDALONE':
        return False
    
    old_tp = position_state['tp']
    if not old_tp:
        # No TP, just create new one
        tp_order = LimitOrder(...)
        ib.placeOrder(contract, tp_order)
        position_state['tp'] = tp_order
        return True
    
    # Place new TP first
    new_tp = LimitOrder(
        action=old_tp.action,
        totalQuantity=old_tp.totalQuantity,
        lmtPrice=new_tp_price,
        tif='GTC',
        transmit=True
    )
    
    new_trade = ib.placeOrder(contract, new_tp)
    ib.sleep(0.5)
    
    if new_trade.orderStatus.status == 'Submitted':
        ib.cancelOrder(old_tp)
        position_state['tp'] = new_tp
        return True
    else:
        ib.cancelOrder(new_tp)
        return False
```

**Benefits:**
- Simple update logic
- No parent-child relationship issues
- Independent updates
- Easy to verify

---

## State Management: Single Source of Truth

### Position State Structure

```python
position_state = {
    # Type
    'type': 'BRACKET' | 'STANDALONE',
    
    # Orders (one source of truth)
    'bracket': bracket_object | None,  # Only if type == 'BRACKET'
    'entry': order_object,
    'stop': order_object,
    'tp': order_object | None,
    
    # Position info
    'direction': 1 | -1,
    'entry_price': float,
    'entry_time': datetime,
    'position_dict': dict,  # From strategy module
    
    # State tracking
    'entry_filled': bool,
    'converted': bool,
    'last_update': datetime
}
```

### Reconciliation Function (Single Point)

```python
def reconcile_positions():
    """
    Single function to reconcile positions[] with ib.trades() and ib.positions().
    Called periodically to ensure state is correct.
    """
    # Get actual positions from IB
    actual_positions = {p.contract.conId: p for p in ib.positions() if p.contract.conId == contract.conId}
    has_position = any(abs(p.position) > 0 for p in actual_positions.values())
    
    # Get actual orders from IB
    actual_orders = {t.order.permId: t for t in ib.trades() if t.contract.conId == contract.conId}
    
    # Reconcile each tracked position
    for position_state in positions[:]:
        entry_permId = position_state['entry'].permId
        
        # Check if entry filled
        entry_trade = actual_orders.get(entry_permId)
        if entry_trade and not entry_trade.isActive():
            position_state['entry_filled'] = True
            
            # Convert to standalone if still bracket
            if position_state['type'] == 'BRACKET' and not position_state['converted']:
                convert_bracket_to_standalone(position_state)
                position_state['converted'] = True
        
        # Check if position closed
        if not has_position:
            # Position closed, remove from tracking
            positions.remove(position_state)
            continue
        
        # Verify stop order is active
        if position_state['type'] == 'STANDALONE':
            stop_permId = position_state['stop'].permId
            stop_trade = actual_orders.get(stop_permId)
            
            if not stop_trade or not stop_trade.isActive():
                # Stop missing or cancelled - recreate
                recreate_stop(position_state)
        
        # Verify TP order is active (if exists)
        if position_state['tp']:
            tp_permId = position_state['tp'].permId
            tp_trade = actual_orders.get(tp_permId)
            
            if not tp_trade or not tp_trade.isActive():
                # TP missing or cancelled - check if should recreate
                if should_recreate_tp(position_state):
                    recreate_tp(position_state)
```

**Benefits:**
- Single reconciliation point
- Clear state transitions
- Easy to debug
- No scattered state checks

---

## Error Recovery: Targeted and Simple

### Instead of Multiple Complex Functions

**Old approach:**
- `protect_existing_positions()` - 200+ lines
- `ensure_stop_is_submitted()` - 150+ lines
- `cleanup_orphaned_orders()` - 100+ lines
- `check_and_recreate_tp_orders()` - 80+ lines

**New approach:**
- `reconcile_positions()` - Single function, ~100 lines
- `recreate_stop()` - Simple helper, ~20 lines
- `recreate_tp()` - Simple helper, ~20 lines

### Recreate Functions

```python
def recreate_stop(position_state):
    """
    Recreate missing stop order.
    Simple because we know the state.
    """
    stop_price = position_state['stop'].auxPrice
    direction = position_state['direction']
    qty = abs(position_state['stop'].totalQuantity)
    
    stop_action = 'SELL' if direction == 1 else 'BUY'
    new_stop = StopOrder(
        action=stop_action,
        totalQuantity=qty,
        stopPrice=stop_price,
        tif='GTC',
        transmit=True
    )
    
    ib.placeOrder(contract, new_stop)
    position_state['stop'] = new_stop

def recreate_tp(position_state):
    """
    Recreate missing TP order.
    Calculate new TP price from strategy.
    """
    # Get latest data
    latest_row = data.iloc[-1]
    
    # Calculate TP from strategy
    tp_price = calculate_tp_price(position_state, latest_row)
    
    direction = position_state['direction']
    qty = abs(position_state['entry'].totalQuantity)
    
    tp_action = 'SELL' if direction == 1 else 'BUY'
    new_tp = LimitOrder(
        action=tp_action,
        totalQuantity=qty,
        lmtPrice=tp_price,
        tif='GTC',
        transmit=True
    )
    
    ib.placeOrder(contract, new_tp)
    position_state['tp'] = new_tp
```

---

## Implementation Plan

### Step 1: Refactor Entry Logic
- Use `ib.bracketOrder()` for entry
- Track as `BRACKET` type initially
- Simple, reliable entry

### Step 2: Add Conversion Logic
- After entry fills, convert to standalone
- Cancel bracket orders, place standalone
- Update state to `STANDALONE`

### Step 3: Simplify Update Logic
- `update_trailing_stop()` - simple standalone update
- `update_tp()` - simple standalone update
- No parent-child relationship issues

### Step 4: Add Reconciliation
- Single `reconcile_positions()` function
- Called periodically (every bar update)
- Ensures state is correct

### Step 5: Simplify Error Recovery
- Remove complex functions
- Use simple recreate helpers
- Called from reconciliation

---

## Benefits of New Architecture

### 1. **Reliable Entry**
- Uses `bracketOrder()` - IB manages relationships
- No PreSubmitted issues
- No duplicate orders

### 2. **Dynamic Updates**
- Standalone orders after conversion
- Independent stop and TP updates
- No parent-child relationship issues

### 3. **Simple State Management**
- Single source of truth
- Clear state transitions
- Easy to debug

### 4. **Targeted Error Recovery**
- Single reconciliation function
- Simple recreate helpers
- Less code, fewer bugs

### 5. **Maintainable**
- Clear separation of concerns
- Easy to understand
- Easy to test

---

## Migration Path

### Phase 1: Add New Functions (No Breaking Changes)
- Add `convert_bracket_to_standalone()`
- Add `update_trailing_stop()` (new version)
- Add `update_tp()` (new version)
- Add `reconcile_positions()`

### Phase 2: Update Entry Logic
- Change `place_bracket_order()` to use `ib.bracketOrder()`
- Track as `BRACKET` type initially

### Phase 3: Update Exit Logic
- Use new `update_trailing_stop()` and `update_tp()`
- Add conversion check after entry fills

### Phase 4: Replace Error Recovery
- Replace `protect_existing_positions()` with `reconcile_positions()`
- Remove `ensure_stop_is_submitted()` (not needed)
- Remove `check_and_recreate_tp_orders()` (handled in reconciliation)

### Phase 5: Cleanup
- Remove old functions
- Clean up code
- Test thoroughly

---

## Code Structure

```
ib_deployment_v2.py
├── Entry Logic
│   └── place_bracket_order()  # Uses ib.bracketOrder()
│
├── Conversion Logic
│   └── convert_bracket_to_standalone()  # After entry fills
│
├── Update Logic
│   ├── update_trailing_stop()  # Simple standalone update
│   └── update_tp()  # Simple standalone update
│
├── State Management
│   ├── reconcile_positions()  # Single reconciliation point
│   └── Position state structure
│
└── Error Recovery
    ├── recreate_stop()  # Simple helper
    └── recreate_tp()  # Simple helper
```

---

## Key Differences from Current Approach

| Current | New |
|--------|-----|
| Manual entry with parentId | `bracketOrder()` for entry |
| Always manual orders | Bracket → Standalone conversion |
| Multiple state sources | Single source of truth |
| Complex error recovery | Simple reconciliation |
| Scattered state checks | Single reconciliation function |
| 500+ lines error recovery | ~150 lines total |

---

## Next Steps

1. **Review this plan** - Does it address all requirements?
2. **Implement Phase 1** - Add new functions alongside old ones
3. **Test conversion** - Ensure bracket → standalone works
4. **Test updates** - Ensure trailing stop and TP updates work
5. **Migrate gradually** - Replace old functions one by one

This architecture gives you:
- ✅ Reliable entry (bracketOrder)
- ✅ Dynamic updates (standalone orders)
- ✅ Simple state management
- ✅ Targeted error recovery
- ✅ Maintainable code


# PreSubmitted Stop Orders - Detailed Explanation & API Disconnect Protection

## What is PreSubmitted Status?

**PreSubmitted** is an Interactive Brokers order status that means:
- The order has been received by IB's system
- It is **NOT yet active** on the exchange
- It is waiting for a trigger condition to become active

### Why Stop Orders Stay in PreSubmitted

1. **Child Order Relationship**: When a stop is created as a child of an entry order (`parentId` set):
   - The stop stays PreSubmitted until the parent (entry) order is **filled**
   - Even after entry fills, it may remain PreSubmitted if IB thinks it needs to wait

2. **`whyHeld='trigger'`**: This indicates IB is waiting for:
   - Market to open (if placed outside trading hours)
   - A trigger condition to be met
   - Some other system condition

3. **`transmit=False`**: When a stop is part of a bracket order:
   - `transmit=False` means "don't transmit until parent is filled"
   - After parent fills, IB should transmit it, but sometimes it doesn't transition to Submitted

## The Critical Problem: API Disconnect Protection

### Current Risk
- **PreSubmitted orders are NOT active on the exchange**
- If the API disconnects, a PreSubmitted stop **will NOT execute** automatically
- The stop only becomes active when it transitions to **Submitted** status
- Manual checks in `check_exits()` won't work during API disconnect

### What We Need
- Stop orders must be in **Submitted** status (active on IB server)
- Stops must work independently of the API connection
- Trailing stop updates must maintain protection (new stop Submitted before old one cancelled)

## Solution: Force Stop Orders to Submitted Status

### Strategy
1. **After Entry Fills**: Verify stop is in Submitted status
2. **If Still PreSubmitted**: Cancel and recreate as standalone order (no `parentId`)
3. **For Trailing Stops**: Ensure new stop is Submitted before cancelling old one
4. **Verification Loop**: Check status and retry if needed

### Implementation Plan

#### 1. Post-Entry Fill Verification
After entry order fills, check stop status:
- If Submitted: ✅ Good, stop is active
- If PreSubmitted: ⚠️ Cancel and recreate as standalone

#### 2. Standalone Stop Order
When recreating:
- Remove `parentId` (make it standalone)
- Set `transmit=True` (transmit immediately)
- Verify it reaches Submitted status

#### 3. Trailing Stop Updates
When updating trailing stop:
- Place new stop order (standalone, `transmit=True`)
- Wait and verify it's Submitted
- Only then cancel old stop
- This ensures zero gap in protection

#### 4. Periodic Verification
Add periodic check (every 30 seconds):
- Verify all stop orders are Submitted
- If any are PreSubmitted, recreate them

## Code Changes Required

### 1. Add Function to Verify/Activate Stop Orders
```python
def ensure_stop_is_submitted(bracket, contract):
    """
    Ensure stop loss order is in Submitted status (active on IB server).
    If it's PreSubmitted, cancel and recreate as standalone order.
    This is CRITICAL for API disconnect protection.
    """
    stop_order = bracket.get('stopLoss')
    if not stop_order:
        return False
    
    # Find the trade for this stop order
    stop_trade = None
    for trade in ib.trades():
        if (trade.contract.conId == contract.conId and
            hasattr(stop_order, 'permId') and stop_order.permId != 0 and
            trade.order.permId == stop_order.permId):
            stop_trade = trade
            break
    
    if not stop_trade:
        logging.warning("Stop order trade not found")
        return False
    
    status = stop_trade.orderStatus.status if stop_trade.orderStatus else None
    why_held = getattr(stop_trade.orderStatus, 'whyHeld', '') if stop_trade.orderStatus else ''
    
    # If already Submitted, we're good
    if status == 'Submitted':
        logging.debug(f"Stop order is Submitted (active): {stop_order.auxPrice:.2f}")
        return True
    
    # If PreSubmitted, we need to activate it
    if status == 'PreSubmitted':
        logging.warning(f"Stop order is PreSubmitted (not active): {stop_order.auxPrice:.2f}, whyHeld: {why_held}")
        logging.warning("Recreating as standalone order to ensure API disconnect protection...")
        
        # Get stop details
        stop_price = getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', 0))
        direction = bracket.get('direction', 1)
        qty = abs(stop_order.totalQuantity)
        stop_action = 'SELL' if direction == 1 else 'BUY'
        
        # Create standalone stop order (no parentId, transmit=True)
        new_stop_order = StopOrder(
            action=stop_action,
            totalQuantity=qty,
            stopPrice=stop_price,
            tif='GTC',
            transmit=True  # Standalone, transmit immediately
        )
        
        try:
            new_trade = ib.placeOrder(contract, new_stop_order)
            ib.sleep(2)  # Wait for order to process
            
            # Verify new order is Submitted
            new_status = new_trade.orderStatus.status if new_trade.orderStatus else None
            if new_status == 'Submitted':
                logging.info(f"Stop order recreated and Submitted: {stop_price:.2f}")
                # Cancel old PreSubmitted order
                try:
                    ib.cancelOrder(stop_order)
                except:
                    pass
                # Update bracket with new order
                bracket['stopLoss'] = new_stop_order
                if hasattr(new_trade.order, 'permId'):
                    new_stop_order.permId = new_trade.order.permId
                return True
            else:
                logging.error(f"New stop order failed to reach Submitted status: {new_status}")
                return False
        except Exception as e:
            logging.error(f"Failed to recreate stop order: {e}")
            return False
    
    return False
```

### 2. Call After Entry Fill
In the entry fill handler, verify stop status:
```python
# After entry order fills
if entry_trade.orderStatus.status == 'Filled':
    # Verify stop is Submitted
    ensure_stop_is_submitted(bracket, contract)
```

### 3. Update Trailing Stop Logic
When updating trailing stop:
```python
# Place new stop (standalone, transmit=True)
new_stop_order = StopOrder(
    action=stop_action,
    totalQuantity=qty,
    stopPrice=new_stop,
    tif='GTC',
    transmit=True  # Standalone
)

new_trade = ib.placeOrder(contract, new_stop_order)
ib.sleep(2)

# Verify new stop is Submitted before cancelling old one
if new_trade.orderStatus.status == 'Submitted':
    # Now safe to cancel old stop
    ib.cancelOrder(old_stop_order)
    bracket['stopLoss'] = new_stop_order
else:
    logging.error("New stop not Submitted - keeping old stop active")
```

### 4. Periodic Verification
Add to main loop:
```python
# Every 30 seconds, verify all stops are Submitted
if time.time() - last_stop_verification > 30:
    for bracket in positions:
        ensure_stop_is_submitted(bracket, contract)
    last_stop_verification = time.time()
```

## Testing Checklist

- [ ] Entry fill: Stop transitions to Submitted
- [ ] PreSubmitted stop: Gets recreated as standalone
- [ ] Trailing stop: New stop Submitted before old one cancelled
- [ ] API disconnect: Stop executes independently
- [ ] Multiple positions: All stops verified
- [ ] Reconnection: Stops still Submitted after reconnect

## Risk Mitigation

1. **Zero Gap Protection**: New stop Submitted before old one cancelled
2. **Verification**: Periodic checks ensure stops stay Submitted
3. **Standalone Orders**: No dependency on parent orders
4. **Immediate Transmit**: `transmit=True` ensures immediate activation


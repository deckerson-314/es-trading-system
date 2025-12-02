# IB API Market Data Type Information

## Overview

The `reqMarketDataType()` function controls what type of market data you receive from Interactive Brokers. By default, IB provides **live data if you have subscriptions**, but you can explicitly control this.

---

## Market Data Types

| Type | Value | Description | Delay | Cost |
|------|-------|-------------|-------|------|
| **LIVE** | 1 | Real-time market data | None | Requires subscription |
| **FROZEN** | 2 | Last available price when market closes | None | Free |
| **DELAYED** | 3 | Delayed data (typically 15 minutes) | ~15 min | Free |
| **DELAYED-FROZEN** | 4 | Delayed data, frozen at close | ~15 min | Free |

---

## Default Behavior

**If `reqMarketDataType()` is NOT called:**
- IB API **defaults to LIVE data (type 1)** if you have market data subscriptions
- Falls back to **DELAYED data (type 3)** if you don't have subscriptions
- The API automatically selects based on your account's subscriptions

**You ARE likely receiving live data** if:
- Your account has market data subscriptions for ES futures
- You're seeing real-time price updates that match TWS
- Bars are updating in real-time (not 15 minutes behind)

---

## Why Explicitly Set `reqMarketDataType(1)`?

Even though IB defaults to live data, explicitly setting it provides:

1. **Explicit Intent**: Makes it clear in code that you want live data
2. **Error Detection**: If you request type 1 but don't have subscriptions, IB will return type 3 and you'll know via callback
3. **Prevents Accidental Changes**: If code elsewhere changes the data type, your explicit setting ensures live data
4. **Debugging**: Easier to verify what data type you're actually receiving

---

## How to Verify You're Receiving Live Data

### Method 1: Check TWS/Gateway
- In TWS, check if prices update in real-time
- Compare API timestamps with current time
- If API bars match TWS timestamps, you're getting live data

### Method 2: Use `marketDataTypeEvent` Callback
```python
def on_market_data_type(marketDataType):
    if marketDataType == 1:
        print("✅ Receiving LIVE data")
    elif marketDataType == 3:
        print("⚠️ Receiving DELAYED data (15-min delay)")
    
ib.marketDataTypeEvent += on_market_data_type
ib.reqMarketDataType(1)  # Request live data
```

### Method 3: Compare Bar Timestamps
- Check if latest bar timestamp matches current time (within 1 minute)
- Delayed data will be ~15 minutes behind

---

## ES Futures Market Data Subscriptions

For ES (E-mini S&P 500) futures, you typically need:

1. **CME Level 1** - Real-time quotes for CME Group futures
   - Cost: ~$10-15/month
   - Provides live bid/ask/last for ES futures

2. **CME Level 2** - Depth of market (optional)
   - Cost: Higher
   - Not needed for basic trading

**Note:** If you're paper trading (port 7497), you may still need subscriptions for live data, or you'll get delayed data.

---

## Current Implementation

### Before (Implicit):
```python
# No explicit market data type set
# IB defaults to live if subscribed, delayed otherwise
bars = ib.reqHistoricalData(...)
```

### After (Explicit):
```python
# Explicitly request live data
ib.reqMarketDataType(1)  # Request live data

# Subscribe to callbacks to verify
ib.marketDataTypeEvent += on_market_data_type

bars = ib.reqHistoricalData(...)
```

---

## What Happens If You Don't Have Subscriptions?

If you call `reqMarketDataType(1)` but don't have subscriptions:
- IB will **still provide data**, but it will be **DELAYED (type 3)**
- The `marketDataTypeEvent` callback will report type 3
- You'll see a warning in logs
- Data will be ~15 minutes behind real-time

**This is safe** - your code will still work, just with delayed data.

---

## Recommendations

### ✅ **Best Practice:**
1. **Explicitly set** `reqMarketDataType(1)` to request live data
2. **Subscribe to** `marketDataTypeEvent` callback to verify what you're receiving
3. **Log the data type** on startup and periodically
4. **Check TWS** to confirm you have market data subscriptions

### ⚠️ **If Receiving Delayed Data:**
- Check your IB account for market data subscriptions
- Verify subscriptions are active in TWS Account Management
- For ES futures, ensure CME Level 1 subscription is active
- Delayed data is fine for backtesting/development, but not for live trading

### ❌ **Don't:**
- Don't assume you're getting live data without verification
- Don't use delayed data for live trading (15-min delay is too much)
- Don't ignore the `marketDataTypeEvent` callback

---

## Testing

To test if you're receiving live vs delayed data:

1. **Compare timestamps:**
   ```python
   latest_bar_time = data.index[-1]
   current_time = datetime.now()
   delay = current_time - latest_bar_time
   print(f"Data delay: {delay}")
   # Live data: delay < 1 minute
   # Delayed data: delay ~15 minutes
   ```

2. **Check callback:**
   - The `on_market_data_type` callback will log the actual data type received
   - Look for "✅ Receiving LIVE market data" or "⚠️ RECEIVING DELAYED DATA"

3. **Compare with TWS:**
   - Open TWS and check ES price
   - Compare with your API's latest bar close price
   - If they match (within seconds), you have live data

---

## Summary

- **Default:** IB provides live data if you have subscriptions
- **Explicit Setting:** `reqMarketDataType(1)` ensures you request live data
- **Verification:** Use `marketDataTypeEvent` callback to confirm what you're receiving
- **If Delayed:** Check your market data subscriptions in IB account
- **For ES Futures:** Need CME Level 1 subscription for live data

The code now explicitly requests live data and logs what type you're actually receiving, so you can verify if you have the necessary subscriptions.


# IB API Retrieval Settings Analysis

## Current Settings in `ib_deployment_v2.py`

### `reqHistoricalData` Parameters Currently Used:

```python
bars = ib.reqHistoricalData(
    contract,              # ✅ Contract object (ES futures)
    endDateTime='',        # ✅ Empty = current time
    durationStr='5400 S',  # ✅ 5400 seconds = 90 minutes
    barSizeSetting='1 min',# ✅ 1-minute bars
    whatToShow='TRADES',   # ✅ Trade data (not bid/ask/midpoint)
    useRTH=False,          # ✅ Include pre-market and after-hours
    formatDate=1,          # ✅ Unix timestamp format
    keepUpToDate=True      # ✅ Real-time updates enabled
)
```

---

## Available Parameters NOT Currently Used

### 1. **Exchange Grouping vs Single Venue**

**Current Status:** NOT EXPLICITLY SET (uses default)

**Options:**
- **Exchange Grouping (Default):** IB aggregates data from multiple exchanges/venues for the same contract
  - For ES futures: Combines data from CME Globex and other venues
  - Provides consolidated volume and pricing
  
- **Single Venue:** Request data from a specific exchange only
  - More granular control
  - Can see venue-specific volume/pricing differences
  - Requires specifying `exchange` parameter in contract

**How to Use Single Venue:**
```python
# Single venue example
contract = Future('ES', '', 'CME', currency='USD')
# Or specify exchange in reqHistoricalData (if supported)
```

**Impact:** 
- Exchange grouping (current): Higher volume (aggregated), smoother prices
- Single venue: Lower volume (single exchange), may see venue-specific patterns

---

### 2. **`whatToShow` Options NOT Used**

**Current:** `'TRADES'` ✅

**Available Options:**
- `'TRADES'` ✅ **Currently Used** - Actual executed trades
- `'MIDPOINT'` ❌ **Not Used** - Midpoint between bid/ask (good for forex)
- `'BID'` ❌ **Not Used** - Bid prices only
- `'ASK'` ❌ **Not Used** - Ask prices only
- `'BID_ASK'` ❌ **Not Used** - Both bid and ask
- `'HISTORICAL_VOLATILITY'` ❌ **Not Used** - Historical volatility
- `'OPTION_IMPLIED_VOLATILITY'` ❌ **Not Used** - Implied volatility (options)
- `'YIELD_BID'` ❌ **Not Used** - Yield bid (bonds)
- `'YIELD_ASK'` ❌ **Not Used** - Yield ask (bonds)
- `'YIELD_BID_ASK'` ❌ **Not Used** - Both yield bid/ask
- `'YIELD_LAST'` ❌ **Not Used** - Last yield
- `'ADJUSTED_LAST'` ❌ **Not Used** - Adjusted last price (accounts for splits/dividends)
- `'SCHEDULE'` ❌ **Not Used** - Trading schedule

**Recommendation:** `'TRADES'` is correct for futures trading. Other options are for different asset types.

---

### 3. **`useRTH` Options**

**Current:** `False` ✅ (includes all hours)

**Options:**
- `False` ✅ **Currently Used** - Includes pre-market, regular hours, and after-hours
- `True` ❌ **Not Used** - Only Regular Trading Hours (9:30 AM - 4:00 PM ET for stocks)

**Impact:**
- `False` (current): More data, includes overnight trading (important for ES futures)
- `True`: Less data, only RTH (9:30 AM - 4:00 PM ET)

**Recommendation:** `False` is correct for ES futures which trade 23/5.

---

### 4. **`barSizeSetting` Options NOT Used**

**Current:** `'1 min'` ✅

**Available Options:**
- `'1 sec'` ❌ - 1-second bars (limited to 6 months old)
- `'5 secs'` ❌ - 5-second bars (limited to 6 months old)
- `'10 secs'` ❌ - 10-second bars (limited to 6 months old)
- `'15 secs'` ❌ - 15-second bars (limited to 6 months old)
- `'30 secs'` ❌ - 30-second bars (limited to 6 months old)
- `'1 min'` ✅ **Currently Used**
- `'2 mins'` ❌ - 2-minute bars
- `'3 mins'` ❌ - 3-minute bars
- `'5 mins'` ❌ - 5-minute bars
- `'10 mins'` ❌ - 10-minute bars
- `'15 mins'` ❌ - 15-minute bars
- `'20 mins'` ❌ - 20-minute bars
- `'30 mins'` ❌ - 30-minute bars
- `'1 hour'` ❌ - 1-hour bars
- `'2 hours'` ❌ - 2-hour bars
- `'3 hours'` ❌ - 3-hour bars
- `'4 hours'` ❌ - 4-hour bars
- `'8 hours'` ❌ - 8-hour bars
- `'1 day'` ❌ - Daily bars
- `'1 week'` ❌ - Weekly bars
- `'1 month'` ❌ - Monthly bars

**Note:** Bars ≤ 30 seconds are only available for data up to 6 months old.

**Recommendation:** Using `'1 min'` and resampling in code is flexible. Could request larger bars directly, but current approach allows strategy flexibility.

---

### 5. **`formatDate` Options**

**Current:** `1` ✅ (Unix timestamp)

**Available Options:**
- `1` ✅ **Currently Used** - Unix timestamp (seconds since epoch)
- `2` ❌ **Not Used** - ISO 8601 format (YYYYMMDD HH:MM:SS)

**Impact:** Minimal - just affects how dates are returned. Current format is fine.

---

### 6. **`keepUpToDate` Parameter**

**Current:** `True` ✅ (real-time updates)

**Options:**
- `True` ✅ **Currently Used** - Enables real-time bar updates via `updateEvent`
- `False` ❌ **Not Used** - One-time historical data request only

**Impact:** `True` is essential for live trading. `False` would only get initial historical data.

---

## Other IB API Methods NOT Currently Used

### 1. **`reqRealTimeBars`** ❌
- Alternative to `reqHistoricalData` with `keepUpToDate=True`
- Provides 5-second bars
- **Not Used:** We use `reqHistoricalData` with `keepUpToDate=True` instead

### 2. **`reqMktData`** ❌
- Real-time tick-by-tick data
- Can subscribe to specific tick types (last, bid, ask, volume, etc.)
- **Not Used:** We use bar data instead of tick data

### 3. **`reqHistoricalTicks`** ❌
- Tick-by-tick historical data
- More granular than bars
- **Not Used:** Bar data is sufficient for strategy

### 4. **`reqTickByTickData`** ❌
- Real-time tick-by-tick data
- More granular than bars
- **Not Used:** Bar data is sufficient for strategy

### 5. **`reqMarketDataType`** ❌
- Controls data type: Live (1), Frozen (2), Delayed (3), Delayed-Frozen (4)
- **Not Used:** Uses default (Live if subscribed, Delayed otherwise)

**Potential Use:** Could explicitly set to ensure live data:
```python
ib.reqMarketDataType(1)  # Live data (requires market data subscription)
ib.reqMarketDataType(3)  # Delayed data (free, 15-min delay)
```

---

## Contract Specification Options

### Current Contract:
```python
contract = Future('ES', '', 'CME', currency='USD')
```

**Options:**
- `exchange=''` (empty) ✅ **Currently Used** - IB selects best exchange
- `exchange='CME'` ❌ **Not Used** - Explicitly use CME only
- `exchange='GLOBEX'` ❌ **Not Used** - Use Globex electronic platform only

**Impact:** Empty exchange uses IB's default (usually best). Explicit exchange gives more control but may limit data sources.

---

## Summary of Recommendations

### ✅ **Currently Optimal Settings:**
- `whatToShow='TRADES'` - Correct for futures
- `useRTH=False` - Correct for ES futures (23/5 trading)
- `keepUpToDate=True` - Essential for live trading
- `barSizeSetting='1 min'` - Good granularity, resample in code

### ⚠️ **Could Consider:**
1. **Explicit Exchange:** Specify `exchange='CME'` or `exchange='GLOBEX'` if you want single-venue data
2. **Market Data Type:** Explicitly set `reqMarketDataType(1)` if you have live data subscription
3. **Larger Bar Sizes:** Could request `'2 mins'` directly instead of resampling, but current approach is more flexible

### ❌ **Not Needed:**
- Other `whatToShow` options (for stocks/forex/bonds)
- `reqRealTimeBars` (redundant with `keepUpToDate=True`)
- Tick-by-tick data (bar data is sufficient)
- `formatDate=2` (current format is fine)

---

## Volume Discrepancy Note

The 10x-20x volume difference between API and TWS is likely due to:
1. **API Filtering:** IB API excludes combo trades, block trades, and some derivative trades
2. **Exchange Grouping:** TWS may show aggregated volume from multiple venues
3. **Data Type:** TWS may include additional trade types not in API `TRADES` data

This is a known limitation of IB's API and cannot be resolved by changing settings.


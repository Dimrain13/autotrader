# Relative Volume Calculation - Critical Issues Found

## Date: December 5, 2025

---

## 🔴 PROBLEM IDENTIFIED

The relative volume calculation is **INCORRECT**. It's comparing today's volume to **yesterday's volume**, not to the **20-day average volume**.

---

## Current Issues

### ❌ Issue 1: Initial Estimate (Line 248-251)
```python
# WRONG: Comparing to yesterday, not average
prev_volume = int(snapshot.previous_daily_bar.volume)
avg_volume = prev_volume  # ← This is yesterday, NOT an average!
volume_ratio_estimate = current_volume / avg_volume
```

**Problem**: This is **relative to yesterday**, not relative to average daily volume.

**Example**:
- Yesterday's volume: 1M shares
- Today's volume: 5M shares
- Current calculation: 5M / 1M = **5x** ✓ (looks good)

BUT:
- 20-day average: 10M shares
- Correct calculation: 5M / 10M = **0.5x** ❌ (below average!)

**Impact**: Shows stocks as "high volume" when they're actually below average.

---

### ❌ Issue 2: Accurate Calculation Fails
```
ERROR - Error calculating accurate volume: 
{"message":"subscription does not permit querying recent SIP data"}
```

**Problem**: Alpaca paper trading doesn't allow access to historical bar data.

**Code** (line 384):
```python
bars = self.data_client.get_stock_bars(bars_request)  # ← Fails!
```

**Impact**: The "accurate" calculation never runs. Falls back to estimation.

---

### ❌ Issue 3: Fallback Still Wrong (Line 452)
```python
# Fallback uses yesterday's volume from initial estimate
avg_volume = result['avg_volume']  # ← Still yesterday's volume!
accurate_volume_ratio = projected_eod_volume / avg_volume
```

**Problem**: Even the fallback uses yesterday's volume as the denominator.

**Impact**: All volume calculations are relative to yesterday, not historical average.

---

## What Relative Volume SHOULD Be

### Correct Formula:
```
Relative Volume = Today's Volume / Average Daily Volume (20 days)
```

### Example (Correct Calculation):
```
Stock: TSLA

Last 20 days volume:
Day 1:  8M
Day 2:  12M
Day 3:  9M
...
Day 20: 11M

Average = (8M + 12M + 9M + ... + 11M) / 20 = 10M shares

Today's volume (so far): 15M shares (by 10am)
Projected EOD volume: 15M * (6.5 hours / 0.5 hours) = 195M shares

Relative Volume = 195M / 10M = 19.5x ← TRUE relative volume
```

### Current (Wrong) Calculation:
```
Yesterday's volume: 12M shares
Today's projected: 195M shares

Relative Volume = 195M / 12M = 16.25x ← WRONG (comparing to yesterday)
```

---

## Solution Options

### Option 1: Use Interactive Brokers API ✅ RECOMMENDED

**Why IB?**
- ✅ Already integrated for float data
- ✅ Provides historical bars without subscription
- ✅ FREE with IB account
- ✅ Accurate 20-day average volume

**Implementation**:
```python
# Get 20-day historical bars from IB
bars = ib_service.get_historical_bars(symbol, duration="20 D", bar_size="1 day")

# Calculate average volume
volumes = [bar['volume'] for bar in bars]
avg_volume_20d = sum(volumes) / len(volumes)

# Calculate relative volume
relative_volume = current_volume / avg_volume_20d
```

---

### Option 2: Use Financial Modeling Prep API

**Pros:**
- Simple REST API
- Provides average volume directly

**Cons:**
- 250 API calls/day limit
- Another service dependency

---

### Option 3: Better Estimation Method

**Current estimation**: Yesterday's volume
**Better estimation**: Use market cap + price to estimate typical volume

**Formula**:
```python
# Stocks with similar price/market cap have similar volume patterns
if price < 5:
    typical_volume = 5_000_000 - 20_000_000
elif price < 10:
    typical_volume = 2_000_000 - 10_000_000
else:
    typical_volume = 1_000_000 - 5_000_000

# Then compare
relative_volume = current_volume / typical_volume
```

**Pros**: No API calls, always available
**Cons**: Still an estimate, less accurate

---

## Recommended Fix

**Use Interactive Brokers for Relative Volume**

Same approach as float data:
1. Try IB API for 20-day average volume
2. Cache result (volume averages don't change much)
3. Fallback to better estimation if IB unavailable

### Benefits:
- ✅ Accurate 20-day average
- ✅ No additional API costs
- ✅ Leverages existing IB integration
- ✅ Caching makes it fast
- ✅ Works outside market hours

---

## Implementation Plan

### Step 1: Add Volume Method to IB Service

```python
def get_average_volume(self, symbol: str, days: int = 20) -> Dict:
    """
    Get average daily volume for last N days
    
    Returns:
    {
        "symbol": "AAPL",
        "avg_volume_20d": 75000000,
        "current_volume": 85000000,
        "relative_volume": 1.13,
        "data_date": "2025-12-05"
    }
    """
```

### Step 2: Update Scanner Service

Replace current volume calculation with IB data:

```python
# Try IB for accurate average volume
if IB_AVAILABLE and ib_service.use_ib_for_volume:
    volume_data = ib_service.get_average_volume(symbol)
    if volume_data:
        avg_volume_20d = volume_data['avg_volume_20d']
        relative_volume = current_volume / avg_volume_20d
```

### Step 3: Add Caching

Cache average volume (updates slowly):
- Cache duration: 24 hours (volume average doesn't change much)
- Refresh daily

### Step 4: Better Fallback

If IB unavailable, use better estimation:

```python
# Fallback: Use market cap + price-based estimation
estimated_avg_volume = estimate_typical_volume(price, market_cap)
relative_volume = current_volume / estimated_avg_volume
```

---

## Testing the Fix

### Verify Correct Calculation

```python
# Test Case
symbol = "AAPL"

# Get 20-day data
volume_data = ib_service.get_average_volume("AAPL", days=20)

# Should return:
{
    "symbol": "AAPL",
    "avg_volume_20d": 75000000,      # Average of last 20 days
    "volume_history": [65M, 80M, 70M, ...],  # Last 20 days
    "current_volume": 85000000,       # Today so far
    "relative_volume": 1.13,          # 85M / 75M = 1.13x
    "hours_into_day": 2.5,
    "projected_eod_volume": 220000000 # Projection
}
```

### Compare Old vs New

**Old (Wrong)**:
```
Symbol: TSLA
Today's volume: 5M (by 10am)
Yesterday's volume: 3M
Relative Volume: 5M / 3M = 1.67x ❌
```

**New (Correct)**:
```
Symbol: TSLA
Today's volume: 5M (by 10am)
20-day average: 8M
Relative Volume: 5M / 8M = 0.625x ✓
```

---

## Impact Assessment

### Current State (Before Fix):

**Scanner Criteria**: "5x relative volume"
- Actually measuring: 5x yesterday's volume
- What it should measure: 5x average daily volume

**Example Stock**:
- Today: 10M shares
- Yesterday: 2M shares (low day)
- 20-day average: 8M shares

**Current calculation**: 10M / 2M = **5.0x** ✓ (passes filter)
**Correct calculation**: 10M / 8M = **1.25x** ❌ (should fail filter)

**Result**: Scanner is showing stocks that aren't actually high-volume!

---

### After Fix:

- Relative volume calculated correctly vs 20-day average
- Fewer false positives in scanner
- More accurate trading signals
- Better trade quality

---

## User Impact

### What User Sees Now (Wrong):
```
TSLA: 5.2x volume  ← (vs yesterday)
AAPL: 3.8x volume  ← (vs yesterday)
NVDA: 6.1x volume  ← (vs yesterday)
```

### What User Should See (Correct):
```
TSLA: 1.2x volume  ← (vs 20-day average)
AAPL: 0.9x volume  ← (below average!)
NVDA: 2.3x volume  ← (vs 20-day average)
```

**Difference**: Many stocks currently shown as "high volume" are actually below average!

---

## Priority: HIGH 🔴

This affects the core scanner logic. Without accurate relative volume:
- ❌ Scanner shows wrong stocks
- ❌ False signals for trading
- ❌ Can't trust volume criterion
- ❌ Strategy effectiveness reduced

---

## Next Steps

1. Implement IB volume data fetching
2. Add caching layer (24-hour cache)
3. Update scanner to use real averages
4. Add better fallback estimation
5. Test with real market data
6. Verify scanner results improve

---

## Summary

**Current State**: ❌ **BROKEN**
- Comparing to yesterday's volume (not average)
- Alpaca historical data not available
- All stocks showing inflated relative volume

**Fix Needed**: ✅ Use IB API for 20-day average volume
- Accurate historical data
- Proper relative volume calculation
- Cached for performance

**Priority**: 🔴 **HIGH** - Core functionality issue


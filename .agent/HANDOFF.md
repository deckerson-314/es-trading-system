# ES Trading System — Agent Handoff Notes
> **Last Updated:** 2026-03-27 21:45 ET
> **Updated By:** Conversation c8d89c7b-292b-4c3d-99a6-22b0f6eb4036

---

## Current Session Summary

### Objective
Reconcile paper-trading Trend strategy trades with backtester output using the comparison tool (`compare_paper_backtest_trend.py`).

### Issue 1: Comparison Tool Data Contamination (FIXED)
**Problem:** `compare_paper_backtest_trend.py` was feeding raw `live_data.csv` (containing 15 non-OHLCV columns from Bollinger strategy) to `TrendStrategy.calculate_indicators()`. The `dropna()` wiped ALL rows.

**Fix:** Added OHLCV-only extraction in `compare_paper_backtest_trend.py`.

### Issue 2: Double-Entry Bug (FIXED — CRITICAL)
**Problem:** `ensure_connected_and_subscribed()` in `main.py` was stacking `bars_obj.updateEvent` handlers. When a data stall (>60s) or reconnection triggered the function, the old handler wasn't cleared (because `cancelHistoricalData()` failed silently). Both old and new handlers then fired on each bar, causing `check_entries()` to be called twice → 2 market orders per signal.

**Evidence:** Position tracking confirmed fills 1-28 (09:35-10:53) are clean ±1 contract, then fills 29+ hit ±2 on every entry starting at 11:07:06.

**Fixes Applied:**
1. `main.py` line 405-445: Clear `bars_obj.updateEvent.clear()` BEFORE cancelling subscription. Old handler is removed regardless of whether cancel succeeds.
2. `core/execution.py` line 30-37: Added 30-second dedup guard — if `check_entries()` is called again within 30s of a placed order, the second call is blocked with a warning log.

### Issue 3: No Timezone Mismatch (Confirmed)
Forensic analysis confirmed both `live_data.csv` (Eastern with offset) and `live_trades.csv` (naive Eastern) correctly align after the backtest pipeline's `pd.to_datetime(utc=True)` → `tz_convert('US/Eastern')` → `tz_localize(None)` conversion. Donchian signals fire at the correct completed bars relative to paper trade times.

### Files Modified
- `main.py` — Fixed event handler stacking in `ensure_connected_and_subscribed()`
- `core/execution.py` — Added 30-second entry dedup guard
- `compare_paper_backtest_trend.py` — Added OHLCV-only extraction

### Files Created
- `debug_compare.py` — Forensic diagnostic (signal chain trace)
- `debug_tz.py` — Timezone forensics
- `debug_fills.py` — Fill analysis and duplicate detection
- `debug_double_entry.py` — Position tracking (net position over time)
- `debug_signal_alignment.py` — Signal cross-reference at paper trade times
- `debug_bt_trades.py` — Backtest trade output analysis

---

## Next Steps for Future Sessions

1. **Verify fix works:** Restart the paper bot and confirm no more doubled fills. Look for "Cleared old bar event handlers" and "handler stacking guard" messages in logs.

2. **Re-run comparison:** After fix verification, re-run `compare_paper_backtest_trend.py` with clean (non-doubled) fill data to get accurate match counts.

3. **Fix trade pairing in comparison tool:** `parse_live_trades_csv()` uses `RealizedPNL == 0` to identify entries — unreliable. Should use sequential BOT/SLD pairing or PermID-based grouping.

4. **Constrain backtest date range:** Filter backtest trades to the paper bot's active window to reduce "BT ONLY" noise.

5. **Revert to production params:** Once signal matching is satisfactory, revert from `trend_strategy_params_testing_ultra_high.csv` to `trend_strategy_params_best_sortino.csv`.

---

## Active Configuration
- **Strategy:** Trend (Donchian breakout)
- **Parameters:** `strategies/trend/parameters/trend_strategy_params_testing_ultra_high.csv` (TESTING ONLY — 1-min, all filters disabled)
- **Data:** `paper_logs/live_data.csv` (15K+ bars, Dec 2025 - present)
- **Trades:** `paper_logs/live_trades.csv` (346 total fills, 61 today — 14 clean + 16 doubled + 1 orphan)
- **Paper bot:** Running on port 7497, needs restart to pick up double-entry fix

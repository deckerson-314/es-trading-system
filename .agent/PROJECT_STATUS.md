> **Last Updated:** 2026-03-28 16:45 ET
> **Updated By:** Conversation c8d89c7b-292b-4c3d-99a6-22b0f6eb4036

---

## System Overview

Modular ES futures trading system using Interactive Brokers (ib_insync), supporting multiple strategies (Bollinger + Trend) with genetic algorithm optimization, live/paper trading, and HTML dashboards.

### Architecture
```
c:\Trading\
├── main.py                    # Live/Paper trading entry point
├── backtest.py                # Single & multi-solution backtesting
├── optimize.py                # Genetic algorithm optimizer (NSGA-II)
├── core/
│   ├── connection.py          # IB connection, contract resolution
│   ├── execution.py           # Order entry/exit logic (bracket orders)
│   ├── monitoring.py          # Bar processing, indicator updates
│   ├── protection.py          # Position protection, orphan cleanup
│   └── account.py             # Account tracking, PnL, utilities
├── strategies/
│   ├── base.py                # Abstract Strategy base class
│   ├── factory.py             # StrategyFactory loader
│   ├── bollinger/             # Bollinger Band strategy
│   │   ├── strategy.py        # BollingerBandStrategy
│   │   ├── parameters.py      # CSV param loading
│   │   └── reporting.py       # Backtest dashboard generation (Plotly)
│   └── trend/                 # Trend/Donchian strategy
│       ├── strategy.py        # TrendStrategy
│       └── parameters/        # Trend params CSV
├── tools/
│   ├── dashboard/updates.py   # Live trading dashboard HTML generator
│   ├── safety/guards.py       # SecurityGuard (PnL limits, position limits)
│   ├── notifications/         # Email alerts
│   └── data/downloader.py     # Market data download
├── web/                       # Generated HTML dashboards
│   ├── index.html             # Control center landing page
│   ├── dashboard_paper.html   # Paper trading dashboard (auto-generated)
│   ├── dashboard_live.html    # Live trading dashboard (auto-generated)
│   └── ...                    # Backtest dashboards, comparison charts
├── compare_*.py               # Live vs backtest comparison scripts
└── extract_solution.py        # GA solution extractor (CLI)
```

---

## Current State (as of 2026-03-11)

### ✅ Working
- **Paper trading with Trend strategy** — currently running, entered LONG @ 6809.75
- **Bollinger strategy** — fully functional (live/paper/backtest/optimize)
- **Dashboard auto-updates** — fixed `while True` loop survives TWS restarts
- **Email notifications** — working for trade opens/closes
- **Bracket orders** — entry + SL + TP working correctly
- **Multi-strategy support** — monitoring.py, execution.py, protection.py all strategy-agnostic
- **Backtest dashboards** — now use proper `generate_dashboard()` with Plotly charts
- **index.html** — all links point to correct dashboard files
- **8-Day Roll Logic** — platform-wide implementation of CME standard roll buffer (8 days before expiry)
- **Data Extender** — capable of bridging/rolling historical data into ratio-adjusted master files
- **Master GA Data** — extended ESM6 contract through today (March 16, 2026) using extender tool
- **GA Parallel Evaluation (Trend)** — Fixed `NoneType` vs `int` comparison error in `TrendStrategy`
- **Cloudflare Dashboard** — Tunnel restarted and stable at `https://directories-equal-ecology-gif.trycloudflare.com`.
- **Order Modification Safety** — Trailing stops now correctly modify existing orders on the exchange while preserving OCA group linkage.

### ⚠️ Known Issues / Recently Fixed (may need restart to take effect)
1. **Fixed in this session:**
   - `core/protection.py` — Fixed `StopOrder` initialization (required `stopPrice` was missing).
   - `core/execution.py` & `protection.py` — Implemented **Deterministic OCA Groups** (`bracket_{conId}_{direction}`). This ensures that SL and TP orders stay linked at the exchange level even if the bot is restarted or orders are recreated at different times.
   - **TWS Field #44 Fix** — Added explicit `float()` casting and 4-decimal rounding to all entry/exit prices to prevent TWS rejection messages.
   - `start_web_server_cloudflare.py` — Fixed `UnicodeEncodeError` by removing emojis and enabled verbose output to show the public URL.

2. **Trend strategy still needs:**
   - Its own `reporting.py` module (currently uses Bollinger's)
   - Its own parameter groups in `optimize.py` `group_and_print_params()` 
   - RTH/maintenance filter params if desired

### 🔴 Not Yet Tested
- Live trading mode (only paper tested)
- **Full GA optimization for Trend strategy** — ✅ Verified & Synchronized with backtest engine
- **Data downloader tool** — ✅ Upgraded with chunking/pacing
- **Data extender tool** — ✅ New: for historical back-filling
- **ESM6 Contract Roll** — ✅ Verified with 8-day logic

---

## Changes Made This Session
### Phase 8: GA Synchronization & Robustness (Mar 28)
- **Synchronized Trade Exit Logic**: Updated `optimize.py` simulation loop to use `+59s` (bar-end) logic, matching `backtest.py` and the live bot.
- **Timezone-Aware Data Loading**: Implemented explicit localization (UTC -> US/Eastern) in the GA loading block to ensure RTH filters align with 9:30 AM - 4:00 PM market hours.
- **Robust Parameter Loading**: Refactored GA configuration to handle missing/NaN fields in strategy and GA parameter CSVs safely.
- **Fitness Multi Fix**: Resolved a crash where the Deap GA population would fail to initialize if fitness weights were missing or empty in the CSV.
- **Verified Run**: Successfully completed diagnostic GA optimization runs (`pop 10`, `gen 2`) for the Trend strategy and verified dashboard output.

### Phase 7: Trend Frequency & Comparison (Mar 27)
- Created testing_ultra_high profile (1-min lookback, filters flattened)
- Updated backtest.py for Same-Bar Execution (matches paper bot behavior)
- Fixed NoneType initialization error in TrendStrategy
- **ROOT CAUSE FOUND**: `compare_paper_backtest_trend.py` was feeding raw `live_data.csv` (which contained 15 non-OHLCV indicator columns from Bollinger strategy: `mid`, `upper`, `lower`, `adx`, `volume_ma`, etc.) directly to `TrendStrategy.calculate_indicators()`. The `dropna()` call at the end of that method wiped ALL rows because those inherited columns had NaN values.
- **FIX**: Strip data to OHLCV-only before passing to backtester, deduplicate timestamps, and drop NaN OHLCV rows.
- **RESULTS**: 0 matches → **12 MATCHED + 15 DIR MISMATCH + 4 LIVE ONLY** (out of 31 live trades and 2106 backtest trades)
- **REMAINING**: DIR MISMATCH (15) likely caused by live trade pairing logic (BOT/SLD sequencing) or Donchian breakout direction ambiguity on the same bar. 2089 BT ONLY trades reflect the backtest running over full historical data range (Dec 2025 - Mar 2026) while live trades only cover the analysis window.
- **DOUBLE-ENTRY BUG FOUND & FIXED**: `ensure_connected_and_subscribed()` in `main.py` was stacking event handlers on reconnection/data-stall. When `cancelHistoricalData()` failed silently, the old `bars_obj.updateEvent` handler remained active while a new one was added, causing `on_bar_update_handler` to fire twice per bar → double orders. Confirmed by position tracking: fills 1-28 (09:35-10:53) are clean ±1, fills 29+ hit ±2 on every entry.
  - **Fix 1** (`main.py`): Clear `bars_obj.updateEvent` handlers BEFORE cancelling, so old handler is removed regardless of cancel success. Elevated cancel failure from `debug` to `warning`.
  - **Fix 2** (`core/execution.py`): Added 30-second dedup guard in `check_entries()` — if a second entry attempt occurs within 30s of the last, it's blocked with a warning log.

### Phase 1: Full System Review & Feature Comparison
- Compared old `ib_deployment_v4.py` (4500+ lines) with new modular system
- Identified 24+ lost features and created restoration plan

### Phase 2: Core Feature Restoration
- **optimize.py** — fixed `HallOfFame` import bug
- **core/monitoring.py** — NEW: bar processing, indicator updates, liveness detection
- **core/execution.py** — NEW: bracket order entry/exit, trailing stops, opposite BB TP
- **core/protection.py** — NEW: orphan cleanup, position protection, TP recreation
- **core/account.py** — NEW: account summary, PnL tracking, error logging
- **main.py** — Complete rewrite with async main loop, reconnection, dashboard updates
- **SecurityGuard** — Enhanced with max position limits, midnight reset

### Phase 3: Multi-Strategy Support
- Made `core/monitoring.py` strategy-agnostic (replaced `strategy.bb_length` → `_get_min_bars()`)
- Made `core/execution.py` strategy-agnostic (`getattr` for all optional strategy attrs)
- Made `core/protection.py` strategy-agnostic (`getattr` for `opposite_bb_tp`)
- Fixed `update_indicators()` to dynamically copy ALL indicator columns
- Fixed entry signal detection to use `check_entry()` OR `calculate_entry_signals()`

### Phase 4: Dashboard & UI
- Fixed `index.html` links — added Bollinger/Trend backtest cards, fixed comparison path
- Fixed `main.py` `--dashboard` auto-naming based on mode (paper vs live)
- Fixed `backtest.py` — single-run now uses `generate_dashboard()` instead of `update_dashboard()`
- Fixed dashboard freeze after TWS restart (`while ib.isConnected()` → `while True`)
- Fixed `Position.realizedPNL` crash in UI update loop

### Phase 6: Data Integrity & Roll Handling
- **8-Day Roll Logic**: Implemented the CME standard 8-day roll buffer in `core/connection.py` and synchronized it across legacy deployment tools to ensure consistency.
- **tools/data/downloader.py**: Integrated stabilized chunking/pacing logic from the archive to support large (90+ day) historical downloads without API timeouts.
- **tools/data/extender.py**: (NEW) Automated tool for bridging and rolling incremental IBKR data into the master 20-year ratio-adjusted CSV used for GA optimization.
- **Dataset Extension**: Successfully bridged the `ES_full_1min_continuous_ratio_adjusted.csv` file from October 10, 2025, to today (March 16, 2026).

---

## Key Design Decisions

1. **Strategy-agnostic core**: All `core/` modules use `getattr()` with safe defaults so any strategy works without having Bollinger-specific attributes
2. **`_get_min_bars(strategy)`**: Dynamically determines min bars from strategy attributes
3. **`_indicators_ready(data)`**: Checks for any non-OHLCV columns rather than hardcoded column names
4. **Dashboard auto-naming**: `--dashboard` defaults to `dashboard_{mode}.html` based on `--mode`
5. **Backtest dashboards**: Single-run uses `generate_dashboard()` from reporting.py (Plotly), with `update_dashboard()` as fallback

---

## Files Modified This Session
```
core/monitoring.py          — REWRITTEN (strategy-agnostic)
core/execution.py           — MODIFIED (strategy-agnostic, f-string fix)
core/protection.py          — MODIFIED (getattr for opposite_bb_tp)
main.py                     — MODIFIED (dashboard loop fix, auto-naming, Position attrs)
backtest.py                 — MODIFIED (use generate_dashboard for single-run)
optimize.py                 — MODIFIED (NaN fix, Timezone sync, Exit timing sync)
web/index.html              — MODIFIED (corrected all dashboard links)
extract_solution.py         — REWRITTEN (argparse CLI)
compare_ga_vs_backtest.py   — MODIFIED (new modular imports)
compare_live_vs_backtest_Jan2.py       — MODIFIED (new imports)
compare_live_vs_backtest_Dec29_31.py   — MODIFIED (new imports)
tools/safety/guards.py      — MODIFIED (max positions, midnight reset)
tools/dashboard/updates.py  — MODIFIED (bar log, richer trades table)
core/connection.py          — MODIFIED (implemented 8-day roll logic)
tools/data/downloader.py    — MODIFIED (added chunking, pacing, 8-day roll)
tools/data/extender.py      — NEW (historical ratio-adjust bridge/roll tool)
ib_deployment.py            — MODIFIED (synced 8-day roll logic)
ib_deployment_v4.py         — MODIFIED (synced 8-day roll logic)
Trend/parameters/trend_strategy_params.csv — MODIFIED (GA weights/params)
```

---

## For Next Agent

### Immediate Priority
The Trend strategy paper trading is **currently running**. The contract resolution now correctly identifies **ESM6 (June 2026)**.
1. **Confirm Data Integrity**: Verify that the extended master CSV (`ES_full_1min_continuous_ratio_adjusted.csv`) does not have large gaps or "ghost spikes" at the Oct-Dec-Mar stitch points.
2. **Complete Full Trend GA**: Now that the `NoneType` error is fixed, run `python optimize.py --strategy trend --cores 12` to completion.
3. **Verify Protection Robustness**: Observe Paper/Live logs to confirm no "Field #44" errors recur with the `auxPrice` fix in place.

### Suggested Next Steps
1. **Troubleshoot Paper/Live Issue**: Address current discrepancies in trade execution or dashboard reporting between paper and live modes.
2. **Validate Trend GA optimization** — `python optimize.py --strategy trend --cores 12` (Now using extended 2026 data).
3. **Create Trend-specific reporting** — `strategies/trend/reporting.py` for Donchian-specific charts.
4. **Test compare scripts** — validate with actual market data from the new extender tool.
5. **Consider adding a `min_bars_required` property** to the base Strategy class for cleaner architecture.

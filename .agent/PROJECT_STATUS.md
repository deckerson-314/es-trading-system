> **Last Updated:** 2026-04-03 17:50 ET
> **Updated By:** Conversation (Functional Test Plan Expansion)

---

## System Overview

Modular ES futures trading system using Interactive Brokers (ib_insync), supporting multiple strategies (Bollinger + Trend) with genetic algorithm optimization, live/paper trading, and HTML dashboards.

### Architecture
```
c:\Trading\
├── main.py                    # Live/Paper trading entry point
├── backtest.py                # Single & multi-solution backtesting
├── optimize.py                # Genetic algorithm optimizer (NSGA-II)
├── STRATEGY_FUNCTIONAL_TEST_PLAN.md # Blueprints for Section 4: Functional Verification
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
│   ├── trend/                 # Trend/Donchian strategy
│   │   ├── strategy.py        # TrendStrategy
│   │   └── parameters/        # Trend params CSV
├── tools/
│   ├── dashboard/updates.py   # Live trading dashboard HTML generator
│   ├── safety/guards.py       # SecurityGuard (PnL limits, position limits)
│   ├── notifications/         # Email alerts
│   └── data/downloader.py     # Market data download
├── web/                       # Generated HTML dashboards
├── compare_*.py               # Live vs backtest comparison scripts
└── extract_solution.py        # GA solution extractor (CLI)
```

---

## Current State (as of 2026-04-03)

### ✅ Working
- **Paper trading with Trend strategy** — currently running, entered LONG @ 6809.75
- **Bollinger strategy** — fully functional (live/paper/backtest/optimize)
- **Dashboard auto-updates** — fixed `while True` loop survives TWS restarts
- **Email notifications** — working for trade opens/closes
- **Bracket orders** — entry + SL + TP working correctly
- **Multi-strategy support** — monitoring.py, execution.py, protection.py all strategy-agnostic
- **Backtest dashboards** — now use proper `generate_dashboard()` with Plotly charts
- **8-Day Roll Logic** — platform-wide implementation of CME standard roll buffer (8 days before expiry)
- **Data Extender** — capable of bridging/rolling historical data into ratio-adjusted master files
- **Cloudflare Dashboard** — Tunnel restarted and stable at `https://directories-equal-ecology-gif.trycloudflare.com`.
- **Order Modification Safety** — Trailing stops now correctly modify existing orders on the exchange while preserving OCA group linkage.
- **Strategy Functional Test Plan** — Comprehensive blueprint completed (April 3).

### ⚠️ Known Issues / Recently Fixed (may need restart to take effect)
1. **Fixed in this session (Apr 3):**
   - Expanded `STRATEGY_FUNCTIONAL_TEST_PLAN.md` with:
     - **Three Pillar Approach**: Truth Table (Synthetic), Action Log (Backtest), Shadow Auditor (Live).
     - **Design of Experiments (DoE)**: Grid-based filter stress testing.
     - **Exit & Management Verification**: Trailing stop "Ratchet" and "Delay" tests.

2. **Trend strategy still needs:**
   - Its own `reporting.py` module (currently uses Bollinger's)
   - Its own parameter groups in `optimize.py` `group_and_print_params()` 

### 🔴 Not Yet Tested
- Live trading mode (only paper tested)
- **Full GA optimization for Trend strategy** — ✅ Verified & Synchronized with backtest engine
- **Data downloader tool** — ✅ Upgraded with chunking/pacing
- **Data extender tool** — ✅ New: for historical back-filling
- **ESM6 Contract Roll** — ✅ Verified with 8-day logic

---

## Changes Made This Session
### Phase 9: Functional Verification & Test Bench Architecture (Apr 3)
- **Defined the Three Pillars**:
    - **Truth Table**: Synthetic unit testing for mathematical gate precision.
    - **Action Log**: Explanatory backtest output to record exactly why historical signals were rejected.
    - **Shadow Auditor**: Real-time monitor to audit "Live vs Backtest" data interaction.
- **Implementation of DoE logic**: Designed a stress-testing framework to systematically verify filter interactions (`AND` logic gates, `OFAT` isolation).
- **Exit Logic Audit**: Expanded the plan to include functional verification for Trailing Stops (Ratchet/Delay), Take Profits, and Support-based exits.
- **Environmental Parity**: Updated success criteria to require identical results between vectorized backtests and bar-by-bar live simulation.

### Phase 8: GA Synchronization & Robustness (Mar 28)
- **Synchronized Trade Exit Logic**: Updated `optimize.py` simulation loop to use `+59s` (bar-end) logic, matching `backtest.py` and the live bot.
- **Timezone-Aware Data Loading**: Implemented explicit localization (UTC -> US/Eastern) in the GA loading block to ensure RTH filters align with 9:30 AM - 4:00 PM market hours.
- **Robust Parameter Loading**: Refactored GA configuration to handle missing/NaN fields in strategy and GA parameter CSVs safely.
- **Fitness Multi Fix**: Resolved a crash where the Deap GA population would fail to initialize if fitness weights were missing or empty in the CSV.

---

## Key Design Decisions

1. **Strategy-agnostic core**: All `core/` modules use `getattr()` with safe defaults so any strategy works without having Bollinger-specific attributes
2. **`_get_min_bars(strategy)`**: Dynamically determines min bars from strategy attributes
3. **`_indicators_ready(data)`**: Checks for any non-OHLCV columns rather than hardcoded column names
4. **The "Truth Table" Approach**: Testing the logic in isolation from market data to ensure 100% precision before running GA.

---

## Files Modified This Session
```
STRATEGY_FUNCTIONAL_TEST_PLAN.md — UPDATED (Three Pillars, DoE, Exit Verification)
.agent/PROJECT_STATUS.md          — UPDATED (Latest Apr 3 Status)
.agent/HANDOFF.md                 — UPDATED (Latest Apr 3 Status)
```

---

## For Next Agent

### Immediate Priority
The Trend strategy paper trading is **currently running**.
1. **Implement Pillar A (Truth Table)**: Create `tests/test_strategy_v5_functional.py` to generate artificial candles and verify the "Truth Table" for all entry filters.
2. **Implement Pillar B (Action Log)**: Add a `verbose` flag to `TrendStrategy` to output "Reason for Rejection" during backtests.
3. **Audit Trailing Stops**: Build a synthetic scenario to prove the "Ratchet" logic for the Trailing Stop works as expected during a pullback.

### Suggested Next Steps
1. **Develop Rejection Gallery**: Create the `rejection_gallery.py` tool to visualize these "Near-Misses."
2. **Validate Trend GA optimization** — `python optimize.py --strategy trend --cores 12` (Now using extended 2026 data).
3. **Create Trend-specific reporting** — `strategies/trend/reporting.py` for Donchian-specific charts.
4. **Consider adding a `min_bars_required` property** to the base Strategy class for cleaner architecture.

# Strategy Functional Test Plan

This plan shifts the focus from statistical PnL optimization to **Functional Verification**. The goal is to prove that every filter (ADX, RSI, VWAP, SMA, Vol) and trade management feature (Trailing Stops, TP ATR, SL) acts exactly as intended.

## Core Objectives
1.  **Verify Logic Gates**: Confirm that the "pipes" are connected correctly and each entry filter is receiving the correct indicator data.
2.  **Audit Rejections**: Create a record of every Donchian Channel breakout that was *blocked* by a filter, including the raw values at that moment.
3.  **Validate Exit Logic**: Prove that **Trailing Stops**, **Take Profits**, and **Initial Stops** are calculated correctly and follow "Ratchet" rules.
4.  **Environmental Parity**: Ensure that the **Core Logic** (shared `Strategy` class) behaves identically across **Backtest** (vectorized) and **Live/Paper** (bar-by-bar) environments.

---

## 1. Implementation Options (The "Three Pillars")

### A. The "Truth Table" (Synthetic Unit Tests)
-   **Environment**: Isolated Python script (no IB, no real data).
-   **Method**: Feed **Artificial Candles** into `strategy.calculate_indicators` and `calculate_entry_signals`.
-   **Goal**: Verify the mathematical "Truth Table." If any individual filter is `False`, the signal *must* be `False`.
-   **Test Case**: A sequence of 10 bars where price is at a breakout level, but a specific filter (e.g., ADX) slides from 15 to 25. Assert signal flips from `False` to `True` at the exact threshold.

### B. The "Action Log" (Explanatory Backtest)
-   **Environment**: Standard backtester over historical CSVs.
-   **Method**: Add a `verbose` audit flag to the strategy. For every bar where a "breakout" occurred but no trade was taken, record the specific violating filter (e.g., `REJECTED: ADX=18.5 < MinADX=20.0`).
-   **Goal**: Analyze **Historical Coverage**. Use real market data to see how often each filter acts as the primary blocker.

### C. The "Shadow Auditor" (Live/Paper Reality)
-   **Environment**: Running live inside `main.py`.
-   **Method**: Capture "Near-Miss" signals in real-time. Record the state of all indicators at the moment of a breakout, even if blocked.
-   **Goal**: Catch **Data Discrepancies**. Verify that the live bar feed (with potential jitter/lags) interacts with the logic exactly as the backtest data does.

---

## 2. Design of Experiments (DoE) & Filter Stress Testing
To fully trust the logic, we must systematically test the combinations of filters rather than just relying on "optimal" GA parameters.

### Logic Gate Verification (OFAT - One Factor at a Time)
Run the "Truth Table" tests through a systematic grid:
-   **Baseline Test**: All filters DISABLED. Expect a trade on *every* Donchian breakout.
-   **The "Killer" Test**: Enable one filter at a time with an "impossible" threshold (e.g., ADX > 99). Expect 0 trades.
-   **The "Relaxed" Test**: Enable all filters with "zero" thresholds (ADX > 0, Vol > 0). Expect it to match the Baseline.

### Interaction Testing
-   **Redundancy Check**: Test if two filters (e.g., VWAP and SMA) always flip at the same time. If they do, one is redundant.
-   **Conflict Check**: Verify that a Long signal isn't blocked by a logic contradiction (e.g., RSI saying "Sell" while Price says "Buy").

---

## 4. Exit & Management Verification (Trade Lifecycle)
Beyond entries, the "Test Bench" must verify the correct behavior of orders after entry.

### A. Trailing Stop "Ratchet" Test
-   **Scenario**: Feed 20 bars of data that trend Up, then dip Down, then trend Up again.
-   **Verification**: Assert that the Trailing Stop price moves Up with the trend, **stays perfectly flat** during the dip (proving the "ratchet" logic), and then resumes moving Up.

### B. Trailing Delay Verification
-   **Scenario**: Set `Trailing Delay (bars)` to 5 and enter a synthetic trade.
-   **Verification**: Assert the stop loss stays at the `Initial SL` for exactly 5 bars, and only begins trailing on bar 6.

### C. ATR-based Take Profit Precision
-   **Scenario**: Enter a trade when ATR is exactly 10.0 and `TP ATR Multiplier` is 2.0.
-   **Verification**: Assert that the Take Profit price is calculated at exactly `Entry + 20.0`.

### D. Reverse-Signal Exit (Channel Exit)
-   **Scenario**: Feed price data for a Long trade where price eventually closes *below* the `Donchian_Low` (support).
-   **Verification**: Assert that `check_exit()` returns `True` at the exact bar the channel is broken.

---

## 5. Visual Rejection Gallery (HTML Dashboard)
Create a new reporting tool `tools/reporting/rejection_gallery.py`.
*   **Implementation**: For every **BLOCKED** trade in the Audit Log, extract 30 bars of OHLCV/Indicator context.
*   **Visuals**: Generate a chart using Plotly that overlays the price action with the "Violating" indicator highlighted in red.
*   **Dashboard**: An HTML page showing these charts sequentially for rapid human review.

---

## Success Criteria
- [ ] **Truth Table Precision**: 100% of synthetic tests pass for all 6+ filters (ADX, ATR, SMA, Vol, RSI, VWAP).
- [ ] **Exit Guard Integrity**: Synthetic "Ratchet" and "Delay" tests for Trailing Stops pass with zero slippage.
- [ ] **Audit Log matches Manual Check**: Randomly pick 5 "BLOCKED" signals from a Backtest run and manually verify the filter was indeed violating the threshold.
- [ ] **Environmental Parity**: Run the same synthetic "Artificial Candles" through BOTH the backtest loop and a simulated live `on_bar_update` loop to ensure identical results.

> [!IMPORTANT]
> This plan ensures that when we eventually run the GA, we are optimizing a **Technically Valid** system, rather than just overfitting a black box.

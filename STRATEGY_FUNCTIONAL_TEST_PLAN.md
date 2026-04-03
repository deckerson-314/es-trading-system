# Strategy Functional Test Plan

This plan shifts the focus from statistical PnL optimization to **Functional Verification**. The goal is to prove that every filter (ADX, RSI, VWAP, SMA, Vol) and trade management feature (Trailing Stops, TP ATR, SL) acts exactly as intended.

## Core Objectives
1.  **Verify Logic Gates**: Confirm that the "pipes" are connected correctly and each entry filter is receiving the correct indicator data.
2.  **Verify Core Breakout Logic**: Prove that the Donchian Crossover (first-bar-only) signal fires correctly and does not re-trigger on subsequent bars.
3.  **Audit Rejections**: Create a record of every Donchian Channel breakout that was *blocked* by a filter, including the raw values at that moment.
4.  **Validate Exit Logic**: Prove that **Trailing Stops**, **Take Profits**, and **Initial Stops** are calculated correctly and follow "Ratchet" rules.
5.  **Environmental Parity**: Ensure that the **Core Logic** (shared `Strategy` class) behaves identically across **Backtest** (vectorized) and **Live/Paper** (bar-by-bar) environments, including the backtest's "Pending Entry" delay pattern.

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
-   **Baseline Test**: All toggleable filters DISABLED *and* `Min ATR (Points)` set to `0.0`. Expect a trade on *every* Donchian crossover breakout.
-   **The "Killer" Test**: Enable one filter at a time with an "impossible" threshold (e.g., ADX > 99). Expect 0 trades.
-   **The "Relaxed" Test**: Enable all filters with "zero" thresholds (ADX > 0, Vol > 0, ATR > 0). Expect it to match the Baseline.

> [!WARNING]
> **ATR Filter is Always-On.** Unlike ADX, RSI, VWAP, SMA, and Volume, the ATR filter (`atr_filter > min_atr_points`) has **no `enable_atr_filter` toggle** in `strategy.py`. It is always evaluated. The Baseline and Relaxed tests must set `Min ATR (Points) = 0.0` to neutralize it, or the tests will produce false failures.

### Interaction Testing
-   **Redundancy Check**: Test if two filters (e.g., VWAP and SMA) always flip at the same time. If they do, one is redundant.
-   **Conflict Check**: Verify that a Long signal isn't blocked by a logic contradiction (e.g., RSI saying "Sell" while Price says "Buy").

---

## 3. Core Signal & Kill Switch Verification
These tests verify the foundational signal logic *before* any filters are applied.

### A. Donchian Crossover (First-Bar-Only) Test
The breakout signal uses crossover logic to prevent "trade storms" (`strategy.py` L324-325):
```python
long_sig = (df['high'] > df['donchian_high']) & (df['high'].shift(1) <= df['donchian_high'].shift(1))
```
-   **Scenario**: Feed 5 bars where price gradually rises through the Donchian High level.
-   **Verification**:
    -   Bar 1: Price below Donchian High → No signal.
    -   Bar 2: Price breaks above Donchian High → **Signal fires.**
    -   Bar 3: Price stays above Donchian High → **No signal** (crossover already consumed).
-   **Why this matters**: If crossover logic is broken, the bot either never trades or fires on every bar above the channel, creating a "trade storm."

### B. Master Kill Switch Test (`enable_long` / `enable_short`)
After all filters and crossover logic, the strategy applies master switches (`strategy.py` L334-335):
```python
if not self.enable_long: long_sig[:] = False
```
-   **Scenario**: Set `Enable Long Trades = False`. Feed data with a valid Long breakout where all filters pass.
-   **Verification**: Assert exactly 0 Long signals. Repeat for `Enable Short Trades = False`.

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

## 5. Environmental Parity (Backtest vs Live Execution)
The backtest engine (`backtest.py` L195-231) uses a **"Pending Entry"** pattern: the signal fires on bar N, but the position opens at bar N+1's `open` price. The live bot may handle this differently.

-   **Test**: Run the same synthetic "Artificial Candles" through:
    1. Direct call to `calculate_entry_signals()` (raw signal check).
    2. The full `backtest.py` `run_backtest()` simulation loop (includes pending entry delay).
    3. A simulated live `on_bar_update` call sequence.
-   **Verification**: Confirm that the **same trades** are taken in all three paths, with entry prices matching the expected bar.

> [!IMPORTANT]
> Testing only `calculate_entry_signals()` will NOT catch the pending-entry delay. The parity test must exercise the full simulation loop.

---

## 6. Visual Rejection Gallery (HTML Dashboard)
Create a new reporting tool `tools/reporting/rejection_gallery.py`.
*   **Implementation**: For every **BLOCKED** trade in the Audit Log, extract 30 bars of OHLCV/Indicator context.
*   **Visuals**: Generate a chart using Plotly that overlays the price action with the "Violating" indicator highlighted in red.
*   **Dashboard**: An HTML page showing these charts sequentially for rapid human review.

---

## Success Criteria
- [ ] **Crossover Precision**: Donchian breakout signal fires on exactly 1 bar per channel break, never re-triggering on subsequent bars.
- [ ] **Truth Table Precision**: 100% of synthetic tests pass for all 6+ filters (ADX, ATR, SMA, Vol, RSI, VWAP).
- [ ] **Kill Switch Integrity**: `enable_long=False` produces exactly 0 long signals; same for short.
- [ ] **Exit Guard Integrity**: Synthetic "Ratchet" and "Delay" tests for Trailing Stops pass with zero slippage.
- [ ] **Audit Log matches Manual Check**: Randomly pick 5 "BLOCKED" signals from a Backtest run and manually verify the filter was indeed violating the threshold.
- [ ] **Environmental Parity**: Same synthetic data produces identical trades through `calculate_entry_signals()`, `run_backtest()`, and simulated live loop.

> [!IMPORTANT]
> This plan ensures that when we eventually run the GA, we are optimizing a **Technically Valid** system, rather than just overfitting a black box.

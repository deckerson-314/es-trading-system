# Handoff: ES Trading System - Phase 9 (Functional Verification)

## Current Status (2026-04-03)
We have shifted focus from statistical GA optimization to **Functional Verification**. A comprehensive **Strategy Functional Test Plan** has been developed to prove that the bot's logic is 100% precise across all environments.

### Core Architecture Update
- **Strategic Blueprint**: `STRATEGY_FUNCTIONAL_TEST_PLAN.md` defines the test bench.
- **The Three Pillars**:
    1. **Truth Table**: Synthetic unit testing with artificial candles (Isolation).
    2. **Action Log**: Explanatory backtest output (History).
    3. **Shadow Auditor**: Live "Near-Miss" monitoring (Reality).

## Immediate Next Steps (For next agent)
1.  **Implement 'Pillar A' (Truth Table)**:
    -   Create `tests/test_strategy_v5_functional.py`.
    -   Develop a helper to generate "Step Function" OHLCV data where an indicator (e.g., ADX) crosses a threshold while price stays at a breakout level.
    -   Assert that `TrendStrategy` triggers/blocks trades at exactly the right bar.
2.  **Implement 'Pillar B' (Action Log)**:
    -   Add a `verbose=False` parameter to `TrendStrategy.calculate_entry_signals`.
    -   When `True`, it should print/log the specific reason for every rejection (e.g., "ADX 19.5 < 20.0").
3.  **Verify Trailing Stop Logic**:
    -   Create a "Ratchet Test" scenario (Price: 100 -> 110 -> 105 -> 115).
    -   Verify the stop loss never move downwards during the dip.

## Contextual Warnings
- **Environmental Parity**: The logic MUST behave the same in vectorized backtests and bar-by-bar live updates. Use the "Shadow Auditor" to prove this if discrepancies arise.
- **DoE (Design of Experiments)**: When testing filters, use a grid approach (OFAT) to isolate each filter and ensure no "logic leaks" (unintended ORs instead of ANDs).

## Key Files
- `STRATEGY_FUNCTIONAL_TEST_PLAN.md`: The main blueprint.
- `strategies/trend/strategy.py`: The "Brain" needing the audit flag.
- `tests/test_strategy_v5.py`: Existing tests (mostly Bollinger).

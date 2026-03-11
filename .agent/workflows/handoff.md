---
description: How to handle agent handoff for the ES Trading System project
---

# Agent Handoff Workflow

## At the Start of Every Conversation

1. **Read the project status file first:**
   ```
   c:\Trading\.agent\PROJECT_STATUS.md
   ```
   This file contains the current system state, recent changes, known issues, and next steps.

2. **Check if the trading bot is currently running:**
   - Ask the user or check for running Python processes
   - Any code changes to `core/`, `main.py`, `strategies/` require a bot restart

3. **Review the architecture section** to understand the modular structure before making changes.

## At the End of Every Conversation

1. **Update `c:\Trading\.agent\PROJECT_STATUS.md`** with:
   - What was changed (add to "Files Modified" section, update date)
   - Any new known issues
   - What the next agent should prioritize
   - Current bot running state

2. **Key sections to update:**
   - `Last Updated` timestamp
   - `Current State` — move fixed items from ⚠️ to ✅
   - `Changes Made This Session` — add new section or update
   - `For Next Agent` — update immediate priorities

## Critical Rules

- **Never modify files while the live bot is running** without warning the user
- **All `core/` modules must be strategy-agnostic** — use `getattr(strategy, 'attr', default)` for any strategy-specific attributes
- **Test with both Bollinger and Trend strategies** when changing shared code
- **The `strategies/bollinger/reporting.py`** generates proper backtest dashboards (Plotly) — `tools/dashboard/updates.py` is for live trading only
// turbo-all

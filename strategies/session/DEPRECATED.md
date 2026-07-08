# Session VWAP — Deprecated

**Status:** Deprecated for optimization and deploy (2026-07-06).

Session v1 and v2 GA runs failed OOS validation (0 profitable solutions; v2 OOS −$18.5k / PF 0.35). VWAP fade attribution showed anti-predictive entry selection (SS − RS ~ −$13.6k).

**Active intraday research:** `orb` — Opening Range Breakout + acceptance (`--strategy orb`).

This module remains for historical GA artifacts, parity replay, and attribution comparisons. Do not run fresh GA on `session` without an explicit experiment.

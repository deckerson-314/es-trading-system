# GA Parameter Context — Implementation Plan

## Branch experiment and merge policy

This work lives on the **`ga-parameter-context`** experiment branch (or equivalent) as a **deliberate fork from main-line behavior**. The goal is to improve how the GA searches over **coupled** and **conditionally relevant** parameters without rewriting the whole optimizer.

**Merge decision is deferred.** We will only merge into the primary development line after:

- Repeated A/Bs (ideally **multi-seed**) show a clear benefit, or  
- Paper / live criteria are met with no regression in robustness workflows.

Until then, treat production paths (e.g. canonical Trend param CSV) as **read-only** for experiments; use copies and explicit `--params` / output dirs.

---

## Guiding principle

**Biggest practical win:** change *what* the GA optimizes (semantic, conditional representation) before investing in making the GA engine itself “smarter.”

---

## 1) Optimize in semantic units (recommended)

| Item | Status | Notes |
|------|--------|--------|
| **Trailing Delay (minutes)** as an optimizable / context input; **derive `Trailing Delay (bars)`** at evaluation from `Timeframe (minutes)` | **Done** | `resolve_trailing_delay_bars`, `finalize_ga_solution_params`, `core_evaluate`, best-params path in `optimize.py`; Trend strategy aligns delay from minutes + timeframe. |
| **Backward compatibility:** if **`Trailing Delay (minutes)`** is absent from the param CSV, honor **bars-only** behavior | **Done** | Resolver uses minutes only when that column exists; baseline A/B used bars-only CSV. |
| **Reduce genotype redundancy** (same real delay from different bar×timeframe combos) | **Partial** | Minutes + derivation addresses trailing delay specifically; other redundant pairs (e.g. risk expressed multiple ways) not yet unified. |
| **Replace / complement ATR multipliers** with a **normalized risk target** (e.g. stop distance in points / dollars) | **Not started** | Candidate for a later semantic unit once trailing + conditional story is stable. |

---

## 2) Hierarchical / conditional genes

| Item | Status | Notes |
|------|--------|--------|
| **Trailing off →** trailing sub-parameters must not drive fitness | **Done** | `trailing_stop_enabled`, `apply_trailing_param_context` strip trailing-specific keys before eval; Trend `update_optimizable_params` restores trailing fields from template when trailing disabled. |
| **`Enable RSI Filter = 0` →** ignore or freeze RSI thresholds | **Done** | `rsi_filter_enabled`, `apply_rsi_param_context` in `optimize.py`; `_restore_rsi_from_template` in Trend `update_optimizable_params` when RSI off. |
| **TP mode conditional** (only relevant TP params active for chosen mode) | **Not started** | Align with `PARAMETER_OPTIMIZATION_GUIDE.md` single **`TP Method`** style encoding if we go this route. |

---

## 3) Interaction-aware constraints

| Item | Status | Notes |
|------|--------|--------|
| **Soft penalties** on unrealistic combinations (e.g. ultra-low trade rate from timeframe + lookbacks + filters; pathological delay) | **Prototype** | **`ENABLE_FILTER_STACK_TRADE_PENALTY`** + `INTERACTION_*` keys in param CSV: when many stack filters are on, raise expected min trades/day (`base + per_filter × count`) and scale `penalty_factor` if realized `avg_trades_day` falls short (`core_evaluate` in `optimize.py`). |
| Document target interactions and penalty shape (linear vs cliff) | **Partial** | Current shape: linear in relative shortfall up to `INTERACTION_PENALTY_STRENGTH`; tune after A/Bs. |

---

## 4) Dual report (raw genes + derived semantics)

| Item | Status | Notes |
|------|--------|--------|
| Export **raw** optimized parameters per solution (as today) | **Done** | Genetic results CSV / solution columns. |
| Export **derived** trailing context for interpretation | **Partial / Done (trailing)** | e.g. **`Derived Trailing Delay (bars from minutes/timeframe)`** row in `save_optimized_results` output (`optimize.py`). |
| **General dual report** for other semantic units (risk distance, effective RSI band, etc.) | **Partial** | **`Derived RSI filter (effective entry gates)`** row in `save_optimized_results` (`describe_effective_rsi_band`); risk-normalized rows still future. |
| Dashboard / JSON export parity for derived fields | **Partial** | Confirm HoF and `visualize-json` paths show derived trailing where relevant. |

---

## 5) Phased search (structural → exits → refine)

| Item | Status | Notes |
|------|--------|--------|
| **Phase A:** regime / structure (timeframe, lookbacks, major filters) | **MVP done** | `strategies/trend/phased_search.py` + `scripts/phased_ga_trend.py`: phase A CSV keeps only `phase_a` genes ranged; others `Min=Max=Value`. Lists in `scripts/phased_trend_phases.json`. |
| **Phase B:** freeze structure, optimize exits / risk micro-params | **MVP done** | `Solution_*_SELECTED` from phase A `genetic_results` locks phase A; phase B restores exit/risk ranges from base CSV; phase B uses `--fresh` (new genome). |
| **Phase C:** local refinement | **Not started** | Optional third leg (narrow ranges / local search); extend script if needed. |

---

## Concrete first experiment (low-risk) — *from design notes*

| Step | Status |
|------|--------|
| Add **`Trailing Delay (minutes)`** as GA / param CSV input | **Done** |
| Derive **`Trailing Delay (bars)`** at evaluation from current **timeframe** | **Done** |
| Keep **backward compatibility** when minutes column absent | **Done** |
| Short **baseline vs context** A/B on same `--pop` / `--gen` / data | **Done** (e.g. `results/ab_trailing_context_v3/`); treat as single snapshot, not final verdict |

---

## Engineering already in place (supporting)

- [x] **`--data-csv`** / **`TRADING_DATA_CSV`** so worktrees do not need to duplicate or accidentally destroy OHLC (`optimize.py`).
- [x] **`.cursorrules`**: do not move canonical data; do not **`Remove-Item -Recurse`** on a worktree `Bollinger\data` until confirming it is not a junction into main (Windows footgun).

---

## Recommended next implementation items (ordered)

1. **Multi-seed A/B harness** — same baseline vs context, **N seeds**, aggregate IS/OOS metrics. **`scripts/multi_seed_ab_trend_trailing.py`** orchestrates runs and writes `per_seed_metrics.csv` + `aggregate_by_arm.csv`. **`--seed`** is in `optimize.py`; overnight script accepts `-Seed`.  
2. ~~**RSI conditional cluster**~~ — **Done** (RSI off → drop RSI tuning genes; strategy restores from template).  
3. ~~**Dual report expansion (RSI)**~~ — **Done** for RSI (`Derived RSI filter (effective entry gates)`); extend for risk distance / other clusters as they land.  
4. **Interaction penalties** — **prototype done**: filter-stack × low-trade penalty (`ENABLE_FILTER_STACK_TRADE_PENALTY` + `INTERACTION_*` in Trend / Bollinger backtest CSVs). Tune strengths after multi-seed evidence.  
5. **Phased search** — **MVP:** `scripts/phased_ga_trend.py` (two-phase Trend GA) + `scripts/phased_trend_phases.json`. Phase C / Bollinger parity later if useful.  

---

## Overnight runs (12–24h) and baseline preservation

A serious GA leg is often **12–24 hours**; a full **A/B** is roughly **twice that** if both sides run to completion. Use overnight (or weekend) windows for **merge-grade evidence**, not for every code tweak.

### When to commit to a long run

Start the clock only when **all** of the following hold:

1. **Frozen setup** — same **git commit** (or tag), frozen **param CSV** copies, frozen **OHLC path** and **GA date range** / split settings; no pending edits to `optimize.py` / `strategy.py` eval paths mid-run.  
2. **Cheaper runs already agree** — shorter or medium runs (or multi-seed, once available) point the **same way** often enough that one long shot is worth the electricity.  
3. **Pre-written decision rule** — e.g. “context wins if OOS Sortino median across seeds improves by X without breaching Y on DD/PF”; avoid interpreting results after the fact only.  
4. **You need the answer for a real gate** — merge, paper/live cutover, or abandoning the branch—not routine iteration.

Until then, prefer **shorter runs + checkpoints** and extend a promising line rather than always `--fresh` cold starts.

### Save the baseline once; reuse for new comparisons

**Yes — baseline should be an immutable snapshot.** For each baseline you care about, archive (copy) into a dedicated folder and **do not overwrite** it when testing new variants.

**Minimum snapshot contents**

| Artifact | Purpose |
|----------|---------|
| `genetic_results_*.csv` | Solutions + aggregate / derived rows |
| Final (or last) **`ga_checkpoint_*.pkl`** | Resume, dashboards, reproduction |
| **Param CSV** used for that run (dated copy) | Exact optimizable set and ranges |
| **Git commit hash** (and branch name) in a `RUN_META.txt` or README snippet | Code / evaluator version |
| **Data** — path to OHLC file + optional file size or hash | Same tape as the run |

**Suggested layout**

`results/ga_context_ab/<YYYY-MM-DD>_baseline_<short_git_sha>/`  
…then add sibling folders for each **context** or future variant, or a single `context/` next to that baseline for one A/B cycle.

**Re-run baseline only when** something material changes: different data slice, fitness weights, `MIN_TRADES_DAY` / penalties, optimizable parameter set, CSV min/max ranges, or evaluator/strategy logic that affects fitness. Otherwise **reuse** the saved baseline CSV + checkpoint and run **only the new variant** + a new comparison summary against the frozen baseline.

**Optional later:** a small script or `optimize.py` flag (e.g. `--archive-run-tag <name>`) that copies results + checkpoint + a resolved “effective config” dump into `results/...` automatically after each run.

**Parallel overnight A/B (implemented):** `scripts/overnight_ab_trend_trailing.ps1` starts baseline + context together (each with `--run-tag` so checkpoints and `genetic_results` do not collide). Set `TRADING_GA_NO_BROWSER=1` inside the script so dashboards do not open a browser. Optional: `TRADING_DATA_CSV` for OHLC path. `optimize.py` also accepts **`--run-tag`** for any manual parallel runs.

### Pre-flight checklist (night before)

- [ ] **OHLC** present at default path **or** `TRADING_DATA_CSV` / `--data-csv` set and verified (`Test-Path` / size check).  
- [ ] **Production param CSV** untouched; experiment uses **`--params`** copies only.  
- [ ] **Machine:** disable sleep/hibernate for the run window; enough **disk** for checkpoints + CSV + logs.  
- [ ] **Commands documented** — same `python optimize.py ...` line for baseline and context (or script file in repo) so a second leg is copy-paste identical except `--params` / tag.  
- [ ] **Baseline folder created first**; after baseline finishes, **copy artifacts immediately** before starting context (so nothing overwrites).  
- [ ] **Post-run:** copy/move archived checkpoint from `Trend/diagnostics/` if the optimizer renames/archives on completion—confirm where the final `.pkl` and `genetic_results` land.

---

## A/B results log (reference snapshots)

*Immutable snapshots live under `results/…`; this section is a quick index only.*

### Overnight parallel (no fixed seed)

| | baseline (bars-only minutes row) | context (with `Trailing Delay (minutes)`) |
|---|-----------------------------------|-------------------------------------------|
| **Folder** | `results/overnight_ab_trailing_20260430_222820/` | same |
| **When** | started `2026-04-30T22:28:20-04:00` | same |
| **Settings** | pop 100, gen 100, cores 6 per leg, 2 legs parallel | same |
| **IS Sortino** | 18.5772 | 2.8737 |
| **IS PF** | 1.4048 | 1.5976 |
| **IS PnL** | $29,594.63 | $105,412.14 |
| **IS MaxDD** | $9,018.85 | $7,458.57 |
| **IS Trades/Day** | 1.007 | 1.078 |
| **OOS Sortino (agg.)** | -0.7757 | 0.3338 |

Source: `ab_summary.csv` in that folder (selected solution column).

### Short seeded smoke (same seed both legs)

| | baseline | context |
|---|----------|---------|
| **Folder** | `results/ab_seed_smoke_20260501_105725/` | same |
| **Seed** | 1337 | 1337 |
| **Settings** | pop 80, gen 5, cores 4 | same |
| **IS Sortino** | 0.1273 | 0.2550 |
| **IS PF** | 1.0238 | 1.0687 |
| **IS PnL** | $5,336.02 | $13,387.55 |
| **IS MaxDD** | $19,850.12 | $13,709.65 |
| **IS Trades/Day** | 1.033 | 1.063 |
| **OOS Sortino (agg.)** | -0.0566 | -0.1859 |

Source: `ab_summary.csv` in that folder.

### Multi-seed A/B (3 seeds, 12 cores)

| | baseline | context |
|---|----------|---------|
| **Folder** | `results/multi_seed_ab_20260501_181940/` | same |
| **Seeds** | 101, 202, 303 | same |
| **Settings** | pop 25, gen 8, cores 12 per leg, legs serial | same |
| **Mean IS Sortino** | 0.680 | 0.316 |
| **Mean OOS Sortino** | -0.138 | -0.013 |
| **Mean IS PF** | 1.144 | 1.067 |

Source: `aggregate_by_arm.csv` in that folder (per-seed detail in `per_seed_metrics.csv`). Short smoke run—not overnight-grade evidence.

### Multi-seed A/B (~12 h budget, pop/gen scaled ~⅓)

| | baseline | context |
|---|----------|---------|
| **Folder** | `results/multi_seed_ab_20260502_001247/` | same |
| **Seeds** | 101, 202, 303 | same |
| **Settings** | pop **58**, gen **58**, cores **12**, legs serial; wall ~**11.5 h** | same |
| **Mean IS Sortino** | 3.319 | 1.971 |
| **Mean OOS Sortino** | −1.917 | −0.133 |
| **Mean IS PF** | 1.214 | 1.471 |

Source: `aggregate_by_arm.csv`; scaling rationale in `TIME_BUDGET.txt` in that folder.

---

## References in repo

- `optimize.py` — `resolve_trailing_delay_bars`, `apply_trailing_param_context`, `apply_rsi_param_context`, `count_enabled_stack_filters` / `filter_stack_trade_penalty_multiplier` (interaction penalty), `finalize_ga_solution_params`, derived rows in `save_optimized_results`.  
- `strategies/trend/strategy.py` — `_restore_trailing_from_template`, `_restore_rsi_from_template`, trailing / RSI resolution in `update_optimizable_params`.  
- `tests/test_param_context.py` — smoke tests for context helpers.  
- `tests/test_interaction_penalty.py` — filter-stack interaction penalty helpers.  
- `PARAMETER_OPTIMIZATION_GUIDE.md` — TP method / bool-as-int patterns for future hierarchical work.  
- `results/ab_trailing_context_v3/` — example A/B artifacts and `ab_summary.csv` (regenerate via `_make_ab_summary.py` if needed).
- `scripts/multi_seed_ab_trend_trailing.py` — multi-seed trailing minutes A/B + aggregates.
- `scripts/overnight_ab_trend_trailing.ps1` — parallel overnight A/B.
- `strategies/trend/phased_search.py` — phase CSV builders (gene freeze / winner lock).
- `scripts/phased_ga_trend.py` — run phase A then phase B `optimize.py` with isolated `--run-tag`s.
- `scripts/phased_trend_phases.json` — default `phase_a` / `phase_b` gene name lists.

---

*Last updated: multi-seed ~12h budget A/B `multi_seed_ab_20260502_001247` (2026-05-02).*

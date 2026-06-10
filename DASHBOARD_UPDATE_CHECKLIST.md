# GA dashboard update -- workstream checklist

Use this when extending `optimize.py` / dashboard HTML. Mark items as you go.

**File encoding:** Save as **UTF-8** only. UTF-16 makes Cursor treat this file as binary ("Markdown preview not supported").

## 1. Convergence and logbook telemetry

| Item | Status |
|------|--------|
| Additive `pop_*` logbook keys (min/max/std, pop avg trades/ppt) without changing GA selection | Done |
| `extend_logbook_header_for_pop_stats` on checkpoint resume | Done |
| `GA_LOGBOOK_HEADER_FULL` for fresh runs and JSON-solution path | Done |
| Convergence figure: outer min-max band and inner avg +/- 0.5 std for PF, trades, profit, PPT | Done |
| Trades/PPT panels use pop averages where recorded | Done |
| Sortino/DD bands only where scale is consistent (normalized branches) | Done |
| Sortino/DD: draw population bands when `actual_*_best` lines are shown | Done (2026-05-10 fix) |
| Info copy under Fitness Convergence explaining bands vs lines | Done |

## 2. Elite parameter intelligence (Hall of Fame)

| Item | Status |
|------|--------|
| Boundary table (% near min/max, flags) | Done |
| Histograms for high boundary-pressure parameters | Done (fixed blank render) |
| Scatter: parameter value vs fitness Sortino | Done (fixed per-param y alignment) |
| `make_subplots` title count padded to rows x cols | Done |
| `extract_chart_html` / Plotly 6 `full_html=False` / trailing `</div>` fixes | Done |
| Versioned Plotly CDN (`plotly_cdn_url`) -- not `plotly-latest` | Done |

## 3. Robustness and ops

| Item | Status |
|------|--------|
| Smoke: `python -m py_compile optimize.py` | Ad hoc |
| Smoke: `--dashboard-from` on a real `.pkl` | Done |
| Large HoF: `TRADING_GA_CSV_MAX_SOLUTIONS` | Env var exists |
| Post-run checkpoint archive on Windows | Warning seen; optional harden |
| `TRADING_GA_NO_BROWSER` for headless runs | Done |

## 4. Optional backlog

| Item | Status |
|------|--------|
| Skip or defer full CSV export in dashboard-only mode | Not done |
| Cap elite subplot count for very wide param sets | Not done |
| Single shared `extract_chart_html` implementation | Partial (`restore_param_analysis.py`) |

---

### Why bands might still be missing

1. **Checkpoint age:** `extend_logbook_header_for_pop_stats` adds column names, but older generations never recorded `pop_*` values (DEAP returns `None`). Envelopes then skip. Fix: **fresh GA run** with current code, or accept line-only plots on old pickles.
2. **Sortino/DD actual-metrics path:** Previously skipped envelopes when actual Sortino/DD was present -- fixed in `optimize.py` (2026-05-10).

---

Regression notes (2026-05-10): paired Sortino arrays per scatter param; use `full_html=False`; `extract_chart_html` must append Plotly trailing `</div>` after `</script>`.

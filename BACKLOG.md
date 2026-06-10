# Trading repo backlog

Central index for bugs, features, and verification work. Check items off here when done; keep detailed specs in the linked docs.

**How to check items off (Cursor)**

Cursor’s built-in **Markdown preview** usually shows task lists as **plain bullets**, not clickable checkboxes (unlike GitHub.com). Use one of these instead:

1. **Edit the source** — change `[ ]` to `[x]` on the line (works everywhere).
2. **Markdown All in One** (recommended) — install when prompted (`.vscode/extensions.json`), put the cursor on a `- [ ]` line, then **Ctrl+Shift+P** → **Markdown All in One: Toggle checkbox** (or assign a keybinding).
3. **GitHub** — push the file and toggle boxes on github.com if you use a remote.

Syntax: `- [ ]` open, `- [x]` done (space inside the brackets).

**How to use**

- Add items under **Bugs** or **Features** with `- [ ]`.
- Link the source doc when the item comes from a plan.
- In Cursor chat: `@BACKLOG.md fix … and check it off`.
- Domain checklists stay for large workstreams; move remaining open items here for one place to scan.

**Fixed vs verified**

Use one checkbox plus a status suffix on the same line:

- **Open:** `- [ ] Short description`
- **Fixed (code in tree, not yet proven):** `- [x] … — **fixed** YYYY-MM-DD · **verified** pending`
- **Verified (evidence in prod/soak/tests):** `- [x] … — **fixed** YYYY-MM-DD · **verified** YYYY-MM-DD (evidence: …)`

When **verified**, move the line to **Done (recent)** and keep the full suffix for audit trail. Live execution items usually need log line, trade id, or test run — not code review alone.

**Now (priority)**

Prefix the line with **Now** at the start (e.g. `- [ ] **Now** dashboard does not survive api restart`). Keep the item in its section for context — no separate Now list. Clear **Now** when done or deprioritized; prefer 1–3 at a time. Find them with search: `**Now**`.

---

## Bugs

Live execution / parity ([docs/execution_and_trailing_stop_design.md](docs/execution_and_trailing_stop_design.md) §9.2):

- [ ] **Now** Flat-book cleanup cancels bracket legs before IB fill lands (`core/protection.py`, `tools/safety/guards.py`) — **fixed** 2026-05-21 · **verified** pending (2026-05-21 trade: stop 52 Cancelled @ entry)
- [ ] **Now** Post-open stop verify + re-protect when broker leg missing (`ensure_bracket_protective_stop`) — **fixed** 2026-05-21 · **verified** pending
- [ ] Working-stop detection ignores PendingCancel/Inactive (`es_position_has_protective_exit_orders`) — **fixed** 2026-05-21 · **verified** pending
- [ ] `_force_close_position`: TRADE CLOSE log + report slippage/live_exit_type — **fixed** 2026-05-21 · **verified** pending
- [ ] No `STRATEGY SIGNAL EXIT: Stop Loss` + market while stop `Submitted`/`PreSubmitted` and position open
- [ ] No `STRATEGY SIGNAL EXIT: Take Profit` + market while TP limit active and position open
- [ ] `bars_held` after N **strategy** bars equals expected (not ~13×N on 1-min clock)
- [ ] During `trailing_delay`, broker stop stays at entry `initial_sl_pct` (no chandelier tighten in logs)
- [ ] Typical SL/TP exits show child order `Filled`, not only market order
- [ ] Channel exits labeled `Channel Exit (signal)`, not `Broker Stop`
- [ ] Strategy bar processing: trail log line precedes any exit signal log on that bar
- [ ] Backtest/GA regression unchanged on fixed seed
- [ ] Compare report: `live_exit_type` in `{broker_stop, broker_tp, channel_signal, software_backup, maintenance, rth}`

### GA dashboard (`optimize.py`)

- [ ] GA split analysis disappears once the GA is complete

### Paper Dashboard
- [ ] **Now** Dashboard lockup with open position: single-flight refresh + throttle `reqOpenOrders` (`main.py`) — **fixed** 2026-05-21 · **verified** pending (2026-05-21 trade: status.js timeout storm)
- [ ] **Now** When position is open, the graph flash the population of the bars associated with the trade periodically.
- [ ] **Now** Active position table does not show current PNL and the unrealized PNL at the top is always 0
- [ ] dashboard does not survive api restart
- [x] Bar chart entry/exit hover: price, bar time, SL/TP@open/close (`tools/dashboard/updates.py`) — **fixed** 2026-05-20 · **verified** pending
- [x] Bar chart: closed-trade SL/TP trail from timeline (`closed_trade_lines`) — **fixed** 2026-05-20 · **verified** pending (needs closed trade on new dashboard)
- [x] Active Positions: bot bracket table with entry time, duration, SL/TP (`main.py` + dashboard) — **fixed** 2026-05-20 · **verified** pending (needs open bracket)
- [x] Trade report: SL/TP lines + slippage + live_exit_type when snapshot present (`unified_trade_report.py`) — **fixed** 2026-05-20 · **verified** pending
- [x] Bar chart default zoom: last 21 bars (`tools/dashboard/updates.py`) — **fixed** 2026-05-20 · **verified** pending
- [x] Stall email only when position open (`main.py`) — **fixed** 2026-05-20 · **verified** pending (flat soak; no stall email yet)
- [x] Ctrl+C cooperative shutdown (no `ib.disconnect()` in signal handler) (`main.py`) — **fixed** 2026-05-20 · **verified** pending

### Backtest
- [ ] If no "--solution" arguement is used, the backetest should use the "Value" column in the csv file
- [ ] The backtest dashboard should show the parameters that were used
- [ ] Old Bollinger Backtest dashboard is non-functional and shouldn't be separate
- [ ] **Paper vs backtest parity: `live_data.csv` / HTF resample mismatch** — `save_live_data_row` appends **13m HTF snapshots** (~`:09/:22/:35/:48`), not continuous 1-min OHLCV; `compare_paper_backtest_trend.py` and `backtest.py` load that file as 1-min and **re-resample**, shifting bar labels (~3m phase: paper **09:35** vs replay **09:45**) and distorting indicators (e.g. Jun 9 2026 09:45 long: paper SMA **7455** pass vs replay SMA **7507** fail on same Donchian breakout). Live uses `resample_data` (`closed='right', label='right'`); backtest uses `resample('13T')` defaults. Investigate: persist true 1-min feed separately; unify resample everywhere; compare on HTF rows or 1-min source without double-resample. Ref: `core/monitoring.py` (`save_live_data_row`, `resample_data`), `compare_paper_backtest_trend.py`, `backtest.py`.

### Code

- [ ] Fix indentation in `BB_Genetic_v3.py` parameter analysis section (~lines 1650–2439); re-enable commented block (inline `TODO`)

---

## Features

### Live / execution

- [x] Maintenance data-stall backoff (`main.py`): when flat and `in_maintenance`, defer aggressive `DATA STALLED` resubscribe to every 5 min; aggressive recovery if position open — **fixed** 2026-05-19 · **verified** pending (needs CME maintenance window soak)
- [x] Phase 3 hardening (partial): OCA trail cancel retries, slippage in trade report + completed_trades, dashboard `live_exit_type` column — **fixed** 2026-05-20 · **verified** pending
- [x] TRADE OPEN fill poll + deferred notify; immediate completed_trades persist; CSV+log merge (`core/execution.py`, `core/completed_trades.py`) — **fixed** 2026-05-20 · **verified** pending (next live entry)
- [ ] Phase 3 remaining: soak verification on next live trade(s)
- [ ] Dynamic TP/SL + reliable order management ([NEW_ARCHITECTURE_PLAN.md](NEW_ARCHITECTURE_PLAN.md): bracket → standalone, state machine)

### Strategy tooling

- [ ] Rejection gallery: `tools/reporting/rejection_gallery.py` — Plotly charts for BLOCKED trades ([STRATEGY_FUNCTIONAL_TEST_PLAN.md](STRATEGY_FUNCTIONAL_TEST_PLAN.md) §6)
- [ ] Verbose audit / action log for filter rejections in backtest ([STRATEGY_FUNCTIONAL_TEST_PLAN.md](STRATEGY_FUNCTIONAL_TEST_PLAN.md) §1B)
- [ ] Shadow auditor for live near-miss signals ([STRATEGY_FUNCTIONAL_TEST_PLAN.md](STRATEGY_FUNCTIONAL_TEST_PLAN.md) §1C)

### GA dashboard (`optimize.py`)

[DASHBOARD_UPDATE_CHECKLIST.md](DASHBOARD_UPDATE_CHECKLIST.md) §4:

- [ ] Skip or defer full CSV export in dashboard-only mode
- [ ] Cap elite subplot count for very wide param sets
- [ ] Single shared `extract_chart_html` implementation (partial in `restore_param_analysis.py`)

### GA / optimizer

[GA_WEIGHTS_AND_CONSTRAINTS_RESEARCH.md](GA_WEIGHTS_AND_CONSTRAINTS_RESEARCH.md) §8:

- [ ] Normalize all objectives to 0–1 range (population statistics)
- [ ] Apply penalties before cap/floor (or remove cap/floor)
- [ ] Hard constraints: win rate < 40%, PNL < 0
- [ ] Stronger non-critical constraint penalties (10–100×)
- [ ] Reduce Sortino cap (e.g. 30 → 10)
- [ ] Remove or reduce fitness floor (0.01) to allow negative fitness
- [ ] Log penalty application and constraint violations
- [ ] Test penalty effectiveness on known bad solutions

Optional ops ([GA_PARAMETER_CONTEXT_PLAN.md](GA_PARAMETER_CONTEXT_PLAN.md)):

- [ ] `optimize.py --archive-run-tag` or script to auto-copy results + checkpoint + config dump after runs

---

## Testing & verification

### Strategy functional

[STRATEGY_FUNCTIONAL_TEST_PLAN.md](STRATEGY_FUNCTIONAL_TEST_PLAN.md) success criteria:

- [ ] Crossover precision: one bar per Donchian break, no re-trigger
- [ ] Truth table: 100% synthetic pass for ADX, ATR, SMA, Vol, RSI, VWAP
- [ ] Kill switch: `enable_long` / `enable_short` off → zero signals
- [ ] Exit guard: trailing ratchet + delay synthetic tests, zero slippage
- [ ] Audit log: 5 random BLOCKED signals match manual threshold check
- [ ] Environmental parity: same synthetic data → identical trades (signals, backtest, live loop)

### Broker stops

[PRESUBMITTED_STOP_ORDERS_EXPLANATION.md](PRESUBMITTED_STOP_ORDERS_EXPLANATION.md):

- [ ] Entry fill: stop transitions to Submitted
- [ ] PreSubmitted stop: recreated as standalone
- [ ] Trailing stop: new stop Submitted before old cancelled
- [ ] API disconnect: stop executes independently
- [ ] Multiple positions: all stops verified
- [ ] Reconnection: stops still Submitted after reconnect

---

## Ops (recurring — GA / overnight runs)

[GA_PARAMETER_CONTEXT_PLAN.md](GA_PARAMETER_CONTEXT_PLAN.md) pre-flight (uncheck when starting a new cycle):

- [ ] OHLC at default path or `TRADING_DATA_CSV` / `--data-csv` verified
- [ ] Production param CSV untouched; experiment uses `--params` copies only
- [ ] Machine: no sleep/hibernate; enough disk for checkpoints + CSV + logs
- [ ] Baseline vs context commands documented (identical except `--params` / tag)
- [ ] Baseline artifacts copied before starting context leg
- [ ] Post-run: final `.pkl` and `genetic_results` locations confirmed

---

## Done (recent)

Move items here when **verified** (keep the full fixed/verified suffix).

- [x] GA dashboard: convergence bands, HoF charts, Plotly CDN fixes ([DASHBOARD_UPDATE_CHECKLIST.md](DASHBOARD_UPDATE_CHECKLIST.md) §1–2) — **fixed** 2026-05-10 · **verified** 2026-05-10
- [x] GA parameter context: `--data-csv`, `.cursorrules` data safety ([GA_PARAMETER_CONTEXT_PLAN.md](GA_PARAMETER_CONTEXT_PLAN.md)) — **fixed** 2026-05-10 · **verified** 2026-05-10
- [x] Sortino/DD population bands when `actual_*_best` shown (`optimize.py`) — **fixed** 2026-05-10 · **verified** 2026-05-10
- [x] Dashboard lockup diagnostics (`tools/dashboard/debug.py`, `DASHBOARD_DEBUG=1`) — **fixed** 2026-05-19 · **verified** 2026-05-19
- [x] Dashboard lockup: status.js heartbeat + full HTML every 30s / on trade (`main.py`) — **fixed** 2026-05-20 · **verified** 2026-05-20 (10:16+ soak: LIVE bars, no status.js timeout storm)
- [x] Skip slow `reqOpenOrders` when flat (`collect_all_ib_open_orders`) — **fixed** 2026-05-20 · **verified** 2026-05-20 (no 5s timeout spam after 10:16 restart)
- [x] Phase 1–2 live execution (`core/execution.py`) — **fixed** 2026-05-19 · **verified** 2026-05-20 (log: `TRADE CLOSE: Broker Stop @ $7394.50`)

---

### Dashboard lockup debug (enable when investigating)

Set before starting **both** the trading bot and the web server:

```text
DASHBOARD_DEBUG=1
```

| Artifact | Path | What it tells you |
|----------|------|-------------------|
| Server write timing | `paper_logs/dashboard_perf.jsonl` | `generate_html_ms`, `write_html_ms`, `total_ms`, `html_bytes`, `write_label` |
| Lightweight poll target | `web/dashboard_paper_health.json` | Same snapshot without reloading multi‑MB HTML |
| Bot log | `trend_paper_execution.log` | `Dashboard write #N …` lines; `Dashboard write timed out` |
| HTTP server console | terminal running port 8000 | `[SLOW HTTP …]` if a GET blocks (e.g. reading huge HTML while bot writes) |
| Browser | DevTools console + bottom-right panel | Full reload ms, `chart-payload` size, health poll every 10s |

**Likely causes to correlate:** (1) 30s full-page reload + large embedded chart JSON + Plotly.react; (2) single-threaded `TCPServer` blocking on concurrent read/write; (3) Windows file lock during in-place HTML write; (4) UI loop write timeout (90s) starving updates.

**Quick checks:** `write_seq` in health JSON advancing? `total_ms` spikes? HTTP slow on `dashboard_paper.html` only? Browser panel frozen but health JSON still updating → client/Plotly; health JSON stale → bot write path.

---

## Source index

| Doc | Role |
|-----|------|
| [docs/execution_and_trailing_stop_design.md](docs/execution_and_trailing_stop_design.md) | Live vs backtest exit authority (draft) |
| [DASHBOARD_UPDATE_CHECKLIST.md](DASHBOARD_UPDATE_CHECKLIST.md) | GA HTML dashboard workstream |
| [GA_PARAMETER_CONTEXT_PLAN.md](GA_PARAMETER_CONTEXT_PLAN.md) | Trailing-minutes A/B runs + archives |
| [STRATEGY_FUNCTIONAL_TEST_PLAN.md](STRATEGY_FUNCTIONAL_TEST_PLAN.md) | Filter/exit functional verification |
| [GA_WEIGHTS_AND_CONSTRAINTS_RESEARCH.md](GA_WEIGHTS_AND_CONSTRAINTS_RESEARCH.md) | Fitness normalization research |
| [NEW_ARCHITECTURE_PLAN.md](NEW_ARCHITECTURE_PLAN.md) | Bracket/standalone order architecture |
| [PRESUBMITTED_STOP_ORDERS_EXPLANATION.md](PRESUBMITTED_STOP_ORDERS_EXPLANATION.md) | IB stop state behavior |

*Created: 2026-05-18.*

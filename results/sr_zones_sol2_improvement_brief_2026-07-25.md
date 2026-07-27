# SR Zones Sol2 — Improvement Brief

**Date:** 2026-07-25  
**Source:** Full-sample deploy backtest  
**Params:** `sr_zones_deploy_sol2_oppdist05_2026-07-25.csv`  
**Dashboard:** `web/backtest_dashboard_sr_zones_sol2_oppdist05.html`  
**Universe:** ES RTH 2020–2025

| Signal | Value |
|--------|--------|
| Entry edge SS−RS | +$62k |
| Exit drag SS−SR | −$18k |
| Side | Long-only by Sol2 genome (two-sided still a valid experiment) |
| Entry Headroom | 0.5 ATR already on |

---

## User decisions (2026-07-25)

| # | Decision | Notes |
|---|----------|-------|
| #1 | **YES — implement** | Genes: `Maintenance Entry Buffer (minutes)` (default 90, 30–240) + unlock exit `Maintenance Buffer Minutes` (default 22, 5–60). Blocks new entries near maint/RTH force-flat. Makes sense: addresses morning/time-budget finding. |
| #2 | **YES — implement** | Separate MFE→breakeven (not classic ATR trail): `Enable Breakeven Stop`, `Breakeven Trigger (ATR)`, `Breakeven Pad (ATR)` locked 0. |
| #3 | Already done | Headroom gene exists; headroom GA running. No change. |
| #4 | Clarified | Entry buffer (#1) only reduces late doomed entries. It does **not** improve capture on open trades with large MFE when force-flatten hits — that remains the separate “forced-flatten capture / trail before force” idea. |
| #5 | No floor | Vol Mult ~1.19 is GA fitness under costs (more trades), not the 1.4–1.6 analyst hypothesis. Do not force a floor unless requested. |
| #6 | Soften long-only | Opposite-entry flip diagnostic ≠ enabling short breakouts of support. Sol2 is long-only by genome choice; two-sided remains valid (e.g. Sol72). |

**GA note:** Running headroom GA must be freshly restarted later to pick up new genes (same as prior gene-space changes). Do not kill the current headroom run.

---

## Core diagnosis

Entries select direction well; exits give back. Almost all net PnL comes from **09–11 entries that survive into 4–8h holds**. Fail-fast stops (0–60m) and green-then-red stops are the main leaks. Opposite-zone exits already capture well — **do not touch that path first**.

---

## Headline metrics

| Metric | Value |
|--------|------:|
| Full-sample PnL | $49,818 |
| Profit factor | 1.27 |
| Win rate | 54.8% |
| Max DD | $11,528 |
| Expectancy / trade | $106 |
| Trades / day | 0.22 |
| Payoff (W/L) | 1.09 |
| Ret / DD | 4.32 |

---

## Extracted dashboard numbers

### Exit mix

| Exit | n | % | PnL | WR | Avg $ | Hold |
|------|--:|--:|----:|---:|------:|-----:|
| Stop Loss | 151 | 32% | −$155k | 0.7% | −$1,030 | 1.6h |
| Opposite Zone | 131 | 28% | +$117k | 100% | +$890 | 2.7h |
| Maintenance\* | 186 | 40% | +$87k | 65% | +$470 | 3.6h |
| Time | 3 | 0.6% | +$1.3k | 33% | +$421 | 20h |

\*Likely includes EOD / `force_exit` flatten (no separate RTH Exit row). Med capture 53% vs Opposite Zone 82%.

### MFE / MAE by exit ($)

| Exit | Med MFE | Med MAE | Med cap% | MFE>$250 & red |
|------|--------:|--------:|---------:|---------------:|
| Stop | $202 | $1,103 | n/a | 45% |
| Opposite Zone | $854 | $618 | 82.5% | 0% |
| Maintenance | $641 | $620 | 53.4% | 17% |
| All | $538 | $749 | 33% med | 21% |

Overall: 72% of trades have MFE > $250; MAE-before-MFE 97%. Stops that went green almost always still closed red.

### 4Q attribution

| Quad | PnL | WR | PF | E[$] |
|------|----:|---:|---:|-----:|
| SS | +$49.8k | 53.9% | 1.27 | +106 |
| SR (time exit) | +$67.5k | 57.5% | 1.25 | +143 |
| RS (rand entry) | −$12.0k | 51.8% | 0.97 | −26 |
| RR null | ~$0 | 47.5% | n/a | ~0 |

SS−RS +$61.9k entry edge · SS−SR −$17.7k exit drag · opposite flip −$64k (keep long-only).

### Hold buckets vs PnL

| Bucket | PnL ($) |
|--------|--------:|
| 0–30m | −29,451 |
| 30–60m | −12,116 |
| 1–2h | +5,185 |
| 2–4h | −4,035 |
| 4–8h | +88,719 |
| 8h+ | +1,516 |

Edge is almost entirely 4–8h (n=138, WR 74.6%, +$89k). Sub-1h holds are the tax.

### Seasonality that matters

**Entry hour PnL**

| Hour | PnL ($) |
|------|--------:|
| 09 | +4,965 |
| 10 | +28,871 |
| 11 | +15,831 |
| 12 | −1,484 |
| 13 | −636 |
| 14 | +3,791 |
| 15 | −1,006 |
| 16 | −514 |

09–11 ≈ +$49.7k of +$49.8k total. Midday/late flat-to-red except a thin 14:00 bump.

**Other slices**

| Slice | Signal |
|-------|--------|
| Thu / Fri | Best DOW (+$19k / +$12k; WR 62%/59%) |
| Mon / Tue | Weak (~+$4k each, ~50% WR) |
| Recent months | 19/36 positive (53%); worst Jul'24 −$7.6k |
| Fixed horizon | Edge grows 60→480m (+$65→+$453 vs opp) |
| Side | 100% long resistance breakouts |

---

## Ranked recommendations

Ordered by likely impact × ease. Param/gene first; logic only where data demands it.

### #1 · high × easy — Morning / time-budget entry gate

- **Data:** ~all PnL from 09–11 entries; winners need 4–8h; RTH force ~15:55 so post-noon entries structurally cannot reach the edge bucket.
- **Change:** block new entries after ~11:30 ET, or require ≥240–300 min until `force_exit_rth`. Prefer time-budget over hard hour cut (keeps rare good 14:00 if enough clock left — usually not).
- **Risk:** already 0.22 t/d → lower still. Not in headroom GA. Highest confidence filter in this dashboard.

### #2 · high × medium — Breakeven / protective trail after MFE threshold

- **Data:** 45% of Stop trades had MFE > $250 then closed red; SS−SR −$17.7k; Opposite Zone already captures ~82% — the leak is failed breakouts that were briefly green.
- **Change:** once MFE ≥ $250 (or ~0.5 ATR), move stop to entry ± costs; optional ATR trail after that. Keep TP off; do not replace opposite-zone exit.
- **Risk:** scratches trades that currently dip then reach opposite zone. Threshold A/B required. Trail currently locked off — new gene/logic.

### #3 · med-high × easy · partial — Raise Entry Headroom above 0.5 ATR

- **Data:** fail-fast 0–30m bucket −$29k @ 25% WR fits stuffed breakouts into nearby stacked R. Sol2 deploy CSV already sets Entry Headroom=0.5 and this backtest applied it.
- **Change:** raise to 0.75–1.0 ATR (or let headroom GA pick). Note: oppdist05 GA CSV has no Headroom gene — 0.5 was deploy default, not evolved for Sol2.
- **Risk:** Already partial: strategy gene + Sol2=0.5 on. Headroom GA at gen 25 (status not final) may supersede a manual bump. Do not claim Sol2 “lacks” headroom — it has the floor value.

### #4 · medium × medium — Improve forced-flatten capture (Maintenance / EOD)

- **Data:** 40% of exits, +$87k but med capture only 53% (avg 32%) vs Opposite Zone 82%. Leaves open profit when session ends.
- **Change:** N minutes before force_exit, if MFE > $X tighten to breakeven/trail or market-out if giveback from MFE exceeds Y%. Complements #1 (fewer doomed late entries).
- **Risk:** can cut the 65% already-green maintenance winners. Evidence for magnitude is softer than stop green-then-red.
- **Clarification:** #1 (entry buffer) only stops *new* late entries. It does **not** help open winners already in profit when maintenance/RTH force-flat fires — that capture problem is still this item.

### #5 · medium × easy — Slightly higher Volume Mult floor

- **Data:** Sol2 Vol Mult=1.19 (near 1.0 floor) while Strength is already selective (4.36). Weak breakouts cluster in sub-1h stop outs.
- **Change:** raise Volume Mult min/lock to ~1.4–1.6, or require breakout bar volume in top quartile of session.
- **Risk:** activity drop; overlaps with #1/#3. Weaker standalone evidence than TOD or MFE trail.
- **Decision:** No forced floor for now. ~1.19 is what IS Sortino/activity fitness selected under costs (lower mult → more trades); 1.4–1.6 was an analyst hypothesis from edge concentration, not the GA optimum.

### #6 · open — Long-only vs two-sided (softened)

- **Data:** opposite-*entry* flip diagnostic (long↔short on same SS timestamps) net −$64k; Sol2 Shorts=0 by genome.
- **Clarification:** That flip test is **not** the same policy as enabling short breakouts of support. Flip-losing ≠ “shorts can never work.”
- **Status:** Sol2 remains long-only by choice; keeping shorts off is **not** a hard conclusion. Two-sided search (e.g. Sol72 / unlocked Enable Short Trades) remains a valid experiment.

### Anti-reco — Do not shorten Max Hold

Max Hold=32×14m≈7.5h rarely fires (3 time exits). Edge lives in 4–8h. Shortening would tax the only profitable hold bucket. Prefer entry time-budget (#1) over earlier time exits.

---

## Context vs prior findings

| Topic | This Sol2 dashboard | Status |
|-------|---------------------|--------|
| Entry Headroom | Deploy CSV = 0.5 ATR (applied) | Partial — not GA-evolved; raise or await headroom GA |
| Min opp zone dist 0.5 | Locked; Opposite Zone 100% WR / 82% capture | Working — keep |
| Long-only / TP&trail off | Sol2 genome long-only; flip ≠ short policy | Softened — two-sided still valid |
| Fail-fast stops / MFE>$250 then red | 45% of stops | Open — #2 trail/BE |
| SS−RS vs SS−SR | +$62k entry / −$18k exit | Open — exit path #2/#4 |
| Maintenance capture ~53% | Confirmed med 53.4% | Open — #4 |
| GA Sol2 vs Sol0 (OOS) | Sol2 OOS +$17.3k PF 1.18 vs Sol0 +$6.1k PF 1.07 | Sol2 is the stronger export candidate |

---

## Suggested next experiment order

1. ~~Replay Sol2 with entry cutoff / time-budget only~~ → **genes landed** (`Maintenance Entry Buffer` + unlocked exit buffer).
2. ~~Add MFE→breakeven~~ → **genes landed** (Enable/Trigger/Pad); leave classic trail off.
3. Let headroom GA finish, then **fresh restart** a climate that includes #1+#2 genes (do not kill current headroom run mid-flight).
4. Optional later: forced-flatten capture on open trades (#4) — still open; not solved by entry buffer.

---

*Recovered from canvas `sr-zones-sol2-improvement-brief.canvas.tsx` (content intact; markdown used because the canvas UI would not open).*

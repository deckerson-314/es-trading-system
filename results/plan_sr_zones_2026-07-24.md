# Multi-zone Support/Resistance Breakout — Plan (refresh brief)

**Status:** Diagnostic GA `sr-zones-v1` — **FAIL deploy** (OOS+ 2/80; Sol #0 IS+/OOS−). Comparison GA `sr-zones-v1-oppdist05` (seed 20260725, Min Opposite Zone Dist ATR=0.5) — **PASS deploy lens** (OOS+ 50/93; Sol0 OOS +$6.1k); Sol2 is reference deploy. Headroom GA `sr-zones-v1-headroom` (same seed, headroom unlocked) — **complete / FAIL climate** (OOS+ 4/79; Sol0 OOS−; no 4/5–5/5); GA preferred high headroom (~1.8 ATR) but did not beat Sol2. Not paper until attrib.  
**Suggested package name:** `sr_zones` (aliases: `sr`, `sr_breakout`)  
**Date:** 2026-07-24 (status note 2026-07-25 headroom)  
**Verdict:** `results/ga_analysis_sr_zones_2026-07-25-sr-zones-v1-headroom.md` · prior `…oppdist05.md` · baseline `…2026-07-24-sr-zones-v1.md`

---

## Context (why this is next)

- Folklore RTH pattern GAs (trend, ORB, session VWAP, regime, MIM, candle-v2, EMA cross, reclaim, open-drive) **FAIL** under deploy lens (costs, pessimistic stops, live-style entry, interleaved OOS).
- `tod_hold` proved the toolchain can produce classic **IS+/OOS−** overfitting.
- `session_premium` overnight: naked PASS, protected mostly FAIL; **wrapped / not papering** (weak fidelity vehicle). See `results/wrap_session_premium_2026-07-24.md`.
- Open toolchain gap: **paper ↔ BT fidelity** (stops, trails, signal timing, broker vs sim).
- This S/R zone family is both a **new edge hypothesis** and a **good fidelity vehicle** (zone tests, breakouts, zone/stop exits).

**Hard rules:** never move OHLC out of `C:\Trading\`; never edit production `strategies/trend/parameters/trend_strategy_params.csv`.

---

## User intent (high level)

Support/resistance **breakout** strategy (Pine success historically; Pine is kitchen-sink — **do not clone**; improve into clean v1).

Core mechanics:
- Track multiple support **and** resistance levels (≈3 each or more).
- Each level is a **zone** defined by the candle that made the reversal (body and/or wick).
- **Strength metric** per zone:
  - Increases significantly when the zone is **tested and survives**
  - May weight **volume during the test**
  - **Decays over time**
- Zone removed if strength → 0 or **evicted** when at capacity (newer/stronger zones win).
- Failed support **flips** to resistance (and vice versa).
- **Entry:** breakout of a zone with sufficient strength + volume confirmation.
- **Exits:** may also be defined by zones (and/or stops beyond origin zone).

Pine script: **not required for v1**; optional later to diff quirks.

---

## Agreed clean v1 (strip kitchen sink)

| Piece | v1 proposal |
|--------|-------------|
| Zone geometry | Wick extreme = level; width = `k × ATR` (stable across TFs) |
| Strength | Formation volume seed → large boost on survived test (price enters zone, closes back on defensive side), volume-weighted; **per-bar linear dissipation** (`strength -= Dissipation (per bar)` each bar, floor 0) |
| Capacity | **3 support + 3 resistance**; evict weakest (oldest on tie) |
| Flip | Close through zone → convert S↔R at same band; strength reset/reduced |
| Entry | Close beyond zone + strength ≥ threshold + volume ≥ MA multiple + optional **`Entry Headroom (ATR)`** clearance to next strong opposite zone (overlap-aware; 0 = off) |
| Exit | Opposite strong zone **or** stop beyond breakout origin zone; optional max hold. Opposite-zone TP requires **`Min Opposite Zone Dist (ATR)`** from entry (default/locked **0.5**) so post-entry micro swing zones cannot clip immediately. **No ADX / EMA / RSI in v1** |
| Sides | Long **and** short (natural for S/R) |
| Genes (capped) | TF, zone width `k`, strength threshold, volume mult, **Dissipation (per bar)** (default 0.25, range 0.05–2.0), **Entry Headroom (ATR)** (default 0.5, range 0–2.5; 0=off), stop rule; **Min Opposite Zone Dist (ATR)** locked at 0.5 — **not** kitchen sink |
| Fidelity | Zone tests, breakouts, zone/stop exits stress sim vs paper |

---

## Suggested build path

1. Scaffold `strategies/sr_zones/` (`strategy.py`, `parameters.py`, params CSV, checkpoints dirs).
2. Wire `StrategyFactory`, `optimize.py` PARAM_CSV, `main.py` defaults (mirror `tod_hold` / `open_drive_pullback`).
3. Smoke-test on a 2024 slice (sane trade count, zone lifecycle, flip, breakout entries).
4. Short diagnostic GA (e.g. POP ~150, NUM_GEN ~20–25, `--fresh --run-tag sr-zones-v1`).
5. Judge on OOS+ mass + climate stability; only then consider paper / fidelity harness.

### Example launch (after scaffold)

```text
python optimize.py --strategy sr_zones --fresh --run-tag sr-zones-v1 --cores 6
```

---

## Explicit non-goals (v1)

- Exact Pine duplication
- Stacked filters (ADX, EMA trend, RSI, etc.)
- Large gene space / kitchen-sink exits
- Papering before short GA + smoke look sane

---

## Open design choices (locked at scaffold 2026-07-24)

- Strength boost: `TEST_BOOST=2.0 × (1 + test_vol/vol_ma)` fixed
- Flip strength: `0.5 × pre_break`
- Exit priority: Maint/RTH → origin-zone stop → opposite strong zone (reach from approach side, only if zone ≥ `Min Opposite Zone Dist (ATR)` from entry; default/locked 0.5) → max hold
- Zone touch (test): wick into zone + close back on defensive side
- Volume MA length: fixed 20 (not a gene)
- **Strength aging (2026-07-24):** per-bar linear dissipation at **bar open**, then survived-test boosts, then flip/entry/form — so a same-bar reinforcement is not wiped by that bar’s dissipation
- **Entry headroom (2026-07-25):** after strength+volume qualify, reject long if any other strong R still has `hi ≥ close` and `max(0, lo−close) < headroom×ATR` (symmetric for shorts vs strong S). Broken origin excluded. Gene optimizable; running GA mid-run will not pick it up — needs fresh/new run.

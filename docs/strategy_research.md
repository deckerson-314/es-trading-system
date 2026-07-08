# Intraday Strategy Research — Trend, Session, ORB

**Last updated:** 2026-07-08  
**Scope:** Completed GA runs on ES (2020–2025), four-quadrant attribution, comparison to practitioner backtests and academic ORB/VWAP literature.  
**Purpose:** Record what we learned, why each hypothesis failed, and specify the **next strategy to optimize** — targeting **~1–4 trades/day** for faster statistical testing.

---

## Executive summary

| Strategy | GA run | OOS PnL (Sol #0) | OOS PF | OOS trades | OOS+ HOF | Attribution: entry (SS−RS) | Verdict |
|----------|--------|------------------|--------|------------|----------|----------------------------|---------|
| **Trend** (Donchian) | 2026-07-03 | −$36,757 | 0.88 | 639 | 0 / 1,333 | −$35.9k (RS n=5*) | **FAIL** |
| **Session** v1 (VWAP fade) | 2026-07-04 | −$10,151 | 0.61 | 135 | 0 / 1,196 | −$8.5k MC med | **FAIL** |
| **Session** v2 | 2026-07-05 | −$18,453 | 0.35 | 225 | 0 / 2,164 | −$13.6k MC med | **FAIL** |
| **ORB** acceptance | 2026-07-06 | −$2,861 | 0.68 | 34 | 58 / 820 | −$3.3k MC med | **FAIL** (Sol #0) |

\*Trend RS quadrant had a small-sample bug early in attribution (5 trades); entry failure is still clear from SS vs RR and direction diagnostics.

**Cross-cutting finding:** All four hypotheses show **negative entry selection** (strategy entries worse than random OOS timing with matched hold). **Exit logic** sometimes helps (Session v1, ORB) but cannot fix wrong-side entries. **Opposite-direction** diagnostics are often positive — direction/timing is wrong, not always a simple sign flip.

**Best relative result:** ORB **Solution_534** — +$3,525 OOS on interleaved slices (PF 1.33), but only **7%** of HOF OOS-positive; **34 contiguous OOS trades** on Sol #0 is too sparse for confidence.

**Recommended next hypothesis:** **`vwap_regime`** — regime-switching between **VWAP pullback (trend days)** and **VWAP deviation fade (range days)**, targeting **1–4 trades/day**, reusing session/OR/VWAP infrastructure. Detailed spec in [§7](#7-recommended-next-strategy-vwap_regime).

---

## 1. Methodology

### 1.1 GA setup (common)

- **Engine:** NSGA-II, 200 generations, pop 400, interleaved IS/OOS (`USE_INTERLEAVED_SPLIT`, 11 OOS slices).
- **Data:** ES continuous, ~2020-01-02 → 2025-10-10, 5-min bars (strategy-dependent).
- **Fitness:** Multi-objective — Sortino, drawdown, PF, trades/day, PnL, profit/trade (penalized/normalized).
- **Selection artifact:** Solution #0 = rank #1 on **interleaved IS fitness**, not necessarily best **contiguous OOS**.

### 1.2 Validation gates (deploy bar)

| Gate | Threshold |
|------|-----------|
| Contiguous OOS PnL | > $0 |
| OOS PF | > 1.0 |
| SS − RS (MC median) | > −$2,000 |
| Entry beats opposite | > 50% |
| Trade count (OOS) | Enough for inference (~100+ preferred) |

### 1.3 Four-quadrant attribution

| Quadrant | Meaning |
|----------|---------|
| **SS** | Strategy entry + strategy exit (actual export) |
| **SR** | Strategy entry + random hold exit |
| **RS** | Random OOS entry + strategy hold duration |
| **RR** | Full random (MC median) |

- **SS − RS** → entry selection effect (negative = entries harmful).  
- **SS − SR** → exit path effect (positive = exits help vs random hold).  

Tool: `python tools/analysis/strategy_attribution.py --strategy <name> --trades <oos.csv>`

---

## 2. Trend (Donchian breakout)

**Status:** Deprecated (`strategies/trend/DEPRECATED.md`)  
**Run:** `Trend/parameters/genetic_results_2026-07-03-1.csv` · 200 gens · 1,333 HOF  
**Attribution:** `results/attribution_jul03.md`

### 2.1 Best GA solutions

| | Solution #0 | Best OOS (HOF) |
|--|-------------|----------------|
| **OOS PnL** | −$36,757 | −$33,480 (Sol #39) |
| **IS PnL** | +$174,442 | +$159,072 |
| **OOS PF** | 0.88 | 0.89 |
| **OOS trades/day** | 0.78 | 0.79 |
| **OOS profitable** | — | **0 / 1,333** |

Classic **IS overfit**: large positive IS, deeply negative OOS; **no** HOF genome positive on slice-OOS.

### 2.2 Four-quadrant (639 OOS trades)

| Quadrant | Net PnL | Win% | PF |
|----------|---------|------|-----|
| SS | −$36,757 | 37.9% | 0.88 |
| SR | −$13,988 | 49.9% | 0.96 |
| RS | −$839 | 40.0% | 0.52 |
| RR | −$71 MC med | 48.5% | — |

- **SS − RS:** −$35,917 (entry selection strongly anti-predictive).  
- **SS − SR:** −$22,769 (exits also destroy value vs random hold on these entries).  
- **Opposite direction:** +$17,587; beats opposite **38%** of the time.  
- **Fixed horizon:** Short horizons negative edge; 240–480 min slightly positive — chasing closes, late exit noise.

### 2.3 Why it failed

- Donchian **breakout at bar close** buys/sells **extended** moves on ES.  
- High trade frequency (~0.37/day export, 639 OOS trades) but **no OOS edge**.  
- Attribution: **entries** are the primary failure; strategy loses to **random trading** (RR ≈ −$71 vs SS −$37k).

### 2.4 vs literature / community

- Academic trend-following on **daily** horizons works; **intraday Donchian on ES** is not a standard published edge.  
- Practitioner intraday trend uses **level-based** entries (OR, VWAP hold), not **close-chase** — aligns with our failure mode.

---

## 3. Session VWAP mean reversion

**Status:** Deprecated (`strategies/session/DEPRECATED.md`)  
**Hypothesis:** Fade VWAP extensions after opening range; ADX cap for range days.

### 3.1 Session v1 (2026-07-04)

**Run:** `Session/parameters/genetic_results_2026-07-04-1.csv` · 1,196 HOF  
**Attribution:** `results/attribution_session_oos_2026-07-04.md`

| | Solution #0 | Best OOS |
|--|-------------|----------|
| **OOS PnL** | −$10,151 | −$7,481 (Sol #1115) |
| **IS PnL** | +$5,447 (slice) | +$1,863 |
| **OOS PF** | 0.61 | 0.75 |
| **OOS trades** | 135 | — |
| **OOS profitable HOF** | 0 / 1,196 | |

**Four-quadrant (135 trades):**

| SS | SR | RS MC | RR MC |
|----|-----|-------|-------|
| −$10,151 | +$292 | −$1,678 | +$21 |

- **SS − RS:** −$8,473 (entries fail).  
- **SS − SR:** −$10,443 (exits fail badly — high WR 55% but small wins / large losses).  
- **Opposite dir:** +$6,101 (56% beat opposite at point level — misleading; full flip backtest still failed).

### 3.2 Session v2 (2026-07-05)

**Changes:** Reversion confirm bars, tighter stops, calendar gap exits, maintenance exit.  
**Run:** 2,164 HOF · **worse** than v1.

| | Solution #0 | Best OOS |
|--|-------------|----------|
| **OOS PnL** | −$18,453 | −$999 (Sol #921) |
| **IS PnL** | −$1,449 | −$4,086 |
| **OOS PF** | 0.35 | 0.34 |
| **OOS trades** | 225 | — |

**Four-quadrant (225 trades):** SS −$18,453 · SS−RS −$13,606 · opposite +$11,703.

v2 increased activity and **deepened** losses — filters did not fix fade-on-momentum regime.

### 3.3 vs literature / community

| Source | Claim | Our result |
|--------|-------|------------|
| [CrossTrade VWAP reversion](https://crosstrade.io/learn/trading-strategies/vwap-reversion) | 2–5 trades/day, PF 1.2–1.6, **ADX filter mandatory** | We faded with ADX **cap** (range); ES often **trends** intraday → wrong regime |
| [ES VWAP Deviation backtest](https://pinescriptforge.com/es/vwap-deviation/backtest) | ~760 trades / 3yr, PF 1.40, WR 47% | Similar VWAP idea but **2σ + confirmation**, not OR fade |
| Practitioner (TraderVerdict, etc.) | Fade **1.5–2σ** with **session-type filter**, 10:00–14:00 | We traded too early/wide; no trend/range switch |

**Lesson:** VWAP **fade alone** on ES is literature-supported only with **strict regime gating** and **deviation bands** — not generic “extended from VWAP after OR.”

---

## 4. ORB acceptance breakout

**Status:** Failed validation (Sol #0); archive may contain slice-OOS winners for follow-up.  
**Run:** `Orb/parameters/genetic_results_2026-07-06-1.csv` · 820 HOF · ~1d 12h  
**Attribution:** `results/attribution_orb_oos_2026-07-06.md`  
**Analysis:** `results/ga_analysis_orb_2026-07-06-1.md`

### 4.1 Best GA solutions

| | Solution #0 | Best OOS (Sol #534) |
|--|-------------|---------------------|
| **OOS PnL (slices)** | −$2,861 | **+$3,525** |
| **IS PnL** | +$10,842 | +$8,340 |
| **OOS PF** | 0.68 | 1.33 |
| **OOS trades/day** | 0.04 | 0.06 |
| **Contiguous OOS trades** | 34 | (not exported) |
| **OOS profitable HOF** | — | **58 / 820 (7%)** |

**Solution #0 params (GA winner):** 56-min OR, 2-bar acceptance, **2.38× OR target**, ATR stop (no opposite-OR stop), VWAP filter off, 1 entry/day.

**Solution #534 (best slice-OOS):** 56-min OR, **4-bar acceptance**, min ADX **22.4**, 2 entries/day, 2.5× OR target.

### 4.2 Four-quadrant (34 contiguous OOS trades)

| SS | SR MC | RS MC | RR MC |
|----|-------|-------|-------|
| −$2,861 | −$3,735 | +$442 | −$199 |

- **SS − RS:** −$3,303 (entries anti-predictive).  
- **SS − SR:** +$874 (exits slightly help).  
- **Opposite dir:** +$1,841; beats opposite **32%**.  
- **30-min horizon:** +3 pts edge; **120+ min:** negative — late breakouts fade.

### 4.3 Convergence note

Mid-run (~gen 40) dashboard showed **+$212 OOS** on interleaved slices; **final** Solution #0 = **−$2,861** contiguous. GA favored **IS Sortino**, not OOS PnL — classic interleaved overfit.

### 4.4 vs literature / community

| Source | Typical ES ORB | Our ORB v1 |
|--------|----------------|------------|
| [Huang et al. 2019 TORB](https://doi.org/10.1109/access.2019.2899177) | **Short** US probe window; >8% annual on index futures 2003–2013 | **56-min** OR on 5-min bars |
| [Zarattini et al. ORB equities](https://www.alexandria.unisg.ch/handle/20.500.14171/122125) | **5-min** OR best; stocks-in-play cross-section | Single ES; **0.02 trades/day** |
| [TradingStats ORB guide](https://tradingstats.net/orb-breakout-strategy-guide/) | 30-min OR + 5m **close** confirm → ~71% continuation; **50–100% OR targets** | **238% OR target** → WR 32% |
| [Edgeful 5-min ES ORB](https://www.edgeful.com/blog/posts/5-minute-opening-range-breakout-es-strategy) | 115 trades / 6 mo, PF 1.62, **50% OR target** | 34 trades / 5 yr |
| [Volatility states paper](https://www.diva-portal.org/smash/get/diva2:732318/FULLTEXT02.pdf) | ORB **negative in low vol**, positive in high vol | Weak vol-regime integration |

**Lesson:** Our ORB was **too sparse**, **too late** (acceptance on long OR), **too ambitious** on targets — opposite of practitioner baselines that show PF 1.5+ with **hundreds of trades**.

---

## 5. Cross-strategy patterns

### 5.1 What failed (in order of evidence)

1. **Entry selection (SS − RS < 0)** — Trend, Session v1/v2, ORB.  
2. **Wrong direction** — opposite-direction diagnostic positive in 3/4 runs.  
3. **Exit logic** — secondary; Session v1 exits especially harmful; ORB exits mildly helpful.  
4. **IS/OOS gap** — Trend and ORB show strong IS, negative contiguous OOS.  
5. **Interleaved GA** — optimizes slice noise; mid-run OOS can mislead.

### 5.2 Trade frequency vs testability

| Strategy | OOS trades | ~Trades/day | Statistical power |
|----------|------------|-------------|-------------------|
| Trend | 639 | 0.37 | Good N; no edge |
| Session v1 | 135 | 0.08 | Moderate N; no edge |
| Session v2 | 225 | 0.13 | Moderate N; worse edge |
| ORB | 34 | **0.02** | **Too few** |

User preference: **handful/day (1–5)** for faster iteration — ORB was **too sparse**; Trend/Session were acceptable frequency but wrong logic.

### 5.3 Infrastructure that worked

- GA engine, interleaved splits, attribution tooling (post RNG fix).  
- Session indicators: **VWAP, OR, ADX, RTH/maintenance**.  
- NSGA-II on hostile landscapes still finds **IS** optima — need **OOS-attribution gates** before trusting convergence.

---

## 6. Literature & practitioner benchmark table

| Strategy class | Typical frequency (ES) | WR / PF (claimed) | Regime / filter | Key sources |
|----------------|------------------------|-------------------|-----------------|-------------|
| **5–15 min ORB** | 0.3–1.5/day | WR 54–72%, PF 1.5–1.6 | Wide OR, close confirm, 50–100% target | [Edgeful](https://www.edgeful.com/blog/posts/5-minute-opening-range-breakout-es-strategy), [PineScriptForge ORB](https://pinescriptforge.com/ES/opening-range-breakout/backtest), [TradingStats](https://tradingstats.net/orb-breakout-strategy-guide/) |
| **TORB (futures)** | Varies | >8% annual 2003–2013 | **Short** probe US | [Huang IEEE 2019](https://doi.org/10.1109/access.2019.2899177) |
| **VWAP deviation fade** | ~1/day (~760/3yr) | WR 47%, PF 1.40 | **2σ**, confirmation | [PineScriptForge VWAP dev](https://pinescriptforge.com/es/vwap-deviation/backtest) |
| **VWAP scalp** | ~1/day | WR 54%, PF 1.37 | Tight revert to VWAP | [PineScriptForge scalp](https://pinescriptforge.com/es/vwap-scalp/backtest) |
| **VWAP pullback trend** | **2–4/day on trend days** | WR 60–65% 1st pullback | **Trend day** only | [NexusFi playbook](https://nexusfi.com/a/strategies/es-futures-trading-strategies) |
| **VWAP fade (range)** | 2–5/day | WR 55–65%, PF 1.2–1.6 | **ADX low**, news filter | [CrossTrade](https://crosstrade.io/learn/trading-strategies/vwap-reversion) |
| **Intraday mean rev (academic)** | Capped turnover | Walk-forward OOS | Vol + costs explicit | [Zanetti GitHub MR](https://github.com/marcozanetti-dev/intraday-mean-reversion-costs-aware) |

**Gap in our tests:** We never ran a **regime switch** (trend vs range) or **literature-standard ORB** (5–15m, 50% target). We ran **fade-only** (Session) and **sparse long-OR breakout** (ORB).

---

## 7. Recommended next strategy: `vwap_regime`

### 7.1 Hypothesis

ES intraday edge is **regime-dependent**:

- **Trend days:** Trade **with** direction — **VWAP pullback** entries (institutions defend VWAP).  
- **Range days:** Trade **mean reversion** — **VWAP deviation fade** at ~1.5–2σ with rejection.

Single-mode Session (always fade) and ORB (always break) both **force one mode on all days** → attribution entry failure.

This matches:

- [NexusFi](https://nexusfi.com/a/strategies/es-futures-trading-strategies): fade VWAP on balance days, **buy pullbacks** on trend days.  
- [CrossTrade](https://crosstrade.io/learn/trading-strategies/vwap-reversion): fade only when **ADX low**.  
- [TradingStats](https://tradingstats.net/orb-strategy-research/): OR direction + **wide OR** + OR-candle direction as filters (reuse for regime).

### 7.2 Proposed logic (v1)

**Shared:** Session VWAP (RTH reset), ATR, ADX, opening range (15–30 min), RTH/maintenance flat.

**Regime classifier (GA-tunable):**

- **Trend mode** if: price predominantly on one side of VWAP since OR complete **and** ADX > threshold **and/or** OR width in “wide” band.  
- **Range mode** if: ADX < cap **and** OR width moderate **and** price crossing VWAP repeatedly.

**Trend mode — VWAP pullback:**

- After 30–60 min from open, enter on **touch/reject VWAP** in direction of session bias (price > VWAP → long pullback only).  
- Stop: below VWAP − k×ATR or session structure.  
- Target: prior swing or 1.5–2× stop.  
- Cap: 2–3 entries/day.

**Range mode — VWAP deviation fade:**

- Enter when price closes beyond **±z×VWAP band** (z ≈ 1.5–2.0) **and** rejection bar (revert toward VWAP).  
- Target: VWAP or opposite 0.5σ.  
- Stop: beyond band + buffer.  
- Cap: 2–3 entries/day.

**Hard rules:**

- No fade in trend mode; no breakout chase in range mode.  
- No entries first 30 min (VWAP unstable) or last 30–60 min.  
- Skip maintenance / calendar gaps (reuse Session v2 path).

### 7.3 Expected frequency

| Source | Trades/day |
|--------|------------|
| CrossTrade VWAP fade | 2–5 (range days) |
| NexusFi VWAP pullback | 1–3 (trend days) |
| **Target for GA** | **1.0–4.0** |

Much better than ORB **0.02/day**; similar order to literature VWAP systems (~760 trades / 3 yr ≈ **1/day**).

### 7.4 GA parameter targets (initial)

| Parameter | Proposed `Value` | Rationale |
|-----------|------------------|-----------|
| `TARGET_TRADES_DAY` | **2.0** | Center of 1–4 band |
| `MIN_TRADES_DAY` | **0.25** | ~1 trade every 4 days floor |
| `NORM_TRADES_MAX` | **3.0** | Align with Trend/Bollinger scale |
| `Max Entries Per Day` | **3** (optimizable 2–5) | Handful/day cap |
| `WEIGHT_PNL` | **1.0** | Contiguous edge matters |

### 7.5 Pass/fail gates (unchanged)

Run attribution on **every** GA export; reject Sol #0 automatically if SS−RS MC med < −$2k even when slice-OOS positive.

### 7.6 Implementation reuse

| Module | Reuse |
|--------|-------|
| `strategies/session/indicators.py` | VWAP, OR, bands |
| `strategies/bollinger/filters.py` | RTH, maintenance |
| `optimize.py` / attribution | Unchanged |
| New | `strategies/vwap_regime/strategy.py`, params CSV |

**CLI:** `--strategy vwap_regime`

### 7.7 Alternative B (if Regime v1 fails): **ORB v2 (literature baseline)**

Minimal ORB aligned with published ES backtests — not a regime switch:

- **5–15 min OR** (not 56).  
- **Close beyond OR** + optional 1-bar confirm (not 4).  
- **Target 0.5–1.0× OR width**; stop **opposite OR**.  
- Filters: wide OR tier, OR-candle direction, **long-only** toggle, vol state.  
- Expected **0.3–1.5 trades/day**, 100+ trades per OOS window.

Use as **controlled experiment** against ORB v1 to separate “GA failed” vs “ORB class failed.”

---

## 8. Research backlog

| Priority | Task |
|----------|------|
| P0 | Implement `vwap_regime` v1 + params CSV + tests |
| P0 | Export + attribute **ORB Solution_534** (best slice-OOS) |
| P1 | ORB v2 literature baseline (5-min OR, 50% target) |
| P1 | GA: add post-run auto-attribution gate in export pipeline |
| P2 | Regime labels vs PnL (trend/range/chop day taxonomy) |
| P2 | Fix Trend attribution RS sample size for old runs |

---

## 9. Artifact index

| Strategy | GA CSV | OOS trades | Attribution |
|----------|--------|------------|-------------|
| Trend | `Trend/parameters/genetic_results_2026-07-03-1.csv` | `Trend/output/genetic_trades_oos_2026-07-03-1.csv` | `results/attribution_jul03.md` |
| Session v1 | `Session/parameters/genetic_results_2026-07-04-1.csv` | `Session/output/genetic_trades_oos_2026-07-04-1.csv` | `results/attribution_session_oos_2026-07-04.md` |
| Session v2 | `Session/parameters/genetic_results_2026-07-05-1.csv` | `Session/output/genetic_trades_oos_2026-07-05-1.csv` | `results/attribution_session_oos_2026-07-05.md` |
| ORB | `Orb/parameters/genetic_results_2026-07-06-1.csv` | `Orb/output/genetic_trades_oos_2026-07-06-1.csv` | `results/attribution_orb_oos_2026-07-06.md` |
| ORB analysis | — | — | `results/ga_analysis_orb_2026-07-06-1.md` |

---

## 10. References

### Academic

- Huang, Y.-H., et al. (2019). *Assessing the Profitability of Timely Opening Range Breakout on Index Futures Markets.* IEEE Access. [DOI](https://doi.org/10.1109/access.2019.2899177)  
- Zarattini, C., et al. (2023). *A Profitable Day Trading Strategy For The U.S. Equity Market.* [UniSG](https://www.alexandria.unisg.ch/handle/20.500.14171/122125)  
- *Day trading returns across volatility states* (ORB on S&P 500 futures). [Diva Portal PDF](https://www.diva-portal.org/smash/get/diva2:732318/FULLTEXT02.pdf)  
- Zanetti, M. *Intraday mean-reversion with costs and walk-forward.* [GitHub](https://github.com/marcozanetti-dev/intraday-mean-reversion-costs-aware)

### Practitioner / research blogs

- [TradingStats ORB guide](https://tradingstats.net/orb-breakout-strategy-guide/) · [ORB deep dive](https://tradingstats.net/orb-strategy-research/)  
- [Edgeful 5-min ES ORB](https://www.edgeful.com/blog/posts/5-minute-opening-range-breakout-es-strategy)  
- [CrossTrade VWAP reversion](https://crosstrade.io/learn/trading-strategies/vwap-reversion)  
- [NexusFi ES playbook — VWAP pullback](https://nexusfi.com/a/strategies/es-futures-trading-strategies)  
- [PineScriptForge ES backtests](https://pinescriptforge.com/es/vwap-deviation/backtest) (VWAP deviation, ORB, scalp — treat as marketing, useful for magnitude benchmarks)

---

*Document owner: research track. Update after each completed GA + attribution cycle.*

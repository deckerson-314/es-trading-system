# Intraday Strategy Research — Trend, Session, ORB, VWAP Regime

**Last updated:** 2026-07-11  
**Scope:** Completed GA runs on ES (2020–2025), four-quadrant attribution, comparison to practitioner backtests and academic ORB/VWAP/MIM literature. Fresh literature/forum survey 2026-07-10 for next hypothesis.  
**Purpose:** Record what we learned, why each hypothesis failed, and specify the **next strategies to optimize** — targeting **~0.5–4 trades/day** for faster statistical testing.

---

## Executive summary

| Strategy | GA run | OOS PnL (Sol #0) | OOS PF | OOS trades | OOS+ HOF | Attribution: entry (SS−RS) | Verdict |
|----------|--------|------------------|--------|------------|----------|----------------------------|---------|
| **Trend** (Donchian) | 2026-07-03 | −$36,757 | 0.88 | 639 | 0 / 1,333 | −$35.9k (RS n=5*) | **FAIL** |
| **Session** v1 (VWAP fade) | 2026-07-04 | −$10,151 | 0.61 | 135 | 0 / 1,196 | −$8.5k MC med | **FAIL** |
| **Session** v2 | 2026-07-05 | −$18,453 | 0.35 | 225 | 0 / 2,164 | −$13.6k MC med | **FAIL** |
| **ORB** acceptance | 2026-07-06 | −$2,861 | 0.68 | 34 | 58 / 820 | −$3.3k MC med | **FAIL** (Sol #0) |
| **VWAP Regime** v1 | 2026-07-08 | −$12,732 | 0.73 | 220 | 1 / 2,212 | −$10.8k MC med | **FAIL** |
| **VWAP Regime** v2 | 2026-07-10 | −$3,349 | 0.71 | 60 | 0 / 2,759 | −$2.7k MC med | **FAIL** — family dead |

\*Trend RS quadrant had a small-sample bug early in attribution (5 trades); entry failure is still clear from SS vs RR and direction diagnostics.

**Cross-cutting finding:** All completed hypotheses show **negative entry selection** (strategy entries worse than random OOS timing with matched hold). **Exit logic** sometimes helps (Session v1, ORB, VWAP Regime v1) but cannot fix wrong-side entries; v2 exits **hurt**. **Opposite-direction** USD is often tautological for losers — use `% beats opposite` + full flip replay.

**Best relative result:** ORB **Solution_534** — +$3,525 OOS on interleaved slices (PF 1.33), but only **7%** of HOF OOS-positive; **34 contiguous OOS trades** on Sol #0 is too sparse for confidence.

### Recommended next hypotheses (2026-07-11)

| Priority | Strategy | Why | Status |
|----------|----------|-----|--------|
| **DONE** | `vwap_regime` v1+v2 | ADX lock did not create OOS+ HOF; activity collapsed; SS−RS & SS−SR both negative on v2 Sol #0 | **Family closed** — `results/ga_analysis_vwap_regime_2026-07-10-1.md` |
| **P1** | **`orb_v2` — literature ORB baseline** | Practitioner consensus (5–15m OR, 0.5× target, opposite-OR stop) ≠ our failed ORB v1 | Spec §9 |
| **P1** | **`mim` — Market Intraday Momentum** | Strongest *academic* OHLC-only edge (Gao et al. JFE 2018; Baltussen et al. JFE 2021) | Spec §10 |
| **P2** | Internals-gated ORB / false-break fade | NexusFi: TICK/VOLD confirmation | Needs new data feed |
| **Skip** | ICT/FVG, DL, Bollinger revive, further VWAP-regime retunes | — | — |

**Decision rule:** `vwap_regime` closed. Implement **ORB v2** and/or **MIM**. Do not re-tune Session fade, Donchian Trend, or VWAP-regime.

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

### 7.4 GA parameter targets

| Parameter | v1 | **v2 (2026-07-10)** | Rationale |
|-----------|----|---------------------|-----------|
| `Enable ADX Filter` | 0–1 | **LOCKED = 1** | Sol #0 disabled regime gate |
| `Timeframe (minutes)` | 3–15 | **LOCKED = 5** | Literature-like bars |
| `TARGET_TRADES_DAY` | 2.0 | **2.0** | Center of 1–4 band |
| `MIN_TRADES_DAY` | 0.25 | **0.5** | Sol #0 ~0.27 barely bound |
| `NORM_TRADES_MAX` | 3.0 | **3.0** | Align with Trend/Bollinger |
| `Min VWAP Extension` | 4–18 | **4–12** | Sol #0 ~16 too rare |
| `Fade Band ATR Mult` | 1.2–2.5 | **1.2–2.0** | Tighter σ-band |
| `Fade/Pullback Confirm` | 1–3 | **1–2** | Less delay |
| `Pullback Touch Buffer` | 0.25–3 | **0.5–2.0** | Sol #0 too tight |
| `Trade Start After OR` | 0–45 | **15–45** | VWAP stable window |
| `Max Hold (bars)` | 18–72 | **12–36** | ~1–3h at TF=5 |
| `Max Entries Per Day` | 2–5 | **2–5** | Handful/day cap |

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

### 7.7 Alternative B (if Regime fails): **ORB v2** — see §8

### 7.8 Alternative C: **Market Intraday Momentum** — see §9

---

## 8. Literature / forum survey (2026-07-10) → next strategy

### 8.1 What the literature agrees on

| Theme | Source class | Claim | Fit for our stack |
|-------|--------------|-------|-------------------|
| **Day-type first** | NexusFi Academy (2026) | ~70% balance / ~30% trend; wrong tool on wrong day = structural loss | We tried via ADX+VWAP (`vwap_regime`); v1 failed, v2 pending |
| **Short ORB + 0.5× target** | Edgeful, Trade That Swing, TradingStats, PineScriptForge | 5–15m OR, close beyond OR, stop opposite OR, target **0.5× OR width** | **Not tested** — our ORB v1 used long OR + multi-bar accept + sparse entries |
| **ORB acceptance** | NexusFi | 5m close beyond OR + short hold outside raises WR ~42%→55–60% | Partial overlap with ORB v1; v1 over-confirmed (4 bars) + wrong OR length |
| **OAIR / OAOR** | NexusFi / Market Profile | Open inside prior RTH range → balance (~80%); open outside → trend (~80%) | **OHLC-only filter** — unused so far; good ORB v2 gate |
| **VWAP pullback (trend) / fade (range)** | NexusFi, CrossTrade | Regime-conditional VWAP | Session fade alone failed; regime v1 failed; v2 running |
| **Market Intraday Momentum** | Gao/Han/Li/Zhou (JFE 2018); Baltussen et al. (JFE 2021) | First half-hour (or rest-of-day) return predicts **last 30 min** | **Never tested**; OHLC-only; ~1 trade/day |
| **Internals (TICK/VOLD/ADD)** | NexusFi | Confirm OR breaks; fade non-confirmed breaks | Needs new data — P2 |
| **ICT / FVG / IFVG** | TradeZella, student papers | Liquidity sweep + FVG inversion on ES/NQ | Discretionary / hard to GA; skip |
| **Deep learning forecasts** | arXiv GCN-LSTM, wavelet-BLSTM | Predict ES returns / vol | Out of scope for current GA engine |

### 8.2 Why our failures do **not** kill the literature recipes

| Our run | What we actually tested | Literature recipe we did **not** test |
|---------|-------------------------|--------------------------------------|
| Session v1/v2 | Generic VWAP fade after OR | Strict σ-band + ADX-on + session-type gate |
| ORB v1 | Long OR (~30–56m), multi-bar acceptance, sparse | **5–15m OR, 1-bar close, 0.5× target, opposite-OR stop** |
| VWAP Regime v1 | GA turned ADX **off**; ~0.27 trades/day | ADX locked + ~1–2/day (v2 now) |
| Trend | Donchian chase all day | Not a published ES day-trading core setup |

**Implication:** ORB class is **not falsified** until ORB v2 matches published geometry. VWAP-regime class is **one constrained re-run** from falsification.

### 8.3 Ranking for *this* repo

1. **ORB v2 (literature baseline)** — best controlled experiment; reuses `strategies/orb`; highest practitioner replication density; expected 0.3–1.5 trades/day.  
2. **MIM (`mim`)** — best *new* academic family; orthogonal to ORB/VWAP; simple rules; ~1 trade/day; strong JFE pedigree + futures replication via hedging-demand channel.  
3. **Internals-gated ORB** — only after TICK/VOLD history is available.  
4. **Do not** re-open Session fade or Donchian Trend without a new exogenous signal.

---

## 9. Spec: `orb_v2` — literature ORB baseline

**Class:** extend / retune `OrbAcceptanceStrategy` (or thin `orb_v2` params CSV)  
**CLI:** `--strategy orb` with `strategies/orb/parameters/orb_v2_strategy_params.csv`  
**Goal:** Falsify or validate the **published** ES ORB recipe under our friction + interleaved GA.

### 9.1 Locked / narrow search (do not re-discover long OR)

| Parameter | Literature default | GA range |
|-----------|-------------------|----------|
| Opening Range | **5 or 15 min** | lock one run each, or discrete {5, 15} |
| Entry | **1 close** beyond OR (± buffer) | confirm bars **1–2** only |
| Stop | **Opposite OR** | locked |
| Target | **0.5 × OR width** | 0.4–1.0 |
| Max entries/day | **1** | locked |
| Timeframe | **5 min** | locked |
| Max OR width | ~0.55% of price or ATR band | optimizable skip-wide |
| Min OR width | skip dead opens | optimizable |
| OAIR/OAOR filter | optional: only OAOR for breakout; OAIR → no trade or fade mode off | 0/1 lock after smoke |
| Long-only toggle | optional (bull regime) | 0/1 |

### 9.2 Expected frequency & gates

- ~0.3–1.5 trades/day → **100+ OOS trades** preferred.  
- Same deploy gates as §1.2.  
- Compare Sol #0 contiguous OOS to ORB v1 (−$2.9k / 34 trades) and to HOF Sol #534 (+$3.5k slices).

### 9.3 Pass interpretation

| Outcome | Conclusion |
|---------|------------|
| OOS+ and SS−RS > −$2k | ORB class viable → harden filters (OAIR, DOW, vol) |
| Still OOS− / SS−RS ≪ 0 | ORB class dead **under our costs/sim** → stop ORB variants |
| Slice-OOS+ but contiguous− | Selection artifact (same as v1) — do not deploy |

---

## 10. Spec: `mim` — Market Intraday Momentum

**Class:** new `strategies/mim/`  
**CLI:** `--strategy mim`  
**Academic core:** Gao, Han, Li, Zhou (2018), *Market Intraday Momentum*, Journal of Financial Economics — first half-hour return (from prior close) predicts last half-hour return. Baltussen, Da, van der Wel (2021) link last-30m momentum to **options/ETF hedging demand** across futures.

### 10.1 Logic (minimal)

1. Measure **signal return** \(r_{\text{FH}}\) = return from prior RTH close → 10:00 ET (first 30 min), **or** rest-of-day to 15:30 (Baltussen variant — GA toggle).  
2. At **15:30 ET**, enter **same direction** as signal if \(|r_{\text{FH}}|\) > threshold (vol-scaled).  
3. Exit at **16:00 ET** (RTH close) or earlier on stop.  
4. Filters (literature-aligned): high overnight/open vol, high volume day, optional FOMC/CPI calendar skip or *include* (effect stronger on news days).  
5. Cap: **1 trade/day**.

### 10.2 Why this fits after our failures

- Orthogonal to VWAP/ORB geometry (time-of-day momentum, not level breakout).  
- ~1 trade/day → fast attribution sample.  
- OHLC-only (no internals).  
- Clear economic story (rebalancing / late-informed / gamma hedge) — not curve-fit folklore.  
- Risk: published sample ends earlier; must survive **2020–2025 ES** + our pessimistic friction.

### 10.3 GA targets

| Parameter | Value / range |
|-----------|----------------|
| Signal window | FH 09:30–10:00 vs ROD→15:30 |
| Entry time | 15:30 (lock) |
| Exit | 16:00 RTH (lock) |
| Min \|signal\| (ATR mult) | 0.1–0.5 |
| Stop ATR mult | 0.5–1.5 (or none — time exit only) |
| TARGET_TRADES_DAY | 0.8–1.0 |
| MIN_TRADES_DAY | 0.4 |

---

## 11. Research backlog

| Priority | Task |
|----------|------|
| P0 | ~~Finish `vwap_regime` v2~~ **FAIL** — 0/2759 OOS+; Sol #0 OOS −$3.3k; family **closed** (`results/ga_analysis_vwap_regime_2026-07-10-1.md`) |
| P0 | Export + attribute **ORB Solution_534** (best slice-OOS) |
| P0 | ~~Export + attribute vwap_regime Solution_223~~ superseded — v2 closed family |
| P1 | Implement **`orb_v2`** literature baseline (5/15m OR, 0.5× target) — §9 |
| P1 | Implement **`mim`** Market Intraday Momentum — §10 |
| P1 | Fix Timeframe lock/export (Jul-10 all sols showed TF=15 while CSV locked Value=5) |
| P1 | GA: post-run auto-attribution gate in export pipeline |
| P2 | OAIR/OAOR day-type label vs PnL (OHLC-only) |
| P2 | Market internals (TICK/VOLD) data path for ORB confirmation |
| P2 | Re-attribute Trend Jul-03 with current RS code (kill stale n=5 report) |

---

## 12. Artifact index

| Strategy | GA CSV | OOS trades | Attribution |
|----------|--------|------------|-------------|
| Trend | `Trend/parameters/genetic_results_2026-07-03-1.csv` | `Trend/output/genetic_trades_oos_2026-07-03-1.csv` | `results/attribution_jul03.md` |
| Session v1 | `Session/parameters/genetic_results_2026-07-04-1.csv` | `Session/output/genetic_trades_oos_2026-07-04-1.csv` | `results/attribution_session_oos_2026-07-04.md` |
| Session v2 | `Session/parameters/genetic_results_2026-07-05-1.csv` | `Session/output/genetic_trades_oos_2026-07-05-1.csv` | `results/attribution_session_oos_2026-07-05.md` |
| ORB | `Orb/parameters/genetic_results_2026-07-06-1.csv` | `Orb/output/genetic_trades_oos_2026-07-06-1.csv` | `results/attribution_orb_oos_2026-07-06.md` |
| ORB analysis | — | — | `results/ga_analysis_orb_2026-07-06-1.md` |
| VWAP Regime v1 | `Vwap_regime/parameters/genetic_results_2026-07-08-1.csv` | `Vwap_regime/output/genetic_trades_oos_2026-07-08-1.csv` | `results/attribution_vwap_regime_oos_2026-07-08.md` |
| VWAP Regime v2 | `Vwap_regime/parameters/genetic_results_2026-07-10-1.csv` | `Vwap_regime/output/genetic_trades_oos_2026-07-10-1_sol0.csv` | `results/attribution_vwap_regime_oos_2026-07-10_sol0.md` |
| VWAP analysis v1 | — | — | `results/ga_analysis_vwap_regime_2026-07-08-1.md` |
| VWAP analysis v2 | — | — | `results/ga_analysis_vwap_regime_2026-07-10-1.md` |

---

## 13. References

### Academic

- Gao, L., Han, Y., Li, S. Z., & Zhou, G. (2018). *Market Intraday Momentum.* Journal of Financial Economics. [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0304405X18301351) · [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2440866)  
- Baltussen, G., Da, Z., & van der Wel, M. (2021). *Hedging Demand and Market Intraday Momentum.* Journal of Financial Economics. [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0304405X21001598)  
- Huang, Y.-H., et al. (2019). *Assessing the Profitability of Timely Opening Range Breakout on Index Futures Markets.* IEEE Access. [DOI](https://doi.org/10.1109/access.2019.2899177)  
- Zarattini, C., et al. (2023). *A Profitable Day Trading Strategy For The U.S. Equity Market.* [UniSG](https://www.alexandria.unisg.ch/handle/20.500.14171/122125)  
- *Day trading returns across volatility states* (ORB on S&P 500 futures). [Diva Portal PDF](https://www.diva-portal.org/smash/get/diva2:732318/FULLTEXT02.pdf)  
- Zanetti, M. *Intraday mean-reversion with costs and walk-forward.* [GitHub](https://github.com/marcozanetti-dev/intraday-mean-reversion-costs-aware)

### Practitioner / forums

- [NexusFi ES playbook](https://nexusfi.com/a/strategies/es-futures-trading-strategies) — day type, VWAP pullback, ORB acceptance  
- [NexusFi regime detection](https://nexusfi.com/a/automation/regime-detection-automated-trading)  
- [NexusFi market internals](https://nexusfi.com/a/strategies/trading-with-market-internals)  
- [TradingStats ORB guide](https://tradingstats.net/orb-breakout-strategy-guide/) (6,142 days ES/NQ extension probabilities)  
- [Edgeful 5-min ES ORB](https://www.edgeful.com/blog/posts/5-minute-opening-range-breakout-es-strategy)  
- [Trade That Swing ORB](https://tradethatswing.com/opening-range-breakout-strategy-up-400-this-year/) (15m OR, 5m close, 50% target)  
- [CrossTrade VWAP reversion](https://crosstrade.io/learn/trading-strategies/vwap-reversion)  
- [PineScriptForge ES ORB / VWAP](https://pinescriptforge.com/ES/opening-range-breakout/backtest) (marketing benchmarks — use for magnitude only)  
- [Alpha Architect summary of MIM](https://alphaarchitect.com/attention-prop-traders-the-first-half-hour-of-trading-predicts-the-last-half-hour/)

### Explicitly deprioritized

- ICT / IFVG / liquidity-sweep discretionary models (not systematic-GA ready).  
- Wavelet/GCN-LSTM return forecasts (different research program).  
- Unfiltered overnight gap fade (fill rates collapse for large gaps; equity overnight-to-intraday reversal often dies after costs).

---

*Document owner: research track. Update after each completed GA + attribution cycle.*

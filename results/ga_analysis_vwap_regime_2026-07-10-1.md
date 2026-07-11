# VWAP Regime GA Full Analysis — 2026-07-10-1 (v2)

**Run:** 200/200 generations · HOF **2,759**  
**Artifacts:** `Vwap_regime/parameters/genetic_results_2026-07-10-1.csv`, `ga_checkpoint_2026-07-10-1.pkl`  
**Trades (replayed):** `Vwap_regime/output/genetic_trades_oos_2026-07-10-1_sol0.csv`, `..._sol1163.csv`  
**Attribution:** `results/attribution_vwap_regime_oos_2026-07-10_sol0.md`, `..._sol1163.md`  
**Compare-to:** v1 `genetic_results_2026-07-08-1.csv` / `results/ga_analysis_vwap_regime_2026-07-08-1.md`

---

## Executive summary

| Metric | Jul-10 **v2** | Jul-08 **v1** |
|--------|---------------|---------------|
| HOF size | 2,759 | 2,212 |
| OOS-profitable HOF | **0 / 2,759 (0%)** | 1 / 2,212 (0.05%) |
| IS-profitable HOF | **1 / 2,759** (Sol #0 only) | 0 / 2,212 |
| Sol #0 OOS PnL | **−$3,349** | −$12,732 |
| Sol #0 OOS PF | 0.71 | 0.73 |
| Sol #0 IS PnL | **+$2,419** | −$4,720 |
| Sol #0 OOS trades/day | **0.073** | 0.266 |
| Best HOF OOS PnL | **−$992** (Sol 1163) | **+$806** (Sol 223) |
| Best HOF OOS PF | 0.78 (Sol 272) | 1.06 (Sol 223) |
| Best robustness | 36.0 | 50.8 |
| ADX locked ON | **Yes (all sols = 1)** | No (Sol #0 = 0) |
| SS − RS (Sol #0) | **−$2,701** | −$10,796 |
| SS − SR (Sol #0) | **−$3,754** (exits hurt) | +$5,808 (exits helped) |
| **Gate verdict** | **FAIL** | **FAIL** |

v2 achieved the intended ADX lock and cut Sol #0 OOS loss vs v1 (−$3.3k vs −$12.7k), but **destroyed activity** (~0.07 trades/day vs TARGET 2.0 / MIN 0.5) and produced **zero OOS-positive genomes**. The only IS+ solution (Sol #0) overfits a tiny trade set and **fails OOS**; attribution shows **both entries and exits destroy value** (unlike v1, where exits helped).

**Do not deploy any solution from this run. Declare `vwap_regime` family dead under current recipe.**

---

## Hall of Fame distribution (interleaved aggregates)

### Jul-10 v2

- OOS profit: best **−$992**, median **−$104,311**, worst **−$165,509**
- IS profit: best **+$2,419** (Sol #0 only), median **−$143,139**
- OOS PF: best **0.780**, median **0.349**
- OOS trades/day: median **1.20** (many high-activity genomes still lose); Sol #0 **0.073**
- Positive OOS splits: max **2/5** (never ≥3/5)
- Robustness: Sol #0 **8.0**, best **36.0**, median **20.0**

### Top 15 by OOS aggregate PnL (all still negative)

| Sol | OOS PnL | OOS PF | IS PnL | OOS t/d | +OOS splits | Robust |
|-----|---------|--------|--------|---------|-------------|--------|
| 1163 | −$992 | 0.41 | −$3,379 | 0.018 | 1/5 | 28 |
| 2728 | −$1,554 | 0.49 | −$5,396 | 0.019 | 2/5 | 36 |
| 272 | −$1,704 | 0.78 | −$6,043 | 0.054 | 1/5 | 28 |
| 238 | −$1,797 | 0.46 | −$4,003 | 0.024 | 1/5 | 28 |
| 144 | −$1,902 | 0.29 | −$2,498 | 0.016 | 1/5 | 28 |
| 1857 | −$2,002 | 0.40 | −$5,355 | 0.025 | 2/5 | 36 |
| 11 | −$2,193 | 0.73 | −$3,415 | 0.068 | 0/5 | 20 |
| 858 | −$2,297 | 0.60 | −$6,469 | 0.053 | 2/5 | 36 |
| 236 | −$2,636 | 0.59 | −$3,635 | 0.041 | 1/5 | 28 |
| 580 | −$3,061 | 0.51 | −$4,505 | 0.056 | 0/5 | 20 |
| 610 | −$3,250 | 0.32 | −$5,481 | 0.025 | 1/5 | 28 |
| **0** | **−$3,349** | **0.71** | **+$2,419** | **0.073** | 1/5 | **8** |
| 34 | −$3,398 | 0.13 | −$2,159 | 0.024 | 0/5 | 20 |
| 26 | −$3,492 | 0.34 | −$7,190 | 0.040 | 1/5 | 28 |
| 782 | −$3,904 | 0.55 | −$7,019 | 0.050 | 0/5 | 20 |

**“Most profitable” OOS = Sol 1163 (−$992)** — only **15 OOS trades** (too sparse).  
**Selected / only IS+ = Sol #0 (−$3,349 OOS, +$2,419 IS)** — **60 OOS trades** (primary attribution).

---

## Convergence (checkpoint logbook)

| Gen | Pareto | Pop avg Sortino (norm) | Best actual IS PnL* | Best actual PF* |
|-----|--------|------------------------|---------------------|-----------------|
| 0 | 400 | −888 | −$106k | 0.40 |
| 5 | 446 | −600 | −$98k | 0.48 |
| 10 | 590 | −6.0 | −$60k | 0.62 |
| 20 | 1,056 | −6.0 | −$56k | 0.63 |
| 50 | 1,665 | −6.0 | −$50k | 0.69 |
| 100 | 2,164 | −6.0 | −$38k | 0.73 |
| 150 | 2,503 | −6.0 | −$38k | 0.74 |
| 199 | 2,759 | −6.0 | −$38k | 0.74 |

\*Logbook `actual_*_best` tracks the generation’s displayed “best” individual under multi-objective ranking — not final Sol #0 contiguous aggregates.

**Phases:** gen 0–10 escape extreme penalties; gen 10+ population stuck near Sortino floor (~−6); Pareto bloat 400→2759 without finding OOS edge. Final Sol #0 IS +$2.4k is a sparse overfit that never appears as the logbook “best actual PnL” (those stay deeply negative).

---

## Solution #0 — contiguous IS vs OOS (replay-verified)

Replay used full-history + masks; **exact match** to CSV aggregates.

| Metric | IS | OOS |
|--------|----|-----|
| Total PnL | **+$2,419** | **−$3,349** |
| PF | 1.229 | 0.714 |
| Trades | 72 | 60 |
| Trades/day | 0.073 | 0.073 |
| Sortino | 1.83 | −3.72 |
| + splits | — | **1 / 5** |
| Robustness | — | **8.0** |

**Per-split OOS PnL:** P2 −$1,392 · P4 −$266 · P6 +$116 · P8 $0 · P10 −$1,806  

Classic **IS+/OOS−** on a sample too thin for confidence (~0.07/day vs MIN_TRADES_DAY 0.5).

### Sol #0 key params (v2 vs v1 Sol #0)

| Param | v2 Sol #0 | v1 Sol #0 |
|-------|-----------|-----------|
| Enable ADX Filter | **1 (locked)** | **0** |
| Timeframe | **15*** | 15 |
| Min VWAP Extension | 7.6 | 13.8 |
| Fade Band ATR Mult | 1.87 | 1.73 |
| Pullback Touch Buffer | 1.17 | 2.41 |
| Max Hold (bars) | 34 | 18 |
| Min Trend ADX | 15.2 | 27.8 |
| Max Range ADX | 19.6 | 23.5 |
| Trend Target R | 1.69 | 3.0 |

\*CSV template for this run has Timeframe Value/Min/Max = **5**, but **every Solution_* column exports 15** and replay at TF=15 reproduces metrics. Treat the run as **15-minute bars**, not the intended 5m lock — investigate export/lock wiring before any future vwap_regime experiment.

---

## Four-quadrant attribution

### Sol #0 (selected / only IS+ / 60 OOS trades) — primary

| Quadrant | Net PnL | Win% | PF |
|----------|---------|------|-----|
| **SS** | **−$3,349** | 46.7% | 0.71 |
| **SR** | +$405 MC med | 40.0% | 1.12 |
| **RS** | −$648 MC med | 50.0% | 1.57 |
| **RR** | −$163 MC med | 47%+ | — |

| Effect | Value | Read |
|--------|-------|------|
| **Exit (SS − SR)** | **−$3,754** | Strategy exits **destroy** value vs time-only hold |
| **Entry (SS − RS)** | **−$2,701** | Entries still anti-predictive |
| Beats opposite | 50.0% | Coin-flip |
| Opposite net | +$1,549 | Tautological for losers |
| Horizon edge 30–120m | negative | Short-horizon anti-edge |
| Horizon edge 240m | +1.04 pts | Not actionable (exits don’t capture) |

**vs v1 Sol #0:** v1 had exits *helping* (SS−SR +$5.8k) with worse entries (−$10.8k). v2 flips that: **exits now hurt more than they help**, and entries remain negative. Regime lock did not create selection edge.

### Sol 1163 (best OOS PnL / 15 trades) — sparse

| Effect | Value |
|--------|-------|
| SS | −$992 |
| SS − SR | −$395 |
| SS − RS | −$636 |
| Beats opposite | 53.3% |

Same qualitative failure; **n=15 is not deployable evidence**.

---

## Comparison to prior strategy GAs (Sol #0 contiguous OOS)

| Strategy | Run | OOS PnL | OOS PF | OOS trades | OOS+ HOF | SS−RS |
|----------|-----|---------|--------|------------|----------|-------|
| Trend | Jul-03 | −$36.8k | 0.88 | 639 | 0/1333 | stale* |
| Session v1 | Jul-04 | −$10.2k | 0.61 | 135 | 0/1196 | −$8.5k |
| Session v2 | Jul-05 | −$18.5k | 0.35 | 225 | 0/2164 | −$13.6k |
| ORB | Jul-06 | −$2.9k | 0.68 | 34 | 58/820 | −$3.3k |
| VWAP Regime v1 | Jul-08 | −$12.7k | 0.73 | 220 | 1/2212 | −$10.8k |
| **VWAP Regime v2** | **Jul-10** | **−$3.3k** | **0.71** | **60** | **0/2759** | **−$2.7k** |

v2 is “less bad” on Sol #0 dollar loss only because it **barely trades**. It is **worse** on the research goal (~1–2 trades/day with regime gate): zero OOS+ HOF, exits now harmful, activity collapsed.

---

## What v2 changed vs intent

| Intent (2026-07-10 params) | Observed in run |
|----------------------------|-----------------|
| ADX filter locked ON | **Achieved** (all sols = 1) |
| Timeframe locked 5 | **Not reflected** — all sols export/replay as **15** |
| MIN_TRADES_DAY = 0.5 | Present in CSV; Sol #0 still at **0.073**/day (penalty death in fitness[0]=−1000) |
| Extension / fade / hold tightened | Ranges respected on Sol #0 |
| Target ~2 trades/day | **Failed** — Sol #0 0.07; median HOF ~1.2 but all lose |

---

## Gate check (deploy bar)

| Gate | Sol #0 | Sol 1163 |
|------|--------|----------|
| Contiguous OOS PnL > 0 | FAIL | FAIL |
| OOS PF > 1.0 | FAIL (0.71) | FAIL (0.41) |
| SS − RS > −$2k | FAIL (−$2.7k) | FAIL (−$0.6k, n=15) |
| Entry beats opposite > 50% | FAIL (50%) | Weak (53%) |
| Adequate OOS N | Weak (60) | FAIL (15) |

---

## Recommended next steps

1. **Close the `vwap_regime` family** for this research track. v1 and v2 both fail gates; v2’s ADX lock did not produce OOS+ genomes. Do not spend another 200-gen retune on the same hypothesis.

2. **Implement ORB v2 (literature baseline)** next — 5/15m OR, 1-bar close, 0.5× OR target, opposite-OR stop (`docs/strategy_research.md` §9). Controlled experiment vs failed ORB v1.

3. **Implement MIM (Market Intraday Momentum)** in parallel or immediately after — Gao et al. / Baltussen; OHLC-only; ~1 trade/day (`strategy_research.md` §10). Orthogonal to VWAP/ORB.

4. **Fix Timeframe lock/export** before any future locked-param GA: every Jul-10 solution shows TF=15 while template Value/Min/Max=5. Confirm workers read locked Value=5 and export matches evaluation.

5. **Optional hygiene (low priority):** attribute ORB Sol 534 / v1 Sol 223 as previously queued; do **not** prioritize Bollinger revive (same fade family).

6. **Do not deploy** Sol #0 or Sol 1163 to paper/live.

---

## Artifact index (this run)

| File | Role |
|------|------|
| `Vwap_regime/parameters/genetic_results_2026-07-10-1.csv` | Full HOF export |
| `Vwap_regime/diagnostics/ga_checkpoint_2026-07-10-1.pkl` | Checkpoint (gen 199) |
| `Vwap_regime/output/genetic_trades_oos_2026-07-10-1_sol0.csv` | Sol #0 OOS trades (replay) |
| `Vwap_regime/output/genetic_trades_oos_2026-07-10-1_sol1163.csv` | Best-OOS-PnL trades |
| `results/attribution_vwap_regime_oos_2026-07-10_sol0.md` | 4-quadrant Sol #0 |
| `results/attribution_vwap_regime_oos_2026-07-10_sol1163.md` | 4-quadrant Sol 1163 |
| `results/_hof_vwap_2026-07-10.csv` | Parsed HOF metrics |

---

*Analysis date: 2026-07-11*

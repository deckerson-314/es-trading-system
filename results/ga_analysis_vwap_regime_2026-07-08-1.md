# VWAP Regime GA Full Analysis — 2026-07-08-1

**Run:** 200/200 generations · HOF **2,212**
**Artifacts:** `Vwap_regime/parameters/genetic_results_2026-07-08-1.csv`, IS/OOS trade exports, `ga_dashboard_v4.html`, `ga_checkpoint_2026-07-08-1.pkl`
**Attribution:** `results/attribution_vwap_regime_oos_2026-07-08.md`

---

## Executive summary

| Metric | Value |
|--------|-------|
| HOF solutions | 2,212 |
| OOS-profitable HOF (slice aggregate) | **1 / 2,212** (0.05%) |
| IS-profitable HOF | 0 / 2,212 (0.00%) |
| Solution #0 OOS PnL (slice / contiguous) | **$-12,732** |
| Solution #0 OOS PF | **0.729** |
| Solution #0 IS PnL | $-4,720 |
| Contiguous OOS | **$-12,732** · 220 trades · PF 0.729 |
| Contiguous IS | $-17,451 · 500 trades |
| Best HOF OOS PnL | $806 (Solution_223) |
| Best HOF OOS PF | 1.064 (Solution_223) |
| Best robustness | 50.8 (Solution_223) |
| SS − RS (entry effect) | **−$10,796** |
| **Gate verdict (Sol #0)** | **FAIL** |

GA completed without a deployable Solution #0. Contiguous IS (−$17.5k) and OOS (−$12.7k) are both negative. Only **1/2212** HOF genomes are OOS-positive on interleaved aggregates (0.05%). Trade frequency stayed ~**0.27/day** vs TARGET **2.0**. Attribution: **entries anti-predictive** (SS−RS −$10.8k); exits help slightly (SS−SR +$5.8k).

**Do not deploy Solution #0.**

---

## Hall of Fame distribution (interleaved aggregates)

- OOS profit: best **$806**, median **$-156,476**, worst **$-241,728**
- IS profit: best **$-731**, median **$-200,159**
- OOS PF: best **1.064**, median **0.350**
- OOS trades/day: median **2.075** (target 2.0)
- Positive OOS splits (Sol #0): **1 / 5**
- Robustness: Sol #0 **28.0**, best **50.8**, median **20.0**

### Top 10 by OOS aggregate PnL

| Sol | OOS PnL | OOS PF | IS PnL | OOS t/d | +OOS splits | Robust |
|-----|---------|--------|--------|---------|-------------|--------|
| 223 | $806 | 1.064 | $-9,602 | 0.093 | 3 | 50.8 |
| 325 | $-145 | 0.910 | $-3,290 | 0.024 | 1 | 28.0 |
| 46 | $-1,110 | 0.729 | $-3,691 | 0.046 | 1 | 28.0 |
| 374 | $-1,866 | 0.720 | $-7,596 | 0.059 | 1 | 28.0 |
| 2176 | $-1,997 | 0.497 | $-5,658 | 0.040 | 1 | 28.0 |
| 317 | $-2,164 | 0.513 | $-2,507 | 0.033 | 0 | 20.0 |
| 343 | $-2,243 | 0.378 | $-7,189 | 0.024 | 2 | 36.0 |
| 5 | $-2,717 | 0.504 | $-3,611 | 0.034 | 0 | 20.0 |
| 306 | $-2,829 | 0.709 | $-6,979 | 0.052 | 3 | 44.0 |
| 1 | $-2,932 | 0.458 | $-731 | 0.042 | 1 | 28.0 |

---

## Convergence (checkpoint logbook)

| Gen | Pareto | Pop avg Sortino (norm) | Best IS PnL | Best IS PF | Best t/d |
|-----|--------|------------------------|-------------|------------|----------|
| 0 | 400 | −922.6 | −$37,826 | 0.45 | 0.24 |
| 5 | 448 | −655.3 | −$26,908 | 0.61 | 0.23 |
| 10 | 504 | −368.1 | −$29,206 | 0.74 | 0.29 |
| 20 | 862 | −6.0 | −$26,077 | 0.63 | 0.23 |
| 40 | 1,240 | −6.0 | −$20,271 | 0.81 | 0.28 |
| 50 | 1,375 | −6.0 | −$19,690 | 0.81 | 0.27 |
| 75 | 1,548 | −6.0 | −$15,448 | 0.85 | 0.27 |
| 100 | 1,715 | −6.0 | −$15,448 | 0.85 | 0.27 |
| 150 | 2,065 | −6.0 | −$15,206 | 0.86 | 0.27 |
| 199 | 2,212 | −6.0 | −$17,451 | 0.83 | 0.28 |

**Phases:** gen 0–10 less-bad (PF 0.45→0.74) but still −$30k; gen 20+ population avg Sortino stuck near −6 (penalty floor); gen 40–150 slow grind −$26k → −$15k; final Sol #0 contiguous IS (−$17.5k) worse than mid-run best (−$15.2k) — rank rotation on multi-objective fitness.

---

## Solution #0 — contiguous IS vs OOS

| Metric | IS | OOS | Diff |
|--------|-----|-----|------|
| Sortino (Trade Proxy) | −1.853 | −3.495 | −1.642 |
| Max Drawdown | $24,676 | $17,828 | +$6,848 |
| Avg Trades/Day | 0.278 | 0.266 | −0.012 |
| Profit Factor | 0.833 | 0.729 | −0.104 |
| Avg Profit/Trade | −$34.90 | −$57.87 | −$22.97 |
| Avg Trade Duration (min) | 375.7 | 365.1 | −10.6 |
| Total Profit | **−$17,452** | **−$12,732** | +$4,720 |

Unlike Trend/ORB, **IS is also negative** — not classic positive-IS overfit; search never found a profitable Sol #0 pocket on either side.

### Solution #0 parameters

- **Timeframe (minutes):** 15.0
- **Opening Range (minutes):** 34.0
- **Max Entries Per Day:** 4.0
- **Enable ADX Filter:** 0.0
- **Min Trend ADX:** 27.8153
- **Max Range ADX:** 23.5241
- **Trend Side Pct:** 0.5736
- **Min VWAP Crosses:** 4.0
- **Pullback Touch Buffer (pts):** 2.412
- **Pullback Confirm Bars:** 1.0
- **Min VWAP Extension (pts):** 13.7962
- **Fade Band ATR Multiplier:** 1.728
- **Fade Confirm Bars:** 3.0
- **Stop ATR Multiplier:** 2.0
- **Trend Target R Multiple:** 3.0
- **Enable Trailing Stop:** 0.0
- **Trade Start After OR (min):** 32.0
- **Max Hold (bars):** 18.0
- **TP VWAP Buffer (pts):** 1.8486
- **Trade End Before RTH Close (min):** 67.0
- **Min OR Width (pts):** 5.5373
- **Max OR Width (pts):** 35.5234

**Notable:** `Enable ADX Filter = 0` — regime ADX gate **off**. `Timeframe = 11` (template 5). Tight pullback buffer (0.41) + 3 confirm bars. Wide fade extension (~16 pts). Cap 3 entries/day but realized ~0.27/day.

### Sol #0 per-split (interleaved)

**IS splits**

| Split | PnL | PF | Trades/day | Sortino |
|-------|-----|----|------------|---------|
| P1 | $3,961 | 1.44 | 0.28 | 6.60 |
| P3 | $-6,516 | 0.23 | 0.20 | -10.65 |
| P5 | $8,962 | 1.67 | 0.43 | 4.25 |
| P7 | $-4,416 | 0.34 | 0.21 | -10.53 |
| P9 | $-4,696 | 0.50 | 0.26 | -4.50 |
| P11 | $-1,898 | 0.82 | 0.33 | -2.04 |

**OOS splits**

| Split | PnL | PF | Trades/day | Sortino |
|-------|-----|----|------------|---------|
| P2 | $-5,010 | 0.58 | 0.27 | -4.73 |
| P4 | $-5,190 | 0.45 | 0.27 | -8.30 |
| P6 | $-4,050 | 0.71 | 0.35 | -5.61 |
| P8 | $-854 | 0.85 | 0.18 | -1.78 |
| P10 | $2,372 | 1.39 | 0.27 | 3.83 |

---

## Four-quadrant attribution (contiguous OOS, 220 trades)

| Quadrant | Net PnL | Win% | PF |
|----------|---------|------|-----|
| SS (strategy) | −$12,732 | 41.4% | 0.73 |
| SR (strat entry / random exit) | −$18,540 MC med | 41.4% | 0.69 |
| RS (random entry / hold-matched) | −$1,936 MC med | 49.1% | 1.20 |
| RR (full random) | +$278 MC med | 53.0% | — |

| Effect | Value | Verdict |
|--------|-------|---------|
| **SS − RS (entry)** | **−$10,796** | Entries anti-predictive |
| **SS − SR (exit)** | **+$5,808** | Exits help vs random hold |
| Opposite-direction net | +$6,132 | Beats opposite only 45% |
| Fixed-horizon edge | −1.4 to −2.5 pts | Wrong direction at all horizons |

Same cross-strategy pattern as Trend/Session/ORB: **entry selection fails**; exits are secondary. Opposite-direction diagnostic positive — direction/timing wrong.

---

## Contiguous trade deep dive (Sol #0)

### Mode attribution

| Mode | OOS n | OOS PnL | IS n | IS PnL |
|------|-------|---------|------|--------|
| trend | 171 | $-6,281 | 367 | $-5,104 |
| range | 49 | $-6,451 | 133 | $-12,347 |

Both modes lose OOS; range fade worse per trade (−$6.5k / 49 vs −$6.3k / 171 trend).

### Exit reasons (OOS)

| Reason | n | PnL |
|--------|---|-----|
| Gap: Session Break | 18 | $2,398 |
| RTH Exit | 96 | $10,061 |
| Stop Loss | 79 | $-36,856 |
| Take Profit | 26 | $11,730 |
| VWAP Exit | 1 | $-65 |

Stops dominate (−$36.9k). RTH exits and TPs net positive — survivors often work; stop/entry timing destroys edge.

### Direction (OOS)

| Dir | n | PnL |
|-----|---|-----|
| Short | 91 | $-7,542 |
| Long | 129 | $-5,190 |

---

## Parameter pressure (OOS+ vs OOS− HOF)

| Param | Sol #0 | Median all | Median OOS+ | Median OOS− |
|-------|--------|------------|-------------|-------------|
| Timeframe (minutes) | 15.0 | 3 | 6 | 3 |
| Opening Range (minutes) | 34.0 | 34.5 | 27 | 35 |
| Max Entries Per Day | 4.0 | 5 | 3 | 5 |
| Enable ADX Filter | 0.0 | 1 | 0 | 1 |
| Min Trend ADX | 27.8153 | 27.04 | 27.65 | 27.04 |
| Max Range ADX | 23.5241 | 27.74 | 27.69 | 27.74 |
| Trend Side Pct | 0.5736 | 0.5647 | 0.5501 | 0.5647 |
| Min VWAP Crosses | 4.0 | 2 | 1 | 2 |
| Pullback Touch Buffer (pts) | 2.412 | 2.615 | 1.072 | 2.615 |
| Pullback Confirm Bars | 1.0 | 1 | 1 | 1 |
| Min VWAP Extension (pts) | 13.7962 | 14.72 | 17.69 | 14.72 |
| Fade Band ATR Multiplier | 1.728 | 1.564 | 2.146 | 1.563 |
| Fade Confirm Bars | 3.0 | 2 | 2 | 2 |
| Stop ATR Multiplier | 2.0 | 1.227 | 1.701 | 1.227 |
| Trend Target R Multiple | 3.0 | 1.65 | 2.297 | 1.649 |
| Enable Trailing Stop | 0.0 | 0 | 1 | 0 |
| Trade Start After OR (min) | 32.0 | 18 | 33 | 18 |
| Max Hold (bars) | 18.0 | 38 | 34 | 38 |
| TP VWAP Buffer (pts) | 1.8486 | 1.194 | 1.965 | 1.193 |
| Trade End Before RTH Close (min) | 67.0 | 67 | 74 | 67 |
| Min OR Width (pts) | 5.5373 | 2.219 | 11.7 | 2.219 |
| Max OR Width (pts) | 35.5234 | 49.07 | 25.35 | 49.07 |

---

## Pass/fail gates (Sol #0 contiguous OOS)

| Gate | Threshold | Result |
|------|-----------|--------|
| OOS PnL > 0 | > $0 | **FAIL** ($-12,732) |
| OOS PF > 1 | > 1.0 | **FAIL** (0.729) |
| SS − RS MC med > −$2k | > −$2,000 | **FAIL** (−$10,796) |
| Trade count | ~100+ | **OK** (220) |
| Trades/day near target | ~1–4 | **FAIL** (0.13 vs 2.0) |

---

## Comparison to prior strategies

| Strategy | Sol #0 OOS | OOS PF | OOS trades | OOS+ HOF | t/d | SS−RS |
|----------|------------|--------|------------|----------|-----|-------|
| Trend Jul-03 | −$36,757 | 0.88 | 639 | 0/1333 | 0.37 | −$36k |
| Session v1 Jul-04 | −$10,151 | 0.61 | 135 | 0/1196 | 0.08 | −$8.5k |
| Session v2 Jul-05 | −$18,453 | 0.35 | 225 | 0/2164 | 0.13 | −$13.6k |
| ORB Jul-06 | −$2,861 | 0.68 | 34 | 58/820 | 0.02 | −$3.3k |
| **VWAP Regime Jul-08** | **−$12,732** | **0.73** | **220** | **1/2212** | **0.13** | **−$10.8k** |

Regime switch did not unlock literature VWAP edge. Better sample size than ORB; same entry-failure signature as Session. Non-zero OOS+ HOF fraction is small and not validated on contiguous export for those genomes.

---

## Why it failed

1. **ADX regime gate off on Sol #0** — core hypothesis disabled by GA.
2. **Frequency never reached target** (~0.27 vs 2.0/day).
3. **Stop losses dominate** (−$37k OOS); TPs/RTH cannot compensate.
4. **Both trend and range modes lose** — not a single-mode bug.
5. **IS also negative** — least-bad multi-objective selection, not a profitable IS niche.
6. **Entry selection anti-predictive** (attribution SS−RS −$10.8k); opposite-dir +$6.1k.

---

## Recommended next steps

| Priority | Action |
|----------|--------|
| P0 | Export + attribute best OOS HOF **Solution_223** (+$806 slices) |
| P1 | Lock `Enable ADX Filter = 1` (non-optimizable); re-run shorter GA |
| P1 | Loosen entry geometry to hit ~1–2 trades/day (extension, confirms, TF) |
| P2 | ORB v2 literature baseline (5–15m OR, 50% target) |
| P2 | Regenerate final dashboard (split tables fix landed after this run) |

---

*Generated 2026-07-10 from checkpoint + genetic_results + contiguous trades + attribution.*
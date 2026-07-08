# ORB GA Full Analysis — 2026-07-06-1

**Run:** 200/200 generations · ~1d 12h · 820 Pareto solutions
**Artifacts:** `genetic_results_2026-07-06-1.csv`, trade exports, dashboard `ga_dashboard_v4.html`

---

## Executive summary

| Metric | Value |
|--------|-------|
| HOF solutions | 820 |
| OOS-profitable HOF | **58 / 820** |
| IS-profitable HOF | 820 / 820 |
| Solution #0 OOS PnL | **$-2,861** |
| Solution #0 OOS PF | **0.678** |
| Solution #0 IS PnL | $10,842 |
| Best HOF OOS PnL | $3,525 (Solution_534) |
| Best HOF OOS PF | 1.325 |
| **Gate verdict (Sol #0)** | **FAIL** |

GA converged to strong **IS** (+$7,981 / PF 1.41) but **Solution #0 fails OOS** (−$2,861 / PF 0.68). **58/820** HOF genomes are OOS-positive on interleaved slices; best is **Solution_534** (+$3,525 OOS). Contiguous export: 93 IS / 34 OOS trades. **Do not deploy Solution #0.**

---

## Hall of Fame distribution

- OOS profit: best **$3,525**, median **$-5,736**, worst **$-14,710**
- IS profit: best **$13,719**, median **$7,525**
- OOS PF: best **1.325**, median **0.668**
- Unique OOS profit levels (rounded $): **382**

---

## Convergence (checkpoint logbook)

| Gen | Pareto | Pop avg fitness | Best IS PnL | Best IS PF | Best IS Sortino |
|-----|--------|-----------------|-------------|------------|-----------------|
| 0 | 400 | -985.01 | $-8,304 | 0.718 | -2.602 |
| 5 | 6 | -962.50 | $3,205 | 1.132 | 1.908 |
| 10 | 20 | -419.97 | $110 | 1.006 | 0.088 |
| 20 | 73 | 0.13 | $6,719 | 1.309 | 4.462 |
| 50 | 531 | 0.20 | $4,790 | 1.268 | 5.042 |
| 100 | 403 | 0.26 | $8,254 | 1.425 | 7.258 |
| 150 | 566 | 0.24 | $7,928 | 1.407 | 6.818 |
| 199 | 820 | 0.24 | $7,981 | 1.409 | 6.863 |

Final HOF in checkpoint: **820** (dashboard reports 820 at export).

**Phases:** gen 0–1 random → gen 2 Pareto collapse → gen 5 first IS-profitable champion → gen 20+ population fitness flipped positive → gen 30–50 IS best ~$7.7k plateau → gen 200 consolidated archive.

---

## Solution #0 — interleaved slice view (dashboard)

- **In-Sample:** PnL $7,981, WR 43.0%, PF 1.41
- **OOS:** PnL $-2,861, WR 32.4%, PF 0.68

| Metric | IS | OOS | Diff |
|--------|-----|-----|------|
| Sortino (Trade Proxy) | 6.863044 | -5.534118 | -12.397162 (-180.6%) |
| Sortino (Daily Std) | 0.314407 | -0.113222 | -0.427629 (-136.0%) |
| Max Drawdown | 3272.403787 | 3541.855680 | -269.451893 (-8.2%) |
| Avg Trades/Day | 0.051695 | 0.041162 | -0.010533 (-20.4%) |
| Profit Factor | 1.409207 | 0.677928 | -0.731279 (-51.9%) |
| Avg Profit/Trade | $85.82 | $-84.14 | $-169.96 (-198.0%) |
| Avg Trade Duration (min, bar-span) | 266.90 | 318.00 | +51.10 (+19.1%) |
| Total Profit | $7,980.96 | $-2,860.81 | $-10,841.77 (-135.8%) |

---

### Solution #0 parameters
- **Opening Range (minutes):** 56
- **Acceptance Bars:** 2
- **Breakout Buffer (pts):** 0.0
- **Min OR Width (pts):** 13.823
- **Max OR Width (pts):** 27.1169
- **Min ADX Threshold:** 14.1911
- **Max ADX Threshold:** 35.5854
- **Enable VWAP Filter:** 0
- **Stop ATR Multiplier:** 1.8278
- **Use Opposite OR Stop:** 0
- **Target OR Width Multiple:** 2.3751
- **Max Entries Per Day:** 1
- **Max Hold (bars):** 41

---

### OOS export (genetic_trades_oos_2026-07-06-1.csv)
- Trades: 34
- PnL: $-2,861
- Win rate: 32.4%
- PF: 0.678
- Avg PnL/trade: $-84
- Top exits: {'Stop Loss': np.int64(18), 'RTH Exit': np.int64(10), 'Take Profit': np.int64(4), 'Gap: Session Break': np.int64(2)}
- dir -1: n=13 pnl=$-2,168 wr=23.1%
- dir 1: n=21 pnl=$-692 wr=38.1%
- Worst months: {'2025-03': np.float64(-1589.5000000000528), '2020-09': np.float64(-1230.999999999999), '2020-11': np.float64(-1087.4999999999955)}
- Best months: {'2024-12': np.float64(418.5000000000037), '2021-12': np.float64(935.0481065413624), '2025-04': np.float64(935.0481065413624)}

### IS export (genetic_trades_is_2026-07-06-1.csv)
- Trades: 93
- PnL: $7,981
- Win rate: 43.0%
- PF: 1.409
- Avg PnL/trade: $86
- Top exits: {'Stop Loss': np.int64(46), 'RTH Exit': np.int64(22), 'Take Profit': np.int64(20), 'Gap: Session Break': np.int64(5)}
- dir -1: n=44 pnl=$3,827 wr=40.9%
- dir 1: n=49 pnl=$4,154 wr=44.9%
- Worst months: {'2025-03': np.float64(-1589.5000000000528), '2020-09': np.float64(-1230.999999999999), '2020-11': np.float64(-1087.4999999999955)}
- Best months: {'2021-03': np.float64(1226.99999999998), '2022-05': np.float64(2359.999999999991), '2025-04': np.float64(2575.644319624098)}

---

## vs Session (reference)

| Run | OOS PnL (Sol #0) | OOS PF | OOS-profitable HOF |
|-----|------------------|--------|-------------------|
| Session v1 Jul-04 | −$10,151 | 0.61 | 0 / 1,196 |
| Session v2 Jul-05 | −$18,453 | 0.35 | 0 / 2,164 |
| **ORB Jul-06** | **$-2,861** | **0.678** | **58 / 820** |

---

## Pass/fail gates

| Gate | Threshold | Result |
|------|-----------|--------|
| OOS PnL > 0 | > $0 | FAIL ($-2,861) |
| OOS PF > 1 | > 1.0 | FAIL (0.678) |
| SS − RS MC med > −$2k | attribution | **FAIL** (−$3,303) |
| Entry beats opposite | attribution | **FAIL** (32.4%, opp +$1,841) |
| Contiguous OOS matches export | replay | export = −$2,861 (34 trades) |

---

## Attribution (four-quadrant, OOS export)

Source: `results/attribution_orb_oos_2026-07-06.md` · 34 trades · MC 200

| Quadrant | Net PnL | Win% | PF | Interpretation |
|----------|---------|------|-----|----------------|
| **SS** (strategy entry/exit) | **−$2,861** | 32.4% | 0.68 | Actual strategy |
| **SR** (entry, random exit) | −$3,735 MC med | 47.1% | 0.29 | Exits slightly help (+$874 vs SS) |
| **RS** (random entry, matched hold) | **+$442** MC med | 41.2% | 0.43 | Entries hurt (−$3,303 vs SS) |
| **RR** (full random) | −$199 MC med | 45.5% | n/a | SS worse than random |

- **Entry selection (SS − RS): −$3,303** — ORB entries are anti-predictive vs random OOS timing (worse than Session v1’s −$8.5k in magnitude per trade but same sign).
- **Exit path (SS − SR): +$874** — stops/targets/RTH exits modestly better than random hold on same entries.
- **Opposite direction:** +$1,841 on same windows; strategy beats opposite only **32.4%** of the time.
- **Fixed horizon:** +3 pts at 30 min, then negative edge by 120–480 min — breakout direction fades over hold.

---

## Risks / caveats

1. **Severe IS/OOS gap** — IS +$7,981 vs OOS −$2,861 on Solution #0 (−136% retention on slice totals).
2. **Mid-run looked better** — gen ~40 dashboard showed +$212 OOS; final winner rotated to higher-IS genome that overfits.
3. **Very low trade count** — 34 OOS trades; one bad month (−$1,590) moves the needle.
4. **Short side OOS** — 13 shorts −$2,168 (23% WR); longs −$692 (38% WR).
5. **Best HOF (Sol #534)** — +$3,525 OOS on slices but still needs contiguous replay + attribution before selection.
6. **58 OOS-positive HOF** — 7% of archive; may be slice noise — not deployable without per-solution validation.

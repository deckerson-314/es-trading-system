# sr_zones GA Analysis — 2026-07-26 `sr-zones-v2-buffers-be` (gen 75)

**Run status:** overnight resume **COMPLETE** · `--gen 75` / run-tag `sr-zones-v2-buffers-be` · seed **20260725** · pop **150** · workers 6  
**Progress:** gens 25→74 evaluated (NUM_GEN=75); final HOF export + dashboard written ~2026-07-26 06:51–06:59  
**HOF size:** **315** solutions (CSV columns Solution_0…Solution_314)  
**Artifacts:**

- `Sr_zones/parameters/genetic_results_2026-07-25-sr-zones-v2-buffers-be.csv` (rewritten at gen75 finish)
- checkpoint `Sr_zones/diagnostics/ga_checkpoint_2026-07-25-sr-zones-v2-buffers-be.pkl` (archived)
- resume logs `Sr_zones/diagnostics/ga_sr_zones_v2_buffers_be_resume75_*.log`
- dashboard `web/ga_dashboard_v4_sr-zones-v2-buffers-be.html`
- HOF summary CSV `results/sr_zones_v2_buffers_be_hof_summary.csv`

**Comparators:** gen24 wrap `results/ga_analysis_sr_zones_2026-07-25-sr-zones-v2-buffers-be.md` · oppdist05 Sol2 · prior deploy Sol45

> Note: solution indices reshuffled after resume export — gen24 “Sol45” is **not** Sol45 in this CSV. Exact gene fingerprint (headroom 1.26 / zoneW 0.4622 / strength 4.5663) **not retained** in the gen75 HOF; closest loose match is a poor OOS− individual — treat gen24 Sol45 export as a historical fingerprint only.

---

## 1. Run status

| Field | Value |
|-------|-------|
| Seed | 20260725 |
| POP_SIZE | 150 |
| NUM_GEN | **75** (resume from 25) |
| Checkpoint generation field | 74 (0-indexed last completed) |
| HOF size | **315** |
| GA process | **not running** (Run Complete) |

---

## 2. Climate

| Metric | gen24 (first 25) | **gen75 (this)** | Delta |
|--------|------------------|------------------|-------|
| HOF size | 120 | **315** | +195 |
| OOS+ count / rate | 47 / 120 (**39.2%**) | **78 / 315 (24.8%)** | +31 / -14.4 pp |
| Best OOS PnL | +$14.1k | **+$12,620** | — |
| Median OOS PnL | — | **−$7,405** | — |
| 5/5-split sols | **0** | **3** | +3 |
| 4/5-split sols | 14 | **12** (exact) / ≥4/5=15 | — |
| 3/5-split sols | 45 | **41** (exact) / ≥3/5=56 | — |
| Sol0 OOS / splits / rob | +$9.7k / 4/5 / 49.7 | **+$9,473 / 4/5 / 48.8** | — |
| BE ON in HOF | 0/120 | **1/315** (OOS+: 0/78) | — |

### OOS PnL histogram

| Bucket | n |
|--------|---|
| <−20k | 84 |
| −20k…−10k | 54 |
| −10k…−5k | 36 |
| −5k…0 | 63 |
| 0…5k | 50 |
| 5k…10k | 27 |
| 10k…20k | 1 |
| >20k | 0 |

**Overnight verdict:** OOS+ rate 24.8% vs gen24 39.2% (↓); 5/5 count 3 vs 0; 4/5 12 vs 14; HOF 315 vs 120. **Yes — produced 5/5.**

---

## 3. Top deploy candidates (~15, deploy lens)

Lens: **positive OOS splits → OOS PF → OOS Sortino → rob → OOS PnL** (not Sol0 order).

| Sol | Side | TF | MaintEntry | MaintBuf | Headroom | BE / trig | Diss | ZoneW | Str | IS $ / PF / Sort | OOS $ / PF / Sort | t/d OOS | Splits | Rob |
|-----|------|----|------------|----------|----------|-----------|------|-------|-----|------------------|-------------------|---------|--------|-----|
| **94** | L+S | 7 | 106 | 44 | 0.76 | OFF / 1.07 | 1.01 | 0.46 | 4.92 | +$53,552 / 1.44 / 7.81 | +$9,184 / 1.09 / 1.81 | 0.30 | 5/5 | 59.1 |
| **95** | L+S | 7 | 106 | 44 | 0.76 | OFF / 0.86 | 1.01 | 0.46 | 4.92 | +$53,552 / 1.44 / 7.81 | +$9,184 / 1.09 / 1.81 | 0.30 | 5/5 | 59.1 |
| **96** | L+S | 7 | 106 | 44 | 0.76 | OFF / 0.90 | 1.01 | 0.46 | 4.92 | +$53,552 / 1.44 / 7.81 | +$9,184 / 1.09 / 1.81 | 0.30 | 5/5 | 59.1 |
| **6** | L+S | 7 | 105 | 43 | 0.92 | OFF / 0.46 | 1.14 | 0.47 | 4.00 | +$97,894 / 1.78 / 12.77 | +$12,620 / 1.13 / 2.45 | 0.29 | 4/5 | 55.4 |
| **0** | L+S | 7 | 105 | 44 | 0.52 | OFF / 0.63 | 1.04 | 0.47 | 4.61 | +$97,161 / 1.80 / 13.20 | +$9,473 / 1.09 / 1.76 | 0.30 | 4/5 | 48.8 |
| **1** | L+S | 7 | 105 | 44 | 0.52 | OFF / 0.61 | 1.04 | 0.47 | 4.61 | +$97,161 / 1.80 / 13.20 | +$9,473 / 1.09 / 1.76 | 0.30 | 4/5 | 48.8 |
| **2** | L+S | 7 | 105 | 44 | 0.52 | OFF / 0.55 | 1.04 | 0.47 | 4.61 | +$97,161 / 1.80 / 13.20 | +$9,473 / 1.09 / 1.76 | 0.30 | 4/5 | 48.8 |
| **3** | L+S | 7 | 105 | 44 | 0.52 | OFF / 0.58 | 1.04 | 0.47 | 4.61 | +$97,161 / 1.80 / 13.20 | +$9,473 / 1.09 / 1.76 | 0.30 | 4/5 | 48.8 |
| **4** | L+S | 7 | 105 | 44 | 0.52 | OFF / 0.80 | 1.04 | 0.47 | 4.61 | +$97,161 / 1.80 / 13.20 | +$9,473 / 1.09 / 1.76 | 0.30 | 4/5 | 48.8 |
| **5** | L+S | 7 | 105 | 44 | 0.52 | OFF / 0.65 | 1.04 | 0.47 | 4.61 | +$97,161 / 1.80 / 13.20 | +$9,473 / 1.09 / 1.76 | 0.30 | 4/5 | 48.8 |
| **9** | L+S | 7 | 105 | 44 | 0.52 | OFF / 0.65 | 1.04 | 0.47 | 4.33 | +$97,442 / 1.75 / 12.47 | +$7,855 / 1.07 / 1.44 | 0.31 | 4/5 | 45.8 |
| **141** | L+S | 7 | 105 | 44 | 0.90 | OFF / 1.16 | 0.98 | 0.47 | 4.08 | +$57,677 / 1.39 / 6.34 | +$8,225 / 1.07 / 1.30 | 0.35 | 4/5 | 46.5 |
| **8** | L+S | 7 | 105 | 44 | 0.36 | OFF / 1.03 | 1.20 | 0.47 | 3.42 | +$97,608 / 1.78 / 12.47 | +$7,182 / 1.06 / 1.28 | 0.30 | 4/5 | 44.3 |
| **17** | L+S | 7 | 105 | 44 | 0.52 | OFF / 0.55 | 1.04 | 0.47 | 4.20 | +$97,340 / 1.72 / 11.79 | +$6,820 / 1.06 / 1.18 | 0.31 | 4/5 | 43.4 |
| **111** | L+S | 7 | 106 | 44 | 0.31 | OFF / 0.94 | 1.17 | 0.42 | 2.29 | +$78,668 / 1.44 / 7.38 | +$4,314 / 1.03 / 0.60 | 0.41 | 4/5 | 38.4 |

Compact:

| Sol | OOS $ | OOS PF | OOS Sort | Splits | Rob | Side | TF | Headroom | MaintEntry | MaintBuf | BE | Diss | ZoneW | Str | Notes |
|-----|-------|--------|----------|--------|-----|------|----|----------|------------|----------|----|------|-------|-----|-------|
| **94** | +$9,184 | 1.09 | 1.81 | **5/5** | 59.1 | L+S | 7 | 0.76 | 106 | 44 | OFF | 1.01 | 0.46 | 4.92 | **5/5** |
| **95** | +$9,184 | 1.09 | 1.81 | **5/5** | 59.1 | L+S | 7 | 0.76 | 106 | 44 | OFF | 1.01 | 0.46 | 4.92 | **5/5** |
| **96** | +$9,184 | 1.09 | 1.81 | **5/5** | 59.1 | L+S | 7 | 0.76 | 106 | 44 | OFF | 1.01 | 0.46 | 4.92 | **5/5** |
| **6** | +$12,620 | 1.13 | 2.45 | **4/5** | 55.4 | L+S | 7 | 0.92 | 105 | 43 | OFF | 1.14 | 0.47 | 4.00 |  |
| **0** | +$9,473 | 1.09 | 1.76 | **4/5** | 48.8 | L+S | 7 | 0.52 | 105 | 44 | OFF | 1.04 | 0.47 | 4.61 | fitness Sol0 |
| **1** | +$9,473 | 1.09 | 1.76 | **4/5** | 48.8 | L+S | 7 | 0.52 | 105 | 44 | OFF | 1.04 | 0.47 | 4.61 |  |
| **2** | +$9,473 | 1.09 | 1.76 | **4/5** | 48.8 | L+S | 7 | 0.52 | 105 | 44 | OFF | 1.04 | 0.47 | 4.61 |  |
| **3** | +$9,473 | 1.09 | 1.76 | **4/5** | 48.8 | L+S | 7 | 0.52 | 105 | 44 | OFF | 1.04 | 0.47 | 4.61 |  |
| **4** | +$9,473 | 1.09 | 1.76 | **4/5** | 48.8 | L+S | 7 | 0.52 | 105 | 44 | OFF | 1.04 | 0.47 | 4.61 |  |
| **5** | +$9,473 | 1.09 | 1.76 | **4/5** | 48.8 | L+S | 7 | 0.52 | 105 | 44 | OFF | 1.04 | 0.47 | 4.61 |  |
| **9** | +$7,855 | 1.07 | 1.44 | **4/5** | 45.8 | L+S | 7 | 0.52 | 105 | 44 | OFF | 1.04 | 0.47 | 4.33 |  |
| **141** | +$8,225 | 1.07 | 1.30 | **4/5** | 46.5 | L+S | 7 | 0.90 | 105 | 44 | OFF | 0.98 | 0.47 | 4.08 |  |
| **8** | +$7,182 | 1.06 | 1.28 | **4/5** | 44.3 | L+S | 7 | 0.36 | 105 | 44 | OFF | 1.20 | 0.47 | 3.42 |  |
| **17** | +$6,820 | 1.06 | 1.18 | **4/5** | 43.4 | L+S | 7 | 0.52 | 105 | 44 | OFF | 1.04 | 0.47 | 4.20 |  |
| **111** | +$4,314 | 1.03 | 0.60 | **4/5** | 38.4 | L+S | 7 | 0.31 | 106 | 44 | OFF | 1.17 | 0.42 | 2.29 |  |

**Recommended deploy pick:** **Sol94** — 5/5, OOS +$9,184, PF 1.09, Sortino 1.81, rob 59.1, sides L+S, TF=7, maintEntry=106, maintBuf=44, headroom=0.76, BE=OFF.

---

## 4. Gene distributions (full HOF vs OOS+)

| Gene | Universe | n | mean | median | mode (share) | takeaway |
|------|----------|---|------|--------|--------------|----------|
| Maintenance Entry Buffer (minutes) | All HOF | 315 | 105 | **105** | 105 (42%) | mode 105 (42%) |
| Maintenance Entry Buffer (minutes) | OOS+ | 78 | 105 | **105** | 105 (67%) | mode 105 (67%) |
| Maintenance Entry Buffer (minutes) | OOS+ & ≥4/5 | 15 | 105 | **105** | 105 (73%) | mode 105 (73%) |
| Maintenance Buffer Minutes | All HOF | 315 | 44 | **44** | 44 (87%) | **collapsed** → 44 |
| Maintenance Buffer Minutes | OOS+ | 78 | 43.8 | **44** | 44 (85%) | **collapsed** → 44 |
| Maintenance Buffer Minutes | OOS+ & ≥4/5 | 15 | 43.9 | **44** | 44 (93%) | **collapsed** → 44 |
| Entry Headroom (ATR) | All HOF | 315 | 0.687 | **0.594** | 0.5178 (2%) | spread 0.446–0.923 |
| Entry Headroom (ATR) | OOS+ | 78 | 0.558 | **0.502** | 0.5178 (9%) | spread 0.421–0.712 |
| Entry Headroom (ATR) | OOS+ & ≥4/5 | 15 | 0.595 | **0.518** | 0.5178 (47%) | mode 0.5178 (47%) |
| Enable Breakeven Stop | All HOF | 315 | 0.00317 | **0** | 0 (100%) | ON 0% |
| Enable Breakeven Stop | OOS+ | 78 | 0 | **0** | 0 (100%) | ON 0% |
| Enable Breakeven Stop | OOS+ & ≥4/5 | 15 | 0 | **0** | 0 (100%) | ON 0% |
| Breakeven Trigger (ATR) | All HOF | 315 | 0.878 | **0.907** | 0.25 (2%) | spread 0.678–1.03 |
| Breakeven Trigger (ATR) | OOS+ | 78 | 0.859 | **0.934** | 0.9732 (5%) | spread 0.627–1.01 |
| Breakeven Trigger (ATR) | OOS+ & ≥4/5 | 15 | 0.763 | **0.647** | 0.6469 (13%) | spread 0.599–0.918 |
| Enable Short Trades | All HOF | 315 | 1 | **1** | 1 (100%) | ON 100% |
| Enable Short Trades | OOS+ | 78 | 1 | **1** | 1 (100%) | ON 100% |
| Enable Short Trades | OOS+ & ≥4/5 | 15 | 1 | **1** | 1 (100%) | ON 100% |
| Timeframe (minutes) | All HOF | 315 | 7 | **7** | 7 (100%) | **collapsed** → 7 |
| Timeframe (minutes) | OOS+ | 78 | 7 | **7** | 7 (100%) | **collapsed** → 7 |
| Timeframe (minutes) | OOS+ & ≥4/5 | 15 | 7 | **7** | 7 (100%) | **collapsed** → 7 |

### Selection summary

| Gene | Selected? | Evidence |
|------|-----------|----------|
| Maintenance Entry Buffer | **Yes** | HOF median 105; OOS+ median 105 |
| Maintenance Buffer Minutes | **Yes** | HOF median 44; mode share 87% |
| Entry Headroom | **Moderate** | HOF median 0.594; OOS+ 0.502 |
| Enable Breakeven Stop | **No (rejected)** | 1/315 HOF ON; **0/78 OOS+ ON** |
| Breakeven Trigger | Free-float while mostly OFF | median 0.907 |
| Enable Short | See mode | ON share HOF 100% / OOS+ 100% |
| Timeframe | See mode | HOF median 7; mode 7 (100%) |

---

## 5. Compare to prior references

| Reference | OOS $ | OOS PF | Splits | Rob | Notes |
|-----------|-------|--------|--------|-----|-------|
| oppdist05 **Sol2** (5/5) | +$17,320 | 1.18 | 5/5 | 59.3 | L-only TF=14; still highest OOS $ among 5/5 refs |
| gen24 buffers-be **Sol45** (export) | +$14.1k | 1.13 | 4/5 | 61.1 | headroom 1.26, maintEntry 105, BE OFF — **not in gen75 HOF** |
| gen75 Sol6 (best OOS $) | +$12,620 | 1.13 | 4/5 | 55.4 | higher $ than Sol94 but one fewer split |
| gen75 Sol0 | +$9,473 | 1.09 | 4/5 | 48.8 | fitness rank 0 |
| gen75 **deploy pick Sol94** (≈95/96 twin) | +$9,184 | 1.09 | **5/5** | 59.1 | first buffers-be 5/5 cluster; rob ≈ Sol2 |

---

## 6. Did overnight improve climate / produce 5/5?

| Question | Answer |
|----------|--------|
| Finished? | **Yes** — gen75 complete, CSV 315 sols, no optimize process running |
| Climate vs gen24 | OOS+ rate 24.8% vs gen24 39.2% (↓); 5/5 count 3 vs 0; 4/5 12 vs 14; HOF 315 vs 120 |
| 5/5 produced? | **Yes — 3 solution(s)** |
| BE selected overnight? | Still mostly rejected (1/315 ON) |
| Buffer genes | Still selected (entry buffer + maint buffer minutes) |

---

## 7. Recommended deploy + exports

**Pick:** **Sol94** (deploy lens above).

Exports written:

- Primary: `C:/Trading/strategies/sr_zones/parameters/sr_zones_deploy_sol94_buffers-be_g75_2026-07-26.csv`
- Fitness Sol0: `C:/Trading/strategies/sr_zones/parameters/sr_zones_deploy_sol0_buffers-be_g75_2026-07-26.csv`
- Prior gen24 Sol45 (stale index; keep for gene fingerprint): `strategies/sr_zones/parameters/sr_zones_deploy_sol45_buffers-be_2026-07-25.csv`
- oppdist05 Sol2 reference: `strategies/sr_zones/parameters/sr_zones_deploy_sol2_oppdist05_2026-07-25.csv`
- Sortable HOF: `results/sr_zones_v2_buffers_be_hof_summary.csv`

---

## Executive verdict

| Question | Answer |
|----------|--------|
| Run | **Complete** gen75 · seed 20260725 · pop 150 · HOF **315** |
| OOS+ climate | **78/315 (24.8%)** |
| 5/5 | **3** |
| Deploy | **Sol94** |
| vs oppdist05 Sol2 | **Same 5/5 tier**, lower OOS $ / PF (Sol94 +$9.2k / 1.09 vs Sol2 +$17.3k / 1.18); rob nearly tied (59.1 vs 59.3) |
| Gene takeaway | Maint entry buffer **~105** + maint buffer **44** + TF **7** + shorts **ON** selected; **BE rejected**; headroom cooled (~0.5–0.8) |

**Bottom line:** Overnight **finished** and **produced 5/5** (Sol94/95/96). Absolute OOS+ rose (47→78) while rate fell on HOF inflation (39%→25%). Prefer **Sol94** as this-run deploy export; keep oppdist05 **Sol2** as higher-$ 5/5 reference until attribution.

---

## Next

- Attribute deploy Sol94 vs oppdist05 Sol2 (SS−RS / exit mix) before paper swap.
- If BE remains rare, lock OFF to free DOF on next GA.
- Optionally tighten Maintenance Entry Buffer / Maintenance Buffer Minutes around HOF modes.

# sr_zones GA Analysis — 2026-07-27 `sr-zones-v3-locked-buffers`

**Run status:** **COMPLETE** · `--fresh --run-tag sr-zones-v3-locked-buffers` · seed **20260726** · pop **150** · NUM_GEN **100** · workers 6  
**Progress:** gens 0→99 evaluated; final HOF export + dashboard written ~2026-07-27 07:19  
**HOF size:** **313** solutions (CSV columns Solution_0…Solution_312)  
**Artifacts:**

- `Sr_zones/parameters/genetic_results_2026-07-26-sr-zones-v3-locked-buffers.csv`
- checkpoint `Sr_zones/diagnostics/ga_checkpoint_2026-07-26-sr-zones-v3-locked-buffers.pkl` (archived)
- console `Sr_zones/diagnostics/ga_sr_zones_v3_locked_buffers_console.log`
- dashboard `web/ga_dashboard_v4_sr-zones-v3-locked-buffers.html`
- HOF summary CSV `results/sr_zones_v3_locked_buffers_hof_summary.csv`
- plan `results/ga_plan_sr_zones_v3_locked_buffers_2026-07-26.md`

**Comparators:** oppdist05 · headroom · buffers-be gen24 · buffers-be g75 (Sol94)

> GA optimize process is **not running**. Paper bot (`main.py --strategy sr_zones --mode PAPER`) left untouched.

---

## 1. Run config summary

| Field | Value |
|-------|-------|
| Seed | **20260726** |
| POP_SIZE | 150 |
| NUM_GEN | **100** (0-indexed last completed = 99) |
| HOF size | **313** |
| GA process | **not running** (Run Complete) |
| Locks | Maint Entry Buffer **105**; Maint Buffer Minutes **44**; Enable BE **0**; BE Trigger **0.5**; Opp Dist **0.5** |
| Headroom range | **0.25–1.25** (narrowed vs v2 0–2.5) |
| Free genes | TF, zoneW, strength, vol, dissipation, headroom, L/S, stop pad, max hold |

Locks **held in full HOF** (nunique=1 for all five locked genes).

---

## 2. Climate

| Metric | v3 locked (this) |
|--------|------------------|
| HOF size | **313** |
| OOS+ count / rate | **31 / 313 (9.9%)** |
| Best OOS PnL | **+$26,010** (Sol145) |
| Median OOS PnL | **−$22,857** |
| Mean OOS PnL | −$20,396 |
| 5/5-split sols | **0** |
| 4/5-split sols | **2** (Sol145, Sol170) |
| 3/5-split sols | **23** (exact) / ≥3/5 = 25 |
| Sol0 OOS / PF / Sort / splits / rob | **−$12,400 / 0.89 / −1.70 / 1/5 / 8.0** |
| BE ON in HOF | **0/313** (locked) |

### OOS PnL histogram

| Bucket | n |
|--------|---|
| <−20k | 176 |
| −20k…−10k | 70 |
| −10k…−5k | 19 |
| −5k…0 | 17 |
| 0…5k | 9 |
| 5k…10k | 1 |
| 10k…20k | 18 |
| >20k | 3 |

**Verdict:** Climate **weaker** than buffers-be g75 on OOS+ rate / split density / Sol0. Tail OOS $ **stronger** (best +$26k vs g75 +$12.6k) but concentrated in a thin 4/5 pocket.

---

## 3. Compare to priors

| Metric | oppdist05 | headroom | buffers-be g25 | buffers-be g75 | **v3 locked** |
|--------|-----------|----------|----------------|----------------|---------------|
| Seed | 20260725 | 20260725 | 20260725 | 20260725 | **20260726** |
| HOF | 93 | 79 | 120 | 315 | **313** |
| OOS+ rate | **53.8%** (50/93) | 5.1% (4/79) | 39.2% (47/120) | 24.8% (78/315) | **9.9% (31/313)** |
| 5/5 | **1** | 0 | 0 | **3** | **0** |
| 4/5 | 6–7 | 0 | **14** | 12 | **2** |
| 3/5 | 40 | 16 | 45 | 41 | 23 |
| Best OOS $ | +$20.7k | +$7.2k | +$14.1k | +$12.6k | **+$26.0k** |
| Sol0 OOS | +$6.1k | −$12.9k | +$9.7k | +$9.5k | **−$12.4k** |
| Deploy ref | Sol2 5/5 | Sol62 3/5 | Sol45 4/5 | **Sol94 5/5** | **Sol145 4/5** |
| Deploy OOS / PF / rob | +$17.3k / 1.18 / 59.3 | +$7.2k / 1.03 / 31 | +$14.1k / 1.13 / 61 | +$9.2k / 1.09 / 59.1 | **+$26.0k / 1.24 / 68.5** |
| TF climate | 14 L-only | 12 L+S | **7** L+S | **7** L+S | **14** L+S |

### Did locking improve denser 5/5 / better Sol0 vs g75?

| Question | Answer |
|----------|--------|
| Denser 5/5? | **No** — 0×5/5 vs g75’s 3×5/5 |
| Better Sol0? | **No** — Sol0 OOS− (−$12.4k) vs g75 Sol0 +$9.5k / 4/5 |
| Better OOS+ rate? | **No** — 9.9% vs 24.8% |
| Better peak OOS $? | **Yes** — Sol145 +$26.0k / PF 1.24 / rob 68.5 beats g75 Sol94 and oppdist05 Sol2 on $ / PF / rob, but at **4/5** not 5/5 |
| Locks held? | **Yes** — entry buf 105, maint 44, BE 0, BE trig 0.5 |

**Interpretation:** Locking buffers/BE removed DOF that g75 used to find a denser robust front (esp. TF=7 cluster). Search collapsed onto a **TF=14 · floor dissipation · high strength/zoneW** island that can print large OOS $ but does not pack 5/5 mass. Same-seed note: v3 seed **20260726** ≠ g75 **20260725** — climate Δ is landscape+seed, not pure A/B.

---

## 4. Top deploy candidates (~15)

Lens: **positive OOS splits → OOS PF → OOS Sortino → rob → OOS PnL** (not Sol0 order).

| Sol | Side | TF | Headroom | Diss | ZoneW | Str | Vol | StopPad | MaxHold | IS $ / PF / Sort | OOS $ / PF / Sort | t/d OOS | Splits | Rob |
|-----|------|----|----------|------|-------|-----|-----|---------|---------|------------------|-------------------|---------|--------|-----|
| **145** | L+S | 14 | 0.75 | 0.051 | 0.72 | 4.77 | 1.64 | 0.32 | 36 | +$70.6k / 1.50 / 4.93 | **+$26,010 / 1.24 / 3.03** | 0.29 | **4/5** | **68.5** |
| **170** | L+S | 14 | 0.69 | 0.050 | 0.71 | 5.02 | 1.53 | 0.32 | 29 | +$78.3k / 1.54 / 4.63 | +$21,342 / 1.18 / 2.67 | 0.32 | **4/5** | 64.9 |
| **200** | L+S | 14 | 0.71 | 0.050 | 0.71 | 4.99 | 1.47 | 0.09 | 23 | +$65.0k / 1.45 / 3.92 | +$20,815 / 1.18 / 2.67 | 0.33 | 3/5 | 59.0 |
| **110** | L+S | 14 | 0.74 | 0.050 | 0.71 | 4.97 | 1.58 | 0.06 | 41 | +$73.5k / 1.56 / 5.31 | +$17,648 / 1.16 / 2.40 | 0.31 | 3/5 | 52.3 |
| **80** | L+S | 14 | 0.74 | 0.050 | 0.71 | 4.88 | 1.58 | 0.38 | 41 | +$80.3k / 1.61 / 5.61 | +$17,176 / 1.15 / 2.06 | 0.31 | 3/5 | 47.8 |
| **48** | L+S | 14 | 0.70 | 0.050 | 0.71 | 4.97 | 1.58 | 0.00 | 41 | +$75.8k / 1.60 / 6.05 | +$15,788 / 1.15 / 2.18 | 0.31 | 3/5 | 48.6 |
| **114** | L+S | 14 | 0.74 | 0.050 | 0.71 | 4.83 | 1.58 | 0.05 | 41 | +$73.0k / 1.56 / 5.27 | +$16,040 / 1.15 / 2.18 | 0.31 | 3/5 | 49.7 |
| **77** | L+S | 14 | 0.68 | 0.050 | 0.71 | 4.68 | 1.58 | 0.00 | 34 | +$73.2k / 1.56 / 5.64 | +$15,310 / 1.14 / 2.12 | 0.31 | 3/5 | 48.5 |
| **78** | L+S | 14 | 0.68 | 0.050 | 0.71 | 4.68 | 1.58 | 0.00 | 33 | +$73.2k / 1.56 / 5.64 | +$15,310 / 1.14 / 2.12 | 0.31 | 3/5 | 48.5 |
| **79** | L+S | 14 | 0.68 | 0.050 | 0.71 | 4.68 | 1.58 | 0.00 | 33 | +$73.2k / 1.56 / 5.64 | +$15,310 / 1.14 / 2.12 | 0.31 | 3/5 | 48.5 |
| **54** | L+S | 14 | 0.65 | 0.050 | 0.71 | 4.95 | 1.62 | 0.00 | 41 | +$74.8k / 1.59 / 5.97 | +$14,598 / 1.14 / 2.01 | 0.31 | 3/5 | 46.8 |
| **191** | L+S | 14 | 0.75 | 0.050 | 0.71 | 4.99 | 1.47 | 0.31 | 23 | +$70.8k / 1.49 / 4.17 | +$16,368 / 1.14 / 1.81 | 0.33 | 3/5 | 47.2 |
| **71** | L+S | 14 | 0.78 | 0.050 | 0.71 | 4.68 | 1.58 | 0.00 | 33 | +$73.4k / 1.57 / 5.70 | +$13,863 / 1.13 / 1.95 | 0.30 | 3/5 | 46.4 |
| **43** | L+S | 14 | 0.74 | 0.050 | 0.71 | 4.83 | 1.58 | 0.00 | 41 | +$77.1k / 1.61 / 6.13 | +$13,900 / 1.13 / 1.91 | 0.31 | 3/5 | 45.5 |
| **81** | L+S | 14 | 0.74 | 0.050 | 0.71 | 4.89 | 1.49 | 0.00 | 41 | +$75.2k / 1.56 / 5.61 | +$14,234 / 1.12 / 1.86 | 0.33 | 3/5 | 45.5 |

All locks: maintEntry=**105**, maintBuf=**44**, BE=**OFF**. Fitness Sol0 is **not** deployable (OOS−).

**Recommended deploy pick:** **Sol145** — only top-tier 4/5 with best OOS PF/Sortino/rob and highest OOS $.

---

## 5. Gene distributions (full HOF + OOS+)

| Gene | Universe | n | mean | median | mode (share) | takeaway |
|------|----------|---|------|--------|--------------|----------|
| Entry Headroom (ATR) | All HOF | 313 | 0.409 | **0.274** | 0.25 (39%) | piled on floor; OOS+ cooler ~0.68 |
| Entry Headroom (ATR) | OOS+ | 31 | 0.573 | **0.684** | 0.25 (16%) | winners prefer ~0.65–0.78 |
| Entry Headroom (ATR) | OOS+ & ≥4/5 | 2 | 0.724 | **0.724** | — | Sol145=0.75 / Sol170=0.69 |
| Dissipation (per bar) | All HOF | 313 | 0.121 | **0.05** | 0.05 (81%) | **floor** |
| Dissipation (per bar) | OOS+ | 31 | 0.050 | **0.05** | 0.05 (97%) | **collapsed to floor** |
| Strength Threshold | All HOF | 313 | 3.82 | **4.15** | — | OOS+ pulls high (~4.8) |
| Strength Threshold | OOS+ | 31 | 4.82 | **4.88** | — | high-strength island |
| Timeframe (minutes) | All HOF | 313 | 13.4 | **14** | 12 (40%) | HOF mass 12–15; **no TF=7** |
| Timeframe (minutes) | OOS+ | 31 | 14.3 | **14** | 14 (71%) | **OOS+ = TF 14/15 only** |
| Enable Short Trades | All / OOS+ | 313/31 | 1 | 1 | 1 (100%) | shorts **always ON** |
| Zone Width ATR Mult | All HOF | 313 | 0.614 | **0.608** | — | OOS+ ~0.71 |
| Zone Width ATR Mult | OOS+ | 31 | 0.706 | **0.713** | 0.713 (42%) | wide zones |
| Volume Mult | OOS+ | 31 | 1.44 | **1.58** | — | elevated vs HOF median ~1.06 |
| Stop Pad ATR | OOS+ | 31 | 0.125 | **0.05** | 0 (48%) | mixed; 4/5 pair ~0.32 |
| Max Hold (bars) | OOS+ | 31 | 37.2 | **39** | 41 (42%) | mid-high hold |
| Maint Entry Buffer | All HOF | 313 | 105 | **105** | 105 (100%) | **LOCK HELD** |
| Maint Buffer Minutes | All HOF | 313 | 44 | **44** | 44 (100%) | **LOCK HELD** |
| Enable Breakeven Stop | All HOF | 313 | 0 | **0** | 0 (100%) | **LOCK HELD** |

### Selection summary

| Gene | Selected? | Evidence |
|------|-----------|----------|
| Maint entry 105 / maint 44 / BE OFF | Locked (held) | nunique=1 |
| Dissipation | **Floor (0.05)** | 97% of OOS+ |
| TF | **14** (OOS+) | 71% of OOS+; no 7-min survivors |
| Shorts | **ON** | 100% |
| ZoneW / strength / vol | High | OOS+ medians ~0.71 / 4.88 / 1.58 |
| Headroom | Moderate ~0.7 on winners | HOF piled at 0.25 floor (IS noise) |

---

## 6. Recommended deploy + exports

**Pick:** **Sol145** (deploy lens). Twin-tier alt: **Sol170** (also 4/5, slightly weaker $ / PF / rob).

Exports written:

- Primary: `strategies/sr_zones/parameters/sr_zones_deploy_sol145_v3-locked-buffers_2026-07-27.csv`
- Alt 4/5: `strategies/sr_zones/parameters/sr_zones_deploy_sol170_v3-locked-buffers_2026-07-27.csv`
- Sortable HOF: `results/sr_zones_v3_locked_buffers_hof_summary.csv`
- Prior refs kept: g75 Sol94 · oppdist05 Sol2

**Deploy gene fingerprint (Sol145):** L+S · TF=14 · zoneW=0.720 · strength=4.77 · vol=1.636 · diss=0.051 · headroom=0.753 · stopPad=0.315 · maxHold=36 · maintEntry=105 · maintBuf=44 · BE=OFF · oppDist=0.5

---

## 7. Executive verdict

| Question | Answer |
|----------|--------|
| Finished? | **Yes** — 100 gens complete, CSV 313 sols, dashboard final, optimize idle |
| Climate vs g75 | **Worse** OOS+ rate / 5/5 / Sol0; **better** peak OOS $ |
| Locking helped denser 5/5? | **No** |
| Deploy | **Sol145** (4/5, OOS +$26.0k, PF 1.24, rob 68.5) |
| vs g75 Sol94 | Higher $ / PF / rob; **weaker splits** (4/5 vs 5/5); different TF island (14 vs 7) |
| vs oppdist05 Sol2 | Higher $ / PF / rob; Sol2 still unique **5/5**; Sol2 was L-only TF=14 |
| Gene takeaway | Locks held; search abandoned TF=7; OOS+ = TF14 + diss floor + high strength/zoneW/vol; headroom winners ~0.7 |

**Bottom line:** v3 locked-buffers **finished** but **did not improve climate density** vs g75. Prefer **Sol145** as this-run high-tail export for attribution; keep **Sol94 (g75 5/5)** and **oppdist05 Sol2** as split-robustness references until four-quadrant attrib decides which island is real.

# sr_zones GA Analysis — 2026-07-25 `sr-zones-v2-buffers-be`

**Run:** `--strategy sr_zones --fresh --run-tag sr-zones-v2-buffers-be` · seed **20260725** · PID 25556 · 24/24 gens · **complete**  
**New genes vs prior:** `Maintenance Entry Buffer (minutes)`, unlocked `Maintenance Buffer Minutes`, `Enable Breakeven Stop` / `Breakeven Trigger` / `Breakeven Pad`; `Entry Headroom` still free; `Min Opposite Zone Dist (ATR)=0.5` locked.  
**Artifacts:**

- `Sr_zones/parameters/genetic_results_2026-07-25-sr-zones-v2-buffers-be.csv`
- checkpoint `Sr_zones/diagnostics/ga_checkpoint_2026-07-25-sr-zones-v2-buffers-be.pkl`
- dashboard `web/ga_dashboard_v4_sr-zones-v2-buffers-be.html`
**Comparators:** `sr-zones-v1-oppdist05` (50/93) · `sr-zones-v1-headroom` (4/79) · same seed 20260725  
**Prior wraps:** `results/ga_analysis_sr_zones_2026-07-25-sr-zones-v1-oppdist05.md` · `…-v1-headroom.md`

---

## Side-by-side (Sol #0 + HOF climate)

| Metric | `oppdist05` | `headroom` | `buffers-be` (this) |
|--------|-------------|------------|---------------------|
| Seed | 20260725 | 20260725 | 20260725 |
| New buffer / BE genes | no | no | **yes** |
| HOF size | 93 | 79 | **120** |
| Sol #0 IS PnL / PF / Sortino | +$68.2k / 1.62 / 7.29 | +$56.5k / 1.39 / 5.05 | **+$86.5k / 1.70 / 11.95** |
| Sol #0 OOS PnL / PF / Sortino | **+$6.1k / 1.07 / +0.88** | −$12.9k / 0.89 / −1.80 | **+$9.7k / 1.10 / +1.83** |
| Sol0 positive OOS splits | 3 / 5 | 1 / 5 | **4 / 5** |
| OOS+ count / rate | **50 / 93 (53.8%)** | 4 / 79 (5.1%) | **47 / 120 (39.2%)** |
| Best OOS PnL | **+$20.7k** | +$7.2k | +$14.1k |
| 5/5-split sols | **1** (Sol2) | 0 | **0** |
| 4/5-split sols | 7 | 0 | **14** |
| 3/5-split sols | 47 | 16 | 45 |
| Sol0 climate (sketch) | L-only · TF=14 · headroom n/a · diss≈0.06 | L+S · TF=12 · headroom≈1.93 · diss≈0.80 | **L+S · TF=7 · headroom≈1.05 · maintEntryBuf=105 · maintBufMin=44 · BE=OFF · diss≈1.06** |

---

## Deploy-oriented top candidates (not just Sol0)

Lens: prefer **positive OOS splits → rob → OOS PF → OOS $** (same spirit as oppdist05 Sol2 over Sol0).

| Sol | OOS $ | OOS PF | Splits | Rob | Side | TF | Headroom | MaintEntryBuf | BE | Notes |
|-----|-------|--------|--------|-----|------|----|----------|---------------|----|-------|
| **45** | **+$14.1k** | **1.13** | **4/5** | **61.1** | L+S | 7 | **1.26** | 105 | OFF | Best deploy-shaped this HOF |
| 4 | +$13.3k | 1.13 | 4/5 | 55.8 | L+S | 7 | 1.24 | 105 | OFF | Near-twin of Sol45 |
| 5 | +$13.3k | 1.13 | 4/5 | 55.8 | L+S | 7 | 1.06 | 105 | OFF | Twin of Sol4 (headroom differs) |
| 46 | +$10.9k | 1.10 | 4/5 | 54.7 | L+S | 7 | 0.53 | 104 | OFF | Lower headroom |
| 30/31 | +$10.5k | 1.10 | 4/5 | 53.8 | L+S | 7 | 0.63 | 105 | OFF | Near-duplicates |
| 0 | +$9.7k | 1.10 | 4/5 | 49.7 | L+S | 7 | 1.05 | 105 | OFF | Fitness Sol0 — solid but below Sol45 on rob/OOS $ |
| opp Sol2 | +$17.3k | 1.18 | **5/5** | 59.3 | L-only | 14 | 0.5* | n/a | n/a | Still strongest split record |

\*Sol2 headroom was deploy-default 0.5 (gene not in that CSV).

No 5/5 solutions in this HOF. Sol45 edges Sol0 on rob and OOS $ at the same 4/5 split tier; still slightly behind oppdist05 Sol2 on splits / best OOS / PF.

---

## Gene distributions (buffers / BE / headroom)

| Gene | Universe | n | mean | median | takeaway |
|------|----------|---|------|--------|----------|
| Maintenance Entry Buffer (min) | All HOF | 120 | 105.0 | **105** | **Hard-selected** (103–106 only) |
| | OOS+ | 47 | 104.8 | 105 | same |
| | OOS+ & ≥4/5 | 13 | 105.1 | 105 | same |
| Maintenance Buffer Minutes | All / OOS+ / ≥4/5 | * | **44** | **44** | **Fixed at 44** across entire HOF (was 22 locked in oppdist05) |
| Enable Breakeven Stop | All HOF | 120 | 0 | 0 | **Never ON** (0/120) |
| | OOS+ / ≥4/5 | * | 0 | 0 | **0% selection** |
| Breakeven Trigger (ATR) | All HOF | 120 | 0.82 | 0.88 | Free-floating (irrelevant while BE=OFF) |
| Entry Headroom (ATR) | All HOF | 120 | 0.81 | **0.88** | Moderate; 60.8% ≥0.75; only 0.8% off |
| | OOS+ | 47 | 0.83 | 0.88 | similar |
| | OOS+ & ≥4/5 | 13 | 0.86 | **0.96** | Best robust cluster ~0.5–1.3; Sol45 at 1.26 |

### Did breakeven / entry buffer get selected?

| Gene | Selected? | Evidence |
|------|-----------|----------|
| **Maintenance Entry Buffer** | **Yes — strongly** | Entire HOF collapsed to ~105 min (share>0 = 100%) |
| **Maintenance Buffer Minutes** | **Yes — to 44** | 100% of HOF at 44 (vs prior locked 22) |
| **Enable Breakeven Stop** | **No** | 0/120 HOF, 0/47 OOS+, 0/13 OOS+&≥4/5 |
| **Entry Headroom** | **Yes — moderate** | Median ~0.88 ATR (cooler than headroom-run’s ~1.8); deploy top likes ~1.0–1.3 |

---

## Executive verdict

| Question | Answer |
|----------|--------|
| Finished? | **Yes** — gen 24/24, CSV + FINAL dashboard written, PID 25556 exited (no remaining optimize.py for this tag) |
| Sol #0 | IS+ / **OOS+** (+$9.7k, PF 1.10, **4/5**, rob 49.7) — passes Sol0 deploy lens |
| OOS+ mass | **47 / 120 (39.2%)** — well above headroom (5.1%), below oppdist05 (53.8%) |
| Best deploy-shaped | **Sol45** (4/5, OOS+$14.1k, PF 1.13, rob **61.1**, headroom 1.26, BE=OFF) |
| vs oppdist05 / Sol2 | Climate **PASS** but not a clean upgrade: denser 4/5 mass (14 vs 7), better Sol0 splits (4/5 vs 3/5), yet **no 5/5**, lower OOS+ rate, best OOS below Sol2 |
| vs headroom | Clear **recovery** — buffers/BE genome space restored OOS+ climate after headroom collapse |
| Buffer / BE learning | **Entry buffer + wider maint buffer selected; breakeven rejected** |

**Bottom line:** `buffers-be` finishes as a healthy same-seed climate: Sol0 OOS+/4/5 and 47/120 OOS+. GA **wanted** ~105 min maintenance entry buffer and 44 min maint buffer, and **refused** breakeven. Prefer **Sol45** as this-run deploy export; keep oppdist05 **Sol2** as the split-champion reference until attribution compares them. Do not paper BE=ON on this evidence.

---

## Exports

- Primary (best deploy-shaped this run): `strategies/sr_zones/parameters/sr_zones_deploy_sol45_buffers-be_2026-07-25.csv`
- Fitness Sol0 (also 4/5): `strategies/sr_zones/parameters/sr_zones_deploy_sol0_buffers-be_2026-07-25.csv`
- Reference (still strong on 5/5): `strategies/sr_zones/parameters/sr_zones_deploy_sol2_oppdist05_2026-07-25.csv`

---

## Next

- Attribute Sol45 vs Sol2 (SS−RS / exit mix) before any paper swap.
- Treat BE as dead gene for next GA (lock OFF) unless a different exit package changes the opportunity set.
- Optionally lock Maintenance Entry Buffer near 105 and Maintenance Buffer Minutes at 44 to free DOF; keep headroom soft-bounded ~0.5–1.5 given moderate selection here.

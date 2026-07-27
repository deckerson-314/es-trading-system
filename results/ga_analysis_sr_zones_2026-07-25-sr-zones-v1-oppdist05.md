# sr_zones GA Analysis — 2026-07-25 `sr-zones-v1-oppdist05`

**Run:** `--strategy sr_zones --fresh --run-tag sr-zones-v1-oppdist05` · seed **20260725** · `Min Opposite Zone Dist (ATR)=0.5` · 25 gens  
**Baseline:** `sr-zones-v1` (2026-07-24, SEED=None) — **not** same-seed A/B; climate comparison only  
**Artifacts:**  
- `Sr_zones/parameters/genetic_results_2026-07-25-sr-zones-v1-oppdist05.csv`  
- dashboard `web/ga_dashboard_v4_sr-zones-v1-oppdist05.html`  
**Prior wrap:** `results/ga_analysis_sr_zones_2026-07-24-sr-zones-v1.md`  
**Plan:** `results/plan_sr_zones_2026-07-24.md`

---

## Side-by-side (Sol #0 + HOF)

| Metric | `sr-zones-v1` (baseline) | `sr-zones-v1-oppdist05` |
|--------|--------------------------|-------------------------|
| Seed | None | **20260725** |
| Min Opposite Zone Dist ATR | *(no gene row in CSV)* | **0.5** (locked) |
| HOF size | 80 | **93** |
| Sol #0 IS PnL / PF / Sortino | +$43.4k / 1.53 / 4.38 | **+$68.2k / 1.62 / 7.29** |
| Sol #0 OOS PnL / PF / Sortino | −$3.9k / 0.94 / −0.50 | **+$6.1k / 1.07 / 0.88** |
| Sol0 positive OOS splits | 1 / 5 | **3 / 5** |
| OOS+ count / rate | **2 / 80 (2.5%)** | **50 / 93 (53.8%)** |
| Best OOS PnL | +$1.2k | **+$20.7k** |
| Sol0 climate (sketch) | Long-only · TF=7 · zone≈0.79 · vol≈1.0 · diss≈0.80 | Long-only · TF=14 · zone≈0.71 · vol≈1.30 · diss≈0.06 · stop pad 0 |

---

## Executive verdict

| Question | Answer |
|----------|--------|
| Sol #0 | IS **+$68.2k** / PF 1.62 → OOS **+$6.1k** / PF 1.07 (Sortino **+0.88**) |
| OOS+ mass | **50 / 93** HOF · best OOS **+$20.7k** |
| Sol0 OOS splits + | **3 / 5** |
| vs baseline | Climate-only: much denser OOS+ and Sol0 OOS flips + (baseline was IS+/OOS−, 2/80) |
| Deploy / paper? | **PASS deploy lens** (OOS+ mass + Sol0 OOS+) — **not** same-seed proof; attribution / paper soak before live |

**Bottom line:** Locked opposite-zone distance (0.5 ATR) coincides with a sharply healthier HOF climate than baseline — Sol0 OOS+ and majority OOS+. Treat as promising climate, not a controlled A/B; do not paper live until export/attribution confirms edge.

---

## Next

- Optional: same-seed A/B (oppdist on/off) if you want causal credit for the gene lock.
- Export Sol0 (or top OOS+) trades + SS−RS before any paper.
- Keep candle Sol 74 as the only current paper candidate until then.

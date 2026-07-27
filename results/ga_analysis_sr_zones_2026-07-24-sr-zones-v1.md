# sr_zones GA Analysis — 2026-07-24 `sr-zones-v1`

**Run:** `--strategy sr_zones --fresh --run-tag sr-zones-v1` · Dissipation gene · 25 gens  
**Params:** `strategies/sr_zones/parameters/sr_zones_strategy_params.csv`  
**Artifacts:**  
- `Sr_zones/parameters/genetic_results_2026-07-24-sr-zones-v1.csv`  
- dashboard `web/ga_dashboard_v4_sr-zones-v1.html`  
**Plan:** `results/plan_sr_zones_2026-07-24.md`

---

## Executive verdict

| Question | Answer |
|----------|--------|
| Sol #0 | IS **+$43.4k** / PF 1.53 → OOS **−$3.9k** / PF 0.94 (Sortino −0.50) |
| OOS+ mass | **2 / 80** HOF · best OOS **+$1.2k** |
| Sol0 OOS splits + | **1 / 5** |
| Climate | Long-only · TF=7 · wide zones (~0.79 ATR) · vol mult ≈1.0 |
| Deploy / paper? | **No** — **FAIL** (thin OOS+) |

**Bottom line:** Classic IS+/OOS− overfit. Geometry searched, but OOS transfer is negligible. Do not paper; no further retune without a new opportunity class.

---

## Next

- Keep candle Sol 74 as the only live/paper candidate from this research track.
- Optional later: fidelity harness use of `sr_zones` zone/stop exits (toolchain stress) — separate from edge deploy.

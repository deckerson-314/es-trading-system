# sr_zones GA Analysis — 2026-07-25 `sr-zones-v1-headroom`

**Run:** `--strategy sr_zones --fresh --run-tag sr-zones-v1-headroom` · seed **20260725** · `Entry Headroom (ATR)` unlocked (0–2.5) · `Min Opposite Zone Dist (ATR)=0.5` locked · 25 gens · **complete**  
**Scope note:** This genome space does **not** include `Maintenance Entry Buffer` / breakeven genes (those landed after the run started). Learnings are **headroom-focused**.  
**Artifacts:**  
- `Sr_zones/parameters/genetic_results_2026-07-25-sr-zones-v1-headroom.csv`  
- checkpoint `Sr_zones/diagnostics/ga_checkpoint_2026-07-25-sr-zones-v1-headroom.pkl`  
- dashboard `web/ga_dashboard_v4_sr-zones-v1-headroom.html`  
**Comparators:** `sr-zones-v1-oppdist05` (same seed) · deploy pick **Sol2** from that run  
**Prior wraps:** `results/ga_analysis_sr_zones_2026-07-25-sr-zones-v1-oppdist05.md` · `results/sr_zones_sol2_improvement_brief_2026-07-25.md`

---

## Side-by-side (Sol #0 + HOF climate)

| Metric | `oppdist05` | `headroom` (this) | Sol2 (oppdist05 deploy) |
|--------|-------------|-------------------|-------------------------|
| Seed | 20260725 | 20260725 | — |
| Entry Headroom gene | *(not in CSV / deploy default 0.5)* | **unlocked 0–2.5** | 0.5 (deploy default) |
| HOF size | 93 | **79** | — |
| Sol #0 IS PnL / PF / Sortino | +$68.2k / 1.62 / 7.29 | +$56.5k / 1.39 / 5.05 | — |
| Sol #0 OOS PnL / PF / Sortino | **+$6.1k / 1.07 / +0.88** | **−$12.9k / 0.89 / −1.80** | — |
| Sol0 positive OOS splits | **3 / 5** | **1 / 5** | — |
| OOS+ count / rate | **50 / 93 (53.8%)** | **4 / 79 (5.1%)** | — |
| Best OOS PnL | +$20.7k | +$7.2k | +$17.3k |
| 5/5-split sols | **1** (Sol2) | **0** | 5/5 |
| 4/5-split sols | **7** | **0** | — |
| 3/5-split sols | 47 | 16 | — |
| Sol0 climate (sketch) | Long-only · TF=14 · headroom n/a · diss≈0.06 | Two-sided · TF=12 · **headroom≈1.93** · diss≈0.80 | Long-only · TF=14 · headroom=0.5 · diss=0.05 |

---

## Deploy-oriented top candidates (not just Sol0)

Lens: prefer **positive OOS splits → rob → OOS PF → OOS $** (same spirit as Sol2 over Sol0).

| Sol | OOS $ | OOS PF | Splits | Rob | Side | TF | Headroom | Notes |
|-----|------:|-------:|-------:|----:|------|---:|---------:|-------|
| **62** | **+$7.2k** | 1.03 | **3/5** | **31.2** | L+S | 12 | **1.78** | Best deploy-shaped in this HOF; thin PF |
| **24** | +$2.8k | 1.03 | **3/5** | 28.5 | L-only | 10 | **1.61** | Cleaner side match to Sol2; Strength=6 |
| 49 | +$6.5k | 1.04 | 2/5 | 23.4 | L+S | 12 | 2.28 | Higher raw OOS than Sol24 but worse splits |
| 64 | +$1.4k | 1.01 | 2/5 | 17.6 | L+S | 12 | 1.83 | Marginal |
| 0 | −$12.9k | 0.89 | 1/5 | 8.0 | L+S | 12 | 1.93 | Fitness Sol0 — **not** deployable |

No 4/5 or 5/5 solutions. Best here (Sol62) is clearly weaker than oppdist05 **Sol2** (OOS +$17.3k / PF 1.18 / **5/5** / rob 59.3).

---

## Entry Headroom distribution

| Universe | n | mean | median | share ≥0.75 | share ≥1.0 | share =0/off |
|----------|--:|-----:|-------:|------------:|-----------:|-------------:|
| All HOF | 79 | 1.68 | **1.78** | 83.5% | 82.3% | **0%** |
| OOS+ | 4 | 1.88 | 1.81 | 100% | 100% | 0% |
| OOS+ & ≥3/5 | 2 | 1.70 | 1.70 | 100% | 100% | 0% |

**Takeaway:** GA **did prefer higher headroom** vs Sol2’s deploy floor of 0.5 ATR — HOF mass sits ~1.5–2.5 ATR; floor in HOF ≈0.59; nobody kept headroom off. OOS+ candidates are all ≥1.6 ATR.

Caveat: within this HOF, headroom correlates **negatively** with OOS PnL / pos-splits / rob (≈ −0.25 to −0.32). So the gene was selected upward under IS multi-obj fitness, but **unlocking headroom alone did not improve OOS climate** vs oppdist05 (and may have interacted badly with two-sided / high-dissipation genomes). Treat “higher headroom preferred” as a genome preference, not as proof that 1.5–2.0 ATR is the right live setting over Sol2’s 0.5.

---

## Executive verdict

| Question | Answer |
|----------|--------|
| Finished? | **Yes** — gen 25/25, CSV + dashboard written, no `optimize.py` process |
| Sol #0 | IS+ / **OOS−** (−$12.9k, 1/5 splits) — fail deploy lens |
| OOS+ mass | **4 / 79 (5.1%)** — near baseline thinness, far below oppdist05 |
| Best deploy-shaped | **Sol62** (3/5, OOS+$7.2k, PF~1.03, headroom~1.78) — optional export only |
| vs oppdist05 / Sol2 | **Climate regression** on same seed; Sol2 remains the stronger export |
| Headroom learning | GA pushed headroom **up** (median ~1.8 ATR); does **not** justify replacing Sol2 yet |
| Maintenance / BE genes | **Not in this run** — next fresh GA should include them |

**Bottom line:** Headroom GA completed and shows a clear preference for **elevated** Entry Headroom (~1.6–2.3 on OOS+), but HOF OOS climate collapsed vs oppdist05. Keep **Sol2 oppdist05** as the reference deploy candidate; treat Sol62/Sol24 as diagnostic exports only. Next productive GA: fresh run with maintenance entry buffer + breakeven genes (and decide whether to lock or re-search headroom around 0.5–1.0 vs 1.5–2.0).

---

## Exports

- Primary (best deploy-shaped this run): `strategies/sr_zones/parameters/sr_zones_deploy_sol62_headroom_2026-07-25.csv`
- Long-only alt: `strategies/sr_zones/parameters/sr_zones_deploy_sol24_headroom_2026-07-25.csv`
- Reference (still preferred): `strategies/sr_zones/parameters/sr_zones_deploy_sol2_oppdist05_2026-07-25.csv`

---

## Next

- Do **not** paper Sol62 over Sol2 on this evidence.
- Fresh GA after gene landings (maint entry buffer + breakeven); optionally soft-bound headroom (e.g. 0.5–1.25) if high values keep starving OOS+.
- Optional: full-sample attrib on Sol62 vs Sol2 only if you want to see whether high headroom cuts fail-fast stuffed breakouts.

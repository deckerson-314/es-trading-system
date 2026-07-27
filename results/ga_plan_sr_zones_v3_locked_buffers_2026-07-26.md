# sr_zones GA plan — v3 locked buffers (2026-07-26)

**Run-tag:** `sr-zones-v3-locked-buffers`  
**Seed:** `20260726`  
**Pop / gens:** 150 / **100**  
**Status (2026-07-27):** **COMPLETE** — wrap `results/ga_analysis_sr_zones_2026-07-27-sr-zones-v3-locked-buffers.md`  
**Outcome:** Locks held; climate **weaker** than g75 (OOS+ 9.9%, **0×5/5**, Sol0 OOS−); peak OOS **Sol145** 4/5 +$26.0k / PF 1.24 / rob 68.5 (TF=14 island). Locking did **not** densify 5/5 vs g75 Sol94.  
**Evidence:** `results/ga_analysis_sr_zones_2026-07-26-sr-zones-v2-buffers-be_g75.md`

## Landscape changes vs buffers-be (v2)

| Gene | v2 (buffers-be) | v3 (this run) | Why |
|------|-----------------|---------------|-----|
| Maintenance Entry Buffer | 30–240 | **LOCKED 105** | HOF mode 105 (42%); OOS+ mode 67%; ≥4/5 73% |
| Maintenance Buffer Minutes | 5–60 | **LOCKED 44** | Collapsed: mode 44 (~87% HOF / 85% OOS+) |
| Enable Breakeven Stop | 0–1 | **LOCKED OFF (0)** | 1/315 HOF ON; **0/78 OOS+** |
| Breakeven Trigger (ATR) | 0.25–2.0 | **LOCKED 0.5** | Unused while BE off — free DOF |
| Entry Headroom (ATR) | 0–2.5 | **0.25–1.25** (default 0.75) | Headroom-only preferred ~1.8 and killed climate; g75 winners ~0.5–0.8 |
| Min Opposite Zone Dist | LOCKED 0.5 | **LOCKED 0.5** | Keep |
| Dissipation / zoneW / strength / vol / TF / L+S / stop pad / max hold | Optimizable | **Unchanged ranges** | Still free; TF/shorts may collapse again |
| Classic trailing | LOCKED off | **LOCKED off** | Do not re-enable |
| NUM_GEN | 25→75 (resume) | **100** | Fresh overnight |
| POP_SIZE | 150 | **150** | Keep |

## Strategy code

No change. `entry_blocked_force` already gates RTH end + daily/weekend maintenance starts via Maintenance Entry Buffer.

## Launch

```powershell
cd C:\Trading
$env:PYTHONUNBUFFERED='1'
.\venv\Scripts\python.exe -u optimize.py --strategy sr_zones --fresh --run-tag sr-zones-v3-locked-buffers --seed 20260726 --gen 100 --cores 6 2>&1 | Tee-Object -FilePath "Sr_zones\diagnostics\ga_sr_zones_v3_locked_buffers_console.log"
```

**Log:** `Sr_zones/diagnostics/ga_sr_zones_v3_locked_buffers_console.log`  
**Params:** `strategies/sr_zones/parameters/sr_zones_strategy_params.csv`

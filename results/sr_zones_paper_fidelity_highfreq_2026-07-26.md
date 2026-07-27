# sr_zones paper fidelity high-freq params (2026-07-26)

**Params:** `strategies/sr_zones/parameters/sr_zones_paper_fidelity_highfreq_2026-07-26.csv`  
**Base:** Sol94 deploy `sr_zones_deploy_sol94_buffers-be_g75_2026-07-26.csv`  
**Dashboard (recent soak window):** `web/backtest_dashboard_sr_zones_paper_fidelity_highfreq.html`

## Knob deltas vs Sol94

| Knob | Sol94 | High-freq soak |
|------|------:|---------------:|
| Strength Threshold | 4.919 | **1.0** |
| Entry Headroom (ATR) | 0.7602 | **0.0** |
| Maintenance Entry Buffer (minutes) | 106 | **30** |
| Volume Mult | 1.0 | 1.0 (already floor) |
| Timeframe (minutes) | 7 | **5** |
| Dissipation (per bar) | 1.0128 | **0.2** |

Unchanged: Zone Width, Stop Pad, Max Hold, Min Opp Dist=0.5, BE off, RTH/maint locks, `$15` costs, pessimistic stops / live-style entry slips.

## Why Dissipation was required

Activity-only floor (ST=1, HR=0, MB=30, TF=5, Vol=1, Dissipation unchanged) tops out ~1.0 calendar / ~1.6 entry t/d. Dissipation `1.0128 → 0.2` is the minimal structure change that reaches ~3–4 entry t/d for paper↔BT soak.

## Metrics

**t/d definition:** `entry_td` = trades / unique entry dates (closest to “trades per active RTH day”); `cal_td` = optimize’s trades / unique bar dates.

### Recent (2025-06-01 → 2025-10-10) — `backtest.py`

- n=302, **entry t/d=3.21**, WR=42.7%, PnL≈-$19.5k, MaxDD≈$29.1k
- Exit mix: Stop Loss 149 (49%), Opposite Zone 101 (33%), RTH 27 (9%), Maintenance 22 (7%), Time 3 (1%)
- Sides: short 166 / long 136

### Long (2024-01-02 → 2025-10-10) — `optimize.run_backtest`

- n=1523, **entry t/d=3.37**, cal t/d=2.75 (not exploding to 20+)
- WR=40%, exit mix ~54% stop / 32% opp zone / 13% session — balanced for soak
- PnL/DD are poor (expected for loosened filters); this CSV is for **fidelity soak**, not deploy alpha

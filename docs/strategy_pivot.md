# Strategy Pivot History

**Date:** 2026-07-08  
**Master doc:** [`docs/strategy_research.md`](strategy_research.md) — full learnings, attribution, literature comparison, next strategy spec.

**Status:** Trend, Session, and ORB v1 **failed** OOS validation. **Active target:** `vwap_regime` (regime-switching VWAP pullback + deviation fade, ~1–4 trades/day).

---

## Session VWAP → ORB (historical)

**Date:** 2026-07-06  
**Status:** Session deprecated; ORB v1 completed 2026-07-08 — **failed** Sol #0 OOS gates.

## Why we abandoned Session VWAP

Jul-04 (v1) and Jul-05 (v2) GA both failed OOS gates:

| Run | OOS PnL (Sol #0) | OOS PF | OOS-profitable HOF |
|-----|------------------|--------|-------------------|
| v1 Jul-04 | −$10,151 | 0.61 | 0 / 1,196 |
| v2 Jul-05 | −$18,453 | 0.35 | 0 / 2,164 |

Attribution (corrected RNG):

- **v1:** SS − RS MC med ~ −$8.5k — mild entry failure; exits also hurt.
- **v2:** SS − RS ~ −$13.6k — entry selection worse; opposite-direction diagnostic +$11.7k but not a deployable sign flip.

VWAP fade chases reversion in a market where session extensions often **continue** (momentum). Tighter v2 geometry increased trade count without fixing edge.

## New strategy: `orb`

**Class:** `OrbAcceptanceStrategy`  
**CLI / GA:** `--strategy orb`  
**Params:** `strategies/orb/parameters/orb_strategy_params.csv`

### Logic (v1 — 2026-07-06)

1. Build **opening range** (default 30 min RTH) — reuse `strategies/session/indicators.py`.
2. After OR completes, require **N consecutive closes** beyond OR high/low (+ buffer) — **acceptance**, not first-touch fade.
3. **Regime:** OR width band, **min ADX** (momentum day), optional **VWAP alignment** (long ≥ VWAP, short ≤ VWAP), ATR band.
4. **Exit:** stop at **opposite OR** (classic) or ATR; target = **k × OR width** measured move; RTH/maintenance/time flat.
5. **Cap:** max 1 entry per session day by default (sparse ORB).

### Commands

```powershell
# GA (fresh)
$env:STRATEGY = 'orb'
python optimize.py --strategy orb --fresh

# Attribution (after OOS export)
python tools/analysis/strategy_attribution.py `
  --trades Orb/output/genetic_trades_oos_YYYY-MM-DD-N.csv `
  --param-csv strategies/orb/parameters/orb_strategy_params.csv `
  --strategy orb
```

### ORB v1 result (2026-07-08)

| Metric | Sol #0 | Best HOF (Sol #534) |
|--------|--------|---------------------|
| OOS PnL | −$2,861 | +$3,525 (slices) |
| OOS PF | 0.68 | 1.33 |
| OOS trades (contiguous) | 34 | — |
| OOS+ HOF | 58 / 820 | |

Attribution: SS − RS −$3.3k · entries anti-predictive. See `results/ga_analysis_orb_2026-07-06-1.md`.

## Active strategy: `vwap_regime`

**Class:** `VwapRegimeStrategy`  
**CLI / GA:** `--strategy vwap_regime`  
**Params:** `strategies/vwap_regime/parameters/vwap_regime_strategy_params.csv`

### Logic (v1 — 2026-07-08)

1. **Regime classifier** after OR: trend day (ADX high + price holds one VWAP side) vs range day (ADX low + VWAP crosses).
2. **Trend mode:** VWAP pullback with session bias (long pullbacks above VWAP, short below).
3. **Range mode:** VWAP deviation fade with rejection (literature-aligned Session fix).
4. **Cap:** 2–5 entries/day (GA target ~2 trades/day).

### Commands

```powershell
# GA (fresh)
$env:STRATEGY = 'vwap_regime'
python optimize.py --strategy vwap_regime --fresh

# Attribution (after OOS export)
python tools/analysis/strategy_attribution.py `
  --trades Vwap_regime/output/genetic_trades_oos_YYYY-MM-DD-N.csv `
  --param-csv strategies/vwap_regime/parameters/vwap_regime_strategy_params.csv `
  --strategy vwap_regime
```

## Pass gates (before deploy)

- Contiguous OOS PnL > 0 (Solution #0 or selected candidate)
- SS − RS MC median > −$2k
- OOS PF > 1.0
- Attribution run on OOS export

## Deprecated strategies

| Strategy | Reason |
|----------|--------|
| **trend** | Donchian chase; SS − RS ~ −$28k Jul-03 |
| **session** | VWAP fade; 0/2164 OOS-profitable Jul-05 |
| **orb** | Long-OR acceptance; Sol #0 OOS −$2.9k Jul-06 |

## Preserved infrastructure

- GA engine, sim fidelity, paper/backtest parity, attribution, live IB execution — unchanged.
- Bollinger — separate product line.
- Session indicators (VWAP, OR) — shared by ORB.

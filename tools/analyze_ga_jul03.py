#!/usr/bin/env python3
"""Analyze Jul-02 vs Jul-03 GA runs (old vs refreshed params)."""
from __future__ import annotations

import csv
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    cols = [c for c in rows[0] if c.startswith("Solution_")]
    by = {r["Name"]: r for r in rows if r.get("Name")}
    return cols, by


def pm(s):
    if not s or not str(s).strip():
        return None
    t = "".join(c for c in str(s).strip() if c.isdigit() or c in ".-")
    return float(t) if t else None


def pf(s):
    if not s or not str(s).strip():
        return None
    try:
        return float("".join(c for c in str(s).strip() if c.isdigit() or c in ".-"))
    except ValueError:
        return None


def find_row(by, substr, prefer=None):
    keys = [k for k in by if substr in k]
    if prefer:
        for k in keys:
            if prefer in k:
                return k
    return keys[0] if keys else None


def uniq(vals, nd=2):
    return len({round(v, nd) for v in vals if v is not None})


def build_sols(cols, by):
    keys = {
        "is_pnl": find_row(by, "Total Profit", "IS aggregate"),
        "oos_pnl": find_row(by, "Total Profit", "OOS aggregate"),
        "is_sortino": find_row(by, "Aggregate IS Sortino"),
        "oos_pf": find_row(by, "Profit Factor", "OOS aggregate"),
        "oos_atd": find_row(by, "Avg Trades/Day", "OOS aggregate"),
        "oos_span": find_row(by, "Avg Trade Span", "OOS aggregate"),
        "rob": find_row(by, "Live-Ready Robustness Score"),
        "deg": find_row(by, "Sortino IS-to-OOS Degradation"),
        "pos": find_row(by, "Positive OOS Splits"),
    }
    params = [
        "Timeframe (minutes)", "Buy Lookback (minutes)", "Sell Lookback (minutes)",
        "Trailing Delay (bars)", "ATR Multiplier for Trailing Stop", "Take Profit ATR Multiplier",
        "RSI Max Buy Threshold", "RSI Min Sell Threshold", "Initial Stop Loss (%)",
        "Enable SMA Filter", "Enable RSI Filter", "Enable VWAP Filter", "Enable Volume Filter", "Enable ADX Filter",
        "Channel Exit Sell Lookback (bars)", "SMA Period", "Enable Trailing Stop",
    ]
    sols = []
    for i, c in enumerate(cols):
        s = {"idx": i}
        for sk, rk in keys.items():
            if not rk:
                s[sk] = None
            elif sk.endswith("_pnl"):
                s[sk] = pm(by[rk][c])
            else:
                s[sk] = pf(by[rk][c])
        for pk in params:
            s[pk] = pf(by.get(pk, {}).get(c))
        sols.append(s)
    return sols, params


def summarize(label, path):
    p = ROOT / path
    cols, by = load(p)
    n = len(cols)
    sols, params = build_sols(cols, by)
    print(f"\n{'='*78}\n{label}  (n={n})")
    for k in ["WEIGHT_TRADES", "WEIGHT_PF", "NORM_PNL_MAX", "GA_PESSIMISTIC_STOPS", "MIN_TRADE_DURATION"]:
        r = by.get(k, {})
        print(f"  {k} = {r.get('Value', '?')}")

    oos_pos = sum(1 for s in sols if s["oos_pnl"] and s["oos_pnl"] > 0)
    is_pos = sum(1 for s in sols if s["is_pnl"] and s["is_pnl"] > 0)
    print(f"  IS PnL>0: {is_pos}/{n}  |  OOS PnL>0: {oos_pos}/{n}")

    for m in ["is_pnl", "oos_pnl", "oos_span", "oos_atd", "oos_pf", "rob"]:
        vals = [s[m] for s in sols if s[m] is not None]
        if not vals:
            continue
        print(
            f"  {m:10} min={min(vals):>10,.1f}  med={statistics.median(vals):>10,.1f}  "
            f"max={max(vals):>10,.1f}  stdev={statistics.stdev(vals):>10,.1f}  uniq={uniq(vals)}"
        )

    near1 = sum(
        1 for s in sols
        if s["oos_span"] and s["Timeframe (minutes)"] and s["oos_span"] <= s["Timeframe (minutes)"] * 1.5
    )
    delay_le1 = sum(1 for s in sols if s["Trailing Delay (bars)"] is not None and s["Trailing Delay (bars)"] <= 1)
    trail_low = sum(
        1 for s in sols
        if s["ATR Multiplier for Trailing Stop"] is not None and s["ATR Multiplier for Trailing Stop"] < 1.5
    )
    rsi_oob = sum(
        1 for s in sols
        if s["RSI Max Buy Threshold"] and s["RSI Max Buy Threshold"] > 100
    )
    print(
        f"  Anti-artifact: near-1bar={near1}/{n}  delay<=1={delay_le1}/{n}  "
        f"trailATR<1.5={trail_low}/{n}  RSI>100={rsi_oob}/{n}"
    )

    ranked = sorted(sols, key=lambda s: s["oos_pnl"] or -1e18, reverse=True)
    print("  Top 5 by OOS PnL:")
    for s in ranked[:5]:
        print(
            f"    #{s['idx']:4}  OOS=${s['oos_pnl']:>9,.0f}  IS=${s['is_pnl']:>9,.0f}  "
            f"PF={s['oos_pf']:.2f}  span={s['oos_span']:.0f}m  TF={s['Timeframe (minutes)']:.0f}  "
            f"delay={s['Trailing Delay (bars)']:.0f}  trail={s['ATR Multiplier for Trailing Stop']:.2f}  "
            f"pos={s['pos']:.0f}/11"
        )

    print("  Parameter diversity (unique / n):")
    for pk in params:
        vals = [s[pk] for s in sols if s[pk] is not None]
        if vals:
            print(
                f"    {pk:42} uniq={uniq(vals):4}/{n}  "
                f"med={statistics.median(vals):7.2f}  [{min(vals):.2f}, {max(vals):.2f}]"
            )
    return sols


def deployable(sols, strict=True):
    out = []
    for s in sols:
        tf = s["Timeframe (minutes)"] or 14
        min_span = tf * 2
        if not s["oos_pnl"] or s["oos_pnl"] <= 0:
            continue
        if strict:
            if not s["oos_pf"] or s["oos_pf"] < 1.1:
                continue
            if s["oos_span"] and s["oos_span"] < min_span:
                continue
            if s["pos"] is not None and s["pos"] < 6:
                continue
        out.append(s)
    return out


if __name__ == "__main__":
    old = summarize("Jul-02 OLD ranges", "Trend/parameters/genetic_results_2026-07-02-1.csv")
    new = summarize("Jul-03 NEW refresh", "Trend/parameters/genetic_results_2026-07-03-1.csv")

    print(f"\n{'='*78}\nDEPLOYABLE SCREEN (Jul-03)")
    strict = deployable(new, strict=True)
    relaxed = deployable(new, strict=False)
    print(f"  Strict (OOS>0, PF>=1.1, span>=2*TF, pos>=6/11): {len(strict)}/{len(new)}")
    print(f"  Relaxed (OOS>0 only): {len(relaxed)}/{len(new)}")

    if relaxed:
        relaxed.sort(key=lambda s: s["oos_pnl"], reverse=True)
        print("\n  Best relaxed OOS candidates:")
        for s in relaxed[:8]:
            print(
                f"    #{s['idx']:4}  OOS=${s['oos_pnl']:>9,.0f}  PF={s['oos_pf']:.2f}  "
                f"span={s['oos_span']:.0f}m  pos={s['pos']:.0f}/11  "
                f"TF={s['Timeframe (minutes)']:.0f}  buyLB={s['Buy Lookback (minutes)']:.0f}  "
                f"sellLB={s['Sell Lookback (minutes)']:.0f}  "
                f"RSI={s['Enable RSI Filter']:.0f}({s['RSI Max Buy Threshold']:.0f}/{s['RSI Min Sell Threshold']:.0f})  "
                f"SMA={s['Enable SMA Filter']:.0f} VWAP={s['Enable VWAP Filter']:.0f} VOL={s['Enable Volume Filter']:.0f}"
            )

    # Bottom-quartile OOS winners (user workflow)
    ranked = sorted(new, key=lambda s: s["oos_pnl"] or -1e18, reverse=True)
    bq = ranked[int(0.75 * len(new)) :]
    bq_pos = [s for s in bq if s["oos_pnl"] and s["oos_pnl"] > 0]
    print(f"\n  Bottom-quartile OOS>0: {len(bq_pos)}/{len(bq)}")
    if bq_pos:
        best_bq = max(bq_pos, key=lambda x: x["oos_pnl"])
        print(f"  Best bottom-quartile: #{best_bq['idx']} OOS=${best_bq['oos_pnl']:,.0f}")

    # Recommend paper candidate
    print(f"\n{'='*78}\nPAPER TEST RECOMMENDATION")
    if strict:
        pick = max(strict, key=lambda x: x["oos_pnl"])
        mode = "strict-best"
    elif relaxed:
        # prefer among top OOS: highest positive splits, then OOS pnl
        pick = max(relaxed, key=lambda x: (x["pos"] or 0, x["oos_pnl"]))
        mode = "relaxed-best (pos-weighted)"
    else:
        # least bad OOS + check IS
        pick = max(new, key=lambda x: x["oos_pnl"] or -1e18)
        mode = "no OOS>0 — NOT RECOMMENDED; showing least-bad"
    print(f"  Mode: {mode}")
    print(f"  Solution index: {pick['idx']}")
    for k in [
        "Timeframe (minutes)", "Buy Lookback (minutes)", "Sell Lookback (minutes)",
        "Trailing Delay (bars)", "ATR Multiplier for Trailing Stop", "Take Profit ATR Multiplier",
        "RSI Max Buy Threshold", "RSI Min Sell Threshold", "Initial Stop Loss (%)",
        "Enable SMA Filter", "Enable RSI Filter", "Enable VWAP Filter", "Enable Volume Filter",
        "Channel Exit Sell Lookback (bars)", "SMA Period",
    ]:
        print(f"    {k}: {pick.get(k)}")
    print(
        f"  Stats: OOS=${pick['oos_pnl']:,.0f} IS=${pick['is_pnl']:,.0f} "
        f"PF={pick['oos_pf']:.2f} span={pick['oos_span']:.0f}m pos={pick['pos']}/11"
    )

    # Fitness vs OOS rank overlap
    by_sortino = sorted(new, key=lambda s: s["is_sortino"] or -1, reverse=True)
    by_oos = sorted(new, key=lambda s: s["oos_pnl"] or -1e18, reverse=True)
    top_fit = {s["idx"] for s in by_sortino[:50]}
    top_oos = {s["idx"] for s in by_oos[:50]}
    print(f"\n  Top-50 IS-Sortino vs top-50 OOS overlap: {len(top_fit & top_oos)}/50")
    print("  Fitness #0:", by_sortino[0]["idx"], "OOS", by_sortino[0]["oos_pnl"])
    print("  Best OOS:", by_oos[0]["idx"], "sortino", by_oos[0]["is_sortino"])

    pos_vals = [s["pos"] for s in new if s["pos"] is not None]
    if pos_vals:
        print(f"  Positive OOS splits: med={statistics.median(pos_vals):.0f} max={max(pos_vals):.0f}")
        for thr in [5, 8, 10]:
            print(f"    pos>={thr}: {sum(1 for p in pos_vals if p >= thr)}/{len(pos_vals)}")

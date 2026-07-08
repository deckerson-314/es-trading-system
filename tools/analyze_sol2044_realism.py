"""Profit realism analysis for Solution_2044 (deployment recommendation)."""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("STRATEGY", "trend")

from backtest import load_ga_params, run_backtest as bt_run
from optimize import run_backtest as opt_run
from strategies.trend.parameters import get_param_value, load_params

GA = ROOT / "Trend/parameters/genetic_results_2026-06-11-1.csv"
DATA = ROOT / "Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv"
DEP = ROOT / "strategies/trend/parameters/trend_strategy_params.csv"
START, END = "2020-01-02", "2025-10-10"


def ga_stat(df, name, col):
    r = df.loc[df["Name"] == name]
    return r.iloc[0][col] if not r.empty and col in r.columns else None


def money(x):
    return float(str(x).replace("$", "").replace(",", ""))


def bar_span(entry, exit, tf):
    st = pd.to_datetime(entry)
    et = pd.to_datetime(exit)
    M = max(float(tf), 1)
    eb = st.floor(f"{int(M)}min")
    xb = et.floor(f"{int(M)}min")
    return max(1.0, (xb - eb).total_seconds() / 60 / M + 1)


def prep_opt_params(params_dict):
    skip = {"POP_SIZE", "NUM_GEN", "MIN_TRADES", "LIMIT_", "DATA_", "NORM_", "WEIGHT_"}
    p = {}
    for k, meta in params_dict.items():
        if not isinstance(meta, dict) or "value" not in meta:
            continue
        if str(k).startswith("GA_") or "WEIGHT" in str(k):
            continue
        if any(str(k).startswith(s) for s in skip):
            continue
        v = meta["value"]
        t = meta.get("type", "")
        if t == "int":
            v = int(float(v))
        elif t == "float":
            v = float(v)
        elif t == "bool" and isinstance(v, str):
            v = v.strip().lower() in ("true", "1", "yes")
        p[k] = v
    return p


def load_ohlcv():
    df = pd.read_csv(DATA, parse_dates=True, index_col=0)
    df.columns = [str(c).lower().strip() for c in df.columns]
    if len(df.columns) == 5 and not all(c in df.columns for c in ["open", "high", "low", "close", "volume"]):
        df = pd.read_csv(DATA, header=None, parse_dates=True, index_col=0)
        df.columns = ["open", "high", "low", "close", "volume"]
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    df = df.loc[START:END]
    return df


def trade_economics(tr, tf, label, pnl_col="pnl_currency"):
    if tr is None or tr.empty:
        print(f"  {label}: no trades")
        return None
    t = tr.copy()
    pnl = t[pnl_col]
    t["bar_span"] = [bar_span(a, b, tf) for a, b in zip(t["entry_time"], t["exit_time"])]
    wins = t[pnl > 0]
    losses = t[pnl < 0]
    stop = t["reason"].astype(str).str.contains("Stop", case=False, na=False)
    bh = t["bars_held"] if "bars_held" in t.columns else None
    et = pd.to_datetime(t["entry_time"])
    days = et.dt.date.nunique()
    total = pnl.sum()
    out = {
        "n": len(t),
        "pnl": total,
        "win_pct": 100 * (pnl > 0).mean(),
        "median": pnl.median(),
        "stop_pct": 100 * stop.mean(),
        "pct_span_le2": 100 * (t["bar_span"] <= 2).mean(),
        "tpd": len(t) / max(days, 1),
        "days": days,
        "annual": total / max(days, 1) * 252,
        "avg_trade": total / len(t),
    }
    if bh is not None:
        out["pct_bh_le2"] = 100 * (bh <= 2).mean()
    print(f"\n  {label}")
    print(f"    trades={out['n']}  days={out['days']}  tpd={out['tpd']:.2f}")
    print(f"    total=${out['pnl']:,.0f}  annualized=${out['annual']:,.0f}  avg/trade=${out['avg_trade']:,.0f}")
    print(f"    win%={out['win_pct']:.1f}%  median=${out['median']:,.0f}")
    print(f"    stop exits={out['stop_pct']:.1f}%  bar_span<=2={out['pct_span_le2']:.1f}%")
    if bh is not None:
        print(f"    bars_held<=2={out['pct_bh_le2']:.1f}%  top bh={bh.astype(int).value_counts().sort_index().head(4).to_dict()}")
    reasons = t["reason"].value_counts().head(5)
    print(f"    exit reasons: {reasons.to_dict()}")
    big = t[pnl > 500]
    top10 = t.nlargest(10, pnl_col)[pnl_col].sum()
    print(f"    pnl>500: {len(big)} trades ({100*len(big)/len(t):.1f}%) sum=${big[pnl_col].sum():,.0f}")
    print(f"    top10=${top10:,.0f} ({100*top10/total:.1f}% of total)")
    return out


def main():
    df_ga = pd.read_csv(GA)
    col = "Solution_2044"

    print("=" * 72)
    print("Solution_2044 — GA dashboard aggregates (Jun 11 run)")
    print("=" * 72)
    stats = {}
    for s in [
        "Total Profit ($) (IS aggregate)",
        "Total Profit ($) (OOS aggregate)",
        "Sortino Ratio (IS aggregate)",
        "Profit Factor (IS aggregate)",
        "Profit Factor (OOS aggregate)",
        "Avg Profit/Trade ($) (IS aggregate)",
        "Avg Profit/Trade ($) (OOS aggregate)",
        "Avg Trades/Day (IS aggregate)",
        "Avg Trades/Day (OOS aggregate)",
        "Max Drawdown ($) (OOS aggregate)",
    ]:
        v = ga_stat(df_ga, s, col)
        stats[s] = v
        print(f"  {s}: {v}")

    is_v = money(stats["Total Profit ($) (IS aggregate)"])
    oos_v = money(stats["Total Profit ($) (OOS aggregate)"])
    print(f"  OOS/IS profit ratio: {oos_v/is_v:.2f}")

    print("\n  Key params:")
    for k in [
        "Timeframe (minutes)",
        "Trailing Delay (bars)",
        "Initial Stop Loss (%)",
        "ATR Multiplier for Trailing Stop",
        "Take Profit ATR Multiplier",
        "GA_LIVE_STYLE_ENTRY",
        "GA_CONSERVATIVE_STOP_SLIPPAGE",
    ]:
        print(f"    {k}: {ga_stat(df_ga, k, col)}")

    params, _ = load_ga_params(str(GA), 2044)
    tf = int(get_param_value(params, "Timeframe (minutes)", 15))
    ohlcv = load_ohlcv()

    print("\n" + "=" * 72)
    print("Engine A: backtest.py (next-bar OPEN entry — no GA_LIVE_STYLE)")
    print("=" * 72)
    res_bt = bt_run("trend", str(DATA), params, suppress_log=True, start_date=START, end_date=END)
    full_bt = trade_economics(res_bt["trades_df"], tf, "Solution_2044")

    print("\n" + "=" * 72)
    print("Engine B: optimize.run_backtest (GA_LIVE_STYLE + stop slippage from params)")
    print("=" * 72)
    d = dict(params)
    d["strategy_name"] = "trend"
    p = prep_opt_params(d)
    res_opt = opt_run(p, ohlcv, d, suppress_output=True)
    tr_opt = res_opt.get("trades_df", pd.DataFrame())
    if not tr_opt.empty and "pnl" in tr_opt.columns:
        tr_opt = tr_opt.rename(columns={"pnl": "pnl_currency"})
    full_opt = trade_economics(tr_opt, tf, "Solution_2044 (GA-fidelity sim)", pnl_col="pnl_currency")

    print("\n" + "=" * 72)
    print("Engine B with LIVE_STYLE forced OFF (same genome)")
    print("=" * 72)
    d0 = dict(d)
    d0["GA_LIVE_STYLE_ENTRY"] = {"value": 0, "min": 0, "max": 1, "type": "int"}
    p0 = prep_opt_params(d0)
    res_off = opt_run(p0, ohlcv, d0, suppress_output=True)
    tr_off = res_off.get("trades_df", pd.DataFrame())
    if not tr_off.empty:
        tr_off = tr_off.rename(columns={"pnl": "pnl_currency"})
    full_off = trade_economics(tr_off, tf, "2044 LIVE=0 SLIP=1", pnl_col="pnl_currency")

    print("\n" + "=" * 72)
    print("Contrast: Solution_0 via optimize (GA-fidelity)")
    print("=" * 72)
    p_s0, _ = load_ga_params(str(GA), 0)
    tf0 = int(get_param_value(p_s0, "Timeframe (minutes)", 15))
    p_s0["strategy_name"] = "trend"
    r_s0 = opt_run(prep_opt_params(p_s0), ohlcv, p_s0, suppress_output=True)
    tr_s0 = r_s0.get("trades_df", pd.DataFrame())
    if not tr_s0.empty:
        tr_s0 = tr_s0.rename(columns={"pnl": "pnl_currency"})
    trade_economics(tr_s0, tf0, "Solution_0 GA-fidelity", pnl_col="pnl_currency")

    print("\n" + "=" * 72)
    print("Paper trading (deployed params, not necessarily 2044)")
    print("=" * 72)
    ct = json.loads((ROOT / "paper_logs/completed_trades.json").read_text())
    pdf = pd.DataFrame([t for t in ct if "Backfilled" not in str(t.get("reason", ""))])
    pdf["exit_time"] = pd.to_datetime(pdf["exit_time"], format="ISO8601", utc=True).dt.tz_convert(None)
    pdf["entry_time"] = pd.to_datetime(pdf["entry_time"], format="ISO8601", utc=True).dt.tz_convert(None)
    for start, label in [("2026-05-01", "Since May 2026"), ("2026-01-01", "YTD 2026")]:
        sub = pdf[pdf["exit_time"] >= start]
        if sub.empty:
            continue
        days = sub.entry_time.dt.date.nunique()
        ann = sub.pnl.sum() / max(days, 1) * 252
        print(f"  {label}: n={len(sub)} pnl={sub.pnl.sum():,.0f} annualized~={ann:,.0f} avg={sub.pnl.mean():,.1f} win%={100*(sub.pnl>0).mean():.1f}")

    for f in ["jun11_2026_compare.csv", "jun12_2026_compare.csv"]:
        p = ROOT / "results" / f
        if p.exists():
            c = pd.read_csv(p)
            m = c[c["Status"] == "MATCHED"]
            print(f"  {f}: live={m['Live PnL'].sum():,.0f} bt={m['BT PnL'].sum():,.0f} gap={m['PnL Diff'].sum():,.0f}")

    print("\n" + "=" * 72)
    print("Deployed vs 2044 — material diffs")
    print("=" * 72)
    dep = load_params(str(DEP))
    diffs = []
    for k in params:
        if k not in dep:
            continue
        v2044 = get_param_value(params, k)
        vdep = get_param_value(dep, k)
        if v2044 != vdep:
            diffs.append((k, vdep, v2044))
    print(f"  {len(diffs)} differences. Notable:")
    for k, a, b in diffs:
        if k in {
            "Timeframe (minutes)",
            "Trailing Delay (bars)",
            "Initial Stop Loss (%)",
            "Buy Lookback (minutes)",
            "Sell Lookback (minutes)",
            "Take Profit ATR Multiplier",
        }:
            print(f"    {k}: deployed={a}  2044={b}")

    print("\n" + "=" * 72)
    print("REALISM VERDICT — Solution_2044")
    print("=" * 72)
    # GA OOS is summed across OOS folds — approximate annual using IS tpd and ~35% calendar as OOS
    oos_pf = float(stats["Profit Factor (OOS aggregate)"])
    oos_avg = money(stats["Avg Profit/Trade ($) (OOS aggregate)"])
    oos_tpd = float(stats["Avg Trades/Day (OOS aggregate)"])
    oos_annual_from_avg = oos_avg * oos_tpd * 252

    print(f"  GA OOS holdout: ${oos_v:,.0f} total, PF={oos_pf:.2f}, ~${oos_avg:.0f}/trade, {oos_tpd:.2f} tpd")
    print(f"  Implied OOS annual (avg/trade * tpd * 252): ~${oos_annual_from_avg:,.0f}/yr")
    print(f"  OOS retains {100*oos_v/is_v:.0f}% of IS profit — much healthier than Solution_0 (22%)")
    if full_bt and full_opt:
        print(f"  Full-window backtest.py (optimistic entry): ${full_bt['annual']:,.0f}/yr")
        print(f"  Full-window GA-fidelity sim:                ${full_opt['annual']:,.0f}/yr")
        if full_off:
            delta = full_off["annual"] - full_opt["annual"]
            print(f"  Entry-model gap (LIVE on vs off):           ${delta:+,.0f}/yr")
    print("  Paper is running DEPLOYED params (TF=13, delay=1), not 2044 (TF=20, delay=0)")
    print("  Jun 11-12 execution gap on 2-bar stops still applies to any trailing-stop genome")


if __name__ == "__main__":
    main()

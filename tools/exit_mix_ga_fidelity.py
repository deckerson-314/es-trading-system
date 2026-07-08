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

GA20 = ROOT / "Trend/parameters/genetic_results_2026-06-20-1.csv"
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


def exit_breakdown(tr, label, pnl_col="pnl_currency"):
    """Count and PnL share by exit reason."""
    if tr is None or tr.empty:
        print(f"\n  {label}: no trades")
        return
    t = tr.copy()
    if pnl_col not in t.columns and "pnl" in t.columns:
        pnl_col = "pnl"
    pnl = t[pnl_col]
    total_pnl = float(pnl.sum())
    n = len(t)
    print(f"\n  {label}  (n={n}, total PnL ${total_pnl:,.0f})")
    print(f"    {'Reason':<28} {'Count':>6} {'%Trades':>8} {'PnL':>14} {'%PnL':>8} {'Avg':>10}")
    print("    " + "-" * 78)
    grp = (
        t.groupby(t["reason"].astype(str))[pnl_col]
        .agg(["count", "sum", "mean"])
        .sort_values("sum", ascending=False)
    )
    for reason, row in grp.iterrows():
        cnt = int(row["count"])
        spnl = float(row["sum"])
        print(
            f"    {reason:<28} {cnt:6d} {100.0 * cnt / n:8.1f} "
            f"${spnl:13,.0f} {100.0 * spnl / total_pnl if total_pnl else 0:8.1f} "
            f"${row['mean']:9,.0f}"
        )


def run_opt(params, ohlcv, label, overrides=None):
    d = dict(params)
    d["strategy_name"] = "trend"
    if overrides:
        for k, v in overrides.items():
            d[k] = {"value": v, "type": "int" if isinstance(v, int) else "float"}
    p = prep_opt_params(d)
    res = opt_run(p, ohlcv, d, suppress_output=True)
    tr = res.get("trades_df", pd.DataFrame())
    if not tr.empty and "pnl" in tr.columns and "pnl_currency" not in tr.columns:
        tr = tr.rename(columns={"pnl": "pnl_currency"})
    return tr


def main():
    ohlcv = load_ohlcv()
    cases = [
        ("Solution_342 (Jun-20 best OOS)", GA20, 342),
        ("Solution_2044 (Jun-11 reference)", GA, 2044),
    ]

    for case_label, ga_path, idx in cases:
        params, _ = load_ga_params(str(ga_path), idx)
        tf = int(get_param_value(params, "Timeframe (minutes)", 15))
        tp = get_param_value(params, "Take Profit ATR Multiplier")
        trail = get_param_value(params, "ATR Multiplier for Trailing Stop")
        delay = get_param_value(params, "Trailing Delay (bars)")
        print("\n" + "=" * 78)
        print(f"{case_label}  |  TF={tf}m  TP={tp}  trail={trail}  delay={delay} bars")
        print("=" * 78)
        print(
            "  Sim flags from export:",
            "LIVE_STYLE=", get_param_value(params, "GA_LIVE_STYLE_ENTRY"),
            "SLIP=", get_param_value(params, "GA_CONSERVATIVE_STOP_SLIPPAGE"),
            "PESSIMISTIC=", get_param_value(params, "GA_PESSIMISTIC_STOPS"),
        )

        print("\n--- backtest.py (next-bar OPEN, slippage if in params) ---")
        res_bt = bt_run("trend", str(DATA), params, suppress_log=True, start_date=START, end_date=END)
        exit_breakdown(res_bt["trades_df"], "backtest.py")

        print("\n--- optimize.run_backtest (GA fidelity: live entry + slip + pessimistic from export) ---")
        tr_ga = run_opt(params, ohlcv, "GA fidelity")
        exit_breakdown(tr_ga, "optimize GA-fidelity")

        print("\n--- Ablation: pessimistic OFF (else unchanged) ---")
        tr_p0 = run_opt(params, ohlcv, "pess off", {"GA_PESSIMISTIC_STOPS": 0})
        exit_breakdown(tr_p0, "pessimistic OFF")

        print("\n--- Ablation: slippage 0 (else unchanged) ---")
        tr_s0 = run_opt(params, ohlcv, "slip 0", {"GA_CONSERVATIVE_STOP_SLIPPAGE": 0.0})
        exit_breakdown(tr_s0, "slippage 0")

        print("\n--- Ablation: live-style OFF (next-bar open, else unchanged) ---")
        tr_l0 = run_opt(params, ohlcv, "live off", {"GA_LIVE_STYLE_ENTRY": 0})
        exit_breakdown(tr_l0, "live-style OFF")


if __name__ == "__main__":
    main()

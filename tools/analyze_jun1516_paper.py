"""Analyze Jun 15-16 2026 paper vs backtest with execution-artifact lens."""
import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backtest import run_backtest
from compare_paper_backtest_trend import load_trend_params
from core.monitoring import pad_htf_for_session_force_exits
from strategies.factory import StrategyFactory

DATA = ROOT / "paper_logs/live_data.csv"
PARAMS = ROOT / "strategies/trend/parameters/trend_strategy_params.csv"
START = pd.Timestamp("2026-06-15 00:00:00")
END = pd.Timestamp("2026-06-16 23:59:59")


def bar_span(entry, exit, tf):
    st = pd.to_datetime(entry)
    et = pd.to_datetime(exit)
    M = max(float(tf), 1)
    eb = st.floor(f"{int(M)}min")
    xb = et.floor(f"{int(M)}min")
    return max(1.0, (xb - eb).total_seconds() / 60 / M + 1)


def load_paper():
    ct = json.loads((ROOT / "paper_logs/completed_trades.json").read_text())
    rows = []
    for t in ct:
        if "Backfilled" in str(t.get("reason", "")):
            continue
        et = pd.to_datetime(t["exit_time"], format="ISO8601", utc=True).tz_convert("America/New_York").tz_localize(None)
        if START <= et <= END:
            rows.append(t)
    return pd.DataFrame(rows)


def run_bt_window(params_dict):
    df = pd.read_csv(DATA, index_col=0, parse_dates=True)
    df.columns = [c.lower().strip() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    df = df.loc[START - pd.Timedelta(days=5) : END + pd.Timedelta(days=1)]
    strategy = StrategyFactory.get_strategy("trend", params_dict)
    tf = int(strategy.timeframe)
    from core.monitoring import prepare_strategy_ohlcv

    if tf > 1:
        df, _htf_native = prepare_strategy_ohlcv(df, tf, assume_htf_native=True)
    df = strategy.calculate_indicators(df)
    df = strategy.apply_filters(df)
    sig = strategy.calculate_entry_signals(df)
    long_s, short_s = sig[0], sig[1]
    df["entry_long_signal"] = long_s
    df["entry_short_signal"] = short_s
    dates = {START.date(), END.date(), pd.Timestamp("2026-06-15").date(), pd.Timestamp("2026-06-16").date()}
    df = pad_htf_for_session_force_exits(df, strategy, restrict_dates=dates)
    res = run_backtest("trend", str(DATA), params_dict, suppress_log=True, start_date=str(START.date()), end_date=str(END.date()) + " 23:59:59")
    return res, tf


def match_trades(live_df, bt_df, tf, tol_sec=600):
    rows = []
    bt_used = set()
    for _, lv in live_df.iterrows():
        le = pd.to_datetime(lv["entry_time"], format="ISO8601", utc=True).tz_convert("America/New_York").tz_localize(None)
        lx = pd.to_datetime(lv["exit_time"], format="ISO8601", utc=True).tz_convert("America/New_York").tz_localize(None)
        ldir = 1 if str(lv["direction"]).upper().startswith("L") else -1
        best = None
        best_d = 9999
        for j, bt in bt_df.iterrows():
            if j in bt_used:
                continue
            be = pd.to_datetime(bt["entry_time"])
            d = abs((be - le).total_seconds())
            bdir = int(bt["direction"])
            if d < best_d and d <= tol_sec and bdir == ldir:
                best_d = d
                best = (j, bt)
        if best is None:
            rows.append({"status": "LIVE_ONLY", "live_entry": le, "live_pnl": lv["pnl"], "live_reason": lv.get("reason"), "live_exit_path": lv.get("exit_path"), "live_dur": lv.get("duration")})
            continue
        j, bt = best
        bt_used.add(j)
        be = pd.to_datetime(bt["entry_time"])
        bx = pd.to_datetime(bt["exit_time"])
        bh = bt.get("bars_held", float("nan"))
        rows.append({
            "status": "MATCHED",
            "live_entry": le,
            "bt_entry": be,
            "entry_diff_s": (le - be).total_seconds(),
            "live_exit": lx,
            "bt_exit": bx,
            "dir": "LONG" if ldir == 1 else "SHORT",
            "live_pnl": lv["pnl"],
            "bt_pnl": bt["pnl_currency"],
            "pnl_gap": lv["pnl"] - bt["pnl_currency"],
            "live_reason": lv.get("reason"),
            "live_exit_path": lv.get("exit_path"),
            "bt_reason": bt.get("reason"),
            "live_dur": lv.get("duration"),
            "bt_bars_held": bh,
            "live_bar_span": bar_span(le, lx, tf),
            "bt_bar_span": bar_span(be, bx, tf),
            "live_entry_px": lv["entry_price"],
            "live_exit_px": lv["exit_price"],
            "bt_entry_px": bt["entry_price"],
            "bt_exit_px": bt["exit_price"],
        })
    for j, bt in bt_df.iterrows():
        if j not in bt_used:
            rows.append({"status": "BT_ONLY", "bt_entry": bt["entry_time"], "bt_pnl": bt["pnl_currency"], "bt_reason": bt.get("reason"), "bt_bars_held": bt.get("bars_held")})
    return pd.DataFrame(rows)


def main():
    paper = load_paper()
    params = load_trend_params(str(PARAMS))
    res, tf = run_bt_window(params)
    bt = res["trades_df"].copy()
    if not bt.empty:
        bt["entry_time"] = pd.to_datetime(bt["entry_time"])
        bt["exit_time"] = pd.to_datetime(bt["exit_time"])
        bt = bt[(bt["entry_time"] >= START) & (bt["entry_time"] <= END)]

    print("=" * 72)
    print(f"Jun 15-16 2026 paper vs backtest (deployed params, TF={tf}m, trailing delay=1)")
    print("=" * 72)
    print(f"Paper completed trades: {len(paper)}")
    if not paper.empty:
        print(f"  Live total PnL: ${paper.pnl.sum():,.0f}")
        for _, r in paper.iterrows():
            print(f"    {r['entry_time'][:16]} {r['direction']:5} pnl=${r['pnl']:,.0f} reason={r.get('reason')} path={r.get('exit_path')} dur={r.get('duration')}")

    print(f"\nBacktest trades in window: {len(bt)}")
    if not bt.empty:
        print(f"  BT total PnL: ${bt.pnl_currency.sum():,.0f}")
        for _, r in bt.iterrows():
            bh = r.get("bars_held", "?")
            span = bar_span(r["entry_time"], r["exit_time"], tf)
            print(f"    {r['entry_time']} {('LONG' if r['direction']==1 else 'SHORT'):5} pnl=${r['pnl_currency']:,.0f} reason={r.get('reason')} span={span:.0f}")

    cmp = match_trades(paper, bt, tf)
    out = ROOT / "results/jun15_16_2026_compare.csv"
    cmp.to_csv(out, index=False)
    print(f"\nSaved: {out}")

    matched = cmp[cmp["status"] == "MATCHED"]
    if not matched.empty:
        print("\n--- Matched trades (execution artifact focus) ---")
        for _, r in matched.iterrows():
            print(f"\n  {r['dir']} entry live={r['live_entry']} bt={r['bt_entry']} (diff {r['entry_diff_s']:.0f}s)")
            print(f"    PnL live=${r['live_pnl']:,.0f} bt=${r['bt_pnl']:,.0f} gap=${r['pnl_gap']:,.0f}")
            print(f"    Exit live={r['live_reason']} ({r['live_exit_path']}) | bt={r['bt_reason']}")
            print(f"    Prices live {r['live_entry_px']}/{r['live_exit_px']} | bt {r['bt_entry_px']:.2f}/{r['bt_exit_px']:.2f}")
            print(f"    bar_span live={r['live_bar_span']:.0f} bt={r['bt_bar_span']:.0f} bt_bars_held={r['bt_bars_held']}")
        print(f"\n  MATCHED SUM: live=${matched.live_pnl.sum():,.0f} bt=${matched.bt_pnl.sum():,.0f} gap=${matched.pnl_gap.sum():,.0f}")

    bt_only = cmp[cmp["status"] == "BT_ONLY"]
    if not bt_only.empty:
        print(f"\n  BT-only: {len(bt_only)} trades, ${bt_only.bt_pnl.sum():,.0f} (sim profits live never got)")

    # Timeline snippet for first trade
    print("\n--- Timeline check (trade 1) ---")
    tl_path = ROOT / "paper_logs/open_trade_timeline.jsonl"
    if tl_path.exists():
        lines = [json.loads(x) for x in tl_path.read_text().splitlines() if "2026-06-16T09:4" in x or "2026-06-16T09:5" in x]
        for row in lines[:15]:
            print(f"  {row['ts']} close={row['close']} stop={row['stop']} unrealized={row.get('unrealized')}")


if __name__ == "__main__":
    main()

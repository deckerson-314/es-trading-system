import pandas as pd
import sys
import os
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest import run_backtest
from core.paper_backtest import (
    load_live_indicator_overlay,
    parse_htf_bar_events,
    run_paper_parity_backtest,
)
from strategies.factory import StrategyFactory
from plot_comparison import generate_comparison_charts
from core.monitoring import (
    PAPER_WARMUP_MAX_BARS,
    compute_paper_log_start,
    load_paper_1min_ohlcv,
    load_paper_compare_htf,
    parse_paper_bot_active_ranges,
    prepare_paper_parity_ohlcv,
    required_htf_warmup_bars,
)


def parse_live_trades_csv(csv_path, analysis_start=None, analysis_end=None):
    if not os.path.exists(csv_path):
        print(f"File not found: {csv_path}")
        return pd.DataFrame()

    print(f"Parsing trades from {csv_path}...")
    try:
        df = pd.read_csv(csv_path, header=None)
        if "Price" not in df.iloc[0].values and "Price" not in df.columns:
            df.columns = [
                "Time",
                "Symbol",
                "Side",
                "Price",
                "Qty",
                "Commission",
                "RealizedPNL",
                "PermID",
            ]
        elif "Price" in df.iloc[0].values:
            df.columns = df.iloc[0]
            df = df[1:]

        df["Time"] = pd.to_datetime(df["Time"])
        df["Price"] = df["Price"].astype(float)
        df["Qty"] = df["Qty"].astype(float)

        if analysis_start is not None:
            df = df[df["Time"] >= (analysis_start - pd.Timedelta(minutes=30))]
        if analysis_end is not None:
            df = df[df["Time"] <= analysis_end]

        if df.empty:
            return pd.DataFrame()

        df = df.sort_values(["Time", "PermID"], ascending=[True, True])

        trades = []
        for symbol, symbol_df in df.groupby("Symbol"):
            net_pos = 0
            entry_fill = None

            for _, row in symbol_df.iterrows():
                side_sign = 1 if row["Side"] == "BOT" else -1
                qty = row["Qty"]
                prev_pos = net_pos
                net_pos += side_sign * qty

                if prev_pos == 0 and net_pos != 0:
                    entry_fill = row
                elif prev_pos != 0 and net_pos == 0:
                    if entry_fill is not None:
                        direction = 1 if entry_fill["Side"] == "BOT" else -1
                        trades.append(
                            {
                                "live_entry_time": entry_fill["Time"],
                                "live_exit_time": row["Time"],
                                "live_direction": direction,
                                "live_entry_price": float(entry_fill["Price"]),
                                "live_exit_price": float(row["Price"]),
                                "live_pnl": (
                                    (float(row["Price"]) - float(entry_fill["Price"]))
                                    * direction
                                    * 50
                                    * float(entry_fill["Qty"])
                                ),
                                "symbol": symbol,
                            }
                        )
                    entry_fill = None

        return pd.DataFrame(trades)

    except Exception as e:
        print(f"Error parsing CSV: {e}")
        return pd.DataFrame()


def load_trend_params(params_path):
    if not os.path.exists(params_path):
        print(f"WARNING: Params file not found at {params_path}, using defaults")
        return {}

    df = pd.read_csv(params_path)
    params = {}

    if "Solution_0" in df.columns:
        col_name = "Solution_0"
        if "Solution_0_SELECTED" in df.columns:
            col_name = "Solution_0_SELECTED"

        for _, row in df.iterrows():
            name = row.get("Name")
            if pd.isna(name) or str(name).startswith("==="):
                continue
            row_type = row.get("Type", "")
            val = row.get(col_name)
            if pd.isna(val) or val == "":
                continue

            if row_type == "int":
                try:
                    val = int(float(val))
                except Exception:
                    pass
            elif row_type == "float":
                try:
                    val = float(val)
                except Exception:
                    pass
            elif row_type == "bool":
                if str(val).lower() == "true":
                    val = True
                elif str(val).lower() == "false":
                    val = False

            params[name] = {"value": val, "type": row_type}
    else:
        for _, row in df.iterrows():
            name = row.get("Name")
            val = row.get("Value")
            if pd.isna(name):
                continue

            row_type = row.get("Type", "float")
            if pd.isna(val) or val == "":
                continue

            if row_type == "int":
                try:
                    val = int(float(val))
                except Exception:
                    pass
            elif row_type == "float":
                try:
                    val = float(val)
                except Exception:
                    pass
            elif row_type == "bool":
                if str(val).lower() in ["true", "1"]:
                    val = True
                else:
                    val = False

            params[name] = {"value": val, "type": row_type}

    return params


def fill_to_event_bar(fill_time, events, tolerance_seconds: float = 1200.0):
    """Map a broker fill time to the HTF bar label from the nearest prior log event."""
    if fill_time is None or not events:
        return None
    t = pd.Timestamp(fill_time)
    if t.tz is not None:
        t = t.tz_convert("US/Eastern").tz_localize(None)
    best_bar = None
    best_lag = None
    for bar_label, wall_time in events:
        lag = (t - wall_time).total_seconds()
        if 0 <= lag <= tolerance_seconds:
            if best_lag is None or lag < best_lag:
                best_lag = lag
                best_bar = bar_label
    return best_bar


def bars_apart(ts_a, ts_b, tf_mins: int) -> float:
    """Absolute distance in HTF bar units (0 = same bar label)."""
    if ts_a is None or ts_b is None:
        return float("inf")
    a = pd.Timestamp(ts_a)
    b = pd.Timestamp(ts_b)
    return abs((a - b).total_seconds()) / max(60.0 * tf_mins, 60.0)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Compare Trend paper trades to run_backtest using the same 1-min warmup "
            "window and resample path as the live paper bot."
        )
    )
    parser.add_argument(
        "--data-1min",
        default=os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "paper_logs", "live_1min.csv"
        ),
        help="Persisted 1-min OHLCV (default: paper_logs/live_1min.csv)",
    )
    parser.add_argument(
        "--data",
        default=os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "paper_logs", "live_data.csv"
        ),
        help="Legacy HTF log for chart overlays only (default: paper_logs/live_data.csv)",
    )
    parser.add_argument(
        "--execution-log",
        default=os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "paper_logs",
            "trend_paper_execution.log",
        ),
        help="Paper execution log used to recover 1-min bars when live_1min.csv is incomplete",
    )
    parser.add_argument(
        "--live-trades",
        default=os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "paper_logs", "live_trades.csv"
        ),
        help="IB execution log (default: paper_logs/live_trades.csv)",
    )
    parser.add_argument(
        "--params",
        default=os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "strategies",
            "trend",
            "parameters",
            "trend_strategy_params.csv",
        ),
        help="Trend params CSV (default: production trend_strategy_params.csv)",
    )
    parser.add_argument(
        "--analysis-start",
        default="2026-03-31 12:00:00",
        help="Inclusive start of trade comparison window (pandas-parsable)",
    )
    parser.add_argument(
        "--analysis-end",
        default="2026-03-31 16:00:00",
        help="Inclusive end of trade comparison window (pandas-parsable)",
    )
    parser.add_argument(
        "--warmup-bars",
        type=int,
        default=PAPER_WARMUP_MAX_BARS,
        help=f"Rolling 1-min warmup window (default: {PAPER_WARMUP_MAX_BARS}, matches live bot)",
    )
    parser.add_argument(
        "--results-csv",
        default="final_comparison_results.csv",
        help="Where to write the match table (default: final_comparison_results.csv)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if any connected-period trade is not MATCHED (±1 HTF bar)",
    )
    args = parser.parse_args()

    data_path = args.data
    live_trades_path = args.live_trades
    params_path = args.params
    analysis_start = pd.Timestamp(args.analysis_start)
    analysis_end = pd.Timestamp(args.analysis_end)

    print(
        f"--- Running Comparison for Trend Strategy "
        f"(Analysis Window: {analysis_start} to {analysis_end}) ---"
    )

    live_trades = parse_live_trades_csv(
        live_trades_path, analysis_start=analysis_start, analysis_end=analysis_end
    )
    if not live_trades.empty:
        live_trades = live_trades[
            (live_trades["live_entry_time"] >= analysis_start)
            & (live_trades["live_entry_time"] <= analysis_end)
        ]
        live_trades = live_trades.sort_values("live_entry_time")
        print(f"Found {len(live_trades)} completed trades in live_trades.csv for Trend Strategy.")
    else:
        print("No completed trades found in log.")
        return

    params_dict = load_trend_params(params_path)
    print(f"Loaded {len(params_dict)} parameters for Trend strategy.")
    strategy_inst = StrategyFactory.get_strategy("trend", params_dict)

    # Load enough 1-min history for IB seed depth + SMA/Donchian HTF warmup.
    log_start = compute_paper_log_start(strategy_inst, analysis_start, max_bars=args.warmup_bars)
    print(f"Loading 1-min OHLCV from {log_start} through {analysis_end} ...")
    df_1min = load_paper_1min_ohlcv(
        args.data_1min,
        execution_log=args.execution_log,
        log_start=log_start,
        log_end=analysis_end,
        legacy_htf_path=None,
    )
    if not df_1min.empty:
        df_1min = df_1min[df_1min.index <= analysis_end].iloc[-int(args.warmup_bars) :]
    need_htf = required_htf_warmup_bars(strategy_inst)
    tf = max(1, int(getattr(strategy_inst, "timeframe", 1) or 1))
    need_1min = min(int(args.warmup_bars), int(need_htf * tf * 1.5))
    pad_dates = {
        d.date()
        for d in pd.date_range(analysis_start.normalize(), analysis_end.normalize(), freq="D")
    }

    df_htf = load_paper_compare_htf(
        args.data,
        strategy_inst,
        log_start,
        analysis_end,
        df_1min=df_1min,
        execution_log_path=args.execution_log,
    )
    if df_htf.empty:
        print("live_data HTF unavailable; falling back to 1-min resample pipeline ...")
        df_htf = prepare_paper_parity_ohlcv(
            df_1min,
            strategy_inst,
            end_time=analysis_end,
            max_bars=args.warmup_bars,
            pad_dates=pad_dates,
            htf_overlay_path=args.data,
        )
    else:
        print(
            f"Using recorded HTF from {args.data}: {len(df_htf)} rows "
            f"({df_htf.index.min()} .. {df_htf.index.max()})"
        )
    if len(df_1min) < need_1min:
        print(
            f"WARNING: Only {len(df_1min)} 1-min bars in rolling window (need ~{need_1min}). "
            f"Restart the paper bot once so paper_logs/live_1min.csv captures the IB seed."
        )
    if df_1min.empty:
        print(
            "ERROR: No 1-min OHLCV available. The paper bot writes paper_logs/live_1min.csv "
            "on subscribe and each new bar; older sessions can be recovered from --execution-log."
        )
        return

    if df_htf.empty:
        print("ERROR: Paper-parity HTF series is empty after resample.")
        return

    min_need = getattr(strategy_inst, "min_bars_required", 0)
    print(
        f"Paper-parity data: {len(df_1min)} 1-min rows "
        f"({df_1min.index.min()} .. {df_1min.index.max()}) -> "
        f"{len(df_htf)} HTF rows; warmup cap={args.warmup_bars}"
    )
    if len(df_1min) < min_need:
        print(
            f"WARNING: Only {len(df_1min)} 1-min bars loaded; strategy prefers >={min_need} "
            f"for full indicator warmup."
        )

    temp_data_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "temp_trend_bt_data.csv"
    )
    df_htf.to_csv(temp_data_path)
    print(f"Saved {len(df_htf)} HTF rows to {temp_data_path} (paper-parity resample)")

    active_ranges = parse_paper_bot_active_ranges(
        args.execution_log,
        dates=pad_dates,
        end_time=analysis_end,
    )
    htf_events = parse_htf_bar_events(
        args.execution_log,
        timeframe=tf,
        start=analysis_start - pd.Timedelta(days=1),
        end=analysis_end + pd.Timedelta(hours=1),
    )
    if active_ranges:
        print(f"Paper bot active ranges ({len(active_ranges)}):")
        for start, end in active_ranges:
            print(f"  {start} .. {end}")

    print("Running paper-parity backtest (execution-log OHLC replay)...")
    live_overlay = load_live_indicator_overlay(args.data)
    if not live_overlay.empty:
        print(f"Using live indicator overlay from {args.data}: {len(live_overlay)} rows")
    bt_results = run_paper_parity_backtest(
        strategy_inst,
        params_dict,
        df_htf,
        args.execution_log,
        df_1min=df_1min,
        live_indicator_overlay=live_overlay,
        active_ranges=active_ranges,
        max_bars=args.warmup_bars,
    )

    bt_trades = bt_results.get("trades_df", pd.DataFrame())

    if not bt_trades.empty:
        bt_trades = bt_trades.rename(
            columns={
                "entry_time": "bt_entry_time",
                "exit_time": "bt_exit_time",
                "direction": "bt_direction",
                "entry_price": "bt_entry_price",
                "exit_price": "bt_exit_price",
                "pnl_currency": "bt_pnl",
                "reason": "bt_reason",
            }
        )
        bt_trades["bt_entry_time"] = pd.to_datetime(bt_trades["bt_entry_time"])
        if bt_trades["bt_entry_time"].dt.tz is not None:
            bt_trades["bt_entry_time"] = (
                bt_trades["bt_entry_time"].dt.tz_convert("US/Eastern").dt.tz_localize(None)
            )
        bt_trades["bt_exit_time"] = pd.to_datetime(bt_trades["bt_exit_time"])
        if bt_trades["bt_exit_time"].dt.tz is not None:
            bt_trades["bt_exit_time"] = (
                bt_trades["bt_exit_time"].dt.tz_convert("US/Eastern").dt.tz_localize(None)
            )
        n_all = len(bt_trades)
        win = (bt_trades["bt_entry_time"] >= analysis_start) & (
            bt_trades["bt_entry_time"] <= analysis_end
        )
        bt_trades = bt_trades.loc[win].reset_index(drop=True)
        print(
            f"Backtest completed with {n_all} trades on paper-parity series; "
            f"{len(bt_trades)} entries fall in analysis window."
        )
    else:
        print("Backtest produced 0 trades.")

    matches = []
    live_trades_sorted = live_trades.sort_values("live_entry_time").reset_index(drop=True)
    bt_trades_sorted = (
        bt_trades.sort_values("bt_entry_time").reset_index(drop=True)
        if not bt_trades.empty
        else pd.DataFrame(columns=["bt_entry_time", "bt_direction"])
    )

    htf_bar_index = df_htf.index

    for _, live_trade in live_trades_sorted.iterrows():
        live_time = live_trade["live_entry_time"]
        live_dir = live_trade["live_direction"]
        live_pnl = live_trade["live_pnl"]
        live_signal_bar = fill_to_event_bar(live_time, htf_events)
        live_exit_bar = fill_to_event_bar(live_trade["live_exit_time"], htf_events)

        if not bt_trades_sorted.empty:
            entry_diffs = bt_trades_sorted["bt_entry_time"].apply(
                lambda t: bars_apart(t, live_signal_bar, tf)
            )
            potential_matches = bt_trades_sorted[
                (entry_diffs <= 1.0) & (bt_trades_sorted["bt_direction"] == live_dir)
            ].copy()
            if not potential_matches.empty:
                potential_matches["entry_bar_diff"] = entry_diffs.loc[potential_matches.index]
        else:
            potential_matches = pd.DataFrame()

        live_dur = live_trade["live_exit_time"] - live_trade["live_entry_time"]

        if not potential_matches.empty:
            best_idx = potential_matches["entry_bar_diff"].idxmin()
            closest_bt_trade = potential_matches.loc[best_idx]

            bt_time = closest_bt_trade["bt_entry_time"]
            bt_dir = closest_bt_trade["bt_direction"]
            bt_pnl = closest_bt_trade["bt_pnl"] if "bt_pnl" in closest_bt_trade else 0
            exit_bar_diff = bars_apart(closest_bt_trade["bt_exit_time"], live_exit_bar, tf)

            time_diff_seconds = (
                (live_signal_bar - bt_time).total_seconds()
                if live_signal_bar is not None
                else (live_time - bt_time).total_seconds()
            )
            status = "MATCHED"
            if live_dir != bt_dir:
                status = "DIR MISMATCH"
            elif closest_bt_trade["entry_bar_diff"] > 0:
                status = "ENTRY BAR OFF"
            elif exit_bar_diff > 1.0:
                status = "EXIT BAR OFF"

            bt_dur = closest_bt_trade["bt_exit_time"] - closest_bt_trade["bt_entry_time"]

            matches.append(
                {
                    "Live Time": live_time,
                    "Live Signal Bar": live_signal_bar,
                    "BT Time": bt_time,
                    "Diff (s)": time_diff_seconds,
                    "Entry Bars Off": closest_bt_trade["entry_bar_diff"],
                    "Exit Bars Off": exit_bar_diff,
                    "Status": status,
                    "Live Dir": live_dir,
                    "BT Dir": bt_dir,
                    "Live Exit Time": live_trade["live_exit_time"],
                    "Live Exit Bar": live_exit_bar,
                    "BT Exit Time": closest_bt_trade["bt_exit_time"],
                    "Live Price": live_trade["live_entry_price"],
                    "BT Price": closest_bt_trade["bt_entry_price"],
                    "Live Exit Price": live_trade["live_exit_price"],
                    "BT Exit Price": closest_bt_trade["bt_exit_price"],
                    "Live PnL": live_pnl,
                    "BT PnL": bt_pnl,
                    "PnL Diff": live_pnl - bt_pnl if bt_pnl else live_pnl,
                    "BT Reason": closest_bt_trade.get("bt_reason", "N/A"),
                    "Live Dur": live_dur,
                    "BT Dur": bt_dur,
                    "SortTime": live_time,
                }
            )
        else:
            matches.append(
                {
                    "Live Time": live_time,
                    "Live Signal Bar": live_signal_bar,
                    "BT Time": None,
                    "Diff (s)": None,
                    "Entry Bars Off": None,
                    "Exit Bars Off": None,
                    "Status": "LIVE ONLY",
                    "Live Dir": live_dir,
                    "BT Dir": None,
                    "Live Exit Time": live_trade["live_exit_time"],
                    "Live Exit Bar": live_exit_bar,
                    "BT Exit Time": None,
                    "Live Price": live_trade["live_entry_price"],
                    "BT Price": None,
                    "Live Exit Price": live_trade["live_exit_price"],
                    "BT Exit Price": None,
                    "Live PnL": live_pnl,
                    "BT PnL": None,
                    "PnL Diff": None,
                    "BT Reason": None,
                    "Live Dur": live_dur,
                    "BT Dur": None,
                    "SortTime": live_time,
                }
            )

    matched_bt_times = {m["BT Time"] for m in matches if m["BT Time"] is not None}
    if not bt_trades_sorted.empty:
        for _, row in bt_trades_sorted.iterrows():
            if row["bt_entry_time"] not in matched_bt_times:
                matches.append(
                    {
                        "Live Time": None,
                        "BT Time": row["bt_entry_time"],
                        "Diff (s)": None,
                        "Status": "BT ONLY",
                        "Live Dir": None,
                        "BT Dir": row["bt_direction"],
                        "Live Price": None,
                        "BT Price": row["bt_entry_price"],
                        "Live Exit Time": None,
                        "BT Exit Time": row["bt_exit_time"],
                        "Live Exit Price": None,
                        "BT Exit Price": row["bt_exit_price"],
                        "Live PnL": None,
                        "BT PnL": row.get("bt_pnl", 0),
                        "PnL Diff": None,
                        "BT Reason": row.get("bt_reason", "N/A"),
                        "Live Dur": None,
                        "BT Dur": row["bt_exit_time"] - row["bt_entry_time"],
                        "SortTime": row["bt_entry_time"],
                    }
                )

    matches_df = pd.DataFrame(matches)

    if not matches_df.empty:
        matches_df = matches_df.sort_values("SortTime").reset_index(drop=True)

        cols = [
            "Live Time",
            "Live Signal Bar",
            "BT Time",
            "Entry Bars Off",
            "Status",
            "Live Exit Bar",
            "BT Exit Time",
            "Exit Bars Off",
            "Live Dir",
            "BT Dir",
            "Live Price",
            "BT Price",
            "Live PnL",
            "BT PnL",
            "BT Reason",
        ]

        print("\n" + "=" * 95)
        print("MATCHED COMPARISON (TREND STRATEGY — PAPER PARITY DATA)")
        print("=" * 95)
        print(matches_df[cols].to_string())

        summary = matches_df["Status"].value_counts()
        matches_df.to_csv(args.results_csv, index=False)
        print("\nSummary:")
        print(summary)
        print(f"\nWrote: {args.results_csv}")

        if args.strict:
            bad = matches_df[
                ~matches_df["Status"].isin(["MATCHED"])
                & ~matches_df["Status"].isin(["BT ONLY"])
            ]
            if not bad.empty:
                print(f"\nSTRICT: {len(bad)} non-matching connected-period trade(s).")
                raise SystemExit(1)

        try:
            print("\nGenerating interactive comparison dashboard overlays...")
            generate_comparison_charts(
                args.results_csv, "web/comparison_charts", data_path=data_path, params_path=args.params
            )
        except Exception as e:
            print(f"Failed to generate dashboard: {e}")
    else:
        print("No matches generated.")


if __name__ == "__main__":
    main()

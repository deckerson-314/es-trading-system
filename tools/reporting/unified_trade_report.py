import os
import html
import json
import math
from types import SimpleNamespace

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def _trade_get(trade, key, default=None):
    if isinstance(trade, dict):
        return trade.get(key, default)
    return getattr(trade, key, default)


def _direction_to_int(direction):
    if isinstance(direction, str):
        d = direction.strip().upper()
        return 1 if d in ("LONG", "BUY", "1", "+1") else -1
    try:
        return 1 if int(direction) == 1 else -1
    except Exception:
        return 1


def _ensure_df_datetime_index(df):
    if df is None:
        return pd.DataFrame()
    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    if df.empty:
        return df.copy()
    out = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(out.index):
        out.index = pd.to_datetime(out.index, errors="coerce")
    out = out[~out.index.isna()]
    return out


def _segment_for_trade(df, entry_time, exit_time, bars=60):
    if df.empty:
        return df
    try:
        e_idx = df.index.get_indexer([entry_time], method="nearest")[0]
        x_idx = df.index.get_indexer([exit_time], method="nearest")[0]
    except Exception:
        return df.tail(min(len(df), 300))
    start = max(0, min(e_idx, x_idx) - bars)
    end = min(len(df) - 1, max(e_idx, x_idx) + bars)
    return df.iloc[start:end + 1]


def _timeframe_mins_from_params(params_snapshot: dict) -> int:
    for key in ("Timeframe (minutes)", "timeframe"):
        if key not in params_snapshot:
            continue
        v = params_snapshot[key]
        if isinstance(v, dict) and "value" in v:
            v = v["value"]
        try:
            return max(1, int(round(float(v))))
        except (TypeError, ValueError):
            continue
    return 1


def _resample_segment_htf(seg_1m: pd.DataFrame, tf_mins: int) -> pd.DataFrame:
    """Align OHLCV + indicator columns to strategy HTF (same rule as live monitoring)."""
    if seg_1m.empty or tf_mins <= 1:
        return seg_1m
    cols = list(seg_1m.columns)
    logic = {}
    for c in cols:
        if c == "open":
            logic[c] = "first"
        elif c == "high":
            logic[c] = "max"
        elif c == "low":
            logic[c] = "min"
        elif c == "close":
            logic[c] = "last"
        elif c == "volume":
            logic[c] = "sum"
        else:
            logic[c] = "last"
    out = seg_1m.resample(f"{tf_mins}min", closed="right", label="right").agg(logic)
    return out.dropna(subset=["open", "high", "low", "close"])


def _pair_align_entry_exit(et, xt):
    """Make entry/exit comparable (same naive vs tz-aware convention)."""
    et = pd.Timestamp(et)
    xt = pd.Timestamp(xt)
    if et.tzinfo is None and xt.tzinfo is not None:
        xt = pd.Timestamp(xt.to_pydatetime().replace(tzinfo=None))
    elif et.tzinfo is not None and xt.tzinfo is None:
        xt = xt.tz_localize(et.tz, ambiguous="infer", nonexistent="shift_forward")
    return et, xt


def _align_ts_to_trade_ref(ts, et):
    """
    Align *ts* to *et*'s clock convention (naive vs aware), matching core/charting.py
    rules for mixing tz-aware bar indices with naive trade datetimes.
    """
    t = pd.Timestamp(ts)
    et = pd.Timestamp(et)
    if et.tzinfo is None and t.tzinfo is not None:
        return pd.Timestamp(t.to_pydatetime().replace(tzinfo=None))
    if et.tzinfo is not None and t.tzinfo is None:
        try:
            return t.tz_localize(et.tz, ambiguous="infer", nonexistent="shift_forward")
        except (TypeError, ValueError):
            return t
    return t


def _timeline_search_dirs() -> list:
    dirs = []
    env = os.environ.get("IB_BOT_OUTPUT_DIR", "").strip()
    if env:
        dirs.append(os.path.abspath(env))
    root = os.getcwd()
    dirs.extend([os.path.join(root, "paper_logs"), os.path.join(root, "live_logs")])
    return [d for d in dirs if d and os.path.isdir(d)]


def _load_timeline_traces(entry_time, exit_time, dir_int, stop_at_open=None, stop_at_close=None,
                          tp_at_open=None, tp_at_close=None, output_dir=None):
    """Build stop/TP hv trail for trade report charts."""
    from core.timeline import build_display_trail_series, load_trade_timeline_series

    raw = load_trade_timeline_series(
        output_dir,
        entry_time,
        exit_time=exit_time,
        direction=dir_int,
    )
    series = build_display_trail_series(
        entry_time,
        exit_time,
        stop_at_open=stop_at_open,
        stop_at_close=stop_at_close,
        tp_at_open=tp_at_open,
        tp_at_close=tp_at_close,
        timeline=raw,
    )
    if not series:
        return None, None, None
    xs = [pd.Timestamp(t) for t in series["times"]]
    return xs, series["stop"], series["tp"]


def generate_unified_trade_report(
    trade,
    df,
    output_dir,
    version="live",
    sol_name=None,
    parent_filename=None,
    params_snapshot=None,
):
    """
    Generate one unified trade artifact used by both:
    - backtest 'chart' links
    - paper/live detailed trade reports
    """
    os.makedirs(output_dir, exist_ok=True)

    exit_time = pd.to_datetime(_trade_get(trade, "exit_time", pd.Timestamp.now()))
    entry_time_raw = _trade_get(trade, "entry_time", None)
    entry_time = pd.to_datetime(entry_time_raw) if entry_time_raw is not None else exit_time

    ts_slug = exit_time.strftime("%Y%m%d_%H%M%S")
    filename = f"trade_report_{ts_slug}.html"
    filepath = os.path.join(output_dir, filename)

    direction_raw = _trade_get(trade, "direction", 1)
    dir_int = _direction_to_int(direction_raw)
    direction_label = "LONG" if dir_int == 1 else "SHORT"

    entry_price = float(_trade_get(trade, "entry_price", 0) or 0)
    exit_price = float(_trade_get(trade, "exit_price", 0) or 0)
    qty = float(_trade_get(trade, "qty", 1) or 1)

    pnl = _trade_get(trade, "pnl_currency", None)
    if pnl is None:
        pnl = _trade_get(trade, "pnl", (exit_price - entry_price) * 50 * qty * dir_int)
    pnl = float(pnl or 0)

    reason = str(_trade_get(trade, "reason", "N/A"))
    live_exit_type = str(_trade_get(trade, "live_exit_type", "") or "")
    duration = str(_trade_get(trade, "duration", "N/A") or "N/A")
    stop_open = _trade_get(trade, "stop_at_open", _trade_get(trade, "stop", None))
    tp_open = _trade_get(trade, "tp_at_open", _trade_get(trade, "tp", None))
    stop_close = _trade_get(trade, "stop_at_close", None)
    tp_close = _trade_get(trade, "tp_at_close", None)
    slip_pts = _trade_get(trade, "slippage_pts", None)
    slip_usd = _trade_get(trade, "slippage_usd", None)
    slip_ref = _trade_get(trade, "slippage_reference", None)

    if params_snapshot is None:
        params_snapshot = _trade_get(trade, "params_snapshot", {}) or {}
    if not isinstance(params_snapshot, dict):
        params_snapshot = {}

    df = _ensure_df_datetime_index(df)
    tf_mins = _timeframe_mins_from_params(params_snapshot)
    bar_window = max(60, min(600, 24 * int(tf_mins)))
    seg_1m = _segment_for_trade(df, entry_time, exit_time, bars=bar_window) if not df.empty else df
    seg_plot = _resample_segment_htf(seg_1m, tf_mins) if tf_mins > 1 else seg_1m
    tl_x, tl_stop, tl_tp = _load_timeline_traces(
        entry_time,
        exit_time,
        dir_int,
        stop_at_open=stop_open,
        stop_at_close=stop_close,
        tp_at_open=tp_open,
        tp_at_close=tp_close,
        output_dir=os.environ.get("IB_BOT_OUTPUT_DIR") or os.path.join(os.getcwd(), "paper_logs"),
    )

    price_title = (
        f"Price ({tf_mins}-min HTF — matches live signal aggregation)"
        if tf_mins > 1
        else "Price + Context (1m; indicators ffill from HTF in live)"
    )
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.62, 0.18, 0.2],
        subplot_titles=(price_title, "RSI/ADX", "Volume"),
    )

    if not seg_plot.empty and all(c in seg_plot.columns for c in ("open", "high", "low", "close")):
        fig.add_trace(
            go.Candlestick(
                x=seg_plot.index,
                open=seg_plot["open"],
                high=seg_plot["high"],
                low=seg_plot["low"],
                close=seg_plot["close"],
                name="Price",
            ),
            row=1,
            col=1,
        )

        for col, color, dash, name in [
            ("upper", "royalblue", "dash", "Upper BB"),
            ("lower", "royalblue", "dash", "Lower BB"),
            ("donchian_high", "deepskyblue", "dot", "Donchian High"),
            ("donchian_low", "deepskyblue", "dot", "Donchian Low"),
            ("vwap", "orange", "solid", "VWAP"),
            ("sma_regime", "gray", "solid", "SMA"),
        ]:
            if col in seg_plot.columns:
                fig.add_trace(
                    go.Scatter(
                        x=seg_plot.index,
                        y=seg_plot[col],
                        line=dict(color=color, dash=dash, width=1.4),
                        name=name,
                    ),
                    row=1,
                    col=1,
                )

        fig.add_trace(
            go.Scatter(
                x=[entry_time],
                y=[entry_price],
                mode="markers+text",
                marker=dict(symbol="triangle-up", size=14, color="green" if dir_int == 1 else "red"),
                text=["ENTRY"],
                textposition="top center",
                name="Entry",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=[exit_time],
                y=[exit_price],
                mode="markers+text",
                marker=dict(symbol="x", size=13, color="lime" if pnl >= 0 else "darkred"),
                text=["EXIT"],
                textposition="bottom center",
                name="Exit",
            ),
            row=1,
            col=1,
        )

        x0 = seg_plot.index.min()
        x1 = seg_plot.index.max()
        has_trail = tl_x and tl_stop and len(tl_x) >= 2
        if not has_trail:
            for val, name, color in [
                (stop_open, "SL@open", "red"),
                (tp_open, "TP@open", "purple"),
                (stop_close, "SL@close", "firebrick"),
                (tp_close, "TP@close", "darkviolet"),
            ]:
                if val is not None:
                    y = float(val)
                    fig.add_trace(
                        go.Scatter(
                            x=[x0, x1],
                            y=[y, y],
                            mode="lines",
                            line=dict(color=color, dash="dot", width=1.2),
                            name=name,
                        ),
                        row=1,
                        col=1,
                    )

        if has_trail:
            has_tp = any(v is not None for v in (tl_tp or []))
            fig.add_trace(
                go.Scatter(
                    x=tl_x,
                    y=tl_stop,
                    mode="lines",
                    line=dict(color="#e65100", width=2.5, shape="hv"),
                    connectgaps=False,
                    name="SL trail",
                ),
                row=1,
                col=1,
            )
            if has_tp:
                fig.add_trace(
                    go.Scatter(
                        x=tl_x,
                        y=tl_tp,
                        mode="lines",
                        line=dict(color="#6a1b9a", width=1.5, dash="dash", shape="hv"),
                        connectgaps=False,
                        name="TP trail",
                    ),
                    row=1,
                    col=1,
                )

        if "rsi" in seg_plot.columns:
            fig.add_trace(
                go.Scatter(x=seg_plot.index, y=seg_plot["rsi"], line=dict(color="purple", width=1.5), name="RSI"),
                row=2,
                col=1,
            )
            fig.add_hline(y=70, line_dash="dot", line_color="red", row=2, col=1)
            fig.add_hline(y=30, line_dash="dot", line_color="green", row=2, col=1)
        if "adx" in seg_plot.columns:
            fig.add_trace(
                go.Scatter(x=seg_plot.index, y=seg_plot["adx"], line=dict(color="steelblue", width=1.5), name="ADX"),
                row=2,
                col=1,
            )
            fig.add_hline(y=25, line_dash="dot", line_color="gray", row=2, col=1)

        if "volume" in seg_plot.columns:
            colors = ["green" if c >= o else "red" for c, o in zip(seg_plot["close"], seg_plot["open"])]
            fig.add_trace(
                go.Bar(x=seg_plot.index, y=seg_plot["volume"], marker_color=colors, name="Volume"),
                row=3,
                col=1,
            )
    else:
        # Fallback for historical trades when OHLC context is unavailable.
        x_vals = [entry_time, exit_time]
        y_vals = [entry_price, exit_price]
        fig.add_trace(
            go.Scatter(
                x=x_vals,
                y=y_vals,
                mode="lines+markers+text",
                line=dict(color="#1f77b4", width=2),
                marker=dict(size=10, color=["#2ca02c", "#d62728" if pnl < 0 else "#2ca02c"]),
                text=["ENTRY", "EXIT"],
                textposition="top center",
                name="Trade Path",
            ),
            row=1,
            col=1,
        )
        for val, name, color in [
            (stop_open, "SL@open", "red"),
            (tp_open, "TP@open", "purple"),
            (stop_close, "SL@close", "firebrick"),
            (tp_close, "TP@close", "darkviolet"),
        ]:
            if val is not None:
                y = float(val)
                fig.add_trace(
                    go.Scatter(
                        x=x_vals,
                        y=[y, y],
                        mode="lines",
                        line=dict(color=color, dash="dot", width=1.2),
                        name=name,
                    ),
                    row=1,
                    col=1,
                )
        fig.add_annotation(
            text="OHLC context unavailable for this historical trade; showing reconstructed path.",
            xref="paper", yref="paper", x=0.5, y=0.72, showarrow=False,
            font=dict(size=11, color="#6b7280"),
        )

    sol_prefix = f"[{sol_name}] " if sol_name else ""
    exit_label = live_exit_type or reason
    title = f"{sol_prefix}{direction_label} | PnL ${pnl:,.2f} | {exit_label}"
    fig.update_layout(title=title, height=980, hovermode="x unified", template="plotly_white")
    plot_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    trade_table = {
        "Direction": direction_label,
        "Entry Time": str(entry_time_raw) if entry_time_raw is not None else "N/A",
        "Exit Time": str(exit_time),
        "Entry Price": f"{entry_price:,.2f}",
        "Exit Price": f"{exit_price:,.2f}",
        "PnL": f"{pnl:,.2f}",
        "Qty": f"{qty:g}",
        "Duration": duration,
        "Reason": reason,
        "Live Exit Type": live_exit_type or "N/A",
        "Stop @ Open": "N/A" if stop_open is None else f"{float(stop_open):,.2f}",
        "TP @ Open": "N/A" if tp_open is None else f"{float(tp_open):,.2f}",
        "Stop @ Close": "N/A" if stop_close is None else f"{float(stop_close):,.2f}",
        "TP @ Close": "N/A" if tp_close is None else f"{float(tp_close):,.2f}",
        "Slippage (pts)": "N/A" if slip_pts is None else f"{float(slip_pts):+,.2f}",
        "Slippage ($)": "N/A" if slip_usd is None else f"{float(slip_usd):+,.2f}",
        "Slippage Ref": str(slip_ref) if slip_ref else "N/A",
    }
    trade_rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{html.escape(v)}</td></tr>" for k, v in trade_table.items()
    )

    param_rows = []
    for k in sorted(params_snapshot.keys(), key=lambda x: str(x).lower()):
        v = params_snapshot[k]
        if isinstance(v, dict) and "value" in v:
            v = v["value"]
        param_rows.append(f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>")
    if not param_rows:
        param_rows.append("<tr><td colspan='2'>No parameter snapshot available.</td></tr>")

    raw_payload = {}
    if isinstance(trade, dict):
        raw_payload = trade
    else:
        raw_payload = vars(SimpleNamespace(**{k: _trade_get(trade, k) for k in dir(trade) if not k.startswith("_")}))
    raw_json = html.escape(json.dumps(raw_payload, default=str, indent=2))

    back_link = parent_filename if parent_filename else "../dashboard_paper.html"
    page = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 0; background: #f7f9fc; padding: 20px; }}
    .wrap {{ max-width: 1400px; margin: 0 auto; background: white; border-radius: 12px; padding: 20px; }}
    .back-home {{ display:inline-block; margin-bottom: 16px; padding: 8px 14px; background:#34495e; color:#fff; text-decoration:none; border-radius:6px; }}
    h2 {{ margin-top: 22px; }}
    table {{ width:100%; border-collapse:collapse; margin-top:8px; }}
    th, td {{ border:1px solid #e5e9f0; padding:8px 10px; text-align:left; vertical-align: top; }}
    th {{ background:#eef3fb; }}
    pre {{ background:#0f172a; color:#e2e8f0; border-radius:8px; padding:12px; overflow:auto; }}
  </style>
</head>
<body>
  <div class="wrap">
    <a href="{html.escape(back_link)}" class="back-home">&larr; Back to Dashboard</a>
    {plot_html}
    <h2>Trade Details</h2>
    <table><tbody>{trade_rows}</tbody></table>
    <h2>Parameter Snapshot At Entry</h2>
    <table><thead><tr><th>Parameter</th><th>Value</th></tr></thead><tbody>{''.join(param_rows)}</tbody></table>
    <h2>Raw Trade Payload</h2>
    <pre>{raw_json}</pre>
  </div>
</body>
</html>"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(page)
    return filename


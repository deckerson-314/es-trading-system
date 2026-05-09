import os
import html
import json
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
    duration = str(_trade_get(trade, "duration", "N/A") or "N/A")
    stop_open = _trade_get(trade, "stop_at_open", _trade_get(trade, "stop", None))
    tp_open = _trade_get(trade, "tp_at_open", _trade_get(trade, "tp", None))
    stop_close = _trade_get(trade, "stop_at_close", None)
    tp_close = _trade_get(trade, "tp_at_close", None)

    if params_snapshot is None:
        params_snapshot = _trade_get(trade, "params_snapshot", {}) or {}
    if not isinstance(params_snapshot, dict):
        params_snapshot = {}

    df = _ensure_df_datetime_index(df)
    seg = _segment_for_trade(df, entry_time, exit_time, bars=60) if not df.empty else df

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.62, 0.18, 0.2],
        subplot_titles=("Price + Context", "RSI/ADX", "Volume"),
    )

    if not seg.empty and all(c in seg.columns for c in ("open", "high", "low", "close")):
        fig.add_trace(
            go.Candlestick(
                x=seg.index,
                open=seg["open"],
                high=seg["high"],
                low=seg["low"],
                close=seg["close"],
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
            if col in seg.columns:
                fig.add_trace(
                    go.Scatter(x=seg.index, y=seg[col], line=dict(color=color, dash=dash, width=1.4), name=name),
                    row=1, col=1
                )

        fig.add_trace(
            go.Scatter(
                x=[entry_time], y=[entry_price], mode="markers+text",
                marker=dict(symbol="triangle-up", size=14, color="green" if dir_int == 1 else "red"),
                text=["ENTRY"], textposition="top center", name="Entry",
            ),
            row=1, col=1
        )
        fig.add_trace(
            go.Scatter(
                x=[exit_time], y=[exit_price], mode="markers+text",
                marker=dict(symbol="x", size=13, color="lime" if pnl >= 0 else "darkred"),
                text=["EXIT"], textposition="bottom center", name="Exit",
            ),
            row=1, col=1
        )

        x0 = seg.index.min()
        x1 = seg.index.max()
        for val, name, color in [
            (stop_open, "SL@open", "red"),
            (tp_open, "TP@open", "purple"),
            (stop_close, "SL@close", "firebrick"),
            (tp_close, "TP@close", "darkviolet"),
        ]:
            if val is not None:
                y = float(val)
                fig.add_trace(
                    go.Scatter(x=[x0, x1], y=[y, y], mode="lines", line=dict(color=color, dash="dot", width=1.2), name=name),
                    row=1, col=1
                )

        if "rsi" in seg.columns:
            fig.add_trace(go.Scatter(x=seg.index, y=seg["rsi"], line=dict(color="purple", width=1.5), name="RSI"), row=2, col=1)
            fig.add_hline(y=70, line_dash="dot", line_color="red", row=2, col=1)
            fig.add_hline(y=30, line_dash="dot", line_color="green", row=2, col=1)
        if "adx" in seg.columns:
            fig.add_trace(go.Scatter(x=seg.index, y=seg["adx"], line=dict(color="steelblue", width=1.5), name="ADX"), row=2, col=1)
            fig.add_hline(y=25, line_dash="dot", line_color="gray", row=2, col=1)

        if "volume" in seg.columns:
            colors = ["green" if c >= o else "red" for c, o in zip(seg["close"], seg["open"])]
            fig.add_trace(go.Bar(x=seg.index, y=seg["volume"], marker_color=colors, name="Volume"), row=3, col=1)
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
    title = f"{sol_prefix}{direction_label} | PnL ${pnl:,.2f} | {reason}"
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
        "Stop @ Open": "N/A" if stop_open is None else f"{float(stop_open):,.2f}",
        "TP @ Open": "N/A" if tp_open is None else f"{float(tp_open):,.2f}",
        "Stop @ Close": "N/A" if stop_close is None else f"{float(stop_close):,.2f}",
        "TP @ Close": "N/A" if tp_close is None else f"{float(tp_close):,.2f}",
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


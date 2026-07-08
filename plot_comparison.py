import json
import re
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
import glob
from datetime import timedelta

from strategies.factory import StrategyFactory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Define paths
LIVE_DATA_PATH = os.path.join(BASE_DIR, "paper_logs", "live_data.csv")
DEFAULT_TREND_PARAMS = os.path.join(BASE_DIR, "strategies", "trend", "parameters", "trend_strategy_params.csv")
DEFAULT_EXECUTION_LOG = os.path.join(BASE_DIR, "paper_logs", "trend_paper_execution.log")

_TRADE_OPEN_RE = re.compile(
    r"TRADE OPEN:\s+(LONG|SHORT)\s+@[\d.]+,\s*SL:\s*(?P<sl>[\d.]+|None),\s*TP:\s*\$?(?P<tp>[\d.]+|None)",
    re.IGNORECASE,
)
_LOG_LINE_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+")


def _load_trend_params_for_plot(params_path):
    """Load trend params dict (same shapes as compare_paper_backtest_trend.load_trend_params)."""
    if not params_path or not os.path.exists(params_path):
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
                    continue
            elif row_type == "float":
                try:
                    val = float(val)
                except Exception:
                    continue
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
                    continue
            elif row_type == "float":
                try:
                    val = float(val)
                except Exception:
                    continue
            elif row_type == "bool":
                val = str(val).lower() in ("true", "1")
            params[name] = {"value": val, "type": row_type}
    return params


def parse_paper_trade_open_sl_tp(log_path, live_entry_time, window_sec=900.0):
    """
    Parse SL/TP from trend_paper_execution.log TRADE OPEN line nearest live_entry_time.
    Returns (sl, tp) as floats or (None, None) if not found / None in log.
    """
    if not log_path or not os.path.exists(log_path) or live_entry_time is None or pd.isna(live_entry_time):
        return None, None
    target = pd.Timestamp(live_entry_time)
    day = target.normalize()
    best_sl, best_tp = None, None
    best_abs = 1e30
    try:
        with open(log_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "TRADE OPEN" not in line:
                    continue
                mts = _LOG_LINE_TS_RE.match(line)
                if not mts:
                    continue
                try:
                    log_ts = pd.Timestamp(mts.group(1))
                except Exception:
                    continue
                if log_ts.normalize() != day:
                    continue
                m = _TRADE_OPEN_RE.search(line)
                if not m:
                    continue
                dt_sec = abs((log_ts - target).total_seconds())
                if dt_sec > window_sec:
                    continue
                if dt_sec < best_abs:
                    best_abs = dt_sec
                    sl_raw, tp_raw = m.group("sl"), m.group("tp")
                    try:
                        best_sl = float(sl_raw) if sl_raw.lower() != "none" else None
                    except (TypeError, ValueError):
                        best_sl = None
                    try:
                        best_tp = float(tp_raw) if tp_raw.lower() != "none" else None
                    except (TypeError, ValueError):
                        best_tp = None
    except OSError:
        return None, None
    return best_sl, best_tp


def _first_column_ci(df, want):
    """First column whose lower name matches ``want`` (avoids duplicate open/Open from live_data)."""
    want_l = want.lower()
    for c in df.columns:
        if str(c).lower().strip() == want_l:
            return df[c]
    raise ValueError(f"OHLC frame missing column {want!r}")


def _ohlc_to_lower_ohlcv(ohlc_df):
    """Build a strict OHLCV lowercase frame (one column per role) for resample / strategy."""
    d = ohlc_df.copy()
    vol = (
        _first_column_ci(d, "volume")
        if any(str(c).lower().strip() == "volume" for c in d.columns)
        else pd.Series(0.0, index=d.index)
    )
    out = pd.DataFrame(
        {
            "open": _first_column_ci(d, "open"),
            "high": _first_column_ci(d, "high"),
            "low": _first_column_ci(d, "low"),
            "close": _first_column_ci(d, "close"),
            "volume": vol,
        },
        index=d.index,
    )
    return out.sort_index()


def prepare_trend_simulation_df(ohlc_upper_df, params_dict):
    """
    Same pipeline as backtest.run_backtest: resample -> indicators -> filters -> entry signals.
    ohlc_upper_df: index datetime, Open/High/Low/Close (or lowercase).
    """
    from core.monitoring import prepare_strategy_ohlcv, is_htf_native_ohlcv

    df = _ohlc_to_lower_ohlcv(ohlc_upper_df)
    strategy = StrategyFactory.get_strategy("trend", params_dict)
    tf = int(getattr(strategy, "timeframe", 1) or 1)
    if tf > 1:
        df, _htf_native = prepare_strategy_ohlcv(
            df, tf, assume_htf_native=is_htf_native_ohlcv(df, tf)
        )
    df = strategy.calculate_indicators(df)
    if hasattr(strategy, "apply_filters"):
        df = strategy.apply_filters(df)
    verbose = params_dict.get("verbose", False)
    signals = strategy.calculate_entry_signals(df, verbose=verbose)
    if len(signals) == 3:
        long_sigs, short_sigs, _ = signals
    else:
        long_sigs, short_sigs = signals
    df = df.copy()
    df["entry_long_signal"] = long_sigs
    df["entry_short_signal"] = short_sigs
    return df, strategy


def replay_bt_sl_tp_per_bar(prep_df, strategy, bt_entry_ts, params_dict=None):
    """
    Replay one backtest position whose entry bar time matches bt_entry_ts (within 90s).
    Returns DataFrame indexed by bar time with columns sl, tp (tp NaN if disabled).
    """
    from core.sim_fidelity import ga_live_style_entry_enabled

    bt_entry_ts = pd.Timestamp(bt_entry_ts)
    pending_entry = None
    live_style = ga_live_style_entry_enabled(params_dict or {})
    open_positions = []
    tracked = None
    rows = []
    for row in prep_df.itertuples():
        if pending_entry is not None:
            pos = strategy.setup_position(row.open, pending_entry["direction"], row, prep_df)
            open_positions.append(pos)
            if abs(pd.Timestamp(pos["entry_time"]) - bt_entry_ts) < pd.Timedelta(seconds=90):
                tracked = pos
            pending_entry = None
        for i, pos in enumerate(open_positions[:]):
            strategy.update_trailing_stop(pos, row, prep_df)
            if tracked is pos:
                tpv = pos.get("tp")
                tp_float = np.nan
                if tpv is not None and not (isinstance(tpv, float) and np.isnan(tpv)) and tpv > 0:
                    tp_float = float(tpv)
                rows.append({"t": pd.Timestamp(row.Index), "sl": float(pos["stop"]), "tp": tp_float})
            should_exit, _, _ = strategy.check_exit(pos, row, prep_df)
            if should_exit:
                if tracked is pos:
                    tracked = None
                open_positions.pop(i)
        if not open_positions:
            if row.entry_long_signal:
                if live_style:
                    pos = strategy.setup_position(row.close, 1, row, prep_df)
                    open_positions.append(pos)
                    if abs(pd.Timestamp(pos["entry_time"]) - bt_entry_ts) < pd.Timedelta(seconds=90):
                        tracked = pos
                else:
                    pending_entry = {"direction": 1}
            elif row.entry_short_signal:
                if live_style:
                    pos = strategy.setup_position(row.close, -1, row, prep_df)
                    open_positions.append(pos)
                    if abs(pd.Timestamp(pos["entry_time"]) - bt_entry_ts) < pd.Timedelta(seconds=90):
                        tracked = pos
                else:
                    pending_entry = {"direction": -1}
    if not rows:
        return pd.DataFrame(columns=["sl", "tp"])
    out = pd.DataFrame(rows).set_index("t")
    return out

def load_ohlc_data(csv_path):
    """Load OHLC from paper_logs/live_data.csv (HTF bars as logged; may have real feed gaps)."""
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path, index_col=0, parse_dates=True, on_bad_lines='skip')
        df.columns = [str(c).lower().strip() for c in df.columns]
        df = df[~df.index.duplicated(keep='last')]
        df.index = pd.to_datetime(df.index, utc=True, errors='coerce')
        df = df[df.index.notna()]
        if getattr(df.index, 'tz', None) is not None:
            df.index = df.index.tz_convert('US/Eastern').tz_localize(None)
        rename = {'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close'}
        for k, v in rename.items():
            if k in df.columns:
                df[v] = df[k]
        if 'upper' in df.columns:
            df['Upper'] = df['upper']
        if 'lower' in df.columns:
            df['Lower'] = df['lower']
        return df.sort_index()
    except Exception as e:
        print(f"Error loading OHLC {csv_path}: {e}")
        return None


def _overlay_x_range(trade_row, default_half_width_min=45):
    """
    Span full trade (live + BT entry/exit) with padding. Fixed ±45m around entry only
    hid multi-hour trades and looked like 'missing bars'.
    """
    ts = []
    for key in ('Live Time', 'Live Exit Time', 'BT Time', 'BT Exit Time'):
        if key not in trade_row.index:
            continue
        v = trade_row.get(key)
        if pd.notna(v):
            ts.append(pd.Timestamp(v))
    if not ts:
        return None, None
    tmin, tmax = min(ts), max(ts)
    span = tmax - tmin
    side = max(timedelta(minutes=30), span * 0.08)
    if span < timedelta(minutes=30):
        side = timedelta(minutes=default_half_width_min)
    return tmin - side, tmax + side

def generate_aggregate_plots(df):
    """Generate Aggregate performance comparison plots."""
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=('Cumulative PnL (Live vs BT)', 'PnL Difference Distribution', 
                       'Time Lag (Live - BT)', 'PnL Comparison Scatter'),
        vertical_spacing=0.15
    )
    
    # Sort by time
    df = df.sort_values('SortTime')
    
    # 1. Cumulative PnL
    live_pnl = df['Live PnL'].fillna(0).cumsum()
    bt_pnl = df['BT PnL'].fillna(0).cumsum()
    
    fig.add_trace(go.Scatter(x=df['SortTime'], y=live_pnl, name='Live Cum PnL', line=dict(color='green')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['SortTime'], y=bt_pnl, name='BT Cum PnL', line=dict(color='blue', dash='dash')), row=1, col=1)
    
    # 2. PnL Diff Hist
    pnl_diff = df['PnL Diff'].dropna()
    fig.add_trace(go.Histogram(x=pnl_diff, name='PnL Diff', marker_color='orange'), row=1, col=2)
    
    # 3. Lag Scatter
    fig.add_trace(go.Scatter(
        x=df['SortTime'], y=df['Diff (s)'], 
        mode='markers', name='Time Lag (s)', marker=dict(color='purple', size=6)
    ), row=2, col=1)
    
    # 4. PnL Scatter (Correlation)
    fig.add_trace(go.Scatter(
        x=df['BT PnL'], y=df['Live PnL'],
        mode='markers', name='PnL Correlation', 
        marker=dict(color='teal', size=8),
        text=df['SortTime']
    ), row=2, col=2)
    # Add 1:1 line
    min_val = min(df['BT PnL'].min(), df['Live PnL'].min())
    max_val = max(df['BT PnL'].max(), df['Live PnL'].max())
    fig.add_trace(go.Scatter(
        x=[min_val, max_val], y=[min_val, max_val],
        mode='lines', name='Perfect Match', line=dict(color='gray', dash='dot')
    ), row=2, col=2)

    fig.update_layout(height=800, template='plotly_white', title_text="Aggregate Comparison Metrics")
    
    # Enable Range Slider and Selector on the X-Axis of the 1st subplot (Cum PnL)
    # And link the X-axis of the 3rd subplot (Lag) to it.
    
    # Note: 'x' is R1C1, 'x3' is R2C1.
    fig.update_xaxes(matches='x') # Link all x-axes? No, R1C2 and R2C2 are not time. 
    # Actually, simpler to just set rangeslider on the layout's xaxis, and ensure x3 matches x.
    
    fig.update_xaxes(matches='x', row=2, col=1) # Make Lag plot match Cum PnL plot
    
    fig.update_layout(
        xaxis=dict(
            rangeselector=dict(
                buttons=list([
                    dict(count=1, label="1h", step="hour", stepmode="backward"),
                    dict(count=4, label="4h", step="hour", stepmode="backward"),
                    dict(count=1, label="1d", step="day", stepmode="backward"),
                    dict(count=7, label="1w", step="day", stepmode="backward"),
                    dict(step="all")
                ])
            ),
            rangeslider=dict(visible=True),
            type="date"
        )
    )
    return fig

def generate_overlay_chart(
    trade_row,
    ohlc_df,
    output_dir,
    sim_prep_df=None,
    strategy=None,
    execution_log_path=None,
):
    """Generate individual trade chart with overlay (candle SL/TP from replay + paper log)."""
    try:
        if ohlc_df is None:
            return None

        # Center time
        center_time = trade_row["Live Time"] if pd.notna(trade_row["Live Time"]) else trade_row["BT Time"]
        if pd.isna(center_time):
            return None

        start_t, end_t = _overlay_x_range(trade_row)
        if start_t is None:
            start_t = pd.Timestamp(center_time) - timedelta(minutes=45)
            end_t = pd.Timestamp(center_time) + timedelta(minutes=45)

        mask = (ohlc_df.index >= start_t) & (ohlc_df.index <= end_t)
        sub_df = ohlc_df.loc[mask]

        if sub_df.empty:
            return None

        # Typical step between logged rows (HTF); helps explain sparse candles vs 1m expectation
        bar_hint = ""
        if len(sub_df.index) >= 2:
            deltas = pd.Series(sub_df.index).diff().dt.total_seconds().div(60).median()
            if pd.notna(deltas) and deltas > 0:
                bar_hint = f" — ~{deltas:.0f} min between candles (live_data HTF log)"

        fig = go.Figure()

        # Candles (HTF as stored; true IB outages still show as time gaps with no candles)
        fig.add_trace(
            go.Candlestick(
                x=sub_df.index,
                open=sub_df["Open"],
                high=sub_df["High"],
                low=sub_df["Low"],
                close=sub_df["Close"],
                name="Price (live_data)",
                increasing_line_color="#26a69a",
                decreasing_line_color="#ef5350",
            )
        )

        # Bollinger Bands
        if "Upper" in sub_df.columns and "Lower" in sub_df.columns:
            fig.add_trace(
                go.Scatter(
                    x=sub_df.index,
                    y=sub_df["Upper"],
                    line=dict(color="blue", dash="dash", width=1),
                    name="Upper BB",
                    opacity=0.5,
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=sub_df.index,
                    y=sub_df["Lower"],
                    line=dict(color="blue", dash="dash", width=1),
                    name="Lower BB",
                    opacity=0.5,
                )
            )

        # --- Candle-by-candle SL/TP: backtest (replay) + paper (log at open) ---
        bt_path = pd.DataFrame()
        if (
            sim_prep_df is not None
            and strategy is not None
            and pd.notna(trade_row.get("BT Time"))
            and not sim_prep_df.empty
        ):
            try:
                bt_path = replay_bt_sl_tp_per_bar(sim_prep_df, strategy, trade_row["BT Time"])
            except Exception as ex:
                print(f"BT SL/TP replay skipped: {ex}")
                bt_path = pd.DataFrame()

        if bt_path is not None and not bt_path.empty:
            sl_bt = bt_path["sl"].reindex(sub_df.index)
            tp_bt = bt_path["tp"].reindex(sub_df.index)
            fig.add_trace(
                go.Scatter(
                    x=sub_df.index,
                    y=sl_bt,
                    mode="lines",
                    line=dict(color="#1e3a5f", width=2),
                    name="BT stop (model, per bar)",
                    connectgaps=False,
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=sub_df.index,
                    y=tp_bt,
                    mode="lines",
                    line=dict(color="#5c4d7d", width=2, dash="dash"),
                    name="BT TP (model, per bar)",
                    connectgaps=False,
                )
            )
        else:
            bt_tp = trade_row.get("BT TP")
            if pd.notna(bt_tp):
                fig.add_trace(
                    go.Scatter(
                        x=[sub_df.index[0], sub_df.index[-1]],
                        y=[bt_tp, bt_tp],
                        mode="lines",
                        line=dict(color="purple", dash="dot", width=1),
                        name="Model TP (flat fallback)",
                    )
                )
            bt_stop_hist_str = trade_row.get("BT Stop Hist")
            if isinstance(bt_stop_hist_str, str) and bt_stop_hist_str:
                try:
                    stop_hist = json.loads(bt_stop_hist_str)
                    if stop_hist:
                        st_times = [pd.to_datetime(x[0]) for x in stop_hist]
                        st_prices = [x[1] for x in stop_hist]
                        fig.add_trace(
                            go.Scatter(
                                x=st_times,
                                y=st_prices,
                                mode="lines",
                                line=dict(color="red", width=1.5),
                                name="Model Stop (Dyn, JSON fallback)",
                            )
                        )
                except json.JSONDecodeError:
                    pass

        log_path = execution_log_path or DEFAULT_EXECUTION_LOG
        if pd.notna(trade_row.get("Live Time")):
            p_sl, p_tp = parse_paper_trade_open_sl_tp(log_path, trade_row["Live Time"])
            t0 = trade_row.get("Live Time")
            t1 = trade_row.get("Live Exit Time")
            if p_sl is not None and pd.notna(t0) and pd.notna(t1):
                m = (sub_df.index >= pd.Timestamp(t0)) & (sub_df.index <= pd.Timestamp(t1))
                xs = sub_df.index[m]
                if len(xs) > 0:
                    fig.add_trace(
                        go.Scatter(
                            x=xs,
                            y=[p_sl] * len(xs),
                            mode="lines",
                            line=dict(color="#c2410c", width=2, dash="dot"),
                            name="Paper SL (open bracket)",
                        )
                    )
            if p_tp is not None and pd.notna(t0) and pd.notna(t1):
                m = (sub_df.index >= pd.Timestamp(t0)) & (sub_df.index <= pd.Timestamp(t1))
                xs = sub_df.index[m]
                if len(xs) > 0:
                    fig.add_trace(
                        go.Scatter(
                            x=xs,
                            y=[p_tp] * len(xs),
                            mode="lines",
                            line=dict(color="#b45309", width=2, dash="dashdot"),
                            name="Paper TP (limit @ open)",
                        )
                    )

        # Live Trade
        if pd.notna(trade_row['Live Time']):
            live_is_long = trade_row.get('Live Dir') in [1, 'LONG', 'Long', 'long']
            color = 'green' if live_is_long else 'red'
            # Entry
            fig.add_trace(go.Scatter(
                x=[trade_row['Live Time']], y=[trade_row['Live Price']],
                mode='markers',
                marker=dict(symbol='triangle-up' if live_is_long else 'triangle-down', size=15, color=color, line=dict(width=2, color='black')),
                name='LIVE Entry'
            ))
            # Exit
            if 'Live Exit Time' in trade_row and pd.notna(trade_row['Live Exit Time']):
                 fig.add_trace(go.Scatter(
                    x=[trade_row['Live Exit Time']], y=[trade_row['Live Exit Price']],
                    mode='markers',
                    marker=dict(symbol='x', size=12, color=color, line=dict(width=2, color='black')),
                    name='LIVE Exit'
                ))
                # Duration Line
                 fig.add_trace(go.Scatter(
                    x=[trade_row['Live Time'], trade_row['Live Exit Time']], 
                    y=[trade_row['Live Price'], trade_row['Live Exit Price']],
                    mode='lines',
                    line=dict(color=color, width=2),
                    name='LIVE Duration'
                ))

        # BT Trade
        if pd.notna(trade_row['BT Time']):
            bt_is_long = trade_row.get('BT Dir') in [1, 'LONG', 'Long', 'long']
            color = 'lime' if bt_is_long else 'magenta'
            # Entry
            fig.add_trace(go.Scatter(
                x=[trade_row['BT Time']], y=[trade_row['BT Price']],
                mode='markers',
                marker=dict(symbol='circle-open', size=15, color=color, line=dict(width=3)),
                name='BT Entry'
            ))
            # Exit
            if 'BT Exit Time' in trade_row and pd.notna(trade_row['BT Exit Time']):
                 fig.add_trace(go.Scatter(
                    x=[trade_row['BT Exit Time']], y=[trade_row['BT Exit Price']],
                    mode='markers',
                    marker=dict(symbol='circle-x-open', size=12, color=color, line=dict(width=3)),
                    name='BT Exit'
                ))
                # Duration Line
                 fig.add_trace(go.Scatter(
                    x=[trade_row['BT Time'], trade_row['BT Exit Time']], 
                    y=[trade_row['BT Price'], trade_row['BT Exit Price']],
                    mode='lines',
                    line=dict(color=color, width=2, dash='dot'),
                    name='BT Duration'
                ))
            
        title = (
            f"Trade Comparison | Status: {trade_row['Status']} | "
            f"Lag: {trade_row.get('Diff (s)', 'N')}s{bar_hint}"
        )
        fig.update_layout(
            title=dict(text=title, font=dict(size=14)), 
            height=500, 
            template='plotly_white',
            yaxis=dict(fixedrange=False, autorange=True),
            xaxis=dict(rangeslider=dict(visible=False))
        )
        
        filename = f"overlay_{center_time.strftime('%Y%m%d_%H%M%S')}.html"
        filepath = os.path.join(output_dir, filename)
        
        # Stats Preparation
        def get_dir_str(d):
            if pd.isna(d) or d == "": return "-"
            if isinstance(d, str):
                return d.upper()
            return "LONG" if d == 1 else "SHORT"
            
        def get_dir_class(d):
            if pd.isna(d) or d == "": return ""
            d_str = str(d).upper()
            if d_str == "LONG" or d == 1: return "long"
            if d_str == "SHORT" or d == -1: return "short"
            return ""

        stats_html = f"""
        <div class="stats-box">
            <h3>Trade Comparison Details</h3>
            <table>
                <tr>
                    <th>Metric</th>
                    <th>Live / Paper</th>
                    <th>Backtest (Model)</th>
                </tr>
                <tr>
                    <td><b>Direction</b></td>
                    <td class="{get_dir_class(trade_row.get('Live Dir'))}">{get_dir_str(trade_row.get('Live Dir'))}</td>
                    <td class="{get_dir_class(trade_row.get('BT Dir'))}">{get_dir_str(trade_row.get('BT Dir'))}</td>
                </tr>
                <tr>
                    <td><b>Entry Time</b></td>
                    <td>{trade_row['Live Time'].strftime('%H:%M:%S') if pd.notna(trade_row.get('Live Time')) else '-'}</td>
                    <td>{trade_row['BT Time'].strftime('%H:%M:%S') if pd.notna(trade_row.get('BT Time')) else '-'}</td>
                </tr>
                <tr>
                    <td><b>Entry Price</b></td>
                    <td>{f"{trade_row.get('Live Price', 0):.2f}" if pd.notna(trade_row.get('Live Price')) else '-'}</td>
                    <td>{f"{trade_row.get('BT Price', 0):.2f}" if pd.notna(trade_row.get('BT Price')) else '-'}</td>
                </tr>
                <tr>
                    <td><b>Exit Price</b></td>
                    <td>{f"{trade_row.get('Live Exit Price', 0):.2f}" if pd.notna(trade_row.get('Live Exit Price')) else '-'}</td>
                    <td>{f"{trade_row.get('BT Exit Price', 0):.2f}" if pd.notna(trade_row.get('BT Exit Price')) else '-'}</td>
                </tr>
                <tr>
                    <td><b>PnL</b></td>
                    <td class="{'pnl-pos' if trade_row.get('Live PnL', 0) > 0 else 'pnl-neg' if trade_row.get('Live PnL', 0) < 0 else ''}">${f"{trade_row.get('Live PnL', 0):.2f}" if pd.notna(trade_row.get('Live PnL')) else '-'}</td>
                    <td class="{'pnl-pos' if trade_row.get('BT PnL', 0) > 0 else 'pnl-neg' if trade_row.get('BT PnL', 0) < 0 else ''}">${f"{trade_row.get('BT PnL', 0):.2f}" if pd.notna(trade_row.get('BT PnL')) else '-'}</td>
                </tr>
                <tr>
                    <td><b>Duration</b></td>
                    <td>{str(trade_row.get('Live Dur', '-')).split('.')[0]}</td>
                    <td>{str(trade_row.get('BT Dur', '-')).split('.')[0]}</td>
                </tr>
                <tr>
                    <td><b>Sync Lag</b></td>
                    <td colspan="2" style="text-align:center; background:#f8f9fa;">{f"{trade_row.get('Diff (s)', 0):.1f}s" if pd.notna(trade_row.get('Diff (s)')) else 'N/A'}</td>
                </tr>
            </table>
        </div>
        """

        # Wrapped in template for "Back to Gallery" button and Stats
        plotly_div = fig.to_html(full_html=False, include_plotlyjs='cdn', config={'scrollZoom': True})
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{title}</title>
            <style>
                body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; margin: 0; background: #f8fafc; padding: 20px; }}
                .container {{ max-width: 1400px; margin: 0 auto; background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
                .back-home {{ 
                    display: inline-block; 
                    margin-bottom: 20px; 
                    padding: 8px 16px; 
                    background: #34495e; 
                    color: white; 
                    text-decoration: none; 
                    border-radius: 6px; 
                    font-size: 14px;
                    transition: background 0.2s;
                }}
                .back-home:hover {{ background: #2c3e50; }}
                .stats-box {{ margin-bottom: 20px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; background: #fff; }}
                .stats-box h3 {{ margin-top: 0; color: #1e293b; font-size: 1.1rem; border-bottom: 2px solid #f1f5f9; padding-bottom: 10px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
                th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #f1f5f9; }}
                th {{ color: #64748b; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; }}
                .long {{ color: #059669; font-weight: bold; }}
                .short {{ color: #dc2626; font-weight: bold; }}
                .pnl-pos {{ color: #059669; }}
                .pnl-neg {{ color: #dc2626; }}
            </style>
        </head>
        <body>
            <div class="container">
                <a href="index.html" class="back-home">&larr; Back to Gallery</a>
                {stats_html}
                {plotly_div}
            </div>
        </body>
        </html>
        """
        with open(filepath, "w", encoding='utf-8') as f:
            f.write(html)
        return filename
        
    except Exception as e:
        print(f"Error plotting overlay: {e}")
        return None

def generate_comparison_charts(
    csv_path="comparison_metrics_sequential.csv",
    output_dir="web/comparison_charts",
    data_path=LIVE_DATA_PATH,
    params_path=None,
    execution_log_path=None,
):
    """
    Reads comparison metrics and generates overlay charts for unmatched/matched trades.
    """
    if not os.path.exists(csv_path):
         print(f"Metrics file not found: {csv_path}")
         return
         
    os.makedirs(output_dir, exist_ok=True)
    df = pd.read_csv(csv_path)
    
    # Parse Timestamps
    df['SortTime'] = pd.to_datetime(df['SortTime'])
    if 'Live Time' in df.columns:
        df['Live Time'] = pd.to_datetime(df['Live Time'])
    if 'Live Exit Time' in df.columns:
        df['Live Exit Time'] = pd.to_datetime(df['Live Exit Time'])
    if 'BT Time' in df.columns:
        df['BT Time'] = pd.to_datetime(df['BT Time'])
    if 'BT Exit Time' in df.columns:
        df['BT Exit Time'] = pd.to_datetime(df['BT Exit Time'])
    
    # Load OHLC
    ohlc_df = load_ohlc_data(data_path)

    params_path = params_path or DEFAULT_TREND_PARAMS
    execution_log_path = execution_log_path or DEFAULT_EXECUTION_LOG
    sim_prep_df, strategy_inst = None, None
    params_dict = _load_trend_params_for_plot(params_path)
    if params_dict and ohlc_df is not None and not ohlc_df.empty:
        try:
            sim_prep_df, strategy_inst = prepare_trend_simulation_df(ohlc_df, params_dict)
        except Exception as e:
            print(f"Warning: trend sim prep for overlays failed: {e}")
    
    # Generate Aggregate Plots
    agg_fig = generate_aggregate_plots(df)
    agg_filename = "aggregate_metrics.html"
    agg_fig.write_html(os.path.join(output_dir, agg_filename), include_plotlyjs='cdn')

    # Helpers for table rendering
    def get_dir_str(d):
        if pd.isna(d) or d == "": return "-"
        if isinstance(d, str): return d.upper()
        return "LONG" if d == 1 else "SHORT"
        
    def get_dir_class(d):
        if pd.isna(d) or d == "": return ""
        d_str = str(d).upper()
        if d_str == "LONG" or d == 1: return "long"
        if d_str == "SHORT" or d == -1: return "short"
        return ""

    # HTML Header
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Trade Comparison Gallery</title>
        <style>
            body { font-family: 'Segoe UI', sans-serif; padding: 20px; background: #f0f2f5; max-width: 1600px; margin: 0 auto; }
            h1, h2 { color: #333; }
            .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(400px, 1fr)); gap: 20px; }
            .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); border: 1px solid #ddd; }
            .match { border-top: 5px solid #2ecc71; }
            .mismatch { border-top: 5px solid #e74c3c; }
            .only { border-top: 5px solid #f39c12; }
            table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.9rem; }
            th, td { padding: 8px; border-bottom: 1px solid #eee; text-align: left; }
            th { background: #f8f9fa; color: #666; }
            .btn { display: inline-block; padding: 5px 10px; background: #3498db; color: white; text-decoration: none; border-radius: 4px; margin-top: 10px; font-size: 0.8rem;}
            .btn:hover { background: #2980b9; }
            iframe { width: 100%; height: 600px; border: none; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); background: white; }
            .back-home { 
                display: inline-block; 
                margin-bottom: 20px; 
                padding: 8px 16px; 
                background: #34495e; 
                color: white; 
                text-decoration: none; 
                border-radius: 6px; 
                font-size: 14px;
                transition: background 0.2s;
            }
            .back-home:hover { background: #2c3e50; }
            .long { color: #059669; font-weight: bold; }
            .short { color: #dc2626; font-weight: bold; }
        </style>
    </head>
    <body>
        <a href="../index.html" class="back-home">&larr; Back to Home</a>
        <h1>Live vs Backtest Comparison Analysis</h1>
        <p>Generated: """ + pd.Timestamp.now().strftime('%Y-%m-%d %H:%M') + """</p>
        
        <h2>Global Metrics</h2>
        <iframe src="aggregate_metrics.html"></iframe>
        
        <h2>Trade Detail Gallery (Last 100 Trades)</h2>
        <div class="grid">
    """
    
    # Sort descending time
    df_rev = df.sort_values('SortTime', ascending=False).head(100)
    
    for _, row in df_rev.iterrows():
        status = row['Status']
        cls = 'match' if status == 'MATCHED' else 'mismatch' if 'MISMATCH' in status else 'only'
        
        # Generate Overlay Plot
        plot_link = ""
        overlay_file = generate_overlay_chart(
            row,
            ohlc_df,
            output_dir,
            sim_prep_df=sim_prep_df,
            strategy=strategy_inst,
            execution_log_path=execution_log_path,
        )
        if overlay_file:
            plot_link = f'<a href="{overlay_file}" class="btn">View Chart Overlay</a>'

        live_t_str = row['Live Time'].strftime('%H:%M:%S') if pd.notna(row['Live Time']) else '-'
        bt_t_str = row['BT Time'].strftime('%H:%M:%S') if pd.notna(row['BT Time']) else '-'
        diff_str = f"{row.get('Diff (s)', 0):.1f}s" if pd.notna(row.get('Diff (s)')) else '-'
        
        # Determine overall direction for the row (favor Live, fallback to BT)
        dir_val = row.get('Live Dir') if pd.notna(row.get('Live Dir')) else row.get('BT Dir')
        dir_label = get_dir_str(dir_val)
        dir_class = get_dir_class(dir_val)
        
        html_content += f"""
        <div class="card {cls}">
            <h3>{status} <span style="float:right; font-size:0.8em; color:#888">{row['SortTime'].strftime('%Y-%m-%d')}</span></h3>
            <table>
                <tr>
                    <th>Metric</th><th>Live</th><th>Backtest</th>
                </tr>
                <tr>
                    <td>Direction</td><td class="{dir_class}">{dir_label}</td><td class="{get_dir_class(row.get('BT Dir'))}">{get_dir_str(row.get('BT Dir'))}</td>
                </tr>
                <tr>
                    <td>Time</td><td>{live_t_str}</td><td>{bt_t_str}</td>
                </tr>
                <tr>
                    <td>Lag</td><td colspan="2" style="text-align:center">{diff_str}</td>
                </tr>
                <tr>
                    <td>Price</td><td>{row.get('Live Price', '-')}</td><td>{row.get('BT Price', '-')}</td>
                </tr>
                <tr>
                    <td>PnL</td><td>{row.get('Live PnL', '-')}</td><td>{row.get('BT PnL', '-')}</td>
                </tr>
                <tr>
                    <td>Duration</td><td>{str(row.get('Live Dur', '-')).split('.')[0]}</td><td>{str(row.get('BT Dur', '-')).split('.')[0]}</td>
                </tr>
            </table>
            {plot_link}
        </div>
        """
        
    html_content += "</div></body></html>"
    
    with open(os.path.join(output_dir, "index.html"), "w", encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"Comparison gallery generated at {output_dir}/index.html")

if __name__ == "__main__":
    generate_comparison_charts()

"""
core/monitoring.py - Bar Processing, Indicator Updates, and Data Recording
Ported from ib_deployment_v4.py lines 1735-2095
Made strategy-agnostic to support Bollinger, Trend, and future strategies.
"""
import asyncio
import os
import json
import logging
import re
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
import pytz
from typing import Any, Dict, List, Optional, Set, Tuple

# Rolling 1-min window kept in memory by IB keepUpToDate + seed_data_ref_from_bars.
PAPER_WARMUP_MAX_BARS = 15000

_ONEMIN_BAR_LOG_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ \w+ "
    r"\[1-min bar\] \[NEW\] (\d{2}:\d{2}:\d{2}).*?"
    r"O: ([\d.]+) H: ([\d.]+) L: ([\d.]+) C: ([\d.]+) \| Vol: ([\d,]+)"
)

from core.account import add_to_live_tracker
from core.execution import check_entries, check_exits

# Async bar pipeline: IB calls on_bar_update_handler synchronously; enqueue OHLCV snapshots so the
# asyncio loop can run dashboard writes and IB I/O while pandas/strategy work runs in a consumer.
BAR_PIPELINE_QUEUE: Optional[asyncio.Queue] = None
BAR_PIPELINE_CTX: Optional[Dict[str, Any]] = None


def configure_bar_pipeline(queue: asyncio.Queue, ctx: Dict[str, Any]) -> None:
    global BAR_PIPELINE_QUEUE, BAR_PIPELINE_CTX
    BAR_PIPELINE_QUEUE = queue
    BAR_PIPELINE_CTX = ctx


def seed_data_ref_from_bars(
    bars_obj,
    data_ref: Dict[str, Any],
    max_bars: int = PAPER_WARMUP_MAX_BARS,
    output_dir: Optional[str] = None,
) -> bool:
    """Populate data_ref immediately after IB historical subscribe (before async bar pipeline runs)."""
    if bars_obj is None or len(bars_obj) == 0:
        return False
    try:
        snap = [
            (b.date, b.open, b.high, b.low, b.close, b.volume)
            for b in list(bars_obj)[-int(max_bars):]
        ]
        df = pd.DataFrame(
            snap, columns=["datetime", "open", "high", "low", "close", "volume"]
        )
        if df.empty:
            return False
        df["datetime"] = pd.to_datetime(df["datetime"]).dt.tz_convert("US/Eastern")
        df.set_index("datetime", inplace=True)
        data_ref["data"] = df[["open", "high", "low", "close", "volume"]].copy()
        if output_dir:
            persist_live_1min_bars(output_dir, data_ref["data"], max_bars=max_bars)
        return True
    except Exception as e:
        logging.warning("seed_data_ref_from_bars failed: %s", e)
        return False


async def _async_process_bar_snapshot(
    snap: List[Tuple[Any, float, float, float, float, float]],
    has_new: bool,
    ctx: Dict[str, Any],
) -> None:
    strategy = ctx["strategy"]
    ib = ctx["ib"]
    contract = ctx["contract"]
    data_ref = ctx["data_ref"]
    positions = ctx["positions"]
    completed_trades = ctx["completed_trades"]
    live_tracker = ctx["live_tracker"]
    bar_log = ctx["bar_log"]
    dashboard_state = ctx.get("dashboard_state")
    send_email_fn = ctx["send_email_fn"]
    output_dir = ctx["output_dir"]

    await asyncio.sleep(0)
    try:
        df = pd.DataFrame(
            snap, columns=["datetime", "open", "high", "low", "close", "volume"]
        )
        if df.empty:
            return

        df["datetime"] = pd.to_datetime(df["datetime"]).dt.tz_convert("US/Eastern")
        df.set_index("datetime", inplace=True)
        data = df[["open", "high", "low", "close", "volume"]].copy()
        data_ref["data"] = data
        if has_new and output_dir:
            persist_live_1min_bars(output_dir, data)

        bar_time = data.index[-1]
        latest_row = data.iloc[-1]

        current_time = datetime.now(pytz.timezone("US/Eastern"))
        delay = (current_time - bar_time).total_seconds()
        delay_tag = " [LIVE]" if delay < 10 else (" [DELAYED]" if delay > 900 else "")

        update_type = " [NEW]" if has_new else " [UPD]"
        log_msg = (
            f"[1-min bar]{update_type} {bar_time.strftime('%H:%M:%S')}{delay_tag} | "
            f"O: {latest_row['open']:.2f} H: {latest_row['high']:.2f} "
            f"L: {latest_row['low']:.2f} C: {latest_row['close']:.2f} | "
            f"Vol: {latest_row['volume']:,.0f}"
        )
        if has_new:
            logging.info(log_msg)
        else:
            logging.debug(log_msg)

        if dashboard_state:
            dashboard_state.current_price = latest_row["close"]

        should_check = False
        if strategy.timeframe == 1:
            should_check = has_new
        elif strategy.timeframe > 1 and has_new:
            total_min = bar_time.hour * 60 + bar_time.minute
            should_check = total_min % strategy.timeframe == 0

        await asyncio.sleep(0)
        update_indicators(strategy, data)

        min_bars = strategy.min_bars_required

        await asyncio.sleep(0)
        if should_check and len(data) >= 2:
            resampled_df = resample_data(data, strategy.timeframe)
            if len(resampled_df) < 2:
                return

            resampled_ind = strategy.calculate_indicators(resampled_df.copy())
            try:
                resampled_filt = strategy.apply_filters(resampled_ind)
            except Exception:
                resampled_filt = resampled_ind

            completed_idx = resampled_filt.index[-2]
            completed_row = resampled_filt.iloc[-2]

            bar_info = (
                f"[{strategy.timeframe}-min] {completed_idx.strftime('%H:%M:%S')} | "
                f"O: {completed_row.get('open', 0):.2f} H: {completed_row.get('high', 0):.2f} "
                f"L: {completed_row.get('low', 0):.2f} C: {completed_row.get('close', 0):.2f} | "
                f"Vol: {completed_row.get('volume', 0):,.0f}"
            )
            logging.info(bar_info)

            # Record bar history before entry/exit work so a trading exception cannot
            # freeze the dashboard bar log while the live chart keeps updating.
            bar_log.append({
                "timestamp": completed_idx.strftime("%H:%M:%S"),
                "bar_info": bar_info,
                "entry_criteria": "",
            })
            if len(bar_log) > 20:
                del bar_log[:-20]

            entry_criteria = ""
            if _indicators_ready(data):
                try:
                    entry_criteria = log_entry_criteria_status(
                        strategy, positions, completed_row, resampled_filt, output_dir=output_dir
                    )
                    save_live_data_row(output_dir, completed_idx, completed_row, resampled_filt)
                    check_entries(
                        strategy, ib, contract, data, positions, {},
                        live_tracker, dashboard_state, send_email_fn, completed_idx, completed_row
                    )
                    check_exits(
                        strategy, ib, contract, data, positions, completed_trades,
                        live_tracker, send_email_fn, completed_idx, completed_row,
                        allow_strategy_exit=True
                    )
                    append_open_trade_timeline(output_dir, completed_idx, completed_row, positions)
                except Exception as e:
                    logging.error(
                        "Bar %s: entry/exit processing failed (bar log still recorded): %s",
                        completed_idx,
                        e,
                        exc_info=True,
                    )
            if bar_log:
                bar_log[-1]["entry_criteria"] = entry_criteria

        await asyncio.sleep(0)
        if len(data) >= min_bars and _indicators_ready(data):
            # Phase 1: monitor-only on 1-min ticks (fills, RTH, PreSubmitted); no trail ratchet.
            check_exits(
                strategy, ib, contract, data, positions, completed_trades,
                live_tracker, send_email_fn, data.index[-1], data.iloc[-1],
                allow_strategy_exit=False,
                skip_trailing=True,
            )
            if has_new and positions:
                append_open_trade_timeline(output_dir, data.index[-1], data.iloc[-1], positions)

    except Exception as e:
        bar_time_str = "unknown"
        try:
            bar_time_str = snap[-1][0].strftime("%H:%M:%S")
        except Exception:
            pass
        logging.error(
            f"Error in on_bar_update at {bar_time_str}: {type(e).__name__}: {e}",
            exc_info=True,
        )


def _sync_on_bar_update_legacy(
    snap, has_new, *, strategy, ib, contract, data_ref,
    positions, completed_trades, live_tracker, bar_log,
    dashboard_state, send_email_fn, output_dir, last_data_receipt,
):
    try:
        df = pd.DataFrame(
            snap, columns=["datetime", "open", "high", "low", "close", "volume"]
        )
        if df.empty:
            return

        df["datetime"] = pd.to_datetime(df["datetime"]).dt.tz_convert("US/Eastern")
        df.set_index("datetime", inplace=True)
        data = df[["open", "high", "low", "close", "volume"]].copy()
        data_ref["data"] = data
        if has_new and output_dir:
            persist_live_1min_bars(output_dir, data)

        bar_time = data.index[-1]
        latest_row = data.iloc[-1]

        current_time = datetime.now(pytz.timezone("US/Eastern"))
        delay = (current_time - bar_time).total_seconds()
        delay_tag = " [LIVE]" if delay < 10 else (" [DELAYED]" if delay > 900 else "")

        update_type = " [NEW]" if has_new else " [UPD]"
        log_msg = (
            f"[1-min bar]{update_type} {bar_time.strftime('%H:%M:%S')}{delay_tag} | "
            f"O: {latest_row['open']:.2f} H: {latest_row['high']:.2f} "
            f"L: {latest_row['low']:.2f} C: {latest_row['close']:.2f} | "
            f"Vol: {latest_row['volume']:,.0f}"
        )
        if has_new:
            logging.info(log_msg)
        else:
            logging.debug(log_msg)

        if dashboard_state:
            dashboard_state.current_price = latest_row["close"]

        should_check = False
        if strategy.timeframe == 1:
            should_check = has_new
        elif strategy.timeframe > 1 and has_new:
            total_min = bar_time.hour * 60 + bar_time.minute
            should_check = total_min % strategy.timeframe == 0

        update_indicators(strategy, data)

        min_bars = strategy.min_bars_required

        if should_check and len(data) >= 2:
            resampled_df = resample_data(data, strategy.timeframe)
            if len(resampled_df) < 2:
                return

            resampled_ind = strategy.calculate_indicators(resampled_df.copy())
            try:
                resampled_filt = strategy.apply_filters(resampled_ind)
            except Exception:
                resampled_filt = resampled_ind

            completed_idx = resampled_filt.index[-2]
            completed_row = resampled_filt.iloc[-2]

            bar_info = (
                f"[{strategy.timeframe}-min] {completed_idx.strftime('%H:%M:%S')} | "
                f"O: {completed_row.get('open', 0):.2f} H: {completed_row.get('high', 0):.2f} "
                f"L: {completed_row.get('low', 0):.2f} C: {completed_row.get('close', 0):.2f} | "
                f"Vol: {completed_row.get('volume', 0):,.0f}"
            )
            logging.info(bar_info)

            bar_log.append({
                "timestamp": completed_idx.strftime("%H:%M:%S"),
                "bar_info": bar_info,
                "entry_criteria": "",
            })
            if len(bar_log) > 20:
                del bar_log[:-20]

            entry_criteria = ""
            if _indicators_ready(data):
                try:
                    entry_criteria = log_entry_criteria_status(
                        strategy, positions, completed_row, resampled_filt, output_dir=output_dir
                    )
                    save_live_data_row(output_dir, completed_idx, completed_row, resampled_filt)
                    check_entries(
                        strategy, ib, contract, data, positions, {},
                        live_tracker, dashboard_state, send_email_fn, completed_idx, completed_row
                    )
                    check_exits(
                        strategy, ib, contract, data, positions, completed_trades,
                        live_tracker, send_email_fn, completed_idx, completed_row,
                        allow_strategy_exit=True
                    )
                    append_open_trade_timeline(output_dir, completed_idx, completed_row, positions)
                except Exception as e:
                    logging.error(
                        "Bar %s: entry/exit processing failed (bar log still recorded): %s",
                        completed_idx,
                        e,
                        exc_info=True,
                    )
            if bar_log:
                bar_log[-1]["entry_criteria"] = entry_criteria

        if len(data) >= min_bars and _indicators_ready(data):
            # Phase 1: monitor-only on 1-min ticks (fills, RTH, PreSubmitted); no trail ratchet.
            check_exits(
                strategy, ib, contract, data, positions, completed_trades,
                live_tracker, send_email_fn, data.index[-1], data.iloc[-1],
                allow_strategy_exit=False,
                skip_trailing=True,
            )
            if has_new and positions:
                append_open_trade_timeline(output_dir, data.index[-1], data.iloc[-1], positions)

    except Exception as e:
        bar_time_str = "unknown"
        try:
            bar_time_str = snap[-1][0].strftime("%H:%M:%S")
        except Exception:
            pass
        logging.error(
            f"Error in on_bar_update at {bar_time_str}: {type(e).__name__}: {e}",
            exc_info=True,
        )


async def bar_pipeline_consumer() -> None:
    if BAR_PIPELINE_QUEUE is None or BAR_PIPELINE_CTX is None:
        logging.error("bar_pipeline_consumer started without configure_bar_pipeline")
        return
    while True:
        job = await BAR_PIPELINE_QUEUE.get()
        try:
            snap, has_new = job
            await _async_process_bar_snapshot(snap, has_new, BAR_PIPELINE_CTX)
        except Exception as e:
            logging.error("Bar pipeline consumer error: %s", e, exc_info=True)
        finally:
            BAR_PIPELINE_QUEUE.task_done()


def resample_data(df, timeframe_mins):
    """
    Resample 1-minute OHLCV data into arbitrary minute timeframe.
    Args:
        df: 1-minute DataFrame with datetime index.
        timeframe_mins: Target timeframe in minutes.
    Returns:
        DataFrame resampled and aggregated correctly.
    """
    if timeframe_mins <= 1:
        return df.copy()

    # Rule: Sum volume, first open, max high, min low, last close
    logic = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }

    # Use closed='right', label='right' to match IB bar behavior (e.g. 10:00 bar contains 09:30-10:00)
    resampled = df.resample(f'{timeframe_mins}min', closed='right', label='right').agg(logic)
    return resampled.dropna()


def median_bar_spacing_minutes(index) -> float:
    """Median minutes between consecutive index timestamps (ignores zero deltas)."""
    if len(index) < 2:
        return 1.0
    deltas = pd.Series(index).diff().dropna()
    deltas = deltas[deltas > pd.Timedelta(0)]
    if deltas.empty:
        return 1.0
    return float(deltas.dt.total_seconds().median() / 60.0)


def is_htf_native_ohlcv(df, timeframe_mins: int, tolerance: float = 0.35) -> bool:
    """
    True when OHLCV rows are already strategy-timeframe bars (e.g. live_data.csv HTF log).

    Uses the fraction of inter-row gaps near ``timeframe_mins`` (not median alone) so mixed
    history files with duplicate 1–2m writes still qualify when most gaps match TF.
    """
    if timeframe_mins <= 1 or df is None or len(df) < 3:
        return False
    deltas = pd.Series(df.index).diff().dropna()
    deltas = deltas[deltas > pd.Timedelta(0)]
    if deltas.empty:
        return False
    mins = deltas.dt.total_seconds() / 60.0
    lo = timeframe_mins * (1.0 - tolerance)
    hi = timeframe_mins * (1.0 + tolerance)
    near_tf = ((mins >= lo) & (mins <= hi)).mean()
    if near_tf >= 0.45:
        return True
    if (mins < 1.5).mean() >= 0.45:
        return False
    return median_bar_spacing_minutes(df.index) >= timeframe_mins * (1.0 - tolerance)


def prepare_strategy_ohlcv(df, timeframe_mins: int, *, assume_htf_native: bool = False):
    """
    Build strategy-timeframe OHLCV with live-parity resample rules.

    Returns ``(ohlcv_df, is_htf_native)``. When input is HTF-native (``live_data.csv`` rows
    from ``save_live_data_row``), pass ``assume_htf_native=True`` or rely on gap detection —
    rows are **not** re-aggregated (double-resample shifts bar labels).
    """
    base = ["open", "high", "low", "close", "volume"]
    cols = [c for c in base if c in df.columns]
    out = df[cols].copy().sort_index()
    out = out[~out.index.duplicated(keep="last")]
    if timeframe_mins <= 1:
        return out, False
    if assume_htf_native or is_htf_native_ohlcv(out, timeframe_mins):
        return out, True
    return resample_data(out, timeframe_mins), False


def normalize_ohlcv_index(df: pd.DataFrame) -> pd.DataFrame:
    """Load paper OHLCV CSV to ET-naive DatetimeIndex with lowercase columns."""
    out = df.copy()
    out.columns = [str(c).lower().strip() for c in out.columns]
    ohlcv_cols = ["open", "high", "low", "close", "volume"]
    out = out[[c for c in ohlcv_cols if c in out.columns]]
    out = out.dropna(subset=ohlcv_cols)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.index = pd.to_datetime(out.index, utc=True)
    out.index = out.index.tz_convert("US/Eastern").tz_localize(None)
    return out


def extract_one_minute_ohlcv(df: pd.DataFrame, spacing_tolerance: float = 0.35) -> pd.DataFrame:
    """
    Keep rows from a mixed-interval CSV that belong to ~1-minute spacing.
    Drops HTF rows appended by save_live_data_row (13/14-min gaps).
    """
    if df.empty or len(df) < 2:
        return df
    out = normalize_ohlcv_index(df)
    mins = out.index.to_series().diff().dt.total_seconds().div(60.0)
    keep = mins.isna() | (mins <= 1.0 + spacing_tolerance)
    # Also keep first row after a gap if prior gap was HTF-sized (session resume).
    return out.loc[keep]


def persist_live_1min_bars(
    output_dir: str,
    df_1min: pd.DataFrame,
    max_bars: int = PAPER_WARMUP_MAX_BARS,
) -> None:
    """Write rolling 1-min OHLCV window for paper/backtest parity (matches data_ref)."""
    if not output_dir or df_1min is None or df_1min.empty:
        return
    try:
        os.makedirs(output_dir, exist_ok=True)
        csv_path = os.path.join(output_dir, "live_1min.csv")
        snap = normalize_ohlcv_index(df_1min)
        if len(snap) > int(max_bars):
            snap = snap.iloc[-int(max_bars):]
        if os.path.isfile(csv_path):
            try:
                existing = normalize_ohlcv_index(
                    pd.read_csv(csv_path, index_col=0, parse_dates=True)
                )
                snap = pd.concat([existing, snap]).sort_index()
                snap = snap[~snap.index.duplicated(keep="last")]
                if len(snap) > int(max_bars):
                    snap = snap.iloc[-int(max_bars):]
            except Exception:
                pass
        snap.to_csv(csv_path)
    except Exception as e:
        logging.warning("persist_live_1min_bars failed: %s", e)


def parse_1min_bars_from_execution_log(
    log_path: str,
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """Recover 1-min OHLCV rows logged by the paper bot ([1-min bar] [NEW] lines)."""
    if not log_path or not os.path.isfile(log_path):
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    start = pd.Timestamp(start) if start is not None else None
    end = pd.Timestamp(end) if end is not None else None
    rows: List[Tuple[pd.Timestamp, float, float, float, float, float]] = []
    current_date: Optional[datetime.date] = None
    with open(log_path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if "[1-min bar] [NEW]" not in line:
                continue
            head = line[:10]
            if len(head) >= 10 and head[4] == "-" and head[7] == "-":
                try:
                    current_date = datetime.strptime(head, "%Y-%m-%d").date()
                except ValueError:
                    continue
            m = _ONEMIN_BAR_LOG_RE.search(line)
            if not m or current_date is None:
                continue
            hh, mm, ss = m.group(1).split(":")
            ts = pd.Timestamp.combine(
                current_date,
                time(int(hh), int(mm), int(ss)),
            )
            if start is not None and ts < start:
                continue
            if end is not None and ts > end:
                continue
            rows.append(
                (
                    ts,
                    float(m.group(2)),
                    float(m.group(3)),
                    float(m.group(4)),
                    float(m.group(5)),
                    float(m.group(6).replace(",", "")),
                )
            )
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    idx, o, h, l, c, v = zip(*rows)
    return pd.DataFrame(
        {"open": o, "high": h, "low": l, "close": c, "volume": v},
        index=pd.DatetimeIndex(idx),
    ).sort_index()


def load_paper_1min_ohlcv(
    path_1min: str,
    *,
    execution_log: Optional[str] = None,
    log_start: Optional[pd.Timestamp] = None,
    log_end: Optional[pd.Timestamp] = None,
    legacy_htf_path: Optional[str] = None,
) -> pd.DataFrame:
    """
    Merge 1-min sources for paper/backtest parity: persisted live_1min.csv,
    execution-log recovery, and (last resort) ~1-min rows extracted from live_data.csv.
    """
    frames: List[pd.DataFrame] = []
    if path_1min and os.path.isfile(path_1min):
        frames.append(normalize_ohlcv_index(pd.read_csv(path_1min, index_col=0, parse_dates=True)))
    if execution_log:
        log_df = parse_1min_bars_from_execution_log(execution_log, log_start, log_end)
        if not log_df.empty:
            frames.append(log_df)
    if not frames and legacy_htf_path and os.path.isfile(legacy_htf_path):
        legacy = pd.read_csv(legacy_htf_path, index_col=0, parse_dates=True)
        one_m = extract_one_minute_ohlcv(legacy)
        if not one_m.empty:
            logging.warning(
                "Using ~1-min rows extracted from %s (HTF log fallback; prefer live_1min.csv)",
                legacy_htf_path,
            )
            frames.append(one_m)
    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    out = pd.concat(frames).sort_index()
    return out[~out.index.duplicated(keep="last")]


def _parse_hhmm_policy(s) -> time:
    s = str(s).strip() if s is not None else ""
    if not s:
        return time(17, 30)
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return pd.to_datetime(s, format=fmt).time()
        except ValueError:
            continue
    return pd.to_datetime(s).time()


def _et_session_pad_end_time(strategy) -> time:
    base_date = datetime(2000, 1, 1).date()
    me = _parse_hhmm_policy(getattr(strategy, "daily_maintenance_end_str", "17:30"))
    end_dt = pd.Timestamp.combine(base_date, me)
    with_post_buf = end_dt + timedelta(minutes=int(strategy.maintenance_buffer_minutes))
    floor_eth = datetime.strptime("18:00", "%H:%M").time()
    return max(with_post_buf.time(), floor_eth)


def pad_htf_for_session_force_exits(
    df_ohlcv: pd.DataFrame,
    strategy,
    restrict_dates: Optional[Set] = None,
):
    """Insert synthetic HTF rows for intra-day gaps / session tail (force-exit parity)."""
    if df_ohlcv.empty:
        return df_ohlcv
    tf = max(1, int(getattr(strategy, "timeframe", 1) or 1))
    pad_end_time = _et_session_pad_end_time(strategy)
    df = df_ohlcv.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    orig_len = len(df)
    step = pd.Timedelta(minutes=tf)
    gap_threshold = step * 1.5
    existing = set(df.index)

    def synth_from(base: pd.Series) -> pd.Series:
        p = base.copy()
        p["volume"] = 0.0
        return p

    inserts = []
    idx_list = list(df.index)
    for i in range(len(idx_list) - 1):
        a, b = idx_list[i], idx_list[i + 1]
        if a.date() != b.date():
            continue
        if restrict_dates is not None and a.date() not in restrict_dates:
            continue
        if (b - a) <= gap_threshold:
            continue
        base = df.loc[a]
        t = a + step
        while t < b:
            if t not in existing:
                inserts.append((t, synth_from(base)))
                existing.add(t)
            t = t + step

    for day in sorted(set(df.index.date)):
        if restrict_dates is not None and day not in restrict_dates:
            continue
        sub = df[df.index.date == day]
        last_ts = sub.index[-1]
        last_row = sub.iloc[-1]
        target_close = pd.Timestamp.combine(pd.Timestamp(day).date(), pad_end_time)
        if last_ts >= target_close:
            continue
        t = last_ts + step
        while t <= target_close:
            if t not in existing:
                inserts.append((t, synth_from(last_row)))
                existing.add(t)
            t = t + step

    if not inserts:
        return df

    extra = pd.DataFrame([r for _, r in inserts], index=[ts for ts, _ in inserts])
    out = pd.concat([df, extra]).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    logging.info(
        "Padded %s synthetic HTF rows (%sm) through %s ET for force-exit parity.",
        len(out) - orig_len,
        tf,
        pad_end_time,
    )
    return out


def compute_paper_log_start(
    strategy,
    analysis_start: pd.Timestamp,
    *,
    max_bars: int = PAPER_WARMUP_MAX_BARS,
    ib_seed_days: int = 10,
) -> pd.Timestamp:
    """
    Earliest 1-min timestamp to load so HTF indicators can warm up like the live bot.

    Live seeds ~``ib_seed_days`` of 1-min bars from IB (see ``request_historical_data``)
    and also needs enough history for long SMA / Donchian lookbacks on the resampled series.
    """
    tf = max(1, int(getattr(strategy, "timeframe", 1) or 1))
    need_htf = int(getattr(strategy, "min_bars_required", 0) or 0)
    if getattr(strategy, "enable_sma_filter", False):
        need_htf = max(need_htf, int(getattr(strategy, "sma_period", 0) or 0))
    lookback_buy = int(getattr(strategy, "lookback_buy", 0) or 0)
    lookback_sell = int(getattr(strategy, "lookback_sell", 0) or 0)
    need_htf = max(need_htf, lookback_buy, lookback_sell)
    # 1-min minutes with gap cushion; capped at rolling in-memory window.
    need_1min = min(int(need_htf * tf * 1.5), int(max_bars))
    lookback_start = pd.Timestamp(analysis_start) - pd.Timedelta(minutes=need_1min + tf * 5)
    ib_start = pd.Timestamp(analysis_start) - pd.Timedelta(days=int(ib_seed_days))
    return min(lookback_start, ib_start)


def overlay_live_htf_log(
    htf: pd.DataFrame,
    live_data_path: str,
    strategy,
    dates: Optional[Set],
) -> pd.DataFrame:
    """
    Replace resampled session OHLCV with HTF rows recorded by ``save_live_data_row``.

    Resampling 1-min history produces a different bar grid than the live bot
    (phase shifts, extra bars). For paper parity, session dates must use only
    the bar labels/OHLC the bot actually traded on.
    """
    if not live_data_path or not os.path.isfile(live_data_path) or not dates:
        return htf
    tf = max(1, int(getattr(strategy, "timeframe", 1) or 1))
    try:
        raw = normalize_ohlcv_index(pd.read_csv(live_data_path, index_col=0, parse_dates=True))
    except Exception:
        return htf
    if len(raw) < 2:
        return htf
    mins = raw.index.to_series().diff().dt.total_seconds().div(60.0)
    lo, hi = tf * 0.65, tf * 1.35
    htf_like = raw[(mins.isna()) | ((mins >= lo) & (mins <= hi))]
    htf_like = htf_like[[c for c in htf_like.columns if c in {"open", "high", "low", "close", "volume"}]]
    htf_like = htf_like[htf_like.index.map(lambda t: t.date() in dates)]
    if htf_like.empty:
        return htf
    # Drop resampled rows on overlay dates; keep warmup history on prior dates only.
    keep_mask = ~htf.index.map(lambda t: t.date() in dates)
    warmup = htf.loc[keep_mask]
    out = pd.concat([warmup, htf_like]).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    logging.info(
        "Replaced session HTF with %s recorded rows from %s (%s warmup rows retained).",
        len(htf_like),
        live_data_path,
        len(warmup),
    )
    return out


def required_htf_warmup_bars(strategy) -> int:
    tf = max(1, int(getattr(strategy, "timeframe", 1) or 1))
    need = int(getattr(strategy, "min_bars_required", 0) or 0)
    if getattr(strategy, "enable_sma_filter", False):
        need = max(need, int(getattr(strategy, "sma_period", 0) or 0))
    need = max(need, int(getattr(strategy, "lookback_buy", 0) or 0))
    need = max(need, int(getattr(strategy, "lookback_sell", 0) or 0))
    return need


def prepare_paper_parity_ohlcv(
    df_1min: pd.DataFrame,
    strategy,
    *,
    end_time: Optional[pd.Timestamp] = None,
    max_bars: int = PAPER_WARMUP_MAX_BARS,
    pad_dates: Optional[Set] = None,
    htf_overlay_path: Optional[str] = None,
) -> pd.DataFrame:
    """
    Build HTF OHLCV exactly as the live paper bot: rolling 1-min window,
    resample closed=right/label=right, then optional session padding.
    """
    df = normalize_ohlcv_index(df_1min)
    if df.empty:
        return df
    if end_time is not None:
        df = df[df.index <= pd.Timestamp(end_time)]
    if len(df) > int(max_bars):
        df = df.iloc[-int(max_bars):]
    tf = max(1, int(getattr(strategy, "timeframe", 1) or 1))
    htf = resample_data(df, tf) if tf > 1 else df
    if htf_overlay_path and pad_dates:
        htf = overlay_live_htf_log(htf, htf_overlay_path, strategy, pad_dates)
    # Session bars from live_data.csv are authoritative; skip synthetic gap padding.
    if pad_dates and tf > 1 and not htf_overlay_path:
        htf = pad_htf_for_session_force_exits(htf, strategy, restrict_dates=pad_dates)
    return htf


def parse_paper_bot_active_ranges(
    execution_log_path: str,
    *,
    dates: Optional[Set] = None,
    end_time: Optional[pd.Timestamp] = None,
) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
    """
    Parse windows when the paper bot had an IB market-data subscription.

    A window opens on ``Subscribed to market data`` and closes on ``Disconnecting``.
    Re-subscribes while already connected extend the same window (refresh).
    """
    import re

    if not execution_log_path or not os.path.isfile(execution_log_path):
        return []
    sub_re = re.compile(
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO Subscribed to market data"
    )
    down_re = re.compile(
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO Disconnecting"
    )
    ranges: List[Tuple[pd.Timestamp, pd.Timestamp]] = []
    open_start: Optional[pd.Timestamp] = None
    last_ts: Optional[pd.Timestamp] = None
    try:
        with open(execution_log_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = sub_re.search(line)
                if m:
                    ts = pd.Timestamp(m.group(1))
                    last_ts = ts
                    if open_start is None:
                        open_start = ts
                    continue
                m = down_re.search(line)
                if m and open_start is not None:
                    ts = pd.Timestamp(m.group(1))
                    last_ts = ts
                    if ts >= open_start:
                        ranges.append((open_start, ts))
                    open_start = None
        if open_start is not None:
            end = pd.Timestamp(end_time) if end_time is not None else last_ts
            if end is None:
                end = open_start + pd.Timedelta(hours=24)
            elif end.date() == open_start.date() and end < open_start:
                end = pd.Timestamp.combine(
                    open_start.date(), pd.Timestamp("23:59:59").time()
                )
            ranges.append((open_start, end))
    except OSError:
        return []

    ranges = merge_timestamp_ranges(ranges)
    ranges = merge_short_active_gaps(ranges, max_gap_seconds=300)
    if dates is None:
        return ranges

    day_start = min(pd.Timestamp(d) for d in dates)
    day_end = max(pd.Timestamp(d) for d in dates) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    clipped: List[Tuple[pd.Timestamp, pd.Timestamp]] = []
    for start, end in ranges:
        overlap_start = max(start, day_start)
        overlap_end = min(end, day_end)
        if overlap_start <= overlap_end:
            clipped.append((overlap_start, overlap_end))
    return merge_timestamp_ranges(clipped)


def merge_short_active_gaps(
    ranges: List[Tuple[pd.Timestamp, pd.Timestamp]],
    *,
    max_gap_seconds: float = 300.0,
) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
    """Merge connect windows separated only by brief maintenance/API blips."""
    merged = merge_timestamp_ranges(ranges)
    if len(merged) < 2:
        return merged
    out: List[Tuple[pd.Timestamp, pd.Timestamp]] = [merged[0]]
    for start, end in merged[1:]:
        gap = (start - out[-1][1]).total_seconds()
        if gap <= max_gap_seconds:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def merge_timestamp_ranges(
    ranges: List[Tuple[pd.Timestamp, pd.Timestamp]],
) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
    """Merge overlapping/adjacent (start, end) windows."""
    if not ranges:
        return []
    merged: List[Tuple[pd.Timestamp, pd.Timestamp]] = []
    for start, end in sorted(ranges, key=lambda x: x[0]):
        start = pd.Timestamp(start)
        end = pd.Timestamp(end)
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def read_live_data_csv(live_data_path: str) -> pd.DataFrame:
    """
    Load ``live_data.csv`` with dynamic columns (header grows as indicators are added).

    Rows written after the header was created may contain extra fields; assign
    known trend indicator names to trailing columns.
    """
    import csv

    if not live_data_path or not os.path.isfile(live_data_path):
        return pd.DataFrame()

    trend_extra = [
        "donchian_high",
        "donchian_low",
        "donchian_exit_high",
        "donchian_exit_low",
        "atr",
        "sma_regime",
        "rsi",
        "vwap",
    ]

    with open(live_data_path, "r", encoding="utf-8", errors="replace") as fh:
        reader = csv.reader(fh)
        header = [str(c).lower().strip() for c in next(reader)]
        rows = list(reader)

    orig_len = len(header)
    max_len = max(orig_len, max((len(r) for r in rows), default=orig_len))
    while len(header) < max_len:
        extra_idx = len(header) - orig_len
        if extra_idx < len(trend_extra):
            header.append(trend_extra[extra_idx])
        else:
            header.append(f"extra_{len(header)}")

    records = []
    index = []
    for row in rows:
        if not row:
            continue
        padded = row + [""] * (len(header) - len(row))
        index.append(padded[0])
        records.append(padded[1 : len(header)])

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records, columns=header[1:], index=index)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("US/Eastern").tz_localize(None)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="ignore")
    return df


def load_paper_compare_htf(
    live_data_path: str,
    strategy,
    analysis_start: pd.Timestamp,
    analysis_end: pd.Timestamp,
    *,
    df_1min: Optional[pd.DataFrame] = None,
    execution_log_path: Optional[str] = None,
) -> pd.DataFrame:
    """
    HTF series for paper vs backtest compare: recorded live bar labels/OHLC only.

    Uses ``live_data.csv`` (``save_live_data_row`` output) so the backtest bar grid
    matches the bot — resampling ``live_1min.csv`` alone can shift bar phases.

    When ``df_1min`` and ``execution_log_path`` are supplied, indicator warmup uses
    the IB seed window at first ``Subscribed to market data`` (same depth as live),
    then session OHLC from ``live_data.csv`` from connect time onward.
    """
    if not live_data_path or not os.path.isfile(live_data_path):
        return pd.DataFrame()
    tf = max(1, int(getattr(strategy, "timeframe", 1) or 1))
    try:
        raw = read_live_data_csv(live_data_path)
    except Exception:
        return pd.DataFrame()
    if raw.empty:
        return pd.DataFrame()
    ohlcv_cols = ["open", "high", "low", "close", "volume"]
    raw = raw.dropna(subset=[c for c in ohlcv_cols if c in raw.columns], how="any")
    raw = raw[~raw.index.duplicated(keep="last")].sort_index()
    if tf <= 1:
        htf = raw
    else:
        mins = raw.index.to_series().diff().dt.total_seconds().div(60.0)
        lo, hi = tf * 0.65, tf * 1.35
        htf = raw[(mins.isna()) | ((mins >= lo) & (mins <= hi))]

    start = pd.Timestamp(analysis_start)
    end = pd.Timestamp(analysis_end)
    need = required_htf_warmup_bars(strategy)

    connect_series = _parse_subscribe_seed_counts(execution_log_path) if execution_log_path else {}
    if df_1min is not None and not df_1min.empty and connect_series:
        df1 = normalize_ohlcv_index(df_1min)
        frames = []
        for day in sorted({d.date() for d in pd.date_range(start.normalize(), end.normalize(), freq="D")}):
            day_ts = pd.Timestamp(day)
            sess = htf[htf.index.date == day]
            if sess.empty:
                continue
            connect = connect_series.get(day)
            if connect is not None:
                connect_ts, seed_n = connect
                warm_htf = ib_htf_seed_at_subscribe(
                    df1, connect_ts, timeframe=tf, seed_n=int(seed_n),
                )
                sess = sess[sess.index >= connect_ts.floor("min")]
                frames.append(pd.concat([warm_htf, sess[ohlcv_cols]]))
            else:
                frames.append(sess[ohlcv_cols])
        if frames:
            prior = pd.concat(frames).sort_index()
            prior = prior[~prior.index.duplicated(keep="last")]
        else:
            prior = htf[htf.index <= end]
    else:
        prior = htf[htf.index <= end]

    idx_end = prior.index.searchsorted(end, side="right")
    slice_end = prior.iloc[:idx_end] if idx_end else prior
    if len(slice_end) <= need:
        out = slice_end
    else:
        session = slice_end[slice_end.index >= start]
        pre = slice_end[slice_end.index < start]
        if len(pre) >= need:
            pre = pre.iloc[-need:]
        out = pd.concat([pre, session]).sort_index()
    return out[~out.index.duplicated(keep="last")]


def ib_htf_seed_at_subscribe(
    df_1min: pd.DataFrame,
    connect_ts: pd.Timestamp,
    *,
    timeframe: int,
    seed_n: int,
    max_bars: int = PAPER_WARMUP_MAX_BARS,
) -> pd.DataFrame:
    """
    HTF bars implied by IB 1-min seed at subscribe (matches live ``data_ref``).

    Includes connect-day bars **before** ``connect_ts`` so session VWAP and other
    intraday cumulative indicators match the live bot after reconnect.
    """
    ohlcv = ["open", "high", "low", "close", "volume"]
    connect_ts = pd.Timestamp(connect_ts)
    day = connect_ts.date()
    df1 = normalize_ohlcv_index(df_1min).sort_index()
    if df1.empty:
        return pd.DataFrame(columns=ohlcv)
    n = int(seed_n) if seed_n else int(max_bars)
    warm_1m = df1[df1.index <= connect_ts].iloc[-n:]
    if warm_1m.empty:
        return pd.DataFrame(columns=ohlcv)
    tf = max(1, int(timeframe))
    warm_htf = resample_data(warm_1m, tf) if tf > 1 else warm_1m
    prior = warm_htf[warm_htf.index.date < day]
    same_day = warm_htf[
        (warm_htf.index.date == day) & (warm_htf.index <= connect_ts)
    ]
    if prior.empty and same_day.empty:
        return pd.DataFrame(columns=ohlcv)
    out = pd.concat([prior, same_day]).sort_index()
    return out[~out.index.duplicated(keep="last")][ohlcv]


def _parse_subscribe_seed_counts(execution_log_path: str) -> Dict:
    """Map session date -> (first_subscribe_ts, ib_bar_count) from execution log."""
    import re

    if not execution_log_path or not os.path.isfile(execution_log_path):
        return {}
    sub_re = re.compile(
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO Subscribed to market data \((\d+) bars\)"
    )
    out: Dict = {}
    try:
        with open(execution_log_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = sub_re.search(line)
                if not m:
                    continue
                ts = pd.Timestamp(m.group(1))
                day = ts.date()
                if day not in out:
                    out[day] = (ts, int(m.group(2)))
    except OSError:
        return {}
    return out


def resample_mask_to_htf(mask, timeframe_mins: int, htf_index):
    """Align a 1m boolean mask to HTF bar index (same closed/label as ``resample_data``)."""
    if timeframe_mins <= 1:
        return mask
    aligned = (
        mask.astype(bool)
        .resample(f"{timeframe_mins}min", closed="right", label="right")
        .max()
        .fillna(False)
    )
    return aligned.reindex(htf_index).fillna(False).astype(bool)


def _indicators_ready(data):
    """Check if indicators have been calculated (strategy-agnostic).
    Returns True if the data has any indicator columns beyond OHLCV.
    """
    base_cols = {'open', 'high', 'low', 'close', 'volume'}
    indicator_cols = set(data.columns) - base_cols
    return len(indicator_cols) > 0


def update_indicators(strategy, data):
    """Update indicators and filters on the global data DataFrame.
    Handles resampling correctly — prevents stale force_exit values across day boundaries.
    Fixed: Now supports higher timeframes by resampling before calculation.
    """
    timeframe = getattr(strategy, 'timeframe', 1)
    min_bars = strategy.min_bars_required
    
    if len(data) < min_bars:
        return

    # 1. Prepare Data for Calculation
    if timeframe > 1:
        # Resample for HTF calculation
        data_to_calc = resample_data(data, timeframe)
    else:
        data_to_calc = data.copy()

    if len(data_to_calc) < 2: # Need at least some history
        return

    # 2. Calculate Indicators on correct periodicity
    data_with_indicators = strategy.calculate_indicators(data_to_calc)
    
    # 3. Apply filters
    data_with_filters = strategy.apply_filters(data_with_indicators)

    # 4. Map back to 1-minute bars
    # Copy ALL indicator and filter columns back
    base_cols = {'open', 'high', 'low', 'close', 'volume'}
    new_cols = [col for col in data_with_filters.columns if col not in base_cols]
    
    for col in new_cols:
        # For force_exit, we only want to map exactly OR ffill if logical
        if col in ['force_exit', 'force_exit_rth']:
            data[col] = False # Reset first
            # Map exactly to the boundary rows
            matching = data.index.intersection(data_with_filters.index)
            if len(matching) > 0:
                data.loc[matching, col] = data_with_filters.loc[matching, col]
        else:
            # For most indicators (SMA, ATR, volume_filter), forward-fill is correct
            # Reindex to 1-min index and ffill
            data[col] = data_with_filters[col].reindex(data.index, method='ffill')


def save_live_data_row(output_dir, timestamp, row, full_df):
    """Save live data row to CSV for backtest comparison."""
    try:
        csv_path = os.path.join(output_dir, 'live_data.csv')
        file_exists = os.path.isfile(csv_path)

        # Dynamically include all available columns
        base_cols = ['open', 'high', 'low', 'close', 'volume']
        extra_cols = ['upper', 'lower', 'mid', 'atr_ts', 'atr', 'donchian_high', 'donchian_low',
                      'in_rth', 'in_maintenance', 'volume_filter', 'atr_filter',
                      'force_exit', 'force_exit_rth']

        row_data = {}
        for col in base_cols + extra_cols:
            val = row.get(col, '') if isinstance(row, dict) else getattr(row, col, '')
            if val != '' and val is not None and not (isinstance(val, float) and pd.isna(val)):
                row_data[col] = val
        # Persist every computed indicator/filter column for paper/backtest parity.
        source = row.to_dict() if isinstance(row, pd.Series) else (row if isinstance(row, dict) else {})
        skip = set(base_cols) | set(row_data.keys())
        for col, val in source.items():
            if col in skip or val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            row_data[col] = val

        row_series = pd.Series(row_data, name=timestamp)

        if not file_exists:
            row_series.to_frame().T.to_csv(csv_path, mode="w", header=True)
        else:
            existing = read_live_data_csv(csv_path)
            new_row = row_series.to_frame().T
            new_row.index = pd.to_datetime(new_row.index)
            if getattr(new_row.index, "tz", None) is not None:
                new_row.index = new_row.index.tz_convert("US/Eastern").tz_localize(None)
            all_cols = list(dict.fromkeys(list(existing.columns) + list(new_row.columns)))
            existing = existing.reindex(columns=all_cols)
            new_row = new_row.reindex(columns=all_cols)
            combined = pd.concat([existing, new_row])
            combined = combined[~combined.index.duplicated(keep="last")].sort_index()
            combined.to_csv(csv_path)
    except Exception as e:
        logging.error(f"Failed to save live data row: {e}")


def append_open_trade_timeline(output_dir, timestamp, row, positions):
    """Append per-bar diagnostics for each open tracked trade (for forensic reconstruction)."""
    if not output_dir or not positions:
        return
    try:
        path = os.path.join(output_dir, "open_trade_timeline.jsonl")
        ts = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
        close_px = float(row.get('close', 0) or 0)
        for b in positions:
            direction = b.get('direction', 0)
            stop_order = b.get('stopLoss')
            tp_order = b.get('takeProfit')
            model_stop = (b.get('position_dict') or {}).get('stop')
            broker_stop = (
                getattr(stop_order, 'auxPrice', getattr(stop_order, 'stopPrice', None))
                if stop_order
                else None
            )
            stop_px = model_stop if model_stop is not None else broker_stop
            tp_px = getattr(tp_order, 'lmtPrice', None) if tp_order else None
            entry_px = float(b.get('entry_price', 0) or 0)
            qty = 1
            if stop_order is not None and hasattr(stop_order, 'totalQuantity'):
                qty = abs(stop_order.totalQuantity)
            elif b.get('entry') is not None and hasattr(b.get('entry'), 'totalQuantity'):
                qty = abs(b.get('entry').totalQuantity)
            rec = {
                "ts": ts,
                "symbol": getattr(b.get('contract', None), 'localSymbol', 'ES'),
                "direction": "LONG" if direction == 1 else "SHORT" if direction == -1 else "N/A",
                "entry_time": b.get('entry_time').isoformat() if hasattr(b.get('entry_time'), "isoformat") else None,
                "entry_price": entry_px,
                "close": close_px,
                "stop": float(stop_px) if stop_px is not None else None,
                "tp": float(tp_px) if tp_px is not None else None,
                "qty": qty,
                "unrealized": ((close_px - entry_px) * direction * 50 * qty) if (entry_px and direction) else None,
                "bar": {
                    "open": float(row.get('open', 0) or 0),
                    "high": float(row.get('high', 0) or 0),
                    "low": float(row.get('low', 0) or 0),
                    "close": close_px,
                    "volume": float(row.get('volume', 0) or 0),
                    "donchian_high": float(row.get('donchian_high')) if row.get('donchian_high') is not None and not pd.isna(row.get('donchian_high')) else None,
                    "donchian_low": float(row.get('donchian_low')) if row.get('donchian_low') is not None and not pd.isna(row.get('donchian_low')) else None,
                    "atr": float(row.get('atr')) if row.get('atr') is not None and not pd.isna(row.get('atr')) else None,
                },
            }
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
    except Exception as e:
        logging.debug(f"Failed to append open trade timeline: {e}")

def save_shadow_audit(output_dir, timestamp, action_log):
    """Save rejection events to daily shadow_audit_YYYYMMDD.json."""
    if not action_log:
        return
        
    try:
        # Only log 'Breakout Rejected' types for the auditor
        rejections = [entry for entry in action_log if entry.get('type') == 'Breakout Rejected']
        if not rejections:
            return
            
        date_str = timestamp.strftime('%Y%m%d') if hasattr(timestamp, 'strftime') else datetime.now().strftime('%Y%m%d')
        audit_path = os.path.join(output_dir, f'shadow_audit_{date_str}.json')
        
        # Load existing audit log
        audit_data = []
        if os.path.exists(audit_path):
            try:
                with open(audit_path, 'r') as f:
                    audit_data = json.load(f)
            except:
                pass
        
        # Add new rejections (avoiding duplicates if possible)
        for rej in rejections:
            # Convert timestamp to string if needed
            if hasattr(rej['timestamp'], 'strftime'):
                rej['timestamp'] = rej['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            
            # Simple deduplication: don't add if timestamp+direction already exists
            exists = any(item['timestamp'] == rej['timestamp'] and item['direction'] == rej['direction'] for item in audit_data)
            if not exists:
                audit_data.append(rej)
        
        # Save back
        with open(audit_path, 'w') as f:
            json.dump(audit_data, f, indent=2)
            
    except Exception as e:
        logging.error(f"Failed to save shadow audit: {e}")


def log_entry_criteria_status(strategy, positions, resampled_row, data_with_filters, output_dir=None):
    """Log entry criteria status with emoji indicators for each filter.
    Strategy-agnostic: uses strategy.check_entry() if available, otherwise basic filter checks.
    """
    try:
        price = resampled_row.get('close', 0)
        volume = resampled_row.get('volume', 0)

        max_ok = len(positions) < strategy.max_open_trades
        in_rth = resampled_row.get('in_rth', True)
        atr_filter = resampled_row.get('atr_filter', False)
        vol_filter = resampled_row.get('volume_filter', True)  # True by default for strategies without volume filter
        in_maint = resampled_row.get('in_maintenance', False)

        enter_long = enter_short = False
        long_reason = short_reason = ""
        action_log = None

        # 1. Strategy-Agnostic Global Filters (Positions, Maintenance, RTH)
        if not max_ok:
            long_reason = short_reason = f"Max trades ({len(positions)}/{strategy.max_open_trades})"
        elif in_maint:
            long_reason = short_reason = "Maintenance Filter"
        elif not in_rth:
            long_reason = short_reason = "Outside RTH"
        else:
            # 2. Strategy Signal and Filter Check
            if hasattr(strategy, 'check_entry'):
                triggered, direction, _ = strategy.check_entry(resampled_row, data_with_filters)
                enter_long = triggered and direction == 'Long'
                enter_short = triggered and direction == 'Short'
                long_reason = "Signal triggered" if enter_long else "No entry"
                short_reason = "Signal triggered" if enter_short else "No entry"
                
            elif hasattr(strategy, 'calculate_entry_signals') and data_with_filters is not None:
                try:
                    # Request Action Log (verbose=True)
                    sigs = strategy.calculate_entry_signals(data_with_filters, verbose=True)
                    
                    if len(sigs) == 3:
                        long_sig, short_sig, action_log = sigs
                    else:
                        long_sig, short_sig = sigs
                    
                    idx = resampled_row.name if hasattr(resampled_row, 'name') else None
                    if idx is not None and idx in data_with_filters.index:
                        loc = data_with_filters.index.get_loc(idx)
                        enter_long = bool(long_sig.iloc[loc]) if loc < len(long_sig) else False
                        enter_short = bool(short_sig.iloc[loc]) if loc < len(short_sig) else False
                        
                        # Extract rejection reasons from Action Log for this specific bar
                        if action_log:
                            bar_logs = [entry for entry in action_log if entry['timestamp'] == idx]
                            long_info = next((l for l in bar_logs if l['direction'] == 'LONG'), None)
                            short_info = next((l for l in bar_logs if l['direction'] == 'SHORT'), None)
                            
                            if long_info:
                                long_reason = " | ".join(long_info['reasons']) if long_info['reasons'] else "Signal triggered"
                            else:
                                long_reason = "No breakout"
                                
                            if short_info:
                                short_reason = " | ".join(short_info['reasons']) if short_info['reasons'] else "Signal triggered"
                            else:
                                short_reason = "No breakout"
                        else:
                            long_reason = "Signal triggered" if enter_long else "No entry"
                            short_reason = "Signal triggered" if enter_short else "No entry"
                            
                except Exception as e:
                    logging.debug(f"Error checking strategy signals: {e}")
                    long_reason = short_reason = "Error"

            # Check ATR and Volume failure if not already covered by strategy core
            if not enter_long and long_reason == "Signal triggered": # Logic error safety
                long_reason = "No signal"
            if not enter_short and short_reason == "Signal triggered":
                short_reason = "No signal"
                
            # If strategy didn't report ATR/Vol failure but they failed globally:
            if not (long_reason or short_reason):
                if not atr_filter: long_reason = short_reason = "ATR filter failed"
                elif not vol_filter: long_reason = short_reason = f"Vol filter (vol={volume:,.0f})"

        # 3. Build detailed parts using numerical values if available
        parts = []
        
        # Get numerical status from strategy if supports it
        num_status = {}
        if hasattr(strategy, 'get_indicator_status'):
            num_status = strategy.get_indicator_status(resampled_row)
            
        # Global Filters
        parts.append(f"MaxTr: {'✅' if max_ok else '❌'}")
        parts.append(f"RTH: {'✅' if in_rth else '❌'}")
        parts.append(f"Maint: {'✅' if not in_maint else '❌'}")
        if hasattr(strategy, 'enable_long'):
            parts.append(f"EnL: {'✅' if strategy.enable_long else '❌'}")
        if hasattr(strategy, 'enable_short'):
            parts.append(f"EnS: {'✅' if strategy.enable_short else '❌'}")
        
        # Numerical Filter Details (Trend.get_indicator_status and similar)
        if num_status:
            if 'ATR' in num_status:
                s = num_status['ATR']
                parts.append(
                    f"ATRfl: {'✅' if s['pass'] else '❌'} "
                    f"({s['value']:.2f}/{s['threshold']:.2f})"
                )
            if 'ADX' in num_status:
                s = num_status['ADX']
                parts.append(f"ADX: {'✅' if s['pass'] else '❌'} ({s['value']:.1f}/{s['threshold']:.1f})")
            if 'Volume' in num_status:
                s = num_status['Volume']
                parts.append(
                    f"Vol: {'✅' if s['pass'] else '❌'} "
                    f"({s['value']/1000:.1f}k/{s['threshold']/1000:.1f}k)"
                )
            if 'RSI' in num_status:
                s = num_status['RSI']
                val = s['value']
                icon = '✅' if (s['pass_long'] or s['pass_short']) else '❌'
                parts.append(
                    f"RSI: {icon} ({val:.1f} / buy≤{s['buy_threshold']:.1f} sell≥{s['sell_threshold']:.1f})"
                )
            if 'SMA' in num_status:
                s = num_status['SMA']
                icon = '✅' if (s['pass_long'] or s['pass_short']) else '❌'
                sm_l = '✅' if s['pass_long'] else '❌'
                sm_s = '✅' if s['pass_short'] else '❌'
                parts.append(
                    f"SMA: {icon} (C:{s['price']:.2f}/SMA:{s['sma']:.2f} L:{sm_l} S:{sm_s})"
                )
            if 'VWAP' in num_status:
                s = num_status['VWAP']
                icon = '✅' if (s['pass_long'] or s['pass_short']) else '❌'
                parts.append(
                    f"VWAP: {icon} (C:{s['price']:.2f}/VWAP:{s['vwap']:.2f})"
                )
        else:
            parts.append(f"ATR: {'✅' if atr_filter else '❌'}")
            parts.append(f"Vol: {'✅' if vol_filter else '❌'}")
        # Row-level volume gate when strategy has no Volume in num_status (e.g. filter off)
        if num_status and 'Volume' not in num_status:
            parts.append(f"VolFlt: {'✅' if vol_filter else '❌'}")

        # Final Signal Status
        parts.append(f"Long: {'✅' if enter_long else '❌'} ({long_reason})")
        parts.append(f"Short: {'✅' if enter_short else '❌'} ({short_reason})")

        criteria_str = ' | '.join(parts)
        logging.info(f"  Entry Criteria: {criteria_str}")
        
        # 4. Save to Shadow Auditor if breakouts were rejected
        if action_log and output_dir:
            save_shadow_audit(output_dir, resampled_row.name, action_log)

        return criteria_str
    except Exception as e:
        logging.debug(f"Error logging entry criteria: {e}")
        return ""


def on_bar_update_handler(bars, hasNewBar, *, strategy, ib, contract, data_ref,
                          positions, completed_trades, live_tracker, bar_log,
                          dashboard_state, send_email_fn, output_dir, last_data_receipt,
                          last_new_bar_receipt=None):
    """IB callback: liveness + snapshot; heavy work runs on the bar pipeline consumer."""
    last_data_receipt["time"] = datetime.now()
    if hasNewBar and last_new_bar_receipt is not None:
        last_new_bar_receipt["time"] = datetime.now()
    snap = [(b.date, b.open, b.high, b.low, b.close, b.volume) for b in bars]

    if BAR_PIPELINE_QUEUE is not None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:

            def _enqueue() -> None:
                try:
                    BAR_PIPELINE_QUEUE.put_nowait((snap, hasNewBar))
                except asyncio.QueueFull:
                    try:
                        BAR_PIPELINE_QUEUE.get_nowait()
                        BAR_PIPELINE_QUEUE.task_done()
                    except (asyncio.QueueEmpty, ValueError):
                        pass
                    try:
                        BAR_PIPELINE_QUEUE.put_nowait((snap, hasNewBar))
                    except asyncio.QueueFull:
                        logging.warning(
                            "Bar pipeline queue saturated; dropping a bar update tick"
                        )

            loop.call_soon(_enqueue)
            return

    _sync_on_bar_update_legacy(
        snap, hasNewBar, strategy=strategy, ib=ib, contract=contract, data_ref=data_ref,
        positions=positions, completed_trades=completed_trades, live_tracker=live_tracker,
        bar_log=bar_log, dashboard_state=dashboard_state, send_email_fn=send_email_fn,
        output_dir=output_dir, last_data_receipt=last_data_receipt,
    )

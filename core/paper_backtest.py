"""Paper-parity backtest: replays live HTF bar evaluation order from the execution log."""
from __future__ import annotations

import os
import re
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from core.monitoring import (
    PAPER_WARMUP_MAX_BARS,
    ib_htf_seed_at_subscribe,
    required_htf_warmup_bars,
    _parse_subscribe_seed_counts,
)
from core.sim_fidelity import (
    ga_live_style_entry_enabled,
    simulate_bar_exit,
)

_HTF_BAR_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO "
    r"\[(\d+)-min\] (\d{2}:\d{2}:\d{2}) \| "
    r"O: ([\d.]+) H: ([\d.]+) L: ([\d.]+) C: ([\d.]+)"
    r"(?: \| Vol: ([\d,]+))?"
)

_OHLCV_COLS = ("open", "high", "low", "close", "volume")

# live_data.csv stores indicators under legacy column names (see save_live_data_row).
_LIVE_INDICATOR_COLS = (
    ("upper", "donchian_high"),
    ("lower", "donchian_low"),
    ("force_exit_rth", "vwap"),
    ("force_exit", "rsi"),
    ("atr_filter", "sma"),
)


def load_live_indicator_overlay(live_data_path: str) -> pd.DataFrame:
    """Load recorded live indicator columns keyed by HTF bar timestamp."""
    if not live_data_path or not os.path.isfile(live_data_path):
        return pd.DataFrame()
    try:
        raw = pd.read_csv(live_data_path, index_col=0, parse_dates=True)
    except (OSError, ValueError):
        return pd.DataFrame()
    if raw.empty:
        return raw
    idx = pd.to_datetime(raw.index, utc=True).tz_convert("US/Eastern").tz_localize(None)
    raw.index = idx
    raw = raw[~raw.index.duplicated(keep="last")].sort_index()
    keep = [src for src, _ in _LIVE_INDICATOR_COLS if src in raw.columns]
    if not keep:
        return pd.DataFrame()
    return raw[keep]


def overlay_live_indicators(
    filt: pd.DataFrame,
    live_overlay: pd.DataFrame,
) -> pd.DataFrame:
    """
    Replace computed indicators with values the live bot persisted at each bar.

    Rolling 1-min resamples after reconnect/subscribe can shift HTF phase; logged
    OHLC plus live_data indicators match what the bot evaluated at each wall time.
    """
    if filt is None or filt.empty or live_overlay is None or live_overlay.empty:
        return filt
    shared = filt.index.intersection(live_overlay.index)
    if shared.empty:
        return filt
    out = filt.copy()
    for src, dst in _LIVE_INDICATOR_COLS:
        if src not in live_overlay.columns:
            continue
        vals = pd.to_numeric(live_overlay.loc[shared, src], errors="coerce")
        if dst not in out.columns:
            out[dst] = float("nan")
        out.loc[shared, dst] = vals
    return out


def parse_htf_bar_events(
    execution_log_path: str,
    *,
    timeframe: int = 14,
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
    include_ohlc: bool = False,
) -> List[Tuple]:
    """
    Parse ``[14-min] HH:MM:SS`` log lines.

    Returns ordered ``(bar_label, wall_time[, ohlc_dict])`` pairs.
    """
    if not execution_log_path or not os.path.isfile(execution_log_path):
        return []
    out: List[Tuple] = []
    try:
        with open(execution_log_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _HTF_BAR_RE.search(line)
                if not m:
                    continue
                tf = int(m.group(2))
                if tf != int(timeframe):
                    continue
                wall = pd.Timestamp(m.group(1))
                if start is not None and wall < pd.Timestamp(start):
                    continue
                if end is not None and wall > pd.Timestamp(end):
                    continue
                bar_date = wall.normalize()
                hh, mm, ss = (int(x) for x in m.group(3).split(":"))
                bar_label = bar_date + pd.Timedelta(hours=hh, minutes=mm, seconds=ss)
                # After midnight, logged bar times can roll to the prior session
                # (e.g. wall 2026-07-03 00:00:07 with [14-min] 23:48:00 -> Jul 2 23:48).
                if bar_label > wall:
                    bar_label -= pd.Timedelta(days=1)
                if include_ohlc:
                    vol_raw = m.group(8)
                    volume = float(vol_raw.replace(",", "")) if vol_raw else 0.0
                    ohlc = {
                        "open": float(m.group(4)),
                        "high": float(m.group(5)),
                        "low": float(m.group(6)),
                        "close": float(m.group(7)),
                        "volume": volume,
                    }
                    out.append((bar_label, wall, ohlc))
                else:
                    out.append((bar_label, wall))
    except OSError:
        return []
    return out


def wall_time_active(wall_time: pd.Timestamp, active_ranges) -> bool:
    """True when the bot had market data at this wall-clock instant."""
    if not active_ranges:
        return True
    ts = pd.Timestamp(wall_time)
    if ts.tz is not None:
        ts = ts.tz_convert("US/Eastern").tz_localize(None)
    for start, end in active_ranges:
        if start <= ts <= end:
            return True
    return False


def _session_window(
    wall_time: pd.Timestamp,
    active_ranges,
) -> Optional[Tuple[pd.Timestamp, pd.Timestamp]]:
    """Active-range window containing ``wall_time``, if any."""
    ts = pd.Timestamp(wall_time)
    if ts.tz is not None:
        ts = ts.tz_convert("US/Eastern").tz_localize(None)
    if not active_ranges:
        return None
    for start, end in active_ranges:
        if start <= ts <= end:
            return start, end
    return None


def _session_first_bar(
    events: List[Tuple],
    wall_time: pd.Timestamp,
    active_ranges,
) -> pd.Timestamp:
    """First logged HTF bar label in the connect window containing ``wall_time``."""
    ts = pd.Timestamp(wall_time)
    if ts.tz is not None:
        ts = ts.tz_convert("US/Eastern").tz_localize(None)

    sess: List[Tuple] = []
    if active_ranges:
        for start, end in active_ranges:
            if start <= ts <= end:
                sess = [e for e in events if start <= e[1] <= ts]
                break
    else:
        sess = [
            e for e in events
            if e[1].normalize() == ts.normalize() and e[1] <= ts
        ]

    if not sess:
        return ts
    return min(e[0] for e in sess)


def _logged_seed_from_events(
    events: List[Tuple],
    session_start: pd.Timestamp,
    *,
    strategy=None,
) -> pd.DataFrame:
    """Last N logged HTF bars before ``session_start`` (indicator carry-over)."""
    start = pd.Timestamp(session_start)
    rows = []
    for item in events:
        if len(item) < 3:
            continue
        bar_label, wall_time, ohlc = item[0], item[1], item[2]
        if wall_time >= start:
            break
        rows.append((bar_label, ohlc))
    if not rows:
        return pd.DataFrame(columns=list(_OHLCV_COLS))
    idx = [b for b, _ in rows]
    data = [o for _, o in rows]
    out = pd.DataFrame(data, index=idx, columns=list(_OHLCV_COLS))
    if strategy is not None:
        need = required_htf_warmup_bars(strategy)
        if len(out) > need:
            out = out.iloc[-need:]
    return out


def _ib_seed_for_session(
    df_1min: pd.DataFrame,
    session_start: pd.Timestamp,
    *,
    timeframe: int,
    seed_map: Dict,
    max_bars: int = PAPER_WARMUP_MAX_BARS,
) -> pd.DataFrame:
    """Resample IB in-memory seed at subscribe (same rules as ``load_paper_compare_htf``)."""
    day = pd.Timestamp(session_start).date()
    connect_ts, seed_n = seed_map.get(day, (pd.Timestamp(session_start), int(max_bars)))
    return ib_htf_seed_at_subscribe(
        df_1min,
        connect_ts,
        timeframe=timeframe,
        seed_n=int(seed_n),
        max_bars=max_bars,
    )


def _build_point_in_time_htf(
    session_pre: pd.DataFrame,
    replay_rows: List[Tuple[pd.Timestamp, dict]],
    bar_label: pd.Timestamp,
    *,
    strategy=None,
) -> pd.DataFrame:
    """HTF series at ``bar_label``: IB seed for this session plus logged bars so far."""
    ohlcv = [c for c in _OHLCV_COLS if c in session_pre.columns]
    if not ohlcv:
        ohlcv = list(_OHLCV_COLS)

    pre = session_pre[ohlcv] if session_pre is not None and not session_pre.empty else pd.DataFrame(columns=ohlcv)
    if strategy is not None and len(pre) > required_htf_warmup_bars(strategy):
        need = required_htf_warmup_bars(strategy)
        pre = pre.iloc[-need:]

    replay_idx = [b for b, _ in replay_rows if b <= bar_label]
    replay_data = [row for b, row in replay_rows if b <= bar_label]
    replay = (
        pd.DataFrame(replay_data, index=replay_idx, columns=ohlcv)
        if replay_data
        else pd.DataFrame(columns=ohlcv)
    )

    if pre.empty and replay.empty:
        return pd.DataFrame(columns=ohlcv)

    out = pd.concat([pre, replay]).sort_index()
    return out[~out.index.duplicated(keep="last")]


def run_paper_parity_backtest(
    strategy,
    params_dict: dict,
    htf_warmup: pd.DataFrame,
    execution_log_path: str,
    *,
    df_1min: Optional[pd.DataFrame] = None,
    live_indicator_overlay: Optional[pd.DataFrame] = None,
    active_ranges=None,
    max_bars: int = PAPER_WARMUP_MAX_BARS,
    transaction_cost: float = 15.0,
) -> Dict[str, Any]:
    """
    Simulate trades by replaying each logged HTF bar evaluation like the live bot.

    Uses OHLCV exactly as logged at each ``[N-min]`` event plus pre-session IB
    warmup from ``htf_warmup`` (``load_paper_compare_htf`` output).
    """
    tf = max(1, int(getattr(strategy, "timeframe", 1) or 1))
    warmup = htf_warmup.sort_index()
    if getattr(warmup.index, "tz", None) is not None:
        warmup = warmup.copy()
        warmup.index = warmup.index.tz_convert("US/Eastern").tz_localize(None)

    events = parse_htf_bar_events(
        execution_log_path,
        timeframe=tf,
        start=warmup.index.min() if len(warmup) else None,
        end=warmup.index.max() + pd.Timedelta(days=1) if len(warmup) else None,
        include_ohlc=True,
    )
    if not events:
        return {"total_pnl": 0.0, "trades_df": pd.DataFrame(), "df": None}

    events.sort(key=lambda x: x[1])
    seed_map = _parse_subscribe_seed_counts(execution_log_path) if df_1min is not None else {}

    live_style_entry = ga_live_style_entry_enabled(params_dict)
    if hasattr(strategy, "_paper_parity_broker_tp"):
        strategy._paper_parity_broker_tp = True
    else:
        setattr(strategy, "_paper_parity_broker_tp", True)
    positions: List[dict] = []
    trades: List[dict] = []
    replay_rows: List[Tuple[pd.Timestamp, dict]] = []
    current_session: Optional[Tuple[pd.Timestamp, pd.Timestamp]] = None
    session_pre = pd.DataFrame()
    use_ib_only = False

    for bar_label, wall_time, ohlc in events:
        if not wall_time_active(wall_time, active_ranges):
            continue

        session = _session_window(wall_time, active_ranges)
        if session != current_session:
            replay_rows = []
            positions = []
            current_session = session
            if session is not None:
                ib_seed = pd.DataFrame()
                if df_1min is not None and not df_1min.empty:
                    ib_seed = _ib_seed_for_session(
                        df_1min,
                        session[0],
                        timeframe=tf,
                        seed_map=seed_map,
                        max_bars=max_bars,
                    )
                logged = _logged_seed_from_events(events, session[0], strategy=strategy)
                gap_seconds = 0.0
                session_idx = 0
                if active_ranges and session in active_ranges:
                    session_idx = active_ranges.index(session)
                    if session_idx > 0:
                        gap_seconds = (
                            pd.Timestamp(session[0]) - pd.Timestamp(active_ranges[session_idx - 1][1])
                        ).total_seconds()
                use_ib_only = gap_seconds > 3600
                if use_ib_only and len(logged) >= required_htf_warmup_bars(strategy):
                    session_pre = logged
                elif use_ib_only and not ib_seed.empty:
                    connect_day = pd.Timestamp(session[0]).date()
                    session_pre = ib_seed[
                        pd.to_datetime(ib_seed.index).date < connect_day
                    ]
                elif len(logged) >= required_htf_warmup_bars(strategy):
                    session_pre = logged
                elif not ib_seed.empty:
                    session_pre = ib_seed
                else:
                    session_pre = logged
            else:
                session_pre = pd.DataFrame()
                use_ib_only = False

        replay_rows.append((bar_label, ohlc))
        pts = _build_point_in_time_htf(
            session_pre, replay_rows, bar_label, strategy=strategy,
        )
        if pts.empty or bar_label not in pts.index:
            continue

        filt = strategy.calculate_indicators(pts.copy())
        if hasattr(strategy, "apply_filters"):
            filt = strategy.apply_filters(filt)
        if bar_label not in filt.index:
            continue

        filt_entry = overlay_live_indicators(filt, live_indicator_overlay)
        if bar_label not in filt_entry.index:
            continue

        row = filt_entry.loc[bar_label]
        row_view = SimpleNamespace(
            **row.to_dict(),
            Index=bar_label,
            name=bar_label,
        )
        row_exit = filt.loc[bar_label]
        row_exit_view = SimpleNamespace(
            **row_exit.to_dict(),
            Index=bar_label,
            name=bar_label,
        )

        for i, pos in enumerate(positions[:]):
            should_exit, reason, price = simulate_bar_exit(
                strategy, pos, row_exit_view, filt, params_dict,
            )
            if not should_exit:
                continue
            pnl_points = (price - pos["entry_price"]) * pos["direction"]
            trades.append(
                {
                    "entry_time": pos["entry_time"],
                    "exit_time": bar_label,
                    "pnl_currency": pnl_points * 50 - transaction_cost,
                    "pnl_points": pnl_points,
                    "direction": pos["direction"],
                    "entry_price": pos["entry_price"],
                    "exit_price": price,
                    "reason": reason,
                }
            )
            positions.pop(i)

        if positions:
            continue

        sigs = strategy.calculate_entry_signals(filt_entry)
        if len(sigs) == 3:
            long_sig, short_sig, _ = sigs
        else:
            long_sig, short_sig = sigs
        if bar_label not in long_sig.index:
            continue

        enter_long = bool(long_sig.loc[bar_label])
        enter_short = bool(short_sig.loc[bar_label])
        if not enter_long and not enter_short:
            continue

        direction = 1 if enter_long else -1
        if live_style_entry:
            entry_price = float(row_view.close)
            pos = strategy.setup_position(entry_price, direction, row_view, filt_entry)
            positions.append(pos)
            should_exit, reason, price = simulate_bar_exit(
                strategy, pos, row_exit_view, filt, params_dict,
            )
            if should_exit:
                pnl_points = (price - pos["entry_price"]) * pos["direction"]
                trades.append(
                    {
                        "entry_time": pos["entry_time"],
                        "exit_time": bar_label,
                        "pnl_currency": pnl_points * 50 - transaction_cost,
                        "pnl_points": pnl_points,
                        "direction": pos["direction"],
                        "entry_price": pos["entry_price"],
                        "exit_price": price,
                        "reason": reason,
                    }
                )
                positions.pop()

    trades_df = pd.DataFrame(trades)
    total_pnl = float(trades_df["pnl_currency"].sum()) if not trades_df.empty else 0.0
    return {
        "total_pnl": total_pnl,
        "trades_df": trades_df,
        "df": None,
    }

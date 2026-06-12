"""Load and format per-trade stop/TP trails from open_trade_timeline.jsonl."""

from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd


def _parse_ts(ts: Any) -> Optional[pd.Timestamp]:
    if ts is None:
        return None
    try:
        return pd.Timestamp(ts)
    except Exception:
        return None


def _align_ts_to_ref(ts: Any, ref: pd.Timestamp) -> Optional[pd.Timestamp]:
    t = _parse_ts(ts)
    if t is None:
        return None
    if ref.tzinfo is None and t.tzinfo is not None:
        return pd.Timestamp(t.to_pydatetime().replace(tzinfo=None))
    if ref.tzinfo is not None and t.tzinfo is None:
        try:
            return t.tz_localize(ref.tz, ambiguous="infer", nonexistent="shift_forward")
        except (TypeError, ValueError):
            return t
    return t


def _direction_label(direction: Any) -> Optional[str]:
    if direction is None:
        return None
    if isinstance(direction, str):
        d = direction.strip().upper()
        if d in ("LONG", "BUY", "1", "+1"):
            return "LONG"
        if d in ("SHORT", "SELL", "-1"):
            return "SHORT"
        return None
    try:
        return "LONG" if int(direction) == 1 else "SHORT"
    except (TypeError, ValueError):
        return None


def timeline_search_dirs(output_dir: Optional[str] = None) -> List[str]:
    dirs: List[str] = []
    if output_dir:
        dirs.append(os.path.abspath(output_dir))
    env = os.environ.get("IB_BOT_OUTPUT_DIR", "").strip()
    if env:
        dirs.append(os.path.abspath(env))
    root = os.getcwd()
    dirs.extend([os.path.join(root, "paper_logs"), os.path.join(root, "live_logs")])
    seen = set()
    out: List[str] = []
    for d in dirs:
        if d and d not in seen and os.path.isdir(d):
            seen.add(d)
            out.append(d)
    return out


def _read_timeline_records(paths: Sequence[str]) -> List[dict]:
    rows: List[dict] = []
    for d in paths:
        path = os.path.join(d, "open_trade_timeline.jsonl")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(rec, dict):
                        rows.append(rec)
        except OSError:
            continue
    return rows


def _float_or_none(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def load_trade_timeline_series(
    output_dir: Optional[str],
    entry_time: Any,
    exit_time: Any = None,
    direction: Any = None,
    max_points: int = 1200,
    entry_tolerance_sec: float = 3600,
) -> Optional[Dict[str, List]]:
    """
    Load stop/TP samples for a trade from open_trade_timeline.jsonl.

    Matches by direction + time window around entry/exit, then picks the
    entry_time cluster with the most records (fuzzy entry_time tolerance).
    """
    et = _parse_ts(entry_time)
    if et is None:
        return None
    xt = _parse_ts(exit_time) if exit_time is not None else et + pd.Timedelta(hours=6)
    want_dir = _direction_label(direction)

    window_start = et - pd.Timedelta(minutes=45)
    window_end = xt + pd.Timedelta(minutes=45)

    candidates: List[dict] = []
    for rec in _read_timeline_records(timeline_search_dirs(output_dir)):
        if want_dir and str(rec.get("direction", "")).upper() != want_dir:
            continue
        tst = _align_ts_to_ref(rec.get("ts"), et)
        if tst is None or tst < window_start or tst > window_end:
            continue
        candidates.append(rec)

    if not candidates:
        return None

    by_entry: Dict[str, List[dict]] = {}
    for rec in candidates:
        key = str(rec.get("entry_time") or "")
        by_entry.setdefault(key, []).append(rec)

    best_key: Optional[str] = None
    best_score = -1.0
    for key, recs in by_entry.items():
        if not key:
            continue
        r_et = _parse_ts(key)
        if r_et is None:
            continue
        delta = abs((r_et - et).total_seconds())
        if delta > entry_tolerance_sec:
            continue
        score = len(recs) * 1000.0 - delta
        if score > best_score:
            best_score = score
            best_key = key

    if best_key is None:
        best_key = max(by_entry.keys(), key=lambda k: len(by_entry[k]))

    rows = sorted(
        by_entry.get(best_key, []),
        key=lambda r: _align_ts_to_ref(r.get("ts"), et) or pd.Timestamp.min,
    )

    dedup: Dict[pd.Timestamp, dict] = {}
    for rec in rows:
        tst = _align_ts_to_ref(rec.get("ts"), et)
        if tst is not None:
            dedup[tst] = rec
    ordered = [dedup[k] for k in sorted(dedup.keys())][-max_points:]

    times: List[str] = []
    stop_vals: List[Optional[float]] = []
    tp_vals: List[Optional[float]] = []
    for rec in ordered:
        tst = _align_ts_to_ref(rec.get("ts"), et)
        if tst is None:
            continue
        times.append(tst.isoformat())
        stop_vals.append(_float_or_none(rec.get("stop")))
        tp_vals.append(_float_or_none(rec.get("tp")))

    if not times:
        return None
    return {"times": times, "stop": stop_vals, "tp": tp_vals}


def build_display_trail(
    entry_time: Any,
    exit_time: Any,
    stop_at_open: Any = None,
    stop_at_close: Any = None,
    tp_at_open: Any = None,
    tp_at_close: Any = None,
    timeline: Optional[Dict[str, List]] = None,
) -> Tuple[List, List, List, List]:
    """
    Merge timeline samples with open/close anchors so charts always show an hv trail
    spanning entry → exit (even when timeline logging was sparse).
    """
    et = _parse_ts(entry_time)
    xt = _parse_ts(exit_time)
    if et is None or xt is None:
        return [], [], [], []

    stop_pts: List[Tuple[pd.Timestamp, float]] = []
    tp_pts: List[Tuple[pd.Timestamp, float]] = []

    so = _float_or_none(stop_at_open)
    sc = _float_or_none(stop_at_close)
    to = _float_or_none(tp_at_open)
    tc = _float_or_none(tp_at_close)

    if so is not None:
        stop_pts.append((et, so))
    if to is not None:
        tp_pts.append((et, to))

    if timeline:
        for ts_raw, sp, tp in zip(
            timeline.get("times") or [],
            timeline.get("stop") or [],
            timeline.get("tp") or [],
        ):
            tst = _align_ts_to_ref(ts_raw, et)
            if tst is None:
                continue
            if sp is not None:
                stop_pts.append((tst, float(sp)))
            if tp is not None:
                tp_pts.append((tst, float(tp)))

    if sc is not None:
        stop_pts.append((xt, sc))
    if tc is not None:
        tp_pts.append((xt, tc))

    def _collapse(points: List[Tuple[pd.Timestamp, float]]) -> Tuple[List, List]:
        if not points:
            return [], []
        points.sort(key=lambda x: x[0])
        merged: Dict[pd.Timestamp, float] = {}
        for t, v in points:
            merged[t] = v
        xs = sorted(merged.keys())
        return [t.isoformat() for t in xs], [merged[t] for t in xs]

    stop_x, stop_y = _collapse(stop_pts)
    tp_x, tp_y = _collapse(tp_pts)
    return stop_x, stop_y, tp_x, tp_y


def build_display_trail_series(
    entry_time: Any,
    exit_time: Any,
    stop_at_open: Any = None,
    stop_at_close: Any = None,
    tp_at_open: Any = None,
    tp_at_close: Any = None,
    timeline: Optional[Dict[str, List]] = None,
) -> Optional[Dict[str, List]]:
    """Unified times/stop/tp arrays for Plotly hv lines (forward-filled)."""
    stop_x, stop_y, tp_x, tp_y = build_display_trail(
        entry_time,
        exit_time,
        stop_at_open=stop_at_open,
        stop_at_close=stop_at_close,
        tp_at_open=tp_at_open,
        tp_at_close=tp_at_close,
        timeline=timeline,
    )
    if not stop_x and not tp_x:
        return None

    et = _parse_ts(entry_time)
    if et is None:
        return None

    all_ts: List[pd.Timestamp] = []
    for xs in (stop_x, tp_x):
        for raw in xs:
            t = _align_ts_to_ref(raw, et)
            if t is not None:
                all_ts.append(t)
    if not all_ts:
        return None

    stop_map = dict(zip(stop_x, stop_y))
    tp_map = dict(zip(tp_x, tp_y))

    times: List[str] = []
    stops: List[Optional[float]] = []
    tps: List[Optional[float]] = []
    last_stop: Optional[float] = None
    last_tp: Optional[float] = None
    for t in sorted(set(all_ts)):
        iso = t.isoformat()
        if iso in stop_map:
            last_stop = stop_map[iso]
        if iso in tp_map:
            last_tp = tp_map[iso]
        times.append(iso)
        stops.append(last_stop)
        tps.append(last_tp)

    if len(times) < 2:
        return None
    return {"times": times, "stop": stops, "tp": tps}

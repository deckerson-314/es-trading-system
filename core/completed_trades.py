"""Completed-trade dedupe, merge, and quality scoring for persistence/bootstrap."""
from datetime import datetime

import pandas as pd

from core.execution import _live_exit_type


def completed_trade_quality_score(tr: dict) -> int:
    """Prefer live execution records over log/CSV backfills when collapsing duplicates."""
    score = 0
    if tr.get("entry_time") is not None:
        score += 4
    if tr.get("entry_price") not in (None, 0, 0.0):
        score += 3
    if tr.get("report_url"):
        score += 2
    if tr.get("stop_at_close") is not None:
        score += 1
    if tr.get("tp_at_close") is not None:
        score += 1
    if tr.get("stop_at_open") is not None:
        score += 1
    if tr.get("tp_at_open") is not None:
        score += 1
    if tr.get("params_snapshot"):
        score += 3
    if tr.get("live_exit_type"):
        score += 5
    reason = str(tr.get("reason") or "")
    if reason and "Backfilled" not in reason and reason != "N/A":
        score += 6
    elif "Backfilled" in reason:
        score -= 3
    return score


def merge_trade_records(records: list) -> dict:
    """Union duplicate rows for the same fill (CSV times + log/live exit reason)."""
    if not records:
        return {}
    if len(records) == 1:
        return dict(records[0])

    merged = {}
    for rec in sorted(records, key=completed_trade_quality_score):
        for key, val in rec.items():
            if val is None or val == "":
                continue
            if key in ("entry_price", "exit_price", "pnl", "qty") and val in (0, 0.0):
                continue
            cur = merged.get(key)
            if cur is None or cur == "":
                merged[key] = val
                continue
            if key == "reason":
                cur_s, val_s = str(cur), str(val)
                if "Backfilled" in cur_s and "Backfilled" not in val_s:
                    merged[key] = val
                continue
            if key == "duration" and cur == "Backfilled" and val != "Backfilled":
                merged[key] = val
                continue
            if key == "direction" and str(cur).upper() in ("N/A", "") and str(val).upper() not in ("N/A", ""):
                merged[key] = val
                continue
            if key == "report_url" and not cur and val:
                merged[key] = val
                continue
            if key == "live_exit_type" and not cur and val:
                merged[key] = val
                continue
            if key == "params_snapshot" and not cur and val:
                merged[key] = val
                continue

    if not merged.get("live_exit_type") and merged.get("reason"):
        merged["live_exit_type"] = _live_exit_type(str(merged["reason"]))
    return merged


def normalize_trade_ts(val):
    if val is None:
        return None
    try:
        ts = pd.Timestamp(val)
        if ts.tzinfo is not None:
            ts = ts.tz_convert("US/Eastern").tz_localize(None)
        return ts.to_pydatetime()
    except Exception:
        return None


def direction_compatible(a: str, b: str) -> bool:
    da = str(a or "").strip().upper()
    db = str(b or "").strip().upper()
    if not da or da == "N/A" or not db or db == "N/A":
        return True
    return da == db


def same_fill_event(a: dict, b: dict, window_sec: float = 120.0) -> bool:
    """
    True when two completed_trade rows likely describe the same broker fill.
    Log lines use second resolution; CSV and live paths use different timestamps
    a few seconds apart for the same exit.
    """
    ea = normalize_trade_ts(a.get("exit_time"))
    eb = normalize_trade_ts(b.get("exit_time"))
    if ea is None or eb is None:
        return False
    if abs((ea - eb).total_seconds()) > window_sec:
        return False
    try:
        pa = round(float(a.get("exit_price")), 2)
        pb = round(float(b.get("exit_price")), 2)
    except (TypeError, ValueError):
        return False
    if pa != pb:
        return False
    if not direction_compatible(a.get("direction"), b.get("direction")):
        return False
    eta = normalize_trade_ts(a.get("entry_time"))
    etb = normalize_trade_ts(b.get("entry_time"))
    if eta is not None and etb is not None:
        if abs((eta - etb).total_seconds()) > 1800:
            return False
    return True


def dedupe_completed_trades_near_fills(trades: list, window_sec: float = 120.0, max_keep: int = 1000) -> list:
    """Collapse near-duplicate rows from CSV + log backfill + live close for the same exit."""
    if not trades:
        return []
    items = list(trades)
    n = len(items)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        for j in range(i + 1, n):
            if same_fill_event(items[i], items[j], window_sec):
                union(i, j)

    groups: dict = {}
    for i in range(n):
        r = find(i)
        groups.setdefault(r, []).append(items[i])

    out = [merge_trade_records(grp) for grp in groups.values()]
    out.sort(key=lambda x: normalize_trade_ts(x.get("exit_time")) or datetime.min)
    return out[-max_keep:]

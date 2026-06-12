import json
import os
import tempfile

import pandas as pd

from core.timeline import build_display_trail_series, load_trade_timeline_series


def _write_timeline(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def test_load_timeline_fuzzy_entry_match():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "open_trade_timeline.jsonl")
        _write_timeline(
            path,
            [
                {
                    "ts": "2026-06-11T11:19:00-04:00",
                    "direction": "SHORT",
                    "entry_time": "2026-06-11T11:28:32.960278",
                    "stop": 7408.5,
                    "tp": 7277.5,
                },
                {
                    "ts": "2026-06-11T11:25:00-04:00",
                    "direction": "SHORT",
                    "entry_time": "2026-06-11T11:28:32.960278",
                    "stop": 7395.0,
                    "tp": 7277.5,
                },
            ],
        )
        raw = load_trade_timeline_series(
            tmp,
            "2026-06-11 11:16:07",
            exit_time="2026-06-11 11:42:06",
            direction=-1,
        )
        assert raw is not None
        assert len(raw["times"]) == 2
        assert raw["stop"][1] == 7395.0


def test_build_display_trail_anchors_entry_exit():
    series = build_display_trail_series(
        "2026-06-11 10:11:07",
        "2026-06-11 10:24:06",
        stop_at_open=7390.0,
        stop_at_close=7396.25,
        timeline=None,
    )
    assert series is not None
    assert len(series["times"]) == 2
    assert series["stop"][0] == 7390.0
    assert series["stop"][1] == 7396.25


def test_build_display_trail_merges_timeline():
    et = pd.Timestamp("2026-06-11 13:39:07")
    xt = pd.Timestamp("2026-06-11 13:52:07")
    series = build_display_trail_series(
        et,
        xt,
        stop_at_open=7410.0,
        stop_at_close=7437.25,
        timeline={
            "times": ["2026-06-11T13:45:00-04:00"],
            "stop": [7420.0],
            "tp": [None],
        },
    )
    assert series is not None
    assert len(series["times"]) >= 3
    assert 7420.0 in series["stop"]

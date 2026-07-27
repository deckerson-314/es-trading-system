"""Reporting for SR Zones — reuse Trend dashboard generator with SR Zones labeling."""
from __future__ import annotations

import os
import webbrowser

from strategies.trend.reporting import (  # noqa: F401 — re-exported for backtest.py
    calculate_stats,
    generate_near_miss_plot,
    generate_trade_plot,
)
from strategies.trend import reporting as _trend_reporting


def group_params_for_display(params_dict_local):
    """Group SR Zones parameters into logical categories."""
    groups = {
        "Entry: Multi-zone S/R Breakout": [
            "Enable Long Trades",
            "Enable Short Trades",
            "Timeframe (minutes)",
            "Zone Width ATR Mult",
            "Strength Threshold",
            "Volume Mult",
            "Dissipation (per bar)",
            "Entry Headroom (ATR)",
            "Stop Pad ATR",
            "Max Hold (bars)",
            "Min Opposite Zone Dist (ATR)",
        ],
        "Filters": [
            "Enable RTH Filter",
            "RTH Start (HH:MM)",
            "RTH End (HH:MM)",
            "RTH Exit Buffer (minutes)",
            "Enable Maintenance Filter",
            "Daily Maintenance Start (HH:MM)",
            "Daily Maintenance End (HH:MM)",
            "Weekend Maintenance Start Day",
            "Weekend Maintenance Start Time (HH:MM)",
            "Weekend Maintenance End Day",
            "Weekend Maintenance End Time (HH:MM)",
            "Maintenance Buffer Minutes",
            "Maintenance Entry Buffer (minutes)",
        ],
        "Exit Logic": [
            "Enable Stop Loss",
            "Stop ATR Multiplier",
            "Enable Take Profit",
            "Take Profit ATR Multiplier",
            "Enable Trailing Stop",
            "Trailing Delay (bars)",
            "ATR Multiplier for Trailing Stop",
            "Enable Breakeven Stop",
            "Breakeven Trigger (ATR)",
            "Breakeven Pad (ATR)",
        ],
        "Risk / Costs": [
            "Max Open Trades",
            "Transaction Cost (Per Trade)",
        ],
        "GA Criteria": [
            "POP_SIZE",
            "NUM_GEN",
            "CX_PB",
            "MUT_PB",
            "DATA_SPLITS",
            "USE_INTERLEAVED_SPLIT",
            "NUM_SPLIT_PERIODS",
            "GA_START_DATE",
            "GA_END_DATE",
            "MIN_TRADES_DAY",
            "TARGET_TRADES_DAY",
        ],
    }

    grouped = {}
    for group_name, param_list in groups.items():
        grouped[group_name] = {k: v for k, v in params_dict_local.items() if k in param_list}

    all_grouped_keys = [k for group in grouped.values() for k in group.keys()]
    others = {
        k: v
        for k, v in params_dict_local.items()
        if k not in all_grouped_keys and not str(v).startswith("===")
    }
    if others:
        grouped["Other Parameters"] = others
    return grouped


def generate_dashboard(
    solutions_data,
    output_dir=None,
    version="5.0",
    open_browser=True,
    filename=None,
    include_attribution=True,
):
    """Generate the standard backtest dashboard (analytics + trades + charts)."""
    old_group = _trend_reporting.group_params_for_display
    _trend_reporting.group_params_for_display = group_params_for_display
    try:
        path = _trend_reporting.generate_dashboard(
            solutions_data,
            output_dir=output_dir,
            version=version,
            open_browser=False,
            filename=filename,
            include_attribution=include_attribution,
        )
    finally:
        _trend_reporting.group_params_for_display = old_group

    if path and os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        html = html.replace("Trend Strategy", "SR Zones Strategy")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)

    if open_browser and path:
        try:
            webbrowser.open(f"file://{os.path.abspath(path)}")
        except Exception:
            pass
    return path

"""
Phased GA helpers for Trend: freeze param subsets per phase (structure → exits).

Mirrors optimize.py gene detection (int/float with Min≠Max, excluding GA meta rows).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

# Keep in sync with optimize.py ga_criteria_params (non-genome configuration rows).
GA_CRITERIA_NAMES = frozenset(
    {
        "POP_SIZE",
        "NUM_GEN",
        "CX_PB",
        "MUT_PB",
        "MUT_MU",
        "MUT_SIGMA",
        "TARGET_TRADES_DAY",
        "TRADES_PENALTY_WEIGHT",
        "DD_WEIGHT",
        "DATA_SPLITS",
        "DATA_SIZE",
        "USE_INTERLEAVED_SPLIT",
        "NUM_SPLIT_PERIODS",
        "MIN_TRADES_DAY",
        "MIN_TRADES_PEN_WEIGHT",
        "GA_START_DATE",
        "GA_END_DATE",
        "GA_LIVE_STYLE_ENTRY",
        "GA_CONSERVATIVE_STOP_SLIPPAGE",
        "GA_PESSIMISTIC_STOPS",
        "WEIGHT_SORTINO",
        "WEIGHT_DRAWDOWN",
        "WEIGHT_PF",
        "WEIGHT_TRADES",
        "WEIGHT_PNL",
        "WEIGHT_PPT",
        "MIN_TRADE_DURATION",
        "MAX_WIN_RATE_CAP",
        "LIMIT_MAX_LOSS",
        "LIMIT_MIN_SORTINO",
        "NORM_SORTINO_MAX",
        "NORM_DD_MAX",
        "NORM_PF_MAX",
        "NORM_TRADES_MAX",
        "NORM_PNL_MAX",
        "NORM_PROFIT_TRADE_MAX",
        "MIN_WIN_RATE",
        "SORTINO_CAP",
        "ENABLE_FILTER_STACK_TRADE_PENALTY",
        "INTERACTION_PENALTY_STRENGTH",
        "INTERACTION_LOW_TRADES_BASE",
        "INTERACTION_LOW_TRADES_PER_FILTER",
        "INTERACTION_MIN_FILTERS",
    }
)

# Default phase splits (Trend). Override via JSON from CLI.
DEFAULT_PHASE_A: frozenset[str] = frozenset(
    {
        "Timeframe (minutes)",
        "Buy Lookback",
        "Sell Lookback",
        "Enable ADX Filter",
        "ADX Period",
        "Min ADX Threshold",
        "ATR Filter Period",
        "Min ATR (Points)",
        "Enable SMA Filter",
        "SMA Period",
        "Enable Volume Filter",
        "Volume MA Length",
        "Min Volume Multiplier",
        "Enable RSI Filter",
        "RSI Period",
        "RSI Max Buy Threshold",
        "RSI Min Sell Threshold",
        "Enable VWAP Filter",
        "Enable RTH Filter",
        "RTH Exit Buffer (minutes)",
    }
)

DEFAULT_PHASE_B: frozenset[str] = frozenset(
    {
        "Initial Stop Loss (%)",
        "Enable Trailing Stop",
        "ATR Length for Trailing Stop",
        "ATR Multiplier for Trailing Stop",
        "Trailing Delay (bars)",
        "Trailing Delay (minutes)",
        "Take Profit ATR Multiplier",
    }
)


def load_phase_sets_json(path: Path) -> tuple[frozenset[str], frozenset[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    a = frozenset(str(x) for x in data["phase_a"])
    b = frozenset(str(x) for x in data["phase_b"])
    return a, b


def is_optimizable_gene_row(row: pd.Series, ga_meta: frozenset[str] = GA_CRITERIA_NAMES) -> bool:
    name = row.get("Name")
    if pd.isna(name):
        return False
    name = str(name).strip()
    if not name or name.startswith("===") or name.startswith("---"):
        return False
    if name in ga_meta:
        return False
    typ = row.get("Type")
    if typ not in ("int", "float"):
        return False
    mn, mx = row.get("Min"), row.get("Max")
    if pd.isna(mn) or pd.isna(mx):
        return False
    try:
        return float(mn) != float(mx)
    except (TypeError, ValueError):
        return False


def _serialize_val(val: Any, typ: Any) -> Any:
    if pd.isna(val):
        return val
    if typ == "int":
        return int(round(float(val)))
    if typ == "float":
        return float(val)
    return val


def _parse_winner_cell(val: Any) -> Any:
    if isinstance(val, str):
        s = val.strip()
        if s.lower() in ("true", "false"):
            return s.lower() == "true"
        try:
            if "." in s:
                return float(s)
            return int(s)
        except ValueError:
            return val
    return val


def _ensure_mutable_param_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ("Value", "Min", "Max"):
        if col in out.columns:
            out[col] = out[col].astype(object)
    return out


def build_phase1_dataframe(base_df: pd.DataFrame, phase_a: frozenset[str]) -> pd.DataFrame:
    """Only phase_a genes keep Min/Max ranges; all other optimizable genes frozen at base Value."""
    out = _ensure_mutable_param_cols(base_df)
    base_by = base_df.set_index("Name", drop=False)
    for idx, row in out.iterrows():
        if not is_optimizable_gene_row(row):
            continue
        name = str(row["Name"]).strip()
        if name in phase_a:
            continue
        if name not in base_by.index:
            continue
        ref_val = base_by.loc[name, "Value"]
        typ = row.get("Type")
        v = _serialize_val(ref_val, typ)
        out.at[idx, "Value"] = v
        out.at[idx, "Min"] = v
        out.at[idx, "Max"] = v
    return out


def build_phase2_dataframe(
    base_df: pd.DataFrame,
    phase_a: frozenset[str],
    phase_b: frozenset[str],
    winner: dict[str, Any],
) -> pd.DataFrame:
    """
    Lock structure (phase_a) at winner values; restore phase_b ranges from base;
    freeze all other optimizable genes at base Value.
    """
    out = _ensure_mutable_param_cols(base_df)
    base_by = base_df.set_index("Name", drop=False)
    for idx, row in out.iterrows():
        if not is_optimizable_gene_row(row):
            continue
        name = str(row["Name"]).strip()
        typ = row.get("Type")
        if name in phase_a:
            if name not in winner:
                raise KeyError(f"Genetic winner missing required phase_a key {name!r}")
            v = _serialize_val(_parse_winner_cell(winner[name]), typ)
            out.at[idx, "Value"] = v
            out.at[idx, "Min"] = v
            out.at[idx, "Max"] = v
        elif name in phase_b:
            b = base_by.loc[name]
            out.at[idx, "Value"] = b["Value"]
            out.at[idx, "Min"] = b["Min"]
            out.at[idx, "Max"] = b["Max"]
        else:
            ref_val = base_by.loc[name, "Value"]
            v = _serialize_val(ref_val, typ)
            out.at[idx, "Value"] = v
            out.at[idx, "Min"] = v
            out.at[idx, "Max"] = v
    return out


def selected_solution_column(df: pd.DataFrame) -> str:
    cols = [c for c in df.columns if c.startswith("Solution_")]
    sel = [c for c in cols if c.endswith("_SELECTED")]
    if not cols:
        raise ValueError("No Solution_* columns in genetic results CSV")
    return sel[0] if sel else cols[0]


def winner_from_genetic_csv(path: Path) -> dict[str, Any]:
    df = pd.read_csv(path)
    col = selected_solution_column(df)
    win: dict[str, Any] = {}
    for _, row in df.iterrows():
        name = row.get("Name")
        if pd.isna(name):
            continue
        name = str(name).strip()
        if name.startswith("===") or name.startswith("---") or "__" in name:
            continue
        val = row.get(col)
        if pd.isna(val) or val == "":
            continue
        win[name] = val
    return win


def validate_disjoint(phase_a: frozenset[str], phase_b: frozenset[str]) -> None:
    inter = phase_a & phase_b
    if inter:
        raise ValueError(f"phase_a and phase_b overlap: {sorted(inter)}")

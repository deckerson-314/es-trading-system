"""Phased Trend GA CSV builders (strategies.trend.phased_search)."""

import os
import sys

import pandas as pd
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from strategies.trend.phased_search import (
    GA_CRITERIA_NAMES,
    build_phase1_dataframe,
    build_phase2_dataframe,
    is_optimizable_gene_row,
    validate_disjoint,
    winner_from_genetic_csv,
)


def test_is_optimizable_gene_row_smoke():
    df = pd.DataFrame(
        [
            {"Name": "Timeframe (minutes)", "Value": 10, "Min": 1, "Max": 15, "Type": "int"},
            {"Name": "POP_SIZE", "Value": 100, "Min": 50, "Max": 200, "Type": "int"},
            {"Name": "Enable Long Trades", "Value": True, "Min": None, "Max": None, "Type": "bool"},
        ]
    )
    assert is_optimizable_gene_row(df.iloc[0])
    assert not is_optimizable_gene_row(df.iloc[1])
    assert not is_optimizable_gene_row(df.iloc[2])


def test_build_phase1_freezes_non_active():
    base = pd.DataFrame(
        [
            {"Name": "Timeframe (minutes)", "Value": 11, "Min": 1, "Max": 15, "Type": "int"},
            {"Name": "Initial Stop Loss (%)", "Value": 0.5, "Min": 0.05, "Max": 5, "Type": "float"},
        ]
    )
    phase_a = frozenset({"Timeframe (minutes)"})
    out = build_phase1_dataframe(base, phase_a)
    tf = out[out["Name"] == "Timeframe (minutes)"].iloc[0]
    assert tf["Min"] == 1 and tf["Max"] == 15
    sl = out[out["Name"] == "Initial Stop Loss (%)"].iloc[0]
    assert sl["Min"] == sl["Max"] == pytest.approx(0.5)


def test_build_phase2_locks_a_and_opens_b():
    base = pd.DataFrame(
        [
            {"Name": "Timeframe (minutes)", "Value": 11, "Min": 1, "Max": 15, "Type": "int"},
            {"Name": "Initial Stop Loss (%)", "Value": 0.5, "Min": 0.05, "Max": 5, "Type": "float"},
        ]
    )
    phase_a = frozenset({"Timeframe (minutes)"})
    phase_b = frozenset({"Initial Stop Loss (%)"})
    winner = {"Timeframe (minutes)": 12, "Initial Stop Loss (%)": 9.9}
    out = build_phase2_dataframe(base, phase_a, phase_b, winner)
    tf = out[out["Name"] == "Timeframe (minutes)"].iloc[0]
    assert int(tf["Value"]) == 12
    assert int(tf["Min"]) == 12 and int(tf["Max"]) == 12
    sl = out[out["Name"] == "Initial Stop Loss (%)"].iloc[0]
    assert sl["Min"] == 0.05 and sl["Max"] == 5 and sl["Value"] == 0.5


def test_build_phase2_missing_winner_raises():
    base = pd.DataFrame(
        [{"Name": "Timeframe (minutes)", "Value": 11, "Min": 1, "Max": 15, "Type": "int"}]
    )
    with pytest.raises(KeyError):
        build_phase2_dataframe(base, frozenset({"Timeframe (minutes)"}), frozenset(), {})


def test_validate_disjoint_rejects_overlap():
    with pytest.raises(ValueError, match="overlap"):
        validate_disjoint(frozenset({"a", "b"}), frozenset({"b"}))


def test_winner_from_genetic_csv(tmp_path):
    p = tmp_path / "g.csv"
    p.write_text(
        "Name,Value,Solution_0_SELECTED\n"
        "Timeframe (minutes),0,12\n"
        "=== SOLUTION STATISTICS ===,,\n",
        encoding="utf-8",
    )
    w = winner_from_genetic_csv(p)
    assert w["Timeframe (minutes)"] == 12


def test_ga_criteria_includes_interaction_keys():
    assert "ENABLE_FILTER_STACK_TRADE_PENALTY" in GA_CRITERIA_NAMES

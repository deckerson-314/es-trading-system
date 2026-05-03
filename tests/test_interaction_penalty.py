"""Filter-stack vs low-trade interaction penalty (optimize.core_evaluate helpers)."""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import optimize as o


def test_count_enabled_stack_filters_params_override_template():
    params = {'Enable ADX Filter': 1, 'Enable RSI Filter': 0}
    pd = {
        'Enable ADX Filter': {'value': 0},
        'Enable RSI Filter': {'value': 1},
    }
    assert o.count_enabled_stack_filters(params, pd) == 1


def test_count_enabled_stack_filters_defaults_from_template():
    params = {}
    pd = {
        'Enable ADX Filter': {'value': 1},
        'Enable Maintenance Filter': {'value': 0},
    }
    assert o.count_enabled_stack_filters(params, pd) == 1


def test_filter_stack_trade_penalty_multiplier_inactive():
    assert (
        o.filter_stack_trade_penalty_multiplier(
            avg_trades_day=0.1,
            filter_count=1,
            strength=0.5,
            base=0.2,
            per_filter=0.15,
            min_filters=2,
        )
        == 1.0
    )


def test_filter_stack_trade_penalty_multiplier_hits():
    # k=3, base=0.2, per=0.15 -> expected=0.65; atd=0.35 -> shortfall 0.3, rel=0.3/0.65, strength 0.5
    m = o.filter_stack_trade_penalty_multiplier(
        avg_trades_day=0.35,
        filter_count=3,
        strength=0.5,
        base=0.2,
        per_filter=0.15,
        min_filters=2,
    )
    rel = min(1.0, 0.3 / 0.65)
    assert m == pytest.approx(1.0 - 0.5 * rel)


def test_filter_stack_trade_penalty_multiplier_no_shortfall():
    assert (
        o.filter_stack_trade_penalty_multiplier(
            avg_trades_day=2.0,
            filter_count=4,
            strength=0.9,
            base=0.1,
            per_filter=0.1,
            min_filters=2,
        )
        == 1.0
    )

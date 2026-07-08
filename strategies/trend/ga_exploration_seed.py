"""Stratified initial-population seeds for Trend GA exploration runs."""

from __future__ import annotations

import random
from typing import Any

# Each archetype samples uniform random within the listed (lo, hi) for genes present in param_keys.
TREND_EXPLORATION_ARCHETYPES: list[dict[str, tuple[float, float]]] = [
    {
        "name": "fast_core",
        "Timeframe (minutes)": (8, 11),
        "Buy Lookback (minutes)": (90, 150),
        "Sell Lookback (minutes)": (90, 150),
        "Trailing Delay (bars)": (4, 6),
        "Take Profit ATR Multiplier": (0, 0),
        "ATR Multiplier for Trailing Stop": (2.5, 3.5),
        "Initial Stop Loss (%)": (0.35, 0.7),
        "Channel Exit Sell Lookback (bars)": (5, 9),
        "Channel Exit Buy Lookback (bars)": (5, 9),
        "Enable Trailing Stop": (1, 1),
    },
    {
        "name": "live_clock",
        "Timeframe (minutes)": (12, 14),
        "Buy Lookback (minutes)": (120, 240),
        "Sell Lookback (minutes)": (120, 240),
        "Trailing Delay (bars)": (5, 8),
        "Take Profit ATR Multiplier": (0, 0),
        "ATR Multiplier for Trailing Stop": (3.0, 4.5),
        "Initial Stop Loss (%)": (0.4, 0.9),
        "Channel Exit Sell Lookback (bars)": (7, 12),
        "Channel Exit Buy Lookback (bars)": (7, 12),
        "Enable Trailing Stop": (1, 1),
    },
    {
        "name": "slow_swing",
        "Timeframe (minutes)": (14, 16),
        "Buy Lookback (minutes)": (240, 360),
        "Sell Lookback (minutes)": (240, 360),
        "Trailing Delay (bars)": (7, 10),
        "Take Profit ATR Multiplier": (0, 1.0),
        "ATR Multiplier for Trailing Stop": (3.5, 5.0),
        "Initial Stop Loss (%)": (0.6, 1.2),
        "Channel Exit Sell Lookback (bars)": (10, 15),
        "Channel Exit Buy Lookback (bars)": (10, 15),
        "Enable Trailing Stop": (1, 1),
    },
    {
        "name": "channel_primary",
        "Timeframe (minutes)": (10, 13),
        "Buy Lookback (minutes)": (150, 300),
        "Sell Lookback (minutes)": (150, 300),
        "Trailing Delay (bars)": (6, 9),
        "Take Profit ATR Multiplier": (0, 0),
        "ATR Multiplier for Trailing Stop": (3.0, 4.0),
        "Initial Stop Loss (%)": (0.5, 1.0),
        "Channel Exit Sell Lookback (bars)": (8, 15),
        "Channel Exit Buy Lookback (bars)": (8, 15),
        "Enable Trailing Stop": (0, 0),
    },
    {
        "name": "wide_stop_patient",
        "Timeframe (minutes)": (11, 15),
        "Buy Lookback (minutes)": (180, 320),
        "Sell Lookback (minutes)": (180, 320),
        "Trailing Delay (bars)": (6, 10),
        "Take Profit ATR Multiplier": (0, 0),
        "ATR Multiplier for Trailing Stop": (4.0, 5.0),
        "Initial Stop Loss (%)": (0.9, 1.5),
        "Channel Exit Sell Lookback (bars)": (6, 12),
        "Channel Exit Buy Lookback (bars)": (6, 12),
        "Enable Trailing Stop": (1, 1),
    },
]


def _sample_gene(lo: float, hi: float, typ: str) -> float | int:
    val = random.uniform(lo, hi)
    if typ == "int":
        return int(round(val))
    return float(val)


def apply_archetype_to_individual(
    ind: list,
    archetype: dict[str, tuple[float, float]],
    param_keys: list[str],
    param_dict: dict[str, Any],
    clamp_fn,
) -> None:
    """Overwrite optimizable genes on ``ind`` from an archetype range map."""
    key_index = {k: i for i, k in enumerate(param_keys)}
    for gene, bounds in archetype.items():
        if gene == "name" or gene not in key_index:
            continue
        meta = param_dict.get(gene, {})
        lo, hi = bounds
        # Respect CSV bounds (archetype may be narrower).
        csv_lo, csv_hi = meta.get("min"), meta.get("max")
        if csv_lo is not None and csv_hi is not None:
            lo = max(float(lo), float(csv_lo))
            hi = min(float(hi), float(csv_hi))
        if lo > hi:
            lo, hi = float(csv_lo), float(csv_hi)
        typ = meta.get("type", "float")
        ind[key_index[gene]] = _sample_gene(lo, hi, typ)
    clamp_fn(ind)


def diversify_initial_population(
    pop: list,
    param_keys: list[str],
    param_dict: dict[str, Any],
    clamp_fn,
    fraction: float = 0.6,
) -> int:
    """
    Replace the first ``fraction`` of *pop* with stratified archetype seeds.

    Returns the number of individuals seeded.
    """
    if not pop or not param_keys:
        return 0
    fraction = max(0.0, min(1.0, float(fraction)))
    n_seed = int(len(pop) * fraction)
    if n_seed <= 0:
        return 0
    archetypes = TREND_EXPLORATION_ARCHETYPES
    per_arch = max(1, n_seed // len(archetypes))
    idx = 0
    seeded = 0
    for arch in archetypes:
        for _ in range(per_arch):
            if idx >= n_seed:
                break
            apply_archetype_to_individual(pop[idx], arch, param_keys, param_dict, clamp_fn)
            idx += 1
            seeded += 1
    # Fill any remainder with random archetype picks.
    while idx < n_seed:
        arch = random.choice(archetypes)
        apply_archetype_to_individual(pop[idx], arch, param_keys, param_dict, clamp_fn)
        idx += 1
        seeded += 1
    return seeded

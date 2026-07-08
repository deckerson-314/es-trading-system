"""
Trade attribution: four-quadrant entry/exit decomposition + MFE/MAE diagnostics.

Industry alignment:
  - Brinson-style attribution separates *selection* (entry) from *timing* (exit).
  - MAE/MFE excursion analysis (TradeVis, RustyBT trade_analysis) diagnoses stop/TP.
  - Random-entry / coin-flip null benchmarks test whether edge is skill vs friction.

Quadrants (2x2 factorial on entry vs exit policy):

  SS  Strategy Entry / Strategy Exit   — actual backtest or live export
  SR  Strategy Entry / Random Exit      — same entries; time-based exit @ close
  RS  Random Entry / Hold-Matched Exit — random OOS entries; strategy hold lengths
  RR  Random Entry / Random Exit        — Monte Carlo null (matched trade count)

Note: True "Random Entry + Strategy Exit Rules" (path-dependent stops on random
entries) requires exit-engine replay; see docs/strategy_attribution_analysis.md.
"""
from __future__ import annotations

import json
import random
import statistics
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

# Minimum excursion (ES points) before "first touch" timing is recorded.
MIN_EXCURSION_PTS = 0.25


class Quadrant(str, Enum):
    SS = "SS"  # strategy entry, strategy exit
    SR = "SR"  # strategy entry, random exit
    RS = "RS"  # random entry, hold-matched exit (proxy for entry selection)
    RR = "RR"  # random entry, random exit


@dataclass
class AttributionConfig:
    point_multiplier: float = 50.0
    transaction_cost: float = 15.0
    mc_runs: int = 200
    seed: int = 42
    min_excursion_pts: float = MIN_EXCURSION_PTS


@dataclass
class TradeLeg:
    """One round-trip leg with optional excursion enrichment."""

    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    direction: int  # 1 long, -1 short
    quadrant: Quadrant
    reason: str = ""
    hold_minutes: float = 0.0
    pnl_pts: float = 0.0
    pnl_usd: float = 0.0
    mfe_pts: float = 0.0
    mae_pts: float = 0.0
    mfe_minutes: float = 0.0
    mae_minutes: float = 0.0
    mae_before_mfe: bool = False
    capture_ratio: float = 0.0

    def compute_pnl(self, cfg: AttributionConfig) -> None:
        self.pnl_pts = (self.exit_price - self.entry_price) * self.direction
        self.pnl_usd = self.pnl_pts * cfg.point_multiplier - cfg.transaction_cost
        if self.entry_time is not None and self.exit_time is not None:
            delta = self.exit_time - self.entry_time
            self.hold_minutes = max(0.0, delta.total_seconds() / 60.0)


@dataclass
class QuadrantStats:
    quadrant: str
    label: str
    trade_count: int
    net_pnl_usd: float
    gross_profit_usd: float
    gross_loss_usd: float
    win_rate: float
    profit_factor: float
    expectancy_usd: float
    avg_hold_minutes: float
    mfe_median_pts: float
    mae_median_pts: float
    mfe_mae_ratio: float
    capture_ratio_median: float
    pct_mae_before_mfe: float
    mfe_minutes_median: float
    mae_minutes_median: float
    pct_mfe_gt_5_close_neg: float
    friction_floor_usd: float
    mc_median_usd: float | None = None
    mc_p5_usd: float | None = None
    mc_p95_usd: float | None = None
    mc_pct_positive: float | None = None


@dataclass
class DirectionDiagnostics:
    """Entry-direction quality at fixed strategy entry/exit windows (SS only)."""

    pct_strategy_beats_opposite: float
    median_edge_pts: float
    opposite_net_pnl_usd: float
    coinflip_mc_median_usd: float
    coinflip_mc_pct_positive: float


@dataclass
class AttributionReport:
    source: str
    trade_count: int
    config: AttributionConfig
    quadrants: dict[str, QuadrantStats] = field(default_factory=dict)
    direction: DirectionDiagnostics | None = None
    horizon_edges: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "source": self.source,
            "trade_count": self.trade_count,
            "config": asdict(self.config),
            "quadrants": {k: asdict(v) for k, v in self.quadrants.items()},
            "direction": asdict(self.direction) if self.direction else None,
            "horizon_edges": self.horizon_edges,
            "notes": self.notes,
        }
        return d


def nearest_index(idx: pd.DatetimeIndex, ts: pd.Timestamp) -> pd.Timestamp:
    if ts in idx:
        return ts
    pos = idx.get_indexer([ts], method="nearest")[0]
    if pos < 0:
        raise KeyError(f"Timestamp {ts} not in index")
    return idx[pos]


def load_trades_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["direction"] = df["direction"].astype(int)
    df["entry_price"] = pd.to_numeric(df["entry_price"])
    df["exit_price"] = pd.to_numeric(df["exit_price"])
    if "pnl" in df.columns:
        df["pnl"] = pd.to_numeric(df["pnl"])
    if "reason" not in df.columns:
        df["reason"] = ""
    return df


def trades_to_ss_legs(trades: pd.DataFrame, cfg: AttributionConfig) -> list[TradeLeg]:
    legs: list[TradeLeg] = []
    for _, row in trades.iterrows():
        leg = TradeLeg(
            entry_time=row["entry_time"],
            exit_time=row["exit_time"],
            entry_price=float(row["entry_price"]),
            exit_price=float(row["exit_price"]),
            direction=int(row["direction"]),
            quadrant=Quadrant.SS,
            reason=str(row.get("reason", "")),
        )
        leg.compute_pnl(cfg)
        legs.append(leg)
    return legs


def excursion_window(
    ohlcv: pd.DataFrame,
    entry_ts: pd.Timestamp,
    exit_ts: pd.Timestamp,
    entry_px: float,
    direction: int,
    min_pts: float = MIN_EXCURSION_PTS,
) -> tuple[float, float, float, float, bool]:
    """
    Return MFE pts, MAE pts, minutes-to-MFE, minutes-to-MAE, mae_before_mfe.
    """
    idx = ohlcv.index
    entry_ts = nearest_index(idx, entry_ts)
    exit_ts = nearest_index(idx, exit_ts)
    w = ohlcv.loc[entry_ts:exit_ts]
    if w.empty:
        return 0.0, 0.0, 0.0, 0.0, False

    mfe = 0.0
    mae = 0.0
    t_mfe: pd.Timestamp | None = None
    t_mae: pd.Timestamp | None = None

    for ts, row in w.iterrows():
        hi, lo = float(row["high"]), float(row["low"])
        if direction == 1:
            fav, adv = hi - entry_px, entry_px - lo
        else:
            fav, adv = entry_px - lo, hi - entry_px
        if fav > mfe:
            mfe = fav
            t_mfe = ts
        if adv > mae:
            mae = adv
            t_mae = ts

    first_mfe_t: pd.Timestamp | None = None
    first_mae_t: pd.Timestamp | None = None
    for ts, row in w.iterrows():
        hi, lo = float(row["high"]), float(row["low"])
        if direction == 1:
            fav, adv = hi - entry_px, entry_px - lo
        else:
            fav, adv = entry_px - lo, hi - entry_px
        if first_mfe_t is None and fav >= min_pts:
            first_mfe_t = ts
        if first_mae_t is None and adv >= min_pts:
            first_mae_t = ts
        if first_mfe_t is not None and first_mae_t is not None:
            break

    mfe_min = (t_mfe - entry_ts).total_seconds() / 60.0 if t_mfe else 0.0
    mae_min = (t_mae - entry_ts).total_seconds() / 60.0 if t_mae else 0.0
    mae_first = (
        first_mae_t is not None
        and first_mfe_t is not None
        and first_mae_t <= first_mfe_t
    )
    return mfe, mae, mfe_min, mae_min, mae_first


def enrich_legs(ohlcv: pd.DataFrame, legs: Sequence[TradeLeg], cfg: AttributionConfig) -> None:
    for leg in legs:
        mfe, mae, mfe_m, mae_m, mae_first = excursion_window(
            ohlcv,
            leg.entry_time,
            leg.exit_time,
            leg.entry_price,
            leg.direction,
            cfg.min_excursion_pts,
        )
        leg.mfe_pts = mfe
        leg.mae_pts = mae
        leg.mfe_minutes = mfe_m
        leg.mae_minutes = mae_m
        leg.mae_before_mfe = mae_first
        if mfe > cfg.min_excursion_pts:
            leg.capture_ratio = max(-1.0, min(1.0, leg.pnl_pts / mfe))
        else:
            leg.capture_ratio = 0.0


def exit_at_hold(
    ohlcv: pd.DataFrame,
    entry_ts: pd.Timestamp,
    entry_px: float,
    direction: int,
    hold_minutes: float,
    cfg: AttributionConfig,
) -> TradeLeg:
    idx = ohlcv.index
    entry_ts = nearest_index(idx, entry_ts)
    hold_bars = max(1, int(round(hold_minutes)))
    entry_loc = idx.get_loc(entry_ts)
    if isinstance(entry_loc, slice):
        entry_loc = entry_loc.start or 0
    exit_loc = min(len(idx) - 1, entry_loc + hold_bars)
    exit_ts = idx[exit_loc]
    exit_px = float(ohlcv.iloc[exit_loc]["close"])
    leg = TradeLeg(
        entry_time=entry_ts,
        exit_time=exit_ts,
        entry_price=entry_px,
        exit_price=exit_px,
        direction=direction,
        quadrant=Quadrant.SR,
    )
    leg.compute_pnl(cfg)
    return leg


def build_sr_legs(
    ss_legs: Sequence[TradeLeg],
    ohlcv: pd.DataFrame,
    cfg: AttributionConfig,
    rng: random.Random,
) -> list[TradeLeg]:
    """Strategy entry + random hold from empirical distribution, exit @ close."""
    holds = [max(1.0, leg.hold_minutes) for leg in ss_legs]
    legs: list[TradeLeg] = []
    for leg in ss_legs:
        hold = rng.choice(holds)
        out = exit_at_hold(
            ohlcv, leg.entry_time, leg.entry_price, leg.direction, hold, cfg
        )
        out.quadrant = Quadrant.SR
        legs.append(out)
    return legs


def sample_non_overlapping_entries(
    ohlcv: pd.DataFrame,
    oos_mask: pd.Series,
    n_trades: int,
    max_hold_minutes: float,
    rng: random.Random,
) -> list[tuple[pd.Timestamp, float]]:
    """Return (entry_ts, entry_close) for random OOS entries."""
    oos_df = ohlcv.loc[oos_mask]
    if oos_df.empty:
        return []
    n = len(oos_df)
    max_hold = max(60, int(max_hold_minutes * 2))
    indices = list(range(0, max(1, n - max_hold)))
    rng.shuffle(indices)
    picks: list[tuple[pd.Timestamp, float]] = []
    last_exit = -1
    for i in indices:
        if len(picks) >= n_trades:
            break
        if i <= last_exit:
            continue
        picks.append((oos_df.index[i], float(oos_df.iloc[i]["close"])))
        last_exit = i + max_hold
    return picks


def build_rs_legs(
    ss_legs: Sequence[TradeLeg],
    ohlcv: pd.DataFrame,
    oos_mask: pd.Series,
    cfg: AttributionConfig,
    rng: random.Random,
) -> list[TradeLeg]:
    """Random entry/direction per paired SS trade; hold matched; exit @ close."""
    oos_df = ohlcv.loc[oos_mask]
    if oos_df.empty:
        return []
    n_oos = len(oos_df)
    max_hold = max(1, int(max(max(1.0, leg.hold_minutes) for leg in ss_legs)))
    # Leave room for hold from sampled entry bar.
    max_start = max(0, n_oos - max_hold - 1)
    legs: list[TradeLeg] = []
    for ss_leg in ss_legs:
        hold = max(1.0, ss_leg.hold_minutes)
        start_hi = max(0, n_oos - int(round(hold)) - 1)
        j = rng.randint(0, start_hi) if start_hi > 0 else 0
        entry_ts = oos_df.index[j]
        entry_px = float(oos_df.iloc[j]["close"])
        direction = rng.choice([-1, 1])
        out = exit_at_hold(ohlcv, entry_ts, entry_px, direction, hold, cfg)
        out.quadrant = Quadrant.RS
        legs.append(out)
    return legs


def simulate_rr_mc(
    ohlcv: pd.DataFrame,
    oos_mask: pd.Series,
    n_trades: int,
    hold_median: float,
    hold_spread: float,
    cfg: AttributionConfig,
    rng: random.Random,
) -> float:
    """Single MC run: random entry, direction, hold; return total USD PnL."""
    oos_df = ohlcv.loc[oos_mask]
    if oos_df.empty or n_trades <= 0:
        return 0.0
    n = len(oos_df)
    max_hold = max(60, int(hold_median + 2 * hold_spread))
    indices = list(range(0, max(1, n - max_hold)))
    rng.shuffle(indices)
    total = 0.0
    count = 0
    last_exit = -1
    for i in indices:
        if count >= n_trades:
            break
        if i <= last_exit:
            continue
        hold = max(1, int(round(rng.gauss(hold_median, hold_spread))))
        hold = min(hold, n - i - 1)
        if hold < 1:
            continue
        direction = rng.choice([-1, 1])
        entry_px = float(oos_df.iloc[i]["close"])
        exit_px = float(oos_df.iloc[i + hold]["close"])
        total += (exit_px - entry_px) * direction * cfg.point_multiplier - cfg.transaction_cost
        count += 1
        last_exit = i + hold
    return float(total)


def aggregate_quadrant(
    legs: Sequence[TradeLeg],
    quadrant: Quadrant,
    label: str,
    cfg: AttributionConfig,
    mc_totals: list[float] | None = None,
) -> QuadrantStats:
    pnls = [leg.pnl_usd for leg in legs]
    n = len(pnls)
    mc_med = mc_p5 = mc_p95 = mc_pct = None
    if mc_totals:
        mc_sorted = sorted(mc_totals)
        mc_med = statistics.median(mc_totals)
        mc_p5 = mc_sorted[int(0.05 * len(mc_sorted))]
        mc_p95 = mc_sorted[int(0.95 * len(mc_sorted))]
        mc_pct = 100.0 * sum(1 for x in mc_totals if x > 0) / len(mc_totals)

    if n == 0:
        return QuadrantStats(
            quadrant=quadrant.value,
            label=label,
            trade_count=0,
            net_pnl_usd=mc_med or 0.0,
            gross_profit_usd=0.0,
            gross_loss_usd=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            expectancy_usd=0.0,
            avg_hold_minutes=0.0,
            mfe_median_pts=0.0,
            mae_median_pts=0.0,
            mfe_mae_ratio=0.0,
            capture_ratio_median=0.0,
            pct_mae_before_mfe=0.0,
            mfe_minutes_median=0.0,
            mae_minutes_median=0.0,
            pct_mfe_gt_5_close_neg=0.0,
            friction_floor_usd=0.0,
            mc_median_usd=mc_med,
            mc_p5_usd=mc_p5,
            mc_p95_usd=mc_p95,
            mc_pct_positive=mc_pct,
        )

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    pf = gross_profit / abs(gross_loss) if losses else float("inf")

    mfes = [leg.mfe_pts for leg in legs]
    maes = [leg.mae_pts for leg in legs]
    med_mfe = statistics.median(mfes)
    med_mae = statistics.median(maes)
    captures = [leg.capture_ratio for leg in legs if leg.mfe_pts > cfg.min_excursion_pts]

    return QuadrantStats(
        quadrant=quadrant.value,
        label=label,
        trade_count=n,
        net_pnl_usd=sum(pnls),
        gross_profit_usd=gross_profit,
        gross_loss_usd=gross_loss,
        win_rate=100.0 * len(wins) / n,
        profit_factor=pf if pf != float("inf") else 999.0,
        expectancy_usd=statistics.mean(pnls),
        avg_hold_minutes=statistics.mean(leg.hold_minutes for leg in legs),
        mfe_median_pts=med_mfe,
        mae_median_pts=med_mae,
        mfe_mae_ratio=med_mfe / max(med_mae, 0.01),
        capture_ratio_median=statistics.median(captures) if captures else 0.0,
        pct_mae_before_mfe=100.0 * sum(1 for leg in legs if leg.mae_before_mfe) / n,
        mfe_minutes_median=statistics.median(leg.mfe_minutes for leg in legs),
        mae_minutes_median=statistics.median(leg.mae_minutes for leg in legs),
        pct_mfe_gt_5_close_neg=100.0
        * sum(1 for leg in legs if leg.mfe_pts > 5 and leg.pnl_pts < 0)
        / n,
        friction_floor_usd=-cfg.transaction_cost * n,
        mc_median_usd=mc_med,
        mc_p5_usd=mc_p5,
        mc_p95_usd=mc_p95,
        mc_pct_positive=mc_pct,
    )


def direction_diagnostics(
    ss_legs: Sequence[TradeLeg],
    cfg: AttributionConfig,
    rng: random.Random,
    mc_runs: int,
) -> DirectionDiagnostics:
    strat_pts = [leg.pnl_pts for leg in ss_legs]
    opp_pts = [
        (leg.exit_price - leg.entry_price) * (-leg.direction) for leg in ss_legs
    ]
    beats = sum(1 for s, o in zip(strat_pts, opp_pts) if s > o)
    opp_net = sum(o * cfg.point_multiplier - cfg.transaction_cost for o in opp_pts)

    mc_totals: list[float] = []
    for _ in range(mc_runs):
        total = 0.0
        for leg in ss_legs:
            fd = rng.choice([-1, 1])
            pts = (leg.exit_price - leg.entry_price) * fd
            total += pts * cfg.point_multiplier - cfg.transaction_cost
        mc_totals.append(total)

    return DirectionDiagnostics(
        pct_strategy_beats_opposite=100.0 * beats / max(len(ss_legs), 1),
        median_edge_pts=statistics.median(s - o for s, o in zip(strat_pts, opp_pts)),
        opposite_net_pnl_usd=opp_net,
        coinflip_mc_median_usd=statistics.median(mc_totals),
        coinflip_mc_pct_positive=100.0 * sum(1 for x in mc_totals if x > 0) / mc_runs,
    )


def horizon_edges(
    ohlcv: pd.DataFrame,
    ss_legs: Sequence[TradeLeg],
    horizons_min: Iterable[int] = (30, 60, 120, 240, 480),
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mins in horizons_min:
        strat_close: list[float] = []
        opp_close: list[float] = []
        for leg in ss_legs:
            end_ts = leg.entry_time + pd.Timedelta(minutes=mins)
            w = ohlcv.loc[leg.entry_time:end_ts]
            if w.empty:
                continue
            close = float(w["close"].iloc[-1])
            strat_close.append((close - leg.entry_price) * leg.direction)
            opp_close.append((close - leg.entry_price) * (-leg.direction))
        if not strat_close:
            continue
        edge = statistics.median(s - o for s, o in zip(strat_close, opp_close))
        rows.append(
            {
                "horizon_minutes": mins,
                "median_close_pts_strategy": statistics.median(strat_close),
                "median_close_pts_opposite": statistics.median(opp_close),
                "median_edge_pts": edge,
            }
        )
    return rows


def run_attribution(
    trades: pd.DataFrame,
    ohlcv: pd.DataFrame,
    oos_mask: pd.Series | None = None,
    *,
    source: str = "",
    cfg: AttributionConfig | None = None,
) -> AttributionReport:
    cfg = cfg or AttributionConfig()
    # Independent RNG streams per quadrant (SR must not consume RS draws).
    rng_sr = random.Random(cfg.seed + 1)
    rng_rs = random.Random(cfg.seed + 3)
    rng_rr = random.Random(cfg.seed + 4)

    if oos_mask is None:
        oos_mask = pd.Series(True, index=ohlcv.index)

    ss_legs = trades_to_ss_legs(trades, cfg)
    enrich_legs(ohlcv, ss_legs, cfg)

    sr_legs = build_sr_legs(ss_legs, ohlcv, cfg, rng_sr)
    enrich_legs(ohlcv, sr_legs, cfg)

    rs_legs = build_rs_legs(ss_legs, ohlcv, oos_mask, cfg, rng_rs)
    enrich_legs(ohlcv, rs_legs, cfg)

    hold_med = statistics.median(max(1.0, leg.hold_minutes) for leg in ss_legs)
    hold_spread = max(30.0, hold_med * 0.35)
    rr_mc: list[float] = []
    for _ in range(cfg.mc_runs):
        rr_mc.append(
            simulate_rr_mc(
                ohlcv,
                oos_mask,
                len(ss_legs),
                hold_med,
                hold_spread,
                cfg,
                rng_rr,
            )
        )

    sr_mc: list[float] = []
    rng_sr_mc = random.Random(cfg.seed + 1)
    for _ in range(cfg.mc_runs):
        batch = build_sr_legs(ss_legs, ohlcv, cfg, rng_sr_mc)
        sr_mc.append(sum(leg.pnl_usd for leg in batch))

    rs_mc: list[float] = []
    rng_rs_mc = random.Random(cfg.seed + 3)
    for _ in range(cfg.mc_runs):
        batch = build_rs_legs(ss_legs, ohlcv, oos_mask, cfg, rng_rs_mc)
        rs_mc.append(sum(leg.pnl_usd for leg in batch))

    report = AttributionReport(
        source=source or "trades",
        trade_count=len(ss_legs),
        config=cfg,
        direction=direction_diagnostics(ss_legs, cfg, random.Random(cfg.seed + 2), cfg.mc_runs),
        horizon_edges=horizon_edges(ohlcv, ss_legs),
        notes=[
            "SS = actual strategy entry and exit (exported trades).",
            "SR = strategy entry with random hold from empirical distribution; exit at bar close.",
            "RS = random OOS entry/direction with hold matched to paired strategy trade; exit at bar close.",
            "RR = Monte Carlo random entry, direction, and hold (matched count and hold distribution).",
            "Path-dependent strategy exits on random entries require exit-engine replay (future work).",
        ],
    )

    report.quadrants = {
        "SS": aggregate_quadrant(
            ss_legs,
            Quadrant.SS,
            "Strategy Entry / Strategy Exit",
            cfg,
        ),
        "SR": aggregate_quadrant(
            sr_legs,
            Quadrant.SR,
            "Strategy Entry / Random Exit",
            cfg,
            mc_totals=sr_mc,
        ),
        "RS": aggregate_quadrant(
            rs_legs,
            Quadrant.RS,
            "Random Entry / Hold-Matched Exit",
            cfg,
            mc_totals=rs_mc,
        ),
        "RR": aggregate_quadrant(
            [],
            Quadrant.RR,
            "Random Entry / Random Exit",
            cfg,
            mc_totals=rr_mc,
        ),
    }
    # MC-null quadrants use median total PnL as point estimate (not a single lucky draw).
    n_trades = len(ss_legs)
    friction = -cfg.transaction_cost * n_trades
    rr = report.quadrants["RR"]
    rr.trade_count = n_trades
    rr.net_pnl_usd = rr.mc_median_usd or 0.0
    rr.expectancy_usd = (rr.mc_median_usd or 0.0) / max(n_trades, 1)
    rr.friction_floor_usd = friction

    rs = report.quadrants["RS"]
    if rs.mc_median_usd is not None:
        rs.net_pnl_usd = rs.mc_median_usd
        rs.expectancy_usd = rs.mc_median_usd / max(n_trades, 1)

    sr = report.quadrants["SR"]
    if sr.mc_median_usd is not None:
        sr.net_pnl_usd = sr.mc_median_usd
        sr.expectancy_usd = sr.mc_median_usd / max(n_trades, 1)

    return report


def format_quadrant_table(report: AttributionReport) -> str:
    lines = [
        "| Quadrant | Label | Trades | Net PnL | Win% | PF | MFE med | MAE med | Capture |",
        "|----------|-------|--------|---------|------|-----|---------|---------|---------|",
    ]
    for key in ("SS", "SR", "RS", "RR"):
        q = report.quadrants[key]
        pnl = f"${q.net_pnl_usd:,.0f}"
        if key in ("SR", "RS", "RR") and q.mc_median_usd is not None:
            pnl = f"${q.mc_median_usd:,.0f} (MC med)"
        cap = f"{q.capture_ratio_median:.2f}" if key != "RR" else "n/a"
        mfe = f"{q.mfe_median_pts:.1f}" if key != "RR" else "n/a"
        mae = f"{q.mae_median_pts:.1f}" if key != "RR" else "n/a"
        pf = f"{q.profit_factor:.2f}" if key != "RR" else "n/a"
        wr = f"{q.win_rate:.1f}%" if key != "RR" else f"{q.mc_pct_positive:.1f}%+"
        lines.append(
            f"| {q.quadrant} | {q.label} | {q.trade_count} | {pnl} | {wr} | {pf} | {mfe} | {mae} | {cap} |"
        )
    return "\n".join(lines)


def format_report_text(report: AttributionReport) -> str:
    lines = [
        "=" * 72,
        "STRATEGY ATTRIBUTION REPORT (Four-Quadrant Entry/Exit Decomposition)",
        "=" * 72,
        f"Source: {report.source}",
        f"Trades: {report.trade_count}",
        f"MC runs: {report.config.mc_runs}  |  Cost/trade: ${report.config.transaction_cost:.0f}",
        "",
        format_quadrant_table(report),
        "",
        "--- Quadrant detail ---",
    ]
    for key in ("SS", "SR", "RS", "RR"):
        q = report.quadrants[key]
        lines.append(f"\n[{q.quadrant}] {q.label}")
        lines.append(f"  Net PnL:        ${q.net_pnl_usd:,.0f}")
        lines.append(f"  Friction floor: ${q.friction_floor_usd:,.0f}")
        if q.mc_median_usd is not None:
            lines.append(
                f"  MC median:      ${q.mc_median_usd:,.0f}  "
                f"(p5 ${q.mc_p5_usd:,.0f}, p95 ${q.mc_p95_usd:,.0f}, "
                f"{q.mc_pct_positive:.1f}% positive)"
            )
        if key != "RR":
            lines.append(
                f"  Win rate: {q.win_rate:.1f}%  PF: {q.profit_factor:.2f}  "
                f"Expectancy: ${q.expectancy_usd:,.0f}/trade"
            )
            lines.append(
                f"  MFE/MAE med: {q.mfe_median_pts:.2f} / {q.mae_median_pts:.2f} pts  "
                f"ratio {q.mfe_mae_ratio:.2f}"
            )
            lines.append(
                f"  Capture med: {q.capture_ratio_median:.2f}  "
                f"MAE-before-MFE: {q.pct_mae_before_mfe:.1f}%  "
                f"MFE>5 & loss: {q.pct_mfe_gt_5_close_neg:.1f}%"
            )
            lines.append(
                f"  Time to MFE/MAE med: {q.mfe_minutes_median:.0f} / "
                f"{q.mae_minutes_median:.0f} min"
            )

    if report.direction:
        d = report.direction
        lines.extend(
            [
                "",
                "--- Entry direction diagnostics (SS windows) ---",
                f"  Strategy beats opposite: {d.pct_strategy_beats_opposite:.1f}%",
                f"  Median edge vs opposite: {d.median_edge_pts:+.2f} pts/trade",
                f"  Opposite-direction net:  ${d.opposite_net_pnl_usd:,.0f}",
                f"  Coin-flip MC median:     ${d.coinflip_mc_median_usd:,.0f} "
                f"({d.coinflip_mc_pct_positive:.1f}% positive)",
            ]
        )

    if report.horizon_edges:
        lines.extend(["", "--- Fixed-horizon edge (strategy vs opposite, no exits) ---"])
        for h in report.horizon_edges:
            lines.append(
                f"  {h['horizon_minutes']:3d} min: strat {h['median_close_pts_strategy']:+.2f} pts  "
                f"opp {h['median_close_pts_opposite']:+.2f} pts  "
                f"edge {h['median_edge_pts']:+.2f} pts"
            )

    lines.extend(["", "--- Interpretation ---"])
    ss = report.quadrants["SS"]
    rr = report.quadrants["RR"]
    sr = report.quadrants["SR"]
    rs = report.quadrants["RS"]
    rr_med = rr.mc_median_usd or 0.0

    if ss.net_pnl_usd < ss.friction_floor_usd:
        lines.append("- SS loses more than friction-only: negative edge beyond costs.")
    if ss.net_pnl_usd < rr_med:
        lines.append("- SS underperforms RR null: strategy logic destroys value vs random trading.")
    elif ss.net_pnl_usd > rr_med:
        lines.append("- SS beats RR null: some structural edge exists (verify OOS stability).")

    sr_ref = sr.mc_median_usd if sr.mc_median_usd is not None else sr.net_pnl_usd
    rs_ref = rs.mc_median_usd if rs.mc_median_usd is not None else rs.net_pnl_usd
    exit_effect = ss.net_pnl_usd - sr_ref
    entry_effect = ss.net_pnl_usd - rs_ref
    lines.append(
        f"- Exit path effect (SS - SR): ${exit_effect:,.0f}  "
        f"(positive => strategy exits help vs time-only random hold)"
    )
    lines.append(
        f"- Entry selection effect (SS - RS): ${entry_effect:,.0f}  "
        f"(positive => strategy entries beat random OOS entries)"
    )

    if report.direction and report.direction.pct_strategy_beats_opposite < 45:
        lines.append("- Direction is anti-predictive vs opposite at same entry/exit times.")

    lines.extend(["", "--- Notes ---", *[f"- {n}" for n in report.notes]])
    return "\n".join(lines)


def write_report_markdown(report: AttributionReport, path: str | Path) -> None:
    text = format_report_text(report)
    table = format_quadrant_table(report)
    md = [
        "# Strategy Attribution Report",
        "",
        f"**Source:** `{report.source}`  ",
        f"**Trades:** {report.trade_count}  ",
        f"**MC runs:** {report.config.mc_runs}",
        "",
        "## Four-Quadrant Summary",
        "",
        table,
        "",
        "## Full Report",
        "",
        "```text",
        text,
        "```",
        "",
    ]
    Path(path).write_text("\n".join(md), encoding="utf-8")


def write_report_json(report: AttributionReport, path: str | Path) -> None:
    Path(path).write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

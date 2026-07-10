"""Backtest orchestration shared by tests and the future stage-6 task runner."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Iterable

from .data_provider import align_bars_to_trading_calendar, canonical_data_hash
from .engine import run_strategy
from .fees import FeeProfile, default_fee_profile
from .indicators import build_indicator_snapshots
from .instrument import require_backtestable
from .metrics import run_benchmark
from .schemas import BacktestConfig, BacktestRunResult, Bar, IndicatorSnapshot
from .strategies import get_strategy


def _prepare_timeline(
    bars: list[Bar],
    config: BacktestConfig,
    trading_dates: Iterable[date] | None = None,
) -> tuple[list[Bar], list[IndicatorSnapshot]]:
    """Build indicators from real bars, then add suspension placeholders."""
    source_bars = sorted(bars, key=lambda bar: bar.date)
    source_snapshots = build_indicator_snapshots(source_bars, config)
    if trading_dates is None:
        return source_bars, source_snapshots

    ordered_bars = align_bars_to_trading_calendar(source_bars, trading_dates)
    snapshot_by_date = {snapshot.date: snapshot for snapshot in source_snapshots}
    snapshots: list[IndicatorSnapshot] = []
    previous_snapshot = None
    for index, bar in enumerate(ordered_bars):
        source = snapshot_by_date.get(bar.date)
        if source is not None:
            current = replace(source, index=index)
            previous_snapshot = current
        elif previous_snapshot is not None:
            current = replace(
                previous_snapshot,
                index=index,
                date=bar.date,
                cross_up=False,
                cross_down=False,
                fib_touched=False,
                fib_rebound=False,
                touched_levels=[],
                trendline_broken=False,
            )
        else:
            raise ValueError("trading calendar begins before available K-line data")
        snapshots.append(current)
    return ordered_bars, snapshots


def run_backtest(
    symbol: str,
    bars: list[Bar],
    config: BacktestConfig,
    *,
    strategy_keys: Iterable[str] = ("A", "B", "C", "D"),
    fee_profile: FeeProfile | None = None,
    adjust: str = "qfq",
    trading_dates: Iterable[date] | None = None,
) -> BacktestRunResult:
    info = require_backtestable(symbol)
    profile = fee_profile or default_fee_profile(info.instrument_type)
    ordered_bars, snapshots = _prepare_timeline(bars, config, trading_dates)
    results = {
        key.upper(): run_strategy(
            ordered_bars,
            snapshots,
            get_strategy(key),
            config,
            info,
            profile,
        )
        for key in strategy_keys
    }
    benchmark = run_benchmark(ordered_bars, config, info, profile)
    return BacktestRunResult(
        symbol=info.symbol,
        data_hash=canonical_data_hash(ordered_bars, adjust),
        strategy_results=results,
        benchmark=benchmark,
    )

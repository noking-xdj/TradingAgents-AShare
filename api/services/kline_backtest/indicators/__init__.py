"""Look-ahead-safe indicator snapshot construction."""

from __future__ import annotations

from decimal import Decimal

from ..schemas import BacktestConfig, Bar, IndicatorSnapshot
from .fibonacci import fib_touch, rebound_confirmed, select_rising_swing
from .ma import crossover, rolling_mean
from .pivots import find_confirmed_pivots, visible_pivots
from .trendline import build_trendline


def build_indicator_snapshots(bars: list[Bar], config: BacktestConfig) -> list[IndicatorSnapshot]:
    short_values = rolling_mean([bar.close for bar in bars], config.short_ma)
    long_values = rolling_mean([bar.close for bar in bars], config.long_ma)
    cross_up, cross_down = crossover(short_values, long_values)
    all_pivots = find_confirmed_pivots(bars, config.pivot_left, config.pivot_right)
    snapshots: list[IndicatorSnapshot] = []
    for index, bar in enumerate(bars):
        visible = visible_pivots(all_pivots, index)
        swing = select_rising_swing(
            visible,
            current_index=index,
            window=config.fib_window,
            min_separation=config.pivot_min_separation,
            min_amplitude=config.fib_min_amplitude,
        )
        touched, levels = fib_touch(
            bar,
            swing,
            tolerance=config.fib_tolerance,
            mode=config.fib_mode,
        )
        trend = build_trendline(
            bars,
            visible,
            current_index=index,
            kind="support",
            min_separation=config.pivot_min_separation,
            touch_tolerance=config.trend_tolerance,
            break_threshold=config.trend_break_threshold,
            min_touches=config.trend_min_touches,
        )
        trend_price = trend.price_at(index) if trend is not None else None
        trend_broken = bool(
            trend is not None
            and trend.effective
            and trend_price is not None
            and bar.close < trend_price * (Decimal("1") - config.trend_break_threshold)
        )
        snapshots.append(
            IndicatorSnapshot(
                index=index,
                date=bar.date,
                ma_short=short_values[index],
                ma_long=long_values[index],
                cross_up=cross_up[index],
                cross_down=cross_down[index],
                visible_pivots=visible,
                swing=swing,
                fib_touched=touched,
                fib_rebound=touched and rebound_confirmed(bars, index),
                touched_levels=levels,
                trendline=trend,
                trendline_price=trend_price,
                trendline_broken=trend_broken,
            )
        )
    return snapshots


__all__ = ["build_indicator_snapshots"]

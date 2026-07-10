"""Deterministic strategies A through D."""

from __future__ import annotations

from ..schemas import Bar, IndicatorSnapshot, Position, SignalDecision
from .base import Strategy, bound_swing_invalid, ma_bearish, ma_bullish


class StrategyA(Strategy):
    key = "A"

    def evaluate(self, snapshot: IndicatorSnapshot, bar: Bar, position: Position | None) -> SignalDecision:
        conditions = {"ma_cross_up": snapshot.cross_up, "ma_cross_down": snapshot.cross_down}
        return SignalDecision(
            buy=snapshot.cross_up,
            sell=snapshot.cross_down,
            buy_reasons=["ma_cross_up"] if snapshot.cross_up else [],
            sell_reasons=["ma_cross_down"] if snapshot.cross_down else [],
            conditions=conditions,
        )


class StrategyB(Strategy):
    key = "B"

    def evaluate(self, snapshot: IndicatorSnapshot, bar: Bar, position: Position | None) -> SignalDecision:
        bullish = ma_bullish(snapshot)
        fib_ready = snapshot.swing is not None
        fib_entry = snapshot.fib_touched and snapshot.fib_rebound
        invalid = bound_swing_invalid(bar, position)
        bearish = ma_bearish(snapshot)
        buy = bullish and fib_ready and fib_entry
        sell = bearish or invalid
        return SignalDecision(
            buy=buy,
            sell=sell,
            buy_reasons=[item for item, ok in (("ma_bullish", bullish), ("fib_touch_rebound", fib_entry)) if ok],
            sell_reasons=[item for item, ok in (("ma_bearish", bearish), ("bound_swing_invalid", invalid)) if ok],
            conditions={
                "ma_bullish": bullish,
                "qualified_swing": fib_ready,
                "fib_touched": snapshot.fib_touched,
                "fib_rebound": snapshot.fib_rebound,
                "bound_swing_invalid": invalid,
            },
            wave_snapshot=snapshot.swing if buy else None,
        )


class StrategyC(Strategy):
    key = "C"

    def evaluate(self, snapshot: IndicatorSnapshot, bar: Bar, position: Position | None) -> SignalDecision:
        bullish = ma_bullish(snapshot)
        effective = bool(snapshot.trendline is not None and snapshot.trendline.effective)
        supported = effective and not snapshot.trendline_broken
        bearish = ma_bearish(snapshot)
        broken = effective and snapshot.trendline_broken
        return SignalDecision(
            buy=bullish and supported,
            sell=bearish or broken,
            buy_reasons=[item for item, ok in (("ma_bullish", bullish), ("valid_trendline", supported)) if ok],
            sell_reasons=[item for item, ok in (("ma_bearish", bearish), ("trendline_broken", broken)) if ok],
            conditions={
                "ma_bullish": bullish,
                "valid_trendline": effective,
                "trendline_supported": supported,
                "trendline_broken": broken,
            },
        )


class StrategyD(Strategy):
    key = "D"

    def evaluate(self, snapshot: IndicatorSnapshot, bar: Bar, position: Position | None) -> SignalDecision:
        bullish = ma_bullish(snapshot)
        effective = bool(snapshot.trendline is not None and snapshot.trendline.effective)
        supported = effective and not snapshot.trendline_broken
        fib_ready = snapshot.swing is not None
        fib_entry = snapshot.fib_touched and snapshot.fib_rebound
        bearish = ma_bearish(snapshot)
        broken = effective and snapshot.trendline_broken
        invalid = bound_swing_invalid(bar, position)
        buy = bullish and supported and fib_ready and fib_entry
        sell = bearish or broken or invalid
        return SignalDecision(
            buy=buy,
            sell=sell,
            buy_reasons=[
                item for item, ok in (
                    ("ma_bullish", bullish),
                    ("valid_trendline", supported),
                    ("fib_touch_rebound", fib_entry),
                ) if ok
            ],
            sell_reasons=[
                item for item, ok in (
                    ("ma_bearish", bearish),
                    ("trendline_broken", broken),
                    ("bound_swing_invalid", invalid),
                ) if ok
            ],
            conditions={
                "ma_bullish": bullish,
                "valid_trendline": effective,
                "trendline_supported": supported,
                "qualified_swing": fib_ready,
                "fib_touched": snapshot.fib_touched,
                "fib_rebound": snapshot.fib_rebound,
                "trendline_broken": broken,
                "bound_swing_invalid": invalid,
            },
            wave_snapshot=snapshot.swing if buy else None,
        )


STRATEGIES: dict[str, Strategy] = {
    "A": StrategyA(),
    "B": StrategyB(),
    "C": StrategyC(),
    "D": StrategyD(),
}


def get_strategy(key: str) -> Strategy:
    try:
        return STRATEGIES[key.upper()]
    except KeyError as exc:
        raise ValueError(f"unknown strategy: {key}") from exc

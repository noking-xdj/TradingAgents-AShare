"""Strategy interface and shared condition helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..indicators.fibonacci import swing_invalid
from ..schemas import Bar, IndicatorSnapshot, Position, SignalDecision


class Strategy(ABC):
    key: str

    @abstractmethod
    def evaluate(
        self,
        snapshot: IndicatorSnapshot,
        bar: Bar,
        position: Position | None,
    ) -> SignalDecision:
        raise NotImplementedError


def ma_bullish(snapshot: IndicatorSnapshot) -> bool:
    return (
        snapshot.ma_short is not None
        and snapshot.ma_long is not None
        and snapshot.ma_short > snapshot.ma_long
    )


def ma_bearish(snapshot: IndicatorSnapshot) -> bool:
    return (
        snapshot.ma_short is not None
        and snapshot.ma_long is not None
        and snapshot.ma_short < snapshot.ma_long
    )


def bound_swing_invalid(bar: Bar, position: Position | None) -> bool:
    return bool(position is not None and swing_invalid(bar.close, position.wave_snapshot))

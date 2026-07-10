"""Confirmed swing pivots with explicit visibility dates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..schemas import Bar


@dataclass(frozen=True)
class Pivot:
    kind: str
    index: int
    date: date
    price: Decimal
    confirmed_index: int
    confirmed_at: date


def find_confirmed_pivots(bars: list[Bar], left: int = 3, right: int = 3) -> list[Pivot]:
    if left < 1 or right < 1:
        raise ValueError("pivot left/right windows must be positive")
    pivots: list[Pivot] = []
    for index in range(left, len(bars) - right):
        high = bars[index].high
        low = bars[index].low
        left_bars = bars[index - left:index]
        right_bars = bars[index + 1:index + right + 1]
        if all(high > item.high for item in left_bars + right_bars):
            pivots.append(Pivot("high", index, bars[index].date, high, index + right, bars[index + right].date))
        if all(low < item.low for item in left_bars + right_bars):
            pivots.append(Pivot("low", index, bars[index].date, low, index + right, bars[index + right].date))
    return sorted(pivots, key=lambda pivot: (pivot.confirmed_index, pivot.index, pivot.kind))


def visible_pivots(pivots: list[Pivot], current_index: int) -> list[Pivot]:
    return [pivot for pivot in pivots if pivot.confirmed_index <= current_index]

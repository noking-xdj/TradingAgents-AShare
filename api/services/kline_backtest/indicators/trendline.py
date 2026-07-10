"""Candidate and touch-validated support/resistance trend lines."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ..schemas import Bar
from .pivots import Pivot


@dataclass(frozen=True)
class TrendlineSnapshot:
    kind: str
    first: Pivot
    second: Pivot
    slope: Decimal
    touch_count: int
    effective: bool
    effective_from_index: Optional[int]

    def price_at(self, index: int) -> Decimal:
        return self.first.price + self.slope * Decimal(index - self.first.index)


def build_trendline(
    bars: list[Bar],
    pivots: list[Pivot],
    *,
    current_index: int,
    kind: str = "support",
    min_separation: int = 5,
    touch_tolerance: Decimal = Decimal("0.005"),
    break_threshold: Decimal = Decimal("0.01"),
    min_touches: int = 3,
) -> Optional[TrendlineSnapshot]:
    pivot_kind = "low" if kind == "support" else "high"
    matching = [pivot for pivot in pivots if pivot.kind == pivot_kind]
    if len(matching) < 2:
        return None
    first, second = matching[-2], matching[-1]
    if second.index - first.index < min_separation:
        return None
    if kind == "support" and second.price <= first.price:
        return None
    if kind == "resistance" and second.price >= first.price:
        return None
    slope = (second.price - first.price) / Decimal(second.index - first.index)
    touch_count = 2
    effective_from: Optional[int] = None
    start = second.confirmed_index + 1
    for index in range(start, current_index + 1):
        line_price = first.price + slope * Decimal(index - first.index)
        bar = bars[index]
        if kind == "support":
            touched = (
                bar.low <= line_price * (Decimal("1") + touch_tolerance)
                and bar.high >= line_price * (Decimal("1") - touch_tolerance)
                and bar.close >= line_price * (Decimal("1") - break_threshold)
            )
        else:
            touched = (
                bar.high >= line_price * (Decimal("1") - touch_tolerance)
                and bar.low <= line_price * (Decimal("1") + touch_tolerance)
                and bar.close <= line_price * (Decimal("1") + break_threshold)
            )
        if touched:
            touch_count += 1
            if touch_count >= min_touches and effective_from is None:
                effective_from = index
    return TrendlineSnapshot(
        kind=kind,
        first=first,
        second=second,
        slope=slope,
        touch_count=touch_count,
        effective=touch_count >= min_touches,
        effective_from_index=effective_from,
    )

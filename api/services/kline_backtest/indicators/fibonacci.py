"""Confirmed swing selection and Fibonacci retracement conditions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from ..schemas import Bar
from .pivots import Pivot


FIB_RATIOS = (
    Decimal("0.236"),
    Decimal("0.382"),
    Decimal("0.5"),
    Decimal("0.618"),
    Decimal("0.786"),
)
DISCRETE_RATIOS = (Decimal("0.382"), Decimal("0.5"), Decimal("0.618"))


@dataclass(frozen=True)
class SwingSnapshot:
    low_index: int
    low_date: date
    low_price: Decimal
    low_confirmed_index: int
    high_index: int
    high_date: date
    high_price: Decimal
    high_confirmed_index: int
    amplitude: Decimal
    levels: dict[str, Decimal]


def _levels(low: Decimal, high: Decimal) -> dict[str, Decimal]:
    move = high - low
    return {format(ratio, "f"): high - move * ratio for ratio in FIB_RATIOS}


def select_rising_swing(
    pivots: list[Pivot],
    *,
    current_index: int,
    window: int = 60,
    min_separation: int = 5,
    min_amplitude: Decimal = Decimal("0.05"),
) -> Optional[SwingSnapshot]:
    floor = max(0, current_index - window + 1)
    lows = [pivot for pivot in pivots if pivot.kind == "low" and pivot.index >= floor]
    highs = sorted(
        [pivot for pivot in pivots if pivot.kind == "high" and pivot.index >= floor],
        key=lambda pivot: (pivot.confirmed_index, pivot.index),
        reverse=True,
    )
    for high in highs:
        eligible_lows = sorted(
            [
                low for low in lows
                if low.index < high.index
                and high.index - low.index >= min_separation
                and high.price > low.price
            ],
            key=lambda pivot: (pivot.confirmed_index, pivot.index),
            reverse=True,
        )
        for low in eligible_lows:
            amplitude = (high.price - low.price) / low.price
            if amplitude < min_amplitude:
                continue
            return SwingSnapshot(
                low_index=low.index,
                low_date=low.date,
                low_price=low.price,
                low_confirmed_index=low.confirmed_index,
                high_index=high.index,
                high_date=high.date,
                high_price=high.price,
                high_confirmed_index=high.confirmed_index,
                amplitude=amplitude,
                levels=_levels(low.price, high.price),
            )
    return None


def fib_touch(
    bar: Bar,
    swing: Optional[SwingSnapshot],
    *,
    tolerance: Decimal = Decimal("0.01"),
    mode: str = "discrete",
) -> tuple[bool, list[str]]:
    if swing is None:
        return False, []
    if mode == "zone":
        upper = swing.levels["0.382"]
        lower = swing.levels["0.618"]
        return bar.low <= upper and bar.high >= lower, ["zone"] if bar.low <= upper and bar.high >= lower else []
    touched: list[str] = []
    for ratio in DISCRETE_RATIOS:
        key = format(ratio, "f")
        level = swing.levels[key]
        if bar.low <= level * (Decimal("1") + tolerance) and bar.high >= level * (Decimal("1") - tolerance):
            touched.append(key)
    return bool(touched), touched


def rebound_confirmed(bars: list[Bar], index: int) -> bool:
    if index <= 0:
        return False
    return bars[index].close > bars[index - 1].close and bars[index].close > bars[index].open


def swing_invalid(
    close: Decimal,
    swing: Optional[SwingSnapshot],
    threshold: Decimal = Decimal("0.01"),
) -> bool:
    if swing is None:
        return False
    return (
        close < swing.levels["0.618"] * (Decimal("1") - threshold)
        or close < swing.low_price
    )

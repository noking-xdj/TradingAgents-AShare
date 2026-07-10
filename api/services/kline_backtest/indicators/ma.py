"""Moving averages and crossover signals."""

from decimal import Decimal
from typing import Optional


def rolling_mean(values: list[Decimal], window: int) -> list[Optional[Decimal]]:
    if window <= 0:
        raise ValueError("window must be positive")
    result: list[Optional[Decimal]] = [None] * len(values)
    running = Decimal("0")
    for index, value in enumerate(values):
        running += value
        if index >= window:
            running -= values[index - window]
        if index >= window - 1:
            result[index] = running / Decimal(window)
    return result


def crossover(
    short: list[Optional[Decimal]],
    long: list[Optional[Decimal]],
) -> tuple[list[bool], list[bool]]:
    if len(short) != len(long):
        raise ValueError("moving-average arrays must have equal length")
    up = [False] * len(short)
    down = [False] * len(short)
    for index in range(1, len(short)):
        prev_short, prev_long = short[index - 1], long[index - 1]
        current_short, current_long = short[index], long[index]
        if None in (prev_short, prev_long, current_short, current_long):
            continue
        up[index] = prev_short <= prev_long and current_short > current_long
        down[index] = prev_short >= prev_long and current_short < current_long
    return up, down

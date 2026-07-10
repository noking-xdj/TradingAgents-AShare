from datetime import date
from decimal import Decimal

from api.services.kline_backtest.indicators.fibonacci import (
    fib_touch,
    select_rising_swing,
    swing_invalid,
)
from api.services.kline_backtest.indicators.pivots import Pivot, find_confirmed_pivots, visible_pivots
from api.services.kline_backtest.indicators.trendline import build_trendline
from api.services.kline_backtest.schemas import Bar
from tests.kline_backtest_helpers import d, make_bars


def test_pivot_is_not_visible_until_confirmed_at():
    bars = make_bars([10, 11, 12, 15, 13, 12, 11])
    # Remove the helper's gap-high tie on the bar after the intended peak.
    bars[4] = Bar(bars[4].date, d("13.2"), d("13.5"), d("12.5"), d("13"), d("100"))
    pivots = find_confirmed_pivots(bars, left=2, right=2)
    high = next(pivot for pivot in pivots if pivot.kind == "high" and pivot.index == 3)
    assert high.confirmed_index == 5
    assert high not in visible_pivots(pivots, 4)
    assert high in visible_pivots(pivots, 5)


def _pivot(kind: str, index: int, price: str, confirmed: int) -> Pivot:
    return Pivot(kind, index, date(2025, 1, 1), d(price), confirmed, date(2025, 1, 2))


def test_fibonacci_uses_recent_confirmed_swing_amplitude_and_range_intersection():
    pivots = [_pivot("low", 2, "10", 5), _pivot("high", 10, "20", 13)]
    swing = select_rising_swing(pivots, current_index=13, min_separation=5, min_amplitude=d("0.05"))
    assert swing is not None
    assert swing.amplitude == Decimal("1")
    assert swing.levels["0.5"] == Decimal("15.0")
    touching = Bar(date(2025, 2, 1), d("15.4"), d("15.4"), d("14.8"), d("15.2"), d("100"))
    hit, levels = fib_touch(touching, swing, tolerance=d("0.01"))
    assert hit is True
    assert "0.5" in levels
    assert swing_invalid(d("13.60"), swing) is True


def test_fibonacci_rejects_small_swing_without_fallback():
    pivots = [_pivot("low", 2, "10", 5), _pivot("high", 10, "10.4", 13)]
    assert select_rising_swing(
        pivots, current_index=13, min_separation=5, min_amplitude=d("0.05"),
    ) is None


def test_trendline_requires_post_confirmation_third_touch():
    bars = make_bars([10 + index * 0.3 for index in range(16)], spread=Decimal("0.05"))
    first = _pivot("low", 1, "10", 4)
    second = _pivot("low", 7, "12", 10)
    # The projected line at index 11 is 13.333...; create a clean validation touch.
    original = bars[11]
    bars[11] = Bar(original.date, d("13.4"), d("13.5"), d("13.32"), d("13.4"), d("100"))
    before = build_trendline(bars, [first, second], current_index=10, min_separation=5)
    after = build_trendline(bars, [first, second], current_index=11, min_separation=5)
    assert before is not None and before.touch_count == 2 and before.effective is False
    assert after is not None and after.touch_count == 3 and after.effective is True
    assert after.effective_from_index == 11


def test_trendline_uses_only_latest_two_pivots_and_never_falls_back():
    bars = make_bars([10 + index * 0.1 for index in range(20)])
    pivots = [
        _pivot("low", 1, "10", 4),
        _pivot("low", 7, "12", 10),
        _pivot("low", 13, "11", 16),
    ]
    assert build_trendline(bars, pivots, current_index=18, min_separation=5) is None

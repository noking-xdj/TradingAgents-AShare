from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from api.services.kline_backtest.indicators.fibonacci import SwingSnapshot
from api.services.kline_backtest.schemas import Bar, IndicatorSnapshot, Position
from api.services.kline_backtest.strategies import get_strategy
from tests.kline_backtest_helpers import d


def _swing() -> SwingSnapshot:
    return SwingSnapshot(
        low_index=1,
        low_date=date(2025, 1, 2),
        low_price=d("10"),
        low_confirmed_index=4,
        high_index=8,
        high_date=date(2025, 1, 9),
        high_price=d("20"),
        high_confirmed_index=11,
        amplitude=d("1"),
        levels={"0.236": d("17.64"), "0.382": d("16.18"), "0.5": d("15"), "0.618": d("13.82"), "0.786": d("12.14")},
    )


def _snapshot(**overrides) -> IndicatorSnapshot:
    values = dict(
        index=12,
        date=date(2025, 1, 13),
        ma_short=d("16"),
        ma_long=d("15"),
        cross_up=False,
        cross_down=False,
        visible_pivots=[],
        swing=_swing(),
        fib_touched=True,
        fib_rebound=True,
        touched_levels=["0.5"],
        trendline=SimpleNamespace(effective=True, touch_count=3),
        trendline_price=d("14"),
        trendline_broken=False,
    )
    values.update(overrides)
    return IndicatorSnapshot(**values)


BAR = Bar(date(2025, 1, 13), d("15"), d("16"), d("14.8"), d("15.5"), d("100"))


def test_strategy_b_and_d_bind_entry_swing_snapshot():
    for key in ("B", "D"):
        decision = get_strategy(key).evaluate(_snapshot(), BAR, None)
        assert decision.buy is True
        assert decision.wave_snapshot == _swing()


def test_strategy_c_and_d_require_effective_trendline_without_fallback():
    invalid = _snapshot(trendline=SimpleNamespace(effective=False, touch_count=2))
    assert get_strategy("C").evaluate(invalid, BAR, None).buy is False
    assert get_strategy("D").evaluate(invalid, BAR, None).buy is False


def test_strategy_b_uses_bound_entry_swing_for_exit():
    swing = _swing()
    position = Position(
        qty=100,
        entry_price=d("15"),
        entry_total_cost=d("1500"),
        entry_index=12,
        entry_date=date(2025, 1, 13),
        stop_price=None,
        take_profit_price=None,
        wave_snapshot=swing,
    )
    broken_bar = Bar(date(2025, 1, 14), d("14"), d("14.2"), d("13"), d("13.5"), d("100"))
    decision = get_strategy("B").evaluate(_snapshot(date=broken_bar.date), broken_bar, position)
    assert decision.sell is True
    assert "bound_swing_invalid" in decision.sell_reasons

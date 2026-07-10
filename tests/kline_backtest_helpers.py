from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from api.services.kline_backtest.schemas import Bar, IndicatorSnapshot


def d(value) -> Decimal:
    return Decimal(str(value))


def make_bars(
    closes: list[float | int | str],
    *,
    start: date = date(2025, 1, 1),
    spread: Decimal = Decimal("0.40"),
) -> list[Bar]:
    bars: list[Bar] = []
    previous = d(closes[0])
    for offset, raw_close in enumerate(closes):
        close = d(raw_close)
        open_price = previous
        bars.append(Bar(
            date=start + timedelta(days=offset),
            open=open_price,
            high=max(open_price, close) + spread,
            low=min(open_price, close) - spread,
            close=close,
            volume=Decimal("100000"),
            amount=Decimal("1000000"),
            change_percent=(close - previous) / previous * Decimal("100") if previous else Decimal("0"),
        ))
        previous = close
    return bars


def dummy_snapshots(bars: list[Bar]) -> list[IndicatorSnapshot]:
    return [
        IndicatorSnapshot(
            index=index,
            date=bar.date,
            ma_short=bar.close,
            ma_long=bar.close,
            cross_up=False,
            cross_down=False,
            visible_pivots=[],
            swing=None,
            fib_touched=False,
            fib_rebound=False,
            touched_levels=[],
            trendline=None,
            trendline_price=None,
            trendline_broken=False,
        )
        for index, bar in enumerate(bars)
    ]

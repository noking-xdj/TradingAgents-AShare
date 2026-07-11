from datetime import date
from decimal import Decimal

from api.services.kline_backtest.engine import run_strategy
from api.services.kline_backtest.fees import STOCK_FEE_PROFILE
from api.services.kline_backtest.instrument import require_backtestable
from api.services.kline_backtest.metrics import compute_metrics, run_benchmark
from api.services.kline_backtest.schemas import (
    BacktestConfig,
    Bar,
    OrderType,
    Position,
    EquityPoint,
    OrderRecord,
    SignalDecision,
)
from api.services.kline_backtest.strategies.base import Strategy
from tests.kline_backtest_helpers import d, dummy_snapshots, make_bars


class ScriptedStrategy(Strategy):
    key = "X"

    def __init__(self, buys=(), sells=()):
        self.buys = set(buys)
        self.sells = set(sells)

    def evaluate(self, snapshot, bar, position):
        return SignalDecision(
            buy=snapshot.index in self.buys,
            sell=snapshot.index in self.sells,
            buy_reasons=["scripted_buy"] if snapshot.index in self.buys else [],
            sell_reasons=["scripted_sell"] if snapshot.index in self.sells else [],
            conditions={"scripted_buy": snapshot.index in self.buys, "scripted_sell": snapshot.index in self.sells},
        )


def _config(bars, **kwargs):
    values = dict(
        start_date=bars[0].date,
        end_date=bars[-1].date,
        short_ma=2,
        long_ma=3,
        stop_loss=None,
        take_profit=None,
    )
    values.update(kwargs)
    return BacktestConfig(**values)


def _run(bars, strategy, **config_kwargs):
    return run_strategy(
        bars,
        dummy_snapshots(bars),
        strategy,
        _config(bars, **config_kwargs),
        require_backtestable("600519.SH"),
        STOCK_FEE_PROFILE,
    )


def test_close_signal_executes_at_next_open_and_period_end_order_is_canceled():
    bars = make_bars([10, 11, 12, 11, 10])
    result = _run(bars, ScriptedStrategy(buys={0, 4}, sells={2}))
    executed = [order for order in result.orders if order.outcome == "executed"]
    assert [(order.side, order.signal_date, order.actual_date) for order in executed] == [
        ("BUY", bars[0].date, bars[1].date),
        ("SELL", bars[2].date, bars[3].date),
    ]
    assert result.orders[-1].outcome == "period_end"


def test_buy_day_intraday_stop_creates_risk_exit_for_following_open():
    bars = make_bars([10, 10, 9, 9])
    bars[1] = Bar(bars[1].date, d("10"), d("12"), d("8"), d("10"), d("100000"), change_percent=d("0"))
    result = _run(
        bars,
        ScriptedStrategy(buys={0}),
        stop_loss=d("0.08"),
        take_profit=d("0.15"),
    )
    sell = next(order for order in result.orders if order.side == "SELL" and order.outcome == "executed")
    assert sell.order_type == OrderType.RISK_EXIT.value
    assert sell.reasons[0] == "stop_loss"
    assert sell.signal_date == bars[1].date
    assert sell.actual_date == bars[2].date


def test_strategy_pending_order_reverses_but_risk_exit_does_not():
    bars = make_bars([10, 11, 10, 9, 8])
    bars[1] = Bar(bars[1].date, d("11"), d("11"), d("11"), d("11"), d("100"), change_percent=d("10"))
    canceled = _run(bars, ScriptedStrategy(buys={0}, sells={1}))
    assert canceled.orders[0].outcome == "signal_reversed"

    risk_bars = make_bars([10, 10, 9, 9, 9])
    risk_bars[1] = Bar(risk_bars[1].date, d("10"), d("10.2"), d("8"), d("9"), d("100"), change_percent=d("-10"))
    risk_bars[2] = Bar(risk_bars[2].date, d("8.1"), d("8.1"), d("8.1"), d("8.1"), d("100"), change_percent=d("-10"))
    result = _run(
        risk_bars,
        ScriptedStrategy(buys={0, 2}),
        stop_loss=d("0.08"),
        max_deferred_days=5,
    )
    sell = next(order for order in result.orders if order.side == "SELL")
    assert sell.order_type == "risk_exit"
    assert sell.outcome == "executed"
    assert sell.deferred_days == 1


def test_pending_order_expires_after_five_unavailable_days():
    bars = make_bars([10] * 8)
    for index in range(1, 6):
        bars[index] = Bar(bars[index].date, d("11"), d("11"), d("11"), d("11"), d("100"), change_percent=d("10"))
    result = _run(bars, ScriptedStrategy(buys={0}), max_deferred_days=5)
    assert result.orders[0].outcome == "expired"
    assert result.orders[0].deferred_days == 5


def test_suspension_day_neither_emits_signal_nor_reverses_pending_order():
    bars = make_bars([10, 10, 11])
    bars[1] = Bar(
        bars[1].date, d("10"), d("10"), d("10"), d("10"), d("0"),
        change_percent=d("0"), tradable=False,
    )
    result = _run(bars, ScriptedStrategy(buys={0}, sells={1}))
    assert [(order.outcome, order.actual_date, order.deferred_days) for order in result.orders] == [
        ("executed", bars[2].date, 1),
    ]
    assert result.audits[1].decision.buy is False
    assert result.audits[1].decision.sell is False
    assert result.audits[1].decision.conditions == {"tradable": False}


def test_benchmark_defers_initial_entry_and_reports_actual_date():
    bars = make_bars([10, 10, 11])
    bars[0] = Bar(bars[0].date, d("11"), d("11"), d("11"), d("11"), d("100"), change_percent=d("10"))
    config = _config(bars)
    benchmark = run_benchmark(bars, config, require_backtestable("600519.SH"), STOCK_FEE_PROFILE)
    assert benchmark.actual_entry_date == bars[1].date
    assert benchmark.equity[0].total == config.initial_cash
    assert benchmark.metrics["unrealized_pnl"] == benchmark.metrics["final_asset"] - config.initial_cash
    assert benchmark.metrics["unrealized_return"] == benchmark.metrics["total_return"]
    assert benchmark.metrics["completed_trades"] == 0


def test_profit_loss_ratio_uses_total_realized_wins_over_total_realized_losses():
    day = date(2025, 1, 2)
    config = BacktestConfig(start_date=day, end_date=day)
    equity = [EquityPoint(day, config.initial_cash, d("0"), config.initial_cash)]
    realized_values = (d("120"), d("30"), d("-50"))
    orders = [
        OrderRecord(
            strategy_key="A",
            signal_date=day,
            planned_date=day,
            actual_date=day,
            order_type="strategy",
            side="SELL",
            outcome="executed",
            reasons=["fixture"],
            realized_pnl=value,
        )
        for value in realized_values
    ]

    metrics = compute_metrics(equity, orders, config)

    assert metrics["profit_loss_ratio"] == d("3")
    assert metrics["win_rate"] == d("2") / d("3")

    no_loss_metrics = compute_metrics(equity, orders[:2], config)
    assert no_loss_metrics["profit_loss_ratio"] is None

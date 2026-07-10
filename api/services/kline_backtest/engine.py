"""Single-strategy, daily event-loop backtest engine."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .fees import FeeProfile, calculate_execution, max_affordable_quantity, money, price
from .instrument import InstrumentInfo
from .metrics import compute_metrics, compute_signal_stats
from .schemas import (
    AuditRecord,
    BacktestConfig,
    Bar,
    EquityPoint,
    IndicatorSnapshot,
    Order,
    OrderRecord,
    OrderType,
    Position,
    Side,
    SignalDecision,
    StrategyResult,
)
from .strategies.base import Strategy


HUNDRED = Decimal("100")


def _latest_completed_index(bars: list[Bar], before_index: int) -> int | None:
    """Return the most recent real K-line before an execution date."""
    for index in range(before_index - 1, -1, -1):
        if bars[index].tradable:
            return index
    return None


def _unavailable_reason(bar: Bar, side: Side, info: InstrumentInfo) -> Optional[str]:
    if not bar.tradable:
        return "suspended"
    if bar.high != bar.low or bar.change_percent is None:
        return None
    at_limit = abs(bar.change_percent) / HUNDRED >= info.price_limit * Decimal("0.97")
    if not at_limit:
        return None
    if side is Side.BUY and bar.change_percent > 0:
        return "limit_up"
    if side is Side.SELL and bar.change_percent < 0:
        return "limit_down"
    return None


def _record_cancel(
    strategy_key: str,
    order: Order,
    bars: list[Bar],
    outcome: str,
    cash: Decimal,
    position: Position | None,
    current_index: int,
) -> OrderRecord:
    planned_date = bars[order.planned_index].date if order.planned_index < len(bars) else None
    position_value = money(position.qty * bars[current_index].close) if position else Decimal("0.00")
    return OrderRecord(
        strategy_key=strategy_key,
        signal_date=bars[order.signal_index].date,
        planned_date=planned_date,
        actual_date=bars[current_index].date,
        order_type=order.order_type.value,
        side=order.side.value,
        outcome=outcome,
        reasons=list(order.reasons),
        deferred_days=order.deferred_days,
        theory_trigger_price=order.theory_trigger_price,
        cash_after=cash,
        position_value_after=position_value,
        wave_snapshot=order.wave_snapshot,
    )


def run_strategy(
    bars: list[Bar],
    snapshots: list[IndicatorSnapshot],
    strategy: Strategy,
    config: BacktestConfig,
    info: InstrumentInfo,
    profile: FeeProfile,
) -> StrategyResult:
    if len(bars) != len(snapshots):
        raise ValueError("bars and indicator snapshots must have equal length")
    period_indices = [index for index, bar in enumerate(bars) if config.start_date <= bar.date <= config.end_date]
    if not period_indices:
        raise ValueError("no bars in requested backtest period")

    cash = money(config.initial_cash)
    position: Position | None = None
    pending: Order | None = None
    orders: list[OrderRecord] = []
    equity: list[EquityPoint] = []
    audits: list[AuditRecord] = []

    for index in period_indices:
        bar = bars[index]
        snapshot = snapshots[index]
        if pending is not None and index >= pending.planned_index:
            previous_index = _latest_completed_index(bars, index)
            if pending.order_type is OrderType.STRATEGY and previous_index is not None:
                previous_decision = strategy.evaluate(
                    snapshots[previous_index], bars[previous_index], position,
                )
                reversed_signal = (
                    pending.side is Side.BUY and previous_decision.sell
                ) or (
                    pending.side is Side.SELL and previous_decision.buy
                )
                if reversed_signal:
                    orders.append(_record_cancel(strategy.key, pending, bars, "signal_reversed", cash, position, index))
                    pending = None
            if pending is not None:
                unavailable = _unavailable_reason(bar, pending.side, info)
                if unavailable:
                    pending.deferred_days += 1
                    if pending.deferred_days >= config.max_deferred_days:
                        pending.reasons.append(unavailable)
                        orders.append(_record_cancel(strategy.key, pending, bars, "expired", cash, position, index))
                        pending = None
                elif pending.side is Side.BUY:
                    if position is not None:
                        orders.append(_record_cancel(strategy.key, pending, bars, "already_holding", cash, position, index))
                        pending = None
                    else:
                        qty = max_affordable_quantity(cash, bar.open, profile, config.max_position_ratio)
                        if qty <= 0:
                            orders.append(_record_cancel(strategy.key, pending, bars, "insufficient_cash", cash, position, index))
                            pending = None
                        else:
                            execution = calculate_execution(bar.open, Side.BUY, qty, profile)
                            cash = money(cash + execution.cash_delta)
                            stop = price(execution.execution_price * (Decimal("1") - config.stop_loss)) if config.stop_loss is not None else None
                            take = price(execution.execution_price * (Decimal("1") + config.take_profit)) if config.take_profit is not None else None
                            position = Position(
                                qty=qty,
                                entry_price=execution.execution_price,
                                entry_total_cost=-execution.cash_delta,
                                entry_index=index,
                                entry_date=bar.date,
                                stop_price=stop,
                                take_profit_price=take,
                                wave_snapshot=pending.wave_snapshot,
                            )
                            orders.append(OrderRecord(
                                strategy_key=strategy.key,
                                signal_date=bars[pending.signal_index].date,
                                planned_date=bars[pending.planned_index].date,
                                actual_date=bar.date,
                                order_type=pending.order_type.value,
                                side=Side.BUY.value,
                                outcome="executed",
                                reasons=list(pending.reasons),
                                deferred_days=pending.deferred_days,
                                exec_price=execution.execution_price,
                                qty=qty,
                                commission=execution.commission,
                                transfer_fee=execution.transfer_fee,
                                slippage_cost=execution.slippage_cost,
                                cash_after=cash,
                                position_value_after=money(execution.execution_price * qty),
                                wave_snapshot=pending.wave_snapshot,
                            ))
                            pending = None
                elif position is None:
                    orders.append(_record_cancel(strategy.key, pending, bars, "no_position", cash, position, index))
                    pending = None
                else:
                    execution = calculate_execution(bar.open, Side.SELL, position.qty, profile)
                    cash = money(cash + execution.cash_delta)
                    realized = money(execution.cash_delta - position.entry_total_cost)
                    orders.append(OrderRecord(
                        strategy_key=strategy.key,
                        signal_date=bars[pending.signal_index].date,
                        planned_date=bars[pending.planned_index].date,
                        actual_date=bar.date,
                        order_type=pending.order_type.value,
                        side=Side.SELL.value,
                        outcome="executed",
                        reasons=list(pending.reasons),
                        deferred_days=pending.deferred_days,
                        theory_trigger_price=pending.theory_trigger_price,
                        exec_price=execution.execution_price,
                        qty=position.qty,
                        commission=execution.commission,
                        stamp_tax=execution.stamp_tax,
                        transfer_fee=execution.transfer_fee,
                        slippage_cost=execution.slippage_cost,
                        realized_pnl=realized,
                        cash_after=cash,
                        position_value_after=Decimal("0.00"),
                        wave_snapshot=position.wave_snapshot,
                    ))
                    position = None
                    pending = None

        risk_reasons: list[str] = []
        theory_price: Decimal | None = None
        if position is not None and bar.tradable:
            stop_hit = position.stop_price is not None and bar.low <= position.stop_price
            take_hit = position.take_profit_price is not None and bar.high >= position.take_profit_price
            if stop_hit:
                risk_reasons = ["stop_loss"]
                theory_price = position.stop_price
            elif take_hit:
                risk_reasons = ["take_profit"]
                theory_price = position.take_profit_price
            if risk_reasons:
                if pending is not None and pending.side is Side.SELL:
                    pending.order_type = OrderType.RISK_EXIT
                    pending.signal_index = index
                    pending.planned_index = index + 1
                    pending.theory_trigger_price = theory_price
                    for reason in risk_reasons:
                        if reason not in pending.reasons:
                            pending.reasons.insert(0, reason)
                elif pending is None:
                    pending = Order(
                        side=Side.SELL,
                        order_type=OrderType.RISK_EXIT,
                        signal_index=index,
                        planned_index=index + 1,
                        reasons=risk_reasons,
                        theory_trigger_price=theory_price,
                        wave_snapshot=position.wave_snapshot,
                    )

        decision = (
            strategy.evaluate(snapshot, bar, position)
            if bar.tradable
            else SignalDecision(conditions={"tradable": False})
        )
        ignored_reason = None
        if position is not None:
            if decision.buy:
                ignored_reason = "already_holding"
            if decision.sell:
                if pending is not None and pending.order_type is OrderType.RISK_EXIT:
                    for reason in decision.sell_reasons:
                        if reason not in pending.reasons:
                            pending.reasons.append(reason)
                elif pending is None:
                    pending = Order(
                        side=Side.SELL,
                        order_type=OrderType.STRATEGY,
                        signal_index=index,
                        planned_index=index + 1,
                        reasons=list(decision.sell_reasons),
                        wave_snapshot=position.wave_snapshot,
                    )
        elif decision.buy and pending is None:
            pending = Order(
                side=Side.BUY,
                order_type=OrderType.STRATEGY,
                signal_index=index,
                planned_index=index + 1,
                reasons=list(decision.buy_reasons),
                wave_snapshot=decision.wave_snapshot,
            )

        position_value = money(position.qty * bar.close) if position else Decimal("0.00")
        equity.append(EquityPoint(bar.date, cash, position_value, money(cash + position_value)))
        audits.append(AuditRecord(strategy.key, bar.date, decision, snapshot, ignored_reason))

    if pending is not None:
        orders.append(_record_cancel(strategy.key, pending, bars, "period_end", cash, position, period_indices[-1]))

    metrics = compute_metrics(equity, orders, config)
    signal_stats = compute_signal_stats(audits, orders)
    return StrategyResult(strategy.key, orders, equity, audits, metrics, signal_stats, position)

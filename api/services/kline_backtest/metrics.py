"""Performance, cost, signal statistics and buy-and-hold benchmark."""

from __future__ import annotations

import math
from collections import Counter
from decimal import Decimal
from typing import Any

from .fees import FeeProfile, calculate_execution, max_affordable_quantity, money
from .instrument import InstrumentInfo
from .schemas import AuditRecord, BacktestConfig, Bar, BenchmarkResult, EquityPoint, OrderRecord, Side


ZERO = Decimal("0")
HUNDRED = Decimal("100")


def apply_drawdown(equity: list[EquityPoint]) -> None:
    peak = ZERO
    for point in equity:
        if point.total > peak:
            peak = point.total
        point.drawdown = ZERO if peak == ZERO else (point.total - peak) / peak


def _daily_returns(equity: list[EquityPoint]) -> list[float]:
    returns: list[float] = []
    for previous, current in zip(equity, equity[1:]):
        if previous.total > 0:
            returns.append(float((current.total - previous.total) / previous.total))
    return returns


def compute_metrics(
    equity: list[EquityPoint],
    orders: list[OrderRecord],
    config: BacktestConfig,
) -> dict[str, Any]:
    apply_drawdown(equity)
    initial = config.initial_cash
    final = equity[-1].total if equity else initial
    total_return = (final - initial) / initial
    days = max(1, len(equity))
    annualized = Decimal(str((1 + float(total_return)) ** (config.annual_trading_days / days) - 1))
    daily = _daily_returns(equity)
    if len(daily) >= 2:
        mean = sum(daily) / len(daily)
        variance = sum((value - mean) ** 2 for value in daily) / (len(daily) - 1)
        volatility = math.sqrt(variance)
        daily_rf = float(config.risk_free_rate) / config.annual_trading_days
        sharpe = (mean - daily_rf) / volatility * math.sqrt(config.annual_trading_days) if volatility else 0.0
    else:
        volatility = 0.0
        sharpe = 0.0
    executed = [order for order in orders if order.outcome == "executed"]
    buys = [order for order in executed if order.side == Side.BUY.value]
    sells = [order for order in executed if order.side == Side.SELL.value]
    realized = [order.realized_pnl for order in sells if order.realized_pnl is not None]
    wins = [value for value in realized if value > 0]
    losses = [value for value in realized if value < 0]
    gross_profit = sum(wins, ZERO)
    gross_loss = abs(sum(losses, ZERO))
    average_asset = sum((point.total for point in equity), ZERO) / Decimal(len(equity)) if equity else initial
    buy_turnover = sum((money(order.exec_price * order.qty) for order in buys if order.exec_price), ZERO)
    commission = sum((order.commission for order in executed), ZERO)
    stamp_tax = sum((order.stamp_tax for order in executed), ZERO)
    transfer_fee = sum((order.transfer_fee for order in executed), ZERO)
    slippage = sum((order.slippage_cost for order in executed), ZERO)
    total_cost = commission + stamp_tax + transfer_fee + slippage
    gross_return = (final + total_cost - initial) / initial
    trading_index_by_date = {point.date: index for index, point in enumerate(equity)}
    holding_days: list[int] = []
    pending_buy_date = None
    for order in executed:
        if order.side == Side.BUY.value and order.actual_date is not None:
            pending_buy_date = order.actual_date
        elif order.side == Side.SELL.value and order.actual_date is not None and pending_buy_date is not None:
            holding_days.append(
                trading_index_by_date[order.actual_date] - trading_index_by_date[pending_buy_date]
            )
            pending_buy_date = None
    average_realized = sum(realized, ZERO) / Decimal(len(realized)) if realized else ZERO
    return {
        "initial_cash": initial,
        "final_asset": final,
        "total_return": total_return,
        "gross_return": gross_return,
        "annualized_return": annualized,
        "max_drawdown": min((point.drawdown for point in equity), default=ZERO),
        "volatility": Decimal(str(volatility)),
        "sharpe": Decimal(str(sharpe)),
        "completed_trades": len(sells),
        "buy_count": len(buys),
        "sell_count": len(sells),
        "win_rate": Decimal(len(wins)) / Decimal(len(realized)) if realized else ZERO,
        "profit_loss_ratio": gross_profit / gross_loss if gross_loss else None,
        "average_trade_net_pnl": average_realized,
        "best_trade_pnl": max(realized) if realized else None,
        "worst_trade_pnl": min(realized) if realized else None,
        "average_holding_days": Decimal(sum(holding_days)) / Decimal(len(holding_days)) if holding_days else ZERO,
        "strategy_turnover": buy_turnover / average_asset if average_asset else ZERO,
        "commission": commission,
        "stamp_tax": stamp_tax,
        "transfer_fee": transfer_fee,
        "slippage_cost": slippage,
        "total_cost": total_cost,
        "total_cost_ratio": total_cost / initial,
        "cost_to_gross_profit": total_cost / gross_profit if gross_profit else None,
        "average_cost_rate": total_cost / buy_turnover if buy_turnover else ZERO,
        "canceled_orders": len([order for order in orders if order.outcome != "executed"]),
    }


def compute_signal_stats(audits: list[AuditRecord], orders: list[OrderRecord]) -> dict[str, Any]:
    condition_false: Counter[str] = Counter()
    buy_signals = sell_signals = 0
    ignored: Counter[str] = Counter()
    for audit in audits:
        buy_signals += int(audit.decision.buy)
        sell_signals += int(audit.decision.sell)
        for name, value in audit.decision.conditions.items():
            if not value:
                condition_false[name] += 1
        if audit.ignored_reason:
            ignored[audit.ignored_reason] += 1
    outcomes = Counter(order.outcome for order in orders)
    return {
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "condition_false_days": dict(sorted(condition_false.items())),
        "ignored_reasons": dict(sorted(ignored.items())),
        "order_outcomes": dict(sorted(outcomes.items())),
    }


def _is_unavailable_for_benchmark(bar: Bar, info: InstrumentInfo) -> bool:
    if not bar.tradable:
        return True
    if bar.high != bar.low or bar.change_percent is None:
        return False
    return bar.change_percent > 0 and abs(bar.change_percent) / HUNDRED >= info.price_limit * Decimal("0.97")


def run_benchmark(
    bars: list[Bar],
    config: BacktestConfig,
    info: InstrumentInfo,
    profile: FeeProfile,
) -> BenchmarkResult:
    cash = config.initial_cash
    qty = 0
    entry_date = None
    equity: list[EquityPoint] = []
    orders: list[OrderRecord] = []
    for bar in bars:
        if bar.date < config.start_date or bar.date > config.end_date:
            continue
        if qty == 0 and not _is_unavailable_for_benchmark(bar, info):
            candidate = max_affordable_quantity(cash, bar.open, profile, config.max_position_ratio)
            if candidate > 0:
                execution = calculate_execution(bar.open, Side.BUY, candidate, profile)
                cash = money(cash + execution.cash_delta)
                qty = candidate
                entry_date = bar.date
                orders.append(OrderRecord(
                    strategy_key="BENCHMARK",
                    signal_date=bar.date,
                    planned_date=bar.date,
                    actual_date=bar.date,
                    order_type="benchmark",
                    side=Side.BUY.value,
                    outcome="executed",
                    reasons=["period_start"],
                    exec_price=execution.execution_price,
                    qty=qty,
                    commission=execution.commission,
                    transfer_fee=execution.transfer_fee,
                    slippage_cost=execution.slippage_cost,
                    cash_after=cash,
                    position_value_after=money(execution.execution_price * qty),
                ))
        position_value = money(bar.close * qty)
        equity.append(EquityPoint(bar.date, cash, position_value, money(cash + position_value)))
    metrics = compute_metrics(equity, orders, config)
    # Buy-and-hold intentionally remains open at period end.  Its entire
    # account-level P&L is therefore mark-to-market unrealized P&L; exit costs
    # and taxes are not included until a future liquidation scenario exists.
    metrics["unrealized_pnl"] = metrics["final_asset"] - config.initial_cash
    metrics["unrealized_return"] = metrics["total_return"]
    return BenchmarkResult(entry_date, equity, metrics)

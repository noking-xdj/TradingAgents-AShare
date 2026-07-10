"""Decimal-only transaction cost calculation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from .schemas import InstrumentType, Side


CENT = Decimal("0.01")
PRICE_QUANT = Decimal("0.0001")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def price(value: Decimal) -> Decimal:
    return value.quantize(PRICE_QUANT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class FeeProfile:
    commission_rate: Decimal
    minimum_commission: Decimal
    stamp_tax_rate: Decimal
    transfer_fee_rate: Decimal
    buy_slippage_rate: Decimal
    sell_slippage_rate: Decimal


STOCK_FEE_PROFILE = FeeProfile(
    commission_rate=Decimal("0.000115"),
    minimum_commission=Decimal("0"),
    stamp_tax_rate=Decimal("0.0005"),
    transfer_fee_rate=Decimal("0.00001"),
    buy_slippage_rate=Decimal("0.001"),
    sell_slippage_rate=Decimal("0.001"),
)

FUND_FEE_PROFILE = FeeProfile(
    commission_rate=Decimal("0.0001"),
    minimum_commission=Decimal("0"),
    stamp_tax_rate=Decimal("0"),
    transfer_fee_rate=Decimal("0"),
    buy_slippage_rate=Decimal("0.001"),
    sell_slippage_rate=Decimal("0.001"),
)


def default_fee_profile(instrument_type: InstrumentType) -> FeeProfile:
    if instrument_type is InstrumentType.STOCK:
        return STOCK_FEE_PROFILE
    if instrument_type is InstrumentType.FUND:
        return FUND_FEE_PROFILE
    raise ValueError("index has no supported fee profile")


@dataclass(frozen=True)
class ExecutionCost:
    reference_price: Decimal
    execution_price: Decimal
    quantity: int
    gross_amount: Decimal
    commission: Decimal
    stamp_tax: Decimal
    transfer_fee: Decimal
    slippage_cost: Decimal
    cash_delta: Decimal


def calculate_execution(
    reference_open: Decimal,
    side: Side,
    quantity: int,
    profile: FeeProfile,
) -> ExecutionCost:
    if reference_open <= 0 or quantity <= 0:
        raise ValueError("reference_open and quantity must be positive")
    slip = profile.buy_slippage_rate if side is Side.BUY else profile.sell_slippage_rate
    multiplier = Decimal("1") + slip if side is Side.BUY else Decimal("1") - slip
    execution_price = price(reference_open * multiplier)
    gross = money(execution_price * quantity)
    commission = money(max(gross * profile.commission_rate, profile.minimum_commission))
    stamp = money(gross * profile.stamp_tax_rate) if side is Side.SELL else Decimal("0.00")
    transfer = money(gross * profile.transfer_fee_rate)
    slippage = money(abs(execution_price - reference_open) * quantity)
    if side is Side.BUY:
        cash_delta = -money(gross + commission + transfer)
    else:
        cash_delta = money(gross - commission - stamp - transfer)
    return ExecutionCost(
        reference_price=reference_open,
        execution_price=execution_price,
        quantity=quantity,
        gross_amount=gross,
        commission=commission,
        stamp_tax=stamp,
        transfer_fee=transfer,
        slippage_cost=slippage,
        cash_delta=cash_delta,
    )


def max_affordable_quantity(
    cash: Decimal,
    reference_open: Decimal,
    profile: FeeProfile,
    max_position_ratio: Decimal = Decimal("1"),
    lot_size: int = 100,
) -> int:
    budget = money(cash * max_position_ratio)
    approximate_price = reference_open * (Decimal("1") + profile.buy_slippage_rate)
    quantity = int(budget / approximate_price) // lot_size * lot_size
    while quantity > 0:
        cost = calculate_execution(reference_open, Side.BUY, quantity, profile)
        if -cost.cash_delta <= budget and -cost.cash_delta <= cash:
            return quantity
        quantity -= lot_size
    return 0

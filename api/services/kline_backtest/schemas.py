"""Domain types shared by the deterministic backtest modules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable, Optional


ZERO = Decimal("0")


class InstrumentType(str, Enum):
    STOCK = "stock"
    FUND = "fund"
    INDEX = "index"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    STRATEGY = "strategy"
    RISK_EXIT = "risk_exit"


@dataclass(frozen=True)
class Bar:
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    amount: Optional[Decimal] = None
    change_percent: Optional[Decimal] = None
    turnover_rate: Optional[Decimal] = None
    tradable: bool = True


@dataclass(frozen=True)
class BacktestConfig:
    start_date: date
    end_date: date
    initial_cash: Decimal = Decimal("100000")
    max_position_ratio: Decimal = Decimal("1")
    short_ma: int = 5
    long_ma: int = 20
    pivot_left: int = 3
    pivot_right: int = 3
    fib_window: int = 60
    fib_tolerance: Decimal = Decimal("0.01")
    fib_min_amplitude: Decimal = Decimal("0.05")
    fib_mode: str = "discrete"
    trend_tolerance: Decimal = Decimal("0.005")
    trend_break_threshold: Decimal = Decimal("0.01")
    trend_min_touches: int = 3
    pivot_min_separation: int = 5
    stop_loss: Optional[Decimal] = Decimal("0.08")
    take_profit: Optional[Decimal] = Decimal("0.15")
    max_deferred_days: int = 5
    risk_free_rate: Decimal = Decimal("0.02")
    annual_trading_days: int = 252

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        if self.short_ma <= 0 or self.long_ma <= 0 or self.short_ma >= self.long_ma:
            raise ValueError("moving-average periods require 0 < short_ma < long_ma")
        if not ZERO < self.max_position_ratio <= Decimal("1"):
            raise ValueError("max_position_ratio must be in (0, 1]")
        if self.initial_cash <= ZERO:
            raise ValueError("initial_cash must be positive")
        if self.fib_mode not in {"discrete", "zone"}:
            raise ValueError("fib_mode must be 'discrete' or 'zone'")
        if self.max_deferred_days < 0:
            raise ValueError("max_deferred_days must be non-negative")
        if self.trend_min_touches < 3:
            raise ValueError("trend_min_touches must be at least 3")


@dataclass
class Position:
    qty: int
    entry_price: Decimal
    entry_total_cost: Decimal
    entry_index: int
    entry_date: date
    stop_price: Optional[Decimal]
    take_profit_price: Optional[Decimal]
    wave_snapshot: Optional[Any] = None


@dataclass
class Order:
    side: Side
    order_type: OrderType
    signal_index: int
    planned_index: int
    reasons: list[str]
    theory_trigger_price: Optional[Decimal] = None
    wave_snapshot: Optional[Any] = None
    deferred_days: int = 0


@dataclass
class OrderRecord:
    strategy_key: str
    signal_date: date
    planned_date: Optional[date]
    actual_date: Optional[date]
    order_type: str
    side: str
    outcome: str
    reasons: list[str]
    deferred_days: int = 0
    theory_trigger_price: Optional[Decimal] = None
    exec_price: Optional[Decimal] = None
    qty: int = 0
    commission: Decimal = ZERO
    stamp_tax: Decimal = ZERO
    transfer_fee: Decimal = ZERO
    slippage_cost: Decimal = ZERO
    realized_pnl: Optional[Decimal] = None
    cash_after: Optional[Decimal] = None
    position_value_after: Optional[Decimal] = None
    wave_snapshot: Optional[Any] = None


@dataclass
class EquityPoint:
    date: date
    cash: Decimal
    position_value: Decimal
    total: Decimal
    drawdown: Decimal = ZERO


@dataclass
class SignalDecision:
    buy: bool = False
    sell: bool = False
    buy_reasons: list[str] = field(default_factory=list)
    sell_reasons: list[str] = field(default_factory=list)
    conditions: dict[str, bool] = field(default_factory=dict)
    wave_snapshot: Optional[Any] = None


@dataclass
class IndicatorSnapshot:
    index: int
    date: date
    ma_short: Optional[Decimal]
    ma_long: Optional[Decimal]
    cross_up: bool
    cross_down: bool
    visible_pivots: list[Any]
    swing: Optional[Any]
    fib_touched: bool
    fib_rebound: bool
    touched_levels: list[str]
    trendline: Optional[Any]
    trendline_price: Optional[Decimal]
    trendline_broken: bool


@dataclass
class AuditRecord:
    strategy_key: str
    date: date
    decision: SignalDecision
    snapshot: IndicatorSnapshot
    ignored_reason: Optional[str] = None


@dataclass
class StrategyResult:
    strategy_key: str
    orders: list[OrderRecord]
    equity: list[EquityPoint]
    audits: list[AuditRecord]
    metrics: dict[str, Any]
    signal_stats: dict[str, Any]
    open_position: Optional[Position]


@dataclass
class BenchmarkResult:
    actual_entry_date: Optional[date]
    equity: list[EquityPoint]
    metrics: dict[str, Any]


@dataclass
class BacktestRunResult:
    symbol: str
    data_hash: str
    strategy_results: dict[str, StrategyResult]
    benchmark: BenchmarkResult


def primitive(value: Any) -> Any:
    """Convert domain objects into stable JSON-compatible values."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [primitive(item) for item in value]
    return value


def bars_in_period(bars: Iterable[Bar], start: date, end: date) -> list[Bar]:
    return [bar for bar in bars if start <= bar.date <= end]

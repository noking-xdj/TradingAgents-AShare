"""Domain types shared by the deterministic backtest modules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable, Literal, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator


ZERO = Decimal("0")


class InstrumentType(str, Enum):
    STOCK = "stock"
    FUND = "fund"
    INDEX = "index"


class KlineDataSource(str, Enum):
    EASTMONEY = "eastmoney"
    SINA = "sina"
    TENCENT = "tencent"


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


def previous_full_year(today: date | None = None) -> tuple[date, date]:
    current = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    year = current.year - 1
    return date(year, 1, 1), date(year, 12, 31)


class FeeProfileRequest(BaseModel):
    commission_rate: Decimal | None = Field(default=None, ge=ZERO)
    minimum_commission: Decimal | None = Field(default=None, ge=ZERO)
    stamp_tax_rate: Decimal | None = Field(default=None, ge=ZERO)
    transfer_fee_rate: Decimal | None = Field(default=None, ge=ZERO)
    buy_slippage_rate: Decimal | None = Field(default=None, ge=ZERO, lt=Decimal("1"))
    sell_slippage_rate: Decimal | None = Field(default=None, ge=ZERO, lt=Decimal("1"))


class KlineBacktestCreateRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    start_date: date | None = None
    end_date: date | None = None
    instrument_type_override: Literal["stock", "fund"] | None = None
    strategy_keys: list[Literal["A", "B", "C", "D"]] = Field(
        default_factory=lambda: ["A", "B", "C", "D"],
    )
    data_source: KlineDataSource = KlineDataSource.TENCENT
    adjust: Literal["qfq", "hfq", "none", "raw"] = "qfq"
    force_refresh: bool = False

    initial_cash: Decimal = Field(default=Decimal("100000"), gt=ZERO)
    max_position_ratio: Decimal = Field(default=Decimal("1"), gt=ZERO, le=Decimal("1"))
    short_ma: int = Field(default=5, gt=0)
    long_ma: int = Field(default=20, gt=0)
    pivot_left: int = Field(default=3, gt=0)
    pivot_right: int = Field(default=3, gt=0)
    fib_window: int = Field(default=60, gt=0)
    fib_tolerance: Decimal = Field(default=Decimal("0.01"), ge=ZERO, lt=Decimal("1"))
    fib_min_amplitude: Decimal = Field(default=Decimal("0.05"), ge=ZERO, lt=Decimal("1"))
    fib_mode: Literal["discrete", "zone"] = "discrete"
    trend_tolerance: Decimal = Field(default=Decimal("0.005"), ge=ZERO, lt=Decimal("1"))
    trend_break_threshold: Decimal = Field(default=Decimal("0.01"), ge=ZERO, lt=Decimal("1"))
    trend_min_touches: int = Field(default=3, ge=3)
    pivot_min_separation: int = Field(default=5, gt=0)
    stop_loss: Decimal | None = Field(default=Decimal("0.08"), gt=ZERO, lt=Decimal("1"))
    take_profit: Decimal | None = Field(default=Decimal("0.15"), gt=ZERO)
    max_deferred_days: int = Field(default=5, ge=0)
    risk_free_rate: Decimal = Field(default=Decimal("0.02"), ge=ZERO)
    annual_trading_days: int = Field(default=252, gt=0)
    fee: FeeProfileRequest | None = None

    @model_validator(mode="before")
    @classmethod
    def apply_instrument_source_defaults(cls, value: Any) -> Any:
        """Choose an explicit healthy default before the request is persisted."""
        if not isinstance(value, dict):
            return value
        source_missing = value.get("data_source") in {None, ""}
        adjust_missing = value.get("adjust") in {None, ""}
        if not source_missing and not adjust_missing:
            return value

        data = dict(value)
        try:
            from .instrument import classify_instrument

            info = classify_instrument(
                str(data.get("symbol") or ""),
                data.get("instrument_type_override"),
            )
        except (TypeError, ValueError):
            return data

        if source_missing:
            data["data_source"] = (
                KlineDataSource.SINA.value
                if info.instrument_type is InstrumentType.FUND or info.market == "BJ"
                else KlineDataSource.TENCENT.value
            )
        selected_source = KlineDataSource(data["data_source"])
        if adjust_missing:
            data["adjust"] = (
                "raw"
                if info.instrument_type is InstrumentType.FUND and selected_source is KlineDataSource.SINA
                else "qfq"
            )
        return data

    @field_validator("strategy_keys")
    @classmethod
    def validate_strategy_keys(cls, value: list[str]) -> list[str]:
        unique = list(dict.fromkeys(value))
        if not unique:
            raise ValueError("at least one strategy is required")
        return unique

    @model_validator(mode="after")
    def validate_ranges(self) -> "KlineBacktestCreateRequest":
        if self.start_date is None and self.end_date is None:
            self.start_date, self.end_date = previous_full_year()
        elif self.start_date is None or self.end_date is None:
            raise ValueError("start_date and end_date must be provided together")
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        if self.short_ma >= self.long_ma:
            raise ValueError("short_ma must be less than long_ma")
        return self

    def engine_config(self) -> BacktestConfig:
        return BacktestConfig(
            start_date=self.start_date,
            end_date=self.end_date,
            initial_cash=self.initial_cash,
            max_position_ratio=self.max_position_ratio,
            short_ma=self.short_ma,
            long_ma=self.long_ma,
            pivot_left=self.pivot_left,
            pivot_right=self.pivot_right,
            fib_window=self.fib_window,
            fib_tolerance=self.fib_tolerance,
            fib_min_amplitude=self.fib_min_amplitude,
            fib_mode=self.fib_mode,
            trend_tolerance=self.trend_tolerance,
            trend_break_threshold=self.trend_break_threshold,
            trend_min_touches=self.trend_min_touches,
            pivot_min_separation=self.pivot_min_separation,
            stop_loss=self.stop_loss,
            take_profit=self.take_profit,
            max_deferred_days=self.max_deferred_days,
            risk_free_rate=self.risk_free_rate,
            annual_trading_days=self.annual_trading_days,
        )

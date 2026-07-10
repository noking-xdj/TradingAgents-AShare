"""Strict AkShare data loading, normalization, caching and hashing."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time as time_module
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from http.client import RemoteDisconnected
from typing import Any, Callable, Iterable, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
from requests import exceptions as requests_exceptions
from sqlalchemy.orm import Session

from api.models.kline_backtest import KlineCacheDB
from tradingagents.dataflows.providers.cn_akshare_provider import AKSHARE_CALL_LOCK

from .instrument import require_backtestable
from .schemas import Bar, InstrumentType, KlineDataSource, primitive


SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_CACHE_TTL = timedelta(days=7)
DEFAULT_AKSHARE_MAX_ATTEMPTS = 3
DEFAULT_AKSHARE_RETRY_BASE_SECONDS = 1.0

logger = logging.getLogger(__name__)


class KlineDataSourceConnectionError(RuntimeError):
    """Raised after the configured AkShare connection retries are exhausted."""


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default


def _is_retryable_connection_error(exc: BaseException) -> bool:
    retryable = (
        requests_exceptions.ConnectionError,
        requests_exceptions.Timeout,
        ConnectionError,
        TimeoutError,
        RemoteDisconnected,
    )
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        if isinstance(current, retryable):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


@dataclass(frozen=True)
class NormalizedKlineData:
    symbol: str
    adjust: str
    source_api: str
    akshare_version: str
    fetched_at: datetime
    bars: list[Bar]
    data_hash: str

    @property
    def actual_start(self) -> Optional[date]:
        return self.bars[0].date if self.bars else None

    @property
    def actual_end(self) -> Optional[date]:
        return self.bars[-1].date if self.bars else None


ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("日期", "date", "Date", "时间"),
    "open": ("开盘", "open", "Open"),
    "high": ("最高", "high", "High"),
    "low": ("最低", "low", "Low"),
    "close": ("收盘", "close", "Close"),
    "volume": ("成交量", "volume", "Volume", "vol"),
    "amount": ("成交额", "amount", "Amount"),
    "change_percent": ("涨跌幅", "change_percent", "pct_chg"),
    "turnover_rate": ("换手率", "turnover_rate", "turnover"),
}


SOURCE_APIS: dict[InstrumentType, dict[KlineDataSource, str]] = {
    InstrumentType.STOCK: {
        KlineDataSource.EASTMONEY: "stock_zh_a_hist",
        KlineDataSource.SINA: "stock_zh_a_daily",
        KlineDataSource.TENCENT: "stock_zh_a_hist_tx",
    },
    InstrumentType.FUND: {
        KlineDataSource.EASTMONEY: "fund_etf_hist_em",
        KlineDataSource.SINA: "fund_etf_hist_sina",
    },
}


def source_api_for(
    instrument_type: InstrumentType,
    data_source: KlineDataSource | str,
    *,
    adjust: str,
    market: str | None = None,
) -> str:
    """Resolve one explicitly selected AkShare endpoint without fallback."""
    selected = KlineDataSource(data_source)
    source_api = SOURCE_APIS.get(instrument_type, {}).get(selected)
    if source_api is None:
        raise ValueError(f"{instrument_type.value} 暂不支持 {selected.value} 数据源")
    if instrument_type is InstrumentType.FUND and selected is KlineDataSource.SINA:
        if adjust not in {"none", "raw", ""}:
            raise ValueError("场内基金的新浪接口只支持不复权数据")
    if market == "BJ" and selected is KlineDataSource.TENCENT:
        raise ValueError("北交所股票暂不支持腾讯数据源")
    return source_api


def _find_column(df: pd.DataFrame, key: str, *, required: bool) -> Optional[str]:
    for candidate in ALIASES[key]:
        if candidate in df.columns:
            return candidate
    if required:
        raise ValueError(f"AkShare dataframe missing required field: {key}")
    return None


def _decimal(value: Any, field: str) -> Decimal:
    if value is None or pd.isna(value):
        raise ValueError(f"missing numeric field: {field}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid numeric field {field}: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"non-finite numeric field {field}: {value!r}")
    return result


def _optional_decimal(value: Any) -> Optional[Decimal]:
    if value is None or pd.isna(value):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _is_incomplete_today(day: date, now: datetime) -> bool:
    local_now = now.astimezone(SHANGHAI) if now.tzinfo else now.replace(tzinfo=SHANGHAI)
    return day == local_now.date() and local_now.time() < time(15, 0)


def canonical_data_hash(bars: list[Bar], adjust: str) -> str:
    payload = {
        "adjust": adjust,
        "bars": [
            {
                "date": bar.date.isoformat(),
                "open": format(bar.open, "f"),
                "high": format(bar.high, "f"),
                "low": format(bar.low, "f"),
                "close": format(bar.close, "f"),
                "volume": format(bar.volume, "f"),
                "amount": None if bar.amount is None else format(bar.amount, "f"),
                "change_percent": None if bar.change_percent is None else format(bar.change_percent, "f"),
                "turnover_rate": None if bar.turnover_rate is None else format(bar.turnover_rate, "f"),
            }
            for bar in bars
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def align_to_trading_calendar(
    data: NormalizedKlineData,
    trading_dates: Iterable[date],
) -> NormalizedKlineData:
    """Insert non-tradable placeholder bars for suspension dates.

    AkShare omits suspended securities from their daily history.  The engine
    still needs those exchange trading days to age pending orders correctly.
    Missing dates after the first real bar are therefore filled at the previous
    close with zero volume and ``tradable=False``.
    """
    aligned = align_bars_to_trading_calendar(data.bars, trading_dates)
    return NormalizedKlineData(
        symbol=data.symbol,
        adjust=data.adjust,
        source_api=data.source_api,
        akshare_version=data.akshare_version,
        fetched_at=data.fetched_at,
        bars=aligned,
        data_hash=canonical_data_hash(aligned, data.adjust),
    )


def align_bars_to_trading_calendar(
    bars: Iterable[Bar],
    trading_dates: Iterable[date],
) -> list[Bar]:
    """Align bars to exchange dates without inventing tradable observations."""
    by_date = {bar.date: bar for bar in bars}
    aligned: list[Bar] = []
    previous: Optional[Bar] = None
    for day in sorted(set(trading_dates)):
        current = by_date.get(day)
        if current is not None:
            aligned.append(current)
            previous = current
            continue
        if previous is None:
            continue
        aligned.append(Bar(
            date=day,
            open=previous.close,
            high=previous.close,
            low=previous.close,
            close=previous.close,
            volume=Decimal("0"),
            amount=Decimal("0"),
            change_percent=Decimal("0"),
            turnover_rate=Decimal("0"),
            tradable=False,
        ))
    if not aligned:
        raise ValueError("trading calendar does not overlap K-line data")
    return aligned


def normalize_dataframe(
    df: pd.DataFrame,
    *,
    symbol: str,
    adjust: str,
    source_api: str,
    akshare_version: str,
    fetched_at: Optional[datetime] = None,
) -> NormalizedKlineData:
    if df is None or df.empty:
        raise ValueError("AkShare returned no K-line data")
    fetched_at = fetched_at or datetime.now(timezone.utc)
    columns = {
        key: _find_column(df, key, required=key in {"date", "open", "high", "low", "close", "volume"})
        for key in ALIASES
    }
    normalized: dict[date, Bar] = {}
    previous_close: Optional[Decimal] = None
    working = df.copy()
    working[columns["date"]] = pd.to_datetime(working[columns["date"]], errors="coerce")
    working = working.dropna(subset=[columns["date"]]).sort_values(columns["date"])
    for _, row in working.iterrows():
        day = row[columns["date"]].date()
        if _is_incomplete_today(day, fetched_at):
            continue
        open_price = _decimal(row[columns["open"]], "open")
        high = _decimal(row[columns["high"]], "high")
        low = _decimal(row[columns["low"]], "low")
        close = _decimal(row[columns["close"]], "close")
        volume = _decimal(row[columns["volume"]], "volume")
        if min(open_price, high, low, close) <= 0:
            raise ValueError(f"non-positive OHLC value on {day}")
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            raise ValueError(f"invalid OHLC range on {day}")
        amount = _optional_decimal(row[columns["amount"]]) if columns["amount"] else None
        change_pct = _optional_decimal(row[columns["change_percent"]]) if columns["change_percent"] else None
        if change_pct is None and previous_close not in (None, Decimal("0")):
            change_pct = (close - previous_close) / previous_close * Decimal("100")
        turnover_rate = _optional_decimal(row[columns["turnover_rate"]]) if columns["turnover_rate"] else None
        normalized[day] = Bar(
            date=day,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
            amount=amount,
            change_percent=change_pct,
            turnover_rate=turnover_rate,
            tradable=volume > 0,
        )
        previous_close = close
    bars = [normalized[day] for day in sorted(normalized)]
    if not bars:
        raise ValueError("no completed K-line bars after normalization")
    return NormalizedKlineData(
        symbol=symbol,
        adjust=adjust,
        source_api=source_api,
        akshare_version=akshare_version,
        fetched_at=fetched_at,
        bars=bars,
        data_hash=canonical_data_hash(bars, adjust),
    )


def _bar_payload(bar: Bar) -> dict[str, Any]:
    return primitive(bar)


def _bar_from_payload(item: dict[str, Any]) -> Bar:
    return Bar(
        date=date.fromisoformat(item["date"]),
        open=Decimal(item["open"]),
        high=Decimal(item["high"]),
        low=Decimal(item["low"]),
        close=Decimal(item["close"]),
        volume=Decimal(item["volume"]),
        amount=Decimal(item["amount"]) if item.get("amount") is not None else None,
        change_percent=Decimal(item["change_percent"]) if item.get("change_percent") is not None else None,
        turnover_rate=Decimal(item["turnover_rate"]) if item.get("turnover_rate") is not None else None,
        tradable=bool(item.get("tradable", True)),
    )


class KlineCacheStore:
    def __init__(self, session: Session):
        self.session = session

    def get(
        self,
        *,
        symbol: str,
        adjust: str,
        start_date: date,
        end_date: date,
        source_api: str | None = None,
        now: Optional[datetime] = None,
    ) -> Optional[NormalizedKlineData]:
        now = now or datetime.now(timezone.utc)
        query = self.session.query(KlineCacheDB).filter(
            KlineCacheDB.symbol == symbol,
            KlineCacheDB.adjust == adjust,
            KlineCacheDB.start_date <= start_date.isoformat(),
            KlineCacheDB.end_date >= end_date.isoformat(),
            KlineCacheDB.expires_at > now,
        )
        if source_api is not None:
            query = query.filter(KlineCacheDB.source_api == source_api)
        record = (
            query
            .order_by(KlineCacheDB.fetched_at.desc())
            .first()
        )
        if record is None:
            return None
        bars = [
            bar for bar in (_bar_from_payload(item) for item in record.payload)
            if start_date <= bar.date <= end_date
        ]
        if not bars:
            return None
        return NormalizedKlineData(
            symbol=symbol,
            adjust=adjust,
            source_api=record.source_api,
            akshare_version=record.akshare_version,
            fetched_at=record.fetched_at,
            bars=bars,
            data_hash=canonical_data_hash(bars, adjust),
        )

    def put(self, data: NormalizedKlineData, ttl: timedelta = DEFAULT_CACHE_TTL) -> KlineCacheDB:
        existing = (
            self.session.query(KlineCacheDB)
            .filter(
                KlineCacheDB.symbol == data.symbol,
                KlineCacheDB.adjust == data.adjust,
                KlineCacheDB.start_date == data.actual_start.isoformat(),
                KlineCacheDB.end_date == data.actual_end.isoformat(),
                KlineCacheDB.source_api == data.source_api,
                KlineCacheDB.data_hash == data.data_hash,
            )
            .first()
        )
        if existing is not None:
            existing.fetched_at = data.fetched_at
            existing.expires_at = data.fetched_at + ttl
            existing.akshare_version = data.akshare_version
            existing.source_api = data.source_api
            existing.payload = [_bar_payload(bar) for bar in data.bars]
            self.session.commit()
            return existing
        record = KlineCacheDB(
            id=uuid4().hex,
            symbol=data.symbol,
            adjust=data.adjust,
            start_date=data.actual_start.isoformat(),
            end_date=data.actual_end.isoformat(),
            fetched_at=data.fetched_at,
            expires_at=data.fetched_at + ttl,
            akshare_version=data.akshare_version,
            source_api=data.source_api,
            data_hash=data.data_hash,
            payload=[_bar_payload(bar) for bar in data.bars],
        )
        self.session.add(record)
        self.session.commit()
        return record


class AkshareKlineProvider:
    """One explicitly selected AkShare endpoint per run; no silent fallback."""

    def __init__(
        self,
        *,
        max_attempts: int | None = None,
        retry_base_seconds: float | None = None,
        sleeper: Callable[[float], None] = time_module.sleep,
    ) -> None:
        self.max_attempts = max_attempts if max_attempts is not None else _env_int(
            "KLINE_AKSHARE_MAX_ATTEMPTS", DEFAULT_AKSHARE_MAX_ATTEMPTS,
        )
        self.retry_base_seconds = (
            retry_base_seconds
            if retry_base_seconds is not None
            else _env_float("KLINE_AKSHARE_RETRY_BASE_SECONDS", DEFAULT_AKSHARE_RETRY_BASE_SECONDS)
        )
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.retry_base_seconds < 0:
            raise ValueError("retry_base_seconds must be non-negative")
        self._sleep = sleeper

    def _fetch_frame(
        self,
        fetcher: Callable[..., pd.DataFrame],
        *,
        source_api: str,
        symbol: str,
        kwargs: dict[str, Any],
        requested_start: date,
        requested_end: date,
        requested_adjust: str,
    ) -> pd.DataFrame:
        for attempt in range(1, self.max_attempts + 1):
            logger.info(
                "AkShare K-line fetch attempt source=%s symbol=%s attempt=%s/%s start=%s end=%s adjust=%s",
                source_api,
                symbol,
                attempt,
                self.max_attempts,
                requested_start.isoformat(),
                requested_end.isoformat(),
                requested_adjust or "raw",
            )
            try:
                with AKSHARE_CALL_LOCK:
                    frame = fetcher(**kwargs)
                logger.info(
                    "AkShare K-line fetch success source=%s symbol=%s attempt=%s/%s rows=%s",
                    source_api,
                    symbol,
                    attempt,
                    self.max_attempts,
                    len(frame),
                )
                return frame
            except Exception as exc:
                if not _is_retryable_connection_error(exc):
                    logger.error(
                        "AkShare K-line fetch failed without retry source=%s symbol=%s attempt=%s/%s error_type=%s error=%s",
                        source_api,
                        symbol,
                        attempt,
                        self.max_attempts,
                        type(exc).__name__,
                        exc,
                    )
                    raise
                if attempt >= self.max_attempts:
                    message = (
                        f"AkShare {source_api} connection failed after {self.max_attempts} attempts "
                        f"for {symbol}: {type(exc).__name__}: {exc}"
                    )
                    logger.error(
                        "AkShare K-line connection exhausted source=%s symbol=%s attempts=%s error_type=%s error=%s",
                        source_api,
                        symbol,
                        self.max_attempts,
                        type(exc).__name__,
                        exc,
                    )
                    raise KlineDataSourceConnectionError(message) from exc
                delay = self.retry_base_seconds * (2 ** (attempt - 1))
                logger.warning(
                    "AkShare K-line connection retry source=%s symbol=%s attempt=%s/%s delay_seconds=%.3f error_type=%s error=%s",
                    source_api,
                    symbol,
                    attempt,
                    self.max_attempts,
                    delay,
                    type(exc).__name__,
                    exc,
                )
                if delay > 0:
                    self._sleep(delay)
        raise AssertionError("unreachable")

    def fetch(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        *,
        adjust: str = "qfq",
        data_source: KlineDataSource | str = KlineDataSource.EASTMONEY,
        cache: Optional[KlineCacheStore] = None,
        force_refresh: bool = False,
        now: Optional[datetime] = None,
        instrument_type_override: str | None = None,
    ) -> NormalizedKlineData:
        info = require_backtestable(symbol, instrument_type_override)
        selected_source = KlineDataSource(data_source)
        source_api = source_api_for(
            info.instrument_type,
            selected_source,
            adjust=adjust,
            market=info.market,
        )
        if cache is not None and not force_refresh:
            cached = cache.get(
                symbol=info.symbol,
                adjust=adjust,
                start_date=start_date,
                end_date=end_date,
                source_api=source_api,
                now=now,
            )
            if cached is not None:
                return cached
        import akshare as ak  # type: ignore

        adjust_arg = "" if adjust in {"none", "raw", ""} else adjust
        compact_start = start_date.strftime("%Y%m%d")
        compact_end = end_date.strftime("%Y%m%d")
        market_symbol = f"{info.market.lower()}{info.code}"
        if source_api in {"stock_zh_a_hist", "fund_etf_hist_em"}:
            kwargs = {
                "symbol": info.code,
                "period": "daily",
                "start_date": compact_start,
                "end_date": compact_end,
                "adjust": adjust_arg,
            }
        elif source_api == "fund_etf_hist_sina":
            kwargs = {"symbol": market_symbol}
        else:
            kwargs = {
                "symbol": market_symbol,
                "start_date": compact_start,
                "end_date": compact_end,
                "adjust": adjust_arg,
            }
        fetcher = getattr(ak, source_api)
        frame = self._fetch_frame(
            fetcher,
            source_api=source_api,
            symbol=info.symbol,
            kwargs=kwargs,
            requested_start=start_date,
            requested_end=end_date,
            requested_adjust=adjust,
        )
        result = normalize_dataframe(
            frame,
            symbol=info.symbol,
            adjust=adjust,
            source_api=source_api,
            akshare_version=getattr(ak, "__version__", "unknown"),
            fetched_at=now,
        )
        selected_bars = [bar for bar in result.bars if start_date <= bar.date <= end_date]
        if not selected_bars:
            raise ValueError("AkShare returned no K-line data in the requested period")
        if len(selected_bars) != len(result.bars):
            result = NormalizedKlineData(
                symbol=result.symbol,
                adjust=result.adjust,
                source_api=result.source_api,
                akshare_version=result.akshare_version,
                fetched_at=result.fetched_at,
                bars=selected_bars,
                data_hash=canonical_data_hash(selected_bars, result.adjust),
            )
        if cache is not None:
            cache.put(result)
        return result

    def fetch_with_warmup(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        **kwargs: Any,
    ) -> NormalizedKlineData:
        # 240 calendar days safely covers at least 120 trading days in the
        # supported mainland markets, including long holiday periods.
        return self.fetch(symbol, start_date - timedelta(days=240), end_date, **kwargs)

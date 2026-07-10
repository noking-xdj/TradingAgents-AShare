"""Dedicated in-process queue and app-owned orphan recovery."""

from __future__ import annotations

import os
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Lock
from typing import Any

from api.database import get_db_ctx
from tradingagents.dataflows.providers.cn_akshare_provider import AKSHARE_CALL_LOCK
from tradingagents.dataflows.trade_calendar import _load_cn_trade_dates

from . import repository
from .data_provider import AkshareKlineProvider, KlineCacheStore, NormalizedKlineData
from .fees import FeeProfile
from .instrument import require_backtestable
from .runner import run_backtest
from .schemas import InstrumentType, KlineBacktestCreateRequest


def _fee_profile(snapshot: dict[str, Any]) -> FeeProfile:
    return FeeProfile(**{key: Decimal(str(value)) for key, value in snapshot.items()})


def _trading_dates(start: date, end: date) -> list[date]:
    with AKSHARE_CALL_LOCK:
        dates, _ = _load_cn_trade_dates()
    if not dates:
        raise ValueError("AkShare 交易日历不可用，无法可靠处理停牌顺延")
    selected = [item for item in dates if start <= item <= end]
    if not selected:
        raise ValueError("请求区间内没有可用的 A 股交易日")
    return selected


class KlineBacktestTaskManager:
    """A lazy, dedicated executor that never shares the analysis pool."""

    def __init__(self, *, max_workers: int | None = None, provider=None):
        configured = int(os.getenv("KLINE_BACKTEST_MAX_WORKERS", "1")) if max_workers is None else max_workers
        if configured < 1:
            raise ValueError("KLINE_BACKTEST_MAX_WORKERS must be at least 1")
        self.max_workers = configured
        self.provider = provider or AkshareKlineProvider()
        self._executor: ThreadPoolExecutor | None = None
        self._lock = Lock()

    def _get_executor(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self.max_workers,
                    thread_name_prefix="kline-backtest",
                )
            return self._executor

    def submit(self, run_id: str) -> Future:
        return self._get_executor().submit(self.execute, run_id)

    def _load_data(self, request: KlineBacktestCreateRequest) -> NormalizedKlineData:
        # Fetch an extra buffer so cache coverage is stable when the requested
        # warmup boundary falls on a weekend or long exchange holiday.
        fetch_start = request.start_date - timedelta(days=270)
        cache_start = request.start_date - timedelta(days=240)
        info = require_backtestable(request.symbol, request.instrument_type_override)
        source_api = "fund_etf_hist_em" if info.instrument_type is InstrumentType.FUND else "stock_zh_a_hist"
        if not request.force_refresh:
            with get_db_ctx() as db:
                cached = KlineCacheStore(db).get(
                    symbol=request.symbol,
                    adjust=request.adjust,
                    start_date=cache_start,
                    end_date=request.end_date,
                    source_api=source_api,
                )
            if cached is not None:
                return cached

        data = self.provider.fetch(
            request.symbol,
            fetch_start,
            request.end_date,
            adjust=request.adjust,
            cache=None,
            force_refresh=True,
            instrument_type_override=request.instrument_type_override,
        )
        with get_db_ctx() as db:
            KlineCacheStore(db).put(data)
        return data

    @staticmethod
    def _fail(run_id: str, *, error_code: str, exc: Exception) -> None:
        message = f"{type(exc).__name__}: {exc}"[:4000]
        with get_db_ctx() as db:
            repository.mark_failed(db, run_id, error_code=error_code, error=message)

    def execute(self, run_id: str) -> None:
        with get_db_ctx() as db:
            if not repository.mark_running(db, run_id):
                return
            run = repository.get_run_for_execution(db, run_id)
            if run is None:
                return
            params_snapshot = dict(run.params_snapshot)
            fee_snapshot = dict(run.fee_snapshot)

        try:
            request = KlineBacktestCreateRequest.model_validate(params_snapshot)
            config = request.engine_config()
            data = self._load_data(request)
            warmup_count = sum(bar.date < request.start_date for bar in data.bars)
            if warmup_count < 120:
                raise ValueError(f"预热数据不足：需要至少 120 个交易日，实际 {warmup_count}")
            calendar = _trading_dates(data.actual_start, request.end_date)
            result = run_backtest(
                request.symbol,
                data.bars,
                config,
                strategy_keys=request.strategy_keys,
                fee_profile=_fee_profile(fee_snapshot),
                adjust=request.adjust,
                trading_dates=calendar,
            )
            actual_data_range = {
                "actual_start": data.actual_start.isoformat(),
                "actual_end": data.actual_end.isoformat(),
                "statistics_start": request.start_date.isoformat(),
                "statistics_end": request.end_date.isoformat(),
                "warmup_bars": warmup_count,
                "source_api": data.source_api,
                "akshare_version": data.akshare_version,
                "fetched_at": data.fetched_at.isoformat(),
                "adjust": request.adjust,
            }
        except Exception as exc:
            self._fail(run_id, error_code="execution_failed", exc=exc)
            return

        try:
            with get_db_ctx() as db:
                repository.persist_completed_run(
                    db,
                    run_id=run_id,
                    result=result,
                    actual_data_range=actual_data_range,
                    cache_version=data.data_hash,
                )
        except Exception as exc:
            self._fail(run_id, error_code="persistence_failed", exc=exc)

    def shutdown(self) -> None:
        with self._lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=True)


_manager = KlineBacktestTaskManager()


def submit_run(run_id: str) -> Future:
    return _manager.submit(run_id)


def recover_orphaned_runs() -> int:
    with get_db_ctx() as db:
        return repository.recover_orphaned_runs(db)


def shutdown() -> None:
    _manager.shutdown()

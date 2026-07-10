import sys
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
from requests import exceptions as requests_exceptions
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import Base
from api.models.kline_backtest import (
    KBBenchmarkEquityDB,
    KBEquityDB,
    KBRunDB,
    KBSignalAuditDB,
    KBStrategyResultDB,
    KBTradeDB,
    KlineCacheDB,
)
from api.services.kline_backtest.data_provider import (
    AkshareKlineProvider,
    KlineCacheStore,
    KlineDataSourceConnectionError,
    align_to_trading_calendar,
    normalize_dataframe,
    source_api_for,
)
from api.services.kline_backtest.fees import (
    FUND_FEE_PROFILE,
    STOCK_FEE_PROFILE,
    calculate_execution,
    max_affordable_quantity,
)
from api.services.kline_backtest.instrument import classify_instrument, require_backtestable
from api.services.kline_backtest.runner import _prepare_timeline
from api.services.kline_backtest.schemas import BacktestConfig, Bar
from api.services.kline_backtest.schemas import InstrumentType, KlineDataSource, Side


@pytest.mark.parametrize(
    ("symbol", "kind", "board", "limit"),
    [
        ("600519", InstrumentType.STOCK, "main", Decimal("0.10")),
        ("300750.SZ", InstrumentType.STOCK, "chinext", Decimal("0.20")),
        ("688001.SH", InstrumentType.STOCK, "star", Decimal("0.20")),
        ("830799", InstrumentType.STOCK, "bse", Decimal("0.30")),
        ("920001", InstrumentType.STOCK, "bse", Decimal("0.30")),
        ("510300.SH", InstrumentType.FUND, "main", Decimal("0.10")),
        ("159915", InstrumentType.FUND, "main", Decimal("0.10")),
    ],
)
def test_instrument_classification(symbol, kind, board, limit):
    info = classify_instrument(symbol)
    assert info.instrument_type is kind
    assert info.board == board
    assert info.price_limit == limit


def test_index_is_explicitly_rejected():
    assert classify_instrument("000001.SH").instrument_type is InstrumentType.INDEX
    with pytest.raises(ValueError, match="不支持指数"):
        require_backtestable("000001.SH")


def test_stock_fee_profile_is_decimal_and免五():
    buy = calculate_execution(Decimal("10"), Side.BUY, 10_000, STOCK_FEE_PROFILE)
    assert buy.execution_price == Decimal("10.0100")
    assert buy.gross_amount == Decimal("100100.00")
    assert buy.commission == Decimal("11.51")
    assert buy.transfer_fee == Decimal("1.00")
    assert buy.stamp_tax == Decimal("0.00")
    assert buy.slippage_cost == Decimal("100.00")
    assert buy.cash_delta == Decimal("-100112.51")

    sell = calculate_execution(Decimal("10"), Side.SELL, 10_000, STOCK_FEE_PROFILE)
    assert sell.execution_price == Decimal("9.9900")
    assert sell.commission == Decimal("11.49")
    assert sell.stamp_tax == Decimal("49.95")
    assert sell.transfer_fee == Decimal("1.00")
    assert sell.cash_delta == Decimal("99837.56")


def test_fund_has_no_stamp_or_transfer_fee_and_affordable_lots_reserve_fees():
    sell = calculate_execution(Decimal("10"), Side.SELL, 10_000, FUND_FEE_PROFILE)
    assert sell.commission == Decimal("9.99")
    assert sell.stamp_tax == Decimal("0.00")
    assert sell.transfer_fee == Decimal("0.00")
    assert max_affordable_quantity(
        Decimal("100000"), Decimal("10"), STOCK_FEE_PROFILE,
    ) == 9900


def _frame() -> pd.DataFrame:
    return pd.DataFrame([
        {"日期": "2025-01-02", "开盘": 10, "最高": 11, "最低": 9, "收盘": 10.5, "成交量": 100, "成交额": 1_000_000, "涨跌幅": 5},
        {"日期": "2025-01-03", "开盘": 10.5, "最高": 12, "最低": 10, "收盘": 11.5, "成交量": 120, "成交额": 1_300_000, "涨跌幅": 9.52},
    ])


def _english_frame() -> pd.DataFrame:
    return pd.DataFrame([
        {"date": "2025-01-02", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100, "amount": 1_000_000, "turnover": 0.012},
        {"date": "2025-01-03", "open": 10.5, "high": 12, "low": 10, "close": 11.5, "volume": 120, "amount": 1_300_000, "turnover": 0.014},
    ])


def test_normalization_keeps_amount_separate_from_volume_and_hash_is_stable():
    now = datetime(2025, 1, 4, 16, tzinfo=timezone.utc)
    first = normalize_dataframe(
        _frame(), symbol="600519.SH", adjust="qfq", source_api="stock_zh_a_hist",
        akshare_version="test", fetched_at=now,
    )
    second = normalize_dataframe(
        _frame()[list(reversed(_frame().columns))], symbol="600519.SH", adjust="qfq",
        source_api="stock_zh_a_hist", akshare_version="test", fetched_at=now,
    )
    assert first.bars[0].volume == Decimal("100")
    assert first.bars[0].amount == Decimal("1000000")
    assert first.data_hash == second.data_hash


def test_incomplete_current_day_is_excluded():
    shanghai_morning_as_utc = datetime(2025, 1, 3, 2, 0, tzinfo=timezone.utc)
    data = normalize_dataframe(
        _frame(), symbol="600519.SH", adjust="qfq", source_api="stock_zh_a_hist",
        akshare_version="test", fetched_at=shanghai_morning_as_utc,
    )
    assert [bar.date for bar in data.bars] == [date(2025, 1, 2)]


def test_manual_fund_override_selects_fund_akshare_endpoint(monkeypatch):
    calls = []

    def fund_fetcher(**kwargs):
        calls.append(("fund", kwargs))
        return _frame()

    def stock_fetcher(**kwargs):
        raise AssertionError("stock endpoint must not be used for a fund override")

    fake_akshare = SimpleNamespace(
        __version__="test",
        fund_etf_hist_em=fund_fetcher,
        stock_zh_a_hist=stock_fetcher,
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)
    data = AkshareKlineProvider().fetch(
        "600519.SH",
        date(2025, 1, 2),
        date(2025, 1, 3),
        instrument_type_override="fund",
        now=datetime(2025, 1, 4, 16, tzinfo=timezone.utc),
    )
    assert data.source_api == "fund_etf_hist_em"
    assert calls[0][0] == "fund"


@pytest.mark.parametrize(
    ("data_source", "source_api"),
    [
        (KlineDataSource.EASTMONEY, "stock_zh_a_hist"),
        (KlineDataSource.SINA, "stock_zh_a_daily"),
        (KlineDataSource.TENCENT, "stock_zh_a_hist_tx"),
    ],
)
def test_explicit_stock_source_selects_exactly_one_endpoint(monkeypatch, data_source, source_api):
    calls: list[tuple[str, dict]] = []

    def fetch(name):
        def inner(**kwargs):
            calls.append((name, kwargs))
            return _english_frame() if name != "stock_zh_a_hist" else _frame()
        return inner

    fake_akshare = SimpleNamespace(
        __version__="test",
        stock_zh_a_hist=fetch("stock_zh_a_hist"),
        stock_zh_a_daily=fetch("stock_zh_a_daily"),
        stock_zh_a_hist_tx=fetch("stock_zh_a_hist_tx"),
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)

    data = AkshareKlineProvider().fetch(
        "600519.SH",
        date(2025, 1, 2),
        date(2025, 1, 3),
        data_source=data_source,
        now=datetime(2025, 1, 4, 16, tzinfo=timezone.utc),
    )

    assert [name for name, _ in calls] == [source_api]
    assert data.source_api == source_api
    assert data.bars[0].amount == Decimal("1000000")
    if data_source is not KlineDataSource.EASTMONEY:
        assert calls[0][1]["symbol"] == "sh600519"
        assert "period" not in calls[0][1]
        assert data.bars[0].turnover_rate == Decimal("0.012")


def test_selected_source_connection_failure_never_silently_falls_back(monkeypatch):
    calls: list[str] = []

    def eastmoney(**kwargs):
        calls.append("eastmoney")
        raise requests_exceptions.ConnectionError("remote closed")

    def unexpected(name):
        def inner(**kwargs):
            calls.append(name)
            return _english_frame()
        return inner

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        __version__="test",
        stock_zh_a_hist=eastmoney,
        stock_zh_a_daily=unexpected("sina"),
        stock_zh_a_hist_tx=unexpected("tencent"),
    ))

    with pytest.raises(KlineDataSourceConnectionError):
        AkshareKlineProvider(max_attempts=1).fetch(
            "600519.SH", date(2025, 1, 2), date(2025, 1, 3), data_source="eastmoney",
        )
    assert calls == ["eastmoney"]


def test_source_capabilities_reject_unsupported_instrument_combinations():
    assert source_api_for(InstrumentType.FUND, "eastmoney", adjust="qfq") == "fund_etf_hist_em"
    assert source_api_for(InstrumentType.FUND, "sina", adjust="raw") == "fund_etf_hist_sina"
    with pytest.raises(ValueError, match="只支持不复权"):
        source_api_for(InstrumentType.FUND, "sina", adjust="qfq")
    with pytest.raises(ValueError, match="暂不支持 tencent"):
        source_api_for(InstrumentType.FUND, "tencent", adjust="raw")
    with pytest.raises(ValueError, match="北交所"):
        source_api_for(InstrumentType.STOCK, "tencent", adjust="qfq", market="BJ")


def test_akshare_connection_failure_retries_then_succeeds_and_logs(monkeypatch, caplog):
    calls = []
    sleeps = []

    def stock_fetcher(**kwargs):
        calls.append(kwargs)
        if len(calls) < 3:
            raise requests_exceptions.ConnectionError("remote closed connection")
        return _frame()

    fake_akshare = SimpleNamespace(
        __version__="test",
        fund_etf_hist_em=lambda **kwargs: _frame(),
        stock_zh_a_hist=stock_fetcher,
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)
    provider = AkshareKlineProvider(
        max_attempts=3,
        retry_base_seconds=0.25,
        sleeper=sleeps.append,
    )

    with caplog.at_level(logging.INFO):
        data = provider.fetch(
            "600519.SH",
            date(2025, 1, 2),
            date(2025, 1, 3),
            now=datetime(2025, 1, 4, 16, tzinfo=timezone.utc),
        )

    assert len(calls) == 3
    assert sleeps == [0.25, 0.5]
    assert data.source_api == "stock_zh_a_hist"
    assert "connection retry" in caplog.text
    assert "fetch success" in caplog.text


def test_akshare_connection_failure_exhausts_retries_and_raises_explicit_error(
    monkeypatch, caplog,
):
    calls = []
    sleeps = []

    def stock_fetcher(**kwargs):
        calls.append(kwargs)
        raise requests_exceptions.ConnectionError("empty reply from server")

    fake_akshare = SimpleNamespace(
        __version__="test",
        fund_etf_hist_em=lambda **kwargs: _frame(),
        stock_zh_a_hist=stock_fetcher,
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)
    provider = AkshareKlineProvider(
        max_attempts=3,
        retry_base_seconds=0.1,
        sleeper=sleeps.append,
    )

    with caplog.at_level(logging.INFO), pytest.raises(
        KlineDataSourceConnectionError,
        match="connection failed after 3 attempts.*600519.SH",
    ):
        provider.fetch(
            "600519.SH",
            date(2025, 1, 2),
            date(2025, 1, 3),
            now=datetime(2025, 1, 4, 16, tzinfo=timezone.utc),
        )

    assert len(calls) == 3
    assert sleeps == [0.1, 0.2]
    assert "connection exhausted" in caplog.text


def test_akshare_non_connection_error_is_not_retried(monkeypatch):
    calls = []

    def stock_fetcher(**kwargs):
        calls.append(kwargs)
        raise ValueError("bad response schema")

    fake_akshare = SimpleNamespace(
        __version__="test",
        fund_etf_hist_em=lambda **kwargs: _frame(),
        stock_zh_a_hist=stock_fetcher,
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)

    with pytest.raises(ValueError, match="bad response schema"):
        AkshareKlineProvider(max_attempts=3, retry_base_seconds=0).fetch(
            "600519.SH",
            date(2025, 1, 2),
            date(2025, 1, 3),
            now=datetime(2025, 1, 4, 16, tzinfo=timezone.utc),
        )

    assert len(calls) == 1


def test_missing_security_day_is_aligned_as_non_tradable_suspension():
    now = datetime(2025, 1, 4, 16, tzinfo=timezone.utc)
    data = normalize_dataframe(
        _frame(), symbol="600519.SH", adjust="qfq", source_api="stock_zh_a_hist",
        akshare_version="test", fetched_at=now,
    )
    calendar = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4)]
    aligned = align_to_trading_calendar(data, calendar)
    assert len(aligned.bars) == 3
    assert aligned.bars[-1].tradable is False
    assert aligned.bars[-1].close == data.bars[-1].close
    assert aligned.data_hash != data.data_hash


def test_suspension_placeholder_does_not_advance_indicator_window():
    bars = [
        Bar(date(2025, 1, 2), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("100")),
        Bar(date(2025, 1, 6), Decimal("12"), Decimal("12"), Decimal("12"), Decimal("12"), Decimal("100")),
    ]
    config = BacktestConfig(
        start_date=date(2025, 1, 2), end_date=date(2025, 1, 6), short_ma=2, long_ma=3,
    )
    timeline, snapshots = _prepare_timeline(
        bars, config, [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 6)],
    )
    assert timeline[1].tradable is False
    assert snapshots[1].ma_short is None
    assert snapshots[2].ma_short == Decimal("11")
    assert snapshots[1].cross_up is False


def test_cache_roundtrip_and_ttl():
    engine = create_engine("sqlite:///:memory:")
    KlineCacheDB.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    now = datetime(2025, 1, 4, 16)
    with Session() as session:
        store = KlineCacheStore(session)
        data = normalize_dataframe(
            _frame(), symbol="600519.SH", adjust="qfq", source_api="stock_zh_a_hist",
            akshare_version="test", fetched_at=now,
        )
        first_record = store.put(data, ttl=timedelta(days=7))
        second_record = store.put(data, ttl=timedelta(days=7))
        assert first_record.id == second_record.id
        assert session.query(KlineCacheDB).count() == 1
        cached = store.get(
            symbol="600519.SH", adjust="qfq", start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 3), now=now + timedelta(days=1),
        )
        assert cached is not None
        assert cached.data_hash == data.data_hash
        assert store.get(
            symbol="600519.SH", adjust="qfq", start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 3), now=now + timedelta(days=8),
        ) is None


def test_models_keep_user_id_only_on_parent_run():
    assert "user_id" in KBRunDB.__table__.columns
    for child in (KBStrategyResultDB, KBTradeDB, KBEquityDB, KBBenchmarkEquityDB, KBSignalAuditDB):
        assert "user_id" not in child.__table__.columns
    assert {table.name for table in Base.metadata.sorted_tables} >= {
        "kline_cache", "kb_runs", "kb_strategy_results", "kb_trades",
        "kb_equity", "kb_benchmark_equity", "kb_signals_audit",
    }

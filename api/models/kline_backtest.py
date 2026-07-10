"""Persistent models for deterministic K-line backtests.

The module is intentionally not imported by ``api.database`` yet.  Stage 6 will
register it with application startup.  Unit tests import it explicitly before
calling ``Base.metadata.create_all``.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint

from api.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class KlineCacheDB(Base):
    __tablename__ = "kline_cache"

    id = Column(String(36), primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    adjust = Column(String(16), nullable=False)
    start_date = Column(String(10), nullable=False)
    end_date = Column(String(10), nullable=False)
    fetched_at = Column(DateTime, nullable=False, default=_utcnow)
    expires_at = Column(DateTime, nullable=False)
    akshare_version = Column(String(32), nullable=False)
    source_api = Column(String(80), nullable=False)
    data_hash = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "symbol", "adjust", "start_date", "end_date", "data_hash",
            name="uq_kline_cache_version",
        ),
    )


class KBRunDB(Base):
    __tablename__ = "kb_runs"

    run_id = Column(String(36), primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    instrument_type = Column(String(16), nullable=False)
    start_date = Column(String(10), nullable=False)
    end_date = Column(String(10), nullable=False)
    status = Column(String(16), nullable=False, index=True)
    params_snapshot = Column(JSON, nullable=False)
    fee_snapshot = Column(JSON, nullable=False)
    data_hash = Column(String(64), nullable=True)
    actual_data_range = Column(JSON, nullable=True)
    cache_version = Column(String(64), nullable=True)
    error_code = Column(String(64), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_kb_runs_user_created", "user_id", "created_at"),)


class KBStrategyResultDB(Base):
    __tablename__ = "kb_strategy_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("kb_runs.run_id"), nullable=False, index=True)
    strategy_key = Column(String(8), nullable=False)
    metrics = Column(JSON, nullable=False)
    signal_stats = Column(JSON, nullable=False)
    open_position = Column(JSON, nullable=True)

    __table_args__ = (UniqueConstraint("run_id", "strategy_key", name="uq_kb_strategy_run_key"),)


class KBTradeDB(Base):
    """All order lifecycles, including canceled and expired orders."""

    __tablename__ = "kb_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("kb_runs.run_id"), nullable=False, index=True)
    strategy_key = Column(String(8), nullable=False, index=True)
    signal_date = Column(String(10), nullable=False)
    planned_date = Column(String(10), nullable=True)
    actual_date = Column(String(10), nullable=True)
    order_type = Column(String(16), nullable=False)
    side = Column(String(8), nullable=False)
    theory_trigger_price = Column(Numeric(24, 8), nullable=True)
    exec_price = Column(Numeric(24, 8), nullable=True)
    qty = Column(Integer, nullable=False, default=0)
    commission = Column(Numeric(24, 8), nullable=False, default=0)
    stamp_tax = Column(Numeric(24, 8), nullable=False, default=0)
    transfer_fee = Column(Numeric(24, 8), nullable=False, default=0)
    slippage_cost = Column(Numeric(24, 8), nullable=False, default=0)
    realized_pnl = Column(Numeric(24, 8), nullable=True)
    trigger_reason = Column(JSON, nullable=False)
    order_outcome = Column(String(32), nullable=False)
    deferred_days = Column(Integer, nullable=False, default=0)
    wave_snapshot = Column(JSON, nullable=True)
    cash_after = Column(Numeric(24, 8), nullable=True)
    position_value_after = Column(Numeric(24, 8), nullable=True)


class KBEquityDB(Base):
    __tablename__ = "kb_equity"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("kb_runs.run_id"), nullable=False, index=True)
    strategy_key = Column(String(8), nullable=False)
    date = Column(String(10), nullable=False)
    cash = Column(Numeric(24, 8), nullable=False)
    position_value = Column(Numeric(24, 8), nullable=False)
    total = Column(Numeric(24, 8), nullable=False)
    drawdown = Column(Numeric(18, 10), nullable=False)

    __table_args__ = (UniqueConstraint("run_id", "strategy_key", "date", name="uq_kb_equity_day"),)


class KBBenchmarkEquityDB(Base):
    __tablename__ = "kb_benchmark_equity"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("kb_runs.run_id"), nullable=False, index=True)
    date = Column(String(10), nullable=False)
    total = Column(Numeric(24, 8), nullable=False)
    drawdown = Column(Numeric(18, 10), nullable=False)

    __table_args__ = (UniqueConstraint("run_id", "date", name="uq_kb_benchmark_day"),)


class KBSignalAuditDB(Base):
    __tablename__ = "kb_signals_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("kb_runs.run_id"), nullable=False, index=True)
    strategy_key = Column(String(8), nullable=False)
    date = Column(String(10), nullable=False)
    ma_values = Column(JSON, nullable=False)
    visible_pivots = Column(JSON, nullable=False)
    fib_levels = Column(JSON, nullable=True)
    swing_amplitude = Column(Numeric(18, 10), nullable=True)
    trendline_price = Column(Numeric(24, 8), nullable=True)
    touch_count = Column(Integer, nullable=False, default=0)
    decision = Column(JSON, nullable=False)

    __table_args__ = (UniqueConstraint("run_id", "strategy_key", "date", name="uq_kb_signal_day"),)

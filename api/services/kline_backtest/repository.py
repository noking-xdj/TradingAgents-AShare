"""Short-transaction persistence and ownership queries for K-line backtests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from api.models.kline_backtest import (
    KBBenchmarkEquityDB,
    KBEquityDB,
    KBRunDB,
    KBSignalAuditDB,
    KBStrategyResultDB,
    KBTradeDB,
)

from .schemas import BacktestRunResult, primitive


ACTIVE_STATUSES = frozenset({"pending", "running"})
TERMINAL_STATUSES = frozenset({"completed", "failed"})
CHILD_MODELS = (
    KBSignalAuditDB,
    KBEquityDB,
    KBBenchmarkEquityDB,
    KBTradeDB,
    KBStrategyResultDB,
)


class ActiveRunDeleteError(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_pending_run(
    db: Session,
    *,
    run_id: str,
    user_id: str,
    symbol: str,
    instrument_type: str,
    start_date: str,
    end_date: str,
    params_snapshot: dict[str, Any],
    fee_snapshot: dict[str, Any],
) -> KBRunDB:
    run = KBRunDB(
        run_id=run_id,
        user_id=user_id,
        symbol=symbol,
        instrument_type=instrument_type,
        start_date=start_date,
        end_date=end_date,
        status="pending",
        params_snapshot=params_snapshot,
        fee_snapshot=fee_snapshot,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_run_for_execution(db: Session, run_id: str) -> KBRunDB | None:
    return db.query(KBRunDB).filter(KBRunDB.run_id == run_id).first()


def mark_running(db: Session, run_id: str) -> bool:
    changed = (
        db.query(KBRunDB)
        .filter(KBRunDB.run_id == run_id, KBRunDB.status == "pending")
        .update(
            {
                KBRunDB.status: "running",
                KBRunDB.started_at: _utcnow(),
                KBRunDB.error_code: None,
                KBRunDB.error: None,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return changed == 1


def mark_failed(db: Session, run_id: str, *, error_code: str, error: str) -> bool:
    changed = (
        db.query(KBRunDB)
        .filter(KBRunDB.run_id == run_id, KBRunDB.status.in_(ACTIVE_STATUSES))
        .update(
            {
                KBRunDB.status: "failed",
                KBRunDB.error_code: error_code,
                KBRunDB.error: error,
                KBRunDB.finished_at: _utcnow(),
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return changed == 1


def recover_orphaned_runs(db: Session) -> int:
    count = (
        db.query(KBRunDB)
        .filter(KBRunDB.status.in_(ACTIVE_STATUSES))
        .update(
            {
                KBRunDB.status: "failed",
                KBRunDB.error_code: "orphaned",
                KBRunDB.error: "app restarted before the in-memory backtest task completed",
                KBRunDB.finished_at: _utcnow(),
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return int(count)


def _delete_children(db: Session, run_id: str) -> None:
    for model in CHILD_MODELS:
        db.query(model).filter(model.run_id == run_id).delete(synchronize_session=False)


def persist_completed_run(
    db: Session,
    *,
    run_id: str,
    result: BacktestRunResult,
    actual_data_range: dict[str, Any],
    cache_version: str,
) -> None:
    """Persist every result and the completed transition in one transaction."""
    try:
        run = db.query(KBRunDB).filter(KBRunDB.run_id == run_id).first()
        if run is None or run.status != "running":
            raise RuntimeError("run is not in running state")
        expected = set(run.params_snapshot.get("strategy_keys") or [])
        if set(result.strategy_results) != expected:
            raise RuntimeError("strategy result set does not match the run snapshot")

        _delete_children(db, run_id)
        for strategy_key, strategy in result.strategy_results.items():
            db.add(KBStrategyResultDB(
                run_id=run_id,
                strategy_key=strategy_key,
                metrics=primitive(strategy.metrics),
                signal_stats=primitive(strategy.signal_stats),
                open_position=primitive(strategy.open_position),
            ))
            for order in strategy.orders:
                db.add(KBTradeDB(
                    run_id=run_id,
                    strategy_key=strategy_key,
                    signal_date=order.signal_date.isoformat(),
                    planned_date=order.planned_date.isoformat() if order.planned_date else None,
                    actual_date=order.actual_date.isoformat() if order.actual_date else None,
                    order_type=order.order_type,
                    side=order.side,
                    theory_trigger_price=order.theory_trigger_price,
                    exec_price=order.exec_price,
                    qty=order.qty,
                    commission=order.commission,
                    stamp_tax=order.stamp_tax,
                    transfer_fee=order.transfer_fee,
                    slippage_cost=order.slippage_cost,
                    realized_pnl=order.realized_pnl,
                    trigger_reason=primitive(order.reasons),
                    order_outcome=order.outcome,
                    deferred_days=order.deferred_days,
                    wave_snapshot=primitive(order.wave_snapshot),
                    cash_after=order.cash_after,
                    position_value_after=order.position_value_after,
                ))
            for point in strategy.equity:
                db.add(KBEquityDB(
                    run_id=run_id,
                    strategy_key=strategy_key,
                    date=point.date.isoformat(),
                    cash=point.cash,
                    position_value=point.position_value,
                    total=point.total,
                    drawdown=point.drawdown,
                ))
            for audit in strategy.audits:
                snapshot = audit.snapshot
                db.add(KBSignalAuditDB(
                    run_id=run_id,
                    strategy_key=strategy_key,
                    date=audit.date.isoformat(),
                    ma_values=primitive({
                        "short": snapshot.ma_short,
                        "long": snapshot.ma_long,
                        "cross_up": snapshot.cross_up,
                        "cross_down": snapshot.cross_down,
                    }),
                    visible_pivots=primitive(snapshot.visible_pivots),
                    fib_levels=primitive(snapshot.swing.levels) if snapshot.swing else None,
                    swing_amplitude=snapshot.swing.amplitude if snapshot.swing else None,
                    trendline_price=snapshot.trendline_price,
                    touch_count=snapshot.trendline.touch_count if snapshot.trendline else 0,
                    decision=primitive({
                        "decision": audit.decision,
                        "ignored_reason": audit.ignored_reason,
                        "fib_touched": snapshot.fib_touched,
                        "fib_rebound": snapshot.fib_rebound,
                        "touched_levels": snapshot.touched_levels,
                        "trendline_broken": snapshot.trendline_broken,
                    }),
                ))

        db.add(KBStrategyResultDB(
            run_id=run_id,
            strategy_key="BENCHMARK",
            metrics=primitive(result.benchmark.metrics),
            signal_stats={},
            open_position={"actual_entry_date": primitive(result.benchmark.actual_entry_date)},
        ))
        for point in result.benchmark.equity:
            db.add(KBBenchmarkEquityDB(
                run_id=run_id,
                date=point.date.isoformat(),
                total=point.total,
                drawdown=point.drawdown,
            ))

        db.flush()
        run.data_hash = result.data_hash
        run.actual_data_range = actual_data_range
        run.cache_version = cache_version
        run.status = "completed"
        run.finished_at = _utcnow()
        run.error_code = None
        run.error = None
        db.commit()
    except Exception:
        db.rollback()
        raise


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def run_record(run: KBRunDB) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "symbol": run.symbol,
        "instrument_type": run.instrument_type,
        "start_date": run.start_date,
        "end_date": run.end_date,
        "status": run.status,
        "params_snapshot": run.params_snapshot,
        "fee_snapshot": run.fee_snapshot,
        "data_hash": run.data_hash,
        "actual_data_range": run.actual_data_range,
        "cache_version": run.cache_version,
        "error_code": run.error_code,
        "error": run.error,
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
    }


def get_owned_run(db: Session, user_id: str, run_id: str) -> KBRunDB | None:
    return db.query(KBRunDB).filter(KBRunDB.run_id == run_id, KBRunDB.user_id == user_id).first()


def list_owned_runs(
    db: Session,
    user_id: str,
    *,
    symbol: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[KBRunDB], int]:
    query = db.query(KBRunDB).filter(KBRunDB.user_id == user_id)
    if symbol:
        query = query.filter(KBRunDB.symbol == symbol)
    total = query.count()
    rows = query.order_by(KBRunDB.created_at.desc()).offset(offset).limit(limit).all()
    return rows, total


def get_run_detail(db: Session, user_id: str, run_id: str) -> dict[str, Any] | None:
    run = get_owned_run(db, user_id, run_id)
    if run is None:
        return None
    detail = run_record(run)
    rows = (
        db.query(KBStrategyResultDB)
        .join(KBRunDB, KBRunDB.run_id == KBStrategyResultDB.run_id)
        .filter(KBRunDB.run_id == run_id, KBRunDB.user_id == user_id)
        .all()
    )
    detail["strategies"] = {
        row.strategy_key: {
            "metrics": row.metrics,
            "signal_stats": row.signal_stats,
            "open_position": row.open_position,
        }
        for row in rows if row.strategy_key != "BENCHMARK"
    }
    benchmark = next((row for row in rows if row.strategy_key == "BENCHMARK"), None)
    detail["benchmark"] = None if benchmark is None else {
        "metrics": benchmark.metrics,
        "actual_entry_date": (benchmark.open_position or {}).get("actual_entry_date"),
    }
    return detail


def _owned_child_query(db: Session, model, user_id: str, run_id: str):
    return (
        db.query(model)
        .join(KBRunDB, KBRunDB.run_id == model.run_id)
        .filter(KBRunDB.run_id == run_id, KBRunDB.user_id == user_id)
    )


def _decimal(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def list_trades(
    db: Session, user_id: str, run_id: str, *, strategy: str | None, offset: int, limit: int,
) -> tuple[list[dict[str, Any]], int] | None:
    if get_owned_run(db, user_id, run_id) is None:
        return None
    query = _owned_child_query(db, KBTradeDB, user_id, run_id)
    if strategy:
        query = query.filter(KBTradeDB.strategy_key == strategy)
    total = query.count()
    rows = query.order_by(KBTradeDB.id).offset(offset).limit(limit).all()
    return [{
        "id": row.id,
        "strategy_key": row.strategy_key,
        "signal_date": row.signal_date,
        "planned_date": row.planned_date,
        "actual_date": row.actual_date,
        "order_type": row.order_type,
        "side": row.side,
        "theory_trigger_price": _decimal(row.theory_trigger_price),
        "exec_price": _decimal(row.exec_price),
        "qty": row.qty,
        "commission": _decimal(row.commission),
        "stamp_tax": _decimal(row.stamp_tax),
        "transfer_fee": _decimal(row.transfer_fee),
        "slippage_cost": _decimal(row.slippage_cost),
        "realized_pnl": _decimal(row.realized_pnl),
        "trigger_reason": row.trigger_reason,
        "order_outcome": row.order_outcome,
        "deferred_days": row.deferred_days,
        "wave_snapshot": row.wave_snapshot,
        "cash_after": _decimal(row.cash_after),
        "position_value_after": _decimal(row.position_value_after),
    } for row in rows], total


def list_equity(
    db: Session, user_id: str, run_id: str, *, strategy: str | None, offset: int, limit: int,
) -> tuple[list[dict[str, Any]], int] | None:
    if get_owned_run(db, user_id, run_id) is None:
        return None
    if strategy == "BENCHMARK":
        query = _owned_child_query(db, KBBenchmarkEquityDB, user_id, run_id)
        total = query.count()
        rows = query.order_by(KBBenchmarkEquityDB.date).offset(offset).limit(limit).all()
        return [{
            "strategy_key": "BENCHMARK",
            "date": row.date,
            "total": _decimal(row.total),
            "drawdown": _decimal(row.drawdown),
        } for row in rows], total
    query = _owned_child_query(db, KBEquityDB, user_id, run_id)
    if strategy:
        query = query.filter(KBEquityDB.strategy_key == strategy)
    total = query.count()
    rows = query.order_by(KBEquityDB.date, KBEquityDB.strategy_key).offset(offset).limit(limit).all()
    return [{
        "strategy_key": row.strategy_key,
        "date": row.date,
        "cash": _decimal(row.cash),
        "position_value": _decimal(row.position_value),
        "total": _decimal(row.total),
        "drawdown": _decimal(row.drawdown),
    } for row in rows], total


def list_signals(
    db: Session, user_id: str, run_id: str, *, strategy: str | None, offset: int, limit: int,
) -> tuple[list[dict[str, Any]], int] | None:
    if get_owned_run(db, user_id, run_id) is None:
        return None
    query = _owned_child_query(db, KBSignalAuditDB, user_id, run_id)
    if strategy:
        query = query.filter(KBSignalAuditDB.strategy_key == strategy)
    total = query.count()
    rows = query.order_by(KBSignalAuditDB.date, KBSignalAuditDB.strategy_key).offset(offset).limit(limit).all()
    return [{
        "id": row.id,
        "strategy_key": row.strategy_key,
        "date": row.date,
        "ma_values": row.ma_values,
        "visible_pivots": row.visible_pivots,
        "fib_levels": row.fib_levels,
        "swing_amplitude": _decimal(row.swing_amplitude),
        "trendline_price": _decimal(row.trendline_price),
        "touch_count": row.touch_count,
        "decision": row.decision,
    } for row in rows], total


def delete_owned_run(db: Session, user_id: str, run_id: str) -> bool:
    try:
        run = get_owned_run(db, user_id, run_id)
        if run is None:
            return False
        if run.status not in TERMINAL_STATUSES:
            raise ActiveRunDeleteError(run.status)
        _delete_children(db, run_id)
        db.delete(run)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise

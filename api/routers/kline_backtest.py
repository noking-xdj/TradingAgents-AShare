"""Authenticated API for deterministic K-line backtests."""

from __future__ import annotations

from dataclasses import asdict
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.database import UserDB, get_db
from api.dependencies import require_api_user
from api.services.kline_backtest import repository, task_manager
from api.services.kline_backtest.data_provider import source_api_for
from api.services.kline_backtest.fees import FeeProfile, default_fee_profile
from api.services.kline_backtest.instrument import normalize_symbol, require_backtestable
from api.services.kline_backtest.schemas import KlineBacktestCreateRequest, primitive


router = APIRouter(prefix="/v1/kline-backtests", tags=["kline-backtests"])


def _fee_snapshot(request: KlineBacktestCreateRequest, instrument_type) -> dict[str, str]:
    defaults = default_fee_profile(instrument_type)
    overrides = request.fee
    values = {}
    for key, default in asdict(defaults).items():
        override = getattr(overrides, key) if overrides is not None else None
        values[key] = override if override is not None else default
    return primitive(asdict(FeeProfile(**values)))


def _strategy(value: str | None, *, benchmark: bool = False) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    allowed = {"A", "B", "C", "D"}
    if benchmark:
        allowed.add("BENCHMARK")
    if normalized not in allowed:
        raise HTTPException(status_code=422, detail="unsupported strategy")
    return normalized


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_kline_backtest(
    body: KlineBacktestCreateRequest,
    current_user: UserDB = Depends(require_api_user),
    db: Session = Depends(get_db),
):
    try:
        info = require_backtestable(body.symbol, body.instrument_type_override)
        source_api_for(
            info.instrument_type,
            body.data_source,
            adjust=body.adjust,
            market=info.market,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    body.symbol = info.symbol
    params_snapshot = body.model_dump(mode="json")
    fee_snapshot = _fee_snapshot(body, info.instrument_type)
    run_id = uuid4().hex
    repository.create_pending_run(
        db,
        run_id=run_id,
        user_id=current_user.id,
        symbol=info.symbol,
        instrument_type=info.instrument_type.value,
        start_date=body.start_date.isoformat(),
        end_date=body.end_date.isoformat(),
        params_snapshot=params_snapshot,
        fee_snapshot=fee_snapshot,
    )
    try:
        task_manager.submit_run(run_id)
    except Exception as exc:
        repository.mark_failed(
            db,
            run_id,
            error_code="queue_submit_failed",
            error=f"{type(exc).__name__}: {exc}"[:4000],
        )
        raise HTTPException(status_code=503, detail="回测任务提交失败") from exc
    return {"run_id": run_id, "status": "pending"}


@router.get("")
def list_kline_backtests(
    symbol: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: UserDB = Depends(require_api_user),
    db: Session = Depends(get_db),
):
    if symbol:
        try:
            symbol = normalize_symbol(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows, total = repository.list_owned_runs(
        db, current_user.id, symbol=symbol, offset=offset, limit=limit,
    )
    return {
        "items": [repository.run_record(row) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/{run_id}")
def get_kline_backtest(
    run_id: str,
    current_user: UserDB = Depends(require_api_user),
    db: Session = Depends(get_db),
):
    detail = repository.get_run_detail(db, current_user.id, run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="未找到该回测任务")
    return detail


@router.delete("/{run_id}")
def delete_kline_backtest(
    run_id: str,
    current_user: UserDB = Depends(require_api_user),
    db: Session = Depends(get_db),
):
    try:
        deleted = repository.delete_owned_run(db, current_user.id, run_id)
    except repository.ActiveRunDeleteError as exc:
        raise HTTPException(status_code=409, detail=f"活动回测任务不可删除：{exc}") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="未找到该回测任务")
    return {"deleted": True, "run_id": run_id}


def _page(items_and_total, run_id: str, offset: int, limit: int):
    if items_and_total is None:
        raise HTTPException(status_code=404, detail="未找到该回测任务")
    items, total = items_and_total
    return {"run_id": run_id, "items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/{run_id}/trades")
def get_kline_backtest_trades(
    run_id: str,
    strategy: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    current_user: UserDB = Depends(require_api_user),
    db: Session = Depends(get_db),
):
    return _page(
        repository.list_trades(
            db, current_user.id, run_id,
            strategy=_strategy(strategy), offset=offset, limit=limit,
        ),
        run_id, offset, limit,
    )


@router.get("/{run_id}/equity")
def get_kline_backtest_equity(
    run_id: str,
    strategy: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    current_user: UserDB = Depends(require_api_user),
    db: Session = Depends(get_db),
):
    return _page(
        repository.list_equity(
            db, current_user.id, run_id,
            strategy=_strategy(strategy, benchmark=True), offset=offset, limit=limit,
        ),
        run_id, offset, limit,
    )


@router.get("/{run_id}/signals")
def get_kline_backtest_signals(
    run_id: str,
    strategy: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    current_user: UserDB = Depends(require_api_user),
    db: Session = Depends(get_db),
):
    return _page(
        repository.list_signals(
            db, current_user.id, run_id,
            strategy=_strategy(strategy), offset=offset, limit=limit,
        ),
        run_id, offset, limit,
    )

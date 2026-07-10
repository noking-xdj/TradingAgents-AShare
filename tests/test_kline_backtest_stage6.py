from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.database import SessionLocal, UserDB
from api.main import app
from api.models.kline_backtest import (
    KBBenchmarkEquityDB,
    KBEquityDB,
    KBRunDB,
    KBSignalAuditDB,
    KBStrategyResultDB,
    KBTradeDB,
    KlineCacheDB,
)
from api.services import auth_service, token_service
from api.services.kline_backtest import repository, task_manager
from api.services.kline_backtest.data_provider import (
    KlineDataSourceConnectionError,
    NormalizedKlineData,
    canonical_data_hash,
)
from api.services.kline_backtest.fees import STOCK_FEE_PROFILE
from api.services.kline_backtest.schemas import KlineBacktestCreateRequest, primitive
from tests.kline_backtest_helpers import make_bars


CHILD_MODELS = (
    KBSignalAuditDB, KBEquityDB, KBBenchmarkEquityDB, KBTradeDB, KBStrategyResultDB,
)


@pytest.fixture(autouse=True)
def clean_backtest_tables():
    with SessionLocal() as db:
        for model in CHILD_MODELS:
            db.query(model).delete(synchronize_session=False)
        db.query(KBRunDB).delete(synchronize_session=False)
        db.query(KlineCacheDB).delete(synchronize_session=False)
        db.commit()
    yield
    with SessionLocal() as db:
        for model in CHILD_MODELS:
            db.query(model).delete(synchronize_session=False)
        db.query(KBRunDB).delete(synchronize_session=False)
        db.query(KlineCacheDB).delete(synchronize_session=False)
        db.commit()


def _user_and_jwt() -> tuple[UserDB, str]:
    user = UserDB(
        id=uuid4().hex,
        email=f"kb-{uuid4().hex[:10]}@test.com",
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    with SessionLocal() as db:
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
    return user, auth_service.create_access_token(user)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _request(**overrides) -> KlineBacktestCreateRequest:
    values = {
        "symbol": "600519.SH",
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "strategy_keys": ["A"],
        "short_ma": 2,
        "long_ma": 3,
        "pivot_left": 1,
        "pivot_right": 1,
        "pivot_min_separation": 2,
    }
    values.update(overrides)
    return KlineBacktestCreateRequest.model_validate(values)


def _create_pending(user_id: str, request: KlineBacktestCreateRequest, *, status: str = "pending") -> str:
    run_id = uuid4().hex
    with SessionLocal() as db:
        repository.create_pending_run(
            db,
            run_id=run_id,
            user_id=user_id,
            symbol=request.symbol,
            instrument_type="stock",
            start_date=request.start_date.isoformat(),
            end_date=request.end_date.isoformat(),
            params_snapshot=request.model_dump(mode="json"),
            fee_snapshot=primitive(asdict(STOCK_FEE_PROFILE)),
        )
        if status != "pending":
            db.query(KBRunDB).filter(KBRunDB.run_id == run_id).update({"status": status})
            db.commit()
    return run_id


def test_new_api_accepts_jwt_and_api_token_but_web_only_dependency_rejects_api_token():
    user, jwt_token = _user_and_jwt()
    with SessionLocal() as db:
        api_token = token_service.create_token(db, user.id, "kline-test")["token"]

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/v1/kline-backtests", headers=_headers(jwt_token)).status_code == 200
    assert client.get("/v1/kline-backtests", headers=_headers(api_token)).status_code == 200
    web_only = client.get("/v1/auth/me", headers=_headers(api_token))
    assert web_only.status_code == 401
    assert web_only.json()["detail"] == "该接口仅限网页端登录访问"


def test_create_is_pending_202_activity_delete_is_409_and_index_is_rejected():
    user, token = _user_and_jwt()
    client = TestClient(app, raise_server_exceptions=False)
    with patch("api.routers.kline_backtest.task_manager.submit_run", return_value=MagicMock()):
        response = client.post(
            "/v1/kline-backtests", headers=_headers(token), json=_request().model_dump(mode="json"),
        )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    with SessionLocal() as db:
        run = db.query(KBRunDB).filter(KBRunDB.run_id == body["run_id"]).one()
        assert run.user_id == user.id
        assert run.status == "pending"
        assert "user_id" not in KBTradeDB.__table__.columns

    assert client.delete(f"/v1/kline-backtests/{body['run_id']}", headers=_headers(token)).status_code == 409
    with patch("api.routers.kline_backtest.task_manager.submit_run", return_value=MagicMock()):
        rejected = client.post(
            "/v1/kline-backtests",
            headers=_headers(token),
            json=_request(symbol="000001.SH").model_dump(mode="json"),
        )
    assert rejected.status_code == 400
    assert "暂不支持指数" in rejected.json()["detail"]


def test_state_machine_persists_all_results_enforces_join_ownership_and_explicit_delete():
    owner, owner_token = _user_and_jwt()
    _, other_token = _user_and_jwt()
    closes = [10, 9, 8, 7, 8, 9, 10, 11] * 20
    bars = make_bars(closes, start=date(2024, 1, 1))
    request = _request(
        start_date=bars[120].date.isoformat(),
        end_date=bars[-1].date.isoformat(),
        stop_loss=None,
        take_profit=None,
    )
    run_id = _create_pending(owner.id, request)
    data = NormalizedKlineData(
        symbol=request.symbol,
        adjust=request.adjust,
        source_api="fixture",
        akshare_version="test",
        fetched_at=datetime.now(timezone.utc),
        bars=bars,
        data_hash=canonical_data_hash(bars, request.adjust),
    )
    manager = task_manager.KlineBacktestTaskManager(max_workers=1)
    observed_statuses = []

    def load_after_running(_request):
        with SessionLocal() as db:
            observed_statuses.append(db.query(KBRunDB).filter_by(run_id=run_id).one().status)
        return data

    with (
        patch.object(manager, "_load_data", side_effect=load_after_running),
        patch("api.services.kline_backtest.task_manager._trading_dates", return_value=[bar.date for bar in bars]),
    ):
        manager.execute(run_id)

    assert observed_statuses == ["running"]
    with SessionLocal() as db:
        run = db.query(KBRunDB).filter(KBRunDB.run_id == run_id).one()
        assert run.status == "completed"
        assert run.started_at is not None and run.finished_at is not None
        assert run.data_hash
        assert db.query(KBStrategyResultDB).filter_by(run_id=run_id).count() == 2
        assert db.query(KBTradeDB).filter_by(run_id=run_id).count() > 0
        assert db.query(KBEquityDB).filter_by(run_id=run_id).count() > 0
        assert db.query(KBBenchmarkEquityDB).filter_by(run_id=run_id).count() > 0
        assert db.query(KBSignalAuditDB).filter_by(run_id=run_id).count() > 0

    client = TestClient(app, raise_server_exceptions=False)
    for suffix in ("", "/trades", "/equity", "/signals"):
        assert client.get(f"/v1/kline-backtests/{run_id}{suffix}", headers=_headers(other_token)).status_code == 404
        assert client.get(f"/v1/kline-backtests/{run_id}{suffix}", headers=_headers(owner_token)).status_code == 200

    deleted = client.delete(f"/v1/kline-backtests/{run_id}", headers=_headers(owner_token))
    assert deleted.status_code == 200
    with SessionLocal() as db:
        assert db.query(KBRunDB).filter_by(run_id=run_id).count() == 0
        for model in CHILD_MODELS:
            assert db.query(model).filter_by(run_id=run_id).count() == 0


def test_persistence_failure_rolls_back_children_and_marks_run_failed():
    user, _ = _user_and_jwt()
    bars = make_bars([10, 9, 8, 9] * 35, start=date(2024, 1, 1))
    request = _request(
        start_date=bars[120].date.isoformat(), end_date=bars[-1].date.isoformat(),
    )
    run_id = _create_pending(user.id, request)
    data = NormalizedKlineData(
        request.symbol, request.adjust, "fixture", "test", datetime.now(timezone.utc),
        bars, canonical_data_hash(bars, request.adjust),
    )
    manager = task_manager.KlineBacktestTaskManager(max_workers=1)
    persist = repository.persist_completed_run

    def fail_during_flush(db, **kwargs):
        with patch.object(db, "flush", side_effect=RuntimeError("write failed")):
            return persist(db, **kwargs)

    with (
        patch.object(manager, "_load_data", return_value=data),
        patch("api.services.kline_backtest.task_manager._trading_dates", return_value=[bar.date for bar in bars]),
        patch("api.services.kline_backtest.repository.persist_completed_run", side_effect=fail_during_flush),
    ):
        manager.execute(run_id)
    with SessionLocal() as db:
        run = db.query(KBRunDB).filter_by(run_id=run_id).one()
        assert run.status == "failed"
        assert run.error_code == "persistence_failed"
        for model in CHILD_MODELS:
            assert db.query(model).filter_by(run_id=run_id).count() == 0


def test_exhausted_data_source_connection_is_terminal_with_specific_error_code():
    user, _ = _user_and_jwt()
    request = _request()
    run_id = _create_pending(user.id, request)
    manager = task_manager.KlineBacktestTaskManager(max_workers=1)

    with patch.object(
        manager,
        "_load_data",
        side_effect=KlineDataSourceConnectionError(
            "AkShare stock_zh_a_hist connection failed after 3 attempts for 600519.SH",
        ),
    ):
        manager.execute(run_id)

    with SessionLocal() as db:
        run = db.query(KBRunDB).filter_by(run_id=run_id).one()
        assert run.status == "failed"
        assert run.error_code == "data_source_connection_failed"
        assert "failed after 3 attempts" in run.error


def test_orphan_recovery_marks_pending_and_running_failed_but_not_completed():
    user, _ = _user_and_jwt()
    request = _request()
    pending_id = _create_pending(user.id, request)
    running_id = _create_pending(user.id, request, status="running")
    completed_id = _create_pending(user.id, request, status="completed")

    assert task_manager.recover_orphaned_runs() == 2
    with SessionLocal() as db:
        states = {
            row.run_id: (row.status, row.error_code)
            for row in db.query(KBRunDB).filter(KBRunDB.run_id.in_([pending_id, running_id, completed_id]))
        }
    assert states[pending_id] == ("failed", "orphaned")
    assert states[running_id] == ("failed", "orphaned")
    assert states[completed_id] == ("completed", None)


def test_app_lifespan_registers_recovery_while_scheduler_startup_does_not():
    from api import main as api_main
    from scheduler import main as scheduler_main

    fake_store = MagicMock()
    fake_executor = MagicMock()
    with (
        patch.object(api_main, "init_db"),
        patch.object(api_main, "get_job_store", return_value=fake_store),
        patch.object(api_main, "_report_version_stats"),
        patch.object(api_main, "_load_cn_stock_map", return_value={}),
        patch.object(api_main, "_executor", fake_executor),
        patch("tradingagents.dataflows.trade_calendar._load_cn_trade_dates", return_value=([], set())),
        patch.object(task_manager, "recover_orphaned_runs", return_value=2) as recover,
        patch.object(task_manager, "shutdown") as shutdown,
    ):
        async def app_startup():
            async with api_main.lifespan(api_main.app):
                pass
        asyncio.run(app_startup())
    recover.assert_called_once_with()
    shutdown.assert_called_once_with()

    with (
        patch.object(scheduler_main, "init_db"),
        patch.object(scheduler_main, "_recover_stale_tasks"),
        patch.object(scheduler_main, "_scheduler_loop", new_callable=AsyncMock),
        patch("tradingagents.dataflows.trade_calendar._load_cn_trade_dates", return_value=([], set())),
        patch("api.main._load_cn_stock_map", return_value={}),
        patch.object(task_manager, "recover_orphaned_runs") as scheduler_recover,
    ):
        asyncio.run(scheduler_main._startup())
    scheduler_recover.assert_not_called()
    if scheduler_main._executor is not None:
        scheduler_main._executor.shutdown(wait=True)
        scheduler_main._executor = None


def test_dedicated_executor_defaults_to_one_and_is_not_analysis_executor():
    from api import main as api_main

    manager = task_manager.KlineBacktestTaskManager(max_workers=1)
    executor = manager._get_executor()
    try:
        assert executor._max_workers == 1
        assert executor is not api_main._executor
        assert executor._thread_name_prefix == "kline-backtest"
    finally:
        manager.shutdown()

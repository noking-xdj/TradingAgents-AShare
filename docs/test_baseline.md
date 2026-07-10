# 全仓测试基线

## 1. 基线信息

- 建立日期：2026-07-10
- 产品代码基准提交：`ce932af`
- 分支：`codex/local-fixes`
- 运行环境：Docker `tradingagents-ashare:local`
- Python：3.10.19
- pytest：9.0.2
- Redis：未在隔离测试容器中启动

本基线只修改测试和测试夹具，不修改 `api/`、`scheduler/`、`frontend/` 或 K 线回测模块。`tests/conftest.py` 在 pytest 导入应用数据库模块之前，将 `DATABASE_URL` 指向每次测试进程新建的临时 SQLite 文件；session 开始时执行 `init_db()`，结束后关闭 engine 并删除临时目录。测试不再读取或污染工作区及部署数据库。

## 2. 可重复运行命令

在仓库根目录、已安装项目依赖与 pytest 的环境中运行：

```bash
python -m pytest -q --tb=short -ra -p no:cacheprovider
```

K 线回测专项回归：

```bash
python -m pytest -q -p no:cacheprovider \
  tests/test_kline_backtest_stage2.py \
  tests/test_kline_backtest_indicators.py \
  tests/test_kline_backtest_engine.py \
  tests/test_kline_backtest_strategies.py \
  tests/test_kline_backtest_golden.py
```

鉴权安全网定点检查：

```bash
python -m pytest -vv -p no:cacheprovider \
  tests/test_api_smoke.py::TestAnalyzeEndpoint::test_requires_auth \
  tests/test_api_smoke.py::TestChatCompletionsEndpoint::test_requires_auth
```

## 3. 基线结果

### 3.1 全仓测试

```text
218 collected
202 passed
5 failed
11 skipped
0 errors
63 warnings
completed in 16.27s
```

pytest 正常运行到 100% 并退出，不再卡在 `tests/test_scheduled_queue.py`。

### 3.2 K 线回测专项

```text
32 passed in 1.13s
```

Golden-file 和“全年无有效线/无合格波段”零交易夹具均包含在这 32 项内。

### 3.3 鉴权断言

```text
TestAnalyzeEndpoint::test_requires_auth PASSED
TestChatCompletionsEndpoint::test_requires_auth PASSED
2 passed in 1.12s
```

两项测试均完成认证用户前置创建，并真正执行了无凭证请求的 `401/403` 断言。

### 3.4 条件跳过

11 项均来自 `tests/test_job_store_redis.py`，原因是隔离容器没有运行 `redis://localhost:6379/15`。这些测试不是失败；在带 Redis 的阶段 8 集成环境中应另行执行。

## 4. 已知失败：等待人工口径决策

以下 5 项是测试期望与当前实现行为不一致。按本任务约束，两侧均未修改。

### 4.1 默认 horizon

1. `tests/test_intent_parser.py::test_parse_intent_returns_defaults`
   - 期望：`["short", "medium"]`
   - 实际：`["short"]`

2. `tests/test_intent_parser.py::test_parse_intent_fallback_on_invalid_json`
   - 期望：无效 JSON 回退为 `["short", "medium"]`
   - 实际：回退为 `["short"]`

### 4.2 短线基本面提示文案

3. `tests/test_intent_parser.py::test_build_horizon_context_short_fundamentals_has_downweight_hint`
   - 期望：短线上下文包含“次要”字样，明确下调基本面权重
   - 实际：只包含“短线（1-2周，技术面主导）”，没有“次要”字样

### 4.3 孤儿报告恢复返回契约

4. `tests/test_report_recovery.py::test_recover_stale_active_reports_marks_empty_running_report_failed`
   - 期望：`{"total": 1, "completed": 0, "failed": 1}`
   - 实际：`{"total": 1, "failed": 1}`

5. `tests/test_report_recovery.py::test_recover_stale_active_reports_marks_partial_running_report_failed`
   - 期望：`{"total": 1, "completed": 0, "failed": 1}`
   - 实际：`{"total": 1, "failed": 1}`

## 5. 已修复的基线问题

- API smoke 每次运行使用全新临时 SQLite，并在 session 开始时执行 `init_db()`；原 16 个 setup error 已消除。
- API 手动触发测试对齐当前 `api.main._run_manual_trigger`；自动调度测试的 import/patch 对齐 `scheduler.main`。
- `test_scheduled_queue.py` 对齐 `scheduler.main._concurrency_slot` 和 semaphore 状态，并为事件等待与 gather 增加保护超时；两个测试不再永久挂死。
- 持仓导入测试的内存 SQLite 使用 `StaticPool` 与 `check_same_thread=False`，匹配调度器的 `asyncio.to_thread` 执行方式。
- 股票名称缓存测试同时保存、设置并恢复 `_cn_stock_map` 与 `_cn_stock_reverse_map`，不再依赖测试顺序或预热状态。

## 6. 后续回归判定规则

在第 4 节口径未决前，以下结果视为与本基线一致：

- pytest 正常运行结束；
- `0 errors`；
- failed 仅限第 4 节列出的 5 项；
- 不新增 skipped；
- K 线回测专项 32 项全部通过；
- 两个 `test_requires_auth` 全部通过。

任何新增失败、错误、挂死，或既有通过项转为 skipped，均视为回归。第 4 节任一口径一旦由人工确认，应同步修改实现或测试，并更新本基线。

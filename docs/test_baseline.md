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
207 passed
0 failed
11 skipped
0 errors
63 warnings
completed in 15.97s
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

## 4. 已确认口径与 Git 考古依据

原基线中的 5 项失败均确认是有意产品变更后测试没有同步，不是实现回归。现已只更新测试，产品实现未修改。

### 4.1 单次综合分析固定使用 short horizon

- 主依据：`b40824b9bb29c193a5cb5bbd618d2fe85e3915b6`
- 提交信息：`fix: 提升决策准确率 — verdict 改革 + 方向翻转治理 + 数据完整性 (#91)`
- 提交说明明确写明：去掉双 horizon，graph 只运行一次，`intent_parser` 固定返回 `["short"]`，各分析师在内部使用自己的自然时间窗口。
- 二次确认：`c1386e3dec854b0e18f2dfc47034bf0c80dff955` 将中英文 prompt 示例同步为固定 `["short"]`。

因此以下两项测试均对齐为 `["short"]`：

- 正常 JSON 解析结果；
- 无效 JSON 的 fallback。

### 4.2 horizon context 不再按 agent_type 全局降权

- 依据：`b40824b9bb29c193a5cb5bbd618d2fe85e3915b6`
- 该提交明确删除 `_WEIGHT_HINTS`，不再由全局 horizon 压制某类分析师；fundamentals/macro 使用各自的 medium 自然窗口，最终权重交由 Research Manager 动态判断。
- 旧测试对中文“次要”做字面断言，已经与新架构冲突。
- 新测试改为语义断言：相同 horizon、关注点和问题下，`agent_type="fundamentals"` 与不指定 `agent_type` 生成相同 context。测试不再绑定具体中文文案。

### 4.3 孤儿报告恢复返回契约

- 依据：`04e5b3774a401d6a54bb8151541c67e210a4ee76`
- 提交说明明确写明：`Remove misleading completed: 0 from recover_stale_active_reports return`。
- 全仓唯一生产调用方位于 `scheduler/main.py`，只读取 `report_reset["total"]`；未发现任何 `completed` 键消费者。
- 两项测试已对齐实际契约：`{"total": 1, "failed": 1}`，无需修改实现。

## 5. 已修复的基线问题

- API smoke 每次运行使用全新临时 SQLite，并在 session 开始时执行 `init_db()`；原 16 个 setup error 已消除。
- API 手动触发测试对齐当前 `api.main._run_manual_trigger`；自动调度测试的 import/patch 对齐 `scheduler.main`。
- `test_scheduled_queue.py` 对齐 `scheduler.main._concurrency_slot` 和 semaphore 状态，并为事件等待与 gather 增加保护超时；两个测试不再永久挂死。
- 持仓导入测试的内存 SQLite 使用 `StaticPool` 与 `check_same_thread=False`，匹配调度器的 `asyncio.to_thread` 执行方式。
- 股票名称缓存测试同时保存、设置并恢复 `_cn_stock_map` 与 `_cn_stock_reverse_map`，不再依赖测试顺序或预热状态。
- 意图解析、horizon context 和孤儿报告恢复的 5 项过期断言已依据第 4 节 Git 历史完成对齐。

## 6. 后续回归判定规则

以下结果视为与最终基线一致：

- pytest 正常运行结束；
- `0 failed`；
- `0 errors`；
- skipped 仅限未运行 Redis 时的 11 项 `tests/test_job_store_redis.py`；
- K 线回测专项 32 项全部通过；
- 两个 `test_requires_auth` 全部通过。

任何失败、错误、挂死、新增 skipped，或既有通过项转为 skipped，均视为回归。带 Redis 的阶段 8 集成环境还应要求 11 项 Redis 测试执行并通过。

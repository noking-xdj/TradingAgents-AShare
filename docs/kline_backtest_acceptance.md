# K 线回测阶段 8 验收核对表

> 核对日期：2026-07-11
> 分支：`codex/kline-data-source-selector`
> 阶段 7 收尾提交：`8f445fb`
> 当前结论：**部分通过，尚不能宣布首期交付完成**。东方财富真实接口持续断连，ETF 完整回测与强制刷新路径缺少成功证据。

## 1. 真实 AkShare 集成测试

### 1.1 环境与入口

- 通过已部署服务 `POST /v1/kline-backtests` 发起，不使用测试桩。
- 默认区间：2025-01-01 至 2025-12-31；默认参数；策略 A/B/C/D 全选。
- 默认数据源：东方财富；AkShare `1.18.30`。
- 未为通过验收切换供应商、降低校验标准或修改数据入口。

### 1.2 强制刷新结果

| 品种 | 标的 | run_id | 结果 | 证据 |
|---|---|---|---|---|
| 主板股票 | `601398.SH` | `10b50a2273c349fd82b4dee3522f86ee` | 失败 | `stock_zh_a_hist` 连续 3 次 `RemoteDisconnected`，错误码 `data_source_connection_failed` |
| 主板股票重试 | `601398.SH` | `e689b5bd04534e5385462de1c5a2e868` | 失败 | 独立重跑仍连续 3 次断连 |
| 主板股票容错轮 | `601398.SH` | `f2de4f06f1354126ba5a2c6148ce1f15` | 失败 | 第三轮仍连续 3 次断连 |
| 场内 ETF | `510300.SH` | `02e88d10ef8f45f9902ab233591aff0b` | 失败 | `fund_etf_hist_em` 连续 3 次 `RemoteDisconnected` |
| 授权后最终复测（股票） | `601398.SH` | `bf3f99645caa4033a7d57f951ee5c2b9` | 失败 | 直接通过 `docker compose exec` 执行阶段 8 脚本，仍连续 3 次断连 |
| 授权后最终复测（ETF） | `510300.SH` | `4d511badc04f483ba5254a4da66ebc2e` | 失败 | 同轮复测，`fund_etf_hist_em` 仍连续 3 次断连 |

重试日志包含 attempt、1/2 秒指数退避、异常类型与最终 exhausted。该结果按需求认定为外部环境阻塞，不修改实现兜底。

### 1.3 可复用的真实股票证据

历史真实 run `2595f251636d4a49b369cd511431e449`（`601398.SH`，东方财富）通过部署 API 复核：

- 243 个信号、权益和订单日期全部属于 AkShare 交易日历，周末/非交易日均为 0。
- 数据范围 2024-05-06 至 2025-12-31，统计区间 2025 全年，预热 164 根。
- 统计首个交易日 2025-01-02 的 MA20 已有值。
- 数据哈希：`a875a0b30aefc1277351df6748378177273e0c9fa1a215fdf4bdd22e36279933`。
- 接口：`stock_zh_a_hist`；AkShare：`1.18.30`。
- 54 笔实际成交订单合计：佣金 663.51 元、印花税 1,457.39 元、过户费 57.68 元、滑点 5,767.83 元。
- 策略 A：净收益 20.60944%，最大回撤 -5.53505%，完整交易 7 笔，总成本 2,114.56 元。

缓存回放 run `bec5d6debb7c4345827a9e4cf22b58d5`：

- 状态 `running -> completed`，未触发 AkShare 拉取。
- 与原 run 数据哈希完全相同。
- 四策略结果、基准结果和费率快照完全相同。

该证据证明股票真实交易日历、股票税费、预热、MA20 和缓存路径；但不能替代本轮要求的成功强制刷新，也不能替代 ETF 实盘税费证据。

### 1.4 边界验证

| 场景 | 状态 | 证据 |
|---|---|---|
| 指数 `000001.SH` | 通过 | HTTP 400，`首期暂不支持指数回测` |
| 北交所 `830799` | 通过 | API 接受标准化查询；识别为 `830799.BJ`、stock、bse、涨跌停阈值 0.30 |
| `short_ma == long_ma == 20` | 通过 | HTTP 422，`short_ma must be less than long_ma` |

## 2. §15 十九条验收标准

| # | 状态 | 核对结论与证据 |
|---:|---|---|
| 1 | 通过 | 当前分析页可发起上一完整自然年回测；`createDefaultBacktestInput`、`test_create_is_pending_202_activity_delete_is_409_and_index_is_rejected`。 |
| 2 | 通过 | 股票万 1.15、基金万 1、免 5且可调；`test_stock_fee_profile_is_decimal_and免五`、`test_fund_has_no_stamp_or_transfer_fee_and_affordable_lots_reserve_fees`、前端参数区。 |
| 3 | **部分通过** | 单测与真实股票费用均正确；股票实际印花税/过户费非零。东方财富持续不可用导致本轮 ETF 实际订单的印花税/过户费双零证据缺失。 |
| 4 | 通过 | `test_pivot_is_not_visible_until_confirmed_at`、golden-file 和逐日快照审计。 |
| 5 | 通过 | `test_fibonacci_uses_recent_confirmed_swing_amplitude_and_range_intersection`、`test_trendline_requires_post_confirmation_third_touch`、策略绑定波段测试。 |
| 6 | 通过 | `test_full_year_without_valid_line_or_swing_returns_zero_trades_normally`。 |
| 7 | 通过 | `test_close_signal_executes_at_next_open_and_period_end_order_is_canceled`；真实股票日期均在交易日历内。 |
| 8 | 通过 | 资金/整数手费用测试、停牌对齐、挂单 5 日超期、T+1 与涨跌停引擎测试。 |
| 9 | 通过 | `test_strategy_pending_order_reverses_but_risk_exit_does_not`。 |
| 10 | 通过 | `test_state_machine_persists_all_results_enforces_join_ownership_and_explicit_delete`；真实股票 run 含 A/B/C/D 独立结果。 |
| 11 | 通过 | 前端展示核心指标、净值/回撤、横向成本构成、信号审计、订单明细和基准；阶段 7 Edge 真机核验。 |
| 12 | 通过 | 活动分析归零后使用最新镜像重建 app/scheduler；重启前 completed 回测 `2595f251636d4a49b369cd511431e449` 经部署 API 完整读取，哈希、交易日、订单、费用及结果不变；同期智能分析 `38dc1c63a933436a93f4d304ab93a62e` 重启后仍为 completed。 |
| 13 | **部分通过** | 股票缓存回放与原 run 哈希、完整结果相同；ETF 强制刷新和缓存配对因东方财富断连未完成。 |
| 14 | 通过 | `test_orphan_recovery_marks_pending_and_running_failed_but_not_completed`、`test_app_lifespan_registers_recovery_while_scheduler_startup_does_not`。 |
| 15 | 通过 | 父 run 所有权 join、JWT/API Token 和跨用户访问/删除测试通过。 |
| 16 | 通过 | 本轮真实 API 边界结果：指数 400；北交所标准化为 `830799.BJ`、30% 阈值；股票/ETF 分类单测通过。 |
| 17 | 通过 | K 线回测路径无 LLM client 引用；相对阶段基线 `backtest_service.py` 无差异；旧分析仍独立运行。 |
| 18 | 通过 | 使用 lightweight-charts 与 Recharts；依赖清单未新增 klinecharts、ECharts、Celery。Redis 为项目既有依赖，阶段分支未修改依赖清单。 |
| 19 | 通过 | 持久化失败回滚、完成态时序、活动 run 409 和显式子记录删除测试通过。 |

当前汇总：**17 通过 / 2 部分通过 / 0 不通过**。第 3、13 条需东方财富恢复后完成 ETF 与强制刷新配对。

## 3. 回归与构建

- 全仓 pytest：224 passed，11 skipped（仅 Redis 环境条件跳过），0 failed，0 errors，72 warnings。
- K 线专项：49 passed，9 warnings。
- Vitest：4 files / 23 tests passed。
- 回测组件 ESLint：0 error，0 warning。
- 前端生产构建：通过；仅既有大 chunk 提示。
- `docker compose build`：通过。
- `app` 健康检查与 `scheduler` 启动验证：重建后均正常，运行同一最新镜像 `sha256:3af5228cab8fc7987c888b2fc761da162ab7f7ac0667c0d7d9e1e4061d4b3983`。
- 重启前真实回测与智能分析历史均可读，持久化结果未改变。

## 4. 静态约束审计

- `api/services/kline_backtest`、路由与模型中无 OpenAI、Anthropic、LLM 或 chat model 引用。
- 阶段基线 `ce932af` 至当前分支未修改 `pyproject.toml`、`uv.lock`、`frontend/package.json`、`frontend/package-lock.json`。
- 未引入 klinecharts、ECharts、Celery；Redis 是存量任务系统既有依赖，不是 K 线模块新增。
- `api/services/backtest_service.py` 相对阶段基线无差异。
- `docs/test_baseline.md` 与 `tests/fixtures/kline_backtest_expected.json` 均已纳入 Git。

## 5. 待完成项

1. 东方财富恢复后重新执行 `601398.SH` 与 `510300.SH` 的强制刷新；各自再执行一次缓存命中并比较哈希与完整结果。
2. 从 ETF 真实逐笔订单核对印花税与过户费均为 0。
3. 上述全部通过后，将 v1.1 状态更新为“首期交付完成”并填写最终提交号。

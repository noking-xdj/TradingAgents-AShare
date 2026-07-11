import { useMemo, useState } from 'react'
import { AlertTriangle, Loader2 } from 'lucide-react'

import type {
    KlineBacktestDetail,
    KlineBacktestEquityPoint,
    KlineBacktestSignal,
    KlineBacktestStrategy,
    KlineBacktestTrade,
    KlineCandle,
} from '@/types'
import BacktestPerformanceCharts from './BacktestPerformanceCharts'
import BacktestPriceChart from './BacktestPriceChart'
import {
    BACKTEST_METRIC_CARDS,
    backtestEndingPnl,
    formatBacktestMetric,
    formatSignedBacktestMoney,
} from '@/utils/backtestMetrics'
import { BACKTEST_DATA_SOURCE_LABELS } from '@/utils/klineBacktest'

interface Props {
    detail: KlineBacktestDetail
    selectedStrategy: KlineBacktestStrategy
    equityByStrategy: Partial<Record<KlineBacktestStrategy | 'BENCHMARK', KlineBacktestEquityPoint[]>>
    trades: KlineBacktestTrade[]
    signals: KlineBacktestSignal[]
    candles: KlineCandle[]
    loading: boolean
    onStrategyChange: (strategy: KlineBacktestStrategy) => void
}

function numeric(value: string | number | null | undefined): number | null {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
}

const CONDITION_LABELS: Record<string, string> = {
    ma_cross_up: '均线金叉', ma_cross_down: '均线死叉', ma_bullish: '均线多头', ma_bearish: '均线空头',
    qualified_swing: '合格上升波段', bound_swing_invalid: '绑定波段失效', fib_touched: '触及斐波位',
    fib_rebound: '斐波反弹确认', valid_trendline: '有效趋势线', trendline_supported: '趋势线支撑',
    trendline_broken: '趋势线跌破',
}

export default function BacktestResults({ detail, selectedStrategy, equityByStrategy, trades, signals, candles, loading, onStrategyChange }: Props) {
    const [tradePage, setTradePage] = useState(0)
    const pageSize = 20
    const strategies = Object.keys(detail.strategies) as KlineBacktestStrategy[]
    const selected = detail.strategies[selectedStrategy]
    const metrics = selected?.metrics ?? {}
    const falseConditions = Object.entries(selected?.signal_stats.condition_false_days ?? {}).sort((a, b) => b[1] - a[1])
    const maxFalse = Math.max(1, ...falseConditions.map(item => item[1]))
    const pagedTrades = useMemo(() => trades.slice(tradePage * pageSize, (tradePage + 1) * pageSize), [tradePage, trades])
    const pageCount = Math.max(1, Math.ceil(trades.length / pageSize))
    const zeroTradeNeedsExplanation = ['C', 'D'].includes(selectedStrategy) && numeric(metrics.completed_trades) === 0
    const params = detail.params_snapshot
    const insufficientCashOrders = trades.filter(order => order.order_outcome === 'insufficient_cash').length
    const noCompletedTradesForCash = insufficientCashOrders > 0 && numeric(metrics.completed_trades) === 0
    const actualRange = detail.actual_data_range
    const warmupBars = numeric(actualRange?.warmup_bars as string | number | null | undefined) ?? 0
    const loadedStart = String(actualRange?.actual_start ?? detail.start_date)
    const loadedEnd = String(actualRange?.actual_end ?? detail.end_date)
    const statisticsStart = String(actualRange?.statistics_start ?? detail.start_date)
    const statisticsEnd = String(actualRange?.statistics_end ?? detail.end_date)
    const benchmarkMetrics = detail.benchmark?.metrics
    const benchmarkUnrealizedPnl = backtestEndingPnl(benchmarkMetrics)
    const selectedEndingPnl = backtestEndingPnl(metrics)
    const holdingAdvantage = benchmarkUnrealizedPnl != null && selectedEndingPnl != null
        ? benchmarkUnrealizedPnl - selectedEndingPnl
        : null

    return (
        <div className="space-y-4">
            <section className="card flex flex-wrap items-center justify-between gap-3">
                <div>
                    <h2 className="font-semibold">回测结果 · {detail.symbol}</h2>
                    <p className="mt-1 text-xs text-slate-500">
                        {actualRange
                            ? `${warmupBars > 0 ? `加载范围（含 ${warmupBars} 根预热 K 线）` : '数据范围'} ${loadedStart} 至 ${loadedEnd} · 统计区间 ${statisticsStart} 至 ${statisticsEnd}`
                            : `${detail.start_date} 至 ${detail.end_date}`}
                        {` · ${BACKTEST_DATA_SOURCE_LABELS[detail.params_snapshot.data_source ?? 'eastmoney']}`}
                        {actualRange?.source_api ? `（${String(actualRange.source_api)}）` : ''}
                        {detail.benchmark?.actual_entry_date ? ` · 基准实际建仓 ${detail.benchmark.actual_entry_date}` : ''}
                    </p>
                </div>
                <div className="flex flex-wrap gap-2">
                    {strategies.map(key => (
                        <button key={key} type="button" className={key === selectedStrategy ? 'btn-primary text-sm' : 'btn-secondary text-sm'} onClick={() => { setTradePage(0); onStrategyChange(key) }}>
                            策略 {key}
                        </button>
                    ))}
                </div>
            </section>

            {loading && (
                <div className="card flex items-center justify-center gap-2 py-12 text-sm text-slate-500"><Loader2 className="animate-spin" size={18} /> 正在加载完整结果...</div>
            )}

            {!loading && selected && (
                <>
                    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 2xl:grid-cols-9">
                        {BACKTEST_METRIC_CARDS.map(item => (
                            <div key={item.key} className="card min-w-0" title={item.description}>
                                <p className="text-xs text-slate-500">{item.label}</p>
                                <p className="mt-2 truncate text-lg font-semibold">{formatBacktestMetric(metrics[item.key], item.format)}</p>
                            </div>
                        ))}
                    </div>

                    {detail.benchmark && (
                        <section className="card grid gap-4 md:grid-cols-3">
                            <div>
                                <p className="text-xs text-slate-500">简单持有浮盈</p>
                                <p className={`mt-1 text-xl font-semibold ${(benchmarkUnrealizedPnl ?? 0) >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                                    {formatSignedBacktestMoney(benchmarkUnrealizedPnl)}
                                </p>
                                <p className="mt-1 text-xs text-slate-500">
                                    {formatBacktestMetric(benchmarkMetrics?.unrealized_return ?? benchmarkMetrics?.total_return, 'percent')} · 期末未卖出，不含退出费用
                                </p>
                            </div>
                            <div>
                                <p className="text-xs text-slate-500">策略 {selectedStrategy} 期末盈亏</p>
                                <p className={`mt-1 text-xl font-semibold ${(selectedEndingPnl ?? 0) >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                                    {formatSignedBacktestMoney(selectedEndingPnl)}
                                </p>
                                <p className="mt-1 text-xs text-slate-500">含已实现盈亏与期末持仓浮盈亏</p>
                            </div>
                            <div>
                                <p className="text-xs text-slate-500">简单持有相对策略 {selectedStrategy}</p>
                                <p className={`mt-1 text-xl font-semibold ${(holdingAdvantage ?? 0) >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                                    {formatSignedBacktestMoney(holdingAdvantage)}
                                </p>
                                <p className="mt-1 text-xs text-slate-500">正数表示简单持有期末收益更高</p>
                            </div>
                        </section>
                    )}

                    {noCompletedTradesForCash && (
                        <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
                            <div className="flex items-start gap-2">
                                <AlertTriangle className="mt-0.5 shrink-0" size={17} />
                                <div>
                                    <p className="font-semibold">初始资金不足，当前策略未能买入一手</p>
                                    <p className="mt-1">共有 {insufficientCashOrders} 笔买单因资金不足取消。当前初始资金为 {formatBacktestMetric(params.initial_cash, 'money')}；A 股及场内基金按 100 股/份一手成交，请提高初始资金后重新回测。</p>
                                </div>
                            </div>
                        </div>
                    )}

                    <BacktestPerformanceCharts detail={detail} selectedStrategy={selectedStrategy} equityByStrategy={equityByStrategy} />
                    <BacktestPriceChart
                        candles={candles}
                        signals={signals}
                        trades={trades}
                        shortMa={params.short_ma}
                        longMa={params.long_ma}
                        trendMinTouches={params.trend_min_touches}
                    />

                    <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
                        <section className="card min-w-0">
                            <h3 className="font-semibold">多策略对比</h3>
                            <div className="mt-3 overflow-x-auto">
                                <table className="w-full min-w-[840px] text-left text-sm">
                                    <thead className="text-xs text-slate-500"><tr><th className="py-2">策略</th><th>净收益</th><th>期末盈亏</th><th>最大回撤</th><th>夏普</th><th>完整交易</th><th>胜率</th><th title="盈利交易净盈利总额 ÷ 亏损交易净亏损绝对值">盈亏比</th><th>总成本</th></tr></thead>
                                    <tbody>
                                        {strategies.map(key => {
                                            const row = detail.strategies[key]?.metrics ?? {}
                                            return <tr key={key} className="border-t border-slate-100 dark:border-slate-700"><td className="py-2 font-semibold">{key}</td><td>{formatBacktestMetric(row.total_return, 'percent')}</td><td>{formatSignedBacktestMoney(backtestEndingPnl(row))}</td><td>{formatBacktestMetric(row.max_drawdown, 'percent')}</td><td>{formatBacktestMetric(row.sharpe, 'ratio')}</td><td>{formatBacktestMetric(row.completed_trades, 'number')}</td><td>{formatBacktestMetric(row.win_rate, 'percent')}</td><td>{formatBacktestMetric(row.profit_loss_ratio, 'ratio')}</td><td>{formatBacktestMetric(row.total_cost, 'money')}</td></tr>
                                        })}
                                        {detail.benchmark && <tr className="border-t border-slate-100 text-slate-500 dark:border-slate-700"><td className="py-2 font-semibold">简单持有（浮盈）</td><td>{formatBacktestMetric(detail.benchmark.metrics.total_return, 'percent')}</td><td>{formatSignedBacktestMoney(benchmarkUnrealizedPnl)}</td><td>{formatBacktestMetric(detail.benchmark.metrics.max_drawdown, 'percent')}</td><td>{formatBacktestMetric(detail.benchmark.metrics.sharpe, 'ratio')}</td><td>0</td><td>--</td><td>--</td><td>{formatBacktestMetric(detail.benchmark.metrics.total_cost, 'money')}</td></tr>}
                                    </tbody>
                                </table>
                            </div>
                        </section>

                        <section className="card min-w-0">
                            <div className="flex flex-wrap items-start justify-between gap-2">
                                <div><h3 className="font-semibold">信号审计</h3><p className="mt-1 text-xs text-slate-500">买入 {selected.signal_stats.buy_signals ?? 0} 次 · 卖出 {selected.signal_stats.sell_signals ?? 0} 次</p></div>
                                {zeroTradeNeedsExplanation && <span className="badge-orange flex items-center gap-1"><AlertTriangle size={13} /> 零交易原因</span>}
                            </div>
                            <div className="mt-4 space-y-3">
                                {falseConditions.length === 0 && <p className="text-sm text-slate-500">没有条件未满足记录</p>}
                                {falseConditions.map(([key, count]) => (
                                    <div key={key}>
                                        <div className="mb-1 flex justify-between gap-3 text-xs"><span>{CONDITION_LABELS[key] ?? key}</span><span className="text-slate-500">未满足 {count} 日</span></div>
                                        <div className="h-2 overflow-hidden rounded bg-slate-100 dark:bg-slate-700"><div className="h-full rounded bg-amber-500" style={{ width: `${Math.max(3, count / maxFalse * 100)}%` }} /></div>
                                    </div>
                                ))}
                            </div>
                        </section>
                    </div>

                    <section className="card min-w-0">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <div><h3 className="font-semibold">订单与交易明细</h3><p className="mt-1 text-xs text-slate-500">记录全部订单生命周期，含成交、顺延、取消、超期及期末取消</p></div>
                            <span className="text-xs text-slate-500">共 {trades.length} 笔订单</span>
                        </div>
                        <div className="mt-3 overflow-x-auto">
                            <table className="w-full min-w-[1180px] text-left text-xs">
                                <thead className="text-slate-500"><tr><th className="py-2">策略</th><th>信号日</th><th>计划日</th><th>实际日</th><th>类型</th><th>方向</th><th>状态</th><th>成交价</th><th>数量</th><th>顺延</th><th>触发/未成交原因</th><th>费用</th><th>已实现盈亏</th></tr></thead>
                                <tbody>{pagedTrades.map(order => {
                                    const fee = ['commission', 'stamp_tax', 'transfer_fee', 'slippage_cost'].reduce((sum, key) => sum + numberFromOrder(order, key), 0)
                                    return <tr key={order.id} className="border-t border-slate-100 dark:border-slate-700"><td className="py-2 font-semibold">{order.strategy_key}</td><td>{order.signal_date}</td><td>{order.planned_date ?? '--'}</td><td>{order.actual_date ?? '--'}</td><td>{order.order_type === 'risk_exit' ? '风险退出' : '策略信号'}</td><td className={order.side === 'BUY' ? 'text-red-500' : 'text-green-500'}>{order.side === 'BUY' ? '买入' : '卖出'}</td><td>{order.order_outcome}</td><td>{order.exec_price ?? '--'}</td><td>{order.qty}</td><td>{order.deferred_days} 日</td><td className="max-w-[240px] whitespace-normal">{order.trigger_reason.join('、') || '--'}</td><td>¥{fee.toFixed(2)}</td><td>{order.realized_pnl == null ? '--' : `¥${Number(order.realized_pnl).toFixed(2)}`}</td></tr>
                                })}</tbody>
                            </table>
                        </div>
                        {trades.length === 0 && <div className="py-8 text-center text-sm text-slate-500">该策略没有生成订单；请结合上方条件未满足分布审计</div>}
                        {trades.length > pageSize && <div className="mt-3 flex items-center justify-end gap-2 text-sm"><button className="btn-secondary" disabled={tradePage === 0} onClick={() => setTradePage(page => page - 1)}>上一页</button><span>{tradePage + 1} / {pageCount}</span><button className="btn-secondary" disabled={tradePage + 1 >= pageCount} onClick={() => setTradePage(page => page + 1)}>下一页</button></div>}
                    </section>
                </>
            )}
        </div>
    )
}

function numberFromOrder(order: KlineBacktestTrade, key: string): number {
    return numeric(order[key as keyof KlineBacktestTrade] as string | number | null | undefined) ?? 0
}

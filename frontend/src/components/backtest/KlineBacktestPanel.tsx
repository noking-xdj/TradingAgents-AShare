import { useEffect, useMemo, useRef, useState } from 'react'
import { Clock3, Loader2, Trash2 } from 'lucide-react'

import { useKlineBacktestStore } from '@/stores/klineBacktestStore'
import type { KlineBacktestCreateInput, KlineBacktestDataSource, KlineBacktestStatus } from '@/types'
import { BACKTEST_DATA_SOURCE_LABELS, classifyBacktestInstrument, createDefaultBacktestInput, defaultBacktestFees, normalizeBacktestSymbol, validateBacktestInput } from '@/utils/klineBacktest'
import BacktestParameterPanel from './BacktestParameterPanel'
import BacktestResults from './BacktestResults'

interface Props { symbol: string }

const STATUS: Record<KlineBacktestStatus, { label: string; className: string }> = {
    pending: { label: '排队中', className: 'badge-orange' },
    running: { label: '运行中', className: 'badge-blue' },
    completed: { label: '已完成', className: 'badge-green' },
    failed: { label: '失败', className: 'badge-red' },
}

export default function KlineBacktestPanel({ symbol }: Props) {
    const analysisSymbol = normalizeBacktestSymbol(symbol) ?? symbol.trim().toUpperCase()
    const [backtestSymbol, setBacktestSymbol] = useState(analysisSymbol)
    const [backtestName, setBacktestName] = useState<string | undefined>()
    const instrument = classifyBacktestInstrument(backtestSymbol)
    const [form, setForm] = useState<KlineBacktestCreateInput>(() => createDefaultBacktestInput(backtestSymbol))
    const mountedRef = useRef(true)
    const {
        history, selectedRunId, selectedStrategy, detail, trades, signals, equityByStrategy, candles,
        historyLoading, detailLoading, resultLoading, submitting, error,
        loadHistory, selectRun, refreshSelectedRun, loadCompletedData, selectStrategy, submit, deleteRun,
    } = useKlineBacktestStore()

    useEffect(() => {
        void loadHistory(backtestSymbol)
    }, [backtestSymbol, loadHistory])

    useEffect(() => () => { mountedRef.current = false }, [])

    useEffect(() => {
        if (!detail || (detail.status !== 'pending' && detail.status !== 'running')) return
        const runId = detail.run_id
        const timer = window.setInterval(() => {
            void refreshSelectedRun().then(next => {
                const currentRunId = useKlineBacktestStore.getState().selectedRunId
                if (!mountedRef.current || currentRunId !== runId || !next || next.run_id !== runId) return
                if (next.status === 'completed') {
                    window.clearInterval(timer)
                    void loadCompletedData(next)
                }
            })
        }, 1500)
        return () => {
            window.clearInterval(timer)
        }
    }, [detail, loadCompletedData, refreshSelectedRun])

    const errors = useMemo(() => validateBacktestInput(form), [form])
    const active = submitting || history.some(run => run.status === 'pending' || run.status === 'running')
        || detail?.status === 'pending' || detail?.status === 'running'

    const changeForm = (value: KlineBacktestCreateInput) => setForm(value)
    const reset = () => setForm(createDefaultBacktestInput(backtestSymbol))
    const start = () => { void submit({ ...form, symbol: backtestSymbol }).catch(() => undefined) }
    const retryWithSource = (dataSource: KlineBacktestDataSource) => {
        if (!detail) return
        const next = { ...detail.params_snapshot, symbol: detail.symbol, data_source: dataSource }
        setForm(next)
        void submit(next).catch(() => undefined)
    }
    const selectBacktestSymbol = (raw: string, name?: string) => {
        const nextSymbol = normalizeBacktestSymbol(raw)
        if (!nextSymbol || nextSymbol === backtestSymbol) return
        const nextInstrument = classifyBacktestInstrument(nextSymbol)
        setBacktestSymbol(nextSymbol)
        setBacktestName(name)
        setForm(current => ({
            ...current,
            symbol: nextSymbol,
            data_source: nextInstrument === 'fund' || (nextSymbol.endsWith('.BJ') && current.data_source === 'tencent')
                ? 'eastmoney'
                : current.data_source,
            fee: defaultBacktestFees(nextInstrument),
        }))
    }

    return (
        <div className="space-y-4 min-w-0">
            <BacktestParameterPanel
                value={form}
                instrument={instrument}
                errors={errors}
                disabled={active}
                analysisSymbol={analysisSymbol}
                selectedName={backtestName}
                onChange={changeForm}
                onSymbolSelect={selectBacktestSymbol}
                onReset={reset}
                onSubmit={start}
            />

            <section className="card min-w-0">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                        <h2 className="font-semibold">历史回测</h2>
                        <p className="mt-1 text-xs text-slate-500">刷新页面后从服务端历史恢复，可切换查看已完成 run</p>
                    </div>
                    {historyLoading && <Loader2 size={17} className="animate-spin text-slate-400" />}
                </div>
                <div className="mt-3 overflow-x-auto">
                    <div className="flex min-w-max gap-2 pb-1">
                        {history.map(run => (
                            <button
                                key={run.run_id}
                                type="button"
                                onClick={() => void selectRun(run.run_id)}
                                className={`min-w-[235px] rounded-lg border p-3 text-left transition ${selectedRunId === run.run_id ? 'border-blue-500 bg-blue-50 dark:bg-blue-950/30' : 'border-slate-200 hover:border-slate-400 dark:border-slate-700'}`}
                            >
                                <span className="flex items-center justify-between gap-2"><span className="text-sm font-semibold">{run.start_date} — {run.end_date}</span><span className={STATUS[run.status].className}>{STATUS[run.status].label}</span></span>
                                <span className="mt-2 flex items-center justify-between gap-2 text-xs text-slate-500">
                                    <span className="flex items-center gap-1"><Clock3 size={12} /> {new Date(run.created_at).toLocaleString('zh-CN')} · {BACKTEST_DATA_SOURCE_LABELS[run.params_snapshot.data_source ?? 'eastmoney']}</span>
                                    {(run.status === 'completed' || run.status === 'failed') && <span role="button" tabIndex={0} className="rounded p-1 hover:bg-red-100 hover:text-red-600 dark:hover:bg-red-950" onClick={event => { event.stopPropagation(); void deleteRun(run.run_id, backtestSymbol) }} onKeyDown={() => undefined}><Trash2 size={13} /></span>}
                                </span>
                            </button>
                        ))}
                        {!historyLoading && history.length === 0 && <p className="py-3 text-sm text-slate-500">当前标的还没有回测记录</p>}
                    </div>
                </div>
            </section>

            {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">{error}</div>}

            {detailLoading && <div className="card flex items-center justify-center gap-2 py-12 text-sm text-slate-500"><Loader2 className="animate-spin" size={18} /> 正在读取回测任务...</div>}

            {!detailLoading && detail && (detail.status === 'pending' || detail.status === 'running') && (
                <div className="card flex items-center gap-3 py-8">
                    <Loader2 className="animate-spin text-blue-500" size={24} />
                    <div><p className="font-semibold">{detail.status === 'pending' ? '任务已进入专用队列' : '正在计算交易信号与账户净值'}</p><p className="mt-1 text-sm text-slate-500">当前状态：{STATUS[detail.status].label}。页面会自动刷新，期间已禁用重复提交。</p></div>
                </div>
            )}

            {!detailLoading && detail?.status === 'failed' && (
                <div className="card border-red-200 dark:border-red-900">
                    <h3 className="font-semibold text-red-600">回测失败 · {detail.error_code ?? 'unknown'}</h3>
                    <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">所选数据源：{BACKTEST_DATA_SOURCE_LABELS[detail.params_snapshot.data_source ?? 'eastmoney']}</p>
                    <p className="mt-2 whitespace-pre-wrap text-sm text-slate-600 dark:text-slate-300">{detail.error ?? '未返回错误详情'}</p>
                    {detail.error_code === 'data_source_connection_failed' && instrument === 'stock' && (
                        <div className="mt-4 flex flex-wrap items-center gap-2">
                            <span className="text-xs text-slate-500">明确选择其他供应商创建新回测：</span>
                            {(['eastmoney', 'sina', 'tencent'] as KlineBacktestDataSource[])
                                .filter(source => source !== (detail.params_snapshot.data_source ?? 'eastmoney'))
                                .filter(source => !(detail.symbol.endsWith('.BJ') && source === 'tencent'))
                                .map(source => <button key={source} type="button" className="btn-secondary text-sm" disabled={submitting} onClick={() => retryWithSource(source)}>改用{BACKTEST_DATA_SOURCE_LABELS[source]}</button>)}
                        </div>
                    )}
                </div>
            )}

            {!detailLoading && detail?.status === 'completed' && (
                <BacktestResults
                    detail={detail}
                    selectedStrategy={selectedStrategy}
                    equityByStrategy={equityByStrategy}
                    trades={trades}
                    signals={signals}
                    candles={candles}
                    loading={resultLoading}
                    onStrategyChange={strategy => void selectStrategy(strategy)}
                />
            )}
        </div>
    )
}

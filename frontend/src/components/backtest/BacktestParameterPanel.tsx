import { RotateCcw, Rocket } from 'lucide-react'

import type { KlineBacktestCreateInput, KlineBacktestDataSource, KlineBacktestInstrument, KlineBacktestStrategy } from '@/types'
import { BACKTEST_DATA_SOURCE_LABELS } from '@/utils/klineBacktest'
import BacktestSymbolPicker from './BacktestSymbolPicker'

interface Props {
    value: KlineBacktestCreateInput
    instrument: KlineBacktestInstrument
    errors: string[]
    disabled: boolean
    analysisSymbol: string
    selectedName?: string
    onChange: (value: KlineBacktestCreateInput) => void
    onSymbolSelect: (symbol: string, name?: string) => void
    onReset: () => void
    onSubmit: () => void
}

const STRATEGIES: Array<{ key: KlineBacktestStrategy; label: string }> = [
    { key: 'A', label: 'A · 均线交叉' },
    { key: 'B', label: 'B · 均线 + 斐波' },
    { key: 'C', label: 'C · 均线 + 趋势线' },
    { key: 'D', label: 'D · 综合策略' },
]

const instrumentLabel: Record<KlineBacktestInstrument, string> = {
    stock: '股票',
    fund: '场内基金',
    index: '指数',
}

export default function BacktestParameterPanel({ value, instrument, errors, disabled, analysisSymbol, selectedName, onChange, onSymbolSelect, onReset, onSubmit }: Props) {
    const dataSources: KlineBacktestDataSource[] = instrument === 'fund'
        ? ['eastmoney', 'sina']
        : ['eastmoney', 'sina', 'tencent']
    const setNumber = (key: keyof KlineBacktestCreateInput, raw: string) => {
        const numberValue = raw === '' ? 0 : Number(raw)
        onChange({ ...value, [key]: numberValue })
    }
    const setFee = (key: keyof KlineBacktestCreateInput['fee'], raw: string) => {
        onChange({ ...value, fee: { ...value.fee, [key]: raw === '' ? 0 : Number(raw) } })
    }
    const toggleStrategy = (key: KlineBacktestStrategy) => {
        const strategy_keys = value.strategy_keys.includes(key)
            ? value.strategy_keys.filter(item => item !== key)
            : [...value.strategy_keys, key]
        onChange({ ...value, strategy_keys })
    }

    return (
        <section className="card space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <h2 className="text-base font-semibold text-slate-900 dark:text-white">回测参数</h2>
                    <p className="mt-1 text-xs text-slate-500">当前标的 {value.symbol} · 识别为 {instrumentLabel[instrument]}</p>
                </div>
                <div className="flex gap-2">
                    <button type="button" className="btn-secondary flex items-center gap-1.5 text-sm" onClick={onReset} disabled={disabled}>
                        <RotateCcw size={15} /> 恢复默认
                    </button>
                    <button type="button" className="btn-primary flex items-center gap-1.5 text-sm" onClick={onSubmit} disabled={disabled || errors.length > 0 || instrument === 'index'}>
                        <Rocket size={15} /> {disabled ? '任务处理中' : '开始回测'}
                    </button>
                </div>
            </div>

            <BacktestSymbolPicker
                key={value.symbol}
                selectedSymbol={value.symbol}
                selectedName={selectedName}
                analysisSymbol={analysisSymbol}
                disabled={disabled}
                onSelect={onSymbolSelect}
            />

            {instrument === 'index' && (
                <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
                    首期暂不支持指数回测
                </div>
            )}
            {errors.length > 0 && instrument !== 'index' && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                    {errors.join('；')}
                </div>
            )}

            <div className="overflow-x-auto pb-1">
                <div className="min-w-[920px] space-y-4">
                    <div className="grid grid-cols-6 gap-3">
                        <label className="text-xs text-slate-500 col-span-2">回测区间
                            <div className="mt-1 grid grid-cols-2 gap-2">
                                <input className="input w-full" type="date" value={value.start_date} onChange={event => onChange({ ...value, start_date: event.target.value })} disabled={disabled} />
                                <input className="input w-full" type="date" value={value.end_date} onChange={event => onChange({ ...value, end_date: event.target.value })} disabled={disabled} />
                            </div>
                        </label>
                        <NumberField label="初始资金（元）" value={value.initial_cash} min={1} step={1000} disabled={disabled} onChange={raw => setNumber('initial_cash', raw)} />
                        <NumberField label="最大仓位（小数）" value={value.max_position_ratio} min={0.01} max={1} step={0.05} disabled={disabled} onChange={raw => setNumber('max_position_ratio', raw)} />
                        <NumberField label="短期 MA" value={value.short_ma} min={1} step={1} disabled={disabled} onChange={raw => setNumber('short_ma', raw)} />
                        <NumberField label="长期 MA" value={value.long_ma} min={2} step={1} disabled={disabled} onChange={raw => setNumber('long_ma', raw)} />
                    </div>

                    <details className="rounded-lg border border-slate-200 p-3 dark:border-slate-700" open>
                        <summary className="cursor-pointer text-sm font-medium">信号与风控参数</summary>
                        <div className="mt-3 grid grid-cols-6 gap-3">
                            <NumberField label="左侧确认 K 数" value={value.pivot_left} min={1} step={1} disabled={disabled} onChange={raw => setNumber('pivot_left', raw)} />
                            <NumberField label="右侧确认 K 数" value={value.pivot_right} min={1} step={1} disabled={disabled} onChange={raw => setNumber('pivot_right', raw)} />
                            <NumberField label="斐波窗口" value={value.fib_window} min={1} step={1} disabled={disabled} onChange={raw => setNumber('fib_window', raw)} />
                            <NumberField label="锚点最小间隔" value={value.pivot_min_separation} min={1} step={1} disabled={disabled} onChange={raw => setNumber('pivot_min_separation', raw)} />
                            <label className="text-xs text-slate-500">斐波模式
                                <select className="input mt-1 w-full" value={value.fib_mode} disabled={disabled} onChange={event => onChange({ ...value, fib_mode: event.target.value as 'discrete' | 'zone' })}>
                                    <option value="discrete">离散关键位</option>
                                    <option value="zone">宽区间</option>
                                </select>
                            </label>
                            <NumberField label="离散位容差（小数）" value={value.fib_tolerance} min={0} max={0.99} step={0.001} disabled={disabled} onChange={raw => setNumber('fib_tolerance', raw)} />
                            <NumberField label="最小波段振幅" value={value.fib_min_amplitude} min={0} max={0.99} step={0.01} disabled={disabled} onChange={raw => setNumber('fib_min_amplitude', raw)} />
                            <NumberField label="趋势线容差" value={value.trend_tolerance} min={0} max={0.99} step={0.001} disabled={disabled} onChange={raw => setNumber('trend_tolerance', raw)} />
                            <NumberField label="趋势线跌破阈值" value={value.trend_break_threshold} min={0} max={0.99} step={0.001} disabled={disabled} onChange={raw => setNumber('trend_break_threshold', raw)} />
                            <NumberField label="趋势线最小触点" value={value.trend_min_touches} min={3} step={1} disabled={disabled} onChange={raw => setNumber('trend_min_touches', raw)} />
                            <NumberField label="止盈（小数）" value={value.take_profit ?? 0} min={0.001} step={0.01} disabled={disabled} onChange={raw => setNumber('take_profit', raw)} />
                            <NumberField label="止损（小数）" value={value.stop_loss ?? 0} min={0.001} max={0.99} step={0.01} disabled={disabled} onChange={raw => setNumber('stop_loss', raw)} />
                            <NumberField label="挂单顺延上限（日）" value={value.max_deferred_days} min={0} step={1} disabled={disabled} onChange={raw => setNumber('max_deferred_days', raw)} />
                        </div>
                    </details>

                    <details className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                        <summary className="cursor-pointer text-sm font-medium">交易成本（费率使用小数，免五已设为最低佣金 0）</summary>
                        <div className="mt-3 grid grid-cols-6 gap-3">
                            <NumberField label="佣金率" value={value.fee.commission_rate} min={0} step={0.000001} disabled={disabled} onChange={raw => setFee('commission_rate', raw)} />
                            <NumberField label="最低佣金（元）" value={value.fee.minimum_commission} min={0} step={0.01} disabled={disabled} onChange={raw => setFee('minimum_commission', raw)} />
                            <NumberField label="印花税率" value={value.fee.stamp_tax_rate} min={0} step={0.00001} disabled={disabled} onChange={raw => setFee('stamp_tax_rate', raw)} />
                            <NumberField label="过户费率" value={value.fee.transfer_fee_rate} min={0} step={0.000001} disabled={disabled} onChange={raw => setFee('transfer_fee_rate', raw)} />
                            <NumberField label="买入滑点率" value={value.fee.buy_slippage_rate} min={0} step={0.0001} disabled={disabled} onChange={raw => setFee('buy_slippage_rate', raw)} />
                            <NumberField label="卖出滑点率" value={value.fee.sell_slippage_rate} min={0} step={0.0001} disabled={disabled} onChange={raw => setFee('sell_slippage_rate', raw)} />
                        </div>
                    </details>

                    <div className="grid grid-cols-[minmax(0,1fr)_160px_160px_180px] gap-4 items-end">
                        <fieldset>
                            <legend className="mb-2 text-xs text-slate-500">待比较策略组</legend>
                            <div className="flex flex-wrap gap-2">
                                {STRATEGIES.map(item => (
                                    <label key={item.key} className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700">
                                        <input type="checkbox" checked={value.strategy_keys.includes(item.key)} onChange={() => toggleStrategy(item.key)} disabled={disabled} />
                                        {item.label}
                                    </label>
                                ))}
                            </div>
                        </fieldset>
                        <label className="text-xs text-slate-500">行情数据源
                            <select className="input mt-1 w-full" value={value.data_source} disabled={disabled} onChange={event => onChange({ ...value, data_source: event.target.value as KlineBacktestDataSource })}>
                                {dataSources.map(source => <option key={source} value={source}>{BACKTEST_DATA_SOURCE_LABELS[source]}{instrument === 'fund' && source === 'sina' ? '（不复权）' : ''}</option>)}
                            </select>
                        </label>
                        <label className="text-xs text-slate-500">复权方式
                            <select className="input mt-1 w-full" value={value.adjust} disabled={disabled} onChange={event => onChange({ ...value, adjust: event.target.value as KlineBacktestCreateInput['adjust'] })}>
                                <option value="qfq">前复权</option>
                                <option value="hfq">后复权</option>
                                <option value="none">不复权</option>
                                <option value="raw">原始数据</option>
                            </select>
                        </label>
                        <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2.5 text-sm dark:border-slate-700">
                            <input type="checkbox" checked={value.force_refresh} onChange={event => onChange({ ...value, force_refresh: event.target.checked })} disabled={disabled} />
                            强制刷新数据
                        </label>
                    </div>
                    <p className="text-xs text-slate-500">每次回测锁定所选数据源并记录接口、版本和数据哈希；连接失败不会静默切换供应商。</p>
                </div>
            </div>
        </section>
    )
}

function NumberField({ label, value, min, max, step, disabled, onChange }: {
    label: string
    value: number
    min?: number
    max?: number
    step?: number
    disabled: boolean
    onChange: (value: string) => void
}) {
    return (
        <label className="text-xs text-slate-500">{label}
            <input className="input mt-1 w-full" type="number" value={value} min={min} max={max} step={step} disabled={disabled} onChange={event => onChange(event.target.value)} />
        </label>
    )
}

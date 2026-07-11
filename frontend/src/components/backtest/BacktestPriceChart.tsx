import { useEffect, useMemo, useRef, useState } from 'react'
import {
    BusinessDay,
    CandlestickSeries,
    ColorType,
    IChartApi,
    ISeriesApi,
    ISeriesMarkersPluginApi,
    LineSeries,
    LineStyle,
    SeriesMarker,
    Time,
    createChart,
    createSeriesMarkers,
} from 'lightweight-charts'
import { Layers3, RotateCcw } from 'lucide-react'

import type { KlineBacktestSignal, KlineBacktestTrade, KlineCandle } from '@/types'
import {
    ALL_BACKTEST_CHART_LAYERS,
    BacktestChartLayerKey,
    BacktestChartLayers,
    COMPACT_BACKTEST_CHART_LAYERS,
    latestQualifiedFibonacciRange,
    resolveBacktestChartLayers,
    splitEffectiveTrendlines,
} from '@/utils/klineBacktest'

interface Props {
    candles: KlineCandle[]
    signals: KlineBacktestSignal[]
    trades: KlineBacktestTrade[]
    shortMa: number
    longMa: number
    trendMinTouches: number
}

const LAYER_STORAGE_KEY = 'kline-backtest-chart-layers-v1'

function initialLayers(): BacktestChartLayers {
    try {
        return resolveBacktestChartLayers(JSON.parse(window.localStorage.getItem(LAYER_STORAGE_KEY) ?? '{}'))
    } catch {
        return { ...COMPACT_BACKTEST_CHART_LAYERS }
    }
}

function asBusinessDay(value: string): BusinessDay | null {
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value)
    if (!match) return null
    return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) }
}

function finite(value: string | number | null | undefined): number | null {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
}

export default function BacktestPriceChart({ candles, signals, trades, shortMa, longMa, trendMinTouches }: Props) {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const [dark, setDark] = useState(document.documentElement.classList.contains('dark'))
    const [layers, setLayers] = useState<BacktestChartLayers>(initialLayers)
    const layersRef = useRef(layers)
    const chartRef = useRef<IChartApi | null>(null)
    const layerApiRef = useRef<{
        shortMa: ISeriesApi<'Line'> | null
        longMa: ISeriesApi<'Line'> | null
        trendlines: ISeriesApi<'Line'>[]
        fibonacci: ISeriesApi<'Line'>[]
        tradeMarkers: ISeriesMarkersPluginApi<Time> | null
        markerData: SeriesMarker<Time>[]
    }>({ shortMa: null, longMa: null, trendlines: [], fibonacci: [], tradeMarkers: null, markerData: [] })

    const effectiveTrendTouches = useMemo(
        () => Math.max(0, ...signals.filter(item => item.trendline_price && item.touch_count >= trendMinTouches).map(item => item.touch_count)),
        [signals, trendMinTouches],
    )

    useEffect(() => {
        const observer = new MutationObserver(() => setDark(document.documentElement.classList.contains('dark')))
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
        return () => observer.disconnect()
    }, [])

    useEffect(() => {
        layersRef.current = layers
        window.localStorage.setItem(LAYER_STORAGE_KEY, JSON.stringify(layers))
        const api = layerApiRef.current
        api.shortMa?.applyOptions({ visible: layers.shortMa })
        api.longMa?.applyOptions({ visible: layers.longMa })
        api.trendlines.forEach(series => series.applyOptions({ visible: layers.trendlines }))
        api.fibonacci.forEach(series => series.applyOptions({ visible: layers.fibonacci }))
        api.tradeMarkers?.setMarkers(layers.tradeMarkers ? api.markerData : [])
    }, [layers])

    useEffect(() => {
        const container = containerRef.current
        if (!container || candles.length === 0) return
        const currentLayers = layersRef.current
        const chart = createChart(container, {
            width: Math.max(container.clientWidth, 900),
            height: 500,
            layout: {
                background: { type: ColorType.Solid, color: 'transparent' },
                textColor: dark ? '#94a3b8' : '#475569',
                attributionLogo: false,
            },
            grid: {
                vertLines: { color: dark ? 'rgba(51,65,85,.55)' : 'rgba(226,232,240,.8)' },
                horzLines: { color: dark ? 'rgba(51,65,85,.55)' : 'rgba(226,232,240,.8)' },
            },
            rightPriceScale: { borderColor: dark ? '#334155' : '#cbd5e1' },
            timeScale: { borderColor: dark ? '#334155' : '#cbd5e1', rightOffset: 5 },
            localization: { locale: 'zh-CN', dateFormat: 'yyyy-MM-dd' },
        })
        chartRef.current = chart

        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#ef4444', downColor: '#22c55e', wickUpColor: '#ef4444', wickDownColor: '#22c55e', borderVisible: false,
        })
        const candleData = candles.flatMap(item => {
            const time = asBusinessDay(item.date)
            const open = finite(item.open)
            const high = finite(item.high)
            const low = finite(item.low)
            const close = finite(item.close)
            return time && open != null && high != null && low != null && close != null
                ? [{ time, open, high, low, close }]
                : []
        })
        candleSeries.setData(candleData)

        const shortSeries = chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 2, title: `MA${shortMa}`, visible: currentLayers.shortMa })
        const longSeries = chart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 2, title: `MA${longMa}`, visible: currentLayers.longMa })
        shortSeries.setData(signals.flatMap(item => {
            const time = asBusinessDay(item.date)
            const value = finite(item.ma_values.short)
            return time && value != null ? [{ time, value }] : []
        }))
        longSeries.setData(signals.flatMap(item => {
            const time = asBusinessDay(item.date)
            const value = finite(item.ma_values.long)
            return time && value != null ? [{ time, value }] : []
        }))

        const trendSeriesList: ISeriesApi<'Line'>[] = []
        const effectiveTrendSegments = splitEffectiveTrendlines(signals, trendMinTouches)
        effectiveTrendSegments.forEach((segment, index) => {
            const trendSeries = chart.addSeries(LineSeries, {
                color: '#8b5cf6', lineWidth: 3, title: index === 0 ? `有效趋势线（${effectiveTrendTouches} 触点）` : '', visible: currentLayers.trendlines,
            })
            trendSeriesList.push(trendSeries)
            trendSeries.setData(segment.flatMap(point => {
                const time = asBusinessDay(point.date)
                return time ? [{ time, value: point.value }] : []
            }))
        })

        const fibonacciSeriesList: ISeriesApi<'Line'>[] = []
        const fibonacciRange = latestQualifiedFibonacciRange(signals)
        if (fibonacciRange) {
            const from = asBusinessDay(fibonacciRange.fromDate)
            const to = asBusinessDay(fibonacciRange.toDate)
            if (from && to) {
                const colors: Record<string, string> = { '0.382': '#06b6d4', '0.5': '#14b8a6', '0.618': '#10b981' }
                Object.entries(fibonacciRange.levels)
                    .filter(([ratio]) => ['0.382', '0.5', '0.618'].includes(ratio))
                    .forEach(([ratio, raw]) => {
                        const value = finite(raw)
                        if (value == null) return
                        const series = chart.addSeries(LineSeries, {
                            color: colors[ratio], lineWidth: 1, lineStyle: LineStyle.Dashed, title: `Fib ${ratio}`, visible: currentLayers.fibonacci,
                        })
                        fibonacciSeriesList.push(series)
                        series.setData([{ time: from, value }, { time: to, value }])
                    })
            }
        }

        const markers: SeriesMarker<Time>[] = trades
            .filter(item => item.order_outcome === 'executed' && item.actual_date)
            .flatMap(item => {
                const time = asBusinessDay(item.actual_date!)
                if (!time) return []
                const stop = item.trigger_reason.includes('stop_loss')
                const take = item.trigger_reason.includes('take_profit')
                const text = stop ? '止损' : take ? '止盈' : item.side === 'BUY' ? '买入' : '卖出'
                return [{
                    time,
                    position: item.side === 'BUY' ? 'belowBar' as const : 'aboveBar' as const,
                    color: stop ? '#dc2626' : take ? '#f59e0b' : item.side === 'BUY' ? '#ef4444' : '#22c55e',
                    shape: item.side === 'BUY' ? 'arrowUp' as const : 'arrowDown' as const,
                    text,
                }]
            })
            .sort((a, b) => JSON.stringify(a.time).localeCompare(JSON.stringify(b.time)))
        const markerApi = createSeriesMarkers(candleSeries, currentLayers.tradeMarkers ? markers : [])
        layerApiRef.current = {
            shortMa: shortSeries,
            longMa: longSeries,
            trendlines: trendSeriesList,
            fibonacci: fibonacciSeriesList,
            tradeMarkers: markerApi,
            markerData: markers,
        }
        chart.timeScale().fitContent()

        const resize = () => chart.applyOptions({ width: Math.max(container.clientWidth, 900) })
        window.addEventListener('resize', resize)
        return () => {
            window.removeEventListener('resize', resize)
            if (chartRef.current === chart) chartRef.current = null
            layerApiRef.current = { shortMa: null, longMa: null, trendlines: [], fibonacci: [], tradeMarkers: null, markerData: [] }
            chart.remove()
        }
    }, [candles, dark, effectiveTrendTouches, longMa, shortMa, signals, trades, trendMinTouches])

    const toggleLayer = (key: BacktestChartLayerKey) => setLayers(current => ({ ...current, [key]: !current[key] }))
    const resetView = () => {
        const chart = chartRef.current
        if (!chart) return
        chart.priceScale('right').applyOptions({ autoScale: true })
        chart.timeScale().fitContent()
    }
    const layerButton = (key: BacktestChartLayerKey, label: string, color: string) => (
        <button
            type="button"
            aria-pressed={layers[key]}
            onClick={() => toggleLayer(key)}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 transition ${layers[key]
                ? 'border-slate-400 bg-slate-100 text-slate-800 dark:border-slate-500 dark:bg-slate-700 dark:text-slate-100'
                : 'border-slate-200 text-slate-400 line-through opacity-65 dark:border-slate-700 dark:text-slate-500'}`}
        >
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />{label}
        </button>
    )

    return (
        <section className="card">
            <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                <div>
                    <h3 className="font-semibold">价格、信号与有效技术线</h3>
                    <p className="mt-1 text-xs text-slate-500">同一画布统一缩放与拖动；通过图层管理按需显示技术线</p>
                </div>
                <div className="min-w-0 rounded-xl border border-slate-200 bg-white/50 p-2.5 dark:border-slate-700 dark:bg-slate-900/30">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                        <span className="inline-flex items-center gap-1.5 font-medium text-slate-600 dark:text-slate-300"><Layers3 size={14} />图层管理</span>
                        <span className="flex gap-1.5">
                            <button type="button" className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700" onClick={resetView}><RotateCcw size={12} />重置视图</button>
                            <button type="button" className="rounded px-2 py-0.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700" onClick={() => setLayers({ ...COMPACT_BACKTEST_CHART_LAYERS })}>精简</button>
                            <button type="button" className="rounded px-2 py-0.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700" onClick={() => setLayers({ ...ALL_BACKTEST_CHART_LAYERS })}>全部显示</button>
                        </span>
                    </div>
                    <div className="flex flex-wrap gap-1.5 text-xs">
                        {layerButton('shortMa', `MA${shortMa}`, '#f59e0b')}
                        {layerButton('longMa', `MA${longMa}`, '#3b82f6')}
                        {layerButton('trendlines', `趋势线${effectiveTrendTouches ? ` · ${effectiveTrendTouches}触点` : ''}`, '#8b5cf6')}
                        {layerButton('fibonacci', '斐波那契', '#14b8a6')}
                        {layerButton('tradeMarkers', '买卖标记', '#ef4444')}
                    </div>
                </div>
            </div>
            {candles.length === 0
                ? <div className="grid h-64 place-items-center text-sm text-slate-500">暂无 K 线数据</div>
                : <div className="overflow-x-auto"><div ref={containerRef} className="min-w-[900px]" /></div>}
        </section>
    )
}

import { useEffect, useMemo, useRef, useState } from 'react'
import {
    BusinessDay,
    CandlestickSeries,
    ColorType,
    LineSeries,
    LineStyle,
    SeriesMarker,
    Time,
    createChart,
    createSeriesMarkers,
} from 'lightweight-charts'

import type { KlineBacktestSignal, KlineBacktestTrade, KlineCandle } from '@/types'
import { splitEffectiveTrendlines } from '@/utils/klineBacktest'

interface Props {
    candles: KlineCandle[]
    signals: KlineBacktestSignal[]
    trades: KlineBacktestTrade[]
    shortMa: number
    longMa: number
    trendMinTouches: number
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
        const container = containerRef.current
        if (!container || candles.length === 0) return
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

        const shortSeries = chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 2, title: `MA${shortMa}` })
        const longSeries = chart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 2, title: `MA${longMa}` })
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

        const effectiveTrendSegments = splitEffectiveTrendlines(signals, trendMinTouches)
        effectiveTrendSegments.forEach((segment, index) => {
            const trendSeries = chart.addSeries(LineSeries, {
                color: '#8b5cf6', lineWidth: 3, title: index === 0 ? `有效趋势线（${effectiveTrendTouches} 触点）` : '',
            })
            trendSeries.setData(segment.flatMap(point => {
                const time = asBusinessDay(point.date)
                return time ? [{ time, value: point.value }] : []
            }))
        })

        let lastQualifiedIndex = -1
        for (let index = signals.length - 1; index >= 0; index -= 1) {
            if (signals[index].fib_levels && finite(signals[index].swing_amplitude) != null) {
                lastQualifiedIndex = index
                break
            }
        }
        if (lastQualifiedIndex >= 0) {
            const levels = signals[lastQualifiedIndex].fib_levels!
            const signature = JSON.stringify(levels)
            let firstIndex = lastQualifiedIndex
            while (firstIndex > 0 && JSON.stringify(signals[firstIndex - 1].fib_levels) === signature) firstIndex -= 1
            const from = asBusinessDay(signals[firstIndex].date)
            const to = asBusinessDay(candles[candles.length - 1].date)
            if (from && to) {
                const colors: Record<string, string> = { '0.382': '#06b6d4', '0.5': '#14b8a6', '0.618': '#10b981' }
                Object.entries(levels)
                    .filter(([ratio]) => ['0.382', '0.5', '0.618'].includes(ratio))
                    .forEach(([ratio, raw]) => {
                        const value = finite(raw)
                        if (value == null) return
                        const series = chart.addSeries(LineSeries, {
                            color: colors[ratio], lineWidth: 1, lineStyle: LineStyle.Dashed, title: `Fib ${ratio}`,
                        })
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
        createSeriesMarkers(candleSeries, markers)
        chart.timeScale().fitContent()

        const resize = () => chart.applyOptions({ width: Math.max(container.clientWidth, 900) })
        window.addEventListener('resize', resize)
        return () => {
            window.removeEventListener('resize', resize)
            chart.remove()
        }
    }, [candles, dark, effectiveTrendTouches, longMa, shortMa, signals, trades, trendMinTouches])

    return (
        <section className="card">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div>
                    <h3 className="font-semibold">价格、信号与有效技术线</h3>
                    <p className="mt-1 text-xs text-slate-500">同一画布统一缩放与拖动；仅展示有效趋势线和合格波段关键位</p>
                </div>
                <div className="flex flex-wrap gap-3 text-xs text-slate-500">
                    <span className="text-amber-500">MA{shortMa}</span><span className="text-blue-500">MA{longMa}</span>
                    <span className="text-violet-500">有效趋势线 {effectiveTrendTouches ? `${effectiveTrendTouches} 触点` : '暂无'}</span>
                </div>
            </div>
            {candles.length === 0
                ? <div className="grid h-64 place-items-center text-sm text-slate-500">暂无 K 线数据</div>
                : <div className="overflow-x-auto"><div ref={containerRef} className="min-w-[900px]" /></div>}
        </section>
    )
}

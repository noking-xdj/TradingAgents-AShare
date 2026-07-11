import { describe, expect, it } from 'vitest'

import {
    ALL_BACKTEST_CHART_LAYERS,
    COMPACT_BACKTEST_CHART_LAYERS,
    classifyBacktestInstrument,
    createDefaultBacktestInput,
    defaultBacktestFees,
    normalizeBacktestSymbol,
    previousFullYear,
    resolveBacktestChartLayers,
    splitEffectiveTrendlines,
    validateBacktestInput,
} from '@/utils/klineBacktest'
import type { KlineBacktestSignal } from '@/types'

describe('K-line backtest defaults', () => {
    it('uses the previous complete natural year and all four strategies', () => {
        expect(previousFullYear(new Date('2026-07-11T12:00:00+08:00'))).toEqual({
            start: '2025-01-01',
            end: '2025-12-31',
        })
        const value = createDefaultBacktestInput('601398.SH', new Date('2026-07-11T12:00:00+08:00'))
        expect(value.strategy_keys).toEqual(['A', 'B', 'C', 'D'])
        expect(value.data_source).toBe('tencent')
        expect(value.adjust).toBe('qfq')
        expect(value.initial_cash).toBe(100000)
        expect(value.fee.minimum_commission).toBe(0)

        const fund = createDefaultBacktestInput('510300.SH', new Date('2026-07-11T12:00:00+08:00'))
        expect(fund.data_source).toBe('sina')
        expect(fund.adjust).toBe('raw')

        const bse = createDefaultBacktestInput('830799.BJ', new Date('2026-07-11T12:00:00+08:00'))
        expect(bse.data_source).toBe('sina')
        expect(bse.adjust).toBe('qfq')
    })

    it('matches backend instrument classification and configured fee defaults', () => {
        expect(normalizeBacktestSymbol('600519')).toBe('600519.SH')
        expect(normalizeBacktestSymbol('159915')).toBe('159915.SZ')
        expect(normalizeBacktestSymbol('SH000001')).toBe('000001.SH')
        expect(normalizeBacktestSymbol('贵州茅台')).toBeNull()
        expect(classifyBacktestInstrument('000001.SH')).toBe('index')
        expect(classifyBacktestInstrument('399006.SZ')).toBe('index')
        expect(classifyBacktestInstrument('510300.SH')).toBe('fund')
        expect(classifyBacktestInstrument('601398.SH')).toBe('stock')
        expect(defaultBacktestFees('stock').commission_rate).toBe(0.000115)
        expect(defaultBacktestFees('fund').commission_rate).toBe(0.0001)
        expect(defaultBacktestFees('fund').stamp_tax_rate).toBe(0)
    })
})

describe('K-line backtest validation', () => {
    it('rejects an invalid date range and short MA not below long MA', () => {
        const input = createDefaultBacktestInput('601398.SH')
        input.start_date = '2025-12-31'
        input.end_date = '2025-01-01'
        input.short_ma = 20
        input.long_ma = 20
        expect(validateBacktestInput(input)).toEqual(expect.arrayContaining([
            '开始日期不能晚于结束日期',
            '短期均线必须小于长期均线',
        ]))
    })

    it('accepts the complete default stock configuration', () => {
        expect(validateBacktestInput(createDefaultBacktestInput('601398.SH'))).toEqual([])
    })

    it('validates source capabilities without silently changing the selection', () => {
        const fund = createDefaultBacktestInput('510300.SH')
        fund.data_source = 'sina'
        fund.adjust = 'qfq'
        expect(validateBacktestInput(fund)).toContain('场内基金使用新浪时只能选择不复权')
        fund.adjust = 'raw'
        expect(validateBacktestInput(fund)).toEqual([])

        const bse = createDefaultBacktestInput('830799.BJ')
        bse.data_source = 'tencent'
        expect(validateBacktestInput(bse)).toContain('北交所股票暂不支持腾讯数据源')
    })
})

describe('backtest chart layer management', () => {
    it('defaults to a compact chart and accepts persisted boolean overrides only', () => {
        expect(COMPACT_BACKTEST_CHART_LAYERS).toMatchObject({
            shortMa: true,
            longMa: true,
            trendlines: false,
            fibonacci: false,
            tradeMarkers: true,
        })
        expect(resolveBacktestChartLayers({ trendlines: true, fibonacci: true, shortMa: 'bad' })).toEqual({
            ...ALL_BACKTEST_CHART_LAYERS,
            shortMa: true,
        })
        expect(resolveBacktestChartLayers(null)).toEqual(COMPACT_BACKTEST_CHART_LAYERS)
    })
})

describe('effective trendline rendering', () => {
    it('keeps stable slopes and never connects unrelated effective lines', () => {
        const values = ['10', '10.1', '10.2', '12', '12.2', '12.4']
        const signals = values.map((value, index) => ({
            date: `2025-01-${String(index + 1).padStart(2, '0')}`,
            trendline_price: value,
            touch_count: 3,
        })) as KlineBacktestSignal[]
        expect(splitEffectiveTrendlines(signals, 3)).toEqual([
            [
                { date: '2025-01-01', value: 10 },
                { date: '2025-01-02', value: 10.1 },
                { date: '2025-01-03', value: 10.2 },
            ],
            [
                { date: '2025-01-04', value: 12 },
                { date: '2025-01-05', value: 12.2 },
                { date: '2025-01-06', value: 12.4 },
            ],
        ])
    })

    it('drops candidate, gapped, and isolated points', () => {
        const signals = [
            { date: '2025-01-01', trendline_price: '10', touch_count: 2 },
            { date: '2025-01-02', trendline_price: '10.1', touch_count: 3 },
            { date: '2025-01-03', trendline_price: null, touch_count: 0 },
            { date: '2025-01-04', trendline_price: '10.3', touch_count: 3 },
        ] as KlineBacktestSignal[]
        expect(splitEffectiveTrendlines(signals, 3)).toEqual([])
    })
})

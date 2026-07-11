import { describe, expect, it } from 'vitest'

import {
    BACKTEST_METRIC_CARDS,
    backtestEndingPnl,
    formatBacktestMetric,
    formatSignedBacktestMoney,
} from './backtestMetrics'

describe('backtest result metrics', () => {
    it('includes and formats the profit/loss ratio', () => {
        expect(BACKTEST_METRIC_CARDS.find(item => item.key === 'profit_loss_ratio')).toMatchObject({
            label: '盈亏比',
            format: 'ratio',
        })
        expect(formatBacktestMetric('1.256', 'ratio')).toBe('1.26')
        expect(formatBacktestMetric(null, 'ratio')).toBe('--')
    })

    it('uses explicit holding unrealized P&L and falls back to ending account P&L', () => {
        expect(backtestEndingPnl({ unrealized_pnl: '23114.03', final_asset: '999999', initial_cash: '1' })).toBe(23114.03)
        expect(backtestEndingPnl({ final_asset: '120609.44', initial_cash: '100000' })).toBeCloseTo(20609.44)
        expect(backtestEndingPnl({ final_asset: null, initial_cash: null })).toBeNull()
        expect(backtestEndingPnl(null)).toBeNull()
        expect(formatSignedBacktestMoney(23114.03)).toBe('+¥23,114.03')
        expect(formatSignedBacktestMoney(-1250)).toBe('-¥1,250')
    })
})

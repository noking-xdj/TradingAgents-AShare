import { describe, expect, it } from 'vitest'

import { BACKTEST_METRIC_CARDS, formatBacktestMetric } from './backtestMetrics'

describe('backtest result metrics', () => {
    it('includes and formats the profit/loss ratio', () => {
        expect(BACKTEST_METRIC_CARDS.find(item => item.key === 'profit_loss_ratio')).toMatchObject({
            label: '盈亏比',
            format: 'ratio',
        })
        expect(formatBacktestMetric('1.256', 'ratio')).toBe('1.26')
        expect(formatBacktestMetric(null, 'ratio')).toBe('--')
    })
})

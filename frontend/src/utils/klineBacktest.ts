import type {
    KlineBacktestCreateInput,
    KlineBacktestFeeInput,
    KlineBacktestInstrument,
    KlineBacktestSignal,
} from '@/types'

export function previousFullYear(today = new Date()): { start: string; end: string } {
    const year = today.getFullYear() - 1
    return { start: `${year}-01-01`, end: `${year}-12-31` }
}

export function normalizeBacktestSymbol(raw: string): string | null {
    const value = raw.trim().toUpperCase()
    const match = /^(?:(SH|SZ|BJ))?(\d{6})(?:\.(SH|SZ|BJ|SS))?$/.exec(value)
    if (!match) return null
    const code = match[2]
    let suffix = match[3] ?? match[1]
    if (suffix === 'SS') suffix = 'SH'
    if (!suffix) {
        if (['4', '8'].some(prefix => code.startsWith(prefix)) || code.startsWith('92')) suffix = 'BJ'
        else if (['5', '6', '9'].some(prefix => code.startsWith(prefix))) suffix = 'SH'
        else suffix = 'SZ'
    }
    return `${code}.${suffix}`
}

export function classifyBacktestInstrument(symbol: string): KlineBacktestInstrument {
    const normalized = normalizeBacktestSymbol(symbol) ?? symbol.trim().toUpperCase()
    const [code, suffix = ''] = normalized.split('.')
    if ((suffix === 'SH' && code.startsWith('000'))
        || (suffix === 'SZ' && code.startsWith('399'))
        || (suffix === 'BJ' && code.startsWith('899'))) return 'index'
    if ((suffix === 'SH' && code.startsWith('5'))
        || (suffix === 'SZ' && ['15', '16', '18'].some(prefix => code.startsWith(prefix)))) return 'fund'
    return 'stock'
}

export function defaultBacktestFees(instrument: KlineBacktestInstrument): KlineBacktestFeeInput {
    if (instrument === 'fund') {
        return {
            commission_rate: 0.0001,
            minimum_commission: 0,
            stamp_tax_rate: 0,
            transfer_fee_rate: 0,
            buy_slippage_rate: 0.001,
            sell_slippage_rate: 0.001,
        }
    }
    return {
        commission_rate: 0.000115,
        minimum_commission: 0,
        stamp_tax_rate: 0.0005,
        transfer_fee_rate: 0.00001,
        buy_slippage_rate: 0.001,
        sell_slippage_rate: 0.001,
    }
}

export function createDefaultBacktestInput(symbol: string, today = new Date()): KlineBacktestCreateInput {
    const period = previousFullYear(today)
    const instrument = classifyBacktestInstrument(symbol)
    return {
        symbol: symbol.trim().toUpperCase(),
        start_date: period.start,
        end_date: period.end,
        strategy_keys: ['A', 'B', 'C', 'D'],
        adjust: 'qfq',
        force_refresh: false,
        initial_cash: 100000,
        max_position_ratio: 1,
        short_ma: 5,
        long_ma: 20,
        pivot_left: 3,
        pivot_right: 3,
        fib_window: 60,
        fib_tolerance: 0.01,
        fib_min_amplitude: 0.05,
        fib_mode: 'discrete',
        trend_tolerance: 0.005,
        trend_break_threshold: 0.01,
        trend_min_touches: 3,
        pivot_min_separation: 5,
        stop_loss: 0.08,
        take_profit: 0.15,
        max_deferred_days: 5,
        risk_free_rate: 0.02,
        annual_trading_days: 252,
        fee: defaultBacktestFees(instrument),
    }
}

export function validateBacktestInput(input: KlineBacktestCreateInput): string[] {
    const errors: string[] = []
    if (!input.symbol.trim()) errors.push('证券代码不能为空')
    if (!input.start_date || !input.end_date || input.start_date > input.end_date) errors.push('开始日期不能晚于结束日期')
    if (!(input.short_ma > 0 && input.short_ma < input.long_ma)) errors.push('短期均线必须小于长期均线')
    if (input.initial_cash <= 0) errors.push('初始资金必须大于 0')
    if (!(input.max_position_ratio > 0 && input.max_position_ratio <= 1)) errors.push('最大仓位必须在 0% 到 100% 之间')
    if (input.strategy_keys.length === 0) errors.push('至少选择一个策略')
    if (input.trend_min_touches < 3) errors.push('趋势线最小触点数不能少于 3')
    if (input.pivot_left < 1 || input.pivot_right < 1 || input.fib_window < 1) errors.push('波段确认窗口必须为正整数')
    if (input.fib_tolerance < 0 || input.fib_tolerance >= 1) errors.push('斐波容差必须在 0 到 100% 之间')
    if (input.fib_min_amplitude < 0 || input.fib_min_amplitude >= 1) errors.push('最小波段振幅必须在 0 到 100% 之间')
    if (input.trend_tolerance < 0 || input.trend_tolerance >= 1) errors.push('趋势线容差必须在 0 到 100% 之间')
    if (input.stop_loss != null && (input.stop_loss <= 0 || input.stop_loss >= 1)) errors.push('止损比例必须在 0 到 100% 之间')
    if (input.take_profit != null && input.take_profit <= 0) errors.push('止盈比例必须大于 0')
    if (input.max_deferred_days < 0) errors.push('挂单顺延上限不能为负数')
    return errors
}

export function splitEffectiveTrendlines(
    signals: KlineBacktestSignal[],
    minTouches: number,
): Array<Array<{ date: string; value: number }>> {
    const contiguousRuns: Array<Array<{ date: string; value: number }>> = []
    let current: Array<{ date: string; value: number }> = []
    let previousSignalIndex = -2
    signals.forEach((signal, signalIndex) => {
        const value = Number(signal.trendline_price)
        const eligible = signal.trendline_price != null && Number.isFinite(value) && signal.touch_count >= minTouches
        if (!eligible) {
            if (current.length) contiguousRuns.push(current)
            current = []
            previousSignalIndex = -2
            return
        }
        if (signalIndex !== previousSignalIndex + 1 && current.length) {
            contiguousRuns.push(current)
            current = []
        }
        current.push({ date: signal.date, value })
        previousSignalIndex = signalIndex
    })
    if (current.length) contiguousRuns.push(current)

    const segments: Array<Array<{ date: string; value: number }>> = []
    contiguousRuns.forEach(run => {
        if (run.length < 3) return
        const slopes = run.slice(1).map((point, index) => point.value - run[index].value)
        let slopeStart = 0
        const flush = (slopeEndExclusive: number) => {
            if (slopeEndExclusive - slopeStart >= 2) segments.push(run.slice(slopeStart, slopeEndExclusive + 1))
        }
        for (let index = 1; index < slopes.length; index += 1) {
            const baseline = slopes[index - 1]
            const tolerance = Math.max(1e-7, Math.abs(baseline) * 0.05, Math.abs(run[index].value) * 1e-6)
            if (Math.abs(slopes[index] - baseline) > tolerance) {
                flush(index)
                slopeStart = index
            }
        }
        flush(slopes.length)
    })
    return segments
}

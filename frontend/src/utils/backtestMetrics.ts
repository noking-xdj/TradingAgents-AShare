export type BacktestMetricFormat = 'money' | 'percent' | 'number' | 'ratio'

export interface BacktestMetricDefinition {
    key: string
    label: string
    format: BacktestMetricFormat
    description?: string
}

export const BACKTEST_METRIC_CARDS: BacktestMetricDefinition[] = [
    { key: 'final_asset', label: '期末资产', format: 'money' },
    { key: 'total_return', label: '净收益率', format: 'percent' },
    { key: 'annualized_return', label: '年化收益率', format: 'percent' },
    { key: 'max_drawdown', label: '最大回撤', format: 'percent' },
    { key: 'sharpe', label: '夏普比率', format: 'ratio' },
    { key: 'completed_trades', label: '完整交易', format: 'number' },
    { key: 'win_rate', label: '胜率', format: 'percent' },
    {
        key: 'profit_loss_ratio',
        label: '盈亏比',
        format: 'ratio',
        description: '盈利交易净盈利总额 ÷ 亏损交易净亏损绝对值',
    },
    { key: 'total_cost', label: '总成本', format: 'money' },
]

export function formatBacktestMetric(
    value: string | number | null | undefined,
    format: BacktestMetricFormat,
): string {
    if (value == null || value === '') return '--'
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) return '--'
    if (format === 'money') return `¥${parsed.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
    if (format === 'percent') return `${(parsed * 100).toFixed(2)}%`
    if (format === 'number') return String(Math.round(parsed))
    return parsed.toFixed(2)
}

export function backtestEndingPnl(metrics: Record<string, string | number | null> | null | undefined): number | null {
    if (!metrics) return null
    const explicit = Number(metrics.unrealized_pnl)
    if (metrics.unrealized_pnl != null && Number.isFinite(explicit)) return explicit
    const finalAsset = Number(metrics.final_asset)
    const initialCash = Number(metrics.initial_cash)
    return metrics.final_asset != null
        && metrics.initial_cash != null
        && Number.isFinite(finalAsset)
        && Number.isFinite(initialCash)
        ? finalAsset - initialCash
        : null
}

export function formatSignedBacktestMoney(value: number | null): string {
    if (value == null || !Number.isFinite(value)) return '--'
    const sign = value > 0 ? '+' : value < 0 ? '-' : ''
    return `${sign}¥${Math.abs(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
}

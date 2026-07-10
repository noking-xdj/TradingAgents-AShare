import {
    Bar,
    BarChart,
    CartesianGrid,
    Cell,
    LabelList,
    Legend,
    Line,
    LineChart,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts'

import type { KlineBacktestDetail, KlineBacktestEquityPoint, KlineBacktestStrategy } from '@/types'

interface Props {
    detail: KlineBacktestDetail
    selectedStrategy: KlineBacktestStrategy
    equityByStrategy: Partial<Record<KlineBacktestStrategy | 'BENCHMARK', KlineBacktestEquityPoint[]>>
}

const COLORS: Record<KlineBacktestStrategy | 'BENCHMARK', string> = {
    A: '#3b82f6', B: '#14b8a6', C: '#8b5cf6', D: '#f97316', BENCHMARK: '#64748b',
}

function number(value: string | number | null | undefined): number {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : 0
}

export default function BacktestPerformanceCharts({ detail, selectedStrategy, equityByStrategy }: Props) {
    const strategies = Object.keys(detail.strategies) as KlineBacktestStrategy[]
    const dates = new Set<string>()
    Object.values(equityByStrategy).forEach(points => points?.forEach(point => dates.add(point.date)))
    const initialByKey = new Map<string, number>()
    const equityMaps = new Map<string, Map<string, KlineBacktestEquityPoint>>()
    Object.entries(equityByStrategy).forEach(([key, points]) => {
        const values = points ?? []
        initialByKey.set(key, number(values[0]?.total) || 1)
        equityMaps.set(key, new Map(values.map(point => [point.date, point])))
    })
    const equityData = [...dates].sort().map(date => {
        const row: Record<string, string | number> = { date }
        ;[...strategies, 'BENCHMARK' as const].forEach(key => {
            const point = equityMaps.get(key)?.get(date)
            if (point) row[key] = number(point.total) / (initialByKey.get(key) || 1) * 100
        })
        return row
    })
    const drawdownData = (equityByStrategy[selectedStrategy] ?? []).map(point => ({
        date: point.date,
        drawdown: number(point.drawdown) * 100,
    }))
    const metrics = detail.strategies[selectedStrategy]?.metrics ?? {}
    const costData = [
        { name: '佣金', value: number(metrics.commission), color: '#3b82f6' },
        { name: '印花税', value: number(metrics.stamp_tax), color: '#ef4444' },
        { name: '过户费', value: number(metrics.transfer_fee), color: '#8b5cf6' },
        { name: '滑点', value: number(metrics.slippage_cost), color: '#f59e0b' },
    ]
    const totalCost = number(metrics.total_cost)
    const totalCostRatio = number(metrics.total_cost_ratio) * 100

    return (
        <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
            <ChartCard title="策略净值与买入持有" subtitle="首日标准化为 100">
                <ResponsiveContainer width="100%" height={300}>
                    <LineChart data={equityData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" opacity={0.25} />
                        <XAxis dataKey="date" minTickGap={45} tick={{ fontSize: 11 }} />
                        <YAxis tick={{ fontSize: 11 }} width={52} />
                        <Tooltip formatter={(value: number) => value.toFixed(2)} />
                        <Legend />
                        {strategies.map(key => <Line key={key} type="monotone" dataKey={key} stroke={COLORS[key]} dot={false} strokeWidth={2} connectNulls />)}
                        <Line type="monotone" name="买入持有" dataKey="BENCHMARK" stroke={COLORS.BENCHMARK} dot={false} strokeDasharray="5 4" connectNulls />
                    </LineChart>
                </ResponsiveContainer>
            </ChartCard>

            <ChartCard title={`策略 ${selectedStrategy} 回撤`} subtitle="按历史峰值计算">
                <ResponsiveContainer width="100%" height={300}>
                    <LineChart data={drawdownData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" opacity={0.25} />
                        <XAxis dataKey="date" minTickGap={45} tick={{ fontSize: 11 }} />
                        <YAxis tick={{ fontSize: 11 }} width={52} unit="%" />
                        <Tooltip formatter={(value: number) => `${value.toFixed(2)}%`} />
                        <Line type="monotone" dataKey="drawdown" name="回撤" stroke="#ef4444" dot={false} strokeWidth={2} />
                    </LineChart>
                </ResponsiveContainer>
            </ChartCard>

            <ChartCard
                title={`策略 ${selectedStrategy} 成本构成`}
                subtitle={`总成本 ¥${totalCost.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} · 占初始资金 ${totalCostRatio.toFixed(2)}%`}
                className="2xl:col-span-2"
            >
                <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={costData} layout="vertical" margin={{ top: 8, right: 96, left: 8, bottom: 8 }} barCategoryGap="28%">
                        <CartesianGrid strokeDasharray="3 3" opacity={0.18} horizontal={false} />
                        <XAxis type="number" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={value => `¥${number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`} />
                        <YAxis type="category" dataKey="name" tick={{ fontSize: 12 }} width={58} axisLine={false} tickLine={false} />
                        <Tooltip formatter={(value: number) => `¥${value.toFixed(2)}`} />
                        <Bar dataKey="value" name="成本" barSize={28} radius={[0, 8, 8, 0]} background={{ fill: 'rgba(148, 163, 184, 0.08)', radius: 8 }}>
                            {costData.map(item => <Cell key={item.name} fill={item.color} />)}
                            <LabelList dataKey="value" position="right" fill="#94a3b8" fontSize={12} formatter={(value: number) => `¥${value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`} />
                        </Bar>
                    </BarChart>
                </ResponsiveContainer>
            </ChartCard>
        </div>
    )
}

function ChartCard({ title, subtitle, className = '', children }: { title: string; subtitle: string; className?: string; children: React.ReactNode }) {
    return (
        <section className={`card min-w-0 ${className}`}>
            <h3 className="font-semibold">{title}</h3>
            <p className="mb-3 mt-1 text-xs text-slate-500">{subtitle}</p>
            <div className="overflow-x-auto"><div className="h-full min-w-[600px]">{children}</div></div>
        </section>
    )
}

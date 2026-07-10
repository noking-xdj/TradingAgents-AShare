import { create } from 'zustand'

import { api } from '@/services/api'
import type {
    KlineBacktestCreateInput,
    KlineBacktestDetail,
    KlineBacktestEquityPoint,
    KlineBacktestRun,
    KlineBacktestSignal,
    KlineBacktestStrategy,
    KlineBacktestTrade,
    KlineCandle,
} from '@/types'

type EquityByStrategy = Partial<Record<KlineBacktestStrategy | 'BENCHMARK', KlineBacktestEquityPoint[]>>

interface KlineBacktestState {
    history: KlineBacktestRun[]
    selectedRunId: string | null
    selectedStrategy: KlineBacktestStrategy
    detail: KlineBacktestDetail | null
    trades: KlineBacktestTrade[]
    signals: KlineBacktestSignal[]
    equityByStrategy: EquityByStrategy
    candles: KlineCandle[]
    historyLoading: boolean
    detailLoading: boolean
    resultLoading: boolean
    submitting: boolean
    error: string | null
    loadHistory: (symbol: string) => Promise<void>
    selectRun: (runId: string) => Promise<void>
    refreshSelectedRun: () => Promise<KlineBacktestDetail | null>
    loadCompletedData: (run: KlineBacktestDetail, strategy?: KlineBacktestStrategy) => Promise<void>
    selectStrategy: (strategy: KlineBacktestStrategy) => Promise<void>
    submit: (input: KlineBacktestCreateInput) => Promise<string>
    deleteRun: (runId: string, symbol: string) => Promise<void>
    clear: () => void
}

async function collectPages<T>(
    loader: (offset: number, limit: number) => Promise<{ items: T[]; total: number }>,
    limit: number,
): Promise<T[]> {
    const items: T[] = []
    let offset = 0
    while (true) {
        const page = await loader(offset, limit)
        items.push(...page.items)
        offset += page.items.length
        if (offset >= page.total || page.items.length === 0) return items
    }
}

function messageOf(error: unknown): string {
    return error instanceof Error ? error.message : '回测请求失败'
}

export const useKlineBacktestStore = create<KlineBacktestState>((set, get) => ({
    history: [],
    selectedRunId: null,
    selectedStrategy: 'A',
    detail: null,
    trades: [],
    signals: [],
    equityByStrategy: {},
    candles: [],
    historyLoading: false,
    detailLoading: false,
    resultLoading: false,
    submitting: false,
    error: null,

    loadHistory: async (symbol) => {
        set({
            historyLoading: true,
            error: null,
            history: [],
            selectedRunId: null,
            detail: null,
            trades: [],
            signals: [],
            equityByStrategy: {},
            candles: [],
        })
        try {
            const page = await api.listKlineBacktests(symbol, 0, 50)
            const current = get().selectedRunId
            const nextId = current && page.items.some(run => run.run_id === current)
                ? current
                : page.items[0]?.run_id ?? null
            set({ history: page.items, selectedRunId: nextId, historyLoading: false })
            if (nextId) await get().selectRun(nextId)
            else set({ detail: null, trades: [], signals: [], equityByStrategy: {}, candles: [] })
        } catch (error) {
            set({ historyLoading: false, error: messageOf(error) })
        }
    },

    selectRun: async (runId) => {
        set({
            selectedRunId: runId,
            detailLoading: true,
            error: null,
            trades: [],
            signals: [],
            equityByStrategy: {},
            candles: [],
        })
        try {
            const detail = await api.getKlineBacktest(runId)
            if (get().selectedRunId !== runId) return
            const available = Object.keys(detail.strategies) as KlineBacktestStrategy[]
            const selectedStrategy = available.includes(get().selectedStrategy)
                ? get().selectedStrategy
                : available[0] ?? 'A'
            set({ detail, selectedStrategy, detailLoading: false })
            if (detail.status === 'completed') await get().loadCompletedData(detail, selectedStrategy)
        } catch (error) {
            if (get().selectedRunId === runId) set({ detailLoading: false, error: messageOf(error) })
        }
    },

    refreshSelectedRun: async () => {
        const runId = get().selectedRunId
        if (!runId) return null
        try {
            const detail = await api.getKlineBacktest(runId)
            if (get().selectedRunId !== runId) return null
            set(state => ({
                detail,
                history: state.history.map(run => run.run_id === runId ? { ...run, ...detail } : run),
                error: null,
            }))
            return detail
        } catch (error) {
            if (get().selectedRunId === runId) set({ error: messageOf(error) })
            return null
        }
    },

    loadCompletedData: async (run, strategy = get().selectedStrategy) => {
        const runId = run.run_id
        set({ resultLoading: true, error: null })
        try {
            const strategies = Object.keys(run.strategies) as KlineBacktestStrategy[]
            const [trades, signals, candlesResponse, benchmark, ...strategyEquity] = await Promise.all([
                collectPages((offset, limit) => api.getKlineBacktestTrades(runId, strategy, offset, limit), 1000),
                collectPages((offset, limit) => api.getKlineBacktestSignals(runId, strategy, offset, limit), 2000),
                api.getKline(run.symbol, run.start_date, run.end_date),
                collectPages((offset, limit) => api.getKlineBacktestEquity(runId, 'BENCHMARK', offset, limit), 2000),
                ...strategies.map(key => collectPages(
                    (offset, limit) => api.getKlineBacktestEquity(runId, key, offset, limit),
                    2000,
                )),
            ])
            if (get().selectedRunId !== runId || get().selectedStrategy !== strategy) return
            const equityByStrategy: EquityByStrategy = { BENCHMARK: benchmark }
            strategies.forEach((key, index) => { equityByStrategy[key] = strategyEquity[index] })
            set({
                trades,
                signals,
                candles: candlesResponse.candles,
                equityByStrategy,
                resultLoading: false,
            })
        } catch (error) {
            if (get().selectedRunId === runId) set({ resultLoading: false, error: messageOf(error) })
        }
    },

    selectStrategy: async (strategy) => {
        const run = get().detail
        set({ selectedStrategy: strategy, trades: [], signals: [] })
        if (!run || run.status !== 'completed') return
        set({ resultLoading: true, error: null })
        try {
            const [trades, signals] = await Promise.all([
                collectPages((offset, limit) => api.getKlineBacktestTrades(run.run_id, strategy, offset, limit), 1000),
                collectPages((offset, limit) => api.getKlineBacktestSignals(run.run_id, strategy, offset, limit), 2000),
            ])
            if (get().selectedRunId !== run.run_id || get().selectedStrategy !== strategy) return
            set({ trades, signals, resultLoading: false })
        } catch (error) {
            if (get().selectedStrategy === strategy) set({ resultLoading: false, error: messageOf(error) })
        }
    },

    submit: async (input) => {
        const active = get().history.some(run => run.status === 'pending' || run.status === 'running')
            || ['pending', 'running'].includes(get().detail?.status ?? '')
        if (active || get().submitting) throw new Error('已有回测任务正在运行，请等待完成')
        set({ submitting: true, error: null })
        try {
            const created = await api.createKlineBacktest(input)
            const detail = await api.getKlineBacktest(created.run_id)
            set(state => ({
                submitting: false,
                selectedRunId: created.run_id,
                detail,
                history: [detail, ...state.history.filter(run => run.run_id !== created.run_id)],
                trades: [],
                signals: [],
                equityByStrategy: {},
                candles: [],
            }))
            return created.run_id
        } catch (error) {
            set({ submitting: false, error: messageOf(error) })
            throw error
        }
    },

    deleteRun: async (runId, symbol) => {
        try {
            await api.deleteKlineBacktest(runId)
            if (get().selectedRunId === runId) set({ selectedRunId: null, detail: null })
            await get().loadHistory(symbol)
        } catch (error) {
            set({ error: messageOf(error) })
        }
    },

    clear: () => set({
        history: [],
        selectedRunId: null,
        detail: null,
        trades: [],
        signals: [],
        equityByStrategy: {},
        candles: [],
        error: null,
    }),
}))

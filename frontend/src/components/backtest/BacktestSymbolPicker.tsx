import { useEffect, useRef, useState } from 'react'
import { Loader2, RefreshCw, Search } from 'lucide-react'

import { api } from '@/services/api'
import type { StockSearchResult } from '@/types'
import { normalizeBacktestSymbol } from '@/utils/klineBacktest'

interface Props {
    selectedSymbol: string
    selectedName?: string
    analysisSymbol: string
    disabled: boolean
    onSelect: (symbol: string, name?: string) => void
}

export default function BacktestSymbolPicker({ selectedSymbol, selectedName, analysisSymbol, disabled, onSelect }: Props) {
    const [query, setQuery] = useState(selectedSymbol)
    const [results, setResults] = useState<StockSearchResult[]>([])
    const [searching, setSearching] = useState(false)
    const [open, setOpen] = useState(false)
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const requestRef = useRef(0)

    useEffect(() => () => {
        if (timerRef.current) clearTimeout(timerRef.current)
        requestRef.current += 1
    }, [])

    const select = (symbol: string, name?: string) => {
        if (timerRef.current) clearTimeout(timerRef.current)
        requestRef.current += 1
        setQuery(symbol)
        setResults([])
        setOpen(false)
        setSearching(false)
        onSelect(symbol, name)
    }

    const search = (raw: string) => {
        setQuery(raw)
        if (timerRef.current) clearTimeout(timerRef.current)
        const term = raw.trim()
        if (!term) {
            requestRef.current += 1
            setResults([])
            setOpen(false)
            setSearching(false)
            return
        }
        const requestId = requestRef.current + 1
        requestRef.current = requestId
        setSearching(true)
        timerRef.current = setTimeout(() => {
            void api.searchStocks(term)
                .then(response => {
                    if (requestRef.current !== requestId) return
                    setResults(response.results)
                    setOpen(response.results.length > 0)
                })
                .catch(() => {
                    if (requestRef.current === requestId) {
                        setResults([])
                        setOpen(false)
                    }
                })
                .finally(() => {
                    if (requestRef.current === requestId) setSearching(false)
                })
        }, 280)
    }

    const applyTypedSymbol = () => {
        const normalized = normalizeBacktestSymbol(query)
        if (normalized) select(normalized)
        else if (results.length === 1) select(results[0].symbol, results[0].name)
    }

    return (
        <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-700 dark:bg-slate-900/40">
            <div className="flex flex-wrap items-end gap-3">
                <div className="relative min-w-[280px] flex-1">
                    <label className="text-xs text-slate-500" htmlFor="backtest-symbol-search">回测标的</label>
                    <Search className="absolute bottom-2.5 left-3 h-4 w-4 text-slate-400" />
                    <input
                        id="backtest-symbol-search"
                        className="input mt-1 w-full pl-9 pr-9"
                        value={query}
                        disabled={disabled}
                        placeholder="输入股票代码或名称，例如 600519 / 贵州茅台"
                        onChange={event => search(event.target.value)}
                        onFocus={() => results.length > 0 && setOpen(true)}
                        onKeyDown={event => {
                            if (event.key === 'Enter') {
                                event.preventDefault()
                                applyTypedSymbol()
                            }
                            if (event.key === 'Escape') setOpen(false)
                        }}
                    />
                    {searching && <Loader2 className="absolute bottom-2.5 right-3 h-4 w-4 animate-spin text-slate-400" />}
                    {open && results.length > 0 && (
                        <div className="absolute z-30 mt-1 max-h-60 w-full overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-800">
                            {results.map(result => (
                                <button
                                    key={result.symbol}
                                    type="button"
                                    className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-slate-50 dark:hover:bg-slate-700/60"
                                    onClick={() => select(result.symbol, result.name)}
                                >
                                    <span className="font-medium">{result.name}</span>
                                    <span className="text-xs text-slate-400">{result.symbol}</span>
                                </button>
                            ))}
                        </div>
                    )}
                </div>
                <button
                    type="button"
                    className="btn-secondary flex items-center gap-1.5 whitespace-nowrap text-sm"
                    disabled={disabled || selectedSymbol === analysisSymbol}
                    onClick={() => select(analysisSymbol)}
                >
                    <RefreshCw size={14} /> 同步当前分析标的
                </button>
            </div>
            <p className="mt-2 text-xs text-slate-500">
                当前回测：{selectedName ? `${selectedName}（${selectedSymbol}）` : selectedSymbol}；切换只影响回测，不改变左侧对话与智能分析。
            </p>
        </div>
    )
}

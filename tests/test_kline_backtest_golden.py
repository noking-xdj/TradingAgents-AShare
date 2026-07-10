from __future__ import annotations

import json
import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

from api.services.kline_backtest.runner import run_backtest
from api.services.kline_backtest.schemas import BacktestConfig, primitive
from tests.kline_backtest_helpers import make_bars


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _metric_snapshot(metrics: dict) -> dict:
    keys = (
        "final_asset", "total_return", "gross_return", "max_drawdown",
        "completed_trades", "total_cost", "commission", "stamp_tax",
        "transfer_fee", "slippage_cost", "sharpe",
    )
    return primitive({key: metrics[key] for key in keys})


def _golden_output() -> dict:
    bars = make_bars([10, 9, 8, 7, 8, 9, 10, 11, 10, 9, 8, 9, 10, 11, 12, 11, 10, 9])
    config = BacktestConfig(
        start_date=bars[3].date,
        end_date=bars[-1].date,
        initial_cash=Decimal("10000"),
        short_ma=2,
        long_ma=3,
        pivot_left=1,
        pivot_right=1,
        pivot_min_separation=2,
        fib_window=20,
        trend_min_touches=3,
        stop_loss=None,
        take_profit=None,
    )
    result = run_backtest("600519.SH", bars, config)
    output = {
        "symbol": result.symbol,
        "data_hash": result.data_hash,
        "benchmark": {
            "actual_entry_date": primitive(result.benchmark.actual_entry_date),
            "metrics": _metric_snapshot(result.benchmark.metrics),
            "equity_points": len(result.benchmark.equity),
            "equity_sha256": _digest(primitive(result.benchmark.equity)),
        },
        "strategies": {},
    }
    for key, strategy in result.strategy_results.items():
        audit = [
            {
                "date": item.date.isoformat(),
                "buy": item.decision.buy,
                "sell": item.decision.sell,
                "conditions": item.decision.conditions,
                "ignored_reason": item.ignored_reason,
            }
            for item in strategy.audits
        ]
        output["strategies"][key] = {
            "metrics": _metric_snapshot(strategy.metrics),
            "signal_stats": primitive(strategy.signal_stats),
            "orders": primitive(strategy.orders),
            "equity_points": len(strategy.equity),
            "equity_sha256": _digest(primitive(strategy.equity)),
            "audit_points": len(audit),
            "audit_sha256": _digest(audit),
        }
    return output


def test_golden_file_matches_full_orders_and_hashed_equity_signal_audit():
    expected = json.loads((FIXTURE_DIR / "kline_backtest_expected.json").read_text(encoding="utf-8"))
    assert _golden_output() == expected


def test_full_year_without_valid_line_or_swing_returns_zero_trades_normally():
    bars = make_bars([Decimal("10") + Decimal(index) / Decimal("100") for index in range(252)])
    config = BacktestConfig(
        start_date=bars[0].date,
        end_date=bars[-1].date,
        short_ma=5,
        long_ma=20,
        stop_loss=None,
        take_profit=None,
    )
    result = run_backtest("510300.SH", bars, config, strategy_keys=("B", "C", "D"))
    for key, strategy in result.strategy_results.items():
        assert not [order for order in strategy.orders if order.side == "BUY" and order.outcome == "executed"]
        assert len(strategy.audits) == 252
        assert strategy.metrics["completed_trades"] == 0
    assert result.strategy_results["B"].signal_stats["condition_false_days"]["qualified_swing"] == 252
    assert result.strategy_results["C"].signal_stats["condition_false_days"]["valid_trendline"] == 252
    assert result.strategy_results["D"].signal_stats["condition_false_days"]["valid_trendline"] == 252


if __name__ == "__main__":
    print(json.dumps(_golden_output(), ensure_ascii=False, indent=2, sort_keys=True))

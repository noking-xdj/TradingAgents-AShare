"""Chinese exchange symbol, instrument and price-limit classification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .schemas import InstrumentType


@dataclass(frozen=True)
class InstrumentInfo:
    symbol: str
    code: str
    market: str
    instrument_type: InstrumentType
    board: str
    price_limit: Decimal


def normalize_symbol(raw: str) -> str:
    value = (raw or "").strip().upper()
    match = re.fullmatch(r"(?:SH|SZ|BJ)?(\d{6})(?:\.(SH|SZ|BJ|SS))?", value)
    if not match:
        raise ValueError(f"unsupported Chinese security symbol: {raw!r}")
    code, suffix = match.groups()
    if suffix == "SS":
        suffix = "SH"
    if suffix is None:
        if code.startswith(("4", "8", "92")):
            suffix = "BJ"
        elif code.startswith(("5", "6", "9")):
            suffix = "SH"
        else:
            suffix = "SZ"
    return f"{code}.{suffix}"


def _is_index(code: str, market: str) -> bool:
    return (
        (market == "SH" and code.startswith("000"))
        or (market == "SZ" and code.startswith("399"))
        or (market == "BJ" and code.startswith("899"))
    )


def _is_fund(code: str, market: str) -> bool:
    if market == "SH":
        return code.startswith("5")
    if market == "SZ":
        return code.startswith(("15", "16", "18"))
    return False


def classify_instrument(raw: str, override: str | None = None) -> InstrumentInfo:
    symbol = normalize_symbol(raw)
    code, market = symbol.split(".")
    inferred = InstrumentType.INDEX if _is_index(code, market) else (
        InstrumentType.FUND if _is_fund(code, market) else InstrumentType.STOCK
    )
    instrument_type = InstrumentType(override) if override else inferred
    if inferred is InstrumentType.INDEX or instrument_type is InstrumentType.INDEX:
        return InstrumentInfo(symbol, code, market, InstrumentType.INDEX, "index", ZERO_LIMIT)

    if market == "BJ":
        board, limit = "bse", Decimal("0.30")
    elif market == "SH" and code.startswith(("688", "689")):
        board, limit = "star", Decimal("0.20")
    elif market == "SZ" and code.startswith(("300", "301")):
        board, limit = "chinext", Decimal("0.20")
    else:
        board, limit = "main", Decimal("0.10")
    return InstrumentInfo(symbol, code, market, instrument_type, board, limit)


ZERO_LIMIT = Decimal("0")


def require_backtestable(raw: str, override: str | None = None) -> InstrumentInfo:
    info = classify_instrument(raw, override)
    if info.instrument_type is InstrumentType.INDEX:
        raise ValueError("首期暂不支持指数回测")
    return info

"""Models for per-symbol intraday trade-day charting."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class IntradayPoint:
    """One replay-granularity intraday point for a symbol."""

    time_raw: int
    price: float
    vwap: float


@dataclass(slots=True)
class TradeMarker:
    """One annotated marker on the intraday timeline."""

    kind: str
    time_raw: int
    price: float
    label: str


@dataclass(slots=True)
class SymbolTradeDay:
    """Full chart payload for one symbol on one replay day."""

    symbol: str
    points: list[IntradayPoint]
    markers: list[TradeMarker]

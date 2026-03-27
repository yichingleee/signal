"""Unit tests for traded-symbol intraday trace and marker builders."""

from __future__ import annotations

from collections.abc import Iterator

from tw_signal_engine.records.market_event_records import MarketTick, QuotePair, TradeRecord
from tw_signal_engine.reporting.build_trade_day_traces import build_trade_day_traces, build_trade_markers


def _tick(
    symbol: str,
    time_raw: int,
    price: int,
    qty: int,
    trade_code: int = 1,
) -> MarketTick:
    return MarketTick(
        symbol=symbol,
        match_time_str=time_raw,
        trade_code=trade_code,
        match=QuotePair(price=price, qty=qty),
    )


def _trade(
    symbol: str = "2330",
    entry_time: int = 91500000000,
    exit_time: int = 93000000000,
    entry_price: float = 50.0,
    exit_price: float = 51.0,
    signal_type: str = "SignalA",
    enter_cause: str = "StrongGroup",
    leave_cause: str = "takeProfit",
) -> TradeRecord:
    return TradeRecord(
        symbol=symbol,
        signal_type=signal_type,
        enter_cause=enter_cause,
        final_leave_cause=leave_cause,
        entry_time_raw=entry_time,
        exit_time_raw=exit_time,
        entry_price=entry_price,
        exit_price=exit_price,
    )


def test_build_trade_day_traces_empty_symbols_returns_empty() -> None:
    traces = build_trade_day_traces(
        trade_date="20260102",
        data_dir="./data/",
        traded_symbols=set(),
        prev_day_limit_up={},
    )
    assert traces == {}


def test_build_trade_day_traces_builds_price_and_vwap(monkeypatch) -> None:
    def _fake_stream(*_args, **_kwargs) -> Iterator[MarketTick]:
        yield _tick("2330", 91500000000, 100000, 10)
        yield _tick("2330", 92000000000, 120000, 30)
        yield _tick("2330", 92100000000, 0, 10)  # malformed price
        yield _tick("2330", 92200000000, 121000, 0)  # malformed qty
        yield _tick("2330", 92300000000, 119000, 5, trade_code=2)  # non-trade tick

    monkeypatch.setattr("tw_signal_engine.reporting.build_trade_day_traces.merge_market_streams", _fake_stream)

    traces = build_trade_day_traces(
        trade_date="20260102",
        data_dir="./data/",
        traded_symbols={"2330"},
        prev_day_limit_up={},
    )
    assert "2330" in traces
    points = traces["2330"]
    assert len(points) == 2
    assert points[0].price == 10.0
    assert points[0].vwap == 10.0
    assert points[1].price == 12.0
    assert abs(points[1].vwap - 11.5) < 1e-9
    assert [p.time_raw for p in points] == sorted(p.time_raw for p in points)


def test_build_trade_markers_creates_three_markers_per_trade_with_reason_text() -> None:
    markers = build_trade_markers(
        [
            _trade(
                signal_type="SignalB",
                enter_cause="StrongSingle",
                leave_cause="stopLoss",
            )
        ]
    )
    symbol_markers = markers["2330"]
    assert len(symbol_markers) == 3
    labels = [m.label for m in symbol_markers]
    assert any("Signal SignalB (StrongSingle)" in label for label in labels)
    assert any("Entry 50.00 (StrongSingle)" in label for label in labels)
    assert any("Exit 51.00 (stopLoss)" in label for label in labels)


def test_build_trade_markers_multiple_trades_same_symbol_are_deterministic() -> None:
    markers = build_trade_markers(
        [
            _trade(entry_time=93000000000, exit_time=94000000000, entry_price=60.0, exit_price=61.0),
            _trade(entry_time=91500000000, exit_time=92500000000, entry_price=50.0, exit_price=52.0),
        ]
    )
    symbol_markers = markers["2330"]
    assert len(symbol_markers) == 6
    assert [m.kind for m in symbol_markers[:2]] == ["signal", "entry"]
    assert symbol_markers[0].time_raw == 91500000000
    assert symbol_markers[-1].time_raw == 94000000000


def test_build_trade_markers_multi_symbol_split() -> None:
    markers = build_trade_markers(
        [
            _trade(symbol="2330"),
            _trade(symbol="2317"),
        ]
    )
    assert set(markers.keys()) == {"2330", "2317"}
    assert len(markers["2330"]) == 3
    assert len(markers["2317"]) == 3


def test_build_trade_markers_empty_input_returns_empty() -> None:
    assert build_trade_markers([]) == {}

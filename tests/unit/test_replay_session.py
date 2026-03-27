"""Tests for replay-session lifecycle helpers."""

from __future__ import annotations

from tw_signal_engine.config.strategy_config import ExecutionConfig, NormalizedStrategyConfig
from tw_signal_engine.records.trade_records import EntryTrade
from tw_signal_engine.replay.replay_session import _finalize_open_positions
from tw_signal_engine.replay.session_time import fmt_time
from tw_signal_engine.state.position_state import PositionState
from tw_signal_engine.state.symbol_state import IndexData


class _LogWriterStub:
    def __init__(self) -> None:
        self.leave_rows: list[tuple[str, str]] = []

    def write_leave(
        self,
        symbol: str,
        match_time_str: int,
        price: int,
        cash: float,
        symbol_cash: float,
        cause: str,
        qty: float,
    ) -> None:
        self.leave_rows.append((symbol, cause))


def _make_pos(entry_time: int = 90000000000) -> PositionState:
    return PositionState(
        stocks={"2330": 10.0},
        symbol_cash={"2330": -100.0},
        orders={"2330": []},
        reserve_stocks={"2330": 0.0},
        profit_taken={"2330": False},
        open_trades={
            "2330": EntryTrade(
                symbol="2330",
                signal_type="SignalA",
                enter_cause="StrongGroup",
                entry_time_raw=entry_time,
                baseline=0.0,
            )
        },
    )


def test_finalize_open_positions_records_trade_and_clears_position() -> None:
    config = NormalizedStrategyConfig(execution=ExecutionConfig(position_cash=100.0))
    pos = _make_pos()
    completed_trades = []
    log_writer = _LogWriterStub()

    _finalize_open_positions(
        config,
        pos,
        {"2330": 110000},
        {"2330": "SignalA"},
        {"2330": IndexData()},
        completed_trades,
        log_writer,
        132500000000,
    )

    assert pos.stocks["2330"] == 0
    assert len(completed_trades) == 1
    assert completed_trades[0].final_leave_cause == "timeExit"
    assert completed_trades[0].pnl == 10.0
    assert completed_trades[0].exit_price == 11.0
    assert log_writer.leave_rows == [("2330", "timeExit")]


def test_finalize_exit_time_uses_last_match_time() -> None:
    """Regression: exit_time_raw must be a real timestamp, not sys.maxsize."""
    config = NormalizedStrategyConfig(execution=ExecutionConfig(position_cash=100.0))
    pos = _make_pos()
    completed_trades = []
    log_writer = _LogWriterStub()

    exit_time = 132500000000  # 13:25:00 — at exit_time_limit

    _finalize_open_positions(
        config,
        pos,
        {"2330": 110000},
        {"2330": "SignalA"},
        {"2330": IndexData()},
        completed_trades,
        log_writer,
        exit_time,
    )

    assert completed_trades[0].exit_time_raw == exit_time
    assert completed_trades[0].exit_price == 11.0
    assert fmt_time(exit_time) == "13:25:00"

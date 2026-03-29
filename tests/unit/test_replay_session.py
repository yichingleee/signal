"""Tests for replay-session lifecycle helpers."""

from __future__ import annotations

from tw_signal_engine.config.strategy_config import ExecutionConfig, NormalizedStrategyConfig
from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.records.trade_records import EntryTrade
from tw_signal_engine.replay.replay_session import _finalize_open_positions, build_dashboard_snapshot
from tw_signal_engine.replay.session_time import fmt_time
from tw_signal_engine.screening.evaluate_strong_group import MatchInfo
from tw_signal_engine.state.position_state import PositionState
from tw_signal_engine.state.signal_state import SignalAState
from tw_signal_engine.state.symbol_state import IndexCalc, IndexData


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
    assert fmt_time(exit_time) == "13:25:00"


class _StrongGroupStub:
    def __init__(self) -> None:
        self.last_match_info = {
            "2330": MatchInfo(group_name="半導體", group_rank=1, member_rank=1, raw_member_rank=1),
        }

    def to_snapshot(self, idx_map: dict[str, IndexData]) -> list[object]:
        return []


class _StrongSingleStub:
    class _Cfg:
        enabled = True

    config = _Cfg()

    def to_snapshot(
        self,
        idx_map: dict[str, IndexData],
        last_price: dict[str, int],
        symbol_to_group: dict[str, str] | None = None,
    ) -> list[object]:
        return []


def test_build_dashboard_snapshot_uses_actual_price_scales_and_normalized_exit_causes() -> None:
    strong_group = _StrongGroupStub()
    strong_single = _StrongSingleStub()

    pos = PositionState(
        stocks={"2330": 10.0},
        open_trades={
            "2330": EntryTrade(
                symbol="2330",
                signal_type="SignalA",
                enter_cause="StrongGroup",
                entry_time_raw=93100000000,
                entry_price=100.0,
                entry_vwap=99.5,
                day_high_at_entry=101.0,
                group_name="半導體",
                group_rank=1,
            )
        },
    )

    completed = [
        TradeRecord(
            symbol="2317",
            signal_type="SignalA",
            final_leave_cause="takeProfit",
            entry_price=120.0,
            return_pct=2.5,
            entry_time_raw=93000000000,
            exit_time_raw=100000000000,
            group_name="電子",
            group_rank=2,
        )
    ]

    idx_calc = IndexCalc()
    idx_calc.calc(1020000, 10)
    snapshot = build_dashboard_snapshot(
        match_time_str=100000000000,
        tick_count=123,
        strong_group=strong_group,  # type: ignore[arg-type]
        strong_single=strong_single,  # type: ignore[arg-type]
        signal_a_map={"2330": SignalAState(symbol="2330", near_vwap=True)},
        pos=pos,
        completed_trades=completed,
        index_calc_map={"2330": idx_calc},
        f1_map={},
        exec_config=ExecutionConfig(stop_loss_ratio_a=0.99, take_profit_pcts=[0.03]),
        last_price={"2330": 1020000},
        monitored_symbols={"2330", "2317"},
    )

    assert snapshot.signal_a.entered[0].entry_price == 100.0
    assert snapshot.signal_a.entered[0].current_price == 102.0
    assert round(snapshot.signal_a.entered[0].pnl_pct, 4) == 0.02
    assert snapshot.signal_a.exited[0].exit_cause == "take_profit"
    assert round(snapshot.signal_a.exited[0].pnl_pct, 4) == 0.025

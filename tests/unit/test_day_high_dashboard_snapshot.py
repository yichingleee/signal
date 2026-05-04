"""Focused tests for DayHigh dashboard explainability snapshot contract."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from tw_signal_engine.config.strategy_config import NormalizedStrategyConfig
from tw_signal_engine.market_data.history_window import HistoryWindow
from tw_signal_engine.records.market_event_records import MarketTick, QuotePair, TradeRecord
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.records.trade_records import EntryTrade
from tw_signal_engine.replay.replay_session import _build_dashboard_snapshot, run_daily_replay
from tw_signal_engine.screening.evaluate_strong_group import MatchInfo
from tw_signal_engine.server.dashboard_snapshot import (
    SignalDayHighEntryRow,
    SignalDayHighMonitorSnapshot,
    SignalDayHighSelectionRow,
)
from tw_signal_engine.state.position_state import PositionState
from tw_signal_engine.state.signal_state import SignalDayHighState
from tw_signal_engine.state.symbol_state import IndexData


def _ref(symbol: str) -> ReferenceSymbol:
    return ReferenceSymbol(
        symbol=symbol,
        name=symbol,
        market="TSE",
        previous_close=100.0,
        limit_up_price=110.0,
        limit_down_price=90.0,
        industry="",
        security="",
        error_code="0",
    )


class _StrongSingleStub:
    def to_snapshot(self, idx_map, last_price, symbol_to_group):  # noqa: ANN001
        return []


class _StrongGroupSnapshotStub:
    def __init__(self, selected: bool = False, reason: str = "group_rank") -> None:
        self.last_match_info: dict[str, MatchInfo] = {}
        self._selected = selected
        self._reason = reason

    def to_snapshot(self, idx_map):  # noqa: ANN001
        return []

    def get_group_limit_up_count(self, group: str) -> int:
        return 0

    def explain_day_high_selection(
        self,
        symbol: str,
        idx: IndexData | None,
        price_raw: int,
    ) -> SignalDayHighSelectionRow:
        return SignalDayHighSelectionRow(
            symbol=symbol,
            name=symbol,
            group_name="G1",
            selected=self._selected,
            rejection_reason="" if self._selected else self._reason,
            group_rank=1 if self._selected else 0,
            member_rank=1 if self._selected else 0,
            raw_member_rank=1 if self._selected else 0,
            current_price=price_raw / 10000 if price_raw > 0 else 0.0,
            vwap=(idx.vwap / 10000 if idx is not None and idx.vwap > 0 else 0.0),
            pass_group_rank=self._selected,
            pass_member_rank=self._selected,
            pass_raw_rank=self._selected,
            pass_vwap_band=self._selected,
            pass_disposition_block=True,
            pass_prev_day_limit_up=True,
        )


def _build_base_snapshot(
    *,
    config: NormalizedStrategyConfig | None = None,
    match_time_str: int = 93100000000,
    signal_day_high_map: dict[str, SignalDayHighState] | None = None,
    day_high_entry_logic: dict[str, SignalDayHighEntryRow] | None = None,
    pos: PositionState | None = None,
    completed_trades: list[TradeRecord] | None = None,
    day_high_limit_up_locked: dict[str, bool] | None = None,
    strong_group: _StrongGroupSnapshotStub | None = None,
) -> SignalDayHighMonitorSnapshot:
    cfg = config or NormalizedStrategyConfig()
    snapshot = _build_dashboard_snapshot(
        config=cfg,
        match_time_str=match_time_str,
        tick_count=1,
        strong_group=strong_group or _StrongGroupSnapshotStub(),
        strong_single=_StrongSingleStub(),
        symbol_to_groups={"2330": ["G1"]},
        f1_map={"2330": _ref("2330")},
        latest_idx_map={"2330": IndexData(vwap=1_045_000.0, day_high=1_060_000, day_low=1_040_000)},
        last_price={"2330": 1_049_000},
        signal_a_map={},
        signal_a_short_map={},
        signal_b_map={},
        signal_day_high_map=signal_day_high_map or {},
        day_high_entry_logic=day_high_entry_logic or {},
        day_high_limit_up_locked=day_high_limit_up_locked or {},
        pos=pos or PositionState(),
        completed_trades=completed_trades or [],
        trade_mode="long",
    )
    return snapshot.signal_day_high


def test_day_high_dashboard_hides_tracked_but_not_selected_symbol() -> None:
    state = SignalDayHighState(symbol="2330", established_high=1_060_000, established_high_time=93000000000)
    day_high = _build_base_snapshot(
        signal_day_high_map={"2330": state},
        strong_group=_StrongGroupSnapshotStub(selected=False),
    )

    assert day_high.rows == []
    assert day_high.preparing == []
    assert day_high.logic.selection_rows == []


def test_open_position_exposes_real_day_high_exit_policy_values() -> None:
    cfg = NormalizedStrategyConfig()
    cfg.execution.exit_time_limit = 132000000000
    cfg.execution.stop_loss_ratio_day_high = 0.99
    cfg.execution.hold_overnight_on_limit_up = True

    pos = PositionState(
        stocks={"2330": 1000.0},
        open_trades={
            "2330": EntryTrade(
                symbol="2330",
                signal_type="SignalDayHigh",
                enter_cause="StrongGroup",
                side="long",
                entry_time_raw=93000000000,
                entry_price=106.0,
                entry_vwap=105.0,
                day_high_at_entry=106.0,
                entry_qty=1000.0,
            )
        },
    )

    day_high = _build_base_snapshot(config=cfg, pos=pos, day_high_limit_up_locked={"2330": True})
    assert len(day_high.entered) == 1
    assert day_high.entered[0].stop_loss == pytest.approx(103.95)
    assert day_high.entered[0].take_profit == 0.0

    exit_rows = [row for row in day_high.logic.exit_rows if row.symbol == "2330" and row.status == "open"]
    assert len(exit_rows) == 1
    exit_row = exit_rows[0]
    assert exit_row.stop_basis == "entry_vwap"
    assert exit_row.stop_price == pytest.approx(103.95)
    assert exit_row.time_exit_deadline == "13:20:00"
    assert exit_row.hold_overnight_on_limit_up is True
    assert exit_row.currently_limit_up_locked is True
    assert exit_row.overnight_eligible_now is False

    after_deadline = _build_base_snapshot(
        config=cfg,
        match_time_str=132000000000,
        pos=pos,
        day_high_limit_up_locked={"2330": True},
    )
    after_deadline_rows = [
        row for row in after_deadline.logic.exit_rows if row.symbol == "2330" and row.status == "open"
    ]
    assert len(after_deadline_rows) == 1
    assert after_deadline_rows[0].currently_limit_up_locked is True
    assert after_deadline_rows[0].overnight_eligible_now is True


def test_closed_trade_exposes_overnight_exit_cause_in_logic_exit_rows() -> None:
    completed = [
        TradeRecord(
            symbol="2330",
            signal_type="SignalDayHigh",
            side="long",
            group_name="G1",
            entry_price=106.0,
            exit_price=109.0,
            entry_vwap=105.5,
            entry_time_raw=93000000000,
            exit_time_raw=90000000000,
            return_pct=2.83,
            final_leave_cause="overnightExit",
        )
    ]
    day_high = _build_base_snapshot(completed_trades=completed)
    closed_rows = [row for row in day_high.logic.exit_rows if row.status == "closed" and row.symbol == "2330"]
    assert len(closed_rows) == 1
    assert closed_rows[0].final_leave_cause == "overnightExit"


def test_block_reason_exposed_for_day_high_group_limit_up_block(monkeypatch: pytest.MonkeyPatch) -> None:
    from tw_signal_engine.replay import replay_session as rs

    class _StrongGroupStub:
        def __init__(self, *args, **kwargs) -> None:
            self.symbol_is_valid = {"2330": True}
            self.last_match_info: dict[str, MatchInfo] = {}
            self._ticks = 0

        def initialize_validity(self) -> None:
            return None

        def on_tick(self, idx, symbol, price, qty, match_time_us, match_time_str, is_limit_up_locked) -> bool:  # noqa: ANN001
            self._ticks += 1
            self.last_match_info[symbol] = MatchInfo(
                group_name="G1",
                group_rank=1,
                member_rank=1,
                raw_member_rank=1,
                m1_symbol=symbol,
            )
            return True

        def is_single_allowed(self, symbol: str, max_rank: int) -> bool:
            return True

        def get_group_limit_up_count(self, group: str) -> int:
            return 2

        def to_snapshot(self, idx_map):  # noqa: ANN001
            return []

        def explain_day_high_selection(
            self,
            symbol: str,
            idx: IndexData | None,
            price_raw: int,
        ) -> SignalDayHighSelectionRow:
            return SignalDayHighSelectionRow(symbol=symbol, name=symbol, group_name="G1")

    class _Provider:
        def __init__(self, ticks: list[MarketTick]) -> None:
            self._ticks = ticks

        def iterate_ticks(self):
            yield from self._ticks

    class _LogWriter:
        def __init__(self, log_dir: str, date: str) -> None:
            self.log_dir = log_dir
            self.date = date

        def write_entry(self, *args, **kwargs) -> None:
            return None

        def write_leave(self, *args, **kwargs) -> None:
            return None

        def close(self) -> None:
            return None

    def _tick(symbol: str, time_str: int, price: int) -> MarketTick:
        tick = MarketTick(symbol=symbol, market="TSE", match_time_str=time_str, match_time_us=time_str // 1000)
        tick.trade_code = 1
        tick.status_code = 0
        tick.match = QuotePair(price=price, qty=100)
        tick.bid[0].price = price - 1000
        tick.ask[0].price = price + 1000
        return tick

    snapshots: list[object] = []
    monkeypatch.setattr(rs, "load_legacy_ini", lambda _: {})
    cfg = NormalizedStrategyConfig()
    cfg.signal_day_high.enabled = True
    cfg.signal_day_high.max_group_limit_up_count = 2
    cfg.strong_group.enabled = True
    cfg.signal_a.enabled = False
    cfg.signal_a_short.enabled = False
    cfg.signal_b.enabled = False
    monkeypatch.setattr(rs, "normalize_strategy_config", lambda _: cfg)
    monkeypatch.setattr(rs, "StrongGroupEvaluator", _StrongGroupStub)
    monkeypatch.setattr(rs, "load_symbol_reference", lambda *_: {"2330": _ref("2330"), "0050": _ref("0050")})
    monkeypatch.setattr(rs, "derive_prev_day_limit_up", lambda *_: {})
    monkeypatch.setattr(rs, "load_group_membership", lambda *_: ([], {"2330": ["G1"]}, {"G1": {"2330"}}))
    monkeypatch.setattr(rs, "OrderLogWriter", _LogWriter)
    monkeypatch.setattr(rs, "_generate_reports", lambda *args, **kwargs: None)

    provider = _Provider(
        [
            _tick("2330", 93000000000, 1_060_000),
            _tick("2330", 93100000000, 1_040_000),
            _tick("2330", 93200000000, 1_061_000),
        ]
    )
    run_daily_replay(
        trade_date="20260129",
        history=HistoryWindow(vol_cum=[], trading_val=[], source_dates=[]),
        provider=provider,
        no_charts=True,
        on_dashboard_snapshot=lambda snapshot: snapshots.append(snapshot),
    )

    assert snapshots, "expected replay snapshots to be emitted"
    last_snapshot = snapshots[-1].signal_day_high
    rows = [row for row in last_snapshot.logic.entry_rows if row.symbol == "2330"]
    assert rows
    assert rows[-1].block_reason == "day_high_group_limit_up_count"
    assert rows[-1].day_high_group_limit_up_passed is False


def test_default_day_high_logic_shape_is_backward_compatible() -> None:
    payload = asdict(SignalDayHighMonitorSnapshot())
    logic = payload["logic"]
    assert logic["selection_rows"] == []
    assert logic["entry_rows"] == []
    assert logic["exit_rows"] == []
    assert logic["funnel"]["block_reasons"] == {}

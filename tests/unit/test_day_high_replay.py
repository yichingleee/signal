"""Replay integration tests for SignalDayHigh flow."""

from __future__ import annotations

import pytest

from tw_signal_engine.config.strategy_config import NormalizedStrategyConfig
from tw_signal_engine.market_data.history_window import HistoryWindow
from tw_signal_engine.records.market_event_records import MarketTick, QuotePair
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.replay.replay_session import run_daily_replay
from tw_signal_engine.screening.evaluate_strong_group import MatchInfo


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


def _tick(symbol: str, time_str: int, price: int) -> MarketTick:
    tick = MarketTick(symbol=symbol, market="TSE", match_time_str=time_str, match_time_us=time_str // 1000)
    tick.trade_code = 1
    tick.status_code = 0
    tick.match = QuotePair(price=price, qty=100)
    tick.bid[0].price = price - 1000
    tick.ask[0].price = price + 1000
    return tick


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


def test_day_high_tracks_pattern_before_group_eligibility_and_triggers_on_group_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tw_signal_engine.replay import replay_session as rs

    class _StrongGroupStub:
        def __init__(self, *args, **kwargs) -> None:
            self.symbol_is_valid = {"2330": True}
            self.last_match_info: dict[str, MatchInfo] = {}
            self._ticks = 0

        def initialize_validity(self) -> None:
            return None

        def on_tick(self, idx, symbol, price, qty, match_time_us, match_time_str, is_limit_up_locked) -> bool:
            self._ticks += 1
            if self._ticks == 5:
                self.last_match_info[symbol] = MatchInfo(
                    group_name="G1",
                    group_rank=1,
                    member_rank=1,
                    raw_member_rank=1,
                    m1_symbol=symbol,
                )
                return True
            return False

        def is_single_allowed(self, symbol: str, max_rank: int) -> bool:
            return True

        def get_group_limit_up_count(self, group: str) -> int:
            return 0

        def to_snapshot(self, idx_map):
            return []

    entries: list[tuple[str, str]] = []

    def _execute_entry(*args, **kwargs) -> None:
        entries.append((args[5], args[4]))

    monkeypatch.setattr(rs, "load_legacy_ini", lambda _: {})
    cfg = NormalizedStrategyConfig()
    cfg.signal_day_high.enabled = True
    cfg.strong_group.enabled = True
    cfg.signal_a.enabled = False
    cfg.signal_a_short.enabled = False
    cfg.signal_b.enabled = False
    cfg.execution.entry_time_limit = 130000000000
    cfg.execution.exit_time_limit = 132000000000
    monkeypatch.setattr(rs, "normalize_strategy_config", lambda _: cfg)
    monkeypatch.setattr(rs, "StrongGroupEvaluator", _StrongGroupStub)
    monkeypatch.setattr(rs, "load_symbol_reference", lambda *_: {"2330": _ref("2330"), "0050": _ref("0050")})
    monkeypatch.setattr(rs, "derive_prev_day_limit_up", lambda *_: {})
    monkeypatch.setattr(rs, "load_group_membership", lambda *_: ([], {"2330": ["G1"]}, {"G1": {"2330"}}))
    monkeypatch.setattr(rs, "OrderLogWriter", _LogWriter)
    monkeypatch.setattr(rs, "_generate_reports", lambda *args, **kwargs: None)
    monkeypatch.setattr(rs, "should_enter", lambda *args, **kwargs: (True, None))
    monkeypatch.setattr(rs, "execute_entry", _execute_entry)

    provider = _Provider(
        [
            _tick("2330", 93000000000, 1_060_000),  # establish high
            _tick("2330", 93100000000, 1_040_000),  # pullback
            _tick("2330", 93200000000, 1_061_000),  # breakout while not group-qualified
            _tick("2330", 93300000000, 1_050_000),  # pullback again
            _tick("2330", 93400000000, 1_062_000),  # breakout + strong group => entry
        ]
    )
    trades = run_daily_replay(
        trade_date="20260129",
        history=HistoryWindow(vol_cum=[], trading_val=[], source_dates=[]),
        provider=provider,
        no_charts=True,
    )

    assert trades == []
    assert entries == [("SignalDayHigh", "StrongGroup")]


def test_day_high_snapshot_exposes_tracking_pullback_holding_phases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tw_signal_engine.replay import replay_session as rs

    class _StrongGroupStub:
        def __init__(self, *args, **kwargs) -> None:
            self.symbol_is_valid = {"2330": True}
            self.last_match_info: dict[str, MatchInfo] = {}

        def initialize_validity(self) -> None:
            return None

        def on_tick(self, idx, symbol, price, qty, match_time_us, match_time_str, is_limit_up_locked) -> bool:
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
            return 0

        def to_snapshot(self, idx_map):
            return []

    snapshots: list[object] = []

    def _capture(snapshot) -> None:
        snapshots.append(snapshot)

    monkeypatch.setattr(rs, "load_legacy_ini", lambda _: {})
    cfg = NormalizedStrategyConfig()
    cfg.signal_day_high.enabled = True
    cfg.strong_group.enabled = True
    cfg.signal_a.enabled = False
    cfg.signal_a_short.enabled = False
    cfg.signal_b.enabled = False
    cfg.signal_day_high.entry_start_time = 90000000000
    cfg.signal_day_high.entry_end_time = 150000000000
    cfg.execution.exit_time_limit = 132000000000
    monkeypatch.setattr(rs, "normalize_strategy_config", lambda _: cfg)
    monkeypatch.setattr(rs, "StrongGroupEvaluator", _StrongGroupStub)
    monkeypatch.setattr(rs, "load_symbol_reference", lambda *_: {"2330": _ref("2330"), "0050": _ref("0050")})
    monkeypatch.setattr(rs, "derive_prev_day_limit_up", lambda *_: {})
    monkeypatch.setattr(rs, "load_group_membership", lambda *_: ([], {"2330": ["G1"]}, {"G1": {"2330"}}))
    monkeypatch.setattr(rs, "OrderLogWriter", _LogWriter)
    monkeypatch.setattr(rs, "_generate_reports", lambda *args, **kwargs: None)
    monkeypatch.setattr(rs, "should_enter", lambda *args, **kwargs: (True, None))

    provider = _Provider(
        [
            _tick("2330", 93000000000, 1_060_000),  # establish high (tracking)
            _tick("2330", 93100000000, 1_049_000),  # pullback
            _tick("2330", 93200000000, 1_061_000),  # breakout + hold
        ]
    )
    run_daily_replay(
        trade_date="20260129",
        history=HistoryWindow(vol_cum=[], trading_val=[], source_dates=[]),
        provider=provider,
        no_charts=True,
        on_dashboard_snapshot=_capture,
    )

    assert len(snapshots) >= 3
    snapshot_tracking = snapshots[0]
    snapshot_pullback = snapshots[1]
    snapshot_holding = snapshots[2]

    tracking_rows = [row for row in snapshot_tracking.signal_day_high.rows if row.symbol == "2330"]
    pullback_rows = [row for row in snapshot_pullback.signal_day_high.rows if row.symbol == "2330"]
    holding_rows = [row for row in snapshot_holding.signal_day_high.rows if row.symbol == "2330"]

    assert len(tracking_rows) == 1
    assert tracking_rows[0].phase == "tracking"
    assert snapshot_tracking.signal_day_high.phase_counts.tracking == 1

    assert len(pullback_rows) == 1
    assert pullback_rows[0].phase == "pullback"
    assert pullback_rows[0].pullback_low == 1_049_000 / 10000
    assert snapshot_pullback.signal_day_high.phase_counts.pullback == 1

    assert len(holding_rows) == 1
    holding = holding_rows[0]
    assert holding.phase == "holding"
    assert holding.last_trigger_high == 1_060_000 / 10000
    assert holding.last_trigger_pullback_low == 1_049_000 / 10000
    assert snapshot_holding.signal_day_high.phase_counts.holding == 1
    assert snapshot_holding.signal_day_high.phase_counts.triggered == 0


def test_day_high_group_limit_up_count_blocks_entry_before_should_enter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tw_signal_engine.replay import replay_session as rs

    class _StrongGroupStub:
        def __init__(self, *args, **kwargs) -> None:
            self.symbol_is_valid = {"2330": True}
            self.last_match_info: dict[str, MatchInfo] = {}
            self._ticks = 0

        def initialize_validity(self) -> None:
            return None

        def on_tick(self, idx, symbol, price, qty, match_time_us, match_time_str, is_limit_up_locked) -> bool:
            self._ticks += 1
            if self._ticks >= 3:
                self.last_match_info[symbol] = MatchInfo(
                    group_name="G1",
                    group_rank=1,
                    member_rank=1,
                    raw_member_rank=1,
                    m1_symbol=symbol,
                )
                return True
            return False

        def is_single_allowed(self, symbol: str, max_rank: int) -> bool:
            return True

        def get_group_limit_up_count(self, group: str) -> int:
            return 2

        def to_snapshot(self, idx_map):
            return []

    should_enter_calls = {"n": 0}
    entry_calls = {"n": 0}

    def _should_enter(*args, **kwargs):
        should_enter_calls["n"] += 1
        return True, None

    def _execute_entry(*args, **kwargs):
        entry_calls["n"] += 1

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
    monkeypatch.setattr(rs, "should_enter", _should_enter)
    monkeypatch.setattr(rs, "execute_entry", _execute_entry)

    provider = _Provider(
        [
            _tick("2330", 93000000000, 1_060_000),
            _tick("2330", 93100000000, 1_040_000),
            _tick("2330", 93200000000, 1_061_000),
        ]
    )
    trades = run_daily_replay(
        trade_date="20260129",
        history=HistoryWindow(vol_cum=[], trading_val=[], source_dates=[]),
        provider=provider,
        no_charts=True,
    )

    assert trades == []
    assert should_enter_calls["n"] == 0
    assert entry_calls["n"] == 0

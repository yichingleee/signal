"""Overnight carry tests for SignalDayHigh replay."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tw_signal_engine.config.strategy_config import NormalizedStrategyConfig
from tw_signal_engine.market_data.history_window import HistoryWindow
from tw_signal_engine.records.market_event_records import MarketTick, QuotePair
from tw_signal_engine.records.overnight_records import OvernightHolding
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.records.trade_records import EntryTrade
from tw_signal_engine.replay.replay_session import DAYHIGH_OVERNIGHT_MAP_WARNING, run_daily_replay
from tw_signal_engine.screening.evaluate_strong_group import MatchInfo
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


def _tick(
    symbol: str,
    time_str: int,
    price: int,
    ask_price: int | None = None,
    bid_price: int | None = None,
) -> MarketTick:
    tick = MarketTick(symbol=symbol, market="TSE", match_time_str=time_str, match_time_us=time_str // 1000)
    tick.trade_code = 1
    tick.status_code = 0
    tick.match = QuotePair(price=price, qty=100)
    tick.bid[0].price = price if bid_price is None else bid_price
    tick.ask[0].price = price if ask_price is None else ask_price
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


@dataclass
class _StrongGroupStub:
    symbol_is_valid: dict[str, bool]
    last_match_info: dict[str, MatchInfo]

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


def _patch_common_dayhigh(monkeypatch: pytest.MonkeyPatch, rs) -> NormalizedStrategyConfig:
    monkeypatch.setattr(rs, "load_legacy_ini", lambda _: {})
    cfg = NormalizedStrategyConfig()
    cfg.signal_day_high.enabled = True
    cfg.signal_a.enabled = False
    cfg.signal_a_short.enabled = False
    cfg.signal_b.enabled = False
    cfg.strong_group.enabled = True
    cfg.execution.hold_overnight_on_limit_up = True
    cfg.execution.exit_time_limit = 132000000000
    cfg.execution.day_trade_tax_rate = 0.0015
    cfg.execution.overnight_tax_rate = 0.003
    monkeypatch.setattr(rs, "normalize_strategy_config", lambda _: cfg)
    monkeypatch.setattr(rs, "StrongGroupEvaluator", lambda *args, **kwargs: _StrongGroupStub({"2330": True}, {}))
    monkeypatch.setattr(rs, "load_symbol_reference", lambda *_: {"2330": _ref("2330"), "0050": _ref("0050")})
    monkeypatch.setattr(rs, "derive_prev_day_limit_up", lambda *_: {})
    monkeypatch.setattr(rs, "load_group_membership", lambda *_: ([], {"2330": ["G1"]}, {"G1": {"2330"}}))
    monkeypatch.setattr(rs, "OrderLogWriter", _LogWriter)
    monkeypatch.setattr(rs, "_generate_reports", lambda *args, **kwargs: None)
    monkeypatch.setattr(rs, "should_enter", lambda *args, **kwargs: (True, None))
    return cfg


def test_hold_transfer_at_1320_and_no_duplicate_close_same_day(monkeypatch: pytest.MonkeyPatch) -> None:
    from tw_signal_engine.replay import replay_session as rs

    _patch_common_dayhigh(monkeypatch, rs)

    call_count = {"n": 0}

    def _trigger_once(*args, **kwargs):
        call_count["n"] += 1
        return (call_count["n"] == 1, "StrongGroup" if call_count["n"] == 1 else "None")

    monkeypatch.setattr(rs, "evaluate_signal_day_high", _trigger_once)

    overnight: dict[str, OvernightHolding] = {}
    provider = _Provider(
        [
            _tick("2330", 93000000000, 1_060_000, ask_price=1_060_500, bid_price=1_059_500),
            _tick("2330", 132000000000, 1_100_000, ask_price=0, bid_price=1_100_000),
            _tick("2330", 132100000000, 1_100_000, ask_price=0, bid_price=1_100_000),
        ]
    )

    trades = run_daily_replay(
        trade_date="20260129",
        history=HistoryWindow(vol_cum=[], trading_val=[], source_dates=[]),
        provider=provider,
        overnight_holdings=overnight,
        no_charts=True,
    )

    assert trades == []
    assert "2330" in overnight
    assert overnight["2330"].carry_from_date == "20260129"


def test_next_day_first_trade_exits_overnight_with_overnight_tax(monkeypatch: pytest.MonkeyPatch) -> None:
    from tw_signal_engine.replay import replay_session as rs

    _patch_common_dayhigh(monkeypatch, rs)
    monkeypatch.setattr(rs, "evaluate_signal_day_high", lambda *args, **kwargs: (False, "None"))

    entry = EntryTrade(
        symbol="2330",
        signal_type="SignalDayHigh",
        enter_cause="StrongGroup",
        side="long",
        entry_time_raw=93000000000,
        baseline=0.0,
        entry_price=106.05,
        entry_vwap=106.0,
        entry_qty=1000.0,
    )
    overnight = {
        "2330": OvernightHolding(
            entry_trade=entry,
            qty=1000.0,
            entry_idx=IndexData(vwap=1_060_000.0),
            entry_signal_type="SignalDayHigh",
            carry_from_date="20260129",
            limit_up_price=1_100_000,
        )
    }

    provider = _Provider([_tick("2330", 90000000000, 1_090_000, ask_price=1_091_000, bid_price=1_089_000)])
    trades = run_daily_replay(
        trade_date="20260130",
        history=HistoryWindow(vol_cum=[], trading_val=[], source_dates=[]),
        provider=provider,
        overnight_holdings=overnight,
        no_charts=True,
    )

    assert len(trades) == 1
    tr = trades[0]
    assert tr.final_leave_cause == "overnightExit"
    assert tr.trade_date == "20260129"
    assert tr.exit_trade_date == "20260130"
    assert tr.is_overnight is True
    assert tr.tax > 0
    assert overnight == {}


def test_standalone_replay_without_carry_map_warns_and_force_closes(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from tw_signal_engine.replay import replay_session as rs

    _patch_common_dayhigh(monkeypatch, rs)

    call_count = {"n": 0}

    def _trigger_once(*args, **kwargs):
        call_count["n"] += 1
        return (call_count["n"] == 1, "StrongGroup" if call_count["n"] == 1 else "None")

    monkeypatch.setattr(rs, "evaluate_signal_day_high", _trigger_once)

    provider = _Provider(
        [
            _tick("2330", 93000000000, 1_060_000, ask_price=1_060_500, bid_price=1_059_500),
            _tick("2330", 132000000000, 1_100_000, ask_price=0, bid_price=1_100_000),
        ]
    )

    trades = run_daily_replay(
        trade_date="20260129",
        history=HistoryWindow(vol_cum=[], trading_val=[], source_dates=[]),
        provider=provider,
        overnight_holdings=None,
        no_charts=True,
    )

    captured = capsys.readouterr()
    assert DAYHIGH_OVERNIGHT_MAP_WARNING in captured.out
    assert len(trades) == 1
    assert trades[0].final_leave_cause == "timeExit"
    assert trades[0].is_overnight is False


def test_tick_filter_includes_existing_overnight_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    from tw_signal_engine.replay import replay_session as rs

    _patch_common_dayhigh(monkeypatch, rs)
    monkeypatch.setattr(rs, "evaluate_signal_day_high", lambda *args, **kwargs: (False, "None"))

    captured_tick_filter: dict[str, set[str]] = {}

    class _FileProviderStub:
        def __init__(
            self,
            otc_date,
            tse_date,
            data_dir="./data/",
            tick_filter=None,
            prev_day_limit_up=None,
            num_tracker=None,
        ):
            captured_tick_filter["value"] = set(tick_filter or set())

        def iterate_ticks(self):
            return iter(())

    monkeypatch.setattr(rs, "FileReplayProvider", _FileProviderStub)

    overnight = {
        "2330": OvernightHolding(
            entry_trade=EntryTrade(symbol="2330", signal_type="SignalDayHigh", enter_cause="StrongGroup"),
            qty=0.0,
            entry_idx=IndexData(),
            entry_signal_type="SignalDayHigh",
            carry_from_date="20260129",
            limit_up_price=1_100_000,
        )
    }

    run_daily_replay(
        trade_date="20260130",
        history=HistoryWindow(vol_cum=[], trading_val=[], source_dates=[]),
        provider=None,
        overnight_holdings=overnight,
        no_charts=True,
    )

    assert "2330" in captured_tick_filter["value"]

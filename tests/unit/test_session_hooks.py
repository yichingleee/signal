"""Tests for session hooks."""

from __future__ import annotations

from tw_signal_engine.records.market_event_records import MarketTick
from tw_signal_engine.replay.session_hooks import SessionHooks
from tw_signal_engine.state.symbol_state import IndexData


class TestSessionHooks:
    def test_default_hooks_are_none(self):
        hooks = SessionHooks()
        assert hooks.on_tick is None
        assert hooks.on_screening is None
        assert hooks.on_screening_detail is None
        assert hooks.on_signal is None
        assert hooks.on_entry is None
        assert hooks.on_exit is None
        assert hooks.on_minute is None

    def test_hooks_can_be_set(self):
        calls = []

        def on_tick(tick: MarketTick, idx: IndexData) -> None:
            calls.append(("tick", tick.symbol))

        hooks = SessionHooks(on_tick=on_tick)
        tick = MarketTick()
        tick.symbol = "2330"
        idx = IndexData()
        hooks.on_tick(tick, idx)
        assert calls == [("tick", "2330")]

    def test_on_minute_callback(self):
        times = []

        def on_minute(match_time_str: int) -> None:
            times.append(match_time_str)

        hooks = SessionHooks(on_minute=on_minute)
        hooks.on_minute(93000000000)
        assert times == [93000000000]

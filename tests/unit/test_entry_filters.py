"""Tests for entry filters (should_enter)."""

from tw_signal_engine.config.strategy_config import ExecutionConfig
from tw_signal_engine.execution.create_entry_trade import should_enter
from tw_signal_engine.records.market_event_records import MarketTick, QuotePair
from tw_signal_engine.state.position_state import PositionState


def _make_tick(symbol: str = "2330", price: int = 500000, time_str: int = 100000000000) -> MarketTick:
    tick = MarketTick(symbol=symbol, match_time_str=time_str)
    tick.match = QuotePair(price=price, qty=100)
    tick.ask[0] = QuotePair(price=price, qty=10)
    return tick


class TestShouldEnter:
    def test_basic_entry_allowed(self):
        config = ExecutionConfig()
        tick = _make_tick()
        pos = PositionState()
        allowed, reason = should_enter(config, tick, "StrongGroup", "SignalA", pos, False, 0, 0, 0.0)
        assert allowed is True
        assert reason is None

    def test_entry_time_limit(self):
        config = ExecutionConfig(entry_time_limit=100000000000)
        tick = _make_tick(time_str=130000000000)
        pos = PositionState()
        allowed, reason = should_enter(config, tick, "StrongGroup", "SignalA", pos, False, 0, 0, 0.0)
        assert allowed is False
        assert reason == "entry_time_limit"

    def test_no_entry_friday(self):
        config = ExecutionConfig(no_entry_friday=True)
        tick = _make_tick()
        pos = PositionState()
        allowed, reason = should_enter(config, tick, "StrongGroup", "SignalA", pos, True, 0, 0, 0.0)
        assert allowed is False
        assert reason == "no_entry_friday"

    def test_already_holding(self):
        config = ExecutionConfig()
        tick = _make_tick(symbol="2330")
        pos = PositionState()
        pos.stocks["2330"] = 1000
        allowed, reason = should_enter(config, tick, "StrongGroup", "SignalA", pos, False, 0, 0, 0.0)
        assert allowed is False
        assert reason == "already_holding"

    def test_max_entry_price(self):
        config = ExecutionConfig(max_entry_price=40.0)
        tick = _make_tick(price=500000)
        pos = PositionState()
        allowed, reason = should_enter(config, tick, "StrongGroup", "SignalA", pos, False, 0, 0, 0.0)
        assert allowed is False
        assert reason == "max_entry_price"

    def test_prev_day_limit_up_filter(self):
        config = ExecutionConfig(filter_prev_day_limit_up=True)
        tick = _make_tick()
        tick.prev_limit_up = True
        pos = PositionState()
        allowed, reason = should_enter(config, tick, "StrongGroup", "SignalA", pos, False, 0, 0, 0.0)
        assert allowed is False
        assert reason == "prev_day_limit_up"

    def test_max_0050_entry_chg(self):
        config = ExecutionConfig(max_0050_entry_chg=1.0)
        tick = _make_tick()
        pos = PositionState()
        allowed, reason = should_enter(
            config, tick, "StrongGroup", "SignalA", pos, False,
            1000000, 1020000, 0.0,
        )
        assert allowed is False
        assert reason == "max_0050_entry_chg"

    def test_volatility_pause(self):
        config = ExecutionConfig(disposition_stocks_enabled=True)
        tick = _make_tick()
        tick.volatility_pause = True
        pos = PositionState()
        allowed, reason = should_enter(config, tick, "StrongGroup", "SignalA", pos, False, 0, 0, 0.0)
        assert allowed is False
        assert reason == "volatility_pause"

    def test_single_forbidden(self):
        config = ExecutionConfig()
        tick = _make_tick(symbol="2330")
        pos = PositionState()
        allowed, reason = should_enter(
            config, tick, "StrongSingle", "SignalA", pos, False, 0, 0, 0.0,
            strong_single_forbidden={"2330": True},
        )
        assert allowed is False
        assert reason == "single_forbidden"

    def test_max_0050_intra_chg(self):
        config = ExecutionConfig(max_0050_intra_chg=0.5)
        tick = _make_tick()
        pos = PositionState()
        # 0050 at +2% total, open chg 1% => intra = 2% - 1% = 1% >= 0.5%
        allowed, reason = should_enter(
            config, tick, "StrongGroup", "SignalA", pos, False,
            1000000, 1020000, 1.0,
        )
        assert allowed is False
        assert reason == "max_0050_intra_chg"

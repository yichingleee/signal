"""Execution-path tests for SignalDayHigh policy."""

from __future__ import annotations

from dataclasses import dataclass

from tw_signal_engine.config.strategy_config import ExecutionConfig
from tw_signal_engine.execution.create_entry_trade import execute_entry
from tw_signal_engine.execution.trade_ledger import on_tick_exit
from tw_signal_engine.records.market_event_records import MarketTick, QuotePair
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.state.position_state import PositionState
from tw_signal_engine.state.symbol_state import IndexData


@dataclass
class _StrongGroupStub:
    last_match_info: dict[str, object]

    def get_group_limit_up_count(self, group: str) -> int:
        return 0


def _ref(symbol: str = "2330") -> ReferenceSymbol:
    return ReferenceSymbol(
        symbol=symbol,
        name="TSMC",
        market="TSE",
        previous_close=100.0,
        limit_up_price=110.0,
        limit_down_price=90.0,
        industry="",
        security="",
        error_code="0",
    )


def _tick(price: int = 500_000) -> MarketTick:
    tick = MarketTick(symbol="2330", match_time_str=93000000000, match_time_us=93000000)
    tick.match = QuotePair(price=price, qty=100)
    tick.bid[0] = QuotePair(price=499_000, qty=10)
    tick.ask[0] = QuotePair(price=501_000, qty=10)
    return tick


def _enter_day_high_position(config: ExecutionConfig) -> tuple[PositionState, IndexData]:
    pos = PositionState()
    idx = IndexData(vwap=500_000.0, day_high=505_000, day_low=495_000)
    execute_entry(
        config,
        "long",
        _tick(),
        idx,
        "StrongGroup",
        "SignalDayHigh",
        pos,
        {"2330": _ref()},
        _StrongGroupStub(last_match_info={}),
        0,
        0,
        0.0,
    )
    return pos, idx


def test_day_high_entry_uses_ask_fixed_notional_and_no_take_profit_orders() -> None:
    config = ExecutionConfig(
        position_cash=10_000_000.0,
        take_profit_splits=2,
        take_profit_pcts=[0.03, 0.03],
        reserve_limit_up_splits=3,
    )
    pos, _ = _enter_day_high_position(config)

    assert pos.open_trades["2330"].signal_type == "SignalDayHigh"
    assert pos.open_trades["2330"].entry_price == 50.1
    assert pos.symbol_cash["2330"] == -10_000_000.0
    assert pos.orders["2330"] == []
    assert pos.reserve_stocks["2330"] == 0
    assert pos.limit_up_prices["2330"] == 1_100_000


def test_day_high_vwap_stop_loss_uses_bid_exit_price() -> None:
    config = ExecutionConfig(
        position_cash=10_000_000.0,
        stop_loss_ratio_day_high=0.990,
        exit_time_limit=140000000000,
    )
    pos, entry_idx = _enter_day_high_position(config)
    entry_qty = pos.open_trades["2330"].entry_qty
    entry_price = pos.open_trades["2330"].entry_price
    completed: list = []

    cause = on_tick_exit(
        config,
        "2330",
        494_000,
        493_000,
        495_000,
        100000000000,
        "SignalDayHigh",
        entry_idx,
        pos,
        completed,
    )

    assert cause == "stopLoss"
    assert len(completed) == 1
    expected_symbol_cash = (-entry_qty * entry_price) + (entry_qty * 49.3)
    assert abs(pos.symbol_cash["2330"] - expected_symbol_cash) < 0.1


def test_day_high_time_exit_uses_bid_price() -> None:
    config = ExecutionConfig(position_cash=10_000_000.0, exit_time_limit=132000000000)
    pos, entry_idx = _enter_day_high_position(config)
    entry_qty = pos.open_trades["2330"].entry_qty
    entry_price = pos.open_trades["2330"].entry_price
    completed: list = []

    cause = on_tick_exit(
        config,
        "2330",
        520_000,
        519_000,
        521_000,
        132000000000,
        "SignalDayHigh",
        entry_idx,
        pos,
        completed,
    )

    assert cause == "timeExit"
    assert len(completed) == 1
    expected_symbol_cash = (-entry_qty * entry_price) + (entry_qty * 51.9)
    assert abs(pos.symbol_cash["2330"] - expected_symbol_cash) < 0.1


def test_day_high_policy_suppresses_bailout() -> None:
    config = ExecutionConfig(position_cash=10_000_000.0, exit_time_limit=140000000000, bailout_ratio=0.985)
    pos, _ = _enter_day_high_position(config)
    pos.profit_taken["2330"] = True
    completed: list = []

    cause = on_tick_exit(
        config,
        "2330",
        480_000,
        479_000,
        481_000,
        100000000000,
        "SignalDayHigh",
        IndexData(vwap=100_000.0, day_high=500_000),
        pos,
        completed,
    )

    assert cause is None
    assert completed == []
    assert abs(pos.stocks.get("2330", 0)) > 0.001

"""Short-mode signed quantity and exit stack behavior tests."""

from __future__ import annotations

from dataclasses import dataclass

from tw_signal_engine.config.strategy_config import ExecutionConfig
from tw_signal_engine.execution.create_entry_trade import execute_entry
from tw_signal_engine.execution.trade_ledger import on_tick_exit
from tw_signal_engine.records.market_event_records import MarketTick, QuotePair
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.records.trade_records import EntryTrade
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


def _tick() -> MarketTick:
    tick = MarketTick(symbol="2330", match_time_str=93000000000, match_time_us=93000000)
    tick.match = QuotePair(price=100500, qty=100)
    tick.bid[0] = QuotePair(price=100000, qty=10)
    tick.ask[0] = QuotePair(price=101000, qty=10)
    return tick


def test_execute_entry_short_uses_signed_qty_and_bid_fill() -> None:
    config = ExecutionConfig(
        position_cash=1000.0,
        take_profit_splits=2,
        take_profit_pcts=[0.01, 0.02],
        reserve_limit_up_splits=3,
    )
    pos = PositionState()

    execute_entry(
        config,
        "short",
        _tick(),
        IndexData(vwap=100000.0, day_high=100500, day_low=99500),
        "StrongGroup",
        "SignalA",
        pos,
        {"2330": _ref()},
        _StrongGroupStub(last_match_info={}),
        0,
        0,
        0.0,
    )

    assert pos.stocks["2330"] < 0
    assert abs(pos.symbol_cash["2330"] - 1000.0) < 1e-6
    assert pos.open_trades["2330"].side == "short"
    assert pos.open_trades["2330"].entry_qty < 0
    assert pos.open_trades["2330"].entry_price == 10.0
    assert pos.reserve_stocks["2330"] == 0.0
    assert len(pos.orders["2330"]) == 2


def _short_pos() -> PositionState:
    return PositionState(
        stocks={"2330": -10.0},
        symbol_cash={"2330": 500.0},
        orders={"2330": []},
        reserve_stocks={"2330": 0.0},
        profit_taken={"2330": False},
        open_trades={
            "2330": EntryTrade(
                symbol="2330",
                side="short",
                signal_type="SignalA",
                enter_cause="StrongGroup",
                entry_time_raw=90000000000,
                baseline=0.0,
                entry_price=50.0,
                entry_qty=-10.0,
            )
        },
        trade_low={"2330": 500000},
        trade_high={"2330": 500000},
    )


def test_short_time_exit_uses_ask_side() -> None:
    pos = _short_pos()
    config = ExecutionConfig(position_cash=1000.0, exit_time_limit=130000000000)
    completed: list = []

    cause = on_tick_exit(
        config,
        "2330",
        490000,
        489000,
        491000,
        132500000000,
        "SignalA",
        IndexData(vwap=500000.0, day_low=480000),
        pos,
        completed,
    )

    assert cause == "timeExit"
    assert len(completed) == 1
    # 500 + (-10 * 49.1) = 9.0
    assert abs(completed[0].pnl - 9.0) < 0.01


def test_short_stop_loss_uses_mirrored_threshold_and_ask_fill() -> None:
    pos = _short_pos()
    config = ExecutionConfig(position_cash=1000.0, exit_time_limit=140000000000, stop_loss_ratio_a=0.995)
    completed: list = []

    cause = on_tick_exit(
        config,
        "2330",
        503000,
        502000,
        504000,
        100000000000,
        "SignalA",
        IndexData(vwap=500000.0, day_low=480000),
        pos,
        completed,
    )

    assert cause == "stopLoss"
    assert len(completed) == 1
    assert completed[0].pnl < 0


def test_short_take_profit_trigger_and_fill() -> None:
    pos = _short_pos()
    pos.orders["2330"] = [(490000, 10.0)]
    config = ExecutionConfig(position_cash=1000.0, exit_time_limit=140000000000)
    completed: list = []

    cause = on_tick_exit(
        config,
        "2330",
        489000,
        488000,
        490000,
        100000000000,
        "SignalA",
        IndexData(vwap=500000.0, day_low=480000),
        pos,
        completed,
    )

    assert cause == "takeProfit"
    assert len(completed) == 1
    assert completed[0].pnl > 0


def test_short_bailout_after_tp_uses_mirrored_day_low_rule() -> None:
    pos = _short_pos()
    pos.profit_taken["2330"] = True
    config = ExecutionConfig(position_cash=1000.0, exit_time_limit=140000000000, bailout_ratio=0.98)
    completed: list = []

    cause = on_tick_exit(
        config,
        "2330",
        490000,
        489000,
        491000,
        100000000000,
        "SignalA",
        IndexData(vwap=500000.0, day_low=480000),
        pos,
        completed,
    )

    assert cause == "bailout"
    assert len(completed) == 1

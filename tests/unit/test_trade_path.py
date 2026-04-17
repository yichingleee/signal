"""Tests for MAE/MFE tracking and population in record_close()."""

from __future__ import annotations

from tw_signal_engine.config.strategy_config import ExecutionConfig
from tw_signal_engine.execution.trade_ledger import _compute_hour_bucket, on_tick_exit
from tw_signal_engine.records.trade_records import EntryTrade
from tw_signal_engine.state.position_state import PositionState
from tw_signal_engine.state.symbol_state import IndexData

PRICE_SCALE = 10000


def _make_pos(
    symbol: str = "2330",
    entry_price: float = 50.0,
    qty: float = 10.0,
    baseline: float = 0.0,
    entry_time: int = 90000000000,
) -> PositionState:
    """Create a PositionState with one open trade."""
    entry_price_int = int(entry_price * PRICE_SCALE)
    pos = PositionState(
        stocks={symbol: qty},
        symbol_cash={symbol: -entry_price * qty + baseline},
        orders={symbol: []},
        reserve_stocks={symbol: 0.0},
        profit_taken={symbol: False},
        open_trades={
            symbol: EntryTrade(
                symbol=symbol,
                signal_type="SignalA",
                enter_cause="StrongGroup",
                entry_time_raw=entry_time,
                baseline=-entry_price * qty,
                entry_price=entry_price,
            )
        },
        trade_low={symbol: entry_price_int},
        trade_high={symbol: entry_price_int},
    )
    return pos


class TestMAEMFETracking:
    def test_mae_mfe_populated_on_close(self):
        """MAE/MFE should be populated when trade closes."""
        config = ExecutionConfig(position_cash=1000.0, exit_time_limit=130000000000)
        pos = _make_pos(entry_price=50.0)

        # Simulate price going up to 51.0 then closing
        pos.trade_high["2330"] = 510000  # 51.0
        pos.trade_low["2330"] = 490000  # 49.0

        # Force time exit
        completed: list = []
        on_tick_exit(config, "2330", 505000, 504000, 506000, 132500000000, "SignalA", IndexData(), pos, completed)

        assert len(completed) == 1
        tr = completed[0]
        # MAE = (49.0 - 50.0) / 50.0 * 100 = -2.0%
        assert abs(tr.mae_pct - (-2.0)) < 0.01
        # MFE = (51.0 - 50.0) / 50.0 * 100 = 2.0%
        assert abs(tr.mfe_pct - 2.0) < 0.01
        assert tr.mae_price == 49.0
        assert tr.mfe_price == 51.0
        assert tr.exit_price == 50.5

    def test_mae_mfe_zero_when_no_movement(self):
        """MAE/MFE should be 0 when price doesn't move from entry."""
        config = ExecutionConfig(position_cash=1000.0, exit_time_limit=130000000000)
        pos = _make_pos(entry_price=50.0)

        completed: list = []
        on_tick_exit(config, "2330", 500000, 499000, 501000, 132500000000, "SignalA", IndexData(), pos, completed)

        assert len(completed) == 1
        tr = completed[0]
        assert tr.mae_pct == 0.0
        assert tr.mfe_pct == 0.0

    def test_mae_updates_on_tick(self):
        """Trade low should be updated when price drops below previous low."""
        config = ExecutionConfig(position_cash=1000.0, exit_time_limit=132500000000)
        pos = _make_pos(entry_price=50.0)

        completed: list = []
        # Price drops to 49.0 - should update trade_low
        on_tick_exit(config, "2330", 490000, 489000, 491000, 100000000000, "SignalA", IndexData(), pos, completed)
        assert pos.trade_low["2330"] == 490000

        # Price drops further to 48.0
        on_tick_exit(config, "2330", 480000, 479000, 481000, 100500000000, "SignalA", IndexData(), pos, completed)
        assert pos.trade_low["2330"] == 480000

    def test_mfe_updates_on_tick(self):
        """Trade high should be updated when price rises above previous high."""
        config = ExecutionConfig(position_cash=1000.0, exit_time_limit=132500000000)
        pos = _make_pos(entry_price=50.0)

        completed: list = []
        # Price rises to 51.0
        on_tick_exit(config, "2330", 510000, 509000, 511000, 100000000000, "SignalA", IndexData(), pos, completed)
        assert pos.trade_high["2330"] == 510000

    def test_trade_low_high_cleaned_on_close(self):
        """MAE/MFE tracking dicts should be cleaned up after trade close."""
        config = ExecutionConfig(position_cash=1000.0, exit_time_limit=130000000000)
        pos = _make_pos(entry_price=50.0)

        completed: list = []
        on_tick_exit(config, "2330", 500000, 499000, 501000, 132500000000, "SignalA", IndexData(), pos, completed)

        assert "2330" not in pos.trade_low
        assert "2330" not in pos.trade_high


class TestHourBucket:
    def test_before_915(self):
        assert _compute_hour_bucket(90500000000) == "09:00-09:15"

    def test_at_915(self):
        assert _compute_hour_bucket(91500000000) == "09:15-09:30"

    def test_at_930(self):
        assert _compute_hour_bucket(93000000000) == "09:30-10:00"

    def test_after_10(self):
        assert _compute_hour_bucket(103000000000) == "10:00+"

    def test_at_1000(self):
        assert _compute_hour_bucket(100000000000) == "09:30-10:00"

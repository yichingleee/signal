"""Tests for take-profit slice tracking in check_take_profit."""

from __future__ import annotations

from tw_signal_engine.execution.apply_take_profit_plan import check_take_profit
from tw_signal_engine.records.trade_records import EntryTrade
from tw_signal_engine.state.position_state import PositionState


def _make_pos(symbol: str = "2330", qty: float = 30.0, entry_price: float = 0.0) -> PositionState:
    return PositionState(
        stocks={symbol: qty},
        symbol_cash={symbol: 0.0},
        orders={symbol: [(500000, 10.0), (510000, 10.0), (520000, 10.0)]},
        profit_taken={symbol: False},
        open_trades={
            symbol: EntryTrade(
                symbol=symbol,
                signal_type="SignalA",
                enter_cause="StrongGroup",
                entry_time_raw=90000000000,
                entry_price=entry_price,
            )
        },
    )


class TestTPSliceTracking:
    def test_single_fill(self):
        pos = _make_pos()
        # Price hits first TP level (50.0)
        result = check_take_profit("2330", 500000, pos, match_time_str=91000000000)
        assert result is True
        ot = pos.open_trades["2330"]
        assert ot.tp_slices_filled == 1
        assert ot.first_tp_time_raw == 91000000000
        assert ot.tp_realized_pnl > 0

    def test_multiple_fills(self):
        pos = _make_pos()
        # Price hits all TP levels (52.0)
        result = check_take_profit("2330", 520000, pos, match_time_str=92000000000)
        assert result is True
        ot = pos.open_trades["2330"]
        assert ot.tp_slices_filled == 3
        assert ot.first_tp_time_raw == 92000000000

    def test_no_fill(self):
        pos = _make_pos()
        # Price below all TP levels
        result = check_take_profit("2330", 490000, pos, match_time_str=91000000000)
        assert result is False
        ot = pos.open_trades["2330"]
        assert ot.tp_slices_filled == 0
        assert ot.first_tp_time_raw == 0

    def test_progressive_fills_accumulate(self):
        pos = _make_pos()
        # First fill
        check_take_profit("2330", 500000, pos, match_time_str=91000000000)
        assert pos.open_trades["2330"].tp_slices_filled == 1

        # Second fill (higher price)
        check_take_profit("2330", 510000, pos, match_time_str=92000000000)
        assert pos.open_trades["2330"].tp_slices_filled == 2
        # first_tp_time should not change
        assert pos.open_trades["2330"].first_tp_time_raw == 91000000000

    def test_tp_realized_pnl_accumulates(self):
        pos = _make_pos()
        check_take_profit("2330", 500000, pos, match_time_str=91000000000)
        pnl_1 = pos.open_trades["2330"].tp_realized_pnl

        check_take_profit("2330", 510000, pos, match_time_str=92000000000)
        pnl_2 = pos.open_trades["2330"].tp_realized_pnl

        assert pnl_2 > pnl_1

    def test_tp_realized_pnl_is_profit_not_revenue(self):
        # entry_price = 48.0 TWD, TP order at 50.0 TWD, qty = 10 shares
        # profit = 10 * (50.0 - 48.0) = 20, NOT revenue = 10 * 50.0 = 500
        pos = _make_pos(entry_price=48.0)
        check_take_profit("2330", 500000, pos, match_time_str=91000000000)
        ot = pos.open_trades["2330"]
        # Profit: 10 shares * (50.0 - 48.0) = 20.0
        assert abs(ot.tp_realized_pnl - 20.0) < 0.01

    def test_no_match_time_leaves_first_tp_time_zero(self):
        pos = _make_pos()
        check_take_profit("2330", 500000, pos, match_time_str=0)
        assert pos.open_trades["2330"].first_tp_time_raw == 0

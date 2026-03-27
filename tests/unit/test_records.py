"""Tests for record dataclasses."""

from tw_signal_engine.records.market_event_records import MarketTick, QuotePair, TradeRecord
from tw_signal_engine.records.trade_records import EntryTrade


class TestQuotePair:
    def test_defaults(self):
        qp = QuotePair()
        assert qp.price == 0
        assert qp.qty == 0


class TestMarketTick:
    def test_defaults(self):
        tick = MarketTick()
        assert tick.symbol == ""
        assert tick.trade_code == 0
        assert len(tick.bid) == 5
        assert len(tick.ask) == 5

    def test_bid_ask_independent(self):
        tick = MarketTick()
        tick.bid[0].price = 100
        assert tick.bid[1].price == 0


class TestTradeRecord:
    def test_defaults(self):
        tr = TradeRecord()
        assert tr.pnl == 0.0
        assert tr.return_pct == 0.0
        assert tr.exit_price == 0.0


class TestEntryTrade:
    def test_creation(self):
        et = EntryTrade(symbol="2330", signal_type="SignalA", enter_cause="StrongGroup")
        assert et.symbol == "2330"
        assert et.had_take_profit is False

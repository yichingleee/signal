"""Tests for the lightweight history trade parser."""

from __future__ import annotations

from tw_signal_engine.market_data.parse_history_trades import parse_history_trade


def test_parse_valid_trade() -> None:
    line = "Trade,2330,90000000000,0,5880000,100"
    trade = parse_history_trade(line)
    assert trade is not None
    assert trade.symbol == "2330"
    assert trade.price == 5880000
    assert trade.qty == 100
    assert trade.match_time_us > 0


def test_parse_rejects_nonzero_status() -> None:
    line = "Trade,2330,90000000000,1,5880000,100"
    assert parse_history_trade(line) is None


def test_parse_rejects_depth_line() -> None:
    line = "Depth,2330,90000000000,BID:1,5880000,ASK:1,5890000"
    assert parse_history_trade(line) is None


def test_parse_rejects_empty_symbol() -> None:
    line = "Trade,,90000000000,0,5880000,100"
    assert parse_history_trade(line) is None


def test_parse_rejects_too_few_fields() -> None:
    line = "Trade,2330,90000000000,0,5880000"
    assert parse_history_trade(line) is None


def test_parse_rejects_non_trade_prefix() -> None:
    assert parse_history_trade("") is None
    assert parse_history_trade("X") is None
    assert parse_history_trade("Tx") is None


def test_parse_time_conversion() -> None:
    # 91500000000 = 9h15m00s000000us
    line = "Trade,SYM,91500000000,0,100000,10"
    trade = parse_history_trade(line)
    assert trade is not None
    # 9*3600 + 15*60 = 33300 seconds = 33300000000 us
    assert trade.match_time_us == 33300000000

"""Tests for MarketDataProvider implementations."""

from __future__ import annotations

import threading

from tw_signal_engine.config.strategy_config import LiveConfig
from tw_signal_engine.market_data.backfill_provider import BackfillThenLiveProvider
from tw_signal_engine.market_data.file_replay_provider import FileReplayProvider
from tw_signal_engine.market_data.paced_replay_provider import PacedReplayProvider
from tw_signal_engine.market_data.parse_format6_replay_rows import parse_trade_line
from tw_signal_engine.market_data.providers import MarketDataProvider
from tw_signal_engine.market_data.redis_live_provider import RedisLiveProvider
from tw_signal_engine.records.market_event_records import MarketTick, QuotePair


class _MockProvider(MarketDataProvider):
    """Test provider that yields a fixed list of ticks."""

    def __init__(self, ticks: list[MarketTick]) -> None:
        self._ticks = ticks

    def iterate_ticks(self):
        yield from self._ticks


class _FakePubSub:
    def __init__(self, messages: list[object], on_empty=None) -> None:
        self.messages = messages
        self.on_empty = on_empty
        self.subscribed: tuple[str, ...] = ()
        self.unsubscribed = False
        self.closed = False

    def subscribe(self, *channels: str) -> None:
        self.subscribed = channels

    def get_message(self, timeout: float = 1.0) -> object | None:
        if self.messages:
            item = self.messages.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if self.on_empty is not None:
            self.on_empty()
        return None

    def unsubscribe(self) -> None:
        self.unsubscribed = True

    def close(self) -> None:
        self.closed = True


class _FakeRedisClient:
    def __init__(self, pubsub: _FakePubSub) -> None:
        self._pubsub = pubsub
        self.closed = False

    def pubsub(self) -> _FakePubSub:
        return self._pubsub

    def close(self) -> None:
        self.closed = True


def _make_tick(symbol: str = "2330", time_str: int = 90000000000, price: int = 5000000) -> MarketTick:
    tick = MarketTick()
    tick.symbol = symbol
    tick.market = "TSE"
    tick.match_time_str = time_str
    tick.match_time_us = 32400000000  # 9:00
    tick.status_code = 0
    tick.trade_code = 1
    tick.match = QuotePair(price=price, qty=100)
    return tick


class TestMockProvider:
    def test_iterate_empty(self):
        p = _MockProvider([])
        assert list(p.iterate_ticks()) == []

    def test_iterate_ticks(self):
        ticks = [_make_tick(time_str=i) for i in range(5)]
        p = _MockProvider(ticks)
        result = list(p.iterate_ticks())
        assert len(result) == 5
        assert result[0].match_time_str == 0
        assert result[4].match_time_str == 4


class TestPacedReplayProvider:
    def test_yields_all_ticks(self):
        ticks = [_make_tick(time_str=90000000000 + i * 1000000) for i in range(3)]
        # match_time_us values need to differ for pacing
        ticks[0].match_time_us = 32400000000
        ticks[1].match_time_us = 32401000000  # +1 sec
        ticks[2].match_time_us = 32402000000  # +2 sec
        inner = _MockProvider(ticks)
        # Use very fast speed to avoid actual delays
        p = PacedReplayProvider(inner, speed=1000000.0)
        result = list(p.iterate_ticks())
        assert len(result) == 3

    def test_preserves_tick_data(self):
        tick = _make_tick(symbol="2317", price=1234000)
        inner = _MockProvider([tick])
        p = PacedReplayProvider(inner, speed=1000.0)
        result = list(p.iterate_ticks())
        assert result[0].symbol == "2317"
        assert result[0].match.price == 1234000


class TestFileReplayProvider:
    def test_is_market_data_provider(self):
        p = FileReplayProvider("20260129", "20260129")
        assert isinstance(p, MarketDataProvider)

    def test_nonexistent_files_yield_nothing(self):
        p = FileReplayProvider("99999999", "99999999", data_dir="/nonexistent/")
        result = list(p.iterate_ticks())
        assert result == []


class TestRedisLiveProvider:
    def test_handle_trade_depth_pairing(self):
        config = LiveConfig()
        p = RedisLiveProvider(config, tick_filter={"2330"})

        # Simulate Trade + Depth pairing
        trade_line = "Trade,2330  ,90000000000,0,5000000,100,1000,1"
        depth_line = "Depth,2330  ,90000000000,BID:5,4999000,100,ASK:5,5001000,200"

        p._handle_line(trade_line)
        # Trade is buffered, no tick yet
        assert p._queue.qsize() == 0

        p._handle_line(depth_line)
        # Now tick should be emitted
        assert p._queue.qsize() == 1
        tick = p._queue.get_nowait()
        assert tick is not None
        assert tick.symbol == "2330"
        assert tick.match.price == 5000000
        assert tick.bid[0].price == 4999000
        assert tick.ask[0].price == 5001000
        status = p.get_status()
        assert status.last_tick_time_raw == 90000000000
        assert status.queue_depth == 0

    def test_handle_trade_without_depth(self):
        config = LiveConfig()
        p = RedisLiveProvider(config, tick_filter={"2330"})

        trade1 = "Trade,2330  ,90000000000,0,5000000,100,1000,1"
        trade2 = "Trade,2330  ,90001000000,0,5010000,200,1200,2"

        p._handle_line(trade1)
        assert p._queue.qsize() == 0  # buffered

        p._handle_line(trade2)
        # trade1 flushed without depth, trade2 buffered
        assert p._queue.qsize() == 1
        tick = p._queue.get_nowait()
        assert tick.match.price == 5000000  # first trade

    def test_handle_empty_line(self):
        config = LiveConfig()
        p = RedisLiveProvider(config, tick_filter={"2330"})
        p._handle_line("")
        assert p._queue.qsize() == 0
        assert p.get_status().ignored_message_count == 0

    def test_empty_tick_filter_terminates(self):
        """iterate_ticks() must terminate when tick_filter is empty (no infinite loop)."""
        config = LiveConfig()
        p = RedisLiveProvider(config, tick_filter=set())
        result = list(p.iterate_ticks())
        assert result == []

    def test_status_code_filter(self):
        config = LiveConfig()
        p = RedisLiveProvider(config, tick_filter={"2330"})

        # status_code=1 (simulated) should be filtered
        trade = "Trade,2330  ,90000000000,1,5000000,100,1000,1"
        depth = "Depth,2330  ,90000000000,BID:5,4999000,100,ASK:5,5001000,200"
        p._handle_line(trade)
        p._handle_line(depth)
        assert p._queue.qsize() == 0  # filtered out
        assert p.get_status().ignored_message_count == 1

    def test_unknown_message_type_increments_ignored_count(self):
        config = LiveConfig()
        p = RedisLiveProvider(config, tick_filter={"2330"})

        p._handle_line("Quote,2330,90000000000")

        assert p._queue.qsize() == 0
        assert p.get_status().ignored_message_count == 1

    def test_malformed_trade_increments_parse_error_count(self):
        config = LiveConfig()
        p = RedisLiveProvider(config, tick_filter={"2330"})

        p._handle_line("Trade,2330")

        status = p.get_status()
        assert p._queue.qsize() == 0
        assert status.parse_error_count == 1
        assert "malformed Trade" in status.last_error

    def test_fake_redis_listener_decodes_bytes_and_strings(self):
        config = LiveConfig(reconnect_delay=0)
        provider_ref: dict[str, RedisLiveProvider] = {}
        pubsub = _FakePubSub(
            [
                {"type": "subscribe", "data": b""},
                {"type": "message", "data": b"Trade,2330  ,90000000000,0,5000000,100,1000,1"},
                {"type": "message", "data": "Depth,2330  ,90000000000,BID:5,4999000,100,ASK:5,5001000,200"},
            ],
            on_empty=lambda: provider_ref["provider"].stop(),
        )
        client = _FakeRedisClient(pubsub)
        provider = RedisLiveProvider(
            config,
            tick_filter={"2330"},
            redis_client_factory=lambda: client,
        )
        provider_ref["provider"] = provider

        thread = threading.Thread(target=provider._listen)
        thread.start()
        thread.join(timeout=1.0)

        assert not thread.is_alive()
        assert pubsub.subscribed == ("2330",)
        assert pubsub.unsubscribed is True
        assert pubsub.closed is True
        assert client.closed is True
        tick = provider._queue.get_nowait()
        assert tick is not None
        assert tick.symbol == "2330"
        status = provider.get_status()
        assert status.connected is False
        assert status.subscribed_channels == 0
        assert status.last_message_at != ""
        assert status.last_tick_time_raw == 90000000000

    def test_fake_redis_listener_reconnect_status(self):
        config = LiveConfig(reconnect_delay=0)
        provider_ref: dict[str, RedisLiveProvider] = {}
        first_pubsub = _FakePubSub([OSError("connection lost")])
        second_pubsub = _FakePubSub(
            [
                {"type": "message", "data": "Trade,2330,90000000000,0,5000000,100"},
                {"type": "message", "data": "Depth,2330,90000000000,BID:1,4999000,100,ASK:1,5001000,200"},
            ],
            on_empty=lambda: provider_ref["provider"].stop(),
        )
        clients = [_FakeRedisClient(first_pubsub), _FakeRedisClient(second_pubsub)]

        provider = RedisLiveProvider(
            config,
            tick_filter={"2330"},
            redis_client_factory=lambda: clients.pop(0),
        )
        provider_ref["provider"] = provider

        thread = threading.Thread(target=provider._listen)
        thread.start()
        thread.join(timeout=1.0)

        assert not thread.is_alive()
        status = provider.get_status()
        assert status.reconnect_count == 1
        assert status.last_error == "connection lost"
        tick = provider._queue.get_nowait()
        assert tick is not None
        assert tick.symbol == "2330"
        assert first_pubsub.closed is True
        assert second_pubsub.closed is True


class TestBackfillThenLiveProvider:
    def test_cutover_computation(self):
        cutover = BackfillThenLiveProvider._compute_cutover()
        assert isinstance(cutover, int)
        assert cutover > 0

    def test_file_then_live(self):
        file_ticks = [
            _make_tick(time_str=90000000000),
            _make_tick(time_str=91000000000),
            _make_tick(time_str=92000000000),
        ]
        live_ticks = [
            _make_tick(time_str=93000000000),
            _make_tick(time_str=94000000000),
        ]
        file_provider = _MockProvider(file_ticks)
        live_provider = _MockProvider(live_ticks)

        # Cutover at 92000000000 — file ticks before that, then live
        p = BackfillThenLiveProvider(
            file_provider=file_provider,  # type: ignore[arg-type]
            redis_provider=live_provider,  # type: ignore[arg-type]
            cutover_time_str=92000000000,
        )
        result = list(p.iterate_ticks())
        # Should get 2 file ticks (before cutover) + 2 live ticks
        assert len(result) == 4
        assert result[0].match_time_str == 90000000000
        assert result[1].match_time_str == 91000000000
        assert result[2].match_time_str == 93000000000
        assert result[3].match_time_str == 94000000000

    def test_dedup_overlap(self):
        file_ticks = [
            _make_tick(symbol="2330", time_str=90000000000),
            _make_tick(symbol="2330", time_str=91000000000),
        ]
        live_ticks = [
            _make_tick(symbol="2330", time_str=91000000000),  # duplicate
            _make_tick(symbol="2330", time_str=92000000000),
        ]
        file_provider = _MockProvider(file_ticks)
        live_provider = _MockProvider(live_ticks)

        p = BackfillThenLiveProvider(
            file_provider=file_provider,  # type: ignore[arg-type]
            redis_provider=live_provider,  # type: ignore[arg-type]
            cutover_time_str=92000000000,
        )
        result = list(p.iterate_ticks())
        # File: 90000, 91000 | Live: 91000 (deduped), 92000
        assert len(result) == 3
        times = [t.match_time_str for t in result]
        assert times == [90000000000, 91000000000, 92000000000]


class TestFormat6DepthParsing:
    def test_depth_parses_total_bid_ask_qty(self):
        trade = "Trade,2330,90000000000,0,5000000,100"
        depth = "Depth,2330,90000000000,BID:2,4999000,300,4998000,200,ASK:2,5001000,150,5002000,50"

        tick = parse_trade_line(trade, depth, "TSE")
        assert tick is not None
        assert tick.bid[0].price == 4999000
        assert tick.ask[0].price == 5001000
        assert tick.total_bid_qty == 500
        assert tick.total_ask_qty == 200

    def test_depth_missing_ask_queue_keeps_ask_total_zero(self):
        trade = "Trade,2330,90000000000,0,5000000,100"
        depth = "Depth,2330,90000000000,BID:1,4999000,300,ASK:0"

        tick = parse_trade_line(trade, depth, "TSE")
        assert tick is not None
        assert tick.ask[0].price == 0
        assert tick.total_ask_qty == 0

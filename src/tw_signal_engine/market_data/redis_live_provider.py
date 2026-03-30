"""Redis Pub/Sub live market data provider."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Iterator

import redis

from tw_signal_engine.config.strategy_config import LiveConfig
from tw_signal_engine.market_data.market_data_records import NumTracker
from tw_signal_engine.market_data.parse_format6_replay_rows import parse_trade_line
from tw_signal_engine.market_data.providers import MarketDataProvider
from tw_signal_engine.records.market_event_records import MarketTick

logger = logging.getLogger(__name__)


class RedisLiveProvider(MarketDataProvider):
    """Consumes live market data from Redis Pub/Sub channels.

    Architecture:
    - Background listener thread subscribes to Redis Pub/Sub channels
    - Parsed MarketTick objects are pushed to a thread-safe queue
    - iterate_ticks() pulls from the queue in the main thread
    - Optional reorder buffer handles out-of-order messages

    The main event loop stays single-threaded — only the listener touches Redis.
    """

    def __init__(
        self,
        config: LiveConfig,
        tick_filter: set[str],
        prev_day_limit_up: dict[str, bool] | None = None,
    ) -> None:
        self._config = config
        self._tick_filter = tick_filter
        self._prev_day_limit_up = prev_day_limit_up or {}
        self._queue: queue.Queue[MarketTick | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._num_tracker = NumTracker()
        # Buffer last trade line per symbol for Trade/Depth pairing
        self._pending_trade: dict[str, str] = {}
        self._listener_thread: threading.Thread | None = None

    def start_listener(self) -> None:
        """Start the Redis listener thread early (idempotent — safe to call before iterate_ticks)."""
        if self._listener_thread is None or not self._listener_thread.is_alive():
            self._listener_thread = threading.Thread(
                target=self._listen, daemon=True, name="redis-listener"
            )
            self._listener_thread.start()

    def iterate_ticks(self) -> Iterator[MarketTick]:
        """Yield MarketTick objects from the Redis stream.

        Starts the listener thread if not already running, then pulls ticks from the queue.
        Stops when the stop event is set or a None sentinel is received.
        """
        self.start_listener()

        buffer: list[MarketTick] = []
        buffer_window_us = self._config.reorder_buffer_ms * 1000

        try:
            while not self._stop_event.is_set():
                try:
                    tick = self._queue.get(timeout=1.0)
                except queue.Empty:
                    # Flush any buffered ticks on timeout
                    if buffer:
                        buffer.sort(key=lambda t: t.match_time_str)
                        yield from buffer
                        buffer.clear()
                    continue

                if tick is None:
                    break

                if buffer_window_us > 0:
                    buffer.append(tick)
                    # Flush ticks that are old enough
                    now_us = tick.match_time_us
                    ready: list[MarketTick] = []
                    remaining: list[MarketTick] = []
                    for t in buffer:
                        if now_us - t.match_time_us >= buffer_window_us:
                            ready.append(t)
                        else:
                            remaining.append(t)
                    buffer = remaining
                    if ready:
                        ready.sort(key=lambda t: t.match_time_str)
                        yield from ready
                else:
                    yield tick

        finally:
            self._stop_event.set()
            # Flush remaining buffered ticks
            if buffer:
                buffer.sort(key=lambda t: t.match_time_str)
                yield from buffer

    def stop(self) -> None:
        """Signal the provider to stop."""
        self._stop_event.set()
        # Push sentinel to unblock queue.get()
        self._queue.put_nowait(None)

    def _listen(self) -> None:
        """Background thread: subscribe to Redis and push ticks to queue."""
        while not self._stop_event.is_set():
            try:
                r = redis.Redis(
                    host=self._config.redis_host,
                    port=self._config.redis_port,
                    db=self._config.redis_db,
                    socket_timeout=self._config.socket_timeout,
                )
                pubsub = r.pubsub()  # type: ignore[no-untyped-call]
                channels = list(self._tick_filter)
                if channels:
                    pubsub.subscribe(*channels)
                else:
                    logger.warning("No channels to subscribe to (empty tick_filter)")
                    self._stop_event.set()
                    return

                logger.info(
                    "Redis listener connected to %s:%d, subscribed to %d channels",
                    self._config.redis_host,
                    self._config.redis_port,
                    len(channels),
                )

                while not self._stop_event.is_set():
                    message = pubsub.get_message(timeout=1.0)
                    if message is None:
                        continue
                    if message["type"] != "message":
                        continue
                    data = message["data"]
                    if isinstance(data, bytes):
                        line = data.decode("utf-8", errors="replace")
                    else:
                        line = str(data)
                    self._handle_line(line)

                pubsub.unsubscribe()
                pubsub.close()
                r.close()

            except (redis.ConnectionError, redis.TimeoutError, OSError) as e:
                if not self._stop_event.is_set():
                    logger.warning(
                        "Redis connection lost (%s), reconnecting in %.1fs",
                        e,
                        self._config.reconnect_delay,
                    )
                    time.sleep(self._config.reconnect_delay)

    def _handle_line(self, line: str) -> None:
        """Parse a single line from Redis and push MarketTick to queue."""
        line = line.rstrip("\n\r")
        if not line:
            return

        is_trade = len(line) >= 2 and line[0] == "T" and line[1] == "r"
        is_depth = len(line) >= 2 and line[0] == "D" and line[1] == "e"

        if is_trade:
            # Extract symbol for pairing
            comma1 = line.find(",", 6)
            if comma1 == -1:
                return
            symbol = line[6:comma1].strip()

            # If we had a pending trade for this symbol, flush it without depth
            if symbol in self._pending_trade:
                self._emit_tick(self._pending_trade.pop(symbol), "")

            # Buffer this trade line, waiting for a depth line
            self._pending_trade[symbol] = line

        elif is_depth:
            # Extract symbol from depth line
            comma1 = line.find(",", 6)
            if comma1 == -1:
                return
            symbol = line[6:comma1].strip()

            # Pair with pending trade
            trade_line = self._pending_trade.pop(symbol, None)
            if trade_line is not None:
                self._emit_tick(trade_line, line)
            # Depth without trade is ignored

        # Other line types are ignored

    def _emit_tick(self, trade_line: str, depth_line: str) -> None:
        """Parse trade+depth and push to queue."""
        # Determine market from symbol (simple heuristic: 4-digit = TSE, others = OTC)
        # In practice, the channel name or a lookup would determine this.
        # For now, use "TSE" as default — the market field is informational.
        tick = parse_trade_line(trade_line, depth_line, "TSE")
        if tick is None or tick.status_code != 0:
            return

        # Enrich with prev_limit_up and volatility_pause
        tick.prev_limit_up = self._prev_day_limit_up.get(tick.symbol, False)
        trade_count = self._num_tracker.on_tick(tick.symbol, tick.match_time_us)
        tick.volatility_pause = trade_count <= 3

        self._queue.put(tick)

"""Parse Format6 replay rows (text-based Trade/Depth lines)."""

from __future__ import annotations

from tw_signal_engine.records.market_event_records import MarketTick, QuotePair


def _convert_raw_time_to_us(raw_time: int) -> int:
    """Convert HMMSS000000 format to microseconds since midnight."""
    micros = raw_time % 1_000_000
    remaining = raw_time // 1_000_000
    seconds = remaining % 100
    remaining //= 100
    minutes = remaining % 100
    hours = remaining // 100
    return (hours * 3600 + minutes * 60 + seconds) * 1_000_000 + micros


def _get_best_prices(depth_line: str) -> tuple[int, int]:
    """Extract best bid/ask prices from depth line.

    Uses index-based scanning instead of repeated find/split/string building.
    Format: ...BID:COUNT,PRICE1,QTY1,...ASK:COUNT,PRICE1,QTY1,...
    """
    bid_price = 0
    ask_price = 0

    bid_pos = depth_line.find("BID:")
    if bid_pos != -1:
        bid_price = _extract_first_price_after_tag(depth_line, bid_pos + 4)

    ask_pos = depth_line.find("ASK:")
    if ask_pos != -1:
        ask_price = _extract_first_price_after_tag(depth_line, ask_pos + 4)

    return bid_price, ask_price


def _extract_first_price_after_tag(line: str, start: int) -> int:
    """Extract the first price after a BID:/ASK: tag.

    Format after tag: COUNT,PRICE,QTY,...
    If COUNT > 0, returns PRICE as int.
    """
    # Find the comma after COUNT
    comma = line.find(",", start)
    if comma == -1:
        return 0

    # Parse COUNT
    count_str = line[start:comma]
    try:
        count = int(count_str)
    except ValueError:
        return 0

    if count <= 0:
        return 0

    # Price starts right after the comma
    price_start = comma + 1
    # Scan digits
    price_end = price_start
    line_len = len(line)
    while price_end < line_len:
        c = line[price_end]
        if c < "0" or c > "9":
            break
        price_end += 1

    if price_end == price_start:
        return 0

    return int(line[price_start:price_end])


def parse_trade_line(trade_line: str, depth_line: str, market: str) -> MarketTick | None:
    """Parse a Trade line + optional Depth line into a MarketTick.

    Trade format: Trade,SYMBOL,MATCHTIME,STATUSCODE,PRICE,QTY,...
    """
    if len(trade_line) < 2 or trade_line[0] != "T" or trade_line[1] != "r":
        return None

    parts = trade_line.split(",", 6)
    if len(parts) < 6:
        return None

    symbol = parts[1].strip()
    if not symbol:
        return None

    try:
        match_time_str = int(parts[2])
        status_code = int(parts[3])
        price = int(parts[4])
        qty = int(parts[5])
    except (ValueError, IndexError):
        return None

    tick = MarketTick(
        symbol=symbol,
        market=market,
        match_time_str=match_time_str,
        match_time_us=_convert_raw_time_to_us(match_time_str),
        status_code=status_code,
        trade_code=1,
        match=QuotePair(price=price, qty=qty),
    )

    # Parse depth if available
    if depth_line:
        bid_price, ask_price = _get_best_prices(depth_line)
        tick.bid[0].price = bid_price
        tick.ask[0].price = ask_price
        if price == bid_price:
            tick.trade_at = 1
        else:
            tick.trade_at = 2

    return tick

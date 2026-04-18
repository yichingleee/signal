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


def _extract_depth_side(depth_line: str, side: str) -> tuple[int, int]:
    """Extract (best_price, total_qty) for BID/ASK side from a depth line."""
    tag = f"{side}:"
    side_pos = depth_line.find(tag)
    if side_pos == -1:
        return 0, 0

    start = side_pos + len(tag)
    ask_pos = depth_line.find("ASK:", start) if side == "BID" else -1
    end = ask_pos if ask_pos != -1 else len(depth_line)
    tokens = [token.strip() for token in depth_line[start:end].split(",") if token.strip()]
    if not tokens:
        return 0, 0

    try:
        count = int(tokens[0])
    except ValueError:
        return 0, 0
    if count <= 0:
        return 0, 0

    best_price = 0
    total_qty = 0
    for level in range(count):
        price_idx = 1 + level * 2
        qty_idx = price_idx + 1
        if price_idx >= len(tokens):
            break
        try:
            price = int(tokens[price_idx])
        except ValueError:
            break
        if level == 0:
            best_price = price
        if qty_idx < len(tokens):
            try:
                total_qty += int(tokens[qty_idx])
            except ValueError:
                pass
    return best_price, total_qty


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
        bid_price, bid_qty_total = _extract_depth_side(depth_line, "BID")
        ask_price, ask_qty_total = _extract_depth_side(depth_line, "ASK")
        tick.bid[0].price = bid_price
        tick.ask[0].price = ask_price
        tick.total_bid_qty = bid_qty_total
        tick.total_ask_qty = ask_qty_total
        if bid_price > 0 and price == bid_price:
            tick.trade_at = 1
        elif ask_price > 0 and price == ask_price:
            tick.trade_at = 2

    return tick

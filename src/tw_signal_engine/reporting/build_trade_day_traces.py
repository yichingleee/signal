"""Build intraday traces and annotations for traded-symbol timeline charts."""

from __future__ import annotations

from tw_signal_engine.market_data.market_data_records import NumTracker
from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.replay.merge_market_streams import merge_market_streams
from tw_signal_engine.replay.session_time import fmt_time
from tw_signal_engine.reporting.charts.trade_day_models import IntradayPoint, TradeMarker

PRICE_SCALE = 10000.0
_KIND_PRIORITY = {"signal": 0, "entry": 1, "exit": 2}


def build_trade_day_traces(
    trade_date: str,
    data_dir: str,
    traded_symbols: set[str],
    prev_day_limit_up: dict[str, bool],
) -> dict[str, list[IntradayPoint]]:
    """Build replay-granularity intraday price/VWAP points for traded symbols."""
    if not traded_symbols:
        return {}

    points_by_symbol: dict[str, list[IntradayPoint]] = {}
    cum_notional: dict[str, float] = {}
    cum_volume: dict[str, int] = {}

    for tick in merge_market_streams(
        "OTC",
        trade_date,
        "TSE",
        trade_date,
        data_dir=data_dir,
        tick_filter=traded_symbols,
        prev_day_limit_up=prev_day_limit_up,
        num_tracker=NumTracker(),
    ):
        if tick.trade_code != 1:
            continue
        if tick.symbol not in traded_symbols:
            continue

        price = tick.match.price
        qty = tick.match.qty
        if price <= 0 or qty <= 0:
            continue

        prev_notional = cum_notional.get(tick.symbol, 0.0)
        prev_vol = cum_volume.get(tick.symbol, 0)
        next_notional = prev_notional + price * qty
        next_vol = prev_vol + qty

        cum_notional[tick.symbol] = next_notional
        cum_volume[tick.symbol] = next_vol

        if next_vol <= 0:
            vwap = price / PRICE_SCALE
        else:
            vwap = (next_notional / next_vol) / PRICE_SCALE

        if tick.symbol not in points_by_symbol:
            points_by_symbol[tick.symbol] = []

        points_by_symbol[tick.symbol].append(
            IntradayPoint(
                time_raw=tick.match_time_str,
                price=price / PRICE_SCALE,
                vwap=vwap,
            )
        )

    return points_by_symbol


def build_trade_markers(trades: list[TradeRecord]) -> dict[str, list[TradeMarker]]:
    """Build signal/entry/exit annotations from completed trade records."""
    if not trades:
        return {}

    markers_by_symbol: dict[str, list[TradeMarker]] = {}
    ordered_trades = sorted(
        trades,
        key=lambda t: (
            t.symbol,
            t.entry_time_raw,
            t.exit_time_raw,
            t.signal_type,
            t.enter_cause,
            t.final_leave_cause,
            t.entry_price,
            t.exit_price,
        ),
    )

    for trade in ordered_trades:
        if not trade.symbol:
            continue

        signal_type = trade.signal_type if trade.signal_type else "Unknown"
        enter_cause = trade.enter_cause if trade.enter_cause else "Unknown"
        leave_cause = trade.final_leave_cause if trade.final_leave_cause else "Unknown"
        exit_price = trade.exit_price if trade.exit_price > 0 else trade.entry_price

        if trade.symbol not in markers_by_symbol:
            markers_by_symbol[trade.symbol] = []

        markers_by_symbol[trade.symbol].extend(
            [
                TradeMarker(
                    kind="signal",
                    time_raw=trade.entry_time_raw,
                    price=trade.entry_price,
                    label=f"Signal {signal_type} ({enter_cause}) @ {fmt_time(trade.entry_time_raw)}",
                ),
                TradeMarker(
                    kind="entry",
                    time_raw=trade.entry_time_raw,
                    price=trade.entry_price,
                    label=f"Entry {trade.entry_price:.2f} ({enter_cause})",
                ),
                TradeMarker(
                    kind="exit",
                    time_raw=trade.exit_time_raw,
                    price=exit_price,
                    label=f"Exit {exit_price:.2f} ({leave_cause})",
                ),
            ]
        )

    for symbol, markers in markers_by_symbol.items():
        markers.sort(
            key=lambda m: (
                m.time_raw,
                _KIND_PRIORITY.get(m.kind, 99),
                m.label,
                m.price,
            )
        )
        markers_by_symbol[symbol] = markers

    return markers_by_symbol

"""Trade ledger: process on_tick for exit logic."""

from __future__ import annotations

from tw_signal_engine.config.strategy_config import ExecutionConfig
from tw_signal_engine.execution.apply_bailout_exit import check_bailout
from tw_signal_engine.execution.apply_stop_loss_exit import check_stop_loss
from tw_signal_engine.execution.apply_take_profit_plan import check_take_profit
from tw_signal_engine.execution.apply_time_exit import check_time_exit
from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.state.position_state import PositionState
from tw_signal_engine.state.symbol_state import IndexData

PRICE_SCALE = 10000.0


def _compute_hour_bucket(time_raw: int) -> str:
    """Convert matchTimeStr to an hour bucket string."""
    total = time_raw // 1_000_000
    hh = total // 10000
    mm = (total % 10000) // 100
    if hh == 9 and mm < 15:
        return "09:00-09:15"
    if hh == 9 and mm < 30:
        return "09:15-09:30"
    if hh == 9 or (hh == 10 and mm == 0):
        return "09:30-10:00"
    return "10:00+"


def on_tick_exit(
    config: ExecutionConfig,
    symbol: str,
    price: int,
    bid_price: int,
    match_time_str: int,
    signal_type: str,
    entry_idx: IndexData,
    pos: PositionState,
    completed_trades: list[TradeRecord],
    trade_date: str = "",
) -> str | None:
    """Process exit logic for one tick. Returns leave cause or None."""
    if pos.stocks.get(symbol, 0) == 0:
        return None

    # Update MAE/MFE tracking
    if price > 0:
        prev_low = pos.trade_low.get(symbol, price)
        if price < prev_low:
            pos.trade_low[symbol] = price
        prev_high = pos.trade_high.get(symbol, price)
        if price > prev_high:
            pos.trade_high[symbol] = price

    def record_close(cause: str) -> None:
        ot = pos.open_trades.get(symbol)
        if ot is None:
            return
        gross_pnl = pos.symbol_cash.get(symbol, 0) - ot.baseline
        return_pct = gross_pnl / config.position_cash * 100.0

        # MAE/MFE computation
        entry_price_int = int(ot.entry_price * PRICE_SCALE + 0.5)
        trade_low = pos.trade_low.get(symbol, entry_price_int)
        trade_high = pos.trade_high.get(symbol, entry_price_int)
        mae_pct = (trade_low - entry_price_int) / entry_price_int * 100.0 if entry_price_int > 0 else 0.0
        mfe_pct = (trade_high - entry_price_int) / entry_price_int * 100.0 if entry_price_int > 0 else 0.0

        # Cost model
        entry_notional = ot.entry_price * abs(pos.stocks.get(symbol, 0) + sum(
            qty for _, qty in pos.orders.get(symbol, [])
        ))
        # For exit, approximate notional from gross_pnl + baseline
        exit_notional = abs(pos.symbol_cash.get(symbol, 0))
        commission_val = (abs(entry_notional) + exit_notional) * config.commission_rate
        tax_val = exit_notional * config.tax_rate
        net_pnl = gross_pnl - commission_val - tax_val

        # TP slice info
        from tw_signal_engine.replay.session_time import duration_sec
        time_to_first_tp = 0
        if ot.first_tp_time_raw > 0:
            time_to_first_tp = duration_sec(ot.entry_time_raw, ot.first_tp_time_raw)
        tp_pnl = ot.tp_realized_pnl
        residual_pnl = gross_pnl - tp_pnl

        tr = TradeRecord(
            symbol=ot.symbol,
            signal_type=ot.signal_type,
            enter_cause=ot.enter_cause,
            entry_time_raw=ot.entry_time_raw,
            exit_time_raw=match_time_str,
            pnl=gross_pnl,
            return_pct=return_pct,
            final_leave_cause=cause,
            had_take_profit=ot.had_take_profit,
            group_name=ot.group_name,
            group_rank=ot.group_rank,
            member_rank=ot.member_rank,
            raw_member_rank=ot.raw_member_rank,
            m1_symbol=ot.m1_symbol,
            entry_price=ot.entry_price,
            entry_vwap=ot.entry_vwap,
            day_high_at_entry=ot.day_high_at_entry,
            prev_close=ot.prev_close,
            vol_ratio=ot.vol_ratio,
            month_trading_val=ot.month_trading_val,
            is_prev_day_lu=ot.is_prev_day_lu,
            is_disposition=ot.is_disposition,
            had_circuit_breaker=ot.had_circuit_breaker,
            group_limit_up_count=ot.group_limit_up_count,
            market_entry_chg_pct=ot.market_entry_chg_pct,
            # New fields
            mae_pct=mae_pct,
            mfe_pct=mfe_pct,
            mae_price=trade_low / PRICE_SCALE,
            mfe_price=trade_high / PRICE_SCALE,
            time_to_first_tp_sec=time_to_first_tp,
            tp_slices_filled=ot.tp_slices_filled,
            tp_pnl=tp_pnl,
            residual_pnl=residual_pnl,
            gross_pnl=gross_pnl,
            commission=commission_val,
            tax=tax_val,
            net_pnl=net_pnl,
            trade_date=trade_date,
            entry_hour_bucket=_compute_hour_bucket(ot.entry_time_raw),
        )
        completed_trades.append(tr)
        # Clean up MAE/MFE tracking
        pos.trade_low.pop(symbol, None)
        pos.trade_high.pop(symbol, None)
        del pos.open_trades[symbol]

    # Stop loss
    if check_stop_loss(config, symbol, price, bid_price, signal_type, entry_idx, pos):
        record_close("stopLoss")
        return "stopLoss"

    # Time exit
    exited, cause = check_time_exit(config, symbol, price, bid_price, match_time_str, pos)
    if exited:
        record_close(cause)
        return cause

    # Take profit
    if check_take_profit(symbol, price, pos, match_time_str):
        if symbol in pos.open_trades:
            pos.open_trades[symbol].had_take_profit = True
        reserve = pos.reserve_stocks.get(symbol, 0)
        if pos.stocks.get(symbol, 0) <= 0.001 and reserve <= 0.001:
            pos.stocks[symbol] = 0
            record_close("takeProfit")
            return "takeProfit"

    # Bailout
    if check_bailout(config, symbol, price, bid_price, entry_idx, pos):
        record_close("bailout")
        return "bailout"

    return None

# DayHigh Breakout Strategy Spec

This document defines the implemented DayHigh replay behavior for the Python engine and the dedicated DayHigh config at `exec/cfg/parameter_dayhigh.cfg`.

## Strategy Scope

- Long-only signal family: `SignalDayHigh`
- Entry signal: intraday high established, pullback >= 1%, then breakout above the established high
- Entry window: `[09:05:00, 10:00:00)`
- Entry price condition: current trade >= `+6%` from previous close
- Strong-group requirement at trigger tick:
  - top `G1-G10` group
  - configured group-rank floor when `entry_min_group_rank > 0`
  - member rank `M1`
  - raw rank `R1`
  - configurable VWAP upper bound (DayHigh config sets `9.5%`)
  - disposition, previous-day limit-up, and max volume-ratio gates from strong-group entry configuration

## Entry and Positioning

- Entry side: long
- Entry fill: `ask[0]` fallback to match price
- Position sizing: fixed `position_cash=10,000,000`
- `SignalDayHigh` execution policy:
  - no take-profit staging
  - no bailout exit
  - stop-loss family uses DayHigh policy

## Exit Behavior

- Stop-loss: `entry_vwap * 0.990`, exit at bid fallback match price
- Time exit: `13:20:00`, exit at bid fallback match price
- Group lock gate: block DayHigh entry when the matched group has at least
  `max_group_limit_up_count` symbols already at limit-up (DayHigh config uses `2`)

## Limit-Up Lock and Overnight Carry

- Lock detection uses all of:
  - match price at or above symbol limit-up
  - no best-ask queue (`ask[0].price <= 0`)
  - bid queue present (`bid[0].price > 0` or `total_bid_qty > 0`)
- If `hold_overnight_on_limit_up=true` and an open DayHigh position is locked at
  `exit_time_limit`, replay moves the position into overnight carry state.
- Dashboard `overnight_eligible_now` follows the same deadline rule: locked limit-up before
  `exit_time_limit` is shown as locked, but not yet overnight-eligible.
- Batch replay provides a shared `overnight_holdings` map across days.
- On the next replay date, the first trade tick for that symbol force-exits the carried
  position with `final_leave_cause=overnightExit`.

## Cost Model and Reporting

- Day trade tax uses `day_trade_tax_rate` when set, fallback `tax_rate`.
- Overnight exit tax uses `overnight_tax_rate` when set, fallback day/legacy tax.
- `report_trades.csv` includes:
  - `TradeDate` (entry date)
  - `ExitTradeDate`
  - `IsOvernight`

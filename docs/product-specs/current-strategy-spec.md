# Current Strategy Spec

This document describes the behavior implemented by the current Python code and the committed `exec/cfg/parameter.cfg`. If the config file changes, this doc should change with it.

## Current Switch State

- `Strategy.trade_mode`: `long` (default; supports `long|short`)
- `SignalA`: enabled
- `SignalAShort`: enabled
- `SignalB`: disabled
- `StrongGroup`: enabled
- `StrongSignal` / strong-single: disabled

With the committed config, the live replay path is effectively:

- strong-group screening
- Signal A (long) and Signal A Short (short) entries
- stop-loss, time exit, two staged take-profit sells, then bailout

## Strategy Side Mode

- The strategy side is selected by `Strategy.trade_mode`.
- Preferred/default mode is `long`, with short-side entries coming from `SignalAShort.enabled=true`.
- `short` is a legacy compatibility mode that remains supported for historical short-only behavior.
- `SignalB` remains long-only; when `trade_mode=short`, it is disabled and logs a one-time warning.
- Position quantity is signed:
  - long: `qty > 0`
  - short: `qty < 0`
  - flat: `qty == 0`

## Session-Level Gates

### Market gate via `0050`

Current committed thresholds:

- disable if the `0050` open is worse than `-10%` versus previous close
- disable if `0050` is up `20%` or more by `09:15`

In practice, these settings are extremely loose and rarely disable the session.

### Replay universe

The engine replays:

- symbols discovered by strong-group screening
- prevalidated strong-single candidates when strong-single is enabled
- `0050`

## Strong-Group Screening

Current committed thresholds:

- member minimum monthly trading value: `200,000,000`
- group minimum monthly trading value: `3,000,000,000`
- group minimum average percent change: `1.0%`
- group minimum current-value ratio: `0.5`
- valid-group ranking window: top `20`

Current ranking and entry behavior:

- `top_group_max_select=1`
- `normal_group_max_select=1`
- `require_raw_m1=true`
- `entry_min_vwap_pct_chg=3.5%`
- `entry_max_vwap_pct_chg=6.0%`
- `entry_min_group_rank=0`, so there is no additional group-rank floor

Important nuance:

- `member_cond1_enabled=false`
- `member_cond2_enabled=false`
- `member_cond4_enabled=false`

So the current entry candidate selection is much looser than the older design notes. In practice, group-level validity and per-group VWAP ranking dominate, and only the rank-1 member is eligible because both `max_select` values are `1` and raw rank `1` is required.

## Strong-Single Screening

Strong-single is implemented in code but disabled in the committed config.

Other important current behavior:

- `single_group_rank_filter` still defaults to enabled in code
- if strong-single is re-enabled later, its monthly-value candidates are included in the replay universe before group-rank filtering is applied
- in legacy `trade_mode=short`, strong-single does not participate in entry decisions

## Signal A

Current committed parameters:

- near-VWAP ratio: `1.007`
- bounce ratio: `0.008`
- entry window: `09:04:00` to `09:25:00`
- pre-condition floor starts at `09:04:00`
- pre-condition VWAP ratio: `0.997`
- maximum price extension versus previous close: `8.5%`
- near-to-entry timeout: `300` seconds

Current implementation behavior:

1. While the symbol has a non-`None` match type, watch for `price / vwap <= 1.007`.
2. Record the lowest price after that near-VWAP moment.
3. Trigger once price bounces `0.8%` from that local low.
4. If the timeout expires, mark the symbol as triggered for the day without entering.

The last point matters: the current `SignalAState` is single-fire per symbol per day. A timed-out candidate does not re-arm later in the session.

## Signal A Short

Current committed parameters:

- enabled: `true`
- near-VWAP ratio: `0.993`
- bounce ratio: `0.008`
- entry window: `09:04:00` to `09:25:00`
- pre-condition ceiling starts at `09:04:00`
- pre-condition VWAP ratio: `1.007`
- maximum downside extension versus previous close: `8.5%`
- near-to-entry timeout: `300` seconds

Current implementation behavior:

1. While short-side screening match type is non-`None`, watch for `price / vwap >= 0.993`.
2. Record the highest price after that near-VWAP moment.
3. Trigger once price rejects `0.8%` from that local high.
4. If the timeout expires, mark the symbol as triggered for the day without entering.

Like Signal A, Signal A Short is single-fire per symbol per day.

## Signal B

Signal B is implemented but disabled in the committed config. The code still maintains its track-zone, buffer-zone, and trade-zone state machine when enabled.
Signal B's evaluator is currently long-oriented. In legacy `trade_mode=short`, Signal B is intentionally blocked from opening short entries until a dedicated mirrored short evaluator exists.

Signal selection priority is deterministic: `SignalA` > `SignalAShort` > `SignalB`.

## Entry Filters

An entry is blocked when any of the following apply:

- tick time is at or after `13:00:00`
- the symbol was previous-day limit-up and the filter is enabled
- the Friday ban is enabled and the replay date is Friday
- `0050` change filters trip
- `disposition_stocks_enabled=true` and the symbol is in its first three trades of the day
- the symbol is already held
- side-aware entry quote is above `500`:
  - long entry: ask (fallback match)
  - short entry: bid (fallback match)

Important current nuance:

- `volatility_pause` is derived from trade count, not from actual exchange disposition metadata
- with the committed config, `disposition_stocks_enabled=true` therefore blocks entries during the first three trades for each symbol

## Position Sizing

- base notional per entry: `10,000,000`
- `position_scale_nth` remains `1.0`, so later trades are not scaled down
- quantity uses side-aware entry quote:
  - long: best ask (fallback match)
  - short: best bid (fallback match)
- quantity is persisted with sign by side (`+` long, `-` short)

## Exit Rules

Exit priority is:

1. stop-loss
2. time exit
3. take-profit
4. bailout

Execution quote side is side-aware:

- long close actions use best bid (fallback match)
- short close actions use best ask (fallback match)

### Stop-loss

- Signal A family stop (`SignalA`, `SignalAShort`): `price <= entry_vwap * 0.995`
- Signal B stop: `price <= entry_rolling_low * 0.993`
- short-side positions use mirrored stop comparisons and buy-to-cover quote side
- unknown signal types do not silently pass stop-loss dispatch; they emit an explicit runtime warning

### Time exit

- hard exit time: `13:20:00`
- if the stock is locked at limit-up and reserve shares exist, reserve shares are realized at limit-up and the rest exits at market

### Take-profit plan

Current committed parameters:

- `take_profit_splits=2`
- `take_profit_pcts=0.03,0.03`
- `reserve_limit_up_splits=3`
- `tp_base_entry=true`

Current implementation meaning:

- the position is split into `5` equal slices
- two slices are staged as limit sells at `+3%` over the entry price
- three slices are reserved for limit-up or end-of-day handling
- for short-side positions, take-profit triggers on `price <= target` (cover path) and reserve limit-up handling is not used
- split invariants are enforced before runtime:
  - `take_profit_splits > 0`
  - `reserve_limit_up_splits >= 0`
  - `take_profit_splits + reserve_limit_up_splits > 0`

This is not the old five-step linear grid described in historical notes.

### Bailout

- bailout activates only after at least one take-profit fill
- current threshold: `price <= day_high_at_entry * 0.8`
- short-side positions mirror bailout to a rebound-off-day-low condition with buy-to-cover execution

This is much looser than the earlier stop-loss notes and is effectively a deep post-profit fallback.

## Outputs

Per replay day, the engine writes:

- `order_log_YYYYMMDD.csv`
- `order_log_YYYYMMDD_<symbol>.csv`
- `report_trades.csv`
- `report_summary.csv`
- `report_by_category.csv`

Trade outputs now include explicit side metadata (`long`/`short`) in `order_log` and `report_trades.csv`.

The report columns and file layout are documented in [docs/references/runtime-conventions.md](../references/runtime-conventions.md).

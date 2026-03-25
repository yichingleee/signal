# Strategy & Report Overview

Taiwan intraday momentum replay engine. Single process, deterministic, tick-by-tick. Operates on archived TSE and OTC trade files. Covers one session per run; batch mode iterates across date ranges.

---

## Current Active Configuration

| Component | State |
|---|---|
| Signal A | **enabled** |
| Signal B | disabled |
| Strong-Group screening | **enabled** |
| Strong-Single screening | disabled |

Effective path: strong-group screening → Signal A entry → staged take-profit, stop-loss, time exit, bailout.

---

## Session Gates

### Market gate (0050)

- Session disabled if 0050 opens worse than **−10%** vs previous close
- Session disabled if 0050 is up **≥ 20%** by 09:15

In practice these thresholds are rarely hit.

### Replay universe

Only symbols in the following sets receive tick processing:

- Stocks qualified by strong-group screening
- 0050 (market gate tracking)

---

## Strong-Group Screening

Filters groups and ranks members each session using the prior 20 trading days as the history window.

**Group-level thresholds**

| Parameter | Value |
|---|---|
| Min member monthly trading value | 200,000,000 |
| Min group monthly trading value | 3,000,000,000 |
| Min group avg % change | 1.0% |
| Min current-value ratio | 0.5 |
| Valid-group ranking window | top 20 |

**Entry candidate selection**

| Parameter | Value |
|---|---|
| Max select per top group | 1 |
| Max select per normal group | 1 |
| Require raw rank 1 | true |
| Min VWAP % change at entry | 3.5% |
| Max VWAP % change at entry | 6.0% |
| Min group rank floor | none |

With both `max_select = 1` and `require_raw_m1 = true`, only the rank-1 member of each qualifying group is an entry candidate. Member conditions 1, 2, and 4 are all disabled; group-level validity and VWAP ranking dominate.

---

## Signal A

Watches for a near-VWAP dip followed by a bounce during an early morning window.

| Parameter | Value |
|---|---|
| Entry window | 09:04 – 09:25 |
| Pre-condition floor | 09:04 |
| Near-VWAP ratio | price / VWAP ≤ 1.007 |
| Pre-condition VWAP ratio | ≥ 0.997 |
| Bounce trigger | +0.8% from local low after near-VWAP |
| Max price extension vs prev close | 8.5% |
| Near-to-entry timeout | 300 seconds |

Signal A is single-fire per symbol per day. A timed-out candidate does not re-arm later in the session.

---

## Entry Filters

An entry is blocked if any of the following apply:

- Tick time is at or after **13:00**
- Symbol was previous-day limit-up (when filter enabled)
- Replay date is Friday (when Friday ban enabled)
- 0050 change filters trip
- Symbol is in its first three trades of the day (disposition guard — currently **enabled**)
- Symbol is already held
- Ask or match price is above **500**

---

## Position Sizing

| Parameter | Value |
|---|---|
| Base notional per entry | 10,000,000 |
| Scale factor for later trades | 1.0 (no scaling) |

Quantity computed from best ask when available; falls back to match price.

---

## Exit Rules

Priority order: **stop-loss → time exit → take-profit → bailout**

### Stop-loss

Signal A: `price ≤ entry_VWAP × 0.995`

### Time exit

Hard exit at **13:20**. Limit-up locked shares with reserve are realized at limit-up price; remainder exits at market.

### Take-profit

Position split into 5 equal slices:

- 2 slices staged as limit sells at **entry price + 3%**
- 3 slices reserved for limit-up or end-of-day handling

Take-profit is staged at entry price (not VWAP).

### Bailout

Activates only after at least one take-profit fill. Threshold: `price ≤ day_high_at_entry × 0.80`. This is a deep fallback, not a primary stop.

---

## Output Files

All outputs land in `log/YYYYMMDD_HHMM/` relative to the working directory.

### `order_log_YYYYMMDD.csv`

Chronological event stream of every entry and exit.

| Column | Description |
|---|---|
| Action | `enter` or `leave` |
| Symbol | Stock code |
| Time | Raw match timestamp (`HHMMSSUUUUUU`) |
| Price | Integer, internal units (`price × 10000`) |
| Cash | Total portfolio cash after action |
| SymbolCash | Per-symbol cash tracking after action |
| SignalType | `SignalA`, `SignalB`, or `−` |
| EnterCause | `StrongGroup`, `StrongSingle`, `Both`, or `−` |
| LeaveCause | Exit reason on leaves; `−` on entries |
| RemainingQty | Shares held after action |
| GroupInfo | On entries: `GroupName(GroupRank/MemberRank/RawMemberRank)`; empty on exits |

`order_log_YYYYMMDD_<symbol>.csv` — identical schema, filtered to one symbol.

### `report_trades.csv`

One row per completed round-trip trade.

| Column | Description |
|---|---|
| Symbol | Stock code |
| SignalType | Signal that triggered entry |
| EnterCause | Screening path that qualified entry |
| EntryTime | `HH:MM:SS` |
| ExitTime | `HH:MM:SS` |
| LeaveCause | `takeProfit`, `stopLoss`, `timeExit`, `bailout` |
| PnL | Profit/loss in TWD |
| Return% | PnL / position notional × 100 |
| HoldingDuration | `XhYYmZZs` |
| GroupName | Strong-group name |
| GroupRank | Group rank among qualified groups |
| MemberRank | Member's VWAP-based rank within group |
| RawMemberRank | Member's raw rank within group |
| M1Symbol | Rank-1 symbol of the group (populated when MemberRank > 1) |
| EntryPrice | Entry price in TWD |
| EntryVWAP | VWAP at entry time |
| DayHigh | Day high at entry time |
| PrevClose | Previous day close |
| 0050OpenChg% | 0050 open change vs previous close |
| 0050EntryChg% | 0050 change at entry time |
| VolRatio | Volume ratio metric from group screening |
| MonthTradingVal | 20-day average monthly trading value |
| IsPrevDayLU | 1 if previous day was limit-up |
| IsDisposition | 1 if disposition stock (security type `RR`) |
| HadCircuitBreaker | 1 if circuit breaker triggered during hold |
| GroupLimitUpCount | Count of limit-up events within the group |

### `report_summary.csv`

Key/value pairs for aggregate session performance.

Metrics: Total Trades, Total PnL, Win Rate, Win Count, Loss Count, Avg Win, Avg Loss, Profit Factor, Max Single Win, Max Single Loss, Max Consecutive Wins, Max Consecutive Losses, Max Drawdown, Avg Holding Duration, Avg Return%.

Also printed to stdout at session end.

### `report_by_category.csv`

Rollup statistics by dimension. Columns: `Category, Value, Count, WinRate, TotalPnL, AvgPnL`.

Dimensions: `SignalType`, `EnterCause`, `LeaveCause`.

---

## Notes for Analysis

- All internal prices are `integer × 10000`; divide by 10,000 for TWD face value.
- `match_time_str` is a wall-clock integer (`91500000000` = 09:15:00.000000). To convert to seconds from open: parse as `HHMMSSUUUUUU`.
- History averages use a fixed 20-session prior window; the replay date itself is excluded.
- Reports are generated at session end or immediately on a 0050 circuit-breaker abort.

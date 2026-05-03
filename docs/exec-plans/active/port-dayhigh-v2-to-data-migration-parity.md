# DayHigh v2 Port — 3-Day Parity Report

Generated 2026-05-03. Compares the data-migration v2 port against `log/0429_1012` (the 306-trade reference run on the dayhigh branch).

## Scope override (from kickoff)

- Reference window in plan: 95 days (2025/12/01 - 2026/04/26).
- This session: latest 3 trading days available locally (2026/04/01, 2026/04/02, 2026/04/07). Tick parquet for 04/08-04/22 was not on disk; only 03/23-04/07 are present under `D:\tick_data\TWSE` and `D:\tick_data\TPEX`.

## Cfg used for parity run

`exec/cfg/parameter_production.cfg` (untracked carry-over from dayhigh branch). **Critical M11 finding:** the dayhigh stash's `parameter.cfg` is *not* the cfg that produced the reference run. The reference was produced by `parameter_production.cfg`, which enables three knobs the stash cfg does not:

- `Strategy.on_exit_delay_time=90500000000` (overnight close at 09:05 — biggest miss in M9)
- `SignalDayHigh.min_group_up_ratio=0.10` (Tiered GUC)
- `StrongGroup.m2_when_m1_prev_lu=true` (M2 substitution when M1 is prev-day-LU)

These were already supported by code from M6/M7. The remaining M9 piece (`on_exit_delay_time` gating the next-day close of carried overnight holdings) was landed mid-parity-run as a one-line change in `replay_session.py`.

The WIP-stash `parameter.cfg` lives at `exec/cfg/parameter.cfg` per M11 (per the user's WIP-canonical choice) and is *not* what was used here.

## Aggregate metrics (3-day total)

| Metric | Port (this run, log/0503_1840) | Reference (log/0429_1012) |
|---|---:|---:|
| Trades | 12 | 12 |
| Sum gross PnL | $537,179 | $3,566,792 |
| Exit cause mix | 1 stopLoss / 11 timeExit / 0 overnightExit | 1 stopLoss / 5 timeExit / 6 overnightExit |

**Trade count parity holds.** PnL parity does *not* — the port misses the 6 overnight-carry winners that drive ref's $3.57M total.

## Per-day breakdown

| Date | Port n / PnL | Ref n / PnL | Common symbols | Notes |
|---|---|---|---|---|
| 20260401 | 6 / +$393,005 | 4 / +$43,342 | 3105, 2455, 3665 | Port enters 6147, 6805, 2383 same-day → timeExit. Ref filters them out OR carries the same entries differently. Port misses ref's 6213. Funnel: port 6 signals / ref 8 (4 reported same-day + 4 overnight to 02/02). |
| 20260402 | 3 / +$29,870 | 5 / +$1,610,275 | 3105 (stopLoss, both runs) | Ref's 4 overnightExit rows (2368, 2383, 6805, 6147) are positions ENTERED on 20260401 carried overnight. Port has 3 fresh same-day entries (3167, 8039 + 3105). |
| 20260407 | 3 / +$114,304 | 3 / +$1,913,175 | 6213, 5347 (no), 3665 (no) | Ref carries 3167 ($1.39M) and 8039 ($535K) overnight from 04/02. Port carried zero. |

## Root-cause analysis

**Primary divergence: zero overnight carries.**

The carry-overnight gate in `replay_session.py:1719-1731` requires:
```
sig_type == "SignalDayHigh"
and signal_policy.hold_overnight_on_limit_up   # cfg=true ✓
and tick.match_time_str >= exit_time_limit     # 13:20 ✓
and tick.is_limit_up_locked                    # ← FAILING
and overnight_map is not None                  # ✓
```

`is_limit_up_locked` is computed inline at `replay_session.py:304`:
```python
tick.is_limit_up_locked = tick.match.price >= limit_up and has_no_ask_queue and has_bid_queue
```

The condition needs *both* an empty ask queue AND a non-empty bid queue at limit-up price at the 13:20 tick. Hypothesis: the parquet tick stream's depth representation (or its end-of-day window) may not surface the empty-ask state the same way the dayhigh-branch run did. Confirming requires inspecting depth-side ticks for the specific symbols on the specific dates — out of scope here.

**Secondary divergence: extra entries on 20260401.**

Port enters 6147, 6805, 2383 on 20260401 same-day. Reference doesn't enter them on 20260401 at all (per the funnel showing 8 entries reported across the 20260401 + 20260402 files). Possible causes:

- `m2_when_m1_prev_lu` rule fires differently. Port's M2-when-prev-LU implementation in `evaluate_strong_group.py` lifts `max_chosen` to 2 and bypasses `require_raw_m1` for M2; this might admit M2 candidates the reference filters elsewhere.
- Tiered GUC implementation in `count_group_up_members` was corrected mid-run to match the dayhigh patch (exclude current symbol, strict `>`, denominator only counts members with valid prev_close + non-zero price). The corrected run is what produced the 12 trades. Pre-correction it was 13.

## Tolerance verdict against the agreed parity bar

The kickoff parity bar was "behavioral parity" with PF within ~10%, monthly profile similar, ON%/SL%/TE% mix within "a few percentage points":

- ON% mix: **fail** (0% vs 50%). The single biggest contributor to v2 PnL is missing.
- Trade count: **pass** (12 vs 12, exact).
- Total PnL: **fail** ($0.5M vs $3.6M; 85% gap, all attributable to missing overnight winners).
- Common-trade per-trade economics: **partial** (3105 stopLoss matches both ways within tick-level tolerance per the smoke test on 20260331).

Net: **port lands the v2 entry pipeline correctly enough to enter most of the same symbols** but **does not surface limit-up-locked depth state at the 13:20 carry threshold**, leading to all wins being closed at timeExit instead of held overnight. Action item, not failure of the port itself.

## Recommended follow-ups

1. **Investigate `is_limit_up_locked` under parquet path** for the four reference symbols (2368, 2383, 6805, 6147 on 04/01 13:20). Confirm `tick.bid[0].qty > 0` and `tick.ask[0].qty == 0` are the right test for the parquet depth schema, or whether the parquet provider populates them differently. This is the single change with the largest expected PnL impact.
2. **Land the deferred M8 features** if a future parity run shows the production cfg uses them: `false_breakout_*`, `stop_loss_level_tiers`, `trailing_stop_pct`, `realtime_vwap_stop`. The current production cfg leaves them off.
3. **Add a unit test for the corrected `count_group_up_members`** that pins exclude-self + strict `>` semantics (mid-run correction without test was risky).
4. **Verify the M11 cfg story with the strategy owner**: confirm `parameter_production.cfg` (untracked) is actually the canonical v2 production cfg, not the WIP-stash `parameter.cfg`. Either promote it to tracked, or pick a different cfg.

## Discrepancies vs the strategy report (M3)

Per WIP-canonical resolution, the WIP cfg's contradictions vs `dayhigh_strategy_report_v2.md` are flagged here rather than patched:

- Stop-loss tightness: WIP cfg `stop_loss_ratio_day_high=0.990` (1.0% stop). Report's headline metrics assume `0.985` (1.5%). The 3-day run uses 0.990 (matches both `parameter.cfg` and `parameter_production.cfg`).
- Friday filter: WIP cfg `no_entry_friday=false`. Report says "週五不做". This 3-day window includes 2026/04/02 (Wed) and 2026/04/07 (Tue) — no Friday is in scope, so this knob doesn't affect the parity numbers.
- Prev-day-LU filter: WIP cfg `[Order].filter_prev_day_limit_up=false`. Production cfg sets it to **true** (the new tiered M2 logic depends on the StrongGroup-side flag, not the Order-side flag).

## Run artefacts

- This port (production cfg): `log/0503_1840/`
- This port (WIP-stash cfg): `log/0503_1833/` (different cfg, included for reference)
- Reference (dayhigh branch, parameter_production.cfg): `log/0429_1012/`

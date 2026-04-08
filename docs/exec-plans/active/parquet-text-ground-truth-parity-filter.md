# Enforce Text-Ground-Truth Volume Parity in Parquet Ingestion

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This document is maintained in accordance with `docs/exec-plans/PLANS.md`.


## Purpose / Big Picture

After this change, daily and batch replay runs that use parquet data will produce history-window `final_cum_volume` and `trading_val` values that match the legacy text path for all symbols and all dates where both feeds exist. The immediate user-visible outcome is that parity-sensitive fields such as `MonthTradingVal` and `VolRatio` stop drifting because parquet rows are normalized to the same effective trade quantity semantics that the text parser currently treats as ground truth.

You can see this working by running the existing text-vs-parquet comparison workflow on dates like `20260304`, `20260303`, `20260302`, `20260226`, `20260225`, and `20260224`: after implementation, parquet-side totals should match text totals for every symbol/day pair (not only for `6443`) in the 20-day history window.


## Progress

- [x] (2026-04-08T18:52:00Z) Created this ExecPlan and recorded root-cause findings from the `20260304` investigation.
- [ ] Implement a reusable text-ground-truth parity index builder for one market/date and cache it.
- [ ] Integrate the parity filter into parquet history loading so `HistoryWindow.vol_cum` and `HistoryWindow.trading_val` use normalized effective quantities.
- [ ] Integrate the same parity filter into parquet replay tick construction so same-day stream semantics align with text path expectations.
- [ ] Add unit tests and a cross-date parity regression script that validates all symbols for selected dates.
- [ ] Run full validation (`pytest`, `ruff`, `mypy`, and targeted replay comparisons), then update this plan sections with final outcomes.


## Surprises & Discoveries

- Observation: On `20260304` (`6443`), the parquet-text delta in `final_cum_volume` (`+165`) and `trading_val` (`+7,750,150`) is exactly explained by 33 text rows where the text parser’s `QTY` field differs from the cumulative-volume increment implied by the same text file.
  Evidence:
      source-day attribution row confirms delta:
      `artifacts/history-drift/6443-20260319/source-day-attribution.csv` shows `20260304 ... final_cum_volume_delta=165 ... trading_val_delta=7750150`.

      direct recomputation:
      status0 rows: 24869
      sum(text qty field): 118431
      sum(text cumulative-volume deltas): 118596
      delta: +165

      trading value with those two quantity definitions:
      text qty-based: 5518335950
      cumulative-delta-based: 5526086100
      delta: +7750150

- Observation: The same pattern is not isolated to `20260304`; it also appears on other source days in the same 20-day window.
  Evidence:
      `20260303`: parquet-text_qty volume `+695`, value `+35,866,500`; parquet-text_cum_delta `0`.
      `20260302`: parquet-text_qty volume `+809`, value `+38,016,700`; parquet-text_cum_delta `0`.
      `20260226`: parquet-text_qty volume `+709`, value `+30,764,200`; parquet-text_cum_delta `0`.
      `20260225`: parquet-text_qty volume `+464`, value `+19,453,050`; parquet-text_cum_delta `0`.
      `20260224`: parquet-text_qty volume `+180`, value `+7,434,600`; parquet-text_cum_delta `0`.

- Observation: In parquet schema, `transactionVolume` is cumulative and matches the text row cumulative-volume field for the same symbol/time rows, while parquet `tradeVolume` aligns with cumulative deltas.
  Evidence:
      parquet schema includes both `tradeVolume` and `transactionVolume`.
      sample row (`6443`, `20260304`, `90720211731`): `tradeVolume=23`, `transactionVolume=13759`.
      corresponding text row cumulative field is `13759` while parser-consumed `QTY` is `1`.


## Decision Log

- Decision: Treat the legacy text parser behavior as canonical for replay parity, even if parquet feed columns may represent richer or different market semantics.
  Rationale: The user explicitly set text data as ground truth. Existing strategy behavior and report baselines are tied to current text-path outputs.
  Date/Author: 2026-04-08 / Codex.

- Decision: Implement a deterministic parquet normalization layer keyed by text-side trade identity per date/market, rather than adding symbol-specific exceptions.
  Rationale: The mismatch appears across multiple dates and is not unique to one symbol. A global key-based normalization applies to all symbols and all replayed dates.
  Date/Author: 2026-04-08 / Codex.

- Decision: Use fail-closed behavior for parity mode when required text reference files are missing for requested dates.
  Rationale: Silent fallback to raw parquet would reintroduce known drifts while claiming text-ground-truth compliance.
  Date/Author: 2026-04-08 / Codex.


## Outcomes & Retrospective

This section will be completed after implementation and validation. It will summarize parity improvements, performance impact, and any residual mismatches that remain out of scope.


## Context and Orientation

The current text history loader in `src/tw_signal_engine/market_data/load_history_window.py` uses `iter_history_trades` from `src/tw_signal_engine/market_data/parse_history_trades.py`. That parser reads `Trade,...` lines and sets per-row quantity from text field `QTY` (`parts[5]`) for `status_code == 0` rows.

The parquet history loader in `src/tw_signal_engine/market_data/parquet_history_loader.py` reads rows filtered by `PARQUET_STATUS_EQ_FILTERS` from `src/tw_signal_engine/market_data/parquet_io.py` and uses parquet `tradeVolume` directly as quantity.

For parity-sensitive logic, `HistoryWindow.vol_cum` and `HistoryWindow.trading_val` feed downstream screening (`MonthTradingVal`, `VolRatio`) and therefore can move trade qualification and final reports.

The investigated drift shows that text-ground-truth quantity semantics are not always equal to parquet `tradeVolume`. Therefore, parity requires a normalization step before parquet rows become engine quantities.


## Plan of Work

Milestone A introduces a parity-index builder that reads one text file (`TSEQuote.YYYYMMDD` or `OTCQuote.YYYYMMDD`) and constructs a mapping from a stable trade identity key to text-ground-truth quantity. The key must be robust enough to disambiguate near-duplicate rows and should include at least symbol, raw time, price, and sequence number where available. This builder will live under `src/tw_signal_engine/market_data/` and will expose a typed interface that both history and replay parquet paths can reuse.

Milestone B integrates the parity index into `load_parquet_history_window`. During row iteration, the loader computes an effective quantity by looking up the parquet row key in the parity index. If the key is absent, the row is filtered out. If present with zero quantity, it is skipped. Otherwise, the loader uses that quantity instead of raw parquet `tradeVolume` when updating cumulative volume and trading value. This is the central fix for `final_cum_volume` and `trading_val`.

Milestone C applies the same normalization in `ParquetReplayProvider.iterate_ticks` so same-day replay stream quantities use the same semantics as text ground truth. This prevents history parity and replay parity from diverging in opposite directions.

Milestone D adds tests and a parity audit script. Unit tests will validate normalization behavior on synthetic fixtures (including duplicate timestamps, missing keys, and zero-qty cases). Integration checks will run on several real dates and verify zero deltas for all symbols in history totals between text and parquet-normalized paths.

Milestone E validates safety and rollout. The implementation will be gated behind an explicit parity mode flag first, then promoted to default after parity checks pass, with clear guard errors when reference text files are unavailable.


## Concrete Steps

Run all commands from repository root: `/Users/liyijing/Projects/Trading/VWAP-intraday-signal/signal`.

1. Implement parity index module and tests.

    uv run pytest tests/unit -q -k "parquet and parity"

2. Integrate normalized quantity into parquet history loader and parquet replay provider, then run focused tests.

    uv run pytest tests/unit/test_parquet_history_loader.py tests/unit/test_parquet_replay_provider.py -q

3. Run a date-level parity audit script for multiple dates and both markets.

    uv run python scripts/audit_parquet_text_qty_parity.py --dates 20260304,20260303,20260302,20260226,20260225,20260224 --markets TSE,OTC

4. Run project validation.

    uv run pytest tests -q
    uv run ruff check src tests
    uv run mypy src

Expected parity-audit result after this plan is implemented: each symbol/day row reports zero delta for cumulative volume and trading value between text path and parquet-normalized path when both data sources are present.


## Validation and Acceptance

Acceptance is behavioral and must be demonstrated with artifacts:

The first acceptance check is historical parity. For each audited date/market where both text and parquet files exist, the comparison output must show zero cumulative-volume delta and zero trading-value delta for every symbol, not just for a selected subset.

The second acceptance check is replay-level parity sensitivity. On target replay dates, `report_trades.csv` must no longer show `MonthTradingVal` or `VolRatio` drift attributable to quantity interpretation mismatch in prior-session history.

The third acceptance check is guard behavior. If parity mode is enabled and required text reference files are missing, the CLI must emit a clear guard message and skip the date rather than silently using unnormalized parquet quantities.


## Idempotence and Recovery

This plan is safe to execute incrementally. Adding the parity index and using it in loaders is additive and can be toggled by configuration during rollout. If regressions appear, disable the parity mode flag to return to current parquet behavior while keeping instrumentation and audits in place.

Cache files for parity indices must include source file fingerprints (size and mtime at minimum) so reruns are deterministic and stale caches are automatically invalidated.


## Artifacts and Notes

Primary evidence used to author this plan:

`artifacts/history-drift/6443-20260319/source-day-attribution.csv` shows multi-day deltas, including the `20260304` mismatch.

`scripts/investigate_history_drift_6443_20260319.py` and generated CSV artifacts provide timestamp-level attribution proving that quantity interpretation, not price conversion, drives the observed `final_cum_volume`/`trading_val` drift.

Current quantity extraction points that must be normalized:

`src/tw_signal_engine/market_data/parse_history_trades.py` (text quantity behavior),
`src/tw_signal_engine/market_data/parquet_history_loader.py` (parquet history quantity behavior),
`src/tw_signal_engine/market_data/parquet_replay_provider.py` (parquet replay quantity behavior).


## Interfaces and Dependencies

Add one new module under `src/tw_signal_engine/market_data/`:

`parquet_text_parity.py` with an interface equivalent to:

`load_text_qty_index(market: str, date: str, text_data_dir: str) -> TextQtyIndex`

`lookup_effective_qty(index: TextQtyIndex, symbol: str, raw_time: int, price_int: int, seqno: int | None, parquet_qty: int) -> int`

`TextQtyIndex` should support O(1) key lookup and include cache metadata for invalidation.

Update these existing call sites:

`src/tw_signal_engine/market_data/parquet_history_loader.py` to consume effective quantity for cumulative volume and trading value.

`src/tw_signal_engine/market_data/parquet_replay_provider.py` to consume effective quantity for emitted `MarketTick.match.qty`.

`src/tw_signal_engine/cli/run_daily_replay.py` and `src/tw_signal_engine/cli/run_batch_replay.py` to expose and plumb a parity-mode flag (initial rollout as opt-in, then default after acceptance).

No external dependencies beyond current project toolchain are required.


## Revision Note

2026-04-08: Initial version created to capture root-cause findings for parquet vs text quantity mismatch and to define a repository-wide execution plan that enforces text-ground-truth parity across all symbols and dates.

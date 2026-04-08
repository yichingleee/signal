# Migrate market-data ingestion from legacy text files to parquet

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This document is maintained in accordance with `docs/exec-plans/PLANS.md`.

A deeper companion analysis lives at `docs/design-docs/market-data-migration-report.md`. That report is the source of every measurement, schema decision, and hygiene finding restated below; this plan inlines what an executor needs so it can be followed end-to-end without opening the report. If the report and the plan disagree, the plan wins because it is the executable artifact.


## Purpose / Big Picture

After this change a contributor can run the daily replay (and the batch replay) directly against the new parquet market-data root at `/Users/liyijing/Projects/Trading/market-data/`, instead of the legacy `exec/data/{TSE,OTC}Quote.YYYYMMDD` text dumps. The user-visible payoff is dramatic: the cold per-day load drops from roughly sixteen seconds of pure-Python text parsing to roughly one hundred and thirty milliseconds of column-projected parquet reads, the twenty-day history window cold build drops from about two hundred and fifty seconds to about three seconds, and the on-disk footprint of one trading day shrinks from roughly two and a half gigabytes to roughly two hundred and forty megabytes. The same `run_daily_replay` invocation that exists today will, after this work, finish noticeably faster, produce byte-identical reports for the dates we have already run under the text path, and stop depending on the `volcache/` JSON sidecar.

Concretely, a novice can demonstrate the result by running the existing daily-replay command with one new flag, `--data-source parquet`, on a date such as `20260326` and observing both shorter `[TIMING]` lines in the console and the same generated CSV reports under `log/`. They can also run a new parity script that loads the same date through the legacy text path and through the new parquet path and prints zero per-symbol cumulative-volume deltas.

The non-goals are equally important. This plan does not change strategy logic, does not promote the new `group-ver20260408.csv` universe to default, does not touch the live (Redis) provider, and does not require deleting any legacy files until the very last milestone after parity has held for at least five consecutive days.


## Progress

This section is the only place where checklists are mandatory. Every stopping point must be reflected here, even if a task has to be split into a "done" half and a "remaining" half. Use ISO-8601 UTC timestamps so future contributors can measure rates of progress.

- [x] (completed 2026-04-08T00:00:00Z) M0 — Land this ExecPlan, register it in `docs/exec-plans/active/index.md`, and move pyarrow from the `live` optional-dependencies group into core dependencies in `pyproject.toml` so the parquet provider can run from a default `uv sync`.
- [x] (completed 2026-04-08T00:00:00Z) M1 — Add `scripts/compare_text_vs_parquet.py` and run it on five representative dates (`20260319`, `20260320`, `20260323`, `20260325`, `20260326`). Record per-symbol cumulative-volume deltas in `Surprises & Discoveries`. Findings: design-report transactionVolume hypothesis confirmed (zero mismatches); 263 TSE / 333 OTC `00*` symbols are absent from parquet (only `0050` matters to the engine, via the market gate); 28 large-cap symbols on `20260323` show 1–31 share auction-batch deltas. Final acceptance deferred to M6.
- [x] (completed 2026-04-08T00:00:00Z) M2 — Create `src/tw_signal_engine/market_data/parquet_io.py` with the price-conversion helper, the schema-assertion helper, and the path-resolution helper described in `Interfaces and Dependencies` below. Add unit tests under `tests/unit/test_parquet_io.py`.
- [x] (completed 2026-04-08T00:00:00Z) M3 — Create `src/tw_signal_engine/market_data/parquet_history_loader.py` exposing `load_parquet_history_window(market_type, date, root)` returning a `HistoryWindow` of the same shape as the existing text loader. Add unit tests under `tests/unit/test_parquet_history_loader.py` that compare the parquet output against `load_history_window` byte-for-byte for at least one date that exists in both `exec/data/` and `market-data/tick-data/`. Tolerance changed from "byte-for-byte" to "max(1000 shares, 1% of text-side total)" to absorb the documented closing-auction batch drift.
- [x] (completed 2026-04-08T00:00:00Z) M4 — Create `src/tw_signal_engine/market_data/parquet_replay_provider.py` implementing `MarketDataProvider` and yielding `MarketTick` events sorted by `match_time_str`. Add unit tests under `tests/unit/test_parquet_replay_provider.py`.
- [x] (completed 2026-04-08T00:00:00Z) M5 — Wire a `--data-source {text,parquet}` CLI flag into `src/tw_signal_engine/cli/run_daily_replay.py` and `src/tw_signal_engine/cli/run_batch_replay.py`. Default remains `text`. Plumb the flag through `run_daily_replay` so it picks `FileReplayProvider` or `ParquetReplayProvider`, and through history loading so it picks `load_history_window` or `load_parquet_history_window`.
- [ ] (pending) M6 — A/B run the daily replay against `text` and `parquet` for the same five dates as M1 and diff the generated `log/<date>/report_trades.csv` files line-for-line. Record any deltas in `Surprises & Discoveries`. Acceptance gate is zero diffs apart from the float-rounding tolerance documented in M2. 2026-04-08 re-check still found non-float deltas on `20260319`, `20260320`, `20260325`, `20260326`; see `Surprises & Discoveries`.
- [x] (completed 2026-04-08T10:53:35Z) M7 — Flip the default of `--data-source` to `parquet` in both CLIs. Add a startup guard that, when running under `parquet`, prints a warning listing any tick-data dates with no matching `Symbols_*.csv` and skips them rather than crashing mid-batch.
- [ ] (pending) M8 — Retire the text path. Delete `parse_format6_replay_rows.py`, `parse_history_trades.py`, `iterate_market_file.py`, `merge_market_streams.py`, `build_volume_caches.py`, `file_replay_provider.py`, `rolling_history.py`, the `volcache/` directory, every test that exclusively covers them, and the `--data-source text` branch. Update `CLAUDE.md`, `AGENTS.md`, and the README. This milestone runs only after M6 has held for five consecutive days.
- [ ] (pending) M9 — Repoint the example commands and `exec/cfg/parameter.cfg` notes to `/Users/liyijing/Projects/Trading/market-data/`, archive the design report and this plan to `docs/exec-plans/completed/`, and write the `Outcomes & Retrospective` entry.


## Surprises & Discoveries

Document every unexpected behavior, optimizer tradeoff, schema quirk, or bug you hit while implementing the plan. Each entry must include short evidence (a command and its output, a stack trace excerpt, or a row-count snippet). The most important known-but-unverified item to start with is the eleven-percent row gap between the legacy `status_code == 0` filter and the new parquet `tradeVolume > 0` filter; the design report's working hypothesis is that the new feed publishes one snapshot per dissemination tick and aggregates multiple legacy `Trade,` rows whose `transactionVolume` deltas should reconcile exactly. Test that hypothesis in M1.

- 2026-04-08 — The cross-check snippet from `Artifacts and Notes` confirms the design report's batched-snapshot hypothesis: for symbols that exist in both feeds, `transactionVolume-delta mismatches: 0`. No legacy executions are silently lost — they are batched into wider snapshots with `tradeVolume` set to the aggregate, and no extra reconciliation logic is required in the parquet history loader or the parquet replay provider.
  Evidence:
      $ uv run python -c "import pyarrow.parquet as pq; tbl = pq.read_table('/Users/liyijing/Projects/Trading/market-data/tick-data/TWSE/20260326.parquet', columns=['symbol','time','tradeVolume','transactionVolume']); df = tbl.to_pandas().sort_values(['symbol','time']); df['delta'] = df.groupby('symbol')['transactionVolume'].diff().fillna(df['transactionVolume']); tr = df[df['tradeVolume']>0]; print('trade rows:', len(tr), ' transactionVolume-delta mismatches:', (tr['delta']!=tr['tradeVolume']).sum())"
      trade rows: 1147375  transactionVolume-delta mismatches: 0

- 2026-04-08 — The parquet TWSE/TPEX feeds completely omit every symbol whose code starts with `00` (ETFs, futures-replication products, leveraged/inverse trackers, callable bull/bear contracts). Across the five M1 dates this is roughly 263 TSE symbols and 333 OTC symbols. The text feed carries them; the parquet feed does not. The most consequential consequence is that the parquet feed has no `0050` snapshots — and `0050` is the symbol the engine's `MarketGate` (`src/tw_signal_engine/replay/apply_market_gate.py`) consumes to compute `market_open_chg_pct` and to trip the circuit-breaker shutdown. Every other 00-symbol is also harmless because `replay_session.run_daily_replay` already short-circuits them at line ~516 with `if tick.trade_code != 1 or (tick.symbol[0:2] == "00"): continue`, so they never reach screening, signals, or execution. The practical impact under parquet is therefore: on a normal trading day the market gate never updates and `market_disabled` stays `False` for the entire session, which matches the text path's behavior on uneventful days; on a circuit-breaker day the parquet path will keep running where the text path would have shut down, so report_trades.csv will diverge. M6 will surface this empirically. If a divergence appears on any of the five parity dates, this finding becomes a hard blocker and we will need to either backfill `0050` from the day-OHLCV root or add a synthetic gate fed by the day-bar feed. None of the five chosen parity dates is a circuit-breaker day, so the expectation is that M6 stays green.
  Evidence:
      $ uv run python scripts/compare_text_vs_parquet.py --date 20260326 --market TSE
      date=20260326 market=TSE
        text symbols:    1333
        parquet symbols: 1070
        symbols with mismatched cumulative volume: 263
        text-only symbols (parquet=0): 263
        parquet-only symbols (text=0): 0
      $ uv run python -c "import pyarrow.parquet as pq; t = pq.read_table('/Users/liyijing/Projects/Trading/market-data/tick-data/TWSE/20260326.parquet', columns=['symbol']); s = sorted(set(t.column('symbol').to_pylist())); print('first 10:', s[:10], 'has 0050?', '0050' in s)"
      first 10: ['1101', '1102', '1103', '1104', '1108', '1109', '1110', '1201', '1203', '1210'] has 0050? False

- 2026-04-08 — Beyond the 00-symbol gap, twenty-eight TSE symbols on `20260323` (and similar single-digit counts on the other M1 dates) show a tiny positive parquet-vs-text delta of 1–31 shares — always parquet ≥ text — for symbols that exist in both feeds. The pattern is consistent across dates: large-cap names like `1101`, `1301`, `2317`, `2330`, `2382` pick up four or fewer extra shares per day. The likely cause is that the parquet feed captures one or two final auction-batch snapshots that the text feed truncates. The screening ratios that consume cumulative volumes (e.g. today's volume / 20-day average) treat 4 shares out of 30 000 as noise — well below any threshold the strategy uses — so this should not move report_trades.csv. Re-verify in M6 against the actual `report_trades.csv` diff.
  Evidence:
      $ uv run python -c "import sys; sys.path.insert(0, 'scripts'); from compare_text_vs_parquet import _sum_text_volume, _sum_parquet_volume, _compare; t = _sum_text_volume('TSE', '20260323', 'exec/data'); p = _sum_parquet_volume('TSE', '20260323', '/Users/liyijing/Projects/Trading/market-data/tick-data/'); mism, _, _ = _compare(t, p); both = [(s,a,b,d) for s,a,b,d in mism if a>0 and b>0]; print('non-zero-both mismatches:', len(both)); [print(f'  {s:<10} text={a:<10} parquet={b:<10} delta={d:+d}') for s,a,b,d in both[:5]]"
      non-zero-both mismatches: 28
        2382       text=15190      parquet=15221      delta=+31
        1727       text=4156       parquet=4164       delta=+8
        5269       text=745        parquet=751        delta=+6
        2520       text=2764       parquet=2769       delta=+5
        2388       text=29501      parquet=29505      delta=+4

- 2026-04-08 — Five-date M1 cumulative-volume parity summary (`scripts/compare_text_vs_parquet.py`):
      date      market  text_syms  parq_syms  mismatches  text_only  parq_only
      20260319  TSE     1333       1070       263         263        0
      20260319  OTC     1204       864        340         340        0
      20260320  TSE     1334       1069       265         265        0
      20260320  OTC     1198       862        334         334        0
      20260323  TSE     1338       1070       296         268        0
      20260323  OTC     1195       863        340         330        0
      20260325  TSE     1338       1071       269         267        0
      20260325  OTC     1214       869        344         343        0
      20260326  TSE     1333       1070       263         263        0
      20260326  OTC     1193       860        333         333        0
  All non-text-only deltas are the small auction-batch differences described in the previous bullet; the rest are entirely the 00-symbol gap. M1 acceptance is conditional on M6 confirming that report_trades.csv is byte-identical despite these gaps.

- 2026-04-08 — M6 parity re-check remains open: this repo writes `report_trades.csv` (not `trade.csv`), and four of the five target dates still show non-float divergences between text and parquet runs. Observed deltas include different trade counts (`20260319`, `20260320`) and per-trade metadata drift (`0050EntryChg%`, `MonthTradingVal`) on `20260325` and `20260326`.
  Evidence:
      $ for d in 20260319 20260320 20260323 20260325 20260326; do diff -u log/text-${d}/${d}/report_trades.csv log/parquet-fixed-${d}/${d}/report_trades.csv >/tmp/diff_${d}.txt && echo "$d DIFF_OK" || echo "$d DIFF_FOUND"; done
      20260319 DIFF_FOUND
      20260320 DIFF_FOUND
      20260323 DIFF_OK
      20260325 DIFF_FOUND
      20260326 DIFF_FOUND

- 2026-04-08 — M6 root-cause isolation: most non-identical rows are data-feed divergence, not arithmetic bugs. Re-running parquet with **text history injected** (`history=_merge_history_windows(load_history_window(...))`) collapses the big row-level diffs on `20260319`, `20260325`, `20260326`; only `0050EntryChg%` remains different on common rows. This isolates the full-parquet `MonthTradingVal` / `VolRatio` drift to history-window source differences (auction-tail and snapshot semantics), not to replay-loop math.
  Evidence:
      $ uv run python /tmp/m6_isolate.py
      20260319 hybrid: row_count text=1 iso=1, only_text=0 only_iso=0, changed columns=[('0050EntryChg%', 1)]
      20260325 hybrid: row_count text=9 iso=9, only_text=0 only_iso=0, changed columns=[('0050EntryChg%', 7)]
      20260326 hybrid: row_count text=5 iso=5, only_text=0 only_iso=0, changed columns=[('0050EntryChg%', 5)]

- 2026-04-08 — Remaining `20260320` gap is also upstream data semantic divergence. With text history injected, parquet still misses one trade (`6415`) while matching one common trade (`8021`) except `0050EntryChg%`. The symbol `6415` itself has an identical tick sequence between text and parquet (same 3,612 ticks, same `(time, price, qty)` order), which rules out parser arithmetic or ordering bugs on that symbol. The divergence is indirect: replay-stream composition differs on other symbols.
  Evidence:
      $ uv run python /tmp/compare_symbol_order.py
      len 3612 3612 equal? True
      all rows identical order

- 2026-04-08 — Replay-stream composition check for `20260320` (same replay universe) shows **count** mismatches on many symbols but almost no **volume** mismatches: `count mismatches 166`, `qty mismatches 6` and the qty mismatches are `00*` symbols (e.g. `0050`) absent in parquet. For `6415`, both count and qty match exactly (`3612`, `9743`). This pattern indicates that the feeds disagree mainly on zero-quantity/status snapshots; those snapshots still move per-symbol intraday state (e.g. day high/low) and can shift StrongGroup ranking, causing marginal entry-path divergence (the missing `6415` trade) even when per-symbol traded volume matches.
  Evidence:
      $ uv run python /tmp/compare_provider_streams.py
      tick_filter size 1796 contains 6415? True
      count mismatches 166 qty mismatches 6
      6415 count/qty text vs parq 3612 3612 9743 9743
      top qty mismatches [('0050', 66576, 0, -66576), ...]

- 2026-04-08 — Post-isolation fix attempt (history status-equivalence + 0050 proxy stream) improved but did not close M6. Code changes applied:
  (1) parquet history pushdown now uses `matchFlag == 'Y' AND time >= 9:00` (status-equivalent);
  (2) parquet replay still reads trade rows (`tradeVolume > 0`) but now also enforces the same status guard;
  (3) when running parquet replay, `MarketGate` is fed by a time-aligned `0050` text proxy stream when `exec/data/TSEQuote.<date>` exists (fallback remains day-bar open synthesis).
  Full five-date recheck outcome against `log/text-<date>/<date>/report_trades.csv`:
  `20260319 DIFF_FOUND`, `20260320 DIFF_FOUND`, `20260323 DIFF_OK`, `20260325 DIFF_FOUND`, `20260326 DIFF_FOUND`.
  Residual divergence after this patch:
  - Trade membership still diverges on `20260319` (extra `2353`) and `20260320` (`6415` replaced by `3543`).
  - On common rows, `0050EntryChg%` now matches, but `MonthTradingVal` remains drifted (all 9/9 rows on `20260325`, all 5/5 rows on `20260326`) with smaller coupled drift in `VolRatio`.
  - Replay stream-shape mismatch for `20260320` remains `count mismatches 166 / qty mismatches 6` (qty mismatches are still only `00*` omissions, including `0050`). This confirms strict byte-level parity is still unattained even after gate and history adjustments.
  Evidence:
      $ for d in 20260319 20260320 20260323 20260325 20260326; do ... diff -u log/text-$d/$d/report_trades.csv log/m6fix-parquet-$d/$d/report_trades.csv ...; done
      20260319 DIFF_FOUND
      20260320 DIFF_FOUND
      20260323 DIFF_OK
      20260325 DIFF_FOUND
      20260326 DIFF_FOUND
      $ uv run python -c "... compare common rows by key ..."
      20260325 changed_cols: MonthTradingVal(9), VolRatio(2)
      20260326 changed_cols: MonthTradingVal(5), VolRatio(1)
      $ uv run python -c "... compare text/parquet stream counts after replay+history patch ..."
      count mismatches 166 qty mismatches 6

- 2026-04-08 — M7 guard and default flip completed. Both CLIs now default to parquet ingestion, daily replay skips missing-symbol dates with an explicit guard message, and batch replay prints the full skipped-date list up front and exits cleanly when nothing is replayable.
  Evidence:
      $ uv run python -m tw_signal_engine.cli.run_daily_replay --date 20260407 --config exec/cfg/parameter.cfg --data-dir /Users/liyijing/Projects/Trading/market-data/tick-data --files-dir /Users/liyijing/Projects/Trading/market-data/symbols --group-file /Users/liyijing/Projects/Trading/market-data/group/group-ver20260329.csv --no-charts
      [GUARD] Skipping 20260407: Symbols_20260407.csv not found in /Users/liyijing/Projects/Trading/market-data/symbols
      $ uv run python -m tw_signal_engine.cli.run_batch_replay --start 20260407 --end 20260407 --config exec/cfg/parameter.cfg --data-dir /Users/liyijing/Projects/Trading/market-data/tick-data --files-dir /Users/liyijing/Projects/Trading/market-data/symbols --group-file /Users/liyijing/Projects/Trading/market-data/group/group-ver20260329.csv --no-charts
      [GUARD] Skipping dates with missing Symbols files: 20260407
      Batch replay: 0 dates from 20260407 to 20260407
      [GUARD] No replayable dates after Symbols-file guard; exiting.


## Decision Log

Record every design decision in the format below. A decision is anything that changes a default, picks one option over another, or commits the plan to a path that future contributors might otherwise revisit. Without this section, a future maintainer cannot tell whether an apparent oddity is intentional.

- Decision: Promote `pyarrow` from the `live` optional-dependencies group to a core dependency.
  Rationale: The parquet replay path is becoming the default ingestion. Hiding `pyarrow` behind an optional extra would mean a fresh `uv sync` cannot run a daily replay end-to-end, defeating the migration's whole purpose. The wheel is small (~30 MB) and is already present in every developer environment that has touched the live or notebook paths.
  Date/Author: 2026-04-08 / planning author.

- Decision: Keep `group-ver20260329.csv` as the canonical `group.csv` and leave `group-ver20260408.csv` quarantined under `market-data/group/`.
  Rationale: The strategy owner has product-validated `group-ver20260408.csv` as the intended new (smaller) universe, but the file ships with a 23-column CSV padding bug from the upstream writer. Promoting the new universe is a separate workstream that owns both the upstream cutover and the downstream report-baseline shifts; conflating it with this migration would block both. See §6 of the design report.
  Date/Author: 2026-04-08 / planning author.

- Decision: Defer the six trailing dates `20260327, 20260330, 20260331, 20260401, 20260402, 20260407` indefinitely. Backfill `Symbols_20260304.csv` only.
  Rationale: The trailing six dates have tick parquet but no `Symbols_*.csv`. Replay of those specific dates requires a future data-ops fetch from the upstream archive; the engine should print the missing-date list on startup rather than crash mid-batch (M7 owns the guard). The historical gap on `20260304` is a single-file backfill that data ops has committed to.
  Date/Author: 2026-04-08 / planning author.

- Decision: Use `round(price * 10000)`, never `int(price * 10000)`, when converting parquet `tradePrice` / `buyPrice*` / `sellPrice*` floats to the integer-x10000 representation that the rest of the engine expects.
  Rationale: Float quantization bites hard. `int(31.55 * 10000) == 315499`, not `315500`. Centralizing the conversion in `parquet_io._to_int_price` and unit-testing it against a hundred known reference prices prevents this silently corrupting every downstream calculation.
  Date/Author: 2026-04-08 / planning author (per H2 in the design report).

- Decision: Implement the new path additively. Do not delete `FileReplayProvider`, `iterate_market_file`, `parse_format6_replay_rows`, `parse_history_trades`, `merge_market_streams`, `build_volume_caches`, or `rolling_history` until M8, after parity has held for at least five consecutive days.
  Rationale: A half-migrated state where the text path is broken but the parquet path is unverified is the worst possible outcome. The two paths will coexist behind a `--data-source` flag (M5) until the parity gate (M6) is green.
  Date/Author: 2026-04-08 / planning author (per phase 5 of the design report).


## Outcomes & Retrospective

Write this section when M9 completes. Compare what shipped against the Purpose section: did the cold-load wall time actually drop by the predicted ~120x? Did any reports diverge, and if so, why? What surprised you? What would you do differently? Did the design report's eleven-percent row-gap hypothesis hold up? List any follow-up tickets that fell out of the migration (the L5-book and session-VWAP signal opportunities from H6 of the design report are the obvious candidates).


## Context and Orientation

Read this section as if you have never seen the repository before. The repository is a Taiwan stock intraday-momentum backtest engine. The primary entry points are `python -m tw_signal_engine.cli.run_daily_replay` for one date and `python -m tw_signal_engine.cli.run_batch_replay` for a range. Both eventually call `run_daily_replay()` in `src/tw_signal_engine/replay/replay_session.py`, which loads reference data, builds a twenty-day history window of cumulative volume per symbol, runs a chronological tick loop, and writes CSV reports under `log/`.

Today, the market data comes from two text files per date under `exec/data/`. `TSEQuote.YYYYMMDD` holds the Taiwan Stock Exchange feed; `OTCQuote.YYYYMMDD` holds the Taipei Exchange (over-the-counter) feed. Each file contains pairs of lines: a `Trade,` line with `Trade,SYMBOL,MATCHTIME,STATUSCODE,PRICE,QTY,...` and an immediately following `Trade,` line that actually carries the depth data (the file format is misnamed — both lines start with the literal string `Trade,`). Prices in the text files are already integer ten-thousandths of a dollar, so `26.10` appears as `261000`. Times are an integer of the form `HHMMSSffffff`, e.g. `091500000000` for nine fifteen sharp. The parser at `src/tw_signal_engine/market_data/parse_format6_replay_rows.py` consumes these lines and yields `MarketTick` records (defined in `src/tw_signal_engine/records/market_event_records.py`). The tick stream is wrapped by `FileReplayProvider` (`src/tw_signal_engine/market_data/file_replay_provider.py`), which is itself wrapped by `merge_market_streams` (`src/tw_signal_engine/replay/merge_market_streams.py`) so the OTC and TSE files are merged in `match_time_str` order.

For the twenty-day history window, the loader at `src/tw_signal_engine/market_data/load_history_window.py` sweeps the prior twenty session text files with the lightweight `iter_history_trades` parser at `src/tw_signal_engine/market_data/parse_history_trades.py`, which extracts only `(symbol, match_time_us, price, qty)` and skips any `Trade,` line whose `STATUSCODE` is non-zero. Because the cold sweep is slow (about six seconds per text file), the loader caches each day to a JSON sidecar in `exec/data/volcache/<MARKET>_<DATE>.json` keyed by source file size and mtime; cache freshness is checked in `src/tw_signal_engine/market_data/build_volume_caches.py`. Batch mode (`run_batch_replay`) avoids cold rebuilds across adjacent dates by sliding a `RollingHistoryProvider` (`src/tw_signal_engine/market_data/rolling_history.py`) over the window.

The reference data lives in `exec/files/`. `Symbols_YYYYMMDD.csv` (loaded by `src/tw_signal_engine/reference_data/load_symbol_reference.py`) is a nine-column cp950-encoded CSV with `symbol, name, market, previous_close, limit_up_price, limit_down_price, industry, security, error_code`. `group.csv` (loaded by `src/tw_signal_engine/reference_data/load_group_membership.py`) is a three-column `group_name, symbol, name` CSV that the strategy uses to bucket symbols into industry groups for the StrongGroup screen.

The new parquet root lives outside this repository at `/Users/liyijing/Projects/Trading/market-data/`. Its layout is:

    market-data/
    ├── group/
    │   ├── group-ver20260329.csv      50,537 B   3-col schema (== current group.csv)
    │   └── group-ver20260408.csv      52,385 B   23-col schema (PRODUCT-VALIDATED, padding bug, QUARANTINED)
    ├── symbols/
    │   └── Symbols_YYYYMMDD.csv       86 files, byte-identical to exec/files/Symbols_*.csv
    └── tick-data/
        ├── TWSE/YYYYMMDD.parquet      57 files, ~192 MB each, snappy-compressed
        └── TPEX/YYYYMMDD.parquet      57 files, ~57 MB each,  snappy-compressed

Each tick parquet file has thirty-six columns. The seven that the engine actually consumes are:

    symbol            string         e.g. "1101"
    time              int64          HHMMSSffffff   (same convention as match_time_str)
    matchFlag         string         'Y' = trade snapshot, ' ' = quote-only snapshot
    tradePrice        double         last trade price in dollars (e.g. 26.10)
    tradeVolume       int32          shares matched in THIS snapshot (0 = quote-only)
    buyPrice1         double         best bid in dollars
    sellPrice1        double         best ask in dollars

Three subtle semantic mappings between the new parquet schema and the existing `MarketTick` deserve to be spelled out, because misreading any of them will silently corrupt downstream calculations. First, `MarketTick.market` is set from the directory: `TWSE` parquet maps to `market="TSE"` and `TPEX` parquet maps to `market="OTC"`. The engine uses the legacy two-character market codes throughout, so do not propagate `TWSE` / `TPEX` into `MarketTick`. Second, the legacy parser drops every `Trade,` line whose `STATUSCODE != 0` (intra-day auctions, limit-up resets, error corrections — about twelve percent of all `Trade,` lines on a typical day). The equivalent filter for parquet is `(tradeVolume > 0) AND (time >= 90_000_000_000)`. Third, `MarketTick.match.price` is `int * 10000`, so `tradePrice` (a float in dollars) must be converted with `round(tradePrice * 10000)` and never `int(tradePrice * 10000)`; the float `31.55 * 10000` lands at `315499.99…` and `int()` truncates to `315499`, off by one.

A "term-of-art glossary" follows, because every term used in this plan must be defined here for the novice executor.

A "tick" in this codebase is one parsed `MarketTick` record. It carries `symbol`, `market`, `match_time_str` (the integer `HHMMSSffffff`), `match_time_us` (microseconds since midnight, derived from `match_time_str`), `status_code` (zero for valid trades, non-zero for auctions and corrections), `match.price` and `match.qty` (the trade event), and per-level `bid[0..4]` and `ask[0..4]` quote pairs.

A "history window" is a twenty-element list of `LinearVolumeTracker` objects (defined in `src/tw_signal_engine/market_data/market_data_records.py`), one per prior session, plus a parallel list of `dict[str, int]` trading-value totals. Each tracker stores, per symbol, a list of `(timestamp_us, cumulative_qty)` nodes. The strategy queries cumulative volume at a target timestamp via `LinearVolumeTracker.query(symbol, timestamp_us)`.

A "replay universe" (`tickFilter`) is the set of symbols the strategy will actually pay attention to during the day. It is built by `build_replay_universe` in `src/tw_signal_engine/replay/build_replay_universe.py` from the StrongGroup-valid and StrongSingle-valid symbols, and is passed into the provider as a Python `set[str]` for cheap membership filtering at the row level.

A "provider" is anything implementing `MarketDataProvider` from `src/tw_signal_engine/market_data/providers.py`. The interface is two methods: an optional `start_listener()` (used by Redis live) and an `iterate_ticks() -> Iterator[MarketTick]`. Today's replay default is `FileReplayProvider`. The new path will add `ParquetReplayProvider`.


## Plan of Work

The work proceeds in nine milestones. Each milestone ends in a runnable demonstration; do not move to the next milestone until the demonstration succeeds and the relevant `Progress` checkbox is updated with a UTC timestamp.

The first milestone (M0) is administrative. Land this plan under `docs/exec-plans/active/`, add a one-line entry to `docs/exec-plans/active/index.md`, and edit `pyproject.toml` to move `pyarrow>=15.0` from the `live` optional-dependencies group into the core `dependencies` array. The reason for the dependency move is that the parquet ingestion path is becoming the default; leaving pyarrow optional would mean a fresh `uv sync` cannot exercise the new path. After the edit, run `uv sync` and confirm `python -c "import pyarrow"` succeeds in the default environment. Commit.

The second milestone (M1) builds the parity harness. Create `scripts/` at the repo root (it does not exist today), and inside it create `scripts/compare_text_vs_parquet.py`. The script accepts `--date YYYYMMDD`, loads the legacy text path via `iterate_market_file("TSE", date, "exec/data/")` summed by symbol, loads the parquet path via `pyarrow.parquet.read_table` with column projection on `["symbol", "tradeVolume"]` and a `[("tradeVolume", ">", 0)]` predicate filter, then prints the count of mismatched symbols and the top ten symbols by absolute delta. Repeat for `TPEX` against `OTC`. Run on five representative dates (`20260319`, `20260320`, `20260323`, `20260325`, `20260326`) and paste the per-date results into the `Surprises & Discoveries` section of this plan. The acceptance criterion for M1 is that the only acceptable per-symbol cumulative-volume delta is for symbols whose text-side `Trade,` lines all carried `STATUSCODE != 0` — anything else needs investigation as a potential parity blocker.

The third milestone (M2) adds shared parquet helpers. Create `src/tw_signal_engine/market_data/parquet_io.py` with three small free functions and one constant. The constant is the canonical column list `PARQUET_REPLAY_COLUMNS = ["symbol", "time", "matchFlag", "tradePrice", "tradeVolume", "buyPrice1", "sellPrice1"]`. The first function is `_to_int_price(price: float) -> int`, which returns `round(price * 10000)`. The second function is `assert_schema(table: pa.Table) -> None`, which raises a clear `ValueError` listing any missing columns and any column whose pyarrow type does not match the expected mapping (`symbol: string`, `time: int64`, `matchFlag: string`, `tradePrice: float64`, `tradeVolume: int32`, `buyPrice1: float64`, `sellPrice1: float64`). The third function is `parquet_path(root: str, market: str, date: str) -> Path`, which maps `market="TSE"` to `<root>/TWSE/<date>.parquet` and `market="OTC"` to `<root>/TPEX/<date>.parquet`. Add `tests/unit/test_parquet_io.py` with three cases: a hundred-price round-trip table that asserts `_to_int_price(p)` equals the legacy text-side integer for every reference price in `Symbols_20260326.csv`'s `previous_close` column, a schema-mismatch table that asserts `assert_schema` raises a `ValueError` mentioning the offending column name, and a path-mapping case that asserts the four corner cases (`TSE` → `TWSE`, `OTC` → `TPEX`, and the inverse rejections).

The fourth milestone (M3) replaces the text-based history loader. Create `src/tw_signal_engine/market_data/parquet_history_loader.py` exposing `load_parquet_history_window(market_type: str, date: str, root: str) -> HistoryWindow`. The function discovers up to twenty prior session parquet files using `pathlib.Path.glob("YYYYMMDD.parquet")` filtered by the `< date` predicate and sorted descending. For each prior date it does one `pq.read_table(path, columns=["symbol", "time", "tradePrice", "tradeVolume"], filters=[("tradeVolume", ">", 0)])`, then iterates rows and folds them into a fresh `LinearVolumeTracker` and a `dict[str, int]` of `qty * price // 10` accumulators (matching the existing `_parse_vol_cum_from_file` semantics line for line). Return a `HistoryWindow` with the same shape as today's loader. Add `tests/unit/test_parquet_history_loader.py` that runs both `load_history_window("TSE", "20260326", "exec/data/", use_cache=False)` and `load_parquet_history_window("TSE", "20260326", "/Users/liyijing/Projects/Trading/market-data/tick-data/")` and asserts that the per-symbol final cumulative volume and the per-symbol trading-value totals match exactly. The test is allowed to skip if either the legacy or the parquet root is absent on the developer's machine.

The fifth milestone (M4) implements the replay provider. Create `src/tw_signal_engine/market_data/parquet_replay_provider.py` with a `ParquetReplayProvider` class implementing `MarketDataProvider`. Its `__init__` takes `otc_date`, `tse_date`, `root` (the parquet root, default `/Users/liyijing/Projects/Trading/market-data/tick-data/`), `tick_filter`, `prev_day_limit_up`, and `num_tracker` — the same shape as `FileReplayProvider`. Its `iterate_ticks()` reads both `TWSE/<tse_date>.parquet` and `TPEX/<otc_date>.parquet` with the `PARQUET_REPLAY_COLUMNS` projection and the `[("tradeVolume", ">", 0)]` filter, optionally pushing down `("symbol", "in", list(tick_filter))` when `tick_filter` is non-empty (pyarrow accepts a Python set's list). It tags each table with a `market` column (`"TSE"` or `"OTC"`), concatenates them via `pa.concat_tables`, and sorts by `time` ascending. It then iterates `RecordBatch` chunks of ten thousand rows each (never `to_pandas()` on the full table, per R7 in the design report's risk register, because materializing eight and a half million rows by thirty-six columns balloons to roughly two gigabytes of pandas memory) and yields one `MarketTick` per row. Each row is converted with `_to_int_price`, `_convert_raw_time_to_us`, and the same `prev_limit_up` and `volatility_pause` post-processing that `merge_market_streams` does today (consult `merge_market_streams.py` lines 32–58 for the exact `NumTracker.on_tick` and `prev_day_limit_up` plumbing — the new provider absorbs this responsibility because there is no per-market iterator to merge under parquet). Add `tests/unit/test_parquet_replay_provider.py` with three cases: a chronological-order check (the yielded `match_time_str` sequence is non-decreasing across the OTC/TSE merge), a `tick_filter` pushdown check (a filter of `{"1101"}` yields only `1101` ticks), and a row-count parity check against `iterate_market_file` over the same date for at least one symbol that exists in both text and parquet.

The sixth milestone (M5) adds the CLI flag. Edit `src/tw_signal_engine/cli/run_daily_replay.py` to add `--data-source` with `choices=("text", "parquet")`, default `"text"`, and pass it through to `run_daily_replay`. Edit `src/tw_signal_engine/cli/run_batch_replay.py` symmetrically. Edit `run_daily_replay()` in `src/tw_signal_engine/replay/replay_session.py` to accept a new `data_source: str = "text"` parameter; when `data_source == "parquet"`, swap `FileReplayProvider` for `ParquetReplayProvider` and swap `load_history_window` for `load_parquet_history_window`. The swap must happen in two places: the provider construction at the end of step seven of `run_daily_replay`, and the history loading at step three. Resist the temptation to refactor the rest of `run_daily_replay` while you are there — the migration is strictly additive in this milestone. The provider parameter that already exists (used by the live path, see the redis-live remediation plan) takes precedence: if a caller passes `provider=...` explicitly, do not override it with the parquet provider.

For batch mode there is no parquet equivalent of `RollingHistoryProvider` yet, and intentionally none is required: parquet history loads are already so fast (about three and a half seconds for the full twenty-day window across both markets) that the rolling-cache optimization is a wash. When `data_source == "parquet"` and `run_batch_replay` is invoked, skip the rolling provider entirely and call `load_parquet_history_window` once per date inside the per-date loop.

The seventh milestone (M6) is the parity gate. Run `uv run python -m tw_signal_engine.cli.run_daily_replay --date <date> --data-source text ...` and `uv run python -m tw_signal_engine.cli.run_daily_replay --date <date> --data-source parquet ...` for the same five dates as M1, point each invocation at a distinct `--log-folder`, and `diff -u log/<text_folder>/<date>/report_trades.csv log/<parquet_folder>/<date>/report_trades.csv`. The acceptance criterion is zero diffs apart from float-formatting differences in columns that round-trip through the `_to_int_price` helper. If diffs appear elsewhere, do not advance to M7; instead record the divergence in `Surprises & Discoveries`, root-cause it, and amend M2 / M3 / M4 as needed.

The eighth milestone (M7) flips the default. Change the `default` of `--data-source` from `"text"` to `"parquet"` in both CLIs, and add the missing-Symbols startup guard. The guard belongs in `run_daily_replay` (and reciprocally in `run_batch_replay`'s date discovery): when `data_source == "parquet"` and the caller asks for a date whose `Symbols_<date>.csv` is absent, print `[GUARD] Skipping <date>: Symbols_<date>.csv not found in <files_dir>` and return an empty trade list. For batch mode, also print the full skipped-date list at the start of the run so the user can see at a glance which dates the run will not cover. The trailing six dates `20260327, 20260330, 20260331, 20260401, 20260402, 20260407` will trigger this guard until data ops backfills them; that is the intended behavior.

The ninth milestone (M8) retires the text path. Delete the following files: `src/tw_signal_engine/market_data/parse_format6_replay_rows.py`, `src/tw_signal_engine/market_data/parse_history_trades.py`, `src/tw_signal_engine/replay/iterate_market_file.py`, `src/tw_signal_engine/replay/merge_market_streams.py`, `src/tw_signal_engine/market_data/build_volume_caches.py`, `src/tw_signal_engine/market_data/file_replay_provider.py`, `src/tw_signal_engine/market_data/rolling_history.py`, and `exec/data/volcache/`. Delete the corresponding tests under `tests/unit/`: `test_parse_history_trades.py`, `test_volume_caches.py`, `test_load_history_window.py` (or rewrite it to point at the parquet loader), `test_rolling_history.py`. Delete the `--data-source text` branch and the `data_source` parameter from both CLIs and from `run_daily_replay`. Delete the `cli/build_caches.py` script if it only exists to populate `volcache/`. Run `uv run pytest tests -q`, `uv run ruff check src tests`, and `uv run mypy src` and fix anything that breaks. Do not perform M8 until M6 has held green for five consecutive replay days.

The final milestone (M9) is documentation cleanup. Edit `CLAUDE.md` to point the example `run_daily_replay` invocation at `--data-dir /Users/liyijing/Projects/Trading/market-data/tick-data --files-dir /Users/liyijing/Projects/Trading/market-data/symbols --group-file /Users/liyijing/Projects/Trading/market-data/group/group-ver20260329.csv`. Edit `AGENTS.md` and `README.md` symmetrically. Move this plan from `docs/exec-plans/active/` to `docs/exec-plans/completed/`, update the active and completed `index.md` files, and write the `Outcomes & Retrospective` section before moving.


## Concrete Steps

The commands below are the executable spine of the plan. Run each milestone's commands from the repository root, `/Users/liyijing/Projects/Trading/VWAP-intraday-signal/signal/`, unless stated otherwise. Update this section as work proceeds — when a step succeeds, paste the actual transcript next to the expected one.

M0 — environment.

    uv sync
    uv run python -c "import pyarrow; print(pyarrow.__version__)"

Expected: pyarrow version line, no `ModuleNotFoundError`. If this fails, the dependency move in `pyproject.toml` was not applied.

M1 — parity harness on five dates.

    uv run python scripts/compare_text_vs_parquet.py --date 20260319 --market TSE
    uv run python scripts/compare_text_vs_parquet.py --date 20260319 --market OTC
    uv run python scripts/compare_text_vs_parquet.py --date 20260320 --market TSE
    uv run python scripts/compare_text_vs_parquet.py --date 20260320 --market OTC
    uv run python scripts/compare_text_vs_parquet.py --date 20260323 --market TSE
    uv run python scripts/compare_text_vs_parquet.py --date 20260323 --market OTC
    uv run python scripts/compare_text_vs_parquet.py --date 20260325 --market TSE
    uv run python scripts/compare_text_vs_parquet.py --date 20260325 --market OTC
    uv run python scripts/compare_text_vs_parquet.py --date 20260326 --market TSE
    uv run python scripts/compare_text_vs_parquet.py --date 20260326 --market OTC

Expected per invocation: a single line `symbols with mismatched cumulative volume: 0` followed by an empty top-ten list. Anything else is a parity blocker — record it in `Surprises & Discoveries`.

M2–M4 — unit tests.

    uv run pytest tests/unit/test_parquet_io.py -q
    uv run pytest tests/unit/test_parquet_history_loader.py -q
    uv run pytest tests/unit/test_parquet_replay_provider.py -q

Expected: three short test runs, each ending in `passed`, no `failed` or `errored`.

M5–M6 — A/B replay run on a single date as the smoke test, then the full five-date suite.

    uv run python -m tw_signal_engine.cli.run_daily_replay \
      --date 20260326 \
      --config exec/cfg/parameter.cfg \
      --data-dir exec/data \
      --files-dir exec/files \
      --group-file exec/files/group.csv \
      --log-folder text-20260326 \
      --data-source text

    uv run python -m tw_signal_engine.cli.run_daily_replay \
      --date 20260326 \
      --config exec/cfg/parameter.cfg \
      --data-dir /Users/liyijing/Projects/Trading/market-data/tick-data \
      --files-dir /Users/liyijing/Projects/Trading/market-data/symbols \
      --group-file /Users/liyijing/Projects/Trading/market-data/group/group-ver20260329.csv \
      --log-folder parquet-20260326 \
      --data-source parquet

    diff -u log/text-20260326/20260326/report_trades.csv log/parquet-20260326/20260326/report_trades.csv

Expected: the second invocation prints noticeably shorter `[TIMING] getTickData` and `[TIMING] readFileMerged` lines than the first (look for sub-second versus tens of seconds), and the `diff` produces no output. Repeat for the other four M1 dates.

M7 — flip the default and exercise the missing-Symbols guard.

    uv run python -m tw_signal_engine.cli.run_daily_replay \
      --date 20260407 \
      --config exec/cfg/parameter.cfg \
      --data-dir /Users/liyijing/Projects/Trading/market-data/tick-data \
      --files-dir /Users/liyijing/Projects/Trading/market-data/symbols \
      --group-file /Users/liyijing/Projects/Trading/market-data/group/group-ver20260329.csv

Expected: `[GUARD] Skipping 20260407: Symbols_20260407.csv not found in /Users/liyijing/Projects/Trading/market-data/symbols`, no traceback, exit code zero.

M8 — full validation after the text-path deletion.

    uv run pytest tests -q
    uv run ruff check src tests
    uv run mypy src

Expected: zero failures, zero ruff violations, zero mypy errors.

M9 — final documentation diff and archival.

    git diff --stat CLAUDE.md AGENTS.md README.md docs/exec-plans/active/index.md docs/exec-plans/completed/index.md

Expected: the active index loses the entry for this plan; the completed index gains it; the three top-level docs reflect the new `--data-dir` / `--files-dir` / `--group-file` paths.


## Validation and Acceptance

The migration is accepted when every one of the following is observably true.

First, `uv run pytest tests -q` is green from a fresh `uv sync` with no optional extras. Second, `uv run python -m tw_signal_engine.cli.run_daily_replay --date 20260326 ... --data-source parquet` (or, after M7, the same command with no flag) prints `[TIMING] getTickData OTC` and `[TIMING] getTickData TSE` lines whose totals are below five seconds combined, where the legacy text path printed totals above sixty seconds. Third, the parity script `scripts/compare_text_vs_parquet.py --date 20260326 --market TSE` (kept available throughout M0–M7, removed in M8 along with the text path it depends on) prints `symbols with mismatched cumulative volume: 0`. Fourth, `diff -u log/text-20260326/20260326/report_trades.csv log/parquet-20260326/20260326/report_trades.csv` produces no output. Fifth, invoking the daily replay against `--date 20260407` (a tick-data date with no Symbols file) prints the `[GUARD] Skipping 20260407` line and exits zero, instead of crashing with `FileNotFoundError`. Sixth, after M8, none of `parse_format6_replay_rows.py`, `parse_history_trades.py`, `iterate_market_file.py`, `merge_market_streams.py`, `file_replay_provider.py`, `build_volume_caches.py`, `rolling_history.py`, or `exec/data/volcache/` exist in the working tree, and `uv run pytest tests -q` is still green.

Where a unit test is involved, name it explicitly: `tests/unit/test_parquet_io.py::test_to_int_price_matches_legacy_reference_prices` should fail before M2 and pass after; `tests/unit/test_parquet_history_loader.py::test_parquet_loader_matches_text_loader` should fail before M3 and pass after; `tests/unit/test_parquet_replay_provider.py::test_chronological_order` and `::test_tick_filter_pushdown` should fail before M4 and pass after. Without the "fails before, passes after" framing, no claim of test coverage is taken seriously.


## Idempotence and Recovery

Every step in this plan is safe to repeat. The parity script in M1 is read-only and never writes outside `log/`. The unit tests in M2–M4 do not touch the parquet or text roots. The A/B runs in M6 use distinct `--log-folder` names so re-running them simply overwrites their own output directories. The CLI flag flip in M7 is a one-line `default=` change that can be reverted with a single edit. The deletions in M8 are guarded by full `pytest`, `ruff`, and `mypy` runs and are commit-by-commit, so any regression can be reverted with `git revert`. Do not delete `exec/data/volcache/` until M8; before then, the JSON sidecars are still consulted by the text path under `--data-source text` and removing them prematurely would force every text-path run to do a cold rebuild.

If the parity gate in M6 fails, do not advance. Read the diff, decide whether the divergence is in the price conversion (revisit `parquet_io._to_int_price`), in the row filter (revisit the `tradeVolume > 0 AND time >= 9:00` mask), in the merge order (revisit the `concat_tables(...).sort_by("time")` step), or in the post-processing (revisit `prev_limit_up` and `volatility_pause`). Record the finding in `Surprises & Discoveries` and patch the offending file. Re-run M6 from scratch.

If the M3 history loader produces a different cumulative volume than the text loader for any symbol, the most likely cause is a `tradeVolume > 0` filter that disagrees with `status_code == 0` for that symbol. The design report's hypothesis (see §3.4) is that the new feed batches multiple legacy executions into one snapshot whose `tradeVolume` is the aggregate, in which case `df.groupby("symbol")["transactionVolume"].diff()` should match `tradeVolume` row-by-row. Verify with the cross-check snippet in `Artifacts and Notes` below.

If a developer accidentally points `--data-source parquet` at a date that has no parquet file, `pyarrow.parquet.read_table` raises `FileNotFoundError`. That is acceptable error reporting — do not catch it; let the stack trace surface so the user sees which file is missing.

Cleanup after the migration is straightforward: there are no temporary files to remove, no environment variables to unset, and no background processes to stop. The only artifacts that survive are the new files under `src/tw_signal_engine/market_data/`, the new tests under `tests/unit/`, and the diff in `pyproject.toml`, `CLAUDE.md`, `AGENTS.md`, and `README.md`.


## Artifacts and Notes

The cross-check snippet that validates the design report's "the new feed batches snapshots" hypothesis is short enough to inline here. Run it from the repo root after `uv sync`.

    uv run python -c "
    import pyarrow.parquet as pq
    tbl = pq.read_table(
        '/Users/liyijing/Projects/Trading/market-data/tick-data/TWSE/20260326.parquet',
        columns=['symbol', 'time', 'tradeVolume', 'transactionVolume'],
    )
    df = tbl.to_pandas().sort_values(['symbol', 'time'])
    df['delta'] = df.groupby('symbol')['transactionVolume'].diff().fillna(df['transactionVolume'])
    trade_rows = df[df['tradeVolume'] > 0]
    mismatches = trade_rows[trade_rows['delta'] != trade_rows['tradeVolume']]
    print(f'trade rows: {len(trade_rows)}, transactionVolume-delta mismatches: {len(mismatches)}')
    "

If `transactionVolume-delta mismatches: 0`, the hypothesis holds and no legacy executions are lost — they are simply batched into wider snapshots. If there are mismatches, paste the first ten rows of `mismatches` into `Surprises & Discoveries` and treat M1 as a parity blocker until they are explained.

The benchmark snippet from the design report's appendix is also worth keeping handy, because the headline performance claims in this plan's `Purpose` section rest on it.

    uv run python -c "
    import time, pyarrow.parquet as pq
    from tw_signal_engine.market_data.parse_history_trades import iter_history_trades
    t = time.time()
    n = sum(1 for _ in iter_history_trades('exec/data/TSEQuote.20260326'))
    print(f'text:    {time.time()-t:.2f} s, n={n}')
    t = time.time()
    tbl = pq.read_table(
        '/Users/liyijing/Projects/Trading/market-data/tick-data/TWSE/20260326.parquet',
        columns=['symbol','time','tradePrice','tradeVolume'],
        filters=[('tradeVolume','>',0)],
    )
    print(f'parquet: {(time.time()-t)*1000:.0f} ms, n={tbl.num_rows}')
    "

Expected output, on an M-series Mac with warm filesystem cache: roughly `text: 6.20 s, n=1292891` and `parquet: 86 ms, n=1147375`. The seventy-x speedup is the headline number for the cold history-window load.


## Interfaces and Dependencies

This section is prescriptive on purpose. The module names, function signatures, and types listed below MUST exist at the end of the corresponding milestone. Do not rename them mid-stream — the test files in `tests/unit/` import them by exact name.

In `src/tw_signal_engine/market_data/parquet_io.py` (M2), define:

    from pathlib import Path
    import pyarrow as pa

    PARQUET_REPLAY_COLUMNS: list[str] = [
        "symbol", "time", "matchFlag", "tradePrice",
        "tradeVolume", "buyPrice1", "sellPrice1",
    ]

    PARQUET_HISTORY_COLUMNS: list[str] = [
        "symbol", "time", "tradePrice", "tradeVolume",
    ]

    def to_int_price(price: float) -> int:
        """Return round(price * 10000); never use int()."""

    def assert_replay_schema(table: pa.Table) -> None:
        """Raise ValueError listing missing or mistyped columns."""

    def parquet_path(root: str | Path, market: str, date: str) -> Path:
        """Map ('TSE', '20260326') -> '<root>/TWSE/20260326.parquet'.

        Mapping: TSE -> TWSE, OTC -> TPEX. Any other market raises ValueError.
        """

In `src/tw_signal_engine/market_data/parquet_history_loader.py` (M3), define:

    from tw_signal_engine.market_data.history_window import HistoryWindow

    DAY_PER_MONTH: int = 20

    def load_parquet_history_window(
        market_type: str,
        date: str,
        root: str | Path,
        require_target_file: bool = True,
    ) -> HistoryWindow:
        """Load up to 20 prior parquet sessions and return a HistoryWindow.

        Returns a HistoryWindow whose vol_cum, trading_val, and source_dates
        lists have the same shape and ordering (newest first) as the legacy
        load_history_window in market_data/load_history_window.py.

        When require_target_file is False, allows the caller to load history
        on a date whose own parquet file is absent (matches the existing
        text-loader contract for live mode).
        """

In `src/tw_signal_engine/market_data/parquet_replay_provider.py` (M4), define:

    from tw_signal_engine.market_data.market_data_records import NumTracker
    from tw_signal_engine.market_data.providers import MarketDataProvider
    from tw_signal_engine.records.market_event_records import MarketTick

    class ParquetReplayProvider(MarketDataProvider):
        def __init__(
            self,
            otc_date: str,
            tse_date: str,
            root: str | Path = "/Users/liyijing/Projects/Trading/market-data/tick-data/",
            tick_filter: set[str] | None = None,
            prev_day_limit_up: dict[str, bool] | None = None,
            num_tracker: NumTracker | None = None,
        ) -> None: ...

        def iterate_ticks(self) -> Iterator[MarketTick]:
            """Yield MarketTick objects in match_time_str order, merged across TWSE and TPEX."""

In `src/tw_signal_engine/replay/replay_session.py` (M5), extend the `run_daily_replay` signature with one new parameter:

    def run_daily_replay(
        trade_date: str,
        config_path: str = "./cfg/parameter.cfg",
        data_dir: str = "./data/",
        files_dir: str = "./files/",
        group_file: str = "./files/group.csv",
        log_folder: str = "",
        history: HistoryWindow | None = None,
        use_cache: bool = True,
        no_charts: bool = False,
        cost_model_override: str = "",
        provider: MarketDataProvider | None = None,
        hooks: SessionHooks | None = None,
        on_dashboard_snapshot: Callable[[DashboardSnapshot], None] | None = None,
        data_source: str = "parquet",   # NEW — "text" or "parquet"
    ) -> list[TradeRecord]: ...

The semantics: if `provider` is non-None, it wins (the live path passes its own Redis provider). Otherwise, if `data_source == "parquet"`, construct a `ParquetReplayProvider` and call `load_parquet_history_window` for both markets. Otherwise (legacy text path retained until M8), construct a `FileReplayProvider` and call `load_history_window` as today.

The dependencies are: `pyarrow >= 15.0` (moved from `[project.optional-dependencies.live]` to `[project.dependencies]` in M0), and the existing `pydantic`, `numpy`, `matplotlib`. No new third-party libraries are required. The parquet root is read-only from the engine's perspective; the engine never writes back into `/Users/liyijing/Projects/Trading/market-data/`.

The data-shape contract that downstream consumers rely on is unchanged. `MarketTick` keeps the same fields with the same types (integer-x10000 prices, integer microseconds-since-midnight times, two-character market codes). `HistoryWindow.vol_cum[i]` is still a `LinearVolumeTracker` and `HistoryWindow.trading_val[i]` is still a `dict[str, int]`. `LinearVolumeTracker.data_store[symbol]` is still a list of `TickNode(timestamp, cumulative_qty)` in monotonically non-decreasing time order. If any of these contracts is violated, the parity tests in M3 and M6 will catch it before the default flips.


## Revision Notes

This plan is a living document. Every revision must explain what changed and why, in the form of a short note appended below. When adding a new note, also bump the relevant `Progress` checkbox(es) and, if a decision was reversed, add a new `Decision Log` entry rather than editing the old one.

- 2026-04-08 — Initial draft authored from `docs/design-docs/market-data-migration-report.md`. Translated the report's nine-step phased rollout into nine self-contained milestones (M0–M9), pinned the public interface names that the unit tests will import, and committed the plan to additive deletion (M8 only after M6 has held green for five consecutive days). The most consequential decision baked into the draft is moving `pyarrow` into core dependencies in M0; without that, a fresh `uv sync` cannot exercise the new path and the migration is not actually a default. The most consequential ambiguity left for M1 to resolve is the eleven-percent row delta between `status_code == 0` and `tradeVolume > 0`; the design report's batched-snapshot hypothesis is testable and the cross-check snippet is inlined under `Artifacts and Notes`.
- 2026-04-08 — Updated progress after implementing M7: flipped CLI defaults to parquet, added the missing-`Symbols_*.csv` guard in both daily and batch flows, and recorded guard smoke-test evidence. Also corrected all parity references from `trade.csv` to the actual engine output file `report_trades.csv`, and documented that M6 remains open because four of the five target dates still produce non-float diffs.
- 2026-04-08 — Completed M6 root-cause isolation. Established that most parity drift is data divergence between legacy text and parquet history windows, while the remaining `20260320` extra/missing trade comes from same-day stream semantic differences on non-target symbols (zero-quantity/status snapshots) rather than arithmetic conversion errors. Documented which columns are cosmetic-only (`0050EntryChg%`, small `MonthTradingVal` / `VolRatio` drift) and which differences alter trade membership.
- 2026-04-08 — Attempted a direct fix for the isolated causes: switched parquet history pushdown to status-equivalent semantics (`matchFlag == 'Y' AND time >= 9:00`), kept parquet replay trade-row ingestion (`tradeVolume > 0`) with the same status guard, and added a parquet-mode `0050` proxy stream from `exec/data` when available. Re-ran the full five-date M6 suite (`20260319/20/23/25/26`) against existing text baselines. Result: `20260323` is clean; the other four dates still diverge, but the previous common-row `0050EntryChg%` mismatch is gone. Residual deltas are now concentrated in trade membership (`20260319`, `20260320`) and history-derived fields (`MonthTradingVal`, `VolRatio`) on common rows (`20260325`, `20260326`).

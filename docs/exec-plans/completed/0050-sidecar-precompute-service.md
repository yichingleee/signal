# Build and Use a Precomputed 0050 Sidecar

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document is maintained in accordance with `docs/references/exec-plan-standard.md`. It is self-contained: a contributor should be able to start from this file, inspect the current repository, implement the service, run the precomputation for available data from `20251216` through `20260407`, and verify that replay no longer scans `TSEQuote` just to feed `0050` into the market gate.


## Purpose / Big Picture

Parquet replay is now the default replay path, but the parquet tick files omit all symbols whose code starts with `00`, including `0050`. The replay engine uses `0050` to compute the market open change, trip the market-wide disable gate, and record entry-time market change. The current parquet-mode mitigation reads `0050` from legacy `TSEQuote.<date>` text files when available. That is correct semantically, but it is slow because the filtered text iterator still scans the entire multi-gigabyte TSE text file for each replay.

After this work, a contributor can run a one-time precompute command that extracts only `0050` from every available `TSEQuote` file between `20251216` and `20260407` and writes small sidecar parquet files. Daily and batch parquet replay will then load the tiny sidecar first, falling back to the old text proxy only when a sidecar is absent. A user can see the improvement by running the same parquet replay twice: before the change, logs show `[GATE] 0050 proxy stream: .../TSEQuote.<date>` and replay pays a text scan; after the change, logs show `[GATE] 0050 sidecar: .../0050/<date>.parquet` and replay avoids opening `TSEQuote` on the hot path.


## Progress

- [x] (2026-04-19T17:13:28Z) Confirmed `.envrc` defines the local data roots: `TW_SIGNAL_DATA_DIR=/mnt/d/tmp/market-data/tick-data` for text `TSEQuote` data, `TW_SIGNAL_PARQUET_DATA_DIR=/mnt/d/tmp/market-data/tick-data-parquet` for parquet replay data, `TW_SIGNAL_FILES_DIR=/mnt/d/tmp/market-data/symbols`, and `TW_SIGNAL_GROUP_FILE=/mnt/d/tmp/market-data/symbols/group-ver20260408.csv`.
- [x] (2026-04-19T17:13:28Z) Confirmed the text root contains 68 `TSEQuote` files in the requested range, with first file `TSEQuote.20251216` and last file `TSEQuote.20260407`.
- [x] (2026-04-19T17:13:28Z) Measured current one-day filtered text proxy cost on this machine: `iterate_market_file("TSE", "20260407", "/mnt/d/tmp/market-data/tick-data", {"0050"})` yielded 19,545 `0050` ticks and took 33.971 seconds.
- [x] (2026-04-19T17:13:28Z) Wrote this implementation plan.
- [ ] Implement the sidecar writer and loader module.
- [ ] Implement the idempotent precompute command.
- [ ] Wire parquet replay to prefer the sidecar before the text proxy and day-bar fallback.
- [ ] Add unit and real-data smoke tests.
- [ ] Run the precompute command for every available `TSEQuote` date from `20251216` through `20260407`.
- [ ] Run daily and batch replay validation and record the measured before/after behavior here.


## Surprises & Discoveries

- Observation: A symbol-filtered `TSEQuote` scan is still too expensive to sit on the default parquet replay path.
  Evidence: On this machine, the command below took 33.971 seconds for one date, even though it parsed only `0050` ticks:

        uv run python - <<'PY'
        import time
        from tw_signal_engine.replay.iterate_market_file import iterate_market_file
        start = time.perf_counter()
        count = 0
        first = None
        last = None
        for tick in iterate_market_file("TSE", "20260407", "/mnt/d/tmp/market-data/tick-data", {"0050"}):
            count += 1
            first = first or tick.match_time_str
            last = tick.match_time_str
        elapsed = time.perf_counter() - start
        print(f"count={count} first={first} last={last} elapsed_sec={elapsed:.3f}")
        PY

        count=19545 first=90002331444 last=133000000000 elapsed_sec=33.971

- Observation: The requested precompute range is available in the local text root.
  Evidence: `/mnt/d/tmp/market-data/tick-data` contains 68 `TSEQuote.*` files, starting at `TSEQuote.20251216` and ending at `TSEQuote.20260407`. Representative sizes are `TSEQuote.20251216` at 1,869,351,828 bytes, `TSEQuote.20260326` at 2,071,895,416 bytes, and `TSEQuote.20260407` at 1,844,945,294 bytes.


## Decision Log

- Decision: Implement the precompute system as an idempotent CLI-backed service, not as a long-running daemon.
  Rationale: The source files are immutable historical `TSEQuote` files. A command that discovers missing or stale sidecars and rebuilds them is simpler, easier to test, and safer than a resident background process. In this plan, "service" means a reusable repository feature with a library module, a CLI entrypoint, and deterministic artifacts.
  Date/Author: 2026-04-19 / Codex

- Decision: Store sidecars outside the repository by default under a sibling of the market-data roots: `/mnt/d/tmp/market-data/0050-sidecar/0050/YYYYMMDD.parquet`.
  Rationale: Sidecars are generated data derived from multi-gigabyte market data. They should not be committed to git. Placing them beside `tick-data` and `tick-data-parquet` keeps the data estate together and lets replay find them from the parquet root.
  Date/Author: 2026-04-19 / Codex

- Decision: Prefer sidecar, then text proxy, then day-bar open fallback in parquet replay.
  Rationale: The sidecar preserves text tick semantics without the text scan. The existing text proxy remains valuable when a sidecar is missing. The day-bar open fallback remains the last resort when no tick-level `0050` data is available.
  Date/Author: 2026-04-19 / Codex

- Decision: Use parquet for the sidecar format.
  Rationale: The project already depends on `pyarrow` for parquet replay. Parquet gives compact files, typed columns, cheap reads, and schema checks without introducing another dependency.
  Date/Author: 2026-04-19 / Codex


## Outcomes & Retrospective

No implementation has shipped yet. The desired outcome is that parquet replay no longer scans any `TSEQuote` file for `0050` when a sidecar exists, while preserving the same `MarketGate` and entry-market-change semantics currently provided by the text proxy. When the implementation is complete, update this section with the number of sidecars generated, total generation time, average sidecar size, replay timing before and after, and any dates that could not be generated.


## Context and Orientation

The active replay engine lives under `src/tw_signal_engine/`. Daily replay is orchestrated by `src/tw_signal_engine/replay/replay_session.py`. The replay loop builds a symbol universe, initializes screening and signal state, constructs a market-data provider, and iterates `MarketTick` records. A `MarketTick` is the internal tick object defined in `src/tw_signal_engine/records/market_event_records.py`; it carries the symbol, market, raw match time, trade price, quantity, and best bid/ask used by execution logic.

The market gate is implemented by `src/tw_signal_engine/replay/apply_market_gate.py`. `MarketGate.on_tick()` ignores everything except valid `0050` trade ticks. On the first `0050` tick at or after `09:00`, it records the open price and computes `market_open_chg_pct`. On the first `0050` tick at or after `09:15`, it checks the rally-disable threshold. The execution code in `src/tw_signal_engine/execution/create_entry_trade.py` also uses `p0050_latest` to enforce `max_0050_entry_chg` and `max_0050_intra_chg` filters and to write `0050EntryChg%` into trade records.

The current parquet provider is `src/tw_signal_engine/market_data/parquet_replay_provider.py`. It reads `TWSE/YYYYMMDD.parquet` and `TPEX/YYYYMMDD.parquet`, filters to regular trade rows, and yields `MarketTick` records. Those parquet files omit `0050`, so `src/tw_signal_engine/replay/replay_session.py` currently compensates in parquet mode by trying a `0050`-only proxy stream from the legacy text file via `src/tw_signal_engine/replay/iterate_market_file.py`. The text iterator has a fast symbol filter, but it must still scan the entire `TSEQuote.<date>` file line by line. That is the cost this plan removes from replay.

The local `.envrc` in this checkout defines the data roots that should be used during validation:

    export TW_SIGNAL_DATA_DIR=/mnt/d/tmp/market-data/tick-data
    export TW_SIGNAL_PARQUET_DATA_DIR=/mnt/d/tmp/market-data/tick-data-parquet
    export TW_SIGNAL_FILES_DIR=/mnt/d/tmp/market-data/symbols
    export TW_SIGNAL_GROUP_FILE=/mnt/d/tmp/market-data/symbols/group-ver20260408.csv

Use those environment variables in commands whenever possible. If the variables are not loaded in the shell, either run `direnv allow` from the repository root or pass the equivalent paths explicitly.


## Plan of Work

First, add a sidecar library module at `src/tw_signal_engine/market_data/proxy_0050_sidecar.py`. This module owns the sidecar schema, path conventions, stale-file checks, writer, and loader. It should expose small functions with stable names so the CLI and replay session do not duplicate sidecar details.

Define `DEFAULT_0050_SIDECAR_DIR_NAME = "0050-sidecar"` and `SIDECAR_SYMBOL = "0050"`. Define `default_sidecar_root(data_dir: str | Path) -> Path`, where `data_dir` is normally the parquet root passed to `run_daily_replay`; the function returns `Path(data_dir).parent / DEFAULT_0050_SIDECAR_DIR_NAME`. Also support an environment override named `TW_SIGNAL_0050_SIDECAR_DIR`. When the override is present, it wins.

Use one sidecar parquet file per date:

    <sidecar_root>/0050/YYYYMMDD.parquet

Next to each parquet file, write a small JSON metadata file:

    <sidecar_root>/0050/YYYYMMDD.meta.json

The parquet file should contain one row per valid text-side `0050` tick yielded by `iterate_market_file("TSE", date, text_data_dir, {"0050"})`. Use these columns:

    symbol: string
    market: string
    match_time_str: int64
    match_time_us: int64
    status_code: int32
    trade_code: int32
    price: int64
    qty: int64
    bid_price: int64
    ask_price: int64
    trade_at: int8

These fields are enough to reconstruct the `MarketTick` shape needed by `MarketGate` and entry filters. They also preserve enough context for future debugging if the sidecar ever disagrees with the text proxy. The metadata JSON should include at least:

    date
    source_path
    source_size
    source_mtime_ns
    row_count
    first_match_time_str
    last_match_time_str
    generated_at_utc
    schema_version

Implement `is_sidecar_fresh(date: str, text_data_dir: str | Path, sidecar_root: str | Path) -> bool` by comparing the metadata `source_size` and `source_mtime_ns` to the current `TSEQuote.<date>` file. Do not compute a full file hash; hashing multi-gigabyte text files would recreate the same I/O cost this sidecar is intended to avoid. If the source file is missing, return `False` and let the caller decide whether to skip or fail.

Implement `build_0050_sidecar(date: str, text_data_dir: str | Path, sidecar_root: str | Path, force: bool = False) -> Build0050SidecarResult`. `Build0050SidecarResult` can be a dataclass with `date`, `path`, `row_count`, `elapsed_sec`, `status`, and `message`. If `force` is false and the sidecar is fresh, return a result with status `skipped_fresh`. Otherwise, scan the text file with the existing `iterate_market_file()` and collect only the `0050` ticks. Write the parquet file atomically by writing to a temporary filename in the same directory and then replacing the final file with `Path.replace()`. Write metadata after the parquet replace succeeds.

Implement `load_0050_sidecar(date: str, sidecar_root: str | Path) -> Iterator[MarketTick]`. It should read the sidecar parquet, assert the schema, sort by `match_time_str` if necessary, and yield `MarketTick` objects. Populate `tick.match.price`, `tick.match.qty`, `tick.bid[0].price`, `tick.ask[0].price`, `tick.trade_at`, `tick.status_code`, `tick.trade_code`, `tick.market`, `tick.symbol`, `tick.match_time_str`, and `tick.match_time_us`. The loader should raise `FileNotFoundError` if the sidecar parquet is missing and `ValueError` if the schema is wrong. `run_daily_replay()` will catch only the missing-file case by checking existence before it chooses the source.

Second, add a CLI entrypoint at `src/tw_signal_engine/cli/build_0050_sidecar.py`. The command should be runnable as:

    uv run python -m tw_signal_engine.cli.build_0050_sidecar \
      --start 20251216 \
      --end 20260407 \
      --text-data-dir "$TW_SIGNAL_DATA_DIR" \
      --sidecar-dir /mnt/d/tmp/market-data/0050-sidecar

The CLI should discover available text files by globbing `TSEQuote.*` under `--text-data-dir`, filter them by the inclusive `--start` and `--end` dates, and build sidecars only for dates that exist. It should print a clear summary before building, such as:

    Building 68 0050 sidecars from /mnt/d/tmp/market-data/tick-data
    Date range: 20251216..20260407
    Output root: /mnt/d/tmp/market-data/0050-sidecar

The CLI should support `--force` to rebuild fresh files, `--dry-run` to print what would be built, and `--jobs N` for optional parallelism. Default `--jobs` to `1` because the source files are multi-gigabyte sequential reads and parallel scans on `/mnt/d` can make wall time worse by thrashing disk I/O. The implementation may still use `concurrent.futures.ProcessPoolExecutor` when `--jobs > 1`, but the single-worker path must be simple and deterministic.

Third, wire the sidecar into parquet replay in `src/tw_signal_engine/replay/replay_session.py`. Keep the current fallback order explicit. In the block that currently starts with `if data_source == "parquet" and p0050_prev > 0:`, do this:

1. Compute `sidecar_root = default_sidecar_root(data_dir)`.
2. If `<sidecar_root>/0050/<trade_date>.parquet` exists, set `proxy_0050_iter = load_0050_sidecar(trade_date, sidecar_root)` and pull `proxy_0050_next = next(proxy_0050_iter, None)`.
3. If the sidecar yielded at least one tick, print `[GATE] 0050 sidecar: <path>`.
4. If no sidecar exists or it is empty, fall back to the existing text proxy discovery with `_find_0050_proxy_text_dir()`.
5. If no text proxy exists, keep the existing day-bar open synthesis.

Do not remove the text proxy yet. It is still useful as a compatibility fallback and as a way to regenerate sidecars.

Fourth, add tests. Create `tests/unit/test_0050_sidecar.py`. Use small synthetic `MarketTick` objects for writer/loader schema tests where possible. For the full parse path, create a minimal `TSEQuote` fixture that includes at least one non-`0050` trade and two `0050` trades. If constructing valid text lines is too brittle, use the existing `iterate_market_file()` behavior on real data in a skipped smoke test and keep synthetic tests focused on sidecar serialization and freshness logic. Required test coverage:

1. `build_0050_sidecar()` writes a parquet file and metadata file.
2. `load_0050_sidecar()` round-trips the fields needed by `MarketGate`.
3. A fresh sidecar is skipped when source size and mtime match.
4. `--force` rebuilds even when metadata is fresh.
5. The CLI `--dry-run` discovers dates and writes nothing.
6. `run_daily_replay()` prefers the sidecar over text proxy in parquet mode. This can be a monkeypatched unit test that patches `load_0050_sidecar`, `_find_0050_proxy_text_dir`, and the data provider to avoid a full replay.

Fifth, run the actual precomputation on local available data. The command should be run from the repository root after implementation:

    cd /home/r12944005/b07401012/Trading/signal
    uv run python -m tw_signal_engine.cli.build_0050_sidecar \
      --start 20251216 \
      --end 20260407 \
      --text-data-dir "${TW_SIGNAL_DATA_DIR:-/mnt/d/tmp/market-data/tick-data}" \
      --sidecar-dir "${TW_SIGNAL_0050_SIDECAR_DIR:-/mnt/d/tmp/market-data/0050-sidecar}" \
      --jobs 1

Expect 68 sidecars to be generated on the current machine. If the command reports fewer than 68, inspect the skipped or failed date list and update this plan with the reason. The implementation should not silently ignore failures. At the end, the command should print totals:

    Summary: built=68 skipped_fresh=0 failed=0
    Output root: /mnt/d/tmp/market-data/0050-sidecar

Sixth, validate replay behavior. Run one daily replay with sidecar present:

    cd /home/r12944005/b07401012/Trading/signal
    uv run python -m tw_signal_engine.cli.run_daily_replay \
      --date 20260407 \
      --data-source parquet \
      --data-dir "${TW_SIGNAL_PARQUET_DATA_DIR:-/mnt/d/tmp/market-data/tick-data-parquet}" \
      --files-dir "${TW_SIGNAL_FILES_DIR:-/mnt/d/tmp/market-data/symbols}" \
      --group-file "${TW_SIGNAL_GROUP_FILE:-/mnt/d/tmp/market-data/symbols/group-ver20260408.csv}" \
      --log-folder sidecar-smoke-20260407 \
      --no-charts

The log must show `[GATE] 0050 sidecar:` and must not show `[GATE] 0050 proxy stream:` for that date. Then temporarily move the sidecar for one date aside and rerun the same command to confirm the old text proxy fallback still works. Move the sidecar back afterward.


## Concrete Steps

From the repository root, inspect current source state:

    cd /home/r12944005/b07401012/Trading/signal
    rg -n "0050|proxy_0050|MarketGate|day_bar|iterate_market_file" src tests docs

Implement the sidecar module:

    src/tw_signal_engine/market_data/proxy_0050_sidecar.py

Add the CLI entrypoint:

    src/tw_signal_engine/cli/build_0050_sidecar.py

Add tests:

    tests/unit/test_0050_sidecar.py

Wire the replay preference order in:

    src/tw_signal_engine/replay/replay_session.py

Run focused tests first:

    uv run pytest tests/unit/test_0050_sidecar.py tests/unit/test_market_gate.py -q

Run parquet-related regression tests:

    uv run pytest tests/unit/test_parquet_io.py tests/unit/test_parquet_replay_provider.py tests/unit/test_day_bar_loader.py -q

Run style and type checks:

    uv run ruff check src tests
    uv run mypy src

Run the precompute command:

    uv run python -m tw_signal_engine.cli.build_0050_sidecar \
      --start 20251216 \
      --end 20260407 \
      --text-data-dir "${TW_SIGNAL_DATA_DIR:-/mnt/d/tmp/market-data/tick-data}" \
      --sidecar-dir "${TW_SIGNAL_0050_SIDECAR_DIR:-/mnt/d/tmp/market-data/0050-sidecar}" \
      --jobs 1

Run the replay smoke test:

    uv run python -m tw_signal_engine.cli.run_daily_replay \
      --date 20260407 \
      --data-source parquet \
      --data-dir "${TW_SIGNAL_PARQUET_DATA_DIR:-/mnt/d/tmp/market-data/tick-data-parquet}" \
      --files-dir "${TW_SIGNAL_FILES_DIR:-/mnt/d/tmp/market-data/symbols}" \
      --group-file "${TW_SIGNAL_GROUP_FILE:-/mnt/d/tmp/market-data/symbols/group-ver20260408.csv}" \
      --log-folder sidecar-smoke-20260407 \
      --no-charts

Record the observed outputs in `Surprises & Discoveries` and update `Progress` after each completed milestone.


## Validation and Acceptance

The implementation is accepted only when all of the following are true.

The sidecar builder is idempotent. Running it once over `20251216..20260407` builds sidecars for all available `TSEQuote` dates. Running the same command again without `--force` skips all fresh sidecars and exits successfully.

The generated artifact count matches the current data root. On this machine, `TW_SIGNAL_DATA_DIR=/mnt/d/tmp/market-data/tick-data` contains 68 `TSEQuote` files in the requested range. Therefore this command should produce 68 parquet sidecars:

    find /mnt/d/tmp/market-data/0050-sidecar/0050 -name '*.parquet' | wc -l

Expected output:

    68

The sidecar loader preserves ordering and essential fields. A small check should print a positive row count and ordered first/last times for a known date:

    uv run python - <<'PY'
    from pathlib import Path
    import pyarrow.parquet as pq
    p = Path("/mnt/d/tmp/market-data/0050-sidecar/0050/20260407.parquet")
    t = pq.read_table(p)
    times = t.column("match_time_str").to_pylist()
    print(t.num_rows, times[0], times[-1], times == sorted(times))
    PY

Expected output should be structurally like:

    19545 90002331444 133000000000 True

The replay hot path uses the sidecar. For a date whose sidecar exists, parquet replay must print `[GATE] 0050 sidecar:` and must not print `[GATE] 0050 proxy stream:`. This proves replay did not scan `TSEQuote` for `0050`.

The fallback remains intact. If a sidecar is absent for a date but `TSEQuote.<date>` exists, parquet replay should still print `[GATE] 0050 proxy stream:` and preserve current behavior. If neither sidecar nor text proxy exists, the existing day-bar open fallback should still run.

The normal project checks pass:

    uv run pytest tests -q
    uv run ruff check src tests
    uv run mypy src


## Idempotence and Recovery

The sidecar builder must be safe to rerun. It should skip fresh files by default, rebuild stale files when source size or mtime changes, and rebuild everything when `--force` is passed. Atomic writes prevent a half-written parquet file from being mistaken for a valid sidecar after interruption.

If the precompute command is interrupted, rerun the same command. Fresh completed dates should be skipped and incomplete dates should be rebuilt. If a metadata file exists but its parquet file is missing, treat the sidecar as stale and rebuild it. If a parquet file exists but metadata is missing, treat it as stale and rebuild it unless a future decision explicitly supports metadata reconstruction.

If a generated sidecar appears corrupt, delete only that date's two files:

    rm /mnt/d/tmp/market-data/0050-sidecar/0050/YYYYMMDD.parquet
    rm /mnt/d/tmp/market-data/0050-sidecar/0050/YYYYMMDD.meta.json

Then rerun the builder for that date:

    uv run python -m tw_signal_engine.cli.build_0050_sidecar \
      --start YYYYMMDD \
      --end YYYYMMDD \
      --text-data-dir "${TW_SIGNAL_DATA_DIR:-/mnt/d/tmp/market-data/tick-data}" \
      --sidecar-dir "${TW_SIGNAL_0050_SIDECAR_DIR:-/mnt/d/tmp/market-data/0050-sidecar}"

Do not delete or modify the source `TSEQuote` files. The sidecar is derived data and can always be regenerated from the text source.


## Interfaces and Dependencies

Use only existing project dependencies. `pyarrow` is already used by the parquet replay path. Do not add a new database, cache service, scheduler, or background process.

In `src/tw_signal_engine/market_data/proxy_0050_sidecar.py`, define:

    SIDECAR_SCHEMA_VERSION = 1
    SIDECAR_SYMBOL = "0050"
    SIDECAR_ENV_VAR = "TW_SIGNAL_0050_SIDECAR_DIR"

    @dataclass(frozen=True)
    class Build0050SidecarResult:
        date: str
        path: Path
        row_count: int
        elapsed_sec: float
        status: str
        message: str = ""

    def default_sidecar_root(data_dir: str | Path) -> Path: ...
    def sidecar_path(sidecar_root: str | Path, date: str) -> Path: ...
    def sidecar_meta_path(sidecar_root: str | Path, date: str) -> Path: ...
    def is_sidecar_fresh(date: str, text_data_dir: str | Path, sidecar_root: str | Path) -> bool: ...
    def discover_text_dates(text_data_dir: str | Path, start: str, end: str) -> list[str]: ...
    def build_0050_sidecar(date: str, text_data_dir: str | Path, sidecar_root: str | Path, force: bool = False) -> Build0050SidecarResult: ...
    def load_0050_sidecar(date: str, sidecar_root: str | Path) -> Iterator[MarketTick]: ...

In `src/tw_signal_engine/cli/build_0050_sidecar.py`, define `main() -> None` and support these arguments:

    --start YYYYMMDD
    --end YYYYMMDD
    --text-data-dir PATH
    --sidecar-dir PATH
    --force
    --dry-run
    --jobs N

In `src/tw_signal_engine/replay/replay_session.py`, import the sidecar helpers and use them only in the parquet-mode `0050` proxy block. Keep all existing text-mode behavior unchanged.


## Artifacts and Notes

The key local evidence collected while authoring this plan is:

    .envrc:
      TW_SIGNAL_DATA_DIR=/mnt/d/tmp/market-data/tick-data
      TW_SIGNAL_PARQUET_DATA_DIR=/mnt/d/tmp/market-data/tick-data-parquet
      TW_SIGNAL_FILES_DIR=/mnt/d/tmp/market-data/symbols
      TW_SIGNAL_GROUP_FILE=/mnt/d/tmp/market-data/symbols/group-ver20260408.csv

    Text data inventory:
      count: 68 TSEQuote files
      first: TSEQuote.20251216
      last: TSEQuote.20260407

    One-day current proxy scan:
      date: 20260407
      0050 ticks: 19545
      elapsed: 33.971 seconds

Revision note, 2026-04-19: Initial plan written to specify the sidecar service, replay integration, data precomputation command, validation, and recovery behavior. The plan exists because the current text proxy is semantically correct but too slow for default parquet replay.

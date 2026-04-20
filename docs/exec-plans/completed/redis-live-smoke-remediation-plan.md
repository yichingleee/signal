# Redis Live Mode Smoke-Test Remediation Plan

**Date**: 2026-03-29  
**Status**: Completed  
**Owner**: `tw_signal_engine` maintainers

## 1) Findings From Manual End-to-End Smoke

### 1.1 Confirmed blocker in official live CLI path

Running:

```bash
uv run python -m tw_signal_engine.cli.run_server --mode live ...
```

caused engine-thread failure:

```text
TypeError: run_daily_replay() got an unexpected keyword argument 'provider'
```

Observed in [ /tmp/twse_live_server_smoke.log ] during this session.

**Impact**:
- `/api/status` serves HTTP, but the engine is not processing live ticks.
- Live mode appears up while being non-functional.

### 1.2 Contract drift is present in both live entrypoints

- [`src/tw_signal_engine/cli/run_server.py`](/Users/liyijing/Projects/Trading/VWAP-intraday-signal/signal-live-data/src/tw_signal_engine/cli/run_server.py) and [`src/tw_signal_engine/cli/run_live.py`](/Users/liyijing/Projects/Trading/VWAP-intraday-signal/signal-live-data/src/tw_signal_engine/cli/run_live.py) call `run_daily_replay(..., provider=...)`.
- [`src/tw_signal_engine/replay/replay_session.py`](/Users/liyijing/Projects/Trading/VWAP-intraday-signal/signal-live-data/src/tw_signal_engine/replay/replay_session.py) no longer accepts `provider`, `hooks`, or `on_dashboard_snapshot`.

### 1.3 Runtime packaging gap for live/server workflows

After `uv sync`, core runtime modules required by server/live path were not installed by default in this environment (`fastapi`, `uvicorn`, `python-socketio`, `redis`, `pandas`).

**Impact**:
- Fresh env can pass basic replay imports but fail when launching server/live commands.

### 1.4 Live history loader has strict target-file dependency

`load_history_window()` enforces presence of `TSEQuote.<date>` and `OTCQuote.<date>` even when ticks come from Redis.

**Impact**:
- Live smoke required temporary placeholder files in `/tmp` to satisfy loader preconditions.

### 1.5 What did pass (via fallback harness using same provider + API stack)

With `RedisLiveProvider` + `LiveState` + existing API app wired directly:
- Trade/Depth ingestion on subscribed symbol: pass
- `status_code != 0` filtering: pass
- Depth-without-trade ignored: pass
- Trade-then-trade flush behavior: pass
- Unsubscribed symbol isolation: pass
- Redis reconnect and resume: pass

Evidence files:
- [`/tmp/twse_smoke_phase1.json`](/tmp/twse_smoke_phase1.json)
- [`/tmp/twse_smoke_reconnect.json`](/tmp/twse_smoke_reconnect.json)

## 2) Remediation Scope and Decisions

### In scope

1. Restore official live CLI paths (`run_server --mode live`, `run_live`) so they run real engine logic over Redis providers.
2. Reintroduce session extension points needed by live state updates (hooks and optional dashboard snapshot callback).
3. Ensure install docs/dependencies match executable server/live code paths.
4. Make live startup robust when same-day replay files are absent (Redis-only mode).

### Out of scope

1. Strategy logic changes.
2. Frontend/dashboard redesign.
3. Historical parity refactors outside live path.

## 3) Implementation Plan

### Phase A — Restore replay/live engine contract (P0) [COMPLETED]

#### A1. Reintroduce provider/hooks callback contract in replay session

Update [`src/tw_signal_engine/replay/replay_session.py`](/Users/liyijing/Projects/Trading/VWAP-intraday-signal/signal-live-data/src/tw_signal_engine/replay/replay_session.py):

1. [x] Add optional parameters back to `run_daily_replay`:
   - `provider: MarketDataProvider | None = None`
   - `hooks: SessionHooks | None = None`
   - `on_dashboard_snapshot: Callable[[DashboardSnapshot], None] | None = None`
2. [x] Use `provider.iterate_ticks()` when provider is provided.
3. [x] Preserve replay-provider dependency injection: when `provider` is passed, use it directly; when absent, let the replay `data_source` select the default provider.
4. [x] Invoke hooks at deterministic points:
   - `on_tick` after index calc
   - `on_screening` after match_type resolution
   - `on_signal` when signal trigger condition is evaluated
   - `on_entry` immediately after successful `execute_entry`
   - `on_exit` when a leave cause is produced
   - `on_minute` on minute boundary transitions
5. [x] If `on_dashboard_snapshot` is provided, emit per-minute snapshots (`DashboardSnapshot`) at the same minute boundary used by `on_minute`.

#### A2. Keep session behavior shared

[x] Do not fork separate logic for replay/live. The same main event loop must run regardless of provider to avoid divergence.

### Phase B — Fix live CLIs to the restored contract (P0) [COMPLETED]

Update:
- [`src/tw_signal_engine/cli/run_server.py`](/Users/liyijing/Projects/Trading/VWAP-intraday-signal/signal-live-data/src/tw_signal_engine/cli/run_server.py)
- [`src/tw_signal_engine/cli/run_live.py`](/Users/liyijing/Projects/Trading/VWAP-intraday-signal/signal-live-data/src/tw_signal_engine/cli/run_live.py)

1. [x] Keep existing provider construction (`RedisLiveProvider` and optional `BackfillThenLiveProvider`).
2. [x] Pass `provider`, `hooks`, `on_dashboard_snapshot` to restored `run_daily_replay`.
3. [x] Add explicit engine-thread error propagation in `run_server --mode live`:
   - if engine thread raises, store fatal status in `LiveState` and surface via `/api/status`.
   - log full traceback and fail fast when startup crashes before first tick.

### Phase C — Resolve install/runtime dependency mismatch (P1) [COMPLETED]

Update [`pyproject.toml`](/Users/liyijing/Projects/Trading/VWAP-intraday-signal/signal-live-data/pyproject.toml):

1. [x] Make live/server runtime dependencies explicit and reproducible.
2. [x] Recommended split:
   - Core runtime dependencies remain minimal.
   - Add `live` extra: `fastapi`, `uvicorn`, `python-socketio`, `redis`, `pandas`, `pyarrow`.
3. [x] Update docs/CLI instructions to use:

```bash
uv sync --extra live
```

for live/server workflows.

### Phase D — Make live startup resilient to missing same-day files (P1) [COMPLETED]

Update history loading path (preferably in [`src/tw_signal_engine/market_data/load_history_window.py`](/Users/liyijing/Projects/Trading/VWAP-intraday-signal/signal-live-data/src/tw_signal_engine/market_data/load_history_window.py)):

1. [x] Add a `require_target_file: bool = True` option.
2. [x] For live mode (`run_live`, `run_server --mode live`), call with `require_target_file=False`.
3. [x] Preserve strict behavior for replay mode.

Result: live Redis start should not require synthetic placeholder files.

## 4) Test and Verification Plan

### 4.1 Automated tests (must pass)

1. Existing provider tests:
```bash
uv run pytest tests/unit/test_providers.py -q
```
2. New unit tests:
   - `run_daily_replay` accepts and uses injected provider.
   - Hook callbacks are fired with expected ordering on controlled ticks.
   - `run_server --mode live` startup path does not crash on stale signature.
3. Static checks:
```bash
uv run ruff check src tests
uv run mypy src
```

Execution status:
- [x] `uv run pytest tests/unit/test_providers.py -q` passed.
- [x] Added unit tests for restored `run_daily_replay` provider/hooks/snapshot contract.
- [x] Added unit tests for `run_server --mode live` startup/fail-fast behavior.
- [x] `uv run ruff check src tests` passed.
- [x] `uv run mypy src` passed.
- [x] `uv run pytest tests/unit/test_replay_session.py tests/unit/test_run_server_cli.py tests/unit/test_load_history_window.py -q` passed.
- [x] `uv run pytest tests -q` executed; only golden parity failures remained due missing baseline artifacts under `artifacts/baseline/cpp/`.

### 4.2 Manual smoke (official CLI path, no fallback harness)

1. Environment:
```bash
uv sync --extra live
```
2. Start Redis:
```bash
redis-server --port 6379
```
3. Start live server:
```bash
uv run python -m tw_signal_engine.cli.run_server \
  --mode live \
  --date 20260129 \
  --data-dir <real data dir or empty dir in Redis-only mode> \
  --files-dir exec/files \
  --group-file exec/files/group.csv \
  --config exec/cfg/parameter.cfg \
  --redis-host 127.0.0.1 \
  --redis-port 6379
```
4. Publish trade/depth pairs and assert:
   - `/api/status.tick_count` increases
   - `/api/status.last_time_str` advances
   - `/api/dashboard/status.mode == "live"`
5. Negative checks:
   - non-zero status code ignored
   - depth-only ignored
   - unsubscribed symbol does not change counters
6. Reconnect check:
   - stop/restart Redis
   - publish new valid pair
   - verify tick_count resumes growth

Execution status:
- [x] Completed on 2026-03-29 in Redis-only mode using official `run_server --mode live`.
- [x] Verified `/api/status.tick_count` growth, `/api/status.last_time_str` advancement, `/api/dashboard/status.mode == "live"`, negative-path filters, and reconnect resume.
- [x] Verified `run_live` CLI starts and runs without `TypeError` on restored signature path.

Artifacts:
- `/tmp/twse_live_cli_smoke_result.json`
- `/tmp/twse_live_server_smoke.log`
- `/tmp/twse_run_live_smoke.log`

### 4.3 Acceptance criteria

1. [x] `run_server --mode live` and `run_live` run without `TypeError`.
2. [x] Engine tick processing is active (not just HTTP process alive).
3. [x] Live API status reflects real progression and engine error state.
4. [x] Fresh environment setup for live mode is reproducible from project metadata/docs.
5. [x] Redis-only live startup works without requiring fake same-day replay files.

## 5) Risks and Mitigations

1. **Risk**: Hook insertion changes replay behavior.
   - **Mitigation**: hooks are optional and no-op by default; replay golden behavior remains unchanged when hooks/provider omitted.
2. **Risk**: Dependency expansion increases install footprint.
   - **Mitigation**: isolate in `live` extra and keep core minimal.
3. **Risk**: Minute-snapshot generation overhead in live mode.
   - **Mitigation**: emit once per minute boundary; keep snapshot fields minimal and deterministic.

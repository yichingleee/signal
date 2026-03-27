# Replay Loop Optimization Research

## Scope

This report investigates the remaining performance bottlenecks in the replay engine after the Phase 0–6 optimizations documented in `docs/design-docs/replay-runtime-optimization-verification.md`. Those optimizations eliminated history-loading overhead (from ~9.5 minutes to 0 ms with warm cache), but the replay loop itself (`readFileMerged`) still consumes ~95% of wall time. This report digs into root causes, explains the observed anomaly and scaling behaviour, and proposes concrete optimizations with expected impact.

Investigated on 2026-03-25 by reading the current codebase at commit `7ae47fc`.

---

## Observations Requiring Explanation

### O1. readFileMerged scales 3.2× with history depth (19s → 62s)

The Dec–Jan block in the full-range batch shows `readFileMerged` growing from 18,924 ms (1-day history on 20251231) to ~61–68 ms (21-day history by late January). The verification doc notes this is "incremental screening computation cost" rather than history-load cost.

### O2. 20260130 anomaly — 95s gap between readFileMerged and TOTAL

On 20260130, TOTAL was 156,203 ms but readFileMerged was 61,152 ms. The batch used `--no-charts`, so chart generation is not the cause. The ~95s gap occurs between the replay loop ending (`replay_session.py:422`) and the TOTAL timer (`replay_session.py:441`), spanning only `_finalize_open_positions()` + `_generate_reports()` — both near-instantaneous for 1 trade with no charts.

### O3. getGroup occasionally spikes (58 ms on 20260116, 52 ms on 20260211)

Most days show 7–19 ms, but two days spike to 52–58 ms. The `initialize_validity()` function loops over all group members × history slots, but this is O(groups × members × slots) = O(150 × 14 × 21) ≈ 44K iterations — not enough to explain 50 ms. These are likely OS-level cache effects.

---

## Root Cause Analysis

### RC1. Per-tick volume query scales linearly with history depth

**Location**: `evaluate_strong_group.py:197`, `evaluate_strong_single.py:105,112`

```python
total_vol = sum(self.vol_cum[i].query(symbol, match_time_us) for i in range(len(self.vol_cum)))
```

This sums across all `N` history slots (up to 21) for every qualifying tick. Each `LinearVolumeTracker.query()` (`market_data_records.py:27-39`) uses a cursor-based amortized-O(1) walk, but:

1. **21 dict lookups per call** — `data_store.get(symbol)` + `_cursors.get(symbol, 0)` + `_cursors[symbol] = cursor` = 3 dict operations × 21 slots = 63 dict operations per tick
2. **Python call overhead** — 21 method calls + 21 generator `yield` in the `sum(... for i in ...)` comprehension
3. **While-loop cursor walks** — amortized O(1) per slot, but with 21 slots the total cursor advancement cost is 21× the single-slot cost

This is the **primary cause** of O1. With 1 history slot, line 197 does 1 query; with 21 slots, it does 21 queries. The 3.2× slowdown (19s → 62s) is consistent with:
- readFileMerged with 1 slot: text parsing dominates (~19s)
- readFileMerged with 21 slots: text parsing (~19s) + screening overhead (~43s)
- Screening overhead scales roughly linearly with slot count

**Evidence**: On 20251231 (1-day history, no vol_cum queries meaningful), readFileMerged = 18,924 ms. On 20260130 (21-day history), readFileMerged = 61,152 ms. The ~42s difference is attributable to 21-slot volume queries over ~1.76M ticks.

### RC2. `_group_percentage_chg()` is called twice per group per tick

**Location**: `evaluate_strong_group.py:135` (inside `_is_valid_group`) and `:190` (in `on_tick`)

```python
# Line 135 — called inside _is_valid_group
avg_pct = self._group_percentage_chg(group, self.config.is_weighted_avg)

# Line 190 — called again with the exact same arguments
g_pct = self._group_percentage_chg(group, self.config.is_weighted_avg)
```

Each call iterates over **all group members** (avg 13.9, max 105 per group). For a symbol in 2 groups, this means 4 calls × 13.9 iterations = 55.6 member iterations per tick. Half of these are pure redundancy.

### RC3. GroupRank re-sorts on every mutation

**Location**: `group_state.py:29-36`

```python
def on_tick(self, name: str, gain: float) -> None:
    # ... update dicts ...
    self._invalidate()  # clears sorted cache every time
```

Every call to `on_tick()` invalidates the sorted cache. The next call to `is_top_n()` or `get_rank()` triggers `sorted(self._gain_to_name.items(), reverse=True)` — O(n log n) where n = number of entries.

This is called from multiple paths per tick:
- `evaluate_strong_group.py:165` — raw VWAP rank update
- `evaluate_strong_group.py:191` — group rank update
- `evaluate_strong_group.py:231` — member VWAP rank update

Each path invalidates → the next query re-sorts. Within a single tick's processing, the sorted cache may be rebuilt 3–4 times.

### RC4. TopKVolumeTracker does full sort on pool-member updates

**Location**: `top_volume_pool.py:29,41-51`

```python
def on_tick(self, symbol: str, volume_delta: int) -> None:
    # ...
    if symbol in self._in_top:
        self._rebuild_if_needed()  # FULL SORT of all volumes
        return
```

For the ~200 symbols in the top-K pool, every tick triggers `sorted(self._all_volumes.items(), ...)` over all tracked symbols. This is O(S log S) where S can be 1,000+.

### RC5. MarketTick allocates 10 unused QuotePair objects

**Location**: `market_event_records.py:25-26`

```python
bid: list[QuotePair] = field(default_factory=lambda: [QuotePair() for _ in range(5)])
ask: list[QuotePair] = field(default_factory=lambda: [QuotePair() for _ in range(5)])
```

Every tick allocates 10 QuotePair objects (5 bid + 5 ask), but only `bid[0]` and `ask[0]` are ever used. At ~1.6M ticks/day, this is 16M wasted object allocations.

### RC6. 20260130 anomaly — GC or OS-level memory stall

The 95s gap between `readFileMerged` and `TOTAL` occurs at the boundary between the replay loop's generator teardown and report writing. The code between these points (`replay_session.py:424-438`) is trivial for 1 trade with `--no-charts`.

The most likely cause is **Python garbage collection or macOS memory management**:

1. **Generator teardown**: When the `for tick in merge_market_streams(...)` loop completes at line 422, the generator chain (merge_market_streams → iterate_market_file × 2) gets garbage-collected along with all intermediate state
2. **Accumulated allocations**: 20260130 is the 22nd date in the batch. While the rolling history provider drops old sessions, `_merge_history_windows()` creates new `LinearVolumeTracker` and `dict` objects each iteration (line 63 of `run_batch_replay.py`). The previous iteration's merged_history isn't freed until GC runs
3. **Large reference graphs**: Each `LinearVolumeTracker` holds `data_store: dict[str, list[TickNode]]` with ~1,800 symbols × hundreds of TickNode objects per symbol × 21 slots. The merged version from `_merge_history_windows()` creates copies (`list(nodes)` at line 94 of `replay_session.py`), doubling the live object count temporarily
4. **macOS memory pressure**: With multiple GB of Python objects accumulated across 22 dates, macOS may have triggered memory compaction or swap, causing the stall

**Supporting evidence**: This anomaly occurred only once in both the January batch and the full-range batch, and only on the 22nd date. The cross-run consistency section shows the January sub-batch total varies by ~5%, suggesting run-to-run variance. A one-time 95s GC/OS stall is within the realm of one-off system events.

**Remediation**: Force `gc.collect()` between dates in batch mode to prevent accumulation. Add timing around the post-loop section to isolate whether the stall is in GC, reporting, or generator teardown.

---

## Proposed Optimizations

### P0. Pre-aggregate vol_cum into a single merged timeline per symbol

**Problem**: 21 separate `LinearVolumeTracker.query()` calls per qualifying tick (RC1)

**Approach**: At initialization time (after history loading, before the replay loop), build a single aggregated volume timeline per symbol that sums cumulative volumes across all history slots at each timestamp.

```python
class AggregatedVolumeTracker:
    """Pre-merged volume across all history days for O(1) per-tick query."""

    def __init__(self, vol_cum: list[LinearVolumeTracker]) -> None:
        self._data: dict[str, list[TickNode]] = {}
        self._cursors: dict[str, int] = {}
        self._num_days = len(vol_cum)
        self._build(vol_cum)

    def _build(self, vol_cum: list[LinearVolumeTracker]) -> None:
        # For each symbol, find the maximum cumulative volume across all days
        # at the end of each day, then build a lookup.
        #
        # Key insight: vol_cum[i].query(symbol, T) returns the cumulative volume
        # for that symbol up to time T on day i. We need sum across all days.
        #
        # Since each day's timeline is sorted by timestamp, and the replay loop
        # queries with monotonically increasing timestamps, we can pre-merge
        # all timelines into a single sorted timeline where each node stores
        # the sum-of-cumulative-volumes at that timestamp.
        all_symbols: set[str] = set()
        for tracker in vol_cum:
            all_symbols.update(tracker.data_store.keys())

        for symbol in all_symbols:
            # Collect all (timestamp, day_index, cum_qty) events
            events: list[tuple[int, int, int]] = []
            for day_idx, tracker in enumerate(vol_cum):
                nodes = tracker.data_store.get(symbol)
                if nodes:
                    for node in nodes:
                        events.append((node.timestamp, day_idx, node.cumulative_qty))

            if not events:
                continue

            # Sort by timestamp
            events.sort()

            # Walk through events, maintaining running sum across all days
            day_latest: dict[int, int] = {}  # day_idx -> latest cum_qty
            merged: list[TickNode] = []
            running_sum = 0

            for ts, day_idx, cum_qty in events:
                old_val = day_latest.get(day_idx, 0)
                running_sum += (cum_qty - old_val)
                day_latest[day_idx] = cum_qty
                merged.append(TickNode(timestamp=ts, cumulative_qty=running_sum))

            self._data[symbol] = merged

    def query(self, symbol: str, timestamp: int) -> int:
        """Same cursor-based amortized O(1) query, but over the merged timeline."""
        history = self._data.get(symbol)
        if not history:
            return 0
        cursor = self._cursors.get(symbol, 0)
        while cursor + 1 < len(history) and history[cursor + 1].timestamp <= timestamp:
            cursor += 1
        self._cursors[symbol] = cursor
        if history[cursor].timestamp > timestamp:
            return 0
        return history[cursor].cumulative_qty
```

The evaluators would change from:
```python
total_vol = sum(self.vol_cum[i].query(symbol, match_time_us) for i in range(len(self.vol_cum)))
avg = total_vol // num_days if total_vol > 0 else 1
```
to:
```python
total_vol = self.agg_vol.query(symbol, match_time_us)
avg = total_vol // num_days if total_vol > 0 else 1
```

**Complication**: `evaluate_strong_single.py:112` also queries `vol_cum[0]` (yesterday only) separately:
```python
cum_vol_yesterday = self.vol_cum[0].query(symbol, match_time_us) if self.vol_cum else 0
```
This needs the per-day tracker preserved for slot 0, or a second pre-aggregated tracker for "yesterday only." A clean solution: keep `vol_cum[0]` as-is for yesterday-specific queries, and add `agg_vol` for the sum-across-all-days query.

**Build cost**: O(T log T) per symbol where T = total tick events across all history days. For 1,800 symbols × ~21 days × ~1000 events/symbol/day = ~38M events total. The sort is per-symbol, so average 21K events per symbol → build time ≈ a few seconds. This is one-time at startup.

**Expected impact**: Eliminates 20 of 21 per-tick dict lookups + method calls on every qualifying tick. For 1.76M ticks with 21 slots, this removes ~35M dict operations and ~35M method calls per day. Estimated readFileMerged reduction of **15–25s** on late-period days (from ~62s to ~37–47s).

---

### P1. Eliminate duplicate `_group_percentage_chg()` calls

**Problem**: Same function called twice per group per tick with identical arguments (RC2)

**Fix**: Compute once in `on_tick()`, pass result to `_is_valid_group()`:

```python
def _is_valid_group(self, symbol: str, group: str, group_pct: float) -> bool:
    cond1 = self.trading_value_month_avg.get(symbol, 0) >= self.config.member_min_month_trading_val
    cond2 = self.group_trading_value_month_avg_sum.get(group, 0) >= self.config.group_min_month_trading_val
    cond3 = group_pct > self.config.group_min_avg_pct_chg
    # ... rest unchanged
    return cond1 and cond2 and cond3 and cond4

def on_tick(self, ...):
    for group in self.symbol_to_groups[symbol]:
        g_pct = self._group_percentage_chg(group, self.config.is_weighted_avg)
        if not self._is_valid_group(symbol, group, g_pct):
            continue
        self.group_rank.on_tick(group, g_pct)
        # ...
```

**Additional optimization**: Short-circuit `_is_valid_group` by evaluating cheap conditions (cond1, cond2) before the expensive `_group_percentage_chg()`:

```python
def on_tick(self, ...):
    for group in self.symbol_to_groups[symbol]:
        # Pre-check cheap conditions before computing group pct
        if self.trading_value_month_avg.get(symbol, 0) < self.config.member_min_month_trading_val:
            continue
        if self.group_trading_value_month_avg_sum.get(group, 0) < self.config.group_min_month_trading_val:
            continue

        group_tv_cumu = self.group_trading_value_cumu.get(group, 0)
        group_tv_month = self.group_trading_value_month_avg_sum.get(group, 1)
        val_ratio = group_tv_cumu / group_tv_month if group_tv_month > 0 else 0.0
        if val_ratio <= self.config.group_min_val_ratio:
            continue

        # Only compute expensive group_pct if all cheap conditions pass
        g_pct = self._group_percentage_chg(group, self.config.is_weighted_avg)
        if g_pct <= self.config.group_min_avg_pct_chg:
            continue

        self.group_rank.on_tick(group, g_pct)
        # ...
```

**Expected impact**: Eliminates 50% of `_group_percentage_chg()` calls, and the short-circuit avoids even that 50% for groups failing cheap conditions. Estimated savings: **3–8s** per day on late-period dates, depending on how many groups pass the cheap filters.

---

### P2. Cache group percentage change with invalidation

**Problem**: `_group_percentage_chg()` recomputes over all members even when the group's state hasn't changed since the last call (RC2)

**Approach**: Maintain incremental state: track each member's last contribution, and only recompute when the contributing symbol trades.

```python
def __init__(self, ...):
    # ...
    self._group_pct_cache: dict[str, float] = {}
    self._group_pct_dirty: set[str] = set()

def on_tick(self, ...):
    # Invalidate groups this symbol belongs to
    for group in self.symbol_to_groups[symbol]:
        self._group_pct_dirty.add(group)

    # ...later...
    def _group_percentage_chg_cached(self, group):
        if group in self._group_pct_dirty:
            result = self._group_percentage_chg(group, self.config.is_weighted_avg)
            self._group_pct_cache[group] = result
            self._group_pct_dirty.discard(group)
            return result
        return self._group_pct_cache.get(group, 0.0)
```

**Expected impact**: If a tick's symbol belongs to group A and B, only those 2 groups are recomputed. The other 148 groups return cached values. For ticks from symbols in non-overlapping groups (97% of ticks based on membership fanout), this eliminates nearly all redundant member iteration. Estimated savings: **2–5s** per day.

Combined with P1, total group-computation savings: **5–12s**.

---

### P3. Slim down MarketTick allocation

**Problem**: 10 QuotePair objects allocated per tick, only 2 used (RC5)

**Fix**: Replace bid/ask lists with scalar fields:

```python
@dataclass(slots=True)
class MarketTick:
    symbol: str = ""
    market: str = ""
    match_time_str: int = 0
    match_time_us: int = 0
    status_code: int = 0
    trade_code: int = 0
    match: QuotePair = field(default_factory=QuotePair)
    best_bid_price: int = 0     # was bid[0].price
    best_ask_price: int = 0     # was ask[0].price
    trade_at: int = 0
    is_limit_up_locked: bool = False
    is_limit_down_locked: bool = False
    prev_limit_up: bool = False
    volatility_pause: bool = False
    total_match_qty: int = 0
    total_bid_qty: int = 0
    total_ask_qty: int = 0
```

All call sites that reference `tick.bid[0].price` change to `tick.best_bid_price` (similarly for ask). The `_finalize_open_positions` dummy tick also simplifies.

**Expected impact**: Eliminates 10 object allocations + 2 list allocations per tick. At 1.6M ticks/day, saves ~19.2M object creations. Python object creation is ~100–200 ns each, so this saves approximately **2–4s** per day.

---

### P4. Replace GroupRank with incremental sorted structure

**Problem**: Full O(n log n) re-sort on every mutation (RC3)

**Option A** — `sortedcontainers.SortedList` (pure Python, no C deps):

```python
from sortedcontainers import SortedList

class GroupRank:
    def __init__(self) -> None:
        self._sorted = SortedList()           # (neg_gain, name) for descending order
        self._name_to_gain: dict[str, float] = {}

    def on_tick(self, name: str, gain: float) -> None:
        old_gain = self._name_to_gain.get(name)
        if old_gain is not None:
            self._sorted.discard((-old_gain, name))
        self._name_to_gain[name] = gain
        self._sorted.add((-gain, name))

    def is_top_n(self, name: str, n: int) -> bool:
        gain = self._name_to_gain.get(name)
        if gain is None:
            return False
        idx = self._sorted.bisect_right((-gain, name))
        return idx <= n

    def get_rank(self, name: str) -> int:
        gain = self._name_to_gain.get(name)
        if gain is None:
            return -1
        idx = self._sorted.index((-gain, name))
        return idx + 1
```

This gives O(log n) updates and O(log n) rank queries instead of O(n log n) sorts + O(n) linear scans.

**Option B** — Keep current structure but add a dirty-threshold check:

```python
def on_tick(self, name: str, gain: float) -> None:
    old_gain = self._name_to_gain.get(name)
    if old_gain is not None and abs(gain - old_gain) < 1e-8:
        return  # No meaningful change, skip sort
    # ... existing logic ...
```

**Expected impact**: With 150 groups, the sort is O(150 log 150) ≈ O(1K). This is called ~3× per qualifying tick. With ~1.6M qualifying ticks, it's ~4.8M sorts × 1K operations = ~5B operations. Using SortedList reduces this to ~4.8M × O(log 150) ≈ ~35M operations. Estimated savings: **3–6s** per day.

**Note**: `sortedcontainers` would be a new dependency. Option B is zero-dependency but less effective. An alternative is a hand-rolled skip list or bisect-based insertion.

---

### P5. Fix TopKVolumeTracker rebuild thrashing

**Problem**: Full sort of all volumes on every tick for pool members (RC4)

**Fix**: Only rebuild when the current tick could change pool membership. Since the pool has K=200 members and volumes only increase, a member tick can never remove itself from the pool.

```python
def on_tick(self, symbol: str, volume_delta: int) -> None:
    old_vol = self._all_volumes.get(symbol, 0)
    new_vol = old_vol + volume_delta
    self._all_volumes[symbol] = new_vol

    if symbol in self._in_top:
        return  # already in pool, volume can only increase → stays in pool

    if len(self._in_top) < self._k:
        self._in_top.add(symbol)
        heapq.heappush(self._heap, (new_vol, symbol))
        if len(self._heap) == self._k:
            self._min_threshold = self._heap[0][0]
        return

    if new_vol > self._min_threshold:
        self._rebuild_if_needed()
```

**Expected impact**: Eliminates the full sort for the ~80% of ticks that are pool-member updates. The rebuild only triggers when a new symbol potentially enters the pool. Estimated savings: **1–3s** per day.

---

### P6. Binary replay cache format

**Problem**: Text parsing (split, int conversion) dominates the replay loop

**Approach**: Build a binary cache of replay files — similar to volcache for history, but for the day's replay data. On first run, parse text and write a binary file. On subsequent runs, read the binary file directly.

Format per tick (fixed-size record, 32 bytes):
```
symbol_id:   u16   (2 bytes, mapped from symbol string)
match_time:  u64   (8 bytes, raw HMMSS000000)
status_code: u8    (1 byte)
trade_code:  u8    (1 byte)
price:       i32   (4 bytes)
qty:         i32   (4 bytes)
best_bid:    i32   (4 bytes)
best_ask:    i32   (4 bytes)
trade_at:    u8    (1 byte)
_padding:    3 bytes
```

With `struct.unpack` or `numpy.frombuffer`, a day's 1.6M ticks = ~51 MB binary file, readable in <1s versus ~35s for text parsing.

**Implementation steps**:
1. Build a symbol → u16 mapping file alongside the binary cache
2. On cache miss, parse text file and write binary cache
3. On cache hit, `mmap` or `read` the binary file and unpack
4. The binary file is market-specific (OTC/TSE), so the merge step remains

**Cache staleness**: Same approach as volcache — check mtime + size of the text source file.

**Expected impact**: Reduces `readFileMerged` from ~35–60s (text parsing) to ~3–8s (binary read + processing). This is the **single largest potential improvement**, potentially yielding a **5–10×** speedup on the replay loop.

**Trade-offs**:
- Additional disk space: ~51 MB per market per day (~100 MB/day total) vs ~1.5 GB text
- Cache-build cost: Same as current text parse time (one-time)
- Maintenance: Cache must be invalidated when source files change (same as volcache)

---

### P7. Cython/native extension for the parser hotpath

**Problem**: Even with binary replay cache, Python-level per-tick dispatch is slow

**Approach**: Compile the inner loop as a Cython extension:
- `iterate_market_file.py` → `iterate_market_file.pyx`
- `parse_format6_replay_rows.py` → `parse_format6_replay_rows.pyx`
- `merge_market_streams.py` → `merge_market_streams.pyx`

With typed declarations (`cdef`, `cpdef`, typed memoryviews), Cython can eliminate Python object overhead and generate C-level tight loops.

**Expected impact**: 3–5× speedup on text parsing, stacking with P6 for total parsing time <1s. However, this adds build complexity (requires Cython compiler, platform-specific wheels).

**Alternative**: Use `cffi` or `ctypes` with a small C library for just `parse_trade_line`.

---

### P8. Force GC between batch dates

**Problem**: The 20260130 anomaly (RC6) — possible GC stall from accumulated objects

**Fix**: Add explicit GC between dates in the batch loop:

```python
# In run_batch_replay.py, after each date:
import gc
gc.collect()
```

Additionally, null out `merged_history` before the next iteration to allow the previous objects to be freed:

```python
for date in dates:
    hw_otc = otc_provider.get_history(date)
    hw_tse = tse_provider.get_history(date)
    merged_history = _merge_history_windows(hw_otc, hw_tse)

    day_trades = run_daily_replay(..., history=merged_history, ...)
    all_trades.extend(day_trades)

    del merged_history  # release references before next iteration
    gc.collect()
```

**Expected impact**: Prevents GC stall from accumulating across dates. Near-zero cost (~50 ms per `gc.collect()`). Eliminates the class of anomalies like the 20260130 95s stall.

---

### P9. Add post-loop timing instrumentation

**Problem**: The 95s anomaly was discovered only because TOTAL − readFileMerged was unexpectedly large. There's no timing between these two points.

**Fix**: Add timing around each post-loop step:

```python
# In replay_session.py, after line 422:
t_post = time.time()
_finalize_open_positions(...)
print(f"[TIMING] finalize: {(time.time() - t_post) * 1000:.0f} ms")

t_post = time.time()
_generate_reports(...)
print(f"[TIMING] reports: {(time.time() - t_post) * 1000:.0f} ms")
```

This is a diagnostic fix — no performance impact, but prevents future anomalies from being mysterious.

---

## Prioritized Implementation Plan

| Priority | Optimization | Est. Savings (per day) | Complexity | Dependencies |
| --- | --- | --- | --- | --- |
| **P0** | Pre-aggregate vol_cum | 15–25s | Medium | None |
| **P1** | Eliminate duplicate group_pct + short-circuit | 5–12s | Low | None |
| **P3** | Slim MarketTick (remove unused QuotePairs) | 2–4s | Low | Touches many call sites |
| **P4** | GroupRank incremental sort | 3–6s | Medium | Optional new dep |
| **P5** | Fix TopKVolumeTracker rebuild | 1–3s | Low | None |
| **P6** | Binary replay cache | 30–55s | High | New subsystem |
| **P7** | Cython parser | 10–30s (on top of P6) | High | Build infra |
| **P8** | Force GC between batch dates | Prevents anomalies | Trivial | None |
| **P9** | Post-loop timing instrumentation | Diagnostic only | Trivial | None |

### Recommended execution order

**Phase A** (low-hanging fruit, no new infrastructure):
1. P8 + P9 — trivial, prevents/diagnoses anomalies
2. P1 — eliminate redundant group_pct calls, simple refactor
3. P5 — fix TopKVolumeTracker, simple logic change
4. P3 — slim MarketTick, requires updating call sites

**Phase B** (medium complexity, significant impact):
5. P0 — pre-aggregate vol_cum (biggest algorithmic win)
6. P4 — GroupRank incremental sort
7. P2 — cache group_pct with invalidation

**Phase C** (new subsystem, transformative impact):
8. P6 — binary replay cache (shifts the bottleneck from parsing to computation)
9. P7 — Cython parser (only worthwhile after P6 to squeeze remaining gains)

### Expected cumulative impact

| After Phase | Est. readFileMerged (21-day, late-period) | Speedup vs current |
| --- | --- | --- |
| Current | ~60s | 1× |
| Phase A (P1+P3+P5) | ~45–50s | 1.2–1.3× |
| Phase B (P0+P2+P4) | ~25–35s | 1.7–2.4× |
| Phase C (P6) | ~5–10s | 6–12× |
| Phase C (P6+P7) | ~2–5s | 12–30× |

---

## Impact on Batch Performance

Current 36-date batch: **36 min 18s** (avg 51.6s/day).

| After Phase | Est. batch time | Notes |
| --- | --- | --- |
| Phase A | ~30 min | Low-risk quick wins |
| Phase B | ~17–22 min | Algorithmic improvements |
| Phase C (P6) | ~5–8 min | Binary cache eliminates parsing |
| Phase C (P6+P7) | ~3–5 min | Near-theoretical minimum for pure Python processing |

At Phase C, the bottleneck shifts from I/O and parsing to the screening/signal computation itself (~5–10s/day), which is already well-optimized.

---

## Appendix: Data Flow Summary

```
replay file (text, ~1.5 GB/market/day)
    │
    ├── iterate_market_file()     ← tick_filter eliminates ~70% of lines
    │       │
    │       ├── _extract_symbol_fast()   ← index-based, fast
    │       ├── parse_trade_line()       ← split(",", 6) + 4× int()
    │       └── _get_best_prices()       ← find() + char scan
    │
    ├── merge_market_streams()    ← two-pointer merge, O(1)/tick
    │
    └── replay loop (replay_session.py:258-421)
            │
            ├── IndexCalc.calc()          ← O(1), fast
            ├── on_tick_exit()            ← only for held positions
            ├── strong_single.on_tick()   ← vol_cum query × N slots ← RC1
            ├── strong_group.on_tick()    ← vol_cum × N + group_pct × members ← RC1, RC2, RC3
            ├── evaluate_signal_a()       ← O(1), fast
            ├── evaluate_signal_b()       ← rolling windows, amortized O(1)
            └── execute_entry()           ← rare (0-8 times/day)
```

---

## Appendix: Measurement Plan for Validation

To validate the estimates above, each optimization should be benchmarked on:

1. **20251231** (1-day history) — isolates pure parsing cost
2. **20260130** (21-day history, standalone) — isolates screening + parsing cost
3. **January batch** (21 dates) — measures cumulative/batch-mode effects
4. **20260319** (largest readFileMerged at 94,951 ms) — worst-case validation

Compare readFileMerged times before and after each optimization. Verify trade counts and PnL are identical to baseline.

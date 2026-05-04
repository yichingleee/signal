# Market-Data Migration Report

**Date:** 2026-04-08
**Source root:** `/Users/liyijing/Projects/Trading/market-data`
**Target consumers:** `tw_signal_engine` replay + live (currently reads `exec/data/{TSE,OTC}Quote.YYYYMMDD` and `exec/files/{Symbols_*.csv,group.csv}`)
**Status:** Discovery + design — no code changes proposed in this document.

This report supersedes the per-symbol analysis in
[`parquet-tick-data-integration-report.md`](parquet-tick-data-integration-report.md), which was
written against `data/test/1101.parquet` (a different, single-symbol layout). The new
`market-data/tick-data/{TWSE,TPEX}/YYYYMMDD.parquet` files use a one-file-per-day,
all-symbols layout that resolves several blockers flagged in the earlier draft.

---

## 1. Executive Summary

| Question | Answer |
|---|---|
| Can the new parquet tick files replace `TSEQuote.*` / `OTCQuote.*`? | **Yes.** Every field consumed by `parse_format6_replay_rows` and `parse_history_trades` is present (or trivially derived). |
| Will I/O get faster? | **Yes — by ~30–100×.** Cold-cache replay-day load drops from ~16 s/day (full Python parse of 2 GB text) to ~0.13 s/day (pyarrow column-projected read of a 183 MB parquet). |
| Will disk usage shrink? | **Yes — ~10×.** TSE+OTC text for 2026-03-26 = 2.45 GB → TWSE+TPEX parquet = 241 MB. |
| Are `market-data/symbols/Symbols_*.csv` valid? | **Yes — byte-identical** to `exec/files/Symbols_*.csv` for all 86 overlapping dates. Same encoding (cp950), same 9-column layout. |
| Are `market-data/group/*.csv` valid? | **Yes — both.** `group-ver20260329.csv` is byte-identical to today's `exec/files/group.csv`. `group-ver20260408.csv` has been **product-validated** as the intended new (smaller) universe, but its 23-column padding is an upstream CSV-writer bug that must be fixed before promotion. Default stays at `group-ver20260329.csv`; the 20260408 file remains quarantined until upstream re-exports it as a clean 3-column file. |
| Major migration blockers | (a) Coverage gaps — `Symbols_20260304.csv` is committed for backfill; 6 trailing dates (`20260327, 20260330, 20260331, 20260401, 20260402, 20260407`) are deferred and will be unreplayable until a future data-ops pass fetches them; (b) `tradePrice` is float, pipeline is `int * 10000`; (c) `status_code`-equivalent must be derived from `matchFlag`/`tradeVolume`. |

**Verdict:** Migration is recommended, gated on the data-hygiene fixes in §7 and the
phased plan in §8. The new format is strictly richer (5-level book, session VWAP,
cumulative volume, trend/limit/match flags) — none of these signals are exposed by the
current text-based ingestion path.

**Implementation decisions (2026-04-08):**

- **`group-ver20260408.csv` is product-validated** but the 23-column padding is an
  accidental upstream CSV-writer bug. Do NOT make it the default. Keep
  `group-ver20260329.csv` as the canonical `group.csv` until upstream re-exports a
  clean 3-column file; promotion of the new universe is deferred to a separate
  follow-up. The file stays under `market-data/group/` as a quarantined reference.
- **Missing `Symbols_*.csv` coverage:** `Symbols_20260304.csv` will be backfilled
  from upstream (data-ops action item, not blocking this design). The 6 most-recent
  trailing dates (`20260327, 20260330, 20260331, 20260401, 20260402, 20260407`) are
  explicitly deferred — they will be fetched in a future pass, and replay of those
  specific dates remains unsupported until then. The engine should clearly surface
  the missing-date list rather than crash.

---

## 2. Inventory of `market-data/`

```
market-data/
├── group/
│   ├── group-ver20260329.csv      50,537 B   3-col schema (matches current group.csv)
│   └── group-ver20260408.csv      52,385 B   23-col schema (DIFFERENT — see §6)
├── symbols/                        86 files   Symbols_YYYYMMDD.csv (cp950, 9-col)
│   └── Symbols_20251112.csv .. Symbols_20260326.csv
└── tick-data/
    ├── TWSE/                       57 files   YYYYMMDD.parquet, 10.66 GB total, ~192 MB/file
    │   └── 20260102.parquet .. 20260407.parquet
    └── TPEX/                       57 files   YYYYMMDD.parquet,  3.15 GB total, ~57 MB/file
        └── 20260102.parquet .. 20260407.parquet
```

Cross-coverage:

| Asset | First date | Last date | # files | Notes |
|---|---|---|---|---|
| `symbols/Symbols_*.csv` | 20251112 | 20260326 | 86 | Stops 13 calendar days before today (2026-04-08) |
| `tick-data/TWSE/*.parquet` | 20260102 | 20260407 | 57 | |
| `tick-data/TPEX/*.parquet` | 20260102 | 20260407 | 57 | |
| Common dates (Symbols ∩ TWSE ∩ TPEX) | — | — | **50** | Days that can run end-to-end today |

**Tick days with NO matching `Symbols_*.csv`:**

- `20260304` — **committed for backfill** (historical gap, data-ops will fetch from
  upstream archive).
- `20260327`, `20260330`, `20260331`, `20260401`, `20260402`, `20260407` — **deferred**
  (6 trailing dates; will be fetched in a future data-ops pass, not blocking the
  migration design).

These cannot be replayed until a Symbols file is sourced — `replay_session.load_symbol_reference()`
raises `FileNotFoundError` if missing. The engine should print the missing-date list
on startup rather than fail mid-batch (see R4 in §9).

---

## 3. New tick parquet — schema and semantics

### 3.1 Schema (TWSE and TPEX are identical)

```
symbol            string         e.g. "1101"
date              int32          YYYYMMDD
time              int64          HHMMSSffffff   (same convention as old match_time_str)
seqno             int64          per-day monotonic feed sequence
remark            string         row remark/flag (often blank, occasionally 'T')
trendFlag         string         1-char trend marker
matchFlag         string         'Y' = trade snapshot, ' ' = quote-only snapshot
tradeLimitFlag    string         circuit/limit indicator
tradePrice        double         last trade price in 元 (e.g. 26.10)
tradeVolume       int32          shares matched in THIS snapshot (0 = quote-only)
transactionVolume int32          cumulative session volume up to this row
vwap              double         cumulative session VWAP in 元
tickSizeBuy       int8           number of populated bid levels (0-5)
limitBuyFlag      string         buy-side limit-up lock indicator
buyPrice1..5      double         5 bid levels in 元
buyVolume1..5     int32          5 bid sizes
tickSizeSell      int8           number of populated ask levels (0-5)
limitSellFlag     string         sell-side limit-down lock indicator
sellPrice1..5     double         5 ask levels in 元
sellVolume1..5    int32          5 ask sizes
```

Total: **36 columns**, snappy-compressed by default.

### 3.2 File scale (sample: `TWSE/20260326.parquet`)

| Metric | Value |
|---|---|
| File size on disk | 183 MB |
| Total rows | 8,511,403 |
| Distinct symbols | 1,073 |
| Row groups | ~170 (50,000 rows each) |
| Trade-only rows (`tradeVolume > 0`) | 1,147,375 (13.5%) |
| matchFlag = `'Y'` rows | 1,297,860 (incl. pre-open simulated matches) |

For the same date the legacy TSE text file is **2,071 MB** with 1,460,886 `Trade,…` lines
(1,292,891 valid after `status_code == 0` filter in `parse_history_trades`).

### 3.3 Semantic mapping vs current `MarketTick`

| `MarketTick` field | Old text source | New parquet source | Notes |
|---|---|---|---|
| `symbol` | Trade line col 1 | `symbol` | Identical |
| `market` | filename prefix `TSE`/`OTC` | directory `TWSE`/`TPEX` | Bind at the loader layer |
| `match_time_str` | Trade line col 2 (int) | `time` (int64) | **Same `HMMSSffffff` convention** |
| `match_time_us` | derived via `_convert_raw_time_to_us` | derived from `time` (same fn) | No change |
| `status_code` | Trade line col 3 | derive: `0 if matchFlag=='Y' and time >= 9:00 else skip` | See §3.4 |
| `match.price` (int×10000) | Trade line col 4 (already int×10000) | `round(tradePrice * 10000)` | Float → int conversion (use `round`, not `int`) |
| `match.qty` | Trade line col 5 | `tradeVolume` | Identical |
| `bid[0].price` | parsed from Depth `BID:N,P*Q,...` | `round(buyPrice1 * 10000)` | Identical |
| `ask[0].price` | parsed from Depth `ASK:N,P*Q,...` | `round(sellPrice1 * 10000)` | Identical |
| `bid[1..4].price/qty` | not currently extracted | `buyPrice2..5`, `buyVolume2..5` | **Bonus** — full L5 book becomes available |
| `ask[1..4].price/qty` | not currently extracted | `sellPrice2..5`, `sellVolume2..5` | **Bonus** |
| `trade_at` | `1 if price==bid_price else 2` | identical inference, single row (no Trade/Depth join needed) | Simpler |
| `is_limit_up_locked` | not set in replay | derivable from `limitBuyFlag` / `tradeLimitFlag` | Currently unused in replay, future-proofs Signal B |
| `volatility_pause` | computed from `NumTracker` | unchanged | Same downstream logic |

### 3.4 `status_code` equivalence

The legacy parser drops any Trade line whose 4th column is non-zero (intra-day
auctions, limit-up resets, error corrections — ~12% of all `Trade,` lines on
2026-03-26).

In the new format the equivalent filter is:

```python
# trade events that match the legacy iter_history_trades semantics
mask = (df["tradeVolume"] > 0) & (df["time"] >= 90_000_000_000)
```

Empirical row counts on 2026-03-26 (TWSE only):

| Filter | Rows | vs legacy |
|---|---|---|
| Legacy TSE text, `status_code == 0` | 1,292,891 | baseline |
| `matchFlag == 'Y'` | 1,297,860 | +0.4% (includes some pre-open simulated matches) |
| `tradeVolume > 0` | 1,147,375 | -11.3% (drops snapshots that re-state the last trade with no new shares) |
| `tradeVolume > 0 AND time >= 9:00` | **1,147,375** | -11.3% |

The 11% gap is the most important open question. Two hypotheses, both testable:

1. **Snapshot-vs-tick-by-tick:** the new feed publishes one snapshot per dissemination
   tick rather than one row per execution; multiple legacy `Trade,` lines that
   share a microsecond may collapse into one parquet row whose `tradeVolume`
   is the *aggregate*. Cross-check via `transactionVolume` jumps:
   ```python
   df["delta"] = df.groupby("symbol")["transactionVolume"].diff().fillna(df["transactionVolume"])
   assert (df.loc[df["tradeVolume"]>0, "delta"] == df.loc[df["tradeVolume"]>0, "tradeVolume"]).all()
   ```
   If this passes, no legacy executions are lost — they're just batched.
2. **Pre-open auction trades:** the legacy parser keeps the 9:00 opening match;
   the parquet may flag it differently. Cross-check by comparing the first 30
   seconds of trading per symbol.

**Action:** run the parity script in §8 phase 1 over a full day before any
production cutover. If it confirms hypothesis 1, the migration is correct
modulo a small change to `IndexCalc.calc()` to handle batched matches (it
already accumulates `price * qty`, so this should be a no-op).

---

## 4. Performance — measured benchmarks

All measurements on 2026-03-26 data, M-series Mac, warm filesystem cache. Replay
universe assumed to be ~600 symbols (typical `tickFilter` size from
`build_replay_universe`).

### 4.1 Single-day load (TWSE / TSE only)

| Operation | Implementation | Wall time | Speedup |
|---|---|---|---|
| Count `Trade,` lines (text scan, no parse) | `iter_history_trades` precursor | 4.17 s | 1× |
| **`iter_history_trades` full lightweight parse** (status_code+vol+price) | current `parse_history_trades.py` | **6.22 s** | 1× |
| **`iterate_market_file` full replay parse** (Trade+Depth → MarketTick) | current `parse_format6_replay_rows.py` | **16.19 s** | 1× |
| `pq.ParquetFile(...).metadata` (just open) | pyarrow | 21 ms | — |
| `pq.read_table(cols=8)` full file | pyarrow | 260 ms | 24× vs lightweight, 62× vs full |
| **`pq.read_table(cols=8, filters=[('tradeVolume','>',0)])`** | pyarrow | **133 ms** | **47× vs lightweight, 122× vs full** |
| Same + `('symbol','in',universe)` (~600 syms) | pyarrow | 129 ms | similar (predicate pushdown is cheap) |
| Same, history-style (4 cols only) | pyarrow | **86 ms** | **72× vs lightweight** |

### 4.2 20-day history window load (used by `load_history_window`)

The replay session loads up to **20 prior days** of history per market on every
run (`DAY_PER_MONTH = 20` in `load_history_window.py`). Mitigated today by a
JSON `volcache/` cache, but cold-build cost matters for fresh dates.

| Phase | Current (text + cache) | Parquet (no cache) | Notes |
|---|---|---|---|
| Cold first run (build cache) | ~6.2 s × 20 days × 2 markets ≈ **248 s** | **86 ms × 20 × 2 ≈ 3.4 s** | ~70× faster cold |
| Warm (cache hit) | ~50–200 ms total (JSON read) | ~3.4 s (no cache needed) | Cache stops being a meaningful win once parquet is in play |
| Disk used by cache | `exec/data/volcache/*.json` | none required | Cache directory can be deleted entirely |

The volume-cache layer in `tw_signal_engine.market_data.build_volume_caches`
becomes **vestigial** under parquet. Recommendation: keep it as a fallback for
the live/Redis path that still has no parquet equivalent, but disable it
automatically when a parquet provider is in use.

### 4.3 Storage footprint (one trading day)

| Source | TSE/TWSE | OTC/TPEX | Total | Ratio |
|---|---|---|---|---|
| Legacy text | 1,975 MB | 476 MB | **2,451 MB** | 1× |
| Parquet (snappy) | 183 MB | 57 MB | **240 MB** | **0.10×** |

At ~250 trading days/year that is 600 GB → 60 GB of raw quote data, which
matters for both local SSDs and any future cloud-archive plan.

---

## 5. Validation — `market-data/symbols/`

### 5.1 Format

- **Encoding:** cp950 (legacy parser already handles this in
  `_open_reference_csv` via `("utf-8-sig", "cp950", "big5hkscs")` fallback chain).
- **Columns (9):** `symbol, name, market, previous_close, limit_up_price,
  limit_down_price, industry, security, error_code` — exactly the
  `ReferenceSymbol` shape.
- **Sample row:** `0050  ,元大台灣50      ,T,76.20,83.80,68.60,00,  ,0`
- **Row count (2026-03-26):** 46,075 (all 9-column-valid) — includes 34,480
  TSE-listed (`market='T'`) and 11,595 OTC-listed (`market='O'`).

### 5.2 Byte-level diff vs `exec/files/`

For all 86 overlapping dates (`Symbols_20251112.csv` through
`Symbols_20260326.csv`):

```
$ for f in market-data/symbols/Symbols_*.csv; do
    cmp -s "$f" "exec/files/$(basename "$f")" || echo "DIFF: $f"
  done
# (no output — all 86 files are byte-identical)
```

**Conclusion:** drop-in replacement. Pointing
`run_daily_replay --files-dir /Users/liyijing/Projects/Trading/market-data/symbols`
will produce identical reference loads for any date in [20251112..20260326].

### 5.3 Cross-check vs tick parquet

For 2026-03-26:

| Set | Count | Subset of `Symbols.csv`? |
|---|---|---|
| TWSE parquet distinct symbols | 1,073 | yes (all 1,073 ⊂ market='T' set) |
| TPEX parquet distinct symbols | 880 | yes (all 880 ⊂ market='O' set) |
| Symbols market='T' not in TWSE parquet | 33,407 | warrants/ETN/inactive — expected |

Tick-data symbol coverage is fully a subset of Symbols-file coverage. No
orphan symbols.

---

## 6. Validation — `market-data/group/`

| File | Bytes | Cols | Rows | Groups | Symbols | Notes |
|---|---|---|---|---|---|---|
| `group-ver20260329.csv` | 50,537 | 3 | 2,085 | 149 | 1,794 | **byte-identical** to `exec/files/group.csv` (md5 `30fd7d99…`) |
| `group-ver20260408.csv` | 52,385 | **23** | **1,181** | **67** | **1,063** | Structurally divergent — see below |
| `exec/files/group.csv` (current) | 50,537 | 3 | 2,085 | 149 | 1,794 | == `group-ver20260329.csv` |
| `exec/files/group_old.csv` (prior) | 51,619 | 3 | 2,125 | 146 | 1,786 | older snapshot |

### 6.1 group-ver20260408.csv: product-validated, blocked on padding bug

A diff of group memberships between `group.csv` (current) and `group-ver20260408.csv`:

```
groups in old not in new:        85
groups in new not in old:         2  ('先進製程', '鈣鈦礦')
common groups:                   64  (49 unchanged, 9 shrunk, 6 grew)
total symbols dropped:          731
total symbols added:               0
```

Examples of **deleted** groups: `GPS`, `保險`, `傳播出版印刷`, `光學鏡頭指標`,
`化學工業`, `太陽能`, `太陽能概念股`, `不織布`, `主力的玩具`, `分離式元件`,
`保健品`, `保全`, `加工絲`, `合成樹酯`, `塑膠製品`, `大宗物資`, `安全監控系統`, …

The file is also written as 23 columns instead of 3 — every line is padded with 20
trailing empty fields, e.g.

```
細產業別,代碼,商品,,,,,,,,,,,,,,,,,,,,
3C通路,2430,燦坤,,,,,,,,,,,,,,,,,,,,
```

**Status (decided 2026-04-08):**

1. **Membership change is intentional.** The smaller group set has been confirmed
   by the strategy owner as the intended new universe — dropping 85 industry
   buckets is a product decision, not data corruption. It will materially shrink
   `tickFilter` and shift `StrongGroup` ranking, and the strategy team is aware.
2. **23-column padding is an upstream bug.** The padded layout is an accidental
   artifact of the upstream CSV writer (likely a fixed-width export template), not
   part of the new schema. The pipeline today parses 3-column `code, group, symbol`
   rows; the padded variant would silently produce 20 empty trailing fields per row
   if loaded. The fix belongs upstream — re-export as a clean 3-column file —
   rather than adding a defensive trim in the engine.
3. **Do NOT promote until the padding bug is fixed.** `group-ver20260408.csv`
   stays under `market-data/group/` as a **quarantined reference**. The default
   continues to be `group-ver20260329.csv` (= current `exec/files/group.csv`).
   Once upstream re-exports a clean 3-column version, promoting the new universe
   becomes a separate follow-up that owns both the upstream cutover and any
   downstream report-baseline shifts; it is **out of scope** for this migration
   design.

### 6.2 Recommended canonical layout

Once accepted, the upstream producer should write a single
`group/group.csv` symlink (or stable filename) that downstream consumers
reference, with versioned snapshots kept under `group/archive/` for
reproducibility:

```
market-data/group/
├── group.csv -> archive/group-ver20260329.csv   # current canonical (3-col, in use)
└── archive/
    ├── group-ver20260329.csv
    └── group-ver20260408.csv                    # quarantined: product-validated,
                                                 # blocked on upstream 23-col padding fix
```

---

## 7. Data hygiene findings

These are the gaps that must be closed (or accepted) before production cutover.

| # | Finding | Severity | Owner | Suggested fix |
|---|---|---|---|---|
| H1a | Historical `Symbols_20260304.csv` is missing | **Medium — backfill committed** | data ops | Fetch from upstream archive; only near-term Symbols action item |
| H1b | 6 most-recent tick days have no matching Symbols file (`20260327, 20260330, 20260331, 20260401, 20260402, 20260407`) | Low — non-blocking, deferred | data ops | Fetch in a future data-ops pass; until then replay of these specific dates is unsupported. Engine should print the missing-date list on startup rather than crash mid-run |
| H2 | `tradePrice`/`buyPrice*`/`sellPrice*` are float — must convert to int×10000 with `round()`, never `int()` (`int(31.55*10000) == 315499`) | High | engine | Centralize in a single `_to_int_price` helper used by every parquet adapter |
| H3 | 11% row delta between legacy `status_code==0` and parquet `tradeVolume>0` (see §3.4) | Medium | engine + data ops | Run parity script over 5 days; document the consolidation rule |
| H4 | `group-ver20260408.csv` is product-validated as the new universe but ships with a 23-column CSV padding bug | Medium — pending upstream fix | data ops + strategy owner | Have upstream re-export as a clean 3-column file; promotion of the new universe is a follow-up out of scope here. Default stays at `group-ver20260329.csv` (see §6) |
| H5 | `volcache/*.json` is fragile (rebuilt on every file mtime change). Once parquet is in place this layer is unnecessary; deleting it removes a class of cache-invalidation bugs | Low | engine | Phase out as part of provider switch |
| H6 | New parquet gives full L5 book + session VWAP + cumulative volume — **none** of which the current pipeline reads. These are a free upgrade once the provider lands | n/a | strategy owner | Track as follow-up signal-engineering opportunities |
| H7 | `market-data/.DS_Store` files exist in every directory | Cosmetic | data ops | Add `.DS_Store` to upstream `.gitignore` / sync filter |

---

## 8. Migration plan

### 8.1 Target layout

```
/Users/liyijing/Projects/Trading/market-data/   # canonical raw data root
├── group/
│   ├── group.csv                  # symlink → archive/<approved version>
│   └── archive/                   # versioned snapshots
├── symbols/
│   └── Symbols_YYYYMMDD.csv       # unchanged
└── tick-data/
    ├── TWSE/YYYYMMDD.parquet
    └── TPEX/YYYYMMDD.parquet
```

`exec/data/` and `exec/files/` become *legacy fallbacks*; the engine reads from
`market-data/` by default and can still be pointed at `exec/` via CLI flags for
A/B parity runs.

### 8.2 Engine changes (additive, no rewrites)

```
src/tw_signal_engine/market_data/
├── parse_format6_replay_rows.py    # keep — fallback path
├── parse_history_trades.py         # keep — fallback path
├── file_replay_provider.py         # keep — fallback path
├── parquet_replay_provider.py      # NEW
├── parquet_history_loader.py       # NEW
└── parquet_io.py                   # NEW (shared helpers: _to_int_price, time conv)
```

The new provider implements `MarketDataProvider.iterate_ticks()` and is wired
into `replay_session.py` behind a CLI flag (`--data-source parquet|text`) that
defaults to `text` until parity is confirmed, then flips to `parquet`.

`parquet_replay_provider.iterate_ticks()` sketch:

```python
def iterate_ticks(self):
    cols = ["symbol", "time", "tradePrice", "tradeVolume",
            "buyPrice1", "sellPrice1", "matchFlag"]
    filters = [("tradeVolume", ">", 0)]
    if self.tick_filter:
        filters.append(("symbol", "in", list(self.tick_filter)))

    twse = pq.read_table(f"{root}/TWSE/{date}.parquet", columns=cols, filters=filters)
    tpex = pq.read_table(f"{root}/TPEX/{date}.parquet", columns=cols, filters=filters)

    # Merge by `time` (already int64 in HMMSSffffff form — no conversion needed)
    merged = pa.concat_tables([
        twse.append_column("market", pa.array(["TSE"] * twse.num_rows)),
        tpex.append_column("market", pa.array(["OTC"] * tpex.num_rows)),
    ]).sort_by("time")

    # Stream rows (avoid materializing 1M MarketTick objects up front)
    for batch in merged.to_batches(max_chunksize=10_000):
        for row in zip(*[batch.column(c).to_pylist() for c in batch.schema.names]):
            yield _row_to_market_tick(row)
```

`parquet_history_loader.load_history_window()` replaces the per-day text scan
with a single column-projected read per (market, date), then folds rows into
the same `LinearVolumeTracker` shape `replay_session` already consumes.
Total cost ~3 s for a 20-day window vs the current 250 s cold build.

### 8.3 Phased rollout

1. **Phase 0 — discovery & parity script** (this report).
2. **Phase 1 — parity harness.** Build a script that runs `iterate_market_file`
   and `parquet_replay_provider.iterate_ticks` on the same date and asserts
   row-count, per-symbol cumulative volume, and final session VWAP match
   within tolerance. Run on 5 representative days. **Gate:** zero deltas in
   cumulative volume / VWAP per symbol.
3. **Phase 2 — opt-in CLI flag.** Add `--data-source parquet` to
   `run_daily_replay` and `run_batch_replay`. Default off. Document in
   `docs/product-specs/current-strategy-spec.md`.
4. **Phase 3 — A/B run** the existing daily report pipeline against text and
   parquet for a week. Compare trade-level outputs row-by-row using
   `compare_runs.py`-style diff (not in repo today; sketch in §8.4).
5. **Phase 4 — flip the default.** `--data-source` defaults to `parquet`,
   text path retained as `--data-source text` fallback.
6. **Phase 5 — retire text path.** Remove `parse_format6_replay_rows.py`,
   `parse_history_trades.py`, `iterate_market_file.py`, `merge_market_streams.py`,
   `build_volume_caches.py`, `volcache/`. Update `AGENTS.md` and the CLAUDE.md
   commands block.
7. **Phase 6 — repoint exec configs.** Change `exec/cfg/parameter.cfg`'s data
   directory expectations and update the example commands in
   `CLAUDE.md` and `README.md` to reference `/Users/liyijing/Projects/Trading/market-data`.

### 8.4 Parity script (phase 1) — minimal sketch

```python
# scripts/compare_text_vs_parquet.py
from collections import defaultdict
from tw_signal_engine.replay.iterate_market_file import iterate_market_file
import pyarrow.parquet as pq

def text_volume_by_symbol(market, date, data_dir):
    out = defaultdict(int)
    for tick in iterate_market_file(market, date, data_dir=data_dir):
        out[tick.symbol] += tick.match.qty
    return out

def parquet_volume_by_symbol(venue, date, root):
    tbl = pq.read_table(f"{root}/{venue}/{date}.parquet",
                        columns=["symbol", "tradeVolume"],
                        filters=[("tradeVolume", ">", 0)])
    df = tbl.to_pandas()
    return df.groupby("symbol")["tradeVolume"].sum().to_dict()

text = text_volume_by_symbol("TSE", "20260326", "exec/data/")
parq = parquet_volume_by_symbol("TWSE", "20260326",
                                "/Users/liyijing/Projects/Trading/market-data/tick-data")

deltas = {s: text.get(s, 0) - parq.get(s, 0)
          for s in set(text) | set(parq) if text.get(s, 0) != parq.get(s, 0)}
print(f"symbols with mismatched cumulative volume: {len(deltas)}")
print(sorted(deltas.items(), key=lambda x: -abs(x[1]))[:10])
```

Acceptance: the only acceptable per-symbol delta is for symbols whose text-side
trades all had `status_code != 0` (rare, auction-only names). Anything else
needs investigation under H3.

---

## 9. Risks & open questions

| # | Risk | Mitigation |
|---|---|---|
| R1 | Float→int rounding differs from upstream's quantization (e.g., `26.05 * 10000 → 260499.99…`) | Use `round()` and unit-test 100 known reference prices against legacy text values |
| R2 | Parquet snapshot consolidation drops legacy `Trade,` rows that share microseconds with another match | Verified equivalent via `transactionVolume` deltas in §3.4 cross-check; gate on parity script |
| R3 | `group-ver20260408.csv` is product-validated but its 23-col padding bug means a naive parser swap would silently load malformed rows. Risk is that upstream keeps producing the padded format while strategy stakeholders expect the new universe to be live | Block promotion on a clean 3-col upstream re-export; keep `group-ver20260329.csv` as default in the meantime; promotion is a separate follow-up |
| R4 | `Symbols_20260304.csv` plus 6 trailing dates (`20260327, 20260330, 20260331, 20260401, 20260402, 20260407`) have no `Symbols_*.csv` — replay will fail on those specific dates | Backfill 20260304 now; defer the 6 trailing dates to a future data-ops pass; add a CLI guard that lists missing dates and skips them rather than crashing mid-batch |
| R5 | `volcache/*.json` invalidation tied to `source_size`/`source_mtime` of the *legacy* text files — these no longer exist after migration | Remove cache code in phase 5; do not let phase 3 leave a half-migrated state |
| R6 | Live (Redis) provider has no parquet equivalent; pipeline must support both text fallback and parquet on the same run | `MarketDataProvider` ABC already abstracts this — phase 4 only flips the *replay* default |
| R7 | Memory: a full-day TWSE parquet (8.5M rows × 36 cols) materializes to ~2 GB pandas if loaded naively | Always pass `columns=` and `filters=` to `read_table`; iterate by `RecordBatch` not by `to_pandas()` for very wide queries |
| R8 | Schema drift — upstream may add/rename columns silently | Pin a schema check at provider boot: assert the 7 columns we read are present and of expected types |

---

## 10. Recommended next steps (in order)

1. **Backfill `Symbols_20260304.csv`** (H1a) — single-file data-ops ticket from the
   upstream archive. The 6 trailing dates in H1b are explicitly deferred and stay
   on the data-ops backlog.
2. **Track upstream re-export of `group-ver20260408.csv`** as a clean 3-column file
   (H4, §6). Product validity is already confirmed; the only remaining work is the
   padding-bug fix. Promoting the new universe to default is a separate follow-up
   and is out of scope here — `group-ver20260329.csv` remains the default.
3. **Land the parity script** (`scripts/compare_text_vs_parquet.py`) and run
   it over 5 days. Block on H3 resolution.
4. **Implement `parquet_io.py`, `parquet_history_loader.py`,
   `parquet_replay_provider.py`** (phase 2). No changes to
   `replay_session`, signals, or reporting.
5. **Document the new layout** in `docs/references/runtime-conventions.md` and
   point `exec/cfg/parameter.cfg` at the new root.
6. **Schedule cutover** (phase 4) once parity has held for ≥5 consecutive days.
7. **Tracking issue:** create a follow-up note under
   `docs/exec-plans/tech-debt-tracker.md` for the L5-book / session-VWAP
   signal opportunities (H6) — these are the strategic upside, separate
   from the migration itself.

---

## Appendix A — commands used for this report

```bash
# Schema and stats
uv run python -c "
import pyarrow.parquet as pq
pf = pq.ParquetFile('/Users/liyijing/Projects/Trading/market-data/tick-data/TWSE/20260326.parquet')
print(pf.schema_arrow); print(pf.metadata.num_rows, pf.num_row_groups)
"

# Byte-level Symbols diff
for f in /Users/liyijing/Projects/Trading/market-data/symbols/*.csv; do
  cmp -s "$f" "/Users/liyijing/Projects/Trading/VWAP-intraday-signal/signal/exec/files/$(basename $f)" \
    || echo "DIFF: $f"
done

# Group structural diff
md5 /Users/liyijing/Projects/Trading/market-data/group/*.csv \
    /Users/liyijing/Projects/Trading/VWAP-intraday-signal/signal/exec/files/group*.csv

# Hot-path benchmark (parquet vs text)
uv run python -c "
import time, pyarrow.parquet as pq
from tw_signal_engine.market_data.parse_history_trades import iter_history_trades
t = time.time(); n = sum(1 for _ in iter_history_trades(
    '/Users/liyijing/Projects/Trading/VWAP-intraday-signal/signal/exec/data/TSEQuote.20260326'))
print(f'text: {time.time()-t:.2f}s, n={n}')
t = time.time(); tbl = pq.read_table(
    '/Users/liyijing/Projects/Trading/market-data/tick-data/TWSE/20260326.parquet',
    columns=['symbol','time','tradePrice','tradeVolume'],
    filters=[('tradeVolume','>',0)])
print(f'parquet: {(time.time()-t)*1000:.0f}ms, n={tbl.num_rows}')
"
```

# Active Plans

- [Merge `strategy-vwap-touch` into Data-Migration Parquet Replay](./merge-strategy-vwap-touch-into-data-migration.md) — integrate strategy behavior with parquet replay without dropping either branch's runtime contract.
- [Reduce `readFileMerged` Runtime With Three Low-Risk Wins](./readfilemerged-low-risk-wins.md) — reduce replay hot-path latency by narrowing universe symbols, removing duplicate group-average recomputation, and gating unnecessary volume-history queries.

When a new implementation starts, add a plan file here and move it to
`docs/exec-plans/completed/` once the work is shipped.

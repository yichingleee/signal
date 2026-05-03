# Active Plans

- [Merge `strategy-vwap-touch` into Data-Migration Parquet Replay](./merge-strategy-vwap-touch-into-data-migration.md) — integrate strategy behavior with parquet replay without dropping either branch's runtime contract.
- [Reduce `readFileMerged` Runtime With Three Low-Risk Wins](./readfilemerged-low-risk-wins.md) — reduce replay hot-path latency by narrowing universe symbols, removing duplicate group-average recomputation, and gating unnecessary volume-history queries.
- [Make Strong-Group Average Change Incremental](./strong-group-incremental-average.md) — replace repeated full-group percentage rescans with cached incremental updates while preserving replay parity.
- [Dashboard Monitoring Parity](./dashboard-monitoring-parity-plan.md) — add source-dashboard monitoring modules to the React dashboard while exposing only real `signal` engine data.
- [Align SignalDayHigh Engine State With Dashboard Display](./signal-day-high-dashboard-display-plan.md) — expose the true DayHigh phase progression and preserved trigger context so the dashboard summary, table, and route all describe the same engine state.
- [Make the Dashboard Replicate Full DayHigh Trading Logic](./dashboard-dayhigh-trading-logic-parity-plan.md) — extend DayHigh snapshots and UI so operators can see stock selection, entry gating, exit policy, and exit causes directly from engine-produced dashboard data.
- [DayHigh v2 Port — 3-Day Parity Report](./port-dayhigh-v2-to-data-migration-parity.md) — compare the data-migration v2 port against the dayhigh reference run and capture parity gaps.

When a new implementation starts, add a plan file here and move it to
`docs/exec-plans/completed/` once the work is shipped.

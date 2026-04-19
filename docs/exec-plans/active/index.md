# Active Plans

- [Redis Live Mode Smoke-Test Remediation Plan](./redis-live-smoke-remediation-plan.md)
- [Market-Data Parquet Migration](./market-data-parquet-migration.md) — keep parquet as the replay default, preserve text as a compatibility source, and validate each source against its own contract.
- [Build and Use a Precomputed 0050 Sidecar](./0050-sidecar-precompute-service.md) — precompute tiny 0050 proxy files from `TSEQuote` so parquet replay does not scan multi-gigabyte text files on the hot path.

Obsolete records retained for context:

- [Parquet Text-Ground-Truth Parity Filter](./parquet-text-ground-truth-parity-filter.md) — superseded by the source-separated truth policy; do not implement as active work.

Move plans to `docs/exec-plans/completed/` once the work is shipped.

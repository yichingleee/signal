# Obsolete: Text-Ground-Truth Parity Filter

Status: obsolete as of 2026-04-20.

This plan is intentionally not active. It was created on 2026-04-08 to force parquet ingestion to normalize history and replay quantities to the legacy text parser's behavior. The repository direction has changed: `text` and `parquet` are separate replay data sources, and strict cross-source output equality is not a parquet acceptance gate.

The superseding policy is recorded in [docs/references/parquet-vs-text-data-source-findings.md](../../references/parquet-vs-text-data-source-findings.md):

- each data source must satisfy its own schema, ordering, market-mapping, time-conversion, price-scaling, and volume contracts;
- parquet replay correctness is evaluated against the parquet source contract, not against byte-for-byte text output;
- cross-source comparison remains diagnostic and should classify differences as expected source differences or potential regressions.

Do not implement the previously proposed text quantity index, parquet normalization layer, parity-mode CLI flag, or fail-closed text-reference dependency. Those changes would reintroduce the old text-ground-truth policy.

Historical root-cause evidence from this plan remains useful when diagnosing source differences:

- parquet `tradeVolume` can align with cumulative-volume deltas where the text parser's row `QTY` field differs;
- same-symbol history quantities can drift between feeds and affect `MonthTradingVal` / `VolRatio`;
- replay stream shape can differ even when per-symbol traded volume is close.

Use `scripts/compare_text_vs_parquet.py` only as a diagnostic audit tool under the new policy.

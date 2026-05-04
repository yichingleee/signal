# Design Docs

These documents explain how the current Python replay engine is organized and why the repository is laid out the way it is.

- [docs/design-docs/runtime-architecture.md](runtime-architecture.md): end-to-end replay flow and module responsibilities
- [docs/design-docs/parquet-tick-data-integration-report.md](parquet-tick-data-integration-report.md): ingest/cache/file-I/O flow map and optimization roadmap (including pyarrow options)
- [docs/design-docs/python-module-namespaces.md](python-module-namespaces.md): namespace review, doc move plan, and future split candidates
- [docs/design-docs/replay-runtime-optimization-research.md](replay-runtime-optimization-research.md): runtime bottlenecks, optimization priorities, and benchmark design for replay work
- [docs/design-docs/replay-runtime-optimization-verification.md](replay-runtime-optimization-verification.md): post-optimization benchmarks, correctness validation, and remaining bottleneck analysis
- [docs/design-docs/dayhigh-strategy-implementation-research.md](dayhigh-strategy-implementation-research.md): compatibility research and implementation plan for the Day High Breakout strategy
- [docs/design-docs/live-data-architecture.md](live-data-architecture.md): provider abstraction, Redis live, paced replay, backfill, session hooks
- [docs/design-docs/dashboard-architecture.md](dashboard-architecture.md): as-built dashboard structure, transport flow, route map, replay UX, and backend/frontend boundaries
- [docs/references/legacy/research/live-data-integration-research.md](../references/legacy/research/live-data-integration-research.md): archived pre-implementation research notes

Cross-links:

- Current committed behavior: [docs/product-specs/current-strategy-spec.md](../product-specs/current-strategy-spec.md)
- Runtime conventions: [docs/references/runtime-conventions.md](../references/runtime-conventions.md)
- Dashboard operations: [docs/references/dashboard-operations.md](../references/dashboard-operations.md)
- Technical debt: [docs/exec-plans/tech-debt-tracker.md](../exec-plans/tech-debt-tracker.md)

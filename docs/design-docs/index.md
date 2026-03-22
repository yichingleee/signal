# Design Docs

These documents explain how the current Python replay engine is organized and why the repository is laid out the way it is.

- [docs/design-docs/runtime-architecture.md](runtime-architecture.md): end-to-end replay flow and module responsibilities
- [docs/design-docs/python-module-namespaces.md](python-module-namespaces.md): namespace review, doc move plan, and future split candidates
- [docs/design-docs/replay-runtime-optimization-research.md](replay-runtime-optimization-research.md): runtime bottlenecks, optimization priorities, and benchmark design for replay work
- [docs/design-docs/replay-runtime-optimization-verification.md](replay-runtime-optimization-verification.md): post-optimization benchmarks, correctness validation, and remaining bottleneck analysis

Cross-links:

- Current committed behavior: [docs/product-specs/current-strategy-spec.md](../product-specs/current-strategy-spec.md)
- Runtime conventions: [docs/references/runtime-conventions.md](../references/runtime-conventions.md)
- Technical debt: [docs/exec-plans/tech-debt-tracker.md](../exec-plans/tech-debt-tracker.md)

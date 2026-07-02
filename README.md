# backstitch

Backstitch style spec-code traceability checks and semantic review tooling.

`backstitch` is a standalone developer tool. It owns the backstitch style v1
traceability grammar, deterministic trace graph construction, and semantic
analysis result schemas. This repository's own specs are a primary acceptance
corpus. Weft is an external target corpus and eventual consumer, not a package
dependency.

Current implementation status: the deterministic checker (`backstitch check`),
review-packet generation (`backstitch packets`), `llm` semantic analysis
(`backstitch analyze`, `backstitch summarize-analysis`), and TOML
configuration (`backstitch config show|path`) are implemented per
`docs/specs/02-backstitch-core.md`, `03-backstitch-configuration.md`, and
`04-backstitch-traceability-exclusions.md`. The invariant traceability spec
(`05-backstitch-invariants.md`) is Proposed and not implemented. This
repository dogfoods itself: `uv run backstitch check` must pass with zero
errors and zero warnings.

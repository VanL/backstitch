# backstitch

Backstitch style spec-code traceability checks and semantic review tooling.

`backstitch` is a standalone developer tool. It owns the backstitch style v1
traceability grammar, deterministic trace graph construction, and semantic
analysis result schemas. This repository's own specs are a primary acceptance
corpus. Weft is an external target corpus and eventual consumer, not a package
dependency.

Current implementation status: package bootstrap and implementation plan are in
place. The deterministic checker and `llm` semantic analysis are planned in
`docs/plans/2026-06-18-backstitch-style-spec-code-traceability-tool-plan.md`.

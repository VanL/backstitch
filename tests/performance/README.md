# Semantic scale qualification

This directory owns the deterministic [EVC-10] scale-fixture generator and the
pinned-runner availability check. The generated tree is exact: 1,000
obligations, 5,000 Python modules, 20,000 discovery candidates, and 50 MiB of
captured Python source.

Performance qualification is currently **unavailable**, not failed. There is
intentionally no `runner-contract.json` and no `semantic-scale` CI job. The
worktree has no observed, reviewed identity for the required Linux runner. The
existing CI jobs also do not capture every contract field: runner image OS and
version, CPU model and logical count, memory bytes, Python version, uv version,
and the lock digest. Filling those fields from this arm64 macOS development
machine, examples, or assumptions about a hosted runner would fabricate the
comparison baseline.

`assess_runner_qualification` returns `runner_contract_missing` in this state.
It also returns unavailable for an invalid contract, an unobserved runtime, or
any exact identity mismatch. A caller must obtain `runtime_identity_match`
before measuring latency or RSS or applying the [EVC-10] ceilings. This status
does not change a semantic report or its policy authority.

To qualify later, first select and review a stable Linux runner. Capture every
required field and the baseline measurements in that same environment. Then
commit `runner-contract.json` and add the `semantic-scale` job together. The
job must recompute the live identity and refuse to measure when any field
differs.

Governing sources:

- `docs/specs/07-verification-and-evidence-cases.md` [EVC-10]
- `docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md` Slice 8.6

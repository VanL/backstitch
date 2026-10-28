# Dependency refresh

Status: active. Class 4: widening the published llm compatibility range crosses a public compatibility boundary. User requested dependency updates and restoring Dependabot's uv operation.

## Sources and context

Consulted program theory, agent context README, decision hierarchy, principles, engineering principles, lessons, hardening and review runbooks, DOM-5/10/11/15, and the user request. `pyproject.toml` owns package constraints; `uv.lock` fixes resolved versions; `.github/workflows/` pins action commits. CI pins uv 0.12.5 independently of the local allowed range.

## Outcome and invariants

Update the named dependencies to current stable versions, allow uv 0.13, and preserve `hatchling.build`, the existing CLI, release behavior, and CI's pinned uv version. The lock and allowed ranges must agree. Action SHAs must resolve to their indicated release tags. Do not change product logic or publish a release.

## Work and verification

1. Resolve release versions and immutable action SHAs. Stop if an upstream tag cannot be verified.
2. Update constraints and lock with real uv, not mocks. Build the sdist and wheel using the actual backend. Stop on incompatibility.
3. Run hermetic tests, lint, format, types, uv policy/lock checks, and the self-corpus gate; use CI for supported platform matrix. Review the diff independently. Record failures honestly.
4. Push a PR and land only after checks pass. Check Dependabot resumes after merge. Rollback is a revert of the dependency commit; no storage migration or one-way door is introduced. Live provider behavior and a production release are outside local verification; observe CI and subsequent Dependabot runs after landing.

## Review and deviations

Implementation was started before writing this plan and before the required risky-plan review; this sequencing deviation cannot be undone. Independent review and all checks remain required before landing. No test or provider boundary should be mocked to manufacture compatibility evidence. Coverage timeout in #24 remains an unproven flake until a fresh run passes.

2026-10-28 verification: uv 0.13.5 resolved the lock and policy check passed; real `python -m build` produced sdist and wheel with hatchling 1.33.0; Ruff check and format, mypy (167 files), doc-path and DOM-15 gates, and `backstitch check --repo-root .` (0 errors, 0 warnings, 0 infos) passed. Full hermetic suite and GitHub CI remain pending. Tier-1 review attempts: Grok refused to start because its read-only sandbox could not be applied (runtime socket symlink); Claude timed out at 120 seconds. Tier-2 same-family review found no P1/P2 findings, conditional on CI and plan closure; it verified action tag SHAs, uv 0.12.5 lock compatibility and 20 llm adapter tests. This is not cross-family review. No findings to disposition. The call-agent skill's sandbox setup needs repair; Claude containment remains unverified per inventory.

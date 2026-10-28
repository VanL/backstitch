# Dependency refresh

Status: active. Class 4: widening the published llm compatibility range crosses a public compatibility boundary. User requested dependency updates and restoring Dependabot's uv operation.

## Sources and context

Consulted program theory, agent context README, decision hierarchy, principles, engineering principles, lessons, hardening and review runbooks, DOM-5/10/11/15, and the user request. `pyproject.toml` owns package constraints; `uv.lock` fixes resolved versions; `.github/workflows/` pins action commits. CI pins uv 0.13.6 independently of the local allowed range.

## Outcome and invariants

Update the named dependencies to current stable versions, allow uv 0.13 and use its latest patch in CI, and preserve `hatchling.build`, the existing CLI, release behavior, and a single explicit CI uv version. The lock and allowed ranges must agree. Action SHAs must resolve to their indicated release tags. Do not change product logic or publish a release.

## Work and verification

1. Resolve release versions and immutable action SHAs. Stop if an upstream tag cannot be verified.
2. Update constraints and lock with real uv, not mocks. Build the sdist and wheel using the actual backend. Stop on incompatibility.
3. Run hermetic tests, lint, format, types, uv policy/lock checks, and the self-corpus gate; use CI for supported platform matrix. Review the diff independently. Record failures honestly.
4. Push a PR and land only after checks pass. Check Dependabot resumes after merge. Rollback is a revert of the dependency commit; no storage migration or one-way door is introduced. Live provider behavior and a production release are outside local verification; observe CI and subsequent Dependabot runs after landing.

## Review and deviations

Implementation was started before writing this plan and before the required risky-plan review; this sequencing deviation cannot be undone. Independent review and all checks remain required before landing. No test or provider boundary should be mocked to manufacture compatibility evidence. Coverage timeout in #24 remains an unproven flake until a fresh run passes.

2026-10-28 verification: uv 0.13.5 resolved the lock and policy check passed; real `python -m build` produced sdist and wheel with hatchling 1.33.0; Ruff check and format, mypy (167 files), doc-path and DOM-15 gates, and `backstitch check --repo-root .` (0 errors, 0 warnings, 0 infos) passed. The local hermetic suite reached 99% without a reported failure but was interrupted while still running (exit 130); it is not a pass. GitHub CI remains pending. Tier-1 review attempts: Grok refused to start because its read-only sandbox could not be applied (runtime socket symlink); Claude timed out at 120 seconds. Tier-2 same-family review found no P1/P2 findings, conditional on CI and plan closure; it verified action tag SHAs, uv 0.12.5 lock compatibility and 20 llm adapter tests. This is not cross-family review. No findings to disposition. The call-agent skill's sandbox setup needs repair; Claude containment remains unverified per inventory.

2026-10-28 follow-up: user requested the newest supported versions. CI now uses uv 0.13.6, while the accepted range remains >=0.12.5,<0.14 so Dependabot running 0.13.5 is not excluded. All direct Python dependencies and workflow actions were checked against current stable releases; the lock was upgraded within declared constraints. The expanded lock and uv bump require renewed verification and review before landing.

Follow-up verification: uv 0.13.6 policy and lock checks, real sdist/wheel build, Ruff lint and format, mypy, documentation gates, and self-corpus (0 errors, 0 warnings, 0 infos) passed. uv 0.13.5 also passes lock and policy checks. The 20 llm adapter tests passed with refreshed dependencies. Same-family follow-up review found one stale uv version in this plan, corrected here; no other actionable findings. The refreshed hermetic suite passed on macOS/Python 3.14 with four workers (exit 0); hosted CI remains pending.

Follow-up: owner requested removing dependency ceilings. Drop the llm and uv upper bounds, update the uv policy script to require a minimum-only constraint, retain the tested CI pin and lockfile, and verify the updater rejects a CI version below the minimum. A future major may be incompatible before CI detects it; release and Dependabot verification remain required.

Ceiling-removal verification: the minimum-only updater test failed before the change because the old parser required an upper bound; all eight updater tests pass afterward, including rejection of a CI pin below the minimum and a ceiling-bearing input. Full hermetic and acceptance suites passed on macOS/Python 3.14 with four workers. Ruff, format, mypy, documentation gates, uv policy and lock checks, and the self-corpus (0 errors, 0 warnings, 0 infos) passed. A Tier-2 same-family review found no P1/P2 findings; the earlier Tier-1 failures are recorded above. Hosted CI and future dependency versions remain unverified. The test-audit skill's owner-boundary and regression requirements fit this change; no skill amendment needed.

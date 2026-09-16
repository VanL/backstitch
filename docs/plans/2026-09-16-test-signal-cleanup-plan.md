# Test Signal Cleanup Plan

Status: Completed
Class: 3 — cross-cutting test-contract cleanup with one product-spec clarification
Plan type: implementation with spec revision

## Goal

Remove tests and assertions that freeze incidental repository process, duplicate
mutable configuration, or pass tautologically. Preserve only independently
valuable behavior, security, transaction, artifact-integrity, and compatibility
proofs, rewriting those proofs against public behavior or one canonical source.

## Source Documents

- `docs/program-theory.md` [THEORY-1], [THEORY-2], [THEORY-6 A5]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-10], [DOM-15]
- `docs/specs/02-backstitch-core.md` [SC-10], [SC-17.1]
- `docs/specs/03-backstitch-configuration.md` [CFG-9]
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-10], [EVC-10.1], [EVC-12.2]
- `docs/agent-context/runbooks/testing-patterns.md`
- TDD skill, especially public-behavior and anti-tautology rules

## Spec Baseline

- `7bdcfd780eadeec7b424c15434dcd8b39a694301` — all cited specs at plan start.
- Promotion baseline: `7bdcfd7` plus the worktree diff to
  `docs/specs/02-backstitch-core.md` implementing the [SC-10]/[SC-17.1]
  clarification recorded below.

## Context and Key Files

- `tests/test_release_workflow.py`, `tests/test_release_script.py`: CI and release
  policy tests currently mix security invariants with exact YAML and argv text.
- `tests/test_bump_uv.py`: valuable atomicity, nonmutation, and rollback proofs;
  mutable version literals and managed-file knowledge must not become a second
  authority.
- `tests/test_backstitch_corpus_traceability.py`, `tests/test_ruff_policy.py`:
  governance tests include exact cardinalities that reject valid additions.
- `tests/test_issue_code_coverage.py`, `tests/test_semantic_eval_identity.py`:
  isolated assertions restate their own inputs.
- `tests/test_semantic_eval_corpus_v3.py`, `tests/test_semantic_settings.py`,
  `tests/test_semantic_scale.py`: minimums and behavior are mixed with current
  corpus totals, duplicated tuning values, and temporary feature absence.
- `tests/test_canonical_owners.py`: some private-helper characterization tests
  over-couple internal decomposition; retain only public-loader behavior and
  explicit ownership constraints.
- `docs/specs/02-backstitch-core.md`: currently requires a manifest/lock/runtime
  Ruff consistency proof. The proof is valuable, but no test may embed a second
  Ruff version literal.

## Invariants and Constraints

- Frozen semantic gold remains independent of product output; do not weaken A5.
- Every enumerable product issue/config contract touched retains a firing or
  observable-behavior proof.
- Security boundaries for hostile PRs, release artifacts, credentials, action
  pinning, and immutable provenance remain tested.
- `bump_uv` dry-run/check nonmutation, all-file atomic update, validation-before-
  write, and rollback on failure remain tested through filesystem state.
- Ruff manifest, lock, and executing binary remain consistent, but the expected
  version is read once from the manifest rather than copied into a test.
- Do not replace brittle tests with mocks of the behavior being proved.
- No production behavior, CLI, report schema, or policy consequence changes.

## Proposed Spec Delta

Promotion strategy: A — in-file active clarification before final verification.

### `docs/specs/02-backstitch-core.md` [SC-10]

Replace “configured Ruff policy tests proving the exact manifest/lock/runtime
pin” with:

> configured Ruff policy tests proving that the single exact manifest pin,
> lock resolution, and executing binary agree, without duplicating the pinned
> version as test-owned policy,

### `docs/specs/02-backstitch-core.md` [SC-17.1]

Replace the first paragraph with:

> Ruff's version is exact-pinned in the development manifest and lock. The
> repository proves that the executing binary and lock resolve to the manifest's
> single exact pin before deriving rule or suppression inventories; tests do not
> carry a second version literal.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Tasks

1. Promote the SC-10/SC-17.1 clarification and record the worktree promotion
   baseline against `7bdcfd7`.
2. Delete dedicated process/cardinality/absence tests with no independent
   correctness value, and remove tautological assertions.
3. Rewrite mixed-value tests so security and behavioral invariants survive while
   exact mutable versions, totals, YAML indentation, step names, and copied
   configuration disappear.
4. Retain `bump_uv` transaction tests, deriving mutable inputs and managed scope
   from one authority where practical; prove mutation and rollback by file bytes.
5. Run focused suites after each coherent group, then full hermetic tests, Ruff,
   mypy, suppression policy, acceptance probes, and the self-corpus gate.
6. Run an independent review; resolve findings; close this plan and its index row.

## Testing Plan

- Use existing tests as the initial red evidence where dependency updates broke
  behavior-neutral assertions.
- For retained proofs, perturb the relevant public input or filesystem boundary
  and assert an observable output/state difference.
- Mutation spot-check: confirm each retained test fails when its protected
  invariant is locally inverted, without committing the mutation.

## Verification and Gates

- `uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm and not benchmark"`
- `uv run pytest tests -q -n 0 -m benchmark`
- `uv run --frozen --no-sync ruff check . bin/check-doc-paths bin/check-dom15-fixtures bin/coalesce-check`
- `uv run --frozen --no-sync ruff format --check backstitch bin .github/scripts tests`
- `uv run mypy backstitch bin/release.py tests --config-file pyproject.toml`
- `uv run --frozen --no-sync python bin/ruff_suppression_index.py --check`
- `uv run backstitch check --repo-root .` must report zero errors and warnings.
- Run `tests/acceptance/` and record the result.

## Independent Review Loop

An independent agent reviews the final diff for lost behavioral/security proof,
remaining duplicated mutable policy, tautologies, and spec/test mismatch. All
findings are applied or explicitly dispositioned before closure.

## Out of Scope

- Production behavior changes.
- Regenerating semantic gold from product output.
- Replacing intentional external artifact/version identities with loose checks.
- General test style cleanup unrelated to signal or brittleness.

## Fresh-Eyes Review

Before closure, verify that each deleted assertion answers “what regression can
now pass?” If the answer names a product, security, transactional, or artifact
integrity regression, restore a non-brittle behavioral proof. If the answer is
only “the repository's current spelling/count/version changed,” keep it deleted.

## Investigation Disposition Matrix

| Finding | Disposition | Owning slice |
|---------|-------------|--------------|
| Dependency and action versions copied into tests | Removed; Ruff consistency retained against the manifest authority | core + workflow |
| Exact suppression/configuration cardinalities | Removed; validity, auditability, and scope checks retained | core |
| Constructor-input and expected-literal tautologies | Removed | core + semantic |
| Exact semantic corpus totals above the spec floor | Replaced with manifest relationships and `>= 20` | semantic |
| Full dogfood tuning snapshot | Replaced with observable resolved-config deltas | semantic |
| Test requiring semantic-scale to remain absent | Removed; absent/present/mismatch behavior tests retained | semantic |
| Copied CI/release command inventories | Removed; canonical Ruff gate membership derives from `bin/release.py` | workflow |
| Copied managed-workflow inventory | Removed; tests derive scope from `bin/bump_uv.py` | workflow |
| Private D5 validator characterization | Removed; public behavior and ownership gates retained | core |
| POSIX package support classifier | Retained as external published-metadata correctness | workflow |

## Review Log

- Independent completed-work review initially found F1–F5: lost canonical
  Ruff-gate execution proof, incomplete uv workflow proof, repeated action SHAs,
  residual dogfood tuning duplication, and lost POSIX metadata proof.
- F3–F5 passed after action checks were reduced to repository identity, raw
  dogfood literals were removed, and the POSIX classifier contract was restored.
- F1 passed after CI and release prechecks were checked against the canonical
  command tuples in `bin/release.py` using active workflow text.
- F2 required two rounds: discovery by current `setup-uv` use was mutation-blind;
  the final proof derives the managed workflow set from `bin/bump_uv.py` and
  requires active setup, declaration, and input wiring in every owned workflow.
- Final independent verdict: PASS.

## Verification Evidence

- Slice suites: workflow/release 126 passed; semantic 303 passed; core focused
  suite passed; final reviewer-fix suite passed.
- Full hermetic suite completed successfully after the cleanup.
- Acceptance suite completed successfully.
- Serial benchmark suite: 2 passed; qualification remains unavailable because
  the runner contract is absent, matching the existing behavioral contract.
- Ruff lint and format checks passed; mypy passed for 166 source files.
- Documentation gates and suppression-index check passed.
- Self-corpus gate reported 0 errors, 0 warnings, and 0 infos.

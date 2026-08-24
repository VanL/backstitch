# Release Supply-Chain and Publication Hardening Plan

Status: completed
Class: 4+P — the work changes the release helper CLI and credential-bearing
publication boundary, and materially changes the gates used to verify future
workflow changes.
Plan type: implementation without product-spec revision

## Goal

Bring Backstitch's single-package release process up to the current
SimpleBroker safety model: immutable GitHub Action references, a repository-wide
action inventory gate, maintained action and uv pins, a locked build frontend,
draft-first GitHub Release staging around the irreversible PyPI publish, and a
fail-closed release preflight over the GitHub repository settings that enforce
those policies.

## Source Documents

Source specs and guidance:

- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11], [DOM-15]
- `docs/specs/02-backstitch-core.md` [SC-10], [SC-17.1]
- `docs/agent-context/runbooks/hardening-plans.md` §15
- `docs/lessons.md` "Pin actions before a workflow receives a secret"
- `docs/program-theory.md` [THEORY-1], [THEORY-6] A1

Operational implementation sources:

- `docs/implementation/05-release-publishing.md`
- `docs/plans/2026-07-03-backstitch-release-publishing-plan.md`
- `../simplebroker/.github/workflows/release-gate.yml`
- `../simplebroker/.github/scripts/release_publication.py`
- `../simplebroker/bin/release.py`
- `../simplebroker/bin/bump_uv.py`
- `../simplebroker/tests/test_release_workflow.py`
- `../simplebroker/tests/test_release_publication_script.py`
- `../simplebroker/tests/test_release_script.py`

The required repository read order was consulted before authoring this plan:
program theory; the agent-context README, decision hierarchy, principles, and
engineering principles; the writing-plans, hardening, review-loop, testing, and
adversarial-acceptance runbooks; agent-context lessons; and the project lessons
ledger.

Source spec for GitHub release publishing and Actions policy: none. These are
repository operations, not Backstitch product behavior. The user's explicit
request to match SimpleBroker's release process is the intent source.

## Spec Baseline

- `6adf7aa651ed8b4b8cd9acbc0f40d5472f0e1afe` — current Backstitch specs at
  plan authoring time.

## Proposed Spec Delta

No product CLI, issue-code, configuration, or traceability contract changes.
The release helper gains an operator-only repository-settings check; the
operational contract remains owned by the implementation note.

One governed registry delta is required: retire `RUFF-SUP-142` from [SC-17.1]
because removing remote retagging reduces `plan_tag_action` below the Ruff
complexity ceiling. Regenerate the derived suppression index and prove zero
policy mismatch. This narrows an exception and does not change a product
contract.

Promotion strategy: direct registry retirement with the same-change generated
index refresh and suppression-policy gate.

## Context and Key Files

Current ownership:

- `.github/workflows/release-gate.yml` waits for `CI` and `local-llm`, verifies
  tag identity, builds with `uv build`, attests, publishes to PyPI, and only
  then creates a GitHub Release. Three checkout references and one setup-uv
  reference are mutable.
- Other workflows still contain floating checkout, setup-uv, and cache
  references. A repository-level full-SHA requirement therefore needs a
  repository-wide migration, not a release-file-only edit.
- `tests/test_release_workflow.py` currently requires the floating setup-uv
  form in CI, local-LLM, and release tests. It is the existing structural test
  owner for trusted workflow policy.
- `bin/release.py` owns authenticated GitHub reads, release preparation,
  branch-first retag safety, and tag pushes. Real releases may skip expensive
  test checks, but there is no repository-settings preflight today.
- `docs/implementation/05-release-publishing.md` is the operational owner
  because no product spec governs publication.
- Backstitch has no `.github/dependabot.yml`, locked release dependency group,
  uv version policy helper, or draft-publication state-machine helper.

Expected files to add:

- `.github/dependabot.yml`
- `.github/scripts/release_publication.py`
- `bin/bump_uv.py`
- `tests/test_release_publication_script.py`
- `tests/test_bump_uv.py`

Expected files to modify:

- `.github/workflows/*.yml`
- `bin/release.py`
- `pyproject.toml`
- `uv.lock`
- `tests/test_release_workflow.py`
- `tests/test_release_script.py`
- `docs/implementation/05-release-publishing.md`
- `docs/implementation/02-repository-map.md`
- `docs/plans/README.md`
- this plan

### Comprehension Questions

1. Which action references must the source gate inspect?
   - Expected answer: every non-local `uses:` reference in both `*.yml` and
     `*.yaml` under `.github/workflows`, not only release-gate actions.
2. Which operation is the publication one-way door?
   - Expected answer: PyPI acceptance. A complete draft GitHub Release must be
     staged first; after PyPI succeeds, the exact draft is verified and made
     immutable/public.
3. Which release check remains mandatory when `--skip-checks` is used?
   - Expected answer: authenticated repository-settings verification. The flag
     skips local test/lint/type checks only.
4. What may tests mock?
   - Expected answer: external GitHub/PyPI HTTP responses and subprocess
     execution. They must keep the real workflow files, release-state
     validation, asset validation, version parsing, and command ordering.

Incorrect or unrecorded answers block implementation until the cited owner
surfaces are reread.

## Invariants and Constraints

- Keep Backstitch single-package only, with `vX.Y.Z` tags and the existing
  `CI` plus `local-llm` exact-SHA prerequisites.
- The local helper never publishes directly. It verifies policy, prepares the
  release commit, pushes `origin main`, waits for exact-identifier `CI` and
  `local-llm`, verifies that the release SHA remains reachable from
  `origin/main`, and only then creates or pushes the release tag.
- All external workflow actions use full 40-character commit SHAs with
  human-readable version comments where practical. Local actions remain local.
- GitHub's live Actions policy must require full SHA pins, allow GitHub-owned
  actions, reject blanket verified publishers, and allow exactly the third-party
  repositories present in source.
- The exact live repository-policy constants are:
  - `ACTIONS_ALLOWED_PATTERNS`: `astral-sh/setup-uv@*`,
    `codecov/codecov-action@*`, `pypa/gh-action-pypi-publish@*`, and
    `softprops/action-gh-release@*`
  - `PYPI_ENVIRONMENT_TAG_PATTERNS`: `("tag", "v*")`
  - `RELEASE_TAG_PATTERNS`: `refs/tags/v*`
  - release ruleset name: `Protect release tags`
  - release ruleset enforcement: active, no bypass actors, no exclusions, and
    exactly the `update` and `deletion` rule types
  - Actions permissions: `allowed_actions == "selected"` and
    `sha_pinning_required is True`
- Exact-SHA source policy and live repository policy must use the same
  third-party action inventory. A new third-party action requires an explicit
  test and release-preflight policy change.
- Do not broaden secrets or permissions. Preserve the semantic workflows'
  step-scoped provider secret handling and keep release write permissions
  job-scoped.
- The build frontend and installed uv version are exact and lock-backed.
  Workflow changes must not silently reintroduce latest-at-runtime tool
  resolution.
- The release workflow stages all distributions and the attestation in a draft
  GitHub Release before PyPI; the public immutable GitHub Release is the final
  step after PyPI succeeds.
- A stale draft may be deleted only after matching the exact tag and target SHA.
  A published release is never deleted or replaced by automation.
- Remote release tags are permanent. The legacy remote-retag escape hatch is
  removed to match current SimpleBroker and the required write-once ruleset;
  local unpublished tag replacement remains allowed.
- Repository policy read failures are fatal for a real release and for the
  standalone check. Dry runs report the check without requiring network access.
- This change does not mutate GitHub repository settings, push a tag, publish
  artifacts, or auto-merge dependency updates.
- No runtime dependency is added. The `build` package is release-tooling only
  and is locked in a dedicated dependency group.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| Operational release helper | Preserve branch-first remote retag support while ensuring it cannot bypass exact-SHA CI | Removed the remote-retag option; an existing remote tag at another SHA always requires a new version | The implementation comparison found current SimpleBroker no longer supports remote retagging, and the planned write-once ruleset would reject it. Preserving a dead escape hatch would make the local contract contradict the live policy. | None; release publishing is owned by the implementation note |
| [SC-17.1] `RUFF-SUP-142` | No product-spec revision | Retired the suppression registry row and regenerated the derived index | The remote-retag removal simplified `plan_tag_action`; retaining a no-longer-needed exception would fail the suppression cardinality gate and weaken policy hygiene | Applied in this change |

## Rollback and Rollout

Rollback before a real release is a normal revert of the workflow, helper,
tests, lockfile, and documentation changes. Keep the source pin gate and live
GitHub setting synchronized during rollback: reverting only one side would make
the repository either unexpectedly reject workflows or silently weaken policy.

Rollout order:

1. Land source pins, tests, helpers, locked build policy, and documentation.
2. Configure the repository's selected-action allowlist and full-SHA setting,
   `pypi` environment tag policy, immutable releases, and protected release-tag
   ruleset outside this patch.
3. Run `bin/release.py --check-repository-settings` with authenticated GitHub
   access. Do not attempt a release until it passes.
4. Exercise dry-run release preparation.
5. The first real tag is the post-deploy acceptance event: require the draft,
   PyPI artifact, attestation, and final immutable GitHub Release to agree on
   tag, SHA, package, version, and assets.

The PyPI publish remains a one-way door. After it succeeds, recovery is a new
fix-forward version; never move or replace the published tag.

## Tasks

1. Add failing structural policy tests.
   - Extend `tests/test_release_workflow.py` to reject every mutable external
     workflow reference across `*.yml` and `*.yaml`, enforce the exact
     third-party inventory, require shared uv pins, require the locked build,
     and require draft-first publication and minimum job permissions.
   - Extend `tests/test_release_script.py` with repository-settings fixtures,
     negative cases, and a proof that `--skip-checks` cannot skip policy.
   - Add focused tests for the publication helper and uv policy helper.
   - Done signal: the new tests fail for the current source for the intended
     reasons before implementation begins.

2. Pin and maintain the workflow toolchain.
   - Replace every external workflow tag with the reviewed current commit used
     by SimpleBroker or the current upstream release where Backstitch alone uses
     the action.
   - Add one exact `UV_VERSION` to every setup-uv workflow and a repository
     `required-version` constraint.
   - Add `bin/bump_uv.py` as the single transactional update path for workflow
     pins, the uv constraint, and `uv.lock`.
   - Add weekly root uv and GitHub Actions Dependabot proposals without
     auto-merge. The uv entry owns the new locked release dependency and root
     lock maintenance; `bin/bump_uv.py` owns the coupled installed-uv policy.
   - Stop if a new action owner is needed or a pin does not resolve to the
     claimed upstream release commit.

3. Port the locked, draft-first publication state machine.
   - Add a release-only locked `build` dependency group.
   - Replace `uv build` in the GitHub release build with
     `uv sync --frozen --group release`, then
     `uv run --frozen --no-sync python -m build --no-isolation` through that
     locked environment. Prove `build` remains out of runtime dependencies.
   - Port and adapt the stdlib-only draft publication helper.
   - Stage a complete draft release before PyPI, download artifacts through the
     authenticated GitHub CLI as in SimpleBroker, and publish the verified
     immutable draft last.
   - Stop if the adaptation would change Backstitch's tag grammar, required
     workflows, or single-package boundary.

4. Add fail-closed repository policy verification.
   - Port the settings reader into `bin/release.py`, adapted to
     `VanL/backstitch`, `v*`, and Backstitch's exact third-party inventory.
   - Add standalone `--check-repository-settings` and run the same check before
     every real release, independent of `--skip-checks`.
   - Keep dry-run network-free and explicit about the deferred verification.
   - Port the pre-tag exact-SHA gate into the real release driver: require the
     `main` branch, push `origin main`, invoke
     `.github/scripts/require_green_workflows.py --repo VanL/backstitch --sha
     <release_sha> --workflow CI --workflow local-llm`, verify the release SHA
     is still reachable from `origin/main`, and only then prepare and push the
     tag. `--skip-checks` may not bypass this sequence, and remote retag mode
     is removed because release tags are permanent.
   - Add command-order and refusal tests for a failed workflow wait or
     reachability check. Mock subprocess execution, not the constructed command
     or ordering contract.

5. Reconcile operational documentation.
   - Update `docs/implementation/05-release-publishing.md` with the new source
     policy, update path, repository settings, publication order, rollback,
     and first-release acceptance signal.
   - Update the repository map for new helpers.
   - Record exact verification and review evidence here.

6. Verify and independently review.
   - Run targeted tests after each slice, then formatting, lint, mypy, the full
     hermetic and benchmark scopes, acceptance tests, build, and the zero-warning
     self-corpus gate.
   - Run an independent plan review before implementation and an independent
     completed-work review before closeout. Disposition every finding.

## Testing Plan

Use real workflow and configuration files for source-policy tests. Use real
asset and publication-state validation in the helper tests. Mock only HTTP and
subprocess boundaries; do not mock the policy comparison, release ordering, or
asset-set checks.

Failing-first proof:

- `uv run --frozen --no-sync pytest -q tests/test_release_workflow.py tests/test_release_script.py tests/test_release_publication_script.py tests/test_bump_uv.py`

Targeted and final commands:

- `uv run --frozen --no-sync pytest -q tests/test_release_workflow.py tests/test_release_script.py tests/test_release_publication_script.py tests/test_bump_uv.py tests/test_release_workflow_gate.py`
- `uv run --frozen --no-sync ruff format --check backstitch bin .github/scripts tests`
- `uv run --frozen --no-sync ruff check . bin/check-doc-paths bin/check-dom15-fixtures bin/coalesce-check`
- `uv run --frozen --no-sync python bin/ruff_suppression_index.py --check`
- `uv run --frozen --no-sync mypy backstitch bin/release.py tests --config-file pyproject.toml`
- `uv run --frozen --no-sync python -m py_compile .github/scripts/require_green_workflows.py .github/scripts/release_publication.py`
- `uv run --frozen --no-sync pytest tests -q -n auto --dist loadgroup -m "not live_llm and not benchmark"`
- `uv run --frozen --no-sync pytest tests -q -n 0 -m benchmark`
- `env -u BACKSTITCH_LIVE_LLM uv run --frozen --no-sync pytest tests/live/test_live_llm.py -q -o run_live_llm=false`
- `uv run --frozen --no-sync pytest tests/acceptance -q`
- `uv sync --frozen --group release`
- `uv run --frozen --no-sync python -m build --no-isolation`
- `uv run --frozen --no-sync backstitch check --repo-root .`

The live repository-settings command is an operational rollout probe, not a
local completion precondition until the external settings are authorized and
configured. The unit tests must prove its fail-closed behavior.

## Verification and Gates

Per-slice evidence is recorded in the Execution Log. Final source completion
requires all listed local commands to pass, the self-corpus check to report
zero errors and zero warnings, and the exact action tags to resolve to the
pinned commits. Operational readiness additionally requires the live
repository-settings check and one successful real tagged release.

## Independent Review Loop

Plan review and completed-work review use the stance in
`docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`: existence
check every named file, flag, API field, and driver order first; then look for
security regression, latent ambiguity, or ceremony that does not reduce a real
risk. A BLOCKED plan verdict must explain why the plan cannot be implemented
confidently or would degrade security/robustness. Every finding is accepted,
rejected with reasoning, or marked out of scope with a reopen condition.

## Out of Scope

- A real release, tag push, PyPI publication, or GitHub Release mutation.
- Mutating GitHub repository, environment, ruleset, or Actions settings.
- Extension or batch release machinery.
- Changing provider secrets, semantic behavior, product contracts, or runtime
  dependencies.
- Automatically merging dependency updates.

## Fresh-Eyes Review

Before closeout, re-read the plan, diff, and executable release driver for
contradictions in publication order, tag identity, action inventory, permission
scope, setting names, dry-run behavior, rollback, and verification commands.

## Execution Log

### Pre-implementation comprehension answers

1. All non-local action references in both workflow suffixes are in scope.
2. PyPI acceptance is the one-way door; draft staging precedes it and immutable
   GitHub publication follows it.
3. Repository-settings verification is mandatory for real releases even with
   `--skip-checks`.
4. Tests mock only HTTP and subprocess boundaries, not policy comparison,
   validation, or order.

### Verification evidence

- Failing-first workflow slice: eight selected structural tests failed against
  mutable action references and the missing UV, dependency-update, locked
  build, draft, and permission contracts.
- Failing-first settings slice: nine settings and CLI tests failed because the
  reader and standalone check did not exist.
- Failing-first publication slice: collection failed because the draft
  publication helper did not exist.
- Focused post-implementation suite:
  `uv run pytest tests/test_release_workflow.py
  tests/test_release_publication_script.py tests/test_bump_uv.py
  tests/test_release_script.py tests/test_release_workflow_gate.py -q` passed;
  the final collection contains 137 tests.
- Focused Ruff and mypy gates passed after splitting the settings verifier into
  bounded policy helpers; no new suppression was added.
- `bin/bump_uv.py --check` passed with CI uv `0.12.5` and local constraint
  `>=0.12.5,<0.13`; CI now runs the same gate after installing uv.
- The frozen release build succeeded and produced
  `backstitch-0.3.0.tar.gz` and `backstitch-0.3.0-py3-none-any.whl` through
  `build==1.5.0` and `hatchling==1.32.0` with isolation disabled.
- Ruff format covered 172 files; canonical Ruff passed; the governed
  suppression index passed; mypy passed 167 source files; Python compilation
  passed for both release helpers.
- The 62-test acceptance suite passed. Both benchmark stories executed and
  passed; their comparative qualification remained explicitly unavailable
  because the runner contract is not committed. The disabled-live probe
  reported exactly one skip.
- The self-corpus gate reported 128 spec sections, 421 mappings, 587 code refs,
  1175 edges, 9 invariants, 17 binds, and zero errors, warnings, or infos.
- Documentation path, DOM-15 fixture, coalescing provenance, and `git diff
  --check` gates passed.
- The full 2,786-test hermetic selection reached completion with four failures.
  Three in-scope Ruff governance fixtures were updated and then passed. The
  sole remaining failure is the pre-existing cross-repository
  `tests/test_weft_corpus_traceability.py` debt set, which no longer matches
  the current `../weft` checkout; no Backstitch release behavior is implicated.
- Live `bin/release.py --check-repository-settings` failed closed as designed:
  immutable releases, selected/full-SHA Actions policy, the `pypi` tag policy,
  and the write-once release-tag ruleset are not yet configured. This is the
  explicit external rollout gate and no setting was mutated by this change.
- GitHub tag resolution, including annotated-tag peeling, verified every
  claimed action version against its pinned executable commit.

## Review Log

Round 1: BLOCKED with F1-F4. All accepted:

- F1: made the SimpleBroker pre-tag branch push, exact-SHA workflow wait,
  reachability check, and non-bypass tests explicit.
- F2: made release-group frozen sync precede the no-isolation build in both
  implementation and final verification; added the dependency-boundary proof.
- F3: added weekly root uv Dependabot maintenance alongside GitHub Actions.
- F4: enumerated the exact Backstitch Actions, PyPI environment, and release-tag
  policy constants.

Round 2: PASS. The reviewer verified F1-F4 against the executable poller,
SimpleBroker source, uv command shape, and GitHub policy fields and found no new
defect introduced by the corrections. Implementation unblocked.

Completed-work review round 1: BLOCKED with two findings.

- The reviewer initially compared three action pins to annotated tag-object
  SHAs. After rechecking peeled executable commits, the reviewer rescinded the
  finding; all three pins match their claimed releases.
- The reviewer correctly found that the publication helper verified the remote
  tag SHA but not the matching release payload's `target_commitish`. Accepted:
  both stale-draft deletion and draft publication/rerun now require
  `target_commitish == expected_sha`, with wrong and missing target tests.

Completed-work review round 2: PASS. The reviewer inspected the target-SHA fix,
reran the focused release suite, compilation, UV gate, and diff check, and
reported no remaining blocking finding.

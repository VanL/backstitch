# Backstitch Release Publishing Plan

## Goal

Port the single-package subset of the release and publishing process used by
`../weft`, `../taut`, and `../simplebroker` into backstitch: a local release
helper, tag-triggered GitHub release gate, PyPI Trusted Publishing, artifact
attestation, and concise release documentation.

## Requested Outcomes

- Add a repo-local `bin/release.py` that updates backstitch version files
  together, runs release prechecks, creates a release commit when needed, and
  safely creates or pushes `vX.Y.Z` tags.
- Add a tag-triggered release gate that publishes the root `backstitch` package
  to PyPI via Trusted Publishing and creates a GitHub Release with distribution
  artifacts and an attestation bundle.
- Keep backstitch single-package only. Do not port sibling extension, batch,
  database, Docker, macOS sandbox, or local Weft dependency machinery.
- Add focused tests for the helper and workflow contracts.
- Document the release boundary and operator steps.

## Source Documents

Source specs:
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-8], [DOM-10], [DOM-11]
- `docs/specs/02-backstitch-core.md` [SC-5], [SC-10]

Source spec for release publishing itself: none. The sibling repositories define
the practical process by implementation:
- `../simplebroker/bin/release.py`
- `../simplebroker/.github/workflows/release-gate.yml`
- `../simplebroker/.github/scripts/require_green_workflows.py`
- `../weft/bin/release.py`
- `../weft/.github/workflows/release-gate.yml`
- `../weft/.github/workflows/release.yml`
- `../taut/bin/release.py`
- `../taut/.github/workflows/release-gate.yml`
- `../taut/.github/workflows/release.yml`

## Spec Baseline

- `2c94c50b180e6ec4cf3018b37f8576af9ffe3318` — DOM and backstitch core specs
  at plan authoring time, with existing worktree modifications in unrelated
  agent-context docs.

## Proposed Spec Delta

None. This plan adds release tooling and implementation documentation. It does
not change the backstitch CLI contract, issue-code contract, configuration
contract, or traceability behavior.

## Context And Key Files

Backstitch currently has package metadata and a console script in
`pyproject.toml`, a matching runtime version in `backstitch/__init__.py`, and a
single CI workflow at `.github/workflows/ci.yml`. There is no `bin/` directory,
no release helper, no release-gate workflow, and no GitHub helper script.

Files to read before editing:
- `pyproject.toml` — package name, version, extras, build backend, tool config.
- `backstitch/__init__.py` — `__version__` source used by `backstitch --version`
  through `backstitch/cli.py`.
- `.github/workflows/ci.yml` — current hermetic and live-LLM CI gates.
- `docs/implementation/04-backstitch-style-traceability.md` — current
  verification map and self-corpus rationale.
- Sibling release helper and workflows listed above.

Files expected to touch:
- `bin/release.py`
- `.github/workflows/release-gate.yml`
- `.github/scripts/require_green_workflows.py`
- `.github/workflows/ci.yml`
- `tests/test_release_script.py`
- `tests/test_release_workflow.py`
- `tests/test_release_workflow_gate.py`
- `README.md`
- `docs/implementation/00-implementation-index.md`
- `docs/implementation/02-repository-map.md`
- `docs/implementation/05-release-publishing.md`
- this plan

Comprehension checks before implementation:
- Which two local files must always carry the same package version?
  `pyproject.toml` and `backstitch/__init__.py`.
- Which CI signal must the release gate wait for before publishing?
  The existing `CI` workflow for the release commit/tag SHA.
- Which sibling process should be rejected as out of scope?
  Extension-specific and batch-release machinery from Weft, Taut, and
  SimpleBroker.

## Invariants And Constraints

- Release tags for backstitch are only `vX.Y.Z`; no namespaced extension tags.
- `pyproject.toml` and `backstitch/__init__.py` versions must match before and
  after the helper writes a release version.
- The helper must never publish directly. Pushing the tag triggers GitHub
  Actions; GitHub Actions publishes via PyPI Trusted Publishing.
- Existing dirty-tree discipline remains: a real release refuses a dirty
  worktree; `--dry-run` may report what would happen.
- A version already published on PyPI or as a GitHub Release must be rejected.
- Retagging an unpublished remote tag is explicit through `--retag`; the helper
  must not move remote tags silently.
- The release workflow must verify the tag still points at the tested commit
  before building/publishing and before creating the GitHub Release.
- The release gate must upload only `dist/*.tar.gz`, `dist/*.whl`, and the
  attestation bundle. Do not attach broad `dist/*` globs.
- Prechecks must include real tests, lint, format check, type check including
  `bin/release.py`, and `backstitch check --repo-root .`.
- The new format check is scoped to release-owned files and `backstitch/`.
  Existing unrelated test formatting drift is not part of this change.
- Version-sensitive generated checks (`uv lock` and `uv build`) are
  post-update steps, not prechecks. They must run after version files are
  updated so they verify the release version.
- No new project dependency is allowed. Use the standard library and existing
  GitHub Actions patterns.
- Auxiliary publication failure is fatal inside the release workflow. A failed
  publish or moved tag must stop the release.
- The local release helper must run the live LLM test by forcing
  `BACKSTITCH_LIVE_LLM=1`; a release precheck should fail when local provider
  credentials or model configuration are missing.
- CI must include the live LLM job in the normal `CI` workflow and skip that
  job's provider call only when repository secrets are unavailable.
- The release gate must wait for the `CI` workflow name, not sibling workflow
  names such as `Test`.
- Release workflow jobs that attest or publish must grant the required least
  permissions at job scope: `id-token: write`, `attestations: write`, and
  artifact metadata permissions for attestation; `id-token: write` for PyPI
  publishing; `contents: write` for the GitHub Release.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Rollback And Rollout

Rollback before first real tag push is a normal revert of the new helper,
workflow, tests, and docs. After a tag has been pushed but before publication,
delete the unpublished tag locally and remotely if the release must be aborted.
After PyPI publication, the release is a one-way door: publish a newer version
instead of deleting or replacing the published artifact.

Rollout requires repository setup outside this patch:
- configure the `pypi` GitHub environment for Trusted Publishing on PyPI
- ensure GitHub Actions can request OIDC tokens for `backstitch`
- run `bin/release.py --dry-run --skip-checks` before the first real release
- configure `OPENAI_API_KEY` for the repository so CI tag runs exercise live
  LLM before the release gate publishes
- run a real release only from a clean branch intended to be pushed

Post-release success signal:
- the tag's `Release Gate (backstitch)` workflow completes successfully
- the new version appears at `https://pypi.org/project/backstitch/`
- the GitHub Release for `vX.Y.Z` contains exactly the source distribution,
  wheel, and attestation bundle

## Tasks

1. Add the single-package release helper.
   - Touch `bin/release.py`.
   - Reuse the SimpleBroker helper's publication-state checks, tag-action
     planning, dry-run behavior, and command-printing structure.
   - Remove all extension, batch, local Weft, and backend-specific behavior.
   - Include prechecks for pytest, live LLM, ruff check, ruff
     format check, mypy over `backstitch` and `bin/release.py`, and
     self-corpus check.
   - Include post-version-update steps for `uv lock`, a version smoke test,
     and `uv build`.
   - Match `backstitch/__init__.py` as it exists today:
     `__version__ = "0.1.0"` without requiring a `Final[str]` annotation.
   - Run the live LLM test with `BACKSTITCH_LIVE_LLM=1`; the hermetic full test
     command must still use `-m "not live_llm"` so provider work is isolated.
   - Stop and re-evaluate if this grows extension-target abstractions.

2. Add the release gate and CI alignment.
   - Touch `.github/workflows/release-gate.yml`,
     `.github/scripts/require_green_workflows.py`, and `.github/workflows/ci.yml`.
   - Use the SimpleBroker top-level gate shape: wait for required workflows,
     verify tag immobility, build, attest, publish to PyPI, then create the
     GitHub Release.
   - Invoke the workflow gate helper with `--workflow "CI"`.
   - Keep the Python/uv setup aligned with the existing backstitch CI style
     unless a release-only requirement forces a different shape.
   - Keep current CI semantics for normal push, pull request, and manual runs.
   - Add format and typed-release-helper checks to CI.

3. Add focused tests.
   - Touch `tests/test_release_script.py`, `tests/test_release_workflow.py`,
     and `tests/test_release_workflow_gate.py`.
   - Test version validation, version-file mismatch rejection, version writes,
     GitHub remote slug parsing, publication-state rejection, tag-action
     planning, dirty real release refusal, dry-run command plan, and workflow
     guardrails.
   - Mock only network, git command output, and command execution boundaries.
     Do not mock version-file parsing or command construction.

4. Add release documentation.
   - Touch `README.md`, `docs/implementation/00-implementation-index.md`,
     `docs/implementation/02-repository-map.md`, and
     `docs/implementation/05-release-publishing.md`.
   - Document owner, boundary, required setup, operator steps, rollback, and
     verification.

5. Verify and review.
   - Run targeted release tests first.
   - Run formatting, type, full hermetic suite, acceptance probes, build, and
     self-corpus gate.
   - Run an independent review if another agent family is available. If not,
     run a strict fresh-eyes review and record that limitation.
   - Update this plan's closeout evidence.

## Testing Plan

Use production file parsing for version reads/writes. Use monkeypatched network,
GitHub, PyPI, git, and subprocess command boundaries for helper tests. Workflow
tests may inspect YAML as text to avoid adding a parser dependency.

Commands:
- `uv run pytest tests/test_release_script.py tests/test_release_workflow.py tests/test_release_workflow_gate.py -q`
- `uv run ruff format --check backstitch bin .github/scripts tests/test_release_script.py tests/test_release_workflow.py tests/test_release_workflow_gate.py`
- `uv run ruff check backstitch tests bin`
- `uv run mypy backstitch bin/release.py --config-file pyproject.toml`
- `uv run pytest tests -q -m "not live_llm"`
- `uv run pytest tests/live/test_live_llm.py -q`
- `BACKSTITCH_LIVE_LLM=1 uv run pytest tests/live/test_live_llm.py -q` when
  local live-provider credentials are available
- `uv run pytest tests/acceptance -q`
- `uv build`
- `uv run backstitch check --repo-root .`

## Verification And Gates

Per-task done signals:
- Helper: targeted helper tests pass and `bin/release.py --dry-run --skip-checks`
  prints a coherent plan without modifying files.
- Workflow: workflow tests prove tag triggers, CI gating, tag immobility, Trusted
  Publishing, attestation, and narrow release artifacts.
- Docs: README and implementation docs name the setup and rollback boundaries.

Final completion requires:
- all testing-plan commands pass from the current worktree
- self-corpus gate exits `0` with zero errors and zero warnings
- independent or fresh-eyes review findings are answered
- residual risks are named, especially any GitHub/PyPI setup that cannot be
  proved locally

## Independent Review Loop

Preferred review: a different agent family using the stance from
`docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`.

Review prompt:

> Read `docs/plans/2026-07-03-backstitch-release-publishing-plan.md`, the
> sibling release setup, and the touched files. Look for errors, bad ideas,
> missing release safety checks, and latent ambiguity. Do not implement. Could
> you operate or maintain this release process confidently after the change?

If no different agent family is available, use a strict fresh-eyes review and
record the limitation in this plan.

Review result:
- Gemini blocked on workspace trust.
- Claude blocked on authentication.
- Qwen blocked on unavailable model.
- OpenCode completed read-only plan review. Accepted findings:
  post-update ordering for `uv lock`/`uv build`; untyped `__version__`
  matching; explicit release workflow permissions; backstitch-aligned Python/uv
  setup; exact `CI` workflow name.
- User correction after initial implementation: `release.py` and CI must both
  include live LLM tests. CI may skip the provider call only when repository
  secrets are unavailable.
- Final OpenCode implementation review attempted and failed with a provider
  error after creating temporary scratch dumps. The scratch files were removed.
  A strict local fresh-eyes review found no code changes required. Residual
  risk: the GitHub/PyPI Trusted Publishing path cannot be fully proved until
  the repository environment and PyPI project trust relationship are configured
  and a real tag workflow runs.

## Out Of Scope

- Publishing extension packages.
- Batch releases.
- TestPyPI support.
- Changing package dependencies.
- Changing backstitch traceability behavior, issue codes, or config schema.
- Running a real release, pushing a tag, or creating a GitHub/PyPI publication.

## Fresh-Eyes Review

Before completion, re-read this plan and the final diff for missing file paths,
missing gates, ambiguous release ownership, hidden tag/publish one-way doors,
and accidental extension machinery.

## Closeout Evidence

- Changed files: `bin/release.py`, `.github/workflows/release-gate.yml`,
  `.github/workflows/ci.yml`, `.github/scripts/require_green_workflows.py`,
  `tests/test_release_script.py`, `tests/test_release_workflow.py`,
  `tests/test_release_workflow_gate.py`, `README.md`,
  `docs/implementation/00-implementation-index.md`,
  `docs/implementation/02-repository-map.md`,
  `docs/implementation/05-release-publishing.md`, and this plan.
- `uv run pytest tests/test_release_script.py tests/test_release_workflow.py tests/test_release_workflow_gate.py -q`
  passed: 31 tests.
- `uv run ruff format --check backstitch bin .github/scripts tests/test_release_script.py tests/test_release_workflow.py tests/test_release_workflow_gate.py`
  passed: 22 files already formatted.
- `uv run ruff check backstitch tests bin .github/scripts` passed.
- `uv run ruff check .` passed.
- `uv run mypy backstitch bin/release.py .github/scripts/require_green_workflows.py --config-file pyproject.toml`
  passed.
- `python3 -m py_compile .github/scripts/require_green_workflows.py` passed,
  proving the release-gate poller is not limited to Python 3.14 syntax.
- `uv run pytest tests -q -m "not live_llm"` passed.
- `uv run pytest tests/live/test_live_llm.py -q` passed with one expected
  opt-in skip for the hermetic skip-proof command.
- User correction supersedes the release-helper skip precheck: `release.py`
  now runs `BACKSTITCH_LIVE_LLM=1 uv run pytest tests/live/test_live_llm.py -q`
  as a real precheck. The provider-backed command requires live-provider
  credentials and was not executed locally in this environment.
- `uv run pytest tests/acceptance -q` passed: 14 tests.
- `uv build` passed and built `dist/backstitch-0.1.0.tar.gz` plus
  `dist/backstitch-0.1.0-py3-none-any.whl`.
- `bin/release.py --version 99.99.99 --dry-run` passed and showed release
  prechecks for hermetic tests, live LLM tests with `BACKSTITCH_LIVE_LLM=1`,
  ruff, ruff format, mypy, and the self-corpus gate before the version bump,
  `uv lock`, version smoke, `uv build`, release commit, `v99.99.99` tag
  creation, branch push, and tag push.
- `uv run backstitch check --repo-root .` passed: exit `0`, 0 errors, 0
  warnings.
- Residual risk: actual PyPI publication, OIDC trust, artifact attestation, and
  GitHub Release creation require a real tagged workflow in GitHub Actions.

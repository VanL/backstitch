# Release Publishing

## Purpose And Scope

This document owns Backstitch's maintainer release path. It covers the local
release driver, exact-SHA pre-tag checks, GitHub repository policy, the
tag-triggered publication gate, PyPI Trusted Publishing, artifact attestation,
and rollback boundaries.

Backstitch is a single-package Python tool. The release process intentionally
does not include extension packages, batch release semantics, database service
tests, or local sibling dependency injection.

## Governing References

- `docs/specs/01-development-documentation-operating-model.md` [DOM-8],
  [DOM-10]
- `docs/specs/02-backstitch-core.md` [SC-5], [SC-10]
- `docs/plans/2026-07-03-backstitch-release-publishing-plan.md`
- `docs/plans/2026-08-24-release-supply-chain-and-publication-hardening-plan.md`

No product spec owns release publishing. This implementation note is the
operational contract.

## Key Files

| Path | Purpose |
|------|---------|
| `bin/release.py` | Maintainer driver for policy checks, version updates, local checks, release commits, exact-SHA CI waits, and immutable tag creation |
| `bin/bump_uv.py` | Transactional updater and consistency check for the shared workflow UV version, `tool.uv.required-version`, and `uv.lock` |
| `.github/workflows/release-gate.yml` | Tag-triggered locked build, attestation, draft staging, PyPI publish, and immutable GitHub Release publication |
| `.github/scripts/require_green_workflows.py` | Polls GitHub Actions for required green runs on one exact commit SHA |
| `.github/scripts/release_publication.py` | Validates, replaces, and publishes the exact GitHub Release draft and its assets |
| `.github/dependabot.yml` | Weekly review-only proposals for root uv dependencies and GitHub Actions |
| `.github/workflows/ci.yml` | Required `CI` workflow |
| `.github/workflows/local-llm.yml` | Required `local-llm` workflow |
| `pyproject.toml` | Package version, locked release dependency group, and supported uv range |
| `backstitch/__init__.py` | Runtime `__version__` used by `backstitch --version` |
| `uv.lock` | Root dependency lock, including release-only build tooling |

## Maintainer Flow

Check the external GitHub controls first:

```bash
bin/release.py --check-repository-settings
```

Run a dry run when the helper should update the version files:

```bash
bin/release.py --version X.Y.Z --dry-run
```

For a real release, use a clean worktree on `main`:

```bash
bin/release.py --version X.Y.Z
```

When the version files are already prepared, `all` remains a
SimpleBroker-compatible alias for Backstitch's one package:

```bash
bin/release.py all --dry-run
bin/release.py all
```

A real release:

1. requires `main`, a clean worktree, authenticated GitHub access, and the
   exact repository policy described below
2. rejects a version already published on PyPI or as a GitHub Release
3. runs local prechecks unless `--skip-checks` is passed; repository policy
   and pre-tag exact-SHA CI cannot be skipped
4. updates `pyproject.toml` and `backstitch/__init__.py` together
5. runs `uv lock`, the version smoke test, frozen synchronization of the
   `release` group, and
   `uv run --frozen --no-sync python -m build --no-isolation`
6. commits changed release files, then records the exact release SHA
7. pushes `origin main` and waits for successful `CI` and `local-llm`
   runs whose `head_sha` is exactly the release SHA
8. fetches `origin/main` and proves the tested release SHA is still reachable
   from it
9. refreshes publication and tag state, then creates `vX.Y.Z` at that exact
   SHA and pushes it

Remote release tags are write-once. There is no remote-retag option. A local
unpublished tag may be replaced before it is pushed, but an existing remote tag
at another commit requires a new version. The helper never publishes package
artifacts directly; the tag starts `.github/workflows/release-gate.yml`.

A dry run performs no GitHub repository-settings read. It reports that a real
release will require that check and prints the exact pre-tag sequence without
executing it.

## Repository Policy

The standalone check and every real release fail closed unless GitHub reports:

- immutable releases enabled
- Actions restricted to selected actions with full-SHA pinning required
- GitHub-owned actions allowed and blanket verified publishers disabled
- exactly these third-party patterns:
  `astral-sh/setup-uv@*`, `codecov/codecov-action@*`,
  `pypa/gh-action-pypi-publish@*`, and
  `softprops/action-gh-release@*`
- the `pypi` environment using custom deployment policies with exactly the
  tag policy `v*`
- one active tag ruleset named `Protect release tags`, covering exactly
  `refs/tags/v*`, with no exclusions or bypass actors and exactly the
  `update` and `deletion` rules

The source policy mirrors that boundary: every external `uses:` reference in
`.github/workflows/*.yml` and `*.yaml` is a reviewed 40-character commit
SHA. Tests reject a new third-party action unless the source allowlist and live
policy contract are changed together.

The current repository settings must be rolled out separately. Source changes
do not authorize a GitHub settings mutation.

## Toolchain Updates

All workflows that install uv declare one `UV_VERSION` and pass it to
`astral-sh/setup-uv`. `pyproject.toml` constrains the supported minor
series. Update these coupled surfaces with:

```bash
bin/bump_uv.py --ci-version X.Y.Z --required-version '>=X.Y.Z,<next-minor'
bin/bump_uv.py --check
```

The updater edits all managed workflows and the root constraint as one
transaction, regenerates `uv.lock`, and rolls back source edits if lock
generation or validation fails.

Dependabot proposes weekly root uv and GitHub Actions updates. There is no
auto-merge path. Review action source and release notes, update the version
comment and full commit SHA together, then run the source-policy tests.

## GitHub Release Gate

The tag-triggered gate repeats the exact-SHA `CI` and `local-llm` check and
verifies that the remote tag still points to the tested commit. It then:

1. checks out the exact SHA and installs the declared uv version
2. performs `uv sync --frozen --group release` against the selected Python
   3.11 interpreter
3. builds through the locked `build==1.5.0` frontend with isolation disabled
4. generates an artifact attestation and stores distributions plus the
   Sigstore bundle as workflow artifacts
5. downloads those artifacts with authenticated `gh run download`, validates
   any matching stale draft, and stages a complete draft GitHub Release
6. publishes the distributions to PyPI through the `pypi` environment and
   OIDC Trusted Publishing
7. after the PyPI publisher succeeds, downloads the same artifacts again,
   verifies the exact draft target and asset set, then publishes the draft as
   the final immutable GitHub Release; an idempotent rerun also verifies the
   exact package/version is visible on PyPI

PyPI acceptance is the publication one-way door. Staging a complete draft
before it reduces the post-PyPI work to validation and one publish transition.
The publication helper never deletes a published release. It deletes a stale
draft only when its tag and target SHA exactly match the requested release.

The final GitHub Release contains only:

- `dist/*.tar.gz`
- `dist/*.whl`
- `attestations/*.sigstore.json`

Do not broaden distribution globs or mix workflow-artifact metadata with
release assets.

## External Setup And First-Release Acceptance

Required external setup:

- PyPI Trusted Publishing for `VanL/backstitch`
- the `pypi` GitHub environment and exact `v*` deployment policy
- the Actions allowlist and full-SHA setting above
- immutable GitHub Releases
- the active write-once release-tag ruleset above

After rollout, `bin/release.py --check-repository-settings` must pass before a
release attempt. The first real release is the post-deploy acceptance event.
Confirm that the tag, workflow SHA, PyPI version, wheel and source
distribution, attestation, and final immutable GitHub Release all agree. A
green source test is not a substitute for this external signal.

## Rollback Boundary

Before the tag is pushed, rollback is a normal revert of local changes or the
landed source change. Keep the source third-party inventory and live Actions
allowlist synchronized during rollout or rollback.

Once a release tag reaches `origin`, the ruleset makes it permanent. If the
workflow fails before PyPI, fix the workflow without moving the tag and rerun
the existing release gate when safe. Once PyPI accepts a version, recovery is a
new fix-forward version. Never delete, replace, or move a published release
tag or artifact.

## Verification

Release-process changes should prove:

- `uv run --frozen --no-sync pytest -q tests/test_release_workflow.py tests/test_release_script.py tests/test_release_publication_script.py tests/test_bump_uv.py tests/test_release_workflow_gate.py`
- `bin/bump_uv.py --check`
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

The final self-corpus command must exit 0 with zero errors and zero warnings.
The live settings check and one real release are rollout gates, not local source
completion gates.

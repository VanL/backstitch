# Release Publishing

## Purpose And Scope

This document explains the backstitch release path for maintainers. It covers
the local helper, tag-triggered GitHub release gate, PyPI Trusted Publishing,
artifact attestation, and rollback boundaries.

Backstitch is a single-package Python tool. The release process intentionally
does not include extension packages, batch releases, database service tests, or
local sibling dependency injection from Weft, Taut, or SimpleBroker.

## Governing References

- `docs/specs/01-development-documentation-operating-model.md` [DOM-8],
  [DOM-10]
- `docs/specs/02-backstitch-core.md` [SC-5], [SC-10]
- `docs/plans/2026-07-03-backstitch-release-publishing-plan.md`

No product spec currently owns release publishing itself. This file is the
implementation note for the operational process.

## Key Files

| Path | Purpose |
|------|---------|
| `bin/release.py` | Maintainer helper for version updates, local prechecks, release commits, and tag pushes |
| `.github/workflows/release-gate.yml` | Tag-triggered release gate for build, attestation, PyPI publish, and GitHub Release upload |
| `.github/scripts/require_green_workflows.py` | Polls GitHub Actions for required green workflow runs before publishing |
| `.github/workflows/ci.yml` | Required `CI` workflow that the release gate waits for |
| `pyproject.toml` | Package metadata and release version source |
| `backstitch/__init__.py` | Runtime `__version__` used by `backstitch --version` |
| `uv.lock` | Lockfile updated after version changes |

## Maintainer Flow

Run a dry run first:

```bash
bin/release.py --version X.Y.Z --dry-run
```

For a real release, run from a clean worktree:

```bash
bin/release.py --version X.Y.Z
```

The helper:

1. rejects a dirty real-release worktree
2. verifies the requested version is unpublished on PyPI and GitHub Releases
3. runs local prechecks unless `--skip-checks` is passed, including the live
   LLM test with `BACKSTITCH_LIVE_LLM=1`
4. updates `pyproject.toml` and `backstitch/__init__.py` together
5. runs `uv lock`, `backstitch --version`, and `uv build`
6. commits changed release files
7. creates or pushes the `vX.Y.Z` tag

The helper never publishes directly. Pushing the tag starts
`.github/workflows/release-gate.yml`.

## GitHub Release Gate

The release gate runs on `v*` tags. It waits for the `CI` workflow on the same
commit SHA, verifies the tag still points at the tested commit, builds the
package with Python 3.14, generates an artifact attestation, publishes to PyPI
through Trusted Publishing, then creates the GitHub Release.

The workflow-gate helper is executed with the runner's system `python` before
the build job sets up Python 3.14. Keep `.github/scripts/require_green_workflows.py`
portable to that interpreter, not only to the project runtime.

Required external setup:

- a `pypi` GitHub environment
- PyPI Trusted Publishing configured for `VanL/backstitch`
- GitHub Actions OIDC permissions available for the publish job

The GitHub Release uploads only:

- `dist/*.tar.gz`
- `dist/*.whl`
- `attestations/*.sigstore.json`

Do not broaden this to `dist/*`; attestation and distribution artifacts have
different trust roles and should stay explicit.

## Rollback Boundary

Before a real tag is pushed, rollback is a normal revert of local changes. After
a tag is pushed but before publication, delete the unpublished tag locally and
from `origin` if the release must be aborted.

After PyPI publication, the release is a one-way door. Do not replace or delete
published artifacts as a normal rollback path; publish a newer version that
corrects the problem.

## Verification

Local release process changes should prove:

- `tests/test_release_script.py`
- `tests/test_release_workflow.py`
- `tests/test_release_workflow_gate.py`
- `uv run ruff format --check backstitch bin .github/scripts tests/test_release_script.py tests/test_release_workflow.py tests/test_release_workflow_gate.py`
- `uv run ruff check backstitch tests bin`
- `uv run mypy backstitch bin/release.py --config-file pyproject.toml`
- `python3 -m py_compile .github/scripts/require_green_workflows.py`
- `uv run pytest tests -q -m "not live_llm"`
- `uv run pytest tests/live/test_live_llm.py -q`
- `BACKSTITCH_LIVE_LLM=1 uv run pytest tests/live/test_live_llm.py -q` when
  live-provider credentials are available
- `uv run pytest tests/acceptance -q`
- `uv build`
- `uv run backstitch check --repo-root .`

The last command must exit `0` with zero errors and zero warnings.

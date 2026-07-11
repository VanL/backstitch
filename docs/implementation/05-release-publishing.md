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

Run a dry run first when the helper should update the version files:

```bash
bin/release.py --version X.Y.Z --dry-run
```

For a real release, run from a clean worktree:

```bash
bin/release.py --version X.Y.Z
```

When the version files and `CHANGELOG.md` are already prepared and committed,
use the SimpleBroker-compatible single-package target:

```bash
bin/release.py all --dry-run
bin/release.py all
```

The helper:

1. rejects a dirty real-release worktree
2. verifies the requested version is unpublished on PyPI and GitHub Releases
3. runs local prechecks unless `--skip-checks` is passed, including cloud and
   local live LLM tests with `BACKSTITCH_LIVE_LLM=1`; the helper starts a
   background local-LLM setup/readiness/prewarm probe before the earlier
   foreground checks, pulls the base Ollama model, recreates the bounded served
   model, and waits for it before the local live test
4. updates `pyproject.toml` and `backstitch/__init__.py` together
5. runs `uv lock`, `backstitch --version`, and `uv build`
6. commits changed release files
7. pushes the reviewed branch before tag mutation
8. checks for an active Release Gate, then refreshes PyPI, GitHub Release, and
   remote/local tag state after the long checks; publication, an active gate,
   or a changed remote tag stops the release
9. for `--retag`, deletes the observed unpublished remote tag with a
   `--force-with-lease` compare-and-swap, then recreates and pushes `vX.Y.Z`

The helper never publishes directly. Pushing the tag starts
`.github/workflows/release-gate.yml`.

## GitHub Release Gate

The release gate runs on `v*` tags. It waits for the `CI` and `local-llm`
workflows on the same commit SHA, verifies the tag still points at the tested
commit, verifies the `vX.Y.Z` tag matches `pyproject.toml`, builds the package
with the floor runtime (Python 3.11), generates an artifact attestation,
publishes to PyPI through Trusted Publishing, then creates the GitHub Release.
The `CI` workflow separately proves the hermetic suite on Python 3.11 and 3.14
before the release gate publishes.

The workflow-gate helper is executed with the runner's system `python` before
the build job sets up Python 3.11. Keep `.github/scripts/require_green_workflows.py`
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

`--retag` is branch-first and lease-guarded. A branch-push failure leaves the
old tag untouched. A lease failure means the remote tag changed and requires a
fresh state inspection. If replacement tag push fails after guarded deletion,
recheck publication and tag state before retrying the tag push. Never delete a
tag while an earlier Release Gate for it is active.

After PyPI publication, the release is a one-way door. Do not replace or delete
published artifacts as a normal rollback path; publish a newer version that
corrects the problem.

## Verification

Local release process changes should prove:

- `tests/test_release_script.py`
- `tests/test_release_workflow.py`
- `tests/test_release_workflow_gate.py`
- `uv run ruff format --check backstitch bin .github/scripts tests`
- `uv run ruff check backstitch tests bin`
- `uv run mypy backstitch bin/release.py tests --config-file pyproject.toml`
- `python3 -m py_compile .github/scripts/require_green_workflows.py`
- `uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm"`
- `env -u BACKSTITCH_LIVE_LLM uv run pytest tests/live/test_live_llm.py -q -o run_live_llm=false`
- `uv run pytest tests/live/test_live_llm.py -q` with the configured live
  provider; the repository pytest policy enables this locally
- `uv run pytest tests/acceptance -q`
- `uv build`
- `uv run backstitch check --repo-root .`

The last command must exit `0` with zero errors and zero warnings.

# Codecov Coverage CI Plan

## Goal

Add a dedicated coverage job to Backstitch's CI, upload its XML report to
Codecov under the same policy used by SimpleBroker, and expose the result with
a README badge.

## Source Documents

Source spec: None — repository tooling and documentation change.

Reference implementation:

- `../simplebroker/.github/workflows/test.yml`
- `../simplebroker/.codecov.yml`
- `../simplebroker/pyproject.toml`
- `../simplebroker/README.md`

Baseline: `c21d7c8bfdd0dae89ffab8d03cec0529f089f492`.

## Context and Key Files

- `.github/workflows/ci.yml` owns hermetic CI. It currently runs pytest without
  coverage collection or upload.
- `pyproject.toml` already declares `pytest-cov`; no dependency is required.
- `.codecov.yml` will carry SimpleBroker's project, patch, comment, and ignore
  policy.
- `README.md` will link the `VanL/backstitch` Codecov project.
- `tests/test_release_workflow.py` already guards load-bearing CI text and will
  gain firing assertions for the coverage contract.

## Invariants and Constraints

- The existing Python 3.11/3.14 hermetic test matrix remains unchanged.
- Coverage runs in its own Python 3.12 job and excludes live provider tests.
- A Codecov service failure remains best-effort (`fail_ci_if_error: false`), as
  in SimpleBroker; Codecov's project and patch status checks still enforce the
  configured thresholds when an upload succeeds.
- The upload action stays SHA-pinned and reads `CODECOV_TOKEN` only through the
  GitHub secret context.
- Do not copy SimpleBroker's shared `COVERAGE_FILE` subprocess setup. Under
  Backstitch's xdist and subprocess-heavy acceptance tests it causes concurrent
  SQLite writes and corrupt coverage data. Let pytest-cov aggregate xdist
  workers for the single test invocation instead.
- No production behavior, public CLI, package dependency, or release gate
  changes.

## Tasks

1. Add failing workflow/config/badge assertions to
   `tests/test_release_workflow.py` and confirm they fail.
2. Add `.codecov.yml`, coverage.py settings, the Python 3.12 CI coverage job,
   and the README badge plus local coverage command.
3. Run the focused tests and reproduce the CI coverage command locally,
   including `coverage.xml` generation.
4. Run the full repository gates and an independent review; reconcile findings.

## Verification

- `uv run pytest tests/test_release_workflow.py -q`
- `uv run coverage erase && uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm" --cov=backstitch --cov-report= && uv run coverage report --show-missing && uv run coverage xml`
- `uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm"`
- `uv run ruff check .`
- `uv run ruff format --check backstitch bin .github/scripts tests`
- `uv run mypy backstitch bin/release.py tests --config-file pyproject.toml`
- `uv run pytest tests/acceptance -q`
- `uv run backstitch check --repo-root .`
- `uv run backstitch check --repo-root . --show-suppressions`

## Rollout and Rollback

The first pushed run is the post-change signal: the coverage job must pass and
the Codecov upload must appear for `VanL/backstitch`. Roll back the coverage job,
config, and badge together if upload authentication or repository association
is wrong. The existing test matrix is independent and continues to gate CI.

## Deviation Log

No governing spec exists. Implementation deviations from this plan will be
recorded here.

## Execution Record

- Red gate: `uv run pytest tests/test_release_workflow.py -q` failed three
  assertions before implementation because the coverage job, policy, and badge
  did not exist.
- Focused gate: the same command passed 11 tests after implementation.
- Coverage gate: the exact CI command passed the hermetic suite, generated
  `coverage.xml`, and reported 88% total coverage (3,705 statements; 457
  missing).
- Full gates: hermetic pytest, the 18-test acceptance suite, Ruff lint and
  format, strict mypy, and both self-corpus invocations passed. Self-corpus
  reported zero errors, warnings, or infos; 155 existing suppressions remained
  visible with `--show-suppressions`.
- Independent review found no blocking correctness or security issue. It
  confirmed the xdist aggregation choice and SHA-pinned, least-privilege upload
  setup. Residual risk: matching SimpleBroker's `fail_ci_if_error: false` and
  `if_not_found: success` makes upload availability best-effort, and fork PRs do
  not receive `CODECOV_TOKEN`; those failures will not turn the CI job red.

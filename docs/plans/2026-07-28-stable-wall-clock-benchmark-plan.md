# Stable Wall-Clock Benchmark Plan

Plan type: implementation with spec revision.

Status: completed 2026-07-28.

Class: 3. This changes the CI and release acceptance meaning of the registered
`benchmark` lane. Product behavior, benchmark commands, and public CLI remain
unchanged.

## Goal

Replace single-shot 0.7-second and 3.0-second hard failures with stable serial
measurements: one warm-up, five measured runs, median reporting, a 20% relative
regression limit only on an exactly pinned runner and baseline, and loose
absolute ceilings that catch catastrophic regressions. Until both runner
identity and baseline are pinned, measurements are explicit and nonblocking.

## Source Documents

- `docs/specs/02-backstitch-core.md` [SC-10]
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-10]
- `docs/plans/2026-07-27-serial-benchmark-lane-plan.md`
- `docs/implementation/05-release-publishing.md`
- `README.md`

## Spec Baseline

- `02eeb8a` for `docs/specs/02-backstitch-core.md` and
  `docs/specs/07-verification-and-evidence-cases.md`.

## Context And Key Files

- `tests/performance/test_evidence_spike_wall_clock.py` currently runs each
  real command once and fails at 0.7 or 3.0 seconds.
- `tests/performance/semantic_scale.py` already owns the closed [EVC-10]
  runner-identity schema and unavailable-state vocabulary.
- The [EVC-10] contract pins `job_id = "semantic-scale"`, so the `benchmark`
  job cannot truthfully match that contract. Wall-clock qualification therefore
  needs its own contract instance using the same closed schema.
- `tests/performance/wall-clock-runner-contract.json` and
  `tests/performance/wall-clock-baseline.json` are intentionally absent, so
  current wall-clock qualification is unavailable.
- `.github/workflows/ci.yml` and `bin/release.py` route every `benchmark` test
  through the serial lane. Their commands do not change.

Comprehension gate: the serial lane is still required and command failures
remain fatal. Only unqualified latency comparisons become nonblocking.

## Invariants And Constraints

1. Keep the real subprocesses, self-corpus, CLI commands, serial CI job, and
   release command.
2. Run exactly one warm-up and five measured samples per command.
3. Report the measured samples and median even when qualification is
   unavailable.
4. Missing, invalid, unobserved, or mismatched runner identity, or a missing
   baseline, is unavailable rather than a latency failure.
5. A matching pinned runner and baseline fails when the median exceeds 120% of
   the baseline.
6. Command failure, timeout, malformed committed baseline, or a median above a
   loose catastrophic ceiling remains fatal.
7. Use 3.0 seconds for default check and 12.0 seconds for obligation list as
   catastrophic median ceilings. They are safety rails, not qualification
   baselines.
8. Add no benchmark dependency and do not change product runtime code.
9. Do not reuse the [EVC-10] `semantic-scale` contract instance across a
   different CI job. Reuse its exact identity schema and comparison rules.

## Proposed Spec Delta

In [SC-10], replace the wall-clock benchmark bullet with:

> wall-clock benchmark tests carry the registered `benchmark` marker. Normal
> xdist and coverage lanes explicitly select `not benchmark`; a dedicated
> serial lane runs every `benchmark` test without xdist. Each command receives
> one unmeasured warm-up and five measured runs. The result reports every
> sample and the median. A latency qualification is available only when the
> current runtime exactly matches the wall-clock runner contract, which uses
> the closed [EVC-10] identity schema, and a content-bound baseline exists; the
> median must not exceed 120% of that
> baseline. A missing baseline, a baseline bound to another contract, or a
> missing, invalid, unobserved, or mismatched runner identity reports
> `unavailable` without failing CI or release. Command failure, timeout,
> malformed committed baseline, or breach of the code-owned catastrophic
> median ceiling remains fatal. Unavailable qualification is a measured
> passing outcome, not a pytest skip; no benchmark failure may be converted
> into a skip. An ordinary serial local pytest run may include both normal and
> benchmark tests.

The wall-clock runner contract path is
`tests/performance/wall-clock-runner-contract.json`. An observed identity is
read from the test-harness-only
`BACKSTITCH_BENCHMARK_RUNNER_IDENTITY_PATH`. The baseline path is
`tests/performance/wall-clock-baseline.json`, with exactly:

```text
{
  schema_version: 1,
  runner_contract_sha256: lowercase SHA-256,
  measured_runs: 5,
  allowed_regression_fraction: 0.2,
  command_medians_seconds: {
    default-check: positive finite seconds,
    obligation-list: positive finite seconds
  }
}
```

No extra fields or command IDs are accepted. A baseline whose runner hash does
not match the current contract is unavailable. Add
`tests/performance/wall_clock.py` and `tests/test_wall_clock_benchmark.py` to
[SC-10]'s implementation mapping.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

No implementation deviation remains. The comprehension gate caught that the
existing [EVC-10] contract instance pins `job_id = "semantic-scale"` and cannot
qualify the `benchmark` job. The plan and proposed spec delta were corrected
before promotion to reuse the closed identity schema with a distinct wall-clock
contract instance.

## Dependency-Ordered Tasks

1. Add red tests for five-sample medians, unavailable qualification, exact
   20% comparison, catastrophic failure, and strict baseline parsing.
2. Add the test-only wall-clock policy helper and migrate the real benchmark
   to one warm-up plus five samples.
3. Promote the exact [SC-10] delta with reciprocal test backlinks.
4. Update README, release implementation guidance, changelog, and plan index.
5. Run targeted tests, the serial benchmark, live LLM, static gates,
   acceptance, self-corpus, and the non-live/non-benchmark suite.

Stop if implementation needs a product dependency, a new CI job, a changed
command, or a relaxed catastrophic ceiling.

## Testing Plan

Use real subprocesses for the benchmark commands. Pure policy tests may pass
literal samples and temporary runner/baseline files; do not mock pytest
selection, CI workflow text, the Backstitch CLI, or the self-corpus.

Required gates:

```bash
uv run pytest -q tests/test_wall_clock_benchmark.py
uv run pytest tests -q -n 0 -m benchmark
uv run pytest -q tests/test_release_workflow.py tests/test_release_script.py
uv run pytest -q -m "not live_llm and not benchmark"
uv run pytest -q -m live_llm
uv run pytest -q tests/acceptance
uv run ruff check .
uv run ruff format --check .
uv run mypy backstitch
uv run backstitch check --repo-root .
git diff --check
```

## Implementation Evidence

- Added the strict test-only sampling, baseline, and qualification policy in
  `tests/performance/wall_clock.py`; no product runtime module changed.
- Migrated both real subprocess benchmarks to one warm-up and five measured
  runs. Final local medians were 0.692 seconds for `default-check` and 0.716
  seconds for `obligation-list`; both reported qualification unavailable
  because the wall-clock runner contract is intentionally absent.
- `uv run pytest -q tests/test_wall_clock_benchmark.py
  tests/test_release_workflow.py tests/test_release_script.py`: passed.
- `uv run pytest tests -q -n 0 -m benchmark`: passed, two measured outcomes,
  no skips.
- `uv run pytest -q -m "not live_llm and not benchmark"`: passed.
- `uv run pytest -q -m live_llm`: passed with the configured live provider.
- `uv run pytest -q tests/acceptance`: passed.
- `uv run ruff check .` and `uv run ruff format --check .`: passed.
- `uv run mypy backstitch bin/release.py tests --config-file pyproject.toml`:
  passed across 124 source files.
- `uv run backstitch check --repo-root . --show-suppressions`: exit 0, 120
  sections, 272 mappings, 357 code refs, 745 edges, zero errors, warnings, or
  infos; 206 configured suppressions remained auditable.
- `git diff --check`: passed.
- Independent `claude -p` review found one P2 and three P3 issues. Firing tests
  were added for every baseline-schema and measurement guard, exact `0.2`
  comparison replaced tolerance, terminal reporting gained a fallback, and the
  no-skip guarantee was restored. Focused rereview returned `VERDICT: PASS`
  with no P1/P2 findings.

## Rollout And Rollback

Land policy helper, benchmark migration, spec, docs, and tests together.
Rollback restores the single-shot assertions and prior [SC-10] text; CI job
topology and release commands need no rollback.

## Out Of Scope

- pinning a runner or publishing the first baseline;
- changing benchmark commands or optimizing product code;
- adding a benchmark framework;
- changing semantic-scale qualification;
- changing live-provider policy.

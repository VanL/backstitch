# Serial Benchmark Lane Plan

Status: completed; independent plan and completed-work reviews PASS.

Plan type: implementation with spec revision.

Class: 5+P. The change revises normative [SC-10] text and materially changes
how future work is verified. Hardening: N/A because no [DOM-5] risky trigger
fires.

## Goal

Keep ordinary hermetic and coverage tests parallel under xdist while running
non-portable wall-clock benchmarks in a separate serial lane. Preserve the
existing 0.7-second and 3.0-second budgets; do not hide failures by raising
thresholds or skipping the benchmark lane.

## Source Documents

- `docs/specs/02-backstitch-core.md` [SC-10]
- `docs/plans/2026-07-16-evidence-spike-hardening-plan.md`, especially its
  non-normative wall-clock testing and verification sections
- `docs/agent-context/runbooks/testing-patterns.md`
- User direction in this task: use a `benchmark` mark and run normal tests as
  `not benchmark`

## Spec Baseline

- Git baseline: `66c84d83f8934cdd869b97ab23e28670d95773c7`.
- `docs/specs/02-backstitch-core.md` is active uncommitted worktree content at
  SHA-256
  `15d81d769bed61b7feb5e73c3ac20ff413f62d4c3dd298c4bcd114aa2ec75444`.
- This plan revises [SC-10]. Promotion uses Strategy B so the requirement,
  mappings, reciprocal backlinks, marker registration, workflow, and firing
  workflow tests enter the worktree atomically after plan review.
- Promotion baseline: Git diff base
  `66c84d83f8934cdd869b97ab23e28670d95773c7` plus the current worktree;
  promoted `docs/specs/02-backstitch-core.md` SHA-256
  `0235877341f0e2aac302527fa7606ae4f4b5abe1a053577afeb8ef44c82871c5`.

## Proposed Spec Delta

Promotion strategy: B, atomic.

In `docs/specs/02-backstitch-core.md` [SC-10], insert after the live-policy
test bullet:

> wall-clock benchmark tests carry the registered `benchmark` marker. Normal
> xdist and coverage lanes explicitly select `not benchmark`; a dedicated
> serial lane runs every `benchmark` test without xdist. The serial lane may
> not convert failures into skips. An ordinary serial local pytest run may
> include both normal and benchmark tests.

Add these [SC-10] implementation mappings:

- `tests/performance/test_evidence_spike_wall_clock.py`
- `tests/test_release_script.py`
- `tests/test_release_workflow.py`

Add reciprocal [SC-10] module backlinks to all three mapped test owners. Add
this plan under the spec's `## Related Plans`. `bin/` is outside configured
`code_roots`, so the release helper is contract input owned by its mapped
firing test rather than a separately parsed implementation owner.

## Context and Key Files

- `tests/performance/test_evidence_spike_wall_clock.py` owns the two real
  subprocess wall-clock assertions and already carries the broader
  `performance` marker.
- `pyproject.toml` owns strict marker registration.
- `.github/workflows/ci.yml` currently runs every non-live test under
  `-n auto`, which makes a wall-clock assertion depend on unrelated worker
  load. Its coverage job repeats the same coupling.
- `bin/release.py::build_precheck_commands` owns the local release precheck
  inventory and currently repeats the old parallel selector.
- `tests/test_release_workflow.py` is the existing static contract owner for
  CI test selection and coverage.
- `tests/test_release_script.py` pins the release-helper command inventory.
- `tests/test_pytest_policy.py` owns repository pytest policy truth tables.
- `README.md` documents local normal, benchmark, live, and coverage commands.
- `docs/implementation/05-release-publishing.md` owns the release verification
  command inventory.

## Invariants and Constraints

1. The benchmark thresholds remain exactly 0.7 and 3.0 seconds.
2. The benchmark subprocesses, repository files, and Backstitch CLI stay real.
3. Every benchmark collected by pytest runs in the serial CI step.
4. Normal and coverage xdist steps exclude every test marked `benchmark`.
5. The existing `performance` marker remains valid for compatibility.
6. Live-provider policy, coverage settings, static checks, and Backstitch
   self-check do not change.
7. No dependency, product behavior, public CLI, or release authority changes.

## Tasks

1. Promote and implement one atomic Strategy-B slice.
   - Add the exact [SC-10] text, mappings, plan backlink, and reciprocal test
     backlinks.
   - Register `benchmark`; apply it to the wall-clock test while retaining
     `performance`.
   - In the `test` matrix and `coverage` job, select
     `not live_llm and not benchmark`.
   - Add one standalone `benchmark` job on `ubuntu-latest` with Python 3.12.
     It checks out the repository, installs the locked dev environment, and
     runs `uv run pytest tests -q -n 0 -m benchmark` with xdist explicitly
     disabled and without `--dist`.
     Its job result is the CI acceptance signal for the benchmark lane.
   - Strengthen workflow contract tests to prove marker registration, both
     normal-lane exclusions, exact standalone command, and absence of xdist
     flags from the benchmark job.
   - Add an exact serial benchmark command to
     `bin/release.py::build_precheck_commands`; map/backlink
     `tests/test_release_script.py` to [SC-10] and pin both exact normal and
     serial command tuples there.
   - Update `README.md` and
     `docs/implementation/05-release-publishing.md` with the split commands.
   - Stop if any threshold, product behavior, live policy, coverage target, or
     release authority must change.
   - Record the post-promotion worktree hashes as the promotion baseline.
2. Run mutating Ruff commands first, then targeted red-green proof, read-only
   static/runtime gates, the split CI lanes, the explicitly requested
   live-provider full suite, acceptance, and both Backstitch self-corpus forms.
3. Run independent completed-work review and disposition every finding.

## Testing Plan

Before implementation, the current CI command has already reproduced the
problem: the default-check benchmark took 1.007 seconds under local
48-worker contention while the full serial suite and the isolated benchmark
directory passed. The post-change proof keeps the real benchmark process and
assertion unchanged. Static workflow tests inspect the actual workflow text;
they do not mock pytest or xdist.

## Verification and Gates

```text
uv run ruff check --fix .
uv run ruff format backstitch bin .github/scripts tests
uv run ruff check .
uv run ruff format --check backstitch bin .github/scripts tests
uv run mypy backstitch bin/release.py tests --config-file pyproject.toml
uv run pytest tests/test_release_workflow.py tests/test_pytest_policy.py -q
uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm and not benchmark"
uv run pytest tests -q -n 0 -m benchmark
uv run pytest tests -q
uv run pytest tests/acceptance -q
uv run backstitch check --repo-root .
uv run backstitch check --repo-root . --show-suppressions
```

Success means every command exits zero, the serial benchmark lane collects
both current wall-clock cases, and the self-corpus report has zero errors and
warnings. The unfiltered `uv run pytest tests -q` command intentionally
requires the configured live-provider credential because the user explicitly
requested all tests including the live contract; it is not described as
hermetic and does not replace the split CI proof.

## Independent Review Loop

A separate Codex review agent receives [SC-10], this plan, the evidence-spike
plan's benchmark policy, and the proposed touched files. It reviews the plan
before promotion and the completed diff before closure. Each finding is
accepted and fixed or rejected with recorded reasoning.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [SC-10] | CI and documentation consumers use the split normal/benchmark lanes | The first promoted slice missed `bin/release.py::build_precheck_commands`, which independently owns the release precheck list | A post-promotion consumer search found the stale selector before closure | Add the serial benchmark release command and map/backlink its parsed firing-test owner, `tests/test_release_script.py`, in the completion correction |

## Out of Scope

- changing benchmark thresholds or implementation performance
- changing xdist worker counts
- adding benchmark dependencies or a benchmark framework
- changing live-provider execution, coverage targets, or product behavior

## Fresh-Eyes Review

Read the workflow as a new contributor: normal parallel tests must visibly
exclude benchmarks, the serial step must visibly select them, and no benchmark
may disappear through a skip or deselection gap.

## Review Record

Round 1 returned BLOCKED with seven findings. All were accepted:

1. mutating Ruff commands now precede all read-only evidence;
2. the unfiltered suite now declares its live-provider prerequisite;
3. promotion and implementation are one atomic Strategy-B slice;
4. the benchmark topology is one standalone Python 3.12 job on an isolated
   runner with an exact serial command and job-success signal;
5. numeric thresholds remain non-normative outside [SC-10];
6. the class is corrected from 3+P to 5+P; and
7. README and release implementation commands are included.

Round 2 verified only those seven corrections and returned PASS with no new
defect.

Completion-revision trigger: a post-promotion search for `not live_llm` found
the release helper's independently executable precheck list. The plan now adds
that owner and its firing test; this bounded ownership/blast-radius revision
requires focused review before the correction is implemented.

Focused review round 1 accepted the serial release precheck but rejected a
direct mapping to `bin/release.py`: `bin/` is outside configured `code_roots`.
The corrected traceability owner is `tests/test_release_script.py`, which pins
the exact command inventory and is inside the parsed test roots.

Focused review round 2 verified that correction and returned PASS with no new
defect.

The completed-work review found two blockers. Both were accepted:

1. every serial benchmark command now carries `-n 0`, and a subprocess firing
   test proves that ambient `PYTEST_ADDOPTS=-n auto` cannot create a worker;
2. the promoted-spec hash above now identifies the post-correction [SC-10]
   worktree bytes.

Round-2 completed-work review returned PASS. Final evidence:

- targeted release/workflow/pytest-policy tests: 82 passed;
- normal xdist lane with `not live_llm and not benchmark`: passed;
- serial benchmark lane, including ambient `PYTEST_ADDOPTS=-n auto`: 2 passed;
- coverage lane: passed, 87% total;
- acceptance probes: 41 passed;
- mypy: 122 source files, zero issues;
- Ruff lint and format: clean across the configured CI paths; and
- both Backstitch self-corpus forms: exit 0 with zero errors, warnings, or
  infos; suppressions remained auditable.

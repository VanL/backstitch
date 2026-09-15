# CI Workflow And Qwen Qualification Plan (2026-09-15)

Status: active

Class: 3. This work repairs repository verification, reconciles its plan-status
ledger, and seeks external model evidence. It does not change a product spec or
public CLI contract.

## Goal

Restore green main CI, make both trusted semantic workflows valid GitHub
Actions workflows, correct every status-index row whose completion is proved by
landed commits and current evidence, and obtain the strongest honest semantic
quality evidence that the existing reviewed Qwen evaluation path supports.

## Source Documents And Baseline

- Baseline: `e628c27`.
- `docs/specs/02-backstitch-core.md` [SC-7], [SC-10], [SC-13].
- `docs/specs/06-semantic-gates.md` [SEM-8], [SEM-9].
- `docs/implementation/07-deterministic-semantic-gate.md`.
- `docs/plans/2026-07-11-deterministic-semantic-gate-plan.md`.
- `docs/plans/2026-09-14-v0-4-0-release-readiness-plan.md`.
- `tests/semantic_eval/v3/README.md` and
  `tests/semantic_eval/v3/qualification-candidate/README.md` own the limits of
  the current evaluation corpora.

No spec delta is planned. If formal Qwen qualification requires changing gold,
thresholds, or the semantic contract, stop and open a reviewed spec-changing
plan rather than hiding that decision in workflow YAML.

## Current Structure And Findings

- `tests/test_semantic_application.py` compares reports from two real analyses
  byte-for-byte. Both reports correctly contain a measured
  `elapsed_milliseconds`, so Linux CI observed `1` versus `0` and failed. The
  stable CLI/application fields should remain equal; each timing value should
  be validated independently.
- Both trusted semantic workflows put `${{ runner.temp }}` in job-level `env`.
  GitHub does not allow the `runner` context there, rejects each workflow at
  validation time, and creates zero jobs. The shell already exposes trusted
  `RUNNER_TEMP`; one early step can publish the same path through `GITHUB_ENV`.
- The plan index contains stale landing qualifiers. A read-only audit found
  eleven rows with completion proved by main-ancestor commits. Three plans
  remain genuinely active and native Windows remains deferred.
- The Qwen live lane proves integration, not quality. The full candidate corpus
  is not qualification-ready: its provenance is synthetic, five expected labels
  conflict with the current prompt contract, and its two-trial call count does
  not fit GitHub's current workflow/runtime bounds. The two-case v3 smoke corpus
  is explicitly non-authoritative.

## Invariants And Constraints

- Keep `elapsed_milliseconds` in the public report. Do not freeze or falsify a
  production clock merely to make two runs byte-identical.
- Preserve semantic workflow triggers, permissions, trusted-tool/hostile-target
  separation, artifact-only output, CLI arguments, cache boundaries, and
  fail-closed enforcement. Add no Actions dependency or general workflow
  validator for these two exact grammar defects.
- Status changes require landed commit or current remote evidence. Do not mark
  the deterministic semantic gate, intent-coverage rollout, release-readiness,
  or native Windows exploration complete.
- Do not call a smoke run or synthetic blocked corpus a formal model
  qualification. Do not silently rewrite corpus gold or raise timeouts.
- Each implementation slice gets one targeted commit. Qwen evidence is recorded
  separately from code changes.

## Deviation Log

| Baseline | Planned behavior | Actual behavior | Rationale |
|---|---|---|---|

## Tasks And Commits

### Slice 0: Land the execution plan

Commit this dated plan and its active index row before implementation. The plan
commit contains no product, workflow, or status-claim change.

### Slice 1: Stable report-parity proof

Change the existing CLI/application parity test to decode both JSON reports,
remove only `elapsed_milliseconds` for the equality comparison, and assert both
removed values are nonnegative integers. Keep the real CLI and analysis path.
Run the test repeatedly, its module, coverage-relevant tests, and self-corpus.
Commit only this test correction.

### Slice 2: Valid trusted semantic workflows

Add failing assertions for each workflow that reject `${{ runner.temp }}` in
job-level environment and require an early, input-independent step exporting
the exact `${RUNNER_TEMP}` report root through `${GITHUB_ENV}` before first use.
Then remove the invalid job-level value and add those steps. Keep every analysis
and publication argument unchanged. Run focused workflow tests, land the slice
on the default branch, and send each exact `repository_dispatch` event. Success
requires each resulting run to create its named job and execute the repaired
revision. A deliberately invalid PR identity may prove parser/job creation when
no real open PR exists, but its expected runtime rejection is not workflow
success. Commit only this repair and its tests.

### Slice 3: Plan-index reconciliation

Update these eleven audit-proved rows to the literal `completed` vocabulary:

- `2026-07-14-agent-guidance-propagation-plan.md` (`9ddb4d6`, then `ecda702`)
- `2026-07-15-agent-guided-evidence-cases-plan.md` (`59a6d18`, `b697b3d`,
  `4659c6b`)
- `2026-07-16-evidence-spike-hardening-plan.md` (same integrated commits)
- `2026-07-17-agent-guidance-delta-wave-propagation-plan.md` (`2a6cc20`, then
  `66c84d8`)
- `2026-07-27-semantic-analysis-lifecycle-plan.md` (`5c2eb43` plus the
  integrated semantic commits)
- `2026-07-27-canonical-config-resolution-plan.md` (integrated semantic
  commits)
- `2026-07-28-documented-suppression-governance-plan.md` (`ccf16f4`,
  `b2a736e`, `b33804a`)
- `2026-07-28-agent-guidance-delta-wave-propagation-plan.md` (`78a6e83`, then
  `9219d24`)
- `2026-08-23-gpt-5-6-luna-responses-plan.md` (`6adf7aa` and descendant
  cross-platform CI run `35006509257`)
- `2026-07-28-configured-default-command-plan.md` (`531d115`)
- `2026-07-28-evidence-stable-semantic-result-reuse-plan.md` (`531d115`)

Preserve the deterministic semantic gate, intent-coverage rollout, and release
readiness as active; preserve native Windows as deferred. Update stale headers
only when the same evidence proves them false; do not edit historical execution
evidence. Run documentation path, DOM-15, self-corpus, and coalescing checks.
Commit only status reconciliation.

### Slice 4: Qwen semantic-quality evidence

Formal qualification is blocked at plan time: the candidate corpus lacks
historical provenance, five gold labels conflict with the current prompt, and
the measured Qwen call rate exceeds the current runtime bounds. This slice is
therefore a qualification assessment, not a formal qualification claim.

The slice must still run one bounded, contract-compatible real-Qwen evaluation
against the existing v3 clean/mutated smoke pair, with one trial and verifier
disabled if the current evaluator supports those settings without a contract
change. Use the production evaluator and local endpoint; do not mock responses.
Publish the canonical report and attempt its zero-call replay through the
existing validator. Record detection, negative-control outcome, validity,
runtime, and replay result as exploratory evidence only. If even this pair
cannot run without changing gold, thresholds, or evaluator semantics, record
the exact executable blocker and stop rather than substituting a hand-written
prompt.

Formal qualification later requires a reviewed corpus whose gold matches the
current contract, declared thresholds, all critical positives detected,
negative controls preserved, and byte-identical zero-call replay. Do not silently
rewrite corpus gold or raise timeouts to manufacture that claim.

## Verification

```bash
uv run pytest tests/test_semantic_application.py -q
uv run pytest tests/test_release_workflow.py -q
uv run pytest tests -q -m "not live_llm"
uv run pytest tests/acceptance -q
uv run ruff format --check backstitch bin .github/scripts tests
uv run ruff check .
uv run mypy backstitch bin/release.py tests --config-file pyproject.toml
python bin/check-doc-paths
python bin/check-dom15-fixtures
bin/coalesce-check
uv run backstitch check --repo-root .
```

Hosted verification uses exact-SHA `CI`, `local-llm`, and non-zero-job runs for
both trusted semantic workflows. Qwen quality evidence uses the evaluator's
canonical JSON report and replay validator, not workflow success alone.

## Rollback And Stop Conditions

Each slice is independently revertible before release. Stop if a workflow fix
changes trigger or trust boundaries, if status evidence is ambiguous, or if
Qwen qualification would require relabeling gold, inventing thresholds, or
raising runtime limits without a reviewed contract decision. No tag or release
is part of this plan.

## Independent Review

Review the plan before implementation and each completed slice for correctness,
YAGNI, CLI reachability, and evidence honesty. The final review must reject any
new framework, duplicated provider path, or claim that integration success is
semantic qualification.

## Execution Log

- Plan authored against `e628c27`. Read-only diagnosis reproduced the CI timing
  delta from run `35012430405` and the two zero-job workflow failures from runs
  `35012428036` and `35012429105`.
- Independent plan review returned `REVISE`: correct hosted dispatch semantics,
  make the real-Qwen probe mandatory, enumerate all status targets, and land the
  plan before implementation. All four corrections were applied.
- Slice 1 preserves the real CLI/application comparison while excluding only
  their independently measured elapsed values. Both reports must still contain
  a nonnegative integer duration; every stable report field remains equal.
- Slice 1 review rejected decoded-object equality because it would weaken byte
  parity for key order, separators, and the final newline. The corrected test
  masks only the validated serialized duration integer, then compares the
  original byte streams exactly. Rereview is required.
- Slice 1 rereview passed. Slice 2's focused tests failed first on the exact
  invalid job-level `${{ runner.temp }}` expressions in both workflows. The
  correction moves only report-root initialization to an early trusted-shell
  step using `${RUNNER_TEMP}` and `${GITHUB_ENV}`.
- Slice 2 review passed. After landing `9e912b3`, repository dispatch runs
  `35016457399` and `35016456007` each created and began their named job,
  proving the former zero-job workflow validation failures are corrected.
- Slice 3 reconciled exactly the eleven audit-proved rows listed above. The
  three genuinely active product/release plans and deferred native Windows
  exploration remain open.
- Slice 3 review confirmed the eleven completion decisions but rejected two
  vague landing citations. Both lifecycle/config rows now cite the exact
  integrated commits `59a6d18`, `b697b3d`, and `4659c6b`.

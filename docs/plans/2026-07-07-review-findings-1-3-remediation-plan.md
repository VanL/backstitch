# Review Findings 1-3 Remediation

Status: implemented in working tree (2026-07-07), not committed.
Plan type: implementation bug fix, no spec revision expected.
Risk level: moderate. This touches suppression warnings and deterministic
artifact validation, which are public contracts. The hardening-plan checklist
applies.

## Goal

Fix the first three findings from the 2026-07-07 project review:
context-dependent error suppressions from config must be auditable, deterministic
report summary validation must be total at the loader boundary, and known config
tables with scalar values must report type errors instead of unknown-key errors.

## Source Documents

- `docs/specs/02-backstitch-core.md` [SC-5], [SC-6], [SC-13]
- `docs/specs/03-backstitch-configuration.md` [CFG-8]
- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-6], [EXC-8],
  [EXC-9]
- `docs/implementation/04-backstitch-style-traceability.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- Review evidence from 2026-07-07:
  - config suppression of `SPEC_SECTION_AMBIGUOUS` remained an error but
    produced no ignored-suppression warning when `warn_unused_ignores = false`
  - `load_deterministic_report()` accepted a report whose `summary` omitted
    `spec_sections`, `code_refs`, and `spec_mappings`
  - `check = "json"` reported `unknown config key 'check'` instead of
    `[check] must be a table`

## Spec Baseline

- Code baseline at plan authoring: `df320ab` (`Harden catalog/doctor plan
  through codex rounds 2-3 to a yes verdict`) plus the current dirty worktree.
- Relevant spec files are already modified in the worktree:
  `docs/specs/02-backstitch-core.md`,
  `docs/specs/03-backstitch-configuration.md`, and
  `docs/specs/04-backstitch-traceability-exclusions.md`.
- No spec delta is planned. If implementation shows that any finding is
  intentionally allowed by the active spec text, stop and add a deviation row
  before changing behavior.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Current Context And Key Files

Read these first, in order:

1. `backstitch/exclusions.py`
   - `should_suppress()` currently returns before matching config rules when
     `issue.severity == "error"`.
   - `validate_lint_codes()` warns only for codes in `ERROR_SEVERITY_CODES`,
     which excludes context-dependent codes such as `SPEC_SECTION_AMBIGUOUS`.
   - `_warn_error_code_suppression()` currently checks inline ignore code sets
     only, so config attempts can be silent.
   - `SuppressionIndex.record_config_usage()` feeds stale-ignore reporting.
2. `backstitch/artifact_contracts.py`
   - `load_deterministic_report()` is the deterministic report trust-boundary
     loader.
   - `_validate_issues_and_summary()` validates issue records and compares
     count disagreement, but only for summary values that are already valid
     non-negative integers.
3. `backstitch/analysis_results.py`
   - `render_analysis_summary()` defensively validates the same six summary
     count keys. Keep that defense; do not move the only validation back into
     the renderer.
4. `backstitch/settings.py`
   - `_unknown_key_messages()` runs before `_expect_table()`.
   - `_TABLE_KEYS` lists known table names, but scalar values currently fall
     through to an unknown-key diagnostic for non-`profile` tables.
5. Tests:
   - `tests/test_exclusions.py`
   - `tests/test_artifact_contracts.py`
   - `tests/test_settings.py`
   - `tests/test_review_remediation.py` if a CLI-level regression is clearer
     than a pure unit test

Comprehension checks before editing:

1. Why does a context-dependent code need per-instance handling? Because
   [SC-11] lets codes such as `SPEC_SECTION_AMBIGUOUS` be errors in one
   context and warnings in another; suppression must gate on
   `issue.severity`, not code-set membership alone.
2. Why keep `render_analysis_summary()` validation after tightening
   `load_deterministic_report()`? It is a defensive consumer check and protects
   future callers that pass summary mappings directly.
3. Why should scalar known-table keys skip unknown-key reporting? Because
   [CFG-8] treats unknown keys and wrong value types as different strictness
   failures; a known key with the wrong type should reach the type validator.

## Invariants And Constraints

- Error-severity findings remain non-suppressible. This plan adds missing
  observability for ignored attempts; it must not allow any error finding to
  move into `suppressed_issues`.
- A matching config suppression for a context-dependent error instance should
  produce an error-severity ignored-suppression warning even when
  `warn_unused_ignores = false`. `warn_unused_ignores` controls stale real
  suppressions, not invalid error-suppression attempts.
- A matching ignored error-suppression rule should count as matched for stale
  config accounting. The user should get the error-severity warning, not an
  additional stale-rule warning for the same match.
- Always-error codes in config should keep their existing load-time warnings.
  Do not remove or weaken `_warn_inline_error_code_attempts()` or
  `validate_lint_codes()`.
- Deterministic report summary validation must reject missing, bool, non-int,
  and negative values for all six count keys:
  `spec_sections`, `code_refs`, `spec_mappings`, `errors`, `warnings`, and
  `infos`.
- Summary count disagreement must still be checked after shape/type validation.
- CLI exit-code behavior must stay aligned with [SC-5]: malformed inputs and
  config errors exit `2`; target-repository findings exit `1`; clean runs exit
  `0`.
- No new dependency.
- No broad refactor. Keep edits local to the three findings and their tests.
- No work on the fourth review finding (`markdown-it-py`) in this plan.

## Tasks

1. Add failing tests for the three findings.
  - In `tests/test_exclusions.py`, cover both config `per-file-ignores` and
    `per-section-ignores` rules for a context-dependent code whose emitted
    issue has `severity="error"`. Assert `should_suppress()` returns
    `(False, None)`, records the matching config rule as used, and appends a
    warning naming the code.
   - Add a CLI-level fixture if the unit test does not prove that the warning
     reaches stderr when `warn_unused_ignores = false`.
   - In `tests/test_artifact_contracts.py`, assert
     `load_deterministic_report()` rejects summary count keys that are missing,
     bool, non-int, or negative. Keep the existing disagreement test.
   - In `tests/test_settings.py`, parameterize representative known table keys
     (`check`, `packets`, `analyze`, `target_roots`, `lint`) with scalar values
     and assert the message says the table must be a table, not unknown key.
     Leave `profile = "..."` on its existing special diagnostic path.

2. Fix suppression warning behavior.
   - Refactor `should_suppress()` so it resolves `spec_file`, `section_id`, and
     `code_file` before the non-suppressible early return.
   - Add a small helper that detects matching config suppression attempts for
     the current issue without suppressing it.
  - For `issue.severity == "error"`, warn when a matching config rule names
    the issue code and record that config rule as used. Pin the warning text in
    tests; the existing inline text is `suppression ignored for error-severity
    code ...`, and config warnings may reuse that prefix while adding rule
    location. Preserve existing inline warning behavior for context-dependent
    error instances.
   - Keep the returned suppression result `(False, None)` for every error
     instance.

3. Tighten deterministic report summary validation.
   - Add a single summary-count validation step inside
     `_validate_issues_and_summary()` before count disagreement comparison.
   - Reject missing keys and bad values with one-line `ValueError` messages
     that name the bad key or keys.
   - Keep `render_analysis_summary()` checks in place as consumer-side
     defense.

4. Fix known-table scalar diagnostics.
   - Change `_unknown_key_messages()` so keys in `_TABLE_KEYS` are known even
     when their value is not a dict. If the value is a dict, keep nested
     unknown-key inspection. If not, let `_expect_table()` or the existing
     `profile` special case produce the type-specific error.
   - Verify `allow_unknown_keys = true` still downgrades unknown keys but does
     not downgrade type errors on known keys.

5. Documentation alignment.
   - No spec text change is expected. If behavior or wording must change,
     update the relevant spec and this plan's Deviation Log in the same slice.
   - Update implementation docs only if the final implementation changes the
     documented suppression or validation model.

6. Independent review.
   - Before implementation starts, run an independent review of this plan.
   - After tests and code pass locally, run an independent review of the diff.
   - Incorporate findings or record why they are not applicable in this plan.

## Testing Plan

Use real `Issue`, `LintSettings`, `SuppressionIndex`, TOML loading, and JSON
report fixtures. Do not mock the suppression engine, config parser, or artifact
loader; those are the contract boundaries under test.

Minimum targeted tests:

- `uv run pytest tests/test_exclusions.py -q`
- `uv run pytest tests/test_artifact_contracts.py -q`
- `uv run pytest tests/test_settings.py -q`

Full verification:

- `uv run pytest tests -q -m "not live_llm"`
- `uv run pytest tests/acceptance -q`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy backstitch bin/release.py --config-file pyproject.toml`
- `uv run backstitch check --repo-root .`
- `uv run backstitch check --repo-root . --show-suppressions`

Manual repros to keep in the completion notes:

- A temp repo with duplicate `[AMB-1]`, `pkg/mod.py` citing `[AMB-1]`, and
  `lint.per-file-ignores` for `SPEC_SECTION_AMBIGUOUS` should exit `1`, keep
  the error visible, and print an ignored error-suppression warning even when
  `warn_unused_ignores = false`.
- A matching `lint.per-section-ignores` rule for the same context-dependent
  error class should behave the same way.
- A deterministic report missing any of the six `summary` count keys should be
  rejected by `load_deterministic_report()`.
- `check = "json"` should exit `2` with a table-type error.

## Rollout And Rollback

Rollout is a normal code/test/docs change. There is no data migration, state
change, or compatibility sequence.

Rollback is a plain revert of the implementation and tests from this plan.
Because no output schema or CLI flag changes are planned, rollback does not
need a compatibility shim.

## Stop Gates

- Stop if the fix would make any error-severity issue suppressible.
- Stop if fixing summary validation requires changing the deterministic JSON
  report schema instead of enforcing the existing six count keys.
- Stop if config scalar diagnostics require weakening unknown-key strictness.
- Stop if a new dependency seems useful.
- Stop if a spec change becomes necessary but has not been recorded in the
  Deviation Log.

## Out Of Scope

- Removing the unused `markdown-it-py` dependency from the fourth review
  finding.
- Redesigning suppression precedence.
- Changing issue severities or issue-code vocabulary.
- Changing `backstitch check` output schema.
- Broad config parser cleanup beyond the known-table scalar diagnostic.

## Completion Gate

Completion requires:

- findings 1-3 fixed with firing tests
- all verification commands above recorded with observed results
- `uv run backstitch check --repo-root .` exits `0` with zero errors and zero
  warnings
- independent diff review run and answered
- changed files and residual risks listed in the final implementation note

## Implementation Notes

Implemented 2026-07-07 in the working tree.

- `backstitch/exclusions.py`: config ignore matching now runs before the
  non-suppressible error early return. Matching config attempts are recorded as
  used and context-dependent error attempts emit an ignored-suppression warning
  while the finding remains unsuppressed.
- `backstitch/artifact_contracts.py`: deterministic report summary validation
  now rejects missing, bool, non-int, and negative values for all six count
  keys before checking count disagreement.
- `backstitch/settings.py`: `_unknown_key_messages()` now treats `_TABLE_KEYS`
  members as known regardless of value type, letting `_expect_table()` produce
  type-specific diagnostics for scalar known tables.
- Tests added in `tests/test_exclusions.py`, `tests/test_artifact_contracts.py`,
  and `tests/test_settings.py`.

## Verification Results

Passing commands from the implementation run:

- `uv run pytest tests/test_exclusions.py tests/test_artifact_contracts.py tests/test_settings.py -q`
- `uv run pytest tests -q -m "not live_llm"`
- `uv run pytest tests/acceptance -q`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy backstitch bin/release.py --config-file pyproject.toml`
- `uv run backstitch check --repo-root .`
- `uv run backstitch check --repo-root . --show-suppressions`

Manual repros:

- `SPEC_SECTION_AMBIGUOUS` with matching `lint.per-file-ignores` exits `1`,
  leaves the ambiguity error visible, and prints
  `suppression ignored for error-severity code SPEC_SECTION_AMBIGUOUS ...`
  even with `warn_unused_ignores = false`.
- `MAPPING_PATH_MISSING` with matching `lint.per-section-ignores` exits `1`,
  leaves the missing-path error visible, and prints
  `suppression ignored for error-severity code MAPPING_PATH_MISSING ...`.
- A deterministic report missing summary count keys is rejected by
  `load_deterministic_report()`.
- `check = "json"` exits `2` with `[check] must be a table`.

One full pytest run failed while unrelated workflow files were changing in the
dirty worktree; the isolated failing release-workflow test passed immediately
afterward, and the full suite passed on rerun.

## Independent Review Results

- Pre-implementation plan review: no blockers. The reviewer requested adding
  `per-section-ignores` coverage for context-dependent error attempts; this was
  incorporated before code changes.
- Post-implementation diff review: no regressions found. Non-blocking notes:
  matching always-error config rules now count as used, which is intentional per
  the plan invariant; repeated matching context-dependent errors can produce
  repeated ignored-suppression warnings, matching existing inline-warning
  behavior.

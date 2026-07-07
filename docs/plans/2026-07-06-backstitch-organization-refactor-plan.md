# Backstitch Organization Refactor Plan

Status: implemented in the working tree, pending user review/commit. Core
verification passed; requested `/claude challenge` review is blocked by missing
Claude authentication.

## Goal

Refactor Backstitch's internal organization to adopt the useful parts of
SimpleBroker's structure: a thin CLI parser/dispatcher, deeper command-support
modules, explicit artifact-contract validation modules, and tighter enumerable
contract inventories. This is a no-behavior-change refactor. The goal is better
locality for maintainers and better leverage for tests, without creating a new
public API or a speculative plugin system.

## Source Documents

Source specs:

- `docs/specs/02-backstitch-core.md` [SC-5], [SC-6], [SC-7], [SC-8], [SC-10],
  [SC-11], [SC-13]
- `docs/specs/03-backstitch-configuration.md` [CFG-5], [CFG-8], [CFG-9],
  [CFG-10]
- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-6], [EXC-7],
  [EXC-8], [EXC-9], [EXC-10]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11]

Implementation docs and runbooks:

- `docs/implementation/02-repository-map.md`
- `docs/implementation/04-backstitch-style-traceability.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`

Reference comparison:

- `/Users/van/Developer/simplebroker/simplebroker/_constants.py`
- `/Users/van/Developer/simplebroker/simplebroker/cli.py`
- `/Users/van/Developer/simplebroker/simplebroker/commands.py`
- `/Users/van/Developer/simplebroker/tests/test_constants.py`
- `/Users/van/Developer/simplebroker/tests/test_public_surface.py`

## Spec Baseline

- `cc1e41c420e330b39e1c67479ca951358164d427` at plan authoring time.
- Plan type: implementation refactor with documentation and implementation
  mapping updates. No intended behavior change.
- Proposed Spec Delta: none at authoring. If implementation discovers a needed
  behavior, CLI, config, report, packet, or public-surface change, stop and
  revise this plan with a `## Proposed Spec Delta`, independent review, and a
  spec-promotion slice before code proceeds.

## Baseline Verification

Current baseline command:

```bash
uv run backstitch check --repo-root . --show-suppressions
```

Observed at plan authoring: exit `0`; `0` errors; `0` warnings; `46` infos;
`140` suppressed findings. This is the traceability floor the refactor must
preserve. Infos are existing unmapped inventory and proposed-invariant debt; do
not treat them as new regressions unless the histogram or locations change in
ways caused by the refactor.

Observed at implementation start: exit `0`; `0` errors; `0` warnings; `46`
infos; `140` suppressed findings.

## Context And Key Files

Current ownership:

- `backstitch/cli.py` owns parser construction, global/per-command config flag
  merging, command dispatch, `check`, `packets`, `analyze`,
  `summarize-analysis`, `config`, packet loading, deterministic report
  validation, suppression application, rendering, output writes, and exit-code
  mapping.
- `backstitch/analysis_results.py` already acts as a deeper module for semantic
  result-row validation and summary rendering.
- `backstitch/analysis_packets.py` owns packet generation and prompt packet
  rendering. It must never import or call `llm`.
- `backstitch/analysis_llm.py` owns the lazy `llm` adapter and model-output
  containment. Importing this module is acceptable only in semantic-analysis
  paths; importing `llm` itself remains confined to `default_adapter`.
- `backstitch/resolver.py` owns pure graph resolution plus repository scanning.
  Suppression must not move into this module.
- `backstitch/exclusions.py` owns suppression rules and suppression-index
  construction. Rendering must not move into this module.
- `backstitch/reporting.py` renders only. It must not filter findings.
- `backstitch/settings.py` owns TOML discovery, config loading, schema-key
  validation, defaults, and config JSON rendering.
- `backstitch/models.py` owns issue-code and report value contracts. Keep
  `ISSUE_CODES` and `ERROR_SEVERITY_CODES` here.

Refactor target shape:

- Add `backstitch/artifact_contracts.py` for packet JSONL and deterministic
  JSON report validation at trust boundaries.
- Add a focused check/suppression pipeline module, tentatively
  `backstitch/check_pipeline.py`, that scans, applies suppression once, and
  returns a structured result for `check` and `packets`.
- Add an internal command-workflow module only if the previous two extractions
  still leave `cli.py` carrying command behavior rather than parser/dispatch.
  Preferred name: `backstitch/commands.py` with a docstring that says it is an
  internal command workflow module, not a public embedding surface. If that
  name would imply public compatibility, use `backstitch/command_workflows.py`.
- Add `backstitch/settings_schema.py` only if it improves the config-key
  contract inventory. Do not create a catch-all `_constants.py`.

Required comprehension checks before editing:

1. Where does `llm` first enter the process today, and which tests prove
   deterministic commands avoid it?
2. Why does suppression happen after report emission and before render/exit?
3. Which validators reject malformed input before model selection or model
   calls?
4. Which spec mapping blocks must change if `cli.py` no longer owns packet or
   report validation?

## Invariants And Constraints

- Preserve the CLI contract exactly: command names, flags, precedence, output
  formats, exit codes, and no-traceback behavior remain unchanged.
- Preserve [SC-5] exit-code meaning: `1` is only deterministic target findings;
  `2` is invocation/tool failure.
- Preserve the `llm` quarantine. `check` and `packets` must not import `llm`,
  and moving code must not introduce a module import chain that loads it.
- Preserve [SC-13] total validation. Extraction must not narrow validators to
  only the fields a consumer happens to read.
- Preserve evidence locality. `analyze` enforces packet-local evidence bounds;
  `summarize-analysis` validates result/report shape but still does not see
  packets.
- Preserve suppression locality. Suppression happens once after deterministic
  report emission and before exit-code/render decisions. Suppressed findings
  remain recoverable with `--show-suppressions`.
- Preserve rendering locality. `reporting.py` renders only and never filters.
- Preserve config behavior. Unknown-key strictness, `allow_unknown_keys`,
  CLI/config/env precedence, path expansion, and no-op prevention remain
  unchanged.
- Do not introduce a public `backstitch.commands` compatibility surface in this
  refactor. If making command functions public becomes desirable, that is a
  separate spec change and review.
- Do not introduce a plugin framework, backend protocol, provider registry, or
  broad `_constants.py` package. SimpleBroker needs those because it has real
  backends and embedders; Backstitch does not yet.
- Do not move local parser regexes, prompt limits, SQL-like contract strings,
  or issue inventories away from their owning modules merely to centralize
  constants.
- Do not add dependencies. Use the standard library and existing project
  helpers.
- Avoid archival churn. Historical completed plans may be referenced or
  amended only if they are currently used as execution guidance. Do not rewrite
  historical plan narratives merely because ownership changed later.

## Rollout And Rollback

This is an internal code organization refactor with no storage, network,
deployment, or data migration. Rollout is the normal package release path after
tests, type checks, and the Backstitch self-corpus gate pass.

Rollback is a clean revert of the refactor commits. To keep rollback simple:

- keep behavior-preserving extractions in small slices
- avoid changing CLI help text except where tests prove it already matched the
  intended contract
- keep docs/spec mapping updates in the same slice as the code ownership move
  they describe
- do not create public API commitments that would survive rollback

One-way doors: none intended. If implementation introduces a public import
surface, a persistent artifact format change, or a behavior change, stop and
re-plan.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| Plan task 4 | Add an internal command-workflow module only if `cli.py` still carries enough command behavior to justify it | Not added in this slice | After artifact validation and scan/suppression moved out, a command module would mostly wrap existing handlers and pass `argparse.Namespace`; that fails the deletion test and risks creating an accidental public surface | None |
| Plan task 5 | Add `settings_schema.py` only if it improves config-key locality | Not added in this slice | Config inventories remain local to `settings.py`, which owns parsing, strictness, defaults, rendering, and tests; moving only constants would reduce locality and create a constants bucket | None |

## Tasks

1. Baseline and red tests.
   - Outcome: make missing verification gaps visible before moving code.
   - Files to read: `backstitch/cli.py`, `backstitch/analysis_llm.py`,
     `tests/test_cli.py`, `tests/test_analysis_packets.py`,
     `tests/acceptance/README.md`,
     `tests/acceptance/test_probe_selfacceptance.py`,
     `docs/implementation/02-repository-map.md`,
     `docs/implementation/04-backstitch-style-traceability.md`.
   - Files to touch:
     - `tests/test_cli.py` or a new `tests/test_llm_quarantine.py`
     - `tests/acceptance/README.md`
   - Before adding red tests, rerun the baseline command and record the current
     counts in this plan. Plan/spec edits may already have changed the
     traceability graph before code movement starts.
   - Add a fresh-process test proving deterministic commands do not import
     `llm`. Use `subprocess.run([sys.executable, "-c", ...])` against the real
     CLI entry point for both `check` and `packets`. Each child process must
     execute one deterministic command and assert `"llm" not in sys.modules`
     after the command returns. Do not use an in-process pytest call as the sole
     proof.
   - Update stale acceptance-probe wording from "twelve" probes to the current
     thirteen-probe contract. Use a broad search, not a narrow phrase match:
     ```bash
     rg -n "\\btwelve\\b|acceptance probes" docs/implementation docs/specs tests/acceptance
     ```
   - Verify:
     ```bash
     uv run pytest tests/test_cli.py tests/acceptance/test_probe_selfacceptance.py -q
     ```
   - Stop and re-evaluate if the quarantine test requires importing
     `analysis_llm` for deterministic commands. That would be a design bug, not
     a test inconvenience.

2. Extract artifact contract validators.
   - Outcome: packet and deterministic-report validation move out of CLI into a
     deeper trust-boundary module.
   - Files to read: `backstitch/cli.py` around `_PACKET_FIELDS`,
     `_packet_shape_error`, `_load_packets`, and `_cmd_summarize`;
     `backstitch/analysis_results.py`; `docs/specs/02-backstitch-core.md`
     [SC-6], [SC-13].
   - Files to touch:
     - new `backstitch/artifact_contracts.py`
     - `backstitch/cli.py`
     - `tests/test_analysis_packets.py`, `tests/test_analysis_results.py`, or
       new `tests/test_artifact_contracts.py`
     - `tests/test_review_remediation.py`
     - `tests/acceptance/test_probe_selfacceptance.py` only if imports need to
       follow the new module
   - Move packet-field inventory, issue-record validation helpers, packet
     loading, and deterministic-report validation into
     `artifact_contracts.py`.
   - Keep error messages compatible enough for existing substring assertions.
     Do not pin new tests to full environment-dependent exception text.
   - Keep `UnknownModel` and model selection after packet validation. A
     malformed packets file must still fail before model lookup.
   - Verify:
     ```bash
     uv run pytest tests/test_analysis_packets.py tests/test_analysis_results.py tests/test_review_remediation.py tests/acceptance/test_probe_selfacceptance.py -q
     ```
   - Stop and re-evaluate if the new module starts importing `analysis_llm` or
     if validators become projections of consumer needs rather than full
     producer contracts.

3. Extract scan plus suppression pipeline.
   - Outcome: `check` and `packets` share one suppression path without
     duplicating index construction or warning emission order.
   - Files to read: `backstitch/cli.py` `_cmd_check` and `_suppressed_report`;
     `backstitch/exclusions.py`; `backstitch/reporting.py`;
     `docs/implementation/04-backstitch-style-traceability.md` "Suppression is
     not filtering".
   - Files to touch:
     - new `backstitch/check_pipeline.py`
     - `backstitch/cli.py`
     - `tests/test_cli.py`, `tests/test_exclusions.py`,
       `tests/test_analysis_packets.py`,
       `tests/test_backstitch_corpus_traceability.py`
   - The module should expose a small interface, for example:
     `build_check_report(repo_root, profile, settings, allow_unknown) ->
     CheckPipelineResult`, where the result contains the kept `Report`,
     suppressed records, and warning strings. The exact name may differ, but
     callers must not need to know suppression internals.
   - Preserve warning order: suppression warnings first, unused-ignore warnings
     after `should_suppress` has recorded usage.
   - Add or strengthen a pipeline-level assertion that the interface returns
     kept report data, suppressed records, and warning strings without changing
     packet issue generation for kept findings.
   - Keep rendering in `reporting.py` and writing/exit decisions in command or
     CLI code.
   - Verify:
     ```bash
     uv run pytest tests/test_exclusions.py tests/test_cli.py tests/test_analysis_packets.py tests/test_backstitch_corpus_traceability.py -q
     ```
   - Stop and re-evaluate if the extraction pulls resolver policy into the
     suppression module or makes `reporting.py` responsible for filtering.

4. Decide and implement the command-workflow split.
   - Outcome: `cli.py` becomes parser, global flag merge, dispatch, and final
     exception-to-exit-code mapping. Command behavior lives in an internal
     command workflow module only if the previous slices did not already make
     `cli.py` adequately thin.
   - Files to read: `backstitch/cli.py`, `simplebroker/cli.py`,
     `simplebroker/commands.py`, `tests/test_cli.py`,
     `docs/specs/02-backstitch-core.md` [SC-5].
   - Files to touch if proceeding:
     - `backstitch/cli.py`
     - `backstitch/commands.py` or `backstitch/command_workflows.py`
     - focused tests for command functions if they provide useful leverage
   - Do not pass raw `argparse.Namespace` deep into new modules unless this is
     explicitly kept as a temporary transitional slice. Prefer small option
     dataclasses or plain typed parameters.
   - Keep lazy imports inside semantic command execution. The new module must
     not import `llm` at module import time.
   - Do not add `commands` to `backstitch.__all__`, README public API docs, or
     a public-surface test. This remains internal.
   - Verify:
     ```bash
     uv run pytest tests/test_cli.py tests/test_cli_config.py tests/test_analysis_llm.py -q
     ```
   - Stop and re-evaluate if the split creates one-function pass-through
     wrappers with no deeper interface. A shallow module fails the deletion
     test.

5. Tighten configuration schema inventory only if it improves locality.
   - Outcome: config-key and table-key inventories become easier to audit
     without turning Backstitch into a constants-dump module.
   - Files to read: `backstitch/settings.py`,
     `docs/specs/03-backstitch-configuration.md` [CFG-6], [CFG-8], [CFG-9],
     `tests/test_settings.py`, `tests/test_cli_config.py`.
   - Files to touch if proceeding:
     - optional new `backstitch/settings_schema.py`
     - `backstitch/settings.py`
     - `tests/test_settings.py`
   - Move only schema inventories and defaults that are genuinely shared by
     loader, config rendering, and tests. Keep parsing, path expansion, merge,
     and validation behavior in `settings.py` unless a deeper interface is
     clear.
   - Add or strengthen a test that enumerates supported config keys against
     the spec table or a single expected inventory, and proves no-op prevention
     remains covered for behavior-affecting keys.
   - Verify:
     ```bash
     uv run pytest tests/test_settings.py tests/test_cli_config.py tests/test_review_remediation.py -q
     ```
   - Stop and re-evaluate if the new module becomes a miscellaneous constants
     bucket or if moved constants reduce locality for parsers and validators.

6. Re-home contract tests only where it improves auditability.
   - Outcome: new tests land beside the contract they prove; historical review
     remediation value is preserved.
   - Files to read: `tests/test_review_remediation.py`,
     `tests/test_cli_config.py`, `tests/test_issue_code_coverage.py`,
     `tests/test_models.py`.
   - Move existing tests only when they are already being edited for this
     refactor and their new home is clearly better, for example artifact
     contract tests moving to `tests/test_artifact_contracts.py`.
   - Do not churn the 2,000-line remediation file solely for neatness.
   - Verify with every affected test file plus:
     ```bash
     uv run pytest tests/test_issue_code_coverage.py tests/test_models.py -q
     ```

7. Documentation, spec mapping, and plan reconciliation.
   - Outcome: docs describe the new ownership and no stale execution guidance
     remains.
   - Files to inspect with `rg` before editing:
     ```bash
     rg -n "backstitch/cli.py|_load_packets|_PACKET_FIELDS|twelve acceptance|llm .*sys\\.modules|artifact_contracts|check_pipeline|command_workflows|backstitch/commands.py" docs README.md tests backstitch
     rg -n "\\btwelve\\b|acceptance probes" docs/implementation docs/specs tests/acceptance
     ```
   - Files to update as needed:
     - `docs/specs/02-backstitch-core.md` implementation mappings for [SC-5],
       [SC-6], [SC-8], [SC-13], and `## Related Plans`
     - `docs/specs/03-backstitch-configuration.md` [CFG-9], [CFG-10], and
       `## Related Plans` if config schema ownership changes
     - `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-7],
       [EXC-9], [EXC-10], and `## Related Plans` if suppression pipeline
       ownership changes
     - `docs/implementation/02-repository-map.md`
     - `docs/implementation/04-backstitch-style-traceability.md`
     - this plan's deviation log and verification notes
     - active, non-archival plans that are still used as implementation
       guidance and name old ownership
   - Do not rewrite completed archival plans except for an explicit amendment
     section when a future implementer would otherwise follow stale guidance.
   - Verify docs with Backstitch itself:
     ```bash
     uv run backstitch check --repo-root . --show-suppressions
     uv run backstitch check --repo-root . --format json --output /tmp/backstitch-organization-refactor-report.json
     ```
   - Success: both commands exit `0`; text summary has `0` errors and `0`
     warnings; JSON summary has `"errors": 0` and `"warnings": 0`; any new
     infos are understood and either eliminated or recorded as intentional
     spec/implementation mapping debt.

8. Final verification and closeout.
   - Outcome: no behavior regression, no traceability regression, no stale
     documentation.
   - Run:
     ```bash
     uv run pytest tests -q -m "not live_llm"
     uv run pytest tests/acceptance -q
     uv run ruff check backstitch tests
     uv run ruff format --check backstitch tests
     uv run mypy backstitch
     uv run backstitch check --repo-root . --show-suppressions
     ```
   - Optional smoke when credentials or local model setup are intentionally
     available:
     ```bash
     BACKSTITCH_LIVE_LLM=1 uv run pytest -m live_llm -q
     ```
   - Completion requires concrete evidence in the plan closeout: changed files,
     commands, observed results, and residual risks. Do not cite an older status
     note as proof.

## Testing Plan

Test through real public surfaces where practical:

- CLI behavior stays covered by subprocess tests in `tests/test_cli.py`,
  `tests/test_cli_config.py`, and acceptance probes.
- Artifact validators get direct unit tests plus real CLI tests proving the
  malformed-input boundary still exits `2`.
- Suppression pipeline gets direct tests only for the new interface, plus
  existing real check/config tests proving output, exit code, and
  `--show-suppressions` behavior.
- The `llm` quarantine proof must use a subprocess or import-level real command
  path. Do not mock the import graph.
- Config key no-op prevention must remain behavior-based. `config show` alone
  is not proof that a key affects `check`, `packets`, or `analyze`.
- Model calls remain fake in hermetic tests. Live LLM tests are optional smoke,
  not required proof for this refactor.

## Verification And Gates

Per-slice gates are listed in the task breakdown. Final gates before claiming
completion:

```bash
uv run pytest tests -q -m "not live_llm"
uv run pytest tests/acceptance -q
uv run ruff check backstitch tests
uv run ruff format --check backstitch tests
uv run mypy backstitch
uv run backstitch check --repo-root . --show-suppressions
uv run backstitch check --repo-root . --format json --output /tmp/backstitch-organization-refactor-report.json
```

Backstitch verification is mandatory, not a nice-to-have. Success means exit
`0`, zero errors, zero warnings, and no unexplained new info-level graph debt.
The JSON report is an inspection aid for summary counts and new issue
locations; do not parse rendered text to prove structured fields.

## Implementation Closeout, 2026-07-06

Implemented slices:

- Added `backstitch/artifact_contracts.py` for packet JSONL and deterministic
  report validation. `backstitch/cli.py` now calls `load_packets()` from
  `analyze` and `load_deterministic_report()` from `summarize-analysis`.
- Added `backstitch/check_pipeline.py` for the shared deterministic scan plus
  suppression pass. `check` and `packets` now use the same kept-report,
  suppression-audit, and warning sequence.
- Added contract tests in `tests/test_artifact_contracts.py` and
  `tests/test_check_pipeline.py`.
- Added a fresh-process `llm` quarantine test in `tests/test_cli.py` for both
  `check` and `packets`.
- Updated spec implementation mappings, implementation docs, acceptance-probe
  wording, and the active input-validation plan that still pointed future
  maintainers at old CLI validator ownership.

Deferred by deletion-test decision:

- No `backstitch/commands.py` or `backstitch/command_workflows.py`: after the
  two extractions, a command module would mostly wrap `argparse.Namespace`
  handlers and risk an accidental public surface.
- No `backstitch/settings_schema.py`: config inventories still have stronger
  locality in `settings.py`, which owns parse, strictness, defaults, rendering,
  and tests.

Verification evidence:

- `uv run pytest tests -q -m "not live_llm"`: pass.
- `uv run pytest tests/acceptance -q`: pass, `14` tests.
- `uv run ruff check backstitch tests`: pass.
- `uv run ruff format --check backstitch tests`: pass, `68` files already
  formatted.
- `uv run mypy backstitch`: pass, no issues in `19` source files.
- `git diff --check`: pass, no whitespace errors.
- `uv run backstitch check --repo-root . --show-suppressions`: pass, exit `0`;
  `56` spec sections, `81` mappings, `234` code refs, `370` edges; `0`
  errors, `0` warnings, `35` infos, `146` suppressed findings.
- `uv run backstitch check --repo-root . --format json --output
  /tmp/backstitch-organization-refactor-report.json`: pass, JSON summary
  `{"spec_sections": 56, "code_refs": 234, "spec_mappings": 81, "errors": 0,
  "warnings": 0, "infos": 35}`.

Backstitch graph note: the final info count is lower than the implementation
start baseline (`46` infos) because the refactor added recognized
implementation mappings. The remaining infos are existing unmapped code refs
and the proposed `docs/specs/05-backstitch-invariants.md` sections; no new
`artifact_contracts.py` or `check_pipeline.py` info debt remains after the
mapping pass.

Residual risks and non-gates:

- `/claude challenge` was retried after implementation. The Claude CLI exists
  at `/Users/van/.local/bin/claude`, but auth is missing: no
  `~/.claude/.credentials.json` and no `ANTHROPIC_API_KEY`. The requested
  adversarial Claude review is therefore blocked, not passed.
- Live LLM smoke was not run; this refactor does not change model-call
  behavior and the final required gates exclude `live_llm`.
- Changes are intentionally uncommitted because the user did not ask for a
  commit. Per repository DoD, this is ready for user review but not claimed as
  landed.

## Independent Review Loop

Run an independent plan review before implementation starts.

Preferred review path:

1. Use a different agent family if available through the agent tools.
2. If unavailable, use a same-family reviewer with a strict review role.
3. Record the review result in this plan or an adjacent closeout note.

Review prompt:

> Read `docs/plans/2026-07-06-backstitch-organization-refactor-plan.md`, the
> governing specs [SC-5], [SC-6], [SC-8], [SC-10], [SC-13], [CFG-9], and
> [EXC-7], plus `docs/implementation/04-backstitch-style-traceability.md`.
> Do not implement. Look for errors, bad ideas, missing invariants, weak tests,
> traceability gaps, and places the plan could cause behavior drift. Could you
> implement it confidently and correctly as written?

The authoring agent must answer every review point by updating the plan,
recording a rejection with reasoning, or marking the point out of scope.

Authoring review status, 2026-07-06:

- Same-family independent review completed before implementation. It found
  missing review-remediation and packet-generation tests in slice gates, a
  too-weak `llm` quarantine proof, a too-narrow stale-doc search, and a missing
  pre-refactor baseline rerun. Those points are folded into the tasks above.
- Requested `/claude challenge` adversarial review was attempted after the plan
  was ready. The Claude CLI was present, but the `/claude` auth gate failed
  because neither `~/.claude/.credentials.json` nor `ANTHROPIC_API_KEY` was
  available. It was retried after implementation with the same auth blocker;
  rerun `/claude challenge` against the current diff before landing if Claude
  auth becomes available.

## Out Of Scope

- Public `backstitch.commands` embedding surface.
- Plugin framework or backend/provider registry.
- New dependencies.
- CLI syntax, flag behavior, help text changes, or exit-code changes.
- Report, packet, or analysis JSONL schema changes.
- Formatter-only churn outside touched files.
- Moving every constant to one module.
- Rewriting historical archival plans for style.
- Implementing `docs/specs/05-backstitch-invariants.md`.

## Fresh-Eyes Review Checklist

Before implementation, re-read this plan and confirm:

- every new module has a specific responsibility and passes the deletion test
- every load-bearing behavior has a named invariant
- each task names files, tests, and stop gates
- Backstitch self-check commands are explicit in verification
- docs/spec mapping updates are not deferred to vague cleanup
- no task creates a public API by accident
- no task hides a behavior change under "refactor"

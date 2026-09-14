# Review Findings Remediation Plan (2026-09-14)

**Status:** completed; seven targeted slices implemented, verified, and reviewed

**Class:** 5, spec-changing. The work changes public configuration,
publication, and platform-support claims. The risky-change checklist applies
to publication and configuration authority. Native Windows implementation is
deferred to a separate exploration plan.

**Plan type:** implementation with spec revision.

## Goal

Close the seven confirmed review findings in seven reviewable slices, with one
targeted final commit per slice. Make the smallest change that restores the
intended boundary. Reuse existing owners; do not add a policy framework,
compatibility layer, or process gate unless the finding cannot be closed
without it.

The seven final implementation commits are listed by finding number. Landing
order is 1, 2, 3, 4, 6, 7, 5:

1. `fix(config): keep publication destinations invocation-owned`
2. `fix(semantic): reject cache and source overlap before providers`
3. `fix(coverage): render typed issues and recovery actions in text`
4. `fix(check): publish reports atomically`
5. `docs(platform): declare current POSIX runtime support`
6. `ci(release): smoke-test built wheel and sdist`
7. `test(architecture): rank every package module`

The plan replaces the prior uncommitted publication-authority draft. It keeps
that draft's decision to remove configuration-owned destinations and its use
of the existing atomic publication primitive. It deliberately drops the
proposed config-file identity guard, generalized destination policy, and extra
filesystem failure modes. Once output selection is invocation-only, an
explicit `--output` is direct user authority; adding another protection layer
would not close the reported repository-authority defect. The prior draft is
not part of this plan's landing set.

The owner's subsequent pasted review narrows slice 5 to an accurate support
declaration. Native Windows support remains a separately considered feature
in `docs/plans/2026-09-14-native-windows-support-exploration-plan.md`; it is not
a prerequisite for any remediation slice.

## Source Documents

- `docs/program-theory.md`
- `docs/agent-context/README.md`, `docs/agent-context/decision-hierarchy.md`,
  `docs/agent-context/principles.md`,
  `docs/agent-context/engineering-principles.md`,
  `docs/agent-context/lessons.md`, and `docs/lessons.md`
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11], [DOM-15]
- `docs/specs/02-backstitch-core.md` [SC-5], [SC-10], [SC-17]
- `docs/specs/03-backstitch-configuration.md` [CFG-5], [CFG-5.1], [CFG-6],
  [CFG-7], [CFG-9]
- `docs/specs/06-semantic-gates.md` [SEM-4]
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-5.1], [EVC-8.2]
- `docs/specs/08-intent-coverage.md` [COV-9]
- `docs/implementation/02-repository-map.md`
- `docs/implementation/05-release-publishing.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`

Origin: the seven findings supplied by the owner after the repository review,
against baseline `7d1bb154665e7fca1d8cf2c16d5fd62a0e9cd2db`.

## Spec Baseline

- `7d1bb154665e7fca1d8cf2c16d5fd62a0e9cd2db`:
  `docs/specs/02-backstitch-core.md`,
  `docs/specs/03-backstitch-configuration.md`,
  `docs/specs/06-semantic-gates.md`,
  `docs/specs/07-verification-and-evidence-cases.md`, and
  `docs/specs/08-intent-coverage.md` at plan authoring time.
- Promotion strategy: **B, atomic**, within the affected implementation
  slice. Each changed requirement, implementation, reciprocal traceability,
  tests, and necessary implementation documentation land in that slice's one
  targeted commit. No separate spec-only implementation commit is needed.
- Before each spec-changing slice is committed, record its promotion baseline
  in the execution log as the pre-slice commit SHA plus the named staged spec
  diff. Report final slice SHAs in the closeout report; do not force a later
  plan-only commit to record a commit's own SHA.

## Proposed Spec Delta

Findings 1 and 4 change intended behavior. Finding 5 corrects packaging and
support claims and removes a contradictory Windows CI obligation; it keeps
the existing POSIX-only snapshot contract. Findings 2 and 3 repair
code to an existing contract. Finding 6 changes the release implementation
gate, whose owner is `docs/implementation/05-release-publishing.md`. Finding 7
makes the existing [SC-17] direction gate exhaustive.

| Spec file | Strategy | Sections touched |
|---|---|---|
| `docs/specs/02-backstitch-core.md` | B, atomic in slices 1 and 4 | [SC-5] |
| `docs/specs/03-backstitch-configuration.md` | B, atomic in slice 1 | [CFG-5], [CFG-5.1], [CFG-6], [CFG-7], [CFG-9] |
| `docs/specs/06-semantic-gates.md` | B, atomic in slice 5 | [SEM-4] |
| `docs/specs/08-intent-coverage.md` | B, atomic in slice 1 | [COV-9] |

### Slice 1: exact publication-authority text

In [SC-5], replace the paragraph beginning `For local use, invoking bare
backstitch` with:

> For local use, invoking bare `backstitch` delegates command selection and
> the selected command's documented side effects to effective repository
> configuration. Repository configuration never selects a report or artifact
> publication destination. `check` and `coverage` publish a report only when
> the invocation explicitly supplies `--output`; relative output paths resolve
> from the process working directory. Configured analyze may read credentials,
> write cache state, make bounded provider calls, and incur bounded cost under
> its existing contract. Bare dispatch is forbidden in secret-bearing
> hostile-target automation: those workflows continue to name the semantic
> command, select trusted tool configuration explicitly, and use only
> workflow-owned static overrides under [SEM-9] and [EVC-11]. The CLI does not
> infer whether an invocation is local or automated; the hostile-target
> prohibition is a workflow contract enforced by trusted workflow source and
> its firing tests.

Apply these exact [CFG-*] edits:

- [CFG-5]: in the coverage-ratchet paragraph, replace `Only the root alias,
  format, output, and --require-ratchet REF are operational CLI inputs.` with
  `Only the root alias, --format, --output, and --require-ratchet REF are
  operational CLI inputs. --output has no configuration equivalent.`
- [CFG-5.1]: replace `Reserved/non-consulted leaves such as packets.output are
  not runtime-overridable.` with `Every accepted generic option names a
  runtime-consulted configuration leaf; publication destinations are not
  configuration leaves.`
- [CFG-5.1]: remove the `--output | check.output | check only` row from the
  dedicated-setting alias map. Replace `non-check --format/--output` in the
  following paragraph with `every --output`; all output flags are operational
  arguments.
- [CFG-6] section 6.3: remove the `output` row from `[check]`.
- [CFG-6] section 6.4: remove the whole `[packets]` table and its reserved-v1
  prose. Renumbering later headings is not required because stable reference
  codes, not display numbers, own citations.
- [CFG-6] section 6.10: remove `[packets]` from the list of tables with
  packaged defaults.
- [CFG-6] section 6.14: remove the `output` row from `[coverage]`.
- [CFG-7]: replace the paragraph beginning `Bare invocation is a local
  convenience` with:

  > Bare invocation is a local convenience over repository configuration, not
  > a hostile-target automation primitive. Selecting `"analyze"` authorizes
  > the same credential, network, cache, and bounded-cost behavior as explicit
  > current-repository analyze. Selecting `"check"` authorizes deterministic
  > scanning but no report publication destination; publication requires an
  > explicit invocation `--output`. Secret-bearing hostile-target workflows
  > must not use bare invocation; [SEM-9] and [EVC-11]'s explicit trusted
  > command/config/override boundary remains mandatory. This restriction is
  > enforced at the workflow contract and test boundary; the CLI does not
  > guess operator intent or trust from the same process inputs.
- [CFG-9]: replace the configured-`check.output` proof bullet with:
  `strict configuration rejects check.output, packets.output, and
  coverage.output as unknown keys; the allow_unknown_keys hatch names and
  ignores them; explicit check and coverage --output still publish to the
  invocation-selected path.`

In [COV-9], replace `--format and --output override their config keys` with:

> `--format` overrides its configuration key. `--output` is an operational
> invocation argument with no configuration equivalent and does not enter
> ratchet policy identity.

No transition schema or deprecated aliases are added. This repository is
pre-release and has no outside consumers; stale keys use the existing
closed-schema behavior.

### Slice 4: exact atomic-check text

Insert in [SC-5] after the `coverage` exit-code paragraph:

> When `check --output PATH` is present, Backstitch publishes the selected
> complete report with a same-directory staged replacement, creating missing
> parent directories for the explicitly selected output path. `coverage`
> uses the same parent-directory behavior. A failed
> publication returns exit `2` and leaves the previous state, including
> absence, or a complete new file; it never leaves a partially written final
> report.

### Slice 5: exact platform-support text

Keep [EVC-8.2]'s existing POSIX-only snapshot algorithm and six-field stat
tuple unchanged.

In [SEM-4], replace the sentence `Windows must exercise the same-file-system
hard-link path in CI; directory fsync is required only where the platform
supports opening and syncing directories.` with:

> The same-filesystem hard-link publication path must be exercised in
> hermetic tests. Runtime platform support is defined by [EVC-8.2]; a
> dependency-only Windows CI lane does not establish runtime support.
> Directory fsync is required only where the platform supports opening and
> syncing directories.

The implemented Windows advisory-lock branch can remain. Its existence is
not evidence of support for end-to-end repository commands. No cache
publication or lock guarantee is weakened.

Replace the `Operating System :: OS Independent` package classifier with
`Operating System :: POSIX` and `Operating System :: MacOS :: MacOS X`.
Add this sentence to README installation requirements and the repository map's
snapshot description:

> Repository commands currently require a POSIX system, including Linux and
> macOS, with the no-follow descriptor primitives defined in [EVC-8.2];
> Windows is not supported.

In the README, link [EVC-8.2] to the existing snapshot section. Do not promise
one universal Windows error string: config bootstrap can reject the platform
before snapshot capture supplies its structured `UNSUPPORTED_PLATFORM`
error.

## Context and Key Files

- Publication/config: `backstitch/settings.py`, `backstitch/cli.py`,
  `backstitch/coverage_application.py`,
  `backstitch/artifact_publication.py`,
  `tests/test_cli.py`, `tests/test_cli_config.py`,
  `tests/test_config_parity.py`, `tests/test_coverage_application.py`.
- Semantic overlap: `backstitch/semantic_application.py`,
  `backstitch/semantic_cache.py`, `tests/test_semantic_analysis.py`.
- Coverage presentation: `backstitch/intent_coverage_reporting.py`,
  `backstitch/coverage_application.py`, `backstitch/cli.py`,
  `backstitch/reporting.py`, `tests/test_coverage_application.py`,
  `tests/test_cli.py`.
- Platform declaration: `pyproject.toml`, `README.md`,
  `docs/implementation/02-repository-map.md`,
  `docs/specs/06-semantic-gates.md` [SEM-4]. Read
  `backstitch/filesystem_io.py` and `backstitch/repository_snapshot.py`
  to verify the existing restriction; do not change their implementation.
- Atomic-output acceptance:
  `tests/acceptance/test_probe_boundaries.py` and
  `tests/test_cli.py` both currently use a missing parent as their
  unwritable-destination fixture.

- Release: `.github/workflows/release-gate.yml`,
  `tests/test_release_workflow.py`, `docs/implementation/05-release-publishing.md`.
- Architecture: `tests/test_architecture.py` and the live `backstitch/**/*.py`
  module inventory.

Before editing output tests, answer in the execution log: what must remain
true when a missing parent becomes valid? Expected answer: an actually
unwritable destination still exits `2` with a one-line error, no traceback,
and no partial final report. Both missing-parent fixtures must instead use a
regular file as the would-be parent, which is unwritable without relying on
permissions or the executing user. Read [SC-10] probe 11 if the answer differs.

Before editing publication code, answer: which part of the reported threat is
removed by deleting config output keys, and which part remains intentional?
Expected answer: scanned repository bytes can no longer choose a destination;
an explicit CLI caller may still replace the path it selected.

## Invariants and Constraints

- No new dependencies.
- No second settings schema, compatibility reader, deprecation epoch, or
  migration state. Removed config keys are ordinary unknown keys.
- No generic path-policy or publication service. Use the existing closed-key
  resolver, one local mutual-overlap predicate, and
  `artifact_publication.atomic_replace_bytes`.
- Exit `1` remains a target-finding result. Invalid config, unsafe overlap,
  unsupported platform, and publication failures remain exit `2` with no
  traceback.
- Deterministic failures happen before provider construction or calls.
- The snapshot remains one immutable whole-attempt POSIX capture. This plan
  changes neither its I/O backend nor its data model, identity, or retry rules.
- Tests assert public behavior and durable contract tokens. They do not pin
  complete prose, helper names, temporary filenames, syscall order, CI step
  names, line counts, commit count machinery, or the current number of package
  modules.
- Existing Windows dependency lanes establish dependency availability only.
  This remediation adds no Windows runtime support or native platform layer.
- No unrelated refactor. If a slice needs a new abstraction used by only one
  call site, stop and justify it in the deviation log before adding it.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|

## Slice Plan

### Slice 1: Invocation-owned publication destinations

**Finding closed:** repository configuration can choose arbitrary writable
destinations for `check` and `coverage`; `packets.output` is dead reserved
schema with the same authority shape.

**Implementation:** remove `check.output`, `coverage.output`, and
`packets.output` from settings key sets, dataclasses, parsers, expansion,
presentation-key exclusions, serialization, and config docs. The packaged
`defaults.toml` currently has no output keys to remove. Stop
folding `check --output` and `coverage --output` into dedicated settings
overrides. Pass each CLI value directly to its command/application request;
add only the one `CoverageRequest` field needed to carry coverage's operational
path to its existing atomic publisher.

**Proof:** parameterized filesystem and blob-backed resolver tests fire each
removed key through ordinary unknown-key handling. This directly covers the
historical config adapter without freezing a full ratchet-history migration
scenario. A real CLI reproduction gives check and coverage a repository config
containing an absolute external destination and proves the external sentinel
remains unchanged. Public CLI tests prove explicit `check --output` and
`coverage --output` still write, and `config show` no longer exposes the
removed fields/table. Existing generic unknown-key tests remain the authority
for unrelated hatch behavior; do not multiply hatch cases per removed key.

**Docs:** promote the slice-1 delta above and update
`docs/implementation/02-repository-map.md` where it describes settings/CLI
output ownership.

**Commit:** `fix(config): keep publication destinations invocation-owned`

### Slice 2: Mutual cache/source overlap preflight

**Finding closed:** `cache_path="."` can contain a configured semantic input,
allowing cache writes before currentness rejects the mutation.

**Implementation:** in `semantic_application.py`, use one local mutual-overlap
predicate: equality, left contains right, or right contains left. Apply it to
the cache root and every current semantic input/output path before provider or
cache work. Do not enumerate `packets`, `results`, `locks`, or other derived
cache namespaces; validating the cache root in both directions covers all of
them without encoding current layout.

**Proof:** add the reverse-containment public/application regression with
`cache_path="."` and a code root beneath it. Assert exit `2`, no provider
construction or call, no cache artifact, and unchanged source bytes. Keep the
existing same-path and cache-under-input cases.

**Spec:** no delta. This implements the existing mutual-overlap and
pre-provider contract in [EVC-5.1].

**Commit:** `fix(semantic): reject cache and source overlap before providers`

### Slice 3: Complete coverage text issues

**Finding closed:** JSON carries typed coverage issues while text omits them;
BSN009 can fail without the required recovery action.

**Implementation:** add `intent_coverage_reporting.render_coverage_text` as the
single coverage text renderer used by the CLI and direct application tests.
Rename `reporting._issue_line` to the internal shared
`reporting.render_issue_line` and use it for both check and coverage issues,
instead of inventing a coverage-only issue format. Both reporting modules
belong at rank 2; verify the planned shared-renderer edge against slice 7's
map, including existing TYPE_CHECKING edges. After the summary/worklist,
render every typed issue. Make BSN009's message contain the changed policy key,
event id, repository-config location, the `Backstitch-Coverage-Policy-Ack`
trailer, and the rerun action. Do not add a second recovery field or change the
JSON schema.

**Proof:** a public CLI ratchet regression exits `1` and asserts durable tokens:
`BSN009`, its canonical code, the changed key, event id, acknowledgement
trailer name, and rerun direction. Renderer tests cover an issue with and
without location. Do not compare the entire paragraph or whitespace layout.

**Spec:** no delta. [COV-9] already requires the same action in JSON and text.

**Commit:** `fix(coverage): render typed issues and recovery actions in text`

### Slice 4: Atomic check report publication

**Finding closed:** `Path.write_text` can truncate the final report on failure.

**Implementation:** keep report selection/rendering in the CLI and replace the
direct write with `artifact_publication.atomic_replace_bytes` over encoded
report bytes. Adopt the helper's existing parent-directory creation behavior
for an explicit output path, matching coverage. This deliberately changes the
old check-only missing-parent failure. Preserve the existing one-line exit-2
translation for actual publication failures; no pre-check or helper option is
needed.

**Proof:** inject failure at the replacement boundary through the existing
publication seam and prove a pre-existing destination remains byte-complete;
also prove successful text and JSON output into a missing parent. Retarget
both `tests/test_cli.py::test_check_unwritable_output_exits_two` and the
unwritable branch of acceptance probe 11 to a regular file used as the parent
of the requested output. Assert exit `2`, no traceback, and unchanged blocker
bytes. This preserves [SC-10]'s unwritable-output contract while dropping a
fixture assumption. Reuse the helper's existing tests for staging/fsync.
The generic acceptance runbook lists missing parents as a default example;
its explicit spec-override rule applies to the revised [SC-5] behavior.

**Docs:** promote the slice-4 [SC-5] delta and update the repository map to
remove `remaining direct output writes` from the CLI description if none
remain.

**Commit:** `fix(check): publish reports atomically`

### Slice 5: Truthful platform declaration

**Finding closed:** package metadata claims OS independence while the core
repository commands require POSIX, and Windows CI proves dependency
availability rather than Backstitch runtime support.

**Implementation:** replace the OS-independent classifier with explicit POSIX
and macOS classifiers; add the support sentence to README requirements and the
repository map; reconcile [SEM-4]'s unconditional Windows hard-link CI
requirement using the delta above. Retain [EVC-8.2]'s capture contract and the
existing cache implementation.

**Proof:** inspect package metadata and the built wheel's classifiers, check
README/map/spec agreement, and run the existing unsupported-capability
pre-traversal regression in `tests/test_repository_snapshot.py`. The existing
semantic-cache suite continues to exercise real hard-link publication on
supported hosts. No new prose-snapshot test, Windows refusal job, or matrix
change is needed. There is no local Windows runner; future native runtime
proof belongs to the separate exploration plan and will run in CI.

**Docs:** promote the slice-5 [SEM-4] delta. The separate plan records the
unresolved Windows product and filesystem questions without prescribing a
native backend or making it a dependency of these fixes.

**Commit:** `docs(platform): declare current POSIX runtime support`

### Slice 6: Test the release distributions before attestation

**Finding closed:** release attests built distributions without installing or
executing either artifact.

**Implementation:** in the existing release `build` job, after build and
before attestation, resolve exactly one wheel and one sdist. Install each into
its own fresh environment, from outside the source checkout, prove
`backstitch.__file__` belongs to that environment, and run the installed
console script for `--version`, `guide alignment --format json`, and
`check --repo-root` against the checkout. Use the artifacts already built by
that job: install the exact wheel file in one environment and the exact sdist
file in the other. Installing the sdist normally builds a wheel from its
contents; that build is part of the test. Do not substitute another source
checkout or a fresh release build for either distribution under test. Keep
this inline in the one workflow unless a second real consumer appears.

**Proof:** extend the release-workflow structure test only far enough to prove
both artifact kinds are installed and exercised before the attestation action.
Assert behavior/order, not step names, venv names, or the full shell text. The
tag workflow remains the real installation test.

**Docs:** update `docs/implementation/05-release-publishing.md` so its gate
order says build, fresh-install smoke of wheel and sdist, then attest.

**Commit:** `ci(release): smoke-test built wheel and sdist`

### Slice 7: Exhaustive architecture ranks

**Finding closed:** upward/private import enforcement omits substantive
modules even though the package-wide cycle check sees them.

**Implementation:** add every current non-`__init__` `backstitch` module to
the existing `_LAYER_RANK` map at its reviewed conceptual layer. Add one set
equality assertion between that map and the live non-initializer module
inventory. Keep the existing rank integers and import parser. Add no exception
registry because the current full map has no upward or private cross-rank
violations.

Initial reviewed placements:

- rank 0: `contract_validation`, `diagnostics`, `models`,
  `operation_progress`
- rank 1: `alignment_guide`, `code_parser`, `exclusions`, `git_baseline`,
  `markdown_specs`, `profiles`, `python_refs`, `target_roots`
- rank 2: `analysis_results`, `evidence_discovery`, `evidence_summary`,
  `intent_coverage`, `intent_coverage_reporting`, `intent_history`,
  `obligations`, `reporting`, `semantic_budget`
- rank 3: `alignment_eval`, `analysis_llm`, `doctor`
- rank 4: `__main__`

`reporting` is a reusable pure renderer at rank 2. It imports `models` and
has a TYPE_CHECKING dependency on rank-2 `check_pipeline`; the graph counts
that dependency. The new `intent_coverage_reporting` to `reporting` import
from slice 3 must pass this map, not merely today's unmodified graph.

Use fully qualified names in the actual table. Re-run both direction gates
after each placement change. If a real violation appears, fix or review that
edge; do not add an unreviewed exception or omit the module.

**Proof:** the set-equality assertion fails for any future unranked shipping
module. Existing upward and private-import tests then apply to the whole set.
Do not assert the current count (`57`) or freeze module filenames anywhere
except the rank map that carries the architectural decision.

**Spec:** no delta. This makes the executable gate match [SC-17]'s existing
package-wide direction contract.

**Commit:** `test(architecture): rank every package module`

## Dependency and Landing Order

Use one branch and land in this order: **1, 2, 3, 4, 6, 7, 5**. Slice numbers
continue to identify the original findings. Each slice has its own targeted
commit including its needed spec, tests, docs, and evidence.

Slice 1 precedes slices 3 and 4 because they touch CLI/output ownership.
Slices 6 and 7 land before the support declaration so neither waits for a
platform decision. Check the planned renderer import when applying slice 3,
then enforce the full map in slice 7. Native Windows support is independent
future work and cannot block any commit in this remediation.

Record final verification and close the plan/index with the last targeted
slice after all seven fixes pass. No process-only closure commit is required.

## Testing and Verification

For each slice:

1. Add the narrow regression first when it can fail on the current tree.
2. Run the directly affected test files without xdist while diagnosing.
3. Run Ruff and mypy on changed Python files.
4. Run the self-corpus gate and record exact counts.
5. Run an independent review for each meaningful slice and disposition every
   finding.
6. Commit only that slice.

Run the complete hermetic suite once over the final seven-commit range.
Earlier slices use targeted and neighboring tests; broaden that testing when
an actual change or failure warrants it.

Final local gates:

```bash
uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm and not benchmark"
uv run --frozen --no-sync ruff check . bin/check-doc-paths bin/check-dom15-fixtures bin/coalesce-check
uv run --frozen --no-sync python bin/ruff_suppression_index.py --check
uv run ruff format --check backstitch bin .github/scripts tests
uv run mypy backstitch bin/release.py tests --config-file pyproject.toml
python bin/check-doc-paths --self-test
python bin/check-doc-paths
python bin/check-dom15-fixtures --self-test
python bin/check-dom15-fixtures
uv run backstitch check --repo-root .
```

Final remote gate: the ordinary CI workflow must be green. The release
artifact smoke is structurally checked on ordinary CI and executes for real
on the next tag; record that tag run as post-merge evidence. Existing Windows
jobs are dependency checks and must not be described as runtime proof.

The [SC-10] acceptance suite exists under `tests/acceptance/` and runs as part
of the complete hermetic suite. Put the four reproductions from this review in
that suite or the nearest existing public CLI regression; do not repeat them as
a manual closeout ritual.

## Rollback and Residual Risk

Each slice is independently revertible. Reverting slice 1 restores unsafe
repository output authority, so do not use that as a compatibility measure.
Slice 4 intentionally starts creating missing output parents; a caller that
depended on failure for a nonexistent directory observes a behavior change.
An actually unwritable path retains exit `2`.

Windows remains unsupported after remediation. This closes the false support
claim but provides no native Windows capability. Reconsidering support is
separate product work, with its real testing constrained to CI.

Release artifact installation runs on the next tag after the structural
workflow check. Local isolated wheel/sdist smoke can verify the same commands
during implementation without publishing a tag; it does not count as a
successful hosted release run.

## Out of Scope

- constraining destinations selected explicitly by the CLI
- a reusable output-authority policy engine or filesystem capability object
- backward-compatible parsing of removed config keys
- native Windows capture, a second snapshot schema, or platform-specific
  semantic identity
- a Windows runtime matrix or a job that freezes today's unsupported status
- refactoring the architecture test or production modules beyond adding the
  missing ranks
- changing release repository settings or publishing a release
- coalescing the plans/lessons backlog reported at session start

## Independent Review Loop

An independent reviewer examines the revised plan and proposed spec delta for
correctness, simplification/YAGNI, and agreement between slices. The review
must include planned import edges, not just the current live graph.

During implementation, independently review each meaningful slice and then
the final range. Record findings and dispositions below. Tests enforce
behavior, not the number of review rounds, reviewer identity, or plan wording.

## Review Log

| Date | Reviewer focus | Verdict | Findings and disposition |
|---|---|---|---|
| 2026-09-14 | Initial simplification and Windows/architecture reviews | Historical pass; superseded by this revision | The earlier passes failed to catch the planned rank-2 to rank-3 renderer edge and understated Windows's total scope. They do not authorize the changed design. |
| 2026-09-14 | Owner-supplied review | Incorporated | Native Windows becomes a separate exploration; slice 5 declares POSIX/macOS support and reconciles [SEM-4]; reporting returns to rank 2; landing order is 1,2,3,4,6,7,5; check adopts parent creation and both unwritable fixtures change; sdist installation explicitly includes its normal build. |
| 2026-09-14 | Independent revision review: correctness and YAGNI | PASS | Confirmed narrowed platform scope and [SEM-4] reconciliation, planned renderer edge including TYPE_CHECKING, both unwritable-output fixtures, sdist build semantics, landing order, deferred Windows exploration, and matching index statuses. No remaining blocker. |
| 2026-09-14 | Slice 1 implementation review: correctness and YAGNI | PASS after corrections | Removed a stale `[packets]` defaults claim, applied the exact planned trust-boundary text, removed a duplicate backlink, and added valid `config show` and unknown-key-hatch proof. The reviewer found no retained configuration authority or remaining blocker. |
| 2026-09-14 | Slice 2 implementation review: correctness and YAGNI | PASS after correction | Replaced assertions about three named cache directories with a before/after repository path inventory, proving no derived cache artifact without freezing the cache namespace layout. The symmetric preflight predicate and ordering were accepted. |
| 2026-09-14 | Slice 3 implementation review: correctness and YAGNI | PASS after correction | Relaxed one no-location assertion so it binds the durable issue token and message rather than incidental leading spaces. Text/JSON issue parity, recovery content, and the rank-2 reporting edge were accepted. |
| 2026-09-14 | Slice 4 implementation review: correctness and YAGNI | PASS after corrections | Added unchanged-blocker and no-traceback acceptance proof, mirrored the blocker check in the unit test, and exercised missing-parent success for both text and JSON. The atomic owner reuse and spec delta were accepted. |
| 2026-09-14 | Slice 6 implementation review: correctness and YAGNI | PASS after correction | Strengthened the structural test to order both exact artifact smoke calls before attestation and prove the function installs its artifact argument. The workflow implementation and minimal inline shape were accepted. |
| 2026-09-14 | Slice 7 implementation review: correctness and YAGNI | PASS | All non-`__init__` modules are ranked consistently with the live import graph; dynamic equality, upward-import, and private-cross-rank checks pass with no fixed count, exceptions, or framework. |
| 2026-09-14 | Slice 5 implementation review: platform truthfulness and YAGNI | PASS | Metadata, README, repository map, and [SEM-4] agree with unchanged [EVC-8.2]; built-wheel metadata and supported-host snapshot/cache tests passed. No Windows runtime promise or process-freezing test was added. |
| 2026-09-14 | Fresh-eyes final range review | PASS after documentation correction | Corrected three stale `active` backlinks and made the planning-only verification statement historical. The combined targeted suite passed; no code correctness or YAGNI blocker remained. |

Existing engineering principles already require bounded scope and checking
producer/consumer changes together. No new process rule or test is needed;
this revision corrects the application of those principles.

## Execution Log

| Slice | Status | Verification |
|---|---|---|
| 1. Invocation-owned publication destinations | complete | Removed all three config keys and projections; filesystem/blob rejection, external-sentinel, explicit-output, focused config/CLI, documentation, and self-corpus checks pass. |
| 2. Semantic cache/source overlap | complete | One mutual overlap predicate rejects equality and either containment direction before snapshot, cache, or provider work; the `cache_path = "."` reverse-containment reproduction preserves source and creates no derived cache namespaces. |
| 3. Coverage text issues | complete | Coverage text has one renderer that includes typed issues via the shared issue-line formatter; BSN009 names the changed key, event, repository-config acknowledgment, trailer, and rerun action. Renderer and public-ratchet tests pass. |
| 4. Atomic check publication | complete | Check delegates to the existing fsynced same-directory replacement owner; missing parents succeed, a regular-file parent yields exit 2, and injected replacement failure preserves the prior complete report and removes staging. Acceptance probe 11 uses the portable failure fixture. |
| 6. Distribution smoke tests | complete | The release build resolves exactly one wheel and sdist, installs each exact artifact in a separate fresh environment outside the checkout, proves import provenance, and runs installed version, alignment-guide, and self-check commands before attestation. Static order checks and local artifact smoke pass. |
| 7. Exact architecture ranks | complete | Every non-`__init__` package module has one reviewed rank; dynamic set equality rejects missing and stale entries, while the existing upward-import and private-cross-rank gates pass without exceptions or fixed module counts. |
| 5. Truthful platform declaration | complete | Package metadata, README, repository map, and [SEM-4] now agree with the unchanged POSIX capture boundary; the existing unsupported-capability and cache hard-link tests pass, and built wheel metadata carries only the POSIX/macOS classifiers. |

## Fresh-Eyes Review

The final reviewer receives the baseline SHA, the seven-commit range, this
plan, and the governing spec sections. They should look first for: retained
config authority through another field; provider/cache effects before mutual
overlap rejection; issue data present only in JSON; a remaining direct final
write; support claims broader than the unchanged POSIX capture boundary; an
attested distribution that was not the one installed; and any live package module
missing from `_LAYER_RANK`.

## Planning Verification

The engineering review checklist was used during initial drafting; the
revision is governed by the repository plan rules and the owner's minimal
implementation constraint. No skill-specific process is an implementation
dependency.

Revision verification on 2026-09-14:

- Read-only evaluation of the revised rank map against the current import
  graph: no unranked or stale entries, no upward or private cross-rank edges;
  the planned renderer import is allowed at rank 2.
- `python bin/check-doc-paths`: PASS.
- `python bin/check-dom15-fixtures`: PASS.
- `git diff --check`: PASS.
- `uv run backstitch check --repo-root .`: exit 0, zero errors, warnings,
  and infos (128 sections, 421 mappings, 587 code refs, 1175 edges).

At plan approval these were planning checks: product code, specs, and workflows
had not yet changed. Completion evidence is recorded in the execution and
review logs above. No native Windows support or hosted release run is claimed.

## Completion Verification

Completed on 2026-09-14:

- Ruff formatting and lint, suppression-index validation, and configured mypy
  passed across the repository.
- The combined targeted suite and `tests/acceptance` passed. The hermetic CI
  suite passed except for the separately checked sibling Weft corpus debt
  baseline, whose current external checkout has a changed error set.
- Both release distributions built and were installed separately outside the
  checkout; import provenance, version, alignment-guide, and repository-check
  smokes passed. The built wheel contains the POSIX and macOS classifiers and
  not the OS-independent classifier.
- The deterministic self-corpus check passed with zero errors and warnings.
- Actual configured semantic analysis was attempted with the stale host
  `LLM_MODEL=gpt-5.5` override removed so repository `gpt-5.6-luna` at `max`
  applied. It reached the provider but exited `2`: four responses were not
  valid JSON, then the serial run exhausted its 1,800-second runtime budget
  during analysis-lock waits. This is an external/runtime residual, not a
  skipped or mocked semantic check and not evidence of a seven-slice
  regression.

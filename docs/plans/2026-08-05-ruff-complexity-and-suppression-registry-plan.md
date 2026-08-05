# Ruff Complexity And Suppression Registry Implementation Plan

Date: 2026-08-05

Status: active; T1-T10 implemented and independently reviewed; final gates in progress

Class: 5+P. This changes a repository-wide required quality gate, its governing
spec, CI and release enforcement, and the approved-suppression process.

Plan type: implementation with spec revision

Hardening: required. Activation crosses configuration, source, generated
documentation, CI, and release-helper boundaries and must be atomic.

## Goal

Replace Backstitch's ineffective McCabe ceiling of 39 with an enforced Ruff
`C901` ceiling of 10. Reduce complexity where an owner-local seam improves the
design, register the branches that protect real contracts or lifecycles, and
make every remaining suppression mechanically discoverable, justified, and
checked against the active spec.

The score is a review trigger, not a design verdict. The work must preserve
cohesion, failure precedence, captured-byte ownership, publication order, and
state-machine locality even when that means retaining a complex function.

## Requested Outcomes

1. Pin Ruff exactly in the manifest and lock, then prove the running binary,
   manifest, and lock agree before recording any baseline.
2. Make `C901` part of the normal configured Ruff selection at
   `max-complexity = 10`; remove the separate threshold-39 CI command.
3. Cover all intended Python entry points, including the extensionless tools in
   `bin/`, and prove that inventory against Ruff discovery.
4. Refactor P1 and defensible P2 findings through named ownership seams with
   real behavior tests. Reverse any extraction that harms locality.
5. Give every retained C901 finding a source pointer to a reviewed registry
   group whose rationale names the protected invariant, real proof, rejected
   alternative, approval, cardinality, and lifetime.
6. Generate and check the suppression index from source plus the active spec.
   Stale, missing, duplicate, unknown, miscounted, or unjustified entries fail.
7. Enforce the same policy locally, in CI, and in release prechecks.
8. Record the final policy and ownership boundaries in implementation docs.

## Premises And Decisions

- The measured complete threshold-10 baseline is **152 findings**:
  `138 backstitch + 4 bin + 10 tests`. The first audit reported 150 because
  Ruff's normal discovery omitted extensionless `bin/` scripts. Explicitly
  adding the three intended tools finds two more C901 diagnostics.
- The initial disposition audit classifies those 152 findings as **22 P1, 27
  P2, and 103 P3**. P1 is a clear seam, P2 is plausible but conditional on a
  locality review, and P3 protects a cohesive contract or lifecycle.
- The implementation will not aim for zero suppressions. It will aim for zero
  unaudited suppressions and lower complexity where that improves ownership.
- Ruff's currently locked and executing version is `0.15.21`, while the
  manifest says `ruff>=0.12`. T2 changes the manifest to `ruff==0.15.21` and
  regenerates the lock before any activation counts are frozen.
- The normal configured rule families remain `E`, `W`, `F`, `I`, `B`, `C4`,
  and `UP`, with `C901` added explicitly. Expanding to all stable Ruff defaults
  is a separate change. Taut showed that combining the two makes the baseline
  and rollback story harder to audit.
- Lint discovery and formatter scope remain separate. Use one canonical lint
  vector, `ruff check . bin/check-doc-paths bin/check-dom15-fixtures
  bin/coalesce-check`, in local checks, policy tests, CI, release prechecks,
  and generator inventory. Do not use Ruff `extend-include`: Ruff 0.15.21 also
  applies it to formatting, which would expand formatter scope.
- Backstitch has a root lock. Repository commands use
  `uv run --frozen --no-sync`; CI may install first and then use `uv run`.
- The generator is ported from Taut's final symbol-keyed implementation. Do
  not port or recreate the earlier line-keyed design.
- A full state-machine inventory is not a prerequisite. A retained or changed
  finding needs the real transition, lifecycle, or contract proof relevant to
  that finding.

## Source Documents

Governing Backstitch sources:

- `docs/specs/02-backstitch-core.md` [SC-10], [SC-17]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11], [DOM-15]
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`

Reference implementations and plans:

- `../simplebroker/docs/plans/2026-07-29-complexity-and-state-machine-hardening-plan.md`
- `../simplebroker/docs/plans/2026-07-29-ruff-lint-expansion-plan.md`
- `../simplebroker/docs/plans/2026-07-30-ruff-suppression-index-generator-plan.md`
- `../simplebroker/docs/implementation/07-complexity-and-state-machine-map.md`
- `../simplebroker/bin/ruff_suppression_index.py`
- `../taut/docs/plans/2026-08-04-ruff-complexity-and-suppression-registry-plan.md`
- `../taut/docs/plans/artifacts/2026-08-04-ruff-suppression-activation-ledger.tsv`
- `../taut/docs/implementation/08-complexity-and-suppression-policy.md`
- `../taut/bin/ruff_suppression_index.py`
- `../taut/tests/test_ruff_policy.py`
- `../taut/tests/test_ruff_suppression_index.py`
- Taut implementation commits `9ec9d87` (complexity) and `eabc272` (separate
  stable-default expansion)

## Context And Key Files

Read before editing:

- `pyproject.toml` and `uv.lock`: Ruff dependency, discovery, selected rules,
  and McCabe threshold.
- `.github/workflows/ci.yml`: current normal lint plus redundant threshold-39
  side lane.
- `bin/release.py` and `tests/test_release_script.py`: release precheck command
  ownership and exact command-vector tests.
- `docs/specs/02-backstitch-core.md` [SC-10], [SC-17]: acceptance and internal
  architecture authority. T4 adds [SC-17.1] here, not in a parallel spec.
- `backstitch/python_refs.py`, `backstitch/resolver.py`, and
  `tests/test_traceability_reducer.py`: source backlinks are part of
  Backstitch's own traceability graph, so the [SC-17.1] mapping must list every
  path carrying a live marker.
- Taut's final generator and tests: reuse symbol identity, atomic replacement,
  exit semantics, hostile-input coverage, and live-spec seam. Do not copy its
  project paths, rule scope, environment commands, or line-keyed history.
- The owner modules and closest real tests named by the activation ledger:
  these are the behavior authorities for refactor slices.

Files created by this plan:

- `docs/plans/artifacts/2026-08-05-ruff-suppression-activation-ledger.tsv`
- `bin/ruff_suppression_index.py`
- `tests/fixtures/ruff-enabled-rules.txt`
- `tests/fixtures/ruff-excluded-python.tsv`
- `tests/test_ruff_policy.py`
- `tests/test_ruff_suppression_index.py`
- `docs/implementation/10-ruff-complexity-and-suppression-policy.md`

Files changed at activation include the governing spec, Ruff config and lock,
all source files with live pointers, CI, release prechecks/tests, the registry,
and generated index. Later refactor slices touch only their named owners,
closest proofs, registry/index, and [SC-17.1] mapping.

## Spec Baseline

- `b380859eaf75ed69bd59ff07a038c0961dc899d7`:
  `docs/specs/02-backstitch-core.md` and
  `docs/specs/01-development-documentation-operating-model.md` at plan
  authoring time.
- The active [SC-17] contract at this baseline says Ruff enforces a McCabe
  ceiling of 39 over production code. The proposed delta below becomes
  governing only when T4 promotes it atomically with the implementation.
- T4 must record a promotion baseline identifier here before later slices make
  compliance claims.

Promotion baseline: commit `25759b7` (`Activate Ruff complexity suppression
policy`).

## Proposed Spec Delta

Promotion strategy: **B, atomic activation**. Configuration, exact source
pointers, registry rows, generated index, tests, CI, release prechecks, and the
spec text below activate in one reviewable slice. No intermediate state may
make C901 required while suppressions are ungoverned, or publish registry rows
that do not point to live source.

| Spec file | Strategy | Sections touched |
|---|---|---|
| `docs/specs/02-backstitch-core.md` | B, atomic | [SC-17], new [SC-17.1], Related Plans |

### [SC-10] replacement bullet

Replace `configured C901 verification over the same production paths as CI`
with:

> - configured Ruff policy tests proving the exact manifest/lock/runtime pin,
>   the reviewed lint discovery surface including intended extensionless Python
>   entry points, configured `C901` at 10, active-rule raw inventory, and the
>   checked [SC-17.1] suppression registry through the same canonical lint
>   vector used by CI and release prechecks

### [SC-17] replacement paragraph

Replace the paragraph beginning `Executable gates enumerate` with:

> Executable gates enumerate the internal import graph and enforce zero
> strongly connected components larger than one. Ruff enforces McCabe
> complexity `C901` at a ceiling of 10 over every lint-eligible tracked Python
> source and intended extensionless Python entry point. The score is a review
> trigger, not a design verdict. A function above the ceiling is permitted only
> through the reviewed, source-linked suppression process in [SC-17.1]. File
> length alone remains insufficient reason to split an owner.

### [SC-17.1] insertion after [SC-17]

Insert the following text before `## Related Plans`:

> ### 17.1 Repository Complexity And Suppression Gate [SC-17.1]
>
> Ruff's version is exact-pinned in the development manifest and lock. The
> repository proves that the executing binary, manifest pin, and lock resolve
> to the same version before deriving rule or suppression inventories.
>
> The normal configured Ruff check includes `C901` with
> `lint.mccabe.max-complexity = 10`. Lint discovery covers every tracked Python
> source that is not inside an explicit, test-owned fixture-input exclusion and every intended
> extensionless Python entry point. Formatter scope is independent and does not
> expand merely because lint discovery expands.
>
> A governed source suppression has the form
> `# noqa: <RULES> approved [SC-17.1] RUFF-SUP-NNN exception`. Its group ID must
> exist exactly once in the registry below. The generated index identifies a
> suppression by `repo-relative path::qualified symbol`; line numbers are
> presentation data, not identity. Each source pointer must map to exactly one
> active Ruff diagnostic for the declared rule, except when the registry
> explicitly declares and tests a reviewed cardinality greater than one.
>
> A registry row records the group ID, rule set, approved source-directive
> count, approved raw-diagnostic counts per rule, temporary or permanent
> lifetime, protected invariant, real proof, rejected alternatives, and
> approval. Blank, placeholder, circular, or score-only rationales are invalid.
> Temporary rows name a deterministic removal or re-evaluation task. Permanent
> rows explain why splitting the owner would weaken locality or correctness and
> cite the real test or acceptance proof.
>
> The checked generator derives the active source inventory, validates every
> registry/source relationship, and rewrites only the generated region below.
> It fails closed on a missing or duplicated registry heading, malformed
> markers, unknown groups or rules, stale symbols, duplicate pointers,
> cardinality drift, unregistered raw diagnostics, or source/spec disagreement.
> The generator must prove that the exact registry heading exists once in this
> active spec; agreement between a fixture and a ported constant is not proof.
>
> The global raw inventory covers diagnostics emitted by the active configured
> Ruff rule families when `noqa` is ignored. It does not claim to inventory
> textual `noqa` comments for disabled rule families. Per-file ignores, global
> baseline allowlists, silent threshold inflation, and unregistered `noqa`
> directives are not valid substitutes for a registry row.
>
> CI and release prechecks run the normal Ruff check and the suppression-index
> check. A change to the Ruff pin, discovery surface, active rules, threshold,
> source markers, registry, or generator requires recomputing the raw inventory
> and reviewing every changed disposition.
>
> #### Approved Ruff Suppression Registry
>
> | Group | Rules | Approved directives | Approved raw diagnostics by rule | Lifetime | Protected invariant | Real proof | Rejected alternatives | Approval |
> |---|---|---:|---|---|---|---|---|---|
> | _Rows promoted from the independently frozen activation ledger_ | | | | | | | |
>
> <!-- BEGIN GENERATED RUFF SUPPRESSION INDEX -->
> <!-- Generated rows are owned by bin/ruff_suppression_index.py. -->
> <!-- END GENERATED RUFF SUPPRESSION INDEX -->
>
> _Implementation mapping_:
> - `.github/workflows/ci.yml`
> - `pyproject.toml`
> - `uv.lock`
> - `bin/ruff_suppression_index.py`
> - `bin/release.py`
> - `tests/test_ruff_policy.py`
> - `tests/test_ruff_suppression_index.py`
> - `backstitch/alignment_eval.py`
> - `backstitch/analysis_llm.py`
> - `backstitch/analysis_packets.py`
> - `backstitch/analysis_results.py`
> - `backstitch/artifact_contracts.py`
> - `backstitch/cli.py`
> - `backstitch/code_parser.py`
> - `backstitch/coverage_application.py`
> - `backstitch/diagnostics.py`
> - `backstitch/doctor.py`
> - `backstitch/evidence_discovery.py`
> - `backstitch/evidence_summary.py`
> - `backstitch/exclusions.py`
> - `backstitch/git_baseline.py`
> - `backstitch/intent_coverage.py`
> - `backstitch/intent_history.py`
> - `backstitch/markdown_specs.py`
> - `backstitch/obligation_api.py`
> - `backstitch/obligation_runtime.py`
> - `backstitch/obligations.py`
> - `backstitch/packet_application.py`
> - `backstitch/python_refs.py`
> - `backstitch/repository_snapshot.py`
> - `backstitch/resolver.py`
> - `backstitch/semantic_analysis.py`
> - `backstitch/semantic_application.py`
> - `backstitch/semantic_cache.py`
> - `backstitch/semantic_eval.py`
> - `backstitch/semantic_eval_reports.py`
> - `backstitch/semantic_evidence.py`
> - `backstitch/semantic_policy.py`
> - `backstitch/semantic_reports.py`
> - `backstitch/semantic_verification.py`
> - `backstitch/settings.py`
> - `bin/check-dom15-fixtures`
> - `bin/coalesce-check`
> - `tests/live/test_live_llm.py`
> - `tests/semantic_eval/v3/generate_qualification_candidate.py`
> - `tests/test_architecture.py`
> - `tests/test_canonical_owners.py`
> - `tests/test_semantic_reports.py`
> - `tests/test_semantic_verification.py`

The unbracketed `RUFF-SUP-NNN` token is governance metadata, not a Backstitch
spec reference. T4 recomputes the exact deduplicated source-path portion before
promotion and records any difference as a proposed-delta revision. Each
bracketed `[SC-17.1]` source backlink must have its exact path in the promoted
implementation mapping. Later slices update that mapping when their last live
pointer is removed or moved.

Append this Related Plans entry:

> - `docs/plans/2026-08-05-ruff-complexity-and-suppression-registry-plan.md`
>   (active implementation plan; [SC-17], [SC-17.1])

## Current Structure And Measured Baseline

Current enforcement is split and ineffective:

- `pyproject.toml` selects `E`, `W`, `F`, `I`, `B`, `C4`, and `UP`; it sets
  `max-complexity = 39` but does not select `C901` normally.
- `.github/workflows/ci.yml` runs a normal `ruff check .`, then a separate
  `ruff check backstitch bin --select C901`. The latter finds nothing at 39.
- `bin/release.py` runs only the normal configured Ruff check, so release
  prechecks do not enforce C901 today.
- There is no suppression registry, generator, policy fixture, or direct Ruff
  policy test.
- The executing and locked Ruff is 0.15.21; the manifest range is not exact.

Measured from the baseline SHA with Ruff 0.15.21:

```text
threshold-10 complete C901 inventory: 152
  backstitch/: 138
  bin/:          4
  tests/:       10

initial dispositions:
  P1 clear seam:                    22
  P2 conditional owner-local seam: 27
  P3 retained contract/lifecycle: 103

raw diagnostics under currently active configured rules:
  F401: 1 (backstitch/doctor.py)
```

Ruff `--show-files .` reports 165 entries: 164 Python files plus
`pyproject.toml`. The repository tracks 263 `*.py` files because 99 test-owned
fixture-input files are deliberately excluded from lint. Many are hash-frozen
or adversarial; every excluded tree still needs an exact role/proof owner.
Normal discovery currently omits
these intended extensionless Python tools:

- `bin/check-doc-paths`
- `bin/check-dom15-fixtures`
- `bin/coalesce-check`

The complete audit therefore uses the canonical lint vector with those three
explicit paths. Two of the three add C901 findings:
`check-dom15-fixtures::check` at 11 and `coalesce-check::main` at 14. The
expected inventory is 167 Python/shebang files and Ruff's extra
`pyproject.toml` entry, for 168 combined `--show-files` rows. The test derives
membership from Git plus the reviewed exclusion patterns; the counts are an
assertion, not the source of truth.

Textual `noqa` comments also mention disabled families such as `BLE001`,
`N802`, and `S310`. They are not part of the current active-rule raw inventory.
T2 must inventory them separately so future rule activation cannot convert
them into unaudited suppressions.

### Required Reading Comprehension Gates

Before editing, the implementer must answer in the plan review record:

1. Why can a C901 extraction that lowers a score make Backstitch less correct?
   Name one captured-byte, cache-lease, publication-order, or first-error
   example from the disposition ledger.
2. Why does `ruff check .` not cover the full intended lint surface, and why
   does that not imply the same paths belong in formatter scope?
3. Which data is human authority, which data is source authority, and which
   region is generator-owned under [SC-17.1]?
4. What exact evidence is required before a temporary suppression becomes
   permanent?
5. Why must registry heading uniqueness be checked against the active spec
   rather than only against a fixture or copied constant?

## Initial C901 Disposition Ledger

The completed read-only audit is the input to T3A. T2 must materialize it as
`docs/plans/artifacts/2026-08-05-ruff-suppression-activation-ledger.tsv`, one
row per raw diagnostic, in deterministic `rule, path::qualified_symbol` order.
It contains 152 C901 rows plus the existing F401 importability-probe row.
Required columns are:

```text
group_id  path_symbol  rules  rule_raw_counts  directive_count  score
priority  target_slice  lifetime  protected_invariant  real_proof
rejected_alternative  approval  freeze_status
```

The row total must be 153. The C901 subset must be 152 with priority totals
exactly 22/27/103; the F401 row is a permanent importability-probe suppression
owned by `doctor.py::_check_llm_import` and proved by the real doctor suite.
Repeated group-level fields must agree across every member row. A changed Ruff
result blocks activation until the plan's baseline and all affected rows are
revised.

Natural implementation slices from the audit:

| Slice | Scope | Audit direction |
|---|---|---|
| A | alignment fixture ownership | `_phase_ids` is P1; five P2 projections are conditional; retain strict fixture, graph, argv, and envelope validators |
| B | settings and configuration | parse closed substructures in-module; preserve precedence, provenance, path anchoring, unknown-key order, and one final settings owner |
| C | analyzer/verifier cache lifecycle | introduce named provider-call owners; never split lease acquisition, arbitration, yield lifetime, cleanup, or reservation ownership |
| D | semantic analysis/application | extract named preflight, execution, and publication phases only after cache owners settle |
| E | semantic evaluation and reports | phase the eval runner; preserve authoritative recomputation and every first-error priority |
| F | CLI adapters | thin analyze/eval/main boundaries while preserving lazy imports, config resolution count, public exit mapping, and traceback containment |
| G | evidence/history/coverage projections | owner-local typed projection helpers only; keep captured bytes, parser ownership, issue order, and diagnostic firing tests real |
| H | test and repository tools | improve helper-heavy tests where locality gains; retain end-to-end proxy/lifecycle tests where their branches are the proof |
| I | P3 registry families | group cohesive artifact schemas, parser grammars, graph classifiers, filesystem/Git lifecycles, resolver phases, and report validators by shared rationale and proof |

Every P1 and P2 row names exactly one slice and one re-evaluation task. P3 is
not automatic approval: T3A must freeze exact group membership, cardinality,
rationale, proof, rejected split, approval, and lifetime before source markers
exist.

## Invariants And Constraints

### Static Analysis And Approval

- `C901` is enforced only through normal rule configuration and the canonical
  lint path vector. No CI-only rule select,
  per-file ignore, global baseline file, threshold inflation, or broad path
  exclusion may hide a finding.
- The exact Ruff pin, discovery fixture, source markers, registry, and
  generated index must agree. Any drift fails closed.
- Every active raw diagnostic, including the existing F401 importability probe,
  is either fixed or represented by a valid live marker and registry row. The
  raw inventory is recomputed after each slice.
- Registry group IDs and meanings are stable after T3A. Reusing a retired ID
  for a different symbol or rationale is forbidden.
- Temporary P1/P2 rows identify their removal slice. They cannot be made
  permanent merely because a refactor is difficult.
- A P3 row requires a nonblank protected invariant, real proof, rejected
  alternative, and independent approval.

### Behavior And Architecture

- No public CLI command, option, output bytes, exit code, report schema,
  diagnostic code, configuration key, cache identity, provider request,
  filesystem rule, or release behavior changes.
- Production paths and real parsers remain the test path. Do not create a
  test-only orchestration, duplicate validator, parallel resolver, or generic
  framework to lower a score.
- Preserve current first-error precedence in strict validators and public
  adapters.
- Preserve captured-byte ownership and no-reopen rules.
- Preserve cache guard/lease lifetimes, provider-call budgets, reservation
  release, cleanup ownership, and primary-failure precedence.
- Preserve result-before-report and all-or-nothing publication ordering.
- File size is not an extraction criterion. Helpers must own a coherent value,
  phase, or lifecycle, not shuttle most of a parent's locals.
- No new runtime or development dependency is introduced.

### Generator And Failure Paths

- `path::qualified_symbol` is stable identity. A line number may move without
  changing identity. A same-symbol remove/add replacement remains a known
  residual and requires review of the raw diff.
- The generator parses real Ruff JSON and real Python source. Tests may replace
  subprocess execution only at the boundary that supplies frozen Ruff JSON;
  source parsing, marker parsing, registry parsing, matching, and rendering
  stay real.
- `--check` never mutates. Rewrite mode uses an atomic same-directory replace
  and leaves the prior spec intact on validation or write failure.
- The tool owns only the generated marker region. Human registry prose and
  rows are never rewritten.
- Malformed Ruff JSON, duplicate keys where parsed, unknown rules, wrong paths,
  ambiguous symbols, duplicate headings/markers, and partial writes are fatal.

## Anti-Mocking Rules

- Policy tests invoke the pinned Ruff binary with the repository config and
  compare real JSON output. Do not mock rule selection or file discovery.
- Refactor tests use existing public or owner-level behavior paths. A helper
  unit test may supplement but never replace the closest real proof named in
  the ledger.
- Filesystem, Git, cache, provider-adapter, and artifact validators keep their
  existing real seams. Do not replace the protected lifecycle with a fake to
  make an extraction pass.
- CI/release command tests assert the exact command vectors and execute the
  focused local checks where practical.

## Rollout, Rollback, And One-Way Doors

T1 through T3A are additive and non-enforcing. They can be reviewed and
reworked without changing developer or CI behavior.

T4 is the only activation point. Land its spec, config, source markers,
registry, generated index, tests, CI, and release-helper changes together.
Partial activation is prohibited.

After T4, each refactor slice removes or updates its own temporary markers and
registry rows in the same change. A slice is reversible by reverting its
owner-local code/tests/registry delta. Do not lower the threshold, broaden an
ignore, or detach the generator to make a revert green.

The one-way door is social rather than data-destructive: once IDs are cited in
source and review history, changing their meaning destroys audit continuity.
T3A therefore freezes IDs before source insertion. Retire IDs; never recycle
them.

If T4 cannot be made atomic, stop. Keep the old threshold-39 behavior active
until a complete activation change is ready.

## Dependency-Ordered Tasks

### T1: Independent Plan, Delta, And Disposition Review

1. Review this plan against SimpleBroker and Taut, with special attention to
   the improvements listed in Premises and Decisions.
2. Verify the three area-audit totals and challenge the proposed P1/P2 seams
   for locality. Exact row and group review occurs after T2 materializes the
   canonical artifact and before source directives in T3A.
3. Review the exact [SC-17]/[SC-17.1] delta and promotion strategy.
4. Record reviewer, evidence, findings, and dispositions in Review Log.

Gate: no unresolved blocker; exact spec text and slice ownership approved.

### T2: Freeze Ruff And Discovery Baseline

Add and make green the non-activation tests in `tests/test_ruff_policy.py`:

- manifest Ruff requirement is exact;
- manifest, lock, and `ruff --version` agree;
- tracked lint-eligible Python plus intended extensionless scripts equals the
  reviewed discovery inventory after explicit fixture exclusions;
- every excluded tracked Python file belongs to an exact reviewed fixture tree
  with a named role/proof owner;
- formatter targets remain unchanged;
- current active-rule raw inventory is explicit and uses `--ignore-noqa`;
- textual no-qa directives for disabled families are separately inventoried.

Then:

1. Change the dev dependency to `ruff==0.15.21` and update `uv.lock`.
2. Add `tests/fixtures/ruff-enabled-rules.txt` from the pinned binary.
   Derive it by parsing `linter.rules.enabled` from
   `uv run --frozen --no-sync ruff check --show-settings
   backstitch/__init__.py`, sort one exact rule code per line, and have the
   policy test rerun that command and compare the set. A hand-maintained family
   list is not the fixture oracle.
3. Define the canonical lint vector with `.`, `bin/check-doc-paths`,
   `bin/check-dom15-fixtures`, and `bin/coalesce-check`; prove its combined
   discovery contains the intended extensionless Python tools without changing
   formatter scope.
4. Recompute threshold-10 JSON. If it is not exactly 152 with the recorded
   distribution, stop and revise the plan and ledger.
5. Materialize the 153-row activation ledger artifact: 152 audited C901
   diagnostics plus the reviewed F401 importability-probe suppression.

The discovery test subtracts only these existing reviewed patterns:
`tests/fixtures/**`, `tests/**/fixtures/**`, and
`tests/semantic_eval/v1/fixture/**`. It must map every excluded file to an exact
reviewed fixture tree and cite the behavior, manifest-hash, or drift test that
owns that tree's input role. Where a manifest declares hashes but no current
test verifies them, T2 adds the missing recomputation proof. A raw count of 99
or proof-file existence alone is not enough to approve an exclusion.

Do not add skipped, expected-failure, or knowingly red C901/10 assertions in
this slice. T4 adds those assertions immediately before the atomic config
change and makes them green in the same slice.

Gate: pin/discovery tests green; ledger totals and command outputs recorded.

### T3: Port The Symbol-Keyed Generator Under Red Tests

Create `bin/ruff_suppression_index.py` by porting Taut's final symbol-keyed
implementation and adapting only Backstitch paths, [SC-17.1] syntax, and locked
command shape.

Create `tests/test_ruff_suppression_index.py` with red tests for:

- a valid multiple-group registry and deterministic generated output;
- exact `path::qualified_symbol` ownership for nested and decorated functions;
- line movement without identity drift;
- missing, duplicate, or wrong registry heading in spec fixtures;
- missing/duplicate generated region markers;
- unknown or duplicate group IDs, rules, symbols, and source pointers;
- cardinality underflow/overflow and unregistered raw findings;
- blank/placeholder rationale, proof, alternatives, approval, or lifetime;
- temporary rows without a named task;
- malformed marker grammar and prose-only near misses;
- malformed Ruff JSON, nonzero Ruff exit, non-UTF-8 source, and path escape;
- `--check` no-mutation and atomic rewrite failure;
- deterministic byte-identical output across two runs.

Gate: focused generator tests green against fixtures; production rewrite is
still not run.

### T3A: Freeze And Review Exact Activation Groups

1. Independently review every ledger row and proposed grouping.
2. Freeze in the activation-ledger TSV: group IDs, exact member symbols, rule
   set, source-directive count, per-rule raw counts, rationale, real proof,
   rejected alternative, approval, and lifetime. This TSV is the pre-activation
   authority from which T4's human registry rows are promoted.
3. Require deterministic T5-T9 task names for every temporary P1/P2 row.
4. Combine rows only when members genuinely share one protected invariant and
   proof. Do not group merely by file or score.
5. The independent reviewer recommends dispositions but does not grant final
   approval. The repository owner approves the frozen group fields. Record an
   owner-authored thread reference, signed review record, or owner commit in
   each group's `approval` field. If that authorization is absent, pause before
   T4 rather than self-approving.
6. Record all audit changes in the plan Revision Log and preserve old IDs as
   retired if already reviewed.

Gate: 153 active raw diagnostics accounted for exactly once (152 C901 plus one
F401); repeated group fields agree; independent freeze PASS; no source
directives yet.

### T4: Atomic Spec, C901, Registry, And Enforcement Activation

In one slice:

1. Promote the proposed [SC-17]/[SC-17.1] text and Related Plans backlink.
2. Add `C901` to normal Ruff select and set the ceiling to 10.
3. Insert exact source directives for all retained or temporary findings.
4. Promote frozen human registry rows and run the generator rewrite.
5. Make `tests/test_ruff_policy.py` activation assertions green. Add the live
   active-spec seam test here: it reads `docs/specs/02-backstitch-core.md` and
   asserts the exact registry heading exists once. Agreement between a fixture
   and a ported constant is insufficient.
6. Change CI dependency installation to `uv sync --frozen --extra dev`, then
   run `uv run --frozen --no-sync ruff check . bin/check-doc-paths
   bin/check-dom15-fixtures bin/coalesce-check` followed immediately by
   `uv run --frozen --no-sync python bin/ruff_suppression_index.py --check`.
   Remove the separate threshold-39 step.
7. In `bin/release.py`, set `RUFF_CHECK_COMMAND` to the same exact frozen,
   no-sync canonical lint vector. Add
   `RUFF_SUPPRESSION_CHECK_COMMAND = ("uv", "run", "--frozen", "--no-sync",
   "python", "bin/ruff_suppression_index.py", "--check")` immediately after it
   in `build_precheck_commands()`. Strengthen release tests for exact order and
   command bytes.
8. Record the promotion baseline identifier in Spec Baseline.

Gate: normal Ruff, raw inventory, generator check, focused tests, CI command
shape, release-helper tests, and self-corpus gate all pass together.

### T5: Settings And Configuration Ownership

Implement the settings P1 rows first: assembly/provenance preparation, request
constraint parsing, raw-path expansion, top-level/subtable parsing,
unknown-key table inventories, and one-row structured suppression parsing.
Attempt P2 blob-chain, model-descriptor, and verify-settings seams only when
they keep precedence and provenance local. Retain the ratchet provenance and
closed analyze parser P3 rows.

Gate: full settings/config parity/semantic settings/CLI config suites; raw
C901 diff; independent locality review; registry updated atomically.

### T6: Cache And Semantic Execution Ownership

1. Introduce named analyzer and verifier provider-call owners while preserving
   budgets, lazy construction, reservation release, error translation, and
   per-item containment.
2. Share only pure read-only preflight between inspection and execution.
3. Refactor evidence-stable preparation and `_run_semantic_analysis` into
   named owner-local phase values after cache changes settle.
4. Keep lease acquisition, second-read arbitration, yield lifetime, reverse
   cleanup, and publication order under one owner.

Gate: full semantic cache, verification, analysis, and application suites;
deadline and race probes; raw C901 diff; independent lifecycle/locality review.

### T7: Evaluation, Reports, And Artifact Contracts

1. Phase `run_semantic_eval` without changing temporary lifetimes, call order,
   global budgets, authoritative revalidation, or atomic publication.
2. Extract only the reviewed report seams: qualification details, source audit
   phases, packet report row builders/binders, and current authoritative report
   binding.
3. Keep discriminator-specific artifact validators and legacy schema readers
   explicit unless a typed owner reduces state without weakening first-error
   order.

Gate: semantic eval/report/artifact suites, all first-error-priority tests, raw
C901 diff, and independent artifact-boundary review.

### T8: Alignment, CLI, Evidence, And Coverage Owners

1. Implement alignment's per-fixture `_phase_ids` seam, then conditionally
   attempt reviewed gold/plan/declaration/candidate/run projections.
2. Thin `_cmd_analyze`, `_cmd_eval`, and `main` while retaining lazy imports,
   one config resolution, public exits, and traceback containment.
3. Attempt owner-local evidence summary, intent history, coverage diagnostic,
   and obligation inventory projections. Keep production parsers and captured
   snapshots real.

Gate: closest real suites named in the ledger, every enumerable diagnostic
firing test, raw C901 diff, and independent locality review.

### T9: Tests, Repository Tools, And P3 Proof Closure

1. Review complex tests and extensionless tools for genuine helper seams.
   Preserve end-to-end branch structure when it is the proof being asserted.
2. Re-run the real test/probe and re-check the rejected split already frozen
   for every P3 group. T9 does not invent missing P3 approval after activation.
3. Convert no temporary row to permanent without independent approval.
4. Remove resolved rows and regenerate the index.

Gate: no orphan temporary task, blank rationale, stale marker, or unproved
permanent row.

### T10: Post-Refactor Locality Remediation

Independently review every P1/P2 extraction without using score reduction as
evidence. Specifically look for helpers that:

- pass most parent locals or mutable collections;
- split one lease, filesystem transaction, parser state, validation order, or
  publication lifecycle across owners;
- duplicate schema or diagnostic vocabulary;
- make failure precedence implicit;
- force a reader to jump files to understand one decision table.

Reverse shallow extractions and register the restored finding when cohesion is
better. Taut restored two C901 findings at this stage; an increased final count
can be the correct result.

Gate: locality review PASS with every reversal and registry change recorded.

### T11: Documentation, Traceability, And Closure

1. Add `docs/implementation/10-ruff-complexity-and-suppression-policy.md` explaining
   authority, discovery, generator ownership, approval, update workflow,
   rollback, and why suppression count is not the success metric.
2. Add it to `docs/implementation/00-implementation-index.md`.
3. Align [SC-10] acceptance language, [SC-17]/[SC-17.1], implementation maps,
   repository maps, CI/release docs, and this plan's evidence.
4. Run all final gates and independent final review.
5. Record commit evidence and close the plan only after `git log` proves the
   implementation is committed.

## Testing Plan

### `tests/test_ruff_policy.py`

Tests exact pin agreement, configured C901/10, enabled-rule fixture, complete
lint discovery including extensionless tools, exact test-owned fixture exclusions,
unchanged formatter scope, normal clean lint, raw active-rule inventory, and
separate textual-disabled-rule inventory.

### `tests/test_ruff_suppression_index.py`

Tests the symbol-keyed registry/source/Ruff join, active-spec seam, rationale
schema, cardinality, hostile inputs, deterministic rendering, check mode, and
atomic replacement. Every failure mode added to the generator needs a firing
test.

### Refactor Proof

Each ledger row names the closest real proof. A refactor slice must run that
proof before and after the change, capture the raw C901 delta, and pass an
independent locality review. New helper tests do not replace lifecycle,
artifact, CLI, or acceptance tests.

## Verification And Gates

Baseline and focused policy:

```bash
uv run --frozen --no-sync ruff --version
uv run --frozen --no-sync ruff check --show-files . bin/check-doc-paths bin/check-dom15-fixtures bin/coalesce-check
uv run --frozen --no-sync ruff check --select C901 --config 'lint.mccabe.max-complexity=10' --output-format json . bin/check-doc-paths bin/check-dom15-fixtures bin/coalesce-check
uv run --frozen --no-sync ruff check --ignore-noqa --output-format json . bin/check-doc-paths bin/check-dom15-fixtures bin/coalesce-check
uv run --frozen --no-sync pytest tests/test_ruff_policy.py tests/test_ruff_suppression_index.py -q
uv run --frozen --no-sync python bin/ruff_suppression_index.py --check
```

Static, documentation, and workflow:

```bash
uv run --frozen --no-sync ruff check . bin/check-doc-paths bin/check-dom15-fixtures bin/coalesce-check
uv run --frozen --no-sync ruff format --check backstitch bin .github/scripts tests
uv run --frozen --no-sync mypy backstitch bin/release.py tests --config-file pyproject.toml
uv run --frozen --no-sync pytest tests/test_release_script.py tests/test_architecture.py -q
bin/check-doc-paths
bin/check-dom15-fixtures
```

Final behavior gates:

```bash
uv run --frozen --no-sync pytest tests -q -n auto --dist loadgroup -m 'not live_llm and not benchmark'
uv run --frozen --no-sync pytest tests/acceptance -q
uv run --frozen --no-sync backstitch check --repo-root .
```

The self-corpus command must exit 0 with zero errors and warnings. Every
enumerable contract element touched by the change must have a firing test.
The acceptance suite exists, so it is mandatory rather than a named residual.

For each meaningful slice, record:

- changed files;
- exact commands and observed results;
- raw C901 before/after counts and registry delta;
- reviewer and disposition;
- residual risk or explicit `none`.

## Independent Review Loop

Independent review is required at these points:

1. T1: plan, exact spec delta, baseline, and all disposition decisions.
2. T3: generator security/failure behavior against fixtures.
3. T3A: exact IDs, memberships, cardinalities, rationales, proofs, rejected
   alternatives, approvals, and lifetimes before source markers.
4. T4: live active-spec seam, atomic activation, and rollback coherence.
5. After each T5-T9 meaningful slice: behavior plus locality review.
6. T10: score-blind fresh-eyes review and reversal decisions.
7. T11: final diff, documentation, verification, and closure review.

Reviewers must inspect real diffs and rerunnable evidence, not summaries alone.
Findings are incorporated or answered in Review Log before the next dependent
slice.

T2, T3, T3A, and T4 are sequential because each consumes the prior frozen
authority. After T4, disjoint owner slices may be researched in parallel, but
cache precedes semantic orchestration, semantic orchestration precedes eval,
and report binding follows the producers it validates. Final verification is
serial against one captured revision.

Each completed meaningful slice is committed after its independent review and
verified with `git log`. If the owner explicitly requests an uncommitted review,
record that state in the handoff and do not call the slice complete.

## Stop And Re-Plan Gates

Stop and revise this plan if:

- the exact-pinned baseline differs from 152 or discovery changes;
- a new rule family is proposed for the same activation;
- a refactor changes public output, exit mapping, config precedence, artifact
  schema, cache/provider identity, or diagnostic behavior;
- a helper needs most of the parent's live state;
- an extraction splits captured bytes, a lock/lease lifetime, parser state,
  validation precedence, or atomic publication;
- generator identity cannot resolve a suppression unambiguously;
- activation cannot be atomic;
- a temporary row lacks a deterministic removal/re-evaluation task;
- a permanent row lacks current real proof or independent approval;
- self-corpus or acceptance cannot pass without broadening suppression.

## Out Of Scope

- stable-default Ruff expansion or activation of disabled families;
- changing textual `noqa` directives for disabled rule families; the active
  F401 importability probe is governed in scope;
- a complete state-machine inventory of Backstitch;
- public CLI/config/report/cache/provider contract changes;
- file splitting based on length or a target suppression count;
- a general static-analysis registry framework beyond Ruff;
- relaxing reviewed test-owned fixture exclusions or formatting extensionless tools;
- dependency upgrades other than exact-pinning the already locked Ruff version.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|
| [SC-17.1] registry heading | Repeat `[SC-17.1]` on the registry subheading | Keep `[SC-17.1]` only on the owning 17.1 heading; use exact subheading `#### Approved Ruff Suppression Registry` | Repeating the stable section ID creates one duplicate declaration and makes every governed source backlink ambiguous in the self-corpus | incorporated in the promoted [SC-17.1] text |

## Revision Log

| Date | Revision | Evidence |
|---|---|---|
| 2026-08-05 | Initial Backstitch plan created from SimpleBroker and Taut. Adopted Taut's activation ledger, T3A freeze, atomic activation, exact pin proof, symbol-key generator, live-spec seam, active-rule wording, deterministic temporary tasks, and post-refactor locality remediation. Kept stable-default expansion separate. | SimpleBroker/Taut plan and implementation inspection; Backstitch baseline commands |
| 2026-08-05 | Corrected initial C901 count from 150 to 152 after the disposition audit found Ruff normal discovery omitted intended extensionless Python tools. Added explicit discovery contract and lint targets. | Ruff 0.15.21 complete-path JSON audit; 138 package + 4 bin + 10 tests |
| 2026-08-05 | Addressed independent readiness blockers: replaced `extend-include` with one explicit canonical lint vector; moved the live-spec seam to atomic activation; made the TSV the 153-row freeze authority with separate directive/raw cardinalities; governed F401; added [SC-10] delta and [SC-17.1] mappings; separated T2 non-activation tests; named owner approval; corrected release commands/tests. | Independent plan review; verified Ruff formatter behavior |
| 2026-08-05 | T2 implementation added one eligible Python file, so combined Ruff discovery moved from the pre-slice 168 rows to 169: 168 Python/shebang files plus `pyproject.toml`. Membership remains derived from Git and reviewed exclusions; the count is only a checked consequence. | `tests/test_ruff_policy.py`; canonical `ruff check --show-files` vector |
| 2026-08-05 | T2 review replaced broad exclusion-owner existence checks with an exact 99-row path/digest/role/proof inventory, separated tracked authority from an explicit pre-landing allowlist, removed stale count authority, sorted and renumbered the provisional ledger, and corrected temporary task routing. | Independent T2 review; `tests/fixtures/ruff-excluded-python.tsv`; focused policy tests |
| 2026-08-05 | Final T2 proof closure added exact AST validation for every cited proof symbol and a non-circular legacy semantic-eval v1 manifest/source/mutation hash recomputation test. | Final T2 rereview PASS; nine policy tests |
| 2026-08-05 | Initial T3 review blocked fail-open and byte-preservation gaps: strict Ruff JSON, closed/single registry authority, duplicate source rules, CRLF-safe region replacement, Markdown-safe paths, and real Ruff end-to-end proof. Corrections assigned before T3A. | Independent hostile review and direct adversarial probes |
| 2026-08-05 | T3 hardening closed strict JSON/noqa-row parsing, registry/fence authority, duplicate rules, Markdown-safe paths, real pinned-Ruff execution, discovery/read failures, atomic cleanup/mode, and exact-byte CRLF/non-ASCII preservation through production `run()`. | Final T3 rereview PASS; 89 combined focused tests |
| 2026-08-05 | Initial T3A cross-review found three new generator C901 diagnostics and three ledger proof gaps. Chose locality-preserving generator decompositions rather than self-suppressing the governance tool, and assigned missing enumerable settings/coalesce proofs before freeze. | Three independent ledger cross-reviews; fresh pinned threshold-10 audit |
| 2026-08-05 | T3A remediation returned the generator to zero C901 findings and added exact ratchet-key, table-map, and hermetic coalesce proof. Three cross-reviewers found all 153 rows technically ready to freeze; approval remains an external owner gate. | 153 exact raw matches; 22/27/103 C901 priorities; T3A technical PASS |
| 2026-08-05 | T4 promotion removed the repeated `[SC-17.1]` token from the registry subheading after the self-corpus gate proved that two headings declaring one stable ID make all 153 source backlinks ambiguous. The generator and live-spec test still require one exact active registry heading. | Adversarial self-corpus probe: 1 duplicate plus 149 ambiguous-reference errors before correction |
| 2026-08-05 | Repository owner approved all 153 exact group fields. T4 froze the ledger, promoted 153 human and generated rows, activated C901/10, inserted 153 reconciled markers, and aligned CI/release enforcement atomically. | Owner task reply `Approve`; integrated T4 gates |
| 2026-08-05 | T5-T9 resolved 43 of 49 temporary C901 groups. Six state-machine and lifecycle owners remain registered: 005, 077, 082, 084, 085, and 088. The live registry now contains 110 directives while the frozen activation ledger remains the historical approval input. | Focused owner suites; exact raw audit `C901=109,F401=1`; generated-index reconciliation |
| 2026-08-05 | T10 score-blind cross-review retained the six cohesive owners and found no shallow extraction to reverse. Retired group IDs remain unused gaps and are not reassigned. | Independent T6, T7, T8, and combined T5/T9 locality reviews |
| 2026-08-05 | The first full-suite run found six integration failures missed by focused selections: JSON preparation-block output moved to stderr, live policy proof still compared against the historical activation ledger, and the expanded self-corpus exceeded repository dogfood work limits while the deterministic registry packet exceeded the reviewed per-request provider capability. Restored JSON stdout parity, made active-marker paths the live policy oracle, added a measured 3,000,000 work-unit override, and dispositioned [SC-17.1] out of model evaluation because Ruff policy/index gates already prove it deterministically. | Full pytest failure matrix; hostile final review; real isolated self-repository dogfood probe |

## Review Log

| Date | Scope | Reviewer | Result | Findings and disposition |
|---|---|---|---|---|
| 2026-08-05 | Read-only initial C901 disposition audit | three independent area reviewers | complete input to T1 | 152 rows: 22 P1, 27 P2, 103 P3; discovered two extensionless-bin findings; no source edits |
| 2026-08-05 | Initial implementation-readiness review | independent production-area reviewer | BLOCKED, revisions applied | Ten blockers: formatter scope, task order, durable freeze/cardinality, F401 scope, traceability mapping, [SC-10] delta, red-test sequencing, release test/command shape, and approval owner |
| 2026-08-05 | Implementation-readiness rereview | independent production-area reviewer | PASS after one wording correction | No remaining blocker after narrowing Out of Scope to disabled-family directives; order, atomicity, cardinalities, mapping, proof, approval, commands, and commit gates are executable |
| 2026-08-05 | T2 implementation review | independent production-area reviewer | initial BLOCKED; final PASS | Replaced false-confidence exclusion proof, corrected ledger order/task routing and Git authority; added exact proof-symbol validation and real v1 hash recomputation |
| 2026-08-05 | T3 generator review | independent settings/tooling reviewer | BLOCKED; corrections in progress | Five fail-open/data-preservation defects and missing real-Ruff/failure-path probes; task-order isolation passed |
| 2026-08-05 | T3 generator final rereview | independent settings/tooling reviewer | PASS | All hostile findings closed; production byte-preservation spot check passed |
| 2026-08-05 | T3A exact ledger freeze | three cross-reviewers | BLOCKED; remediation in progress | New generator findings must be removed or registered; rows for ratchet policy, table keys, and coalesce lacked the claimed real proof; owner approval remains pending |
| 2026-08-05 | T3A exact ledger freeze rereview | three cross-reviewers | technical PASS; owner gate pending | All 153 rows exact and substantive; generator C901=0; corrected proofs fire; all approval fields remain `pending owner` and freeze status remains `proposed` |
| 2026-08-05 | T3A owner authorization | repository owner | APPROVED | Exact 153-row ledger approved in the implementation task; all approval fields record the reply and freeze status is `frozen` |
| 2026-08-05 | T4 atomic activation | independent semantic-area reviewer | PASS | 153 ledger/human/generated/source rows exact; config, policy, CI, release, self-corpus, acceptance, and atomic rollback all align |
| 2026-08-05 | T5 settings and T9 tools/tests | independent semantic-area reviewer | PASS after bookkeeping correction | No behavior, precedence, release-order, proxy-state, corpus-identity, visitor-traversal, locality, or proof finding. Removed stale live-registry rows and regenerated the index. |
| 2026-08-05 | T6 semantic execution | independent settings-area reviewer | PASS | Lease/guard lifetime, reservation release, lazy construction, call budgets, packet order, and preparation isolation remain owned; groups 077/082/084/085/088 are correctly retained. |
| 2026-08-05 | T7 eval and reports | independent core-area reviewer | PASS | Temporary lifetimes, cold/replay order, global budgets, publication, schema dispatch, first-error order, report binding, and final digests remain intact. |
| 2026-08-05 | T8 alignment, CLI, evidence, and coverage | independent semantic-area reviewer | PASS | Snapshot/parser ownership, output and exit precedence, lazy provider imports, aggregate order, and proof strength remain intact; group 005 is correctly retained. |
| 2026-08-05 | T10 locality remediation | cross-review matrix above | PASS; no reversals | Every changed P1/P2 owner received a score-blind review. The six retained owners are cohesive state machines; no new unregistered owner exceeds 10. |
| 2026-08-05 | T11 initial integration review | independent semantic-area reviewer | BLOCKED; correction applied | Rejected an unsupported 40 MB analyzer request limit because `maximum_input_bytes` is a provider capability, not aggregate corpus capacity. |
| 2026-08-05 | T11 corrected integration rereview | independent semantic-area reviewer | PASS | Provider capability remains 1.6 MB. The exact SC-17.1 semantic skip, section/code suppression, and declaration are narrow and non-circular; real Ruff/index proof, self-check, preflight, and documentation align. |

## Execution Evidence

| Task | Changed files | Commands and observed result | Raw/registry delta | Review | Residual risk |
|---|---|---|---|---|---|
| T1 | this plan; `docs/plans/README.md` | complete threshold-10 Ruff audit: 152 C901; combined show-files: 168; `git diff --check`: pass; `backstitch check --repo-root .`: exit 0, zero issues | no source or registry activation; current active raw F401=1 | initial BLOCKED review corrected; rereview PASS | exact 153-row TSV is deliberately a T2 deliverable and must pass T3A freeze before activation |
| T2 | `pyproject.toml`; `uv.lock`; `tests/test_ruff_policy.py`; enabled-rule fixture; exact 99-row excluded-input fixture; activation-ledger TSV | policy/release/workflow suite: 88 passed; policy tests after proof closure: 9 passed; Ruff, focused mypy, format, diff check: pass; self-corpus: exit 0, zero issues; discovery membership derived exactly; commit `1e1fbe5` | proposed ledger only: 152 C901 + 1 F401; no activation or source markers | initial review BLOCKED; corrections incorporated; final rereview PASS | nine pre-existing dangling document path claims remain outside this slice |
| T3 | `bin/ruff_suppression_index.py`; `tests/test_ruff_suppression_index.py`; policy discovery expectation | combined policy/generator tests: 89 passed; canonical Ruff, full format, focused mypy, diff check: pass; real Ruff 0.15.21 extensionless end-to-end: pass; commit `dc36067` | fixture-only generator; no active spec rewrite or source markers | initial review BLOCKED twice; all findings closed; final rereview PASS | full repository mypy has the same six pre-existing `tests/test_semantic_application.py:144` errors with and without T3 |
| T3A technical freeze | generator locality refactor; `tests/test_settings.py`; `tests/test_coalesce_check.py`; three ledger proof fields | combined focused selection: 278 passed; canonical threshold audit: 152 C901, generator 0; Ruff, full format, focused mypy, diff check: pass | ledger remains 153 proposed rows; no source markers or activation | three cross-reviewers technical PASS | repository-owner authorization is required before changing approval/freeze fields or starting T4 |
| T4 | 43 governed source files; frozen ledger; core spec; Ruff config/rule fixture; generator/index; policy tests; CI; release helper/tests; self-corpus snapshot | integrated policy/generator/release/workflow: 175 passed; corpus/architecture/policy: 23 passed; acceptance: 24 passed; canonical Ruff, index check, full format, focused mypy, diff check: pass; self-corpus exit 0 with zero issues | 153 frozen human rows; 153 generated rows; raw `C901=152,F401=1`; normal Ruff clean | independent review PASS | promoted registry heading delta recorded after adversarial self-corpus caught duplicate section ID |
| T5 | `backstitch/settings.py` | 511 settings, semantic-settings, config-parity, and CLI-config tests passed; Ruff, format, mypy, and diff checks passed | 10 temporary groups removed: 126, 127, 130-133, 135-138 | independent review PASS | none |
| T6 | `backstitch/semantic_analysis.py`; `semantic_application.py`; `semantic_cache.py` | 193 semantic analysis/application/cache/verification tests plus seven targeted race/deadline/order probes passed; Ruff, format, mypy, and diff checks passed | 8 groups removed: 071-075, 078, 083, 089; 5 retained: 077, 082, 084, 085, 088 | independent review PASS | retained owners deliberately preserve ordered mutable lifecycle state |
| T7 | `backstitch/semantic_eval.py`; `semantic_reports.py` | implementation selection: 305 passed; independent review selection: 176 passed; Ruff, format, and mypy passed | 6 groups removed: 090, 110, 117, 122-124 | independent review PASS | none |
| T8 | alignment, CLI, coverage, evidence-summary/history, obligations, semantic-evidence owners; canonical-owner inventory | implementation selection: 339 passed; independent review covered 12 focused suites; Ruff, format, and mypy passed | 13 groups removed: 002, 003, 009, 010, 027, 028, 031, 034, 040, 041, 047, 055, 100; group 005 retained | independent review PASS | `_phase_ids` remains one phase-wide manifest, uniqueness, and coverage state machine |
| T9 | `bin/coalesce-check`; `bin/release.py`; live proxy, semantic corpus generator, and canonical-owner tests | release 37, coalesce 2, and combined helper/corpus/owner selection 89 passed; generator no-write, Ruff, and focused mypy passed | 6 groups removed: 140, 141, 143, 144, 146, 150 | independent review PASS after registry reconciliation | qualification generator source hash intentionally refreshed; generated corpus bytes unchanged |
| T10 | all T5-T9 P1/P2 diffs and retained owners | exact raw audit `C901=109,F401=1`; normal Ruff and suppression-index check pass | live registry 153 -> 110 directives; 43 retired gaps; frozen activation ledger unchanged | cross-review PASS | no reversal required; six temporary groups retained under their approved invariants |
| T11 integration correction | CLI JSON blocked-result stream; active policy oracle; repository work limit; [SC-17.1] semantic disposition and declared suppression | final full suite: 2,668 passed; acceptance: 62 passed; self-check exit 0 with zero errors/warnings; preflight complete with 111 packets, 33,373,837 aggregate prompt bytes, and 1,119,701 maximum request bytes under the 1.6 MB capability; canonical Ruff, index, format, policy/release, and diff gates pass | no Ruff suppression or rule delta; one valid semantic skip and exact audited deterministic suppression | initial BLOCKED; corrected rereview PASS | full mypy retains the same six pre-existing errors at `tests/test_semantic_application.py:144`; nine pre-existing dangling document-path claims remain |

## Fresh-Eyes Checklist

- [ ] Exact Ruff pin, lock, and binary agree.
- [ ] Discovery covers tracked lint-eligible Python and intended extensionless
      entry points; every excluded fixture tree has an exact role/proof owner.
- [ ] Normal Ruff selects C901 at 10; there is no threshold-39 side lane.
- [ ] Stable-default expansion did not enter this change.
- [ ] Every raw finding is fixed or maps exactly once to a reviewed live row.
- [ ] The existing active F401 importability probe is fixed or governed under
      the same generic marker and registry contract.
- [ ] Registry fields are substantive, not score-only or circular.
- [ ] The active spec heading exists exactly once and is tested directly.
- [ ] Generator identity is symbol-keyed and check mode is non-mutating.
- [ ] CI and release prechecks run the same complete lint and index checks.
- [ ] Every P1/P2 change passed real proof and a score-blind locality review.
- [ ] Shallow extractions were reversed even if the final count increased.
- [ ] Every permanent P3 group has current proof and rejected alternatives.
- [ ] Full tests, acceptance, static gates, and self-corpus pass.
- [ ] Spec, implementation docs, maps, plan evidence, and index agree.
- [ ] Final implementation is committed and verified with `git log` before the
      plan is marked completed.

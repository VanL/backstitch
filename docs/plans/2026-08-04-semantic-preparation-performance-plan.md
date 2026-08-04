# Semantic Preparation Performance Plan

Date: 2026-08-04

Status: completed; implementation, verification, and final independent review
PASS.

Plan type: implementation against the existing specification. No normative
spec delta is proposed.

Class: 4 under [DOM-15]. This repairs a cross-command conformance defect in
the authoritative packet-plan boundary and changes the internal lifetime of
derived discovery data. Public CLI, artifact, identity, budget, deadline, and
provider contracts remain fixed. The shared preparation path and semantic
artifact trust boundary make independent review and full acceptance evidence
mandatory.

## Goal

Make provider-free semantic preparation materially faster without changing
what Backstitch accepts, measures, publishes, sends, or reports. The first
slice removes two proven duplicate computations: current report construction
must consume the already-authoritative `PacketPlan` rather than regenerate the
entire packet corpus, and each immutable catalog node's lexical tokens must be
derived once per prepared snapshot rather than once per obligation.

This follows the release order already recorded in the usability plan: make it
work, make it correct, then make it fast and cheap. Model/provider changes and
request-protocol changes come later and cannot substitute for eliminating
local duplicate work.

## Outcome Checklist

- [x] One `PacketPlan` supplies packet bytes and packet-report inputs for
  standalone packet publication, current preflight/current analysis, and
  semantic evaluation.
- [x] Source packet report construction performs no packet generation,
  discovery, repository recapture, or serialization of replacement packet
  bytes.
- [x] Forged packet content remains rejected because callers cannot supply
  independent bytes beside the authoritative plan and report validation still
  checks packet schema, IDs, snapshot identity, completeness, and content
  hashes.
- [x] Immutable catalog-node lexical tokens are computed once during catalog
  preparation and reused across isolated obligation derivations; report-issue
  nodes added later compute their own tokens once.
- [x] Logical work-unit accounting, cooperative deadline checks, progress
  phases, packet/result/report bytes, identities, ordering, and failure classes
  remain unchanged.
- [x] Deterministic tests prove one packet-planning traversal per operation and
  no repeated tokenization of prepared catalog nodes.
- [x] The full non-live suite, [SC-10] acceptance suite, hermetic extended
  dogfood, and `backstitch check --repo-root .` pass.
- [x] A repeatable unprofiled preflight measurement and an independent
  implementation review are recorded before closure.

## Source Documents

Source specs:

- `docs/specs/07-verification-and-evidence-cases.md` [EVC-9.1]: one
  authoritative `PacketPlan` owns canonical bytes and report inputs;
  publication and execution consume retained bytes and do not regenerate,
  reserialize, or reframe them.
- `docs/specs/06-semantic-gates.md` [SEM-10]: preflight and ordinary current
  analysis consume one preparation identity and exact measured request bytes.
- `docs/specs/02-backstitch-core.md` [SC-5], [SC-7]: packet/report publication
  and the source-bounded semantic boundary.
- `docs/specs/05-backstitch-invariants.md` [INV-5], [INV-6]: deterministic
  packet and evidence identities.

Related records:

- `docs/plans/2026-07-29-usability-remediation-plan.md`, especially the
  post-correctness provider/cost decision and the first provider-free speed
  target.
- `docs/implementation/08-aligned-intent-read-model.md`, especially the one
  prepared discovery catalog and one packet-producer ownership model.
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/review-loops.md`

## Spec Baseline

Diff base:

```text
506ef048ae785a845f3bed473e774be80f0972d7
```

The governing specs already include the reviewed usability promotion in the
working baseline. Their exact plan-authoring SHA-256 values are:

```text
docs/specs/07-verification-and-evidence-cases.md
ba365feb2e09cc6262f108cbbab7805adfe08730a904ffef0ae779414cae475e

docs/specs/06-semantic-gates.md
4852136cc4c6aea1430dec5cc0abc7dfd8bd48d21652026611dff5c7f88e8d14
```

No proposed spec delta exists. The implementation must conform to the quoted
[EVC-9.1] rule. If code work requires a second packet derivation, a new cache
trust rule, different work accounting, or different bytes, stop and revise the
plan and specs before continuing.

## Profile Evidence and Decisions

The previous unprofiled reference measurement was 261.54 seconds for one
complete preparation plus trust-boundary validation. The extended hermetic
self journey took about 15.5 minutes. Those numbers are historical reference
points, not portable CI ceilings.

On 2026-08-04, a local `cProfile` run of:

```text
env -u LLM_MODEL uv run python -m cProfile \
  -o /tmp/backstitch-preflight-20260804.prof \
  -m backstitch analyze --repo-root . --preflight --format json
```

recorded 6,554,995,879 calls. Profile instrumentation inflated wall time, so
only call counts and relative hot paths are used for design:

- `plan_source_aligned_packets`: 2 calls, about 973 profiled cumulative
  seconds. The second call came only from
  `build_source_packet_report`, after `_prepare_current` had already retained
  the complete plan.
- `_candidate_tokens`: 7,734,410 calls.
- `_tokens`: 23,203,854 calls, about 650 profiled cumulative seconds.
- `discover_evidence_candidates`: 208 calls, about 927 profiled cumulative
  seconds. Those 208 calls are 104 obligations traversed twice, not two
  intentional semantic passes.

Decision: remove these two duplicate computations before considering a
persistent cache. The current snapshot-bound in-memory objects already own the
facts. A persistent artifact would introduce invalidation, cleanup, provenance,
and mutable-cache trust questions that are not needed for this correction.

Discarded approaches:

- A process-global `_tokens` cache is rejected. It is unbounded, crosses
  snapshot lifetimes, hides memory retention, and weakens authority reasoning.
- A second "fast report" builder is rejected. It would recreate the duplicate
  path this plan is meant to remove.
- Accepting independent `packet_jsonl` bytes plus a plan is rejected. Two
  authorities at one boundary allow disagreement and retain the need for a
  byte-match recomputation.
- A persisted discovery/packet cache is deferred. It may be useful for the
  composed multi-command dogfood journey, but it is not required to remove
  duplicate work inside one operation.
- Changing model, provider, packet schema, request framing, or evidence
  selection is rejected for this slice. Those affect cost or semantics, not
  the measured local duplication.

## Context and Key Files

- `backstitch/analysis_packets.py`: `PacketPlan` owns retained canonical line
  bytes, request bytes, accounting, and complete/incomplete state.
- `backstitch/semantic_reports.py`: `build_source_packet_report` currently
  accepts caller bytes, locally imports the packet generator, regenerates the
  corpus, and byte-compares it. This violates [EVC-9.1] and is the primary edit
  point.
- `backstitch/semantic_application.py`: `_prepare_current` already creates the
  authoritative plan, then passes only its bytes to the report builder. It must
  pass the plan itself.
- `backstitch/packet_application.py`: standalone packet publication also owns a
  plan before optional report construction. It must use the same report seam.
- `backstitch/semantic_eval_observation.py`: qualification currently calls the
  compatibility packet projection before report construction. It must create
  one plan and project packets/bytes from it.
- `backstitch/evidence_discovery.py`: `PreparedEvidenceCatalog` retains
  snapshot-bound parser/static-relation data. `_catalog_nodes_for_obligation`
  clones only mutable derivation state, while `_candidate_tokens` currently
  re-tokenizes stable path/module/symbol text for every clone.
- `tests/test_analysis_packets.py`: packet-plan and source-report contract
  tests, including forged-source rejection.
- `tests/test_evidence_discovery.py`: prepared-catalog equivalence, isolation,
  budget, and discovery tests.
- `tests/acceptance/`: real CLI journey coverage. Do not replace this with
  application-seam mocks.

Comprehension gates before editing:

1. Why can report construction trust the plan but not arbitrary packet bytes?
   Because the plan is the operation's retained output from the sole packet
   producer, while arbitrary bytes constitute a second authority. The report
   must still validate the retained bytes against runtime completeness,
   identity, schema, and snapshot contracts.
2. Which discovery fields may be shared across obligations? Parser facts,
   static edges, and lexical tokens derived only from immutable node identity
   fields may be shared. Bases, trace flags, closure neighbors, and lexical
   scores are obligation-local and must still be cloned/reset.

## Invariants and Constraints

- There remains exactly one packet generation path. `PacketPlan` is the sole
  owner of generated packet and request bytes.
- The report builder takes a complete real plan. It must reject an incomplete
  plan before reading retained bytes.
- Report schema and canonical bytes do not change. `created_at` remains the
  only caller-controlled report timestamp.
- Runtime checks remain real: fail-on findings, active/selected/alignment
  state, exact packet order/IDs, schema eligibility, packet hashes, and source
  snapshot hashes are still validated.
- No repository file is reopened and no snapshot is recaptured during report
  construction or per-obligation discovery.
- Token reuse is snapshot-local. No module-global cache, disk cache, weak
  reference registry, or hidden mutable singleton may be introduced.
- Cached lexical tokens are derived only from `path`, `module_name`, and
  `symbol`/`owner`. If `_candidate_tokens` begins to depend on an
  obligation-local field, stop and redesign rather than caching the wrong
  value.
- `_WorkBudget` charges and `OperationProgress` events do not change in this
  slice. CPU implementation cost is not the logical contract budget.
- No dependency, config key, issue/exit code, model descriptor, provider call,
  artifact path, schema version, algorithm version, or cache identity changes.
- Keep the real parser, snapshot, packet compiler, validators, and filesystem
  in tests. A narrow spy around the packet planner or tokenizer is acceptable
  only to count traversals after the real production operation runs.
- Adjacent usability defects observed while profiling are recorded but out of
  scope: explicit `backstitch analyze` requires `--repo-root` while the default
  command does not; ambient `LLM_MODEL=gpt-5.5` can override repository intent
  and fail descriptor resolution.

## Rollback and One-Way Doors

There is no data migration, persistence, external write, or one-way door.
Each slice is source-compatible only within this unshipped worktree and can be
reverted independently. Rollback of the report slice restores the redundant
regeneration but not a different artifact format. Rollback of token reuse
restores repeated pure computation but not different discovery results.

If verification finds any byte, identity, work-unit, progress, or failure
change, rollback that slice. Do not paper over the difference with fixture
updates or budget increases.

## Dependency-Ordered Tasks

### Slice 0: Pin the duplicate traversal as a red contract test

First make the import shape observable without changing behavior:
`semantic_application.py` and `semantic_eval_observation.py` must import the
`analysis_packets` module and call
`analysis_packets.plan_source_aligned_packets`, matching
`packet_application.py`. Run their existing focused tests after this mechanical
change. This prevents a monkeypatch of the defining module from missing a
bare-name function bound at import time. It is a testability/layering
precondition, not the functional optimization.

Add a test around a real source-aligned runtime and real packet/report
validation. Instrument only `plan_source_aligned_packets` and prove that an
operation producing a report invokes it once. Preserve the existing forged
source test by expressing the forgery as a forged/fake plan or, preferably,
by proving that no public report-builder input accepts independent bytes.

Red gate: the new test must fail because current report construction invokes
the planner twice.

Stop if the only possible test mocks packet generation, runtime validation,
or packet parsing. Find a higher seam instead.

### Slice 1: Make report construction consume the plan

Change `build_source_packet_report` to accept one complete `PacketPlan` and
derive `packet_jsonl` from it. Remove the local generator/render import and
byte-regeneration comparison. Keep all downstream validation. Update
`semantic_application`, `packet_application`, and semantic-eval observation to
pass their already-created plan. Replace semantic-eval's compatibility
projection with `plan_source_aligned_packets` so it also performs one traversal.
As the report builder's first validation, explicitly reject an incomplete plan
with `PacketReportError` before reading `plan.packet_jsonl`; do not allow the
property's `SourceAlignedPacketError` to escape and change the caller's report
failure-stage contract.

Update direct tests and the implementation note to name
`plan_source_aligned_packets`/`PacketPlan` as the authoritative producer;
`generate_source_aligned_packets` remains only a compatibility projection for
callers that need packet dictionaries and no report.

Green gate: focused packet, application, semantic-eval, and publication tests
pass; source-report bytes before/after are identical for a fixed timestamp.

Independent slice review: run direct `claude -p` against the diff. Resolve or
explicitly answer every P0-P2 finding before Slice 2.

### Slice 2: Pin and implement catalog-local token reuse

First add a test that prepares a real catalog, derives at least two obligations
from it, and proves prepared catalog nodes do not call `_tokens` again. It must
also cover a late report-issue node or an equivalent uncached node so new nodes
still receive correct lexical scores.

Add an optional cached lexical-token field to private `_Node`. Populate it once
for catalog nodes during `prepare_evidence_catalog`. Preserve the immutable
token set across obligation clones. For nodes introduced after catalog
preparation, compute and retain it on first lexical scoring. Keep
`_candidate_tokens` pure and based only on immutable identity fields.

Green gate: prepared and unprepared discovery outputs remain byte/equality
identical; two obligations cannot leak bases, trace flags, closure neighbors,
or scores; work-budget and progress tests remain unchanged.

Stop if reuse needs global state, changes `_WorkBudget`, or couples tokens to
obligation text.

### Slice 3: Measure, verify, and record

Run the focused suites, full non-live suite, acceptance suite, hermetic dogfood,
format/lint/type/complexity gates, and self-corpus check. Capture an unprofiled
preflight measurement with ambient `LLM_MODEL` removed and the explicit repo
root. Compare exact packet/report output hashes or fixed-fixture bytes against
the pre-change contract tests.

The primary deterministic performance gates are:

- one packet-plan traversal for a report-producing operation;
- zero `_tokens` calls for already-prepared catalog nodes across obligations;
- unchanged logical work counts and output bytes.

Wall time is supporting evidence because machine load is noisy. Record the
command, environment qualification, sample count, median, and observed delta.
Do not add a brittle single-sample absolute CI ceiling.

### Slice 4: Final independent review and closure

Run direct `claude -p` over the integrated implementation, tests, specs,
implementation note, and this plan. Ask specifically about trust-boundary
weakening, circular imports, hidden second paths, stale mutable cache state,
work/deadline drift, and tests that mock away the production proof. Resolve or
record each finding.

Close only when the plan checklist and deviation log are accurate and all
required commands have concrete observed results. Landing remains an owner
decision; do not commit merely to satisfy the completion gate.

## Testing Plan

Focused gates, adjusted to exact selected test names during implementation:

```text
uv run pytest -q tests/test_analysis_packets.py tests/test_packet_application.py \
  tests/test_semantic_application.py tests/test_semantic_eval.py
uv run pytest -q tests/test_evidence_discovery.py \
  tests/test_obligation_runtime.py
```

Repository gates:

```text
uv run ruff check .
uv run ruff format --check .
uv run mypy backstitch
uv run pytest -q -m "not live_llm and not benchmark"
uv run pytest -q tests/acceptance
env -u LLM_MODEL uv run backstitch check --repo-root .
```

Run the extended isolated self-dogfood acceptance canary named by [SC-10] and
record its exact node ID and result. Use the existing protected live-LLM tests
only if this internal provider-free change touches provider-visible bytes. It
must not; any such change is a stop-and-replan signal.

## Verification and Acceptance Matrix

| Path | Must prove | Forbidden regression |
|------|------------|----------------------|
| `packets` without report | one plan, same packets | report work introduced |
| `packets` with report | one plan supplies both artifacts | corpus regeneration |
| `analyze --preflight` | one preparation, zero provider/cache/publication effects | second discovery pass |
| current analyze | same plan bytes reach report and analyzer | reserialization or request drift |
| semantic eval variant | one production plan and real report validation | compatibility projection plus regeneration |
| incomplete plan | report construction rejects it | partial report publication |
| forged packet/plan | schema/hash/snapshot/completeness validation fails closed | arbitrary bytes trusted |
| two obligations, one catalog | stable tokens reused; mutable fields isolated | lexical or trace leakage |
| late issue candidate | tokens computed and scored once | empty/stale lexical score |

## Independent Review Loop

Use direct `claude -p`, not a wrapper skill. Review once after the report-plan
slice and once after the integrated implementation. Each review receives the
plan, exact diff, governing spec excerpts, focused test output, and profile
evidence. A `PASS` without inspecting those artifacts is not sufficient.

## Out of Scope

- provider/model migration, including Grok qualification or default changes;
- price descriptor or tokenizer changes;
- packet/request schema redesign, batching, shared-source protocol, or prompt
  compression;
- persistent discovery/packet artifacts across separate CLI processes;
- lowering functional headroom or configured deadlines before stable
  multi-sample evidence exists;
- the explicit-analyze `--repo-root` asymmetry and ambient `LLM_MODEL`
  precedence issue;
- unrelated complexity, naming, layering, or file-splitting work.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Evidence Log

Append commands, observed results, output identities, performance samples, and
review dispositions here as each slice completes. Do not record transient
staging or worktree state.

- 2026-08-04 plan review, direct `claude -p --model sonnet`: FAIL with two
  correctable findings. P1: the traversal spy would miss bare-name planner
  imports in `semantic_application` and `semantic_eval_observation`. Resolved
  by adding the module-qualified import precondition to Slice 0. P2: incomplete
  plan rejection did not pin the report builder's exception type. Resolved by
  requiring an explicit pre-property `PacketReportError` in Slice 1. The review
  found no import cycle, trust-boundary weakening, mutable token-authority
  defect, work/progress drift, or further P3 issue.
- 2026-08-04 focused follow-up, direct `claude -p --model sonnet`: PASS. Both
  corrections were confirmed sufficient, with no new P0-P2 finding.
- Slice-review sequencing correction: the two tightly coupled implementation
  slices were completed before the planned post-Slice-1 review. No normative
  behavior changed because of the ordering. An integrated implementation
  review is required immediately before broader verification; this record does
  not waive the final independent review.
- Integrated review attempt timed out without a verdict. The review was split
  by coherent boundary. The direct Claude PacketPlan/report review found the
  core change sound, with no trust, traversal, import-cycle, or test-proof
  defect, but returned FAIL for one adjacent P2: an unreachable conditional
  `debt_ids` detail in the touched `SourceAlignedPacketError` handler. The
  condition could never be true after the earlier debt return, so it was
  removed without changing observable output. Follow-up remains required.
- Direct Claude lexical-token review: PASS with no P0-P2 finding. It confirmed
  immutable derivation inputs, one computation for prepared nodes, safe shared
  frozensets with isolated mutable clone fields, correct late-node scoring, and
  unchanged logical work accounting.
- Direct Claude follow-up on the PacketPlan/report P2: PASS. The unreachable
  conditional was removed and the handler retains the same empty `details`
  value through the dataclass default.
- Focused production-boundary tests:
  `uv run pytest -q tests/test_analysis_packets.py
  tests/test_packet_application.py tests/test_semantic_application.py
  tests/test_semantic_eval.py tests/test_evidence_discovery.py
  tests/test_obligation_runtime.py` passed (130 tests).
- Three serial unprofiled self-preflight samples used
  `env -u LLM_MODEL uv run backstitch analyze --repo-root . --preflight
  --format json`. Wall times were 105.86, 122.07, and 181.63 seconds; median
  122.07 seconds. User CPU times were 104.96, 109.75, and 122.61 seconds. The
  third sample had 59.02 seconds of non-CPU delay and is retained with that
  machine-contention caveat. The median is 53.3% below the recorded 261.54
  second reference (2.14 times faster). All three 1,946-byte outputs had exact
  SHA-256
  `56a9d7b99b4199b13d7be064e16bfed237060237d0ad5a9e371990be55de54c7`.
- `uv run ruff format --check .`: PASS, 164 files already formatted.
- `uv run ruff check .`: PASS. `uv run ruff check --select C901 backstitch
  tests`: PASS.
- `uv run mypy backstitch`: PASS, 58 source files.
- `uv run pytest -q -m "not live_llm and not benchmark"`: PASS, including the
  hermetic self-dogfood path.
- `uv run pytest -q tests/acceptance`: PASS, including the extended [SC-10]
  dogfood journey.
- `env -u LLM_MODEL uv run backstitch check --repo-root .`: exit 0; 122 spec
  sections, 372 mappings, 475 code refs, 1,013 edges, 9 invariants, 17 binds,
  and zero errors/warnings/infos.
- `backstitch check --show-suppressions`: exit 0; 263 governed suppressions and
  one declared obligation skip were shown with nonblank rationales. No blank
  rationale pattern matched.
- `git diff --check`: PASS.
- Residual performance fact: a 122-second median preflight is materially better
  but still not easy to use. Separate CLI processes in the full dogfood journey
  repeat snapshot/catalog/relation/closure work, and the full plus standalone
  acceptance gates rerun the same expensive journey. Cross-command,
  currentness-bound artifact reuse and better test progress reporting need a
  separate plan; this plan intentionally introduced no persistence lifecycle.
- Final integrated direct Claude review: PASS with no P0-P2 finding. It
  rechecked the complete-plan trust boundary, all three module-qualified
  single-plan callers, absence of an import cycle, immutable snapshot-local
  token sharing, late-node scoring, unchanged logical work accounting, removal
  of the dead `debt_ids` branch, and the production-path quality of the new
  tests.

## Fresh-Eyes Review

Before closure, reread only the governing spec paragraphs, this plan's
invariants, and the final diff. Confirm that the optimization removes work
rather than moving it behind hidden state, and that every changed production
branch has a firing test through the real boundary.

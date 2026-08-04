# Architecture And Code Quality Remediation Plan

Date: 2026-07-29

Status: completed; implementation, verification, and independent review PASS.
Owner-authorized integrated landing recorded with this plan's closeout.

Plan type: implementation plan with coordinated spec revision.

Class: 5+P under [DOM-15]. This plan changes normative
architecture and verification contracts. It also crosses configuration,
snapshot, cache-locking, semantic-analysis, and CLI boundaries, so the
hardening checklist is mandatory.

Promotion strategy: hybrid Strategy A/B from the plan-writing runbook. Promote
the exact behavior-specific amendments to [CFG-5.1], [COV-5], [SEM-4], and
[EVC-10.1] before implementation. Promote new [SC-17], its [SC-10] proof
bullets, index entry, implementation mapping, and reciprocal `Spec:` docstrings
atomically in the final architecture/traceability slice, after every mapped
owner and executable gate exists. Existing mappings are reconciled in the
slice that changes their owner.

## Goal

Remove accidental architecture and quality debt without changing Backstitch's
public CLI, artifact bytes, policy, or persistence contracts:

- eliminate every internal import cycle;
- converge duplicate config, cache, evaluation-identity, publication, and
  command-orchestration paths;
- make the CLI an adapter over typed application entry points;
- remove the non-shipping packet analyzer after harvesting its unique tests;
- split uncoupled publication and filesystem primitives from domain modules,
  while keeping cohesive parsers and cache state machines together;
- reduce every function with current McCabe complexity at or above 40 below
  that threshold and add an executable ceiling;
- rename only touched functions whose names do not read as short declarative
  statements;
- distinguish registry-shape tests from tests that fire real producers; and
- leave the reciprocal spec, plan, implementation, code, and test references
  valid so `backstitch check --repo-root .` exits 0 with zero errors and zero
  warnings.

The plan does not adopt Pydantic. See "Dependency Decision: Pydantic".

## Outcome Checklist

- [x] The static internal `backstitch.*` import graph is a DAG. Local imports
  do not hide an edge.
- [x] Filesystem and Git-blob config adapters call one merge, provenance,
  parse, and final-validation owner.
- [x] Equal configuration layers accept or reject identically in current and
  historical resolution, including final test-root containment.
- [x] Analyzer, evidence-stable review, and verifier cache ownership use one
  parameterized guard/lock/wait/cleanup state machine.
- [x] The eval producer and authoritative validator call one effective-epoch
  derivation function.
- [x] Atomic replace and ordered artifact-set publication have one generic
  leaf owner, distinct from immutable cache publication.
- [x] Coverage, analyze, obligation, and packet orchestration moved in this
  plan run through typed application entry points. `cli.py` owns parsing,
  translation, rendering, and exit mapping only.
- [x] `analysis_llm.analyze_packets` and its legacy adapter path are gone.
  Unique normalization and provider-boundary cases exercise shipping owners.
- [x] All 14 functions whose baseline complexity is at least 40 are below 40.
  Ruff enforces `max-complexity = 39`.
- [x] A test named as registry consistency no longer claims producer firing.
  Every affected diagnostic code/context still has a real firing test.
- [x] No rename-only sweep or file-size-driven fragmentation is introduced.
- [x] Specs, mappings, backlinks, implementation docs, code docstrings, tests,
  and the plan agree.
- [x] Acceptance, full CI-equivalent checks, suppression review, and the
  hermetic self-corpus gate pass.
- [x] Each coherent slice and the final diff receive independent review.

## Source Documents

Read these before implementation:

- `AGENTS.md`
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/principles.md`
- `docs/agent-context/engineering-principles.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/lessons.md`
- `docs/lessons.md`
- `docs/specs/00-specs-index.md`
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11], [DOM-15]
- `docs/specs/02-backstitch-core.md` [SC-3], [SC-5], [SC-7], [SC-10],
  [SC-15], and proposed [SC-17]
- `docs/specs/03-backstitch-configuration.md` [CFG-5], [CFG-5.1], [CFG-9]
- `docs/specs/05-backstitch-invariants.md` [INV-11]
- `docs/specs/06-semantic-gates.md` [SEM-3], [SEM-4], [SEM-7], [SEM-8],
  [SEM-10]
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-3.1], [EVC-5.1],
  [EVC-7], [EVC-7.2], [EVC-8.2], [EVC-8.3], [EVC-8.7], [EVC-10.1],
  [EVC-12.2]
- `docs/specs/08-intent-coverage.md` [COV-3], [COV-5], [COV-9]
- `docs/implementation/02-repository-map.md`
- `docs/implementation/04-backstitch-style-traceability.md`
- `docs/implementation/07-deterministic-semantic-gate.md`
- `docs/implementation/08-aligned-intent-read-model.md`
- `docs/implementation/09-intent-coverage.md`

Reference architectures:

- `../taut/taut/cli.py` and `../taut/taut/commands/_protocol.py`
- `../taut/taut/commands/`
- the corresponding CLI, application, and domain boundaries in
  `../simplebroker`

The references are design evidence, not copy targets. Backstitch's cache,
snapshot, and artifact contracts are stricter and remain authoritative.

## Spec Baseline

Plan-authoring baseline:

```text
506ef048ae785a845f3bed473e774be80f0972d7
```

At authoring time, `git diff --quiet -- docs/specs` exited 0. The normative
spec baseline was clean. The worktree had unrelated owner changes in
`AGENTS.md`, four test files, and `tmp_gbexp.sh`; implementation must preserve
and work around those changes. Plan authoring then added this file and modified
`docs/plans/README.md`; those two paths are plan-owned, not baseline owner
changes.

Reviewed behavior-spec promotion is uncommitted. Its initial `git diff` SHA-256
over specs 00, 02, 03, 05, 06, 07, and 08 is:

```text
00a078259cf9d38efe0795a5cc6792d2da1666bb261e691fc9a916e506aabb0a
```

New [SC-17] remains Strategy-B deferred until its implementation and mapping
exist. Later mapping reconciliation will change the working-tree digest and
must be recorded in the implementation log.

## Evidence And Current Structure

### Configuration divergence

`backstitch.settings.resolve_config` and
`resolve_repository_config_from_blobs` implement parallel assembly paths.
The filesystem path performs final test-root containment; the blob path
returns without the equivalent check. A controlled probe accepted
`code_roots = ["src"]`, `test_roots = ["tests"]` through blobs while the
filesystem resolver raised `ConfigLoadError`.

The blob resolver is used by historical intent coverage. It must remain
filesystem-independent, but that is a source-adapter difference, not authority
to own a second policy.

### Internal import cycles

The runtime graph has three strongly connected components:

1. `settings` and `repository_snapshot`;
2. `semantic_analysis` and `semantic_eval`;
3. `semantic_identity` and `semantic_verification`.

The cycles are implementation accidents, not unavoidable runtime constraints.
They are currently hidden in part by local imports. External provider loading
is the only justified lazy-import quarantine.

### Duplicate paths and misplaced ownership

- `semantic_cache.py` has separate semantic, review, and verifier
  guard/lock/wait/cleanup implementations for the same state machine.
- `semantic_eval.py` and `semantic_eval_reports.py` encode effective epochs
  separately, including delimiter ownership at the call site.
- `semantic_reports.py` owns generic fsync, staging, atomic replace, and
  ordered set publication used by several domains.
- `cli.py` imports most package modules and contains application workflows:
  `_cmd_coverage`, `_cmd_analyze`, and `_run_obligation`.
- `analysis_llm.analyze_packets` is a second analyzer orchestration path with
  no production caller. Its adapter, thread pool, prompt, exit, and rendering
  helpers are used only by tests.

### Complexity baseline

`uv run ruff check backstitch bin --select C901 --output-format concise`
reports 142 functions above Ruff's default 10. The default is not a useful
blanket boundary for cohesive parsers and closed artifact validators.

Four functions exceed 60:

| Function | Baseline |
|---|---:|
| `intent_coverage_reporting.validate_coverage_report` | 117 |
| `markdown_specs.parse_markdown_spec_bytes` | 106 |
| `evidence_discovery._resolve_references` | 81 |
| `code_parser._static_syntax_facts` | 74 |

Ten more are at least 40:

| Function | Baseline |
|---|---:|
| `semantic_eval_reports.load_semantic_eval_corpus` | 59 |
| `semantic_reports._packet_report_source_shape` | 59 |
| `semantic_reports._validate_analysis_report_source_shape` | 54 |
| `alignment_eval._validate_task` | 52 |
| `cli._cmd_coverage` | 51 |
| `artifact_contracts._packet_v3_shape_error` | 49 |
| `python_refs.parse_python_bytes` | 45 |
| `semantic_cache.analyze_with_cache` | 44 |
| `alignment_eval._load_alignment_eval_result` | 42 |
| nested `code_parser.visit_reference` | 40 |

The first ratchet sets 60 after the four extreme outliers are reduced. The
same plan then reduces all remaining baseline scores at or above 40 and lowers
the final ceiling to 39. Scores 11 through 39 remain measured debt, not proof
that those functions are well designed.

### Test audit

The audit found no broad mock-heavy false proof. Most fakes isolate the model
or process boundary and retain behavioral assertions. Those should remain.

`test_intent_coverage_registry_rows_and_contexts_all_fire` is mislabeled: it
constructs `Issue` values and proves registry projection, not that producers
fire. Other CLI tests cover the codes. The correction is to name this test
honestly and keep a separate producer-firing matrix.

## Context And Key Files

| Boundary | Current owner/edit point | Primary tests | Load-bearing contract |
|---|---|---|---|
| Filesystem config | `backstitch/settings.py::resolve_config`; `backstitch/config.py::resolve_profile_root` and `uncontained_test_root` | settings, config, and semantic-settings tests | [CFG-4], [CFG-5], [CFG-5.1], [CFG-6], [CFG-9] |
| Historical config | `resolve_repository_config_from_blobs`, `intent_history.py` | coverage/ratchet and Git-baseline tests | [COV-5], [EVC-12.2] |
| Snapshot/no-follow I/O | `backstitch/repository_snapshot.py` | snapshot and canonical-owner tests | [INV-11], [EVC-8.2] |
| CLI workflows | `_cmd_coverage`, `_cmd_analyze`, `_run_obligation` in `cli.py` | CLI subprocess, coverage, semantic-analysis, obligation tests | [SC-5], [SC-7], [EVC-5.1], [COV-9] |
| Semantic runner | `backstitch/semantic_analysis.py` | semantic-analysis tests | [SC-7], [SEM-7], [EVC-5.1] |
| Provider boundary | `backstitch/analysis_llm.py` | analysis-LLM and live helper/proxy tests | [SEM-3], [SC-10] |
| Cache ownership | `backstitch/semantic_cache.py` | semantic cache, review reuse, verifier cache tests | [SEM-4], [SEM-10] |
| Qualification/eval | `semantic_eval.py`, `semantic_eval_reports.py`, `semantic_identity.py`, `semantic_verification.py` | semantic eval and verification tests | [SEM-3], [SEM-8], [EVC-3.1], [EVC-10.1] |
| Artifact publication | generic helpers in `semantic_reports.py` | semantic, eval, coverage, publication-failure tests | [EVC-5.1], [SEM-7], [COV-9] |
| Architecture/complexity | `pyproject.toml`, `.github/workflows/ci.yml`, new `tests/test_architecture.py` | normal Ruff/CI plus explicit C901 | [SC-10], proposed [SC-17] |
| Traceability/docs | specs 02, 03, 05, 06, 07, 08; implementation docs 02, 04, 07, 08, 09 | self-corpus and doc/plan fixtures | [DOM-10], [INV-10] |

Before editing the relevant boundary, record concise answers to these
comprehension checks in the implementation record:

1. Which operation establishes cache ownership, and which token comparison
   prevents a stale owner or cleaner from removing a successor's lock?
2. Where must final configuration validation run so filesystem and Git-blob
   sources share policy without historical resolution reading the checkout?
3. Which recapture and staging order prevents semantic output from certifying
   a repository state changed by its own publication?
4. Which eval inputs remain independently authoritative after producer and
   validator share an epoch encoder?

## Contract Decisions

### Dependency direction

The dependency direction is:

```text
leaf primitives and closed contracts
  -> source and configuration adapters
  -> domain owners
  -> application workflows
  -> CLI
```

The graph is a DAG. A local import is still an edge. `TYPE_CHECKING` imports
may be excluded from the runtime graph only when annotations cannot be
resolved at runtime and the architecture test records the rule. Lazy imports
are allowed for the external `llm` quarantine; they may not form an internal
SCC.

### Config containment semantics

Final profile-root containment becomes a pure value operation for both current
and historical settings. After [CFG-4]'s existing user/environment
expansion, join relative values to the target repository root and normalize
`.` and `..` lexically. Do not call `Path.resolve`, `realpath`, `stat`, or any
other filesystem operation. Equality and ancestry compare these normalized
path values.

This deliberately corrects the current filesystem resolver, whose
`config.py::resolve_profile_root` follows the live checkout while the
historical resolver has no valid historical filesystem to follow. Physical
symlink and no-follow enforcement remains at snapshot/capture boundaries; it
is not configuration merge policy. Slice 1 must characterize current
committed configurations and symlink fixtures before changing the resolver,
then record any accept/reject delta. A delta is an intended [CFG-5.1]
correction, not an unmentioned compatibility change.

### Layer boundaries

`cli.py` owns argparse, translation from `Namespace` plus resolved settings to
typed requests, rendering, and public exit mapping. It does not own snapshot
capture, packetization, cache coordination, domain validation, or artifact-set
publication.

Introduce application entry points only where orchestration currently leaks
into the CLI:

- `check_application.py`
- `coverage_application.py`
- `packet_application.py`
- `semantic_application.py`
- `obligation_api.py` (deepened per the recorded Slice 5 deviation)

Do not create one class per command. Do not move cohesive domain algorithms
just to shorten files. Inspection confirmed `_cmd_check` owns snapshot capture,
report construction, warning policy, and failure classification, while
`_cmd_packets` owns runtime construction, packet generation, report assembly,
and ordered publication. Both therefore cross the application seam. Their
typed entry points return domain/application results; `cli.py` retains format
selection, stream/file emission where it is not ordered artifact-set
publication, message rendering, and exit mapping.

### Leaf ownership

- Move stable no-follow read/stat behavior to `filesystem_io.py`.
- Move generic scan-exclusion matching out of `settings.py` to a small leaf
  selected during Slice 2. Prefer an existing cohesive path-policy module; add
  `scan_paths.py` only if no existing owner fits.
- Move generic ordered artifact publication to
  `artifact_publication.py`.
- Move eval epoch derivation to `semantic_eval_identity.py`.
- Move analyzer/verifier shared qualification contract data to
  `semantic_qualification.py` or a smaller leaf contract module if the data
  has no qualification behavior.

These moves must reduce import direction or establish one canonical owner.
They are not a license to collect unrelated helpers in a `utils.py` file.

### Cache coordination

Keep the shared state machine inside `semantic_cache.py` unless extraction
would produce a deeper, more cohesive module. One parameterized coordinator
owns guard acquisition, lock creation and validation, ownership tokens,
waiting, completion, cleanup, reincarnation handling, and timeout.

Analyzer, review, and verifier adapters may supply only their key/object
types, paths, object loader/publisher, and closed validation contract. Cache
paths, object bytes, lock ordering, token semantics, audit objects, failure
priority, and cleanup behavior do not change.

### Shipping semantic path

`run_semantic_analysis(SemanticAnalysisRequest) -> SemanticAnalysisRun` remains
the packet/cache/policy gate. The semantic application layer owns current and
historical input preparation, snapshot currentness, ordered publication, and
the application result.

Delete these non-shipping `analysis_llm.py` symbols after migrating unique
tests:

```text
ModelAdapter
_CONTROLLED_PROVIDER
_CONTROLLED_REQUEST
build_prompt
_packet_evidence_bounds
_snippet_evidence_bounds
_has_binding_test_evidence
_parse_model_output
analyze_packets
analyze_exit_code
render_results_jsonl
default_adapter
```

Keep and tighten the shipping provider boundary:

```text
_install_completion_limit_shim
_resolved_model_adapter_parts
default_provider_adapter
_semantic_response_schema
resolve_model_name
```

Make `_resolved_model_adapter_parts` require request identity and remove its
legacy no-request branch. Do not retain a compatibility shim for the dead
path. Before deletion, search package exports, current docs, and production
callers. Stop and re-evaluate only if that search finds a documented public
Python API or a real caller.

### Naming and cohesion

Renames occur only when a symbol is moved or its responsibility changes. A
name should read as a short declarative statement at the call site. Avoid both
opaque abbreviations and names that encode the whole call protocol.

Large cohesive parser and cache files are acceptable. Complexity is reduced
with named phases, explicit state, and typed intermediate results. Uncoupled
publication and filesystem primitives move to their own owners.

Temporal state machines are discrete objects with one explicit transition
surface and comprehensive table-driven transition tests. Do not describe a
stateful traversal, ordered validator, or application workflow as a state
machine merely because it carries intermediate state.

`markdown-it-py` remains the sole Markdown block-syntax parser.
`markdown_specs.py` consumes its CommonMark tokens and applies Backstitch's
cross-block traceability semantics: section ownership, mapping attachment,
directive windows, and suppression/skip placement. The discrete object for
that work is a traceability token reducer, not a Markdown parser; name it
`_TraceabilityReducer`. It must not rediscover headings, lists, fences, or
code blocks from raw Markdown when `markdown-it-py` already supplies the
corresponding token structure.

### Dependency Decision: Pydantic

Do not add Pydantic in this remediation.

Backstitch already has closed contract validation in
`contract_validation.py`. Its important properties are exact accepted types,
no coercion, closed fields, stable error class and precedence, NFC/path rules,
canonical ordering, and byte-for-byte recomputation. Pydantic would remove
some field-check boilerplate, but it would not solve layer ownership,
provenance, config merging, state-machine duplication, or canonical identity.
Its generated errors, traversal order, and coercion defaults would themselves
become observable contract risks.

Pydantic is currently transitive through `llm`, not a declared Backstitch
dependency. Repository policy also requires the owner to add dependencies.
Do not import a transitive dependency.

Revisit only through a separate dependency proposal that proves all of:

- a direct, owner-approved dependency and locked version;
- strict, no-coercion, `extra = "forbid"` behavior;
- exact error-class, error-priority, and canonical-byte parity;
- no import of `llm` or provider code on deterministic paths;
- a net reduction in code and McCabe complexity on a representative closed
  artifact; and
- no loss of family-specific diagnostics or authoritative recomputation.

## Invariants And Constraints

1. Public CLI grammar, stdout/stderr shape, exit precedence, artifact schemas,
   canonical bytes, and diagnostic identities do not change unless this plan
   names an existing bug fix.
2. The config parity correction may reject a historical config that was
   incorrectly accepted. Switching current containment from physical
   `Path.resolve` semantics to the specified lexical rule may also change
   symlink-sensitive current acceptance. Both are named corrections and must
   be characterized before implementation.
3. Historical config reads only Git object bytes. Profile-root containment is
   lexical for both adapters and the common assembler must not cause a
   checkout, symlink resolution, stat, or live-filesystem read.
4. `check`, `packets`, obligation commands, help, and version do not import
   `llm`, read credentials, construct an adapter, or touch provider state.
5. Current semantic analysis still captures one accepted source image,
   recaptures before publication, and publishes nothing current after drift.
6. Immutable cache object paths and bytes are unchanged. Lock acquisition
   remains lexically ordered. Cleanup and audit retain current token and
   failure semantics.
7. Eval epoch bytes are unchanged. The authoritative validator independently
   reconstructs inputs; sharing the encoder must not make report data
   authoritative.
8. Generic artifact replacement is distinct from cache immutable no-replace
   publication. Do not merge these contracts.
9. Controlled model fakes remain at the provider boundary. Filesystem, Git,
   TOML parsing, lock races, publication, and CLI tests use real boundaries.
10. Existing owner worktree changes are preserved. Each slice checks overlap
    before editing.
11. No broad renaming, formatter-driven churn, or file-size quota is part of
    this plan.
12. Every touched enumerable contract element has a firing test.
13. Every new mapping has a reciprocal code or test docstring. Every spec
    lists this plan, and every touched implementation doc lists the governing
    specs and plan.

## Hidden Couplings And Failure Priorities

- Config resolution couples paired-root reset, extension order, provenance,
  unknown-key policy, model selection, profile selection, and final
  cross-field validation. The common assembler owns all of them.
- Snapshot reading and config reading share no-follow primitives but have
  different source authority. A shared leaf must not collapse that authority.
- Semantic cache lock files are process-coordination state. Race tests must
  retain real files, processes or threads, tokens, and timeouts.
- Provider construction occurs after all deterministic preflight that can
  fail. Application extraction must preserve that order.
- Artifact staging and final replacement participate in currentness. Moving
  functions must not move the recapture boundary.
- Validator extraction may change which error is reported first. Preserve
  existing validation order through explicit phase order and golden hostile
  fixtures.
- Parser extraction may lose closure state or line-byte semantics. Prefer
  explicit parser state and phase helpers in the same module over many tiny
  modules.
- Removing `default_adapter` affects live transport scaffolding. Migrate those
  tests to `default_provider_adapter`; do not keep production dead code for a
  test preflight.
- C901 counts nested functions separately. The architecture gate must scan the
  same paths as CI and fail on nested outliers too.
- `backstitch check` evaluates reciprocal mappings and plan/spec references.
  Traceability is part of every slice, not a final repair-only activity.

Failure priority remains: invalid input/config, corrupt cache, provider or
publication failure, and incomplete work are exit 2; target findings are exit
1; clean results are exit 0. Refactoring may not let a lower-priority finding
mask a tool failure.

## Proposed Spec Delta

Promote this text exactly unless independent review records a justified
deviation.

### Add `docs/specs/02-backstitch-core.md` [SC-17]

Add after the [SC-16] implementation-mapping block and before
`## Related Plans`:

> ## 17. Internal Architecture And Dependency Direction [SC-17]
>
> The static runtime import graph among `backstitch.*` modules is a directed
> acyclic graph. A function-local import remains an edge and does not excuse an
> internal cycle. Lazy imports are permitted at the external provider
> quarantine, but no lazy import may create an internal strongly connected
> component.
>
> Dependency direction is leaf primitives and closed contracts, then source
> and configuration adapters, then domain owners, then application workflows,
> then CLI adapters. The CLI owns argument parsing, translation to typed
> application requests, rendering, and public exit mapping. It does not own
> domain computation, snapshot or cache lifecycle, or artifact-set
> publication.
>
> Each supported behavior has one shipping orchestration path, and behavioral
> tests exercise that path. A test-only duplicate orchestration path is not a
> supported interface. Cohesion, shared state, and lifecycle determine module
> boundaries; file length alone does not. Generic no-follow I/O, identity, and
> artifact-publication primitives have one leaf owner when they are genuinely
> independent of a domain lifecycle.
>
> Names changed by architecture work read as short declarative statements at
> their call sites. Architecture work does not require a standalone rename
> wave.
>
> Executable gates enumerate the internal import graph and enforce zero
> strongly connected components larger than one. Ruff enforces a McCabe
> ceiling of 39 over production code. Lower-scoring functions remain
> reviewable design debt; the ceiling is not a claim that every permitted
> function is simple.

Strategy B promotes [SC-17] only when its complete implementation mapping and
reciprocal docstrings exist. The final mapping includes the real application
and leaf owners, `tests/test_architecture.py`, `pyproject.toml`, and
`.github/workflows/ci.yml`.

### Amend `docs/specs/02-backstitch-core.md` [SC-10]

Add to required proof surfaces:

> - an enumerated runtime-import graph test proving [SC-17]'s DAG and layer
>   boundary without hiding function-local imports;
> - configured C901 verification over the same production paths as CI;
> - registry consistency tests named and documented as consistency tests, plus
>   separate firing fixtures that reach each diagnostic through its real
>   producer; constructing the producer's output type is not firing proof; and
> - application-boundary tests proving CLI adapters preserve public
>   bytes/exits while deterministic commands do not import provider code.

### Amend `docs/specs/03-backstitch-configuration.md` [CFG-5.1]

Add after the sole-owner paragraph:

> Filesystem discovery and Git-blob lookup are source adapters only. Both
> produce the same ordered configuration-layer envelope and call one effective
> settings assembler/finalizer. That owner alone performs merge, provenance
> projection, model selection, typed parsing, unknown-key and cross-field
> checks, and final paired-root containment.
>
> After [CFG-4]'s user and environment expansion, final profile-root
> containment is lexical for every adapter. Join a relative root to the target
> repository root, normalize `.` and `..`, and compare normalized path equality
> or ancestry. Containment does not call `Path.resolve`, `realpath`, `stat`, or
> another filesystem operation; physical symlink and no-follow enforcement
> belongs to repository capture. Given equal defaults, environment, and layer
> bytes with no CLI overlay, both adapters yield equal non-operational settings
> and identical profile-root containment. Operational output, cache,
> qualification-artifact, and target-root addresses may differ only in adapter
> normalization: the filesystem adapter may preserve its physical
> canonicalization, while the blob adapter validates and normalizes them
> lexically because they are not historical gate authority. Operational source
> provenance may also differ. Blob-backed resolution never consults the
> checkout or live filesystem.

### Amend `docs/specs/08-intent-coverage.md` [COV-5]

Add after the Git-object baseline paragraph:

> Historical repository configuration uses [CFG-5.1]'s common effective
> settings assembler and final validation. An invalid historical
> configuration fails before baseline comparison. Git-blob lookup supplies
> bytes and source provenance only; it is not a second merge or validation
> policy.

### Amend `docs/specs/06-semantic-gates.md` [SEM-4]

Add to the lock-state-machine contract:

> Analyzer, evidence-stable review, and verifier single-flight use one
> parameterized internal ownership coordinator. It owns guard acquisition,
> lock creation and validation, ownership tokens, waiting, completion,
> reincarnation handling, cleanup, and timeout. Family adapters supply only
> key/object types, paths, completion loading/publication, and their closed
> object validation. The shared implementation does not change family object
> bytes, paths, lexical lock order, audit records, cleanup behavior, or failure
> priority.

### Amend `docs/specs/07-verification-and-evidence-cases.md` [EVC-10.1]

Add immediately after the effective-epoch formulas:

> One code-owned
> `derive_eval_search_epoch(domain, base, corpus_sha256, trial_index)` function
> owns the closed domains `eval-analyze` and `eval-verify`, inserts the single
> `:` separator, and hashes the exact object above. Producer and authoritative
> validator both call it. The validator independently supplies and rechecks
> every input; a report never supplies an epoch prefix or hash preimage.

### Implementation mapping reconciliation with no normative delta

These are implementation and documentation reconciliation tasks, not
additional spec text. Do not add paraphrased normative sentences during
promotion. Update each mapping only when its real owner lands:

- [SC-7] and [EVC-5.1]: map the semantic application owner after it becomes the
  sole current and replay orchestration path. The existing single-interface
  contract already excludes the raw-packet test path.
- [SEM-3], [EVC-3.1], and [EVC-10.1]: map identity and qualification leaves
  with reciprocal docstrings after their import direction changes.
- [EVC-5.1], [SEM-7], and [COV-9]: map
  `artifact_publication.py` after that owner and its tests exist. Immutable
  cache no-replace publication remains under [SEM-4].
- [SEM-10]: add the race, timeout, reincarnation, token-mutation, cleanup, and
  shared-coordinator proof with the implementation.
- [CFG-9] and [EVC-12.2]: add filesystem-versus-blob parity matrices in the
  config slice, including paired-root reset and invalid final containment.

### Backlinks and index

Add this plan to `## Related Plans` in specs 02, 03, 05, 06, 07, and 08.
Update mappings only for real owners created in the matching slice. Add
[SC-17], its [SC-10] proof bullets, and the specs-index entry atomically in the
final architecture/traceability slice.

## Dependency-Ordered Implementation Tasks

### Spec-promotion slice: independent review and promotion

1. Review this plan against the current tree and the named reference
   architectures.
2. Resolve every review finding in the review log.
3. Promote the exact behavior-specific amendments and plan backlinks. Defer
   [SC-17], its [SC-10] bullets, and index entry under Strategy B.
4. Record the promoted spec tree/commit identity in "Spec Baseline".
5. Run spec/plan traceability, the full self-corpus gate, and suppression
   inspection before code changes.

Stop if promotion cannot be made zero-warning without weakening traceability.

### Slice 1: config convergence and parity

1. Add failing parity tests for equal filesystem/blob layers, paired-root
   replacement/reset, invalid final containment, unknown keys, extension
   order, and profile/model selection. Add symlink and `.`/`..` fixtures that
   distinguish lexical normalization from `Path.resolve`.
2. Add a real Git-baseline acceptance case whose historical config violates
   final containment and must exit 2 before comparison.
3. Inventory every committed profile-root configuration and current
   containment test. Record whether lexical normalization changes any current
   accept/reject result; any change is the intended [CFG-5.1] correction named
   by this plan.
4. Replace `config.py::resolve_profile_root` with one pure lexical normalizer
   used by final containment. Snapshot/capture code retains physical no-follow
   enforcement.
5. Define one internal normalized layer envelope.
6. Refactor both source adapters to call one assembler/finalizer.
7. Preserve blob-only historical reads and provenance distinctions.
8. Update [CFG-4], [CFG-5.1], [CFG-6], [CFG-9], [COV-5], [EVC-12.2],
   tests, and implementation
   docs in the same slice.

Review this slice independently because it changes a fail-closed boundary.

### Slice 2: leaf primitives and import DAG gate

1. Add the reusable import-graph discovery in `tests/test_architecture.py`. It
   resolves module-scope and function-local internal imports and computes SCCs.
   In this slice, assert specifically that `settings` and
   `repository_snapshot` no longer share an SCC; do not yet claim the whole
   graph is acyclic.
2. Characterize the planned layer-boundary table, but defer its zero-cycle and
   forbidden-direction enforcement to Slice 3 when all current SCCs are gone.
3. Move stable no-follow read/stat primitives to `filesystem_io.py` and update
   the canonical-owner inventory.
4. Move scan-exclusion matching to its cohesive leaf owner.
5. Remove the `settings`/`repository_snapshot` cycle and private cross-module
   imports.
6. Update [CFG-5.1], [EVC-8.2], [INV-11], repository maps, and reciprocal
   docstrings. Do not add the [SC-17] mapping yet.

### Slice 3: semantic identity and qualification direction

1. Add producer/validator tests for the closed eval epoch domains, one
   delimiter, mutation sensitivity, and unknown-domain rejection.
2. Add `semantic_eval_identity.py` and make producer and authoritative
   validator call it.
3. Move shared analyzer/verifier qualification facts and prompt/contract
   descriptors to lower-level owners.
4. Remove the `semantic_analysis`/`semantic_eval` and
   `semantic_identity`/`semantic_verification` SCCs.
5. Complete the architecture gate: assert zero SCCs, add the small explicit
   layer-direction table, and test forbidden direction and private
   cross-layer imports. No permanent SCC allowlist is permitted.
6. Prove the authoritative validator still recomputes inputs rather than
   trusting report identity. Pin that the shared epoch helper reproduces the
   exact existing producer and validator bytes for both domains despite their
   current delimiter conventions.
7. Update [SC-17], [SEM-3], [SEM-8], [EVC-3.1], [EVC-10.1],
   implementation docs, and
   reciprocal docstrings.

At the end of this slice the internal import graph must be a DAG.

### Slice 4: generic artifact publication owner

1. Write real-filesystem tests for exclusive staging, fsync, ordered
   replacement, callback failure, partial-publication reporting, and staging
   cleanup.
2. Move `_fsync_directory`, `atomic_replace_bytes`, staging, ordered set
   publication, and the partial-publication error to
   `artifact_publication.py`.
3. Keep report schema/validation in report modules.
4. Keep immutable cache publication separate.
5. Update CLI/application, semantic eval, semantic analysis, and coverage
   callers.
6. Update [EVC-5.1], [SEM-7], [COV-9], [SC-17], repository maps, and
   reciprocal docstrings.

### Slice 5: application seams and thin CLI

Proceed one command at a time. Each command move is a coherent review point.

1. Check: move snapshot capture, report construction, warning collection, and
   failure classification behind a typed check application request and result.
   Leave format selection, suppression display selection, output emission, and
   exit mapping in CLI.
2. Coverage: move repository-state, historical-state, ratchet, report build,
   and publication orchestration behind a typed coverage application request
   and result. Leave argparse/render/exit mapping in CLI.
3. Packet: move runtime construction, packet generation, optional report
   construction, and ordered artifact-set publication behind a typed packet
   application request and result. Leave argument-combination errors,
   human-readable messages, and exit mapping in CLI.
4. Analyze: move current/historical input validation, capture/readiness/
   packetization, semantic runner invocation, recapture, and ordered
   publication behind a typed semantic application request and result.
5. Obligation: move snapshot/domain orchestration behind a typed obligation
   application request and result. Reuse and deepen `obligation_api.py` or
   `obligation_runtime.py` if that is more cohesive than a new module; record
   a deviation before changing the planned filename.
   Deviation recorded 2026-07-29: deepen `obligation_api.py` as the typed
   application seam instead of adding the initially proposed
   `obligation_application.py`. The API owner already defines every
   transport-neutral operation, success envelope, closed failure, cursor, and
   response budget consumed by the CLI. It can therefore absorb snapshot and
   domain orchestration as one deep interface while continuing to delegate
   reusable snapshot/inventory construction to `obligation_runtime.py`.
   Adding a separate application filename would leave either the request/result
   or the envelope/failure contract as a pass-through wrapper.
6. Preserve lazy provider construction and exact public outputs/exits with
   explicit-versus-new-entry-point equivalence tests.
7. Reduce `cli._cmd_coverage` below the final complexity ceiling.
8. Update [SC-5], [SC-7], [EVC-5.1], [EVC-8.3], [EVC-8.7], [COV-9],
   [SC-17], implementation docs, and reciprocal docstrings.

### Slice 6: shared cache ownership coordinator

1. Build a parameterized state-machine fixture that runs the same real
   race/reincarnation/timeout/token-mutation/cleanup cases through analyzer,
   review, and verifier adapters.
2. Extract one internal ownership coordinator inside `semantic_cache.py`.
3. Keep family-specific object validation, loading, and publication in thin
   adapters.
4. Preserve exact paths, bytes, lexical multi-key ordering, cleanup audit, and
   failure precedence.
5. Reduce `analyze_with_cache` below the final complexity ceiling by naming
   preflight, acquisition, provider, and publication phases.
6. Update [SEM-4], [SEM-10], [SC-17], implementation docs, and reciprocal
   test references.

Use real filesystem and concurrency. Do not replace the core proof with mocked
`open`, lock, clock, or publication calls.

### Slice 7: remove the non-shipping analyzer

1. Confirm no production/export/current-doc caller with `rg`.
2. Migrate unique normalization cases to `tests/test_semantic_evidence.py`:
   wrong packet ID or classification, invariant weak-binding downgrade,
   missing binding evidence, out-of-region or empty evidence, blank paths, and
   boolean line coordinates.
3. Keep ordering/concurrency and partial-failure/exit-2/canonical-output proof
   in shipping `tests/test_semantic_analysis.py`. Add plain and fenced non-JSON
   variants only if not already covered.
4. Convert unique adapter tests to `default_provider_adapter`: exact request
   controls, schema, provenance, model mismatch, completion shim, default
   model resolution, JSON-mode-off behavior, and one-call/no-fallback errors.
5. Convert live helper/proxy tests and prompt budgets to
   `default_provider_adapter`, `model_request_bytes`, and contract-3 evidence.
6. Delete only the first symbol block under "Shipping semantic path", from
   `ModelAdapter` through `default_adapter`, and remove stale imports.
   Explicitly preserve the following "Keep and tighten" block, including
   `default_provider_adapter` and `resolve_model_name`.
7. Update canonical-owner inventories, the stale `artifact_contracts.py`
   comment, implementation docs 02, 04, and 07, and reciprocal mappings.
8. Require `rg` over `backstitch`, `tests`, and `docs/implementation` to find
   none of the removed symbols. Historical closed plans are not rewritten.

Do not migrate tests that only prove malformed raw packets can reach the old
adapter. The shipping path validates packet artifacts before that boundary.

### Slice 8: complexity ratchet A, extreme outliers

Use characterization and hostile fixtures before refactoring. Preserve error
priority, ordering, byte/line behavior, and closed schema acceptance.

1. `validate_coverage_report`: split ordered section validators that return
   typed indexes/context. Keep authoritative cross-field recomputation after
   shape validation.
2. `parse_markdown_spec_bytes`: name token-reduction state and phases; extract
   handlers inside the cohesive module. Keep `markdown-it-py` as the sole
   Markdown syntax parser. Model Backstitch's cross-block token semantics as
   the discrete `_TraceabilityReducer` state machine and add a comprehensive
   table-driven transition matrix covering valid transitions, invalid
   transitions, attachment ownership, and directive-window closure.
3. `_resolve_references`: separate symbol-table construction, scope binding,
   one-reference resolution, and edge projection.
4. `_static_syntax_facts`: centralize syntax/scope policy and split reference,
   binding, and projection phases.
5. Bring all four below 60, configure Ruff
   `[tool.ruff.lint.mccabe] max-complexity = 60`, and add an explicit C901
   step to `.github/workflows/ci.yml` over `backstitch` and `bin`. Normal
   `ruff check .` does not select C901 and is not sufficient.

Review each domain independently. A function moved unchanged does not count as
a complexity fix.

### Slice 9: complexity ratchet B, final ceiling

Reduce the other ten baseline scores at or above 40. Use the same pattern:
shape phases, typed intermediate state, and one authoritative cross-field
phase. Do not relax errors or split cohesive lifecycles across files.

Set `max-complexity = 39` only after every production function, including
nested functions, passes. Keep the explicit CI C901 step and record the new
score of all 14 baseline outliers in the implementation record.

### Slice 10: test semantics, naming, and documentation reconciliation

1. Rename the synthetic all-fire test to a registry/context consistency test
   and correct its docstring.
2. Maintain an enumerated producer-firing matrix that invokes real
   coverage/policy/report paths for each affected code/context.
3. Review mocks in touched tests. Keep controlled provider and subprocess
   boundaries; remove only mocks that bypass the behavior claimed by a test.
4. Review names changed in prior slices at their call sites. Rename only
   unclear touched symbols, and update reciprocal references in the same
   change.
5. Update implementation docs 02, 04, 07, 08, and 09, plus repository and
   agent inventory maps where ownership changed.
6. Reconcile all spec mappings, Related Plans backlinks, code/test docstrings,
   and the plan's implementation record.
7. Record a durable lesson only if implementation exposes a reusable
   correction not already covered by current guidance.

### Final slice: gates, review, and landing record

1. Run all focused, acceptance, CI-equivalent, architecture, C901,
   suppression, and self-corpus gates below.
2. Run an independent full-diff review with emphasis on contracts,
   concurrency, validation precedence, and traceability.
3. Resolve or explicitly reject every finding with evidence.
4. Update the implementation and verification record with changed files,
   commands, observed results, residual risks, and review identity.
5. Do not call the work complete until it is committed by owner authorization.
   If the owner wants an uncommitted review, report that state explicitly.

## Testing Plan

### Anti-mocking rules

Keep real:

- filesystem and no-follow file identity;
- TOML bytes and extension order;
- Git object reads and merge-base history;
- import graph enumeration;
- cache paths, guard/lock files, tokens, races, and timeouts;
- artifact staging, fsync, replacement, and cleanup;
- parser bytes, spans, and line endings;
- the traceability reducer's table-driven state transitions over
  `markdown-it-py` tokens;
- CLI subprocess output and exit codes; and
- authoritative artifact reload/recomputation.

Use controlled fakes only for:

- the external model/provider boundary;
- deterministic clocks or randomness where the contract injects them; and
- fault injection that cannot be produced safely otherwise, while retaining a
  real boundary test for the normal path.

### Required focused proof

- current/blob config parity and invalid-containment Git acceptance;
- zero import SCCs and forbidden layer directions;
- eval epoch mutation/domain/delimiter parity;
- three-family cache state-machine matrix;
- real ordered publication and partial-failure behavior;
- CLI versus typed application output/exit equivalence;
- shipping semantic ordering, continuation, partial failure, and canonical
  output;
- migrated normalization and provider-boundary cases;
- producer-firing diagnostics, separate from registry consistency; and
- characterization fixtures for every refactored complexity outlier.

### Acceptance and negative paths

Run `tests/acceptance/` after every boundary-crossing slice. The final run must
include [SC-10]'s real Git, invalid config, malformed artifact, provider
failure, concurrent order, replay, currentness, and self-round-trip probes.

Each new happy path needs at least one malformed input, stale/corrupt state,
or failure-order test. Each new enumerable architecture or diagnostic contract
needs a firing test.

## Verification And Gates

Per slice, run the smallest focused set plus:

```bash
uv run ruff check .
uv run ruff format --check
uv run mypy backstitch bin/release.py tests --config-file pyproject.toml
uv run backstitch check --repo-root .
```

Cache, semantic application, dead-path removal, and complexity slices also run
their named broader suites from the task descriptions.

Final local CI-equivalent commands:

```bash
uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm and not benchmark"
env -u BACKSTITCH_LIVE_LLM uv run pytest tests/live/test_live_llm.py -q -o run_live_llm=false
uv run pytest tests/acceptance -q
uv run ruff check .
uv run ruff format --check
uv run mypy backstitch bin/release.py tests --config-file pyproject.toml
uv run ruff check backstitch bin --select C901 --output-format concise
uv run pytest tests -q -n 0 -m benchmark
uv run coverage erase
uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm and not benchmark" --cov=backstitch --cov-report=
uv run coverage report --show-missing
uv run coverage xml
uv run backstitch check --repo-root .
uv run backstitch check --repo-root . --show-suppressions
```

The GitHub CI matrix remains the authority for Python 3.11 and 3.14 hermetic
jobs. The binary-wheel matrix remains the authority for Python 3.11 through
3.14 across supported Linux, macOS, and Windows architectures, including
locked dependency installation from wheels. Those multi-runtime and
multi-platform checks cannot be reproduced by one local environment and are
named residual gates until the branch runs remotely. The release workflow's
build/install checks remain release-only gates.

If `--show-suppressions` is not valid in that position, use the parser's
documented placement and record the exact command. The observed final result
must be exit 0, zero errors, zero warnings. Every governed suppression must
have a valid spec declaration and nonblank rationale. Every eligible
suppression packet must have a current semantic result or reviewed disposition
under the applied configuration.

The live provider suite is environment-dependent and is not required without
credentials. It must collect and skip cleanly when disabled. Hermetic proxy and
provider-adapter tests are mandatory.

## Rollout, Rollback, And One-Way Doors

This is an internal refactor except for three deliberate corrections:

1. blob-backed historical config now rejects inputs already invalid under the
   final-root contract;
2. current and historical profile-root containment use the same lexical rule
   instead of consulting the live filesystem; and
3. undocumented direct imports of the legacy analyzer cease to work.

Spec promotion lands before code. Each implementation slice must be coherent,
green, reviewed, and independently revertible with its matching mappings/docs.
Do not mix cache-format changes, public CLI changes, or policy changes into
these slices.

There is no cache migration and no persistent data rewrite. Rollback is a
code/spec/doc revert of the affected slice. Existing cache objects remain
valid because bytes and paths do not change.

The dead Python import removal is a source-compatibility one-way door for
undocumented consumers. The pre-delete export/doc/caller search is the gate.
If it finds a supported consumer, stop and create an explicit deprecation plan;
do not silently keep two orchestration paths.

The config correction can expose an invalid merge-base config in ratchet CI or
change a current symlink-sensitive containment result. Slice 1 records the
committed-config and fixture delta before implementation. An invalid
relationship must be named and exit 2. Rollback restores the divergent,
live-filesystem-dependent policy, so the preferred recovery is to correct the
root values or current policy rather than reintroduce the old behavior.

Post-release success signals:

- no internal import SCC;
- no config parity failure;
- no cache race or publication regression;
- no production function above the configured complexity ceiling;
- no import of provider code by deterministic commands; and
- zero-warning self-corpus and acceptance gates.

## Stop-And-Re-Evaluate Gates

Stop and update this plan before proceeding if:

- config parity requires live-filesystem access during historical resolution;
- the cache coordinator needs a storage-path, object-schema, lock-order, or
  cleanup-token change;
- CLI extraction changes output bytes, exit precedence, provider preflight, or
  currentness timing;
- eval identity parity would require changing existing epoch bytes;
- a current documented/exported consumer of the legacy analyzer is found;
- a complexity refactor changes accepted artifact shape or first-error order;
- the DAG gate cannot represent a justified runtime cycle without a permanent
  allowlist;
- a new dependency appears necessary; or
- self-corpus green requires a suppression rather than a mapping/backlink fix.

## Independent Review Loop

Required review points:

1. plan and exact spec delta before promotion;
2. spec promotion before code;
3. config parity slice;
4. import/identity DAG slices;
5. artifact and application boundary slices;
6. cache coordinator slice;
7. dead-path removal slice;
8. each complexity domain group;
9. final complete diff and verification record.

Each review receives the governing spec refs, invariants, focused commands,
changed files, and observed results. The reviewer checks the diff, not only the
author's summary. Findings are recorded below with disposition and evidence.
A different model family is preferred for the final +P review.

## Review Log

### 2026-07-29: independent full-plan review

Scope: full plan, exact spec delta, hardening, verification, and Pydantic
decision against the current tree and repository runbooks.

Findings and dispositions:

- P0: Strategy A contradicted a proposed [SC-17] mapping to files that do not
  exist. Accepted. Promotion now omits the mapping; mappings land with real
  owners and reciprocal docstrings.
- P1: part of the claimed exact spec delta was only a summary. Accepted. It is
  now mapping/documentation reconciliation with no normative delta.
- P1: comprehension checks and a key-file map were missing. Accepted and
  added.
- P1: C901 was only a manual command, not a durable CI gate. Accepted. The
  complexity slice now changes `.github/workflows/ci.yml`.
- P2: the permanent spec included the transient ceiling of 60. Accepted. The
  spec now states only the final ceiling of 39.
- P2: `Slice 0` was reserved for acceptance-suite creation. Accepted. The
  heading is now "Spec-promotion slice."
- P2: local "CI-equivalent" commands omitted coverage and did not state remote
  matrix residuals. Accepted and added.
- P2: plan type and structured deviation metadata were missing. Accepted. A
  follow-up review found the first table still used the wrong columns; it now
  uses the runbook's exact spec-reconciliation fields.

Review result: PASS after follow-up review. The amended plan passed
`git diff --check`, the zero-warning self-corpus gate, and suppression
inspection. The reviewer found the Pydantic decision sound.

### 2026-07-29: direct Claude other-model review

Reviewer: Claude Code 2.1.207 via direct read-only `claude -p`, not through a
skill. Raw review:
`/Users/van/.claude/plans/you-are-reviewing-only-floofy-raven.md`.

Claude independently verified the complexity counts, three import SCCs,
config divergence, dead analyzer, misleading test, eval-epoch duplication,
spec anchors, and the `taut`/`simplebroker` layering comparison.

Findings and dispositions:

- High: [CFG-5.1]'s parity promise conflicted with current
  `Path.resolve`-based containment and historical no-filesystem authority.
  Accepted. The proposed contract now defines pure lexical containment for
  both adapters, names the current semantic correction, adds
  symlink/normalization characterization, and updates rollout risk.
- High: Slice 7's deletion instruction could be read to include the adjacent
  production keep-list. Accepted. It now names only the `ModelAdapter` through
  `default_adapter` deletion block and explicitly preserves the shipping
  provider symbols.
- Medium: Slice 2 could not assert a zero-SCC graph while two semantic SCCs
  remained until Slice 3. Accepted. Slice 2 now proves only the
  settings/snapshot correction; Slice 3 lands the complete DAG and layer gate.
- Low: insertion location, baseline plan-owned files, exact eval-byte
  compatibility, and `Class:` metadata needed precision. Accepted and
  corrected.

Review result: findings incorporated. Final amended-plan verification is
recorded below.

## Implementation And Verification Record

Implementation started on 2026-07-29. Work remains uncommitted at the owner's
request; completion and landing gates have not been claimed.

Plan-authoring verification on 2026-07-29:

- direct other-model review: Claude Code 2.1.207 via read-only `claude -p`;
  four findings groups incorporated;
- `git diff --check`: exit 0;
- `uv run backstitch check --repo-root .`: exit 0, zero errors, warnings, and
  infos; and
- `uv run backstitch check --repo-root . --show-suppressions`: exit 0, zero
  errors, warnings, and infos; 190 governed suppressions displayed.

### 2026-07-29: Slice 1, config convergence and parity

Changed owners and tests:

- `backstitch/settings.py` now has one `_assemble_settings` owner for defaults,
  ordered file-layer merge, provenance, model selection, overlay merge, typed
  parse, unknown/cross-field validation, and final paired-root containment.
  Filesystem and Git-blob paths now only acquire ordered `_ConfigLayer`
  envelopes.
- `backstitch/config.py` now owns pure lexical root normalization. Historical
  resolution rejects a relative repository root and does not call
  `Path.cwd`, `Path.resolve`, `realpath`, or `stat` for path normalization.
- `tests/test_config_parity.py`, `tests/test_settings.py`, and
  `tests/test_cli.py` cover equal layer bytes, provenance projections, model
  source, profile selection, default `check` and `analyze`, extension/reset,
  unknown keys, lexical `.`/`..`, symlink-sensitive containment, blob-only
  path normalization, and real Git-baseline invalid containment.
- [CFG-4], [CFG-5.1], [CFG-9], [COV-5], and [EVC-12.2] mappings and
  implementation docs were reconciled with the new owners.

Committed-root inventory: `backstitch/defaults.toml` and `pyproject.toml` use
plain `backstitch`/`tests` roots. Product-eval fixtures use plain `src`/`tests`
roots; `tests/fixtures/config_project/.backstitch.toml` uses plain `src`.
No committed configuration uses absolute, dot-segment, parent-segment, or
symlink-alias profile roots. The lexical correction therefore changes no
committed accept/reject result. The new symlink fixture records the deliberate
correction: lexical alias spelling outside a declared code-root spelling is
rejected even when the live filesystem points it inside.

Observed focused verification:

- `uv run ruff check backstitch/settings.py backstitch/config.py
  tests/test_settings.py tests/test_config_parity.py tests/test_cli.py`: exit 0.
- `uv run mypy backstitch/settings.py backstitch/config.py`: exit 0.
- `uv run pytest -q tests/test_settings.py tests/test_config_parity.py
  tests/test_cli.py -x`: exit 0.
- After the strengthened provenance/default-command/path matrix,
  `uv run pytest -q tests/test_settings.py tests/test_config_parity.py -x`:
  exit 0.

The first independent review returned NOT PASS: it found duplicated
adapter-side merge/provenance, a remaining blob `Path.cwd` call, thin parity
assertions, and missing plan/mapping evidence. All findings were accepted and
corrected. A second review found the model-selection case still inherited the
packaged model; a complete non-default file descriptor and explicit selected
model, revision, available-model, and source assertions now close that gap.
Final follow-up review result: PASS with no open P1/P2 findings. The reviewer
observed `git diff --check`, 186 focused tests including the Git-baseline
case, Ruff on all five changed Python files, and mypy on the same files.

Residual risk: local tests cover POSIX lexical and symlink behavior. Native
Windows path spelling and the remote Python 3.11/3.14 matrix remain CI gates.
The assembler is internal, so downstream private imports are unsupported; its
observable contract is exercised through both public resolution functions.

### 2026-07-29: Slice 2, leaf primitives and import gate

Changed owners and tests:

- `filesystem_io.py` now owns the stable six-field stat identity and bounded
  no-follow regular-file read. `repository_snapshot.py` retains whole-capture
  inventory, retries, immutable-view construction, and snapshot identity.
- `scan_exclusions.py` now owns pure normalized exclusion matching for current
  and historical adapters. `settings.py` no longer imports
  `repository_snapshot`, and historical intent no longer imports exclusions
  through settings.
- `alignment_eval.py`, `semantic_cache.py`, and
  `semantic_eval_reports.py` import the public filesystem leaf directly.
  Production search finds no private import of the moved stat/read symbols.
- `tests/test_architecture.py` parses every package file, includes function-
  local imports, computes deterministic SCCs, asserts the full graph has no
  multi-module component, checks a small ranked owner table for upward imports,
  and rejects private symbol imports across those ranks.
- [CFG-5.1], [INV-11], and [EVC-8.2] mappings, canonical-owner assertions,
  the repository map, and implementation docs now name the leaf owners.

Observed focused verification:

- Architecture, canonical-owner, settings/config parity, repository snapshot,
  intent history, alignment eval, semantic cache, and semantic report tests:
  exit 0.
- Ruff and format checks on the eleven affected Python files: exit 0.
- Mypy on the eleven affected production files: exit 0.
- `git diff --check`: exit 0.
- `uv run backstitch check --repo-root .`: exit 0, zero errors, warnings, or
  infos (121 sections, 333 mappings, 408 code references, 878 edges).

The full DAG/layer assertions were pulled into this slice after the semantic
slice removed the final observed SCCs. Combined Slice 2/3 independent review
result: PASS with no open P1/P2 findings. Residual risk is the POSIX-specific descriptor implementation;
unsupported platforms retain the existing explicit fail-closed path and the
native remote matrix remains authoritative.

### 2026-07-29: Slice 3, semantic identity and import direction

Changed owners and tests:

- `semantic_eval_identity.py` now owns the closed `eval-analyze` and
  `eval-verify` effective-epoch encoder. Producer and authoritative validator
  both call it with independently derived inputs.
- `semantic_eval_observation.py` now owns provider-free corpus observation and
  variant derivation, removing the `semantic_analysis` to `semantic_eval`
  import direction.
- `semantic_verification_contract.py` now owns verifier prompt metadata,
  immutable claim/request/identity records, the closed contract error, and
  cache-independent work records. `semantic_identity` depends on this leaf
  rather than the verifier runtime.
- `semantic_verification.build_verification_work` owns verifier work
  construction through a narrow structural settings protocol. Existing
  supported import surfaces remain available where they were already used.
- `tests/test_semantic_eval_identity.py` pins both exact historical epoch
  bytes, one separator, the closed domains, and mutation of every input.
  Existing authoritative report mutation tests continue to prove independent
  recomputation.
- [SEM-3], [EVC-3.1], and [EVC-10.1] mappings now name the new real owners.

Observed focused verification:

- Ruff on the nine changed semantic production files and five focused test
  files: exit 0.
- Mypy on the nine changed semantic production files: exit 0.
- `uv run pytest -q tests/test_semantic_eval_identity.py
  tests/test_semantic_analysis.py tests/test_semantic_eval_corpus_v3.py
  tests/test_semantic_eval_reports_v3.py
  tests/test_semantic_verification.py -x`: exit 0.
- An AST graph including module-scope and function-local imports reported no
  internal SCC. The durable full-DAG/layer gate lands with the concurrent
  architecture-test slice before this slice is closed.

The first independent review returned NOT PASS for the incomplete layer gate,
missing [SEM-8] owner documentation, and lack of forged stored-epoch tests.
All findings were accepted. The final combined Slice 2/3 follow-up returned
PASS with no open P1/P2 findings. Residual risk is limited to remote
Python/platform matrices; the semantic contracts and exact bytes are locally
green.

### 2026-07-29: Slice 4, generic artifact publication

`artifact_publication.py` now owns same-directory exclusive staging, file and
directory durability, atomic single-file replacement, ordered set
publication, callback timing, cleanup, and partial-publication context. CLI,
semantic analysis, semantic eval, coverage, and packet callers import this
public leaf directly. `semantic_reports.py` retains artifact schema and report
validation only. Immutable cache no-replace publication remains separate in
`semantic_cache.py`.

Real-filesystem tests cover staging collisions, exact bytes, file/directory
fsync, currentness callback success and failure, ordered replacement, partial
publication metadata, and cleanup. Publication/report/architecture/owner-pin,
full CLI, semantic analysis, semantic eval, analysis-packet, and focused
failure suites passed. Ruff, format, mypy, `git diff --check`, and the
zero-warning self-corpus gate passed. [EVC-5.1], [SEM-7], and [COV-9]
mappings/docs name the new owner. Independent review result: PASS with no open
P1/P2 findings. The reviewer confirmed all six definitions were AST-identical
moves and immutable hard-link/no-replace cache publication remained separate.

Residual risk: directory fsync behavior varies by platform; the implementation
preserves the prior fail-closed platform behavior and native CI remains the
cross-platform gate.

### 2026-07-29: Slice 5, check and packet application seams

`check_application.py` now owns snapshot capture, pipeline/report
construction, warning collection, and gate classification.
`packet_application.py` owns obligation-runtime construction, packet/report
assembly, deterministic failure precedence, and ordered artifact-set
publication. `cli.py` retains argument validation, rendering, messages,
output emission outside artifact-set publication, and exit mapping.

Direct application tests and baseline/current CLI differentials preserve exact
exit codes, stdout, stderr, warning order, packet bytes, snapshot/discovery/
report errors, and partial-publication context. Deterministic import probes
show neither seam loads `llm` or `analysis_llm`. Focused CLI, application,
architecture, canonical-owner, and publication suites passed; Ruff, format,
strict mypy, `git diff --check`, and the zero-warning self-corpus gate passed.
Independent review result: PASS after one stale unused `get_profile` import
was removed. No P1/P2 finding remains. Residual gates are the final full and
cross-platform suites.

The coverage portion of Slice 5 adds `coverage_application.py` as the owner of
accepted repository capture, current and historical definition projection,
bounded ratchet loading, policy/drift/history folding, report construction and
validation, effective gate classification, and durable output publication.
`cli._cmd_coverage` retains argument validation, text/JSON rendering, stdout
emission, and public error/exit mapping. `profiles.configured_profile` is the
single current/historical projection from resolved settings to an immutable
profile.

Direct application tests compare application results with CLI bytes and exits
for text and JSON, exercise real output replacement, pin snapshot-failure
precedence before CLI mapping, and prove publication failures remain one-line
exit-2 errors with staging cleanup. The focused coverage, reporting, Git
baseline, config-parity, architecture, and full CLI suites passed. Ruff,
format, and strict mypy pass for the touched production and test files. The
explicit max-38 C901 probe reports only the pre-existing `_cmd_analyze`;
`_cmd_coverage` is below the plan ceiling. [SC-5], [EVC-8.7], [EVC-12.2],
[COV-3], [COV-5], and [COV-9] mappings and implementation ownership docs name
the new seam. The hermetic self-corpus gate passed with 121 sections, 358
mappings, 436 code refs, 942 edges, 9 invariants, 17 binds, and zero issues.
Independent review result: PASS after adding a deletion-sensitive real CLI
matrix that joins every declared intent diagnostic code, context, and default
severity to its producer. No P1/P2 finding remains. No public grammar, report
schema, output bytes, exit code, failure precedence, Git/provider boundary, or
configuration semantics changed.

The semantic portion of Slice 5 adds `semantic_application.py` as the typed
owner of current/historical input validation, current repository readiness and
packetization, `run_semantic_analysis` invocation, currentness recapture, and
ordered current artifact publication. `cli._cmd_analyze` retains argument
parsing, the lazy `analysis_llm` import, provider-adapter factory construction,
rendering and messages, and public exit mapping. Provider factories cross the
application boundary only as closures and remain unconstructed until the
semantic cache/runtime requests one.

Direct application tests compare current and historical report bytes and exits
with the CLI, pin validation before provider construction, prove recapture
precedes every publication, retain ordered partial-publication context, and
execute the application without importing `llm` or `analysis_llm`. The focused
semantic, report, verification, publication, check, coverage, packet,
architecture, and full CLI suites passed 301 tests; all 45 acceptance probes
passed. Ruff, format, strict mypy, `git diff --check`, and the explicit max-39
C901 gate passed for the seam and CLI. The hermetic self-corpus gate passed
with 121 sections, 367 mappings, 443 code refs, 964 edges, 9 invariants,
17 binds, and zero issues. [SC-5], [SC-7], [SEM-1], [SEM-7], [EVC-5.1],
[EVC-8.7], and [EVC-9] mappings and ownership docs name the seam.
Independent review found and fixed one exact-byte regression: current-mode
exit-2 runs again emit stderr only and publish nothing, while historical
exit-2 replay still renders its report. Separate CLI and real-application
tests pin both rendering and non-publication. Final result: PASS with no P1/P2
finding. No public CLI grammar, packet/report/result bytes, exit code, failure
precedence, currentness timing, provider construction order, replay semantics,
or publication order changed.

The obligation portion of Slice 5 deepens `obligation_api.py` as the typed
application seam. It now owns accepted snapshot/runtime construction, all five
read-mode branches, candidate-count enrichment, closed cursor and discovery
failures, response budgeting, deadlines, and post-capture internal-failure
identity. `obligation_runtime.py` remains the reusable domain runtime shared
with packet and semantic consumers. `cli.py` retains invocation/config
validation, profile selection, JSON/text rendering, stream selection, and exit
mapping.

Direct application and CLI differential tests pin exact success and cursor
failure bytes. Existing CLI and acceptance tests exercise the same seam for
configured limits, complete-catalog unreadability, candidate pagination and
detail, source-declared summaries, deadline precedence, read-only behavior,
and snapshot-bearing post-capture `ValueError` and runtime failure. The
application boundary uses frozen dataclasses rather than Pydantic: its callers
are internal typed Python code, while the existing CLI validators and closed
envelope constructors already own external validation. Adding Pydantic here
would duplicate those contracts and increase deterministic-command import
cost without creating a new trust boundary.

Focused obligation/API/runtime, architecture, owner-pin, CLI, and relevant
acceptance suites pass. All 45 acceptance probes pass. Ruff, format, strict
mypy, the explicit max-39 C901 gate, and `git diff --check` pass. The hermetic
self-corpus gate passes with 122 sections, 395 mappings, 447 code refs, 1010
edges, 9 invariants, 17 binds, and zero issues. Independent review remains
PASS after the application was changed to call
`ObligationRuntime.evidence_summary` as the single shared summary owner and an
architecture test prohibited the duplicate direct builder path. No P1/P2
finding remains. No public grammar, core or rendered bytes, exit code, failure
precedence, snapshot identity, filesystem behavior, or provider-import
boundary changed.

The intent diagnostic producer-firing matrix is separate from registry
consistency and invokes the real coverage application, policy projection,
report build, and CLI render path.
`test_every_intent_diagnostic_context_fires_from_a_real_producer` runs the
seven real repository/Git scenarios, collects every emitted
`(code, context, default_severity)` tuple, proves effective severity is
unchanged under the fixture policy, and compares the exact union with
`coverage_application.INTENT_DIAGNOSTIC_CONTEXTS`:

| Code/context | Real producer test |
|---|---|
| `INTENT_UNCOVERED_DEFINITION` (`repository`, `patch`) | `test_coverage_ratchet_marks_dirty_uncovered_definition_as_patch` |
| `INTENT_INHERITED_ONLY` (`repository`, `patch`) | `test_coverage_ratchet_fires_inherited_repository_and_patch_contexts` |
| `INTENT_EXEMPTION_UNUSED` | `test_coverage_fires_unused_exemption_and_floor_regression` |
| `INTENT_EXEMPTION_UNREASONED` | `test_coverage_fires_unreasoned_marker_and_unimplemented_requirement` |
| `INTENT_REQUIREMENT_UNIMPLEMENTED` | `test_coverage_fires_unreasoned_marker_and_unimplemented_requirement` |
| `INTENT_DRIFT_SUSPECT` | `test_coverage_ratchet_computes_committed_drift_from_exact_projections` |
| `INTENT_COVERAGE_FLOOR_REGRESSION` | `test_coverage_fires_unused_exemption_and_floor_regression` |
| `INTENT_COVERAGE_INCOMPLETE` (`repository`, `patch`) | `test_coverage_ratchet_fires_incomplete_repository_and_patch_contexts` |
| `INTENT_COVERAGE_POLICY_REGRESSION` | `test_coverage_ratchet_blocks_unacknowledged_committed_policy_weakening` |

### 2026-07-29: Slice 6, shared cache ownership coordinator

`semantic_cache._OwnershipCoordinator` is the discrete state machine for all
analyzer, evidence-stable review, and verifier ownership lifecycles. It creates
the exact family lock/token bytes and owns guard acquisition, claim and retry,
waiting, timeout, token checks, completion, reincarnation, failure cleanup,
and cleanup guidance. Family adapters supply paths, completion loading,
publication, removal, and closed object validation. A review lease retains the
same coordinator object from lexical multi-key acquisition through recheck,
nested analysis, baseline publication, release, or failure cleanup.

`tests/test_semantic_cache_coordinator.py` table-drives the same real-filesystem
transition scenarios across all three families: valid claim/check/
completion, unchanged-owner failure cleanup, no-steal timeout, owner
reincarnation, stale-owner cleanup against a successor token, and waiter
completion. Existing deadline-publication pins now construct the real
coordinator with production family callbacks; the removed family-specific
wait wrappers have no remaining references. Lock bytes match the pre-change
family bytes under fixed token/time inputs, and immutable cache publication
remains distinct from generic artifact replacement.

`analyze_with_cache` McCabe changed from 44 to 34. The coordinator, semantic
cache, verification, and semantic-analysis suites passed 180 focused tests;
Ruff, format, strict mypy, `git diff --check`, and the explicit max-39 gate
passed. [SEM-4] and [SEM-10] mappings/docs name the coordinator and matrix.
Independent review result: PASS after the reviewer required coordinator-owned
token creation, review-owned retry/timeout, the three-family matrix, removal
of dead family wait wrappers, and migration of their two contention pins.
No P1/P2 finding remains. Remote platform races remain a CI gate.

### 2026-07-29: Slice 7, non-shipping analyzer removal

The legacy string-only `ModelAdapter`, controlled test identities,
`default_adapter`, duplicate prompt builder, packet-analysis loop, model-output
parser, exit helper, evidence-bound helpers, and result renderer are removed
from `analysis_llm.py`. The module now owns only the shipping lazy-`llm`
provider request, schema, wire, provenance, completion-limit, and model-name
adapter behavior. `_resolved_model_adapter_parts` requires the complete
`RequestIdentity`; there is no request-mode inference or weaker retry.

Unique tests moved to the shipping interfaces. `semantic_evidence` directly
proves blank, whitespace, boolean-coordinate, empty-snippet, and out-of-region
rejection. Provider tests prove exact controls, packet-bound schema, closed
provenance, model mismatch, unsupported request rejection, JSON-mode-off
behavior, completion-token translation, and one-call/no-fallback errors.
Live proxy and prompt-budget tests use `default_provider_adapter`,
`model_request_bytes`, and the current packet schema. Canonical-owner and
implementation documentation no longer name removed symbols.

Focused provider, remediation, evidence-boundary, live-helper, and
canonical-owner suites passed. Ruff, formatting, strict mypy, `git diff
--check`, and the max-39 C901 gate passed. Repository-wide `rg` finds no
removed symbol in production, tests, active specs, or implementation docs.
Independent review result: PASS after adding deletion-sensitive shipping tests
for wrong packet identity, cross-kind classification, invariant
`ok`-to-`weak_binding` downgrade, insufficient invariant evidence, and fenced
otherwise-valid JSON rejection. No P1/P2 finding remains.

### 2026-07-29: Slice 8, Markdown parser complexity

`parse_markdown_spec_bytes` moved its coupled closure state into one cohesive
token-reduction object in `markdown_specs.py`. `markdown-it-py` remains the
sole Markdown syntax parser; the Backstitch object owns only mapping
attachment, heading/invariant ownership, directive windows, suppression order,
line/byte projection, and memo behavior.

McCabe changed from 106 to 5; the largest new handler is 11. The explicit
max-39 C901 gate passes. Parser, evidence-spike, review-remediation,
canonical-owner, and Git-baseline tests passed (257 focused tests). Ruff,
format, strict file mypy, and `git diff --check` passed. A differential run
matched `dataclasses.asdict` output from the pre-change parser across 477
committed Markdown files and five hostile fixtures. Independent review result:
PASS with no open P1/P2 findings. The review expanded the differential gate to
524 parses across both unknown-code modes and independently checked memo
partitioning/identity reuse. Residual risk is unenumerated CommonMark byte
streams beyond the committed corpus and hostile fixtures.

Owner-directed follow-up implemented: the misleading `_MarkdownSpecParser`
name is now `_TraceabilityReducer`, `advance` is its single block-token
transition surface, and `tests/test_traceability_reducer.py` table-drives
heading, paragraph, ordinary and invariant lists, HTML, fence, indented code,
ordered lists, blockquotes, mapping ownership, no-ID and invalid headings,
reserved-skip acceptance/invalidation, and directive-window closure.
`markdown-it-py` continues to own every Markdown syntax decision. The reducer
table and full Markdown suite pass with Ruff, format, and strict mypy green.
Independent rereview required deletion-sensitive rows for ordinary-bullet and
ordinary-HTML closure plus both reserved-skip outcomes; final disposition is
PASS after both mutations failed the expanded 16-case table. No P1/P2 finding
remains. This is an implementation-proof correction with no public or
normative behavior delta.

`evidence_discovery._resolve_references` now delegates to one cohesive
`_ReferenceResolver` with named symbol-table, definition/import/shadow binding,
lexical lookup, per-reference resolution, candidate materialization, and graph
projection phases. McCabe changed from 81 to 1; the largest new helper is 10.
Evidence-discovery, boundary-pin, obligation API, semantic-evidence, and
canonical-owner suites passed (182 focused tests). Ruff, format, strict file
mypy, `git diff --check`, and the explicit max-39 gate passed. A differential
run matched the pre-change hostile catalog exactly: 76 nodes, 96 static edges,
and 173 charged work units. Independent review result: PASS with no open
P1/P2 findings. The reviewer also matched all public candidate projections
and exact exception type/code/message/details at every work-unit ceiling from
0 through 300.

`code_parser._static_syntax_facts` now delegates to one typed
`_StaticSyntaxCollector` with cohesive reference traversal, binding traversal,
owner-scope, and ordered-projection phases. Outer McCabe changed from 74 to 1;
the former nested `visit_reference` changed from 40 to 17, now the largest
helper. Code-parser, Python-reference, evidence-discovery, boundary,
cache-performance, semantic-evidence, and canonical-owner suites passed 227
parser assertions. Ruff, format, strict file mypy, `git diff --check`, and the
explicit max-39 gate passed. A differential run matched complete
`ParsedModule` values for 234 tracked Python files and eight hostile fixtures,
including static facts, ordering, scopes, lines, and byte offsets. Independent
review result: PASS with no open P1/P2 findings after 484 independent parses
across both static-facts modes.

`intent_coverage_reporting.validate_coverage_report` now delegates to one
cohesive ordered `_CoverageReportValidator`. It retains shape and aggregate
validation before authoritative source-fact and report-hash recomputation.
McCabe changed from 117 to 1; the largest new phase is 9. Intent coverage,
reporting, Git-baseline, architecture, and selected CLI suites passed 88
focused tests. Ruff, format, strict file mypy, `git diff --check`, and the
explicit max-39 gate passed. Independent review result: PASS with no open
P1/P2 findings. The reviewer matched exception type and message across 716
recursive mutations, plus exact dictionaries and rendered JSON bytes for
valid reports and rich ratchet projections. Residual risk is the
non-exhaustive space of possible hostile JSON streams.

### 2026-07-29: Slice 9, final non-semantic complexity ceiling

`alignment_eval._validate_task` and `_load_alignment_eval_result` now delegate
to ordered local validation phases. McCabe changed from 52 and 42 to 1 and 1.
Focused alignment tests passed 102 cases with exact valid-output and hostile
first-error parity. Independent review matched the valid Phase A projection
and nine ordered hostile outcomes; result: PASS with no P1/P2 finding.

`artifact_contracts._packet_v3_shape_error` now delegates to cohesive
closed-record phases. McCabe changed from 49 to 3; the largest helper is 12.
Focused packet-contract tests passed 136 cases. Independent review matched 249
recursive and competing-error cases; result: PASS with no P1/P2 finding.

`python_refs.parse_python_bytes` now delegates to local source-decode, parser,
error, and projection phases. McCabe changed from 45 to 5; the largest helper
is 12. Python-reference and integration suites passed 160 focused tests. A
differential matched complete output or exact competing error behavior across
251 committed Python files, twelve hostile modes, and three competing-error
cases. Independent review matched 476 tracked and hostile cases across both
unknown-code modes; result: PASS with no P1/P2 finding.

All fourteen baseline functions at McCabe 40 or above are now below 40.
`pyproject.toml` configures `max-complexity = 39`, and CI runs an explicit
`ruff check backstitch bin --select C901` step because normal Ruff selection
does not include C901.

### 2026-07-29: Slice 9, semantic report validator complexity

`semantic_reports._validate_analysis_report_source_shape` now separates the
closed source/scope/count header from ordered diagnostic, problem, cache, and
verification recomputation through a typed intermediate record.
`semantic_reports._packet_report_source_shape` similarly separates the source,
derivation, and readiness header from alignment-audit validation and final
issue, packet, kind-count, content-hash, and timestamp validation. The phases
remain local to the cohesive report-contract module.

McCabe changed from 54 to 34 for the analysis validator and from 59 to 20 for
the packet validator; the largest extracted phase is 21. Characterization
tests pin canonical output and exact first-error priority across phase
boundaries. The [SEM-7] text, reciprocal test backlink, and deterministic
semantic-gate implementation table now state the ordered closed-shape boundary
explicitly. Semantic-report, semantic-analysis, and packet-production suites
passed 216 focused tests. Ruff, format, strict mypy, `git diff --check`, and
the explicit max-39 gate passed. A HEAD/current differential matched exact
normalized output or exception type/message across 516 valid and mutated
schema-2 through schema-5 cases. The self-corpus gate passes in the integrated
worktree. Independent review matched 23 phase-priority and canonical-output
cases; result: PASS with no P1/P2 finding. Residual risk is the non-exhaustive
space of hostile JSON values beyond the systematic schema and nested-field
differential.

### 2026-07-29: Slice 9, semantic eval corpus validator complexity

`semantic_eval_reports.load_semantic_eval_corpus` now delegates to one
cohesive `_SemanticEvalCorpusValidator`. Its ordered local phases load frozen
fixture trees, validate critical sets, validate gold identities and
cross-links, enforce control semantics, validate reviewed historical units,
and apply enforce-only corpus floors. The loader and its coupled validation
state remain in the closed semantic-eval contract module.

McCabe changed from 59 to 3; the largest new phase is 6. A characterization
test pins exact first-error priority across manifest schema, fixture identity,
critical-set, gold, and later historical phases. Corpus, report, eval, identity,
and semantic-analysis suites passed 85 focused tests. Ruff, format, strict
mypy, `git diff --check`, and the explicit max-39 gate passed. A HEAD/current
differential matched exact success projections, canonical manifest values,
fixture bytes/executable bits, or exception type/message for both committed
corpora and 497 recursive hostile mutations. Implementation ownership docs
name the ordered corpus/fixture validator; normative mappings did not change.
The self-corpus gate passes in the integrated worktree. Independent review
reloaded both committed corpora in report and enforce modes with exact output;
result: PASS with no P1/P2 finding. Residual risk is the non-exhaustive space
of hostile JSON values beyond the recursive mutation catalog.

### 2026-07-29: Slice 10, architecture promotion and final integration

[SC-17] is active and indexed. Its reciprocal mappings and code docstrings name
the leaf contracts, application entry points, CLI adapter, import-DAG proof,
Markdown token reducer, and CI complexity gate. [SC-10] now requires the
whole-package graph/layer proof, explicit max-39 C901 run, real diagnostic
producer matrix, exact application/CLI byte-and-exit comparisons,
provider-free application execution, and comprehensive reducer transition
table. The repository map and affected implementation docs identify the same
owners and boundaries.

One clean local integration pass produced:

- the full hermetic test suite at 100% with exit 0 under
  `pytest tests -q -n auto --dist loadgroup -m "not live_llm and not benchmark"`;
- all 45 [SC-10] acceptance probes passing;
- Ruff, the explicit `--select C901` ceiling, format-check, strict mypy over
  154 source files, and `git diff --check` passing;
- the corpus traceability suite passing; and
- `backstitch check --repo-root .` reporting 122 sections, 395 mappings,
  447 code refs, 1010 edges, 9 invariants, 17 binds, and zero errors, warnings,
  or infos.

The refreshed governed-suppression audit reports 263 suppressed findings:
235 test-citation, 15 DOM-meta, 7 verification-meta, 2 documentation-meta,
2 evidence-process, and 2 deferred-MCP findings. The deferred-MCP pair
includes the one explicit `EVC-8.6` obligation skip. Every record names a
valid declaration and has a nonblank rationale; there are zero unsuppressed
errors, warnings, or infos.

The required independent final review ran through Claude Code via direct
read-only `claude -p`, not through a skill. It returned PASS with no P1/P2
finding after inspecting the complete tracked and untracked diff. It
independently confirmed that function-local imports participate in the DAG
gate, the non-shipping analyzer is absent, `markdown-it-py` remains the sole
Markdown parser, `_TraceabilityReducer` and `_OwnershipCoordinator` are
discrete table-tested state objects, and the application seams own real
workflows. Claude could not execute `uv` inside its review harness; the clean
local integration pass above supplies that missing execution evidence.

Residual risks are the native remote platform matrices, the non-exhaustive
space of hostile JSON and Markdown inputs beyond the differential and
transition catalogs, and compatibility for undocumented imports from the
deleted analyzer path. The intended config correction also makes historical
blob resolution reject a final uncontained test root where the duplicate
pre-change path failed to apply the existing contract. No public CLI grammar,
artifact schema or bytes, documented exit code, policy, persistence format, or
shipping semantic classification changed.

The owner authorized the integrated landing after the local and independent
review gates passed. Native remote platform matrices remain residual release
evidence; they do not invalidate the completed local architecture correction.

For each slice, record:

- changed files;
- contract refs and mappings changed;
- commands and observed results;
- before/after complexity where relevant;
- independent review and disposition;
- deviations from this plan; and
- residual risk.

## Out Of Scope

- changing public CLI grammar, artifact schemas, exit codes, policy, or
  semantic classification;
- adopting Pydantic or another validation framework;
- reducing all 142 baseline C901 findings to Ruff's default 10;
- a repository-wide rename campaign;
- splitting files based on line count;
- redesigning cache formats or adding cache cleanup features;
- adding a supported Python library API for semantic analysis;
- rewriting historical completed plans; and
- running a paid live-provider qualification without owner direction and
  credentials.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|
| [SC-17], [SC-10] | Promote the new architecture section without mappings under Strategy A, then add mappings by slice. | Promote [SC-17], its new [SC-10] proof bullets, index entry, mappings, and reciprocal docstrings atomically under Strategy B in the final architecture/traceability slice. | The real promotion gate proved an unmapped active [SC-17] is `BSS007` error, so Strategy A cannot keep the required zero-warning corpus without an invalid suppression. | No text change; change promotion sequencing only. This proposal is resolved by the reviewed plan deviation and cannot remain pending at completion. |
| [SC-17] | Add application entry points for coverage, analyze, obligation, and packet only if later inspection found packet orchestration. | Add typed check and packet application entry points as well as coverage, analyze, and obligation entry points. | Direct inspection found `_cmd_check` owns snapshot/report/policy workflow and `_cmd_packets` owns runtime/generation/report/publication workflow. Leaving either in `cli.py` would contradict the proposed application/CLI dependency direction. | No normative text change; the proposed [SC-17] already requires the CLI to exclude domain computation, snapshot lifecycle, and artifact-set publication. Expand only the final implementation mapping and proof fixtures. |
| [SC-17] | Name the extracted Markdown state object as a parser and rely on parser differentials plus hostile fixtures. | Keep `markdown-it-py` as the sole Markdown syntax parser; rename the Backstitch object `_TraceabilityReducer` and add a comprehensive table-driven transition matrix. | The owner clarified the repository rule that state machines are discrete objects with table-based transition proof. Inspection confirmed the object reduces `markdown-it-py` tokens and owns only cross-block traceability semantics. | No normative behavior change. The final [SC-17] proof mapping names the reducer and its transition matrix without claiming a second Markdown parser. |

Any deviation must be recorded before implementation continues.

## Fresh-Eyes Review Checklist

- Does any local import still conceal an internal SCC?
- Can filesystem and blob config resolution diverge on any final validation?
- Does a new application module own a real workflow, or is it a shallow pass
  through?
- Did CLI extraction preserve provider construction and snapshot currentness
  order?
- Does the cache coordinator truly own all three lifecycles?
- Are cache publication and generic artifact replacement still distinct?
- Is effective epoch recomputed from independent inputs with one encoder?
- Did removal tests move to shipping owners instead of preserving dead
  concepts?
- Did complexity fall through named phases rather than move unchanged?
- Are parser/validator first-error and byte-order contracts pinned?
- Are test names honest about whether a real producer fired?
- Are mocks confined to real external boundaries?
- Do touched names read clearly at call sites without needless churn?
- Are long files still cohesive, and are new leaf files genuinely generic?
- Do all mappings, backlinks, docstrings, and implementation docs agree?
- Does `backstitch check --repo-root .` report zero errors and warnings?

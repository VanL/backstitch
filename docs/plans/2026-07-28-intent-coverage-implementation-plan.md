# Intent Coverage Implementation Plan

Status: implementation in progress after internal slice reviews and an external
Claude implementation review. Deterministic report, current-range ratchet,
bounded stale history, and closed-report slices are implemented. Semantic
mapping-quality qualification and rollout gates remain open as recorded below.

Class: **5 + risky** under [DOM-15]. This promotes an entire proposed product
spec, adds a public CLI command, configuration table, diagnostics, JSON
artifact, Git subprocess boundary, history traversal, and semantic
qualification-corpus cases. Rollout order and backward compatibility matter.

Plan type: **implementation with coordinated spec revision**.

## Outcome Checklist

- [x] Promote the Intent Coverage spec from `Proposed` to `Active` only after
  the clarification delta in this plan receives independent review.
- [x] Add deterministic definition coverage for modules, classes, functions,
  async functions, and methods under configured Python code roots.
- [x] Distinguish direct, inherited, exempt, and uncovered definitions without
  weakening current trace-graph rules.
- [x] Report the reverse complement: active requirement sections with no live
  implementation owner.
- [x] Add reasoned inline and configured exemptions with unused-exemption
  auditing.
- [x] Add report and ratchet modes, repository-derived Git baselines, monotonic
  floors, and exact changed-definition semantics.
- [x] Add current-diff drift suspects, Git-derived stale-document trends, and a
  durable commit-trailer acknowledgment that does not create Backstitch-owned
  state.
- [x] Keep the triage loop read-only. Backstitch ranks work and shows supported
  source edits; it never writes source or stores dispositions.
- [x] Add spec-side mutation cases to the semantic qualification corpus without
  changing packet schemas or claiming that the current semantic lane sees a
  diff it does not receive.
- [x] Dogfood report mode before enabling ratchet policy.
- [x] Add firing tests for every `BSN*` diagnostic, public field, config key,
  CLI branch, exit class, and suppression/acknowledgment state.
- [x] Pass the full suite, acceptance suite, static checks, self-corpus gate,
  and independent implementation review.

## Implementation Checkpoint (2026-07-28)

Implemented slices now include the canonical definition inventory, closed
coverage settings and BSN registry, repository-state classification, reverse
requirement complement, reasoned exemptions, schema-1 report validation,
public report mode, bounded object-database baselines, exact changed-definition
patch findings, first-parent policy transitions, and exact current-range drift
events. Bounded stale-document history now reconstructs its oldest inspected
parent tree from immutable Git objects, reuses revision projections across the
overlapping current and stale ranges, indexes changed paths to affected edges,
and publishes explicit complete or truncated trends. Behavioral CLI tests
cover every BSN001-BSN009 diagnostic in repository and patch contexts where
applicable, plus both complete and truncated stale-history reports. The final
Claude review found two medium contract gaps: event rows were not canonicalized
at the report boundary, and multi-file transition framing lacked a firing test.
Both are fixed; the review's cheaper inherited-accounting and ambiguous-owner
branches are also pinned by tests.

The report-mode dogfood result is complete but fails the Slice 9 activation
stop condition:

```text
direct 185; inherited 2925; exempt 0; uncovered 582; total 3692
direct_rate 0.050108; accounted_rate 0.050108
active unimplemented requirements 23
```

Inherited coverage still dominates direct coverage. Therefore this change does
not enable a repository floor, change this repository to ratchet mode, or add
the CI `--require-ratchet origin/main` assertion. That is a required stop, not
an omitted rollout step.

Remaining work:

- Slice 8 semantic mapping-quality qualification (the anti-Goodhart control).
  Source review found that the preregistered label for several new cases
  conflicts with the active analyzer prompt. This requires a separate reviewed
  prompt/spec revision and qualification plan before any live provider call.
  After that revision, report the exact maximum calls/cost and obtain owner
  authorization as required below.
- Slice 9 backlog review. The 582 uncovered and 2925 inherited definitions need
  owner review before exemptions or floors are defensible.
- Final removal of `SUP-COV-INFLIGHT`. COV-1, COV-2, and COV-7 remain
  intentionally suppressed until the open slices close.

## Goal

Implement [COV-1] through [COV-9] as one deterministic, auditable coverage
surface. A user can run `backstitch coverage` to see which Python definitions
are connected to stated intent, which requirements lack live owners, and which
changed contract edges may have drifted. Repositories can begin in advisory
report mode and later enable a diff ratchet without accepting a historical
backlog as new debt.

## Source Documents

Source specs:

- `docs/specs/08-intent-coverage.md` [COV-1] through [COV-9]
- `docs/specs/02-backstitch-core.md` [SC-2] through [SC-6], [SC-8], [SC-10],
  [SC-11], [SC-15], [SC-16]
- `docs/specs/03-backstitch-configuration.md` [CFG-3] through [CFG-9]
- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-2] through
  [EXC-7]
- `docs/specs/05-backstitch-invariants.md` [INV-4], [INV-7], [INV-11]
- `docs/specs/06-semantic-gates.md` [SEM-3], [SEM-6], [SEM-8]
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-7] through [EVC-9],
  [EVC-12]

Predecessor decision record:

- `docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md`
  (COV vocabulary was reconciled, but coverage computation was explicitly
  left for a promoted plan)

Required runbooks:

- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`

## Spec Baseline

- `b33804a03f25168ea02bb4c9dc732c8cabaa2c75`:
  `docs/specs/08-intent-coverage.md` is committed at `Status: Proposed`.
- Coordinated active-spec baseline: the same commit plus SHA-256
  `49f273ae75a1823b803942dde3ea186a440ca68f20ca3e8e7c5c7acb1a43c79a`
  of the worktree diff over `02`, `03`, `04`, `05`, `06`, and `07`. Those
  pending changes implement the separately reviewed default-command and
  evidence-stable reuse work; the Intent Coverage promotion must preserve and
  layer on that exact delta, not reconstruct those files from `HEAD`.
- The same baseline config classifies the whole file through
  `profile.planned_spec_globs` and suppresses its expected
  `SPEC_SECTION_UNMAPPED` findings through `SUP-COV-PLANNED`.
- Promotion baseline: record after the spec-promotion slice. Until then, the
  proposed delta below is a review target, not the governing contract.

## Why Spec Promotion Must Precede Code

The proposed spec states the product direction but leaves several executable
contracts open:

- no CLI owner or exit behavior
- no closed report schema or content-hash preimage
- no canonical definition identity or synthesized-module rule
- no exact direct/inherited precedence
- no configured exemption shape or overlap rule
- no metric denominators, tree-overlap rule, or floor-regression diagnostic
- no Git base, dirty-worktree, untracked-file, rename, or change algorithm
- no binding-test association for drift
- no acknowledgment syntax or stale-history authority
- no way to identify "loop-generated" prose because [COV-6] correctly forbids
  Backstitch-owned proposal state
- no active `SC`, `CFG`, `EXC`, `SEM`, or `EVC` registration for the public
  contracts

Those are product decisions. Implementing them ad hoc would create an
undeclared second spec in code.

## Proposed Spec Delta

Promotion strategy: **C graduation followed by A-style incremental mapping**.
The file already occupies a dedicated planned rung. The spec-promotion slice
will:

1. apply the exact clarifications below;
2. change `Status: Proposed` to `Status: Active`;
3. remove `docs/specs/08-intent-coverage.md` from
   `planned_spec_globs`;
4. replace `SUP-COV-PLANNED` with a temporary exact
   `SUP-COV-INFLIGHT` suppression for `SPEC_SECTION_UNMAPPED`;
5. add no production backlink until the owning code, mapping, and backlink for
   that section land together.

The final traceability slice removes `SUP-COV-INFLIGHT` and its declaration.
Do not leave the graduated file under a planned glob while shipped code cites
it.

### Replace the classification rules in [COV-3] with

> Coverage runs through the public `backstitch coverage` command. It consumes
> the same accepted immutable repository snapshot and raw trace graph as
> `backstitch check`; it never opens a second live-source path. `check`
> remains byte-compatible and does not compute coverage implicitly.
>
> The measured unit is a canonical Python definition. The inventory includes
> one synthesized module definition per parsed Python file plus every
> tree-sitter class, function, and async-function definition. A method is a
> function or async function whose nearest enclosing definition is a class.
> The identity is the tuple `(path, structural_locator)`, where locators are
> `python-module:<module-name>` when the current module-name resolver yields
> one unambiguous name, `python-module-path:<canonical-path>` otherwise, and
> `python-definition:<qualname>:<kind>:<ordinal>`. Ordinal is zero-based among
> same-file definitions with the same normalized qualified name and kind in
> source order. The fallback adds module candidates only where none exist
> today; valid existing evidence-discovery module locators and candidate IDs
> remain byte-identical. Invalid Python path components, duplicate module names
> across roots, and equal-specificity overlapping roots therefore use the
> path fallback. A unique longest matching root owns module derivation;
> `__init__.py` resolves to its containing package name and a root-level
> `__init__.py` falls back to its canonical path. Line numbers are coordinates,
> never identity.
>
> Each definition also has an own-source projection. It contains the
> physical bytes from the start of the attachment line through the end of the
> definition's final physical line, including its terminating LF when present.
> The attachment line is the first decorator line belonging to that definition,
> or otherwise the line containing its `class`, `def`, or `async def` keyword;
> indentation bytes belong to the interval. A definition's final physical line
> is the final line in its tree-sitter node.
> Module bounds are byte `0` through EOF. Before hashing, remove each direct
> child definition's complete attachment-line-through-final-line byte interval,
> including its terminating LF, then concatenate the remaining intervals in
> source order without separators or normalization. A module removes top-level
> class/function spans; a class removes method/nested-class spans. Therefore a
> child body edit changes the child, not its parent. Adding or removing a child
> changes only the child inventory when all remaining parent-owned bytes,
> including blank lines outside the removed interval, remain identical.
> An empty projection hashes the zero-length byte string. Projection comparison
> is byte equality; projection IDs are `sha256:` plus lowercase SHA-256 of the
> exact concatenated bytes.
>
> Existing graph edges identify logical symbols, not physical ordinals. An
> exact `path::symbol` mapping therefore covers every same-path physical
> definition with that qualified symbol. A code reference is joined to the
> unique smallest physical owner span containing its source line; if duplicate
> definitions have indistinguishable owner spans, all matching physical
> definitions receive the edge. Invariant declarations and binds use their
> existing line/start/end coordinates to join to the unique physical
> definition span. No resolver edge schema is silently reinterpreted as
> ordinal-aware.
>
> Classification precedence is `direct`, `exempt`, `inherited`, `uncovered`.
> A matching exemption on a directly covered definition is audited as an
> overlap but cannot reduce direct coverage. A definition is direct when:
>
> 1. its exact owner or a non-module enclosing class/function owner carries a
>    resolving code reference;
> 2. an exact `path::symbol` mapping targets it or a non-module enclosing
>    class/function owner;
> 3. it is the exact target of an invariant declaration or binding edge.
>
> A whole-file mapping or module-level reference makes the module and its
> descendants inherited, never direct. A direct non-module enclosing owner
> makes its descendants direct. A definition is exempt when no direct rule
> applies and at least one valid [COV-4] exemption matches. Everything else is
> uncovered.
>
> Coverage includes every Python file under effective `code_roots`, including
> files under `test_roots`. Reports group production and test trees separately.
> Files outside the accepted snapshot, unreadable files, and syntax-invalid
> files retain their existing deterministic issues and contribute no invented
> definitions. The report lists them as unscannable and marks repository-state
> completeness false. Ratchet mode additionally emits
> `INTENT_COVERAGE_INCOMPLETE` with context `patch` when an added or changed
> Python file is unreadable or syntax-invalid; it cannot pass by shrinking an
> unknown denominator.
>
> The reverse complement includes every active, non-meta requirement section
> whose implementation mappings are absent or have no resolving live target.
> Planned, exploratory, and meta sections are listed with their rung but do
> not count as unimplemented active requirements. This view is derived from
> the raw graph before diagnostic suppression. An absent mapping retains the
> existing `SPEC_SECTION_UNMAPPED` diagnostic and is not duplicated as BSN005.
> The coverage report's `issues` array includes the shared scan's applied
> deterministic issues, including that BSS007, exactly once; coverage neither
> requires a second `check` run nor constructs a second copy. BSN005 fires only
> when mapping declarations exist but none resolves to a live owner. Both
> states appear as unimplemented in the coverage view.
>
> Per-tree totals are assigned by longest matching configured code root.
> Equal-length overlap is a configuration error. Ratios use integer
> numerators and denominators; displayed decimals are presentation only.
> `direct_rate = direct / total` and
> `accounted_rate = (direct + exempt + inherited_when_enabled) / total`.
> A zero-definition denominator yields `null`, never `0` or `1`.

### Add this closed public report contract to [COV-3]

> JSON output is artifact `backstitch-intent-coverage-report`, schema version
> `1`. Its top-level fields are closed and ordered canonically:
>
> | Field | Contract |
> |---|---|
> | `artifact`, `schema_version` | exact identity above |
> | `profile`, `repo_root`, `mode` | effective invocation identity |
> | `metric_identity` | exact ID `intent-coverage-definition-v1`, algorithm version `1`, and the direct/accounted numerator and denominator field names |
> | `baseline` | `null` in report mode; otherwise configured ref, resolved commit, merge base, current snapshot hash, current content hash, baseline/current policy identities, history completeness, and history commits inspected |
> | `summary` | completeness, unscannable-file count, exact direct, inherited, exempt, uncovered, total, active-unimplemented-requirement, policy-regression, drift, stale-trend, and acknowledgment counts plus nullable direct/accounted rates |
> | `trees` | JSON array of path-identified summaries in canonical path order |
> | `floors` | JSON array of scope-identified evaluations, counts, configured targets, and pass states |
> | `unscannable_files` | path, role, and existing structured scan issue identities |
> | `definitions` | identity, coordinates, role, classification, changed flag, governing edges, matching exemptions, and source-slice SHA-256 |
> | `worklist` | JSON array of uncovered definition IDs in deterministic triage order |
> | `requirements` | spec path, section ID, rung, implementation state, and resolved owners |
> | `exemptions` | inline/config origin, selector, reason, matched identities, and overlap state |
> | `policy_events` | changed gate key, baseline/current canonical values, event identity, acknowledgment state, commit, and reason |
> | `drift_events` | edge ID, current/baseline hashes, acknowledgment, reason, and current-diff status |
> | `stale_doc_trends` | edge ID, section-change commit, unacknowledged event count, last event commit, and history completeness |
> | `spec_growth` | changed section count and UTF-8 byte delta for the current diff; no unverifiable authoring-origin claim |
> | `issues` | ordinary structured deterministic issues after applied policy |
> | `report_sha256` | `sha256:` plus SHA-256 of canonical JSON for every preceding field, excluding `report_sha256` itself |
>
> Nested records are closed:
>
> - `metric_identity`: `id: string`, `algorithm_version: integer`,
>   `direct_numerator: "direct"`, `direct_denominator: "total"`,
>   `accounted_numerator: "direct+exempt+inherited_when_enabled"`, and
>   `accounted_denominator: "total"`.
> - `baseline`: `configured_ref: string`, `resolved_commit: lowercase Git
>   object ID`, `merge_base: lowercase Git object ID`,
>   `current_snapshot_sha256: sha256 token`,
>   `current_content_sha256: sha256 token`,
>   `baseline_policy_sha256: sha256 token`,
>   `current_policy_sha256: sha256 token`, `history_complete: boolean`, and
>   `history_commits_inspected: nonnegative integer`. Git object IDs must match
>   the repository object format and are never assumed to be SHA-1.
>   `current_snapshot_sha256` reuses the accepted snapshot identity;
>   `current_content_sha256` hashes canonical JSON of sorted
>   `[canonical_path, source_sha256]` pairs for every in-scope file.
> - `summary`: `complete: boolean`; nonnegative integer fields `unscannable`,
>   `direct`, `inherited`, `exempt`, `uncovered`, `total`,
>   `unimplemented_requirements`, `policy_events`,
>   `acknowledged_policy_events`, `drift_events`,
>   `acknowledged_drift_events`, and `stale_doc_trends`; plus `direct_rate` and
>   `accounted_rate`, each
>   `null` or a finite JSON number derived only for display.
> - a `tree` row: `root: canonical directory string`, `role:
>   "production"|"test"`, the same five definition counts and two nullable
>   rates as `summary`, and `complete: boolean`.
> - a `floor` row: `scope: canonical directory string`; nonnegative integer
>   fields `direct`, `inherited`, `exempt`, `uncovered`, and `total`;
>   `direct_rate` and `accounted_rate` with the summary nullability/rounding;
>   `direct_target` and `accounted_target`, each a finite JSON number in
>   `[0,1]` or null when not configured; and `passes: boolean`.
> - an `unscannable_file` row: `path`, `role`, and nonempty
>   `issue_identities`, where each closed identity has `code: string`,
>   `path: canonical path`, and `line: positive integer|null` and is sorted by
>   `(code, path, line-or-0)`.
> - a `definition` row: `definition_id` (SHA-256 of path and locator), `path`,
>   `structural_locator`, `qualname` (`null` only for fallback modules),
>   `kind: "module"|"class"|"function"|"async_function"|"method"|
>   "async_method"`, `role: "production"|"test"`, positive `start_line` and
>   `end_line`, `tree`, `classification:
>   "direct"|"inherited"|"exempt"|"uncovered"`, `changed: boolean|null`
>   (`null` in report mode), `source_projection_sha256`, sorted
>   `governing_edge_ids`, and sorted `matching_exemption_ids`.
>   A synthesized module uses `start_line = 1`; its `end_line` is the final
>   physical line number, or `1` for an empty file.
> - `worklist` contains each and only `uncovered` `definition_id` once, ordered
>   production before test, then canonical path, then structural locator. Text
>   triage output follows this array. Inherited definitions remain visible in
>   `definitions` and metrics but are not [COV-6]'s uncovered worklist.
> - a `requirement` row: `requirement_id` (the hash defined below), `path`,
>   `section_id`, `rung: "active"|"planned"|"exploratory"|"meta"`,
>   `implementation_state: "implemented"|"absent_mapping"|
>   "declared_without_live_owner"`, and sorted `owner_definition_ids`.
> - an `exemption` row: `exemption_id`, `origin:
>   "inline"|"config_path"|"config_glob"`, `path`, `line: integer|null`,
>   `selector`, `reason`, sorted `matched_definition_ids`, and
>   `state: "used"|"overlap_only"|"unused"`.
> - a `policy_event` row: `event_id`, `key`, `baseline_value`,
>   `current_value` (the two values are canonical JSON values admitted by the
>   corresponding config key), `parent_commit: Git object ID`,
>   `transition_commit: Git object ID|null` (null only for the synthetic
>   accepted-snapshot transition), `acknowledged: boolean`,
>   `acknowledgment_commit: Git object ID|null`, and
>   `acknowledgment_reason: string|null`.
> - a `drift_event` row: `event_id`, `edge_id`, `requirement_id`,
>   `definition_id`, `parent_commit: Git object ID`,
>   `transition_commit: Git object ID|null` (null only for the synthetic
>   accepted-snapshot transition),
>   `base_projection_sha256`, `current_projection_sha256`,
>   `acknowledged: boolean`, `acknowledgment_commit: Git object ID|null`,
>   `acknowledgment_reason: string|null`, and
>   `synthetic_current: boolean`.
> - a `stale_doc_trend` row: `edge_id`,
>   `section_change_commit: Git object ID|null`,
>   `unacknowledged_event_count: nonnegative integer`,
>   `last_event_commit: Git object ID|null`, `history_complete: boolean`, and
>   `commits_inspected: nonnegative integer`. `section_change_commit` is null
>   exactly when the bounded walk ends before finding a governing-section
>   change.
> - `spec_growth`: nonnegative `changed_sections`, signed
>   `utf8_byte_delta`, and sorted `requirement_ids`.
> - each `issue` is the exact existing `Issue` dataclass field set serialized by
>   `Report.to_dict()` (`code`, `severity`, `path`, `line`, `message`,
>   `section_id`, `symbol`, `short_code`, `context`, `default_severity`, and
>   `invariant_id`). `code`, `path`, `message`, and `short_code` are strings;
>   `severity` is `"error"|"warning"|"info"`; `line` is a positive
>   integer or null; `section_id`, `symbol`, `context`, and `invariant_id` are
>   string or null; `default_severity` is the severity vocabulary or null.
>   Coverage does not define a second issue shape.
>
> Stable IDs use the existing `canonical_json_bytes()` function as their
> unambiguous preimage and the `sha256:` lowercase-hex encoding:
> `definition_id = hash(["intent-definition-v1", path,
> structural_locator])`; configured `exemption_id =
> hash(["intent-exemption-v1", origin, selector])`; inline `exemption_id =
> hash(["intent-exemption-v1", "inline", path, line, normalized_reason])`.
> `requirement_id =
> hash(["intent-requirement-v1", path, section_id])`.
> Edge and event preimages are the exact tuples defined in [COV-8] and [COV-5].
> Nullable rates are rounded to six decimal places using decimal
> round-half-even and serialized as the shortest JSON number with that value;
> enforcement never consumes the rounded value.
>
> Arrays use canonical identity order. JSON is stable for the same accepted
> snapshot, Git object database, effective configuration, and command
> arguments. Text is a rendering of the typed report and is never parsed back
> into structure. Sort keys are `tree(root, role)`, `floor(scope)`,
> `unscannable(path, role)`,
> `definition(path, structural_locator)`, `requirement(path, section_id)`,
> `worklist(role-production-first, path, structural_locator)`,
> `exemption(exemption_id)`, `policy_event(event_id)`,
> `drift_event(event_id)`,
> `trend(edge_id)`, and the existing canonical issue key. The validator
> rejects unknown/missing keys,
> wrong nullability, invalid vocabulary, duplicate identities, dangling joins,
> overlapping classification partitions, or noncanonical order. It recomputes
> every definition ID, edge ID, count, rate numerator/denominator, tree
> partition, floor scope/result, exemption join, requirement state,
> worklist membership/order, policy/drift/trend aggregate,
> spec-growth aggregate, and final report hash from separately supplied source
> facts. `report_sha256` is computed by removing that key and passing the
> complete remaining top-level mapping to the existing
> `canonical_json_bytes()` encoding (sorted keys, compact separators,
> ASCII-escaped text, finite numbers), then prefixing the lowercase SHA-256
> hex digest with `sha256:`.

### Replace the exemption rules and diagnostic authority in [COV-4] with

> Inline exemptions use exactly
> `# backstitch: no-spec -- <nonblank reason>`. A candidate is recognized only
> when either (a) tree-sitter classifies it as a comment attached to the
> physical line containing that owner's `class`, `def`, or `async def`
> keyword, after which the comment bytes with leading whitespace removed begin
> exactly `# backstitch: no-spec`, or (b) one complete logical docstring line,
> after removing only its indentation, begins exactly
> `backstitch: no-spec`. A module marker is recognized only by form (b) in the
> module docstring. In both forms the token must end the logical line or be
> followed by ASCII whitespace; a longer token such as `no-specification` is a
> near miss. The exact separator is one or more ASCII spaces, `--`, then one
> or more ASCII spaces. The reason is the remaining UTF-8 text with outer
> Unicode whitespace removed and NFC normalized; it must contain no CR, LF, or
> NUL and encode to at most 4096 bytes.
>
> The recognition table is closed:
>
> | Input | Result |
> |---|---|
> | exact prefix, separator, nonblank reason | valid exemption |
> | exact prefix with no separator | recognized, `BSN004` |
> | exact prefix with separator but empty/whitespace reason | recognized, `BSN004` |
> | exact prefix with malformed separator | recognized, `BSN004` |
> | different prefix/case/spelling or wrong syntax-tree location | inert near miss |
>
> String literals outside the owning docstring, comments on other statements,
> nested example text, and near-miss spellings are inert.
>
> Configured exemptions use:
>
> ```toml
> [[tool.backstitch.coverage.exemptions]]
> path = "generated/client.py" # exactly one of path or glob
> reason = "Generated from the service schema."
>
> [[tool.backstitch.coverage.exemptions]]
> glob = "vendor/**/*.py"
> reason = "Vendored upstream source."
> ```
>
> `path` and `glob` are mutually exclusive repository-relative selectors.
> Configured reasons use the same normalization and byte bound as inline
> reasons. A configured missing, non-string, blank, multiline, NUL-containing,
> or over-limit reason is a configuration error: exit `2`, no report. Config
> order is retained as provenance but does not affect classification.
>
> All matching exemptions appear in the ledger with exactly one state:
> `used` when they match at least one otherwise non-direct definition,
> `overlap_only` when every match is already direct, or `unused` when they
> match no definition. `unused` emits `INTENT_EXEMPTION_UNUSED`;
> `overlap_only` remains visible but emits no unused finding. A recognized
> inline candidate with an invalid reason emits
> `INTENT_EXEMPTION_UNREASONED` and does not exempt anything.
>
> Delete [COV-4]'s existing BSN001-through-BSN005 diagnostics table and the
> paragraphs assigning their family and packaged levels. [COV-9] is the single
> authoritative BSN registry. [COV-4] defines exemption behavior and refers to
> the [COV-9] rows; it does not define a second code meaning or level.

### Replace the ratchet rules in [COV-5] with

> The command has two modes:
>
> - `report`: compute repository-state coverage without invoking Git;
> - `ratchet`: compute repository-state coverage plus a repository-derived
>   aggregate diff and enforce patch/floor contexts.
>
> Ratchet mode requires a nonblank `coverage.ratchet_base` in committed
> repository configuration. There is no CLI base-ref override. Backstitch
> resolves the configured ref to a commit, computes its merge base with
> `HEAD`, reads baseline blobs from the Git object database, and compares them
> with the already accepted current snapshot. It never fetches, executes an
> external diff driver, invokes a shell, trusts pager/editor configuration, or
> reads baseline files through a checkout path.
>
> The current side includes tracked worktree/index changes and untracked Python
> files present in the accepted snapshot. A new file makes every current
> definition changed. A deleted definition has no patch-coverage obligation
> but may make a requirement unimplemented. Renames are remove-plus-add.
> A surviving definition is changed when the canonical source slice selected
> by `(path, structural_locator)` differs byte-for-byte from its merge-base
> slice. Coordinate-only movement outside the slice is not a change.
>
> In ratchet mode, changed uncovered definitions emit
> `INTENT_UNCOVERED_DEFINITION` with context `patch`; changed inherited-only
> definitions emit `INTENT_INHERITED_ONLY` with context `patch` when
> `inherited_counts = false`. Packaged policy makes both patch contexts errors.
> Repository-state contexts remain info. Applied diagnostic policy remains the
> final severity and exit authority.
>
> Floor keys are `direct` and `accounted`, each a finite number in `[0, 1]`.
> Comparison uses integer cross multiplication, not rounded display values.
> A current metric below its configured floor emits
> `INTENT_COVERAGE_FLOOR_REGRESSION` (`BSN007`, packaged error). Baseline floor
> changes are policy transitions handled by BSN009 below, so one config edit
> does not produce two competing diagnostics.
>
> Ratchet authority is closed. A repository-owned config layer is a regular,
> no-follow file inside the accepted repository root that exists in the
> accepted snapshot and is addressable by the same canonical path at the merge
> base. Every effective gate-affecting value must originate only from packaged
> defaults or such repository-owned layers. Ratchet mode rejects home,
> environment, external include, explicit CLI `--config`, CLI `--no-config`,
> CLI `--profile`, and CLI `--option` contributions to gate inputs as an
> invocation error. Only `format`, `output`, the root alias, and the
> `--require-ratchet REF` assertion may be operational invocation overrides.
>
> The canonical policy is the following closed JSON mapping after normal
> config merge, path normalization, and profile selection. Tuple/set-like
> collections are arrays in canonical value order; authored diagnostic and
> suppression rule order remains an array because order affects behavior:
>
> ```text
> {
>   "schema": "intent-coverage-policy-v1",
>   "profile": {
>     "name": string|null,
>     "spec_roots": [string], "code_roots": [string],
>     "test_roots": [string], "planned_spec_globs": [string],
>     "exploratory_spec_globs": [string], "meta_spec_globs": [string],
>     "process_spec_globs": [string]
>   },
>   "exclude": [string],
>   "coverage": {
>     "mode": string, "granularity": string, "inherited_counts": boolean,
>     "ratchet_base": string,
>     "exemptions": [{"id": string, "kind": "path"|"glob",
>                     "selector": string, "reason": string}],
>     "floors": [{"scope": string, "direct": number|null,
>                 "accounted": number|null}],
>     "maximum_baseline_files": integer, "maximum_file_bytes": integer,
>     "maximum_baseline_bytes": integer, "maximum_history_commits": integer,
>     "maximum_git_command_seconds": number,
>     "maximum_git_commands": integer, "maximum_git_output_bytes": integer,
>     "maximum_commit_message_bytes": integer,
>     "maximum_runtime_seconds": number
>   },
>   "diagnostics": {
>     "default_level": string, "fail_on": [string],
>     "suppressible_levels": [string],
>     "levels": [{"selectors": [string], "level": string}]
>   },
>   "suppressions": {
>     "warn_unused_ignores": boolean,
>     "require_suppression_declarations": boolean,
>     "per_file_ignores": [{"selector": string, "codes": [string]}],
>     "per_section_ignores": [{"selector": string, "codes": [string]}],
>     "rules": [{
>       "mechanism": string, "provenance": string, "path": string,
>       "sections": [string], "codes": [string], "declaration": string|null,
>       "origin": {"source": string, "position": integer|null,
>                  "line": integer|null}
>     }]
>   }
> }
> ```
>
> The policy identity is the SHA-256 token of
> `canonical_json_bytes(canonical_policy)`. Presentation-only `format` and
> `output` are intentionally absent. Every transition compares these mappings
> by these stable changed-key names:
>
> - fixed scalar JSON pointers, such as `/coverage/inherited_counts`;
> - set member pointers
>   `/<collection>/<sha256:canonical-json-member>`, with JSON null representing
>   absence;
> - `/coverage/exemptions/<exemption_id>` for one selector/reason row;
> - `/coverage/floors/<sha256:canonical-scope>/<direct|accounted>`; and
> - whole ordered objects `/diagnostics` and `/suppressions`.
>
> The comparison table is executable and closed:
>
> 1. Any change to a nonblank `ratchet_base`, any profile-name change, or any
>    `granularity` change is weakening. A current `report` invocation never
>    opens Git merely to compare its former mode; the trusted CI
>    `--require-ratchet REF` assertion is the authority that makes a
>    ratchet-to-report edit fail closed. Report-to-ratchet is strengthening.
> 2. `inherited_counts` false-to-true is weakening; true-to-false strengthens.
> 3. Removing `spec_roots`/`code_roots`, adding any `exclude` value, adding any
>    planned/exploratory/meta/process glob, or changing `test_roots` is
>    weakening. The reverse set operations strengthen. This rule compares
>    selector strings only and never attempts glob-language inclusion.
> 4. Adding an exemption ID or changing its `kind`/`selector` is weakening;
>    removing one strengthens; a reason-only change is neutral. A changed
>    selector is mechanically one removal plus one addition.
> 5. Lowering/removing a floor is weakening; adding/raising one strengthens.
> 6. Any byte-distinct canonical `/diagnostics` or `/suppressions` object is
>    authority-sensitive and requires acknowledgment, even when a human might
>    judge it stronger. This conservative rule covers `fail_on`, default and
>    per-code/context severity, `suppressible_levels`, per-file/per-section
>    ignores, and governed suppression rules without a second policy
>    interpreter.
> 7. Budget changes are neutral for acceptance because every overrun fails
>    closed with exit `2`; they remain in the policy identity and report.
>
> A weakening or authority-sensitive current event is recorded in
> `policy_events`. If unacknowledged, it emits
> `INTENT_COVERAGE_POLICY_REGRESSION` (`BSN009`, packaged error), including the
> baseline/current policy identities and changed key. BSN009 cannot be
> suppressed or severity-demoted by current policy.
>
> An intentional weakening must be acknowledged by the commit that introduces
> its exact first-parent policy transition:
>
> ```text
> Backstitch-Coverage-Policy-Ack: <policy-event-id> -- <nonblank reason>
> ```
>
> `policy-event-id = hash(["intent-policy-event-v1", parent_commit,
> changed_key, baseline_value, current_value])`. The same bounded trailer
> grammar and exact-transition rules as drift apply. A dirty-worktree
> weakening cannot be acknowledged. An acknowledged event remains in
> `policy_events` but emits no BSN009 `Issue`; only an unacknowledged current
> event enters `issues` and the ordinary exit-1 test. Unknown, malformed,
> duplicate, or pre-acknowledging trailers do not match. This mechanism is for
> explicit, reviewed policy changes. It does not claim to resist a maintainer
> who can also rewrite the CI workflow or Backstitch binary.
>
> Policy transitions are folded over the same first-parent
> `merge_base..HEAD` sequence plus the synthetic accepted-snapshot transition.
> A weakening event remains current only while its weakened value is the final
> effective value; a later strengthening supersedes it. BSN009 is emitted for
> each current event, and its acknowledgment can come only from the commit
> whose parent-to-child transition first introduced that exact final value.

### Add this exact configuration table to [COV-5]

> ```toml
> [tool.backstitch.coverage]
> mode = "report"               # report | ratchet
> format = "text"               # text | json
> # output = "coverage.json"    # optional; absent means stdout
> granularity = "definition"    # the only v1 value
> inherited_counts = false
> ratchet_base = ""             # required only in ratchet mode
> maximum_baseline_files = 20000
> maximum_file_bytes = 5000000
> maximum_baseline_bytes = 100000000
> maximum_history_commits = 1000
> maximum_git_command_seconds = 10.0
> maximum_git_commands = 64
> maximum_git_output_bytes = 100000000
> maximum_commit_message_bytes = 1000000
> maximum_runtime_seconds = 60.0
>
> [tool.backstitch.coverage.floors."backstitch/"]
> direct = 0.0
> accounted = 0.0
> ```
>
> Floor scope keys must equal or be nested within a final effective code root
> and use canonical repository-relative directory syntax. A scope contains
> exactly definitions whose canonical path equals the scope path or begins
> with `scope + "/"`; a zero-definition scope has null rates and any positive
> floor fails. Each floor is an independent assertion over every definition
> below that scope. All matching overlapping floors are evaluated;
> display-tree longest-root ownership does not select or suppress a floor.
> The scope path is the floor identity in reports. Unknown keys, invalid refs,
> missing objects,
> shallow-history insufficiency, budget overruns, and Git command failures are
> invocation errors with exit `2`, one-line stderr, and no partial output.
> `maximum_runtime_seconds` is one absolute deadline for the entire ratchet
> and history phase, starting after current snapshot/config acceptance and
> ending after transition evaluation and report validation. It covers Git
> subprocess time plus baseline parsing, definition projection, policy/drift
> comparison, history folding, and cleanup. CPU loops check the same monotonic
> deadline at each file/commit batch and before output publication. Every Git
> operation additionally consumes the shared command count and cumulative
> stdout/stderr byte budget. Per-command timeouts are capped by both
> `maximum_git_command_seconds` and the remaining phase budget. Batch protocols
> are required where
> history size could otherwise create one command per commit, blob, edge, or
> definition. `maximum_commit_message_bytes` applies to each decoded commit
> message before trailer parsing, and those bytes also count toward
> `maximum_git_output_bytes`. The allowed topology is constant-count ref/object
> setup (`rev-parse`, `merge-base`, `rev-list`/`log`, `ls-tree`) plus batched
> `cat-file --batch` streams; no loop may spawn a process per file, commit,
> blob, edge, or definition. A producer that crosses a byte bound is
> terminated and reaped immediately; unread buffered bytes do not excuse the
> overrun.

### Replace the unknowable origin claims in [COV-7] with

> Backstitch does not claim to know whether a human-authored section originated
> from triage advice. The anti-Goodhart signal is source-derived instead:
> ratchet reports count and byte-size every spec section added or changed in
> the diff. Semantic qualification adds paired spec-side mutations in which
> implementation stays fixed while informative contract text is replaced by
> vacuous, overbroad, or non-discriminating prose. The ordinary current-source
> semantic packet and analyzer judge those cases; no proposal provenance,
> author label, or new packet schema is introduced.

### Replace the drift rules in [COV-8] with

> A contract edge is the tuple `(spec_path, section_id, code_path,
> structural_locator)` and has a stable SHA-256 edge ID. A current-diff drift
> suspect exists when:
>
> 1. the mapped production definition source slice changed;
> 2. the governing section body bytes, excluding its implementation-mapping
>    block, did not change;
> 3. the section's normalized mapping target set did not change; and
> 4. no test-root definition connected to that section through a resolving
>    mapping, backlink, or invariant bind changed.
>
> Missing or ambiguous edges do not become drift suspects; their existing
> graph issues remain authoritative. Drift emits
> `INTENT_DRIFT_SUSPECT` (`BSN006`, packaged info).
>
> Drift hash inputs are byte-exact:
>
> - The Markdown parser adds `mapping_block_spans` as typed
>   `(section_id, start_line, end_line)` facts. A span begins at the first
>   physical source line of a recognized `_Implementation mapping_:` paragraph
>   and ends at the final physical line of the immediately following mapping
>   list sequence that the existing parser assigns to that owner. It includes
>   the marker token's complete source-line range, every owned mapping-list
>   token's complete range, all intervening physical lines, and each final
>   line's LF when present. A marker paragraph with inline mapping tokens and
>   no following list ends at that paragraph token's final source line.
> - The governing section interval reuses `ParsedSpec.section_spans`: physical
>   bytes from the start of `start_line` through the end of `end_line`,
>   including terminating LFs when present. `section_projection` removes every
>   owned mapping-block byte interval and concatenates the retained byte
>   intervals in source order without separators or normalization.
>   `section_hash` is SHA-256 of those exact bytes.
> - `mapping_hash =
>   hash(["intent-mapping-set-v1", rows])`, where `rows` is the sorted unique
>   array of `[resolved_canonical_code_path, normalized_code_symbol_or_null]`
>   for every resolving raw-graph mapping owned by the section. Path mappings
>   use null symbol; symbols use the resolver's existing normalized spelling.
>   Nonresolving declarations remain represented by their graph issues and do
>   not invent targets.
> - `connected_test_hash =
>   hash(["intent-connected-tests-v1", rows])`, where `rows` is the array of
>   `[definition_id, source_projection_sha256]` for every connected test-root
>   definition, sorted uniquely by definition ID. No connected tests hashes
>   the canonical empty array. The same mapping/backlink/invariant-bind join
>   used by the predicate selects the rows.
>
> Drift is evaluated per first-parent transition in `merge_base..HEAD`, plus
> one synthetic `HEAD..accepted-snapshot` transition when tracked, staged, or
> untracked current bytes differ. `edge_id =
> hash(["intent-edge-v1", spec_path, section_id, code_path,
> structural_locator])`. Each `event_id` hashes
> `["intent-drift-event-v1", edge_id, parent_commit,
> before_section_hash, after_section_hash, before_mapping_hash,
> after_mapping_hash, before_implementation_hash,
> after_implementation_hash, before_connected_test_hash,
> after_connected_test_hash]`. Including the transition's parent commit makes
> repeated A-to-B content changes distinct while omitting the child commit lets
> a developer compute the ID before writing that child commit and its trailer.
>
> `drift_events` contains every event produced by the inspected
> `merge_base..HEAD` first-parent transitions plus the synthetic transition,
> including acknowledged events. It does not fold or deduplicate events by
> edge. Stale-history events outside that current range appear only in
> `stale_doc_trends`.
>
> A commit acknowledges one or more drift events produced by its exact
> first-parent-to-commit transition with a Git trailer:
>
> ```text
> Backstitch-Drift-Ack: <event-id> -- <nonblank reason>
> ```
>
> The trailer is read as untrusted bounded UTF-8 data, appears in the report
> audit ledger, and suppresses only the identical event emitted for that
> commit's first-parent transition. A trailer in any other commit does not
> match. An aggregate range is acknowledged only event by event; there is no
> range-wide shortcut. The synthetic dirty-worktree transition has no commit
> and cannot be acknowledged until committed. Malformed, duplicate, or unknown
> event IDs do not suppress. Backstitch creates no acknowledgment file or
> mutable ledger.
>
> Stale-document trends are derived from first-parent Git history. Starting at
> the most recent transition where the governing section body changed,
> Backstitch applies the same edge predicate to each bounded commit transition
> and counts unacknowledged drift events. History truncation is explicit and
> never represented as a complete zero. The signal remains advisory.
>
> The semantic lane evaluates current source alignment after the change. This
> version does not claim that existing semantic packets contain diff context;
> adding a diff packet is a separate semantic-contract change.
>
> Delete [COV-8]'s existing one-row BSN006 diagnostics table. [COV-9] is the
> single authoritative BSN registry; [COV-8] refers to its BSN006 row rather
> than restating code meaning or packaged level.

### Add these exact public contracts to [COV-9]

> `backstitch coverage [PATH] [--repo-root PATH] [--format text|json]
> [--output PATH] [--profile NAME] [--config PATH|--no-config]
> [--option KEY VALUE]... [--require-ratchet REF]` uses the common config
> controls.
> Positional `PATH` and `--repo-root PATH` are exact aliases and are mutually
> exclusive; when neither is supplied, the root anchor is the current working
> directory. `--format` and `--output` override their config keys.
> Report mode accepts the listed config/profile/option controls with ordinary
> precedence. Ratchet mode rejects `--profile`, every `--option`, `--no-config`,
> and every explicit CLI `--config`. Ratchet configuration must come from
> ordinary repository discovery, after which every discovered/include layer
> must meet the repository-owned-layer rule. This prevents selecting an
> alternate lax in-repository config whose baseline and current policy happen
> to match.
> `--require-ratchet REF` is an operational assertion with no config
> equivalent: it returns exit `2` without producing a report unless the
> repository-owned effective mode is `ratchet` and its literal
> `ratchet_base` equals `REF`. It does not override or resolve a different
> base. CI must pin the expected ref with this flag once ratchet is enabled so
> a config-only mode or base change cannot silently disable or collapse the
> gate.
>
> The command returns `0` when no issue meets effective `fail_on`, `1` when
> findings meet it, and `2` for invocation, configuration, Git, budget, or
> output-publication failure.
> Output publication is atomic. The command never imports `llm`, invokes a
> provider, or writes repository source.
>
> The `BSN` registry is:
>
> | Code | Short | Packaged level |
> |---|---|---|
> | `INTENT_UNCOVERED_DEFINITION:repository` | `BSN001` | info |
> | `INTENT_UNCOVERED_DEFINITION:patch` | `BSN001` | error |
> | `INTENT_INHERITED_ONLY:repository` | `BSN002` | info |
> | `INTENT_INHERITED_ONLY:patch` | `BSN002` | error |
> | `INTENT_EXEMPTION_UNUSED` | `BSN003` | warning |
> | `INTENT_EXEMPTION_UNREASONED` | `BSN004` | error |
> | `INTENT_REQUIREMENT_UNIMPLEMENTED` | `BSN005` | info; declarations exist but no live owner resolves |
> | `INTENT_DRIFT_SUSPECT` | `BSN006` | info |
> | `INTENT_COVERAGE_FLOOR_REGRESSION` | `BSN007` | error |
> | `INTENT_COVERAGE_INCOMPLETE:repository` | `BSN008` | info |
> | `INTENT_COVERAGE_INCOMPLETE:patch` | `BSN008` | error |
> | `INTENT_COVERAGE_POLICY_REGRESSION` | `BSN009` | error; only an exact policy acknowledgment makes it non-failing |
>
> Every row, context, exit class, config key, report field, exemption form,
> changed-definition branch, drift branch, acknowledgment branch, null metric,
> and history-completeness state has a firing test.

### Coordinated active-spec registrations

The spec-promotion slice must add exact registrations, not loose cross-links:

- [SC-5]: register `coverage`, its mutually exclusive path aliases, exact
  config/profile/option controls and ratchet rejections, format/output flags,
  `--require-ratchet REF`, and `0/1/2` exit contract.
- [SC-6]: register the separate schema-1 coverage artifact and state that the
  existing check JSON remains unchanged.
- [SC-8]: include `coverage` in the deterministic no-provider boundary.
- [SC-10]: add black-box coverage probes for hostile marker mimicry, unknown
  config, missing base, untracked definitions, and byte-stable serial output.
- [SC-11]/[SC-15]: allocate `BSN001` through `BSN009`, including the
  context-sensitive codes.
- [CFG-3]/[CFG-5]/[CFG-6]/[CFG-8]/[CFG-9]: register the complete
  `[coverage]`, `[[coverage.exemptions]]`, and `[coverage.floors]` shapes,
  merge behavior, path expansion, no-op prevention, and command precedence.
- [EXC-2]/[EXC-5]/[EXC-7]: register `no-spec` as a coverage exemption, not an
  ordinary issue suppression, and require its separate audit ledger.
- [SEM-8]: add spec-side informativeness mutation families to the committed
  qualification corpus and require corpus/report hash refresh before enforce
  mode.
- [EVC-7]/[EVC-8]: allow coverage to reuse the read-only definition inventory
  and current graph without creating proposal or activation state.
- [INV-11]: add a required invariant that coverage, check, obligation, and
  semantic discovery share one Python definition identity owner and one
  accepted-snapshot path.

## Product And Architecture Decisions

### Separate command, shared core

Use `backstitch coverage`, not an implicit extension of `check`.

The strongest counterargument is product fragmentation: users may expect one
deterministic command. The reason to keep it separate is stronger for v1:
ratchet mode introduces Git and history failure classes that must not make the
advertised default `check` depend on repository history. The implementation
still shares capture, parse memos, graph construction, diagnostics, and output
publication. A later product decision may add an aggregate command without
changing the coverage engine.

### No Backstitch-owned coverage database

Current state, baselines, acknowledgment, and trends derive from the accepted
snapshot and immutable Git objects. This avoids cleanup, locking, migration,
and stale-ledger authority. The cost is bounded history work; the plan includes
budgets and a performance gate.

### Current semantic packets only

Anti-Goodhart corpus cases mutate spec text while keeping implementation fixed,
which the current section packet can express. Drift may recommend running
semantic analysis on the affected current section, but this plan does not add
diff bytes to packet schemas. Claiming otherwise would require a separate
semantic identity/cache/report migration.

## Context And Key Files

### Read first

- `backstitch/code_parser.py`: owns tree-sitter definition spans. It already
  emits class/function/async-function records but no synthesized module record
  and no canonical public locator helper.
- `backstitch/python_refs.py`: parses code backlinks, invariant declarations,
  and scoped directives while reusing `ParsedModule` through a `(path,
  raw_sha256)` memo.
- `backstitch/resolver.py`: builds the raw trace graph and `ScanArtifacts` from
  one snapshot. Coverage must consume these results, not resolve a second
  graph.
- `backstitch/check_pipeline.py`: applies diagnostic policy and ordinary
  suppression. Coverage uses the same policy but owns a separate exemption
  ledger.
- `backstitch/repository_snapshot.py` and
  `backstitch/obligation_runtime.py`: own bounded no-follow current-source
  capture. Git baselines must not bypass the current side of this boundary.
- `backstitch/settings.py` and `backstitch/defaults.toml`: own closed config,
  layering, path anchoring, and diagnostic registry.
- `backstitch/cli.py`: owns public command parsing, one settings resolution,
  lazy imports, exit classes, and atomic output errors.
- `backstitch/models.py` and `backstitch/reporting.py`: own the existing check
  report. Do not add coverage fields to that schema.
- `backstitch/artifact_contracts.py`: owns closed deterministic artifact
  loading. Register the separate coverage artifact here without weakening
  existing check-report validation.
- `backstitch/evidence_discovery.py`: independently constructs structural
  definition locators today. Extract the locator helper; do not create a third
  identity implementation.
- `backstitch/semantic_eval.py`, `backstitch/semantic_eval_reports.py`, and
  `tests/semantic_eval/v3/`: own the closed qualification corpus/report path.

### Expected files to add

- `backstitch/intent_coverage.py`: pure typed definition inventory,
  classification, reverse complement, metrics, triage ranking, drift
  predicate, and report builder over supplied facts.
- `backstitch/git_baseline.py`: the sole Git subprocess owner for baseline
  resolution, bounded blob reads, commit messages, current tree identity, and
  first-parent history facts.
- `backstitch/intent_coverage_reporting.py`: closed schema-1 validation,
  canonical hash, text rendering, and atomic-publication payload.
- `tests/test_intent_coverage.py`
- `tests/test_git_baseline.py`
- `tests/test_intent_coverage_reporting.py`
- `tests/acceptance/test_probe_intent_coverage.py`

### Expected files to modify

- `backstitch/code_parser.py`
- `backstitch/python_refs.py`
- `backstitch/evidence_discovery.py`
- `backstitch/resolver.py`
- `backstitch/check_pipeline.py`
- `backstitch/models.py`
- `backstitch/settings.py`
- `backstitch/defaults.toml`
- `backstitch/cli.py`
- `backstitch/diagnostics.py`
- `backstitch/artifact_contracts.py`
- `backstitch/semantic_eval.py`
- `backstitch/semantic_eval_reports.py`
- `tests/test_code_parser.py`
- `tests/test_python_refs.py`
- `tests/test_settings.py`
- `tests/test_cli.py`
- `tests/test_cli_config.py`
- `tests/test_issue_code_coverage.py`
- `tests/test_canonical_owners.py`
- `tests/test_release_workflow.py`
- `tests/semantic_eval/v3/manifest.json` and new paired fixtures
- `.github/workflows/semantic-pr-report.yml`
- `README.md`
- `docs/specs/00-specs-index.md`
- `docs/specs/02-backstitch-core.md`
- `docs/specs/03-backstitch-configuration.md`
- `docs/specs/04-backstitch-traceability-exclusions.md`
- `docs/specs/05-backstitch-invariants.md`
- `docs/specs/06-semantic-gates.md`
- `docs/specs/07-verification-and-evidence-cases.md`
- `docs/specs/08-intent-coverage.md`
- `docs/implementation/02-repository-map.md`
- `docs/implementation/04-backstitch-style-traceability.md`
- `pyproject.toml`

### Comprehension checks before editing

1. Why must coverage get `ParsedModule` and raw graph facts from the same
   accepted snapshot instead of calling the parser or filesystem again?
2. Which current module owns structural definition locators, and how will
   evidence discovery and coverage prove they use the same owner?
3. Why is a Git baseline blob not allowed to replace current-side no-follow
   snapshot capture?
4. Which fields determine an ordinary diagnostic's final severity and exit
   effect after context-sensitive policy?
5. Why does changing the semantic corpus require an authoritative report-hash
   refresh even though no prompt changed?

## Invariants And Constraints

1. **One current-source image.** Coverage, graph resolution, exemptions, and
   current-side diff facts consume one accepted `RepositorySnapshot`.
2. **One definition identity.** Module and definition locators have one
   production owner used by coverage and evidence discovery.
3. **No check-schema drift.** Existing `check` text and JSON remain unchanged.
4. **No provider boundary regression.** `coverage` never imports `llm`, builds
   an adapter, or performs network traffic.
5. **No source writes.** Triage guidance, exemptions, and drift audit are
   reports only.
6. **No hidden Git behavior.** Git runs without a shell, pager, prompt, textconv,
   external diff, hooks, or fetch. Arguments are arrays; environment and
   timeout are closed. One absolute runtime deadline covers subprocess and CPU
   work across the entire ratchet/history phase; command count and cumulative
   output budgets cover Git. Replacement objects and inherited Git
   repository/object-selection variables are disabled.
7. **No partial truth.** Fatal capture, Git, config, schema, budget, or output
   failure returns exit `2` and publishes no report. Advisory history
   truncation is explicit in a successfully emitted report.
8. **Policy remains authority within its boundary.** Ratchet emits patch
   contexts with strict packaged defaults; applied diagnostic policy
   determines ordinary finding severity and exit. BSN009 separately audits
   attempts to weaken that authority and is failing unless its exact policy
   transition is acknowledged.
9. **Coordinates are not identity.** Line movement cannot silently create a new
   logical definition if locator and source slice remain stable.
10. **Exemptions cannot hide direct coverage.** Direct wins; every overlap stays
    visible.
11. **No rounded comparisons.** Ratios display decimals but floors compare
    integer fractions.
12. **No historical guessing.** Shallow or missing history fails ratchet
    baseline work; a capped stale trend says incomplete instead of zero.
13. **No mock-created confidence.** Tests keep the parser, snapshot, graph,
    config resolver, report validator, filesystem, and local Git repository
    real.
14. **Backward-compatible rollout.** Packaged mode is `report`; existing users
    see no new behavior unless they invoke `coverage`.
15. **No new runtime dependency.** Use the installed Git executable and standard
    library. Stop if implementation requires GitPython, a database, or another
    parser.

## Hidden Couplings

- The parser memo is currently optional in `check`; `coverage` must create and
  thread it so definition inventory does not parse files a second time.
- Evidence discovery already manufactures module locators and ordinals. A
  coverage-local copy would make identities diverge.
- Suppression operates after policy over `Issue` values. Coverage exemptions
  classify definitions before issue construction and must not be smuggled into
  ordinary suppression rules.
- `Report` is the stable [SC-6] check artifact. Reusing it by adding optional
  fields would still change consumers and snapshots.
- Config discovery may include home or explicit layers. Ratchet policy
  authority needs per-key provenance, rejects external gate inputs, and
  compares canonical repository-owned policy at the merge base and current
  snapshot.
- Git history can be large, shallow, replaced during a run, or configured with
  hostile external helpers. The Git owner must bind all object IDs before
  analysis and use closed subprocess settings.
- The semantic qualification report is content-bound to its corpus. Adding
  spec mutations invalidates the current dogfood hash even if all runtime code
  is correct.

## Fatal Versus Advisory Failures

Fatal, exit `2`, no output:

- invalid coverage config or exemption
- snapshot capture failure
- report schema/hash inconsistency
- output publication failure
- ratchet base missing, invalid, shallow, or no merge base
- baseline blob/file/byte budget exceeded
- Git timeout, non-UTF-8 protocol data, or object replacement/inconsistency
- current or baseline repository policy not representable for canonical
  monotonicity comparison
- untrusted gate-affecting config provenance or a required ratchet assertion
  running in report mode

Reported through ordinary policy, exit `0` or `1`:

- uncovered/inherited definitions
- unimplemented requirements
- unused/unreasoned inline exemptions
- drift suspects
- floor regressions
- incomplete repository-state or changed-file coverage

Advisory structured state, never silently complete:

- stale-document history stopped at `maximum_history_commits`
- exemption overlap with direct coverage
- malformed or unknown drift acknowledgment trailer
- acknowledged policy regressions; unacknowledged BSN009 is a fixed failing
  ratchet finding rather than an ordinary severity override

## Security And Trust Boundary

- Treat repository paths, refs, blob bytes, and commit messages as untrusted.
- Pass refs to Git only as separate arguments after `--` where the subcommand
  permits it. Reject leading-hyphen refs before invocation.
- Resolve one absolute Git executable before the run. Invoke it with
  `--no-replace-objects`, never through `PATH` after resolution. Construct the
  child environment from an allowlist, not a copy of `os.environ`:
  `LC_ALL=C`, `GIT_TERMINAL_PROMPT=0`, `GIT_PAGER=cat`, `PAGER=cat`,
  `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=<platform null device>`, and on
  Windows only the minimum `SystemRoot`/`WINDIR` values required to start the
  executable. Do not pass any ambient `GIT_*` repository, worktree, object
  directory, alternates, namespace, index, ceiling, replace-ref, or config
  count/value variable.
- Pass closed `-c` values that disable hooks, textconv, external diff,
  credential prompting, pagers, and optional locks where relevant. Use
  explicit `--git-dir` and `--work-tree` paths derived from the accepted root;
  do not accept repository-local aliases as subcommands.
- Capture stdout/stderr with byte and time limits. Never interpolate into a
  shell command. Charge every invocation and byte to the run-wide budget, not
  only a per-command timeout.
- Use `git cat-file --batch` for bounded blob content; validate declared sizes
  before accepting bytes.
- Never follow worktree symlinks for the baseline. Baseline content comes from
  Git objects; current content stays under snapshot no-follow rules.
- Never execute target-project code.

## Rollout, Rollback, And One-Way Doors

There is no durable database or artifact migration. The schema-1 report is new,
so rollback is file-level:

1. Ship the command in packaged `report` mode with no repository floor.
2. Run dogfood coverage and classify the existing backlog. Do not manufacture
   specs to reach a percentage.
3. Add narrowly reasoned exemptions and initial floors only after review.
4. After report-mode acceptance passes, enable repository `ratchet` mode with
   `ratchet_base = "origin/main"` in a separate, reviewable config slice and
   pin the repository CI invocation with `--require-ratchet origin/main`.
   The workflow checkout must materialize `origin/main` with sufficient
   history before invocation; Backstitch itself still never fetches.
5. Refresh the semantic qualification report only after the expanded corpus is
   independently reviewed and live-provider spend is explicitly authorized.

Rollback can remove the command/config/registry entries and restore the
planned-spec glob plus `SUP-COV-PLANNED`, provided no shipped code still cites
active COV sections. Report artifacts are disposable outputs.

The one-way risk is social, not storage: a ratchet can incentivize vacuous specs
and permanent exemptions. The staged dogfood audit and spec-side semantic cases
must pass before strict repository floors are enabled.

Post-release success signals:

- `backstitch coverage --format json` is byte-stable on an unchanged repo.
- report mode adds no `check` latency or output change.
- ratchet CI blocks a newly uncovered definition and permits existing backlog.
- unused exemptions and acknowledged or rejected floor-policy changes are
  visible.
- no Git subprocess remains after command completion or timeout.
- semantic qualification remains authoritative for the expanded corpus.

## Dependency-Ordered Implementation Tasks

### Spec-promotion slice: close and activate the contract

- Files: all coordinated spec files named above, `pyproject.toml`, and this
  plan.
- Apply the exact proposed delta, active registrations, COV backlink, and
  temporary `SUP-COV-INFLIGHT`.
- Record the promotion baseline identifier in `## Spec Baseline`.
- Add no production citation yet.
- Tests: spec/config registry tests for the newly enumerable contract may be
  added red but no production mapping is claimed.
- Stop if independent review rejects the separate-command choice, Git-derived
  trend authority, or semantic boundary.
- Done signal: spec text is active; `backstitch check --repo-root .` has zero
  errors and warnings; any remaining unmapped COV debt is exactly the temporary
  declared suppression.

### Slice 1: canonical definition inventory and marker grammar

- Files: `code_parser.py`, `python_refs.py`, `evidence_discovery.py`,
  `tests/test_code_parser.py`, `tests/test_python_refs.py`,
  `tests/test_canonical_owners.py`.
- Add the synthesized module record and one public structural-locator helper.
- Extract evidence discovery's current locator formatting to that helper.
- Parse exact `no-spec` marker candidates and reasons as typed facts; do not
  classify them yet.
- Use red-green tests for duplicate names/ordinals, nested methods, decorators,
  async definitions, multiline signatures, module markers, docstring markers,
  invalid UTF-8, syntax errors, string mimicry, and near misses.
- Stop if the change requires `include_static_facts=True` for coverage or
  changes existing candidate IDs.
- Done signal: existing evidence candidate IDs are byte-identical; one
  enumerating test proves there is one locator owner.

### Slice 2: coverage settings and diagnostic registry

- Files: `settings.py`, `defaults.toml`, `diagnostics.py`, `models.py`,
  `tests/test_settings.py`, `tests/test_semantic_settings.py`,
  `tests/test_issue_code_coverage.py`.
- Add frozen `CoverageSettings`, `CoverageExemption`, and `CoverageFloor`
  values with the exact closed keys.
- Register `coverage` as a config-consuming command and serialize it in
  `config show`.
- Implement layer merge and repository anchoring for paths/globs/output.
- Retain per-key provenance for every ratchet gate input; reject an external
  contribution before Git work starts.
- Register `BSN001` through `BSN009` and exact contexts/defaults.
- Add no-op-prevention tests for every key and all invalid type/value/unknown
  branches.
- Stop if floors depend on ambient user config or if dynamic floor tables can
  bypass unknown-key validation.
- Done signal: `config show` is canonical; every registry row/context fires in
  a focused test.

### Slice 3: pure repository-state classification and reverse complement

- Files: new `intent_coverage.py`, plus `resolver.py`, `check_pipeline.py`,
  `tests/test_intent_coverage.py`.
- Thread the real Python parse memo through one snapshot scan.
- Build typed definition/edge/exemption indexes and apply exact precedence.
- Build own-source projections so nested edits do not change enclosing
  definition hashes.
- Compute longest-root tree ownership, integer metrics, null denominators,
  unimplemented active requirements, and deterministic triage order:
  uncovered definitions only, production before test, then canonical path and
  locator.
- Build issues through the existing diagnostic registry/policy seam.
- Do not read Git or render output in this slice.
- Tests keep the real parser, snapshot, and resolver. Fixtures cover every edge
  source independently and in conflict.
- Stop if classification needs raw live filesystem reads or a parallel graph.
- Done signal: repeated classification over the same supplied facts is
  byte-equivalent and all COV-3/COV-4 branches fire.

### Slice 4: closed report and public report-mode command

- Files: new `intent_coverage_reporting.py`, `cli.py`, `settings.py`,
  `README.md`, `tests/test_intent_coverage_reporting.py`, `tests/test_cli.py`,
  `tests/test_cli_config.py`.
- Add schema-1 typed build, consistency validation, hash recomputation, JSON
  and text rendering.
- Add `backstitch coverage [PATH]` with common config options and dedicated
  `--format`/`--output`.
- Resolve settings once; capture once; parse once; publish output atomically.
- Keep coverage imports deterministic and outside provider modules.
- Add mutation tests for every report field, count, hash, ordering, and closed
  nested shape.
- Stop if implementing this changes `Report.to_dict()` or existing check
  snapshots.
- Done signal: report mode works without `.git`; check output fixtures are
  unchanged.

### Slice 5: bounded Git baseline owner and changed-definition ratchet

- Files: new `git_baseline.py`, `intent_coverage.py`, `cli.py`,
  `tests/test_git_baseline.py`, `tests/test_intent_coverage.py`,
  `tests/test_cli.py`.
- Build real temporary Git repositories for tests. Do not mock subprocess.
- Resolve ref and merge base; enumerate/read baseline blobs; bind object IDs;
  compare current snapshot definitions; include untracked current files.
  Compare own-source projections, not full enclosing spans. Resolve one
  absolute Git executable and enforce the closed child environment,
  `--no-replace-objects`, process topology, global deadline, and aggregate
  byte/message budgets.
- Parse baseline repository config blobs, compute baseline/current policy
  identities, classify every gate-input transition, emit patch contexts,
  `BSN007`, and `BSN009`, and implement `--require-ratchet`.
- Prove no fetch, shell, pager, external diff, hook, or target code execution.
- Cover detached HEAD, unborn repo, shallow history, missing objects,
  submodules, symlinks, non-UTF-8 blobs/messages, renamed/deleted files,
  replacement refs, hostile global/repository config and `GIT_*` environment,
  many commits, output floods, timeouts, and each budget. Add one bypass test
  for every gate-affecting config key and for external/CLI overlays.
- Stop if subprocess calls become per definition, a new dependency appears, or
  aggregate work is worse than `O(files + definitions + blobs)`.
- Done signal: ratchet blocks only new/changed uncovered debt; repeated serial
  and concurrent invocations emit identical bytes.

### Slice 6: drift predicate and exact current acknowledgments

- Files: `markdown_specs.py`, `intent_coverage.py`, `git_baseline.py`,
  `intent_coverage_reporting.py`, `tests/test_markdown_specs.py`, and related
  coverage/Git tests.
- Add the parser-owned `mapping_block_spans` fact without changing existing
  mapping ownership or token interpretation.
- Compute section body, normalized mapping set, production source slice, and
  connected test-definition hashes at merge base and current state using the
  exact byte/canonical-JSON preimages.
- Emit stable edge IDs and current drift events.
- Parse bounded `Backstitch-Drift-Ack` and
  `Backstitch-Coverage-Policy-Ack` trailers and join only exact event IDs
  produced by the same first-parent transition.
- Mutation tests independently change each of the four predicate inputs,
  malformed/unknown/duplicate trailers, multi-commit ranges, and reasons.
- Stop if test association requires call-graph guessing. Only declared
  mapping/backlink/bind edges count.
- Done signal: the drift truth table is exhaustive and acknowledgments never
  suppress another edge.

### Slice 7: bounded stale-document history

- Files: `git_baseline.py`, `intent_coverage.py`,
  `intent_coverage_reporting.py`, `tests/test_git_baseline.py`,
  `tests/performance/semantic_scale.py` or a new coverage-scale module.
- Build a first-parent transition index once, cache blobs by object ID, and
  apply the exact drift predicate only to edges whose paths changed.
- Reset at the latest section-body transition; exclude exact acknowledged
  events; expose complete/truncated history.
- Add a scale fixture with at least 10,000 definitions, 1,000 mappings, and 200
  synthetic commit transitions. Pin work counts first; wall clock remains a
  qualified secondary signal.
- Stop if the implementation approaches `edges × commits` reparsing, needs
  persistence, or exceeds declared budgets in the closed fixture.
- Done signal: trend counts recompute from Git only and truncated history never
  claims a complete zero.

### Slice 8: anti-Goodhart semantic corpus

- Files: `tests/semantic_eval/v3/manifest.json`, new paired fixtures,
  generator/review protocol as needed, `semantic_eval.py`,
  `semantic_eval_reports.py`, workflow tests, applied configuration hashes.
- Add paired spec-side mutations: vacuous restatement, overbroad guarantee,
  tautology, implementation narration, and non-discriminating prose. Keep
  implementation constant in each pair.
- Generate and independently review the candidate corpus before replacing the
  committed authority.
- Run controlled-provider primary/replay tests first.
- Before any live provider call, report exact maximum calls/cost and obtain
  owner authorization. Do not weaken enforce hashes or thresholds to avoid the
  refresh.
- Stop if the current prompt cannot distinguish the cases. That triggers a
  separate prompt/spec revision and qualification plan, not silent fixture
  relabeling.
- Done signal: committed corpus and authoritative report hashes match; every
  critical case passes under the applied qualification policy.

### Slice 9: dogfood report, exemptions, and floor rollout

- Files: `pyproject.toml`, `README.md`, coverage docs and tests.
- Run report mode on Backstitch. Review every uncovered definition; classify it
  as needs-spec, glue, dead, or contradicts-spec.
- Backstitch's repository wildcard currently promotes every diagnostic to
  error. Add explicit repository-context BSN001/BSN002/BSN005/BSN006/BSN008
  advisory rules after that wildcard for the report-only audit; keep patch
  contexts and BSN003/BSN004/BSN007/BSN009 strict. Document the exception
  instead of leaving the current "every diagnostic is a violation" comment
  false.
- Land only defensible existing-spec mappings or reasoned exemptions. Do not
  write vacuous COV text to improve the number.
- Record initial direct/accounted floors from the reviewed result.
- After the report-mode acceptance and self-corpus probes pass, enable ratchet
  in a separate config edit with `ratchet_base = "origin/main"` and update CI
  to pass `--require-ratchet origin/main`.
- Stop if more than 10% of production definitions would be exempted, inherited
  coverage dominates direct coverage, or reviewers cannot explain the metric.
- Done signal: repository ratchet catches a synthetic uncovered diff and the
  unchanged repository passes.

### Final slice: traceability and integration reconciliation

- Complete COV implementation mappings and reciprocal production backlinks.
- Remove `SUP-COV-INFLIGHT`, its config rule, and declaration.
- Update implementation docs, repository map, README, plans index, lessons if
  needed, and all active coordinated-spec mappings.
- Run every final gate below and an independent completed-work review.
- Done signal: no COV section relies on a planned/inflight suppression; default
  invocation exits `0` with zero errors and warnings; every enumerable contract
  has a firing test.

## Testing Plan

### Test diagram

| Flow or branch | Real proof |
|---|---|
| definition inventory and identity | parser unit tests plus canonical-owner enumeration |
| reference/mapping/invariant classification | real snapshot + parser + resolver integration fixtures |
| inline/config exemptions | grammar mimicry and config-layer tests |
| report schema/hash/order | build, reload, mutation, and byte-repeat tests |
| report-mode CLI | public `main()` and subprocess acceptance tests without `.git` |
| Git ratchet | real temporary repositories and real Git executable |
| dirty/index/untracked/deleted/renamed | real repository state transitions |
| floors and lowering prevention | baseline/current repository config commits |
| drift truth table | real section/mapping/code/test mutations across commits |
| acknowledgment | real commit trailers; malformed and foreign IDs |
| stale trends | bounded first-parent synthetic histories |
| semantic informativeness | controlled provider plus reviewed qualification corpus |
| output failure and exit classes | public CLI against unwritable/missing paths |
| deterministic/provider boundary | import enumeration and network/provider tripwire |
| self-dogfood | public command with committed repo config |

### Anti-mocking rules

Do not mock:

- tree-sitter parsing
- repository snapshot capture
- resolver/trace graph
- config discovery and layering
- report serialization/validation
- local filesystem
- Git subprocess in integration tests
- committed semantic corpus/report validation

Mock only:

- the external semantic provider in ordinary tests
- monotonic time at the narrow timeout seam when a real bounded timeout test
  would be flaky

At least one subprocess test must prove each public CLI flow. At least one real
Git timeout test must use a controlled executable shim that never evaluates
repository content.

### Required firing matrices

- all nine `BSN` short codes and all BSN001/BSN002/BSN008 contexts
- all coverage config keys and each invalid type/value
- every ratchet policy transition class, provenance rejection, policy
  acknowledgment state, and `--require-ratchet` branch
- all definition kinds and each classification precedence collision
- all zero/nonzero metric denominators
- every changed-definition branch
- every drift predicate input
- valid, malformed, duplicate, unknown, and absent acknowledgment
- complete and truncated history
- all `0/1/2` exit classes
- text, JSON, stdout, output file, and unwritable output
- report mutation of every top-level and nested field

## Per-Slice Verification

Run the narrow changed tests first, then:

```text
uv run ruff check <changed Python files and tests>
uv run ruff format --check <changed Python files and tests>
uv run mypy backstitch
git diff --check
```

After each meaningful slice, request an independent review against the promoted
spec and this plan. Do not wait until the end to discover a split identity,
second scan path, or weak Git boundary.

## Final Verification And Gates

Before Slice 9 changes the repository config to ratchet mode, run the
report-mode acceptance gate:

```text
uv run pytest tests/acceptance -q
uv run backstitch check --repo-root . --show-suppressions
uv run backstitch coverage --repo-root . --format json
```

Only after those commands pass, commit the reviewed repository setting
`mode = "ratchet"` and `ratchet_base = "origin/main"` plus the CI assertion.
Then run the final landing gate:

```text
uv run pytest -q
uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm and not benchmark"
uv run pytest tests/acceptance -q
uv run ruff check .
uv run ruff format --check .
uv run mypy backstitch
uv run backstitch check --repo-root . --show-suppressions
uv run backstitch coverage --repo-root . --format json --require-ratchet origin/main
git diff --check
```

Required observations:

- existing `check` golden output and summary contract remain unchanged
- default invocation exits `0` with zero errors and warnings
- every governed suppression has a valid declaration and nonblank rationale
- no COV planned/inflight suppression remains
- coverage report hash recomputes and a repeated run is byte-identical
- report mode works outside Git
- ratchet mode fails a fresh uncovered definition and ignores baseline backlog
- provider/network tripwires remain untouched
- acceptance adds black-box hostile marker, config, Git, output, and self-run
  probes
- semantic qualification corpus/report hashes are authoritative
- independent completed-work review has no unresolved P1/P2 finding

Live semantic qualification is not authorized by this plan alone. The
implementation turn must present the bounded call/cost estimate and obtain
explicit owner authorization before spend. Until the authoritative artifact is
refreshed, Slice 8 and the overall feature remain incomplete.

## Independent Review Loop

Plan review:

> Read this plan, its Proposed Spec Delta, `docs/specs/08-intent-coverage.md`,
> the coordinated active specs, and the current parser/resolver/settings/CLI
> code. Look for incorrect product choices, missing enumerable contracts,
> identity drift, unsafe Git behavior, unbounded history work, semantic
> overreach, weak anti-Goodhart measures, and performative overengineering.
> Do not implement. Could a zero-context engineer implement the entire active
> spec confidently and correctly if this delta were promoted?

The author must record every finding and disposition below. Any finding that
leaves command shape, definition identity, metric math, Git authority, report
schema, or semantic qualification ambiguous blocks implementation.

Implementation review:

- Review after Slices 1, 4, 5, 7, and 9.
- Use a different agent family where available.
- Final review reads the complete diff, reruns focused adversarial tests, and
  checks that every plan deviation has a closed spec proposal.

## Out Of Scope

- automatic source/spec edits
- durable proposal, triage, or coverage databases
- non-Python definition parsers
- call-graph inference or guessed test ownership
- using coverage as a default command
- changing existing check JSON/text
- MCP exposure
- fetching remotes or choosing a base from ambient CI variables
- semantic diff-packet schema changes
- line or branch test coverage
- percentage targets imposed without a reviewed repository baseline

## Stop-And-Re-Evaluate Gates

Stop and revise the plan/spec if:

- any slice needs a second current-source scan or definition identity
- the Git owner cannot stay bounded and shell-free
- ratchet truth depends on ambient CI or home configuration
- stale trends require persistent mutable state
- the semantic analyzer needs prompt or packet changes
- report-mode work changes `check` output or default latency
- dogfood incentives produce vacuous mappings or more than 10% exemptions
- a new dependency, new artifact schema version, or new public command appears
  outside this plan

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|

## Review Findings And Dispositions

| Date | Reviewer | Finding | Severity | Disposition |
|---|---|---|---|---|
| 2026-07-28 | independent adversarial plan review | Nested report records, identities, ordering, validation, and hash preimage were not closed. | P1 | Revised with exact top-level/nested schemas, ID preimages, sort/uniqueness rules, recomputation, and canonical hash encoding. |
| 2026-07-28 | independent adversarial plan review | Module identity omitted invalid, ambiguous, duplicate-root, and package-root cases. | P1 | Added the path fallback, longest-root rule, `__init__.py` behavior, and byte-compatibility boundary for existing IDs. |
| 2026-07-28 | independent adversarial plan review | Physical ordinals could not join current logical graph edges. | P1 | Defined mapping fan-out and coordinate/span joins for references, declarations, and binds without changing resolver schemas. |
| 2026-07-28 | independent adversarial plan review | Own-source projection was not byte precise. | P1 | Defined decorator attachment, byte intervals, LF ownership, child subtraction, concatenation, empty input, and hash comparison. |
| 2026-07-28 | independent adversarial plan review | Gate authority could be bypassed through config, base, provenance, or policy edits. | P1 | Added repository-owned per-key provenance, transition classification, BSN009, exact policy acknowledgments, and CI-pinned `--require-ratchet REF`. |
| 2026-07-28 | independent adversarial plan review | Git had per-command limits but no fully closed run/environment/process boundary. | P1 | Added run-wide command/time/output/message budgets, batched topology, absolute executable, environment allowlist, no-replace mode, and hostile-config tests. |
| 2026-07-28 | independent adversarial plan review | Drift acknowledgments did not identify one deterministic transition event. | P1 | Defined per-first-parent plus synthetic transitions, content event IDs, exact trailer placement, and no dirty or range-wide acknowledgment. |
| 2026-07-28 | independent adversarial plan review | Nested floor denominators and overlap were ambiguous. | P2 | Defined canonical subtree membership, independent overlapping assertions, null/positive-floor behavior, and report identity. |
| 2026-07-28 | independent adversarial plan review | Config output and CLI root contracts contradicted task text. | P2 | Made output an exact config key with CLI precedence; defined positional/flag root aliases, mutual exclusion, and cwd default. |
| 2026-07-28 | independent adversarial plan review | Exemption recognition, invalid reasons, and overlap-only state were not closed. | P2 | Added syntax-tree recognition grammar, truth table, normalization/bounds, config exit behavior, and `used`/`overlap_only`/`unused` states. |
| 2026-07-28 | independent adversarial rereview | Event rows could not represent repeated transition-scoped drift/policy events or truncated pre-change history. | P1 | Added event and parent/child transition identities, event ordering and range inclusion, and nullable section-change commit under truncation. |
| 2026-07-28 | independent adversarial rereview | Policy identity, changed-key grammar, selector comparison, and diagnostic/suppression authority were not executable. | P1 | Added the closed canonical policy mapping, JSON-pointer/member keys, finite set rules, full diagnostics/suppression objects, and conservative acknowledgment requirement. |
| 2026-07-28 | independent adversarial rereview | An acknowledged packaged-error BSN009 conflicted with the general issue exit rule. | P1 | Acknowledged policy events remain ledger-only and emit no BSN009 Issue; only unacknowledged current events enter issues. |
| 2026-07-28 | independent adversarial rereview | Invocation-level profile selection could change the ratchet gate. | P1 | Ratchet rejects `--profile` and `--option`; report mode retains them, and the exact CLI grammar now says so. |
| 2026-07-28 | independent adversarial rereview | Delimited requirement IDs were ambiguous for paths containing `#`. | P2 | Requirement identity now hashes a canonical structured tuple. |
| 2026-07-28 | independent adversarial rereview | Tree/floor collection JSON types were inconsistent. | P2 | Both are exact arrays with canonical row identities and sort keys. |
| 2026-07-28 | independent adversarial rereview | The runtime budget did not clearly cover CPU work between Git calls. | P2 | The absolute deadline now covers the full ratchet/history CPU, subprocess, validation, and cleanup phase. |
| 2026-07-28 | independent adversarial final rereview | Explicit `--config` could select a second lax in-repository policy. | P1 | Ratchet rejects all explicit config selection and uses only ordinary repository discovery plus layer provenance checks. |
| 2026-07-28 | independent adversarial final rereview | The transition table did not state report-to-ratchet behavior. | P2 | Report-to-ratchet is explicitly strengthening; ratchet-to-report is caught by the CI assertion without violating report mode's no-Git boundary. |
| 2026-07-28 | independent adversarial final rereview | Full revised plan. | PASS | No implementation blocker remains; reviewed plan hash `c76da84eae4fe0473878619f976c9eabd8117205eb020c0b5315a2bc05ba8976` before status-only closeout edits. |
| 2026-07-28 | Claude outside-model review (`claude -p`) | Drift event IDs depended on three hashes without byte/canonical preimages. | P1 | Added parser-owned mapping-block spans plus exact section projection, normalized mapping-set, and connected-test-set hash algorithms. |
| 2026-07-28 | Claude outside-model review (`claude -p`) | The final ratchet command contradicted report-first rollout and used an unresolved placeholder. | P2 | Split report-mode acceptance from the final ratchet landing gate; pinned this repository to `origin/main`. |
| 2026-07-28 | Claude outside-model review (`claude -p`) | Existing [COV-4]/[COV-8] diagnostic tables would conflict with the new [COV-9] registry. | P2 | Promotion now explicitly deletes both duplicate tables and makes [COV-9] the sole registry authority. |
| 2026-07-28 | Claude outside-model review (`claude -p`) | Triage ordering and BSS007 projection were derivable but not explicit in the closed report. | P3 | Added the exact uncovered-definition worklist and stated that shared applied scan issues, including BSS007, appear exactly once. |
| 2026-07-28 | Claude outside-model rereview (`claude -p --resume`) | Full revised plan and prior outside-model findings. | PASS | All drift preimages, two-phase gates, single registry authority, worklist, and issue projection checked; no P1/P2 implementation blocker remains. |
| 2026-07-28 | Claude outside-model implementation review (`claude -p`, tool-less bounded packet) | Multi-event report ordering could fail closed because sources were not canonicalized by event ID; multi-file transition framing had no firing test. | P2 | Canonicalized policy and drift events at report build/validation boundaries and added two-event plus add/modify/delete transition tests. |
| 2026-07-28 | Claude outside-model implementation review (`claude -p`, tool-less bounded packet) | Inherited-count accounting and equal-span ambiguous-owner branches lacked direct tests; the history projector's policy boundary was implicit. | P3 | Added both branch tests and documented that history reconstruction intentionally excludes current-policy rungs, exemptions, and inherited accounting from COV-8 preimages. |
| 2026-07-28 | Claude outside-model implementation review (`claude -p`, tool-less bounded packet) | Reviewed core implementation packet after prior independent CLI, schema, corpus, and history slice reviews. | PASS WITH FINDINGS | All P2 findings were fixed and focused tests pass; no unresolved implementation P1/P2 remains. Qualification and rollout stop gates are product-policy blockers, not code-review defects. |

## Fresh-Eyes Checklist

- [x] Every public field, key, code, context, exit, and marker is enumerable.
- [x] Every task names files, real seams, tests, stop gates, and done signals.
- [x] The spec-promotion and suppression-removal order cannot create hidden
  warning debt.
- [x] Current snapshot, Git baseline, and semantic source authority are not
  conflated.
- [x] Definition identity and metric formulas are implementable without
  inference.
- [x] Rollback works without a data migration.
- [x] No task weakens the user's requested complete Intent Coverage outcome.

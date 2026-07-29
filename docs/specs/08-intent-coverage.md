# Intent Coverage Spec

Status: Active

Related specs:

- `docs/specs/02-backstitch-core.md` [SC-3], [SC-4], [SC-11]
- `docs/specs/03-backstitch-configuration.md` [CFG-3], [CFG-5], [CFG-6],
  [CFG-8], [CFG-9]
- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-*]
- `docs/specs/05-backstitch-invariants.md` [INV-11]
- `docs/specs/06-semantic-gates.md` [SEM-*]
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-7], [EVC-8]

## 1. Purpose And Scope [COV-1]

Every existing Backstitch check is conditional: references that exist must
resolve; invariants that are declared must bind. Intent coverage adds the
universal claim: **every code definition is accounted for by stated intent,
or is deliberately and auditably exempted** — and, in the reverse
direction, every stated requirement is accounted for by implementation.

`coverage.py` asks whether every line is exercised by a test. Intent
coverage asks whether every behavior is reachable from a spec. The
complements are the product:

- **code-without-spec**: definitions with no intent edge — undocumented
  behavior, dead code, or scope creep that entered the repository without
  stated intent;
- **spec-without-code**: requirement sections with no live implementation
  mapping — stated guarantees nothing owns.

Both complements are ranked worklists for the triage loop ([COV-6]), not
merely numbers. The target is never 100% coverage; it is zero
*unaccounted-for* definitions, where "accounted for" includes an explicit
exemption with a reason.

This spec owns coverage computation, exemptions, the ratchet gate, drift
coverage, and the triage loop. It does not own per-annotation resolution
diagnostics (those are [SC-4]/[SC-11], e.g. `SPEC_SECTION_UNMAPPED`),
scan-boundary exclusion ([CFG-6]/[EXC-*]), or semantic judgment mechanics
([SEM-*]). Together with [INV-*] and the semantic lane, these axes form the
contract-coverage matrix stated in [SC-16].

## 2. Mental Model [COV-2]

The four-tool suite, one sentence each: `ruff` — every line well-formed;
`mypy` — every value well-typed; `coverage` — every line exercised by a
test; `backstitch` — every behavior traceable to intent and every intent
traceable to behavior. Intent coverage is the quantifier that makes the
fourth sentence complete.

Like test coverage, intent coverage is a *reach* metric, not a quality
metric: a covered definition has an intent edge; whether the spec text is
informative is a separate, sampled semantic question ([COV-7]). The
deterministic layer never claims more than reach.

## 3. Coverage Computation [COV-3]

Coverage runs through the public `backstitch coverage` command. It consumes
the same accepted immutable repository snapshot and raw trace graph as
`backstitch check`; it never opens a second live-source path. `check`
remains byte-compatible and does not compute coverage implicitly.

The measured unit is a canonical Python definition. The inventory includes
one synthesized module definition per parsed Python file plus every
tree-sitter class, function, and async-function definition. A method is a
function or async function whose nearest enclosing definition is a class.
The identity is the tuple `(path, structural_locator)`, where locators are
`python-module:<module-name>` when the current module-name resolver yields
one unambiguous name, `python-module-path:<canonical-path>` otherwise, and
`python-definition:<qualname>:<kind>:<ordinal>`. Ordinal is zero-based among
same-file definitions with the same normalized qualified name and kind in
source order. The fallback adds module candidates only where none exist
today; valid existing evidence-discovery module locators and candidate IDs
remain byte-identical. Invalid Python path components, duplicate module names
across roots, and equal-specificity overlapping roots therefore use the
path fallback. A unique longest matching root owns module derivation;
`__init__.py` resolves to its containing package name and a root-level
`__init__.py` falls back to its canonical path. Line numbers are coordinates,
never identity.

Each definition also has an own-source projection. It contains the
physical bytes from the start of the attachment line through the end of the
definition's final physical line, including its terminating LF when present.
The attachment line is the first decorator line belonging to that definition,
or otherwise the line containing its `class`, `def`, or `async def` keyword;
indentation bytes belong to the interval. A definition's final physical line
is the final line in its tree-sitter node.
Module bounds are byte `0` through EOF. Before hashing, remove each direct
child definition's complete attachment-line-through-final-line byte interval,
including its terminating LF, then concatenate the remaining intervals in
source order without separators or normalization. A module removes top-level
class/function spans; a class removes method/nested-class spans. Therefore a
child body edit changes the child, not its parent. Adding or removing a child
changes only the child inventory when all remaining parent-owned bytes,
including blank lines outside the removed interval, remain identical.
An empty projection hashes the zero-length byte string. Projection comparison
is byte equality; projection IDs are `sha256:` plus lowercase SHA-256 of the
exact concatenated bytes.

Existing graph edges identify logical symbols, not physical ordinals. An
exact `path::symbol` mapping therefore covers every same-path physical
definition with that qualified symbol. A code reference is joined to the
unique smallest physical owner span containing its source line; if duplicate
definitions have indistinguishable owner spans, all matching physical
definitions receive the edge. Invariant declarations and binds use their
existing line/start/end coordinates to join to the unique physical
definition span. No resolver edge schema is silently reinterpreted as
ordinal-aware.

Classification precedence is `direct`, `exempt`, `inherited`, `uncovered`.
A matching exemption on a directly covered definition is audited as an
overlap but cannot reduce direct coverage. A definition is direct when:

1. its exact owner or a non-module enclosing class/function owner carries a
   resolving code reference;
2. an exact `path::symbol` mapping targets it or a non-module enclosing
   class/function owner;
3. it is the exact target of an invariant declaration or binding edge.

A whole-file mapping or module-level reference makes the module and its
descendants inherited, never direct. A direct non-module enclosing owner
makes its descendants direct. A definition is exempt when no direct rule
applies and at least one valid [COV-4] exemption matches. Everything else is
uncovered.

Coverage includes every Python file under effective `code_roots`, including
files under `test_roots`. Reports group production and test trees separately.
Files outside the accepted snapshot, unreadable files, and syntax-invalid
files retain their existing deterministic issues and contribute no invented
definitions. The report lists them as unscannable and marks repository-state
completeness false. Ratchet mode additionally emits
`INTENT_COVERAGE_INCOMPLETE` with context `patch` when an added or changed
Python file is unreadable or syntax-invalid; it cannot pass by shrinking an
unknown denominator.

The reverse complement includes every active, non-meta requirement section
whose implementation mappings are absent or have no resolving live target.
Planned, exploratory, and meta sections are listed with their rung but do
not count as unimplemented active requirements. This view is derived from
the raw graph before diagnostic suppression. An absent mapping retains the
existing `SPEC_SECTION_UNMAPPED` diagnostic and is not duplicated as BSN005.
The coverage report's `issues` array includes the shared scan's applied
deterministic issues, including that BSS007, exactly once; coverage neither
requires a second `check` run nor constructs a second copy. BSN005 fires only
when mapping declarations exist but none resolves to a live owner. Both
states appear as unimplemented in the coverage view.

Per-tree totals are assigned by longest matching configured code root.
Equal-length overlap is a configuration error. Ratios use integer
numerators and denominators; displayed decimals are presentation only.
`direct_rate = direct / total` and
`accounted_rate = (direct + exempt + inherited_when_enabled) / total`.
A zero-definition denominator yields `null`, never `0` or `1`.

JSON output is artifact `backstitch-intent-coverage-report`, schema version
`1`. Its top-level fields are closed and ordered canonically:

| Field | Contract |
|---|---|
| `artifact`, `schema_version` | exact identity above |
| `profile`, `repo_root`, `mode` | effective invocation identity |
| `metric_identity` | exact ID `intent-coverage-definition-v1`, algorithm version `1`, and the direct/accounted numerator and denominator field names |
| `baseline` | `null` in report mode; otherwise configured ref, resolved commit, merge base, current snapshot hash, current content hash, baseline/current policy identities, history completeness, and history commits inspected |
| `summary` | completeness, unscannable-file count, exact direct, inherited, exempt, uncovered, total, active-unimplemented-requirement, policy-regression, drift, stale-trend, and acknowledgment counts plus nullable direct/accounted rates |
| `trees` | JSON array of path-identified summaries in canonical path order |
| `floors` | JSON array of scope-identified evaluations, counts, configured targets, and pass states |
| `unscannable_files` | path, role, and existing structured scan issue identities |
| `definitions` | identity, coordinates, role, classification, changed flag, governing edges, matching exemptions, and source-slice SHA-256 |
| `worklist` | JSON array of uncovered definition IDs in deterministic triage order |
| `requirements` | spec path, section ID, rung, implementation state, and resolved owners |
| `exemptions` | inline/config origin, selector, reason, matched identities, and overlap state |
| `policy_events` | changed gate key, baseline/current canonical values, event identity, acknowledgment state, commit, and reason |
| `drift_events` | edge ID, current/baseline hashes, acknowledgment, reason, and current-diff status |
| `stale_doc_trends` | edge ID, section-change commit, unacknowledged event count, last event commit, and history completeness |
| `spec_growth` | changed section count and UTF-8 byte delta for the current diff; no unverifiable authoring-origin claim |
| `issues` | ordinary structured deterministic issues after applied policy |
| `report_sha256` | `sha256:` plus SHA-256 of canonical JSON for every preceding field, excluding `report_sha256` itself |

Nested records are closed:

- `metric_identity`: `id: string`, `algorithm_version: integer`,
  `direct_numerator: "direct"`, `direct_denominator: "total"`,
  `accounted_numerator: "direct+exempt+inherited_when_enabled"`, and
  `accounted_denominator: "total"`.
- `baseline`: `configured_ref: string`, `resolved_commit: lowercase Git
  object ID`, `merge_base: lowercase Git object ID`,
  `current_snapshot_sha256: sha256 token`,
  `current_content_sha256: sha256 token`,
  `baseline_policy_sha256: sha256 token`,
  `current_policy_sha256: sha256 token`, `history_complete: boolean`, and
  `history_commits_inspected: nonnegative integer`. Git object IDs must match
  the repository object format and are never assumed to be SHA-1.
  `current_snapshot_sha256` reuses the accepted snapshot identity;
  `current_content_sha256` hashes canonical JSON of sorted
  `[canonical_path, source_sha256]` pairs for every in-scope file.
- `summary`: `complete: boolean`; nonnegative integer fields `unscannable`,
  `direct`, `inherited`, `exempt`, `uncovered`, `total`,
  `unimplemented_requirements`, `policy_events`,
  `acknowledged_policy_events`, `drift_events`,
  `acknowledged_drift_events`, and `stale_doc_trends`; plus `direct_rate` and
  `accounted_rate`, each
  `null` or a finite JSON number derived only for display.
- a `tree` row: `root: canonical directory string`, `role:
  "production"|"test"`, the same five definition counts and two nullable
  rates as `summary`, and `complete: boolean`.
- a `floor` row: `scope: canonical directory string`; nonnegative integer
  fields `direct`, `inherited`, `exempt`, `uncovered`, and `total`;
  `direct_rate` and `accounted_rate` with the summary nullability/rounding;
  `direct_target` and `accounted_target`, each a finite JSON number in
  `[0,1]` or null when not configured; and `passes: boolean`.
- an `unscannable_file` row: `path`, `role`, and nonempty
  `issue_identities`, where each closed identity has `code: string`,
  `path: canonical path`, and `line: positive integer|null` and is sorted by
  `(code, path, line-or-0)`.
- a `definition` row: `definition_id` (SHA-256 of path and locator), `path`,
  `structural_locator`, `qualname` (`null` only for fallback modules),
  `kind: "module"|"class"|"function"|"async_function"|"method"|
  "async_method"`, `role: "production"|"test"`, positive `start_line` and
  `end_line`, `tree`, `classification:
  "direct"|"inherited"|"exempt"|"uncovered"`, `changed: boolean|null`
  (`null` in report mode), `source_projection_sha256`, sorted
  `governing_edge_ids`, and sorted `matching_exemption_ids`.
  A synthesized module uses `start_line = 1`; its `end_line` is the final
  physical line number, or `1` for an empty file.
- `worklist` contains each and only `uncovered` `definition_id` once, ordered
  production before test, then canonical path, then structural locator. Text
  triage output follows this array. Inherited definitions remain visible in
  `definitions` and metrics but are not [COV-6]'s uncovered worklist.
- a `requirement` row: `requirement_id` (the hash defined below), `path`,
  `section_id`, `rung: "active"|"planned"|"exploratory"|"meta"`,
  `implementation_state: "implemented"|"absent_mapping"|
  "declared_without_live_owner"`, and sorted `owner_definition_ids`.
- an `exemption` row: `exemption_id`, `origin:
  "inline"|"config_path"|"config_glob"`, `path`, `line: integer|null`,
  `selector`, `reason`, sorted `matched_definition_ids`, and
  `state: "used"|"overlap_only"|"unused"`.
- a `policy_event` row: `event_id`, `key`, `baseline_value`,
  `current_value` (the two values are canonical JSON values admitted by the
  corresponding config key), `parent_commit: Git object ID`,
  `transition_commit: Git object ID|null` (null only for the synthetic
  accepted-snapshot transition), `acknowledged: boolean`,
  `acknowledgment_commit: Git object ID|null`, and
  `acknowledgment_reason: string|null`.
- a `drift_event` row: `event_id`, `edge_id`, `requirement_id`,
  `definition_id`, `parent_commit: Git object ID`,
  `transition_commit: Git object ID|null` (null only for the synthetic
  accepted-snapshot transition),
  `base_projection_sha256`, `current_projection_sha256`,
  `acknowledged: boolean`, `acknowledgment_commit: Git object ID|null`,
  `acknowledgment_reason: string|null`, and
  `synthetic_current: boolean`.
- a `stale_doc_trend` row: `edge_id`,
  `section_change_commit: Git object ID|null`,
  `unacknowledged_event_count: nonnegative integer`,
  `last_event_commit: Git object ID|null`, `history_complete: boolean`, and
  `commits_inspected: nonnegative integer`. `section_change_commit` is null
  exactly when the bounded walk ends before finding a governing-section
  change.
- `spec_growth`: nonnegative `changed_sections`, signed
  `utf8_byte_delta`, and sorted `requirement_ids`.
- each `issue` is the exact existing `Issue` dataclass field set serialized by
  `Report.to_dict()` (`code`, `severity`, `path`, `line`, `message`,
  `section_id`, `symbol`, `short_code`, `context`, `default_severity`, and
  `invariant_id`). `code`, `path`, `message`, and `short_code` are strings;
  `severity` is `"error"|"warning"|"info"`; `line` is a positive
  integer or null; `section_id`, `symbol`, `context`, and `invariant_id` are
  string or null; `default_severity` is the severity vocabulary or null.
  Coverage does not define a second issue shape.

Stable IDs use the existing `canonical_json_bytes()` function as their
unambiguous preimage and the `sha256:` lowercase-hex encoding:
`definition_id = hash(["intent-definition-v1", path,
structural_locator])`; configured `exemption_id =
hash(["intent-exemption-v1", origin, selector])`; inline `exemption_id =
hash(["intent-exemption-v1", "inline", path, line, normalized_reason])`.
`requirement_id =
hash(["intent-requirement-v1", path, section_id])`.
Edge and event preimages are the exact tuples defined in [COV-8] and [COV-5].
Nullable rates are rounded to six decimal places using decimal
round-half-even and serialized as the shortest JSON number with that value;
enforcement never consumes the rounded value.

Arrays use canonical identity order. JSON is stable for the same accepted
snapshot, Git object database, effective configuration, and command
arguments. Text is a rendering of the typed report and is never parsed back
into structure. Sort keys are `tree(root, role)`, `floor(scope)`,
`unscannable(path, role)`,
`definition(path, structural_locator)`, `requirement(path, section_id)`,
`worklist(role-production-first, path, structural_locator)`,
`exemption(exemption_id)`, `policy_event(event_id)`,
`drift_event(event_id)`,
`trend(edge_id)`, and the existing canonical issue key. The validator
rejects unknown/missing keys,
wrong nullability, invalid vocabulary, duplicate identities, dangling joins,
overlapping classification partitions, or noncanonical order. It recomputes
every definition ID, edge ID, count, rate numerator/denominator, tree
partition, floor scope/result, exemption join, requirement state,
worklist membership/order, policy/drift/trend aggregate,
spec-growth aggregate, and final report hash from separately supplied source
facts. `report_sha256` is computed by removing that key and passing the
complete remaining top-level mapping to the existing
`canonical_json_bytes()` encoding (sorted keys, compact separators,
ASCII-escaped text, finite numbers), then prefixing the lowercase SHA-256
hex digest with `sha256:`.

_Implementation mapping_:

- `backstitch/code_parser.py::parse_python_source`
- `backstitch/python_refs.py::python_definition_inventory_bytes`
- `backstitch/intent_coverage.py`
- `backstitch/intent_coverage_reporting.py`

## 4. Exemptions [COV-4]

Not all code deserves a spec. Re-exports, argument plumbing, generated code,
and trivial glue are accounted for by exemption, not by manufactured spec
text.

Inline exemptions use exactly
`# backstitch: no-spec -- <nonblank reason>`. A candidate is recognized only
when either (a) tree-sitter classifies it as a comment attached to the
physical line containing that owner's `class`, `def`, or `async def`
keyword, after which the comment bytes with leading whitespace removed begin
exactly `# backstitch: no-spec`, or (b) one complete logical docstring line,
after removing only its indentation, begins exactly
`backstitch: no-spec`. A module marker is recognized only by form (b) in the
module docstring. In both forms the token must end the logical line or be
followed by ASCII whitespace; a longer token such as `no-specification` is a
near miss. The exact separator is one or more ASCII spaces, `--`, then one
or more ASCII spaces. The reason is the remaining UTF-8 text with outer
Unicode whitespace removed and NFC normalized; it must contain no CR, LF, or
NUL and encode to at most 4096 bytes.

The recognition table is closed:

| Input | Result |
|---|---|
| exact prefix, separator, nonblank reason | valid exemption |
| exact prefix with no separator | recognized, `BSN004` |
| exact prefix with separator but empty/whitespace reason | recognized, `BSN004` |
| exact prefix with malformed separator | recognized, `BSN004` |
| different prefix/case/spelling or wrong syntax-tree location | inert near miss |

String literals outside the owning docstring, comments on other statements,
nested example text, and near-miss spellings are inert.

Configured exemptions use:

```toml
[[tool.backstitch.coverage.exemptions]]
path = "generated/client.py" # exactly one of path or glob
reason = "Generated from the service schema."

[[tool.backstitch.coverage.exemptions]]
glob = "vendor/**/*.py"
reason = "Vendored upstream source."
```

`path` and `glob` are mutually exclusive repository-relative selectors.
Configured reasons use the same normalization and byte bound as inline
reasons. A configured missing, non-string, blank, multiline, NUL-containing,
or over-limit reason is a configuration error: exit `2`, no report. Config
order is retained as provenance but does not affect classification.

All matching exemptions appear in the ledger with exactly one state:
`used` when they match at least one otherwise non-direct definition,
`overlap_only` when every match is already direct, or `unused` when they
match no definition. `unused` emits `INTENT_EXEMPTION_UNUSED`;
`overlap_only` remains visible but emits no unused finding. A recognized
inline candidate with an invalid reason emits
`INTENT_EXEMPTION_UNREASONED` and does not exempt anything.

Exemption is deliberately **cheaper than specification**: one line with a
reason versus authored spec text plus mappings. This asymmetry is a design
requirement, not an accident — if faking a spec is easier than exempting,
the gate manufactures vacuous specs ([COV-7]).

[COV-9] is the single authoritative `BSN` registry. This section defines
exemption behavior and refers to its BSN003 and BSN004 rows; it does not
define a second code meaning or level.

_Implementation mapping_:

- `backstitch/code_parser.py::parse_python_source`
- `backstitch/python_refs.py::python_definition_inventory_bytes`
- `backstitch/settings.py::CoverageExemption`
- `backstitch/settings.py::_parse_coverage_settings`
- `backstitch/intent_coverage.py`

## 5. The Ratchet Gate [COV-5]

Absolute coverage on an existing repository invites either despair or boiling
the ocean. The command therefore has two modes:

- `report`: compute repository-state coverage without invoking Git;
- `ratchet`: compute repository-state coverage plus a repository-derived
  aggregate diff and enforce patch/floor contexts.

Ratchet mode requires a nonblank `coverage.ratchet_base` in committed
repository configuration. There is no CLI base-ref override. Backstitch
resolves the configured ref to a commit, computes its merge base with `HEAD`,
reads baseline blobs from the Git object database, and compares them with the
already accepted current snapshot. It never fetches, executes an external diff
driver, invokes a shell, trusts pager/editor configuration, or reads baseline
files through a checkout path.

The current side includes tracked worktree/index changes and untracked Python
files present in the accepted snapshot. A new file makes every current
definition changed. A deleted definition has no patch-coverage obligation but
may make a requirement unimplemented. Renames are remove-plus-add. A surviving
definition is changed when the canonical source slice selected by
`(path, structural_locator)` differs byte-for-byte from its merge-base slice.
Coordinate-only movement outside the slice is not a change.

In ratchet mode, changed uncovered definitions emit
`INTENT_UNCOVERED_DEFINITION` with context `patch`; changed inherited-only
definitions emit `INTENT_INHERITED_ONLY` with context `patch` when
`inherited_counts = false`. Packaged policy makes both patch contexts errors.
Repository-state contexts remain info. Applied diagnostic policy remains the
final severity and exit authority.

Floor keys are `direct` and `accounted`, each a finite number in `[0, 1]`.
Comparison uses integer cross multiplication, not rounded display values.
A current metric below its configured floor emits
`INTENT_COVERAGE_FLOOR_REGRESSION` (`BSN007`, packaged error). Baseline floor
changes are policy transitions handled by BSN009 below, so one config edit
does not produce two competing diagnostics.

Ratchet authority is closed. A repository-owned config layer is a regular,
no-follow file inside the accepted repository root that exists in the accepted
snapshot and is addressable by the same canonical path at the merge base.
Every effective gate-affecting value must originate only from packaged
defaults or such repository-owned layers. Ratchet mode rejects home,
environment, external include, explicit CLI `--config`, CLI `--no-config`,
CLI `--profile`, and CLI `--option` contributions to gate inputs as an
invocation error. Only `format`, `output`, the root alias, and the
`--require-ratchet REF` assertion may be operational invocation overrides.

The canonical policy is the following closed JSON mapping after normal config
merge, path normalization, and profile selection. Tuple/set-like collections
are arrays in canonical value order; authored diagnostic and suppression rule
order remains an array because order affects behavior:

```text
{
  "schema": "intent-coverage-policy-v1",
  "profile": {
    "name": string|null,
    "spec_roots": [string], "code_roots": [string],
    "test_roots": [string], "planned_spec_globs": [string],
    "exploratory_spec_globs": [string], "meta_spec_globs": [string],
    "process_spec_globs": [string]
  },
  "exclude": [string],
  "coverage": {
    "mode": string, "granularity": string, "inherited_counts": boolean,
    "ratchet_base": string,
    "exemptions": [{"id": string, "kind": "path"|"glob",
                    "selector": string, "reason": string}],
    "floors": [{"scope": string, "direct": number|null,
                "accounted": number|null}],
    "maximum_baseline_files": integer, "maximum_file_bytes": integer,
    "maximum_baseline_bytes": integer, "maximum_history_commits": integer,
    "maximum_git_command_seconds": number,
    "maximum_git_commands": integer, "maximum_git_output_bytes": integer,
    "maximum_commit_message_bytes": integer,
    "maximum_runtime_seconds": number
  },
  "diagnostics": {
    "default_level": string, "fail_on": [string],
    "suppressible_levels": [string],
    "levels": [{"selectors": [string], "level": string}]
  },
  "suppressions": {
    "warn_unused_ignores": boolean,
    "require_suppression_declarations": boolean,
    "per_file_ignores": [{"selector": string, "codes": [string]}],
    "per_section_ignores": [{"selector": string, "codes": [string]}],
    "rules": [{
      "mechanism": string, "provenance": string, "path": string,
      "sections": [string], "codes": [string], "declaration": string|null,
      "origin": {"source": string, "position": integer|null,
                 "line": integer|null}
    }]
  }
}
```

The policy identity is the SHA-256 token of
`canonical_json_bytes(canonical_policy)`. Presentation-only `format` and
`output` are intentionally absent. Every transition compares these mappings by
these stable changed-key names:

- fixed scalar JSON pointers, such as `/coverage/inherited_counts`;
- set member pointers
  `/<collection>/<sha256:canonical-json-member>`, with JSON null representing
  absence;
- `/coverage/exemptions/<exemption_id>` for one selector/reason row;
- `/coverage/floors/<sha256:canonical-scope>/<direct|accounted>`; and
- whole ordered objects `/diagnostics` and `/suppressions`.

The comparison table is executable and closed:

1. Any change to a nonblank `ratchet_base`, any profile-name change, or any
   `granularity` change is weakening. A current `report` invocation never opens
   Git merely to compare its former mode; the trusted CI
   `--require-ratchet REF` assertion is the authority that makes a
   ratchet-to-report edit fail closed. Report-to-ratchet is strengthening.
2. `inherited_counts` false-to-true is weakening; true-to-false strengthens.
3. Removing `spec_roots`/`code_roots`, adding any `exclude` value, adding any
   planned/exploratory/meta/process glob, or changing `test_roots` is
   weakening. The reverse set operations strengthen. This rule compares
   selector strings only and never attempts glob-language inclusion.
4. Adding an exemption ID or changing its `kind`/`selector` is weakening;
   removing one strengthens; a reason-only change is neutral. A changed
   selector is mechanically one removal plus one addition.
5. Lowering/removing a floor is weakening; adding/raising one strengthens.
6. Any byte-distinct canonical `/diagnostics` or `/suppressions` object is
   authority-sensitive and requires acknowledgment, even when a human might
   judge it stronger. This conservative rule covers `fail_on`, default and
   per-code/context severity, `suppressible_levels`, per-file/per-section
   ignores, and governed suppression rules without a second policy
   interpreter.
7. Budget changes are neutral for acceptance because every overrun fails
   closed with exit `2`; they remain in the policy identity and report.

A weakening or authority-sensitive current event is recorded in
`policy_events`. If unacknowledged, it emits
`INTENT_COVERAGE_POLICY_REGRESSION` (`BSN009`, packaged error), including the
baseline/current policy identities and changed key. BSN009 cannot be
suppressed or severity-demoted by current policy.

An intentional weakening must be acknowledged by the commit that introduces
its exact first-parent policy transition:

```text
Backstitch-Coverage-Policy-Ack: <policy-event-id> -- <nonblank reason>
```

`policy-event-id = hash(["intent-policy-event-v1", parent_commit,
changed_key, baseline_value, current_value])`. The same bounded trailer
grammar and exact-transition rules as drift apply. A dirty-worktree weakening
cannot be acknowledged. An acknowledged event remains in `policy_events` but
emits no BSN009 `Issue`; only an unacknowledged current event enters `issues`
and the ordinary exit-1 test. Unknown, malformed, duplicate, or
pre-acknowledging trailers do not match. This mechanism is for explicit,
reviewed policy changes. It does not claim to resist a maintainer who can also
rewrite the CI workflow or Backstitch binary.

Policy transitions are folded over the same first-parent `merge_base..HEAD`
sequence plus the synthetic accepted-snapshot transition. A weakening event
remains current only while its weakened value is the final effective value; a
later strengthening supersedes it. BSN009 is emitted for each current event,
and its acknowledgment can come only from the commit whose parent-to-child
transition first introduced that exact final value.

```toml
[tool.backstitch.coverage]
mode = "report"               # report | ratchet
format = "text"               # text | json
# output = "coverage.json"    # optional; absent means stdout
granularity = "definition"    # the only v1 value
inherited_counts = false
ratchet_base = ""             # required only in ratchet mode
maximum_baseline_files = 20000
maximum_file_bytes = 5000000
maximum_baseline_bytes = 100000000
maximum_history_commits = 1000
maximum_git_command_seconds = 10.0
maximum_git_commands = 64
maximum_git_output_bytes = 100000000
maximum_commit_message_bytes = 1000000
maximum_runtime_seconds = 60.0

[tool.backstitch.coverage.floors."backstitch/"]
direct = 0.0
accounted = 0.0
```

Floor scope keys must equal or be nested within a final effective code root
and use canonical repository-relative directory syntax. A scope contains
exactly definitions whose canonical path equals the scope path or begins with
`scope + "/"`; a zero-definition scope has null rates and any positive floor
fails. Each floor is an independent assertion over every definition below that
scope. All matching overlapping floors are evaluated; display-tree
longest-root ownership does not select or suppress a floor. The scope path is
the floor identity in reports.

Unknown keys, invalid refs, missing objects, shallow-history insufficiency,
budget overruns, and Git command failures are invocation errors with exit `2`,
one-line stderr, and no partial output. `maximum_runtime_seconds` is one
absolute deadline for the entire ratchet and history phase, starting after
current snapshot/config acceptance and ending after transition evaluation and
report validation. It covers Git subprocess time plus baseline parsing,
definition projection, policy/drift comparison, history folding, and cleanup.
CPU loops check the same monotonic deadline at each file/commit batch and
before output publication. Every Git operation additionally consumes the
shared command count and cumulative stdout/stderr byte budget. Per-command
timeouts are capped by both `maximum_git_command_seconds` and the remaining
phase budget. Batch protocols are required where history size could otherwise
create one command per commit, blob, edge, or definition.
`maximum_commit_message_bytes` applies to each decoded commit message before
trailer parsing, and those bytes also count toward `maximum_git_output_bytes`.
The allowed topology is constant-count ref/object setup (`rev-parse`,
`merge-base`, `rev-list`/`log`, `ls-tree`) plus batched `cat-file --batch`
streams; no loop may spawn a process per file, commit, blob, edge, or
definition. A producer that crosses a byte bound is terminated and reaped
immediately; unread buffered bytes do not excuse the overrun.

_Implementation mapping_:

- `backstitch/settings.py::CoverageFloor`
- `backstitch/settings.py::CoverageSettings`
- `backstitch/settings.py::_parse_coverage_settings`
- `backstitch/git_baseline.py`
- `backstitch/intent_history.py`

## 6. The Triage Loop [COV-6]

The uncovered-definition report is a worklist owned by intent coverage. It
does not create an evidence broker, proposal store, activation state, or
evidence case. A human or agent may use [EVC-8]'s read-only obligation list,
evidence summary, and candidate discovery to inspect related intent and
source, but those reads cannot ratify a classification or source relation.

For each deterministically ranked uncovered definition, the reviewer chooses
one outcome: `needs-spec`, `glue`, `dead`, or `contradicts-spec`.
`needs-spec` proposes ordinary spec text plus reciprocal source declarations;
`glue` proposes a reasoned [COV-4] exemption; `dead` proposes source removal;
and `contradicts-spec` identifies the existing obligation and proposes a
corrective source diff whose semantic effect can be evaluated through the
ordinary current-repository gate. Backstitch may show exact supported
annotation forms, but it does not apply any proposal.

Only a human-reviewed source diff changes coverage or alignment. After that
diff lands, the resolver and coverage computation recompute from repository
source. Rejected advice creates no durable product state. The loop continues
until the worklist is empty or the owner records a bounded stop decision.
The coverage runner owns ranking; the human reviewer owns disposition;
[EVC-8] owns obligation reads and guidance. Verification reruns coverage and
the reciprocal trace gate from current source. The required action is to land
or reject an ordinary source diff, never to activate tool-owned state.

_Implementation mapping_:

- `backstitch/intent_coverage.py`

## 7. Anti-Goodhart Requirements [COV-7]

Two failure modes are anticipated and must be countered by design:

- **Vacuous specs.** A coverage gate incentivizes spraying uninformative
  text ("this module manages state") over uncovered code — the analogue of
  tests that execute lines without asserting. Countermeasure: sampled
  semantic informativeness review — a spec's text should distinguish the
  current implementation from a mutated one; the [SEM-8] corpus gains
  spec-side mutations for this. Exemption being cheaper than fake
  specification ([COV-4]) removes the incentive at the source.
- **Over-specification.** Every spec the loop generates is prose that must
  be maintained and re-read; unbounded spec growth is a real cost, and a
  coverage gate must not become the mechanism by which the corpus grows
  without bound. The `needs-spec` classification bar is behavioral: a
  definition needs spec text only when it embodies a decision a maintainer
  would want stated. Everything else is glue, and glue is exempted.

Backstitch does not claim to know whether a human-authored section originated
from triage advice. The anti-Goodhart signal is source-derived instead:
ratchet reports count and byte-size every spec section added or changed in
the diff. Semantic qualification adds paired spec-side mutations in which
implementation stays fixed while informative contract text is replaced by
vacuous, overbroad, or non-discriminating prose. The ordinary current-source
semantic packet and analyzer judge those cases; no proposal provenance,
author label, or new packet schema is introduced.

## 8. Drift Coverage [COV-8]

The fifth deterministic question is asked at change time: **which changed
code touches contract-bearing areas without corresponding spec or test
movement?** Spec, test-evidence, and orphan coverage measure a repository
state; drift coverage measures a *diff* against the trace graph.

A contract edge is the tuple `(spec_path, section_id, code_path,
structural_locator)` and has a stable SHA-256 edge ID. A current-diff drift
suspect exists when:

1. the mapped production definition source slice changed;
2. the governing section body bytes, excluding its implementation-mapping
   block, did not change;
3. the section's normalized mapping target set did not change; and
4. no test-root definition connected to that section through a resolving
   mapping, backlink, or invariant bind changed.

Missing or ambiguous edges do not become drift suspects; their existing graph
issues remain authoritative. Drift emits `INTENT_DRIFT_SUSPECT` (`BSN006`,
packaged info).

Drift hash inputs are byte-exact:

- The Markdown parser adds `mapping_block_spans` as typed
  `(section_id, start_line, end_line)` facts. A span begins at the first
  physical source line of a recognized `_Implementation mapping_:` paragraph
  and ends at the final physical line of the immediately following mapping
  list sequence that the existing parser assigns to that owner. It includes
  the marker token's complete source-line range, every owned mapping-list
  token's complete range, all intervening physical lines, and each final
  line's LF when present. A marker paragraph with inline mapping tokens and no
  following list ends at that paragraph token's final source line.
  When a bracket bullet defines a subsection and owns mapping tokens inside
  the enclosing list, the parser also emits an owned span for that subsection
  covering each complete physical inline-token range that contributes its
  mappings. These subsection spans may overlap the enclosing heading's block;
  projection removes each section's own spans only.
- The governing section interval reuses `ParsedSpec.section_spans`: physical
  bytes from the start of `start_line` through the end of `end_line`, including
  terminating LFs when present. `section_projection` removes every owned
  mapping-block byte interval and concatenates the retained byte intervals in
  source order without separators or normalization. `section_hash` is SHA-256
  of those exact bytes.
- `mapping_hash = hash(["intent-mapping-set-v1", rows])`, where `rows` is the
  sorted unique array of
  `[resolved_canonical_code_path, normalized_code_symbol_or_null]` for every
  resolving raw-graph mapping owned by the section. Path mappings use null
  symbol; symbols use the resolver's existing normalized spelling.
  Nonresolving declarations remain represented by their graph issues and do
  not invent targets.
- `connected_test_hash = hash(["intent-connected-tests-v1", rows])`, where
  `rows` is the array of `[definition_id, source_projection_sha256]` for every
  connected test-root definition, sorted uniquely by definition ID. No
  connected tests hashes the canonical empty array. The same
  mapping/backlink/invariant-bind join used by the predicate selects the rows.

Drift is evaluated per first-parent transition in `merge_base..HEAD`, plus one
synthetic `HEAD..accepted-snapshot` transition when tracked, staged, or
untracked current bytes differ. `edge_id = hash(["intent-edge-v1", spec_path,
section_id, code_path, structural_locator])`. Each `event_id` hashes
`["intent-drift-event-v1", edge_id, parent_commit, before_section_hash,
after_section_hash, before_mapping_hash, after_mapping_hash,
before_implementation_hash, after_implementation_hash,
before_connected_test_hash, after_connected_test_hash]`. Including the
transition's parent commit makes repeated A-to-B content changes distinct
while omitting the child commit lets a developer compute the ID before writing
that child commit and its trailer.

`drift_events` contains every event produced by the inspected
`merge_base..HEAD` first-parent transitions plus the synthetic transition,
including acknowledged events. It does not fold or deduplicate events by edge.
Stale-history events outside that current range appear only in
`stale_doc_trends`.

A commit acknowledges one or more drift events produced by its exact
first-parent-to-commit transition with a Git trailer:

```text
Backstitch-Drift-Ack: <event-id> -- <nonblank reason>
```

The trailer is read as untrusted bounded UTF-8 data, appears in the report
audit ledger, and suppresses only the identical event emitted for that
commit's first-parent transition. A trailer in any other commit does not
match. An aggregate range is acknowledged only event by event; there is no
range-wide shortcut. The synthetic dirty-worktree transition has no commit
and cannot be acknowledged until committed. Malformed, duplicate, or unknown
event IDs do not suppress. Backstitch creates no acknowledgment file or
mutable ledger.

Stale-document trends are derived from first-parent Git history. Starting at
the most recent transition where the governing section body changed,
Backstitch applies the same edge predicate to each bounded commit transition
and counts unacknowledged drift events. History truncation is explicit and
never represented as a complete zero. The signal remains advisory.

The semantic lane evaluates current source alignment after the change. This
version does not claim that existing semantic packets contain diff context;
adding a diff packet is a separate semantic-contract change.

_Implementation mapping_:

- `backstitch/markdown_specs.py::ParsedSpec`
- `backstitch/markdown_specs.py::parse_markdown_spec_bytes`
- `backstitch/git_baseline.py`
- `backstitch/intent_history.py`

[COV-9] is the single authoritative `BSN` registry. This section refers to its
BSN006 row rather than restating code meaning or packaged level.

## 9. Verification Expectations [COV-9]

`backstitch coverage [PATH] [--repo-root PATH] [--format text|json]
[--output PATH] [--profile NAME] [--config PATH|--no-config]
[--option KEY VALUE]... [--require-ratchet REF]` uses the common config
controls.
Positional `PATH` and `--repo-root PATH` are exact aliases and are mutually
exclusive; when neither is supplied, the root anchor is the current working
directory. `--format` and `--output` override their config keys. Report mode
accepts the listed config/profile/option controls with ordinary precedence.
Ratchet mode rejects `--profile`, every `--option`, `--no-config`, and every
explicit CLI `--config`. Ratchet configuration must come from ordinary
repository discovery, after which every discovered/include layer must meet the
repository-owned-layer rule. This prevents selecting an alternate lax
in-repository config whose baseline and current policy happen to match.
`--require-ratchet REF` is an operational assertion with no config equivalent:
it returns exit `2` without producing a report unless the repository-owned
effective mode is `ratchet` and its literal `ratchet_base` equals `REF`. It
does not override or resolve a different base. CI must pin the expected ref
with this flag once ratchet is enabled so a config-only mode or base change
cannot silently disable or collapse the gate.

The command returns `0` when no issue meets effective `fail_on`, `1` when
findings meet it, and `2` for invocation, configuration, Git, budget, or
output-publication failure. Output publication is atomic. The command never
imports `llm`, invokes a provider, or writes repository source.

The `BSN` registry is below. `Code` is canonical diagnostic identity;
`Context` is a separate closed field and never forms a second code.

| Code | Context | Short | Packaged level |
|---|---|---|---|
| `INTENT_UNCOVERED_DEFINITION` | `repository` | `BSN001` | info |
| `INTENT_UNCOVERED_DEFINITION` | `patch` | `BSN001` | error |
| `INTENT_INHERITED_ONLY` | `repository` | `BSN002` | info |
| `INTENT_INHERITED_ONLY` | `patch` | `BSN002` | error |
| `INTENT_EXEMPTION_UNUSED` | none | `BSN003` | warning |
| `INTENT_EXEMPTION_UNREASONED` | none | `BSN004` | error |
| `INTENT_REQUIREMENT_UNIMPLEMENTED` | none | `BSN005` | info; declarations exist but no live owner resolves |
| `INTENT_DRIFT_SUSPECT` | none | `BSN006` | info |
| `INTENT_COVERAGE_FLOOR_REGRESSION` | none | `BSN007` | error |
| `INTENT_COVERAGE_INCOMPLETE` | `repository` | `BSN008` | info |
| `INTENT_COVERAGE_INCOMPLETE` | `patch` | `BSN008` | error |
| `INTENT_COVERAGE_POLICY_REGRESSION` | none | `BSN009` | error; only an exact policy acknowledgment makes it non-failing |

Every row, context, exit class, config key, report field, exemption form,
changed-definition branch, drift branch, acknowledgment branch, null metric,
and history-completeness state has a firing test. Executable gates also cover:

- a definition with a resolving docstring reference, a `path::symbol`
  mapping, and an invariant binding is directly covered under each edge kind
  independently;
- file-level blanket mapping yields inherited, never direct, coverage;
- `INTENT_UNCOVERED_DEFINITION` fires for a fresh unreferenced definition and
  stops firing when a reference, mapping, or exemption is added;
- an exemption without a reason fails; an unused exemption fires its finding;
  removing the exempted code makes the exemption unused;
- ratchet mode passes a diff whose new definitions are covered or exempted,
  fails one that adds an uncovered definition, and ignores pre-existing
  backlog; base-ref computation is repository-derived;
- floor and policy regressions fire under the exact [COV-5] rules;
- the spec-side complement lists a requirement section whose mapping was
  deleted, and clears when a live mapping returns;
- coverage output is deterministic and byte-stable across repeated runs;
- the uncovered-definition worklist ranking is deterministic for a fixed
  repository state; repeated runs return the same definition identities and
  ranking facts;
- for each `needs-spec`, `glue`, `dead`, or `contradicts-spec` disposition,
  only an ordinary landed source diff changes coverage or alignment; rejected
  or no-diff advice leaves both unchanged, and no proposal or activation
  object exists;
- a diff that changes a mapped implementation without touching its section
  text, mapping block, or binding tests fires `INTENT_DRIFT_SUSPECT`; the same
  diff with a binding-test change does not; an acknowledged suspect remains
  recoverable through the coverage audit ledger with its reason; and
- drift computation is deterministic for a fixed base ref and repository
  state, and the base ref is repository-derived, never trusted from the
  invoker.

_Implementation mapping_:

- `backstitch/intent_coverage_reporting.py`
- `backstitch/git_baseline.py`

## Related Plans

- `docs/plans/2026-07-28-intent-coverage-implementation-plan.md`
  (active implementation plan; spec promotion baseline)
- `docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md`
  (vocabulary reconciliation)

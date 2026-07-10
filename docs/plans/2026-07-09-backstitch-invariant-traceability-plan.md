# Backstitch Invariant Traceability Pass

Status: implementation and strict-policy follow-up gates passed after
independent review. The worktree remains uncommitted, so the repository
completion/ready-to-land gate remains open.
Plan type: implementation with spec revision.
Risk level: high. This changes parser grammar, profile/configuration shape,
diagnostic allocation, deterministic report schemas, packet/result contracts,
and CLI behavior. The hardening-plan rules apply.

## Goal

Activate and implement invariant traceability as a first-class deterministic
graph pass plus an advisory semantic binding pass. Specs and owning Python
docstrings will declare stable invariant IDs; bounded test definitions will bind
those IDs; deterministic mode will report missing, invalid, duplicate, and
unknown links without model calls; and the existing semantic pipeline will
review bounded target/test evidence.

The spec revision is part of the work, not cleanup after implementation. It
must first resolve the proposed contract's stale severity rules, marker leakage,
missing test-root definition, packet-shape contradiction, overloaded
`invariant` name, and unverifiable assertion-line claim.

## Source Documents

Source specs:

- `docs/specs/05-backstitch-invariants.md` [INV-1] through [INV-10]
- `docs/specs/02-backstitch-core.md` [SC-2] through [SC-7], [SC-10],
  [SC-11], [SC-13], [SC-15]
- `docs/specs/03-backstitch-configuration.md` [CFG-5], [CFG-6], [CFG-8],
  [CFG-9]
- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-6], [EXC-8],
  [EXC-9], [EXC-10]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11]

Implementation context:

- `docs/implementation/04-backstitch-style-traceability.md`
- `docs/implementation/02-repository-map.md`
- `backstitch/models.py`
- `backstitch/code_parser.py`
- `backstitch/python_refs.py`
- `backstitch/markdown_specs.py`
- `backstitch/resolver.py`
- `backstitch/check_pipeline.py`
- `backstitch/diagnostics.py`
- `backstitch/defaults.toml`
- `backstitch/analysis_packets.py`
- `backstitch/artifact_contracts.py`
- `backstitch/analysis_llm.py`
- `backstitch/analysis_results.py`
- `backstitch/reporting.py`
- `backstitch/config.py`
- `backstitch/profiles.py`
- `backstitch/settings.py`
- `backstitch/cli.py`

Required runbooks:

- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`

## Spec Baseline

- Baseline commit at plan authoring:
  `fc7427180fcbc99eb19ae5771a2231546ddd026b`.
- `docs/specs/05-backstitch-invariants.md` is clean in the worktree and was
  last changed by `1e9c0d9d185c1a2c244f70db8af8c39139fc245c`.
- The worktree is not clean. It contains the uncommitted, locally verified
  configurable-diagnostics implementation described by
  `docs/plans/2026-07-08-configurable-diagnostics-plan.md`. It overlaps
  [SC-11], [SC-15], [CFG-*], [EXC-*], `models.py`, `resolver.py`,
  `artifact_contracts.py`, `settings.py`, `cli.py`, tests, and the golden.
- This plan targets that visible worktree behavior because invariant
  diagnostics require its packaged registry, context selectors, effective
  policy, and suppression audit. Those changes belong to the existing
  worktree and must not be reverted or silently absorbed.
- Diagnostics prerequisite completed uncommitted on 2026-07-09 against base
  `fc7427180fcbc99eb19ae5771a2231546ddd026b`. The 31-path implementation,
  spec, and test baseline excludes both plan files from its sorted per-file
  SHA-256 manifest and hashes to
  `6d351d49dd2450f739dc05cdb930dad32681e90dffe5707bdebd3117a0ebf4eb`.
  Targeted diagnostics tests, acceptance probes, full pytest, Ruff, format,
  mypy, `config show`, and self-corpus all passed; self-corpus reported 0
  errors, 0 warnings, and 33 infos. Independent remediation review closed with
  no findings. Task 2 is satisfied against this exact uncommitted baseline;
  later invariant edits must not be mistaken for prerequisite drift.
- The residual invariant-owned contract delta is exactly the Proposed Spec
  Delta below, applied on top of that Task 2 baseline. Pre-existing diagnostic
  hunks in specs 00, 02, 03, and 04 remain owned by the diagnostics plan and
  are not reapplied or reviewed as invariant work. Because the prerequisite is
  intentionally uncommitted, reviewers must use the recorded baseline manifest
  identity plus this enumerated residual delta, not a raw `HEAD` diff, to
  distinguish ownership.
- Contract-alignment baseline completed uncommitted on 2026-07-09 against base
  `fc7427180fcbc99eb19ae5771a2231546ddd026b`. The 33-path implementation,
  spec, context, and test baseline excludes both plan files from its sorted
  per-file SHA-256 manifest and hashes to
  `a151ff6ee6c146c790947e6f3c9e251890cb01ddcf9fd7727b1b94d29d83eeb4`.
  `git diff --check` and self-corpus passed; self-corpus remained exit 0 with
  0 errors, 0 warnings, and 33 infos. The final narrow Grok challenge found no
  blockers and answered the requested confidence question "Yes."

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Context And Key Files

Read first, in this order:

1. `backstitch/models.py`, `backstitch/resolver.py`, and
   `backstitch/check_pipeline.py`
   - Current ownership: typed graph records and reports live in `models.py`;
     pure deterministic relation construction lives in `resolve`; diagnostic
     policy and suppression are applied afterward by the check pipeline.
   - Load-bearing boundary: invariant resolution belongs in the same pure pass,
     not in packet generation or CLI code.
2. `backstitch/code_parser.py`, `backstitch/python_refs.py`, and
   `backstitch/markdown_specs.py`
   - Current ownership: tree-sitter supplies Python doc blocks, owner spans,
     comments, and statement spans. `python_refs.py` currently extracts every
     bracketed ID from every docstring/comment line. Markdown block structure
     belongs to markdown-it.
   - Load-bearing boundary: invariant marker recognition must precede generic
     bracket extraction, and Markdown parsing must not add a raw-text parser.
3. `backstitch/diagnostics.py`, `backstitch/defaults.toml`, and
   `backstitch/settings.py`
   - Current ownership: packaged TOML owns canonical/short codes, statuses,
     contexts, and default levels. Repository policy layers over it.
   - Load-bearing boundary: `INVARIANT_UNTESTED` requires `required` and
     `draft` contexts; no hard-coded parallel severity table is allowed.
4. `backstitch/analysis_packets.py` and `backstitch/artifact_contracts.py`
   - Current ownership: section packets are generated for edge-bearing
     sections; tests are path-only; packet validation has one closed shape.
   - Load-bearing boundary: invariant packets require line-bounded test
     snippets and a discriminated shape without weakening section validation.
5. `backstitch/analysis_llm.py` and `backstitch/analysis_results.py`
   - Current ownership: `analyze` sees packets and enforces packet-local
     evidence. `summarize-analysis` sees only a report and result file.
   - Load-bearing boundary: only `analyze` can normalize evidence-deficient
     `ok` results. Summary loading cannot re-prove snippet locality.
6. `backstitch/config.py`, `backstitch/profiles.py`, and `backstitch/cli.py`
   - Current ownership: `code_roots` select one Python traversal. No
     `test_roots` contract exists; packet generation currently guesses from
     path names.
   - Load-bearing boundary: test roots classify already scanned paths and must
     not create a second traversal.

Comprehension checks before editing:

1. Where must `Invariant: [INV.RES.1]` be consumed so it cannot become a
   phantom ordinary backlink?
2. Which facts belong in parsed records, which in pure resolution, and which
   exist only after bounded snippets are built?
3. Why can `summarize-analysis` validate kind/hash shape but not packet-local
   evidence?
4. Which current `SectionKind` value already says `invariant`, and why must
   first-class invariant records stay separate?
5. Why does `Issue.__post_init__` force registry activation, locator support,
   and a firing test into the same slice that first emits each new code?

## Planned Data Flow

~~~text
Markdown sections ---> ParsedSpec.invariants ---------+
                                                       |
Python docstrings ---> ParsedPython.invariants --------+--> resolve()
                                                       |      |
Python test markers -> ParsedPython.binding_refs ------+      +--> invariants
                                                              +--> binds
                                                              +--> issues
                                                                    |
                                                                    v
                                                              deterministic report
                                                                    |
                                     +------------------------------+----------------+
                                     |                                               |
                                     v                                               v
                              section packets                                invariant packets
                                                                               statement
                                                                               target snippets
                                                                               binding snippets
                                                                               content hash
                                     |                                               |
                                     +------------------ analyze --------------------+
                                                                    |
                                                             validated results
                                                             grouped by kind
~~~

## Invariants And Constraints

- **One deterministic path.** Parsed declarations and binding references feed
  existing `resolve`. Packet generation consumes the report and cannot decide
  whether an invariant is known, unique, tested, or validly bound.
- **No model contamination.** `check` and `packets` remain structurally unable
  to import `llm`. Semantic results never alter deterministic diagnostics,
  policy, suppression, or exit status.
- **Separate records, shared ID namespace.** `InvariantDeclaration` is not a
  `SpecSection`. Existing `SpecSection.kind == "invariant"` continues to mean
  a legacy invariant-style Markdown bullet with no binding obligation.
  Invariant and section IDs still share one uniqueness namespace. Both use the
  exact unbracketed [SC-4] grammar
  `[A-Z][A-Za-z0-9.\-]*[0-9][A-Za-z0-9]*`; dotted dogfood IDs such as
  `INV.RES.1` are valid without adding a second grammar. Dots and hyphens may
  occur before the token's last digit; its suffix is alphanumeric only.
- **Reserved marker lines are single-purpose.** A marker prefix must be the
  first non-whitespace content on a physical docstring-content line, after an
  opening quote delimiter when content starts on the delimiter's line.
  `Invariant:`, `Invariant (draft):`, and `Tests-invariant:` lines are consumed
  by invariant grammar, valid or malformed, and never passed to generic Python
  reference extraction. `Some Invariant:` is prose. A separate `Spec:` line
  remains an ordinary backlink.
- **Physical-line and statement grammar.** Python markers exist only in one
  non-interpolated `string` docstring node. Escaped newlines and
  `concatenated_string` nodes do not create marker lines; a reserved prefix
  found only after evaluating either form emits `INVARIANT_MARKER_INVALID` at
  the physical opening line. A declaration statement starts with nonblank text
  after the closing `]`. It continues over immediately following nonblank
  physical content lines whose indentation column is strictly greater than the
  marker's (tabs expanded to 8-column stops); a reserved marker prefix always
  terminates it. Blank lines or the first line at/below marker indentation
  terminate it. Strip each statement segment and join segments with `\n`.
  Markdown uses the same nonblank text-after-ID rule, then includes immediately
  following nonblank plain-text source lines in the same top-level paragraph;
  a block boundary or another marker terminates it. Strip and `\n`-join.
- **Explicit test role with compatible overrides.** Packaged defaults use
  `test_roots = ["tests"]`. Test roots classify files already traversed under
  `code_roots`. Process each precedence layer as a pair: a layer that replaces
  `code_roots` and omits `test_roots` resets test roots to empty; a layer that
  supplies `test_roots` replaces them and otherwise retains the effective code
  roots. After all config and CLI layers, validate every nonempty effective test
  root against the final effective code roots. `with_overrides` uses the same
  algorithm. This preserves
  production-only `--code-root pkg` as a valid invocation, not a promise of a
  clean report: once production files declare required invariants, a scan that
  deliberately omits all tests correctly emits `INVARIANT_UNTESTED`.
- **Definition-bounded binding.** A valid bind points to a concrete `test_*`
  function or async function/method under an effective test root. A class
  marker expands only to directly defined `test_*` methods in that class body,
  not inherited methods, nested-class methods, or cross-file descendants. A
  comment marker attaches only when it is the final comment line immediately
  before a definition or its first decorator, at the same indentation; blank
  lines, other comments, or statements break attachment, while the contiguous
  decorator stack belongs to the definition. Module markers, helpers, comments
  inside bodies, comments attached elsewhere, and markers outside test roots do
  not bind. A class marker that expands to zero direct `test_*` methods emits
  `INVARIANT_BINDING_NOT_TEST` and creates no binding references or binds.
  `test_symbol` is the parser's existing source-qualified owner name: a free
  function uses `test_name`; a method uses `Class.test_name` with any lexical
  outer qualifiers; sync and async definitions use the same form. Class
  expansion and a marker attached directly to the same method therefore share
  one bind key.
- **No guessed/cascading edges.** Duplicate or section-colliding invariant IDs
  emit one root `INVARIANT_DUPLICATE` finding, no binds, no
  `INVARIANT_UNKNOWN` for references to that ambiguous ID, and no
  `INVARIANT_UNTESTED` cascade for its declarations. Locate the root finding at
  the smallest `(path, line)` among every colliding declaration and section,
  using Backstitch's canonical repository-relative POSIX path and normal Python
  string/tuple order.
- **Normalized report relations.** Add top-level `invariants` and `binds`.
  `summary.invariants` equals `len(report.invariants)`, including duplicate
  declaration records. Existing `edges` remain section mapping/backlink
  relations. Bind rows are unique by `(invariant_id, test_path, test_symbol)`;
  when multiple markers produce the same key, retain the smallest marker line.
  Add optional `Issue.invariant_id`. Invariant diagnostics set `section_id` to
  null even for spec declarations and set `invariant_id` when a valid ID was
  parsed. Marker-invalid findings without a parseable ID leave both IDs null
  and rely on mandatory `path` plus physical `line`, with the syntactic owner
  in `symbol` when one exists. Ordinary section/mapping diagnostics set
  `invariant_id` to null. The two ID locators are mutually exclusive.
- **Diagnostic policy remains authoritative.** Packaged defaults make
  `INVARIANT_UNTESTED:required`, `INVARIANT_UNKNOWN`,
  `INVARIANT_DUPLICATE`, and `INVARIANT_MARKER_INVALID` errors;
  `INVARIANT_UNTESTED:draft` and `INVARIANT_BINDING_NOT_TEST` are warnings.
  Repository policy may change effective levels, including `off`. Suppression
  follows effective level and remains auditable.
- **Useful packet eligibility.** Emit an invariant packet only when at least
  one valid bind exists. A bound spec-declared invariant with no resolved
  target emits `targets: []` and a packet warning; the contract never claims
  an always-present triad.
- **Target construction is declaration-specific.** A code declaration targets
  only its declaring `(path, symbol)` and never consults mapping edges. A spec
  declaration targets unique resolved `mapping` edges for its enclosing
  section; backlink edges are not targets. A code declaration cannot be
  targetless at report time, though a file race during packet generation may
  yield an empty snippet plus warning. A spec declaration is targetless when
  it has zero resolved mapping edges and uses warning text containing
  `no target code resolved for spec-declared invariant`. The module owner uses
  the reserved symbol `<module>`, which cannot collide with a Python
  identifier; its target is the first 120 lines of the whole file's UTF-8
  replacement-decoded text read at packet generation, starting at line 1.
- **Evidence claims match proof.** The prompt asks for assertion lines.
  Results use the existing `evidence` array of `{path, line}` objects. A shown
  snippet's inclusive range is `start_line` through
  `start_line + len(snippet.splitlines()) - 1`; an empty snippet has no range.
  Deterministic validation proves only that invariant `ok` cites at least one
  line inside a shown binding-test range. Missing binding-test evidence
  normalizes to `weak_binding` during `analyze`, even if target-code evidence
  is present. V1 does not pretend to parse every Python assertion idiom.
  Zero evidence items are valid and evidence-deficient. Every present item's
  path must equal a shown item's path and its line must fall inside that item's
  range; one failure makes the whole result malformed. A test omitted by the
  eight-test cap has no range.
- **Trusted result metadata.** Packet ID, kind, and invariant content hash in
  emitted results come from the packet, never model authority. The model's
  packet ID must match; model-supplied kind/hash values are ignored. Serialize
  the canonical validated result, not the raw model dictionary.
- **Exact hash contract.** Hash the final ordered, bounded packet content after
  snippet truncation. The projection is exactly:
  `{"statement": str, "targets": [{"path": str, "symbol": str | null,
  "start_line": int, "snippet": str}], "binding_tests": [{"path": str,
  "symbol": str | null, "start_line": int, "snippet": str}]}`.
  Use `json.dumps(projection, sort_keys=True, separators=(",", ":"),
  ensure_ascii=True).encode("utf-8")` and lowercase
  `hashlib.sha256(...).hexdigest()`. Exclude IDs, tier, instructions, issues,
  warnings, and model output.
- **Exact packet bounds.** Reuse `MAX_SNIPPET_LINES = 120`; add
  `MAX_INVARIANT_TARGETS_PER_PACKET = 8` and
  `MAX_BINDING_TESTS_PER_PACKET = 8`. Sort targets by `(path, symbol or "",
  start_line)` and binding tests by the same tuple, retain
  the first eight, and add omission warnings for the rest. A snippet is the
  complete resolved definition/file slice capped to its first 120 lines, with
  no ellipsis inserted into `snippet`; truncation is recorded only in
  `packet_warnings`. Empty snippets are legal only with an explicit unreadable,
  missing-symbol, or file-race warning and participate in the hash as `""`.
- **Stable order.** Invariants sort by declaration path, line, and ID. Binds
  sort by invariant ID, test path, test start line, and symbol. For
  `--kind all`, all section packets appear first in their existing order,
  followed by invariant packets in invariant order. Concurrency cannot change
  result order.
- **No caching or helper expansion in v1.** The hash is for comparison only.
  Do not add storage, skip-if-unchanged, cache invalidation, or automatic
  inclusion of locally referenced test helpers.
- **No new parser/runtime dependency.** Reuse tree-sitter-python,
  markdown-it-py, hashlib, and json. No AST fallback or second Markdown parser.

## Rollback And Rollout

Rollout order mirrors the task DAG:

1. Complete and baseline the configurable-diagnostics prerequisite.
2. Review this plan and exact spec delta.
3. Apply the coordinated contract text while invariant spec status and index
   remain Proposed.
4. Add paired test-root configuration and classification.
5. Implement and independently review the deterministic invariant pass.
6. Add discriminated section/invariant packets and `--kind`.
7. Add invariant semantic result validation and summaries.
8. Dogfood Backstitch declarations and add black-box acceptance probes.
9. Close mappings/backlinks and docs, then activate the invariant spec and
   index in one final reconciliation slice.

Task 3 keeps the feature visibly Proposed while its text acts as the reviewed
implementation target. Its self-corpus gate proves only that the pre-invariant
scanner has no new graph errors/warnings. BSI codes first emit in Task 5; zero
untested self-corpus is required only after Task 8 dogfood. Task 3 cannot start
until Task 2 records the diagnostics baseline, and activation cannot occur
until Tasks 4 through 8 pass.

There is no persistence or data migration. Public short codes and artifact
shapes are the one-way doors. Reserve `BSI001` through `BSI005` once promoted;
never reuse them.

Compatibility rules:

- New report producers always emit `summary.invariants`, `invariants`, and
  `binds`. The report loader accepts the old shape only when all three are
  absent, normalizes to count zero and empty collections, and rejects partial
  mixed shapes.
- New packet/result producers always emit `kind`. Loaders accept old
  section-only packet/result shapes without `kind` only in these exact forms:
  a packet has none of `invariant_id`, `tier`, `statement`, `declaration`,
  `targets`, `binding_tests`, or `content_hash`, and
  `packet_id == f"{spec_path}#{section_id}"`; a result has no `content_hash` and
  its packet ID does not use the reserved `invariant::` prefix. Normalize
  either to `kind = section`. New invariant results require `content_hash`;
  section results must omit the key entirely, and presence with any value
  including null is malformed. Reject missing-kind invariant identities and
  every partial or mixed legacy/new shape.
- `packets --kind {section,invariant,all}` defaults to `section`, preserving
  no-flag packet population and order. `--kind all` is the explicit mixed
  stream.

Rollback reverts the feature as one coordinated unit. Remove report/packet
variants and Backstitch dogfood markers together, because the old parser would
otherwise treat marker IDs as ordinary references. If a release exposed BSI
short codes, leave them reserved. `--kind section` is the operational fallback
for semantic packet/model-volume trouble; it does not disable deterministic
invariant checks.

## Proposed Spec Delta

Promotion strategy: **A - coordinated Proposed text first, activation last.**

The contract-alignment slice applies this delta before code cites [INV-*], but
defers the status/index edits explicitly called out below. It does not add
[INV-*] implementation mappings. Implementation code also does not add [INV-*]
`Spec:` backlinks until final reconciliation adds mappings and reciprocal
backlinks together. This preserves the zero-warning gate without glob changes
or temporary suppressions.

| Spec file | Sections touched |
|-----------|------------------|
| `docs/specs/05-backstitch-invariants.md` | status, [INV-2] through [INV-10], Related Plans |
| `docs/specs/02-backstitch-core.md` | [SC-2] through [SC-7], [SC-10], [SC-11], [SC-13], [SC-15] |
| `docs/specs/03-backstitch-configuration.md` | [CFG-5], [CFG-6], [CFG-8], [CFG-9] |
| `docs/specs/04-backstitch-traceability-exclusions.md` | [EXC-6], [EXC-8], [EXC-9], [EXC-10] |
| `docs/specs/00-specs-index.md` | Recommended Starting Points |

Residual action checklist, excluding diagnostics-owned prerequisite text:

- `05`: replace [INV-2] through [INV-10] contracts and add this plan backlink;
  keep status Proposed until Task 9
- `02`: add status-aware invariant targets, test-root/marker/packet/report/
  semantic/validation/diagnostic contracts in the listed [SC-*] sections
- `03`: add only paired `test_roots` precedence, schema, failure, and test rules
- `04`: add only BSI required/draft policy, audit, verification, and docs rules
- `00` and engineering principles: expose Proposed work-in-progress status and
  distinguish durable plan citations from parsed declarations or bindings

### `docs/specs/05-backstitch-invariants.md`

In Task 3, retain `Status: Proposed`. In Task 9, after implementation and
dogfood gates pass, replace it with:

> Status: Active

Replace Related specs with the exact touched set: [SC-2] through [SC-7],
[SC-10], [SC-11], [SC-13], [SC-15], [CFG-5], [CFG-6], [CFG-8], [CFG-9],
[EXC-4], [EXC-5], [EXC-6], [EXC-8], [EXC-9], and [EXC-10].

Insert at the end of [INV-2]:

> First-class invariant declarations are distinct from spec sections. The
> existing report value `SpecSection.kind = "invariant"` continues to describe
> invariant-style Markdown bullets. Those bullets remain ordinary sections and
> create no binding obligation. `Invariant:` markers produce records in the
> report's `invariants` collection. Both record types share one ID uniqueness
> namespace. Invariant IDs use the exact unbracketed [SC-4] grammar
> `[A-Z][A-Za-z0-9.\-]*[0-9][A-Za-z0-9]*`. They are not required to start with
> `INV`, but authors should prefer `INV.<DOMAIN>.<N>` to avoid section-code
> collisions. Dotted IDs such as `INV.RES.1` are valid. For example, a
> first-class declaration `[INV-3]` in this file is invalid because section
> `[INV-3]` already exists.

Replace the marker/binding rules in [INV-3] with:

> Python invariant prefixes are reserved grammar when the prefix is the first
> non-whitespace content on a physical docstring-content line (after the opening
> quote delimiter when content shares that line). Recognize `Invariant:`,
> `Invariant (draft):`, and `Tests-invariant:` before generic bracket
> extraction. Consume a recognized marker, its declaration continuation, and a
> malformed line beginning with a reserved prefix; none emits an ordinary
> `CodeRef`. A separate `Spec:` line remains an asserted backlink.
>
> A Python marker must begin on a physical source line in one
> non-interpolated string-literal docstring. Escaped newlines and implicitly
> concatenated docstrings do not create marker lines. A reserved prefix found
> only after evaluating either form emits `INVARIANT_MARKER_INVALID` at the
> physical docstring opening line and creates no record.
>
> A Python declaration statement starts with nonblank text after its closing
> `]`. It continues over immediately following nonblank physical content lines
> whose indentation column is strictly greater than the marker's, with tabs
> expanded to 8-column stops. A blank line, a reserved marker prefix, or the
> first physical content line at or below marker indentation terminates it.
> Strip each statement segment and join segments with `\n`. A Markdown
> declaration uses the same nonblank text-after-ID rule and includes immediately
> following nonblank plain-text source lines in the same top-level paragraph;
> another marker or any Markdown block boundary terminates it. Strip and
> `\n`-join those segments.
>
> `Invariant:` and `Invariant (draft):` declare only in module, class,
> function, or method docstrings. A declaration in a comment, a Markdown
> declaration outside an ID-bearing section, or a missing or invalid ID or
> statement emits `INVARIANT_MARKER_INVALID` and creates no record. A malformed
> `Tests-invariant:` ID list also emits `INVARIANT_MARKER_INVALID` and creates
> no binding reference. Markdown declarations are recognized only in top-level paragraph
> tokens in an ID-bearing section body. Fences, indented code, lists,
> blockquotes, HTML blocks, and examples are silent structural non-matches even
> when their text resembles a reserved marker; they do not emit marker-invalid
> findings.
>
> A reserved prefix at the start of a top-level Markdown paragraph is parsed
> as marker syntax and emits `INVARIANT_MARKER_INVALID` when its ID or statement
> is invalid. A mid-paragraph mention is ordinary prose and emits neither a
> record nor a marker diagnostic.
>
> `test_roots` classify Python paths already scanned through `code_roots`. A
> test definition is a function, async function, or method whose leaf name
> starts `test_`. A marker in its docstring binds it. A marker in a class
> docstring, or an attached comment on a class, expands only to directly defined
> `test_*` methods in that class body; inherited, nested-class, and cross-file
> methods are excluded. A comment marker attaches only when it is the final
> comment line immediately before the definition or its first decorator, at the
> same indentation. Blank lines, other comments, and statements break
> attachment; a contiguous decorator stack belongs to the definition. An
> attached comment on a `test_*` function/method binds that definition.
> Module markers, helper markers, comments inside bodies, comments attached to
> non-definitions, and markers outside effective test roots emit
> `INVARIANT_BINDING_NOT_TEST` and create no bind. One binding marker may name
> comma-separated IDs and emits one reference per ID and concrete test. A class
> marker with zero direct `test_*` methods also emits
> `INVARIANT_BINDING_NOT_TEST` and creates no references or binds.
> `test_symbol` is the existing source-qualified parser owner name: free
> functions use `test_name`; methods use `Class.test_name` with lexical outer
> qualifiers; sync and async definitions have the same form. Class expansion
> and a direct marker on the same method therefore deduplicate to one bind.

Replace [INV-4]'s severity/suppression/report paragraphs with:

> `INVARIANT_UNTESTED` has `required` and `draft` contexts. Packaged defaults
> set required to error and draft to warning. `INVARIANT_UNKNOWN`,
> `INVARIANT_DUPLICATE`, and `INVARIANT_MARKER_INVALID` default to error;
> `INVARIANT_BINDING_NOT_TEST` defaults to warning. Under [SC-15], repository
> policy may change effective level without changing identity, context, or
> `default_severity`.
>
> Suppression follows effective policy. Under packaged defaults, required
> untested is not suppressible and draft untested is suppressible. A repository
> policy change also changes suppressibility according to
> `diagnostics.suppressible_levels`. Suppressed/off invariant findings remain
> auditable through `--show-suppressions`.
>
> A duplicate invariant ID, including collision with a spec section ID, emits
> one `INVARIANT_DUPLICATE` root finding. It emits no binds, no unknown cascade,
> and no untested cascade. The root finding uses the smallest `(path, line)`
> among every colliding invariant declaration and section, comparing canonical
> repository-relative POSIX paths with normal Python string/tuple order.
> Binding references to the duplicated ID are intentionally discarded; the one
> duplicate root finding is their only diagnostic in v1.
>
> Reports add normalized `invariants` and `binds` collections plus
> `summary.invariants = len(invariants)`; duplicate declarations remain visible
> records and count individually. Existing `edges` remain mapping/backlink
> relations. Binds are unique by invariant ID, test path, and test symbol;
> duplicate markers retain the smallest marker line. `Issue` adds optional
> `invariant_id`. Invariant diagnostics always leave `section_id` null and set
> `invariant_id` when parsing produced a valid ID. A marker-invalid issue with
> no parseable ID leaves both ID locators null and uses mandatory path/physical
> line plus the syntactic owner in `symbol` when available. Non-invariant
> diagnostics leave `invariant_id` null.

Replace [INV-5] with:

> `backstitch packets` emits discriminated section/invariant records.
> `--kind {section,invariant,all}` defaults to `section`. `all` emits existing
> section order first, then invariant order. Filtering occurs after the full
> deterministic report, so diagnostics and exit status remain whole-repository.
>
> New packets always carry `kind`. Loaders normalize the legacy section shape
> without kind. An invariant packet exists only for an invariant with a valid
> bind and contains `packet_id = "invariant::<ID>"`, kind, ID, tier, statement,
> declaration locator, bounded `targets`, bounded `binding_tests`, relevant
> issues, `packet_warnings`, instructions, and `content_hash`. A bound
> spec-declared invariant without a resolved target has `targets: []` plus a
> warning. An untested invariant has no semantic packet.
> Every named envelope key is required; array-valued fields may be empty but
> may not be omitted.
>
> Packet `issues` are exactly report issues whose `invariant_id` equals the
> packet invariant ID, ordered by path, nullable line (null first), canonical
> code, and message.
>
> The invariant-only keys are `invariant_id`, `tier`, `statement`,
> `declaration`, `targets`, `binding_tests`, and `content_hash`. `declaration`
> contains `kind`, `path`, `line`, nullable `symbol`, and nullable `section_id`;
> exactly one of the two owner locators is non-null.
>
> For a code declaration, `targets` contains only the declaring path/symbol and
> never consults mappings. A module declaration uses the reserved symbol
> `<module>`, which cannot collide with a Python identifier, `start_line = 1`,
> and the first 120 lines of the whole file's UTF-8 replacement-decoded text
> read at packet generation. For a spec declaration,
> `targets` contains unique
> resolved mapping edges of the enclosing section; backlinks are excluded. A
> spec declaration with zero mapping targets uses `targets: []` and a warning
> containing `no target code resolved for spec-declared invariant`.
>
> Targets and binding tests both sort by path, nullable symbol (null as empty
> string), and start line. Retain at most
> eight targets and eight binding tests. Each snippet is capped to its first 120
> lines with no inserted ellipsis; omission/truncation is represented only in
> `packet_warnings`. Empty snippets require an explicit unreadable,
> missing-symbol, or file-race warning.
>
> The prompt asks: "Describe a concrete target-code change that violates this
> invariant while every shown test still passes. If none exists, cite the
> specific assertion lines in shown binding-test snippets that would fail."
>
> Invariant packets allow `ok`, `weak_binding`, `confirmed_mismatch`,
> `probable_mismatch`, and `ambiguous`. Section packets retain `ok`,
> `confirmed_mismatch`, `probable_mismatch`, `missing_trace`, and `ambiguous`.
> Results use the existing `evidence` array of `{path, line}` objects. A shown
> snippet's inclusive range is `start_line` through
> `start_line + len(snippet.splitlines()) - 1`; an empty snippet has no range.
> During `analyze`, invariant `ok` requires at least one evidence item in a
> shown `binding_tests` range; otherwise normalize it to `weak_binding`, even
> when target-code evidence is present. V1 does not syntactically recognize all
> assertion idioms. Zero evidence items are valid and evidence-deficient. Every
> present item's path must equal a shown item's path and its line must fall
> inside that item's range; one failure makes the whole result malformed. This
> includes a test omitted by the eight-test packet cap.
>
> The model must return the existing packet ID; a mismatch is malformed.
> Model-supplied kind/hash values are ignored. The canonical result copies
> packet ID, kind, and invariant hash from the packet. Hash the final
> ordered/truncated packet projection exactly
> as defined in [SC-6]. `summarize-analysis` validates identity, kind, row
> shape, and hash shape, but not snippet locality because it has no packet.
> It renders section and invariant advisory blocks separately. V1 adds no cache
> and no automatic test-helper expansion.
> `summarize-analysis` is not a trust boundary for evidence locality; only
> `analyze`, while holding the packet, can validate it.

Replace [INV-7]'s no-mapping case with:

> A bound spec invariant with no resolved implementation mapping still emits a
> packet with statement, bounded binding tests, `targets: []`, and an explicit
> warning. Its ordinary section-mapping finding remains.

Replace [INV-8] with:

> ## 8. Diagnostic Codes And Default Policy [INV-8]
>
> | Code | Short | Default | Context | Meaning |
> |------|-------|---------|---------|---------|
> | `INVARIANT_UNTESTED` | `BSI001` | error/warning | `required`, `draft` | A unique declaration has no valid binding test |
> | `INVARIANT_UNKNOWN` | `BSI002` | error | none | A valid test binding names no declaration |
> | `INVARIANT_DUPLICATE` | `BSI003` | error | none | An invariant ID is duplicate or collides with a section ID |
> | `INVARIANT_BINDING_NOT_TEST` | `BSI004` | warning | none | A well-formed binding marker is outside valid test-definition scope |
> | `INVARIANT_MARKER_INVALID` | `BSI005` | error | none | Reserved marker syntax/owner is invalid |
>
> Each code becomes implemented only in the same slice as its first emission
> and firing test. Short codes are never reused.

Replace [INV-9]'s assertion-laundering proof and add:

> - assertion-laundering fixture: fake-adapter tests prove the refutation prompt
>   and deterministic `ok` to `weak_binding` normalization when no evidence
>   falls inside a shown binding-test range
> - marker-isolation tests covering every documented marker position plus
>   adversarial CST fixtures and proving no ordinary `code_refs` or section
>   backlink edges for those cases
> - self-acceptance for new report/packet/result forms and all three documented
>   legacy artifact forms: deterministic report without all three invariant
>   additions; section packet without `kind`; section result without `kind`
> - both `INVARIANT_UNTESTED` contexts and every BSI code have firing coverage

Replace [INV-10]'s activation sequence with:

> Keep this specification Proposed while implementing through a dated,
> independently reviewed plan and coordinated delta to [SC-2] through [SC-7],
> [SC-10], [SC-11], [SC-13], [SC-15],
> [CFG-5], [CFG-6], [CFG-8], [CFG-9], [EXC-6], [EXC-8], [EXC-9], and
> [EXC-10]. Final reconciliation flips this file to Active and removes the
> index's Proposed note only after implementation and dogfood gates pass.
> Implement deterministic grammar/graph first, semantic
> packets/results second, then dogfood before completion. Plans and
> `docs/agent-context` are not parsed invariant sources: naming an invariant ID
> there is durable human/agent guidance, not a machine bind or declaration.

Replace Related Plans with this plan (implementing). Replace the existing
engineering-principles bullet so it asks plans to cite durable invariant IDs
but explicitly states those plan citations are not parsed bindings.

### `docs/specs/02-backstitch-core.md`

Replace [SC-2]'s Proposed gate with:

> [INV-*] remains Proposed until its implementation, dogfood, and acceptance
> gates pass. While Proposed, it is the reviewed implementation target; its BSI
> diagnostics and artifact additions are not yet required released behavior.
> On activation, declared invariants are first-class trace nodes: deterministic
> mode resolves declarations and test bindings, semantic mode reviews bounded
> binding packets, and semantic verdicts remain advisory.

Add `test_roots: [tests]` to both [SC-3] profile examples and add:

> Test roots classify paths already traversed through code roots. A layer that
> explicitly replaces `code_roots` and omits `test_roots` resets test roots to
> empty at that precedence. A layer that supplies `test_roots` replaces them and
> otherwise retains effective code roots. After all config and CLI layers,
> every nonempty test root must be equal to or nested under a final effective
> code root. `ProfileConfig.with_overrides` follows this same ordered algorithm.
> A lone `test_roots` override retains inherited code roots. Repeatable
> `--test-root` is available
> wherever `--code-root` is available. An empty effective test-root set does
> not disable invariant diagnostics: a partial production-only scan remains a
> valid invocation but reports required declarations as untested because their
> tests were intentionally omitted.

Add to [SC-4]:

> The exact unbracketed ID regular expression is
> `[A-Z][A-Za-z0-9.\-]*[0-9][A-Za-z0-9]*`. It requires an uppercase initial and
> at least one digit. Dots and hyphens may occur before the token's last digit;
> the suffix after that digit is alphanumeric only. Sections and invariants use
> this one grammar.
>
> Invariant marker prefixes are reserved before generic bracket-reference
> extraction. Their grammar and physical-source-line restriction are [INV-3].
> Marker IDs cannot also emit ordinary code references.

Add to [SC-5]:

~~~bash
backstitch packets --repo-root . --kind section --output packets.jsonl
backstitch packets --repo-root . --kind invariant --output invariants.jsonl
backstitch packets --repo-root . --kind all --output all-packets.jsonl
~~~

> `--kind` defaults to `section`. Filtering affects packet output only, not the
> deterministic report, policy, or exit status.
> For one corpus and policy, `section`, `invariant`, and `all` have the same
> exit code: `1` when any rendered issue has a severity in effective
> `diagnostics.fail_on`, otherwise `0` after successful output.

Add to [SC-6]:

> New deterministic reports require `summary.invariants`, `invariants`, and
> `binds`. Invariant records contain `invariant_id`, `statement`, `tier`,
> `declaration_kind` (`code` or `spec`), `path`, `line`, nullable
> `owner_symbol`, and nullable `section_id`; exactly one owner locator is
> non-null. Code owner symbols use the parser's source-qualified name; module
> declarations use the reserved `<module>` sentinel.
> `summary.invariants` equals the invariant-record count, including duplicates.
> Bind records contain `invariant_id`, `test_path`, `test_symbol`,
> `marker_line`, `start_line`, and `end_line`. Test symbols use the same
> source-qualified parser name for sync and async definitions; binds are unique
> by invariant ID, path,
> and symbol, retaining the smallest marker line. Existing `edges` remain
> mapping/backlink. Invariant issue records use `invariant_id` with null
> `section_id`. Marker-invalid issues with no parseable ID leave both ID fields
> null and use path/physical line plus an available syntactic owner; all other
> issues use null `invariant_id`. A duplicate root issue uses the smallest
> `(path, line)` across its colliding declarations and sections, using canonical
> repository-relative POSIX paths and normal Python string/tuple order.
>
> The report loader accepts the legacy shape only when all three invariant
> additions are absent and normalizes to zero/empty. Partial shapes are
> malformed. Producers always emit the new shape.
>
> Packets/results are closed unions on `kind`. Producers always emit kind. The
> only accepted legacy artifacts are: (1) a deterministic report with all of
> `summary.invariants`, `invariants`, and `binds` absent, normalized to
> zero/empty; (2) an exact legacy section packet with no `kind`, no
> invariant-only fields (`invariant_id`, `tier`, `statement`, `declaration`,
> `targets`, `binding_tests`, or `content_hash`), and
> `packet_id = spec_path#section_id`, normalized to
> `kind = section`; and (3) an exact legacy section result with no `kind`, no
> `content_hash`, and a packet ID other than the reserved `invariant::` prefix,
> normalized to `kind = section`. Any partial new shape, missing-kind invariant
> identity, or mixed legacy/new fields is malformed. An invariant result
> requires `content_hash`; section results must omit the key entirely, and
> presence with any value including null is malformed. Invariant result hashes
> are 64 lowercase hexadecimal characters.
>
> Invariant `content_hash` is lowercase SHA-256 of the final, bounded packet
> content after ordering/truncation. The exact projection has `statement` plus
> ordered `targets` and `binding_tests` items containing only `path`, nullable
> `symbol`, `start_line`, and `snippet`. Serialize with
> `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True)` as
> UTF-8 before hashing. Exclude all other fields.
>
> Invariant packets reuse `MAX_SNIPPET_LINES = 120`, add
> `MAX_INVARIANT_TARGETS_PER_PACKET = 8`, and add
> `MAX_BINDING_TESTS_PER_PACKET = 8`. Target and binding-test order are both
> path, nullable symbol, start line. Keep the first eight of each. Snippets keep the
> first 120 lines with no ellipsis; warnings alone record truncation/omission.
> Code declarations target only their declaring path/symbol; module declarations
> use symbol `<module>`, `start_line = 1`, and the first 120 lines of the whole
> file's UTF-8 replacement-decoded text read at packet generation. Spec declarations
> target unique enclosing-section mapping edges and never backlinks.

Add to [SC-7]:

> Classification vocabulary is closed by kind. Results use the existing
> `evidence` array of `{path, line}` objects. A shown snippet's inclusive range
> is `start_line` through `start_line + len(snippet.splitlines()) - 1`; an empty
> snippet has no range. For invariant packets, `analyze` normalizes `ok` to
> `weak_binding` unless at least one evidence item falls in a shown binding-test
> range, even when target-code evidence is present. Zero evidence items are
> valid and evidence-deficient. Every present item's path must equal a shown
> item's path and its line must fall inside that item's range; one failure makes
> the result malformed. An omitted capped test has no shown range. Packet ID,
> kind, and invariant `content_hash` come from packet metadata, not model output.
> The model's packet ID must match; model-supplied kind/hash values are ignored.
> Summary rendering separates kinds and does not
> re-prove locality. `summarize-analysis` is not a trust boundary for evidence
> locality; only `analyze`, while holding the packet, can validate it.

Add to [SC-10]:

> Invariant probes cover marker isolation, paired root overrides, every BSI
> firing case, report/packet/result self-acceptance and legacy normalization,
> `--kind` filtering and mixed-order byte stability, targetless packets,
> laundering normalization, hash stability, and three dogfood invariants.

Add the five [INV-8] rows to [SC-11], remove Proposed wording, and add their
registry rows/default rules to [SC-15]. `INVARIANT_UNTESTED` has allowed
contexts `required` and `draft`.

Add to [SC-13]:

> Total validation covers invariant/report relations and both packet/result
> variants. Binds reference an invariant in the same report and a concrete test
> definition. Invariant packet IDs equal `invariant::<ID>`. Accept only the
> three legacy forms enumerated in [SC-6] and apply its exact normalization;
> reject every partial or mixed legacy/new shape.

### `docs/specs/03-backstitch-configuration.md`

Add to [CFG-5], [CFG-6], [CFG-8], and [CFG-9]:

> | `test_roots` | array of strings | Test-role classifiers within effective code roots; CLI `--test-root` |
>
> Test roots use normal path expansion. A configuration layer that explicitly
> replaces `code_roots` and omits `test_roots` resets test roots to empty.
> A layer that supplies `test_roots` replaces them and otherwise retains
> effective code roots. After all configuration and CLI layers, each nonempty
> effective test root must be equal to or nested under a final effective code
> root; invalid containment is exit 2.
> The CLI applies the same rule: `--code-root` without `--test-root` resets test
> roots, while explicit `--test-root` values are validated after all overrides.
> `--test-root` without `--code-root` retains inherited code roots and validates
> against them. Empty effective test roots do not suppress invariant diagnostics.
> Tests cover packaged defaults, config/CLI pairing, production-only overrides,
> containment failure, and a custom path not named `tests`.

### `docs/specs/04-backstitch-traceability-exclusions.md`

[EXC-4] and [EXC-5] remain Related Specs because their structural marker and
next-statement scope rules are reused by [INV-3]; this plan does not change
their text. The invariant-specific behavior is added to the sections below.

Add to [EXC-6], [EXC-8], [EXC-9], and [EXC-10]:

> Invariant diagnostics use normal canonical/short-code policy and the audit
> stream. Under packaged defaults, required untested is error-level and not
> suppressible; draft untested is warning-level and suppressible. Repository
> effective policy controls suppressibility, and `off` remains auditable.
> Tests prove both contexts and an explicit policy override.

### `docs/specs/00-specs-index.md`

In Task 3, retain the Proposed annotation and allow the explanatory wording
`implementation in progress under its dated plan`. In Task 9, replace the
fifth entry with `05-backstitch-invariants.md` and no Proposed annotation.

## Tasks

1. **Independent plan/spec review before implementation.**
   - Read this plan/delta, touched specs, configurable-diagnostics state, and
     parser/resolver/packet/result contracts.
   - Review for contradictions, impossible validation, compatibility traps,
     wrong ownership, weak probes, and zero-warning slice failures.
   - Done: every finding is incorporated or answered under Independent Review
     Incorporation.

2. **Finish the diagnostic prerequisite and refresh baseline.**
   - Inspect, do not overwrite, files owned by the 2026-07-08 diagnostics plan.
   - Run its final gates; record commit or exact worktree baseline here.
   - Stop if registry/policy/artifact behavior differs from this plan; update
     and re-review before continuing.

3. **Proposed contract-alignment slice.**
   - Touch specs 00, 02, 03, 04, 05 and this plan.
   - Apply the Proposed Spec Delta atomically except the explicitly deferred
     status and index edits; add Related Plans backlinks.
   - Do not add [INV-*] implementation mappings or code backlinks yet.
   - Verify the existing scanner graph only: unmapped [INV-*] infos are
     acceptable; errors/warnings are not. BSI behavior does not exist yet.
   - Keep the invariant spec and index visibly Proposed until final
     reconciliation; the index may say implementation is in progress under
     this dated plan.
   - Done: aligned Proposed cross-spec contracts and a clean text baseline for
     the implementation slices that immediately follow.

4. **Add explicit test-root configuration with compatibility semantics.**
   - Touch `defaults.toml`, `config.py`, `profiles.py`, `settings.py`,
     `cli.py`, `analysis_packets.py`, and config/CLI/packet tests.
   - Add profile/config/show/CLI fields, paired reset semantics, containment
     validation, and root-based classification. Remove `_is_test_path` guessing.
   - TDD custom root, production-only code-root override, lone test-root
     override, invalid containment, config and CLI precedence, and
     `with_overrides` behavior.
   - Stop if test roots begin a second scan path.
   - Done: current `--code-root pkg` invocations remain valid, without a promise
     of a clean invariant report after declarations exist; custom and inherited
     roots classify through the real settings/CLI path.

5. **Implement the complete deterministic invariant pass atomically.**
   - Touch `models.py`, `code_parser.py`, `python_refs.py`,
     `markdown_specs.py`, `resolver.py`, `defaults.toml`,
     `diagnostics.py` as needed, `reporting.py`, `artifact_contracts.py`,
     parser/resolver/diagnostic/report/golden tests, and issue-code coverage.
   - Add `InvariantDeclaration`, parsed binding references, report binds,
     `Issue.invariant_id`, report collections/counts, stable sort, and legacy
     report normalization.
   - Register BSI001-BSI005, locator support, first emission, and each firing
     test in this same slice. Cover both untested contexts.
   - Parse markers before generic references. Use tree-sitter definition spans
     and markdown-it top-level paragraphs. Enforce physical-line restriction.
   - Resolve shared uniqueness, valid/unknown/untested bindings, no-cascade
     duplicates, and declaration owner locators. Report records do not
     materialize packet targets; Task 6 derives spec targets from mapping edges.
   - Deduplicate binds by `(invariant_id, test_path, test_symbol)`, retaining
     the smallest marker line. Count every declaration row, including duplicate
     declarations, in `summary.invariants`. Keep section and invariant issue
     locators mutually exclusive.
   - Update text/JSON rendering, total validation, and the golden via its
     documented regeneration command; hand-review every delta.
   - Stop if resolution consults snippets, CLI state, model code, or a second
     severity source.
   - Review three coherent checkpoints within the slice before proceeding:
     parser grammar and record shapes; diagnostics/locators with every firing
     test; resolver/report/legacy normalization with the reviewed golden.
   - Run an independent whole-slice deterministic-pass review after all three
     checkpoints pass.
   - Done: all BSI codes fire, valid fixture emits one invariant/bind, marker
     IDs in every documented marker position and adversarial CST fixture do not
     leak into ordinary references, report self-accepts, no `llm` import.

6. **Add discriminated packet generation and `--kind`.**
   - Touch `analysis_packets.py`, `artifact_contracts.py`, `cli.py`, add
     `prompts/invariant_binding_analysis.md`, and packet/artifact/CLI tests.
   - Add `kind` to new section packets, invariant packets, bounded target/test
     snippets, targetless warnings, eligibility, exact post-truncation hash,
     legacy packet normalization, and explicit mixed ordering.
   - Build code-declaration targets from only the declaring code symbol. Use
     reserved symbol `<module>`, `start_line = 1`, and the first 120 lines of
     the whole scanned file for module declarations. Build
     spec-declaration targets from unique resolved mapping edges. Sort targets
     and tests by the specified total orders, keep the first eight of each, and
     keep the first 120 lines of each snippet without an ellipsis. Emit explicit
     warnings for omitted or empty content before hashing the final packet.
   - Default no-flag behavior to `section`. Build full report before filtering.
   - Reuse bounded snippet helpers; no automatic helper expansion.
   - Done: all kinds pass subprocess/self-acceptance/hash/order tests and no
     model import occurs.

7. **Add invariant semantic validation and summaries.**
   - Touch `analysis_llm.py`, `analysis_results.py`,
     `artifact_contracts.py` and semantic/result tests.
   - Validate per-kind classifications; inject trusted packet metadata;
     track binding-test ranges; normalize evidence-deficient `ok`; keep
     out-of-range evidence malformed; serialize canonical validated rows.
   - Preserve packet order, partial failure semantics, section behavior, and
     legacy report/result normalization.
   - Fake only the model adapter. Cover laundering, forged metadata, wrong-kind
     classification, valid evidence, malformed output, and concurrency order.
   - Run an independent trust-boundary review.
   - Done: both result variants self-accept and summaries separate kinds.

8. **Dogfood and add black-box acceptance probes.**
   - Add required declarations:
     - `[INV.RES.1]` identical resolver inputs produce byte-stable output
     - `[INV.RES.2]` ambiguity is reported and never guessed into an edge
     - `[INV.CLI.1]` deterministic commands never import `llm`
   - Add bindings only to existing concrete tests that enforce each statement;
     strengthen tests instead of weakening statements.
   - Add `tests/acceptance/test_probe_invariants.py` and fixtures for marker
     isolation, roots, all BSI codes, self-acceptance/legacy forms, kinds/order,
     targetless warning, hash, and zero untested dogfood.
   - Add a partial-scan probe: `--code-root pkg` remains a valid invocation but
     exits 1 with BSI001 for omitted test roots after dogfood declarations are
     active. A lone `--test-root` retains inherited code roots and can resolve
     the dogfood bindings.
   - Use shipped CLI and real parser/resolver/settings/artifacts. No core mocks.
   - Done: exactly three initial dogfood declarations, valid binds, zero
     `INVARIANT_UNTESTED`.

9. **Documentation, traceability, final review, and completion state.**
   - Add [INV-*] mappings and reciprocal module/test backlinks together. After
     all Task 8 gates pass, flip the invariant spec and index from Proposed to
     Active in the same reconciliation change.
   - Update implementation docs, repository map/index as needed, engineering
     principles (human/agent citation boundary), README, this plan's baseline,
     deviations, status, and evidence. Add a lesson only if durable.
   - Run final independent review against promoted specs and complete diff.
   - Reproduce or answer every finding and rerun affected gates.
   - Completion requires the requested landing state to be committed and
     verified by `git log`. If the user requests uncommitted review, report it
     as uncommitted rather than calling it complete.

## Testing Plan

Use red-green TDD. Keep real tree-sitter, markdown-it, temporary repositories,
TOML/settings, resolver, diagnostic policy, suppression, packet generation,
artifact loaders, rendering, and CLI subprocesses. Fake only external model
calls.

Required coverage:

- `test_code_parser.py`, `test_python_refs.py`, `test_markdown_specs.py`:
  first-non-whitespace matching after the opening delimiter, exact positive and
  negative indentation boundaries, continuation start/termination and newline
  joining, direct sync/async function and class-method scope, decorator/comment
  attachment with intervening blank/comment/statement breakers,
  source-qualified test symbols, empty class expansion, module owner `<module>`,
  invalid/concatenated/escaped forms, silent Markdown block non-matches, and no
  ordinary-reference leakage from documented marker positions or adversarial
  CST fixtures
- `test_resolver.py`, `test_diagnostics.py`,
  `test_issue_code_coverage.py`: normalized records, shared namespace,
  no-cascade duplicate, a binding to a duplicate ID producing neither a bind
  nor `INVARIANT_UNKNOWN`, directly-defined class-body boundaries, bind
  deduplication with smallest marker line, deterministic duplicate root locus,
  marker-invalid path/line with no parsed ID, every BSI firing case, both
  contexts, and policy/suppression
- `test_reporting.py`, `test_artifact_contracts.py`,
  `test_behavior_freeze.py`: declaration-row summary cardinality, mutually
  exclusive section/invariant issue locators, fields/relations, complete legacy
  three-form normalization, every partial report-key combination, missing-kind
  `invariant::` rejection, legacy result rejection when `content_hash` is
  present, other partial/mixed rejection, producer self-acceptance, and reviewed
  golden
- `test_analysis_packets.py`: code-versus-spec target decision table, stable
  target/test ordering, eight-entry caps, 120-line snippet caps without
  ellipses, explicit omission/empty warnings, targetless spec case, eligibility,
  `<module>` whole-file target, source-qualified-symbol dedupe, invariant issue
  selection/order, exact post-bound hash, `--kind` default/filter, and identical
  policy-driven exit status under BSI001 for `section`, `invariant`, and `all`,
  plus mixed byte order
- `test_analysis_llm.py`, `test_analysis_results.py`: per-kind vocabularies,
  trusted metadata, laundering, locality, malformed containment, ordering,
  omitted-capped-test rejection, separate summaries, legacy results
- `test_config.py`, `test_settings.py`, `test_cli_config.py`, `test_cli.py`:
  paired and lone test-root semantics, containment, custom root, production-only
  valid invocation, partial-scan invariant exit, and quarantine
- `tests/acceptance/test_probe_invariants.py`: black-box production path,
  including partial production-only BSI001 and inherited-code-root resolution

No test may mock marker extraction, structural parsers, `resolve`, settings,
diagnostic policy, packet generation, artifact validation, report serialization,
or CLI dispatch to prove this feature.

## Verification And Gates

Targeted:

~~~bash
uv run pytest tests/test_config.py tests/test_settings.py tests/test_cli_config.py tests/test_cli.py -q
uv run pytest tests/test_code_parser.py tests/test_python_refs.py tests/test_markdown_specs.py -q
uv run pytest tests/test_models.py tests/test_resolver.py tests/test_diagnostics.py tests/test_issue_code_coverage.py -q
uv run pytest tests/test_reporting.py tests/test_artifact_contracts.py tests/test_behavior_freeze.py -q
uv run pytest tests/test_analysis_packets.py tests/test_analysis_llm.py tests/test_analysis_results.py -q
uv run pytest tests/acceptance/test_probe_invariants.py -q
~~~

Golden update when intentional:

~~~bash
BACKSTITCH_UPDATE_GOLDEN=1 uv run pytest tests/test_behavior_freeze.py -q
uv run pytest tests/test_behavior_freeze.py -q
~~~

Final:

~~~bash
uv run pytest tests/acceptance -q
uv run pytest -q
uv run ruff check backstitch tests bin/release.py
uv run ruff format --check backstitch tests bin/release.py
uv run mypy backstitch bin/release.py tests
uv run backstitch check --repo-root . --show-suppressions
uv run backstitch packets --repo-root . --kind invariant --output /tmp/backstitch-invariant-packets.jsonl
uv run backstitch packets --repo-root . --kind section --output /tmp/backstitch-section-packets.jsonl
uv run backstitch packets --repo-root . --kind all --output /tmp/backstitch-all-packets.jsonl
~~~

Success:

- all commands exit 0
- self-corpus has zero errors and zero warnings
- suppressions/off findings are auditable
- every implemented code has a firing test
- new and legacy artifact forms validate as specified
- three dogfood invariants have valid binds and no untested finding
- deterministic commands keep `llm` absent from `sys.modules`
- no-flag/section packet order remains stable; mixed order is byte-pinned

Plan-authoring validation on 2026-07-09:

| Command | Result |
|---------|--------|
| `git diff --no-index --check /dev/null <plan>` | no whitespace diagnostics; exit 1 is expected because the new file differs from `/dev/null` |
| `UV_CACHE_DIR=/tmp/backstitch-uv-cache uv run backstitch check --repo-root . --show-suppressions` | exit 0; 0 errors, 0 warnings, 33 infos; suppressions auditable |

Implementation evidence on 2026-07-09:

| Slice | Evidence |
|-------|----------|
| Task 3 contract alignment | 33-path baseline `a151ff6ee6c146c790947e6f3c9e251890cb01ddcf9fd7727b1b94d29d83eeb4`; diff check and self-corpus passed; final narrow Grok challenge found no blockers and answered the confidence question yes |
| Task 4 test roots | red run failed 12 intended tests; 74 focused tests passed after implementation; full pytest passed with one expected live-LLM skip; Ruff, format, mypy, acceptance, config show, and self-corpus passed; Grok recheck returned PASS with no P1/P2 findings |
| Task 5 deterministic invariants | parser, resolver, BSI firing, report, legacy-normalization, locator, and golden tests pass; full pytest passed with one opt-in live-LLM skip; Ruff, format, mypy, and self-corpus passed with 0 errors, 0 warnings, 33 infos, and 158 auditable suppressions. Repeated self-scan exposed and fixed native `tree-sitter` point-access crashes; a 100-parse stress loop and regression test pass. Grok found one real cross-feature regression (ordinary docstring refs had changed from evaluated to physical text), which was fixed and pinned; root wiring/registry/legacy objections were review-packet omissions or contradicted explicit contracts. Defense-in-depth test-root validation and additional parser/artifact rejection cases were incorporated. |
| Task 6 packet union | 61 focused packet/artifact tests pass; full pytest passes with one opt-in live-LLM skip; Ruff, format, and mypy pass. Subprocess tests pin identical policy exit status for `section`, `invariant`, and `all`; generator tests pin target/test caps, ordering, deduplication, backlink exclusion, code-owner isolation, targetless warnings, module slicing, issue ordering, and exact post-bound hash. Loader tests pin explicit-null and missing-kind discrimination, malformed legacy IDs, invariant-only field rejection, exact identity, owner locators, hash recomputation, and unknown-field preservation. Tool-less Grok review required generator and loader packets because full-diff prompt offloading was incompatible with disabled tools. It exposed explicit-null `kind` normalization and unsafe legacy `packet_id.startswith`; both were fixed. Claims about nullable paths, nullable spec ownership, unvalidated report binds, and missing definitions were rejected against the report contract or identified as bounded-review omissions. |
| Task 7 semantic results | per-kind vocabulary, trusted metadata, laundering normalization, target/test locality, empty-range rejection, malformed containment, mixed concurrency order, result-union legacy/partial cases, report-derived identities, producer self-acceptance, and separate summary tests pass. Full pytest passes with one opt-in live-LLM skip; Ruff, format, mypy, and self-corpus pass with 0 errors, 0 warnings, 33 infos, and 158 auditable suppressions. Grok's trust-boundary review exposed an unexpected parse/canonicalization exception path outside per-packet containment and a null-rationale inconsistency; both were fixed and pinned. Its claims that result loading should re-prove snippet locality or normalize evidence paths were rejected against [SC-7]'s explicit ownership and exact-path contracts. The compact recheck found no P1 blockers and answered the exact confidence question `Yes`. |
| Task 8 dogfood and probes | committed profile pairs `code_roots` with `test_roots`; default self-scan emits exactly three required declarations and exact binds to the existing resolver, ambiguity, and CLI quarantine tests with zero invariant findings. The resolver stability test now compares rendered UTF-8 JSON bytes, not only dictionaries. Four new black-box probes cover default/partial/lone-root behavior, all BSI codes with exact counts and locators, marker isolation, kind/default/mixed byte order, targetless behavior, independent hash recomputation across packet invocations, new report/packet/result acceptance, and all three exact legacy forms. The full acceptance suite, full pytest (one opt-in live-LLM skip), Ruff, format, mypy, and self-corpus pass: 3 invariants, 3 binds, 0 errors, 0 warnings, 33 infos, and 160 auditable suppressions. Grok review found the byte-stability overclaim and several weak positive assertions; the real findings were fixed. Objections to exactly three initial IDs, packet exit parity, warning substring matching, and summarize hash recomputation contradicted the explicit Task 8, [INV-5], or [SC-6] contracts and were rejected. |
| Task 9 activation reconciliation | invariant spec and index are Active; [SC-2]/[SC-15], README, implementation rationale, repository map, role-root lesson, and status-runbook examples are aligned. Every [INV-1] through [INV-10] section has implementation mappings and reciprocal code/test backlinks. Activated self-scan passes with 58 sections, 128 mappings, 272 code refs, 3 invariants, 3 binds, 0 errors, 0 warnings, and no invariant mapping debt; every INV section has at least two resolved edges. Whole-diff review and executable gates passed; only the user-controlled commit gate remains. |
| Final verification and review | `git diff --check`, Ruff check, Ruff format check, mypy over `backstitch` and `tests`, full pytest, all acceptance probes, default self-corpus with `--show-suppressions`, all three packet kinds, mixed byte concatenation, and report/packet self-loading pass. Final corpus: 58 sections, 128 mappings, 272 refs, 3 invariants, 3 binds, 0 errors, 0 warnings, 23 infos, 159 suppressions, and no visible or suppressed invariant issue. Packet corpus: 45 section, 3 invariant, 48 mixed. A repository-reading Grok attempt exhausted its tool-turn budget and produced no verdict. The compact integration review initially raised three blockers whose governing clauses were omitted from its packet; one useful hardening was added to forbid suppressed invariant findings. The correction review, supplied the omitted SC-6/CFG-6/INV-5 clauses and current gates, found no P1 blockers and answered the exact confidence question `Yes`. Work remains uncommitted by user policy, so the repository completion gate is intentionally not claimed. |
| 2026-07-10 strict-policy remediation | Repository `select = ["*"]`, `level = "error"` exposed 23 reciprocal mapping errors that had been info-level debt. Five over-broad rationale/verification citations were removed and 18 reference records were closed through 16 real owner mappings. Diff hygiene, Ruff, format, mypy, all 18 acceptance probes, and the full suite pass (only the opt-in live-LLM test skips). Fresh corpus: 58 sections, 144 mappings, 269 refs, 3 invariants, 3 binds, zero visible findings, 159 auditable existing suppressions, and no suppressed invariant issue. Packet corpus remains 45 section, 3 invariant, 48 mixed. |

Task 5 Grok review required smaller contract-owned packets because the CLI's
prompt offloading cannot work with review mode's required `--tools ""` safety
boundary. Parser, resolver, and artifact checkpoints were reviewed separately.
The review's claims were reproduced before disposition: findings that confused
`INVARIANT_UNKNOWN`/`INVARIANT_MARKER_INVALID` locators with declaration edges,
or treated intentionally preserved duplicate declarations as malformed, were
rejected against [INV-4] and [SC-6], not silently ignored.

Task 6 used the same bounded-review method. Generator review prompted explicit
cap, ordering, deduplication, mapping/backlink, code-owner, and issue-order
probes. Loader review found two real hostile-input cases: explicit `kind: null`
was being treated as an omitted legacy discriminator, and a non-string legacy
packet ID could reach `.startswith`. Both now reject as malformed artifacts;
legacy issue rows remain byte-shape preserving except for the required top-level
`kind = section` normalization.

## Independent Review Loop

Initial architecture reviewer: `019f491f-23fc-7f00-9987-813ecf061189`
("Russell"). It confirmed ownership and identified required decisions around
test roots, separate records, issue locator, policy, marker scope, packets,
result-validation ownership, legacy SectionKind, and non-parsed plan guidance.

Draft reviewer: `019f492c-4a29-7943-b320-c24988cc5549` ("Lorentz"). It
reviewed the full draft against current code/specs and initially returned "not
confident" with one P0 and six P1/P2 findings. All are incorporated below.

Different-family review was first attempted twice. Claude timed out after five
minutes without output. A direct Claude retry found no usable authentication.
Gemini refused the untrusted workspace. These failures produced no findings and
are recorded rather than presented as completed cross-family review.

Grok then reviewed the complete untracked plan through the repository `grok`
skill in challenge mode, with tools and subagents disabled. The review prompt
asked for errors, bad ideas, latent ambiguities, and unnecessary or performative
overengineering, and asked exactly: "If asked, could you implement this plan as
written confidently and correctly?" Its initial answer was "No" and identified
seven implementation blockers plus eleven advisories. Every item is disposed
below.

During Task 3 execution, a fresh bounded Grok challenge reviewed the current
plan delta, invariant spec, and coordinated cross-spec diff. It again answered
"No", with seven blockers and thirteen advisories. The valid findings exposed
stale wording left after the earlier plan review; their execution-time
dispositions are included below before the Task 3 closeout review.

Two attempts to rerun the complete enlarged plan produced no verdict: the Grok
CLI offloaded the prompt, then exhausted the challenge/consult turn caps trying
to reread or inspect it. A smaller tool-less post-incorporation packet containing
the normative rules, spec deltas, tasks, tests, and disposition table completed.
It again answered "No." Two claimed missing-text blockers were packet-boundary
artifacts; its remaining contract findings and useful advisories are disposed
below. A final compact, inline, tool-less correction-surface challenge then
completed. It found no blockers and answered the exact confidence question:
"Yes, with low residual risk." Its three optional precision edits are also
incorporated below.

Implementation reviews are still required after the deterministic slice, after
the semantic slice, and against the final diff. Prefer another family when
available. Reviewers must read promoted specs, this plan/deviation log,
implementation docs, schemas, diagnostics, probes, and dogfood markers.

## Independent Review Incorporation

| Finding | Disposition | Plan change |
|---------|-------------|-------------|
| Parser task emitted BSI004/BSI005 before registry and locator support. | Accepted. | Combined parser, registry, locator, graph, report, firing tests, and golden into one atomic deterministic slice. |
| Inherited `test_roots = tests` broke existing production-only code-root overrides. | Accepted. | Added paired reset semantics for config, CLI, and `with_overrides`; explicit pairs still validate containment. |
| Legacy packets/results were promised but old deterministic reports would fail first. | Accepted. | Added all-or-none legacy report normalization to zero/empty and partial-shape rejection. |
| Default `--kind all` broke no-flag packet population. | Accepted. | Default is `section`; mixed output requires explicit `all`. |
| Exact marker lines were undefined for escaped/concatenated docstrings. | Accepted. | Restricted markers to physical lines in one string node; evaluated-only prefixes are invalid at the opening line. |
| Hash omitted truncation stage and exact canonical projection/options. | Accepted. | Hash is over final bounded content with exact fields, JSON options, UTF-8, and SHA-256. |
| Mixed packet stream had no cross-kind total order. | Accepted. | Section packets first in existing order, then invariant packets in invariant order; byte-pinned. |
| Grok: "line beginning" did not define how indented docstring content or a same-line opener is matched. | Accepted. | A marker starts at the first non-whitespace content after the opening delimiter when present on that physical line; prose lookalikes remain non-markers, with positive and negative fixtures. |
| Grok: declaration continuation had no executable statement grammar. | Accepted. | Python and Markdown now have separate continuation start, indentation/paragraph, termination, stripping, and newline-join rules. |
| Grok: snippets were exact-hashed but had no size or truncation contract. | Accepted. | Targets and tests cap at eight; snippets cap at 120 lines without ellipses; omission/empty warnings are explicit and hashing occurs after all bounds. |
| Grok: target resolution did not distinguish code declarations, spec mappings, multiple edges, or targetless output. | Accepted. | Code targets only their declaring symbol; spec targets are unique resolved mapping edges; stable sort/dedup is explicit; targetless spec packets carry a required warning. |
| Grok: production-only code-root compatibility conflicted with required dogfood invariants. | Accepted. | The invocation remains configuration-valid, but after dogfood it intentionally exits 1 with BSI001 because tests were omitted. The acceptance probe pins that distinction. |
| Grok: next-statement comment attachment was undefined around indentation, decorators, blank lines, and other comments. | Accepted. | Comment markers must be the final same-indent comment immediately before the definition or its first decorator; intervening content breaks attachment and decorators belong to the definition. |
| Grok: promoting the spec to Active before implementation blurred normative status and release readiness. | Accepted. | Task 3 now keeps the spec/index Proposed; Task 9 flips both to Active only after implementation, dogfood, and acceptance gates pass. |
| Grok: Task 5 was too large for a useful review boundary. | Accepted. | The atomic dependency slice now has three mandatory review checkpoints: parser/records, diagnostics/locators/firing tests, and resolver/report/legacy golden, followed by a whole-slice review. |
| Grok: duplicate bindings had no report deduplication rule. | Accepted. | Bind rows deduplicate on invariant ID, test path, and test symbol, retaining the smallest marker line. |
| Grok: class binding scope did not cover nested, inherited, or async methods. | Accepted. | Class markers expand only to directly defined sync/async test methods; inherited, nested, and cross-file descendants are excluded. |
| Grok: `summary.invariants` had no duplicate-declaration cardinality. | Accepted. | It equals the declaration-row count, including duplicate declarations, and has a firing artifact test. |
| Grok: `Issue.section_id` and `Issue.invariant_id` could co-occur. | Accepted. | The ID locators are mutually exclusive; invariant diagnostics use `invariant_id` when parseable and otherwise path/line, while ordinary diagnostics leave `invariant_id` null. |
| Grok: EXC-4 and EXC-5 were named without a proposed delta. | Answered. | They remain unchanged Related Specs because INV-3 reuses their structural and next-statement rules; the plan now says that explicitly before the exclusion delta. |
| Grok: marker-looking Markdown in structural blocks was not classified as invalid or ignored. | Accepted. | Fences, lists, blockquotes, headings, tables, and other non-paragraph blocks are silent structural non-matches, with fixtures. |
| Grok: ID naming and collision guidance was weak. | Accepted. | `INV.<DOMAIN>.<N>` is recommended but not mandatory, and shared-namespace collision behavior cites INV-3. |
| Grok: "marker IDs never leak" claimed more than finite tests can prove. | Accepted. | The gate is limited to every documented marker position plus adversarial CST fixtures. |
| Grok: lone `--test-root` behavior was unspecified. | Accepted. | It retains inherited code roots and validates the explicit test roots against them. |
| Grok: the diagnostics prerequisite was still a real execution blocker. | Accepted. | Task 2 remains a mandatory stop gate: implementation cannot start until the current diagnostics work passes its final gates and matches the assumed contracts. |
| Grok rerun: compatibility prose and EXC delta were missing. | Rejected as review-packet artifacts. | Both texts were already complete in the plan at Rollback And Rollout and the EXC proposed delta; direct plan inspection confirmed the excerpt command had omitted their boundary lines. |
| Grok rerun: `test_symbol` was not deterministic for free, method, class-expanded, and async bindings. | Accepted. | It is now the existing source-qualified parser owner name, with exact free/method examples, lexical qualifiers, sync/async equivalence, and class/direct-marker dedupe behavior. |
| Grok rerun: "three legacy forms" was not an accept/normalize/reject matrix. | Accepted. | SC-6 enumerates legacy report, section packet, and section result identities, their normalization, and rejection of partial, mixed, or invariant missing-kind forms; SC-13 delegates to that exact matrix. |
| Grok rerun: Task 5 conflated report ownership with packet mapping targets. | Accepted. | Task 5 resolves only declaration owner locators. Task 6 alone derives code/spec packet targets, with spec mappings consumed there. |
| Grok rerun: marker-invalid issues without a parseable ID lacked a locator contract. | Accepted. | Such issues leave both ID locators null and require path/physical line plus available syntactic owner; tests pin that shape. |
| Grok rerun: test-root precedence wording diverged across the delta. | Accepted. | Every layer now applies one ordered paired-field algorithm followed by containment validation against final effective code roots. |
| Grok rerun: duplicate finding locus, module ownership, and empty class expansion were unspecified. | Accepted. | Duplicate roots use smallest `(path, line)`; module owners use reserved `<module>` and a file slice; empty class expansion emits BSI004 and no references/binds. |
| Grok rerun: capped evidence, Related Specs, cap naming, and asymmetric orders were avoidable hazards. | Accepted. | Omitted-test evidence is malformed; Related Specs equals the touched set; targets have a dedicated cap; targets/tests share one total order. |
| Grok final: legacy identity wording, class-scope test wording, and duplicate path ordering could be more explicit. | Accepted. | Compatibility rules now mirror SC-6's packet/result identities and rejection cases; tests say directly defined class-body scope; duplicate paths use canonical repository-relative POSIX form and Python tuple order. |
| Task 3 Grok P1: rollout summary ordered dogfood before packet/result work. | Accepted. | The rollout list now mirrors Tasks 1 through 9 exactly: roots, deterministic graph, packets, semantic results, dogfood, activation. |
| Task 3 Grok P1: raw `HEAD` diff mixed diagnostics-plan work with the invariant residual delta. | Answered and clarified. | Task 2's exact uncommitted manifest remains the prerequisite identity; the invariant-owned residual is only the enumerated Proposed Spec Delta applied on top. Raw `HEAD` diff is explicitly not the ownership boundary. |
| Task 3 Grok P1: dotted dogfood IDs relied on an unstated grammar. | Accepted. | [SC-4], [INV-2], plan constraints, and the delta quote the exact shared regex and state that `INV.RES.1` is valid. |
| Task 3 Grok P1: legacy result identity said only "no invariant hash." | Accepted. | The field is now exactly `content_hash`; invariant results require it, section results do not, and missing-kind legacy section results must omit it. |
| Task 3 Grok P1: Active [SC-2] claimed implemented behavior while [INV-*] remained Proposed. | Accepted. | [SC-2] is status-aware: Proposed text is the reviewed implementation target, and released invariant behavior becomes required only on activation. |
| Task 3 Grok P1: invariant `ok` locality lacked an evidence schema and range formula. | Accepted. | [SC-7], [INV-5], constraints, and delta now name `evidence[{path,line}]`, the inclusive snippet range, empty-range behavior, target-only evidence normalization, and malformed boundaries. |
| Task 3 Grok P1: declaration invalidity referred to a binding list. | Accepted. | Declaration ID/statement invalidity and malformed `Tests-invariant:` lists are now separate grammar rules. |
| Task 3 Grok P2: packet issues, Markdown mid-prose, duplicate binds, summary trust, and missing probes were implicit. | Accepted. | Added exact issue selection/order, mid-prose non-match behavior, one-root duplicate disposition, the summary trust-boundary statement, and explicit partial-shape, duplicate-bind, locator, and `--kind` exit probes. |
| Task 3 Grok P2: module owner `module` can collide with a real function. | Accepted. | Invariant module ownership now uses reserved `<module>` and a file slice; ordinary legacy code-reference ownership is unchanged. |
| Task 3 Grok P2: evidence beyond the 120-line cap should become weak rather than malformed. | Rejected. | The model never sees omitted lines. No shown binding evidence already normalizes `ok` to `weak_binding`; a fabricated out-of-range citation remains malformed. |
| Task 3 Grok P2: Task 5 should require internal commits. | Rejected. | Three coherent review checkpoints remain mandatory, but commits are controlled by the user and final landing workflow, not forced during an uncommitted review. |
| Task 3 Grok P2: index wording and CFG `6.3.x` were underspecified. | Accepted. | Task 3 explicitly allows the in-progress Proposed note; diagnostics is now stable subsection 6.11 without renumbering durable 6.4 through 6.10 references. |
| Task 3 Grok P2: invariant text repeated diagnostics ownership. | Answered. | The residual delta limits EXC additions to BSI required/draft policy and audit behavior, while canonical registry and policy remain owned by [SC-15] and the diagnostics baseline. |
| Task 3 closeout Grok: INV-9 said every result carried a hash. | Accepted. | INV-9 now requires `content_hash` only on invariant results and requires section results to omit it. |
| Task 3 closeout Grok: golden regeneration was missing. | Rejected as a bounded-review excerpt artifact. | Direct inspection confirmed both documented commands remain under Verification And Gates. |
| Task 3 closeout Grok: packet-only keys, evidence membership, trusted metadata, module slicing, and omit-versus-null needed precision. | Accepted. | The contracts now enumerate packet-only keys, require envelope fields, match evidence by path and line, ignore model kind/hash, define whole-file decoded module snippets, and reject `content_hash` presence on section results. |
| Task 3 final narrow Grok: Task 8, dogfood, and packet-filter prose appeared truncated. | Rejected as excerpt-boundary artifacts. | Direct inspection confirmed all three are complete in the plan/spec; the reviewer found no P1 and answered the exact confidence question "Yes." |

Post-incorporation conclusion: diagnostics and contract-alignment baselines are
complete. The final narrow Grok challenge found no blockers and said the plan
could be implemented confidently and correctly. The Task 4 implementation
boundary is open.

## Out Of Scope

- Discovery of undeclared invariants.
- Test generation, repair, or automatic spec edits.
- Mutation testing or calibration against mutations.
- Syntactic recognition of every Python assertion idiom.
- Runtime assertion instrumentation.
- Cross-repository invariants.
- Invariant declarations in plans.
- Model-driven deterministic findings or semantic CI failures.
- Caching, persistence, skip-if-unchanged, or helper expansion.
- New languages, parser plugins, editor/LSP support, or dependencies.
- Renaming public `SpecSection.kind == "invariant"`.

## Fresh-Eyes Checklist

- Are section invariant bullets, declarations, parsed refs, and resolved binds
  unambiguous?
- Is every marker position valid, explicitly invalid, or a structural non-match?
- Do the exact continuation and comment-attachment rules cover indentation,
  decorators, blank lines, comments, statements, and block boundaries?
- Do all documented marker positions and adversarial CST fixtures avoid
  ordinary code-reference leakage?
- Do code-root overrides preserve old behavior while explicit test roots remain
  validated, including lone test-root and partial production-only scans?
- Are direct class descendants, async methods, inherited/nested methods, and
  duplicate binds resolved exactly once under the stated scope?
- Can each report relation and artifact variant self-validate, including legacy
  normalization?
- Are declaration counts and section/invariant issue locators total and
  unambiguous?
- Is assertion evidence described no more strongly than the tool can prove?
- Are identity, default/effective level, suppression, and exit policy separate?
- Is targetless packet behavior valid without an imaginary triad?
- Are target construction, total ordering, entry caps, snippet caps, warnings,
  and post-bound hashing fully deterministic?
- Is no-flag section behavior compatible and mixed order total?
- Does each meaningful slice have a stop/review gate?
- Are mappings/backlinks delayed until reciprocity can remain clean?
- Is every public contract tied to firing or acceptance proof?

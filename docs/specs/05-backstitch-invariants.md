# Backstitch Invariant Traceability Specification

Status: Active

This spec makes declared invariants first-class nodes in the backstitch trace
graph. Deterministic mode checks that every declared invariant is cited by at
least one test; semantic mode judges whether the citing test actually *binds*
the invariant — whether the invariant could be violated while the test still
passes.

Related specs:

- `docs/specs/02-backstitch-core.md` [SC-2] through [SC-7], [SC-10], [SC-11],
  [SC-13], [SC-15]
- `docs/specs/03-backstitch-configuration.md` [CFG-5], [CFG-6], [CFG-8],
  [CFG-9]
- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-4], [EXC-5],
  [EXC-6], [EXC-8], [EXC-9], [EXC-10]
- `docs/specs/08-intent-coverage.md` [COV-3], [COV-8], [COV-9]

## 1. Purpose And Scope [INV-1]

Traceability answers "does a test cite this?"; invariant traceability answers
"would that test fail if this stopped being true?". The gap between those two
questions is where the most expensive class of deficiency lives: contracts
that are declared, cited, and unenforced.

The tool owns:

- an invariant declaration grammar for Markdown specs and code docstrings
- invariant binding references from tests
- deterministic invariant graph records and issue records
- bounded invariant-packet generation for semantic review
- semantic binding classifications, collected via the existing `analyze`
  pipeline

The tool does not own:

- discovery of undeclared invariants
- proof of correctness (a bound invariant is enforced, not proven)
- mutation testing (a complementary, execution-based answer to the same
  question; see [INV-6])
- generation or repair of tests

_Implementation mapping_:
- `backstitch/models.py`
- `backstitch/resolver.py`

## 2. Mental Model [INV-2]

The core trace graph gains one node type and one edge type:

`spec section <-> implementation owner <-> tests <-> plans`
becomes
`spec section <-> implementation owner (declares invariant) <- binds - test`

Important concepts:

- **Invariant declaration**: a stable-ID statement of something that must
  stay true, declared where it must hold — in the docstring of the module,
  class, or function that owns it.
- **Binding reference**: a test that cites an invariant ID, claiming to
  enforce it.
- **Binding assertion**: the specific assertion line(s) that would fail if
  the invariant were violated. A test can cite an invariant without
  containing a binding assertion; that is *assertion laundering*, and
  detecting it is the purpose of semantic binding analysis.
- **Weak binding**: the test exercises the relevant path but its assertions
  would not fail if the invariant broke.

Deterministic checks answer whether declared invariants have citing tests.
Semantic analysis answers whether the citations bind. Both operate on
declared knowledge only: this spec verifies stated intent and cannot
manufacture unknown unknowns — hostile-input and edge-case coverage remain
[SC-9]/[SC-10] territory.

Design and naming variation stays free; declared deficiency gets gated. An
implementation may declare any invariants it can defend, but once declared,
an invariant without a binding test is a reportable finding.

Declarations come from two directions on purpose. Code-side declarations let
an implementer state what their code guarantees. Spec-side declarations let
a *different* author — the spec writer, planner, or reviewer — impose an
invariant the implementation must bind. This closes the self-declaration
loophole: an implementer who simply omits the dangerous invariant does not
escape it if the spec declares it, because the binding obligation attaches
at declaration, wherever the declaration lives.

First-class invariant declarations are distinct from spec sections. The
existing report value `SpecSection.kind = "invariant"` continues to describe
invariant-style Markdown bullets. Those bullets remain ordinary sections and
create no binding obligation. `Invariant:` markers produce records in the
report's `invariants` collection. Both record types share one ID uniqueness
namespace. Invariant IDs use the existing [SC-4] ID grammar, whose exact
unbracketed regular expression is `[A-Z][A-Za-z0-9.\-]*[0-9][A-Za-z0-9]*`.
They are not required to start with `INV`, but authors should prefer
`INV.<DOMAIN>.<N>` to avoid section-code collisions. Dotted IDs such as
`INV.RES.1` are valid. For example, a first-class declaration `[INV-3]` in
this file is invalid because section `[INV-3]` already exists.

_Implementation mapping_:
- `backstitch/models.py`

## 3. Invariant Grammar [INV-3]

Declaration, in the docstring of the owning module, class, function, or
method, alongside existing `Spec:` backlink lines:

```python
"""Deterministic resolver.

Spec: docs/specs/02-backstitch-core.md [SC-4]
Invariant: [INV.RES.1] resolve() output is byte-identical across runs on
    identical inputs.
Invariant: [INV.RES.2] resolve() never guesses an edge; ambiguity is
    reported, not resolved.
"""
```

The same marker works in the body of a Markdown spec section:

```markdown
## Deterministic Trace Graph [SC-4]

Invariant: [INV.RES.1] resolve() output is byte-identical across runs on
identical inputs.
```

Python invariant prefixes are reserved grammar when the prefix is the first
non-whitespace content on a physical docstring-content line (after the opening
quote delimiter when content shares that line). Recognize `Invariant:`,
`Invariant (draft):`, and `Tests-invariant:` before generic bracket extraction.
Consume a recognized marker, its declaration continuation, and a malformed
line beginning with a reserved prefix; none emits an ordinary `CodeRef`. A
separate `Spec:` line remains an asserted backlink.

A Python marker must begin on a physical source line in one non-interpolated
string-literal docstring. Escaped newlines and implicitly concatenated
docstrings do not create marker lines. A reserved prefix found only after
evaluating either form emits `INVARIANT_MARKER_INVALID` at the physical
docstring opening line and creates no record.

A Python declaration statement starts with nonblank text after its closing
`]`. It continues over immediately following nonblank physical content lines
whose indentation column is strictly greater than the marker's, with tabs
expanded to 8-column stops. A blank line, a reserved marker prefix, or the
first physical content line at or below marker indentation terminates it.
Strip each statement segment and join segments with `\n`. A Markdown
declaration uses the same nonblank text-after-ID rule and includes immediately
following nonblank plain-text source lines in the same top-level paragraph;
another marker or any Markdown block boundary terminates it. Strip and
`\n`-join those segments.

`Invariant:` and `Invariant (draft):` declare only in module, class, function,
or method docstrings. A declaration in a comment, a Markdown declaration
outside an ID-bearing section, or a missing or invalid ID or statement emits
`INVARIANT_MARKER_INVALID` and creates no record. A malformed
`Tests-invariant:` ID list also emits `INVARIANT_MARKER_INVALID` and creates no
binding reference. Markdown
declarations are recognized only in top-level paragraph tokens in an
ID-bearing section body. Fences, indented code, lists, blockquotes, HTML blocks,
and examples are silent structural non-matches even when their text resembles
a reserved marker; they do not emit marker-invalid findings.

A reserved prefix at the start of a top-level Markdown paragraph is parsed as
marker syntax and emits `INVARIANT_MARKER_INVALID` when its ID or statement is
invalid. A mid-paragraph mention of `Invariant:` is ordinary prose and emits
neither an invariant record nor a marker diagnostic.

The `Invariant:` marker is the entire declaration grammar. There is no
`_Invariant mapping_:` block. A code declaration is owned by its docstring
scope; a spec declaration is owned by its enclosing section. Plans and
`docs/agent-context` may cite invariant IDs as durable guidance but are not
parsed declaration or binding sources.

Binding, in a test docstring or comment, using the existing reference
grammar with a dedicated marker:

```python
def test_resolver_output_is_stable() -> None:
    """Tests-invariant: [INV.RES.1]"""
```

`test_roots` classify Python paths already scanned through `code_roots`. A test
definition is a function, async function, or method whose leaf name starts
`test_`. A marker in its docstring binds it. A marker in a class docstring, or
an attached comment on a class, expands only to directly defined `test_*`
methods in that class body; inherited, nested-class, and cross-file methods are
excluded. A comment marker attaches only when it is the final comment line
immediately before the definition or its first decorator, at the same
indentation. Blank lines, other comments, and statements break attachment; a
contiguous decorator stack belongs to the definition. An attached comment on a
`test_*` function or method binds that definition.

Module markers, helper markers, comments inside bodies, comments attached to
non-definitions, and markers outside effective test roots emit
`INVARIANT_BINDING_NOT_TEST` and create no bind. One binding marker may name
comma-separated IDs and emits one reference per ID and concrete test. A class
marker with zero direct `test_*` methods also emits
`INVARIANT_BINDING_NOT_TEST` and creates no references or binds. `test_symbol`
is the existing source-qualified parser owner name: free functions use
`test_name`; methods use `Class.test_name` with lexical outer qualifiers; sync
and async definitions have the same form. Class expansion and a direct marker
on the same method therefore deduplicate to one bind.

_Implementation mapping_:
- `backstitch/markdown_specs.py`
- `backstitch/code_parser.py`
- `backstitch/python_refs.py`

## 4. Deterministic Checks [INV-4]

Deterministic mode extends the resolver graph with invariant records and
`binds` edges. No model calls ([SC-4] boundary rules apply unchanged).

Checks:

- every declared invariant has at least one binding reference from a test
  root (`INVARIANT_UNTESTED` otherwise)
- every binding reference resolves to a declared invariant
  (`INVARIANT_UNKNOWN` otherwise — the test asserted something false)
- invariant IDs are unique corpus-wide (`INVARIANT_DUPLICATE` otherwise)
- binding references outside test roots are reported
  (`INVARIANT_BINDING_NOT_TEST`) and do not satisfy the invariant

`INVARIANT_UNTESTED` has `required` and `draft` contexts. Packaged defaults set
required to error and draft to warning. `INVARIANT_UNKNOWN`,
`INVARIANT_DUPLICATE`, and `INVARIANT_MARKER_INVALID` default to error;
`INVARIANT_BINDING_NOT_TEST` defaults to warning. Under [SC-15], repository
policy may change effective level without changing identity, context, or
`default_severity`.

Suppression follows effective policy. Under packaged defaults, required
untested is not suppressible and draft untested is suppressible. A repository
policy change also changes suppressibility according to
`diagnostics.suppressible_levels`. Suppressed or off invariant findings remain
auditable through `--show-suppressions`.

A duplicate invariant ID, including collision with a spec section ID, emits
one `INVARIANT_DUPLICATE` root finding. It emits no binds, no unknown cascade,
and no untested cascade. The root finding uses the smallest `(path, line)`
among every colliding invariant declaration and section, comparing canonical
repository-relative POSIX paths with normal Python string and tuple order.
Binding references to the duplicated ID are intentionally discarded; the one
duplicate root finding is their only diagnostic in v1.

Reports add normalized `invariants` and `binds` collections plus
`summary.invariants = len(invariants)`; duplicate declarations remain visible
records and count individually. Existing `edges` remain mapping and backlink
relations. Binds are unique by invariant ID, test path, and test symbol;
duplicate markers retain the smallest marker line. `Issue` adds optional
`invariant_id`. Invariant diagnostics always leave `section_id` null and set
`invariant_id` when parsing produced a valid ID. A marker-invalid issue with no
parseable ID leaves both ID locators null and uses mandatory path and physical
line plus the syntactic owner in `symbol` when available. Non-invariant
diagnostics leave `invariant_id` null.

_Implementation mapping_:
- `backstitch/resolver.py`
- `backstitch/diagnostics.py`
- `backstitch/reporting.py`

## 5. Semantic Binding Analysis [INV-5]

`backstitch packets --kind {section,invariant,all}` defaults to section.
Filtering occurs after the full deterministic report, so every kind shares the
same deterministic policy exit. `all` emits section order followed by
invariant order.

A packet-schema-3 invariant is emitted only for an executable obligation under
[EVC-2.1] and [EVC-9.1]. A spec-declared invariant without a valid bound
implementation target is non-executable and emits no semantic packet; it does
not become a warning-bearing targetless packet. A code-declared invariant's
declaration owner is its implementation target. Both forms still require one
valid binding test. Code-only invariants have no valid v1 skip location.

The packet's requirement, declared implementation, binding-test evidence,
counterevidence, trace summary, readiness, snapshot identity, regions, issues,
and hashes are the exact closed [EVC-9.1] shape. Packet membership is complete
or fails closed; the old bounded target/test truncation contract is historical
only. The code-owned invariant prompt asks for a concrete target-code change
that violates the invariant while shown tests pass, or the exact shown
assertion spans that prevent one.

Invariant classifications are `ok`, `weak_binding`,
`confirmed_mismatch`, `probable_mismatch`, and `ambiguous`. Canonical model
evidence is the closed role/path/span shape in [SEM-5]. Invariant `ok`
requires test evidence. An `ok` row without it normalizes to
`weak_binding` only when requirement and implementation evidence are valid;
otherwise it is malformed. Weak binding intentionally requires no test role.
Every present span must match exactly one shown declaration, target, or binding
test region for its role. Empty/omitted snippets provide no evidence.

Packet ID, kind, packet hash, analysis key, and verification state
are trusted metadata, not model fields. Malformed/provider failures follow
[SC-7]'s problem-only contract and exit 2. `summarize-analysis` validates row
shape and identity but cannot re-prove locality without packets.

Packet-schema-2 and unversioned invariant forms are bounded historical
validation/presentation input under [SC-6]. They cannot produce a current or
qualification report and have no schema-3 gate authority. There is no
automatic test-helper expansion.

_Implementation mapping_:
- `backstitch/analysis_packets.py`
- `backstitch/artifact_contracts.py`
- `backstitch/analysis_llm.py`
- `backstitch/analysis_results.py`
- `backstitch/cli.py`

## 6. Boundaries And Non-Goals [INV-6]

The first implementation must not include:

- automatic invariant extraction from code or prose
- test generation or test repair
- mutation execution as part of ordinary invariant checking. The repository-
  owned semantic evaluation corpus is separately governed by [SEM-8].
- CI failure authority outside [SEM-5] through [SEM-9]
- cross-repository invariants
- runtime assertion checking (this spec is about tests, not `assert`)

_Implementation mapping_:
- `backstitch/analysis_packets.py`
- `backstitch/analysis_llm.py`

## 7. Failure Modes And Edge Cases [INV-7]

The tool must handle these cases explicitly:

- duplicate invariant IDs, including collision with spec section IDs
- binding references to unknown invariant IDs
- invariant declarations in unreadable or syntactically invalid files
  (existing `FILE_UNREADABLE` / `PYTHON_SYNTAX_ERROR` behavior; the scan
  continues per [SC-4])
- binding references outside test roots
- invariants whose complete requirement, implementation, binding-test, or
  counterevidence universe exceeds packet/report bounds are non-executable;
  packet construction fails closed and never truncates required evidence
- a spec invariant with no resolved implementation target is non-executable,
  emits no semantic packet, and retains its ordinary deterministic mapping
  and readiness findings
- malformed/provider output for invariant packets emits no canonical result or
  verifier event, records the [SC-7]/[EVC-8.7] structured problem, and exits
  `2`
- an invariant declared and bound in the same file (legal but reported as
  `INVARIANT_BINDING_NOT_TEST` when that file is not under a test root)

_Implementation mapping_:
- `backstitch/resolver.py`
- `backstitch/artifact_contracts.py`
- `backstitch/analysis_llm.py`

## 8. Diagnostic Codes And Default Policy [INV-8]

| Code | Short | Default | Context | Meaning |
|------|-------|---------|---------|---------|
| `INVARIANT_UNTESTED` | `BSI001` | error/warning | `required`, `draft` | A unique declaration has no valid binding test |
| `INVARIANT_UNKNOWN` | `BSI002` | error | none | A valid test binding names no declaration |
| `INVARIANT_DUPLICATE` | `BSI003` | error | none | An invariant ID is duplicate or collides with a section ID |
| `INVARIANT_BINDING_NOT_TEST` | `BSI004` | warning | none | A well-formed binding marker is outside valid test-definition scope |
| `INVARIANT_MARKER_INVALID` | `BSI005` | error | none | Reserved marker syntax or owner is invalid |

Each code becomes implemented only in the same slice as its first emission and
firing test. Short codes are never reused.

_Implementation mapping_:
- `backstitch/diagnostics.py`

## 9. Verification Expectations [INV-9]

<!-- backstitch: meta because docs/specs/04-backstitch-traceability-exclusions.md#SUP-VERIFICATION-META -->

Required proof:

- fixture-backed grammar tests: declaration parsing in code (module, class,
  function, method scopes; continuation lines) and in spec section bodies,
  the draft tier, binding parsing (single ID, comma lists), and non-matches
  (prose containing the word "Invariant:", fenced-code-block content)
- resolver tests proving each [INV-8] code fires, and that a bound
  invariant produces a `binds` edge and no finding
- assertion-laundering fixture: controlled-adapter tests prove the code-owned
  refutation prompt and deterministic `ok` to `weak_binding` normalization;
  role-matrix tests cover every invariant classification, forged roles/spans/
  excerpts, declaration evidence, and the intentional no-test weak-binding set
- marker-isolation tests covering every documented marker position plus
  adversarial CST fixtures and proving no ordinary `code_refs` or section
  backlink edges for those cases
- packet completeness and byte-ceiling tests for invariant packets; a missing
  target or binding test is non-executable, and overflow fails closed rather
  than truncating required evidence
- packet-hash independence tests: declaration excerpt/span and every other
  model-visible projection field affect `packet_hash`, while prompt-only edits
  affect prompt identity/analysis key and do not widen `content_hash`
- dogfood: `backstitch`'s own deterministic core declares its load-bearing
  invariants (at minimum: byte-stable resolver output, no guessed edges,
  deterministic commands never import `llm`) bound to the existing tests
  that enforce them, and the self-corpus check reports zero
  `INVARIANT_UNTESTED`
- self-acceptance for packet-schema-3, packet-report-schema-2,
  analysis-report-schema-3, result, cache-hit, and replay forms; schema-2 and
  unversioned forms remain historical-only under [SC-6]
- skip tests prove spec-declared skips are auditable and code-only invariants
  remain unskippable
- both `INVARIANT_UNTESTED` contexts and every BSI code have firing coverage

Fakes only at the model boundary, per [SC-10].

## 10. Documentation And Traceability [INV-10]

<!-- backstitch: meta because docs/specs/04-backstitch-traceability-exclusions.md#SUP-VERIFICATION-META -->

This specification became Active after its dated, independently reviewed plan
implemented the coordinated [SC-*], [CFG-*], and [EXC-*] changes and passed
the deterministic, semantic, dogfood, and acceptance gates. Future changes
must keep those contracts and their implementation docs aligned. Plans and
`docs/agent-context` are not parsed invariant sources: naming an invariant ID
there is durable human and agent guidance, not a machine bind or declaration.

Implementation must also update the style-traceability implementation doc,
repository map as needed, engineering-principles citation guidance, and the
reciprocal spec and code traceability chain.

## 11. Phase Hardening Invariants [INV-11]

Invariant: [INV.CANON.1] exactly one production implementation of canonical
JSON serialization, of the sha256-hex token grammar, of the deterministic
issue sort key, and of bounded no-follow file reading exists in the package;
every consumer imports the owner module named in the closed allowed-owner
table in `tests/test_canonical_owners.py`, proven by AST-level enumeration
of the package.

Invariant: [INV.LINE.1] production line-number arithmetic over source bytes
or snippet text splits on `\n` only, through the one shared line-slicing
helper; no production module outside the closed exemption table in
`tests/test_canonical_owners.py` calls `splitlines`, performs ad-hoc
`split("\n")` line splitting outside the shared helper, or does manual
newline-count arithmetic — the enumeration test covers all three call-site
forms. Receipts, packet spans, and shown-region reconstruction agree
byte-for-byte on any input, including `\r`, `\f`, `\v`, `\x85`, U+2028, and
U+2029.

Invariant: [INV.SCAN.1] one scan pipeline exists: every repository read used
by resolve, discovery, packets, and reports consumes the captured immutable
byte image, and only the owner modules named in the closed allowed-owner
table in `tests/test_canonical_owners.py` open repository files, proven by
AST-level enumeration; no live-filesystem twin path exists in the package.

Invariant: [INV.IDENTITY.1] coverage, check, obligation discovery, and semantic
candidate discovery share one Python definition-identity owner and one
accepted-snapshot path. A valid existing evidence-discovery module locator and
candidate ID remains byte-identical when coverage is enabled; coverage may add
only [COV-3]'s fallback module locator where discovery previously had no module
candidate. No consumer reparses live source, invents a parallel qualifier, or
reinterprets logical resolver edges as physical ordinals. One enumerating
owner test and cross-surface identity fixtures enforce the shared boundary.

Invariant: [INV.PERF.1] the advertised explicit `backstitch check`
invocation, and bare `backstitch` when effective configuration selects
`check`, perform zero static-syntax parses and at most one repository snapshot
capture; bare dispatch also resolves file configuration exactly once.
`backstitch obligation list` parses each unique file at most once per
invocation. Wall-clock budgets are non-normative and live only in marked
performance tests.

Invariant: [INV.CFG.2] for every config key whose settings-dataclass default
is a concrete value, the packaged-default TOML value equals that dataclass
default; keys whose dataclass default is None-means-packaged are exempt. On
conflict the packaged TOML is canonical and the dataclass is corrected. A
single enumerating test proves the equality.
The normalized optional `default_command` setting is covered explicitly:
packaged `false` normalizes to `None`, while repository `"check"` and
`"analyze"` values normalize to the corresponding closed command literals.

_Implementation mapping_:
- `backstitch/canonical.py`
- `backstitch/contract_validation.py`
- `backstitch/filesystem_io.py`
- `backstitch/grammar.py`
- `backstitch/models.py`
- `backstitch/repository_snapshot.py`
- `backstitch/scan_exclusions.py`
- `backstitch/settings.py`
- `backstitch/semantic_packets.py`
- `backstitch/code_parser.py`
- `tests/test_architecture.py`
- `tests/test_canonical_owners.py`
- `backstitch/obligation_runtime.py`

## Related Plans

- `docs/plans/2026-08-04-semantic-preparation-performance-plan.md`
  (implementation plan; [INV-5] and [INV-6])
- `docs/plans/2026-07-29-architecture-quality-remediation-plan.md`
  (active implementation plan; [INV-11])
- `docs/plans/2026-07-28-intent-coverage-implementation-plan.md`
  (active implementation plan; [INV.IDENTITY.1])
- `docs/plans/2026-07-28-configured-default-command-plan.md`
  (implemented and independently reviewed; uncommitted)
- `docs/plans/2026-07-11-deterministic-semantic-gate-plan.md`
  (implementing)
- `docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md`
  (implementing)
- `docs/plans/2026-07-09-backstitch-invariant-traceability-plan.md`
  (implemented)
- `docs/plans/2026-07-16-evidence-spike-hardening-plan.md`
  (implementing)

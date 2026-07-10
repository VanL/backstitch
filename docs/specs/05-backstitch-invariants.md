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

`backstitch packets` emits discriminated section and invariant records.
`--kind {section,invariant,all}` defaults to `section`. `all` emits existing
section order first, then invariant order. Filtering occurs after the full
deterministic report, so diagnostics and exit status remain whole-repository.
For one corpus and policy, every kind has the same policy-driven exit code.

New packets always carry `kind`. Loaders normalize the legacy section shape
without kind. An invariant packet exists only for an invariant with a valid
bind and contains `packet_id = "invariant::<ID>"`, kind, ID, tier, statement,
declaration locator, bounded `targets`, bounded `binding_tests`, relevant
issues, `packet_warnings`, instructions, and `content_hash`. A bound
spec-declared invariant without a resolved target has `targets: []` plus a
warning. An untested invariant has no semantic packet.
Every named envelope key is required; array-valued fields may be empty but may
not be omitted.

An invariant packet's `issues` are exactly report issues whose
`invariant_id` equals that packet's invariant ID, ordered by path, nullable
line (null before numbered lines), canonical code, and message.

The invariant-only packet keys are `invariant_id`, `tier`, `statement`,
`declaration`, `targets`, `binding_tests`, and `content_hash`. `declaration` is
an object with `kind`, `path`, `line`, nullable `symbol`, and nullable
`section_id`; exactly one of `symbol` and `section_id` is non-null.

For a code declaration, `targets` contains only the declaring path and symbol
and never consults mappings. A module declaration uses the reserved symbol
`<module>`, which cannot collide with a Python identifier, `start_line = 1`,
and the first 120 lines of the whole file's UTF-8 replacement-decoded text read
at packet generation. For a spec declaration,
`targets` contains unique resolved mapping edges of the enclosing section;
backlinks are excluded. A spec declaration with zero mapping targets uses
`targets: []` and a warning containing
`no target code resolved for spec-declared invariant`.

Targets and binding tests both sort by path, nullable symbol (null as empty
string), and start line. Retain at most eight targets and eight binding tests.
Each snippet is capped to its first 120 lines with no inserted ellipsis;
omission and truncation are represented only in `packet_warnings`. Empty
snippets require an explicit unreadable, missing-symbol, or file-race warning.

The prompt asks: "Describe a concrete target-code change that violates this
invariant while every shown test still passes. If none exists, cite the
specific assertion lines in shown binding-test snippets that would fail."

Invariant packets allow `ok`, `weak_binding`, `confirmed_mismatch`,
`probable_mismatch`, and `ambiguous`. Section packets retain `ok`,
`confirmed_mismatch`, `probable_mismatch`, `missing_trace`, and `ambiguous`.
The result's existing `evidence` field is an array of `{path, line}` objects.
A shown snippet's inclusive evidence range is `start_line` through
`start_line + len(snippet.splitlines()) - 1`; an empty snippet has no valid
line range. During `analyze`, invariant `ok` requires at least one evidence item
inside a shown `binding_tests` range. If it has none, normalize it to
`weak_binding`, even when it cites target-code evidence. V1 does not
syntactically recognize all assertion idioms. Any evidence path or line outside
the packet's shown target and binding-test ranges is malformed output. More
precisely, zero evidence items are valid and evidence-deficient; every present
item's path must equal the shown item's path and its line must fall in that
item's range, or the whole result is malformed. This includes evidence for a
binding test omitted by the eight-test packet cap.

The model must return the existing packet ID; a mismatch is malformed. Model
output does not need `kind` or `content_hash`, and any supplied values are
ignored. The canonical result copies packet ID, kind, and invariant hash from
the packet. Hash the final ordered and truncated packet projection
exactly as defined in [SC-6]. `summarize-analysis` validates identity, kind, row
shape, and hash shape, but not snippet locality because it has no packet. It
renders section and invariant advisory blocks separately. V1 adds no cache and
no automatic test-helper expansion.

`summarize-analysis` is not a trust boundary for evidence locality. Only
`analyze`, while holding the source packet, can validate those ranges.

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
- mutation testing. It is the execution-based ground truth for the same
  question and the natural calibration path for the semantic judge (run
  mutations on a sample of invariants; compare against `ok` verdicts to
  measure the judge's false-`ok` rate) — but it is a separate spec if
  adopted, because it changes the execution boundary.
- CI failures from semantic classifications
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
- invariants whose owning code or binding tests exceed packet bounds
  (truncate with `packet_warnings`, never silently)
- a bound spec invariant with no resolved implementation mapping still emits a
  packet with statement, bounded binding tests, `targets: []`, and an explicit
  warning; its ordinary section-mapping finding remains
- malformed model output for invariant packets (per-packet containment per
  [SC-7])
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

Required proof:

- fixture-backed grammar tests: declaration parsing in code (module, class,
  function, method scopes; continuation lines) and in spec section bodies,
  the draft tier, binding parsing (single ID, comma lists), and non-matches
  (prose containing the word "Invariant:", fenced-code-block content)
- resolver tests proving each [INV-8] code fires, and that a bound
  invariant produces a `binds` edge and no finding
- assertion-laundering fixture: fake-adapter tests prove the refutation prompt
  and deterministic `ok` to `weak_binding` normalization when no evidence
  falls inside a shown binding-test range
- marker-isolation tests covering every documented marker position plus
  adversarial CST fixtures and proving no ordinary `code_refs` or section
  backlink edges for those cases
- packet-bound tests for invariant packets, including truncation warnings
- content-hash tests: every invariant result carries a 64-character lowercase
  hexadecimal `content_hash`, every section result omits that key, identical
  triads hash identically across runs, and changing the statement, target code,
  or binding tests changes the invariant hash
- dogfood: `backstitch`'s own deterministic core declares its load-bearing
  invariants (at minimum: byte-stable resolver output, no guessed edges,
  deterministic commands never import `llm`) bound to the existing tests
  that enforce them, and the self-corpus check reports zero
  `INVARIANT_UNTESTED`
- self-acceptance for new report, packet, and result forms and all three
  documented legacy artifact forms: deterministic report without all three
  invariant additions; section packet without `kind`; section result without
  `kind`
- both `INVARIANT_UNTESTED` contexts and every BSI code have firing coverage

Fakes only at the model boundary, per [SC-10].

_Implementation mapping_:
- `tests/acceptance/test_probe_invariants.py`

## 10. Documentation And Traceability [INV-10]

This specification became Active after its dated, independently reviewed plan
implemented the coordinated [SC-*], [CFG-*], and [EXC-*] changes and passed
the deterministic, semantic, dogfood, and acceptance gates. Future changes
must keep those contracts and their implementation docs aligned. Plans and
`docs/agent-context` are not parsed invariant sources: naming an invariant ID
there is durable human and agent guidance, not a machine bind or declaration.

Implementation must also update the style-traceability implementation doc,
repository map as needed, engineering-principles citation guidance, and the
reciprocal spec and code traceability chain.

_Implementation mapping_:
- `tests/test_backstitch_corpus_traceability.py`

## Related Plans

- `docs/plans/2026-07-09-backstitch-invariant-traceability-plan.md`
  (implemented)

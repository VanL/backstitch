# Backstitch Invariant Traceability Specification

Status: Proposed

This spec makes declared invariants first-class nodes in the backstitch trace
graph. Deterministic mode checks that every declared invariant is cited by at
least one test; semantic mode judges whether the citing test actually *binds*
the invariant — whether the invariant could be violated while the test still
passes.

Related specs:

- `docs/specs/02-backstitch-core.md` [SC-2], [SC-4], [SC-6], [SC-7], [SC-10],
  [SC-11]
- `docs/specs/03-backstitch-configuration.md` [CFG-6]
- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-6]

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

Rules:

- Token sequence is `Invariant:` then a bracketed stable ID then the
  statement. `Invariant (draft):` declares a draft-tier invariant (see
  [INV-4]).
- Statement termination is exact, not stylistic. In a code docstring, the
  statement is the marker line plus any immediately following lines indented
  deeper than the marker line; the first line at or below the marker's
  indent ends it. In Markdown, the statement is the marker line plus
  immediately following non-blank plain-text lines; a blank line, heading,
  list bullet, fence, another marker, or HTML comment ends it. A parser must
  never absorb the next paragraph into an invariant statement.
- IDs use the existing section-ID shape ([SC-4]) and share the corpus-wide
  uniqueness namespace with spec section IDs: an invariant ID must not
  collide with a section ID or another invariant ID.
- A code-declared invariant's owner is the enclosing docstring scope
  (module, class, function, or method), recorded like any code backlink
  owner. A spec-declared invariant's owner is the enclosing spec section;
  its target code is that section's mapped implementation owners, so the
  full triad — invariant statement, target code, binding test — resolves
  through existing mapping machinery.
- Invariant-style bullets ([SC-4], e.g. `- **OBS.13.10**: ...`) remain plain
  spec sections and carry no binding obligation; only the `Invariant:`
  marker creates one. Fenced-code-block content is ignored per [SC-4].
- Plans do not declare invariants directly, because plans are execution
  documents that go archival while invariants are durable contracts. A
  plan's "invariants that must survive" section ([DOM-5], engineering
  principle 9) names existing `[INV.*]` IDs or adds new `Invariant:`
  declarations to the governing spec in the same change — the plan cites,
  the spec declares, and the contract outlives the plan.
- The `Invariant:` marker is the **entire** declaration grammar. There is no
  `_Invariant mapping_:` block form and none should be invented: target-code
  linkage comes from the enclosing docstring scope (code-declared) or the
  section's existing `_Implementation mapping_:` block (spec-declared), and
  test linkage comes only from `Tests-invariant:` references.

Binding, in a test docstring or comment, using the existing reference
grammar with a dedicated marker:

```python
def test_resolver_output_is_stable() -> None:
    """Tests-invariant: [INV.RES.1]"""
```

- Token sequence is `Tests-invariant:` then one or more bracketed IDs,
  comma-separated ([SC-4] comma-list rules apply).
- Binding scope is exact, because semantic packets need a bounded
  binding-test snippet. A `Tests-invariant:` marker binds as follows:
  in a test function or method docstring, it binds that function; in a class
  docstring under a test root, it binds every test method of that class; as
  a comment immediately preceding a test function or class definition, it
  binds that definition (next-statement scope, consistent with [EXC-5]).
  Module docstrings do not bind — a module is too coarse a unit to package
  as a binding snippet. A marker in any other position, or outside the
  configured test roots, is reported (`INVARIANT_BINDING_NOT_TEST`) and does
  not satisfy the invariant: production code asserting its own invariant is
  not a test.

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

`INVARIANT_UNTESTED` severity is tiered by declaration form. A plain
`Invariant:` declaration is a required invariant: untested is an **error**,
because a declared load-bearing contract with no enforcement is exactly the
deficiency this spec exists to catch. An `Invariant (draft):` declaration is
a stated intention whose test does not exist yet: untested is a **warning**,
so declaring early is never punished harder than not declaring at all — the
draft tier is the adoption ramp, and promoting a draft to required is a
one-word edit.

There is no per-code severity promotion in v1: the only promotion lever is
the global `warnings_as_errors` / `--warnings-as-errors` ([CFG-6]), which
affects draft-tier findings like any other warning. A per-code promotion
table is a [CFG] revision to propose alongside activating this spec, not
machinery this spec may assume.

Suppression follows [EXC-*] unchanged, and the interaction is deliberate:
`INVARIANT_UNTESTED` on a draft-tier invariant is a warning and is
suppressible like any other (for example, `lint.per-file-ignores` on a
work-in-progress module). On a required-tier invariant it is an error, and
[EXC]'s severity policy makes errors non-suppressible — so a required
invariant cannot be silenced, only satisfied with a binding test or
explicitly demoted to draft in the declaration itself. The demotion is a
visible, reviewable edit; that is the point.

The JSON report ([SC-6]) gains an `invariants` collection (ID, statement,
owner path/symbol/line, binding test references) and `binds` edges. Summary
counts gain `invariants`.

## 5. Semantic Binding Analysis [INV-5]

Invariant packets ride the existing pipeline: `backstitch packets` emits them
alongside section packets, each record carrying a `kind` field
(`"section"` or `"invariant"`), and a `--kind` filter selects one stream.
`analyze` and `summarize-analysis` need no new commands; the summary output
reports invariant-binding classifications in their own block, separated from
section findings.

Invariant packets extend the [SC-6] packet contract. Each packet contains:

- packet ID (`invariant::<ID>`)
- the invariant ID and full statement text
- the bounded target-code snippet: the enclosing docstring scope for a
  code-declared invariant, or the declaring section's mapped implementation
  owners for a spec-declared one — the packet always carries the full triad
  of statement, target code, and test code
- the bounded binding-test snippet(s), including directly referenced local
  helpers when they fit the packet bounds
- deterministic issues relevant to the invariant
- truncation warnings ([SC-6] `packet_warnings`) whenever bounds trimmed
  content
- prompt instructions per the refutation contract below

**Refutation contract.** The prompt must ask the refutation question, not
the confirmation question:

> Describe a concrete change to the target code that violates this
> invariant while every shown test still passes. If no such change exists,
> cite the specific assertion lines (packet-local file and line) that would
> fail.

A classification of `ok` is valid only when the result names binding
assertion lines that exist in the packet. A result that affirms the test
without citing binding assertions must be classified `weak_binding`.

Classifications extend the [SC-6] set for invariant packets:

- `ok` — binding assertions identified and cited
- `weak_binding` — the test exercises the path but its assertions would not
  fail if the invariant broke
- `confirmed_mismatch` — the test does not exercise the invariant at all
- `probable_mismatch`
- `ambiguous`

All [SC-7] rules apply unchanged: packets are the review boundary, model
output is untrusted (packet IDs come from packets), results are advisory and
never CI-failing, malformed output is contained per packet, and concurrent
analysis emits results in packet order.

**Re-evaluation economy.** Each result record must include a content hash
over (invariant statement, target snippet, binding snippets), so unchanged
packets are identifiable across runs. Skip-if-unchanged behavior is
explicitly **not** a v1 requirement: a real caching contract needs a CLI
surface, a storage location, an invalidation rule, and a trust decision
about prior result files, and deserves its own spec revision. v1 only
guarantees the hash is there so that revision (or an external wrapper) can
build on it.

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
- a spec-declared invariant in a section with no implementation mapping (the
  binding obligation stands; the packet carries the statement and tests with
  a `packet_warnings` note that no target code resolved, and the section's
  `SPEC_SECTION_UNMAPPED` finding fires as usual)
- malformed model output for invariant packets (per-packet containment per
  [SC-7])
- an invariant declared and bound in the same file (legal but reported as
  `INVARIANT_BINDING_NOT_TEST` when that file is not under a test root)

## 8. Issue Codes [INV-8]

Additions to the [SC-11] table, following its severity rationale (errors =
asserted something false; warnings = weak or one-directional links):

| Code | Severity | Meaning |
|------|----------|---------|
| `INVARIANT_UNTESTED` | error/warning | Declared invariant has no binding test (required tier: error; draft tier: warning) |
| `INVARIANT_UNKNOWN` | error | Test binds an invariant ID that is not declared |
| `INVARIANT_DUPLICATE` | error | Invariant ID declared more than once or collides with a section ID — every `Tests-invariant:` edge to it is ambiguous |
| `INVARIANT_BINDING_NOT_TEST` | warning | Binding reference outside test roots or in a position that cannot bind ([INV-3] scope rules) |

All four codes participate in the [SC-10] contract-coverage gate: each must
have at least one test that proves it fires.

## 9. Verification Expectations [INV-9]

Required proof:

- fixture-backed grammar tests: declaration parsing in code (module, class,
  function, method scopes; continuation lines) and in spec section bodies,
  the draft tier, binding parsing (single ID, comma lists), and non-matches
  (prose containing the word "Invariant:", fenced-code-block content)
- resolver tests proving each [INV-8] code fires, and that a bound
  invariant produces a `binds` edge and no finding
- an **assertion-laundering fixture**: a test that cites an invariant but
  asserts adjacent behavior, paired with a fake-adapter test proving the
  refutation prompt is constructed, and that an `ok` verdict lacking cited
  assertion lines is downgraded to `weak_binding` at **result validation**
  (the analysis-results layer that parses and validates model output — not
  the deterministic Markdown/Python parsers, which never see model output).
  The downgrade is deterministic tool behavior, not model behavior, so it
  is testable without a model
- packet-bound tests for invariant packets, including truncation warnings
- content-hash tests: every result record carries the hash, identical
  triads hash identically across runs, and changing the statement, target
  code, or binding tests changes the hash
- dogfood: `backstitch`'s own deterministic core declares its load-bearing
  invariants (at minimum: byte-stable resolver output, no guessed edges,
  deterministic commands never import `llm`) bound to the existing tests
  that enforce them, and the self-corpus check reports zero
  `INVARIANT_UNTESTED`

Fakes only at the model boundary, per [SC-10].

## 10. Documentation And Traceability [INV-10]

**Activation sequence.** This spec stays `Proposed` — and core work must not
implement it — until each step lands, in order:

1. a dated implementation plan exists per [DOM-5], dogfooding first: the
   initial declarations are backstitch's own core invariants (byte-stable
   resolver output, no guessed edges, deterministic commands never import
   `llm`), bound to the existing tests that already enforce them
2. the status line flips to `Active` in the same change that applies the
   coordinated core-spec delta, so the contract is never split
   inconsistently across files: [SC-5] gains the `--kind` filter in its
   usage examples, [SC-6] gains the `invariants` collection, `binds` edges,
   the `invariants` summary count, and the packet `kind` field, and the
   [SC-2]/[SC-11] pointers drop their "proposed" gating language
3. `docs/specs/00-specs-index.md` drops the Proposed annotation
4. if per-code severity promotion is wanted, it is proposed as a [CFG]
   revision in the same change, not assumed

Implementation must also update:

- `docs/implementation/04-backstitch-style-traceability.md` (invariant node
  type, binding semantics, refutation contract rationale)
- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-10] — add the
  invariant-suppression example (draft-tier suppressible, required-tier not)
- `docs/agent-context/engineering-principles.md` — principle 9's plan-level
  invariants should name their `[INV.*]` IDs once this spec is implemented,
  so a plan's "invariants that must survive" section becomes machine-traced
  declarations rather than prose that dies with the plan

## Related Plans

- (none yet — implementation requires a dated plan per [DOM-5])

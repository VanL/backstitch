# Verification And Aligned Evidence Spec

Status: Active

> **Superseded draft:** The prior proposal and activation based evidence-case
> design is preserved at commit
> `25346a988ad2022237160261aa61d2692d5baaa4` (file SHA-256
> `3df5b8eb9391ba98400aa8736f1c99d67082c97278ef371f9b85560ab52b43f1`).
> Retrieve it with
> `git show 25346a988ad2022237160261aa61d2692d5baaa4:docs/specs/07-verification-and-evidence-cases.md`.
> That draft was `Status: Proposed`; it was never normative and is superseded
> by this active revision.

Related specs:

- `docs/specs/02-backstitch-core.md` [SC-3] through [SC-8], [SC-10],
  [SC-13], [SC-15], [SC-16]
- `docs/specs/03-backstitch-configuration.md` [CFG-3], [CFG-5], [CFG-6],
  [CFG-8], [CFG-9]
- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-4], [EXC-6],
  [EXC-7], [EXC-8]
- `docs/specs/05-backstitch-invariants.md` [INV-3], [INV-5], [INV-7], [INV-9]
- `docs/specs/06-semantic-gates.md` [SEM-1] through [SEM-10]
- `docs/specs/08-intent-coverage.md` [COV-6], [COV-7], [COV-9]

This spec defines how Backstitch helps turn aligned intent into an executable
gate. It adds an obligation-centered human and agent interface, deterministic
candidate discovery, source-derived evidence packets, and independent semantic
verification. It does not create a second evidence authority. Repository
source remains authoritative.

The coordinated promotion record in the related plan is the evidence that this
revision passed its independent review and cross-spec gate. Implementations
may cite only the active, hashed revision recorded there.

## 1. Purpose And Scope [EVC-1]

<!-- backstitch: meta because docs/specs/04-backstitch-traceability-exclusions.md#SUP-EVC-PROCESS -->

Backstitch answers three different questions and must keep them separate:

1. **What does the repository say must be true?** Spec sections and invariant
   declarations identify obligations.
2. **What source does the repository declare as implementing or testing that
   intent?** Reciprocal mappings, backlinks, binds, and binding-test markers
   establish alignment.
3. **Does the aligned implementation appear to conform to the intent?** The
   semantic analyzer and blinded adversarial verifier provide measured
   judgments over a deterministic source-derived packet.

The first two questions are deterministic. Their answer is repository source,
not an agent decision. The third question is stochastic and cannot confer
alignment that the first two questions did not establish.

This spec governs:

- obligation inventory, detail, evidence summary, and readiness;
- source-authored obligation skips;
- deterministic discovery of candidate evidence and counterevidence;
- exact source receipts, candidate identities, static relations, and trace
  guidance;
- the CLI, optional local stdio MCP adapter, and installed alignment guide;
- compilation of aligned source into section/invariant packet schema 3 and
  suppression packet schema 4, with exact mixed-artifact rules in [EVC-9.1];
- current-repository analysis versus historical packet replay;
- independent blinded verification, aggregation, measurement, and policy
  integration.

This spec does not govern or permit:

- Backstitch editing specs, source, tests, mappings, backlinks, binds, skips,
  or configuration;
- agent-authored evidence manifests, proposal files, activation, deactivation,
  or mutable evidence-case state;
- runtime tracing, arbitrary filesystem query, HTTP or remote MCP transport;
- model-selected packet membership;
- describing semantic judgment as mechanical proof.

Backstitch may write packets, reports, caches, and evaluation artifacts only
to paths explicitly requested by an existing artifact-producing command.
Those files are derived output. Deleting them loses no alignment decision.

## 2. Mental Model And Authority [EVC-2]

The public nouns are:

| Noun | Meaning | Authority |
|---|---|---|
| **obligation** | One addressable spec section, first-class invariant, or valid used suppression declaration | Its repository source declaration |
| **evidence link** | A mapping, backlink, bind, or binding-test relation associated with an obligation | A valid human-reviewed source declaration and its required reciprocal relation |
| **candidate** | A bounded deterministic discovery result that may be relevant | Advisory; it has no alignment authority |
| **skip** | A reasoned source annotation that suppresses semantic evaluation without claiming conformance | Human-reviewed spec source |
| **evidence packet** | Exact requirement, declared evidence, and deterministic counterevidence sent to semantic analysis | Derived, content-addressed output |
| **gate** | Alignment readiness followed by semantic analysis, verification, and policy | Backstitch computation over one current source snapshot |

The product has a repeatable bootstrap loop and a separate gate:

```text
bootstrap (repeat on any current source snapshot)
  obligation -> deterministic candidate report
             -> human disposition
             -> human-reviewed reciprocal source declarations

gate (always rebuild from current source declarations)
  obligation -> alignment readiness
             -> deterministic evidence packet
             -> analyze -> adversarial verify -> policy
             -> executable gate result
```

Discovery cannot establish alignment. A model result cannot establish
alignment. A packet or cache object cannot establish alignment. A candidate
becomes declared evidence only when repository source carries the supported
declarations and the existing resolver establishes the required reciprocal
relations.

_Implementation mapping_:

- `backstitch/obligations.py`

### 2.1 Obligation Identity And Readiness [EVC-2.1]

A section obligation uses the existing canonical file-qualified section
identity from [SC-4]. An invariant obligation uses
`invariant::<invariant_id>`. Bare aliases may be accepted as input only when
the existing resolver finds exactly one canonical identity. Responses always
return the canonical identity. Ambiguity is never guessed.

Each addressable obligation has these independent facts:

| Fact | Closed values | Meaning |
|---|---|---|
| `intent_state` | `identified` | The addressable source obligation has one supported identity; identity defects are separate `unaddressable_intent` rows |
| `alignment_state` | `untraced`, `partial`, `complete`, `invalid` | Required evidence roles are absent, incomplete, complete, or malformed |
| `disposition` | `evaluate`, `skipped` | Semantic evaluation is requested or suppressed by one valid source skip |
| `obligation_rung` | `active`, `planned`, `exploratory`, `meta` | Existing profile and traceability classification determines whether the intent participates in the current gate |
| `gate_state` | `not_executable`, `executable` | The current addressable obligation cannot run or can run; operation failures are top-level problems, not synthetic obligation states |

`gate_state` is readiness, not a semantic verdict. Analyzer classifications,
verifier verdicts, policy findings, and process exit status remain separate.

A valid suppression declaration referenced by at least one matched governed
rule enters the inventory as one active suppression obligation. Its identity
is `suppression::PATH#SUP-ID`; intent is identified, alignment is complete,
disposition is evaluate, gate state is executable, and required source roles
are empty. Invalid, unreferenced, or unmatched declarations do not become
executable semantic obligations; their deterministic hygiene remains
[EXC-8]. Suppression obligations cannot carry an [EVC-8.3.2] skip because
their declaration already exists to explain a suppression. Section and
invariant readiness rules do not change.

The deterministic state rules are:

- a section requires at least one valid reciprocal `implementation` evidence
  relation;
- configured section role `test` requires at least one valid reciprocal test
  relation when present in `section_required_roles`;
- an invariant requires its unique declaration, at least one atomic bound target,
  and at least one valid binding-test relation under [INV-5]; its roles are
  fixed as `implementation` and `binding_test` and cannot be weakened by the
  section-role setting;
- a v1 spec-invariant target is atomic only when its resolved mapping names a
  captured regular `.py` file, tree-sitter parsing succeeds, and an explicit
  symbol selects exactly one owner; a null symbol selects the whole parsed
  module receipt. A code-declared invariant is atomic only when its declaration
  line selects exactly one containing owner (the `module` sentinel selects the
  whole parsed module). Directory, non-Python, unparseable, or ambiguous-owner
  attempts remain visible one-sided declarations and do not satisfy readiness;
- for section and invariant obligations, no required role present gives
  `untraced`;
- for section and invariant obligations, at least one required role satisfied while another is absent, or a one-sided
  declaration that can be attributed to the obligation, gives `partial`;
- for section and invariant obligations, every required role satisfied by valid reciprocal relations gives
  `complete`;
- malformed or ambiguous identity, duplicate declaration, or contradictory
  declarations that prevent one readiness answer give `invalid`;
- valid sections under `spec_roots`, valid first-class invariants, and valid
  used suppression declarations enter the inventory.
  Planned/exploratory file classification and section/file meta
  classification produce their named `obligation_rung`. Invariant-style
  Markdown bullets remain ordinary sections under [INV-2]. ID-less prose does
  not enter. A code-declared invariant is `active` unless its captured source
  is excluded from the active profile;
- `alignment_state = invalid` gives `gate_state = not_executable`;
- `alignment_state` other than `complete` gives `not_executable`;
- `obligation_rung` other than `active` gives `not_executable` without
  creating current-gate alignment debt;
- `disposition = skipped` gives `not_executable`, regardless of alignment;
- complete alignment with `disposition = evaluate` gives `executable`;
- capture, configuration, budget, or internal failures return a top-level
  operation problem and exit 2. They do not mint an obligation record.

A skipped obligation remains in every denominator. Its alignment state is
still computed and reported without change. Evidence summary and candidate
discovery remain available. The skip does not count as analysis, independent
verification, or conformance.

Current semantic selection and corpus behavior are exact. The last column
describes readiness only; deterministic issue policy is applied later by
[EVC-8.7]:

| Active obligation condition | Corpus bucket | Semantic calls | Creates readiness blocker |
|---|---|---:|---|
| `disposition = skipped` at any alignment state | `skipped` | 0 | no |
| `evaluate` and `alignment_state = complete` | `selected` | analyzer plus configured verifier | no |
| `evaluate` and alignment is `untraced`, `partial`, or `invalid` | `alignment_debt` | 0 | yes, exit 2 |
| Determination fails after a captured identity exists | `blocked` | 0 | yes, exit 2 |

Non-active rungs enter `out_of_scope` and cause no semantic call or readiness
blocker. If any active `alignment_debt` or `blocked` row exists, current analyze
makes zero provider calls for the whole corpus, publishes no current analysis
report, and exits 2. Otherwise [EVC-8.7]'s first-match matrix applies. In
particular, any failing deterministic issue exits 1 with no current analysis
report before semantic calls. This includes BSE001 and retained trace issues;
BSE001 is not a separate or later exit selector. If no deterministic issue
fails, Backstitch evaluates every `selected` row. A corpus with at least one
active obligation and all active obligations skipped then makes zero provider
calls, performs final recapture, publishes a report with
`semantic_status = "not_run_all_skipped"`, makes no conformance claim for a
skipped obligation, and exits 0.
A corpus with no active obligation is `semantic_status = "no_active_intent"`,
makes zero provider calls, publishes no current analysis report, and exits 2.
After successful selected evaluation, semantic policy owns exit 0 or 1.
Provider/tool failure still owns exit 2.

Corpus discovery also reports parser-recognized reserved intent syntax that
cannot become an addressable obligation: an ID-bearing heading or first-class
invariant marker with an invalid, missing, duplicate, or ambiguous ID. Such a
row has `entry_type = "unaddressable_intent"`; it is not assigned a synthetic
obligation ID. For Markdown headings, reserved syntax means the complete inline
heading content ends in one square-bracket marker (or consists only of that
marker) after supported trailing directives are removed. A blank or invalid
marker ID, or a marker with no section title, fires
`SPEC_SECTION_HEADING_INVALID`; its inventory row carries the exact captured
source line as `excerpt`. A heading with no terminal marker remains ordinary
ID-less prose, including a heading that uses brackets before later prose. It is
not inferred to be intent in v1.

_Implementation mapping_:

- `backstitch/markdown_specs.py`
- `backstitch/obligation_runtime.py`
- `backstitch/obligations.py`

### 2.2 Evidence Roles And Relations [EVC-2.2]

The closed evidence roles are `implementation`, `test`, and `binding_test`.
`counterevidence` is a packet role, not a source-declared alignment role.

For section obligations, role derives from the resolved evidence path after
root containment and profile exclusions. A reciprocal mapping/backlink whose
path is under any configured `test_root` has role `test`; otherwise it has role
`implementation`. A path under both code and test roots is `test` only. One
edge never satisfies both roles. Tests use the same `_Implementation mapping_`
and code `Spec:` backlink forms as other section evidence; v1 adds no test-only
annotation grammar. Invariants continue to use declaration/bind and
`Tests-invariant:` grammar, and a binding-test row has role `binding_test`.

The closed relation kinds are:

- `spec_mapping`: an implementation mapping owned by a spec section;
- `code_backlink`: a resolving code `Spec:` reference;
- `invariant_declaration`: the owner of a first-class invariant;
- `invariant_bind`: a resolved invariant target;
- `binding_test`: a resolved `Tests-invariant:` relation;
- `static_import`: a conservative captured Python import relation;
- `static_call`: a conservative captured Python call relation;
- `static_reference`: another conservative captured Python name relation;
- `enclosing_definition`: lexical ownership of a candidate;
- `issue_target`: an existing deterministic resolver issue attributed to the
  obligation.

The first five may describe declared evidence. The last five are derived
orientation or counterevidence only. A static relation never claims runtime
reach, execution, assertion, or conformance.
In discovery algorithm version 2, `enclosing_definition` is orientation only:
it remains a returned relation and trace-summary membership but never becomes
a closure hop.

For section implementation evidence, one `spec_mapping` and one resolving
`code_backlink` must form the reciprocal relation required by [SC-4]. One side
alone is visible in evidence summary but does not satisfy the role. Invariant
roles use [INV-5]'s declaration, bind, and test rules without inventing a
parallel relation language.

All consumers use one resolved evidence atom with exactly:

```text
{
  source_role,
  model_role,
  source_identity,
  relation_kinds,
  reciprocity_state,
  eligibility,
  reason
}
```

`source_role` uses this section's role vocabulary. `model_role` is
`implementation` for implementation evidence and `test` for test or
binding-test evidence. `source_identity` is the canonical resolved receipt
identity. `relation_kinds` is the sorted nonempty set of relations carried by
that receipt. `reciprocity_state` is `complete` or `one_sided`.
`eligibility` is `implementation`, `test`, `binding_test`, or `invalid`.
`reason` is null for valid evidence and otherwise is the canonical blocking
reason. Diagnostics, obligation readiness, invariant-target selection,
evidence summaries, discovery, and packet projection consume this atom; none
may infer a different role or eligibility from a path.

A resolving mapping under a configured test root is valid test evidence. It is
excluded from both successful and broken implementation-target counts. Only an
invalid production mapping can poison implementation readiness. When an
implementation mapping resolves but every resolved target is under configured
test roots, deterministic resolution emits `SPEC_MAPPING_TEST_ONLY` (`BSC009`)
at the mapping. The issue supplies test evidence and no implementation
evidence; [SC-11] and [SC-15] own its default warning severity, policy, and
firing contract.

_Implementation mapping_:

- `backstitch/obligations.py`

### 2.3 Bootstrap-To-Gate Lifecycle [EVC-2.3]

Bootstrap and gate are separate operations joined only by human-reviewed
repository source:

1. bootstrap captures one current snapshot and reports plausible candidates,
   receipts, trace states, discovery reasons, and supported trace forms;
2. a human accepts or rejects those suggestions and records accepted evidence
   through the repository's existing source declarations;
3. gate captures current source again, resolves only source-declared evidence,
   builds a deterministic packet, and reports whether that packet appears to
   support the obligation.

A candidate report is disposable derived output. It never becomes gate input
or evidence authority. Re-running bootstrap on the same snapshot and settings
must produce byte-identical core results. Re-running it after source changes
must produce a newly snapshot-bound report, so new, removed, moved, newly
declared, partially declared, and conflicted candidates are visible for human
review. The command must not describe an earlier candidate report as current.

Gate packet construction does not reuse candidate dispositions. It resolves
the human decisions expressed in current source, rejects incomplete alignment
before provider calls, and applies [EVC-5.1]'s currentness boundary before it
publishes a current result. Better discovery ranking, explanations, and trace
advice reduce the cost of the human bridge; they never confer authority.

_Implementation mapping_:

- `backstitch/obligation_runtime.py`

## 3. Blinded Adversarial Verify Stage [EVC-3]

Semantic analyze remains a bounded stochastic search heuristic under [SEM-*].
A blinded adversarial verify stage attempts to falsify each normalized analyze
finding before stronger policy may act on it.

Verify must:

- receive a reason-free projection of the same source-derived packet that
  analyze used;
- receive the normalized claim and its trusted evidence-bound citations;
- exclude analyzer rationale, analyzer confidence, policy level, source skip
  reason, discovery guidance, and any human or agent selection reason;
- use a separately resolved verifier inference contract, adversarial prompt
  identity, request controls, and search epoch; its provider/model tuple may
  equal or differ from analyze's tuple;
- return one closed verdict: `support`, `refute`, or `indeterminate`;
- return a finite `support_score` in `[0, 1]` and trusted evidence citations
  reconstructed from the supplied packet;
- never search the repository, request more evidence, or change packet
  membership;
- treat provider, shape, budget, and evidence-binding failures as inability to
  verify, not as evidence that the claim is false.

An aggregate claim state is:

- `independently_verified` when every required verify event says `support` and
  each support score meets `minimum_support_score`;
- `disputed` when any required event says `refute` with valid bound evidence;
- `verification_indeterminate` otherwise.

Verifier independence is procedural: a reason-free packet projection, a
falsification prompt, and separate request, event, and cache identities. It is
not statistical or model independence. Cross-model correlation is not a
qualification metric, and a distinct model grants no additional evidence
class. The state `independently_verified` means the claim survived this bounded
blinded process under the exact qualified configuration. It does not mean
mechanical proof.

_Implementation mapping_:

- `backstitch/semantic_verification.py`

### 3.1 Closed Verifier Contracts [EVC-3.1]

For each normalized analyze finding, Backstitch derives a claim object with
exactly:

```text
{
  packet_id,
  packet_hash,
  obligation_id,
  kind,
  code,
  classification,
  statement,
  evidence: [{role, path, start_line, end_line, excerpt_sha256}]
}
```

The claim's `evidence` is reconstructed and normalized under [SEM-5].
`statement` is the normalized analyzer result's required nonblank `summary`
field, byte-for-byte after [SEM-3]'s existing string validation. Analyzer
`rationale` and confidence do not enter. Claim evidence uses only
[EVC-9.1]'s `requirement`, `implementation`, `test`, or `counterevidence`
coordinates, with exact reconstructed excerpt hashes and canonical role/path/
span/hash ordering. `claim_hash` is lowercase SHA-256 of canonical JSON for
this exact object.

The model-visible verifier request has exactly:

```text
{
  verify_contract_version: 3,
  packet: <the EVC-9.1 model-visible packet projection>,
  claim: <the claim object above>
}
```

It contains no source snapshot metadata, receipts, analyzer rationale,
analyzer confidence, guide text, trace guidance, skip reason, artifact path,
cache metadata, or policy. `verifier_packet_hash` is SHA-256 of canonical JSON
for that exact request.

The untrusted verifier response is one closed object with exactly:

```text
{
  packet_id,
  claim_hash,
  verdict,
  support_score,
  summary,
  evidence
}
```

`verdict` uses the closed vocabulary above. `summary` is nonblank. Evidence
items use [SEM-5]'s exact role/path/span model fields and are independently
reconstructed from packet bytes. Unknown keys, wrong identities, non-finite
scores, out-of-packet citations, or unsupported roles invalidate the event.
`support` and `refute` each require at least one valid bound citation;
`indeterminate` may use an empty evidence array. An empty refutation therefore
cannot create a disputed policy context.

Verifier claim/result contracts admit `kind = "suppression"`, result schema
3, and the [SEM-6] suppression classifications/codes. The reason-free claim
still excludes analyzer rationale, confidence, policy, dispositions, and
source skip reasons. A suppression declaration's rationale is the packet's
source-authored requirement and remains visible; it is not analyzer
rationale. The verifier may challenge a suppression finding through the
same support/refute/indeterminate result and evidence binding, but BSA006
through BSA008 have no independent failure authority without a future exact
[EVC-10.1] qualification. This revision does not add them to the measured
promotion corpus.

The exact verifier provider input is the code-owned adversarial prompt bytes,
two LF bytes, then canonical JSON for the model-visible verifier request. When
`json_mode = "require"`, the provider JSON Schema is a closed object with the
six response fields above, exact packet and claim identity constants, the
three verdict values, a finite numeric score bounded to `[0, 1]`, a nonblank
summary string, and evidence items restricted to exact packet
`evidence_regions` choices. This is only a generation constraint. Trusted
normalization still revalidates every returned byte and relationship.

Before provider construction, Backstitch derives the offline verify inference
contract:

```text
{
  verify_contract_version: 3,
  verifier_packet_hash,
  claim_hash,
  prompt: {id, version, sha256},
  provider: {
    backend_id, plugin_id, model_id, model_revision,
    adapter_id, adapter_version,
    llm_distribution_version,
    plugin_distribution_name, plugin_distribution_version
  },
  request: {json_mode, temperature, seed, max_tokens, reasoning_effort},
  base_search_epoch,
  effective_search_epoch
}
```

`verify_key` is SHA-256 of canonical JSON for this contract. Cache objects are
immutable and keyed by `verify_key`. A cached row is accepted only after its
object schema, inference contract, key, response hash, identities, score, and
evidence binding are recomputed. Provider provenance never changes the
pre-call key.

`base_search_epoch` is one configured [EVC-5] epoch. In an ordinary analysis,
`effective_search_epoch` equals it. In an [EVC-10.1] evaluation,
`effective_search_epoch` is the trial-specific derivation defined there. Every
finding causes at most one verify request per configured base epoch. There is
no unkeyed retry or fallback under the same event identity.

A cached verifier object contains exactly:

```text
{
  schema_version: 1,
  object_type: "verification-result",
  inference_contract,
  verify_key,
  result,
  provenance,
  raw_response_sha256
}
```

Its canonical result contains exactly:

```text
{
  schema_version: 1,
  packet_id,
  packet_hash,
  claim_hash,
  verifier_packet_hash,
  verify_key,
  verdict,
  support_score,
  summary,
  evidence
}
```

`provenance` contains provider response identity, observed model identity, and
token counts under the existing [SEM-4] opaque provenance rules.
It is required for audit but excluded from every pre-call key. The raw response
hash binds exact returned bytes without storing them in reports.

One aggregate verification event contains exactly:

```text
{
  packet_id,
  packet_hash,
  claim_hash,
  verifier_packet_hash,
  required_epochs: [{base_search_epoch, effective_search_epoch}],
  results: [{
    verify_key, base_search_epoch, effective_search_epoch,
    verdict, support_score, evidence
  }],
  aggregate_state,
  context
}
```

Required epochs and results preserve configured base-epoch order, and every
result pair must equal the corresponding required pair. `aggregate_state` is
`independently_verified`, `disputed`, or `verification_indeterminate`.
`context` is respectively `independently_verified`, `disputed_by_verifier`, or
`verification_indeterminate`. A mechanically or human verified finding may
still have a lower-precedence verifier event, but final policy context composes
through [EVC-6] rather than rewriting this event.

_Implementation mapping_:

- `backstitch/semantic_verification.py`
- `backstitch/semantic_verification_contract.py`

## 4. Derived Evidence Artifacts [EVC-4]

Backstitch has no evidence-case authority object. It has derived artifacts:

- evidence packet JSON Lines and its packet report;
- analysis and verification result objects;
- immutable cache objects;
- analysis, policy, and evaluation reports.

Each artifact states its schema version, exact content identity, source
snapshot identity where applicable, and scope. An artifact never chooses which
source evidence is authoritative. Packet construction always re-derives that
choice from the captured source graph.

There is no proposal schema, proposal validation, activation, deactivation,
active manifest, case root, case ID, case hash, evidence-case conflict token,
or source mutation receipt in v1. No compatibility reader may convert one of
those superseded objects into current alignment authority.

_Implementation mapping_:

- `backstitch/artifact_contracts.py`
- `backstitch/semantic_cache.py`
- `backstitch/semantic_reports.py`

### 4.1 Identity, Canonical JSON, And Receipts [EVC-4.1]

Unless a related active spec defines a narrower projection, canonical JSON is
`json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`
encoded as UTF-8 with no trailing newline. Every identity in this spec uses
lowercase SHA-256 of the named canonical bytes.

A raw source receipt contains exactly:

```text
{
  receipt_version: 1,
  path,
  structural_locator,
  start_line,
  end_line,
  raw_sha256
}
```

Paths are canonical repository-relative POSIX paths. Lines are one-based and
inclusive. `raw_sha256` hashes the exact raw bytes from the beginning of the
start line through the end of the end line, including captured line
terminators inside the span. The empty file has span `1..1` and empty bytes.
The `receipt_hash` is SHA-256 of canonical JSON for the complete receipt.

Candidate identity is:

```text
"candidate:sha256:" + SHA256({
  candidate_identity_version: 1,
  candidate_kind,
  path,
  structural_locator
})
```

Candidate identity is stable across a body-only edit that preserves its
structural locator. Its receipt changes whenever its exact span bytes or
coordinates change. A candidate ID without its addressed snapshot and receipt
does not prove current content.

Artifact integrity and repository currentness are independent. Integrity is
`valid` only after schema, digest, identity, and internal relationships
recompute; otherwise it is `corrupt` and the operation fails. A valid artifact
addressed without a repository comparison has
`artifact_currentness = "unverifiable"`. A repository-addressed comparison
uses exactly:

| Value | Meaning |
|---|---|
| `current` | Artifact source snapshot equals the captured repository snapshot and the artifact validates |
| `stale` | Artifact validates but names a different source snapshot |
| `unverifiable` | No repository address was captured for comparison |

Currentness never follows from filename, modification time, Git status, or a
matching obligation ID alone.

_Implementation mapping_:

- `backstitch/evidence_discovery.py`
- `backstitch/evidence_summary.py`

### 4.2 Structural Locator Grammar [EVC-4.2]

The closed locator kinds are:

```text
markdown-section:<section-id>
markdown-invariant:<section-id>:<invariant-id>
python-file:<canonical-path-sha256>
python-module:<module-name>
python-definition:<qualified-name>:<node-kind>:<same-name-ordinal>
python-reference:<owner-locator-sha256>:<node-kind>:<ordinal>
resolver-issue:<canonical-code>:<target-identity>:<ordinal>
source-declaration:<relation-kind>:<line>:<same-line-ordinal>
```

All components are UTF-8 NFC. An ordinal is the zero-based position among
same-kind nodes in tree-sitter source order after normalization. A definition's
same-name ordinal is among definitions with the same qualified name and node
kind in one module. It therefore distinguishes repeated `def f` or `class C`
statements without using body bytes. `owner-locator-sha256` hashes the complete
canonical structural locator of the enclosing definition or module, so a
reference cannot inherit an ambiguous qualified owner. Node kind is one of
`class`, `function`, `async-function`, `call`, `import`, `name`, or
`attribute`. A locator that cannot be derived without guessing does not mint a
candidate.

A source-declaration locator addresses the exact source marker reported in an
evidence row. `relation-kind` is one of `spec_mapping`, `code_backlink`,
`invariant_declaration`, `invariant_bind`, or `binding_test`. `line` is its
one-based captured source line with no leading zero. Its ordinal is the
zero-based position among declarations of the same projected relation kind on
that line in parser source order. The locator is a receipt address only; it
does not mint a candidate or add alignment authority. Receipt construction
asserts the closed grammar before returning a public row, so an unknown
locator kind cannot ship.

A `python-file` locator addresses a whole-file evidence receipt by SHA-256 of
the NFC canonical repository-relative POSIX path encoded as UTF-8. The receipt
also carries that readable path. This locator is for an exact path-qualified
source evidence atom, including captured targets outside configured code/test
roots. It is independent of `python-module`, which names an unambiguous import
candidate under [EVC-7.2]. Import-root overlap, duplicate module names, or an
identifier-invalid path can block a module candidate without invalidating an
exact file receipt.

Receipt spans are:

| Origin | Span |
|---|---|
| Markdown section or invariant | Exact parser-owned statement/section span, excluding a skip directive from semantic text |
| Python file | Complete captured file addressed by exact repository path |
| Python module | Complete captured file |
| Class, function, or async function | Complete tree-sitter definition beginning at the first decorator |
| Python reference | Complete enclosing definition, or complete module for module scope |
| Binding test | Complete bound test definition beginning at the first decorator |
| Resolver issue | Exact target requirement span; the issue retains its own locator separately |
| Source declaration | Exact one-line mapping, backlink, invariant, or binding marker |

Tree-sitter points are zero-based and end-exclusive. Start line is
`start_point.row + 1`. If `end_point.column == 0` and the end row follows the
start row, inclusive end line is `end_point.row`; otherwise it is
`end_point.row + 1`.

_Implementation mapping_:

- `backstitch/code_parser.py`
- `backstitch/evidence_discovery.py`
- `backstitch/evidence_summary.py`
- `backstitch/markdown_specs.py`

## 5. Verification Aggregation And Provider Resolution [EVC-5]

`support_score` is an ordinal decision aid, not a probability. Policy uses it
only through the closed threshold in [EVC-3]. It must not be called calibrated
unless a future contract defines and measures a calibration target.

Verify has a separate non-secret table for its adversarial prompt, request
controls, aggregation, cache, and budgets. Provider resolution is one explicit
all-or-nothing choice. Packaged defaults contain only `enabled = false`. The
default enabled form reuses analyze's complete resolved provider and cost
descriptor:

```toml
[tool.backstitch.verify]
enabled = true
provider_source = "analyze"      # analyze | override
concurrency = 1
cache_path = ".backstitch/semantic-cache"
cache_mode = "require"            # off | read-write | require
search_epochs = ["1"]             # ordered, unique, nonblank
json_mode = "require"
temperature = 0.0
seed = 42
max_tokens = 512
required_verdicts = 1
minimum_support_score = 0.90
indeterminate = "report"          # allow | report
maximum_provider_calls = 100
maximum_prompt_bytes = 1000000
lock_wait_timeout_seconds = 300
maximum_runtime_seconds = 1800
maximum_estimated_cost_microusd = 1000000
```

The enabled base may also contain optional `reasoning_effort` with the exact
[SEM-9] value domain. Its absence accepts the selected provider's default.

A repository that wants another provider or model uses
`provider_source = "override"` and supplies exactly one complete nested table:

```toml
[tool.backstitch.verify.provider]
backend_id = "llm"
plugin_id = "provider-plugin"
plugin_distribution_name = "provider-distribution"
model = "pkg:service/provider.example/provider-model"
adapter_model_id = "provider-model-id"
model_revision = "repository-declared-revision"
capability_schema_version = 1
capability_revision = "provider-capabilities-2026-07-29"
maximum_input_bytes = 1000000
input_cost_microusd_per_million_tokens = 400000
output_cost_microusd_per_million_tokens = 1600000
input_token_overhead = 256
cost_rate_source = "reviewed source and date"

[tool.backstitch.verify.provider.request_constraints.json_mode]
presence = "required"
allowed_values = ["require"]

[tool.backstitch.verify.provider.request_constraints.temperature]
presence = "required"
allowed_values = [0.0]

[tool.backstitch.verify.provider.request_constraints.seed]
presence = "required"
minimum = 0
maximum = 9223372036854775807

[tool.backstitch.verify.provider.request_constraints.max_tokens]
presence = "required"
minimum = 1
maximum = 2147483647

[tool.backstitch.verify.provider.request_constraints.reasoning_effort]
presence = "forbidden"
```

When disabled, Backstitch makes no verify call, reads or writes no verifier
cache object, and projects no independent verification context. Two disabled
shapes are valid. Minimal disabled contains exactly `enabled = false`. An
enabled or dormant-complete verifier contains every non-request base key shown
above, required request keys `json_mode` and `max_tokens`, and zero or more
optional request keys `temperature`, `seed`, and `reasoning_effort`. Provider
constraints decide which optional fields may be present. A dormant table is
complete when this shape and its selected provider descriptor are complete;
omission of an optional request key is not partial configuration. A dormant
complete table may also contain an optional but complete `verify.eval` table.
Dormant fields receive the same unknown-key, type, range, nonblank, provider-
identity, cost, path, and internal cross-field validation as enabled fields,
but disabled state performs no adapter construction, evaluation-corpus/report
load, cache access, or provider call.

Config/environment/CLI layers apply before final verify-shape validation.
Therefore `--option verify.enabled true` activates a dormant complete
descriptor and applies ordinary enabled validation, while applying it to the
minimal disabled form is exit `2` for missing required fields.
`provider_source` is exactly `analyze` or `override` in enabled and dormant
complete forms.

For `analyze`, the nested provider table must be absent. Backstitch reuses the
fully resolved analyze `backend_id`, `plugin_id`,
`plugin_distribution_name`, canonical-PURL `model`, raw `adapter_model_id`,
`model_revision`, capability schema and revision, normalized request
constraints, maximum input bytes, input/output cost rates, token overhead,
cost-rate source, and descriptor provenance after ordinary config precedence.
`provider_source = "analyze"` requires that complete descriptor to be declared
in resolved config. `--model` or `LLM_MODEL` may be absent or equal that model;
it cannot select another model while retaining the configured revision or cost
metadata. A different model requires an atomic config change to the complete
analyze descriptor, which changes both resolved inference identities and the
qualification selector. Credential resolution follows the one resolved
plugin/provider; the verify contract does not require another credential. The
inherited descriptor must satisfy the same nonblank provider and cached-identity
validation as an override; analyze's optional off-cache resolution cannot
supply guessed or blank verify identity.

For `override`, the nested table is required with exactly every shown scalar
key and every shown `request_constraints` child. It resolves one complete
`ResolvedInference`: stable PURL and raw `adapter_model_id` remain distinct,
the verifier request is frozen and capability-validated before
`RequestIdentity` is derived, and the adapter may only serialize that frozen
request. Partial override, analyze fallback for a missing override field, an
override table in analyze mode, generic-option edits, and unknown nested keys
are invalid. Provider strings are nonblank. Cost fields use [SEM-9]'s exact
rules. The resolved override tuple may equal or differ from analyze's tuple.
Equality is valid; difference is an optional ensemble choice and grants no
additional policy authority.

For `provider_source = "analyze"`, stable identity, raw selector, capabilities,
descriptor provenance, and cost inputs are inherited atomically from the
selected analyzer descriptor, but the verifier freezes and validates its own
independent effective request from the verify base table. An inherited
verifier request that violates the analyzer descriptor's capability
constraints is exit `2` before credential, cache, or provider work. This is a
strict validation break for configurations that previously loaded only
because inherited capability constraints were not enforced; Backstitch does
not silently correct the verifier request.

`required_verdicts` is a positive integer excluding booleans and equals the
length of unique ordered `search_epochs`. `minimum_support_score` is finite in
`[0, 1]`; `indeterminate` is `allow` or `report`; `maximum_prompt_bytes` is a
positive integer. Shared cache, request, runtime, cost-ceiling, and locking
fields use [SEM-9]'s exact value rules and no coercion. The complete resolved
provider/request descriptor enters [EVC-3.1]'s inference contract; config
spelling and `provider_source` do not, so equal resolved contracts have equal
identity. Epoch enters each event key. Operational budgets, concurrency, and
cost rates do not enter the event identity.

Raw selector aliases and descriptor provenance remain audit facts outside
`RequestIdentity`, `analysis_key`, `review_key`, and `verify_key`. Changing
only a raw alias for the same stable descriptor revision therefore preserves
semantic and cache identity; changing stable identity, capability-bearing
descriptor members, or the frozen effective request changes the affected
identity. This contract changes no cache object, analysis/report schema, or
bounded historical reader. Existing receipts remain audit evidence only.

A positive verifier cost ceiling requires a nonblank resolved cost-rate source
and explicit resolved rates/overhead whether they came from analyze or the
override. A zero ceiling disables that budget under [SEM-9]'s existing rule.

Multiple required verify epochs aggregate conservatively:

- one valid `refute` makes the claim `disputed`;
- otherwise, every epoch must return valid `support` at or above the threshold
  for `independently_verified`;
- otherwise, any valid `indeterminate` response or valid support below the
  threshold makes the claim `verification_indeterminate`.

A valid model verdict `indeterminate` follows that last rule. A provider,
cache, malformed-shape, binding, budget, or tool failure is not a model verdict:
it returns exit 2, publishes no aggregate event or current report, and never
becomes `refute` or `verification_indeterminate`. `indeterminate = allow`
records the valid indeterminate event without a debt notice; `report` also
marks that same aggregate event as verification debt and emits one concise
non-failing notice. The event in the closed analysis-report `verification`
object is the complete machine-readable debt record; there is no second debt
array or shadow representation.

Changing prompt, provider identity, request controls, packet bytes, claim
bytes, verifier contract version, effective epoch, or evidence normalization
creates new affected verify keys. Changing the required epoch list, support
threshold, or indeterminate rule changes verifier composition and aggregate
policy identity; it does not rewrite an otherwise identical per-event key.
Newly required epochs still create their own new event keys. Rendering, output
paths, concurrency, policy severity, and timestamps change neither event keys
nor composition identity.

Stronger independently verified policy remains disabled until a committed
evaluation report passes [EVC-10.1]. Failure to qualify does not block
report-only operation.

Until Slice 8 implements and validates the current [EVC-10.1] qualification
artifact, no `BSA*:independently_verified` selector may gain failure authority.
If resolved policy requests such authority, Slice-7 code fails closed before
cache or provider construction with the requalification action. Slice 8 owns
successful qualification loading plus missing, corrupt, failing, and
composition-mismatched artifact cases. `[analyze.eval]` remains historical
schema-2 report-field vocabulary only; settings loading always rejects an
`[analyze.eval]` table under [CFG-6.5].

_Implementation mapping_:

- `backstitch/semantic_verification.py`
- `backstitch/settings.py`

### 5.1 Invocation, Scope, And Publication [EVC-5.1]

`backstitch analyze` has two mutually exclusive input modes:

```text
backstitch analyze --repo-root PATH
  [--packets-output PATH --packet-report-output PATH]
  [--output PATH] [--report PATH]
  [--model MODEL] [--concurrency N]
  [--config PATH | --no-config] [--format text|json]
  [--option KEY VALUE]...

backstitch analyze --packets PATH --packet-report PATH
  [--compare-repo-root PATH]
  [--output PATH] [--report PATH]
  [--model MODEL] [--concurrency N]
  [--config PATH | --no-config] [--format text|json]
  [--option KEY VALUE]...
```

The configuration selection and override grammar composes with [CFG-5.1].
Configuration controls may appear globally before `analyze` or in the
positions shown here, but may not assign the same generic key twice or combine
a generic key with its dedicated alias.

`--repo-root` and `--packets` are required alternatives. Packet replay always
requires `--packet-report`. Current mode forbids input `--packet-report` and
`--compare-repo-root`; historical mode forbids both packet-output flags.
`--packets-output` and `--packet-report-output` must occur together. `--config`
and `--no-config` are mutually exclusive. `--concurrency` is a positive
integer. Existing model/config rules remain [SEM-9].

All four output flags are optional. `--output` writes canonical policy-neutral
result JSONL. `--report` writes the closed analysis report. The packet-output
pair writes the internally derived packet JSONL and packet report. Without an
output flag, that artifact is retained in memory only. Stdout always renders
the final analysis summary: text by default, or the complete analysis report
as canonical JSON for `--format json`. A failed run with no publishable report
prints one line-safe error to stderr and nothing to stdout. This makes the
advertised `backstitch analyze --repo-root PATH` a complete gate invocation.

Current-repository mode owns this sequence:

1. capture one immutable repository snapshot;
2. resolve obligations and readiness from that snapshot;
3. apply [EVC-2.1]'s corpus matrix, failing the whole run before provider work
   for alignment debt while excluding valid skips and non-active rungs;
4. derive packets from the same snapshot and resolved graph;
5. analyze, verify, and project policy;
6. capture a second whole repository snapshot through the same owner;
7. publish current results only when both snapshot identities match.

All requested final artifact paths are staged until step 7. A changed snapshot
returns exit 2 and publishes no current report or policy result. Immutable
cache entries already written for the first snapshot may remain valid facts
about that historical snapshot, but they have no current gate authority.

Each requested artifact resolves distinctly from every other requested output
and from every input artifact. In current mode it must also lie outside every
captured spec/plan/code/test root, must not equal any selected config or extend-
chain file, and must not match any other semantic input path. The directory
containing a config file is not itself a config root and remains eligible when
no other rule excludes it. This check happens before capture. It prevents
publication from changing the semantic snapshot it just certified.

The same exclusion applies to the resolved analyze and verify cache roots,
lock/guard/audit paths, and any provider-local file path Backstitch itself can
write. A configured mutable path that overlaps a semantic input is invalid
configuration before cache or provider construction. Remote provider state is
outside repository currentness.

Each staged artifact is created beside its final path as a unique exclusive
regular file named with the current process ID plus 128 bits of randomness,
written completely, flushed, and closed before the final snapshot comparison.
After a match, Backstitch atomically replaces each final path in dependency order:
`--packets-output`, `--packet-report-output`, `--output`, then `--report`.
A replacement failure is exit 2 and reports which earlier finals were
published. Cross-path replacement is not physically atomic: a later failure or
process crash may leave an earlier final beside an absent or older paired
artifact. A consumer must validate paired digests and reject that orphaned
final as an invalid pair. No current analysis report or gate success is
emitted. The current invocation removes only the exact staging
paths it created and recorded in memory. There is no automatic startup cleanup
or age-based deletion of another run's staging files in v1.

Current mode reports `scope = "current_repository"` and
`artifact_currentness = "current"` only after step 7.

Packet mode validates exact packet bytes and packet report identity, performs
no repository comparison, reports `scope = "historical_snapshot"` and
`artifact_currentness = "unverifiable"`, and judges the internally consistent
packet content under its **claimed historical snapshot**. Without source bytes
or a repository comparison it does not prove that the named snapshot ever
contained those bytes. It cannot emit a current-repository policy claim.
Packet-only analysis summary has the same historical scope.

For explicit audit comparison, packet mode may also receive
`--compare-repo-root PATH`. This captures the repository solely to compute
`artifact_currentness`. A match permits `current`; a mismatch reports `stale`.
The operation remains `scope = "historical_snapshot"` and cannot become the
current gate because it did not derive packets and readiness inside the
start/end capture boundary. `--repo-root` current mode and `--packets` remain
mutually exclusive.

Config discovery for current mode anchors at the resolved repository root.
Config discovery for historical mode anchors at the packet file's parent, as
the packet replay command does. Every `analyze --packets` invocation requires
its paired schema-2 packet report and packet-schema-3 contents. Legacy
packet-schema-2 and unversioned artifacts remain accepted only by bounded
validation and presentation paths; they are never analyzable, rewritten, or
accepted by current, historical schema-3, completeness, or qualification runs.

_Implementation mapping_:

- `backstitch/artifact_publication.py`
- `backstitch/cli.py`
- `backstitch/semantic_analysis.py`
- `backstitch/semantic_application.py`

## 6. Policy And Diagnostic Integration [EVC-6]

Alignment readiness, analyzer judgment, verifier judgment, and policy are
separate records. Policy may make execution stricter but cannot make an
unaligned or skipped obligation executable.

For each semantic classification from [SEM-6], final policy context is exactly
one of `evidence_bound`, `verification_indeterminate`,
`independently_verified`, `mechanically_verified`, `human_verified`,
`disputed_by_verifier`, or `human_rejected`. The noun `candidate` is reserved
for discovered source and is not a semantic context.

Context composition uses this first-matching precedence:

1. an exact matching human `accepted` disposition produces
   `human_verified`; an exact matching `rejected` disposition produces
   `human_rejected`;
2. otherwise, a named deterministic predicate under [SEM-5] produces
   `mechanically_verified`;
3. otherwise, aggregate independent verification produces
   `independently_verified`, `disputed_by_verifier`, or
   `verification_indeterminate`;
4. otherwise, a normalized analyzer finding is `evidence_bound`.

Every lower-precedence observation remains in the analysis report. Precedence
selects policy context only; it does not erase a verifier dispute or human
decision from audit. The old `corroborated` context is read-only legacy input
and normalizes to `evidence_bound`; producers never emit it after coordinated
promotion.

Only `mechanically_verified` and `human_verified` have failure authority by
default. `independently_verified` may have failure authority only for an exact
semantic-code/context selector after [EVC-10.1] enforce qualification passes
for that canonical long code and current derivation/inference identities.
Configuration may spell the code with [SEM-6]'s long code or `BSA00*` alias;
policy resolution normalizes it to the long code before qualification lookup.
Evidence-bound,
indeterminate, and both disputed contexts never cause exit 1. Wildcards may
lower visibility but cannot grant failure authority.

At configuration resolution, every explicit exact
`CODE:independently_verified` selector whose effective level is in
`fail_on` requires `verify.enabled = true` and the configured enforce report to
be present, valid, passing in both its aggregate and exact-code cohorts, and
matched to the current source-derivation algorithms and analyzer/verifier
inference identities. Its corpus digest, trial count, interval/confidence,
sample floors, thresholds, and critical requirement must also equal the current
enforce configuration. Every required aggregate and `<SEMANTIC-code>:` check
must exist and pass; an aggregate
pass cannot substitute for a missing, empty, or failing code cohort. Disabled
verification is invalid config for that selector. Missing, corrupt, failing,
or identity-mismatched qualification is exit 2 before cache/provider work with
`qualification/required_qualification_unavailable`; it never silently lowers
the requested gate to report-only. The problem names the affected selectors,
reason, expected report identity when available, current composed identity, and
the action `Re-run qualification for the current source-derivation,
qualification, and inference contracts or remove the failure-authority
selector.` When no failure-authority selector is
requested, unavailable qualification leaves `independently_verified` advisory
and report-only as before.

That before-cache ordering applies when the configured/current composition is
already sufficient to decide qualification. Evidence-stable read-write may
need [SEM-4]'s sorted review-lock acquisition and baseline recheck to discover
the actual producing analyzer identities. This is the sole permitted cache
work before the final qualification decision. It creates no result or
baseline, constructs no adapter, and makes no provider call. After the recheck,
qualification for the complete selected result set still fails before any
analysis lock, result production, baseline publication, or report publication.

Evidence-stable analyzer reuse does not transfer qualification between
providers. Each carried result retains the analyzer identity that produced
it. When no failure-authority selector is requested, a carried result may
participate in ordinary advisory analysis and current verification under that
honest provenance. When any exact independently-verified selector would gain
failure authority, every analyzer result selected for the run must have the
analyzer identity bound by the configured passing qualification artifact. Any
carried result from another analyzer identity makes qualification unavailable and
exits `2` before provider work or report publication; Backstitch never lowers
the selector or attributes the result to the newly selected model. V1 does
not load a catalog of qualification artifacts. The operator must choose
`result_reuse = "exact-inference"` and establish current-model results under a
qualified composition, or change `search_epoch` and requalify.

Coordinated promotion gives these packaged levels:

| BSA code | evidence_bound | verification_indeterminate | independently_verified | mechanically_verified | human_verified | disputed_by_verifier | human_rejected |
|---|---|---|---|---|---|---|---|
| `BSA001` | warning | warning | warning | warning | warning | info | info |
| `BSA002` | info | info | warning | warning | warning | info | info |
| `BSA003` | warning | warning | warning | warning | warning | info | info |
| `BSA004` | warning | warning | warning | warning | warning | info | info |
| `BSA005` | info | info | info | info | info | info | info |

The canonical `BSA001` through `BSA005` issue family remains owned by [SEM-6].
This spec allocates exactly one EVC audit diagnostic:

| Code | Short | Packaged level | Meaning |
|---|---|---|---|
| `OBLIGATION_SKIPPED` | `BSE001` | info | One valid source-authored skip suppressed semantic evaluation for the addressed obligation |

It is emitted once per valid skip at the marker locator, with context
`source_skip`, obligation ID, and exact reason in the suppression/audit record.
The skip marker does not suppress this diagnostic. Ordinary exact policy may
set BSE001 to error to prohibit skips, or off to hide it from default findings
while retaining audit visibility. No other BSE code is allocated. Deterministic
trace defects retain their existing [SC-*]/[INV-*] canonical codes. Artifact,
budget, input, provider, and snapshot failures are operation problems and exit
2, not suppressible repository findings.

Disposition rules in [SEM-6] apply only to semantic findings. They do not
alter `intent_state`, `alignment_state`, `disposition`, `gate_state`, evidence
summary, candidate trace state, packet bytes, or artifact currentness.

_Implementation mapping_:

- `backstitch/semantic_policy.py`

## 7. Deterministic Candidate Discovery [EVC-7]

`--find-evidence` discovers a closed, deterministic candidate universe from
the same captured source snapshot and resolved report used for readiness. It
does not call a model.

Intent coverage may reuse this read-only definition catalog, accepted snapshot,
and raw resolver graph under [COV-3]. The shared owner preserves every valid
existing candidate identity byte-for-byte; coverage adds only its
`python-module-path:<canonical-path>` fallback where this discovery path
currently emits no module candidate. Coverage classification and worklist
membership do not become candidate trace state, declared evidence, or
alignment authority. Neither consumer reparses source or mutates the shared
catalog.

The closed candidate kinds are:

- `implementation_definition`: module, class, function, or method under a code
  root;
- `test_definition`: module, class, function, or method under a test root;
- `static_reference`: a conservatively resolved Python import, call, name, or
  attribute reference;
- `unresolved_reference`: a plausible local Python relation that the closed
  resolver cannot resolve uniquely;
- `report_issue`: an existing policy- and suppression-independent raw resolver
  issue attributable to the obligation.

Each candidate has one trace state:

| State | Meaning |
|---|---|
| `declared` | Existing source declarations fully establish the candidate's required reciprocal evidence relation |
| `partially_declared` | At least one relevant source declaration exists but reciprocity or a required role is missing |
| `untraced` | No relevant source declaration associates the candidate with the obligation |
| `conflicted` | Ambiguous, duplicate, malformed, or contradictory declarations prevent one relation answer |

`report_issue` candidates represent a resolver's existing evidence that some
relation was attempted or required. They are therefore
`partially_declared` unless the issue is ambiguous, duplicate, malformed, or
contradictory, in which case they are `conflicted`. A `report_issue` candidate
cannot be `declared` or `untraced`.

An untraced heuristic candidate is advisory. It does not by itself change
alignment or exit status. It becomes readiness-blocking only if it exposes an
existing broken source declaration or a separate active spec defines a closed
universal coverage rule. Discovery never silently turns similarity or static
reach into a required evidence link.

The closed discovery bases are `declared_relation`, `invariant_relation`,
`resolver_issue`, `lexical_match`, `static_neighbor`, and
`ambiguous_relation`. One candidate may carry several bases in this order.

The initial seed set for one obligation is:

- every declared evidence owner and binding test;
- every raw resolver issue targeted to the obligation;
- the first `maximum_lexical_seeds` positive lexical matches among class,
  function, and method `implementation_definition` and `test_definition`
  candidates in the complete captured candidate catalog; whole-module
  candidates are not lexical seeds;
- every definition reachable within `static_neighbor_depth` through the
  discovery-v2 collapsed definition graph below, plus the reference candidates
  that orient each traversed hop;
- every same-name ambiguous local definition encountered during that closure.

A path-only Python source declaration seeds only the exact `python-module`
candidate for that file. It never marks definitions or references inside the
file, or candidates below a directory path, as declared. An explicit symbol
seeds only the matching definition owner. This preserves the distinction
between a whole-file human declaration and the graph nodes used to find nearby
advisory candidates.

Discovery algorithm version 2 treats `enclosing_definition` as directed
orientation metadata, never as an undirected closure edge. A resolved
`static_import`, `static_call`, or `static_reference` from a reference
candidate contributes one collapsed hop from that reference's unique enclosing
definition to each uniquely resolved target definition. Both endpoints must be
`implementation_definition` or `test_definition` candidates; a
`python_module`, unresolved reference, or enclosing module is not a collapsed
endpoint. The inverse hop represents the same conservative relation. One
collapsed definition-to-definition hop consumes one `static_neighbor_depth`
unit regardless of its orienting reference. When a hop is selected, its
orienting reference candidate remains in the candidate inventory with
`static_neighbor`; it consumes no additional depth. Ambiguous local targets
remain governed by the same-name expansion below. Therefore selecting a
definition can reach its direct conservative definition neighbors, but lexical
ownership alone cannot pull its enclosing module or unrelated definitions and
references from that module into closure.

Lexical matching is exact and portable. Normalize source strings to UTF-8 NFC,
split their ASCII letter/digit runs at non-alphanumeric bytes, lower-to-upper
camel transitions, and letter/digit transitions, then lowercase. Discard
tokens shorter than three bytes and this closed stop set: `the`, `and`, `for`,
`with`, `from`, `this`, `that`, `must`, `should`, `will`, `not`, `are`, `was`,
`into`, `when`, `where`. Obligation tokens come from its canonical ID, title,
and requirement text. Candidate tokens come from its canonical path, module
name, and qualified symbol. A lexical score is the pair `(shared_token_count,
shared_token_byte_count)`. A positive match has nonzero first component.
Lexical seed selection excludes whole-module, reference, and issue candidates.
A whole-module match would inject a complete file as advisory text, while an
unresolved reference with a generic owner can consume a seed and force a large
same-name ambiguity closure before any owning definition is selected. Modules
remain available when source-declared; references remain available through
conservative static reach from selected definitions. Selection sorts
descending by score, then by candidate ID, and takes the configured prefix.
Tokens do not enter receipts or alignment authority.

Fixed-point expansion follows candidate-ID order. Candidate response ordering
is `(trace_state_order, candidate_kind_order, negative_shared_token_count,
negative_shared_token_byte_count, path, start_line, structural_locator,
candidate_id)`, where trace state order is `conflicted`,
`partially_declared`, `untraced`, `declared` and candidate kind order is the
declaration order above. Negative fields mean larger lexical scores sort
first. Pagination never changes universe membership.

Every candidate returns its identity and receipt, kind, path, owner, span,
ordered discovery bases, lexical score, derived static relations, existing
declared relations, trace state, and a structured `suggested_trace_edits`
array. Guidance names the supported source forms and exact target ID. It is
advice, not a patch. It must not claim that the suggested relation is correct.
For a spec-declared invariant with no implementation target,
`ADD_INVARIANT_BIND` names the owning section's canonical `path#section` ID and
`supported_forms = ["spec_mapping"]`; the human authors that mapping in the
owning section. A code-declared invariant already has its declaration owner as
the target and emits no target-edit advice. `ADD_BINDING_TEST` continues to
name the invariant obligation and the `binding_test` form.

_Implementation mapping_:

- `backstitch/code_parser.py`
- `backstitch/evidence_discovery.py`
- `backstitch/markdown_specs.py`
- `backstitch/resolver.py`

### 7.1 Candidate Spans, Budgets, And Closure [EVC-7.1]

Candidate spans follow [EVC-4.2]. Overlapping candidates remain distinct.
Packet construction separately merges overlapping model-visible text while
retaining candidate accounting and receipt-derived semantic identity.
Discovery-v2 visible-source equality is the role-independent tuple
`(path, start_line, end_line, raw_sha256)`. It affects only repeated snippet
rendering; it never changes a candidate's trace state, discovery bases,
relation membership, receipt hash, trace-summary counts, or source-declared
alignment.
Public candidate IDs, receipts, raw static relations, and candidate ordering
are unchanged from discovery-v1; only closure membership can change. Building
the per-obligation collapsed bridge index inspects each raw static edge once.
Selecting an orienting reference and a definition endpoint remains one unique
closure insertion attempt per identity under the existing work-unit rules.

Deterministic work budgets select or reject a universe. Wall time never selects
a prefix. The work-unit accounting is:

- one unit per catalog node visited;
- one unit per static edge inspected;
- one unit per unique closure insertion attempt;
- one unit per candidate-to-declaration comparison;
- one unit per receipt byte hashed, charged in 4096-byte blocks rounded up.

Catalog overflow, per-obligation candidate overflow, work-unit overflow, file
overflow, snapshot overflow, or packet overflow aborts the complete operation
with `BUDGET_EXHAUSTED`, exit 2, and no partial page, packet, result, or cursor.
An operational deadline may abort the whole operation with `DEADLINE_EXCEEDED`,
exit 2, and no partial output. Repeating an operation on the same snapshot and
configuration produces the same universe regardless of machine speed.

_Implementation mapping_:

- `backstitch/code_parser.py`
- `backstitch/evidence_discovery.py`

### 7.2 Conservative Python Relations [EVC-7.2]

Module identity derives only from captured `.py` files under configured code
and test roots. A root containing `__init__.py` contributes its last component
as a package prefix; another root is an import base. Remove `.py` and a final
`__init__`. Components must be Python identifiers and not keywords. Overlap
that derives different names, duplicate module names, or an empty name is
ambiguous and never guessed.

The resolver supports only:

- absolute and relative `import` and `from ... import ...` forms that resolve
  to one captured module or one captured module-scope definition;
- lexical alias bindings visible after their import and not shadowed by a
  nearer parameter, assignment, definition, target, or deletion;
- direct calls to a unique local definition by local name, imported alias, or
  resolved module-qualified name;
- inverse caller relations derived from those same resolved calls.

Wildcard imports, dynamic imports, re-exports with multiple targets,
higher-order calls, computed attributes, monkey patching, and runtime dispatch
remain unresolved. A plausible local unresolved form becomes an
`unresolved_reference`; an obviously external form may be omitted from the
mandatory universe. The rule is based on captured local module prefixes and
definition names, never on environment imports.

Collapsing a resolved reference for discovery-v2 closure does not create a
public owner-to-target relation. Returned relations remain the original
owner-to-reference `enclosing_definition` and reference-to-target
`static_import`, `static_call`, or `static_reference` rows.

_Implementation mapping_:

- `backstitch/code_parser.py`
- `backstitch/evidence_discovery.py`

## 8. Obligation Interface [EVC-8]

The CLI is the complete human, script, and CI interface. MCP is an optional
local context-efficient adapter over the same read core. Neither surface has
more alignment authority than the other.

The public bootstrap loop is:

```text
backstitch obligation list
backstitch obligation OBLIGATION_ID
backstitch obligation OBLIGATION_ID --summarize-evidence
backstitch obligation OBLIGATION_ID --find-evidence
backstitch obligation OBLIGATION_ID --candidate CANDIDATE_ID
backstitch guide alignment
backstitch check
backstitch analyze --repo-root PATH
```

`--find-evidence` is intentionally re-runnable. Every invocation captures the
addressed repository as it exists for that invocation and returns the accepted
snapshot identity. A saved candidate report is historical as soon as its
snapshot differs from the repository; users refresh it by running the same
command again. `--summarize-evidence` independently reads the current
human-reviewed source declarations, and `analyze --repo-root` independently
builds the current gate packet from those declarations. Neither consumes a
saved candidate report as authority.

No public v1 command named `proposal`, `validate`, `activate`, `deactivate`,
`skip`, or `unskip` exists. `backstitch check` remains the deterministic
repository-wide traceability gate. There is no separate obligation-specific
check pipeline.

`backstitch coverage` is a separate deterministic read-only aggregate over
the same accepted snapshot, definition inventory, and raw graph. It may list
uncovered definitions and requirement complements, but creates no obligation
proposal, disposition, activation, evidence relation, or durable state.
Reviewers may use this section's obligation reads and guidance while triaging
[COV-6]'s worklist; only an ordinary reviewed source diff changes later
coverage or alignment.

`obligation list` includes executable suppression obligations in canonical
identity order. `obligation get` returns their declaration, normalized rules,
matched issue count, and current readiness. Existing evidence discovery and
mutation guidance do not run for this kind: suppression packet evidence is
deterministically derived from the declaration, normalized rules, matched
issues, and accepted snapshot. Unsupported summarize/find/get-candidate
selectors return the existing closed invalid-operation envelope; no parallel
suppression API is added.

_Implementation mapping_:

- `backstitch/cli.py`
- `backstitch/obligation_api.py`

### 8.1 Teaching And Progressive Disclosure [EVC-8.1]

`backstitch guide alignment` prints the installed versioned quick start. It
teaches obligation identity, evidence summary, candidate trace states,
supported mapping/backlink/invariant-target/binding-test/skip forms, review ownership, and
the commands above. It does not restate payload schemas or normative rules.

`skills/backstitch-alignment/SKILL.md` is a thin repository workflow adapter.
It tells an agent when to list, summarize, discover, inspect, and hand a source
diff to a human for review. It points to the installed guide and command help.
It must not contain a second protocol contract.

The installed guide artifact is exactly:

```text
{
  guide_schema_version: 1,
  guide_id: "alignment",
  guide_version: 2,
  backstitch_version,
  content_sha256,
  content
}
```

`content` is the exact installed UTF-8 Markdown; `content_sha256` hashes those
bytes. Text format prints `content` unchanged. JSON and MCP return the complete
artifact. A guide content change increments `guide_version`; the hash detects
an unincremented edit. Guide identity is measurement provenance and never
enters source alignment or packet identity.

CLI help teaches the first useful bootstrap command and the distinction
between declared evidence and candidates. A zero-context user must not need MCP
or repository-specific agent guidance to discover the complete loop.

_Implementation mapping_:

- `backstitch/alignment_guide.py`

### 8.2 Snapshot Capture And Stateless Addressing [EVC-8.2]

There is no `init`, hidden session, server handle, or mutable draft. Every
repository operation uses an explicit `--repo-root` or the inspectable current
directory. When [EVC-8.6]'s adapter is implemented, every MCP repository tool
requires `repo_root`. The MCP server is started with one allowed root; a tool
root must resolve to that same contained root. MCP framing may echo the allowed
canonical root as transport metadata outside the core result. CLI text prints
the resolved root in its orientation header; CLI JSON is the canonical core
object and excludes it. Each implemented surface identifies the captured
snapshot inside the core result. Root bytes never enter semantic identity.

The snapshot owner captures one immutable view of all included config, spec,
plan, code, and test inputs. Readable files contribute exact bytes. A file that is
stably unreadable across an accepted attempt contributes an `unreadable`
manifest row and the existing `FILE_UNREADABLE` issue, not guessed bytes. An
attempt:

1. enumerates canonical repository-relative POSIX paths in Unicode code-point
   order and records one `lstat` tuple per input;
2. opens each readable path without following symlinks, compares `fstat` with
   its `lstat`, reads once through a bounded stream, and repeats `fstat`;
3. repeats the complete sorted inventory and every `lstat` tuple;
4. accepts only if membership and every compared tuple are unchanged.

The exact comparison tuple is `(st_dev, st_ino, file_type_and_permission_mode,
st_size, st_mtime_ns, st_ctime_ns)`. Nanoseconds are required; a platform that
cannot supply them is unsupported and exits 2. `file_type_and_permission_mode`
is `stat.S_IFMT(st_mode) | stat.S_IMODE(st_mode)`. A readable file's pre-open
`lstat`, first `fstat`, second `fstat`, and repeated `lstat` tuples must all be
equal. An unreadable row requires equal pre/post/repeated `lstat` tuples and
the same platform-neutral error class on both bounded open attempts.

On POSIX, the owner walks from an already opened repository directory
descriptor. Each intermediate component is opened with
`O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`; the final component uses
`O_RDONLY|O_NOFOLLOW|O_CLOEXEC`. It rejects empty, dot, dot-dot, absolute,
backslash, NUL, non-directory intermediate, symlink, and non-regular final
components. V1 supports only `os.name == "posix"` systems that expose directory
file descriptors, `O_NOFOLLOW`, `O_DIRECTORY`, `O_CLOEXEC`, and nanosecond stat
fields with the behavior above. Every other platform returns
`UNSUPPORTED_PLATFORM`, exit 2, before repository traversal. V1 uses this exact
descriptor-walk algorithm; non-POSIX or alternative open algorithms require a
new reviewed contract. It never falls back to a path-based open that follows
symlinks.

Membership, tuple, or readable/error-class change is a torn attempt: discard
every byte and retry from an empty buffer up to `snapshot_capture_attempts`,
which defaults to 3. No bytes or metadata are mixed across attempts. A stable
symlink, escape, non-regular object, unsupported platform, permanent budget
overflow, or invalid root is not retried. Exhausting torn attempts returns
`SNAPSHOT_UNSTABLE` with exact attempt count, exit 2, and no partial core
result or artifact.

Inventory applies [SC-3]/[CFG-6]'s root and exclusion selection. The no-follow
open and containment algorithm is owned here because the active specs do not
yet define it. Replacement between enumeration and open therefore discards the
attempt rather than changing the addressed file.

The accepted inventory also retains one frozen path catalog. It contains each
existing configured spec, plan, code, and test root; every non-excluded
directory and regular file below those roots, including objects whose suffix
does not make them semantic file inputs; and every exact repo-relative mapping
target declared by the captured specs, even when that target is outside a
configured root. Catalog rows are exactly
`{path, kind}`, where `kind` is `directory` or `regular_file`; they are unique
and ordered by path. The capture records and compares the full stat tuple for
every row in both inventory passes, but clone-local stat values do not enter
semantic identity. A missing configured root has no root row. Therefore the
normalized configured roots plus the catalog distinguish a missing root from
an existing empty root. Resolver path existence and directory-ownership checks
use only this catalog. `maximum_catalog_items` bounds its complete row count;
overflow is `BUDGET_EXHAUSTED` for `catalog_items`, never truncation.

Declared-target expansion is part of the same bounded whole-capture owner. An
attempt captures the configured-root/config view plus the previous exact
target set, parses only those captured spec bytes to derive the current exact
target set, and accepts only when both sets are equal. A changed target set
discards the attempt and retries from empty with the newly derived set. A
regular-file target outside the configured roots becomes a readable or stably
unreadable semantic file row so path-symbol resolution consumes captured bytes;
a directory target is catalog-only. Target-set convergence, torn inventory,
and metadata retry share the one `snapshot_capture_attempts` ceiling: no more
than three whole capture attempts occur by default. Exhaustion has the same
`SNAPSHOT_UNSTABLE` result and publishes no partial view.

Canonical catalog and target paths are Unicode NFC repository-relative POSIX
strings. No absolute path, backslash, NUL, empty component, dot-dot component,
or surrogate code point is valid. The already-open repository root is the one
special row `.`. A trailing slash on an exact directory mapping is removed
before lookup (`pkg/` addresses catalog path `pkg`); no other dot component is
retained. If two native inventory names or declared tokens normalize to the
same canonical path, capture fails as invalid input instead of choosing one.
Sorting is Unicode code-point order over these canonical strings.

Before effective configuration is known, the bootstrap loader reads at most
64 config files, 1,000,000 raw bytes per file, and 5,000,000 raw bytes over the
resolved extend chain. It applies bounded reads before TOML parsing. Overflow,
cycle, unreadable config, or changed config identity is exit 2. Config
discovery and `extend` may select a layer outside `--repo-root` as [CFG-3] and
[CFG-6] permit. The bootstrap loader therefore retains each layer's exact raw
bytes and stable read identity in base-to-leaf application order. The snapshot
revalidates each layer with a bounded no-follow read before and after every
whole capture attempt. The accepted repository snapshot must contain the exact
same config bytes used to derive its inventory and semantic settings;
otherwise the whole attempt is discarded. An absolute config path is
operational capture metadata and never enters snapshot identity.

After capture, parsers, resolver, obligation readiness, discovery, receipts,
and packet construction receive only the immutable view and cannot reopen
repository source. List, evidence summary, and deterministic `check` may report
a stable unreadable file and continue as [SC-4] requires. Evidence that needs
that file is incomplete. Default obligation detail includes discovery-derived
candidate counts, so it has the same completeness boundary as
`--find-evidence` and `--candidate`. Those three reads, packet generation, and
current semantic analysis require a complete semantic catalog; any included
unreadable config, spec, plan, code, or test input is `SOURCE_UNREADABLE`, exit
2, for those operations. The intentional final capture in current analyze mode
is a new whole snapshot through the same owner.

Snapshot identity is SHA-256 of canonical JSON for:

```text
{
  identity: "backstitch-repository-snapshot",
  version: 1,
  config_inputs: [{ordinal, raw_sha256}],
  files: [{path, state, raw_sha256, error_class}],
  catalog_sha256,
  missing_roots,
  semantic_config: {
    profile_name,
    spec_roots, plan_roots, code_roots, test_roots, exclusions,
    planned_spec_globs, exploratory_spec_globs,
    section_required_roles,
    maximum_candidate_items, maximum_catalog_items, maximum_lexical_seeds,
    maximum_snapshot_files, maximum_file_bytes, maximum_snapshot_bytes,
    maximum_work_units, maximum_packet_bytes, maximum_packet_report_bytes,
    static_neighbor_depth
  },
  algorithms: {
    snapshot_algorithm_version,
    obligation_algorithm_version,
    discovery_algorithm_version,
    packet_contract_version,
    normalization_version
  }
}
```

`config_inputs` contains every selected non-packaged config layer in exact
base-to-leaf order. `ordinal` is its zero-based position and `raw_sha256`
hashes the retained exact bytes. Rows contain no path. A repository-contained
config also remains a file row so repository inventory changes remain visible;
file and byte counts count that physical input once. A config outside the
repository exists only in `config_inputs`, but its exact bytes remain in the
immutable internal view. Changing its location without changing the complete
ordered bytes does not change semantic identity.

File rows include every repository-contained semantic input and sort by path.
`state` is `readable` or `unreadable`; readable rows require `raw_sha256` and
null `error_class`, while unreadable rows require null `raw_sha256` and one
stable platform-neutral class: `permission`, `not_regular`, or `io`. Arrays
are unique and Unicode-code-point sorted after normalization.
`missing_roots` is the unique ordered array of normalized configured roots
that have no accepted directory row. `catalog_sha256` is lowercase SHA-256 of
canonical JSON for exactly `{catalog_version: 1, paths: <the complete ordered
catalog row array>, missing_roots}`. The accepted immutable snapshot retains
those rows for downstream resolution; they are not expanded in the public
identity document. `semantic_config` binds the normalized roots and
exclusions. A catalog membership, kind, or missing-root change therefore
changes snapshot identity even when semantic file bytes do not.
Absolute roots become contained repository-relative POSIX paths. Page sizes,
response byte limits, deadline, retry count, output paths, policy levels, and
provider configuration are operational and excluded.

_Implementation mapping_:

- `backstitch/check_application.py`
- `backstitch/check_pipeline.py`
- `backstitch/filesystem_io.py`
- `backstitch/obligation_runtime.py`
- `backstitch/repository_snapshot.py`
- `backstitch/resolver.py`
- `backstitch/scan_exclusions.py`
- `backstitch/settings.py`

### 8.3 Exact CLI Grammar [EVC-8.3]

The new command grammar is:

```text
backstitch obligation list
  [--repo-root PATH] [--cursor TOKEN] [--limit N] [--format text|json]
  [--active-only]
  [--alignment-state untraced|partial|complete|invalid]...
  [--gate-state not_executable|executable]...
  [--kind section|invariant|suppression]...
  [--reason BLOCKING_REASON_CODE]...

backstitch obligation OBLIGATION_ID
  [--repo-root PATH] [--format text|json]
  [--summarize-evidence | --find-evidence |
   --candidate CANDIDATE_ID]
  [--cursor TOKEN] [--limit N]

backstitch guide alignment [--format text|json]

backstitch mcp --repo-root PATH              # when the Phase D adapter ships

backstitch analyze --repo-root PATH
  [--packets-output PATH --packet-report-output PATH]
  [--output PATH] [--report PATH]
  [--model MODEL] [--concurrency N]
  [--config PATH | --no-config] [--format text|json]
  [--option KEY VALUE]...

backstitch analyze --packets PATH --packet-report PATH
  [--compare-repo-root PATH]
  [--output PATH] [--report PATH]
  [--model MODEL] [--concurrency N]
  [--config PATH | --no-config] [--format text|json]
  [--option KEY VALUE]...
```

Every grammar above for a command that consumes configuration composes with
[CFG-5.1]'s global or command-local
`[--config PATH | --no-config] [--option KEY VALUE]...` grammar. This includes
`obligation`; `guide`, conditional `mcp`, and other commands consume
configuration only where their own governing sections explicitly say so.

The three detail selectors are mutually exclusive. `--cursor` and `--limit`
are valid only for `list`, `--summarize-evidence`, and `--find-evidence`.
Candidate detail is one bounded item and is not paginated. Unknown IDs,
snapshot-mismatched cursors, selector misuse, and invalid limits are exit 2.
Analyze flag compatibility, output ownership, path rules, stdout, and config
anchors are exactly [EVC-5.1].

The five list filters are valid only for `obligation list`. Repeated values
within one filter family combine with OR; different families combine with AND.
`--active-only` retains only `obligation_rung = "active"` and
`disposition = "evaluate"`. Filtering occurs before pagination without
changing canonical row order. The complete normalized filter object enters
cursor identity. Reusing a cursor with a different filter object is
`CURSOR_INVALID`; it never silently changes the addressed result set.

The MCP line is conditional. CLI is the complete required interface. A Phase D
deferral may omit the MCP command, extra, tools, and resource without weakening
CLI, packet, or semantic qualification. Once an installed distribution
advertises `backstitch mcp`, all of [EVC-8.6] and its conditional verification
requirements apply.

`obligation list` is the bootstrap report. It returns one paginated `entries`
array ordered by `(path, start_line, entry_type_order, entry_identity)`, where
entry type order is `unaddressable_intent` then `obligation`. Each row is
either:

```text
{
  entry_type: "obligation",
  entry_identity,
  obligation_id, kind, path, start_line, title,
  intent_state, alignment_state, disposition, obligation_rung, gate_state,
  blocking_reason_codes
}
```

or:

```text
{
  entry_type: "unaddressable_intent",
  entry_identity,
  diagnostic: {code, path, line, message},
  excerpt,
  action
}
```

For an obligation, `entry_identity = obligation_id`. For unaddressable intent,
it is `"unaddressable:sha256:" + SHA256(canonical JSON of {code, path, line,
ordinal})`; ordinal is the zero-based same-code/path/line issue occurrence in
parser source order. `start_line` for ordering is the diagnostic line. Null
diagnostic line sorts as zero and is serialized as null.

No discoverable intent returns exit 0 with an empty array,
`bootstrap_state = "no_intent"`, and action `ADD_OR_CONFIGURE_SPEC_INTENT`.
Otherwise bootstrap state is `intent_found`. Untraced obligations are normal
obligation rows and are never hidden among errors.

Default obligation detail returns exactly one compact orientation record with
identity, source locator, kind, the four readiness facts, required roles,
counts by evidence role and candidate trace state, ordered blocking reasons,
snapshot identity, and ordered next actions. It does not inline snippets and
makes no artifact-currentness claim.

The operation-specific results are closed:

```text
obligation.list result = {
  bootstrap_state,
  applied_filters: {
    active_only,
    alignment_states,
    gate_states,
    kinds,
    reasons
  },
  readiness_summary: {
    total,
    active_evaluate,
    executable,
    skipped,
    alignment_debt,
    blocked,
    out_of_scope,
    reason_counts: [{code, count}]
  },
  filtered_count,
  entries,
  next_cursor
}

obligation.get result = {
  obligation_id, kind, path, start_line, end_line, title,
  intent_state, alignment_state, disposition, obligation_rung, gate_state,
  required_roles,
  evidence_counts: {implementation, test, binding_test},
  candidate_counts: {
    declared, partially_declared, untraced, conflicted
  },
  blocking_reasons: [{code, role, relation_kind, issue_identity}],
  next_actions
}
```

`bootstrap_state` is `no_intent` or `intent_found`. `kind` is `section` or
`invariant` in schema-1 historical examples and additionally `suppression` in
the current schema-2 envelope. Applied-filter arrays use their declaration
order and contain no duplicates. Summary buckets are disjoint and recompute
from the filtered inventory before pagination; reason counts contain every
blocking reason with a nonzero count in declaration order. `filtered_count`
equals the filtered row population, including unaddressable intent rows.
Count fields are nonnegative integers. Nullable `role`,
`relation_kind`, and `issue_identity` are present on every blocking row.
Blocking reason code is one of `IMPLEMENTATION_UNTRACED`,
`IMPLEMENTATION_PARTIAL`, `TEST_UNTRACED`,
`TEST_PARTIAL`, `INVARIANT_TARGET_MISSING`, `BINDING_TEST_MISSING`,
`TRACE_CONFLICT`, `OUT_OF_GATE_SCOPE`, or `SKIPPED`. Rows sort by this
declaration order, then role, relation kind, and issue identity. `next_actions`
is an ordered array of [EVC-8.4] guidance codes.

`--summarize-evidence` returns exact declared evidence rows. Each row contains
role, source path, symbol, owner, start/end lines, declared relation kinds,
reciprocity state (`complete`, `one_sided`), receipt, bounded excerpt, and a
nullable `declared_target`. For a valid atomic code owner, source coordinates
and receipt name that owner. A one-sided or broken mapping atom preserves its
authored target token in `declared_target`; a complete reciprocal row may
represent more than one mapping and therefore leaves that scalar null. Its
ordered declaration entries preserve every authored target instead. A broken
mapping is an honest one-sided declaration row: source coordinates and receipt
name the spec mapping line, while `declared_target` preserves its unresolved or
ineligible target token. Broken declarations never masquerade as code receipts.
Every row also carries ordered `declarations` entries with exact
`relation_kind`, source `path`, source `line`, one-line receipt, and nullable
`declared_target`. Thus a complete reciprocal row exposes both the spec mapping
and code backlink declaration locations; the row's primary code receipt never
stands in for a declaration it does not cover.

`--find-evidence` returns the candidate rows defined by [EVC-7].
`--candidate` returns the exact full receipt span and bounded structural
neighbors for one discovery-minted candidate. It never accepts an arbitrary
path as a substitute identity.

Their closed results are:

```text
obligation.summarize_evidence result = {
  obligation_id,
  alignment_state,
  disposition,
  items: [{
    role, path, symbol, owner, start_line, end_line,
    relation_kinds, reciprocity_state,
    receipt, excerpt, declared_target,
    declarations: [{relation_kind, path, line, receipt, declared_target}]
  }],
  next_cursor
}

candidate_relation = {
  relation_kind, source_candidate_id, target_candidate_id,
  source_locator, target_locator
}

trace_advice = {
  guidance_code, target_id, evidence_role,
  supported_forms, review_warning
}

candidate = {
  candidate_id, candidate_kind, path, owner, start_line, end_line,
  structural_locator, receipt,
  discovery_bases, lexical_score: {
    shared_token_count, shared_token_byte_count
  },
  static_relations, declared_relations,
  trace_state, suggested_trace_edits
}

obligation.find_evidence result = {
  obligation_id,
  candidates: [candidate],
  next_cursor
}

obligation.get_candidate result = {
  obligation_id,
  candidate,
  source: {receipt, text, text_sha256},
  neighbors: [{candidate_id, relation_kind, direction}]
}
```

`owner`, `symbol`, source/target candidate IDs, and source/target locators are
present and nullable where a relation kind has no such endpoint. Static and
declared relation fields are arrays of `candidate_relation`.
`suggested_trace_edits` is an array of `trace_advice`, including an empty array
when no supported advice applies. `direction` is `incoming` or `outgoing`.
Relation rows sort by `(relation_kind, source_locator, target_locator,
source_candidate_id, target_candidate_id)`, treating null as empty string.
Discovery bases use [EVC-7]'s order. `supported_forms` is a nonempty ordered
subset of `spec_mapping`, `code_backlink`, and `binding_test`.
`review_warning` is the fixed sentence `Advice is not evidence; review the
source relation before editing.` Suggested edits sort by guidance-code order,
target ID, role, and supported forms. Candidate neighbors sort by
`(relation_kind, direction, candidate_id)`.

Candidate source `receipt` equals the candidate receipt. `text` is its exact
raw span decoded as UTF-8 with replacement for invalid byte sequences and no
newline normalization. `text_sha256` hashes the resulting UTF-8 bytes. Raw
receipt identity still hashes original bytes; replacement-decoded text never
substitutes for it.

_Implementation mapping_:

- `backstitch/cli.py`
- `backstitch/evidence_discovery.py`
- `backstitch/evidence_summary.py`
- `backstitch/obligation_api.py`
- `backstitch/obligations.py`
- `backstitch/packet_application.py`

#### 8.3.1 Configuration [EVC-8.3.1]

The initial configuration is:

```toml
[tool.backstitch.obligations]
section_required_roles = ["implementation"]
page_size = 5
maximum_page_size = 100
maximum_response_bytes = 65536
maximum_candidate_items = 2000
maximum_catalog_items = 100000
maximum_lexical_seeds = 10
maximum_snapshot_files = 20000
maximum_file_bytes = 5000000
maximum_snapshot_bytes = 100000000
maximum_work_units = 2000000
maximum_packet_bytes = 10000000
maximum_packet_report_bytes = 10000000
maximum_call_seconds = 10.0
snapshot_capture_attempts = 3
static_neighbor_depth = 1
```

`section_required_roles` is a unique ordered subset of `implementation` then
`test` and must contain `implementation`. All integer values except
`static_neighbor_depth` are positive; that depth may be zero.
`maximum_response_bytes >= 16384`; `page_size <= maximum_page_size`;
`maximum_snapshot_bytes >= maximum_file_bytes`; `maximum_packet_bytes >=
16384`; `maximum_packet_report_bytes >= 16384`; `maximum_call_seconds` is
finite and positive;
`snapshot_capture_attempts` is in `[1, 10]`; and `static_neighbor_depth` is in
`[0, 3]`.

Page and response limits affect presentation only. Candidate, catalog,
lexical-seed, snapshot, file, work, packet, role, and static-depth settings
enter the snapshot identity because they can change readiness, packet
membership, or whether the complete audit artifact can be emitted. A deadline
aborts an operation but never truncates its deterministic result.

There is no repository ID, case root, manifest path, proposal limit,
activation option, or source-write option. Clone-local absolute paths do not
enter semantic identities.

_Implementation mapping_:

- `backstitch/repository_snapshot.py`
- `backstitch/settings.py`

#### 8.3.2 Source-Authored Skip [EVC-8.3.2]

One obligation may carry one exact source disposition:

```markdown
## Trace Graph [SC-4] <!-- backstitch: skip-obligation [SC-4] "Generated code is checked downstream." -->
```

The equivalent directive-block forms are accepted before body text:

```markdown
<!-- backstitch: skip-obligation [SC-4] "Generated code is checked downstream." -->
_Traceability: skip-obligation [SC-4] "Generated code is checked downstream."_
```

One ordinary [EXC-4] `_Traceability: meta` or `_Traceability: ignore ...`
directive may coexist in the same block. Its canonical position is first,
followed immediately by the standalone skip line. An inline heading skip is
followed by the ordinary directive on the next line. More than one ordinary
directive, a standalone skip before the ordinary directive, interleaving body
text, or a second skip for the same target is invalid syntax. Ordinary
traceability policy and skip disposition are parsed independently; neither
consumes or suppresses the other.

The target is the owning section ID or one invariant declared in that same
Markdown section. The reason is one strict JSON string. Decoded text must be
nonblank, at most 4096 UTF-8 bytes, and contain no CR, LF, U+2028, or U+2029.
HTML forms must contain no raw `--`, `<`, or `>` inside the JSON token; authors
use JSON Unicode escapes when needed.

The marker is invalid in a preamble, prose, code block, non-owning section,
Python source, or more than once for one obligation. Malformed syntax,
placement, target ownership, coexistence order, or duplicate skip emits
`SUPPRESSION_INVALID_SYNTAX`/`BSX004`; a missing or blank reason emits
`SUPPRESSION_REASON_MISSING`/`BSX010`; a well-formed target with no parsed
owner emits `SUPPRESSION_UNUSED`/`BSX001`. All three have packaged level
`warning`, are reported through ordinary hygiene policy/audit, and leave
`disposition = evaluate`. They do not cause strict-loader exit 2 merely
because the recognized skip form is bad. `allow_unknown_keys` has no effect on
this reserved grammar. Invalid config or invocation syntax remains exit 2
under [EXC-8]. Valid syntax sets `disposition = skipped`; absence sets
`evaluate`.

The parser excludes a valid directive from requirement text and model input
but retains its exact reason in audit output. The source bytes still enter the
repository snapshot. `--show-suppressions` lists every valid skip with target,
reason, source locator, and effective policy. A skip suppresses semantic
evaluation only. It suppresses no trace, identity, syntax, containment,
currentness, or artifact-integrity problem.

Every valid marker also emits `OBLIGATION_SKIPPED`/`BSE001` as [EVC-6]
defines. This is the policy hook for a repository that prohibits skips; no
second `allow_skips` setting exists.

Backstitch does not write or remove this marker. CLI, guide, and implemented
MCP output may show the exact form and location an agent or human could edit.
The resulting source diff remains subject to ordinary human review.

A code-only invariant has no valid v1 skip location. Backstitch does not infer
a related Markdown section or suggest inserting a skip in Python. To make such
an invariant skippable, a human must first move or add its declaration to an
ID-bearing Markdown section through an ordinary reviewed source change.

_Implementation mapping_:

- `backstitch/check_pipeline.py`
- `backstitch/exclusions.py`
- `backstitch/markdown_specs.py`
- `backstitch/models.py`
- `backstitch/reporting.py`

### 8.4 Evidence Summary And Discovery Results [EVC-8.4]

The transport-neutral core result envelope is:

```text
{
  schema_version: 2,
  operation,
  snapshot: {snapshot_hash, file_count, byte_count, unreadable_count} | null,
  result,
  guidance: [{code, message, action}],
  problems: [{code, message, action, details}]
}
```

`operation` is one of `obligation.list`, `obligation.get`,
`obligation.summarize_evidence`, `obligation.find_evidence`, or
`obligation.get_candidate`. Success has an operation-specific `result` and no
problems. Failure has null result and one or more ordered problems. Snapshot is
null exactly when failure occurs before one capture is accepted. Core JSON
contains no absolute root, timestamps, transport IDs, ANSI text, or provider
metadata.

Schema 2 is the current live obligation-command envelope. All operation
producers and CLI/MCP consumers change together; it is not a persisted
artifact and has no permissive schema-1 compatibility reader.

The closed guidance codes are:

- `ADD_OR_CONFIGURE_SPEC_INTENT`;
- `FIX_OBLIGATION_IDENTITY`;
- `ADD_RECIPROCAL_MAPPING`;
- `ADD_RECIPROCAL_BACKLINK`;
- `ADD_INVARIANT_BIND`;
- `ADD_BINDING_TEST`;
- `REVIEW_UNTRACED_CANDIDATE`;
- `REVIEW_CONFLICTED_TRACE`;
- `REVIEW_SKIP_REASON`;
- `RUN_DETERMINISTIC_CHECK`;
- `RUN_CURRENT_ANALYSIS`.

Every success carries at least one applicable guidance row. Failure guidance
is carried by each problem's required action and the top-level guidance array
is empty. Guidance rows sort by the declaration order above, then message and
action. Message and action are nonblank, line-safe strings. Guidance is closed
advice. It is never evidence and never applied automatically.

The closed operation problem codes are:

- `INVALID_INPUT`;
- `UNSUPPORTED_PLATFORM`;
- `NOT_FOUND`;
- `CURSOR_INVALID`;
- `SNAPSHOT_UNSTABLE`;
- `SOURCE_UNREADABLE`;
- `BUDGET_EXHAUSTED`;
- `DEADLINE_EXCEEDED`;
- `INTERNAL_ERROR`.

Problem details are a closed union:

```text
INVALID_INPUT:       {field, reason}
UNSUPPORTED_PLATFORM:{platform}
NOT_FOUND:           {identity}
CURSOR_INVALID:      {reason}
SNAPSHOT_UNSTABLE:   {attempts}
SOURCE_UNREADABLE:   {path, error_class}
BUDGET_EXHAUSTED:    {budget, limit, observed}
DEADLINE_EXCEEDED:   {
  limit_milliseconds,
  phase,
  configured_key,
  cooperative_tolerance_milliseconds
}
INTERNAL_ERROR:      {}
```

Fields and reasons are nonblank line-safe strings. Attempts, limits,
observations, and milliseconds are nonnegative integers. Budget is one of
`candidate_items`, `catalog_items`, `snapshot_files`, `file_bytes`,
`snapshot_bytes`, `work_units`, or `response_bytes`.
`error_class` uses [EVC-8.2]. Problems sort by the code declaration order,
then path, field, identity, reason, and canonical details bytes, with absent
sort fields as empty strings.

One absolute monotonic deadline begins immediately before snapshot capture and
passes through catalog construction, relation derivation, closure,
candidate-detail work, packet materialization, and packet accounting.
Checkpoints run before and after each repository file read and at bounded work
unit intervals. Discovery work samples its monotonic clock at phase entry and
after no more than 64 work-budget checkpoint requests; receipt hashing samples
before the next bounded block. The closed deadline phases are `snapshot`, `catalog`,
`relations`, `closure`, `candidate_detail`, `packet_materialization`, and
`packet_accounting`. `configured_key` is exactly
`obligations.maximum_call_seconds`; `cooperative_tolerance_milliseconds` is
`100`. A fake-monotonic-clock firing test must detect cancellation within that
tolerance. Blocking operating-system reads and scheduler suspension are
outside the cooperative wall-time guarantee. The problem action contains a
syntactically valid recovery command such as
`--option obligations.maximum_call_seconds 30`.

Those seven phases plus terminal `complete` form the closed ordered progress
vocabulary. Events contain completed work units, nullable total work units,
and a line-safe current identity. Progress is best effort and noncanonical.
Only a TTY stderr adapter renders it. It never enters stdout, this envelope,
packet or report bytes, cache identity, or exit classification. A
progress-sink failure disables later progress and does not change the domain
operation.

Each problem has a line-safe message, one required action, and only bounded
non-secret details. Tracebacks, secrets, provider raw responses, and source
bytes outside the addressed repository are forbidden.

Artifact, provider, output, cache, and semantic-normalization failures belong
to [SEM-7]'s analysis problem union, not this five-operation read envelope.

A page cursor is unpadded base64url canonical JSON followed by a period and
the lowercase SHA-256 of those decoded JSON bytes. Its object has exactly
`cursor_version = 2`, `operation`, `snapshot_hash`, nullable
`obligation_id`, `selector`, `filters`, `limit`, and `after`. `filters` is the
complete normalized [EVC-8.3] list-filter object and is empty for operations
that do not support list filters. `after` is the complete
last-row ordering tuple. A malformed digest, changed snapshot, wrong operation,
wrong obligation, wrong selector, changed filters, or changed limit is
`CURSOR_INVALID`.
Evidence-summary rows order by `(role_order, path, start_line, end_line,
symbol_or_empty, ordered_relation_kinds, declared_target_or_empty)`, where role
order is `implementation`, `test`, then `binding_test`. The evidence cursor's
`after` is exactly that seven-field tuple; its relation-kinds member is an
ordered array on the wire.

_Implementation mapping_:

- `backstitch/cli.py`
- `backstitch/evidence_discovery.py`
- `backstitch/evidence_summary.py`
- `backstitch/obligation_api.py`
- `backstitch/obligations.py`
- `backstitch/operation_progress.py`

### 8.5 Result Economy And Repair [EVC-8.5]

Text output is a rendering of the same core result. JSON is authoritative for
automation. Default detail orients; evidence and candidates require explicit
selectors; full candidate source requires an exact candidate ID. Excerpts are
bounded by response limits and never silently alter receipt spans. If a full
required response cannot fit, the operation returns `BUDGET_EXHAUSTED` rather
than claiming completion.

Safe normalization may accept a uniquely resolvable bare obligation ID and
return its canonical identity with a guidance note. Backstitch never
normalizes an ambiguous ID, arbitrary path, guessed symbol, candidate digest,
or source edit.

_Implementation mapping_:

- `backstitch/obligation_api.py`

### 8.6 Optional Local MCP Adapter [EVC-8.6]

<!-- backstitch: skip-obligation [EVC-8.6] "The optional Phase D local MCP adapter remains deferred until a separate product promotion." -->

This adapter is an optional product phase, not setup required by another phase.
Its owner records `implemented` or `deferred` under [EVC-10.2]. A deferred
adapter has no MCP command or advertised tools and creates no parity or semantic
qualification requirement. An implemented adapter starts as
`backstitch mcp --repo-root PATH`, uses local stdio only, and exposes exactly:

```text
list_obligations
get_obligation
summarize_obligation_evidence
find_obligation_evidence
get_obligation_candidate
```

It also exposes static resource `backstitch://guides/alignment`.

Tool inputs are exactly:

```text
list_obligations:
  {repo_root, cursor, limit}
get_obligation:
  {repo_root, obligation_id}
summarize_obligation_evidence:
  {repo_root, obligation_id, cursor, limit}
find_obligation_evidence:
  {repo_root, obligation_id, cursor, limit}
get_obligation_candidate:
  {repo_root, obligation_id, candidate_id}
```

Nullable `cursor` and `limit` keys remain present. Other fields are nonblank
strings except positive integer `limit`. Unknown keys are invalid input.

Every repository tool requires `repo_root`, which must resolve to the server's
startup root after symlink and containment checks. Addressed tools also require
`obligation_id`; candidate detail requires `candidate_id`. List, summary, and
discovery accept nullable `cursor` and `limit`. Tools return the same canonical
core result object as CLI JSON. MCP framing and server metadata live outside
that object. Golden tests byte-compare canonical core JSON from both adapters.

Tool and guide descriptors include installed Backstitch version, contract
version, and guide content hash. The server may cache immutable indexes by
snapshot hash in memory, but every call is stateless and independently
addressed. It performs no source write, provider import, network call,
approval, arbitrary filesystem read, or remote transport.

### 8.7 Exit Semantics [EVC-8.7]

Exit behavior is:

| Condition | Exit |
|---|---:|
| Successful read, guide output, packet-only historical report, or report-only semantic result with no applied gate failure | 0 |
| A valid current repository gate runs and effective policy finds a configured failure | 1 |
| Invalid input/config, unresolved required source, snapshot instability/change, budget/deadline, corrupt/stale required artifact, provider/tool/internal failure | 2 |

Current analyze applies this first-matching precedence:

| Order | Condition | Calls/report | Exit |
|---:|---|---|---:|
| 1 | Invalid CLI/config, required qualification unavailable, unsupported platform, output/cache overlap, or initial capture/input/readiness-construction failure | zero provider calls; no current report | 2 |
| 2 | No active obligation, active alignment debt, or blocked readiness | zero provider calls; no current report | 2 |
| 3 | Any effective deterministic issue, including BSE001, has severity in `fail_on` | zero provider calls; no current report | 1 |
| 4 | All active obligations are validly skipped | zero provider calls; final recapture and `not_run_all_skipped` report | 0 |
| 5 | Selected packet count/kind/prompt preflight violates a semantic completeness or budget setting | zero provider calls; no current report | 2 |
| 6 | Cache/provider/verify/normalization/runtime/source-change/output/internal failure, or `require_complete` is true and any selected packet lacks a valid result | attempted calls remain auditable; no current-success report | 2 |
| 7 | `finding_handling = "require_disposition"` and one semantic finding lacks an exact disposition | complete report with finding debt | 2 |
| 8 | One failure-authoritative semantic diagnostic has effective severity in `fail_on` | complete current report | 1 |
| 9 | Otherwise | complete current report | 0 |

`analyze --preflight` evaluates rows 1 through 5 through the same immutable
preparation that ordinary current analysis consumes and stops before cache or
provider work. An invocation or configuration failure before a preparation
exists remains the ordinary one-line stderr error with empty stdout. Once a
preparation assessment exists, preflight renders the complete versioned
assessment to stdout even when its exit is 1 or 2. An executable or valid
all-skipped assessment exits 0; a row-3 deterministic target finding exits 1;
readiness, packet, aggregate-prompt, request-capability, budget, snapshot, or
tool blockers exit 2. A phase whose prerequisite failed is `not_evaluated`
with its blocking phase; it is never fabricated as pass or fail.

Preflight performs no credential read, provider call, cache read or mutation,
output temporary creation, or artifact publication. Ordinary current analysis
executes the same accepted preparation and retains rows 6 through 9. Source is
recaptured before cache/provider work and again before current artifact
publication. A mismatch at the first boundary makes zero provider calls; a
mismatch at the second cannot publish a current artifact.

Artifact publication follows this closed matrix:

| Mode or stage | Published artifacts |
|---|---|
| current preflight, any outcome | none |
| current failure before execution | none |
| current source change before execution | none |
| current execution, source, or output failure | no current-success artifact |
| current success | complete requested current artifacts as one digest-bound logical set; each path replacement is atomic |
| historical input validation failure | none |
| historical attempted run after valid input | only the failed or incomplete historical artifacts already authorized by this section |
| progress | never an artifact |

No mode treats a measured packet prefix, a digest-mismatched packet/report
half-pair, or an incomplete current artifact set as valid output or current
success. Ordered replacement failure may leave an earlier final path as the
explicitly reported invalid residue defined by [EVC-5.1].

Row 4 is reached only after row 3, so setting BSE001 or another retained trace
diagnostic to a failing level prohibits the skip or fails its unresolved trace
without turning it into a tool error. Non-failing deterministic issues remain
in packet/report context.

Legacy semantic completeness keys apply only when at least one row is
`selected`: `minimum_packets` compares selected count;
`required_kinds` requires `section` and `invariant` among selected rows
exactly as before. For `suppression`, current packet-report schema 3 is
intrinsically complete: eligible and emitted both count selected
executable/evaluate rows, and packet-report validation rejects any missing
selected packet before semantic analysis. Zero eligible suppressions is
vacuously complete. [EVC-12] fires both the zero-eligible case and the invalid
packet-report boundary. This asymmetry lets removal of the last exception
remain a passing end state without weakening ordinary intent completeness.
`maximum_packets` and `maximum_prompt_bytes` are fail-closed ceilings;
`require_complete` requires one valid result per selected packet. All-skipped bypasses these semantic
packet/result requirements because no packet is eligible. No-active-intent and
alignment debt were already rejected by row 2. Historical replay skips rows 2 through 4 and
applies artifact validation, semantic completeness, provider/tool, finding
handling, semantic policy, and output rows in the same precedence.

Every schema-3 analysis report, in current-repository or historical-snapshot
scope, requires `packet_warning_count = 0` and `packet_warning_debt = []`.
Warning-debt vocabulary retained by the legacy schema-1 report validator is
historical validation/presentation only and has no schema-3 policy authority.

Schema-3 analysis problems retain [SEM-7]'s closed rows and add nullable
`obligation_id` plus required `details`. New stage/code/detail pairs are:

```text
alignment/no_active_intent:       {}
alignment/alignment_incomplete:   {obligation_ids}
alignment/readiness_blocked:      {obligation_ids}
snapshot/snapshot_unstable:       {attempts}
snapshot/source_changed:          {before_snapshot, after_snapshot}
input/mutable_path_overlap:       {mutable_path, semantic_input}
input/unsupported_platform:       {platform}
input/packet_report_budget_exhausted: {limit_bytes, observed_bytes}
qualification/required_qualification_unavailable: {
  selectors, reason, qualification_report_raw_sha256,
  expected_derivation_identity, current_derivation_identity,
  expected_qualification_identity, current_qualification_identity,
  expected_composition_sha256, current_composition_sha256,
  unqualified_analyzer_providers
}
```

Obligation IDs are unique and canonical-sorted; hashes are lowercase SHA-256;
paths are canonical absolute local diagnostic paths excluded from content
identity; attempts, limits, and observed byte counts are positive. Existing
SEM stage/code pairs use empty details unless their coordinated migration
defines a narrower object. Every new pair is an exit-2 problem and has a firing
test. Packet generation uses the same code and details in its traceback-free
CLI error projection when it exceeds [EVC-8.3.1]'s report-byte bound.

Qualification selectors are unique long `SEMANTIC_*`-code/context strings in
[SEM-6] declaration order; a configured `BSA00*` alias is normalized before
this projection. Reason is `missing`, `corrupt`, `failed`, or
`identity_mismatch`.
The raw report hash is null only for `missing`; otherwise it is bare lowercase
SHA-256 of the exact read bytes, including the required final LF. It is distinct
from configured `qualification_report_sha256`, which hashes the canonical
object without that LF. Composition SHA-256 hashes canonical JSON for exactly
`{analysis_composition_sha256, verify_composition_sha256}` under [EVC-10.1].
Expected composition is null for `missing` or `corrupt`; otherwise the stored
objects and all three hashes are recomputed from the report. Current composition
uses the same closed objects and hash rules over resolved installed/configured
values before cache/provider construction and is null only when verification
is disabled or cannot resolve. Derivation identity has exactly
`snapshot_algorithm_version`, `obligation_algorithm_version`,
`discovery_algorithm_version`, `packet_contract_version`, and
`normalization_version`; expected is null for `missing` or `corrupt` and
otherwise comes from the validated report, while current comes from code-owned
values. Qualification identity has exactly `corpus_sha256`, `mode`, `trials`,
and `eval_config`; expected is null for `missing` or `corrupt` and otherwise
comes from the validated report, while current uses the resolved enforce
configuration and configured corpus digest. Current is null only when no
complete enforce configuration can be resolved. This problem's line-safe
message uses [EVC-6]'s required requalification action.
`unqualified_analyzer_providers` is the canonical-JSON-sorted unique array of
exact [SEM-3] provider identities selected from evidence-stable result
envelopes but not covered by the qualified current composition. It is nonempty
only for a late post-review-lock `identity_mismatch`; early qualification
failures use `[]`.

Untraced candidates do not cause exit 1. Deterministic trace findings affect
`backstitch check` and current analyze through existing configured severity and
`fail_on` rules. Active/evaluate alignment debt blocks current semantic
analysis and is exit 2 before provider work. A valid skip or non-active rung is
non-executable but not a tool failure. An all-skipped corpus follows the same
matrix: a failing deterministic issue exits 1 without a report; otherwise it
publishes the recapture-validated `not_run_all_skipped` report and exits 0.
No-active-intent is exit 2. A bootstrap read still exits 0 and reports every
readiness fact.

All exits are traceback-free. MCP returns the same problem code and core result
but has no process-exit contract per call.

_Implementation mapping_:

- `backstitch/check_application.py`
- `backstitch/cli.py`
- `backstitch/coverage_application.py`
- `backstitch/obligation_api.py`
- `backstitch/packet_application.py`
- `backstitch/semantic_analysis.py`
- `backstitch/semantic_application.py`

## 9. Current CI Gate [EVC-9]

The current CI lane is:

```text
capture current source
  -> resolve obligation inventory and reciprocal trace graph
  -> run deterministic check
  -> select executable, evaluate-disposition obligations
  -> derive packet v3 from the same captured image
  -> analyze and normalize
  -> independently verify
  -> project policy
  -> recapture current source
  -> publish only if snapshot is unchanged
```

No committed packet, cache result, historical replay, semantic success, or
policy override may replace the first four steps. Zero-selected behavior is
the closed all-skipped/no-active/debt matrix in [EVC-2.1], never an ambient
repository rule.

Packet and result caches are performance layers. Every read revalidates the
complete object and keyed preimage. Cache corruption, stale identity, or
missing required cached data in require mode fails closed without provider
traffic.

_Implementation mapping_:

- `backstitch/semantic_analysis.py`
- `backstitch/semantic_application.py`

### 9.1 Source-Aligned Evidence Packets [EVC-9.1]

One executable section or invariant obligation produces the exact schema-3
row defined below. One executable suppression obligation produces the exact
schema-4 row and projection in [SEM-3]. A current JSONL artifact may contain
both versions. `kind` is `section`, `invariant`, or `suppression` and must
agree with row schema and canonical identity. Schema-3 semantics and bytes
do not change.

One authoritative `PacketPlan` owns selection, materialization, canonical
JSONL bytes, packet-report inputs, code-owned prompt bytes, and budget facts
for standalone packets, preflight, current analysis, and historical
validation. A complete plan retains the exact canonical JSONL line bytes and
exact model-request bytes it measured. Publication and execution consume those
retained bytes; they do not regenerate, reserialize, or reframe them.

The complete plan has exactly:

```text
{
  status: "complete",
  complete: true,
  packet_count,
  packet_bytes,
  aggregate_prompt_bytes,
  maximum_request_bytes,
  packets: [{
    packet_id, kind, packet_byte_count, request_byte_count,
    requirement_byte_count, declared_evidence_byte_count,
    counterevidence_byte_count,
    packet_line_bytes, model_request_bytes
  }]
}
```

`maximum_request_bytes` is the largest `model_request_bytes` length, or zero
for an empty valid all-skipped plan. `packet_bytes` includes every JSONL
line-feed terminator. `aggregate_prompt_bytes` is the sum of all complete
`model_request_bytes` lengths and is the quantity governed by
`analyze.maximum_prompt_bytes`. That key remains an aggregate corpus ceiling;
it is never interpreted as a per-packet or per-request limit. A trusted
[SEM-3] capability `maximum_input_bytes`, when present, separately limits each
complete request.

Every `*_byte_count` member is a nonnegative integer length. The two members
ending in `_bytes` are the retained immutable byte strings. Thus a field never
changes type between accounting and execution, and `request_byte_count` must
equal `len(model_request_bytes)`.

Prompt instructions are code-owned, selected only by obligation kind, and
independent of provider, stable model identity, raw transport selector,
effective request, and capability descriptor. A firing matrix varies every
resolved inference field while holding packet content fixed and requires
byte-identical prompt bytes. Changing the prompt contract bytes changes prompt
counts and packet-plan identity.

```text
{
  schema_version: 3,
  packet_id,
  packet_hash,
  kind,
  obligation_id,
  source_snapshot: {
    snapshot_hash, obligation_state_hash, derivation_config_hash
  },
  readiness: {
    intent_state, alignment_state, disposition, obligation_rung, gate_state,
    required_roles
  },
  requirement,
  declared_evidence,
  counterevidence,
  trace_summary,
  evidence_regions,
  issues,
  packet_warnings
}
```

`packet_id` equals the canonical obligation ID. `kind` is `section` or
`invariant`. Nested records are closed:

```text
requirement = {
  role: "requirement",
  path, identity, title, start_line, end_line, text
}

declared_source = {
  source_role, receipt_hash, relation_kinds, reciprocity_state
}

declared_region = {
  role, path, symbol, start_line, end_line, snippet,
  sources: [declared_source]
}

counterevidence_source = {
  candidate_id, candidate_kind, receipt_hash, trace_state,
  discovery_bases, relation_kinds
}

counterevidence_region = {
  role: "counterevidence",
  path, start_line, end_line, snippet,
  candidates: [counterevidence_source]
}

trace_summary = {
  declared_counts: [{
    source_role, total, complete, one_sided
  }],
  candidate_counts: [{
    candidate_kind, declared, partially_declared, untraced, conflicted
  }],
  relation_counts: [{relation_kind, count}]
}

evidence_region = {role, path, start_line, end_line}
```

Requirement identity is the local section ID or invariant ID. Section title is
nonblank; invariant title is null. For a section, the parser takes the complete
physical section span, removes the inline skip token, and masks every
parser-owned mapping or traceability/skip directive line to an empty line. For
an invariant, it takes the exact declaration span and statement. In both cases
it UTF-8 replacement-decodes raw bytes, normalizes CRLF to
LF, preserves a bare CR that is not part of a CRLF pair as literal
in-line content, preserves exactly one output line per LF-delimited
physical source line, and joins lines with `\n` without a final
terminator. That exact string is `text`; its physical first/last lines are the
stored inclusive coordinates. No prose summarization enters requirement.

A snippet uses the same decode/newline rule over its complete receipt span,
without masking. It has exactly `end_line - start_line + 1` logical lines,
where an empty single-line span is one empty line. `symbol` is present and
nullable. Declared source role is `implementation`, `test`, or
`binding_test`. Model role is `implementation` for source role implementation
and `test` for source role test or binding_test. Thus invariant binding tests
reuse [SEM-5]'s model-facing `test` role without erasing the source role.
Reciprocity state uses [EVC-8.3]'s vocabulary. Relation kinds, discovery bases,
candidate kinds, and trace states use their closed EVC orders.

Declared regions sort by `(role, path, start_line, end_line, symbol)` with null
symbol as empty. Sources sort by `(source_role, receipt_hash,
relation_kinds)`. Counterevidence regions sort by `(path, start_line, end_line,
first_candidate_id)`; candidate sources sort by candidate ID. Trace summary
contains one row for every vocabulary member, including zero-count rows, in
[EVC-2.2]/[EVC-7] declaration order. Counts are nonnegative and recompute from
the unmerged source/candidate inventory. A relation count is the number of
unique `(inventory_side, source_identity, relation_kind)` memberships, where
`inventory_side` is `declared` or `candidate`, declared source identity is
`(source_role, receipt_hash)`, and candidate source identity is `candidate_id`.
Each source contributes at most one membership for a relation kind even when
multiple internal graph rows project the same kind.

Issues use [SC-6]'s canonical model-visible issue shape and order.
`packet_warnings` is exactly the empty list for schema 3. Packet construction
emits no truncation warning: any required text or universe budget overflow is
fatal.

Packet construction includes all required declared evidence and the complete
closed counterevidence universe from [EVC-7]. No caller, agent, or model selects
rows. Any candidate whose discovery-v2 visible-source tuple exactly equals a
declared-evidence tuple remains represented in candidate and relation counts
but does not duplicate that declared snippet as counterevidence text. This is
role-independent and does not depend on trace state. Candidate and declared
receipt hashes remain the semantic identities used by trace accounting; a hash
match without the same path and coordinates does not suppress text. Untraced
and conflicted candidates with distinct visible-source tuples remain explicit
counterevidence.

This presentation rule preserves schema 3's existing boundary: a suppressed
duplicate candidate remains individually available from the authoritative
discovery result, while the packet preserves its candidate-kind, trace-state,
and relation aggregate memberships in `trace_summary`. Schema 3 does not add an
individual duplicate-candidate row merely to carry text-free identity. Doing
so would require a new packet schema rather than a discovery-version change.

Within each model role and path, identical and fully contained snippet spans
merge to the first maximal span. Equal later duplicates are omitted. The
maximal region accumulates every source or candidate subrow. Its symbol is
retained only when every accumulated source has the same symbol; otherwise it
is null. Partial or disjoint spans remain separate. Text-free candidate and
receipt identities attached to retained counter regions therefore remain
represented and merging never hides their universe membership. The exact
declared-duplicate suppression above has the separately stated schema-3
aggregate boundary.

`evidence_regions` is derived after merging. It begins with the nonblank
requirement region, then every nonblank declared region, then every nonblank
counterevidence region. Its role vocabulary is exactly `requirement`,
`implementation`, `test`, and `counterevidence`; it sorts in that role order,
then path and span. Duplicate coordinates are impossible after merging.
Analyzer and verifier model evidence contains exactly role/path/start/end and
must equal one `evidence_regions` row. `counterevidence` is a permitted
advisory citation. It never satisfies a required `implementation` or `test`
role and never changes alignment.

The model-visible projection contains exactly:

```text
{
  packet_contract_version: 3,
  packet_id,
  kind,
  obligation_id,
  requirement,
  declared_evidence,
  counterevidence,
  trace_summary,
  evidence_regions,
  issues,
  packet_warnings
}
```

It excludes `schema_version`, `packet_hash`, `source_snapshot`, readiness,
full receipt objects, guide text, skip reason, local absolute paths, policy,
cache, and provenance. Nested receipt hashes remain visible as source identity.
`packet_hash` is SHA-256 of canonical JSON for this exact model-visible
projection. Exact visible source bytes therefore own the semantic identity; an
unrelated captured file may change snapshot identity without changing this
packet hash.

Schema-4 suppression rows use [SEM-3]'s exact closed top-level, nested-rule,
requirement, counterevidence, evidence-region, issue, readiness, and
model-visible projection contracts. Their packet hash uses contract version
4. Schema-3 and schema-4 rows share source-snapshot currentness, complete
population, byte-ceiling, canonical JSONL ordering, publication, and
self-validation rules. There is no compatibility normalization from one row
version or kind into another.

Discovery-v2 increments `discovery_algorithm_version` without changing packet
schema 3 or 4. Its snapshot and derivation identities deliberately cold-miss
discovery-v1 current caches. Historical schema-3 and schema-4 rows retain
their recorded discovery-v1 identities and continue through their exact
readers; current-source comparison never rewrites or accepts an old derivation
identity as discovery-v2.

`obligation_state_hash` is SHA-256 of canonical JSON for:

```text
{
  obligation_state_version: 1,
  obligation_id, kind, obligation_rung,
  intent_state, alignment_state, disposition, gate_state,
  required_roles,
  declared_sources: [{
    source_role, receipt_hash, relation_kinds, reciprocity_state
  }]
}
```

Declared sources use the same sorted unique inventory that feeds merged
regions. `derivation_config_hash` is SHA-256 of canonical JSON for:

```text
{
  derivation_config_version: 1,
  section_required_roles,
  maximum_candidate_items, maximum_catalog_items, maximum_lexical_seeds,
  maximum_work_units, maximum_packet_bytes, maximum_packet_report_bytes,
  static_neighbor_depth,
  obligation_algorithm_version, discovery_algorithm_version,
  packet_contract_version, normalization_version
}
```

Every field is required and uses the effective captured setting/version. Page,
response, deadline, retry, output, provider, and policy settings are excluded.

The immediately prior packet-report schema 2 is exactly:

```text
{
  schema_version: 2,
  artifact: "backstitch-packet-report",
  packet_schema_version: 3,
  scope: "source_snapshot",
  source_snapshot: {
    snapshot_hash, file_count, byte_count, unreadable_count
  },
  derivation_contract: {
    obligation_algorithm_version,
    discovery_algorithm_version,
    packet_contract_version,
    normalization_version,
    semantic_config_sha256
  },
  packet_jsonl_sha256,
  packet_count,
  packet_bytes,
  selection_status,
  readiness_counts: {
    total, active, out_of_scope, selected, skipped, alignment_debt, blocked
  },
  alignment_audit: [{
    obligation_id, kind, path, start_line,
    intent_state, alignment_state, disposition, obligation_rung, gate_state,
    skip
  }],
  deterministic_issues: [{
    issue_identity, code, short_code, context,
    severity, default_severity,
    path, line, message, obligation_id
  }],
  packets: [{packet_id, packet_hash}],
  packet_report_content_sha256,
  tool_version,
  created_at
}
```

Current generation emits packet-report schema 3. It is packet-report schema
2 with exactly these closed changes:

- `schema_version` is `3`;
- scalar `packet_schema_version` becomes
  `packet_schema_versions`, an ascending duplicate-free array containing
  exactly the row versions present: `[3]` or `[3, 4]`;
- `derivation_contract.packet_contract_version` becomes
  `packet_contract_versions` with the same exact array;
- `alignment_audit.kind` admits `suppression`;
- `kind_counts` is added with exactly `eligible` and `emitted`; each contains
  exactly nonnegative `section`, `invariant`, and `suppression` counts that
  recompute from the inventory/audit and emitted JSONL rows;
- `readiness_counts` uses the same disjoint buckets across all three kinds;
- `packet_count` and `readiness_counts.selected` equal section + invariant +
  suppression emitted rows.

Every other field and semantic rule is unchanged. The
`packet_report_content_sha256` preimage contains exactly every packet-report
schema-3 field except itself, `tool_version`, and `created_at`, including
both plural version fields and `kind_counts`. Canonical JSON owns key order.
The hash therefore continues to cover every non-provenance report field.
Readers retain exact packet-report schema 2 support for historical
section/invariant-only replay and never reinterpret a schema-2 artifact as
containing suppression.

Packet rows use JSONL order. Counts are nonnegative and satisfy `total =
out_of_scope + selected + skipped + alignment_debt + blocked` and `active =
selected + skipped + alignment_debt + blocked`. Buckets are the disjoint
[EVC-2.1] corpus matrix. `selection_status` is `selected`,
or `not_run_all_skipped`; debt, blocked, and no-active runs publish no packet
report. `packet_count` equals the length of `packets` and `selected`.

`alignment_audit` contains every addressable obligation in the captured
inventory, including out-of-scope and skipped rows. It sorts by path, start
line, and obligation ID. `skip` is null for `evaluate`; for `skipped` it is
exactly `{reason, path, line}` from the valid source marker. The facts use
[EVC-2.1]'s closed vocabularies. In schema 2, kind is `section` or
`invariant`; schema 3 additionally admits `suppression`. Paths are
canonical repository-relative POSIX strings; lines are positive integers; and
the reason uses [EVC-8.3.2]'s validation. The rows deterministically reproduce
every readiness count. They are audit projection only and cannot alter packet
selection or alignment.

`deterministic_issues` is the complete ordered projection of every effective,
non-`off`, unsuppressed issue retained by the ordinary deterministic report for
the same snapshot. It uses [SC-4]'s canonical code, short code, nullable
context, effective severity, packaged default severity, nullable path/line,
and message. `obligation_id` is the canonical attributed obligation or null.
`issue_identity` is lowercase SHA-256 of canonical JSON for exactly
`{code, context, path, line, obligation_id, ordinal}`; `ordinal` is the
zero-based occurrence among otherwise equal preceding fields in ordinary
deterministic issue order. The array preserves that ordinary order. It never
contains an `off` or suppressed issue; those remain recoverable only through
the existing suppression audit. A successful current report can contain only
issues whose effective severity is outside `fail_on`, because [EVC-8.7] row 3
precedes publication.

The historical schema-2 `packet_report_content_sha256` is lowercase SHA-256
of canonical JSON for exactly this object:

```text
{
  schema_version, artifact, packet_schema_version, scope,
  source_snapshot, derivation_contract,
  packet_jsonl_sha256, packet_count, packet_bytes, selection_status,
  readiness_counts, alignment_audit, deterministic_issues, packets
}
```

It covers every schema-2 packet-report field except itself and the two provenance fields
`tool_version` and `created_at`. Current generation uses the schema-3
preimage defined above. Historical replay recomputes the applicable version
before using any audit, count,
snapshot, derivation, or packet identity field; mismatch is corrupt input,
exit 2, with no analysis report. Successful validation proves internal report
integrity only. The named source derivation remains `claimed_unverified` until
an explicit repository comparison succeeds.

`packet_bytes` is the exact JSONL byte length. `created_at` is RFC 3339 UTC
provenance. It and `tool_version` are excluded from content identity; all
packet-derived fields are recomputed from packet bytes. In current generation,
the snapshot owner also validates the source-snapshot and derivation fields. A
packet-only loader can validate their shape and internal use but treats their
historical source provenance as a claim until repository comparison.
`semantic_config_sha256` hashes the `semantic_config` object in [EVC-8.2]. The
canonical JSON bytes of the complete packet report, including content hash and
provenance, must not exceed `maximum_packet_report_bytes`. The loader applies
that bound before JSON parsing. Generation applies it after complete assembly
and before staging. Overflow is exit 2 and publishes no packet report, packet
JSONL, analysis report, cache entry, or policy result; the report is never
truncated and no partial audit is permitted.

Packet overflow is fatal. There is no warning-based truncation of requirement,
required declared evidence, or counterevidence universe. A report-only
bootstrap command may describe why a packet is unavailable, but must not emit
a semantic packet for a non-executable obligation. `maximum_packet_bytes`
limits the complete canonical packet JSONL artifact, including its line-feed
terminators, not each row independently. Exact-limit output succeeds;
limit-plus-one fails before any packet or report publication.

Ordinary planning stops immediately after the first exactly measured row
crosses any fail-closed packet-count, complete-JSONL, aggregate-prompt, or
trusted per-request capability ceiling. Its nonpublishable overflow plan has
exactly:

```text
{
  status: "over_budget",
  complete: false,
  crossed_ceiling,
  measured_packet_count,
  unmeasured_packet_count,
  measured_packet_bytes,
  measured_prompt_bytes,
  first_crossing_packet_id,
  top_measured_contributors: [{
    packet_id, kind, packet_byte_count, request_byte_count
  }]
}
```

Prefix values are always named `measured`; they are never labeled totals,
forecasts, or a complete corpus. Contributors sort by descending measured
bytes for the crossed ceiling, then packet ID. An overflow plan cannot be
loaded as current or historical input and publishes no partial JSONL, packet
report, analysis report, cache entry, or policy result. Exact-limit succeeds;
limit-plus-one fails.

Gate 1 uses a provider-free, nonpublishing diagnostic measurement built by the
same planner and serializer. Its closed record includes snapshot,
configuration, and algorithm identities; selected and debt counts by kind;
complete-versus-prefix state; committed ceilings; packet and aggregate prompt
totals; first crossing; top packet IDs with packet, prompt, requirement,
declared-evidence, and counterevidence bytes plus source owners; unmeasured
identities/count; prompt-instruction descriptor hashes/sizes; work units; and
elapsed time. Diagnostic continuation may measure after the ordinary first
crossing only to produce a complete Gate-1 audit. It is never a sendable plan
and cannot publish artifacts, read credentials, touch cache, or call a
provider.

Gate 1 selects the current representation only when one complete audited plan
fits `maximum_packets`, `maximum_packet_bytes`,
`analyze.maximum_prompt_bytes`, every trusted per-request
`maximum_input_bytes`, and the reviewed cost ceiling after all trace changes
have an identity-level truthful-owner disposition. An incomplete measurement
or unresolved trace row is no decision. If a complete audited plan still
exceeds a ceiling, implementation pauses for a separately reviewed and
promoted representation or budget delta; no fallback is inferred from this
section.

The standalone `backstitch packets` inspection command may filter packet JSONL
with `--kind`, but current schema-3 `--report` is valid only with `--kind all`. A
filtered JSONL file has no complete-corpus packet report and therefore cannot
be supplied to historical analysis. Current `analyze --repo-root` and its
optional packet/report output pair always compile the unfiltered selected
corpus.

The current analysis report schema 6 retains [SEM-7]'s closed analysis,
finding, problem, debt, cost, cache, selected-inference, result-source, and
producer records. The EVC fields first added by analysis-report schema 3 remain
required and are exactly:

```text
scope
semantic_status
artifact_integrity
artifact_currentness
source_provenance
source_snapshot
packet_report_content_sha256
alignment_summary
alignment_audit
deterministic_issues
verification
```

`scope` is `current_repository` or `historical_snapshot`.
`semantic_status` is `evaluated`, `not_run_all_skipped`, or
`historical_replay`. Current selected runs use the first, current all-skipped
runs the second, and packet mode the third.
`artifact_integrity` is `valid`; corrupt input publishes no report.
`artifact_currentness` uses [EVC-4.1]. `source_provenance` is
`captured_current`, `compared_match`, `compared_mismatch`, or
`claimed_unverified`. `source_snapshot` is the packet-report snapshot record.
`packet_report_content_sha256` is the validated packet-report value above.
`alignment_summary` is the packet report's exact `readiness_counts`.
`alignment_audit` and `deterministic_issues` are byte-for-byte canonical JSON
copies of the packet-report arrays. Thus a zero-packet all-skipped report still
shows every skipped obligation's alignment state, source reason, and retained
BSE001 or trace issue. Historical replay preserves the captured audit without
reinterpreting it as current source state.
`verification` is the following closed tagged object:

```text
{
  state,
  contract,
  events,
  aggregate_counts: {
    independently_verified,
    disputed,
    verification_indeterminate
  },
  cache_hits,
  cache_misses,
  provider_calls
}
```

`state` is `disabled` or `enabled`. Disabled verification requires
`contract = null`, an empty `events` array, all three aggregate counts equal to
zero, and zero cache hits, misses, and provider calls. It projects no
independent verification context. Enabled verification requires `contract`
with exactly:

```text
{
  verify_contract_version,
  prompt: {id, version, sha256},
  adapter_model_id,
  provider: {
    backend_id, plugin_id, model_id, model_revision,
    adapter_id, adapter_version,
    llm_distribution_version,
    plugin_distribution_name, plugin_distribution_version
  },
  request: {json_mode, temperature, seed, max_tokens, reasoning_effort},
  search_epochs,
  required_verdicts,
  minimum_support_score,
  indeterminate
}
```

`adapter_model_id` is the nonblank raw verifier transport selector selected for
this run. It is operational provenance, not part of the verifier review or
cache identity. Analysis-report schema 5 lacks this member and remains an
exact historical reader shape. These fields otherwise are the common
projection of [EVC-3.1] and [EVC-5]; epochs retain configured order. Enabled
verification with zero selected findings, including an all-skipped corpus, has
this non-null contract but requires empty events, zero aggregate counts, and
zero cache/provider counters. With selected findings, events and counters are
recomputed under [EVC-3.1]. Counts and cache/provider counters are nonnegative
integers and aggregate counts equal the number of events in each state.
Current reports require `artifact_currentness = current`. Packet-only reports
require `unverifiable` and `claimed_unverified`; compare mode reports
`current`/`compared_match` or `stale`/`compared_mismatch` while scope remains
historical. Current mode reports `current`/`captured_current`. Corruption is
returned in the exit-2 problem envelope and no analysis report is published.

_Implementation mapping_:

- `backstitch/markdown_specs.py`

## 10. Measurement And Promotion [EVC-10]

<!-- backstitch: meta because docs/specs/04-backstitch-traceability-exclusions.md#SUP-VERIFICATION-META -->

Qualification measures distinct product questions separately:

- obligation identification and unaddressable-intent recall;
- readiness-state correctness for every state transition;
- declared-evidence locator, reciprocity, and receipt correctness;
- candidate recall by kind and trace-state precision;
- guidance usefulness, first-reviewed-diff correctness, and absence of source
  mutation;
- authoring cost from untraced or partial intent to the first executable
  obligation, including elapsed time, reviewed source-diff attempts, changed
  source files/lines, and Backstitch calls;
- candidate disposition counts and rates for human-reviewed `accepted`,
  `rejected`, and `irrelevant` labels;
- public-help-only bootstrap completion and comprehension of the source-authority
  boundary;
- packet evidence sufficiency and counterevidence capture;
- analyzer conditional precision/recall;
- composed analyze-to-adversarial-verify conditional precision/recall,
  false-positive rate, indeterminate rate, and uncached flip rate;
- end-to-end recall from source intent through independently verified claim;
- CLI call count, pages, and response bytes, plus MCP cost and parity only when
  Phase D is implemented;
- invalidation under relevant edits versus unrelated edits;
- cold/warm latency, deterministic work units, and peak RSS.

Candidate recall does not imply declared-evidence correctness. Alignment
completion does not imply semantic conformance. Semantic precision does not
repair missing trace. Aggregate dashboards must preserve these denominators.
Qualification judges the exact composed analyzer/verifier configuration on the
committed corpus. It does not estimate cross-model correlation or award credit
for a distinct model tuple. Stability alone is insufficient: stronger policy
requires measured precision, sensitivity, critical-case capture, and replay.

The deterministic scale fixture contains at least 1,000 obligations, 5,000
Python modules, 20,000 candidates, and 50 MiB captured source. The provisional
design targets at spec promotion are 30 seconds for full discovery or packet
generation, 5 seconds for cache-only current analyze, 2 seconds for warm
list/detail, and 1 GiB peak RSS on the pinned Linux CI runner. No
pre-implementation benchmark is required to promote this spec. Once the
relevant operation exists, its implementation slice must create a comparable
baseline and meet these values as hard acceptance ceilings before that slice or
the overall implementation is called qualified. Tests also assert deterministic
work counts. If the first comparable baseline misses a ceiling, stop the slice,
diagnose the cause, and independently review an explicit spec revision; do not
silently relax the ceiling during implementation.

The pinned runner identity is owned by committed
`tests/performance/runner-contract.json`, with exactly:

```text
{
  schema_version: 1,
  workflow_path: ".github/workflows/ci.yml",
  job_id: "semantic-scale",
  runs_on,
  runner_image_os,
  runner_image_version,
  architecture,
  cpu_model,
  logical_cpu_count,
  memory_bytes,
  python_version,
  uv_version,
  uv_lock_sha256
}
```

Strings are nonblank and contain no wildcard; counts are positive integers;
the lock hash is exact lowercase SHA-256. The workflow probes the runtime and
requires exact equality before applying time/RSS ceilings. A mismatch makes
performance qualification unavailable, not failed or silently comparable.
Changing runner image, hardware, Python, uv, or lock identity requires a
reviewed contract update and baseline rerun. The first implementation slice
that claims performance qualification must add this file and the named job.
Their absence makes qualification unavailable; it does not block promotion of
an otherwise reviewed pre-implementation contract.

### 10.1 Evaluation Artifact [EVC-10.1]

The evaluation corpus and report are committed and content-addressed.
Provider-free replay means the authoritative loader can revalidate corpus
trees, stored analyzer attempts, primary/replay verifier events, metrics,
bounds, checks, and qualification without importing a provider or constructing
an adapter. Report generation is not provider-free: it performs one cold
provider-backed primary phase followed immediately by a cache-only,
zero-provider-call replay phase.

This semantic corpus starts only from source variants whose deterministic
gold projection is executable. Obligation/readiness transitions, malformed or
missing declarations, candidate-search quality, skips, currentness, and corrupt
artifacts remain in the separately measured Phase A/B/C suites. The semantic
corpus uses these closed control tags:

```text
historical_misalignment
valid_vacuous_trace
analyzer_false_positive
analyzer_false_negative
verifier_false_positive
verifier_false_negative
indeterminate
uncached_flip
misleading_nearby_code
out_of_packet_decoy
omitted_disconfirming_evidence
prompt_injection_source
```

An enforce corpus contains every tag at least once. Tags state reviewed test
intent; measured outcomes still come only from production analyzer/verifier
results and cannot be asserted by a tag. A fixture tagged
`analyzer_false_positive` or `verifier_false_positive` has no expected finding.
A fixture tagged `analyzer_false_negative`, `verifier_false_negative`,
`indeterminate`, `uncached_flip`, `valid_vacuous_trace`, or
`omitted_disconfirming_evidence` has at least one expected finding. Other tags
carry no finding-polarity implication.

The eight-case synthetic semantic baseline remains historical evidence, not a
stronger-policy corpus. Before independently verified findings receive stronger
policy, the qualification corpus also contains at least 20 distinct reviewed
historical misalignment units, including syntactically valid but substantively
vacuous reciprocal traces, plus the synthetic controls above. Literal removal
of a mapping, backlink, bind, or binding-test relation belongs to deterministic
readiness evaluation and is not counted as semantic recall.

Qualification uses this complete table:

```toml
[tool.backstitch.verify.eval]
mode = "report"                    # report | enforce
qualification_corpus = "tests/semantic_eval/v3/manifest.json"
qualification_corpus_sha256 = "sha256:<digest>"
qualification_report = "docs/evidence/verify-eval-report.json"
qualification_report_sha256 = "sha256:<digest>"
trials = 2
interval_method = "wilson"
confidence_level = 0.95
minimum_positive_units = 1
minimum_negative_units = 1
minimum_evidence_sufficiency_rate = 0.0
minimum_conditional_precision = 0.0
minimum_conditional_recall = 0.0
minimum_end_to_end_recall = 0.0
minimum_recall_lower_bound = 0.0
maximum_false_positive_rate = 1.0
maximum_false_positive_upper_bound = 1.0
maximum_indeterminate_rate = 1.0
maximum_uncached_flip_rate = 1.0
require_all_critical = false
```

The promoting public generator is:

```text
backstitch eval --corpus MANIFEST --output REPORT
  [--config PATH | --no-config]
  [--option KEY VALUE]...
```

The evaluation command's configuration controls compose with [CFG-5.1].
Trusted refresh may therefore activate a dormant complete verifier and change
analyzer/verifier cache modes through the exact static options in [SEM-9.1].

The corpus and output resolve to distinct paths before corpus loading, cache
creation, or adapter construction. A nonblank configured corpus path must
resolve to `--corpus`; a nonblank configured corpus hash must match its
validated canonical object digest. `--output` is a candidate publication path
and need not equal the configured qualification-report path. This lets the
human review a new report before pinning it as gate authority. Eval exits 0
after atomic publication of a structurally valid report in report mode or a
passing report in enforce mode. A completed enforce measurement with failed
checks atomically publishes its non-authoritative candidate report and exits 2
so the failure remains inspectable. Setup, corpus, source, provider, cache,
replay, or publication failure exits 2 without publishing a report. Eval never
exits 1.

The output and configured qualification-report paths must lie outside every
fixture directory and must not equal the corpus manifest, any tree manifest,
or any selected/extended config file. The output must also differ from the
configured report path when that existing path is one of those inputs. Path
containment and no-follow regular-file checks happen before fixture copying or
adapter construction. These rules prevent staging/publication from changing a
corpus or configuration being measured.

Mode is `report` or `enforce`; `trials` is a positive integer excluding
booleans; interval method is exactly `wilson`; confidence is finite strictly
between zero and one; sample floors are nonnegative integers excluding
booleans; rate fields are finite in `[0, 1]`; and the last field is boolean.
Report mode permits blank paths/hashes and cannot authorize stronger policy.
Enforce mode requires a contained nonblank corpus path, its exact
`sha256:<64 lowercase hex>` digest, positive sample floors, at least two
trials, every minimum quality threshold greater than zero, every maximum below
one, `maximum_false_positive_rate = 0`, and `require_all_critical = true`.
The qualification-report path/hash may remain blank while generating a new
enforce candidate. They must both be nonblank, contained, canonical, and match
that exact report before an [EVC-6] selector gains failure authority. Changing
only these external report-binding fields does not change candidate report
bytes. Unknown keys are errors.

Candidate capture, trace-state precision, interaction cost, authoring cost,
maintenance churn, currentness, and pinned-runner performance are owned by the
separate [EVC-10.2] product stages. They are not semantic-report fields or
surrogate inputs to independently-verified policy authority.

Both evaluation modes require `verify.enabled = true` with the complete
[EVC-5] table. Disabled verification is invalid evaluation configuration,
makes zero provider calls, and publishes no qualification report. This does
not affect ordinary analysis, whose disabled representation is closed in
[EVC-9.1]. Every primary and replay run in one evaluation uses the same enabled
report-level verification composition. Trial-specific effective verifier
epochs are event identity, not report-level composition.

Eval resolves outer configuration once from the manifest anchor and
explicit `--config`/`--no-config` choice before copying a fixture. Outer config
contributes only analyze, verify, and verify-eval settings. The corpus supplies
each case's closed deterministic profile, exclusions, and obligation settings;
the runner uses packaged deterministic diagnostic policy and neutral semantic
projection (`finding_handling = allow`, no dispositions). A config file inside
a fixture is ordinary captured source data and never participates in settings
resolution. Every variant therefore runs under one exact report-level
inference composition and manifest-owned source derivation rather than
fixture-selected provider or policy settings.

Each evaluation execution creates fresh, empty, operation-scoped analyzer and
verifier cache staging roots. It never reads either ordinary repository cache
or a prior evaluation execution's cache. Failure to create or prove both roots
empty is setup failure before a provider call. The runner owns cache modes
regardless of ordinary analysis configuration: each trial's analyzer and
verifier primary phase is `read-write`; its immediate replay is `require`.
Primary writes immutable objects; replay addresses only those exact objects.
Both staging roots are discarded after the report is atomically published or
the execution fails. Provider-free report validation uses the committed report
and corpus, not either ephemeral root.

Analyze and verify `maximum_provider_calls` and positive estimated-cost
ceilings are separate lane-wide ceilings over the complete evaluation
execution, across every case, variant, and trial; they never reset per fixture
or trial. The smaller resolved maximum-runtime value is one monotonic deadline
for the whole execution. Prompt-byte ceilings remain per request; concurrency
and lock waits retain their lane/object meanings. Budget exhaustion is exit 2,
publishes no report, and cannot be converted to an indeterminate model verdict.

The corpus manifest contains exactly `schema_version = 3`, `corpus_id`,
`reviewed_historical_units`, `critical_case_ids`,
`critical_vacuous_trace_case_ids`, and ordered `cases`. Agent-interface
surfaces and the optional MCP disposition remain in the Phase A/B/D evidence
and do not create semantic cohorts. Nested records are exactly:

```text
corpus_case = {
  case_id,
  deterministic_config,
  clean,
  mutations,
  gold_obligations,
  gold_evidence,
  gold_candidates,
  expected_findings,
  critical
}

fixture = {
  variant_id, fixture_path, tree_manifest_path,
  tree_manifest_sha256, transform, control_tags
}

gold_obligation = {
  gold_id, variant_id, obligation_id, packet_id,
  intent_state, alignment_state,
  disposition, obligation_rung, gate_state
}

gold_evidence = {
  gold_id, variant_id, obligation_id, source_role, path,
  structural_locator, start_line, end_line,
  receipt_hash, reciprocity_state
}

gold_candidate = {
  gold_id, variant_id, obligation_id, candidate_id,
  candidate_kind, path, structural_locator,
  start_line, end_line, receipt_hash, trace_state
}

expected_finding = {
  gold_id, variant_id, packet_id, code, classification,
  required_declared_evidence_gold_ids,
  required_counterevidence_gold_ids
}

reviewed_historical_unit = {
  unit_id, case_id, variant_id, expected_finding_gold_id,
  source_reference, review_reference
}

deterministic_config = {
  profile: {
    spec_roots, plan_roots, code_roots, test_roots,
    planned_spec_globs, exploratory_spec_globs, meta_spec_globs
  },
  exclude_globs,
  obligations: {
    section_required_roles,
    page_size, maximum_page_size, maximum_response_bytes,
    maximum_candidate_items, maximum_catalog_items,
    maximum_lexical_seeds, maximum_snapshot_files,
    maximum_file_bytes, maximum_snapshot_bytes, maximum_work_units,
    maximum_packet_bytes, maximum_packet_report_bytes,
    maximum_call_seconds, snapshot_capture_attempts,
    static_neighbor_depth
  }
}
```

Case IDs are nonblank and unique. Clean has `variant_id = "clean"` and null
`transform`; mutation variant IDs are nonblank and unique within their case,
and transform descriptions are nonblank. Fixture directories and tree-manifest
paths are each unique across the corpus. Fixture paths are contained
manifest-relative POSIX directories; tree hashes use exact
`sha256:<64 lowercase hex>`. Every gold `variant_id` resolves to clean or one
mutation in its case. Gold IDs are unique nonblank strings across all gold
arrays in one case. Roles, states, kinds, codes, classifications, locators, and
receipts use their owning closed vocabularies. Inclusive spans are positive
and ordered. Candidate ID recomputes from kind/path/locator under [EVC-4.1];
candidate and evidence receipt hashes recompute from the exact variant tree and
span. Every expected packet ID resolves to one gold obligation in the same
variant. Required declared-evidence IDs resolve only to gold evidence for the
same variant, obligation, and packet; required counterevidence IDs resolve only
to gold candidates under those same constraints.
At most one expected finding may address one `(case_id, variant_id, packet_id)`
because production emits exactly one normalized result per packet.

Cases sort by case ID; mutations by variant ID; all gold arrays by variant
(`clean` first) then gold ID; required IDs by Unicode code point. Each
fixture's control tags are unique and follow the closed order above. `code` is
a canonical long `SEMANTIC_*` code and must match `classification` through
[SEM-6]'s exact table. Critical case IDs are the unique sorted IDs of rows with
`critical = true`. `critical_vacuous_trace_case_ids` is a unique sorted subset
of critical case IDs. Every named case has at least one fixture tagged
`valid_vacuous_trace` and an expected finding in that same variant with
classification `missing_trace` and canonical code
`SEMANTIC_MISSING_TRACE`. In enforce mode both sets are nonempty. Skip is
invalid on a qualifying critical unit.

Reviewed historical unit IDs are nonblank and unique; records sort by unit ID
and uniquely resolve one expected finding in the named case/variant. Both
references are nonblank stable audit references, source references are unique
across units, and resolved
`(case_id, variant_id, expected_finding_gold_id)` target tuples are unique.
Each resolved fixture has `historical_misalignment` in its tags. An enforce
corpus has at least 20 such distinct target tuples. These records make the
floor and review trail machine-checkable; independent corpus review remains
the trust boundary for whether a reference represents a real reviewed
misalignment rather than synthetic data.

Deterministic config strings and arrays use the owning profile/config path and
ordering rules; limits use [EVC-8.3.1]'s exact types and ranges. The evaluation
runner constructs this manifest-owned profile and obligation setting object
directly. It uses packaged deterministic diagnostic policy and requires every
qualifying variant's deterministic report to contain zero issues, so applied
repository policy cannot alter corpus readiness or packet issue bytes. This
config is gold-side harness input and is never provider-visible except through
the ordinary source-derived packet it deterministically produces.

The manifest file bytes are [EVC-4.1] canonical JSON with an optional single
final LF and no other whitespace or trailing bytes.
`qualification_corpus_sha256` is `sha256:` plus lowercase SHA-256 of the
canonical object bytes without that optional LF. The report stores this same
prefixed value as `identity.corpus_sha256`.

Each tree manifest path is a contained manifest-relative JSON file outside its
fixture directory and has exactly:

```text
{
  schema_version: 1,
  artifact: "backstitch-eval-fixture-tree",
  files: [{path, raw_sha256, byte_count, executable}]
}
```

It inventories every regular file below the fixture directory and no other
object. Paths are canonical fixture-relative POSIX strings and sort by Unicode
code point. Symlinks, directories reached through symlinks, sockets, devices,
and duplicate normalized paths are invalid corpus input. `raw_sha256` is
`sha256:<64 lowercase hex>` over exact file bytes; byte count is nonnegative;
`executable` is the boolean owner-execute bit and all other permission bits are
ignored. `tree_manifest_sha256` hashes the exact canonical JSON bytes for this
closed object using [EVC-4.1]. The runner bounded-reads the manifest, validates
its hash, inventories and hashes the isolated copied fixture, and requires
exact row equality before any production operation. Manifest files are corpus
artifacts, not copied into the target repository.

The current semantic qualification report has exactly:

```text
{
  schema_version: 3,
  artifact: "backstitch-verification-eval-report",
  identity,
  analysis_attempts,
  events,
  metrics,
  by_code,
  operational,
  qualification
}
```

Its file bytes are canonical JSON for that object plus exactly one final LF.
`qualification_report_sha256` is `sha256:` plus lowercase SHA-256 of the
canonical object bytes without the LF. The digest is an external authorization
binding and is not a field in the object it hashes.

Its nested records are exactly:

```text
identity = {
  corpus_sha256,
  snapshot_algorithm_version,
  obligation_algorithm_version,
  discovery_algorithm_version,
  packet_contract_version,
  normalization_version,
  analysis_composition,
  analysis_composition_sha256,
  verify_composition,
  verify_composition_sha256,
  composition_sha256,
  trials,
  eval_config
}

composition_provider = {
  backend_id, plugin_id, model_id, model_revision,
  adapter_id, adapter_version,
  llm_distribution_version,
  plugin_distribution_name, plugin_distribution_version
}

composition_request = {json_mode, temperature, seed, max_tokens, reasoning_effort}

analysis_composition = {
  analysis_contract_version,
  provider: composition_provider,
  request: composition_request,
  prompts: [{kind, id, version, sha256}],
  base_search_epoch
}

verify_composition = {
  verify_contract_version,
  prompt: {id, version, sha256},
  provider: composition_provider,
  request: composition_request,
  search_epochs,
  required_verdicts,
  minimum_support_score,
  indeterminate
}

eval_event = {
  trial_index, case_id, variant_id,
  obligation_id, packet_id, claim_hash, code, classification,
  claim_evidence,
  primary_present, replay_present,
  primary_results, replay_results,
  primary_aggregate_state, primary_context,
  replay_aggregate_state, replay_context,
  primary_sha256, replay_sha256, comparison_signature_sha256
}

analysis_attempt = {
  trial_index, case_id, variant_id,
  packet_id, packet_hash,
  base_search_epoch, effective_search_epoch, analysis_key,
  primary_result, replay_result,
  primary_sha256, replay_sha256,
  primary_cache_object_sha256, replay_cache_object_sha256,
  primary_raw_response_sha256, replay_raw_response_sha256,
  primary_provenance, replay_provenance
}

event_result = {
  verify_key, base_search_epoch, effective_search_epoch,
  result, cache_object_sha256, raw_response_sha256, provenance
}

result_provenance = {
  adapter_id, adapter_version, plugin_version, model_class,
  provider_model_id, provider_model_revision, response_id,
  input_tokens, output_tokens
}

metric_row = {
  positive_unit_count, negative_unit_count,
  evidence_sufficiency_rate,
  conditional_precision, conditional_recall, end_to_end_recall,
  recall_lower_bound, false_positive_rate,
  false_positive_upper_bound, indeterminate_rate,
  uncached_flip_rate, false_positive_count,
  all_critical_passed
}

by_code_row = {code, metrics: metric_row}

operational = {
  cache_hits, cache_misses, provider_calls,
  analyzer_primary_cache_hits, analyzer_primary_cache_misses,
  analyzer_primary_provider_calls,
  analyzer_replay_cache_hits, analyzer_replay_cache_misses,
  analyzer_replay_provider_calls,
  verifier_primary_cache_hits, verifier_primary_cache_misses,
  verifier_primary_provider_calls,
  verifier_replay_cache_hits, verifier_replay_cache_misses,
  verifier_replay_provider_calls,
  analysis_cost, verify_cost, total_estimated_cost_microusd
}

cost_record = {estimated_cost_microusd, cost_rate_source}

numeric_qualification_check = {
  kind: "numeric", name, comparator, threshold, observed, passed
}

boolean_qualification_check = {
  kind: "boolean", name, comparator: "true",
  threshold: true, observed, passed
}

qualification = {
  mode, positive_unit_count, negative_unit_count,
  checks, passed, failure_reasons
}
```

These request notations name the one closed five-field vocabulary, not five
mandatory values. Each canonical inference, report, evaluation composition,
load, and equality check omits an optional field that is absent from the
resolved request.

`claim_evidence` is the exact canonical claim `evidence` array from [EVC-3.1],
not verifier response evidence. `checks` is an array of the numeric/boolean
qualification-check union above; unknown fields or cross-kind values are
invalid. Each `event_result.result` is the complete canonical verifier-result
row from [EVC-3.1], not a report-specific verdict projection.

The composition provider is [SEM-3]'s exact provider projection. Request fields
use [SEM-3]'s resolved values. Analyzer prompts contain exactly one installed
descriptor for `section` then `invariant`, even when a corpus has no unit of one
kind. `base_search_epoch` is [SEM-9]'s resolved nonblank analyze epoch.
Verifier prompt, ordered epochs, verdict count, threshold, and indeterminate
rule are [EVC-3.1]/[EVC-5]'s resolved values. Strings and versions satisfy their
owning contracts; thresholds are finite.
The five source-derivation version fields are positive code-owned integers
excluding booleans and must equal the installed runtime's exported values.

For each zero-based `trial_index` and each configured verifier epoch in order,
the evaluation runner derives:

```text
effective_search_epoch =
  "eval-verify:" + SHA256(canonical JSON of {
    "base_search_epoch": <the configured verifier epoch>,
    "qualification_corpus_sha256": <the validated config digest>,
    "trial_index": <the zero-based integer>
  })
```

`identity.corpus_sha256` equals the validated
`qualification_corpus_sha256`. The primary verifier call uses the derived
epoch in [EVC-3.1]'s inference contract; that trial's replay uses the identical
base/effective pair. A distinct trial therefore cannot reuse a verifier object
from an earlier trial, while replay addresses exactly the primary object.

For the analyzer, each zero-based trial similarly derives:

```text
effective_analysis_search_epoch =
  "eval-analyze:" + SHA256(canonical JSON of {
    "base_search_epoch": <analysis_composition.base_search_epoch>,
    "qualification_corpus_sha256": <the validated config digest>,
    "trial_index": <the zero-based integer>
  })
```

Every analyzer primary in that trial uses this effective epoch. Its replay uses
the identical base/effective pair. The configured base epoch stays in
`analysis_composition`; the derived epoch is attempt identity. This prevents a
trial from reusing an analyzer object from another trial without making trial
index part of report-level composition.

One code-owned
`derive_eval_search_epoch(domain, base, corpus_sha256, trial_index)` function
owns the closed domains `eval-analyze` and `eval-verify`, inserts the single
`:` separator, and hashes the exact object above. Producer and authoritative
validator both call it. The validator independently supplies and rechecks
every input; a report never supplies an epoch prefix or hash preimage.

Each composition SHA-256 hashes [EVC-4.1] canonical JSON for exactly its named
closed object. `composition_sha256` hashes canonical JSON for exactly
`{analysis_composition_sha256, verify_composition_sha256}`. Objects and stored
hashes must recompute exactly. These projections intentionally exclude packet,
claim, fixture, trial index, effective epoch, path, cache, concurrency,
cost/budget, policy, timestamp, and provider-response fields. Configured base
epochs remain included as `verify_composition.search_epochs`. Packet or claim
changes create new per-call keys but do not invalidate qualification; changing
any composition field does.

The five algorithm/contract-version fields in `identity` form the complete
source-derivation identity. Authoritative loading compares each field with the
current code-owned value before cache/provider construction. A mismatch is
`identity_mismatch` even when composed inference identity is unchanged.
Changing one packet or claim instance does not invalidate qualification;
changing snapshot capture, obligation resolution, discovery, packet contract,
or normalization semantics requires a new report.

Authoritative loading also requires `identity.corpus_sha256`, `identity.trials`,
and `identity.eval_config` to equal the current configured corpus digest and
complete projection from `trials` through `require_all_critical`. Changing a
trial count, interval/confidence value, sample floor, threshold, or critical
requirement therefore requires a new report. Changing only the external
qualification-report path/hash binds or relocates the same reviewed bytes and
does not.

Eval config is the complete ordered table projection from `trials` through
`require_all_critical`. Mode appears only as `qualification.mode`;
corpus/report paths and hashes are external input/authorization bindings and
are not embedded in the candidate report. Guide, skill, and interface
identity remain bound by [EVC-10.2]'s bootstrap/discovery records and are not
part of the semantic inference qualification identity.

Events exist for the union of normalized findings in primary and replay runs.
They sort by trial, case, variant (`clean` first, then variant ID), packet ID,
code, classification, and claim hash. Primary/replay result rows preserve
configured base-epoch order and retain both the configured base and derived
effective epoch. Each event result's complete verifier row has the enclosing
packet/claim identity and verify key. For each side, `present = false` requires an empty
results array and null aggregate/context; `present = true` requires the closed
aggregate/context pair from [EVC-3.1]. The side hash covers canonical JSON for
exactly `{present, results, aggregate_state, context}`. Thus an absent finding
has a stable side hash distinct from a present finding with no verifier calls.
Comparison signature hashes canonical JSON for case, variant, packet, code,
classification, claim hash, `claim_evidence`, and the two side projections of
exactly `{present, results: [{verdict, support_score, evidence}],
aggregate_state, context}`. Result projections preserve configured epoch order
while excluding keys, epochs, summaries, provenance, and cost. One absent side is always a flip;
both sides cannot be absent because events use their union. Event evidence uses
[SEM-5]'s canonical order.

Analysis attempts exist for every trial, corpus variant, and derived packet,
including packets whose normalized result is `ok`. They sort by trial, case,
variant (`clean` first, then variant ID), and packet ID. `primary_result` and
`replay_result` are the complete canonical semantic-result rows produced by
the ordinary analyzer normalization path. Each result's packet ID/hash and
analysis key equal its enclosing attempt. The analysis key recomputes from the
validated packet, the resolved analyzer inference contract, and the attempt's
effective epoch. The two result hashes cover their exact canonical JSON. A
qualifying replay requires the primary and replay result objects and hashes to
be byte-identical. This array, rather than finding events alone, proves replay
for negative and `ok` results and makes analyzer call cardinality
reconstructable without provider access.

Every analyzer attempt and verifier event result retains the immutable cache
object's exact byte SHA-256, raw-response SHA-256, and closed provider
provenance. The authoritative loader reconstructs each complete cache object
from the report's inference contract, key, canonical result, provenance, and
raw-response digest, then requires its cache-object digest to match. Primary
and replay projections for one key are identical. This preserves the declared
provider-boundary audit after ephemeral caches are discarded. It is not a
cryptographic attestation by the provider: the evaluation runner and
independent review remain the trust boundary for the truth of opaque provider
metadata.

Metric nullable fields are null at zero denominator. Counts and false-positive
count are nonnegative integers; rates are finite in `[0, 1]`. Aggregate
`metrics` is one `metric_row`. By-code rows use canonical long `SEMANTIC_*`
codes in [SEM-6] declaration order for every code named by at least one expected
finding or independently verified prediction. Event codes and expected-finding
codes use that same representation and must match their classification. Rows
are recomputed cohorts, never averages.

Operational counters are nonnegative integers. For each lane, zero primary
provider calls requires cost `{0, null}`; positive calls with configured cost
data require a nonnegative estimate and the lane's nonblank resolved rate
source; positive calls without configured cost data require `{null, null}`.
Total estimated cost is the sum when both lane estimates are nonnull and is
null otherwise. Separate records preserve valid analyze-provider reuse and
different-provider override
provenance; a composed display string is not a qualification artifact field.
Analyzer primary execution is cold: its cache-hit count is zero and its
cache-miss and provider-call counts each equal the number of distinct primary
`analysis_key` values. Analyzer replay is cache-only: its hit count equals the
number of distinct replay `analysis_key` values and its miss and provider-call
counts are zero. Repeated attempts with the same analysis key reuse the
already-loaded canonical result without another cache operation.
Verifier primary execution is cold: its cache-hit count is zero and its
cache-miss and provider-call counts each equal the number of distinct primary
`verify_key` values. Verifier replay is cache-only: its hit count equals the
number of distinct replay `verify_key` values and its miss and provider-call
counts are zero. Repeated event rows with the same key reuse the already loaded
canonical result without another cache operation. The aggregate cache/provider
counters include analyzer and verifier activity and recompute from their
phase-specific records. Any violation invalidates qualification.
Qualification checks appear in eval-table order for aggregate thresholds, then
canonical [SEM-6] code order with long `<SEMANTIC-code>:` prefixes. A numeric check uses
comparator `>=` or `<=`, finite numeric threshold, and null or finite numeric
observed value; null never passes in either mode. A boolean check has threshold
`true`, records raw `all_critical_passed` as observed, and passes exactly when
`require_all_critical` is false or observed is true. Failure reasons are
unique check names in failed-check order. Top-level pass equals every check
passed. Report mode may publish and exit 0 with failed checks; enforce mode
returns exit 2 for failed checks. That failed candidate remains a valid audit
artifact but cannot become authoritative.

An expected-finding identity is exactly `(case_id, variant_id, packet_id, code,
classification)` and is unique in the corpus. One aggregate positive unit is
one expected finding. One by-code positive unit is one expected finding for
that code. One aggregate negative unit is one corpus variant with no expected
finding. One by-code negative unit is one corpus variant with no expected
finding for that code. Trials never multiply these labelled units.

An analyzer-produced expected finding is a normalized primary finding whose
packet, code, and classification exactly match one expected-finding identity.
The analyzer contract produces exactly one normalized semantic result per
packet, so at most one analyzer finding can occupy an expected-finding slot in
one trial.
An observed independently verified prediction slot is a primary finding slot
whose aggregate context is `independently_verified` in at least one trial. It
matches gold only by that same exact identity; expected-finding uniqueness and
the one-result-per-packet contract make the match one-to-one. A stable matching
prediction requires that exact slot with `independently_verified` context in
every trial, byte-identical replay in every trial, and one identical comparison
signature across trials.

A variant is evidence-eligible when deterministic production yields exactly
its ordered gold obligation/readiness and packet-ID projection, every named
obligation is executable, and the packet set's complete declared-evidence and
counterevidence identity projections equal the variant-scoped gold evidence
and candidate rows at exact coordinates, locators, receipts, and candidate
IDs. This definition applies equally to negative variants with no expected
finding, so their eligibility is not inferred from an absent expected packet.
One expected finding is evidence-sufficient when its variant is eligible and
all its `required_declared_evidence_gold_ids` and
`required_counterevidence_gold_ids` occur in that finding's packet. Gold is
validator input only and never enters provider-visible packet bytes.

Metrics recompute exactly:

- `evidence_sufficiency_rate` is evidence-sufficient positive units divided by
  positive units;
- `conditional_precision` is distinct observed independently verified
  prediction slots that match an expected finding divided by all distinct
  observed independently verified prediction slots on evidence-eligible
  variants;
- `conditional_recall` is evidence-sufficient expected findings with a
  stable matching prediction divided by all
  evidence-sufficient expected findings;
- `end_to_end_recall` is expected findings with a stable matching prediction
  divided by all expected findings;
- `indeterminate_rate` is expected-finding slots produced by the analyzer in at
  least one trial and given `verification_indeterminate` context in at least
  one trial, divided by expected-finding slots produced in at least one trial;
- aggregate `false_positive_rate` is aggregate negative variants containing
  any observed independently verified prediction divided by aggregate negative
  units;
  the by-code rate uses by-code negative variants and predictions for that
  code;
- `recall_lower_bound` is the Wilson lower bound over distinct expected-finding
  booleans used by end-to-end recall; `false_positive_upper_bound` is the
  Wilson upper bound over distinct negative-unit booleans; and
- `false_positive_count` is the numerator of the corresponding
  false-positive rate.

Every by-code metric applies the corresponding aggregate equation after
filtering expected findings, observed predictions, and critical finding slots
to that canonical long code. By-code negative units remain variants with no
expected finding for that code. By-code `all_critical_passed` applies the same
critical equation as follows: every critical case retains its global exact
gold obligation/readiness/evidence projection; every critical expected finding
for that code has a stable match; every critical variant with no expected
finding for that code has no observed prediction for that code; and every
critical variant has no observed prediction for that code outside its exact
expected identities and every critical slot for that code has zero flips.
Findings of another code do not otherwise enter the cohort.

Every rate with a zero denominator is null. A null observation never passes an
enforce check. Wilson bounds use labelled corpus units, not trials.

For uncached flips, the validator forms the union of primary finding slots
`(case_id, variant_id, packet_id, code, classification)` across all trials. For
each slot and unordered pair of distinct trials, the side is either absent or
the canonical comparison signature defined above. Unequal sides are flips;
absent/present is a flip; absent/absent is not. `uncached_flip_rate` is flips
divided by all such slot/trial-pair comparisons and is null when there is no
comparison.

`all_critical_passed` is true exactly when every critical case has its exact
gold obligation/readiness projection and evidence-eligible packets; every
critical expected finding has a matching independently verified primary and
byte-identical replay event in every trial; every critical negative variant
has no independently verified prediction; every critical positive variant has
no observed independently verified prediction outside its exact expected-
finding identities; and every critical slot has zero uncached flips. Any
missing or extra critical packet, result, prediction, replay,
candidate/evidence atom, or current source relation makes it false.

Aggregate qualification check names, in exact eval-table order, are
`minimum_positive_units`, `minimum_negative_units`,
`minimum_evidence_sufficiency_rate`, `minimum_conditional_precision`,
`minimum_conditional_recall`, `minimum_end_to_end_recall`,
`minimum_recall_lower_bound`, `maximum_false_positive_rate`,
`maximum_false_positive_upper_bound`, `maximum_indeterminate_rate`,
`maximum_uncached_flip_rate`, and `require_all_critical`. Each by-code cohort
repeats those exact names prefixed by its long `<SEMANTIC-code>:` in [SEM-6]
declaration order.
Minimums use `>=`, maximums use `<=`, and the critical check uses `true`.

Promotion to stronger independently verified policy requires:

- `mode = "enforce"` and authoritative report recomputation;
- positive and negative sample floors for the aggregate and each gated BSA
  code;
- zero critical-case failures and zero independently verified false positives
  on negative controls;
- configured lower bounds for end-to-end recall and conditional precision;
- configured upper bounds for false-positive, indeterminate, and uncached flip
  rates;
- cold analyzer and verifier primary execution with one provider call per
  distinct inference key, plus cache-only replay with zero provider calls and
  byte-identical analyzer results and verifier event results;
- exact equality between stored and recomputed analysis attempts, events,
  metrics, bounds, checks, and pass flag.

An exact `CODE:independently_verified` failure-authority selector is normalized
to [SEM-6]'s long code and authorized only when the aggregate qualification and that exact code's
`by_code` cohort both contain every required check, both pass, and the report's
source-derivation identity and composed inference identity equal the current
code/configuration. A passing
aggregate cannot stand in for a missing, empty, or failing code cohort. Codes
that appear only as independently verified predictions therefore receive a
negative-control cohort and cannot gain authority by being absent from gold.

Repeated stochastic trials do not multiply labelled corpus units. Confidence
bounds use distinct corpus units. Qualification is evidence about the tested
corpus and exact composed inference identities, not a universal model guarantee
or evidence of cross-model independence. Changing either resolved inference
contract, including switching between equal-model and distinct-model
composition, requires a new qualification report.

_Implementation mapping_:

- `backstitch/semantic_eval.py`
- `backstitch/semantic_eval_identity.py`
- `backstitch/semantic_eval_observation.py`
- `backstitch/semantic_eval_reports.py`
- `backstitch/semantic_analysis.py`
- `backstitch/cli.py`

### 10.2 Staged Product Qualification [EVC-10.2]

Qualification is staged so the deterministic product can prove value without
waiting for every adapter or semantic extension:

Before any Phase A or B participant sees product output, the owner freezes a
content-addressed qualification manifest and one reviewer protocol per phase.
The manifest
has exactly:

```text
{
  schema_version: 2,
  artifact: "backstitch-alignment-dogfood-plan",
  phase_a_fixture_manifest_path,
  phase_a_fixture_manifest_sha256,
  phase_b_fixture_manifest_path,
  phase_b_fixture_manifest_sha256,
  phase_a_reviewer_protocol_path,
  phase_a_reviewer_protocol_sha256,
  phase_b_reviewer_protocol_path,
  phase_b_reviewer_protocol_sha256,
  phase_a_sessions,
  phase_b_sessions,
  critical_candidate_ids,
  tested_distribution_sha256,
  guide_sha256,
  skill_sha256,
  thresholds: {
    minimum_bootstrap_completion_rate,
    minimum_authority_comprehension_rate,
    minimum_candidate_capture_rate,
    minimum_trace_state_precision,
    maximum_irrelevant_candidate_rate,
    minimum_first_diff_correct_rate,
    require_all_critical_candidates
  }
}
```

Paths are contained manifest-relative POSIX paths. Hashes use exact
`sha256:<64 lowercase hex>`. Session counts are integers of at least two.
Critical candidate IDs are unique and Unicode-code-point sorted. Rates are
finite in `[0, 1]`; the boolean is true. The initial thresholds are exactly
`1.0`, `1.0`, `0.9`, `1.0`, `0.2`, `1.0`, and `true` in field order. Phase A's
content-addressed fixtures include at least one each for no intent, untraced,
partial, complete, and skipped state. Phase B covers every candidate kind and
trace state, includes accepted, rejected, irrelevant, and disconfirming
examples, and marks every candidate whose omission would hide a known
alignment failure as critical.

The top manifest is a closed index over both phases. Each result instead binds
one phase-owned qualification projection so a valid Phase-B-only change cannot
invalidate accepted Phase A evidence. The projection has exactly:

```text
{
  schema_version: 1,
  artifact: "backstitch-alignment-dogfood-phase-plan",
  phase,
  fixture_manifest_path,
  fixture_manifest_sha256,
  reviewer_protocol_path,
  reviewer_protocol_sha256,
  session_count,
  tested_distribution_sha256,
  guide_sha256,
  skill_sha256,
  thresholds,
  critical_candidate_ids  // Phase B only
}
```

Phase A's `thresholds` object contains only minimum bootstrap completion and
authority comprehension. Phase B's contains only candidate capture, trace-state
precision, maximum irrelevant rate, first-diff correctness, and critical
capture. `phase_qualification_sha256` is SHA-256 of canonical JSON for this
exact projection. The top manifest file must be canonical JSON with at most one
final LF; that LF is transport formatting. Referenced fixture manifests and
phase protocols retain their explicitly declared raw-byte hashes. The complete
top-manifest digest remains useful as an audit identity but is not a phase
result identity.

The three product identities are preregistered judged inputs, not values first
asserted by a result. `tested_distribution_sha256` hashes canonical JSON for an
ordered inventory of `pyproject.toml`, `uv.lock`, and every regular non-cache
file under `backstitch/`; each inventory row has canonical repository-relative
path, exact raw-byte SHA-256, byte count, and executable bit. Cache directories
named `__pycache__`, `.mypy_cache`, `.pytest_cache`, or `.ruff_cache` and regular
`.pyc`/`.pyo` files are excluded. `guide_sha256` hashes the exact installed
`backstitch/guides/alignment.md` bytes. `skill_sha256` hashes the exact
`skills/backstitch-alignment/SKILL.md` bytes. Plan and result loading recompute
these values from the current authoritative files and reject a missing,
renamed, symlinked, non-regular, or byte-drifted input. Result values must equal
the manifest-derived values exactly.

The tested-distribution identity object is exactly:

```text
{
  schema_version: 1,
  artifact: "backstitch-tested-distribution-inventory",
  files: [{path, raw_sha256, byte_count, executable}]
}
```

Rows are unique and Unicode-code-point sorted by NFC path. `raw_sha256` uses the
prefixed hash form above, byte count is nonnegative, and executable is boolean.

The phase protocols give participants only installed public help, the installed
guide and repository skill, and their assigned fixture. They fix task prompts,
timing boundaries, label definitions, and first-diff rules. Phase A additionally
fixes these four authority-comprehension propositions: repository source is the
alignment authority; candidates are advice; Backstitch neither edits nor
ratifies source relations; semantic success cannot repair incomplete alignment.
A session passes comprehension only when all four are answered correctly.

For each Phase B task, the runner also supplies the exact Unicode-sorted
`candidate_id` projection of the frozen human `accepted` rows. This projection
is participant input, not an answer and not a Backstitch verdict. Rejected,
irrelevant, critical, and expected-trace-state labels remain hidden. Each task
records the supplied projection as `human_accepted_candidate_ids`, and the
validator requires exact equality with frozen gold. Phase B never scores a
participant's ability to infer the human disposition.

A changed phase fixture, threshold, prompt, rubric, or other phase-owned judged
input creates a new phase qualification digest and fresh phase result; the old
result remains in the record. A common tested distribution, guide, or skill
change invalidates both. Human labels are evaluation ground truth only and
never enter runtime alignment state. The manifest and both protocols receive
independent review before the run, so output cannot tune the test that judges
it.

Each participant receives phase fixtures one at a time in frozen order. A task
timer starts at the handoff that first exposes that fixture and prompt, not at
the first product call, and stops at the participant's final task submission.
The runner records those boundaries from a monotonic wall clock. Later fixtures
must remain unavailable until their own handoff. Installed help, guide, and
skill orientation may happen before the first timed task.

Each phase fixture manifest has exactly:

```text
{
  schema_version: 1,
  artifact: "backstitch-alignment-dogfood-fixtures",
  phase,
  fixtures: [{
    fixture_id, fixture_path, tree_manifest_path, tree_manifest_sha256,
    candidate_artifact_path, candidate_artifact_sha256,
    task_obligation_id, expected_bootstrap_outcome, expected_diagnosis,
    first_diff_required,
    required_trace_declarations,
    gold_candidates: [{
      gold_id, candidate_id, candidate_kind, path, start_line, end_line,
      structural_locator, receipt, trace_state, disposition_label, critical
    }]
  }]
}
```

`phase` is `A` or `B`; fixture IDs and gold IDs are unique nonblank strings and
fixtures sort by ID. Fixture paths, tree manifests, hashing, containment, and
object rules are [EVC-10.1]'s. `expected_bootstrap_outcome` is `completed` or
`correctly_diagnosed` for Phase A and null for Phase B. Phase A's initial state
is derived from the exact task obligation's production inventory and readiness
record before the run; a null target is `no_intent` only when that exact
inventory contains no addressable obligation. No repository-wide issue-code
heuristic may substitute. The five-fixture coverage rule applies to that
derived state, not to the final outcome. An initially
untraced, partial, or skipped fixture may therefore preregister `completed`
when the task requires source repair. `task_obligation_id` is the nonblank
target ID for a completed Phase A task and every Phase B task; it is nullable
only for a Phase A diagnosis.
`expected_diagnosis` is null for completed and Phase B tasks; otherwise it is
exactly `{bootstrap_state, blocking_reason_codes, next_action_codes}` using
[EVC-8.3]'s closed values and orders. Phase A has `first_diff_required = false`,
empty declarations and gold candidates, and null candidate-artifact fields.
Phase B uses null bootstrap outcome and diagnosis, a nonblank task ID, nonnull
candidate-artifact fields, and a complete reviewed gold-candidate set.
Disposition label is `accepted`, `rejected`, or `irrelevant`. A critical row is
listed in the parent manifest as `<fixture_id>#<gold_id>`; the two projections
must be exactly equal and the set is nonempty. A critical row has disposition
`accepted` or `rejected`; an `irrelevant` negative control cannot be critical.
Inclusive spans and vocabularies use [EVC-10.1]. `candidate_id` recomputes from
the candidate kind, canonical path, and structural locator under [EVC-7]. The
receipt recomputes byte-for-byte from that locator, span, and frozen tree.

Each Phase B candidate artifact has exactly:

```text
{
  schema_version: 1,
  artifact: "backstitch-alignment-dogfood-candidates",
  obligation_id,
  snapshot: {snapshot_hash, file_count, byte_count, unreadable_count},
  candidates
}
```

Its path and exact canonical-JSON hash are fixture-manifest fields. Loading the
preregistration reruns production snapshot capture, report construction, and
`obligation.find_evidence` discovery for the fixture's exact tree, task
obligation, profile, and settings. The derived artifact must be byte-identical,
including candidate IDs, receipts, locators, relations, trace states, advice,
ordering, and snapshot identity. This artifact is the frozen production
observation under test, not expected-label ground truth. It is evaluation input
only and never a runtime evidence or alignment authority.

One required trace declaration is exactly
`{form, target_id, evidence_role, gold_id}`.
`form` is `spec_mapping`, `code_backlink`, or `binding_test`; the other values
use their owning closed vocabularies and
`gold_id` must resolve to an accepted row in the same fixture. Rows are unique
and sort by form in that order, then target, role, and gold ID. The required set
is derived exactly from human-accepted candidates that the frozen production
artifact actually surfaced. The complete section relation is `spec_mapping`
plus `code_backlink` for the candidate's owning implementation or test role;
the required diff set is that complete relation minus declarations already in
the original fixture. Thus a partial candidate contributes only its missing
side and an untraced candidate contributes both. A spec-invariant
implementation target similarly contributes a missing `spec_mapping`, and an
invariant binding-test target contributes a missing `binding_test`. A
one-sided, already-present, or extra required set is invalid preregistration. A Phase B
fixture with at least one surfaced accepted candidate whose trace state is not
`declared` sets `first_diff_required = true` and declares one cumulative,
complete set of declarations missing from the original tree for every such
row. An accepted
already-declared candidate requires no diff and no new declarations. An
accepted candidate absent from production discovery is a capture miss, not an
impossible authoring task; it contributes no required declaration until the
product surfaces it. A fixture with no surfaced accepted non-declared row uses
false and an empty set. At least one fixture requires a first diff and at least
one fixture contains a surfaced accepted already-declared row. Gold candidates
label every candidate in the production-derived artifact exactly once by exact
candidate ID, locator, receipt, span, and kind. Expected `trace_state` is an
independently reviewed label; it is neither copied from nor required to equal
the artifact's discovered state at plan load. The reviewed gold set may also
contain source-bound candidates absent from production output. Each such row
must exist in the production parser's complete captured candidate catalog before
obligation selection, and its kind, ID, locator, span, and receipt must exactly
equal that catalog fact. It must be `accepted` or `rejected` rather than
`irrelevant`, enters the eligible capture denominator, and is uncaptured unless
output surfaces that exact ID. Human acceptance is independent of product
output; an absent source-bound row may therefore be accepted or rejected.
Candidate
IDs and full coordinates are unique. The corpus covers every reachable
kind/expected-state pair;
`report_issue` contributes only `partially_declared` and `conflicted`. An
unmatched, ambiguous, duplicate, or conflicting output invalidates the run
rather than acquiring a post-output label. A known contradicting declared
candidate is critical because omitting it would hide a known alignment failure.

Each phase produces its own independently content-addressed result. The common
result has exactly:

```text
{
  schema_version: 2,
  artifact: "backstitch-alignment-dogfood-result",
  phase,
  phase_qualification_sha256,
  prior_phase_result_sha256,
  tested_distribution_sha256,
  guide_sha256,
  skill_sha256,
  sessions,
  candidate_runs,
  metrics,
  checks,
  passed,
  failure_reasons
}

session = {
  session_id, participant_kind, participant_identity_sha256,
  public_help_only,
  tasks: [{
    fixture_id, human_accepted_candidate_ids, bootstrap_outcome,
    elapsed_milliseconds, backstitch_call_count,
    reviewed_diff_attempt_count, review_round_count,
    changed_source_paths, changed_source_line_count,
    source_revisions,
    backstitch_calls,
    cli_observations
  }],
  authority_answers: [{proposition, answer}]
}

source_revision = {
  ordinal, diff_path, diff_sha256,
  result_tree_manifest_path, result_tree_manifest_sha256,
  observed_trace_declarations
}

backstitch_call = {
  ordinal, argv, source_revision_ordinal
}

cli_observation = {
  ordinal, argv, source_revision_ordinal,
  source_tree_manifest_path, source_tree_manifest_sha256,
  output_path, output_sha256
}

candidate_run = {
  fixture_id, obligation_id,
  source_tree_manifest_path, source_tree_manifest_sha256,
  output_path, output_sha256,
  candidates: [{
    candidate_id, candidate_kind, path, start_line, end_line,
    trace_state, matched_gold_id
  }]
}

phase_a_metrics = {
  bootstrap_task_count, bootstrap_success_count,
  authority_session_count, authority_session_pass_count,
  bootstrap_completion_rate, authority_comprehension_rate
}

phase_b_metrics = {
  eligible_gold_candidate_count, captured_eligible_gold_candidate_count,
  captured_trace_state_correct_count,
  surfaced_candidate_count, irrelevant_candidate_count,
  first_diff_required_count, first_diff_correct_count,
  critical_candidate_count, critical_candidate_captured_count,
  candidate_capture_rate, trace_state_precision,
  irrelevant_candidate_rate, first_diff_correct_rate,
  all_critical_candidates_captured
}

check = {name, comparator, threshold, observed, passed}
```

All hashes use exact `sha256:<64 lowercase hex>`. Artifact paths are contained
result-relative POSIX paths. Session IDs are unique within a phase. Participant
kind is `human` or `agent`; participant hashes are unique within a phase, so
the minimum two sessions are independent. `public_help_only` is true. Every
session runs every fixture for its phase exactly once in fixture order.
Session-array length equals the corresponding preregistered session count.

`backstitch_calls` records every task-scoped product call in execution order;
one-time help/guide orientation before a task timer is not a task call.
Ordinals are contiguous, `source_revision_ordinal` binds the exact original or
revised tree in force for the call, and `backstitch_call_count` equals the call
array length. The closed read-only grammar permits obligation list/detail,
evidence summary, discovery, candidate detail, and pagination plus deterministic
`check` with optional suppression audit. It rejects mutation, packets, model,
provider, cache, and arbitrary command surfaces. Every recorded call binds
`--repo-root .`; `--format` is optional and, when present, is `text` or `json`.
Thus authoring-cost call count is not reduced to the smaller proof-observation
set.

A source revision is a complete unified diff from the original tree-verified
fixture, not from a prior attempt. Ordinals start at one and are contiguous.
The runner applies each exact diff to a fresh original fixture copy and requires
the result-tree manifest to match. `reviewed_diff_attempt_count` equals the
source-revision count. Changed paths and changed lines recompute from the final
tree's byte delta against the original tree, independent of diff headers, or
are empty and zero when there is no revision. The production declaration
parsers derive each revision's ordered declarations against its exact result
tree and bind them to the frozen gold candidate's kind, path, and structural
locator. The stored rows preserve multiplicity until duplicate or conflicting
gold-bound relations are rejected. An apply, tree, parse, gold binding, or
stored-declaration mismatch is an invalid observation.
First-diff correctness additionally requires the revised target obligation's
production readiness record to be `gate_state = "executable"`; a later repair
does not rescue the first diff. For Phase B, revision one is one cumulative diff
from the original fixture containing the exact complete missing-declaration set for all
surfaced, human-accepted, nondeclared candidates. Separate candidate-local
diffs do not satisfy this rule.

CLI observations are nonempty, ordered with contiguous ordinals, and bind exact
argv, source tree, snapshot, and canonical public JSON output.
`source_revision_ordinal` is null for the original fixture or resolves to a
source revision in the same task; its tree hash must equal that revision's
result tree hash. The only canonical command arrays are `backstitch obligation
list --repo-root . --format json`, `backstitch obligation <OBL> --repo-root .
--format json`, and `backstitch obligation <OBL> --find-evidence --limit 100
--repo-root . --format json` for their respective operations. The validator
reruns each recorded proof command from the bound exact tree through the public
module entry point and requires byte-identical stdout, exit zero, and empty
stderr.
Every proof observation must also occur in `backstitch_calls` at the same source
revision. The call log may contain additional read-only interactions whose
outputs are not qualification evidence.

An initially partial, untraced, or skipped Phase A task records the original
tree's `obligation.list` output first, has at least one source revision, and
records the exact target's `obligation.get` output from the final revision last.
An initially complete task records the target `obligation.get` output without a
revision. A no-intent diagnosis records `obligation.list` without a revision.
For `completed`, the final core result contains the preregistered target with
`gate_state = "executable"`; for `correctly_diagnosed`, its projection of
bootstrap state, blocking reasons, and next actions exactly equals the
preregistered diagnosis. Stored `bootstrap_outcome` equals this recomputation.

Each Phase B task records exactly one complete public `obligation.find_evidence
--limit 100 --format json` observation for its preregistered obligation and
original fixture tree. The limit is the closed evaluation proof limit and must
be large enough for every frozen candidate set; default-page calls and cursor
pages remain task interactions but are not substituted for the complete proof
run. The complete run must have `next_cursor = null`. Its source-tree manifest
path and hash plus output path, hash, and raw bytes exactly equal that fixture's
canonical candidate run and byte-exact public rerun. Equal or synthesized bytes
under a different path are not the bound observation. Phase B stores
null outcome. Counts, milliseconds, and changed-line counts are nonnegative
integers; paths are unique canonical source-relative POSIX strings in Unicode
order. The human-accepted projection is task input. The participant may flag a
believed preregistration defect outside the result; the owner must stop and
review it rather than coaching the participant or silently changing gold. A
confirmed defect creates new preregistered bytes and a new result.

Phase A uses `phase = "A"`, null `prior_phase_result_sha256`, exactly the
preregistered Phase A session count, empty candidate runs, `phase_a_metrics`,
and checks only `minimum_bootstrap_completion_rate` then
`minimum_authority_comprehension_rate`. Its sessions have the four authority
propositions in their declared order and empty
`human_accepted_candidate_ids`. It can pass and receive an owner stop/continue
disposition before a Phase B run or result exists; the complete Phase B
preregistration is still part of the frozen top plan.

Phase B uses `phase = "B"`; `prior_phase_result_sha256` is the exact canonical
JSON hash of a passing Phase A result whose Phase A qualification projection
matches the current top plan and whose tested distribution, guide, and skill
match Phase B. Phase B binds its own distinct qualification projection. It has
exactly the preregistered Phase B session count, `phase_b_metrics`, and checks
the remaining five thresholds in manifest order. Its authority-answer arrays
are empty. Each task's `human_accepted_candidate_ids` exactly equals the sorted
accepted gold projection, including accepted rows discovery omitted. Candidate runs exist
exactly once per Phase B fixture and sort by fixture ID. Each run's candidates
array must exactly equal the candidates reconstructed from its bound canonical
CLI JSON. The run binds the fixture's exact nonblank obligation ID and original
tree-manifest hash. Its snapshot and full candidate rows must equal the
production-rederived preregistration artifact. Relation kinds, source and target
IDs, locators, directions, row uniqueness, candidate-coordinate uniqueness,
trace states, advice, and [EVC-7] order are all validated. Each projection
matches the preregistered exact candidate ID and records that row's gold ID.
Unmatched, ambiguous, duplicate, or cross-obligation rows are invalid.

Metrics are recomputed, never averaged across session rates:

- bootstrap completion is Phase A tasks whose recomputed outcome equals their
  fixture's expected outcome divided by all Phase A tasks;
- authority comprehension is Phase A sessions whose four recorded raw boolean
  answers equal the frozen proposition rubric divided by all Phase A sessions;
- candidate capture is distinct captured `(fixture_id, gold_id)` rows whose
  gold disposition is `accepted` or `rejected`, matched by the exact candidate
  ID and source-bound gold identity projection, divided by all distinct Phase B gold
  rows with one of those two dispositions;
- trace-state precision is every surfaced candidate row whose discovered trace
  state equals its matched gold row divided by all surfaced candidate rows;
- irrelevant-candidate rate is surfaced candidate rows whose matched gold label
  is `irrelevant` divided by all surfaced candidate rows;
- first-diff correctness is Phase B session tasks for fixtures with at least one
  surfaced, human-accepted, nondeclared candidate whose first cumulative source
  revision's parser-derived declaration set exactly equals the fixture's
  required set and makes the target obligation executable, divided by all such
  session tasks; and
- all-critical-candidates-captured is true exactly when the captured critical
  count equals the nonzero gold critical count.

A zero numeric denominator serializes its rate as null and cannot pass. Counts
are nonnegative integers and rates are null or finite in `[0, 1]`. Comparators
are `>=` for minimums, `<=` for the maximum, and `true` for the boolean. Each
stored count, rate, check, pass flag, and failure-reason list must exactly equal
recomputation. Failure reasons are failed check names in order, preceded by
`INVALID_OBSERVATION` when any participant task, candidate run, bound artifact,
candidate match, or parser-derived declaration is invalid. A malformed outer
result or preregistration is rejected before metric recomputation. One phase
result passes only when no invalid observation exists and every applicable
check passes. Its exact
canonical JSON digest is recorded in that phase's owner-visible stage record;
neither result confers runtime alignment authority. A later product review may
cite both exact artifacts, but the semantic qualification report neither embeds
nor replaces either phase result or owner disposition.

1. **Obligation core:** inventory, readiness, evidence summary, guide, and CLI
   bootstrap qualify first. A public-help-only user must identify source intent,
   inspect declared evidence, explain that Backstitch does not ratify or edit
   traces, and reach or correctly diagnose the first executable obligation.
2. **Discovery and guidance:** Phase B asks, "Given obligation X, what current
   code or tests are plausible candidates for fulfilling X?" Candidate
   discovery qualifies against independent reviewed gold. After human
   disposition is supplied as input, authoring guidance qualifies against the
   cumulative source diff. It records search-set capture, false surfacing,
   trace-state correctness, and post-selection authoring correctness. It does
   not measure whether human disposition itself is easy, fast, or correct.
3. **Packets and currentness:** packet v3, current repository analysis, and
   historical replay qualify only after evidence sufficiency, mutation
   sensitivity, unrelated-edit stability, and stale-result rejection pass.
4. **Optional MCP:** MCP qualifies only after the CLI read model is stable and
   measured CLI call count, response bytes, or agent context cost shows a
   concrete adapter benefit. It additionally requires installed-wheel stdio
   parity. Semantic-policy success is not an MCP prerequisite.
5. **Semantic verification and policy:** analyzer/verifier qualification uses
   [EVC-10.1]. Stronger policy remains blocked until that artifact passes for
   the selected provider, model, prompt, and canonical semantic code.

The implementation chain is obligation core to discovery to
packets/currentness to semantic qualification. Qualification authority remains
separate: semantic policy requires the passing Phase C source-pipeline record
and [EVC-10.1] report, not a current Phase A/B human-session artifact. Current
bootstrap/discovery product claims still require current Phase A/B results.
Optional MCP branches after discovery; it does not depend on packet or semantic
qualification and neither one depends on MCP.

The obligation-core record includes elapsed time, reviewed source-diff attempts,
changed source files and lines, and Backstitch calls from the starting
untraced/partial state to the first executable obligation. Discovery labels are
evaluation ground truth chosen by a human reviewer: `accepted` means the
candidate appears in the final reviewed trace, `rejected` means it was plausible
but not selected, and `irrelevant` means it does not implement or test the
obligation. These records are qualification evidence, not runtime alignment
state or a second evidence manifest.

Phase B call count, elapsed time, review rounds, and changed lines measure the
cost of using Backstitch after the human disposition is handed off. They do not
measure selection burden. Candidate report usefulness is instead evidenced by
capture, irrelevant rate, exact trace state, complete advice, and successful
first-diff authoring. Re-running discovery against later repository snapshots
is part of the shipped bootstrap workflow, not a new source of authority.

For Phase B measurement, `accepted` and `rejected` rows are eligible discovery
gold: both are relevant candidates the tool should surface for human judgment.
`irrelevant` rows are negative controls the tool should omit. They are excluded
from the candidate-capture denominator and measured when surfaced through
`irrelevant_candidate_count` and `irrelevant_candidate_rate`. Every surfaced
row, including a tolerated irrelevant row, remains in the trace-state-precision
denominator because trace state is an independent deterministic claim. Every
critical row has disposition `accepted` or `rejected`; an `irrelevant` row
cannot be critical. This keeps capture and false-surfacing measurements
disjoint: a correct implementation is never required to surface a negative
control to pass capture, and every state it does surface must still be exact.

_Implementation mapping_:

- `backstitch/alignment_eval.py`

Each stage has an owner-visible stop/continue review. A failed or unavailable
later stage does not invalidate an already qualified earlier stage, but it
blocks every dependent stage and any claim that includes it. Stage records must
state the tested source identity, guide identity, interface surface, observed
values, threshold or correctness rule, and reviewer disposition.

## 11. Anti-Gaming And Trust Requirements [EVC-11]

All of these must hold:

- repository source is the only alignment authority;
- every satisfied section implementation role has reciprocal source trace;
- invariant readiness uses the existing declaration/bind/binding-test graph;
- derived artifacts cannot add, remove, or override evidence links;
- discovery exposes untraced and conflicted candidates instead of silently
  curating them away;
- over-approximate candidates remain advisory unless a closed source-based
  readiness rule says otherwise;
- packet membership is deterministic and complete under the configured
  universe, never agent or model selected;
- the verifier is blinded to analyzer and author reasons;
- skip remains reasoned, visible, denominator-preserving, and unable to grant
  coverage or conformance;
- semantic results cannot upgrade incomplete alignment or skipped disposition;
- packet-only replay is historical and cannot claim current repository
  conformance;
- no deterministic read or MCP operation imports a provider, reads credentials,
  makes network traffic, or writes repository source;
- semantic CI may treat repository bytes as hostile input only when the
  executable, locked dependencies, config, prompt, provider controls, mutable
  roots, and workflow definition are independently trusted;
- secret-bearing hostile-target workflows obtain generic CLI option keys and
  values only from static trusted workflow text; event payload fields and
  target bytes cannot select or construct configuration;
- no secret-bearing semantic step executes or installs target-repository code,
  hooks, plugins, workflows, configuration, or commands;
- a report-only pull-request run binds to an API-confirmed exact head revision,
  rechecks that binding immediately before provider work, and has no repository
  write or semantic failure authority;
- restored semantic cache bytes remain untrusted and cannot bypass complete
  packet, identity, provenance, schema, and evidence validation;
- public enumerations, schemas, ordering, budgets, and exits have firing tests.

The main Goodhart risks are fake trace links and irrelevant broad mappings.
Reciprocity proves declared reach, not relevance. The semantic corpus must
therefore include broad, vacuous, and misleading declared-evidence mutations.
The semantic lane may report weak or mismatched evidence, but cannot silently
rewrite the trace graph.

_Implementation mapping_:

- `backstitch/semantic_analysis.py`
- `backstitch/semantic_cache.py`

## 12. Verification Expectations [EVC-12]

<!-- backstitch: meta because docs/specs/04-backstitch-traceability-exclusions.md#SUP-VERIFICATION-META -->

Implementation is not complete until real-boundary tests prove:

1. Empty and no-spec repositories return the bootstrap state and action.
2. Mixed addressable obligations and unaddressable intent paginate in exact
   order with self-contained cursor validation.
3. Every readiness transition fires for sections and invariants, including
   missing, one-sided, duplicate, ambiguous, and complete relations.
4. Valid, malformed, duplicate, and ownerless skips preserve alignment facts,
   audit reasons, and evidence reads; no Backstitch command changes source.
5. Evidence summary returns exact coordinates, receipts, roles, and broken
   reciprocity.
6. Every candidate/relation/trace-state branch fires, including conservative
   unresolved and negative static-relation fixtures.
7. Repeated discovery is byte-identical; unrelated edits do not change
   obligation-local packet hash when its visible projection is unchanged.
8. Candidate/catalog/work/file/snapshot/packet budgets fail closed without a
   partial page, cursor, packet, cache, or policy result.
9. Mid-capture add, remove, replace, and permission mutations discard the
   entire attempt, retry at most the configured three times, and never mix
   bytes.
10. Stable symlink and non-regular inputs fail without traversal; replacing an
    intermediate directory during descriptor walk discards the attempt;
    unsupported platforms return the exact problem before traversal.
11. Current analyze rejects every output, staging, cache, lock, guard, audit,
    or provider-local mutable path that overlaps a captured semantic input.
12. After successful capture, resolver, parsers, readiness, discovery, and
    packet construction survive live replacement/deletion because they never
    reopen source; current analyze's final recapture detects the change.
13. Phase D has an explicit `implemented` or `deferred` owner disposition. If
    implemented, CLI JSON and a real installed-wheel stdio MCP client return
    byte-identical canonical core results for every success and problem family.
    If deferred, the distribution advertises no MCP command, tools, or resource.
14. Obligation reads, deterministic discovery, guide, packet generation, and
    `check` neither import a provider nor make network traffic; the same holds
    for MCP when Phase D is implemented.
15. Packet v3 recomputes from source, includes the full closed evidence and
    counterevidence universe, and has no alternate manifest authority.
16. Current analyze publishes only after equal start/end snapshots; historical
    packet replay is labelled and structurally unable to claim a current gate.
17. Analyze and verify call counts, exact outbound bytes, identities, cache
    hits/misses, evidence reconstruction, failure aggregation, and policy
    projection have firing tests without live providers.
18. Every public command, flag, state, candidate kind, relation kind, trace
    state, guidance code, problem code, schema version, config key, and exit
    path has at least one firing test.
19. The scale fixture meets [EVC-10]'s time, work-count, and memory ceilings.
20. The full self-corpus gate exits 0 with zero errors and warnings; all
    suppressions remain exact and auditable through `--show-suppressions`.
21. Every row of [EVC-8.7]'s combined exit matrix fires, including failing
    non-skip trace diagnostics on an all-skipped corpus and every legacy
    completeness key's selected/all-skipped behavior.
22. Eval primary-only, replay-only, equal, and divergent findings reconstruct
    exact nullable side states, hashes, comparison signatures, and flip counts.
23. Fixture tree manifests reject missing/extra/changed/symlink files, and the
    performance gate refuses a runtime that differs from the committed runner
    contract.
24. Selected and zero-packet all-skipped reports reproduce readiness counts
    from exact alignment-audit rows and preserve every non-failing
    deterministic issue; a skipped untraced obligation is distinguishable
    from a skipped completely aligned obligation.
25. Mutating only an alignment-audit or deterministic-issue row corrupts the
    packet-report content identity; packet-report input and generated output
    over the exact byte ceiling fail before partial packet, audit, cache,
    analysis, or policy publication.
26. [EVC-10.2]'s obligation and discovery manifests, fixtures, thresholds,
    critical IDs, prompts, and rubric are content-addressed and independently
    reviewed before their dogfood; at least two sessions per phase run before
    claiming current bootstrap or discovery product qualification. Their
    records keep bootstrap cost, candidate quality, packet quality, and
    semantic quality in separate denominators. Every result count, rate,
    zero-denominator value, critical-capture flag, check, and pass value
    recomputes exactly from the bound fixture, CLI-output, diff, and session
    observations. A stale or absent Phase A/B result cannot enter or silently
    block semantic-report authority.
27. Enabled verify accepts the exact same analyze provider/model tuple in
    `provider_source = "analyze"` mode and an optional complete override tuple.
    Analyze mode requires no distinct credential configuration or duplicate
    cost table; override mode rejects every partial/fallback shape. A different
    `--model` or `LLM_MODEL` selects a complete trusted model descriptor and
    cannot retain stale revision/cost metadata. Same-model and distinct-model
    compositions receive separate inference identities. Evidence-stable
    analyzer results retain their producing identity; qualification never
    transfers to the selected model.
28. An exact failure-authority selector with missing, corrupt, failing, or
    identity-mismatched qualification exits 2 before provider work and emits
    the requalification action. It also precedes cache work unless [SEM-4]'s
    sorted review-lock selection is required to discover carried producers;
    that exceptional path still creates no result or baseline. Firing probes
    cover equal CLI/environment model values, catalog-resolved different
    CLI/environment values, unknown model selectors, carried results from a
    different analyzer identity, complete analyze descriptor changes, complete
    verifier-override changes, and equal-to-distinct composition changes.
    Every analyzer/verifier composition and source-derivation-version field
    invalidates the selector; packet/claim instance, per-event trial
    index/effective epoch, path, budget, and policy changes do not. Changing
    configured `verify.eval.trials`, any threshold, or another
    qualification-identity field does invalidate authority. With no
    failure-authority selector, the same unavailable artifacts remain
    report-only and non-promoting.
29. Evaluation derives a distinct effective analyzer epoch per trial and a
    distinct effective verifier epoch for every ordered configured base epoch
    and trial. Primary analyzer/verifier execution makes one call per distinct
    key; require-mode replay makes zero calls. Stored `analysis_attempts`
    include `ok` results and exact cache-object/provenance records. Stored
    events retain and recompute both base and effective epochs; changing only
    trial index does not invalidate report-level composition identity.
30. Variant-scoped obligation, evidence, candidate, packet, receipt, and
    required-evidence gold reject every cross-variant reference. Historical
    unit references, duplicate historical target tuples, multiple expected
    findings for one packet, the 20-target floor, required control tags,
    nonempty critical cases, and a critical valid-vacuous-trace subset all have
    failure probes.
31. Expected findings, event rows, by-code cohorts, and check prefixes use long
    `SEMANTIC_*` codes in [SEM-6] order. Long and `BSA00*` selectors normalize
    to the same cohort; aggregate pass never substitutes for a missing or
    failing exact-code cohort.
32. Report-mode and enforce-mode checks use the same raw observations. A false
    `require_all_critical` setting makes its boolean check nonbinding without
    rewriting `observed`; enforce requires true. Negative variants qualify only
    through their exact variant gold projection, and every by-code equation is
    independently recomputed.
33. Eval output and configured report paths reject corpus, fixture, tree-
    manifest, and config aliasing before adapter construction. Corpus case,
    variant, fixture path, tree-manifest path, historical-unit, and expected-
    finding identities each have duplicate and ordering failure probes.
34. Public-CLI cache lifecycle probes use real temporary cache roots and
    provider call counters to fire `off`, `read-write`, and `require`; exact
    hit, miss, packet-change, policy-only, search-epoch, deleted-cache,
    corrupt-cache, restore-failure-reset, fresh-publishable-report, and
    pre-report-failure branches all preserve [SEM-4] and [SEM-7].
35. Trusted semantic workflow probes bind the tool checkout to the run's exact
    default-branch SHA, bind the target checkout to the API-confirmed readable
    head repository and SHA, revalidate immediately before provider work, keep
    secrets and every executable/configurable input outside the target, move
    only immutable packet/result cache trees under distinct trusted workflow
    prefixes, and give the pull-request lane no repository write or semantic
    failure authority. Real hostile-target subprocess fixtures prove successful
    data-only analysis separately from fail-closed captured-root symlink
    rejection.

Acceptance probes use real temporary repositories, Markdown and Python
parsers, resolver, filesystem, CLI subprocesses, packet/cache/report loaders,
and, when Phase D is implemented, real installed-wheel stdio MCP framing.
Provider adapters may be controlled, but request
bytes, identities, normalization, cache, and failures remain real. Tests must
not mock the resolver for readiness, parser for guidance, candidate index for
CLI or implemented MCP, or cache for packet identity.

Acceptance probes cover mixed schema-3/schema-4 packet JSONL,
packet-report schema 2 compatibility and schema 3 production,
suppression obligation/API behavior, analyzer and optional verifier
evidence binding, empty and nonempty required-kind completeness, and the
invariant that schema-3 section/invariant bytes and identities do not change
merely because suppression support is installed.

### 12.1 Required Cross-Spec Promotion [EVC-12.1]

<!-- backstitch: meta because docs/specs/04-backstitch-traceability-exclusions.md#SUP-EVC-PROCESS -->

This revision changed active contracts through one coordinated spec change;
EVC does not silently override them. The promotion recorded in the related
plan required the following exact reconciliations and one independent review:

- [SC-5], [SC-8], and [SC-16] register `obligation`, `guide alignment`, and,
  when Phase D is implemented, `mcp`; add current `analyze --repo-root`;
  preserve lazy provider imports; and state that no obligation or implemented
  MCP operation writes repository source. SC-16 also removes every remaining
  `evidence case` and `frozen case` authority phrase in favor of source
  alignment and derived packets. SC-16 defines verifier independence as
  blinded adversarial procedure, not provider/model or statistical
  independence. SC-16's metric-identity rule replaces its final sentence with:
  `Semantic qualification reports exact counts, rates, confidence bounds, and
  pass checks bound to one committed corpus and exact composed inference
  identities; Backstitch emits no blended correctness percentage or calibrated
  model score.`
- [SC-6], [SC-7], [SC-13], [INV-5], and [SEM-3] through [SEM-9] adopt packet
  schema 3, packet-report schema 2, exact model projection, current/historical
  scope, deferred current-result publication, and new cache identities as one
  migration. Packet schema 2 remains readable only for bounded historical
  diagnostics and cannot satisfy a schema-3 gate.
- [CFG-3], [CFG-5], [CFG-6], [CFG-8], and [CFG-9] register the exact
  `[tool.backstitch.obligations]` table, config anchor behavior for repo-root
  current analysis and packet replay, verify `provider_source` plus its
  all-or-nothing provider override, the exact `[tool.backstitch.verify.eval]`
  qualification table, MCP optional dependency, and no-op-prevention tests.
  `[tool.backstitch.verify.eval]` is the sole promoting evaluation path;
  superseded `[tool.backstitch.analyze.eval]` is always rejected as settings;
  only its schema-2 report fields remain explicit historical artifact input and
  grant no policy authority. Superseded case/proposal/activation keys are
  rejected as unknown, not ignored. [CFG-5]'s descriptor-selection rule applies
  whenever enabled verify uses `provider_source = "analyze"`, even if analyze
  is cache-off: `--model` and `LLM_MODEL` select either the flat descriptor or
  an exact trusted catalog descriptor and cannot retain another model's
  revision or cost metadata. Evidence-stable carried results retain their
  original analyzer identity and never borrow current-model qualification.
- [EXC-4], [EXC-6], [EXC-7], and [EXC-8] adopt [EVC-8.3.2]'s skip grammar,
  audit projection, malformed behavior, and source-read-only boundary. Skip
  suppresses semantic execution only. It neither changes alignment nor
  suppresses ordinary trace diagnostics; repositories that also want those
  diagnostics non-gating use existing exact reasoned issue suppression.
  BSX010 is allocated as reserved during the spec-only checkpoint and becomes
  implemented atomically with its skip-reason emitter and firing test;
  BSX004, BSX010, and BSX001 take the exact packaged warning behavior stated
  there instead of EXC-8's strict-loader exit for this recognized
  repository-source grammar.
- [INV-5] makes a spec-declared invariant without a valid bound target
  non-executable instead of producing a warning-bearing semantic packet. A
  code-declared invariant's declaration owner is its implementation target.
  Both forms still require a valid binding test. Code-only invariants remain
  unskippable in v1.
- [SC-4]'s unreadable-file continuation is preserved for deterministic check
  and read operations through [EVC-8.2]'s stable unreadable manifest row.
  Discovery, packet generation, and current semantic analysis fail when an
  unreadable included input prevents a complete candidate catalog.
- `SEMANTIC_MISSING_TRACE`/`BSA003` is not emitted for a syntactically missing
  mapping, backlink, bind, or binding-test relation. Those defects stop current
  semantic execution through deterministic readiness. BSA003 remains only for
  a syntactically complete reciprocal graph whose packet content is judged not
  to establish the claimed behavioral trace. The old
  `trace_reference_removed` semantic mutation moves to deterministic alignment
  evaluation; its semantic replacement preserves valid syntax but makes the
  declared relation substantively vacuous.
- [SEM-6]'s setting `candidate_handling` is renamed `finding_handling` because
  this spec uses candidate for discovered source. The old name is a one-release
  deprecated alias that cannot coexist with the new name; equal or conflicting
  dual specification is invalid configuration rather than precedence magic.
  [SEM-7]'s `candidate_debt` report field becomes `finding_debt`, and all help,
  defaults, reports, tests, and prose make the same vocabulary migration.
- [SEM-5], [SEM-6], and [SEM-7] adopt [EVC-6]'s full context vocabulary,
  first-match precedence, packaged-level matrix, failure-authority rules, and
  report values: `evidence_bound`, `verification_indeterminate`,
  `independently_verified`, `mechanically_verified`, `human_verified`,
  `disputed_by_verifier`, and `human_rejected`. Legacy `corroborated`
  normalizes read-only to `evidence_bound`; producers stop emitting generic
  `disputed`. Every transition and precedence pair gets a firing test.
  Independently verified remains advisory unless the exact current
  [EVC-10.1] qualification artifact passes for the selected BSA code;
  mechanical and human contexts keep their distinct authority.
- [SC-15] allocates only `OBLIGATION_SKIPPED`/`BSE001` and no case-lifecycle
  BSE codes. Existing trace and invariant diagnostics remain authoritative;
  EVC operation problems use [EVC-8.4]'s non-suppressible problem vocabulary.
- Proposed [COV-6] removes its broker, proposal, activation, and frozen-case
  wording and consumes obligation discovery as advice whose accepted outcome
  is an ordinary human-reviewed source diff. [COV-9] tests deterministic
  worklist ranking and source-diff outcomes, not `uncovered_next` proposal
  objects. EVC promotion cannot leave the related proposed spec describing the
  superseded flow.

Promotion evidence includes exact hashes for every coordinated spec, default
self-corpus exit 0 with zero errors and warnings, suppression audit, and an
independent PASS with no open P1/P2 finding. Those bytes and observed results
are recorded in the related plan; a later normative change requires the same
review discipline.

### 12.2 Canonical Configuration Resolution [EVC-12.2]

Firing tests must prove the full defaults/config/environment/CLI cascade
through the public CLI and the canonical resolver. They cover every
`--option` value family and error family in [CFG-5.1], the exact
dedicated-setting alias map, operational non-aliases, minimal and dormant
disabled verifier shapes, arbitrary explicit and extended TOML filenames,
command-specific anchors, single resolution per invocation, direct
typed-settings injection below the boundary, and rejection before
provider/cache/output effects.

Workflow contract tests must prove that trusted refresh and hostile-target PR
analysis explicitly select the trusted checkout's `pyproject.toml`, use the
exact reviewed literal options from [SEM-9.1], and never derive config or
option text from event payload or target repository data. Tests use real
temporary files, TOML parsing, environment mappings, CLI parsing, and command
dispatch. They must not mock the canonical resolver, config discovery,
`extend`, settings validation, or the trusted/target path split.

_Implementation mapping_:

- `backstitch/coverage_application.py`
- `tests/test_cli.py`
- `tests/test_cli_config.py`
- `tests/test_coverage_application.py`
- `tests/test_doctor.py`
- `tests/test_release_workflow.py`
- `tests/test_config_parity.py`
- `tests/test_semantic_analysis.py`
- `tests/test_semantic_settings.py`
- `tests/test_settings.py`

## Related Plans

- `docs/plans/2026-08-23-gpt-5-6-luna-responses-plan.md`
  (active implementation plan; request capabilities, Responses migration,
  and release qualification)
- `docs/plans/2026-08-04-semantic-preparation-performance-plan.md`
  (implementation plan; [EVC-9.1])
- `docs/plans/2026-07-29-usability-remediation-plan.md`
  (active implementation and coordinated specification plan; [EVC-2.2],
  [EVC-8.3], [EVC-8.4], [EVC-8.7], and [EVC-9.1])
- `docs/plans/2026-07-29-architecture-quality-remediation-plan.md`
  (active implementation plan; [EVC-3.1], [EVC-5.1], [EVC-10.1], and
  [EVC-12.2])
- `docs/plans/2026-07-28-intent-coverage-implementation-plan.md`
  (active implementation plan; [EVC-7]/[EVC-8] shared read-only inventory)
- `docs/plans/2026-07-28-evidence-stable-semantic-result-reuse-plan.md`
  (specification and implementation plan)
- `docs/plans/2026-07-28-documented-suppression-governance-plan.md`
  (implemented and independently reviewed)

- `docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md`
- `docs/plans/2026-07-27-semantic-analysis-lifecycle-plan.md`
- `docs/plans/2026-07-27-canonical-config-resolution-plan.md`
  (implementation and verification recorded)

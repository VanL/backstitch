# Verification And Evidence Case Spec

Status: Proposed

Related specs:

- `docs/specs/02-backstitch-core.md` [SC-4] through [SC-8], [SC-10],
  [SC-13], [SC-15], [SC-16]
- `docs/specs/03-backstitch-configuration.md` [CFG-3], [CFG-6], [CFG-8]
- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-4], [EXC-6.2],
  [EXC-7], [EXC-8]
- `docs/specs/05-backstitch-invariants.md` [INV-5], [INV-7], [INV-9]
- `docs/specs/06-semantic-gates.md` [SEM-1] through [SEM-10]

This spec extends the semantic gate ([SEM-*]) with an independent
verification stage, an obligation-centered agent interface backed by a
deterministic evidence broker, and a durable,
content-addressed **evidence case** as the unit CI validates. [SEM-*] governs
how one model result is produced, bound, cached, and policed. This spec governs
how a *claim* accumulates independent support, how an agent discovers and
proposes relevant evidence through deterministic interfaces, how Backstitch
validates and activates that proposal as a frozen case, and how CI re-validates
the active case without re-running discovery.

## 1. Purpose And Scope [EVC-1]

The semantic lane's analyze stage is a bounded search heuristic. Search
output alone must not gate. This spec defines the two mechanisms that turn a
searched claim into something a repository may gate on:

- an **adversarial verify stage**, independent of analyze, that attempts to
  falsify each candidate claim and returns a structured, evidence-bound
  verdict with a support score;
- an **evidence case**: a frozen, content-addressed proof object containing
  the claim, its proof obligations, every cited span with digests, the
  deterministic candidate universe considered, recorded omissions, and the
  assembly record — so that CI validates a bounded case instead of asking an
  agent to rediscover the repository.

The mental model is proof-carrying review: the stochastic part searches for
and assembles the proof object once, at authoring time; the checking part is
cheap, bounded, and repeatable. Trust concentrates in the checker and in
measurement, never in the searcher.

This spec does not claim mechanical semantic truth. A verified claim is a
measured, replayable judgment — stronger evidence, not proof. Nothing in
this spec may be described as mechanical verification; that term remains
reserved for [SEM-5] `mechanically_verified`.

## 2. Overall Model [EVC-2]

The full pipeline, including the [SEM-*] layers it builds on:

```text
deterministic packet or evidence case
  -> analyze: candidate claim search               (stochastic, cached)
  -> deterministic evidence binding                ([SEM-5])
  -> verify: independent falsification attempt     (stochastic, cached)
  -> support score -> conservative event aggregate (measured, [EVC-5])
  -> verification state and diagnostic context     ([SEM-5]/[SEM-6])
  -> packaged default policy -> applied policy     ([SEM-6])
  -> fail_on -> exit 0 / 1 / 2                     ([SEM-7])
```

And the obligation and evidence-case lifecycle around it:

```text
specifications -> obligation list -> one obligation
        -> current evidence/counterevidence views
        -> deterministic evidence discovery and named candidate detail
        -> agent evidence proposal                 (stochastic, untrusted)
        -> deterministic proposal validation
        -> explicit obligation activation          (atomic, content-addressed)
        -> human review and ordinary repository landing
        |
        +-> explicit obligation skip annotation    (scoped, reasoned, auditable)
        |
        v
CI validates each non-skipped obligation and its active frozen case:
  spans still match -> universe recomputed and diffed
  -> coverage obligations met -> cached verdicts reused
  -> policy applied
```

Layer boundaries mirror [SEM-2]: classification and verdicts are
policy-neutral; verification state is trusted metadata; diagnostic identity
is stable vocabulary; severity comes from policy. Changing policy re-uses
cached analyze and verify results with zero provider calls.

## 3. The Verify Stage [EVC-3]

Verify is a second, independent stochastic judgment over a canonical finding
produced by analyze. A frozen evidence case shapes the finding's packet, but
is never itself direct verifier input. Its contract:

- **Adversarial task.** The verify prompt instructs the model to construct
  the strongest counter-interpretation of the claim and to identify what
  would make the claim false. It is not asked to agree.
- **Blinded input.** The verifier receives the claim, its proof obligations,
  and a closed verifier-case projection. That projection contains case ID/hash,
  target requirement, proof obligations, current selected implementation/test/
  counterevidence spans, exact current spans for every omitted universe
  candidate, and universe candidate IDs/kinds/paths/locators
  with selected/considered/omitted state. It exposes reason-free obligation
  completion state but excludes every assembler reason, question text,
  exploratory log, analyzer support estimate, analyzer summary or rationale,
  and prior verify verdict. Trusted normalization constructs the projection
  rather than redacting an open case object.
- **Independent identity.** Verify has its own prompt ID/version/byte-hash
  and its own configured model and request controls, defaulting separately
  from analyze. Its `(backend_id, plugin_id, model, model_revision)` tuple must
  differ from analyze's tuple; otherwise enabled configuration is invalid.
  A different model family is preferred because distinct IDs do not remove
  correlated failure modes. The verify inference contract and cache key follow
  the [SEM-3] rules with a distinct contract family; analyze and verify
  results never share a cache object.
- **Canonical claim.** An analyzed claim is bound by the exact [SEM-6] finding
  projection whose canonical SHA-256 is `finding_hash`: code, classification,
  packet kind, packet ID, packet hash, and ordered trusted evidence. EVC names
  that existing digest `claim_hash`; it does not hash summary, rationale,
  confidence, or other presentation text. The verifier's model-visible claim
  contains exactly `claim_hash`, code, classification, packet kind/ID/hash,
  and ordered evidence coordinates `{role, path, start_line, end_line,
  excerpt_sha256}`. It excludes evidence excerpt text because the trusted case
  sources below provide each current body once. The verifier request contains
  that canonical claim projection and only the trusted closed verifier-case
  projection defined below, derived from the case-mode source packet and
  validated active case. Exact preimages are in [EVC-3.1].
- **Structured output.** The untrusted model response contains exactly
  `claim_hash`, `verdict`, `support_score`, `rationale`, and `evidence`.
  Verdict is `supported`, `unsupported`, or `indeterminate`; score is in
  `[0.0, 1.0]`; rationale is nonblank; and evidence uses [SEM-5] model fields.
  Trusted normalization replaces quotes from shown content and rejects any
  citation outside it. The immutable cache object is the exact [EVC-3.1]
  record. Cache hits recursively revalidate all identities and evidence.
- **Evidence sufficiency.** A `supported` result uses a classification-aware
  minimum. `confirmed_mismatch` and `probable_mismatch` cite `requirement` and
  `implementation`. Section `missing_trace` cites `requirement` and at least
  one `implementation`, is valid only in case mode, and requires the trusted
  complete structural-relation projection to show no declared mapping or
  backlink for the target. It proves absence of the required trace edge, not
  absence of implementation. Invariant `weak_binding` cites `requirement` and
  `implementation` and is valid only in case mode. When selected test evidence
  exists it also cites `test`; only the absent-test variant may omit that
  citation, and then the trusted projection must show a complete universe with
  zero eligible test candidates. `ambiguous` cites `requirement` plus at least one of
  `implementation`, `test`, or `counterevidence`. `unsupported` cites
  `requirement` plus at least one `implementation`, `test`, or
  `counterevidence` region. `indeterminate` cites at least the requirement;
  its nonblank rationale names the missing or conflicting evidence. Extra
  citations may use only those four roles and exact shown regions. A result
  that violates this matrix or a required complete-universe precondition is
  malformed tool output, never a verdict. No `supported` result is eligible
  unless `case_verifiable` is true and every proof-obligation status is
  `complete` or validly `complete_absent`; `complete_absent` can support only
  the invariant weak-binding absent-test branch. Otherwise the finding remains `evidence_bound` with context
  `verification_indeterminate` without a provider call.
- **Failure is not falsity.** Provider failure, malformed output, or
  evidence-binding failure of the verify result is a tool failure ([SEM-7]
  exit `2` semantics), never `unsupported`.

An `unsupported` verdict on an analyze finding does not delete the finding;
it sets the finding's verify context (see [EVC-6]) so policy can decide.
Configured verify epochs select distinct keyed adversarial repetitions without
modifying the frozen case; they are not claimed as statistically independent
samples. Repeated identical requests replay from cache and are one event.
The exact selection and aggregation rules are in [EVC-5].

### 3.1 Closed Verifier Contracts [EVC-3.1]

The verifier-case projection contains exactly:

```text
schema_version = 1
claim_hash
packet_id
packet_hash
case_id
case_evidence_hash
obligation_id
target
proof_obligations
evidence_sources
case_verifiable = true
universe_complete = true
structural_relations_complete = true
universe
structural_relations
```

`target` contains exactly the [EVC-9.1] requirement `path`, `start_line`,
`end_line`, `raw_sha256`, `normalized_sha256`, and `receipt_hash`; requirement
text appears only in the source catalog below. A `proof_obligations` row
contains exactly `proof_obligation_id` and `status` (`complete` or
`complete_absent`, or `unresolved`) and sorts by ID. `evidence_sources` is the
exact maximal, deduplicated, text-bearing [EVC-9.1] catalog and order. It
contains the requirement and every packet evidence candidate, including each
considered or omitted candidate rendered as analyzer counterevidence, while
showing each source line at most once per role. No receipt body is copied into
the claim, target, universe, or a second omission array. An accounted candidate
without one current showable source prevents `case_verifiable`. A verifier-
universe row contains exactly
`candidate_id`, `candidate_kind`, `path`, `structural_locator`, and
`decisions`; decisions use the exact [EVC-4.1] shape and order. A structural-
relation row contains exactly `proof_obligation_id`, `candidate_id`, and
`relation_kind`, where relation kind is one of the four derived kinds in
[EVC-4.1]. Rows sort by `(proof_obligation_id, candidate_id, relation_kind)`.
The two completeness booleans and `case_verifiable` are set only after [EVC-9]
reconstructs the entire universe and all derived relations. Any unresolved
proof obligation prevents `case_verifiable`; its question and reason remain
hidden. Trace mode has no verifier-case projection and cannot invoke verify.

This projection contains no reason, open question, exploratory telemetry,
analyzer text/score, proposed relation, prior verdict, or disposition. Its
`verifier_case_hash` is the lowercase SHA-256 of [SEM-3] canonical JSON for
the complete projection above.

The verify inference contract contains exactly:

```text
contract_version = 1
prompt = {id, version, sha256}
provider = {
  backend_id, plugin_id, model_id, model_revision,
  adapter_id, adapter_version, llm_distribution_version,
  plugin_distribution_name, plugin_distribution_version
}
request = {json_mode, temperature, seed, max_tokens}
```

This is the exact [SEM-3] offline provider/request identity under a distinct
verify contract family. Strings are nonblank in cached modes, versions are
validated exactly as [SEM-3], prompt/adapter versions are positive integers,
hashes are lowercase SHA-256, and request values follow [EVC-5]. The exact
model-input object contains `request_schema_version = 1`, canonical `claim`,
`verifier_case`, `verifier_case_hash`, and the event `search_epoch`. Request
bytes are the verify prompt instruction bytes, two newline bytes, then
canonical JSON for that object. The epoch is therefore both model-visible and
keyed; configured repetitions are distinct requests, though not statistically
independent samples.

Before cache lookup or provider construction, Backstitch counts those exact
UTF-8 request bytes for every event and requires each to be at most
`verify.maximum_prompt_bytes`. Overflow is exit `2` with
`BUDGET_EXHAUSTED`, the exact byte count, and an action to reduce the reviewed
case/universe spans or raise the reviewed ceiling. It makes zero provider calls
and cache writes. The ceiling is operational policy and does not enter the
inference contract; the exact request bytes already do. Orientation and
proposal validation report the conservative request upper bound defined in
[EVC-8.3.1], so an inevitable overflow is visible before activation/analyze.
Analyze still measures the exact request for each actual claim.

Each configured event has this exact key preimage:

```text
{identity: "verify-event", version: 1, claim_hash, case_evidence_hash,
 verifier_case_hash, search_epoch, inference_contract}
```

`verify_key` is lowercase SHA-256 of its canonical JSON. Distinct claims,
semantic case evidence, shown bytes, universes, relations, epochs, prompts, models, controls, or
adapters cannot collide. Operational budgets and concurrency do not enter.

The immutable `verify/results/<verify_key>.json` object contains exactly
`schema_version = 1`, `object_type = "verify-result"`, `verify_key`, `claim`,
`case_evidence_hash`, `verifier_case_hash`, `search_epoch`, `inference_contract`,
`result`, `provenance`, and `raw_response_sha256`. `result` contains exactly
`claim_hash`, normalized `verdict`, finite `support_score`, nonblank
`rationale`, and canonical `evidence`. Evidence uses [SEM-5]'s exact trusted
record and order. `provenance` reuses the exact [SEM-4] provenance record.
Unknown fields or any path/key/content mismatch are cache corruption and exit
`2`, never a miss.

Verify cache concurrency uses these disjoint paths:

```text
verify/results/<verify_key>.json
verify/locks/<verify_key>.lock
verify/guards/<verify_key>.guard
verify/audit/locks/<verify_key>.<audit_sha256>.json
```

Every [SEM-4] validation, immutable no-replace publication, guard, advisory
lock, single-flight, waiter, owner-token, failure cleanup, stale-lock audit,
and filesystem rule applies by exact substitution of `verify_key` for
`analysis_key` and object-type prefix `verify-` for `semantic-`. Provider calls
never occur while holding the guard, and concurrent misses produce at most one
verify provider call. Explicit cleanup uses `backstitch cache cleanup-lock
--cache-path PATH --family verify --key VERIFY_KEY --lock-stale-seconds N
--reason TEXT`; family is closed to `analyze` or `verify`, and verify cleanup
can touch only the paths above.

## 4. Evidence Cases [EVC-4]

An evidence case is the durable unit for claims whose evidence spans more
than one packet, or that a repository wants to gate on over time. It is a
canonical JSON object, content-addressed by `case_hash` (SHA-256 of the
complete canonical case payload excluding the `case_hash` envelope field,
using [SEM-3] canonical serialization rules). Agent proposal reasons and
relations remain labeled untrusted data, but their exact bytes are still
hash-bound so review history cannot change without a new case hash. The object
is committed to the repository as the human-readable PR-diff projection.

In v1, a case target is exactly one canonical spec section or declared
invariant. The semantic claim is derived, not agent-authored: the repository's
implementation and tests conform to the target's exact normative content at
the addressed snapshot. Backstitch derives these closed proof-obligation IDs:

| Target | Proof-obligation ID suffix | Meaning |
|---|---|---|
| section | `::implementation` | Selected implementation evidence supports the normative section |
| section | `::test` | Selected test evidence exercises the normative section |
| invariant | `::implementation` | Selected target evidence implements the invariant |
| invariant | `::binding-test` | Selected binding-test evidence exercises the invariant |
| both | `::counterevidence` | Every deterministic counterevidence candidate is considered or omitted with reason |

The full proof-obligation ID is the canonical `obligation_id` plus the suffix.
Custom free-form claims or agent-defined proof-obligation schemas require a
later case-format version. Backstitch derives the proof obligations, but only
the agent may propose that a selected candidate semantically supports one.

A frozen case must contain:

- the exact semantic claim, stated once; its stable case ID; and its one
  canonical `obligation_id` ([EVC-8])
- its proof obligations: the enumerated sub-claims that must each hold
- the portable repository identity and exact repository snapshot against which the
  proposal was validated and frozen
- the canonical agent proposal: selected implementation evidence, selected
  test evidence, counterevidence considered, reasoned omissions, and open
  questions; every selection and unresolved request names a derived proof
  obligation; the proposal contains candidate IDs and reasons, never
  agent-supplied trusted locators, digests, universe membership, or validation
  states
- every cited source span: stable candidate ID, path, structural locator, exact
  excerpt, exact receipt hash, and a **normalized span digest** (see below)
- the exact target section or invariant text, structural locator, target
  receipt hash, and normalized target digest from which every proof obligation
  was derived
- every typed relation between a proof obligation and cited candidate,
  using the closed vocabulary `declared_mapping`, `declared_backlink`,
  `invariant_binding`, `static_reference`, `semantic_support`, and
  `counterevidence`; structural relations record their trusted derivation,
  while semantic support and counterevidence record untrusted proposal status
- the deterministic candidate universe considered ([EVC-7]): every member,
  each marked included or omitted, every omission carrying a nonblank reason
- unresolved evidence requests, if any, each with a proof-obligation ID,
  nonblank question, and reason
- the configured candidate and response budgets, plus the deterministic
  selected-evidence totals reconstructed from unique cited broker receipts;
  exploratory call totals and wall time are adapter telemetry, not trusted
  case fields
- content-addressed receipts for the exact broker observations cited by the proposal,
  plus the deterministic reconstruction record used at activation; exploratory
  adapter logs may be retained for audit but are not gate authority
- the evidence-guide identity, broker schema version, universe-construction
  version, and case-format version

`case_id` is the stable SHA-256 identity of repository ID plus canonical
obligation ID and is unchanged by refresh. `case_hash` identifies one frozen
version. Neither the active-manifest path nor local clone path is another case
identity. Stable IDs render as `case:sha256:<64 lowercase hex>` and
`candidate:sha256:<64 lowercase hex>`; content hashes render as
`sha256:<64 lowercase hex>`.

Analyze and verify outputs are not case fields. They are produced after activation
and stored as separate immutable cache objects whose identities bind the case
semantic evidence through packet or claim identity and the inference contract.
The audit-only `case_hash` is not an inference key. This keeps the case
immutable and prevents a stochastic result from changing its evidence identity.

Candidate and observation identities are different because they identify
different things. `candidate_id` is stable across non-structural content
edits: it hashes the portable repository ID, canonical repository-relative
path, parser-owned structural locator, and candidate kind. A structural edit
that changes the locator intentionally changes the candidate ID. Universe
diffs compare candidate IDs.
Definition, reference, report-issue, and target locators use the exact closed
[EVC-4.2] objects. Line numbers and raw digests never enter candidate identity.
`receipt_hash` identifies one exact observation: it binds the portable
repository/candidate coordinate, exact excerpt digest, normalization digest,
and broker schema, but not the repository-wide snapshot. The case object binds
the capture snapshot separately for audit. An unrelated file edit therefore
does not rename an unchanged receipt.
Proposal input uses candidate IDs; activation derives and records receipt hashes.

Span normalization v1 is an exact byte transform. Decode strict UTF-8; replace
each CRLF pair with LF, then every remaining CR with LF. On each resulting
line remove only trailing U+0020 SPACE and U+0009 TAB code points. Preserve all
other code points, leading indentation, internal blank lines, comments,
docstrings, tokens, and line order. Remove every terminal LF, then append
exactly one LF when the remaining text is nonempty; the empty result stays zero
bytes. Re-encode UTF-8. Comments can carry Backstitch refs, invariant binds,
suppressions, type directives, and coverage pragmas, so comment changes are
semantic for case validity. Invalid UTF-8 is unreadable input and never a
replacement-decoded receipt. The normalization algorithm is code-owned and
versioned; changing it is a case-format version bump. Raw-byte digests are
recorded alongside as provenance.

Invalidation is obligation-scoped: a changed span invalidates exactly the
obligations that cite it, not the whole case. A case with some invalidated
obligations is stale, not deleted; refresh re-assembles only the invalidated
obligations from the current deterministic universe.
Target requirement churn is the exception: a changed normalized target digest
invalidates every derived proof obligation because their meaning may have
changed. Raw-only target churn preserves case currency but changes packet and
cache identity exactly like raw-only source churn.

Normalized case validity and semantic cache identity are separate contracts.
When the normalized span digest is unchanged but the raw bytes changed, the
case remains current, but packet generation uses the current exact bytes. The
packet hash therefore changes and required semantic replay may need a trusted
cache refresh. Formatting tolerance must never be represented as byte-stable
model input.

Agent-facing proposal input is canonicalized at its write boundary: safe
identifier and path near-misses are normalized and reported through [EVC-8]
guidance. Frozen cases remain a closed trusted schema. Unknown structural
fields at activation or CI validation are rejected with an exact repair action;
this deliberate strictness protects canonical hashing and provenance rather
than treating an unknown field as harmless extension data.

### 4.1 Closed Case Artifact [EVC-4.1]

The immutable case object contains exactly these top-level fields:

```text
schema_version = 1
object_type = "evidence-case"
case_id
case_hash
case_evidence_hash
repository_id
repository_snapshot
obligation_id
claim
target
proof_obligations
universe_contract
expanded_candidates
implementation_evidence
test_evidence
counterevidence_considered
omissions
open_questions
universe
relations
receipts
budgets
reconstruction
guide
```

`claim` contains exactly `claim_contract_version = 1`, `kind =
"conformance"`, `obligation_id`, and `target_receipt_hash`. `target` contains
exactly `target_kind` (`section` or `invariant`), `path`,
`structural_locator`, `start_line`, `end_line`, `excerpt`, `raw_sha256`,
`normalized_sha256`, and `receipt_hash`. A proof-obligation row contains
exactly `proof_obligation_id` and `kind` (`implementation`, `test`,
`binding-test`, or `counterevidence`) plus `status` (`complete`,
`complete_absent`, or `unresolved`). A section has exactly implementation,
test, and counterevidence rows; an invariant has exactly implementation,
binding-test, and counterevidence rows. `complete_absent` is allowed only for
an invariant binding-test row when the complete mandatory universe has zero
eligible test candidates. It is derived, never agent-asserted. A section test
obligation with no candidate remains unresolved. An open question makes
its named obligation `unresolved`; otherwise allowed selected evidence and
complete counterevidence accounting make it `complete`.

`universe_contract` contains exactly `contract_version = 1`, the fixed ordered
`candidate_kinds`, fixed ordered `relation_kinds`, canonical ordered
`profile_name`, `spec_roots`, `plan_roots`, `code_roots`, `test_roots`, and
`exclusions`, canonical ordered `planned_spec_globs` and
`exploratory_spec_globs`, positive `maximum_candidate_items`,
positive `maximum_catalog_items`, `static_neighbor_depth`, and nonblank
`universe_algorithm_version` and `report_issue_projection_version`.
Candidate-kind order is `implementation`,
`test`, `static_reference`, `unresolved_reference`, `report_issue`. Relation-
kind order is `declared_mapping`, `declared_backlink`, `invariant_binding`,
`static_reference`, `semantic_support`, `counterevidence`.

The five proposal arrays preserve the exact agent judgments but never acquire
trusted status. An expanded-candidate row contains exactly `candidate_id` and
nonblank `reason`. Implementation, test, counterevidence-considered, and
omission rows contain exactly `proof_obligation_id`, `candidate_id`, and
nonblank `reason`. An open-question row contains exactly
`proof_obligation_id`, nonblank `question`, and nonblank `reason`.

A `universe` row contains exactly `candidate_id`, `candidate_kind`, `path`,
`structural_locator`, `receipt_hash`, and `decisions`. Each decision contains
exactly `proof_obligation_id` and `decision` (`selected`, `considered`, or
`omitted`). A `relations` row contains exactly `proof_obligation_id`,
`candidate_id`, `relation_kind`, `trust` (`derived` or `proposed`), and
nullable `reason`. Derived relations require null reason and use only the four
structural relation kinds; proposed relations require a nonblank reason and use
only `semantic_support` or `counterevidence`.

A `receipts` row contains exactly `receipt_hash`, `candidate_id`, `path`,
`structural_locator`, `start_line`, `end_line`, `excerpt`, `raw_sha256`, and
`normalized_sha256`. Every universe receipt resolves exactly one row; target
receipt fields live only in `target`.

`reconstruction` contains exactly `broker_schema_version`,
`snapshot_algorithm_version`,
`universe_algorithm_version`, `report_issue_projection_version`,
`normalization_version`, `case_format_version`, `proposal_sha256`, and
`universe_sha256`.
`guide` contains exactly nonblank `guide_id`, positive integer `guide_version`,
and `content_sha256`.

`budgets` contains exactly `maximum_response_bytes`,
`maximum_candidate_items`, `maximum_catalog_items`, `maximum_snapshot_files`,
`maximum_file_bytes`, `maximum_snapshot_bytes`, `maximum_proposal_bytes`,
`maximum_proposal_text_bytes`, `maximum_case_bytes`, `static_neighbor_depth`,
`accounted_candidate_count`, and `accounted_raw_bytes`. All are integers
excluding booleans and nonnegative; configured maxima are positive.
`accounted_candidate_count` is the number of
unique universe candidate IDs having at least one `selected`, `considered`, or
`omitted` decision. `accounted_raw_bytes` groups those candidates' receipt
intervals by path, merges overlapping inclusive physical-line intervals, and
sums the UTF-8 byte length of the exact captured slices for the resulting
maximal intervals. Source bytes, including captured line terminators, count at
most once even when candidate receipts overlap; adjacent non-overlapping
intervals remain separate but do not duplicate bytes. An empty-module virtual
span contributes zero bytes. The target receipt is not a universe candidate
and is excluded from both counts.

Canonical array order is: proof obligations by ID; expanded candidates by
`(candidate_id, reason)`; each evidence/omission array by
`(proof_obligation_id, candidate_id, reason)`; open questions by
`(proof_obligation_id, question, reason)`; universe by `candidate_id`, with
decisions by `(proof_obligation_id, decision)`; relations by
`(proof_obligation_id, candidate_id, relation_kind, trust, reason-or-empty)`;
and receipts by `receipt_hash`. Root, exclusion, and classification-glob
strings are unique and sort by Unicode code point. `profile_name` and every
algorithm/reconstruction version string are nonblank. IDs are unique in their
owning array except one
candidate may have decisions for distinct proof obligations. Every path is a
canonical repository-relative POSIX path, every line is a positive integer
with end not before start, and every digest/ID uses its required lowercase
format. Unknown fields, duplicate identities, broken cross-references, or
non-canonical order are invalid.

`case_hash` is the SHA-256 of canonical JSON for every field above except
`case_hash` itself. The canonical indented object stored on disk has the same
semantic values and is serialized with `json.dumps(sort_keys=True, indent=2,
ensure_ascii=True, separators=(",", ": "))`, UTF-8 encoding, and exactly one
terminal newline. Whitespace does not enter the hash. `proposal_sha256` hashes
the canonical [EVC-8.4] proposal after its arrays are put in the orders above
and after removing only the global `active_manifest_hash` compare-and-swap
token. That token is an activation precondition/result, not case identity.
`universe_sha256` hashes the canonical `universe` array. These rules make the
artifact independently reproducible without trusting the freezing process.

`case_evidence_hash` is a separate semantic identity. Its exact preimage is:

```text
{
  identity: "evidence-case-semantic",
  version: 1,
  case_id,
  repository_id,
  obligation_id,
  target,
  proof_obligations,
  universe_contract,
  universe,
  relations: [{proof_obligation_id, candidate_id, relation_kind, trust}],
  receipts,
  reconstruction: {
    broker_schema_version,
    snapshot_algorithm_version,
    universe_algorithm_version,
    report_issue_projection_version,
    normalization_version,
    case_format_version
  }
}
```

Every value and array order is the exact corresponding [EVC-4.1] value and
order. The relation projection removes only `reason`. The preimage excludes
`case_evidence_hash`, `case_hash`, `repository_snapshot`, every agent
reason/question string, guide provenance, proposal digest, and active-manifest
CAS state. It changes for
evidence, decisions, structural/proposed relation types, receipts, target, or
semantic reconstruction-contract changes, but not advocacy prose or
operational response/time budgets. Semantic universe limits already enter the
snapshot and universe contract. The rendered value is
`sha256:<64 lowercase hex>` and the full case hash binds it.

### 4.2 Versioned Identity Preimages [EVC-4.2]

All identity preimages use [SEM-3] canonical JSON and contain exactly the
shown fields. The digest is SHA-256 of those UTF-8 bytes:

```text
case_id:
  {identity: "evidence-case-series", version: 1,
   repository_id, obligation_id}

candidate_id:
  {identity: "evidence-candidate", version: 1,
   repository_id, path, structural_locator, candidate_kind}

receipt_hash:
  {identity: "evidence-receipt", version: 1,
   repository_id, candidate_id, path, structural_locator,
   start_line, end_line, raw_sha256, normalized_sha256,
   broker_schema_version}
```

The case and candidate digests render with their named prefixes from [EVC-4].
Receipt digests render `sha256:<64 lowercase hex>`. `raw_sha256` is the digest
of the exact UTF-8 excerpt bytes and `normalized_sha256` is the digest after
the versioned [EVC-4] normalization. Target receipts use the same preimage with
`candidate_id` replaced by the canonical `obligation_id` and add
`target_kind`; this is a separate exact variant, not a fabricated candidate.

`structural_locator` is a closed canonical JSON object, never a delimiter-
joined string. Its variants are:

```text
Python definition:
  {kind: "python_definition", definition_kind, name_path}

Python reference:
  {kind: "python_reference", owner_name_path, reference_kind,
   normalized_target, occurrence}

Report issue:
  {kind: "report_issue", code, target_kind, target_id,
   owner: {path, line, section_id, symbol, invariant_id}}

Spec target:
  {kind: "spec_section", spec_path, section_id}

Code invariant target:
  {kind: "invariant_code", invariant_id, declaration_kind: "code",
   owner_name_path}

Spec invariant target:
  {kind: "invariant_spec", invariant_id, declaration_kind: "spec",
   section_id}
```

Name paths are arrays of exact Python identifier spellings from outermost to
innermost lexical definition; module has an empty path. Definition kind is
`module`, `class`, `function`, or `async_function`. Reference kind is one of
`import_module`, `import_name`, `call_name`, `call_import_alias`,
`call_module_member`, `call_self_member`, `call_cls_member`, or `unresolved`.
`normalized_target` is the NFC-normalized token spelling after the exact alias
table resolution in [EVC-7.2], with dotted components joined by one period and no
added whitespace. `occurrence` is the zero-based source-order index among
references with the same owner path, reference kind, and normalized target.
Report-owner `path` is canonical repository-relative, and its other four
fields are the exact nullable [SC-6] Issue coordinates; `line` is null or
positive. Target and issue kinds use their existing closed vocabularies. The source path remains the
separate identity `path`; each invariant variant rejects the other variant's
owner field. Unknown keys or variants are invalid. The locator object itself enters identity preimages, so JSON escaping
handles delimiter-like target text without another escaping rule.

## 5. Support Scores And Calibration [EVC-5]

`support_score` is model self-estimate. It is uncalibrated and must not be
named, rendered, or documented as a probability. Policy may threshold on it,
but a finding gated only by an uncalibrated score cannot exceed the packaged
advisory ceiling in [SEM-6]. Calibrated probability and calibration-map
artifacts are outside v1; adding them requires a new reviewed spec and cannot
be enabled by an unknown config key.

Verify uses a complete, separate, non-secret table. No value inherits from
`[tool.backstitch.analyze]`. This is an enabled repository example, not the
packaged default:

```toml
[tool.backstitch.verify]
enabled = true
backend_id = "llm"
plugin_id = "provider-plugin"
plugin_distribution_name = "provider-distribution"
model = "provider-model-id"
model_revision = "repository-declared-revision"
concurrency = 1
cache_path = ".backstitch/semantic-cache"
cache_mode = "require"            # off | read-write | require
search_epochs = ["1"]              # ordered, unique, nonblank
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
lock_stale_seconds = 3600
maximum_runtime_seconds = 1800
maximum_estimated_cost_microusd = 1000000
input_cost_microusd_per_million_tokens = 400000
output_cost_microusd_per_million_tokens = 1600000
input_token_overhead = 256
cost_rate_source = "reviewed source and date"
```

The packaged default has `enabled = false`. In that state Backstitch makes no
verify calls, reads or writes no verify cache objects, emits no verification-
debt record or verify notice, and projects no `independently_verified` state.
Enabling verify requires the repository to supply the complete table above,
including reviewed model identity, budgets, and cost rates. An incomplete
enabled table or any unknown key is a configuration error.

When enabled, the resolved `(backend_id, plugin_id, model, model_revision)`
tuple must differ from the resolved analyze tuple. This establishes an
independent model identity and separate blinded protocol; it does not claim
statistical independence between repeated verify epochs or model families.

`enabled` is boolean. `minimum_support_score` is a finite number in `[0, 1]`.
`required_verdicts` is an integer excluding booleans and at least one.
`indeterminate` is exactly `allow` or `report`. Cost, budget, timeout, cache,
model, and request fields use the [SEM-9] value rules for their corresponding
analyze keys; no type coercion occurs. `maximum_prompt_bytes` is an integer
excluding booleans and at least one. `search_epochs` is the ordered nonblank
string list constrained below.

Backend, plugin, distribution, model, revision, JSON mode, temperature, seed,
maximum tokens, verify prompt descriptor, and adapter identity enter the
verify inference contract. Epoch enters the separate verify event identity and
model request. Operational budgets and concurrency do not. The
validation and mode rules for the shared fields are exactly [SEM-3]/[SEM-9];
missing independent identity fields are configuration errors. The length of
`search_epochs` must equal `required_verdicts`, which is a positive integer;
epochs are unique and their listed order is canonical.

Aggregation is conservative and order-independent after selecting that exact
configured set:

| Events for one `claim_hash` | Aggregate state |
|---|---|
| Any provider/tool/malformed/binding failure | exit `2`; no aggregate verdict |
| Any `unsupported` | `disputed` with context `disputed_by_verifier` |
| Otherwise any missing event under required replay | exit `2` and `CASE_VERDICT_MISSING` |
| Otherwise any `indeterminate` or supported score below threshold | `evidence_bound` with context `verification_indeterminate` |
| All `supported` and every score meets the threshold | `independently_verified` with context `verified` |

The displayed aggregate support score is the minimum selected event score,
never an average or probability. Policy changes reuse the same event objects.
Adding, removing, or reordering configured epochs changes the verification-run
identity but not an existing event's cache key.

`indeterminate = "allow"` projects the documented indeterminate context with
no separate debt record or stderr notice. `report` additionally appends the
claim hash and event keys to the closed verification-debt report and emits one
concise non-failing stderr notice. Neither mode exits `2` merely because the
verdict is indeterminate; exact diagnostic policy may still control the target
finding. Unknown values are configuration errors.

Correlated error is acknowledged, not hidden: two model judgments from
similar models share failure modes. The [SEM-8] lane must therefore measure
verify quality separately per configured verify model, and the promotion
requirements of [SEM-8] (zero hard-fail false positives on negative
controls, recall with interval, replay stability) apply to the combined
analyze-plus-verify pipeline end to end, not to the verifier in isolation.

### 5.1 Invocation, Reports, And Exit Ownership [EVC-5.1]

`backstitch analyze` owns verify execution. After each non-`ok` analyze result
is normalized into a canonical finding and before policy projection, it runs
or replays the configured verify events only when verify is enabled, the
packet is case mode, and the active case satisfies [EVC-9]'s policy-independent
`case_verifiable` predicate. Trace-mode, stale, incomplete, and unresolved-case
findings remain `evidence_bound` and make no verify cache access or call.
`backstitch eval` invokes the same production path. `summarize-analysis` never
runs or replays verify; it only validates and renders an existing report.

Analyze result JSONL remains the policy-neutral schema-v2 analyze rows. Verify
events remain immutable cache objects; trusted aggregate state appears in the
analysis report and semantic diagnostic projection, not by rewriting result
rows.

Every post-EVC [SEM-7] analysis-report producer emits schema version 2.
Version 1 is read-only migration input. Version 2 contains every version-1
field unchanged plus exactly one new top-level `verification` field. That
record contains exactly `enabled`,
`cache_hits`, `cache_misses`, `provider_calls`, nullable
`estimated_cost_microusd`, nullable `cost_rate_source`, `events`, `debt`, and
`case_diagnostics`.
When disabled, `enabled` is false, counts are zero, nullable fields are null,
and all three arrays are empty.

When verify is enabled but a finding is not `case_verifiable`, no verification
event, debt, or BSE005/BSE006 row is created because no event was required or
attempted. Counts do not change. The ordinary semantic diagnostic remains
`evidence_bound` with `verification_indeterminate` context and the case-
validation diagnostics explain the policy-independent reason. Thus no empty
verify-key list or null aggregate score is serialized as a synthetic event.

An event row contains exactly `claim_hash`, `case_id`, `case_hash`,
`case_evidence_hash`, `verifier_case_hash`, ordered `verify_keys`,
`aggregate_state`, `context`,
`aggregate_support_score`, and `minimum_support_score`. Aggregate support is
the [EVC-5] minimum selected event score; state/context pairs are exactly
[EVC-6]. Rows preserve packet input order, then canonical finding-code and
claim-hash order within a packet. Verify keys preserve configured epoch order. A debt row
contains exactly `claim_hash`, `case_hash`, `case_evidence_hash`, ordered
`verify_keys`, and
`context = "verification_indeterminate"`; debt rows preserve event order.
`indeterminate = "allow"` leaves debt empty, while `report` appends the row and
emits its one concise stderr notice.

A verification case-diagnostic row contains exactly `code`, `short_code`,
`packet_id`, `claim_hash`, `case_id`, `case_hash`, `case_evidence_hash`, `context`,
`default_severity`, `severity`, `message`, and `winning_policy_rule`, reusing
[SEM-6]'s exact rule record. `analyze` emits BSE005 once for a claim when any
configured event is absent after cache replay/attempt, and emits BSE006 once
when any selected event is `unsupported`. Their exact contexts are
`missing_verify_event` and `disputed_by_verifier`, respectively. Unsupported
produces both
the original BSA finding in `disputed_by_verifier` context and the BSE006 audit
row; it never deletes either. Rows preserve event order then BSE code order.

The failure row in [EVC-5]'s aggregation table has precedence over every
verdict row. In a mixed set with one valid `unsupported` event and one failed
or absent event, the failed report retains BSE005 and BSE006 audit rows for the
two observed conditions, but emits no aggregate event row, no debt row, and no
`disputed_by_verifier` BSA projection. The immutable analyzer result row and
valid verify cache object remain available for diagnosis. Exit is `2`; the
partial event set cannot become a target finding.

BSE005/BSE006 use [SC-15] visibility levels but are failure-ineligible audit
diagnostics: no applied severity can grant them exit `1`. A missing required
event still causes mandatory exit `2` through the verify-cache/completeness
problem regardless of BSE005's info/warning/off presentation. BSE006 has no
exit effect. `eval` obtains the same records only through its production
analyze substages; no evidence command emits either code.

[SEM-7] report problems gain stages `verify_cache`, `verify_provider`, and
`verify_normalization`, paired respectively with its existing cache/provider/
malformed-result codes. Any verify cache miss under require mode, provider
failure, malformed response, binding failure, missing configured event, or
invalid aggregate makes report status `failed` and overall analyze exit `2`.
Tool/completeness exit `2` takes precedence; otherwise a projected diagnostic
in `fail_on` exits `1`; otherwise analyze exits `0`. No verify problem becomes
`unsupported`, `indeterminate`, or a target finding.

## 6. Verification State And Policy Integration [EVC-6]

Verify extends the [SEM-5] trusted verification-state vocabulary with one
state and three exact diagnostic contexts:

- `independently_verified`: an independent, blinded, adversarial verify
  event (or the configured N of them) returned `supported` with scores
  meeting the applied thresholds. This is a specific, protocol-bound
  strengthening of [SEM-5] `corroborated`.

The projection table is:

| Aggregate outcome | Verification state | Diagnostic context |
|---|---|---|
| all required events supported above threshold | `independently_verified` | `verified` |
| any unsupported event | existing `disputed` | `disputed_by_verifier` |
| indeterminate or below threshold | existing `evidence_bound` | `verification_indeterminate` |
| missing/tool failure | no projected finding | exit `2` problem |

Diagnostic projection follows [SEM-6]. Contexts are selectable exactly, for
example:

```toml
[[tool.backstitch.diagnostics.levels]]
select = ["SEMANTIC_CONFIRMED_MISMATCH:verified"]
level = "error"
```

Policy boundaries:

- The packaged default policy keeps `analyzed` (evidence_bound),
  `corroborated`, and `verified` findings advisory. Its
  `independently_verified` levels match [SEM-6]'s
  `mechanically_verified` column exactly: warning for BSA001 through BSA004
  and info for BSA005. Packaged defaults never make a stochastic verdict an
  error.
- A repository-applied policy may promote `verified` findings to `error`
  only when the applied `[tool.backstitch.verify]` thresholds are met and the [SEM-8] eval
  mode for the verify lane is `enforce` with measured, committed
  thresholds. Promotion without a measured baseline is a configuration
  error.
- `unsupported` uses the existing `disputed` state and the
  `disputed_by_verifier` context. It is advisory and visible; it does not
  suppress the finding.
- `indeterminate` and below-threshold support use `evidence_bound` plus
  `verification_indeterminate` and follow the exact allow/report behavior in
  [EVC-5].
- [SEM-5]'s boundary is preserved: `mechanically_verified` and
  `human_verified` remain the only states the *packaged* policy may treat
  as error-eligible. `independently_verified` error promotion is always a
  repository decision, made against measurement.

## 7. The Candidate Universe [EVC-7]

The assembling agent must never be the sole judge of what evidence is
"all the necessary code". Completeness of consideration is deterministic:

The closed v1 candidate kinds are `implementation`, `test`,
`static_reference`, `unresolved_reference`, and `report_issue`. Root role,
parser node, or report ownership derives the kind; the agent never supplies it.

- Backstitch constructs the **seed set** from the target section or invariant,
  every valid mapping and backlink edge for it, invariant targets and binding
  tests, and every deterministic report issue bound to the target.
- Backstitch constructs the **mandatory candidate universe** by repeatedly
  adding the captured Python import and static-reference neighbors of every
  code or test definition in the seed set, in candidate-ID order, through
  `static_neighbor_depth`. Depth zero is the seed set only; depth one adds its
  direct neighbors. Closure stops at the configured depth or a fixed point.
- The agent may **expand** the universe with additional candidates (each
  recorded with a reason) through the contained candidate-resolution operation
  in [EVC-8]. Each expanded candidate becomes another seed and receives the
  same configured closure. Proposal validation computes the fixed universe;
  newly exposed members make the proposal incomplete until selected,
  considered, or omitted with a nonblank reason. Open questions affect proof-
  obligation readiness, not candidate accounting. The agent can never remove
  a member.
- At validation time ([EVC-9]) the universe is **recomputed** from current
  repository structure and diffed against the frozen universe. Members
  present in the recomputation but absent from the frozen case — a new
  caller, a new implementation, a new binding test — make the case stale.
  Span digests detect mutation of considered evidence; the universe diff
  detects the *addition* of unconsidered evidence. Both are required; hash
  checks alone would freeze omissions-by-evolution into green cases.

V1 Python relations are deliberately closed:

- imports resolve `import module [as alias]` and `from module import name [as
  alias]` only when the module maps to exactly one captured `.py` file under a
  configured code or test root;
- calls resolve `name(...)`, an imported `alias(...)`, `module.name(...)`, and
  `self.name(...)` or `cls.name(...)` inside a captured class only when lexical
  scope, the import table, or that class yields exactly one definition;
- dynamic imports, re-exports without one captured target, wildcard imports,
  higher-order calls, computed attributes, and other `object.name(...)` calls
  are unresolved and never guessed;
- inverse caller edges are built only from those same resolved calls. Ordering
  is `(candidate_id, relation_kind, source_locator, target_locator)`.

An unresolved form in the closure becomes a mandatory
`unresolved_reference` candidate only when its normalized module or name can
plausibly target the captured repository: a module-qualified or imported form
must have a first module segment that matches a captured local module; an
unqualified or computed call must have a terminal referenced name that matches
a captured definition in the candidate catalog. Clearly external unresolved
references may be retained as bounded orientation telemetry, or omitted from
the mandatory universe, but they are never guessed into local relations. This
rule prevents ordinary dependency calls from making every case permanently
incomplete while keeping plausible local ambiguity visible.

Deterministic counterevidence candidates are: target-bound report issues,
mandatory unresolved-reference candidates, ambiguous same-name definitions
encountered during resolution, and closure members not already classified by
a declared mapping/backlink or invariant bind as implementation or test
support. The public operation is therefore `--find-evidence --kind
counterevidence`; it proposes places that may weaken the case and does not assert semantic
counterevidence. A static relation proves only that the parser observed a
source relation. It does not prove runtime reach or that a test assertion
checks the obligation. Runtime tracing is outside v1.

The broker's report-issue projection consumes the resolver's raw deterministic
`Issue` inventory after planned/exploratory profile classification but before
traceability suppression, diagnostic-level policy, `fail_on`, or synthetic
unused-suppression findings. A suppression can hide presentation noise but can
never shrink a mandatory evidence universe. Effective `profile_name`,
`plan_roots`, `planned_spec_globs`, and `exploratory_spec_globs` enter the
snapshot and universe contract because they can change target or report-issue
classification. `meta_spec_globs`, its `process_spec_globs` alias, lint ignore
tables, `warn_unused_ignores`, diagnostic levels, and `fail_on` do not enter:
the raw report-issue projection is defined to be independent of them.
`report_issue_projection_version` changes whenever that raw resolver seam or
its target-binding rule changes.

Universe construction parameters (edge kinds, neighborhood depth, size
budget) are non-secret configuration recorded inside the frozen case; a
parameter change is a case-invalidating event, not a silent widening.
`maximum_catalog_items` caps unique candidate IDs across the complete global
catalog of every eligible captured origin, independent of obligation. Catalog
construction follows candidate-ID order and fails with observed count
`limit + 1` as soon as the next unique member would exceed the ceiling; it
returns no partial catalog. `maximum_candidate_items` separately caps unique
candidate IDs in one addressed obligation's mandatory fixed-point universe,
including closure from every agent-expanded seed. The limit is checked after
each deterministic closure insertion and fails at observed `limit + 1` with
no partial page, proposal receipt, or frozen case. Page size and aggregate
exploration calls do not consume either ceiling.
Universe reads are ordered and paginated. A page cursor is a self-contained,
snapshot-bound continuation token; it is not server-side session state, and a
fresh CLI process or MCP server can serve the next page from the full call
address alone.

### 7.1 Closed Candidate Spans [EVC-7.1]

Every candidate receipt uses the captured byte image and this closed span
table. Source lines are one-based and inclusive. An excerpt is the exact bytes
from the beginning of its start line through the end of its end line, including
captured line terminators that fall inside that slice; an unterminated final
line is not modified. The empty module has span `1..1` and an empty excerpt.

| Candidate origin | Receipt span |
|---|---|
| path-only Python implementation/test or module definition | complete captured file |
| class, function, async function, or code-invariant owner | complete tree-sitter definition, beginning at the first decorator when present |
| static or unresolved Python reference | complete lexical owner definition; complete file when owner is module |
| invariant binding test | complete bound test definition, beginning at its first decorator |
| deterministic report issue | complete target section or invariant requirement span |

Tree-sitter points are zero-based and end-exclusive. The start line is
`start_point.row + 1`. When `end_point.column = 0` and the end row follows the
start row, the inclusive end line is `end_point.row`; otherwise it is
`end_point.row + 1`. The decorated-definition wrapper, not only its inner
definition, supplies these points. A multiline reference therefore receives
its owner body once, not an arbitrary call-line fragment. A report-issue
candidate's `path` is the target requirement path; its locator retains the
issue's own [SC-6] coordinates. A missing target or unreadable owner cannot
produce a receipt and prevents universe completeness.

Candidate-specific receipts may have identical or overlapping spans. They
remain distinct observations because candidate IDs differ. [EVC-9.1] performs
the separate maximal model-visible merge, preserving every candidate and
receipt identity in text-free subrows while showing overlapping source lines
once per role.

### 7.2 Python Module And Alias Resolution [EVC-7.2]

Module identity is derived only from captured `.py` files under configured
code/test roots. For each containing root, derive one name as follows. If the
root itself contains captured `__init__.py`, the root contributes its final
path component as the package prefix; otherwise it is an import base and
contributes no prefix. Append the file path relative to the root, remove the
`.py` suffix, and remove a final `__init__` component. Every remaining
component must be a Python identifier and not a keyword. Repository root `.`
has no final component and never contributes a prefix. A file contained by
overlapping roots is importable only when every root derives the same module
name. One module name mapping to multiple files, an empty derived name, or
disagreement across roots is ambiguous and never guessed.

For a file that is not `__init__.py`, its current package is its module name
without the final component; for `__init__.py`, it is the whole module name.
A relative import with `d` leading dots starts at that package and removes
`d - 1` trailing components; insufficient components are unresolved. Its
written module components are then appended. Absolute imports use their
written components. Resolution succeeds only when the resulting module maps
to one captured file. `from M import N` first resolves `M`; `N` resolves to a
captured submodule `M.N` when one exists, otherwise to exactly one captured
module-scope definition named `N` in module `M`. Both is ambiguous; neither is
unresolved.

Each lexical definition owns an import-binding table. At a reference,
bindings from enclosing scopes through the current scope are considered;
the innermost binding wins, then the latest import textually before the
reference. Any parameter, assignment target, loop/with target, exception
target, local definition, or deletion of the same spelling in that Python
scope makes an import binding there unavailable; Backstitch does not emulate
runtime control flow. `import A.B as X` binds `X` to module `A.B`; without
`as`, it binds `A` to module `A`. `from M import N as X` binds `X` (or `N`)
to the unique submodule/definition resolution above. Wildcard imports create
no bindings. Import aliases affect only references after their import node.

The normalized target for a resolved import/reference is its fully qualified
module name, plus one period and definition name where applicable. An
unresolved target is the NFC-normalized exact dotted token spelling after
removing surrounding syntax, with no whitespace rewriting inside identifiers.
Call resolution then applies [EVC-7]'s closed call forms against this alias
table and the captured lexical definition table. Any collision, shadowing,
unsupported syntax, or multiple definition remains an
`unresolved_reference`; it never chooses by filesystem or traversal order.

## 8. Obligation Interface And Evidence Broker [EVC-8]

The public aggregate root is an **obligation**: one spec section or invariant
that Backstitch can inspect, discover evidence for, activate, check, skip, or
unskip. Evidence cases, candidates, receipts, relations, cursors, and the
mandatory universe are subordinate protocol nouns. They remain exact and
inspectable, but an agent does not assemble the domain model from broker
endpoints before it can ask what the repository requires.

Assembly runs against a deterministic **evidence broker**, not against raw
repository access. One transport-neutral library owns obligation discovery,
evidence discovery, canonicalization, pagination, relation derivation,
budgets, receipts, and response guidance. The CLI and MCP server are thin
adapters over that library; they may not define transport-specific obligation
or evidence semantics.

### 8.1 Teaching And Progressive Disclosure [EVC-8.1]

An agent must be able to become competent through Backstitch itself. The
surface is taught in three layers:

1. **Reference:** `backstitch obligation --help`, `backstitch obligation
   reference --format json`, and `backstitch guide evidence-assembly`
   explain the obligation lifecycle, proposal shape, evidence vocabulary,
   result guidance, skip semantics, and trust boundary. MCP exposes the exact
   installed guide and schemas as `backstitch://guides/evidence-assembly`,
   `backstitch://reference/obligations`, and
   `backstitch://schemas/evidence-proposal` resources.
2. **Orientation:** `backstitch obligation list` or
   `backstitch obligation ID`, and MCP `list_obligations` or
   `get_obligation`, return compact status, counts, freshness, and the
   required next action. They do not return all snippets.
3. **Detail:** obligation evidence, counterevidence, candidate discovery, and
   candidate detail are explicit, named, paginated views requested only when
   needed.

The default obligation view is the compact orientation read. There is no
public `orient` verb. The public interface says what the repository is trying
to check before exposing how the broker represents candidate evidence.

The repository skill `skills/evidence-assembly/SKILL.md` is an optional
workflow accelerator, not required training. It is a thin wrapper around the
installed guide; duplicated normative guidance is forbidden. Updating the
guide changes its content digest, which enters the frozen case and any
agent-assembly evaluation identity as historical provenance. A guide-only
change does not make an existing case stale; a broker schema, universe rule,
or normalization change does.

### 8.2 Stateless Address And Identity [EVC-8.2]

There is no `init` command, hidden draft session, MCP session handle, or
multi-step context setup. Every read carries or derives an inspectable full
address:

- one canonical repository identity and exact repository snapshot
- one canonical `obligation_id`
- the named operation and any operation-specific selector
- an optional self-contained, snapshot-bound page cursor

`repository_id` is a required, non-secret, portable configuration string for
every repository-bound evidence operation and read. Packaged reference, guide,
and schema-resource operations perform no repository discovery and carry no
repository identity. For this repository the configured identity is
`github.com/VanL/backstitch`. It is identical across clones and enters
candidate IDs, cases, and hashes. The resolved absolute root is local transport
metadata only; it is echoed for inspection but excluded from canonical
payloads, committed artifacts, and hashes.

The repository snapshot is not Git `HEAD`. The broker first captures one
immutable byte image of every broker-visible spec, source, test, mapping,
invariant, and configuration input. Inventory is sorted by canonical relative
path; symlinks and escapes are rejected. Each capture attempt records file
metadata before and after each read, then repeats inventory and metadata
inspection. A changed inventory or file discards the whole attempt. Exhausting
`snapshot_capture_attempts` is exit `2`; data from attempts are never mixed.
Resolver, parser, universe, span, and receipt construction consume only that
byte image and may not reopen live repository files.

Every semantic or configuration source file in that image is read through a
bounded stream. If one file exceeds `maximum_file_bytes`, reading stops at
`limit + 1` and returns `BUDGET_EXHAUSTED` with budget `file_bytes`; no partial
image survives. `maximum_snapshot_bytes` counts the sum of exact raw bytes for
all semantic and configuration input files in sorted inventory order. If the
next complete file would exceed it, capture returns budget `snapshot_bytes`
with observed equal to the prior sum plus that file's exact byte length and
discards the attempt. File-count exhaustion likewise observes `limit + 1`.
Before repository configuration is known, the code-owned bootstrap loader
allows at most 64 configuration files, 1,000,000 raw bytes per file, and
5,000,000 raw bytes across the resolved extend chain. It uses bounded reads
before TOML parsing; overflow is traceback-free invalid configuration and exit
`2`. These constants are part of `broker_schema_version`, not repository
overrides. The later immutable capture must contain those exact same config
bytes and applies the configured file/snapshot ceilings too.

The snapshot is the versioned SHA-256 of the semantic image's canonical
path/raw-digest manifest plus a canonical effective projection of repository
ID, effective profile classification, resolved roots/exclusions, candidate and
snapshot ceilings, static depth, and broker/universe/report-issue/
normalization algorithm versions. Configuration source
bytes are captured and parsed from the same image but their raw digest is not
hashed as a semantic file merely because they contain operational keys.
Contained absolute root configuration is normalized to the canonical
repository-relative path before entering this projection; the clone-specific
absolute prefix never enters a snapshot or committed object.
Case root, required-obligation policy, page sizes, response/request/proposal/
proposal-text/case byte ceilings, call time, and capture retry count are
operational or policy fields and are excluded. The
snapshot binds dirty and
untracked inputs inside the declared boundary. Immediately before switching
the active-case manifest, activation captures a second image; a different snapshot
writes no active state and returns `SNAPSHOT_CONFLICT`. A later edit may make a
newly frozen case immediately stale, but cannot make the frozen object's own
fields internally inconsistent.

The snapshot preimage is exactly:

```text
{
  identity: "evidence-repository-snapshot",
  version: 1,
  repository_id,
  files: [{path, raw_sha256}],
  semantic_config: {
    profile_name,
    spec_roots, plan_roots, code_roots, test_roots, exclusions,
    planned_spec_globs, exploratory_spec_globs,
    maximum_candidate_items, maximum_catalog_items, maximum_snapshot_files,
    maximum_file_bytes, maximum_snapshot_bytes,
    static_neighbor_depth
  },
  algorithms: {
    broker_schema_version, snapshot_algorithm_version,
    universe_algorithm_version, report_issue_projection_version,
    normalization_version
  }
}
```

File rows sort by path and contain every semantic file in the captured image,
not operational config source files; `raw_sha256` hashes the exact complete
captured file bytes. Each root/exclusion/glob array is unique and sorts by
Unicode code point after contained absolute roots become canonical
repository-relative POSIX paths. `profile_name` and every named algorithm
version are nonblank. Every named config/algorithm field is required. No other
effective config, file metadata, Git identity, timestamp, or local path enters
this preimage. The rendered snapshot is
`sha256:<64 lowercase hex>` of its [SEM-3] canonical JSON.

CLI working-directory or `--repo-root` context is allowed only when the
portable identity, local root metadata, and snapshot are echoed in the response. The
MCP server is started for one explicit repository root; every tool response
echoes that root's identity and current snapshot. Neither adapter may accept a
per-call absolute path outside the resolved root.

Section obligations use the existing canonical packet identity
`<spec_path>#<section_id>`. Invariant obligations use
`invariant::<invariant_id>`. User input may use an unambiguous shorthand such
as `INV.RES.1`; the broker normalizes it once, returns
`IDENTIFIER_NORMALIZED` guidance, and emits only the canonical identity in
trusted artifacts. Ambiguous input is a true conflict and is rejected with
the candidate identities and an action for choosing one.

The obligation inventory is exactly the complete ordered union of the
section targets eligible for the sole semantic packet producer under [SEM-3]
and the invariant targets eligible under [INV-5]. Backstitch does not invent a
second eligibility filter for the CLI. `backstitch obligation list` includes
evaluated, uncovered, stale, and skipped members in canonical obligation-ID
order; filtering a member out because it lacks evidence or carries a skip
would make the inventory dishonest.

Every universe member has one stable broker-minted `candidate_id`; every exact
observation has one content-addressed `receipt_hash`, as defined in [EVC-4].
The agent selects a candidate ID and supplies a proof-obligation binding and
reason. It never supplies a trusted locator, digest, receipt, structural
relation, validation state, or universe-membership claim that Backstitch can
derive. For a candidate the broker did not discover, the agent may propose a
contained repository-relative path and optional symbol to the resolution
operation; Backstitch derives everything else.

### 8.3 Obligation-Centered Interface [EVC-8.3]

The CLI read surface is one resource-first family:

```text
backstitch obligation list
backstitch obligation ID
backstitch obligation ID --evidence
backstitch obligation ID --counterevidence
backstitch obligation ID --find-evidence
backstitch obligation ID --candidate CANDIDATE
backstitch obligation ID --candidate CANDIDATE --neighbors
backstitch obligation ID resolve --path RELPATH
```

The default `backstitch obligation ID` view is a compact summary. Exactly one
of `--evidence`, `--counterevidence`, `--find-evidence`, or
`--candidate` may select a detail view. `--kind
implementation|test|counterevidence` is valid only with `--find-evidence`;
omitting it returns the three kinds in that order. `--neighbors` is valid
only with `--candidate` and changes candidate detail from source text to
static neighbors. These constraints prevent accidental context expansion
while keeping the common reads on one obligation-shaped surface.

The MCP tool surface is:

```text
list_obligations
get_obligation
find_obligation_evidence
get_obligation_candidate
resolve_obligation_candidate
validate_obligation_proposal
```

`get_obligation` has the closed view vocabulary `summary`, `evidence`,
and `counterevidence`. `find_obligation_evidence` has the closed evidence
kind vocabulary `all`, `implementation`, `test`, and
`counterevidence`. `get_obligation_candidate` explicitly selects source
or neighbors. These are obligation-specific reads, not a generic query
language. A generic `query` tool whose meaning depends on a separate
operation-name lookup table is not conforming. The library may use one internal
dispatcher, but that storage-oriented shape must not leak through either
agent-facing adapter.

All reads and proposal validation are deterministic and repository-read-only.
They serve obligation status, active resolved evidence, recorded
counterevidence and omissions, exact candidate spans, definitions, static
callers/callees, mappings, invariants, universe pages, and content-addressed
receipts. Response ordering and pagination are stable for one repository
snapshot. The broker enforces configured request, byte, candidate, and
wall-time limits per call. Activation reconstructs the canonical
`accounted_candidate_count` and overlap-deduplicated
`accounted_raw_bytes` totals for every universe candidate selected,
considered, or omitted in the proposal. It does not claim to know session-wide
exploration cost.

`--find-evidence` and `find_obligation_evidence` invoke deterministic broker
discovery only. They never call a model or agent. The installed guide and
read-only MCP tools let an external authorized agent use those reads to build
a proposal; no CLI spelling silently crosses from deterministic discovery into
stochastic judgment.

The exact CLI address shapes are below. `COMMON` means the optional
`[--format json|text]`; it defaults to `json`. `REPOSITORY` means the
optional `[--repo-root PATH]`. Options after a subcommand may appear in any
order, at most once; no unlisted option is accepted.

```text
backstitch obligation reference COMMON
backstitch guide evidence-assembly COMMON
backstitch obligation list [--cursor TOKEN] [--limit N] REPOSITORY COMMON
backstitch obligation ID REPOSITORY COMMON
backstitch obligation ID --evidence [--cursor TOKEN] [--limit N] REPOSITORY COMMON
backstitch obligation ID --counterevidence [--cursor TOKEN] [--limit N] REPOSITORY COMMON
backstitch obligation ID --find-evidence [--kind implementation|test|counterevidence] [--cursor TOKEN] [--limit N] REPOSITORY COMMON
backstitch obligation ID --candidate CANDIDATE [--cursor TOKEN] REPOSITORY COMMON
backstitch obligation ID --candidate CANDIDATE --neighbors [--cursor TOKEN] [--limit N] REPOSITORY COMMON
backstitch obligation ID resolve --path RELPATH [--symbol SYMBOL] REPOSITORY COMMON
backstitch obligation ID validate --proposal PATH REPOSITORY COMMON
backstitch obligation ID activate --proposal PATH REPOSITORY COMMON
backstitch obligation ID check REPOSITORY COMMON
backstitch obligation check --all REPOSITORY COMMON
backstitch obligation ID deactivate --expected-manifest HASH REPOSITORY COMMON
backstitch obligation ID skip --reason TEXT REPOSITORY COMMON
backstitch obligation ID unskip REPOSITORY COMMON
```

At the first token after `obligation`, only `reference`, `list`, and `check
--all` are aggregate addresses; every other value is parsed as the obligation
ID or shorthand. After an ID, `resolve`, `validate`, `activate`, `check`,
`deactivate`, `skip`, and `unskip` are the closed action literals. An ambiguous
shorthand is rejected with the canonical choices. This fixed ID position lets
an agent extend `backstitch obligation ID` from summary to detail or mutation
without reconstructing another argument order.

`--limit` may reduce a page but may not exceed the configured page ceiling.
Candidate source pages split only on UTF-8 line boundaries with self-contained
cursors and no partial line; a single line larger than
`maximum_response_bytes` fails with `BUDGET_EXHAUSTED` whose action is to
raise the reviewed byte limit or select a narrower structural candidate. It
never returns a silently truncated line. Proposal paths resolve under the
repository root; activation output resolves under the configured case root.
There is no flag that disables containment, snapshot checking, source-edit
compare-and-swap, or budget enforcement.

### 8.3.1 Closed Operation Contracts [EVC-8.3.1]

The core payload for each named operation is closed. JSON object key order is
irrelevant because [SEM-3] canonical JSON sorts keys. Every array uses the
order stated here; unknown fields, duplicate identities, invalid order, or a
value outside its declared type is `INVALID_INPUT`. A nullable field is always
present with JSON null when absent.

The reference, installed guide, and MCP resources return this exact artifact
payload:

```text
{artifact_id, artifact_version, media_type, sha256, text}
```

`artifact_id` is respectively `obligation-reference`, `evidence-assembly-guide`,
or `evidence-proposal-schema`; `artifact_version` is a positive integer;
`media_type` is respectively `application/json`, `text/markdown`, or
`application/schema+json`; `sha256` is `sha256:<64 lowercase hex>` over the
exact UTF-8 `text` bytes. The
CLI guide and the matching MCP resource return byte-identical `text` and
metadata. The proposal schema text is the canonical JSON Schema document for
the exact [EVC-8.4] input object. CLI `--help` remains ordinary deterministic
terminal help, not a core-result payload.

These shared records are exact:

```text
obligation_summary = {
  obligation_id, target_kind, path, start_line, evaluation_disposition,
  skip_reason, skip_path, skip_line,
  active_case_id, active_case_hash, case_evidence_hash, case_verifiable
}
candidate = {
  candidate_id, candidate_kind, path, symbol, structural_locator,
  receipt_hash, proof_obligation_ids, relation_kinds
}
obligation_evidence_item =
  {
    item_type: "candidate", proof_obligation_id, evidence_kind,
    decision, reason, candidate, span_start_line, span_end_line, text
  }
  | {
    item_type: "open_question", proof_obligation_id, question, reason
  }
budget = {
  items_returned, payload_bytes, response_bytes,
  maximum_items, maximum_response_bytes
}
case_diagnostic = {
  code, short_code, obligation_id, case_id, case_hash,
  proof_obligation_id, candidate_id, path, message,
  default_severity, severity, winning_policy_rule
}
```

`skip_reason`, `skip_path`, `skip_line`, the three active-case identity
fields, `symbol`, diagnostic `case_id`, `case_hash`,
`proof_obligation_id`, `candidate_id`, `path`, and
`winning_policy_rule` are nullable strings, integers, or the exact nullable
[SEM-6] rule record as appropriate; all other scalar strings are nonblank.
`evaluation_disposition` is `evaluate` or `skip`. Skip fields are all null
for `evaluate` and are respectively a nonblank reason, canonical
repository-relative spec path, and positive directive line for `skip`.
`case_verifiable` is always false while skipped. `target_kind` is
`section` or `invariant`.
`candidate_kind` uses [EVC-7]. Candidate proof-obligation IDs sort by Unicode
code point; relation kinds use [EVC-4.1] order. Candidate rows sort by
`candidate_id`. Obligation summaries sort by `obligation_id`. Candidate
evidence items sort by `(proof_obligation_id, evidence_kind, candidate_id,
decision, reason)`; open-question items follow candidate items and sort by
`(proof_obligation_id, question, reason)`. `evidence_kind` is
`implementation`, `test`, or `counterevidence`; `decision` is
`selected`, `considered`, or `omitted`. Evidence-view items admit only
selected implementation/test candidates. Counterevidence-view items admit
considered/omitted candidates and open questions. Diagnostic rows use [SC-15]
registry order, then obligation,
proof-obligation, candidate, and path. Counts are nonnegative integers.
`maximum_items` is non-null only for candidate and neighbor item-page
operations, obligation-list pages, and evidence/counterevidence pages and is
their effective limit after applying a smaller requested limit. It is null
for candidate-source and non-page operations. `payload_bytes` is
the UTF-8 length of canonical JSON for the complete payload or problem object.
The common core result, not an individual payload, carries this budget record
as specified in [EVC-8.5].

The exact operation payloads are:

```text
obligation.reference | guide.evidence-assembly | MCP resource read:
  artifact

obligation.list:
  {
    counts: {total, evaluate, skipped, with_active_case, verifiable},
    items: [obligation_summary],
    next_cursor
  }

obligation.get:
  {
    obligation: obligation_summary,
    active_manifest_hash, repository_snapshot,
    candidate_counts: {
      implementation, test, static_reference,
      unresolved_reference, report_issue
    },
    unresolved_count, case_verifiable,
    analyze_request_bytes, verify_request_upper_bound_bytes
  }

obligation.evidence | obligation.counterevidence:
  {
    obligation_id, evaluation_disposition, evidence_mode,
    items: [obligation_evidence_item], next_cursor
  }

obligation.find-evidence:
  {
    obligation_id, evidence_kind,
    items: [{evidence_kind, candidate}], next_cursor
  }

obligation.candidate-source:
  {
    obligation_id, candidate_id, receipt_hash, path, structural_locator,
    span_start_line, span_end_line, chunk_start_line, chunk_end_line,
    text, next_cursor
  }

obligation.candidate-neighbors:
  {
    obligation_id, candidate_id,
    items: [{relation_kind, direction, candidate}],
    next_cursor
  }

obligation.resolve-candidate:
  {obligation_id, candidate, expanded_universe_count}

obligation.validate:
  {
    obligation_id, valid, proposal_sha256, case_id, case_evidence_hash,
    repository_snapshot, active_manifest_hash, universe_count,
    analyze_request_bytes, verify_request_upper_bound_bytes,
    case_object_bytes, active_manifest_bytes, discrepancies
  }

obligation.activate:
  {
    changed, obligation_id, case_id, case_hash, case_evidence_hash,
    active_manifest_hash, repository_snapshot, object_path
  }

obligation.check:
  {
    obligation: obligation_summary,
    valid, case_verifiable, diagnostics
  }

obligation.check-all:
  {
    active_manifest_hash,
    obligation_count, evaluated_count, skipped_count,
    case_count, valid, case_verifiable_count,
    obligations: [obligation_summary],
    diagnostics
  }

obligation.deactivate:
  {changed, obligation_id, previous_case_hash, active_manifest_hash}

obligation.skip | obligation.unskip:
  {
    changed, obligation_id, evaluation_disposition, reason,
    path, line, previous_repository_snapshot, repository_snapshot
  }
```

Each page cursor is nullable. List counts describe the complete obligation
inventory, not only the returned page; `total = evaluate + skipped`,
`with_active_case` counts retained active-manifest entries in either
disposition, and `verifiable` counts only evaluated obligations satisfying
the complete [EVC-9] predicate. `evidence_mode` is `case`, `trace`, or
`none`: current active-case evidence uses `case`; an evaluated obligation
without an active case uses the existing deterministic trace projection; a
skipped obligation uses `none` and returns no evidence items. Trace
counterevidence is empty because it contains no reviewed universe decisions.

Find-evidence rows sort by evidence-kind order `implementation`, `test`,
`counterevidence`, then candidate ID. The same candidate may occur in more
than one kind because the row records a possible proof role, not another
candidate identity. Neighbor `direction` is `incoming` or `outgoing` and
rows sort by `(relation_kind, direction, candidate.candidate_id)`. A
candidate source covers inclusive positive line ranges and chunks sort in
source order. Summary `unresolved_count` is the number of this target's
derived proof obligations whose active-case status is `unresolved`; when no
active case exists and disposition is `evaluate`, every derived proof
obligation counts as unresolved. It is zero while skipped and never counts
`unresolved_reference` candidates. Resolution `expanded_universe_count` is
the total unique mandatory-universe member count after the resolved candidate
is added as a closure seed and closure reaches its fixed point, not merely the
number of members newly added by that seed.
`valid`, `case_verifiable`, and `changed` are booleans. `previous_case_hash`
is nullable. Mutation `reason`, `path`, and `line` are nonblank/canonical/
positive for every skip result and for a changed unskip; they are nullable for
an idempotent unskip. A changed unskip returns the removed reason and its
former location. Validation
`case_evidence_hash`, the two request-size fields,
`case_object_bytes`, and `active_manifest_bytes` are nullable until their
respective trusted projections are complete. `object_path` is a canonical
repository-relative POSIX path, never an absolute clone path. Discrepancies
sort by code, proof obligation, candidate, and message.

Proposal `valid` is true exactly when no discrepancy is blocking and the proposal
can activate against the echoed snapshot and manifest without changing input.
The proposal's self-contained `obligation_id` must equal the command/tool
address after normalization. This deliberate duplicate address keeps the
portable proposal self-identifying outside one invocation; a mismatch is a
true conflict, never silently derived in either direction. A malformed
proposal is a problem, not `valid = false`.

`obligation.check.valid` is true for an evaluated obligation exactly when
deterministic [EVC-9] validation produces none of BSE001 through BSE004,
BSE008, or BSE009; structural corruption is a problem rather than a payload.
Its `case_verifiable` additionally requires the checked hash to be active and
every [EVC-9] readiness predicate. A skipped obligation validates only its
directive and any retained manifest/object structural integrity; it does not
run currency, universe, relation, coverage, packet, analyze, or verify checks,
and its `case_verifiable` remains false. `obligation.check-all.valid` is true
exactly when every evaluated obligation check is valid, every retained skipped
object is structurally valid, and no BSE007 is present for an evaluated
required obligation. `case_verifiable_count` counts only evaluated
obligations satisfying the full predicate. A valid proposal with an open
question activates as visible coverage debt and is not case-verifiable.
Applied diagnostic policy affects exit `0` or `1`, never either boolean.

A discrepancy contains exactly `code`, boolean `blocking`, nullable
`proof_obligation_id`, nullable `candidate_id`, `message`, and `action`. Its code is one of
`SNAPSHOT_STALE`, `MANIFEST_STALE`, `CANDIDATE_MISSING`,
`UNIVERSE_UNACCOUNTED`, `ROLE_MISMATCH`, `PROOF_OBLIGATION_UNRESOLVED`,
`RELATION_UNAVAILABLE`, `ANALYZE_PROMPT_OVERSIZED`, or
`VERIFY_PROMPT_OVERSIZED`, or `CASE_ARTIFACT_OVERSIZED`. Every code is blocking except one conditional
branch: `PROOF_OBLIGATION_UNRESOLVED` is nonblocking only when the exact
proposal contains at least one open-question row naming that proof obligation.
That branch records deliberate visible debt. The same code is blocking when a
proof obligation lacks selected support and has no named open question; an
omitted or considered candidate does not silently acknowledge missing support.
Discrepancies describe a well-formed proposal's readiness.
Malformed, unsafe, or unknown input is a problem and never a discrepancy.

`analyze_request_bytes` is the exact analyzer prompt plus canonical packet
request length from [SEM-3], computed from the reconstructed current v3 model
projection. When analyze `maximum_prompt_bytes` is greater than zero, a value
over it adds blocking `ANALYZE_PROMPT_OVERSIZED`; zero retains [SEM-9]'s exact
disabled-maximum meaning. The verify request upper bound is the exact byte
count from [EVC-3.1]
using the reconstructed case projection, the longest allowed BSA code and
classification strings, and one canonical claim evidence row for every
available trusted packet region. Claim evidence is an ordered unique subset of
those regions, so no real request can exceed this bound. The summary view reports
analyze bytes for a reconstructable active packet and null otherwise; its
verify bound is null unless that active case is verifier-complete. Proposal
validation reports analyze bytes after universe/decision reconstruction, even
for a nonblocking open question, and reports the verify bound only when every
proof obligation is verifier-complete. A bound over
`verify.maximum_prompt_bytes` is `VERIFY_PROMPT_OVERSIZED` and prevents
activation. The exact per-claim check still runs before each cache lookup.
`case_object_bytes` is the byte length of [EVC-4.1]'s exact indented UTF-8 case
file including its terminal LF. `active_manifest_bytes` measures the same exact
stored representation for the manifest that a successful activation would switch.
A value over `maximum_case_bytes` for either adds blocking
`CASE_ARTIFACT_OVERSIZED`; validation and activation create no staging file.

The MCP input objects are also closed:

```text
list_obligations:
  {cursor, limit}
get_obligation:
  {obligation_id, view, cursor, limit}
find_obligation_evidence:
  {obligation_id, evidence_kind, cursor, limit}
get_obligation_candidate:
  {obligation_id, candidate_id, detail, cursor, limit}
resolve_obligation_candidate:
  {obligation_id, path, symbol}
validate_obligation_proposal:
  {obligation_id, proposal}
```

Here `cursor`, `limit`, and `symbol` are always present and nullable; a
non-null limit is a positive integer excluding booleans. `view` is
`summary`, `evidence`, or `counterevidence`. Summary requires null cursor
and limit. `evidence_kind` is `all`, `implementation`, `test`, or
`counterevidence`. `detail` is `source` or `neighbors`; source requires a
null limit. `proposal` is the direct closed [EVC-8.4] object, not a path.
The server's repository root is bound at startup and is not a tool input. The
CLI proposal path is an adapter input; the core operation receives the parsed
closed proposal. MCP exposes no activation, skip/unskip, deactivation, or
check operation in v1.

On a first item page, the effective page size is the smaller of a non-null
requested limit and the configured page size, or the configured page size when
limit is null. An item cursor carries that effective size. On continuation, a non-null limit
must equal the cursor `page_size`; null means use the cursor value. A mismatch
is `INVALID_INPUT`, never a resized continuation.

A cursor is self-contained and is one of two exact preimages:

```text
item page:
{
  version: 1,
  cursor_kind: "items",
  operation,
  repository_snapshot,
  obligation_id,
  selector_sha256,
  next_item_index,
  page_size
}

source span:
{
  version: 1,
  cursor_kind: "source_lines",
  operation: "obligation.candidate-source",
  repository_snapshot,
  obligation_id,
  selector_sha256,
  candidate_id,
  receipt_hash,
  next_line
}
```

`selector_sha256` is `sha256:<64 lowercase hex>` of canonical JSON for the
operation's semantic selector fields: `{}` for the obligation list,
`{view}` for evidence/counterevidence, `{evidence_kind}` for discovery, and
`{candidate_id, detail}` for candidate source or neighbors. Obligation and
operation are separate cursor fields; `obligation_id` is null only for the
repository-wide obligation list. Cursor and page controls, including nullable
`limit`, are excluded; item `page_size` already binds the effective limit.
The
token is unpadded base64url of the preimage's canonical UTF-8 bytes, one ASCII
period, then lowercase SHA-256 hex of those same bytes. This digest is a
corruption checksum, not an authority boundary. On every page read Backstitch
decodes with strict base64url, rejects duplicate JSON keys and unknown fields,
checks the digest, exact operation/snapshot/obligation/selector match,
nonnegative integer item index and positive page size no greater than the
current item ceiling, or a positive next line inside the bound inclusive span.
The line cursor's candidate and receipt must equal the selected current
observation; `next_line` is the first not-yet-returned complete source line.
Item cursors apply only to obligation-list, evidence/counterevidence,
find-evidence, and candidate-neighbor pages; line cursors apply only to
candidate-source spans. A malformed, altered, stale, cross-variant,
cross-operation, or selector-mismatched cursor is `INVALID_INPUT` and exit `2`; it never
restarts at page one. A changed response-byte ceiling may change the number of
later lines per span chunk but cannot skip or repeat a line.

The closed problem-code vocabulary is `INVALID_INPUT`, `UNSAFE_PATH`,
`SNAPSHOT_UNSTABLE`, `SNAPSHOT_CONFLICT`, `MANIFEST_CONFLICT`, `NOT_FOUND`, `AMBIGUOUS`,
`BUDGET_EXHAUSTED`, `DEPENDENCY_MISSING`, `HANDSHAKE_FAILED`,
`ARTIFACT_CORRUPT`, `LOCK_TIMEOUT`, `PUBLICATION_FAILED`, and
`INTERNAL_ERROR`. Its `details` object is the one exact variant selected by
the code:

```text
INVALID_INPUT:       {field, reason}
UNSAFE_PATH:         {path, reason}
SNAPSHOT_UNSTABLE:   {attempts}
SNAPSHOT_CONFLICT:   {expected_snapshot, current_snapshot, changed_candidate_ids}
MANIFEST_CONFLICT:   {expected_manifest_hash, current_manifest_hash}
NOT_FOUND:           {entity, identity}
AMBIGUOUS:           {field, value, candidates}
BUDGET_EXHAUSTED:    {budget, limit, observed}
DEPENDENCY_MISSING:  {distribution, extra}
HANDSHAKE_FAILED:    {protocol, reason}
ARTIFACT_CORRUPT:    {path, reason}
LOCK_TIMEOUT:        {lock_path, timeout_seconds}
PUBLICATION_FAILED:  {path, operation, reason}
INTERNAL_ERROR:      {operation}
```

`AMBIGUOUS.candidates` is a nonempty array of strings in Unicode code-point
order; `SNAPSHOT_CONFLICT.changed_candidate_ids` is a unique candidate-ID-order
array. `NOT_FOUND.entity` is `obligation`, `candidate`, `case`, `artifact`,
`path`, or `symbol`. `BUDGET_EXHAUSTED.budget` is `candidate_items`,
`catalog_items`, `snapshot_files`, `file_bytes`, `snapshot_bytes`,
`request_bytes`, `proposal_bytes`, `proposal_text_bytes`, `case_bytes`,
`response_bytes`, `wall_time`, or `verify_prompt_bytes`.
Candidate identity arrays use candidate-ID order. Budget observations are
integers, except wall-time observations and limits are finite nonnegative
decimal numbers. `SNAPSHOT_UNSTABLE.attempts` is the exact configured positive
capture-attempt count exhausted without one coherent image; this problem needs
no expected or current snapshot because neither was established.
`timeout_seconds` is finite and positive. Publication
operation is `mkdir`, `create_stage`, `write`, `chmod`, `fsync`, `link`,
`replace`, or `unlink`; internal operation is one of the closed core operation
strings.
These details do
not expose tracebacks, local secrets, provider responses, or bytes outside the
repository. Every problem has the line-safe message, action, and repair
guidance required by [EVC-8.5].

The initial non-secret configuration contract is:

```toml
[tool.backstitch.evidence]
repository_id = "github.com/VanL/backstitch"
case_root = "docs/evidence-cases"
required_obligations = []
page_size = 25
maximum_page_size = 100
maximum_response_bytes = 65536
maximum_candidate_items = 1000
maximum_catalog_items = 100000
maximum_snapshot_files = 20000
maximum_file_bytes = 5000000
maximum_snapshot_bytes = 100000000
maximum_request_bytes = 1100000
maximum_proposal_bytes = 1000000
maximum_proposal_text_bytes = 4096
maximum_case_bytes = 10000000
maximum_call_seconds = 10.0
snapshot_capture_attempts = 3
static_neighbor_depth = 1
```

`repository_id` and every required obligation are nonblank and canonical;
repository ID is UTF-8 NFC, at most 255 code points, with no leading/trailing
whitespace, control character, or backslash. It is case-sensitive. Duplicates
are errors. `case_root` is a nonblank canonical repository-relative POSIX
directory string with no empty, dot, dot-dot, backslash, control-character, or
absolute component. Its existing components and every later filesystem object
must remain contained regular directories without symlinks; activation creates
missing final directories one component at a time only after rechecking the
contained parent. The entire configured case root is an exact built-in
exclusion from the semantic snapshot, parser, candidate catalog, and universe;
active case loading is the sole trusted read path for those artifacts. It may
therefore be nested under a broad source, spec, or test root. A file at the
path, an escape, a symlink, or a case root equal to or containing any configured
source/spec/test root is invalid configuration because it would exclude real
semantic inputs. All integer limits except `static_neighbor_depth` are
positive; `maximum_response_bytes` is at least 16384;
`maximum_call_seconds` is finite and greater than zero; `page_size`
cannot exceed `maximum_page_size`; and `static_neighbor_depth` is in `[0, 3]`.
`maximum_snapshot_bytes` is at least `maximum_file_bytes`;
`maximum_request_bytes` is at least `maximum_proposal_bytes`;
`maximum_case_bytes` is at least `maximum_proposal_bytes`; and
`maximum_proposal_bytes` is at least `maximum_proposal_text_bytes`.
Catalog, candidate-universe, or snapshot exhaustion is
exit `2`, never silent truncation and never a smaller claimed universe.
Changing either item ceiling, `static_neighbor_depth`, candidate eligibility,
profile classification, roots, exclusions, or a reconstruction algorithm
invalidates the universe identity. Presentation page sizes do not.

### 8.3.2 Obligation Skip Annotation [EVC-8.3.2]

An obligation may carry one exact section-scoped disposition:

```markdown
## 4. Trace Graph [SC-4] <!-- backstitch: skip-obligation [SC-4] "Generated code is checked downstream." -->
```

The bracketed value is the exact local section or invariant ID. The quoted
value is one JSON string. After strict JSON decoding it must be nonblank, at
most 4096 UTF-8 bytes, and contain no CR, LF, U+2028, or U+2029. The canonical
writer first computes `token = json.dumps(reason, ensure_ascii=True)`, then
replaces every raw `--` in `token` with `\u002d\u002d`, raw `<` with
`\u003c`, and raw `>` with `\u003e`, in that order. These are JSON escapes,
so strict decoding recovers the exact reason while no raw HTML open, close, or
double-hyphen delimiter can occur inside the token. It uses that token and the
owner ID in the exact inline HTML comment above at the parser-derived heading
content insertion offset defined in [EVC-8.6]. The same HTML comment as a
standalone directive-block line and the equivalent italic directive-block form
are accepted:

```markdown
<!-- backstitch: skip-obligation [SC-4] "Generated code is checked downstream." -->
_Traceability: skip-obligation [SC-4] "Generated code is checked downstream."_
```

All forms use [EXC-4]'s parser-owned Markdown boundary. The marker must occur
on one section heading or in its directive block before body text. Its target
must be that section's own ID or one invariant ID declared in that same
Markdown section; an invariant target may be resolved after the complete
section is parsed. This explicit target lets several obligations in one
section carry independent reasons without making the marker part of an
invariant statement. The marker is invalid in a file preamble, inside other
prose or a code block, on a non-obligation section, for an ID owned elsewhere,
or more than once for one obligation. All accepted positions and spellings are
aliases, not independent dispositions. Malformed/duplicate syntax is
`SUPPRESSION_INVALID_SYNTAX`; a missing or blank reason is
`SUPPRESSION_REASON_MISSING`; an otherwise valid marker with no obligation
owner is `SUPPRESSION_UNUSED`. No invalid form changes evaluation.

The inline form is valid only at [EVC-8.6]'s parser-derived insertion offset
with exactly one preceding ASCII space and the exact comment delimiters. An
inline lookalike elsewhere in heading content is invalid syntax, not prose and
not a best-effort suppression. Inline and standalone HTML forms require the
JSON token itself to contain no raw `--`, `<`, or `>`; manually authored
reasons use the canonical escapes when needed. The italic form is parsed from
the exact physical directive line and admits the ordinary strict JSON token.
All forms compare the decoded reason, not its spelling. This makes canonical
unskip's byte range unambiguous even for manually authored markers.

The parsed disposition is exactly `evaluate` when no marker exists and
`skip` when one valid marker exists. A skip:

- leaves the obligation in the inventory and every total denominator;
- creates `OBLIGATION_SKIPPED`/BSE010 at the obligation and suppresses that
  audit record with the exact decoded reason through the ordinary [EXC-7]
  `--show-suppressions` path;
- prevents case-currency, universe, relation, coverage, packet, analyze, and
  verify work for that obligation;
- suppresses no parser, identity, duplicate-ID, malformed-directive,
  containment, manifest-corruption, or immutable-object-corruption failure;
- leaves any active-manifest entry and immutable case untouched as retained
  audit history; and
- never counts as covered, verifiable, analyzed, or verified.

BSE010 has packaged level `info` and follows ordinary effective-level
suppression policy. If repository policy makes its effective level
non-suppressible, [EXC-6.2]'s unsuppressible-suppression behavior applies and
BSE010 remains unsuppressed and auditable; its effective level, the resulting
suppression-hygiene diagnostic, and `fail_on` determine the exit. A repository
that intends to prohibit skips uses an exact BSE010 error rule and includes
`error` in `fail_on`. This reuses the existing policy path rather than adding a
second skip-authorization configuration.

Every accepted skip marker is parser metadata and is excluded from target
requirement text, candidate text, the report-issue projection, and model input.
The canonical inline marker is also excluded from the target normalized/raw
receipt without changing physical line coordinates. Its source file bytes
still change the repository snapshot, so adding or removing only the canonical
inline marker invalidates cursors but does not by itself stale a retained case.
A standalone directive alias contributes no semantic text, but its physical
line exists in parser-owned locators; manually adding it, or removing it with
`unskip`, can change target or later invariant coordinates and therefore can
make a retained case stale after evaluation resumes. Backstitch reports that
refresh action rather than pretending line-number churn is coordinate-stable.

`backstitch obligation ID skip --reason TEXT` inserts or updates this exact
marker. `backstitch obligation ID unskip` removes either accepted form. These
are the only Backstitch operations allowed to edit a spec. They never edit the
obligation statement, IDs, mappings, invariants, evidence proposal, source,
tests, configuration, or policy.

The editable v1 set is exactly section obligations and invariants declared in
a Markdown spec. A code-only invariant has no spec-owned annotation point;
`skip` returns `INVALID_INPUT` for field `obligation_id` with an action to move
the declaration to an ID-bearing Markdown spec section if the owner intends it
to be skippable. Backstitch never inserts a suppression into a Python docstring
or guesses a related section from backlinks. `unskip` remains an idempotent
no-op when the addressed obligation has no marker.

### 8.4 Agent Proposal [EVC-8.4]

The agent emits one atomic, agent-shaped proposal rather than editing the
case storage schema. The proposal contains exactly:

```json
{
  "obligation_id": "invariant::INV.RES.1",
  "repository_snapshot": "sha256:<digest>",
  "active_manifest_hash": "sha256:<digest>",
  "expanded_candidates": [
    {"candidate_id": "candidate:sha256:<digest>", "reason": "<nonblank>"}
  ],
  "implementation_evidence": [
    {
      "proof_obligation_id": "invariant::INV.RES.1::implementation",
      "candidate_id": "candidate:sha256:<digest>",
      "reason": "<nonblank>"
    }
  ],
  "test_evidence": [
    {
      "proof_obligation_id": "invariant::INV.RES.1::binding-test",
      "candidate_id": "candidate:sha256:<digest>",
      "reason": "<nonblank>"
    }
  ],
  "counterevidence_considered": [
    {
      "proof_obligation_id": "invariant::INV.RES.1::counterevidence",
      "candidate_id": "candidate:sha256:<digest>",
      "reason": "<nonblank>"
    }
  ],
  "omissions": [
    {
      "proof_obligation_id": "invariant::INV.RES.1::counterevidence",
      "candidate_id": "candidate:sha256:<digest>",
      "reason": "<nonblank>"
    }
  ],
  "open_questions": [
    {
      "proof_obligation_id": "invariant::INV.RES.1::implementation",
      "question": "<nonblank>",
      "reason": "<nonblank>"
    }
  ]
}
```

Every `reason` and `question` is measured as its exact UTF-8 bytes after JSON
decoding and must be nonblank and at most `maximum_proposal_text_bytes`.
After closed-shape validation, safe identifier normalization, and the canonical
array ordering in [EVC-4.1], the complete proposal's [SEM-3] canonical JSON
must be at most `maximum_proposal_bytes`. Either overflow is
`BUDGET_EXHAUSTED` (`proposal_text_bytes` with observed string length, or
`proposal_bytes` with observed canonical length) before universe
reconstruction, hashing, or filesystem work.

The CLI reads a proposal file through a `maximum_request_bytes + 1` bounded
reader and rejects raw input over `maximum_request_bytes` before JSON parsing.
The MCP stdio adapter enforces the same limit on each complete JSON-RPC message
before SDK parsing; if the approved SDK cannot expose a bounded message-reader
seam, the MCP dependency gate fails and that adapter is not implemented.
Adapter overflow is `BUDGET_EXHAUSTED` with budget `request_bytes` and observed
`limit + 1`; CLI uses the addressed `obligation.validate` or
`obligation.activate` core problem envelope,
while a pre-parse MCP overflow has no knowable core operation and uses SDK
JSON-RPC error `-32600` with no `data`, then closes the local stdio connection.
No partial request is processed.

Backstitch derives mandatory-universe membership, paths, locators, exact and
normalized digests, structural relations, budget totals, and receipts. A
proposal cannot override a derived value. `semantic_support` and
`counterevidence` relations are untrusted proposal relations created only from
the agent's explicit proof-obligation binding and reason. Evidence selected
under the wrong role remains in the validation receipt under the submitted
proof obligation and receives `EVIDENCE_ROLE_MISMATCH`; it is not silently
reclassified and cannot satisfy coverage until corrected.

The allowed binding matrix is closed:

| Candidate kind | Allowed proof-obligation suffixes |
|---|---|
| `implementation` | `::implementation`, `::counterevidence` |
| `test` | section `::test`, invariant `::binding-test`, `::counterevidence` |
| `static_reference` | `::counterevidence` |
| `unresolved_reference` | `::counterevidence` |
| `report_issue` | `::counterevidence` |

Root role and target kind select the exact row. No other binding is valid.

`expanded_candidates` may contain only candidate IDs that the global captured
candidate catalog can resolve exactly for the addressed snapshot. Validation
reconstructs each coordinate, makes it a closure seed, and returns every newly
mandatory member.
The proposal is incomplete until that fixed-point universe is fully accounted
for.

`validate_obligation_proposal` and `backstitch obligation ID validate` are
deterministic, read-only operations. They return a compact validation receipt,
the current repository snapshot, discrepancies, and actionable guidance.
They do not activate, approve, publish, skip, or mutate the repository.

### 8.5 Guidance And Result Economy [EVC-8.5]

Every success, finding, conflict, and tool failure carries a nonempty
`guidance` array. Each guidance entry contains exactly `code`, `message`, and
`action`; `action` is mandatory and tells the caller what to do next. The
initial closed guidance-code vocabulary is:

| Code | Required action class |
|---|---|
| `IDENTIFIER_NORMALIZED` | Reuse the returned canonical identity |
| `CANDIDATE_RESOLVED` | Use the broker-minted candidate ID in the proposal or discard it |
| `PAGE_CONTINUE` | Request the named next page with its continuation token |
| `READ_COMPLETE` | Use the returned canonical evidence or request another named read |
| `EVIDENCE_INCOMPLETE` | Request or account for the named missing evidence |
| `EVIDENCE_ROLE_MISMATCH` | Bind the candidate to an allowed proof obligation or replace it |
| `PROPOSAL_VALID` | Review the compact validation receipt before activation |
| `SNAPSHOT_CONFLICT` | Re-read the obligation, inspect the diff, revalidate, and retry |
| `CASE_ACTIVATED` | Review the rendered case and active-manifest diff, then run obligation check |
| `CASE_DEACTIVATED` | Review the active-manifest diff and run repository case validation |
| `OBLIGATION_SKIP_RECORDED` | Review the spec diff and use unskip when evaluation should resume |
| `OBLIGATION_SKIP_REMOVED` | Review the spec diff and check or rebuild the obligation evidence |
| `REQUEST_REJECTED` | Correct the named invalid, ambiguous, unsafe, or unavailable input and retry |
| `BUDGET_EXHAUSTED` | Narrow the read or change the reviewed configured budget before retrying |

The transport-neutral success result contains exactly `schema_version`,
`operation`, `repository`, `payload`, `guidance`, and `budget`; a problem result
contains the same fields except that `problem` replaces `payload`.
`schema_version` is exactly `1`. The closed operation strings are
`obligation.reference`, `guide.evidence-assembly`,
`resource.obligation-reference`, `resource.evidence-assembly-guide`,
`resource.evidence-proposal-schema`, `mcp.startup`, `obligation.list`,
`obligation.get`, `obligation.evidence`,
`obligation.counterevidence`, `obligation.find-evidence`,
`obligation.candidate-source`, `obligation.candidate-neighbors`,
`obligation.resolve-candidate`, `obligation.validate`,
`obligation.activate`, `obligation.check`, `obligation.check-all`,
`obligation.deactivate`, `obligation.skip`, and `obligation.unskip`.
`mcp.startup` is problem-only;
every other operation has the success payload defined above. CLI and MCP
adapters use the same semantic operation string for the same core evidence
call.

The CLI uses `mcp.startup` for a missing-extra startup failure before stdio
framing. Successful MCP initialization uses the SDK's protocol-owned standard
InitializeResult unchanged and is outside core-result parity. A protocol or
handshake failure uses the SDK/JSON-RPC error shape; its optional structured
`data` is the exact `mcp.startup` core problem result with no traceback. MCP
tool/resource results after initialization use the exact SDK mappings below.

`repository` contains exactly `repository_id` and `snapshot` on repository-
bound success. It is null on successful `obligation.reference`,
`guide.evidence-assembly`, and static MCP resource reads because those
packaged artifacts perform no repository discovery. Those operations and
pre-config `mcp.startup` problems use the packaged
`maximum_response_bytes`; every other operation uses resolved repository
config. On a pre-resolution failure `repository` is null; after partial
resolution it contains those same two nullable fields, using only values
already established safely. A
problem has exactly `code`, `message`, `action`, and `details`. Guidance and
budget remain present on problems. Guidance entries are unique by code and
sort in the vocabulary-table order above. Normalization guidance therefore
cannot depend on parser encounter order.

`budget.response_bytes` is the unique nonnegative integer `n` equal to the
UTF-8 length of [SEM-3] canonical JSON for the complete core result when that
field contains `n`. Backstitch computes it by starting with zero and replacing
the field with the newly measured length until it is unchanged.
`payload_bytes` measures canonical JSON for only `payload` or `problem`.
`items_returned` is the length of a top-level `items` array when present, else
the length of `obligations`, `diagnostics`, or `discrepancies` in that priority, else
one for a success and zero for a problem. `maximum_items` is the effective page
limit for obligation lists, evidence/counterevidence, discovery, and neighbor
item pages and is null for source spans and non-paged calls. Every core result
must have `response_bytes <=
maximum_response_bytes`; the CLI envelope, its terminal newline, text
projection, and MCP `_meta` are transport bytes and are excluded.

Paged operations choose the largest ordered prefix that satisfies both item
and complete-core-response limits after adding the exact continuation cursor
and guidance. If even one item cannot fit, they return `BUDGET_EXHAUSTED` with
no partial page. A non-paged success that cannot fit does the same. If another
problem would exceed the ceiling, it is replaced by the compact
`BUDGET_EXHAUSTED` response whose `observed` is that problem's fixed-point byte
count. Configuration requires `maximum_response_bytes >= 16384`, which is
large enough for the fixed problem envelope after line-safe bounded fields;
agent-supplied operation, obligation, path, symbol, and cursor strings are
each limited to 4096 UTF-8 bytes before interpretation. Thus the ceiling
applies to the actual transport-neutral result, including locators, cursors,
guidance, and budget metadata, not just snippets.

Obligation and guide commands accept `--format json|text`, default `json`, as
enumerated in [EVC-8.3]. The CLI JSON transport envelope contains exactly
`local_root` and `result`; `result` is the core result and `local_root` is the
resolved absolute root string for a repository-bound call or null for a
packaged reference/guide call. Exit-0/1 writes one canonical line to stdout
with empty stderr; exit-2 writes that one problem envelope to stderr with empty
stdout. For text format, repository-bound exit 0/1 writes the deterministic
human projection to stdout beginning with `Repository root: <local_root>` and
leaves stderr empty. Packaged `obligation reference` and `guide
evidence-assembly` text success writes exactly the artifact payload's `text`
bytes to stdout and empty stderr; each packaged text artifact is UTF-8 and
ends in exactly one LF. Text exit 2 writes exactly one line to stderr,
`backstitch: error: <message>; action: <action>`, and leaves stdout empty.

For a tool call, the MCP SDK `CallToolResult` contains exactly
`content`, `structuredContent`, `isError`, and `_meta`. `content` is a
one-element array containing exactly `{type: "text", text}`; `text` is the
[SEM-3] canonical JSON bytes of the complete core result decoded as UTF-8,
with no trailing LF. `structuredContent` is that same core result as an object.
`isError` is false for a core success and true for a core problem. `_meta`
contains exactly `local_root`, using the resolved absolute root string. The
canonical bytes in `content[0].text`, parsed and reserialized canonically,
must equal `structuredContent` and the adapter-independent core result byte for
byte.

For a successful static resource read, the SDK `ReadResourceResult` contains
exactly `contents` and `_meta`. `contents` has one `TextResourceContents` row
containing exactly `uri`, `mimeType`, and `text`; `uri` is the requested exact
`backstitch://guides/evidence-assembly`,
`backstitch://reference/obligations`, or
`backstitch://schemas/evidence-proposal` URI; `mimeType` is
`application/json`; and `text` is the canonical UTF-8 JSON of the matching
complete `resource.*` core success with no trailing LF. `_meta` is the empty
object because resource reads perform no repository discovery. Resource
results have no `isError` field. An unknown resource URI is JSON-RPC invalid
params `-32602` with the SDK's ordinary line-safe message and no `data`; it has
no core operation. A known resource whose packaged artifact cannot be
validated is JSON-RPC internal error `-32603` whose `data` is the exact
matching `resource.*` `ARTIFACT_CORRUPT` core problem result, with no traceback. Other
protocol errors remain SDK-owned and do not masquerade as core operation
results. Removing these exact SDK envelopes yields the same canonical core
result bytes as the CLI adapter.

`guidance[].message`, `guidance[].action`, `problem.message`, and
`problem.action` are nonblank and contain no CR, LF, U+2028, or U+2029. Any
other string interpolated into text output follows the same rule. When
untrusted parser, filesystem, provider, or path text contributes to one of
those fields, each line separator is rendered as a literal six-character
`\u000a`-style escape using lowercase hexadecimal before the core result is
built; existing spaces are not collapsed. This same normalized field supplies
JSON, text, and MCP, so hostile text cannot create a second stderr line or a
transport-dependent message.

Mutation responses are context-small: activation returns the case ID, case
hash, active-manifest hash, repository snapshot, written object path, and
guidance, never the full case. Skip/unskip return the disposition, reason
location, old/new freshness tokens, and guidance, never the obligation body.
The default obligation view is the explicit read for state; detail reads are
explicit.
Adding or removing a guidance code is an enumerable contract change and must
update its firing tests.

Agent-facing draft input canonicalizes safe near-misses and reports every
normalization in-band. Unknown but safe free-form material may be preserved
only inside the existing reason or open-question fields. Unknown executable
fields, relation types, or trusted case fields are unsafe because they would
change canonical meaning; they are rejected with repair guidance as specified
in [EVC-4].

### 8.6 Activation, Skip, Conflict Recovery, And Trust [EVC-8.6]

Activation is an explicit CLI/library operation, not an MCP tool. It validates
the proposal against the addressed snapshot, freezes the immutable case by
recomputing the mandatory universe and all derived fields, and publishes
through this exact layout:

```text
<case_root>/objects/<bare-case-hash-hex>.json
<case_root>/objects/.backstitch-evidence-object-<bare-case-hash-hex>-<owner-token>.tmp
<case_root>/active.json
<case_root>/.backstitch-evidence-active.lock
<case_root>/.backstitch-evidence-active.next
```

The object file is one authoritative deterministic, indented JSON envelope;
its exact excerpts, relations, reasons, and proof-obligation bindings are the
human review projection. There is no second trusted Markdown sidecar. The
closed active manifest contains exactly `schema_version = 1`, `object_type =
"evidence-case-active-manifest"`, `repository_id`, `active_cases`, and
`manifest_hash`. `active_cases` is a JSON object whose canonical obligation-ID
keys map to case-hash strings. Duplicate keys are rejected and canonical JSON
sorts the keys. `manifest_hash` is `sha256:<64 lowercase hex>` of the [SEM-3]
canonical JSON object containing exactly the first four fields, excluding only
`manifest_hash`.
Before the first activation, an absent `active.json` is treated as the canonical
empty manifest for the configured repository ID and its derived manifest hash.
Duplicate JSON keys are rejected at parse time.

The manifest uses the same exact indented on-disk serialization and terminal
newline as [EVC-4.1]. Existing-object and idempotence comparisons use these
authoritative bytes after independently validating their semantic hashes.

The repository-root `.gitignore` must contain the exact patterns
`**/.backstitch-evidence-active.lock` and
`**/.backstitch-evidence-active.next`, and
`**/objects/.backstitch-evidence-object-*.tmp`, plus the exact source-edit
patterns `/.backstitch-obligation-edit.lock` and
`**/.backstitch-obligation-edit-*.tmp`, before the matching mutation is
allowed. Those
reserved names cover every contained configured `case_root`; a missing rule is
exit `2` with an action to add it. `active.json` and final object JSON files
must not be ignored by a matching repository rule. Backstitch validates these
facts but never edits ignore files itself.

Activate and deactivate acquire the same process-scoped single-writer lock before
reading the active manifest and hold it through file/directory fsync and final
manifest replace. Process death releases the operating system lock; failure to
acquire it within `maximum_call_seconds` is exit `2`. The lock and staging
paths are never symlinks and enter no committed identity.

Under that lock, activation first removes stale regular, non-symlink object staging
files matching the reserved pattern. Any non-regular or symlink match is
`ARTIFACT_CORRUPT` and is not removed. It then creates one staging file in the
same `objects/` directory using `O_CREAT|O_EXCL|O_NOFOLLOW`, mode `0600`, the
case hash, and a fresh 32-byte lowercase-hex owner token. It writes the exact
[EVC-4.1] bytes, fsyncs the file, closes it, reopens without following symlinks,
and revalidates its bytes and case hash. It publishes no-replace by creating a
hard link from that staging inode to the final hash path. If the final path
already exists, the existing-object rule below applies. On a new link it fsyncs
the `objects/` directory, unlinks the staging name, and fsyncs the directory
again. It never opens the final path for write. Death before the link leaves
only one ignored staging file; death after the link leaves a complete,
already-fsynced immutable object. The next writer performs the bounded cleanup.

Activation then rechecks repository snapshot and expected active-manifest hash.
It writes the exact manifest bytes to the single
`.backstitch-evidence-active.next` path with exclusive, no-follow creation,
mode `0600`, file fsync, and byte/hash revalidation; atomically replaces
`active.json`; and fsyncs the case-root directory. A stale regular staging file
is removed before exclusive creation; a symlink or non-regular path is
corruption. Readers use only hashes referenced by a valid active manifest. An
object published before a failed manifest switch is inert history, not
partially active state. It may remain for audit.

If the content-addressed object path already exists, activation requires a regular,
non-symlink file, validates its canonical bytes and path/hash identity, and
continues only when those bytes equal the object it would publish. Different
bytes at the same hash path are corruption and exit `2`; activation never replaces
or repairs the object in place. After an identical-object validation it unlinks
its private staging name and fsyncs `objects/` before continuing.

If the repository snapshot changed, activation writes nothing to active state and
returns `SNAPSHOT_CONFLICT` with the current snapshot and
the complete recovery sequence: re-read the obligation, inspect changed candidates,
revalidate, retry. If only the active manifest changed, `MANIFEST_CONFLICT`
returns its current hash and requires another obligation read. A caller may not force or bypass
either compare-and-swap check.

Activation activates or replaces exactly one obligation entry.
`backstitch obligation ID check` validates the addressed active obligation;
`backstitch obligation check --all` validates the inventory, active manifest,
and every retained object. `deactivate` is the only case-removal operation:
it atomically removes one active entry after manifest compare-and-swap and
retains the immutable object. Duplicate inactive hashes are harmless;
duplicate obligation identities, missing referenced objects, path/hash
mismatches, or malformed manifests are exit `2`. A required obligation with no
active case is the [EVC-9] missing-case diagnostic unless it carries a valid
skip disposition, so deleting or deactivating an evaluated gate cannot
silently weaken CI.

Activation is idempotent when the addressed snapshot, expected manifest hash,
obligation entry, and immutable object already match: it returns exit `0`,
`changed = false`, and `CASE_ACTIVATED` without rewriting the object or manifest.
Deactivate is idempotent only for a non-required obligation when the addressed
manifest already lacks the entry: it returns exit `0`, `changed = false`, and
`CASE_DEACTIVATED` without a write. Deactivating an absent required obligation
still reports `CASE_REQUIRED_MISSING` through policy; idempotence cannot weaken
the required-case contract.

`skip` and `unskip` use a separate repository-root
`.backstitch-obligation-edit.lock`. They capture the immutable repository
image, resolve exactly one obligation and marker byte range through the
Markdown parser, acquire the process-scoped lock, and re-read the target spec
without following symlinks. The current exact file hash must equal the captured
hash before any staging write; otherwise they return `SNAPSHOT_CONFLICT`.
The lock is held through final file and directory fsync. Timeout is
`LOCK_TIMEOUT`, and process death releases the operating-system lock.

The canonical skip writer changes only the marker bytes:

- insertion adds one ASCII space and the canonical HTML comment, including the
  exact local target ID, at a parser-derived offset in the owning heading's
  content line. For an ATX heading the offset is before the whitespace that
  introduces an optional CommonMark closing-hash sequence, or otherwise before
  trailing spaces/tabs and LF, CRLF, or end of file. For a setext heading it is
  before trailing spaces/tabs on the final content line above the underline,
  never on the underline. The Markdown parser, not a second regular expression,
  supplies the heading form, content line, and optional closing-hash boundary.
  Existing heading content, suffix bytes, underline, and terminator state are
  unchanged; multiple canonical skip comments append at that same semantic
  content boundary in invocation order;
- a changed reason replaces only the accepted marker bytes and preserves its
  inline or directive-block spelling and the line's terminator state;
- unskip removes the canonical inline marker and its one writer-owned leading
  ASCII space, restoring the exact heading bytes, or removes only an accepted
  directive-block marker line and its
  following terminator; and
- every other source byte, including surrounding blank lines, remains
  byte-identical.

The operation creates one sibling
`.backstitch-obligation-edit-<owner-token>.tmp` with
`O_CREAT|O_EXCL|O_NOFOLLOW`, mode `0600`, then applies the original regular
file's permission bits. It writes the complete edited bytes, fsyncs, closes,
reopens without following symlinks, and revalidates the expected bytes. While
still holding the lock it revalidates the original path/hash once more,
atomically replaces that one spec file, and fsyncs its parent directory.
Symlink/non-regular targets or staging paths are `ARTIFACT_CORRUPT`; a write,
mode, fsync, or replace failure is `PUBLICATION_FAILED`. Death before replace
leaves only one ignored staging file; the next skip/unskip removes stale
regular matching staging files and refuses symlink/non-regular matches. No
failure leaves a partial spec file.

Skipping with the same canonical reason and unskipping an evaluated obligation
are idempotent `changed = false` operations with no source write. Updating a
reason is `changed = true`. Skip/unskip never changes the active manifest.
Before writing, Backstitch derives the exact post-edit repository snapshot by
substituting the staged spec bytes into the captured immutable image. The
successful response returns that token after the target-file compare-and-swap;
it performs no fallible post-commit recapture. A concurrent change to another
file may make the returned token immediately stale, as any edit after a read
may, but cannot be overwritten by this one-file mutation. All old cursors are
stale after a changed edit. An idempotent mutation returns the unchanged
snapshot and does not itself stale a cursor. Activation of a skipped obligation is
`INVALID_INPUT` with an action to unskip first; validation remains available
so evidence can be prepared while an obligation is skipped.

MCP v1 is local stdio only, started as `backstitch mcp --stdio --repo-root
<path>`. It has no network listener, no provider/model calls, no repository
writes, and no activate, skip/unskip, deactivate, or approval tool. The CLI is
the canonical CI,
validation, and artifact-publication surface. CLI and MCP responses for the
same library read must contain byte-identical canonical payloads after the
transport envelope is removed.

A case created by activation is still a proposal until a human reviews its
rendered diff and it lands through the repository's ordinary change-control
workflow. A skip/unskip edit likewise has no review authority beyond its
visible repository diff and ordinary landing. No
agent-supplied `reviewed_by`, approval flag, or similar field can cross this
trust boundary.

### 8.7 Exit Semantics [EVC-8.7]

Obligation commands preserve [SEM-7]'s exit classes:

- exit `0`: the requested read, proposal validation, activation,
  skip/unskip, deactivation, or check completed and applied policy allows it
- exit `1`: the operation completed and found a target condition whose
  effective diagnostic level is in `fail_on`
- exit `2`: malformed or ambiguous input, unsafe unknown fields, snapshot
  conflict, path escape, pagination mismatch, budget exhaustion, publication
  failure, MCP dependency/handshake failure, or internal/tool failure

No failure path emits a traceback. MCP maps the same problem records into its
structured error envelope without changing their code, message, action, or
trusted payload.

For a well-formed proposal, `obligation validate` exits `0` even when
`valid = false`; discrepancies and guidance are its requested read result.
`activate` accepts only `valid = true` and disposition `evaluate`.
Snapshot and manifest staleness use their specific conflict problems; another
well-formed but non-activatable proposal is
`INVALID_INPUT` exit `2` with an action to run validation and resolve every
discrepancy. Activation never publishes a partial case. Reads and resolution
exit `0` on success. Checks, activation, deactivation, and skip may exit `1`
only through applied BSE policy after completing the requested check or
mutation. A policy-forbidden skip therefore leaves the visible annotation in
the spec and returns the BSE010 finding; it never pretends the source write
rolled back. Unskip does not run semantic analysis, but its guidance requires
an obligation check before relying on the resumed gate.
Structural corruption, conflict, unsafe input, or incomplete tool work is
always exit `2`, regardless of policy.

## 9. CI Validation Of Frozen Cases [EVC-9]

CI never re-runs stochastic or agent-guided discovery for a frozen case. It
does deterministically reconstruct trusted fields and the mandatory universe.
Every active-manifest and immutable-case read is limited to
`maximum_case_bytes + 1` before JSON parsing. Oversize input is
`BUDGET_EXHAUSTED` with budget `case_bytes`, observed `limit + 1`, and exit
`2`; it is never partially parsed. Activation applies the same ceiling to both
proposed stored files before creating staging.
Validation is, in order:

1. **Obligation inventory and disposition.** Resolve every section/invariant
   obligation and its [EVC-8.3.2] disposition before selecting cases. Invalid
   skip syntax is suppression hygiene and never changes disposition. A valid
   skip creates BSE010 and runs it through ordinary suppression policy with the
   exact reason. For a skipped obligation, validate any retained manifest and
   immutable object through steps 2 and 3 for structural integrity, then stop
   before currency, universe, relation, coverage, packet, analyze, or verify
   work. It has no `CASE_REQUIRED_MISSING` diagnostic.
2. **Active manifest check.** The manifest schema, repository ID, hash,
   obligation ordering, referenced object paths, and object availability are
   exact. Structural corruption or ambiguity is exit `2`.
3. **Schema and identity check.** The case uses a supported closed schema;
   its canonical identities, trusted digests, receipt references, and
   `case_hash` recompute exactly. The stored guide record is validated for
   closed shape and digest format as historical provenance but is not compared
   with current installed guide bytes; a guide-only edit does not stale the
   case. Agent-shaped fields cannot occupy trusted fields.
4. **Target requirement check.** The current target section or invariant is
   resolved by canonical obligation ID and its normalized digest is compared
   with the frozen target receipt. A missing or changed target fires
   `CASE_REQUIREMENT_STALE` and invalidates every derived proof obligation.
   Raw-only target churn preserves case currency but changes packet identity.
5. **Span check.** Every cited span's normalized digest is recomputed from
   the current repository. Mismatches mark the citing obligations stale. A
   raw-byte-only change preserves case currency but is reported as provenance
   churn because it changes any newly generated model-visible packet.
6. **Universe contract check.** A snapshot, broker, or universe-construction
   algorithm version, eligibility, root, exclusion, or identity-affecting parameter change fires
   `CASE_UNIVERSE_CONFIG_CHANGED`; a case cannot silently adopt it. Under the
   same contract, the mandatory universe is recomputed and diffed ([EVC-7]).
   New stable candidate IDs fire `CASE_UNIVERSE_EXPANDED`; raw receipt churn
   does not.
7. **Relation check.** `declared_mapping`, `declared_backlink`,
   `invariant_binding`, and `static_reference` relations are re-derived from
   repository structure. `semantic_support` and `counterevidence` remain
   explicitly untrusted, proof-obligation-bound proposal relations. Missing or
   changed trusted structural relations fire `CASE_RELATION_STALE`. A static
   reference is never upgraded to runtime reach or assertion coverage.
8. **Coverage check.** Every implementation obligation is bound to allowed
   current evidence or has a structured unresolved request. A section test
   obligation is `complete` with selected allowed test evidence or
   `unresolved`. An invariant binding-test obligation may additionally be
   `complete_absent` only when the complete universe has zero eligible test
   candidates. Counterevidence is
   complete only when every universe member is selected, considered, or omitted
   with a nonblank reason. Gaps or an unresolved request fire
   `CASE_COVERAGE_INCOMPLETE`; applied diagnostic policy decides whether that
   debt fails the target. A blank reason is malformed case input and exit `2`,
   not a repository finding.
9. **Packet selection.** The sole producer emits schema-v3 packets for every
   evaluated eligible section and invariant. A skipped obligation emits no
   semantic packet and can reach no analyze or verify path. An active case
   produces `evidence_mode =
   "case"`, binding its case hash and current selected implementation/test
   bytes. A target without an active case produces `evidence_mode = "trace"`
   from the existing deterministic mappings, backlinks, and binds and cannot
   reach `independently_verified`. If its obligation is listed in
   `required_obligations`, it also fires `CASE_REQUIRED_MISSING`. A valid
   skip is the explicit exception and remains visible as BSE010 in the
   suppression audit. A stale case
   remains case-mode and visible but cannot reach `independently_verified`
   until refreshed. The producer never silently falls back from an active
   malformed case to trace mode.
10. **Verdict reuse.** Analyze results reuse the current packet identity;
   case-mode verify events reuse exact `claim_hash`, `case_evidence_hash`,
   `verifier_case_hash`, epoch, and verify inference identity. Trace mode has
   no verify event. A reason, guide-provenance, or other audit-only change that
   changes `case_hash` but preserves `case_evidence_hash` reuses the verify
   event. Under `cache_mode = "require"`, a miss caused by
   raw-byte churn or any other identity change is incomplete analysis, even
   when normalized case validity remains current.
11. **Policy.** Findings project through [SEM-6]/[EVC-6] to the applied
   policy and `fail_on`.

`case_verifiable` is policy-independent and true only when the obligation is
evaluated, the case is active,
its target/span/universe/relation/config checks are current, its universe and
structural relations are complete, every member is accounted for, every proof
obligation is `complete` or validly `complete_absent` with no open request,
and every omitted universe span can be included in the closed verifier
projection. Thus
none of BSE001 through BSE004, BSE007 through BSE009, malformed input, or an
unresolved request may be present. Applied policy may let such debt exit `0`
for report-only adoption, but it cannot make the case verifiable or allow a
verify call.

### 9.1 Semantic Packet Schema V3 [EVC-9.1]

The v3 artifact row is closed and contains exactly:

```text
schema_version = 3
packet_id
packet_hash
kind                         # section | invariant
evidence_mode                # trace | case
case_id                      # null in trace mode
case_hash                    # null in trace mode
case_evidence_hash           # null in trace mode
content_hash                 # null for section; required for invariant
subject
requirement
implementation_evidence
test_evidence
counterevidence
evidence_decisions
open_questions
issues
packet_warnings
```

`subject` is a closed variant. Section subject contains exactly `spec_path`,
`section_id`, and `title`. Invariant subject contains exactly `invariant_id`,
`tier`, and the existing closed declaration record. `requirement` contains
exactly `path`, `start_line`, `end_line`, `excerpt`, `raw_sha256`,
`normalized_sha256`, and `receipt_hash`.

Every item in the three evidence arrays contains exactly `candidate_id`,
`candidate_kind`, `path`, nullable `symbol`, `start_line`, `end_line`,
`snippet`, `raw_sha256`, `normalized_sha256`, and `receipt_hash`.
`snippet` is nonblank except that an empty-module candidate has the exact
virtual span `1..1` and empty snippet defined by [EVC-7.1]. No other blank
snippet or virtual range is valid.
`evidence_decisions` contains exactly `proof_obligation_id`, `candidate_id`,
`decision` (`selected`, `considered`, or `omitted`), and nonblank `reason`.
`open_questions` contains exactly `proof_obligation_id`, nonblank `question`,
and nonblank `reason`. `issues` retains the exact v2 closed issue record.
Unknown fields, duplicate candidate/decision identities, role mismatch, or
non-canonical order are invalid packet input.

The three evidence arrays sort by `(candidate_id, path, start_line, end_line,
receipt_hash)`. `evidence_decisions` sorts by `(proof_obligation_id,
candidate_id, decision, reason)`. `open_questions` sorts by
`(proof_obligation_id, question, reason)`. Issues retain [SEM-3]'s canonical
issue order. Packet warnings are unique and sort by Unicode code point. Null
symbols compare as the empty string wherever a nested tie-break needs them.

The model-visible projection contains exactly `packet_contract_version = 3`,
`packet_id`, `kind`, `evidence_mode`, nullable `case_id`, nullable
`case_evidence_hash`, nullable `content_hash`, `subject`, text-free
`requirement`, `evidence_sources`, reason-free `evidence_states`, reason-free
`proof_obligation_status`, `issues`, and `packet_warnings`. It excludes the
artifact evidence arrays, `case_hash`, every decision reason, every open
question string/reason, and all guide/proposal provenance. Model-visible
`requirement` contains exactly artifact requirement `path`, `start_line`,
`end_line`, `raw_sha256`, `normalized_sha256`, and `receipt_hash`.
`evidence_states`
contains exactly `proof_obligation_id`, `candidate_id`, and `decision` in the
same order as artifact `evidence_decisions`; `proof_obligation_status` contains
exactly `proof_obligation_id` and `status` (`complete`, `complete_absent`, or
`unresolved`) in ID order.

An `evidence_sources` row contains exactly `role`, `path`, `start_line`,
`end_line`, `shown_text`, ordered `candidates`, and ordered `receipt_hashes`.
A candidate subrow contains exactly `candidate_id` and `candidate_kind`.
Backstitch seeds one interval from the requirement and each artifact evidence
item, grouped by `(role, path)`. It sorts by `(start_line, end_line,
candidate_id-or-empty, receipt_hash)` and merges intervals whose inclusive
line ranges overlap; adjacent non-overlapping intervals remain separate. A
merged row spans the minimum start through maximum end and reads `shown_text`
once from those exact current inclusive source lines. Its candidates and
receipt hashes are the unique unions in candidate-ID and hash order. The
requirement seed has no candidate and one target receipt. Rows sort by role,
path, start, and end using role order `requirement`, `implementation`, `test`,
`counterevidence`. This produces one maximal region for any model evidence
coordinate, and each source line appears at most once per role. Trusted [SEM-5]
normalization therefore matches model `{role, path, start_line, end_line}` to
exactly one row and reconstructs the excerpt from `shown_text`.
The one exception to physical-line slicing is [EVC-7.1]'s empty-module
candidate: its row retains virtual coordinate `1..1`, has empty `shown_text`,
and carries its candidate and receipt identity. It does not assert that a
physical line exists. This exact row is a valid trusted model citation with an
empty excerpt and SHA-256 of empty UTF-8 bytes. No other empty `shown_text` row
is valid.

`packet_hash` is SHA-256 of the canonical model-visible projection. Current raw
bytes supply every `shown_text`; candidate-specific artifact snippets never
enter the request a second time.

Case mode includes every selected implementation/test item as its support role.
Every other universe member, whether considered or omitted and regardless of
its original candidate kind, appears in `counterevidence` as its full current
receipt span with original `candidate_kind`; a selected support candidate is
already visible and is not duplicated. Thus no accounted evidence-bearing
candidate is hidden from analyze, even when an agent labels it an omission.
Case mode never truncates or drops evidence: an unreadable span, or a packet
over a positive configured `maximum_prompt_bytes`, is exit `2` with an action
to narrow the universe or raise the reviewed ceiling. A zero ceiling retains
[SEM-9]'s disabled-maximum meaning. Proposal reasons and open-question
prose remain only in the review artifact and never enter analyzer or verifier
request bytes. Reason-only edits preserve `case_evidence_hash`, packet hash,
and both model requests while changing the audit `case_hash`.

Trace mode derives implementation and test evidence from the same ordered
mapping/backlink/bind edges used by v2. It admits at most eight implementation
spans and eight test spans, each at most 120 lines, ordered by path, symbol,
and start line. Module evidence uses the first 120 lines. It leaves
`counterevidence`, `evidence_decisions`, and `open_questions` empty and adds a
packet warning when an eligible span is omitted by these bounds. Unlike v2,
section test edges resolve and include current test snippets. Trace-mode
warnings preserve [SEM-2]/[SEM-7] packet-completeness handling and trace mode
is never independently verified.

Packet v2 remains a read-only legacy artifact during the migration window. No
v2 producer remains after v3 activation, and no analysis result bound to a v2
packet hash can satisfy a v3 cache key. The canonical analyze result row stays
at schema version 2 and the cache object stays at version 1 because their
closed shapes do not change; their existing packet hash and inference identity
bind the v3 projection. Unsupported legacy packet input receives an explicit
migration action.

Staleness and insufficiency are **diagnostics, not new exit codes**. The
[SEM-7] exit contract is unchanged: exit `2` remains tool/invocation/
completeness failure; exit `1` remains an effective target finding; exit
`0` otherwise. A strict repository makes staleness an effective `error`
(exit `1`); a tolerant one reports it. The diagnostics:

| Code | Short | Packaged level | Meaning |
|---|---|---|---|
| `CASE_EVIDENCE_STALE` | `BSE001` | warning | A cited span's normalized digest no longer matches |
| `CASE_UNIVERSE_EXPANDED` | `BSE002` | warning | Recomputed universe contains unconsidered members |
| `CASE_COVERAGE_INCOMPLETE` | `BSE003` | warning | A proof obligation or universe member is not accounted for |
| `CASE_RELATION_STALE` | `BSE004` | warning | A trusted structural relation no longer re-derives |
| `CASE_VERDICT_MISSING` | `BSE005` | info | No verify result exists for a claim configured to require one |
| `CASE_DISPUTED_BY_VERIFIER` | `BSE006` | info | Verify returned `unsupported` |
| `CASE_REQUIRED_MISSING` | `BSE007` | warning | A configured required obligation has no active case |
| `CASE_UNIVERSE_CONFIG_CHANGED` | `BSE008` | warning | Universe identity or construction parameters differ from the frozen case |
| `CASE_REQUIREMENT_STALE` | `BSE009` | warning | The target section or invariant no longer matches the frozen requirement receipt |
| `OBLIGATION_SKIPPED` | `BSE010` | info | The obligation carries an explicit reasoned skip disposition |

BSE010 is created before semantic packet selection and is the one audit
representative for a skip. Under packaged policy the skip directive suppresses
it into [EXC-7]'s `suppressed_issues` with the exact reason and scope. If
applied policy makes BSE010 non-suppressible, it remains visible under the
ordinary suppression-hygiene rules and may fail through `fail_on`; no other
BSE diagnostic is synthesized for work the skip deliberately did not run.

The refresh workflow is author-pays: the change that invalidates a case is
the change responsible for refreshing it, exactly as a change that breaks a
test fixes the test. Validation output must name the invalidated cases and
the specific stale obligations so a refresh is targeted, not a rediscovery.

## 10. Measurement [EVC-10]

Four quantities are targetable and must be measurable from committed
artifacts before any error promotion:

- **Candidate capture:** how often deterministic discovery includes the code
  and tests an adjudicator identifies as necessary. Report implementation,
  test, and counterevidence capture separately; a good verifier cannot repair
  evidence it never receives.
- **Evidence sufficiency:** how often a frozen case contains what an
  adjudicator needs, measured as the rate at which sufficiency review and CI
  verify complete without adjudicator-requested evidence additions.
- **Verdict quality conditional on sufficiency:** precision, recall,
  indeterminate rate, and uncached flip rate of verify verdicts on the
  [SEM-8] labelled corpus, reported per verify model, end to end through
  the assembled-case path.
- **Maintenance cost:** cases invalidated per changed line, refresh
  frequency, and refresh cost. A case invalidated by unrelated churn is
  over-cited; evidence minimality is a quality dimension and high
  invalidation rates are reported as case-quality debt, not hidden.

Agent interaction cost is reported with candidate capture and sufficiency:
named calls, pages, bytes returned, budget exhausted events, normalization
events, and adjudicator-requested evidence additions per completed obligation. The qualifying
corpus includes agents that start with only the reference surface and agents
that use the optional repository skill. This distinguishes interface quality
from hidden prompt or session knowledge.

Skip visibility is never denominator laundering. Every obligation-coverage
report carries `total_obligations`, `evaluated_obligations`,
`skipped_obligations`, and `covered_obligations`, plus both
`covered_obligations / total_obligations` and
`covered_obligations / evaluated_obligations` (null at a zero denominator).
Skipped obligations remain in the first denominator and never enter the
covered numerator. A qualification fixture or manifest unit carrying a skip
annotation is invalid corpus input; gate qualification must measure the
interface, not exempt its hard examples.

End-to-end seeded-violation recall is the qualifying metric: a seeded
misalignment must be captured by some case's obligations, survive assembly,
and be flagged through policy. Verifier-only metrics cannot qualify a gate.

### 10.1 Verify Evaluation And Promotion Artifact [EVC-10.1]

Verify evaluation has its own closed table; it does not inherit analysis-lane
thresholds:

```toml
[tool.backstitch.verify.eval]
mode = "report"                    # report | enforce
qualification_corpus = "tests/semantic_eval/v2/manifest.json"
qualification_corpus_sha256 = "sha256:<digest>"
qualification_report = "docs/evidence/verify-eval-report.json"
qualification_report_sha256 = "sha256:<digest>"
trials = 2
interval_method = "wilson"
confidence_level = 0.95
minimum_positive_units = 1
minimum_negative_units = 1
minimum_reference_only_positive_units = 1
minimum_reference_only_negative_units = 1
minimum_candidate_capture_rate = 0.0
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

Mode is `report` or `enforce`; `trials` is an integer excluding booleans and at
least one, interval method is exactly `wilson`, confidence is finite strictly
between zero and one, distinct-unit sample floors are integers excluding booleans and
nonnegative, every rate/threshold is finite in `[0, 1]`, and the final field is
boolean. Report mode permits blank corpus/report paths and hashes and cannot
authorize an error. Both paths resolve relative to the configuration file that
contributed them. Enforce mode requires a contained nonblank schema-v2 corpus
path and report path, each exact `sha256:<64 lowercase hex>` file digest,
positive sample floors, and a
validated qualifying artifact whose verify identity equals current effective
config. It also requires at least two trials, every minimum rate/precision/
recall threshold to be greater than zero, every maximum rate below one,
`maximum_false_positive_rate = 0`, and `require_all_critical = true`. Any
hard-fail prediction on a negative unit fails qualification regardless of a
rounded rate or interval. Unknown keys are errors.

The [SEM-8] corpus manifest moves to schema version 2 for a verify-qualifying
run. Each clean/mutated variant retains its v1 fields and adds exactly
`evidence_case_source`, `evidence_case_sha256`, `active_manifest_source`, and
`active_manifest_sha256`, plus `assembly_surface`, `assembly_transcript`, and
`assembly_transcript_sha256`. `assembly_surface` is exactly `reference_only`
or `repository_skill`. Source paths are contained under the corpus root,
manifest-relative, and outside every transformed variant working tree. Each
variant has its own frozen case object whose repository snapshot and case hash
must pass [EVC-9] against that exact post-transform clean or mutated fixture;
the active manifest's entry must reference that case. A case from the other variant is
stale and cannot substitute. Manifest v1 remains analysis-only input and can
never qualify verify or stochastic error authority.

Each case/variant run receives a fresh isolated transformed working tree, so
clean and mutated runs never share a live `active.json`. After applying that
variant's ordinary source transform, the runner reads each bounded source
artifact, validates its manifest-declared file digest, and validates the case
object's closed schema and hash sufficiently to derive its destination. It
then copies the exact case source bytes to the resolved production
`<case_root>/objects/<bare-case-hash>.json` and the exact manifest source bytes
to `<case_root>/active.json`. The source manifest must be the canonical
single-entry [EVC-8.6] manifest for that case's obligation/hash and repository
ID; its entry must reference the case that binds the post-transform snapshot.
Any other entry or destination is invalid. The
runner finally invokes the production case loader and full [EVC-9] validation
against those ordinary derived paths. Source artifacts are never treated as
alternate loader paths, and no test-only case injection seam exists. Thus one
base fixture may have distinct digest-bound clean and mutated source artifacts
without asking one live path to contain two byte strings.

An assembly transcript contains exactly `schema_version = 1`, `object_type =
"evidence-assembly-transcript"`, `assembly_surface`, `assembler_identity`,
`assembler_identity_sha256`, `assembler_base_identity_sha256`,
`repository_snapshot`, `obligation_id`, and ordered `events`. Its surface must equal the owning
variant manifest field; its snapshot and obligation must equal the installed
variant case. `reference_only` means the assembling agent was supplied the
installed reference/guide surface and no repository skill or preloaded copy of
its workflow; `repository_skill` means the agent was explicitly supplied the
repository skill. An event contains exactly consecutive zero-based `sequence`,
named `operation`, nonnegative `items_returned`, `bytes_returned`, ordered
`guidance_codes`, boolean `budget_exhausted`, nonnegative
`normalization_count`, and boolean `adjudicator_requested_addition`. It stores
no analyzer or verifier judgment. Surface, assembler, and adjudicator-addition
fields are human-reviewed qualification inputs in the same trust class as
manifest gold labels: they indirectly affect eval promotion, but have no
runtime case-validity, diagnostic, or policy authority. Enforce adoption
requires independent review and commit of the exact corpus/transcript/report
hashes; editing configured hashes is not a substitute for that review. The
validator proves shape, binding, digest, and derived calculations, not the
historical truth of a human-labelled provenance claim. Its manifest digest
binds the exact canonical JSON file bytes.

`assembler_identity` contains exactly:

```text
{
  contract_version: 1,
  agent_tool: {id, version},
  model: {backend_id, model_id, model_revision},
  request: {
    temperature, seed, maximum_output_tokens, reasoning_effort
  },
  harness: {id, version, sha256},
  teaching_artifacts: [{artifact_id, artifact_version, sha256}],
  skill_sha256
}
```

Identity strings are nonblank. Hashes are `sha256:<64 lowercase hex>`.
Request temperature is finite or null, seed is a nonnegative integer excluding
booleans or null, maximum output tokens is a positive integer excluding
booleans or null, and reasoning effort is a nonblank string or null. Null means
the named agent tool does not expose that control; it is not permission to
invent a default. Harness hashes bind the exact non-secret assembly instruction
bytes. Teaching rows use [EVC-8.3.1]'s artifact IDs, versions, and content
digests in fixed order `obligation-reference`, `evidence-assembly-guide`, then
`evidence-proposal-schema`. Reference and guide rows are required and equal the
exact artifacts supplied to the agent; the guide row also equals the case
guide record. The proposal-schema row is present if and only if that separate
artifact was supplied. `skill_sha256` is null for `reference_only` and is the exact
repository skill-file digest for `repository_skill`.
`assembler_identity_sha256` hashes the complete identity. The base identity
hashes the same object with only `skill_sha256` removed, so the same
tool/model/request/harness/teaching artifacts can be compared across surfaces without
pretending the skill was absent. These identities are historical measurement
provenance and grant no case or gate authority.

Transcript `operation` is one of `obligation.reference`,
`guide.evidence-assembly`, the three static `resource.*` operations,
`obligation.list`, `obligation.get`, `obligation.evidence`,
`obligation.counterevidence`, `obligation.find-evidence`,
`obligation.candidate-source`, `obligation.candidate-neighbors`,
`obligation.resolve-candidate`, or `obligation.validate`. Guidance codes
are unique, use [EVC-8.5]'s closed vocabulary/order, and must have been present
on that core result. `bytes_returned` equals its `budget.response_bytes`;
`items_returned` equals its `budget.items_returned`; `budget_exhausted` is true
exactly when the result has problem code and guidance code
`BUDGET_EXHAUSTED`. `normalization_count` is the number of safe input-field
normalizations reported by that call and is zero unless
`IDENTIFIER_NORMALIZED` is present. Mutation, check, startup, provider, and
unknown operations cannot enter an assembly transcript.

The [SEM-8] eval report moves to schema version 3. It retains the exact v2 top-
level `corpus`, `analysis`, `trials`, `metrics`, `qualification`, and
`operational` records and adds exactly one top-level `verification` record:

```text
verification = {
  identity,
  events,
  metrics,
  qualification,
  interaction,
  maintenance,
  operational
}
```

`identity` contains exactly `analysis_identity_sha256`, `inference_contract`,
ordered `search_epochs`, `required_verdicts`, `minimum_support_score`,
`indeterminate`, `corpus_manifest_sha256`, ordered `assembler_identities`,
ordered `assembler_base_identities`, and `eval_controls`.
`analysis_identity_sha256` hashes canonical JSON for the report's complete
top-level `analysis` record retained from schema v2. That record binds the
analyze model/revision, offline provider descriptor, request controls, prompt
descriptors and bytes, contract version, and base search epoch. The verify
inference contract is the exact [EVC-3.1] object. `eval_controls` contains
exactly every `[verify.eval]` key from `trials` through
`require_all_critical`, in the table order in this section, including
`interval_method`, `confidence_level`, every sample floor, and every
threshold; it excludes mode and the four qualification path/hash fields.
The two assembler arrays are the unique transcript identity hashes sorted by
Unicode code point and are recomputed from the bound corpus.
An event contains exactly `trial_index`,
`corpus_case_id`, `variant` (`clean` or `mutated`), `assembly_surface`,
`assembler_identity_sha256`, `assembler_base_identity_sha256`, `packet_id`, `code`,
`classification`, `claim_hash`, `case_hash`, `case_evidence_hash`,
`verifier_case_hash`,
`primary_event_results`, `replay_event_results`, `aggregate_state`, `context`, `primary_event_sha256`, and
`replay_event_sha256`, and `comparison_signature_sha256`. Event results
contain exactly `verify_key`, `search_epoch`, `verdict`, `support_score`, and
canonical `evidence` in configured epoch order. Event assembly surface and
assembler hashes equal the owning manifest transcript. Events sort by trial index, manifest case order,
clean before mutated, packet order, then claim hash. Primary/replay hashes
cover canonical JSON for their respective ordered result arrays; aggregation,
metrics, and comparison signatures use the primary array. Inequality is immediate
replay failure, not an uncached flip observation. The replay phase requires
zero analyze calls and zero verify calls; either nonzero count is report
failure and exit `2`.

Verification `metrics` contains exactly nullable
`implementation_candidate_capture_rate`, `test_candidate_capture_rate`,
`counterevidence_candidate_capture_rate`, `candidate_capture_rate`,
`evidence_sufficiency_rate`, `conditional_precision`, `conditional_recall`,
`end_to_end_recall`, `recall_lower_bound`, `false_positive_rate`,
`false_positive_upper_bound`, `indeterminate_rate`, and
`uncached_flip_rate`, ordered `by_surface` and `by_code`, plus boolean
`all_critical_passed`. A by-code row contains exactly `code`,
`classification`, `positive_unit_count`, `negative_unit_count`, nullable
`candidate_capture_rate`, nullable `evidence_sufficiency_rate`, nullable
`conditional_precision`, nullable `conditional_recall`, nullable
`end_to_end_recall`, nullable `recall_lower_bound`, nullable
`false_positive_rate`, nullable `false_positive_upper_bound`, nullable
`indeterminate_rate`, nullable `uncached_flip_rate`, integer
`false_positive_count`, boolean `all_critical_passed`, and boolean `qualified`.
Rows use canonical BSA code order and exist only for codes with positive gold
units. Undefined
denominators produce null, never fabricated zero.

A by-surface row contains exactly `assembly_surface`, `positive_unit_count`,
`negative_unit_count`, the same ten nullable aggregate rate/bound fields
from `candidate_capture_rate` through `uncached_flip_rate`, and boolean
`all_critical_passed`. It deliberately omits the three role-specific capture
rates; the aggregate candidate-capture formula still applies to that cohort.
Rows exist exactly once in `reference_only`, then `repository_skill` order,
including zero-count rows. Each metric applies the exact aggregate formula to
only manifest case/variant units of that surface; trials still do not multiply
units. The aggregate row remains a recomputed union, not an average of surface
rates.

Metric units and formulas are exact. A candidate gold atom is one manifest
gold-evidence row whose role is `implementation`, `test`, or
`counterevidence`; requirement atoms measure target detection separately and
never inflate candidate capture. An implementation atom is captured when one
universe candidate of kind `implementation` has the same path and its receipt
fully covers the inclusive gold line range. A test atom applies the same rule
with kind `test`. A counterevidence atom is captured by any universe candidate
kind with the same path and covering receipt because counterevidence is an
evidence disposition, not a candidate kind. Capture tests raw deterministic
discovery only; whether the agent selected or considered the candidate enters
sufficiency, not capture. Per-role capture is captured atoms of that role
divided by all atoms of that role; aggregate capture uses all candidate gold
atoms. A positive unit is sufficient when its variant case is verifiable, its
bound transcript contains zero events with
`adjudicator_requested_addition = true`, and the packet's model-visible
`evidence_sources` contains the gold role/path and a merged interval covering
every gold atom. A repaired final case therefore remains an observed assembly
failure for this corpus unit when an adjudicator had to request evidence.
Implementation/test atoms therefore
require selected support in that role; a counterevidence atom requires the
candidate to be considered or omitted and rendered in the counterevidence
role. Sufficiency rate divides sufficient positive units by all positive units.
Candidate capture and sufficiency count
each manifest corpus case/variant once; stochastic trials never multiply their
denominators.

A trial has an expected verified prediction when it matches the positive
unit's expected packet ID, expected BSA code, every gold role/line predicate,
and aggregate context `verified`. A **true verified unit** is a sufficient
positive unit for which every configured trial has that expected prediction
and no trial has an extra verified hard-fail prediction. A **false verified
unit** is any positive or negative unit for which a trial has a verified
hard-fail prediction that is not its expected prediction; an extra wrong-code
prediction makes the unit false, even alongside the expected one. A **false
negative unit** is a sufficient positive unit that is not a true verified unit
and is not counted as a false verified unit. These categories are disjoint.
Conditional precision is true verified units divided by true plus false
verified units; conditional recall is true verified units divided by all
sufficient positive units. End-to-end recall divides positive units with all
atoms captured, sufficient evidence, the expected analyze code, and true
verified-unit status by all positive units. False-positive rate is negative
units with false-verified-unit status divided by all negative units.

Indeterminate rate is verify-eligible units with at least one trial in
aggregate `verification_indeterminate` context divided by all verify-eligible
units. The recall lower bound is the Wilson lower score bound over distinct
positive-unit end-to-end success booleans; the false-positive upper bound is
the Wilson upper score bound over distinct negative-unit false-positive
booleans, both using configured confidence. Repeated trials collapse through
the conservative unit predicates above and never increase sample count. These
score bounds are promotion margins over the labelled corpus, not a claim that
corpus units or model events are independent population samples. A zero
denominator is null for every rate. Support score is deliberately not treated
as a probability, so no calibration-error metric or qualifying threshold
exists.

A by-code row for canonical code `C` restricts positive denominators,
candidate capture, sufficiency, recall, indeterminate observations, and
critical-case checks to positive units whose expected code is `C`. Its
negative-unit count and false-positive denominator use every negative unit. A
true verified `C` unit has the expected verified `C` prediction in every trial
and no unexpected verified `C` prediction on another packet in any trial. A
false verified `C` unit is any negative or positive unit with an unexpected
verified `C` prediction, including an expected-`C` unit that also emits `C` on
the wrong packet. Thus a wrong `C` prediction on another code's positive unit
or an extra `C` prediction on an expected-`C` unit counts against `C`
precision. An extra wrong code on a true `C` unit counts against that other
code and the aggregate. A false-negative `C` unit is a sufficient expected-`C`
unit that is neither true verified `C` nor false verified `C`; these categories
remain disjoint.
By-code flip rate uses the same packet-keyed pair slots and attributes a slot
to `C` when the event on either side has finding code `C`. A `C` to `D` change
therefore enters and, when unequal, counts against both code rows; a missing to
`C` change counts against `C`. By-code false-positive count is negative units with any verified `C`
prediction. Every rate then uses the same formula as its aggregate counterpart
over these restricted sets.

For trial `t` and configured base verify epoch `e`, the effective event epoch
is `"eval:" + SHA256(canonical JSON of {corpus_manifest_sha256,
trial_index:t, base_search_epoch:e})`. Trial primary runs therefore create
distinct uncached keyed repetitions; they are not claimed as statistically
independent samples. The replay reuses those exact keys. The uncached
comparison signature has this exact preimage:

```text
{
  signature_version: 1,
  corpus_case_id,
  variant,
  packet_id,
  code,
  classification,
  claim: {
    claim_hash,
    packet_hash,
    evidence: [{role, path, start_line, end_line, excerpt_sha256}]
  },
  event_results: [{verdict, support_score_text, evidence}],
  aggregate_state,
  context
}
```

Here `event_results` is the projection of the event's primary result array.
Claim evidence is the canonical trusted [SEM-5] order and
`excerpt_sha256` hashes its exact shown UTF-8 excerpt. Event evidence is the
same canonical trusted record used in the cached result, with no verify key or
epoch. `support_score_text` is Python `format(score, ".17g")` after rejecting
non-finite values and normalizing both signed zero values to `"0"`. Event rows
preserve configured epoch position even though the epoch itself is absent.
The object excludes trial index, epochs, keys, response IDs, case/audit hashes,
and operational fields. The stored `comparison_signature_sha256` hashes
canonical JSON for exactly this object, so report validation can recompute it.
Uncached flip rate uses exact packet-keyed pair slots. For every unordered pair
of distinct trial indexes and each `(corpus_case_id, variant, packet_id)`
present as a verification event in at least one side, one slot enters the
denominator. Two present events compare their
`comparison_signature_sha256`; unequal hashes are one flip. An event present
on only one side is also one flip. A packet absent from both sides creates no
slot. Thus multiple packets never form a cross-product, a missing/extra
finding is instability rather than hidden incomparability, and a
code/classification change is visible because both are inside the signature.
The rate is null with fewer than two trials or zero slots.

Verification `qualification` contains exactly `mode`,
`positive_unit_count`, `negative_unit_count`, ordered `checks`, `passed`, and
`failure_reasons`. One check is emitted in the TOML key order above for every
sample floor, metric threshold, replay requirement, and critical-case rule; it
contains exactly `name`, `comparator` (`>=`, `<=`, or `true`), `threshold`,
nullable `observed`, and `passed`. A null observation never passes enforce
mode. The two reference-only sample-floor keys observe the matching by-surface
unit counts; other unprefixed keys observe aggregate metrics. For every by-code
row, the aggregate positive/negative sample-floor and applicable
quality/critical checks repeat with `name` prefixed by `<canonical-code>:`;
the two `minimum_reference_only_*` keys never repeat by code. A code is
qualified only when its positive sample floor and every per-code quality check pass and its
false-positive count is zero. Failure reasons are unique strings in check
order. After the aggregate TOML/replay/critical checks and before by-code
checks, two assembly-surface checks appear in `reference_only`, then
`repository_skill` order. Each is named
`assembly_surface:<value>`, uses comparator `>=`, threshold `1`, and observes
the number of distinct `assembler_base_identity_sha256` values represented by
at least one manifest case/variant unit on both surfaces. Enforce qualification
therefore requires at least one same tool/model/request/harness/guide base
identity in both cohorts; stochastic trials never multiply the count. Surface
comparisons remain observational because fixture mix is not paired in v1; the
report must not call a difference a causal skill effect. Next, checks prefixed
`reference_only:` apply every configured candidate-capture, sufficiency,
precision, recall, false-positive, indeterminate, flip, and critical-case
threshold to the reference-only by-surface row. Enforce `passed` requires all
aggregate, surface-coverage, reference-only, and by-code checks to pass. The
repository-skill quality row is observational and cannot compensate for a
failed reference-only check. `operational`
contains exactly `cache_hits`, `cache_misses`, `provider_calls`, nullable
`estimated_cost_microusd`, and nullable `cost_rate_source`.

`interaction` contains exactly nonnegative integer `agent_calls`, `pages`,
`bytes_returned`, `budget_exhausted_events`, `normalization_events`, and
`adjudicator_requested_additions`, plus ordered `by_surface`, summed from the
bound assembly transcripts for the variant cases. A `by_surface` row contains
exactly `assembly_surface`, `variant_count`, and those same six count fields;
rows exist exactly once in `reference_only`, then `repository_skill` order.
`variant_count` is the number of distinct manifest case/variant units of that
surface. Each total equals the sum of the two rows; absent observations produce
a zero row rather than omitting the surface. `agent_calls` counts transcript
events. `pages` counts events whose operation is one of
`obligation.list`, `obligation.evidence`,
`obligation.counterevidence`, `obligation.find-evidence`,
`obligation.candidate-source`, or `obligation.candidate-neighbors`.
`bytes_returned` and `normalization_events` sum
their corresponding event integers; `budget_exhausted_events` and
`adjudicator_requested_additions` count true event booleans. `maintenance` contains exactly nonnegative integer
`changed_line_count`, `invalidated_case_count`,
`invalidated_obligation_count`, `refresh_count`, `refresh_agent_calls`,
`refresh_bytes`, and `unrelated_invalidation_count`, plus nullable
`invalidations_per_changed_line`. That rate is invalidated cases divided by
changed lines and is null at zero lines. These records are measurement and
review inputs, not provider identity or standalone failure authority.

Outside `backstitch eval`, configuration validation grants
`CODE:verified` error eligibility only after reading the configured committed
corpus and report, checking both exact file hashes, validating the corpus's
manifest-v2 schema, gold records, variant case/manifest objects through the
production loader, and matching the report's corpus identity. It then checks
the report schema; recomputes the retained top-level `analysis` record from the
current analyze provider/request/prompt/contract/search-epoch configuration;
matches that record and `analysis_identity_sha256`; and matches the current
verify inference contract, ordered base `search_epochs`, required verdicts,
support threshold, indeterminate mode, and exact `eval_controls`. This
comparison therefore includes trials, interval method, confidence level,
sample floors, and all thresholds. It recomputes every assembler full/base
identity and requires each required reference/guide descriptor, and any
supplied proposal-schema descriptor, to equal the currently installed
[EVC-8.3.1] artifact. A `repository_skill` identity must also equal the current
raw SHA-256 of `skills/evidence-assembly/SKILL.md`; a missing or changed skill
fails currentness. A teaching-artifact change does not stale a frozen case, but
it does invalidate old assembly-quality qualification until reevaluated.
It also validates replay hashes, requires
`mode = "enforce"`, and requires `passed = true` only after authoritative
recomputation. The validator reconstructs each production packet, claim,
verifier-case projection, identity, key, evidence binding, aggregate state,
context, primary/replay digest, and comparison signature from the bound
corpus, cases, manifests, transcripts, and closed report event rows. It then
recomputes every capture and sufficiency atom, conservative unit predicate,
aggregate, by-surface, and by-code metric, Wilson bound, interaction row, qualification
check, failure reason, per-code `qualified`, and top-level `passed` value and
requires exact equality with the report. Maintenance fields remain review-only
and cannot enter a qualification check. Any altered event, metric, bound,
check, by-code row, or pass flag invalidates the qualification artifact; a
matching configured file hash does not bless self-consistent but
non-recomputed claims. The exact policy-selected BSA code must also have a by-code
row with `qualified = true`; a passing aggregate cannot authorize an unmeasured
classification. The eval command computes the candidate report from the
current production path and never treats the output it is still producing as
a pre-existing qualification artifact. Eval remains exit `0`/`2`; it never
turns seeded fixture findings into target-repository exit `1`.

## 11. Anti-Gaming Requirements [EVC-11]

The assembling agent will often be the agent that authored the code under
claim. Required countermeasures, all of which must hold simultaneously:

- the mandatory universe cannot be shrunk, and omissions require recorded
  reasons visible in review ([EVC-7]);
- agent proposals contain only broker-minted candidate IDs,
  proof-obligation bindings, and reasons;
  agent-supplied locators, digests, derived relations, universe state, and
  review claims are rejected rather than trusted;
- direct repository access may help an agent reason or propose additional
  candidates, but only broker-resolvable candidate IDs and derived receipts can enter a
  frozen case as evidence;
- the verifier is blinded to assembler rationale and score ([EVC-3]); its
  closed projection contains universe selected/considered/omitted state but
  no assembler reason;
- insufficient verifier evidence resolves `indeterminate`; v1 has no verifier
  evidence-request loop or undeclared second discovery phase;
- dispositions on verified findings follow the exact-match, reasoned,
  auditable form of [SEM-6]; there is no family-wide semantic suppression;
- the [SEM-8] corpus includes assembly-bias mutations: cases whose frozen
  evidence is curated to omit the disconfirming span. An unaccounted omission
  fails the universe check; a reasoned omission remains valid but its complete
  current span is analyzer-visible as counterevidence. If analyze emits a
  claim, verify sees the same span. If analyze emits no claim, verify has
  nothing to assess; evaluation counts the miss against end-to-end recall.
  This design prevents the assembler from hiding the span but does not claim
  that one stochastic analyze run must recognize its meaning.

## 12. Verification Expectations [EVC-12]

Executable gates cover, at minimum:

- verify cache keys are disjoint from analyze keys; identical claim with
  changed `claim_hash`, epoch, semantic `case_evidence_hash`, verify
  prompt/model/controls misses; reason, guide, audit-only case-hash, and policy
  changes do not miss
- dependency and plugin distribution version changes miss verify cache; exact
  verifier projection/request/key/cache golden bytes reject every unknown or
  reordered field, prove assembler reasons never enter, and show each current
  source line at most once per role even when overlapping candidates are
  omitted
- `analyze` and `eval` are the only verify runners; disabled/enabled report-v2
  records, debt modes, verify problems, aggregate score, and 2-before-1 exit
  precedence fire while `summarize-analysis` makes no verify access
- the verifier request contains no analyzer rationale or score bytes
- `supported`/`unsupported`/`indeterminate` each fire and project to the
  documented contexts; mixed N-event sets follow [EVC-5]; tool failure never
  projects to `unsupported`
- an unsupported-plus-failed mixed set retains BSE005/BSE006 audit rows but
  has no aggregate event, debt, or disputed BSA projection and exits `2`
- unknown calibration keys are rejected; uncalibrated `support_score` is never
  named or rendered as probability
- obligation reference, list, compact default view, evidence/counterevidence,
  discovery, and candidate detail form a complete progressive-disclosure path;
  a fresh process can continue a page from its full address without `init`, a
  hidden handle, or server-side session state
- CLI and MCP expose the named operations in [EVC-8], not a generic query
  surface; every [EVC-8.3.1] payload, nullable field, ordering rule, problem
  variant, and mutation `changed` result has golden parity across adapters
- cursor golden vectors resume in a fresh process; altered digest, unknown
  field, stale snapshot, selector mismatch, cross-variant or cross-operation
  reuse, bad item index/line, and current item-ceiling violation each fail
  without silently restarting; a changed response ceiling resumes a source
  span without line loss or duplication
- canonical obligation shorthand normalizes with `IDENTIFIER_NORMALIZED`;
  ambiguity is rejected with candidates and `REQUEST_REJECTED`
- portable repository ID produces the same candidate, case, and manifest
  hashes across two clone roots; an absolute local root enters none of them
- golden snapshot, case/candidate/receipt, proposal/universe, case-object, and
  active-manifest preimages reproduce every digest and exact indented file byte
- snapshot capture builds resolver, parser, universe, and receipts from one
  immutable byte image; a mid-capture mutation retries or exits `2`, and a
  pre-publication mutation returns `SNAPSHOT_CONFLICT`
- seed and closure ordering is byte-stable; every supported Python relation
  form resolves, every unsupported or ambiguous form becomes an exact
  unresolved candidate, and depth zero includes only seeds
- module-resolution golden fixtures cover import-base and package roots,
  `__init__.py`, relative levels, overlapping-root agreement/conflict, duplicate
  modules, aliases, lexical shadowing, wildcard imports, and submodule-versus-
  definition ambiguity
- candidate-span golden fixtures cover decorated/nested definitions, modules,
  multiline references using their lexical owner, binding tests, report issues,
  empty and unterminated files, and tree-sitter end points at column zero
- contained candidate resolution mints a stable candidate ID without trusting
  agent locators; adding it expands closure to a fixed point that the proposal
  must account for
- stable candidate IDs survive raw and normalized non-structural content
  churn; a structural-locator edit intentionally changes identity; receipt
  hashes change on raw churn, so universe diff never mistakes non-structural
  content change for a new member
- an edit to an unrelated semantic file changes the audit repository snapshot
  but not unchanged candidate, receipt, semantic-case, packet, analyze-cache,
  or verify-cache identities for an unaffected obligation
- normalization golden vectors cover lone CR, CRLF, trailing spaces and tabs,
  empty spans, multiple terminal newlines, strict UTF-8 rejection, and content
  whose bytes resemble a delimiter; structural-locator vectors cover nested
  definitions, aliased calls, identical occurrences, and both invariant
  locator variants
- every guidance code in [EVC-8.5] has a firing test and every response has a
  nonblank action; terminal reads remain compact and use `READ_COMPLETE`
- JSON stdout/stderr framing, text projection, MCP success/error envelopes,
  and CLI/MCP core-result parity fire for exits 0, 1, and 2
- candidate-source paging never splits a UTF-8 line; one over-budget line fails with
  the exact raise-limit-or-select-narrower-candidate action
- proposal validation accepts candidate IDs, proof-obligation bindings, and
  reasons; derives trusted fields; preserves wrong-role selections with
  `EVIDENCE_ROLE_MISMATCH`; and rejects attempts to override trusted fields
- fixed bootstrap, raw request, proposal string/canonical, captured file/image,
  and case/manifest byte ceilings reject at exact observed counts before parse,
  reconstruction, or staging; every budget variant fires
- a deliberate open question is a nonblocking proposal discrepancy that
  activates as BSE003-visible, nonverifiable debt and makes zero verify calls;
  other discrepancy codes block activation
- zero eligible tests deterministically produces `complete_absent` only for an
  invariant binding-test obligation and permits its weak-binding absent-test
  verifier branch; a section test remains unresolved, and one eligible test
  makes invariant absence completion invalid
- every cell in the closed candidate-kind/proof-obligation role matrix has an
  acceptance or `EVIDENCE_ROLE_MISMATCH` test
- activation is deterministic: the same repository snapshot and canonical
  proposal produce byte-identical case objects and `case_hash`
- repeated matching activation and non-required absent deactivation return their
  exact no-write, `changed = false` idempotent responses; required absent
  deactivation remains visible through `CASE_REQUIRED_MISSING`
- activation publishes an immutable object then switches the active manifest last;
  snapshot or manifest conflict changes no active state, returns the complete
  recovery sequence, and cannot be forced; inactive objects are never treated
  as active cases
- death injection before object fsync, before hard-link publication, after the
  hard link, before manifest fsync, and after manifest replace proves that no
  partial final object or partial active manifest is observable; the next
  writer cleans only exact regular staging names
- a pre-existing identical object is validated and reused; a symlink,
  non-regular object, hash/path mismatch, or different bytes at the same object
  path exits `2` without replacement
- obligation listing, activation replacement, deactivation, missing required cases,
  malformed manifests, referenced-object loss, and stable staging cleanup all
  fire through the [EVC-8.6] lifecycle
- section and invariant skip markers parse only on the owner heading or in its
  directive region; parser-derived ATX closing-hash and setext insertion,
  italic/HTML aliases, HTML-safe JSON escaping for `-->`, `<`, `>`, quotes,
  backslashes, controls, and delimiter-like text, missing/blank/oversized
  reasons, duplicates, non-obligation owners, and fenced/prose mimicry each
  fire their exact [EVC-8.3.2] behavior
- skip and unskip preserve every non-marker source byte across LF, CRLF, and
  unterminated owner lines; matching skip and absent unskip are no-write
  idempotent operations, while a reason update changes only the marker bytes;
  canonical inline markers preserve target coordinates, while standalone
  aliases expose their expected coordinate-staling refresh action
- skip/unskip source edits use real sibling staging, no-follow checks, lock,
  file/directory fsync, and compare-and-swap; concurrent edit, permission
  failure, symlink/non-regular path, and death before/after replace expose no
  partial spec and retain only the exact ignored staging residue
- a skipped obligation remains in list totals, appears as BSE010 with its exact
  reason under `--show-suppressions`, creates no packet/analyze/verify work,
  retains any active immutable case, and resumes ordinary currentness checks
  after unskip; parser and artifact corruption remain fatal while skipped
- applied policy that makes BSE010 non-suppressible exercises the ordinary
  unsuppressible-suppression path; exact effective level and `fail_on` decide
  the exit, an exact BSE010 error rule prohibits skips, skip counts never enter
  the covered numerator, and a skipped qualification fixture is rejected
- broad roots such as `code_roots = ["."]` and `spec_roots = ["docs"]` still
  discover ordinary inputs while the exact configured case root, final
  objects, manifests, and transient files never enter the semantic snapshot
- MCP stdio performs no network, provider/model, repository-write, activate,
  skip/unskip, deactivate, or approval action; its missing dependency and handshake failures are
  structured exit-`2` equivalents without tracebacks
- the installed guide and MCP guide resource return the same bytes; the
  repository skill adds workflow only and duplicates no normative contract;
  a guide-only digest change preserves case validity while changing assembly
  evaluation provenance
- every relation type fires; trusted structural relations re-derive, while
  `semantic_support` and `counterevidence` remain visibly proposed; a static
  reference never projects as runtime reach or assertion coverage
- line-ending, trailing-whitespace, and terminal-newline edits do not
  invalidate the case, but do change a packet containing current raw bytes and
  therefore require an exact cache hit or trusted refresh; indentation,
  comment, docstring, token, and line-order edits make the obligation stale
- target requirement normalization churn fires `CASE_REQUIREMENT_STALE` and
  invalidates every derived proof obligation; raw-only target churn preserves
  case validity but changes packet identity
- a new caller/implementation/test in the recomputed universe fires
  `CASE_UNIVERSE_EXPANDED` on a previously green case
- obligation-scoped invalidation: an edit invalidates only citing
  obligations; refresh touches only those
- every `BSE*` diagnostic fires and respects packaged-versus-applied policy
  layering, including promotion of staleness to error by an applied policy
- an omission without a reason fails activation, not merely CI
- assembly-bias corpus cases prove that changing a disconfirming candidate from
  selected/considered to reasoned omission does not remove its current span
  from analyzer or verifier input; an analyze no-finding is recorded as an
  end-to-end false negative and fails qualification when thresholds require it
- one huge omitted span and many bounded omitted spans can exceed the exact
  analyze or verify request ceiling; proposal validation rejects the exact
  analyze overflow or conservative verify overflow, and analyze's defensive
  exact checks make zero provider/cache writes
- verify-eval manifest v2 and report v3 validate exact committed cases,
  identities, events, replay hashes, metrics, null denominators, checks, and
  report hash; distinct trial epochs are measured as keyed repetitions, not
  independent samples, and increasing trials never increases positive/negative
  unit counts; report mode cannot authorize error, while enforce mode requires
  a current passing artifact and exact `CODE:verified` policy
- clean and mutated source artifacts install into isolated config-derived case
  paths and pass the production loader; reference-only and repository-skill
  transcripts bind exact assembler full/base identities, both surfaces share
  at least one base identity, and interaction counts recompute per surface
- a transcript with an adjudicator-requested addition makes its otherwise
  complete positive unit insufficient; event/metric/check/by-code/pass tamper
  fixtures and multi-packet missing/changed-code flip fixtures all fail
  authoritative report validation
- source text containing prompt injection, fake tool instructions, or forged
  candidate IDs remains quoted untrusted data; symlink and containment attacks
  are rejected before any read or write
- section and invariant semantic packets include the selected implementation
  and test bodies under schema v3; case and trace modes both fire; stale cases
  cannot reach independent verification; changing semantic case evidence or
  current raw evidence bytes changes packet and cache identity, while an
  audit-reason-only case-hash change does not; v2 never satisfies v3
- schema-v3 golden tests cover every closed top-level and nested field, exact
  model-visible projection, maximal source-region merge/deduplication, unique
  SEM-5 citation binding, role source, ordering, case-mode fail-closed cap,
  trace-mode truncation warning, and legacy-v2 migration action
- pre-resolution and partially resolved failures exercise the exact nullable
  repository envelopes, plus JSON and text exit-2 framing; CR/LF and Unicode
  line separators in hostile path/parser text remain escaped inside one line
- exit precedence matches [SEM-7] with staleness expressed only through
  diagnostics

## Related Plans

- `docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md`
